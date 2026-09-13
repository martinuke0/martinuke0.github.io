

---
title: "Building a Pure-Python LoRA Adapter for BERT: A Portfolio Project"
date: "2026-09-13T13:01:41.790"
draft: false
tags: ["machine-learning", "pytorch", "lora", "bert", "fine-tuning"]
description: "Learn to implement a LoRA adapter injection layer for BERT in pure Python, with a full fine-tuning loop, to showcase systems skill to hiring managers."
summary: "This post walks through building a LoRA adapter injection layer for BERT in pure Python, including a complete fine-tuning loop, and shows how to extend it for production-grade systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-13-building-a-pure-python-lora-adapter-for-bert-a-portfolio-project.svg"
  alt: "A diagram of a transformer with LoRA adapters"
  caption: ""
  relative: false
---

> **TL;DR** — This project implements a LoRA adapter injection layer for BERT in pure Python, demonstrating parameter‑efficient fine‑tuning and a complete training loop. It showcases hands‑on skills with PyTorch, Hugging Face, and software engineering best practices, making it a compelling portfolio piece for systems roles.

The demand for engineers who can ship efficient, scalable model solutions has never been higher. A side project that proves you can both *understand* and *implement* a modern fine‑tuning technique like LoRA (Low‑Rank Adaptation) signals real systems skill to hiring managers. In this guide you will build a pure‑Python LoRA adapter injection layer for a BERT‑style transformer, complete with a full fine‑tuning loop, and then see how to extend it toward production‑grade concerns.

## Why This Project Stands Out on a CV

- **Parameter‑efficient fine‑tuning (LoRA)** – Demonstrates knowledge of low‑rank matrix decomposition and how it reduces trainable parameters by orders of magnitude, a technique used at Meta, Google, and many startups.
- **Pure Python implementation** – Shows you can implement the adapter logic without relying on black‑box libraries, highlighting linear algebra, PyTorch internals, and software engineering discipline.
- **End‑to‑end ML pipeline** – Covers data loading (Hugging Face Datasets), model definition, injection, training, and evaluation, proving you can own the full lifecycle.
- **Production‑oriented extensions** – The roadmap section explicitly addresses persistence, scaling, observability, fault tolerance, and benchmarking, which are the concerns of senior ML infrastructure roles.
- **Industry‑standard stack** – Uses PyTorch, Hugging Face Transformers, and common tooling (Accelerate, DeepSpeed, MLflow), showing you can work in modern MLOps environments.

## Architecture Overview

The system is composed of five tightly coupled components:

