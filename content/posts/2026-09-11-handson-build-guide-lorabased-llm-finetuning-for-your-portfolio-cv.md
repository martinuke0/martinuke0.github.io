---
title: "Hands‑On Build Guide: LoRA‑Based LLM Fine‑Tuning for Your Portfolio CV"
date: "2026-09-11T13:01:30.913"
draft: false
tags: ["LLM", "LoRA", "Fine-tuning", "Python", "Machine Learning"]
description: "Build a production‑ready LoRA fine‑tuning pipeline for LLMs using PyTorch and Hugging Face, with runnable code, CI‑ready scripts, and clear evaluation."
summary: "A hands‑on guide to building a LoRA‑based LLM fine‑tuning system you can ship to GitHub and discuss in interviews."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-handson-build-guide-lorabased-llm-finetuning-for-your-portfolio-cv.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — LoRA lets you fine‑tune huge LLMs with tiny parameter updates, making it possible to create a custom CV/portfolio model in hours rather than weeks. This guide walks you through building a complete pipeline—from data prep to a runnable training script—using PyTorch, Transformers, and the PEFT library. By the end you’ll have a reproducible project that signals systems‑level skill to hiring managers.

Building a custom LLM for your portfolio is a powerful way to demonstrate that you can take a research idea and turn it into a runnable, maintainable system. Hiring managers love seeing a concrete project that shows you understand data pipelines, model serving, and production‑grade tooling—all while staying within a reasonable time and compute budget.

## Why This Project Stands Out on a CV

- **Systems‑level thinking:** You design a full pipeline (data ingestion → tokenization → LoRA wrapper → training loop → checkpointing → inference). That signals you can operate end‑to‑end, not just notebook tweaks.
- **Named‑tool fluency:** Using *Hugging Face Transformers*, *PEFT* (Parameter‑Efficient Fine‑Tuning), and *PyTorch* shows you’re comfortable with the de‑facto stack most companies already run.
- **Reproducibility & CI‑readiness:** A script that can be `pip install`‑ed, trained on a laptop or a small GPU, and version‑controlled with Git demonstrates engineering discipline.
- **Evaluation rigor:** Including a validation split, loss tracking, and a generation test means you can prove quality—something many candidates skip.
- **Role signal:** This project is a strong fit for *ML Engineer*, *NLP Engineer*, and *AI Infrastructure* roles because it touches model customization, training infrastructure, and observable results.

## Architecture Overview

The system can be visualized as a linear pipeline with a few feedback loops:

```
┌─────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
│  Data CSV   │────►│ Tokenizer (HF)       │────►│ Dataset (Dict)       │
└─────┬───────┘      └─────────────────────┘      └───────┬───────────────┘
      │                    │                         │
      │                    ▼                         ▼
      │            ┌─────────────────────┐   ┌─────────────────────┐
      │            │  Base Model (GPT‑2/   │   │ LoRA Wrapper (PEFT) │
      │            │   LLaMA‑ish)           │   │   (rank=8, alpha=16) │
      │            └─────▲───────────────┘   └─────▲───────────────┘
      │                  │                     │
      │                  ▼                     ▼
      │            ┌─────────────────────┐ ┌─────────────────────┐
      │            │  Training Loop (PyTorch)││ Optimizer & Scheduler│
      │            └─────▲───────────────┘ └─────▲───────────────┘
      │                  │                 │
      │                  ▼                 ▼
      │            ┌─────────────────────┐ ┌─────────────────────┐
      │            │  Checkpoint & Metrics ││ Evaluation (Loss/PPL)│
      │            └─────▲───────────────┘ └─────▲───────────────┘
      │                  │                 │
      └──────────────────┘                 └─────────────────────┘
                                   ▲
                                   │  Inference / Generation
```

**Component breakdown**

| Component | Responsibility | Key Library |
|-----------|----------------|--------------|
| **Data CSV** | Raw prompts/completions, one per line | `pandas` / `csv` |
| **Tokenizer** | Convert text → token IDs, handle padding/truncation | `transformers.PreTrainedTokenizer` |
| **Dataset** | Wrap tokenized inputs into a `torch.utils.data.Dataset` | `datasets` |
| **Base Model** | Frozen backbone (e.g., `gpt2`) | `transformers.AutoModelForCausalLM` |
| **LoRA Wrapper** | Inject low‑rank matrices into attention layers | `peft.LoraConfig` + `peft.get_peft_model` |
| **Training Loop** | Forward, loss (cross‑entropy), backward, optimizer step | `torch`, `torch.optim` |
| **Checkpoint** | Save adapter weights + optimizer state every N steps | `torch.save` |
| **Evaluation** | Compute validation loss, possibly perplexity | `torch.no_grad`, `math.exp` |
| **Inference** | Generate text from fine‑tuned model using adapted weights | `model.generate` |

