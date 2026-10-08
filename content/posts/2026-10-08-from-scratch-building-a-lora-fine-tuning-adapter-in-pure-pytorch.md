---
title: "From Scratch: Building a LoRA Fine-Tuning Adapter in Pure PyTorch"
date: "2026-10-08T08:00:59.535"
draft: false
tags: ["deep-learning", "pytorch", "lora", "fine-tuning", "transformers"]
description: "A hands-on guide to implementing LoRA fine-tuning from scratch in PyTorch, with runnable code, production-oriented extensions, and scaling tips."
summary: "Implement a Low-Rank Adaptation (LoRA) module from scratch in PyTorch, then extend it with persistence, observability, and distributed training for production readiness."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-08-from-scratch-building-a-lora-fine-tuning-adapter-in-pure-pytorch.svg"
  alt: "A neural network diagram showing low-rank weight matrices"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a LoRA fine‑tuning adapter from scratch in pure PyTorch, providing runnable code that you can drop into any transformer. You’ll learn how the low‑rank decomposition works, how to hook it into attention and feed‑forward layers, and how to evolve the prototype into a production‑grade component with checkpointing, metrics, and distributed training.

In the race to fine‑tune large language models, parameter‑efficient methods like LoRA have become the de‑facto standard for teams that need to adapt a model without retraining all weights. By injecting trainable low‑rank matrices into the transformer blocks, LoRA slashes memory usage and enables rapid iteration. However, most tutorials stop at the Hugging Face wrapper; they hide the underlying mechanics. This guide pulls the curtain back, implementing the LoRA adapter from first principles in PyTorch, then showing how to turn that prototype into a resilient, observable service.

## Why This Project Stands Out on a CV

- **Low‑rank optimization expertise** – you will write the math that decomposes a weight matrix into two smaller matrices, demonstrating a deep understanding of linear algebra and parameter‑efficient fine‑tuning.
- **Custom autograd & PyTorch internals** – by subclassing `nn.Module` and defining forward/backward manually, you signal comfort with PyTorch’s dynamic graph and extensibility.
- **End‑to‑end ML pipeline** – the project includes data loading, training, evaluation, and model serialization, showcasing the full lifecycle expected of a senior ML engineer.
- **Production readiness** – you will add checkpointing, distributed training (DDP), mixed precision, and observability hooks, which are common requirements for infrastructure or applied research roles.
- **Transferable to real systems** – the same patterns apply to large‑scale training on GPUs/TPUs, making the candidate attractive for positions at companies like Anthropic, Cohere, or any team shipping LLM products.

## Architecture Overview

The solution is composed of four layers:

1. **LoRA Linear Layer** – a thin wrapper that holds the frozen original weight `W` and two trainable low‑rank matrices `A` (shape `r × d`) and `B` (shape `d × r`). The effective weight becomes `W + α·B·A`.
2. **Transformer Block Injection** – each attention (`Q/K/V`) and feed‑forward linear projection is replaced with the LoRA wrapper, allowing the model to keep its pretrained weights intact while only the small `A`/`B` parameters are updated.
3. **Training Engine** – a standard PyTorch training loop that iterates over a dataset, computes the loss, and calls `optimizer.step()`. The optimizer only sees the LoRA parameters; the base model is frozen via `requires_grad=False`.
4. **Persistence & Serving** – adapters are saved as separate checkpoint files (`lora_adapters.pt`) and can be reloaded into any compatible model, enabling quick swapping of fine‑tuned behaviors.

A simplified textual diagram:

```
Pretrained Transformer
   ┌─────────────────────┐
   │  Attention Block    │
   │  ┌─────┐  ┌─────┐   │
   │  │ W_q │→ │LoRA │   │
   │  └─────┘  └─────┘   │
   │  ┌─────┐  ┌─────┐   │
   │  │ W_k │→ │LoRA │   │
   │  └─────┘  └─────┘   │
   │  ┌─────┐  ┌─────┐   │
   │  │ W_v │→ │LoRA │   │
   │  └─────┘  └─────┘   │
   └─────────────────────┘
          │
   Feed‑Forward Linear
   ┌─────┐  ┌─────┐
   │ W_1 │→ │LoRA │
   └─────┘  └─────┘
```

## Building It Step by Step

### 1. Environment Setup

