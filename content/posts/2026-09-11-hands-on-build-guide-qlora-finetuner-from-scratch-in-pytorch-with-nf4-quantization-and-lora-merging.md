---
title: "Hands-On Build Guide: QLoRA Fine‑Tuner From Scratch in PyTorch with NF4 Quantization and LoRA Merging"
date: "2026-09-11T12:00:50.640"
draft: false
tags: ["pytorch", "qlora", "4bit-quantization", "lora", "cv", "side-project"]
description: "Build a QLoRA fine‑tuner from scratch in PyTorch, implementing NF4 4‑bit quantization and LoRA weight merging for efficient CV model customization."
summary: "A step‑by‑step guide to training a quantized LLaMA‑style model with QLoRA, merging LoRA adapters, and packaging the result as a portable CV asset."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-hands-on-build-guide-qlora-finetuner-from-scratch-in-pytorch-with-nf4-quantization-and-lora-merging.svg"
  alt: "Neural network weights and code editor representing QLoRA fine‑tuning."
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a QLoRA fine‑tuner from scratch in PyTorch, using NF4 4‑bit quantization to slash memory, LoRA adapters for parameter‑efficient updates, and a weight‑merge step that yields a single, deployable model you can ship to production or showcase on your CV.

Building a QLoRA fine‑tuner from scratch is a concrete, high‑impact side project that demonstrates you can manipulate low‑level PyTorch APIs, work with 4‑bit quantized models, and produce a merged, ready‑to‑deploy artifact. Hiring managers see that you understand both the theory of quantized training and the practical steps of inference‑ready model assembly.

## Why This Project Stands Out on a CV

A QLoRA implementation signals several production‑grade competencies. First, you show mastery of PyTorch’s lower‑level APIs—loading models with `bitsandbytes`, inserting LoRA modules via the PEFT library, and performing in‑place weight updates without copying the entire parameter set. Second, the project demonstrates familiarity with modern quantization schemes (NF4) that reduce GPU memory by ~50 % while preserving accuracy, a skill directly relevant to roles that work with large language models on constrained hardware. Third, the end‑to‑end pipeline—from data preparation → quantized training → LoRA merging → model export—mirrors the workflow of an ML engineer deploying custom adapters to a serving stack (e.g., FastAPI + HuggingFace Text Generation Inference). Finally, the merged model is a single, portable artifact (Safetensors) that can be version‑controlled, shared in a portfolio, or directly uploaded to a model hub, showcasing your ability to ship reproducible code rather than just notebook experiments. Together, these elements position the project for ML engineer, NLP researcher, or applied AI product developer roles.

## Architecture Overview

- **Base model** – a LLaMA‑style decoder, loaded in NF4 4‑bit via `bitsandbytes`. The quantized weight tensors live in int4, reducing VRAM roughly 4× compared with fp16.  
- **Quantization wrapper** – `nn.Module` that maps the original `float16` parameters to their NF4 int4 counterparts and provides a `dequantize()` method for inference.  
- **LoRA adapter** – `peft.LoraModel` inserted after each attention’s `q_proj` and `v_proj`. Only the low‑rank ΔW matrices are trained, leaving the quantized base weights untouched.  
- **Trainer loop** – standard PyTorch forward/backward with gradient checkpointing to keep memory footprints low; optimizer is AdamW with a cosine decay schedule.  
- **Merge step** – `model.merge_and_unload()` adds the accumulated LoRA ΔW to the de‑quantized base weights, producing a full‑precision fp16 model ready for `save_pretrained`.  
- **Persistence layer** – outputs are written as Safetensors files, which are mmap‑able and supported by both HuggingFace `transformers` and `optimum` serving runtimes.

```
Base Model ──► NF4 Quant wrapper ──► LoRA insert ──► Trainer ──► Merge ──► Safetensors model
```

## Building It Step By Step

Below are numbered, runnable code snippets that cover the core logic. Install the required packages first:

```bash
pip install torch bitsandbytes transformers peft datasets tqdm
```

**Step 1 – Imports & reproducibility**

```python
import random
import torch
from torch import nn
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, Trainer, DataCollatorForLanguageModeling
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from datasets import load_dataset
from tqdm import tqdm
import os, json

# Seed everything for deterministic runs
random.seed(42)
torch.manual_seed(42)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(42)
```

**Step 2 – Load the base model in NF4 4‑bit**

```python
model_name = "meta-llama/Llama-2-7b-hf"          # any decoder‑only model works
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",                   # NF4 quantization
    bnb_4bit_compute_dtype=torch.float16,
    device_map="auto",
)
tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
tokenizer.pad_token = tokenizer.eos_token   # Llama‑2 needs this
```

**Step 3 – Prepare the model for k‑bit training & insert LoRA**

```python
model = prepare_model_for_kbit_training(model)

lora_cfg = LoraConfig(
    r=8,                       # rank
    lora_alpha=16,
    target_modules=["q_proj", "v_proj"],   # attention layers
    lora_dropout=0.1,
    bias="none",
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()   # should show ~0.1 % of all params
```

**Step 4 – Load a tiny instruction‑following dataset**

```python
dataset = load_dataset("tatsu-lab/alpaca", split="train[:1%]")   # ~500 examples
def format_example(example):
    prompt = f"""Below is an instruction that describes a task. Write a response that appropriately completes the request.

### Instruction:
{example['instruction']}

### Input:
{example.get('input', '')}

### Response:
"""
    return tokenizer(prompt, truncation=True, max_length=512)
dataset = dataset.map(format_example, remove_columns=dataset.column_names)
```

**Step 5 – Data collator & training arguments**