## Building It Step by Step

Below are **numbered, runnable steps** that you can copy‑paste into a fresh directory. All code uses Python 3.10+ and PyTorch 2.x.

### Step 1 – Scaffold the project and install dependencies

```bash
# Create a clean environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate

# Core libraries
pip install "transformers>=4.37" "peft>=0.9" "datasets>=2.14" "torch>=2.3"
# Optional: rich for nice progress bars
pip install rich
```

### Step 2 – Prepare a tiny dataset

Create `data/prompts.csv` with two columns: `prompt` and `completion`. Example rows:

```
prompt,complete
"Write a short tagline for a coffee shop.","Brewing brilliance, one cup at a time."
"Explain why the sky is blue.","Rayleigh scattering makes the sky appear blue."
```

Now load it in a quick Python snippet:

```python
# data/load.py
import pandas as pd
from datasets import Dataset

df = pd.read_csv("data/prompts.csv")
dataset = Dataset.from_pandas(df)
dataset.save_to_disk("data/tokenized")   # persists for later steps
```

### Step 3 – Load the base model and configure LoRA

```python
# models/setup.py
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model, TaskType

model_name = "gpt2"                     # small, CPU‑friendly; swap for "meta-llama/Llama-2-7b-chat-hf" if you have GPU
tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
tokenizer.pad_token = tokenizer.eos_token   # GPT‑2 lacks a pad token

model = AutoModelForCausalLM.from_pretrained(model_name, device_map="cpu")

lora_cfg = LoraConfig(
    r=8,                       # rank
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],   # GPT‑2 attention keys
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
)

model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()   # should show ~3.5 M params (≈1 % of GPT‑2)
```

### Step 4 – Tokenize the dataset and create a `Dataset` object

```python
# data/tokenize.py
from datasets import load_from_disk
from transformers import DataCollatorForLanguageModeling
import torch

raw = load_from_disk("data/tokenized")

def tokenize(batch):
    # GPT‑2 uses eos as pad; we truncate to 128 tokens for speed
    return tokenizer(batch["prompt"], truncation=True, max_length=128, padding="max_length")

tokenized = raw.map(tokenize, batched=True, remove_columns=raw.column_names)
data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

tokenized.set_format("torch", columns=["input_ids", "attention_mask"])
```

### Step 5 – Define the training loop

```python
# train.py
import torch
from torch.utils.data import DataLoader
from transformers import AdamW
from tqdm import tqdm
from data.tokenize import tokenized, data_collator

train_loader = DataLoader(tokenized, batch_size=4, collate_fn=data_collator)

model = ...  # loaded from Step 3
optimizer = AdamW(model.parameters(), lr=3e-4)

epochs = 3
global_steps = 0

for epoch in range(1, epochs + 1):
    model.train()
    pbar = tqdm(train_loader, desc=f"Epoch {epoch}")
    for batch in pbar:
        inputs = {k: v.to(model.device) for k, v in batch.items()}
        outputs = model(**inputs)                 # Cross‑entropy loss built‑in
        loss = outputs.loss
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
        global_steps += 1
        pbar.set_postfix(loss=loss.item())

    # --- simple validation / save checkpoint ---
    torch.save(
        {"model_state": model.state_dict(), "optimizer_state": optimizer.state_dict()},
        f"checkpoints/lora_epoch{epoch}.pt",
    )
```

### Step 6 – Generate a sample to verify fine‑tuning works

```python
# infer.py
import torch
from transformers import AutoTokenizer
from models.setup import model, tokenizer   # reuse the LoRA‑wrapped model

prompt = "Write a short tagline for a coffee shop."
inputs = tokenizer(prompt, return_tensors="pt").to(model.device)

# generate with the adapted model
generated = model.generate(
    **inputs,
    max_new_tokens=30,
    do_sample=True,
    temperature=0.8,
    top_p=0.95,
)
print(tokenizer.decode(generated[0], skip_special_tokens=True))
```

Run `python infer.py` – you should see a short, coherent tagline that reflects the (tiny) LoRA adaptation.

