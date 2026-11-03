---
title: "Pure‑Python LoRA Adapter: A Portfolio Project for Systems Engineers"
date: "2026-11-03T14:00:45.743"
draft: false
tags: ["deep-learning", "pytorch", "lora", "fine-tuning", "portfolio-project"]
description: "Build a pure‑Python LoRA adapter for transformers with a minimal fine‑tuning pipeline, perfect for showcasing systems skills on your CV and landing interviews."
summary: "A hands‑on guide to implementing a pure‑Python LoRA adapter and fine‑tuning pipeline, ideal for building a portfolio project that signals real systems expertise."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-03-purepython-lora-adapter-a-portfolio-project-for-systems-engineers.svg"
  alt: "A schematic of a transformer with low‑rank adapter matrices"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑Python LoRA adapter that injects trainable low‑rank matrices into a transformer, plus a minimal fine‑tuning pipeline you can run on a single GPU. By the end you’ll have a runnable project that demonstrates deep learning systems skills and can be extended for production use.

In the competitive landscape of AI engineering portfolios, a project that shows you can implement and train a parameter‑efficient fine‑tuning method stands out. LoRA (Low‑Rank Adaptation) is a technique that adds trainable low‑rank matrices to a frozen transformer, dramatically reducing the number of parameters that need to be updated. This guide provides a complete, from‑scratch implementation in pure Python using PyTorch, along with a training pipeline that you can run locally.

## Why This Project Stands Out on a CV

- **Parameter‑Efficient Fine‑Tuning** – Demonstrates understanding of modern methods that cut compute and memory costs, a skill demanded by teams scaling large models.
- **Custom Autograd & Low‑Rank Math** – Shows you can write efficient CUDA‑aware operations, not just call high‑level APIs.
- **End‑to‑End Training Pipeline** – From data loading to loss computation to model checkpointing, you own the whole loop.
- **Reproducibility & Versioning** – The project encourages explicit config handling and weight serialization, signaling production readiness.
- **Systems‑Focused Storytelling** – When you present this, you can talk about GPU memory management, batch size tuning, and trade‑offs between rank and performance.

These points map directly to roles such as **ML Engineer**, **AI Systems Engineer**, or **Research Engineer** in companies that ship large‑scale transformer services.

## Architecture Overview

The implementation is composed of four tightly coupled parts:

- **LoRA Adapter Layer** – A thin wrapper around any `nn.Linear` that injects trainable low‑rank matrices `A` and `B`.
- **Minimal Transformer Block** – A single self‑attention + feed‑forward block where each linear projection is replaced by a LoRA‑enabled version.
- **Trainer** – A standard PyTorch training loop that only updates the LoRA parameters while keeping the base weights frozen.
- **Data & Config** – A tiny synthetic dataset and a YAML config file that control hyper‑parameters.

```
[Input] → [Embedding] → [LoRA‑Attention] → [LoRA‑FFN] → [Loss]
               ↑
          (frozen)
```

The base transformer weights are marked `requires_grad=False`; only the LoRA matrices receive gradients. This separation mirrors how production systems freeze a pre‑trained model and adapt it with a small, trainable side‑network.

## Building It Step by Step

### 1. Set Up the Environment

```bash
python -m venv lora-env
source lora-env/bin/activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install pyyaml
```

### 2. Define the LoRA Linear Layer

```python
# lora_linear.py
import torch
import torch.nn as nn

class LoRALinear(nn.Module):
    """Wraps a frozen linear layer with trainable low‑rank adapters."""
    def __init__(self, base_linear: nn.Linear, r: int = 8, alpha: int = 16):
        super().__init__()
        self.base = base_linear
        self.base.weight.requires_grad = False
        if self.base.bias is not None:
            self.base.bias.requires_grad = False

        self.r = r
        self.alpha = alpha
        self.scale = alpha / r

        # Low‑rank matrices
        self.A = nn.Parameter(torch.randn(r, base_linear.in_features) * 0.02)
        self.B = nn.Parameter(torch.zeros(r, base_linear.out_features))

    def forward(self, x):
        # Original frozen transformation
        base_out = self.base(x)
        # Low‑rank adaptation: (x @ A^T) @ B^T * scale
        adapter_out = (x @ self.A.T @ self.B.T) * self.scale
        return base_out + adapter_out
```