```python
data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)

training_args = TrainingArguments(
    output_dir="./qlora_out",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    max_steps=500,
    learning_rate=2e-4,
    fp16=True,
    logging_steps=10,
    save_steps=100,
    warmup_ratio=0.03,
    weight_decay=0.01,
    lr_scheduler_type="cosine",
    report_to="none",
)
```

**Step 6 – Instantiate the Trainer**

```python
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=dataset,
    data_collator=data_collator,
)
```

**Step 7 – Train the QLoRA model**

```python
trainer.train()
```

**Step 8 – Merge LoRA adapters and export**

```python
merged_model = model.merge_and_unload()
merged_model.save_pretrained(
    "./qlora_merged",
    safe_serialization=True,   # produces .safetensors
)
tokenizer.save_pretrained("./qlora_merged")
print("✅ Merged model saved to ./qlora_merged")
```

**Step 9 – Verify the merged model works**

```python
from transformers import pipeline

pipe = pipeline(
    "text-generation",
    model="./qlora_merged",
    tokenizer=tokenizer,
    device_map="auto",
)

prompt = "Write a short tagline for a cloud‑native data platform."
output = pipe(prompt, max_new_tokens=30, do_sample=True, temperature=0.8)[0]["generated_text"]
print("\nGenerated tagline:", output.strip())
```

## Running and Testing It

1. **Execute the script**  
   ```bash
   python train_qlora.py
   ```
   The Trainer prints loss at every `logging_steps` and saves checkpoints under `./qlora_out`.

2. **Check memory usage** – before training, run  
   ```python
   print("GPU memory allocated:", torch.cuda.memory_allocated() / 1e9, "GB")
   ```  
   After the merge, the same call should show a ~40‑50 % reduction versus the original fp16 model.

3. **Validate generated text** – the snippet in Step 9 of the building section produces coherent output; you can further probe with a few seed prompts to ensure the fine‑tuned style is present.

4. **Unit‑test the merge** – a quick assertion that the merged weight matrix equals the base weight plus the LoRA ΔW:  
   ```python
   for name, param in merged_model.named_parameters():
       if "lora_" not in name:
           base = model.get_parameter(name)  # original quantized param
           assert torch.allclose(param.data, base.data + model.lora_parameters[name].weight.sum(dim=0), rtol=1e-5)
   print("Merge sanity check passed")
   ```

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence with FSDP** – Wrap the model in `torch.distributed.fsdp.FullyShardedDataParallel` to train across 2‑8 GPUs without OOM, and checkpoint only the LoRA ΔW (tiny files). *Why it matters*: Enables scaling the project to larger models (13 B+ parameters) on a single workstation or small cluster.  

2. **Horizontal scaling with DeepSpeed ZeRO‑3** – Use `deepspeed.initialize()` to offload optimizer states and gradients to CPU RAM, allowing batch sizes an order of magnitude larger. *Why it matters*: Faster convergence and the ability to experiment with learning‑rate schedules that require more steps.  

3. **Observability stack** – Integrate TensorBoard (`trainer.add_callback(TensorBoardCallback)`) and emit custom metrics (peak GPU memory, loss curvature) that can be scraped by Prometheus. *Why it matters*: Hiring managers value engineers who can instrument code for production monitoring and debugging.  

4. **Fault tolerance & early stopping** – Add a `EarlyStoppingCallback` that monitors validation loss and restores the best‑performing checkpoint automatically. *Why it matters*: Prevents wasted compute on over‑fitting and mirrors real‑world training pipelines that must survive pre‑emptible spot instances.  

5. **Benchmarking against a FP16 baseline** – After merging, run `evaluate` from the `datasets` library on a held‑out split (e.g., MMLU or PIQA) and log accuracy/F1. Compare to the same model trained in pure fp16 to quantify the QLoRA trade‑off. *Why it matters*: Provides concrete numbers you can quote in interviews (“QLoRA retained 98 % of fp16 accuracy while using 55 % less VRAM”).  

6. **Deployment via FastAPI + HuggingFace Text Generation Inference** – Package the merged Safetensors model into a Docker image, expose a `/generate` endpoint, and add request‑rate limiting. *Why it matters*: Turns the side project into a demonstrable production service that can be directly showcased in a portfolio or discussed in technical interviews.

## Key Takeaways

- QLoRA combines **4‑bit NF4 quantization** with **LoRA adapters** to achieve parameter‑efficient fine‑tuning of large models while keeping memory footprints low.  
- The pipeline—**load → quantize → insert LoRA → train → merge → export**—is reproducible, version‑controllable, and produces a single Safetensors artifact ready for serving.  
- Mastery of **PyTorch’s low‑level APIs**, **bitsandbytes**, and **PEFT** signals to hiring managers that you can work on real‑world LLM customization tasks.  
- The merged model can be **benchmark‑tested**, **deployed via FastAPI**, and **integrated into CI/CD** pipelines, demonstrating end‑to‑end engineering skill.  
- Extending the project with **FSDP/DeepSpeed scaling**, **observability**, and **benchmarking** moves it from a toy notebook to a production‑grade capability.  

## Further Reading

- [QLoRA: Efficient Finetuning of Quantized LLMs (arXiv)](https://arxiv.org/abs/2305.14314) – the primary paper that introduces NF4 quantization and LoRA merging.  
- [bitsandbytes Documentation – 4‑bit NF4 quantization](https://github.com/TimDettmers/bitsandbytes) – official guide to loading and de‑quantizing models in NF4.  
- [PEFT – LoRA API (HuggingFace)](https://huggingface.co/docs/peft/) – comprehensive reference for configuring and using LoRA adapters.  
- [Merging LoRA adapters – HuggingFace blog](https://huggingface.co/blog/peft-lora-merging) – step‑by‑step walkthrough of the `merge_and_unload` workflow.  

---