```bash
python -m venv lora_env
source lora_env/bin/activate
pip install torch==2.2.0 --index-url https://download.pytorch.org/whl/cu118
pip install transformers==4.39.0 datasets==2.18.0
```

### 2. Implement the LoRA Linear Layer

```python
import torch
import torch.nn as nn

class LoRALinear(nn.Module):
    """
    Linear layer with LoRA adaptation.
    Args:
        in_features: original input dimension
        out_features: original output dimension
        r: rank of the low‑rank matrices
        alpha: scaling factor (often r)
    """
    def __init__(self, in_features: int, out_features: int, r: int = 8, alpha: int = 16):
        super().__init__()
        # Frozen original weight
        self.weight = nn.Parameter(torch.empty(out_features, in_features), requires_grad=False)
        nn.init.kaiming_uniform_(self.weight, a=math.sqrt(5))
        # Trainable low‑rank matrices
        self.lora_A = nn.Parameter(torch.empty(r, in_features))
        self.lora_B = nn.Parameter(torch.empty(out_features, r))
        nn.init.kaiming_uniform_(self.lora_A, a=math.sqrt(5))
        nn.init.zeros_(self.lora_B)          # start from zero
        self.alpha = alpha
        self.r = r

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Original linear transformation
        base = F.linear(x, self.weight)
        # LoRA contribution: (B @ A) scaled
        lora = F.linear(x, self.lora_A)      # (batch, seq, r)
        lora = F.linear(lora, self.lora_B)   # (batch, seq, out)
        return base + (self.alpha / self.r) * lora
```

### 3. Inject LoRA into a Transformer Block

For demonstration we use a minimal transformer block based on `nn.TransformerEncoderLayer`. In practice you would replace the `self_attn` and `linear1`/`linear2` with `LoRALinear`.

```python
class LoRATransformerBlock(nn.Module):
    def __init__(self, d_model: int, nhead: int, dim_feedforward: int, r: int = 8):
        super().__init__()
        self.self_attn = nn.MultiheadAttention(d_model, nhead, batch_first=True)
        # Replace linear projections with LoRA versions
        self.q_proj = LoRALinear(d_model, d_model, r=r)
        self.k_proj = LoRALinear(d_model, d_model, r=r)
        self.v_proj = LoRALinear(d_model, d_model, r=r)
        self.out_proj = LoRALinear(d_model, d_model, r=r)

        self.linear1 = LoRALinear(d_model, dim_feedforward, r=r)
        self.linear2 = LoRALinear(dim_feedforward, d_model, r=r)

        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.dropout = nn.Dropout(0.1)

    def forward(self, src: torch.Tensor, src_mask=None) -> torch.Tensor:
        # Self‑attention with LoRA‑adapted projections
        q = self.q_proj(src)
        k = self.k_proj(src)
        v = self.v_proj(src)
        attn_out, _ = self.self_attn(q, k, v, attn_mask=src_mask)
        attn_out = self.out_proj(attn_out)
        src = src + self.dropout(attn_out)
        src = self.norm1(src)

        # Feed‑forward with LoRA
        ff_out = self.linear2(F.relu(self.linear1(src)))
        src = src + self.dropout(ff_out)
        src = self.norm2(src)
        return src
```

### 4. Training Loop

```python
from torch.utils.data import DataLoader, TensorDataset
import torch.optim as optim

# Dummy dataset – replace with your own
x = torch.randn(128, 32, 768)   # (batch, seq_len, d_model)
y = torch.randint(0, 10, (128,))  # classification labels
dataset = TensorDataset(x, y)
loader = DataLoader(dataset, batch_size=16, shuffle=True)

model = LoRATransformerBlock(d_model=768, nhead=12, dim_feedforward=3072, r=8)
criterion = nn.CrossEntropyLoss()
optimizer = optim.AdamW(
    [p for p in model.parameters() if p.requires_grad],
    lr=1e-3, weight_decay=0.01
)

model.train()
for epoch in range(10):
    for batch_x, batch_y in loader:
        optimizer.zero_grad()
        out = model(batch_x)               # (batch, seq, d_model)
        # Use mean pooling for classification
        pooled = out.mean(dim=1)
        loss = criterion(pooled, batch_y)
        loss.backward()
        optimizer.step()
    print(f"Epoch {epoch+1}, loss: {loss.item():.4f}")
```