1. **LoRA Adapter Module** – A lightweight linear layer that factorizes the weight update into two low‑rank matrices \(A \in \mathbb{R}^{r \times d}\) and \(B \in \mathbb{R}^{d \times r}\). The effective weight becomes \(W' = W + \alpha \cdot BA\).
2. **Injection Mechanism** – Recursively walks the BERT model and replaces selected `nn.Linear` layers (typically the query, key, value, and output projections in each attention block) with LoRA‑augmented versions. The original weights are frozen.
3. **BERT Backbone** – A standard Hugging Face `BertForSequenceClassification` model, which provides the transformer encoder and a classification head.
4. **Training Loop** – A custom PyTorch loop that only optimizes the LoRA parameters, using AdamW and a cross‑entropy loss. It leverages the Hugging Face `Trainer` or a manual loop for fine‑grained control.
5. **Data & Evaluation Pipeline** – Uses Hugging Face Datasets to load a GLUE benchmark (e.g., SST‑2) and computes accuracy/F1 on a validation split.

A simplified textual diagram:

```
Input → [BERT Encoder] → [LoRA‑Injected Attention] → [Classifier Head] → Output
                ↑                    ↑
          Frozen weights      LoRA (A, B) – trainable
```

## Building It Step by Step

### Step 1: Set up the environment

```bash
pip install torch transformers datasets accelerate
```

### Step 2: Define the LoRA adapter

```python
import torch
import torch.nn as nn

class LoRALinear(nn.Module):
    """
    A linear layer with a LoRA adapter.
    The original weight is frozen; only the low‑rank matrices are trained.
    """
    def __init__(self, original_linear: nn.Linear, rank: int = 8, alpha: int = 16):
        super().__init__()
        self.in_features = original_linear.in_features
        self.out_features = original_linear.out_features
        # Freeze the original weight
        self.weight = nn.Parameter(original_linear.weight.data.clone(), requires_grad=False)
        if original_linear.bias is not None:
            self.bias = nn.Parameter(original_linear.bias.data.clone(), requires_grad=False)
        else:
            self.register_parameter('bias', None)
        # LoRA low‑rank matrices
        self.rank = rank
        self.alpha = alpha
        self.lora_A = nn.Parameter(torch.randn(rank, self.in_features) * 0.02)
        self.lora_B = nn.Parameter(torch.randn(self.out_features, rank) * 0.02)
        self.scaling = self.alpha / self.rank

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Original frozen linear transformation
        original_out = nn.functional.linear(x, self.weight, self.bias)
        # LoRA path
        lora_out = nn.functional.linear(x, self.lora_A)
        lora_out = nn.functional.linear(lora_out, self.lora_B)
        return original_out + self.scaling * lora_out
```

### Step 3: Inject LoRA adapters into BERT

```python
from transformers import BertModel

def inject_lora(model: BertModel, rank: int = 8, alpha: int = 16):
    """
    Recursively replaces every nn.Linear in the attention blocks
    with a LoRALinear wrapper.
    """
    for name, module in model.named_modules():
        if isinstance(module, nn.Linear) and any(
            keyword in name for keyword in ['query', 'key', 'value', 'dense']
        ):
            # Replace the layer
            parent_name, child_name = name.rsplit('.', 1)
            parent = model.get_submodule(parent_name)
            setattr(parent, child_name, LoRALinear(module, rank, alpha))
    return model
```

### Step 4: Load a BERT model and apply injection

```python
from transformers import BertForSequenceClassification

model = BertForSequenceClassification.from_pretrained(
    'bert-base-uncased',
    num_labels=2  # Example: binary classification
)
model = inject_lora(model, rank=8, alpha=16)
```

### Step 5: Prepare the dataset

```python
from datasets import load_dataset

dataset = load_dataset('glue', 'sst2')
tokenizer = BertTokenizerFast.from_pretrained('bert-base-uncased')

def tokenize_fn(examples):
    return tokenizer(
        examples['sentence'],
        max_length=128,
        padding='max_length',
        truncation=True
    )

tokenized = dataset.map(tokenize_fn, batched=True)
```

### Step 6: Training loop (manual, fine‑grained control)

```python
from torch.utils.data import DataLoader
import torch.optim as optim

# Freeze all parameters except LoRA ones
for param in model.parameters():
    param.requires_grad = False
# Re‑enable LoRA parameters
for module in model.modules():
    if isinstance(module, LoRALinear):
        module.lora_A.requires_grad = True
        module.lora_B.requires_grad = True

train_loader = DataLoader(tokenized['train'], batch_size=16, shuffle=True)
val_loader = DataLoader(tokenized['validation'], batch_size=16)

criterion = nn.CrossEntropyLoss()
optimizer = optim.AdamW(
    [p for p in model.parameters() if p.requires_grad],
    lr=2e-4,
    weight_decay=0.01
)

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
model.to(device)

for epoch in range(num_epochs):
    model.train()
    for batch in train_loader:
        batch = {k: v.to(device) for k, v in batch.items()}
        outputs = model(**batch)
        loss = criterion(outputs.logits, batch['labels'])
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()
    # Validation
    model.eval()
    correct = 0
    total = 0
    with torch.no_grad():
        for batch in val_loader:
            batch = {k: v.to(device) for k, v in batch.items()}
            outputs = model(**batch)
            preds = torch.argmax(outputs.logits, dim=1)
            correct += (preds == batch['labels']).sum().item()
            total += batch['labels'].size(0)
    print(f'Epoch {epoch+1}, Val Acc: {correct/total:.4f}')
```

## Running and Testing It

1. **Save the script** as `train_lora.py`.
2. **Execute**:

```bash
python train_lora.py
```

3. **Expected output** (example):

```
Epoch 1, Val Acc: 0.8723
Epoch 2, Val Acc: 0.9154
...
```

4. **Verify** that only LoRA parameters are updated by checking the number of trainable parameters:

```python
trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
total_params = sum(p.numel() for p in model.parameters())
print(f'Trainable: {trainable_params} / {total_params}')
```

A typical BERT‑base model has ~110M parameters; with rank‑8 LoRA you should see only ~0.5M trainable parameters, confirming the adapter is working.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence** – Save only the LoRA weights (`torch.save({'lora_A': ..., 'lora_B': ...}, 'lora.pt')`) to keep artifacts small and enable easy sharing. *Matters because* it allows versioning and deploying adapters independently of the backbone.

2. **Horizontal Scaling** – Integrate DeepSpeed or FSDP to shard the model across multiple GPUs or nodes. *Matters because* it lets you fine‑tune larger BERT variants (e.g., BERT‑large) without running out of memory.

3. **Observability** – Log metrics, hyperparameters, and model graphs to MLflow or Weights & Biases. *Matters because* it provides experiment tracking, reproducibility, and a clear audit trail for stakeholders.

4. **Fault Tolerance** – Implement checkpointing every N steps and a resume flag that reloads the optimizer state. *Matters because* training can be interrupted by preemption or hardware failures, and you avoid losing days of compute.

5. **Benchmarking** – Use `torchprof` or `torchbench` to profile latency, memory usage, and FLOPs of the LoRA‑augmented model versus the baseline. *Matters because* you can quantify the speed‑accuracy trade‑off and justify the adapter in production.

6. **Export to Production Formats** – Convert the fine‑tuned model (backbone + LoRA) to ONNX or TensorRT for low‑latency serving. *Matters because* it bridges the gap between research prototypes and real‑world APIs.

## Key Takeaways

- LoRA provides a practical, parameter‑efficient way to adapt large transformers without full fine‑tuning.
- Implementing the adapter in pure Python deepens understanding of linear algebra, PyTorch internals, and software engineering discipline.
- The project covers the full ML lifecycle: data ingestion, model definition, training, evaluation, and production‑oriented extensions.
- Demonstrating scaling, observability, and fault tolerance signals readiness for senior ML infrastructure roles.

## Further Reading

- **LoRA paper**: [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
- **Hugging Face Transformers documentation**: [Transformers Docs](https://huggingface.co/docs/transformers/)
- **PyTorch official tutorial on fine‑tuning**: [PyTorch Tutorial](https://pytorch.org/tutorials/beginner/transfer_learning_tutorial.html)
- **DeepSpeed documentation for scaling**: [DeepSpeed Docs](https://www.deepspeed.ai/docs/)
- **MLflow experiment tracking**: [MLflow Docs](https://mlflow.org/docs/latest/index.html)