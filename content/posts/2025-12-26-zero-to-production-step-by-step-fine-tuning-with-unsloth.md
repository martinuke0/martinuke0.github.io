---
title: "Zero to Production: Step-by-Step Fine-Tuning with Unsloth"
date: "2025-12-26T22:28:30.034"
draft: false
tags: ["unsloth", "fine-tuning", "llm", "machine-learning", "production"]
---

Unsloth has quickly become one of the most practical ways to fine‑tune large language models (LLMs) efficiently on modest GPUs. It wraps popular open‑source models (like Llama, Mistral, Gemma, Phi) and optimizes training with techniques such as QLoRA, gradient checkpointing, and fused kernels—often cutting memory use by 50–60% and speeding up training significantly.

This guide walks you **from zero to production**:

1. Understanding what Unsloth is and when to use it  
2. Setting up your environment  
3. Preparing your dataset for instruction tuning  
4. Loading and configuring a base model with Unsloth  
5. Fine‑tuning with LoRA/QLoRA step by step  
6. Evaluating the model  
7. Exporting and deploying to production (vLLM, Hugging Face, etc.)  
8. Practical tips and traps to avoid

All examples use Python and the Hugging Face ecosystem.

---

## Table of contents

- [Introduction](#introduction)  
- [1. What is Unsloth and Why Use It?](#1-what-is-unsloth-and-why-use-it)  
- [2. Prerequisites and Environment Setup](#2-prerequisites-and-environment-setup)  
  - [2.1 Hardware requirements](#21-hardware-requirements)  
  - [2.2 Python environment](#22-python-environment)  
  - [2.3 Installing Unsloth and dependencies](#23-installing-unsloth-and-dependencies)  
- [3. Choosing a Base Model and Use Case](#3-choosing-a-base-model-and-use-case)  
- [4. Preparing Your Dataset (Zero to Clean SFT Data)](#4-preparing-your-dataset-zero-to-clean-sft-data)  
  - [4.1 Recommended data format](#41-recommended-data-format)  
  - [4.2 Example: loading and cleaning with `datasets`](#42-example-loading-and-cleaning-with-datasets)  
  - [4.3 Formatting prompts for chat models](#43-formatting-prompts-for-chat-models)  
- [5. Loading a Model with Unsloth](#5-loading-a-model-with-unsloth)  
  - [5.1 Quickstart: QLoRA with Unsloth](#51-quickstart-qlora-with-unsloth)  
  - [5.2 Configuring LoRA adapters](#52-configuring-lora-adapters)  
- [6. Training: Step-by-Step Fine-Tuning](#6-training-step-by-step-fine-tuning)  
  - [6.1 Training arguments](#61-training-arguments)  
  - [6.2 Running the training loop](#62-running-the-training-loop)  
  - [6.3 Monitoring and debugging training](#63-monitoring-and-debugging-training)  
- [7. Evaluating Your Fine-Tuned Model](#7-evaluating-your-fine-tuned-model)  
- [8. Saving, Merging, and Publishing Models](#8-saving-merging-and-publishing-models)  
  - [8.1 Saving LoRA adapters](#81-saving-lora-adapters)  
  - [8.2 (Optional) Merging LoRA into a full model](#82-optional-merging-lora-into-a-full-model)  
  - [8.3 Pushing to the Hugging Face Hub](#83-pushing-to-the-hugging-face-hub)  
- [9. Deploying to Production](#9-deploying-to-production)  
  - [9.1 Serving with vLLM](#91-serving-with-vllm)  
  - [9.2 Hugging Face Inference Endpoints](#92-hugging-face-inference-endpoints)  
  - [9.3 Basic production checklist](#93-basic-production-checklist)  
- [10. Best Practices and Common Pitfalls](#10-best-practices-and-common-pitfalls)  
- [Conclusion](#conclusion)  

---

## 1. What is Unsloth and Why Use It?

**Unsloth** is an open‑source library focused on **fast, memory‑efficient fine‑tuning of LLMs**, especially using LoRA/QLoRA. It builds on top of the Hugging Face ecosystem and integrates tightly with `transformers` and `trl` (for supervised fine‑tuning).

Key advantages:

- **Lower VRAM**: QLoRA with 4‑bit quantization lets you fine‑tune 7–8B models on 1× 16–24 GB GPU, sometimes smaller.
- **Speed**: Custom kernels and optimizations often yield ~2× faster fine‑tuning versus a naïve `transformers` setup.
- **Simple API**: A couple of calls (`FastLanguageModel.from_pretrained` and `.get_peft_model`) give you a ready‑to‑train model.
- **Compatible**: Works with popular checkpoints from Hugging Face (Llama, Mistral, Gemma, Phi, Qwen, etc.—check the Unsloth docs for the current list).

Use Unsloth when:

- You want **instruction‑tuning** or **domain adaptation** of an existing open‑source LLM.  
- You have **limited GPU memory** but still want to train 7B+ models.  
- You prefer a Hugging Face‑centric workflow.

---

## 2. Prerequisites and Environment Setup

### 2.1 Hardware requirements

For a smooth experience:

- **GPU**:  
  - 7B models: 1× 16–24 GB GPU (e.g., RTX 4090, A10G, A5000, L4, A100 40GB, etc.)  
  - 13B+ models: 1× 24–40 GB GPU or multiple GPUs (or aggressive QLoRA settings)
- **CPU**: Any modern multi‑core CPU; more cores help with data pre‑processing.
- **RAM**: 16 GB+ recommended, depending on dataset size.
- **Disk**: At least 40–80 GB free if you download multiple models and save checkpoints.

### 2.2 Python environment

Use a fresh virtual environment or Conda:

```bash
python -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate           # Windows (PowerShell)
```

Use **Python 3.9–3.11** for best compatibility.

### 2.3 Installing Unsloth and dependencies

Install Unsloth plus core libraries:

```bash
pip install --upgrade pip

# Install Unsloth (choose the extra matching your setup per Unsloth docs)
pip install "unsloth[full]"  # or "unsloth[cuda]" / "unsloth[cpu]" depending on their README

# Hugging Face + TRL + evaluation
pip install "transformers>=4.40.0" "datasets>=2.18.0" "accelerate>=0.27.0" "trl>=0.8.0"
pip install bitsandbytes einops sentencepiece
```

> **Note**  
> The exact extras for Unsloth (e.g., CUDA versions) may change. Always check the [Unsloth GitHub repo](https://github.com/unslothai/unsloth) for the current recommended install command.

Verify GPU visibility:

```bash
python -c "import torch; print(torch.cuda.is_available(), torch.cuda.device_count())"
```

---

## 3. Choosing a Base Model and Use Case

Before touching code, clarify:

1. **Use case**  
   - Customer support/chatbot  
   - Code assistant  
   - Domain‑specific Q&A (finance, medical, legal, etc.)  
   - Tool‑using agent / RAG reasoning booster

2. **Language & size constraints**  
   - English only vs multilingual  
   - Max latency & memory budget in production  
   - Open‑weight licensing requirements (e.g., commercial use)

3. **Base model selection**  
   Common choices (check Unsloth docs for supported variants):
   - General chat: Llama‑3‑8B, Llama‑2‑7B, Mistral‑7B  
   - Code: CodeLlama, StarCoder‑like models (if/when supported)  
   - Low‑resource / compact: Phi‑3, Gemma‑2B/7B  

For this tutorial, assume:

- **Use case**: General instruction‑following chatbot  
- **Base model**: A 7–8B general model (e.g., a Llama‑style chat model on Hugging Face)

You can substitute your own `model_name` later.

---

## 4. Preparing Your Dataset (Zero to Clean SFT Data)

### 4.1 Recommended data format

For **supervised fine‑tuning (SFT)**, a practical schema is:

```json
{
  "instruction": "Explain the concept of overfitting in simple terms.",
  "input": "",
  "output": "Overfitting happens when a model memorizes the training data instead of learning general patterns..."
}
```

Fields:

- `instruction`: user request or task description
- `input`: optional extra context (docs, passages, question body)
- `output`: ideal assistant answer

Store this as **JSONL** (`.jsonl`, one record per line) or as a Hugging Face dataset.

Example layout:

```text
data/
  train.jsonl
  validation.jsonl
```

### 4.2 Example: loading and cleaning with `datasets`

```python
from datasets import load_dataset

# If you have local JSONL files
dataset = load_dataset(
    "json",
    data_files={
        "train": "data/train.jsonl",
        "validation": "data/validation.jsonl",
    },
)

print(dataset)
print(dataset["train"][0])
```

Optional cleaning steps (recommended):

- Drop very long or very short examples  
- Normalize whitespace  
- Remove duplicates by hashing `(instruction, input, output)`

```python
def clean_example(ex):
    ex["instruction"] = ex["instruction"].strip()
    ex["input"] = ex.get("input", "").strip()
    ex["output"] = ex["output"].strip()
    return ex

dataset = dataset.map(clean_example)

# Filter by output length
def is_reasonable_length(ex, min_len=10, max_len=2048):
    n = len(ex["output"].split())
    return (n >= min_len) and (n <= max_len)

dataset = dataset.filter(is_reasonable_length)
```

### 4.3 Formatting prompts for chat models

Modern chat models expect **special tokens and structured prompts**, e.g.:

```text
<|user|>
{instruction + optional input}
<|assistant|>
{output}
```

The exact template varies by model. Many Unsloth examples use something like:

```python
SYSTEM_PROMPT = "You are a helpful, concise AI assistant."

def make_prompt(instruction, input_text=None, output=None):
    user_content = instruction if not input_text else f"{instruction}\n\nInput:\n{input_text}"
    text = f"""<|system|>
{SYSTEM_PROMPT}
<|user|>
{user_content}
<|assistant|>
"""
    if output is not None:
        text += output
    return text
```

We’ll use this structure to generate a single `text` field the trainer can consume.

```python
def formatting_prompts_func(examples):
    texts = []
    for inst, inp, out in zip(
        examples["instruction"],
        examples.get("input", [""] * len(examples["instruction"])),
        examples["output"],
    ):
        texts.append(make_prompt(inst, inp, out))
    return {"text": texts}

dataset = dataset.map(formatting_prompts_func, batched=True)
```

After this, each sample has a `text` string that contains the full conversation.

---

## 5. Loading a Model with Unsloth

### 5.1 Quickstart: QLoRA with Unsloth

The central API in Unsloth is `FastLanguageModel`.

```python
from unsloth import FastLanguageModel
import torch

max_seq_length = 2048        # or 4096 depending on your GPU
dtype = None                 # let Unsloth pick (bfloat16/float16)
load_in_4bit = True          # QLoRA: 4-bit base model

model_name = "unsloth/llama-3-8b-bnb-4bit"  # EXAMPLE; use a supported model from Unsloth docs

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=model_name,
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=load_in_4bit,
)
```

> **Important**  
> The `model_name` should be a **quantized checkpoint compatible with Unsloth**, often provided directly by the Unsloth team or as recommended in their docs (e.g., `unsloth/<model-name>-bnb-4bit`). Using arbitrary models may fail or be sub‑optimal.

### 5.2 Configuring LoRA adapters

Next, wrap the base model with LoRA/QLoRA adapters. This is where Unsloth applies many optimizations (e.g., gradient checkpointing, rank‑stabilized LoRA).

```python
model = FastLanguageModel.get_peft_model(
    model,
    r=16,  # LoRA rank (8–64 are typical)
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_alpha=16,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",  # saves memory
    random_state=3407,
    use_rslora=True,  # often improves stability
    loftq_config=None,  # leave as default unless you know you need it
)
```

Parameters you’ll tune most often:

- `r`: controls adapter capacity; higher can fit more complex tasks but uses more memory.  
- `target_modules`: which attention/MLP modules get LoRA weights. The default list above is a good start for decoder LLMs.  
- `lora_dropout`: small non‑zero value (0.05–0.1) can help regularization.  
- `use_gradient_checkpointing`: enables memory savings at the cost of extra compute; recommended for tight VRAM budgets.

---

## 6. Training: Step-by-Step Fine-Tuning

We’ll use the **TRL `SFTTrainer`**, which integrates nicely with Unsloth models for supervised fine‑tuning.

### 6.1 Training arguments

```python
from trl import SFTTrainer
from transformers import TrainingArguments

BATCH_SIZE = 4
GRAD_ACCUM_STEPS = 4
EPOCHS = 3
LEARNING_RATE = 2e-4

training_args = TrainingArguments(
    output_dir="outputs/unsloth-llama3-chat",
    per_device_train_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM_STEPS,
    num_train_epochs=EPOCHS,
    learning_rate=LEARNING_RATE,
    max_grad_norm=1.0,
    warmup_ratio=0.03,
    lr_scheduler_type="cosine",

    logging_steps=10,
    save_strategy="epoch",
    evaluation_strategy="epoch",
    report_to="none",   # or "wandb" / "tensorboard"

    bf16=torch.cuda.is_bf16_supported(),
    fp16=not torch.cuda.is_bf16_supported(),

    optim="paged_adamw_32bit",  # bitsandbytes optimizer often used with QLoRA
)
```

### 6.2 Running the training loop

Create the trainer using our `text` field:

```python
train_dataset = dataset["train"]
eval_dataset  = dataset.get("validation")

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_dataset,
    eval_dataset=eval_dataset,
    dataset_text_field="text",
    max_seq_length=max_seq_length,
    packing=True,  # packs multiple samples per sequence for efficiency
    args=training_args,
)
```

Then train:

```python
trainer.train()
```

This will:

1. Stream your dataset, tokenize, and pack samples into up to `max_seq_length`.  
2. Fine‑tune only the LoRA parameters (the base 4‑bit model stays frozen).  
3. Log losses and evaluation metrics per epoch.

After training completes, you’ll see checkpoints in `outputs/unsloth-llama3-chat`.

### 6.3 Monitoring and debugging training

A few sanity checks during training:

- **Loss decreasing?**  
  - Training loss should fall steadily in the first epoch.  
  - Validation loss typically decreases but may plateau or rise if overfitting.

- **Memory issues (`CUDA out of memory`)**  
  - Reduce `per_device_train_batch_size`.  
  - Reduce `max_seq_length`.  
  - Use `use_gradient_checkpointing="unsloth"` (already set).  
  - Lower `r` (LoRA rank).

- **Speed**  
  - Try `packing=True` (already on) to reduce padding overhead.  
  - Use `bf16` if supported; it often gives good speed vs `fp16`.

Example: quick manual evaluation after each epoch:

```python
def chat(model, tokenizer, prompt, max_new_tokens=256):
    model.eval()
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            do_sample=True,
            top_p=0.9,
            temperature=0.7,
        )
    return tokenizer.decode(outputs[0], skip_special_tokens=True)

test_prompt = make_prompt("Explain QLoRA in one paragraph.", "", None)
print(chat(model, tokenizer, test_prompt))
```

---

## 7. Evaluating Your Fine-Tuned Model

For a production‑oriented project, you need **structured evaluation** beyond just checking a few prompts.

Approaches:

1. **Manual eval / rubric**  
   - Prepare a fixed set of ~50–200 prompts that represent real user queries.  
   - Have domain experts rate responses on criteria (correctness, helpfulness, safety).

2. **Automatic metrics**  
   - For classification‑like tasks: accuracy / F1.  
   - For QA: exact match / F1 against reference answers.  
   - For generation/style tasks, use model‑based annotators (e.g., LLM‑as‑a‑judge) with care.

3. **Benchmark frameworks**  
   - Use `lm-eval-harness` or similar to run standard tasks (if relevant).  

Example minimal evaluation loop for a custom dataset:

```python
import random

eval_samples = random.sample(list(eval_dataset), k=min(50, len(eval_dataset)))

for ex in eval_samples[:5]:
    prompt = make_prompt(ex["instruction"], ex.get("input", None), None)
    response = chat(model, tokenizer, prompt)
    print("INSTRUCTION:", ex["instruction"])
    print("EXPECTED:", ex["output"][:300], "...")
    print("MODEL:", response[:300], "...")
    print("=" * 80)
```

Document your evaluation procedure and results; this becomes crucial for **regression testing and governance** when you iterate models.

---

## 8. Saving, Merging, and Publishing Models

### 8.1 Saving LoRA adapters

The cheapest way to store and ship a fine‑tuned model is:

- Keep the **original base model** as is (from Hugging Face or Unsloth).  
- Save only your **LoRA adapter weights + tokenizer**.

```python
adapter_dir = "outputs/unsloth-llama3-chat-lora"

model.save_pretrained(adapter_dir)
tokenizer.save_pretrained(adapter_dir)
```

This directory now contains the LoRA adapter configuration and weights. To use it later:

```python
from unsloth import FastLanguageModel

base_model_name = model_name  # same as used earlier

base_model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=base_model_name,
    max_seq_length=max_seq_length,
    dtype=dtype,
    load_in_4bit=True,
)

base_model = FastLanguageModel.load_peft_model(
    base_model,
    adapter_dir,
)
```

> **Note**  
> The exact helper for loading PEFT/LoRA adapters may differ by Unsloth version. If `load_peft_model` isn’t available, you can fall back to standard PEFT APIs or check the current Unsloth docs.

### 8.2 (Optional) Merging LoRA into a full model

Sometimes you want a **fully merged model** (no external adapter), e.g., for deployment environments that don’t support LoRA, or for exporting to certain formats.

Unsloth typically offers a helper like `FastLanguageModel.for_inference` to:

- Merge LoRA into the base model  
- Convert to half/bfloat16  
- Enable efficient inference structures

A typical pattern (conceptual):

```python
from unsloth import FastLanguageModel

# Prepare for inference (may merge LoRA depending on settings/version)
FastLanguageModel.for_inference(model)

# Then save as a standard HF `transformers` model
merged_dir = "outputs/unsloth-llama3-chat-merged"
model.save_pretrained(merged_dir, safe_serialization=True)
tokenizer.save_pretrained(merged_dir)
```

> **Always check the current Unsloth docs** for the recommended way to merge and export; APIs may evolve.

### 8.3 Pushing to the Hugging Face Hub

Publishing to the Hub makes production deployment and collaboration easier.

1. Log in:

```bash
huggingface-cli login
```

2. Push from Python:

```python
from huggingface_hub import HfApi, create_repo

repo_id = "your-username/llama3-chat-unsloth-lora"
create_repo(repo_id, private=True, exist_ok=True)

from transformers import AutoTokenizer, AutoModelForCausalLM

# If you're saving LoRA‑only or merged, just push that directory:
api = HfApi()
api.upload_folder(
    folder_path=adapter_dir,    # or merged_dir
    repo_id=repo_id,
    commit_message="Initial Unsloth fine-tuned model",
)
```

Now your model can be loaded from anywhere with:

```python
from transformers import AutoModelForCausalLM, AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained(repo_id)
model = AutoModelForCausalLM.from_pretrained(repo_id)
```

(Or via Unsloth if exporting with Unsloth‑friendly format.)

---

## 9. Deploying to Production

Once the model is evaluated and saved, you need a **reliable, scalable inference stack**. Two common routes:

### 9.1 Serving with vLLM

[vLLM](https://github.com/vllm-project/vllm) is a fast inference engine that supports many HF models and exposes an OpenAI‑compatible API.

1. Install:

```bash
pip install "vllm>=0.4.0"
```

2. Start an API server:

```bash
python -m vllm.entrypoints.openai.api_server \
  --model your-username/llama3-chat-unsloth-lora-or-merged \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype bfloat16
```

3. Call it from your application:

```python
import requests
import json

API_URL = "http://localhost:8000/v1/chat/completions"
headers = {"Content-Type": "application/json"}

payload = {
    "model": "your-username/llama3-chat-unsloth-lora-or-merged",
    "messages": [
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Explain the benefits of QLoRA briefly."},
    ],
    "temperature": 0.7,
    "max_tokens": 256,
}

resp = requests.post(API_URL, headers=headers, data=json.dumps(payload))
print(resp.json()["choices"][0]["message"]["content"])
```

Deploy this container behind:

- An HTTP load balancer  
- Authentication      (API keys, OAuth, etc.)  
- Logging and observability stack (Prometheus, Grafana, ELK, etc.)

### 9.2 Hugging Face Inference Endpoints

For a fully managed deployment:

1. Push model to Hugging Face Hub (as above).  
2. In the HF UI, create an **Inference Endpoint** for your repo.  
3. Choose hardware (GPU type) and auto‑scaling.  
4. Hit the endpoint’s OpenAI‑style or HF‑style API from your app.

Pros:

- No infra to manage  
- Good for production with SLAs

Cons:

- Ongoing cost  
- Less control than self‑hosted vLLM

### 9.3 Basic production checklist

Before calling it “production”:

- [ ] **Load testing**: evaluate latency and throughput (e.g., Locust, k6).  
- [ ] **Autoscaling**: scale out under load (Kubernetes HPA, HF autoscaling, etc.).  
- [ ] **Monitoring**:  
  - Latency (p50, p90, p99)  
  - GPU/CPU usage  
  - Error rates (timeouts, OOMs)  
- [ ] **Safety**: content filters or guardrails if your use case demands it.  
- [ ] **Versioning**: tag your model + app versions; keep rollback paths.  
- [ ] **Canary releases**: route a small % of traffic to new versions first.

---

## 10. Best Practices and Common Pitfalls

### Data & training

- **Garbage in, garbage out**  
  - The single biggest determinant of quality is dataset quality.  
  - Remove toxic, outdated, or misleading examples for safety and correctness.

- **Domain balance**  
  - If you add a lot of domain‑specific data (e.g., finance), ensure mixed general data if you still want broad capabilities.

- **Sequence length**  
  - Don’t set `max_seq_length` to 8k just because it’s possible. Longer contexts are slower and need more VRAM.  
  - Match to realistic usage (2k–4k is enough for many assistant use cases).

### Hyperparameters

- Start with conservative settings:  
  - `learning_rate`: 2e‑4 or 1e‑4  
  - `r`: 8–16  
  - `epochs`: 1–3 (longer if dataset is small)  
- Monitor for overfitting: if validation loss keeps climbing, reduce epochs or add regularization (increase `lora_dropout` a bit).

### Unsloth specifics

- **Use official example configs**  
  - Unsloth’s README and notebooks include recommended parameters for each model family; start there and then adjust.

- **CUDA / bitsandbytes compatibility**  
  - If you see weird 4‑bit errors, ensure your CUDA, PyTorch, and bitsandbytes versions match the Unsloth recommendations.

- **Gradient checkpointing**  
  - Great for memory, but increases compute. If training is too slow and you have VRAM headroom, try disabling it.

### Deployment

- **Keep LoRA separate** if you want:
  - Small artifacts to ship  
  - Ability to swap base models underneath

- **Merge weights** if you:
  - Need compatibility with tools that don’t support PEFT/LoRA  
  - Want a single self‑contained model

- **Cache warming**:  
  - Run a few warm‑up requests before taking traffic to avoid cold‑start latency spikes.

---

## Conclusion

Fine‑tuning LLMs used to require multi‑GPU clusters and complex engineering. Unsloth, combined with LoRA/QLoRA and the Hugging Face ecosystem, makes it feasible to:

- Start with a strong open‑source base model  
- Prepare a relatively