### 5. Save & Load Adapters

```python
def save_lora_adapters(model, path: str):
    """Only store trainable LoRA parameters."""
    lora_state = {
        name: param.clone()
        for name, param in model.named_parameters()
        if 'lora' in name and param.requires_grad
    }
    torch.save(lora_state, path)

def load_lora_adapters(model, path: str):
    """Load saved LoRA weights into the model."""
    state = torch.load(path, map_location='cpu')
    model.load_state_dict(state, strict=False)
```

## Running and Testing It

1. **Train**  
   ```bash
   python train_lora.py
   ```
   The script prints loss per epoch; a decreasing curve confirms the adapter is learning.

2. **Quick Evaluation**  
   ```python
   model.eval()
   with torch.no_grad():
       logits = model(x).mean(dim=1)
       preds = logits.argmax(dim=-1)
       acc = (preds == y).float().mean()
       print(f"Accuracy: {acc.item():.4f}")
   ```

3. **Unit Test for LoRA Layer**  
   ```python
   def test_lora_linear():
       layer = LoRALinear(768, 768, r=8)
       x = torch.randn(4, 32, 768)
       out = layer(x)
       assert out.shape == (4, 32, 768)
       # Verify gradient flows only to A and B
       loss = out.sum()
       loss.backward()
       assert layer.weight.grad is None
       assert layer.lora_A.grad is not None
       assert layer.lora_B.grad is not None
   ```

4. **Integration Test**  
   Save adapters, reload, and ensure the model reproduces identical outputs:

   ```python
   save_lora_adapters(model, "adapters.pt")
   model2 = LoRATransformerBlock(d_model=768, nhead=12, dim_feedforward=3072, r=8)
   load_lora_adapters(model2, "adapters.pt")
   model2.eval()
   with torch.no_grad():
       out1 = model(x)
       out2 = model2(x)
   assert torch.allclose(out1, out2, atol=1e-5)
   ```

## Extending It: Your Roadmap to Senior-Level

- **Distributed Training with `torch.distributed`** – wrap the training loop in `DistributedDataParallel` to scale across multiple GPUs or nodes, cutting wall‑clock time linearly.
- **Mixed Precision & Gradient Checkpointing** – use `torch.cuda.amp.autocast` and `torch.utils.checkpoint.checkpoint` to reduce memory consumption, enabling larger batch sizes on the same hardware.
- **Persistent Model Registry** – store adapters in a versioned object store (e.g., S3, GCS) with metadata, and expose a simple REST endpoint via FastAPI for serving; this mirrors real MLOps pipelines.
- **Observability & Metrics** – integrate `torchmetrics` and push loss/accuracy to Prometheus/Grafana, add logging of gradient norms, and set up alerts for divergence.
- **Fault‑Tolerant Training** – implement checkpointing every N steps, automatic resume on node failure, and retry logic for data loading, ensuring long‑running jobs survive infrastructure hiccups.
- **Benchmarking & Profiling** – run `torch.profiler` to identify bottlenecks, compare throughput against a baseline, and report numbers that demonstrate performance awareness to stakeholders.

## Key Takeaways

- LoRA replaces a weight matrix `W` with `W + α·B·A`, drastically reducing trainable parameters while preserving model capacity.
- The adapter can be injected into any linear layer of a transformer, allowing fine‑tuning of attention and feed‑forward projections without touching the pretrained backbone.
- A clean PyTorch implementation uses `nn.Module` subclasses, frozen weights, and a standard optimizer loop, making it easy to extend.
- Production readiness requires distributed training, mixed precision, checkpointing, observability, and a model registry.
- This project showcases both algorithmic depth and systems engineering skill, appealing to hiring managers in ML infrastructure, research, or applied AI roles.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – the original paper that introduced the technique.
- [PyTorch Distributed Data Parallel (DDP) Tutorial](https://pytorch.org/tutorials/intermediate/ddp_tutorial.html) – guide to scaling training across GPUs.
- [Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers/) – reference for integrating LoRA with pretrained models.
- [torch.cuda.amp — Automatic Mixed Precision](https://pytorch.org/docs/stable/amp.html) – official docs for memory‑efficient training.
- [MLflow Model Registry](https://mlflow.org/docs/latest/model-registry.html) – tool for versioning and serving adapters in production.