---
title: "Hands‑On LoRA Fine‑Tuning Portfolio Project"
date: "2026-09-15T00:01:13.869"
draft: false
tags: ["loRA", "fine-tuning", "PyTorch", "Hugging Face", "PEFT"]
description: "Hands‑on guide to building a LoRA fine‑tuning portfolio project with PyTorch, Hugging Face, and PEFT, ready to showcase on your CV."
summary: "Learn how to construct a runnable LoRA fine‑tuning side project that demonstrates production‑grade ML engineering skills and can be highlighted on your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-15-handson-lora-finetuning-portfolio-project.svg"
  alt: "A developer working on a laptop with code snippets and a model diagram."
  caption: ""
  relative: false
---

> **TL;DR** — In this post we walk through building a complete LoRA fine‑tuning pipeline from data prep to a deployable model, using PyTorch, the PEFT library and Hugging Face Transformers. The result is a portable script you can run, extend, and point to on your CV as proof of systems‑level ML skill.

Building a portfolio side‑project that actually runs and demonstrates production‑grade ML engineering is one of the fastest ways to catch a hiring manager’s eye. This guide walks you through creating a **LoRA (Low‑Rank Adaptation) fine‑tuning** project from scratch: installing dependencies, loading a base model, applying parameter‑efficient adapters, training on a small dataset, and packaging everything so you can point to a working repo on your CV. Along the way you’ll see how LoRA fits into a modern ML stack, why it signals specific skills, and how to evolve the toy into a senior‑level pipeline.

## Why This Project Stands Out on a CV

Employers scanning dozens of CVs look for concrete evidence that you can operate in real ML systems, not just theory. A LoRA fine‑tuning project demonstrates several overlapping competencies:

- **Parameter‑efficient transfer learning** – you’ve worked with the PEFT library and understood how rank‑r adapters reduce memory footprints while preserving model capability.  
- **Large‑model handling** – you can load, instantiate, and run a multi‑billion‑parameter model (even a small one like Llama‑3.2‑1B) on a single GPU or CPU.  
- **End‑to‑end pipeline design** – data loading, tokenization, training loops, checkpointing, and publishing to the Hugging Face Hub all appear in a single reproducible script.  
- **Debugging & reproducibility** – loss tracking, seed setting, and environment pinning (requirements.txt or environment.yml) show you can ship reliable code.  
- **Systems awareness** – choices around optimizer, gradient accumulation, and mixed‑precision reveal that you think about throughput, VRAM, and training stability.

Roles that particularly value this signal include **ML Engineer, NLP Engineer, AI Research Engineer, and Data Scientist** positions where you’ll be asked to adapt large models quickly without retraining from scratch.

## Architecture Overview

The project’s architecture is deliberately minimal yet complete. The core components and their flow can be expressed as a text diagram:

```
Base LLM (e.g., Llama‑3.2‑1B)
       |
   +-----+-----+
   |   LoRA    |  (rank r, alpha α, target modules)
   +-----+-----+
       |
   +-----+-----+
   | Optimizer |  (AdamW, lr, weight decay)
   +-----+-----+
       |
   +-----+-----+
   | Trainer   |  (PyTorch loop, epochs, gradient clipping)
   +-----+-----+
       |
   +-----+-----+
   | Dataset   |  (tokenized texts, batched via DataLoader)
   +-----+-----+
       |
   +-----+-----+
   | Checkpoint/Hub  (save_pretrained / push_to_hub)
   +-----+-----+
```

Key points:

- **LoRA adapter** injects two low‑rank matrices per target module (`q_proj`, `v_proj` in transformer blocks). All other weights stay frozen, cutting trainable parameters from ~1 B to a few millions.  
- **AdamW** optimizer with a modest learning rate (≈ 1e‑4) works well for LoRA; weight decay is optional.  
- **PyTorch training loop** gives full control over gradient accumulation, mixed‑precision (`torch.cuda.amp`), and custom callbacks.  
- **Hugging Face `datasets`** provides an easy way to load, shuffle, and batch your data; tokenization is done with the model’s associated tokenizer.  
- **Checkpointing** via `model.save_pretrained()` stores both the base model weights (unchanged) and the LoRA adapters, ready for later resumption or hub upload.

## Building It Step by Step

Below are six numbered steps that produce a runnable LoRA fine‑tuning script. Each step includes a short Python code snippet tagged with the language identifier.

### Step 1 – Install dependencies
```bash
pip install "torch>=2.3" "transformers>=4.41" "peft>=0.10" "datasets>=2.18" "accelerate>=0.30"
```
*(If you have an NVIDIA GPU, make sure the matching CUDA toolkit is installed; PyTorch will auto‑select the appropriate build.)*

### Step 2 – Load a base model and its tokenizer
```python
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "meta-llama/Llama-3.2-1B"          # small enough for a single GPU
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    device_map="auto",                         # puts layers on GPU/CPU automatically
)
```
> **Tip:** `device_map="auto"` works with the `accelerate` package; if you prefer explicit `.to("cuda")`, replace it.

### Step 3 – Wrap the model with a LoRA adapter
```python
from peft import LoraConfig, get_peft_model

lora_cfg = LoraConfig(
    r=8,                 # rank – controls adapter size
    lora_alpha=16,       # scaling factor
    target_modules=["q_proj", "v_proj"],   # attention Q and V projections
    lora_dropout=0.05,
    bias="none",
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()   # shows ~0.5 M trainable params
```
The model now contains the frozen base plus trainable LoRA matrices.