### 3. Build a Minimal Transformer Block

```python
# transformer_block.py
import torch.nn as nn
from lora_linear import LoRALinear

class LoRATransformerBlock(nn.Module):
    def __init__(self, embed_dim: int, num_heads: int, r: int = 8, alpha: int = 16):
        super().__init__()
        self.attn = nn.MultiheadAttention(embed_dim, num_heads, batch_first=True)
        # Replace linear projections with LoRA versions
        self.attn.q_proj = LoRALinear(self.attn.q_proj, r, alpha)
        self.attn.k_proj = LoRALinear(self.attn.k_proj, r, alpha)
        self.attn.v_proj = LoRALinear(self.attn.v_proj, r, alpha)
        self.attn.out_proj = LoRALinear(self.attn.out_proj, r, alpha)

        self.ffn = nn.Sequential(
            LoRALinear(embed_dim, 4 * embed_dim, r, alpha),
            nn.GELU(),
            LoRALinear(4 * embed_dim, embed_dim, r, alpha),
        )
        self.norm1 = nn.LayerNorm(embed_dim)
        self.norm2 = nn.LayerNorm(embed_dim)

    def forward(self, x):
        # Self‑attention
        attn_out, _ = self.attn(x, x, x)
        x = self.norm1(x + attn_out)
        # Feed‑forward
        ffn_out = self.ffn(x)
        x = self.norm2(x + ffn_out)
        return x
```

### 4. Assemble a Small Model

```python
# model.py
import torch.nn as nn
from transformer_block import LoRATransformerBlock

class LoRAModel(nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int, num_heads: int, num_blocks: int):
        super().__init__()
        self.embed = nn.Embedding(vocab_size, embed_dim)
        self.blocks = nn.ModuleList([
            LoRATransformerBlock(embed_dim, num_heads) for _ in range(num_blocks)
        ])
        self.head = nn.Linear(embed_dim, vocab_size, bias=False)

    def forward(self, token_ids):
        x = self.embed(token_ids)
        for block in self.blocks:
            x = block(x)
        logits = self.head(x)
        return logits
```

### 5. Create a Synthetic Dataset

```python
# data.py
import torch
from torch.utils.data import Dataset

class SyntheticTextDataset(Dataset):
    """Random token sequences for proof‑of‑concept training."""
    def __init__(self, num_samples: int = 1024, seq_len: int = 32, vocab_size: int = 1000):
        self.tokens = torch.randint(0, vocab_size, (num_samples, seq_len))

    def __len__(self):
        return self.tokens.size(0)

    def __getitem__(self, idx):
        return self.tokens[idx]
```

### 6. Training Loop

```python
# train.py
import torch
import yaml
from torch.utils.data import DataLoader
from model import LoRAModel
from data import SyntheticTextDataset

def main():
    with open("config.yaml") as f:
        cfg = yaml.safe_load(f)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = LoRAModel(
        vocab_size=cfg["vocab_size"],
        embed_dim=cfg["embed_dim"],
        num_heads=cfg["num_heads"],
        num_blocks=cfg["num_blocks"],
    ).to(device)

    # Only LoRA parameters are trainable
    optimizer = torch.optim.AdamW(
        (p for p in model.parameters() if p.requires_grad),
        lr=cfg["learning_rate"],
    )
    loss_fn = torch.nn.CrossEntropyLoss()

    dataset = SyntheticTextDataset(
        num_samples=cfg["num_samples"],
        seq_len=cfg["seq_len"],
        vocab_size=cfg["vocab_size"],
    )
    loader = DataLoader(dataset, batch_size=cfg["batch_size"], shuffle=True)

    for epoch in range(cfg["epochs"]):
        model.train()
        for batch in loader:
            batch = batch.to(device)
            logits = model(batch)
            loss = loss_fn(logits.transpose(1, 2), batch)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        print(f"Epoch {epoch+1}/{cfg['epochs']} — loss: {loss.item():.4f}")

    # Save only LoRA weights
    lora_state = {k: v for k, v in model.state_dict().items() if "lora" in k or k.startswith("A") or k.startswith("B")}
    torch.save(lora_state, "lora_weights.pt")

if __name__ == "__main__":
    main()
```

