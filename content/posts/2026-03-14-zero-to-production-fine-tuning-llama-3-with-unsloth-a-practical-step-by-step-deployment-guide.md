---
title: "Zero to Production Fine-Tuning Llama 3 with Unsloth: A Practical Step-by-Step Deployment Guide"
date: "2026-03-14T06:00:33.845"
draft: false
tags: ["Llama3","Fine-Tuning","Unsloth","MLOps","Deployment"]
---

## Introduction

Large language models (LLMs) have moved from research curiosities to production‑ready services in a matter of months. **Llama 3**, Meta’s latest open‑source family, combines a strong architectural foundation with permissive licensing, making it a prime candidate for custom fine‑tuning. Yet, the fine‑tuning process can still feel daunting: data preparation, GPU memory management, hyper‑parameter selection, and finally, serving the model at scale.

Enter **Unsloth**, a lightweight library that dramatically simplifies the fine‑tuning workflow for Llama‑style models. Built on top of 🤗 Transformers and PyTorch, Unsloth offers:

- **Memory‑efficient LoRA (Low‑Rank Adaptation)** that fits 70B‑class models on a single 24 GB GPU.
- **One‑line trainer configuration** that abstracts boilerplate.
- **Built‑in integration with Hugging Face Hub** for seamless model versioning.

This guide walks you through the entire pipeline—from a clean development environment to a containerized production endpoint—using Llama 3 and Unsloth. By the end, you’ll have a fully‑functional API that can be queried with a single HTTP request.

> **Note:** The steps assume you have access to at least one GPU with CUDA support (e.g., an NVIDIA A100 or RTX 3090). For CPU‑only experimentation, replace the CUDA‑specific commands with their CPU equivalents, but expect slower training and inference.

---

## Table of Contents