### Step 4 – Prepare a tiny tokenized dataset
```python
from datasets import load_dataset

# Use a ready‑made tiny subset (IMDB reviews, first 1 % of train split)
raw_dataset = load_dataset("imdb", split="train[:1%]")

def tokenize_fn(examples):
    return tokenizer(
        examples["text"],
        truncation=True,
        max_length=512,
        padding="max_length",
    )

tokenized = raw_dataset.map(tokenize_fn, batched=True, remove_columns=["text"])
```
We now have a `Dataset` object ready for `DataLoader` consumption.

### Step 5 – Define and run a minimal training loop
```python
import torch
from torch.utils.data import DataLoader

model.train()
optimizer = torch.optim.AdamW(model.parameters(), lr=1e-4)
dataloader = DataLoader(tokenized, batch_size=4, shuffle=True)

for epoch in range(1):                     # single epoch for demo purposes
    for batch in dataloader:
        # Move inputs to the same device as the model
        inputs = {k: v.to(model.device) for k, v in batch.items()}
        # Forward + loss (CausalLM automatically creates a language modeling loss)
        outputs = model(**inputs, labels=inputs["input_ids"])
        loss = outputs.loss
        loss.backward()
        optimizer.step()
        optimizer.zero_grad()
print("Training finished – LoRA adapters updated")
```
> **Production note:** In a real pipeline you’d add gradient clipping (`torch.nn.utils.clip_grad_norm_`), mixed‑precision (`torch.cuda.autocast`), and a learning‑rate scheduler.

### Step 6 – Save the fine‑tuned model and push to the Hugging Face Hub
```python
model.save_pretrained("./lora_finetuned")       # stores adapter weights + config
tokenizer.save_pretrained("./lora_finetuned")   # same tokenizer for inference

# Optional: upload to the Hub (requires `huggingface_hub` installed & login)
# from huggingface_hub import login; login()
# model.push_to_hub("your-username/lora-llama-demo")
# tokenizer.push_to_hub("your-username/lora-llama-demo")
```
You now have a portable artifact: the base model (unchanged) plus the LoRA adapters, ready for inference or further fine‑tuning.

## Running and Testing It

1. **Execute the script**  
   ```bash
   python train_lora.py
   ```
   Expected output includes per‑batch loss (e.g., `loss: 3.21`) and the final “Training finished – LoRA adapters updated” message.

2. **Verify the adapters work** – run a quick generation test:
   ```python
   from transformers import pipeline
   generator = pipeline("text-generation", model="./lora_finetuned", tokenizer="./lora_finetuned")
   print(generator("Once upon a time", max_new_tokens=20))
   ```
   You should see a short continuation that reflects the fine‑tuned style (even with just one epoch).

3. **Checkpoint resumption** – re‑run the script; because `model.save_pretrained` stores the adapter state, you can continue training:
   ```bash
   python train_lora.py --resume_from_checkpoint ./lora_finetuned
   ```
   (Add a small `resume_from_checkpoint` logic in the script if you want full resumption.)

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | One‑line reason it matters |
|---|---------|----------------------------|
| 1 | **FSDP / DeepSpeed integration** – wrap the model with `accelerate`’s `FSDP` or DeepSpeed’s ZeRO‑3 to shard parameters across multiple GPUs, enabling fine‑tuning of 7 B+ models on a single node. | Scales training beyond a single GPU, a must‑have skill for production ML. |
| 2 | **Persistent logging with MLflow or TensorBoard** – hook `torch.utils.tensorboard.SummaryWriter` or `mlflow.start_run()` inside the loop to record loss, learning‑rate, and gradient norms. | Provides reproducible experiment tracking; hiring managers value observability habits. |
| 3 | **Gradient accumulation + mixed‑precision** – accumulate `N` batches before `optimizer.step()` and enable `torch.cuda.amp.autocast`. | Simulates larger effective batch sizes without blowing VRAM, a common real‑world pattern. |
| 4 | **Fault‑tolerant checkpointing** – add `torch.save(model.state_dict(), "ckpt.pt")` after each epoch and a `resume` flag that loads the optimizer state and step counter. | Guarantees you won’t lose progress on preemptible cloud instances (e.g., AWS Spot). |
| 5 | **Benchmarking & evaluation** – compute perplexity on a held‑out validation set and log it alongside training loss. | Moves the project from “it works” to “I can measure quality”, a key differentiator in senior interviews. |
| 6 | **Hub‑driven deployment** – after training, `model.push_to_hub("your‑username/lora‑demo")` and then use `transformers.pipeline` or the Hugging Face Inference API to serve the model as an HTTP endpoint. | Demonstrates end‑to‑end pipeline thinking: training → model registry → production serving. |

Pick any three of the above to turn the toy into a portfolio piece that mirrors the complexity of a real‑world ML engineering role.

## Key Takeaways

- LoRA lets you fine‑tune massive models with **only a few million trainable parameters**, making experiments fast and cheap.  
- The **PEFT + Hugging Face** stack gives you a reproducible, portable pipeline that runs on a laptop or scales to clusters.  
- A **complete training script** (data → tokenizer → LoRA → optimizer → checkpoint) signals to hiring managers that you can ship production‑grade ML code.  
- Adding **observability, fault tolerance, and scaling** transforms the project from a demo into a senior‑level engineering artifact.  
- Documenting every step (requirements, seeds, environment) ensures the project is **repeatable** and **shareable** on GitHub or the HF Hub.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – the original paper that introduced the method.  
- [PEFT — Parameter‑Efficient Fine‑Tuning](https://github.com/huggingface/peft) – library source, config reference, and usage examples.  
- [Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers) – core API for model loading, tokenization, and pipelines.  
- [Accelerate: Easy PyTorch distributed training](https://huggingface.co/docs/accelerate) – guide for FSDP, mixed‑precision, and multi‑GPU setups.  
- [DeepSpeed Zero‑3 Optimizer](https://docs.deepspeed.ai/getting-started/) – alternative scaling path for very large models.  

---