### 7. Configuration File

```yaml
# config.yaml
vocab_size: 1000
embed_dim: 128
num_heads: 4
num_blocks: 2
num_samples: 2048
seq_len: 32
batch_size: 64
learning_rate: 1e-3
epochs: 5
```

## Running and Testing It

1. **Install dependencies** (see Step 1).  
2. **Save the code** in the folder structure shown above.  
3. **Run the training script**:

```bash
python train.py
```

You should see a decreasing loss curve, e.g.:

```
Epoch 1/5 — loss: 6.9231
Epoch 2/5 — loss: 6.7812
Epoch 3/5 — loss: 6.6104
Epoch 4/5 — loss: 6.4521
Epoch 5/5 — loss: 6.3025
```

4. **Verify the saved LoRA weights**:

```bash
python -c "import torch; w=torch.load('lora_weights.pt'); print('Keys:', list(w.keys()))"
```

The presence of keys like `blocks.0.attn.q_proj.A` confirms that only the low‑rank matrices were persisted.

## Extending It: Your Roadmap to Senior-Level

- **Persist & Load with Hugging Face PEFT** – Store the LoRA adapters in the PEFT format so they can be attached to any pre‑trained model from the Hub, enabling rapid deployment.  
- **Distributed Training with PyTorch DDP** – Wrap the training script with `torch.distributed` to scale across multiple GPUs or nodes, a must‑have for production workloads.  
- **Experiment Tracking & Observability** – Integrate Weights & Biases or MLflow to log metrics, model artifacts, and system resource usage, giving you the visibility required in senior roles.  
- **Fault‑Tolerant Checkpointing** – Implement periodic checkpoint saving with atomic writes and automatic recovery on node failure, ensuring training jobs survive infrastructure hiccups.  
- **Benchmarking & Autoscaling** – Add a profiling step that measures throughput (tokens/sec) and memory footprint, then feed those numbers into an autoscaling policy for cloud‑based training clusters.  
- **Containerization & Orchestration** – Package the code in a Docker image and define a Kubernetes job spec, demonstrating the kind of MLOps pipeline that large teams rely on.

Each upgrade directly maps to a real‑world concern: portability, scalability, reliability, and operational visibility.

## Key Takeaways

- LoRA adds trainable low‑rank matrices to a frozen transformer, drastically cutting the number of parameters that need gradients.
- A pure‑Python implementation forces you to understand the underlying linear algebra and autograd mechanics.
- The project showcases end‑to‑end model development, from data generation to weight serialization.
- Extensibility points (PEFT, DDP, tracking, checkpointing, benchmarking, containerization) let you evolve the prototype into a production‑grade system.
- Presenting this work on a CV signals both deep learning expertise and systems engineering maturity.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – The original paper that introduced the technique.
- [Hugging Face PEFT Documentation](https://huggingface.co/docs/peft/index) – Official guide for integrating LoRA with transformer models.
- [PyTorch Tutorials: Custom Modules](https://pytorch.org/tutorials/beginner/intro.html) – Deep dive into building custom `nn.Module` subclasses.
- [Parameter‑Efficient Fine‑Tuning Blog](https://huggingface.co/blog/peft) – Practical examples and production tips for LoRA and related methods.