1. [Prerequisites](#prerequisites)  
2. [Setting Up the Development Environment](#setting-up-the-development-environment)  
3. [Acquiring the Base Llama 3 Model](#acquiring-the-base-llama3-model)  
4. [Preparing Your Fine‑Tuning Dataset](#preparing-your-fine-tuning-dataset)  
5. [Fine‑Tuning with Unsloth](#fine-tuning-with-unsloth)  
   - 5.1 [LoRA Configuration](#lora-configuration)  
   - 5.2 [Training Script Walkthrough](#training-script-walkthrough)  
6. [Evaluating the Fine‑Tuned Model](#evaluating-the-fine-tuned-model)  
7. [Exporting to ONNX for Faster Inference](#exporting-to-onnx-for-faster-inference)  
8. [Building a FastAPI Service](#building-a-fastapi-service)  
9. [Containerizing with Docker](#containerizing-with-docker)  
10. [Deploying to a Cloud Provider (Optional)](#deploying-to-a-cloud-provider-optional)  
11. [Monitoring, Logging, and Scaling](#monitoring-logging-and-scaling)  
12. [Conclusion](#conclusion)  
13. [Resources](#resources)  

---

## Prerequisites

Before diving into code, verify the following:

| Requirement | Minimum Specification |
|------------|-----------------------|
| **Operating System** | Linux (Ubuntu 22.04 LTS recommended) or macOS (M1/M2 for testing) |
| **GPU** | NVIDIA GPU with at least 24 GB VRAM (A100, RTX 3090, RTX 4090) |
| **CUDA** | CUDA 12.1+ (compatible with your PyTorch version) |
| **Python** | 3.10 or newer (recommended 3.11) |
| **Git** | Latest stable version |
| **Docker** | Engine ≥ 24.0 for containerization |
| **Internet** | Stable connection for model & dataset downloads |

You’ll also need an account on the **Hugging Face Hub** to push the fine‑tuned checkpoint and retrieve the base Llama 3 weights.

---

## Setting Up the Development Environment

A reproducible environment eliminates “works on my machine” headaches. We’ll use **conda** for package isolation, but a plain virtualenv works just as well.

```bash
# 1️⃣ Create a new conda environment
conda create -n llama3-unsloth python=3.11 -y
conda activate llama3-unsloth

# 2️⃣ Install PyTorch with CUDA support
# Adjust the CUDA version if needed; this example uses 12.1
conda install pytorch torchvision torchaudio pytorch-cuda=12.1 -c pytorch -c nvidia -y

# 3️⃣ Install Unsloth and related libraries
pip install unsloth[torch] transformers datasets accelerate huggingface_hub tqdm

# 4️⃣ Verify GPU visibility
python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
```

> **Tip:** If you encounter dependency conflicts, create a fresh environment and install **torch** first, as it pins a specific CUDA toolkit version.

---

## Acquiring the Base Llama 3 Model

Meta publishes Llama 3 in two primary sizes:

| Variant | Parameters | Recommended GPU VRAM |
|---------|------------|----------------------|
| **Llama 3‑8B** | 8 billion | 16 GB |
| **Llama 3‑70B** | 70 billion | 48 GB (or LoRA‑enabled single‑GPU) |

For this guide we’ll fine‑tune the **8B** variant, which fits comfortably on a 24 GB GPU with Unsloth’s memory optimizations.

```bash
# Log in to Hugging Face (you’ll be prompted for a token)
huggingface-cli login

# Pull the model repo (public)
git lfs install
git clone https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct
```

> **Note:** The “Instruct” checkpoint already contains instruction‑following behavior, making it a solid starting point for downstream tasks.

---

## Preparing Your Fine‑Tuning Dataset

Fine‑tuning quality hinges on data relevance. In this example we’ll create a **customer‑support** dataset, but the same pipeline works for any domain (code generation, medical QA, etc.).

### 1️⃣ Dataset Format

Unsloth works natively with the 🤗 Datasets library. The expected format is a list of dictionaries, each containing:

- `instruction`: The user query or task description.
- `input` *(optional)*: Additional context (e.g., previous conversation turns).
- `output`: The desired model response.

```json
[
  {
    "instruction": "Explain how to reset a forgotten password for our web portal.",
    "output": "To reset your password, click 'Forgot password' on the login page..."
  },
  ...
]
```

### 2️⃣ Creating a CSV/JSONL File

You can collect data manually, scrape tickets, or use existing public datasets. For illustration, we’ll generate a small CSV and then load it with 🤗 Datasets.

```csv
instruction,output
"How can I upgrade my subscription?","To upgrade, go to Settings → Billing and select the desired plan."
"What is the refund policy?","We offer a 30‑day money‑back guarantee on all plans..."
```

### 3️⃣ Loading the Dataset

```python
from datasets import load_dataset

# Load a local CSV file
data_files = {"train": "support_data.csv"}
dataset = load_dataset("csv", data_files=data_files, column_names=["instruction", "output"])

# Verify a sample
print(dataset["train"][0])
```

### 4️⃣ Tokenizer Pre‑Processing

Unsloth provides a **fast tokenizer** that aligns with Llama 3’s Byte‑Pair Encoding (BPE). We’ll wrap the dataset to produce model‑ready inputs.

```python
from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(
    "meta-llama/Meta-Llama-3-8B-Instruct",
    use_fast=True,
    trust_remote_code=True
)

def format_prompt(example):
    # Llama 3 Instruct follows the <s>[INST] ... [/INST] format
    prompt = f"<s>[INST] {example['instruction']} [/INST] {example['output']}"
    return {"text": prompt}

tokenized_dataset = dataset["train"].map(format_prompt, remove_columns=["instruction", "output"])
```

---

## Fine‑Tuning with Unsloth

Unsloth abstracts away the low‑level LoRA handling while still exposing the knobs you need for a production‑grade run.

### 5.1 LoRA Configuration

LoRA introduces two small trainable matrices **A** and **B** that approximate weight updates. The key hyper‑parameters:

| Parameter | Description | Typical Value |
|-----------|-------------|---------------|
| `r` | Rank of the low‑rank decomposition | 64 |
| `alpha` | Scaling factor (α = r * scaling) | 16 |
| `target_modules` | Which transformer layers receive LoRA | `"q_proj","v_proj"` |
| `dropout` | Regularization dropout | 0.05 |

Unsloth’s `LoraConfig` wrapper sets sensible defaults for Llama models.

```python
from unsloth import LoraConfig, Trainer, TrainingArguments

lora_cfg = LoraConfig(
    r=64,
    alpha=16,
    target_modules=["q_proj", "v_proj"],
    dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)
```

### 5.2 Training Script Walkthrough

Below is a **complete** training script (`train_llama3_unsloth.py`). It covers:

- Model loading with LoRA injection.
- Dataset tokenization.
- Trainer setup with mixed‑precision (FP16) and gradient checkpointing.
- Automatic push to the Hugging Face Hub.

```python
# --------------------------------------------------------------
# train_llama3_unsloth.py
# --------------------------------------------------------------
import os
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from datasets import load_dataset
from unsloth import LoraConfig, Trainer, TrainingArguments

# ------------------- 1️⃣ Configurable Parameters -------------------
MODEL_ID = "meta-llama/Meta-Llama-3-8B-Instruct"
DATA_PATH = "support_data.csv"          # Path to your CSV dataset
OUTPUT_DIR = "./llama3-finetuned"       # Local checkpoint folder
HF_REPO = "username/llama3-customer-support"  # Replace with your HF repo name
EPOCHS = 3
BATCH_SIZE = 4                         # Adjust based on GPU memory
LEARNING_RATE = 2e-4
MAX_SEQ_LEN = 1024

# ------------------- 2️⃣ Setup -------------------
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Load tokenizer (fast)
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_ID,
    use_fast=True,
    trust_remote_code=True
)

# Load and format dataset
raw_dataset = load_dataset("csv", data_files={"train": DATA_PATH},
                           column_names=["instruction", "output"])

def build_prompt(example):
    # Llama 3 Instruct format
    prompt = f"<s>[INST] {example['instruction']} [/INST] {example['output']}"
    return {"text": prompt}

train_dataset = raw_dataset["train"].map(build_prompt, remove_columns=["instruction", "output"])

# Tokenize (truncate/pad to MAX_SEQ_LEN)
def tokenize(example):
    tokenized = tokenizer(
        example["text"],
        truncation=True,
        max_length=MAX_SEQ_LEN,
        padding="max_length",
        return_tensors="pt"
    )
    # Unsloth expects "input_ids" and "labels" (labels = input_ids)
    tokenized["labels"] = tokenized["input_ids"].clone()
    return tokenized

train_dataset = train_dataset.map(tokenize, batched=True, remove_columns=["text"])

# ------------------- 3️⃣ Model + LoRA -------------------
base_model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True
)

lora_cfg = LoraConfig(
    r=64,
    alpha=16,
    target_modules=["q_proj", "v_proj"],
    dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

# Inject LoRA layers
model = lora_cfg.apply_to(base_model)

# ------------------- 4️⃣ Trainer -------------------
training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    per_device_train_batch_size=BATCH_SIZE,
    num_train_epochs=EPOCHS,
    learning_rate=LEARNING_RATE,
    fp16=True,
    logging_steps=10,
    save_steps=200,
    evaluation_strategy="no",
    report_to="none",          # Disable wandb/MLflow unless you use them
    push_to_hub=False,         # We'll push manually after training
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
)

# ------------------- 5️⃣ Train -------------------
trainer.train()

# ------------------- 6️⃣ Save & Push -------------------
trainer.save_model(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)

# Push to Hugging Face Hub (requires huggingface_hub login)
trainer.push_to_hub(repo_id=HF_REPO, commit_message="Add fine‑tuned Llama 3 support model")
# --------------------------------------------------------------
```

#### Running the Script

```bash
python train_llama3_unsloth.py
```

You should see logs indicating LoRA parameter count (usually < 5 M for 8B model) and GPU memory usage staying under 20 GB.

---

## Evaluating the Fine‑Tuned Model

After training, you’ll want to verify that the model has learned the target behavior.

```python
from transformers import pipeline

# Load the fine‑tuned checkpoint from the Hub
model_name = "username/llama3-customer-support"
pipe = pipeline(
    "text-generation",
    model=model_name,
    tokenizer=MODEL_ID,
    torch_dtype=torch.float16,
    device=0
)

prompt = "<s>[INST] How do I change my billing address? [/INST]"
generated = pipe(prompt, max_new_tokens=150, do_sample=True, temperature=0.7)[0]["generated_text"]
print(generated)
```

**Qualitative checklist:**

1. **Relevance:** Does the answer address the instruction directly?
2. **Safety:** Is the response free of disallowed content?
3. **Verbosity:** Is the answer concise enough for a support bot?
4. **Hallucination:** Verify factual claims against your knowledge base.

For systematic evaluation, you can compute **BLEU**, **ROUGE**, or **GPT‑Eval** scores on a held‑out validation set.

---

## Exporting to ONNX for Faster Inference

While the PyTorch model works well for prototyping, production services often benefit from **ONNX Runtime** acceleration, especially when combined with **TensorRT** on NVIDIA GPUs.

```bash
pip install onnx onnxruntime-gpu
```

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import onnx

model = AutoModelForCausalLM.from_pretrained(
    "username/llama3-customer-support",
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True
)
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)

# Dummy input for tracing
dummy_input = tokenizer(
    "<s>[INST] Hello, how can I help you? [/INST]",
    return_tensors="pt"
).to("cuda")

# Export
torch.onnx.export(
    model,
    (dummy_input["input_ids"], dummy_input["attention_mask"]),
    "llama3_support.onnx",
    input_names=["input_ids", "attention_mask"],
    output_names=["logits"],
    dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                  "attention_mask": {0: "batch", 1: "seq"},
                  "logits": {0: "batch", 1: "seq"}},
    opset_version=16,
    do_constant_folding=True,
    use_external_data_format=True  # Handles >2GB files
)
print("ONNX export completed.")
```

**Performance tip:** Enable **CUDA graphs** in ONNX Runtime for sub‑millisecond latency on short prompts.

```python
import onnxruntime as ort

sess_options = ort.SessionOptions()
sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
sess_options.enable_mem_pattern = True
sess_options.enable_cpu_mem_arena = False
sess_options.intra_op_num_threads = 1

session = ort.InferenceSession("llama3_support.onnx", sess_options, providers=["CUDAExecutionProvider"])
```

---

## Building a FastAPI Service

Now we’ll wrap the model in a stateless HTTP API. FastAPI provides automatic OpenAPI docs and async support.

### 1️⃣ Install Dependencies

```bash
pip install fastapi uvicorn python-multipart
```

### 2️⃣ Service Code (`app.py`)

```python
# --------------------------------------------------------------
# app.py
# --------------------------------------------------------------
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
from transformers import AutoTokenizer
import onnxruntime as ort

# ------------------- Configuration -------------------
MODEL_ID = "meta-llama/Meta-Llama-3-8B-Instruct"
CHECKPOINT = "username/llama3-customer-support"
ONNX_PATH = "./llama3_support.onnx"
MAX_NEW_TOKENS = 150
TEMPERATURE = 0.7

# ------------------- Load Tokenizer -------------------
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, use_fast=True)

# ------------------- Load ONNX Session -------------------
session_opts = ort.SessionOptions()
session_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
session = ort.InferenceSession(ONNX_PATH, sess_options=session_opts,
                               providers=["CUDAExecutionProvider"])

# ------------------- FastAPI App -------------------
app = FastAPI(title="Llama 3 Support Bot API", version="1.0.0")

class PromptRequest(BaseModel):
    instruction: str
    input: str = ""   # Optional context

@app.post("/generate")
async def generate(request: PromptRequest):
    # Build the Llama‑3 prompt format
    raw_prompt = f"<s>[INST] {request.instruction}"
    if request.input:
        raw_prompt += f"\n{request.input}"
    raw_prompt += " [/INST]"

    # Tokenize
    inputs = tokenizer(
        raw_prompt,
        return_tensors="np",
        padding="max_length",
        truncation=True,
        max_length=1024
    )
    input_ids = inputs["input_ids"]
    attention_mask = inputs["attention_mask"]

    # ONNX inference
    ort_inputs = {
        "input_ids": input_ids.astype('int64'),
        "attention_mask": attention_mask.astype('int64')
    }
    logits = session.run(None, ort_inputs)[0]  # Shape: (1, seq_len, vocab)

    # Simple greedy decoding loop (replace with beam search if needed)
    generated_ids = input_ids.tolist()[0]
    for _ in range(MAX_NEW_TOKENS):
        next_token_logits = logits[0, -1, :]
        next_token = int(torch.argmax(torch.from_numpy(next_token_logits)))
        generated_ids.append(next_token)

        if next_token == tokenizer.eos_token_id:
            break

        # Prepare next step input
        input_ids = torch.tensor([generated_ids], dtype=torch.int64).numpy()
        attention_mask = torch.ones_like(input_ids).numpy()
        ort_inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
        logits = session.run(None, ort_inputs)[0]

    # Decode
    response = tokenizer.decode(generated_ids, skip_special_tokens=True)
    # Remove the original prompt from the response
    answer = response.split("[/INST]")[-1].strip()
    return {"answer": answer}
# --------------------------------------------------------------
```

### 3️⃣ Run the Service Locally

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 2
```

Visit `http://localhost:8000/docs` to explore the interactive Swagger UI.

---

## Containerizing with Docker

Deploying to Kubernetes, AWS ECS, or any cloud VM becomes trivial once the service lives in a Docker image.

### 1️⃣ Dockerfile

```dockerfile
# --------------------------------------------------------------
# Dockerfile
# --------------------------------------------------------------
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip git curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Create a non‑root user
RUN useradd -m appuser
WORKDIR /home/appuser

# Python environment
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app.py .
COPY llama3_support.onnx .

# Switch to non‑root user
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
# --------------------------------------------------------------
```

### 2️⃣ `requirements.txt`

```
fastapi
uvicorn[standard]
python-multipart
transformers
torch==2.2.0+cu121
onnxruntime-gpu
sentencepiece
```

> **Tip:** Pin the exact Torch version that matches the CUDA base image to avoid runtime mismatches.

### 3️⃣ Build & Test

```bash
docker build -t llama3-support-api .
docker run --gpus all -p 8000:8000 llama3-support-api
```

Open `http://localhost:8000/docs` again—now you’re interacting with the containerized service.

---

## Deploying to a Cloud Provider (Optional)

If you need a scalable endpoint, consider these managed options:

| Provider | Service | Key Benefits |
|----------|---------|--------------|
| **AWS** | Amazon SageMaker Endpoints (multi‑model) | Automatic scaling, built‑in logging, IAM security |
| **GCP** | Vertex AI Prediction | Serverless scaling, integrated monitoring |
| **Azure** | Azure Machine Learning Managed Online Endpoints | Easy deployment from Azure Container Registry |
| **DigitalOcean** | App Platform (Docker) | Simpler pricing, quick rollout for small workloads |

**General deployment steps:**

1. Push the Docker image to a container registry (Docker Hub, GHCR, ECR, etc.).
2. Create a new endpoint/service using the provider’s UI/CLI.
3. Configure autoscaling policies (e.g., min 1 replica, max 5 based on CPU/GPU utilization).
4. Attach a **log sink** (CloudWatch, Stackdriver, Azure Monitor) for observability.
5. Secure the endpoint with API keys or OAuth.

---

## Monitoring, Logging, and Scaling

A production service must be observable. Here’s a minimal stack:

- **Metrics:** Use **Prometheus** exporter in FastAPI (`fastapi_prometheus`) to expose request latency, error rates, and GPU utilization.
- **Logs:** Forward `stdout`/`stderr` to a central log aggregator (ELK, Loki, or cloud‑native services).
- **Alerting:** Set thresholds on CPU/GPU memory, request latency > 500 ms, or error rate > 1 %.
- **Horizontal Scaling:** Configure your orchestrator (K8s HPA) to scale pods based on the Prometheus metric `request_duration_seconds`.

```python
# Example: Adding Prometheus middleware
from fastapi import FastAPI
from fastapi_prometheus import PrometheusMiddleware, metrics

app = FastAPI()
app.add_middleware(PrometheusMiddleware, app_name="llama3_support")
app.add_route("/metrics", metrics)
```

---

## Conclusion

Fine‑tuning Llama 3 for a domain‑specific task no longer requires a team of engineers or a multi‑GPU cluster. By leveraging **Unsloth’s** LoRA‑centric workflow, you can:

1. **Rapidly prototype** on a single 24 GB GPU.
2. **Maintain reproducibility** via a concise training script and Hugging Face Hub versioning.
3. **Serve at production scale** using ONNX Runtime, FastAPI, and Docker containers.
4. **Scale safely** with cloud‑native monitoring and autoscaling patterns.

The end‑to‑end pipeline presented here—data preparation, LoRA fine‑tuning, ONNX export, API creation, containerization, and observability—covers the full lifecycle of an LLM product. Whether you’re building a customer‑support bot, a specialized code assistant, or any other conversational AI, the same building blocks apply.

Happy fine‑tuning, and may your models be both **powerful** and **responsibly deployed**!

---

## Resources

- **Llama 3 Model Card** – Official Meta release with technical details  
  [Meta Llama 3 Model Card](https://huggingface.co/meta-llama/Meta-Llama-3-8B-Instruct)
- **Unsloth GitHub Repository** – Documentation, API reference, and community examples  
  [Unsloth on GitHub](https://github.com/unslothai/unsloth)
- **FastAPI Documentation** – Guides for building high‑performance APIs  
  [FastAPI Official Docs](https://fastapi.tiangolo.com/)
- **ONNX Runtime GPU Guide** – Optimizing inference on NVIDIA hardware  
  [ONNX Runtime GPU Documentation](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html)
- **Hugging Face Accelerate** – Simplifies distributed training and mixed‑precision  
  [Accelerate Docs](https://huggingface.co/docs/accelerate/index)