### Step 7 – (Optional) Push to the Hugging Face Hub

If you want a remote backup and a showcase URL:

```bash
pip install huggingface_hub
# Log in once: huggingface-cli login
REPO_ID="your-username/llm-lora-portfolio"
model.save_pretrained(f"hub/{REPO_ID}")
tokenizer.save_pretrained(f"hub/{REPO_ID}")
!huggingface-cli push $REPO_ID
```

Now you have a Git‑tracked, runnable project that can be demonstrated in an interview or linked on your CV.

## Running and Testing It

| Action | Command | Expected outcome |
|--------|---------|-------------------|
| **Install deps** | `bash setup.sh` (the `pip install` line from Step 1) | All libraries available |
| **Train** | `python train.py` | Training loops for 3 epochs, loss printed, checkpoints saved under `checkpoints/` |
| **Quick inference** | `python infer.py` | Prints a generated tagline; verify the output changed from the base model’s output |
| **Checkpoint sanity** | `python -c "import torch; c=torch.load('checkpoints/lora_epoch1.pt'); print('keys:', list(c['model_state'].keys()))"` | Shows adapter weights (`lora_A`, `lora_B`) – proof the LoRA updates are persisted |
| **Unit test the tokenizer** | `python -m pytest tests/test_tokenize.py -v` (you can add a minimal test that `len(ids) == 128`) | Guarantees the data pipeline stays correct as you iterate |

If any step fails, inspect the printed error, adjust the learning rate, batch size, or `max_length`, and re‑run. The project is deliberately lightweight so debugging happens in seconds on a laptop CPU or a modest GPU (e.g., Colab free tier).

## Extending It: Your Roadmap to Senior‑Level

1. **Persistent checkpointing with version control** – Store each run in a `mlflow` or `wandb` experiment, enabling reproducibility across teams and easy rollback.
2. **Distributed training with `torchrun` or DeepSpeed** – Scale to multiple GPUs or even CPU clusters; matters when you want to fine‑tune larger bases (Llama‑2‑13B) without hitting OOM.
3. **Human‑in‑the‑loop data curation UI** – Build a tiny Streamlit app to let reviewers up‑vote/down‑vote generated completions, feeding that feedback back into the training set for iterative improvement.
4. **Benchmark suite** – Run a standard benchmark (e.g., `lighteval` or `MMLU` subsets) before and after fine‑tuning to quantify performance gains; a concrete metric is far more persuasive than “it feels better.”
5. **Docker / CI pipeline** – Containerize the training script with a `Dockerfile` and add a GitHub Actions workflow that runs a smoke test on every PR, ensuring you never break the pipeline.
6. **Model‑serving endpoint** – Export the fine‑tuned adapter to `torchscript` or `ONNX` and serve it with `FastAPI` + `Uvicorn`; demonstrates you can take a model from notebook to production API.

Each upgrade adds a production‑grade dimension—observability, scalability, or automation—turning the toy into a portfolio piece that hiring managers can probe technically.

## Key Takeaways

- LoRA enables **parameter‑efficient fine‑tuning**, letting you adapt large models with < 5 % extra parameters.
- A **complete pipeline** (data → tokenizer → LoRA wrapper → training → evaluation → inference) signals end‑to‑end systems competence.
- Using **Hugging Face Transformers + PEFT** puts you in the mainstream ML stack that most companies already run.
- Adding **checkpointing, CI, and benchmarking** transforms a notebook experiment into a reproducible, employable project.
- The project is **scalable**: you can swap in larger base models, add distributed training, or containerize for production deployment.

## Further Reading

- **LoRA: Low‑Rank Adaptation of Large Language Models** – https://arxiv.org/abs/2106.09685  
- **PEFT (Parameter‑Efficient Fine‑Tuning) — Hugging Face** – https://github.com/huggingface/peft  
- **Transformers Documentation – Fine‑tuning** – https://huggingface.co/docs/transformers/main/en/training  
- **DeepSpeed Zero‑3 for large‑scale training** – https://docs.deepspeed.ai  
- **MLflow Tracking for experiment management** – https://mlflow.org/docs/latest/python_api/mlflow.tracking.html  
- **Evaluation & Benchmarking with lighteval** – https://github.com/lighteval/lighteval  

Feel free to clone the repo, tweak the dataset, and iterate—your next interview conversation starter is just a `git push` away. Happy fine‑tuning!