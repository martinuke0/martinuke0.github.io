---
title: "From Scratch: Building a LoRA Weight Merger in PyTorch"
date: "2026-09-22T15:00:42.752"
draft: false
tags: ["PyTorch", "LoRA", "Machine Learning", "Systems Engineering", "Portfolio Project"]
description: "Build a LoRA weight merger from scratch in PyTorch, demonstrating systems engineering and practical ML skills that signal readiness for senior roles."
summary: "This tutorial walks you through implementing a LoRA weight merger in PyTorch, giving you a concrete portfolio piece that highlights systems thinking and ML engineering prowess."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-22-from-scratch-building-a-lora-weight-merger-in-pytorch.svg"
  alt: "A diagram of a neural network merging LoRA weights"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you'll implement a LoRA weight merger from scratch using PyTorch, turning a theoretical concept into a runnable, testable tool. The project demonstrates real systems skills—data loading, tensor operations, and modular design—that hiring managers look for in ML engineering roles. By the end you'll have a portfolio piece you can extend with persistence, scaling, and observability.

LoRA (Low‑Rank Adaptation) has become the de facto method for fine‑tuning large language models with limited resources. However, many tutorials stop at training a single adapter, leaving the crucial step of merging multiple adapters back into the base model as an exercise. In this guide we will build a robust, reusable LoRA weight merger in PyTorch that can combine several adapters, handle different rank configurations, and produce a single merged model ready for inference.

## Why This Project Stands Out on a CV

- **Hands‑on PyTorch expertise** – You’ll write custom tensor operations, manage device placement, and serialize models, demonstrating fluency with the framework that powers most production ML systems.
- **Modular design** – The merger is encapsulated as a standalone function, showing you can build reusable components—a skill prized for senior ML engineer and ML infrastructure roles.
- **Parameter‑efficient fine‑tuning (PEFT) knowledge** – Implementing LoRA merging signals familiarity with modern adapter techniques used at companies like Meta, Google, and Hugging Face.
- **Systems thinking** – By adding testing, CLI, and later persistence/scaling, you exhibit the end‑to‑end ownership expected of engineers who ship and maintain ML tooling.

## Architecture Overview

The project is composed of four clear layers:

1. **Base Model** – A small but representative neural network (e.g., a two‑layer MLP) that will receive the merged weights.
2. **LoRA Adapters** – Each adapter contains low‑rank matrices `A` and `B` for a specific target layer, along with a scaling factor `alpha`.
3. **Merger Core** – A pure function that takes the base model state dict and a list of adapter state dicts, computes the merged weight for each layer, and returns a new state dict.
4. **I/O & CLI** – Utilities to load/save models and a simple command‑line interface to run the merge from the terminal.

```
+----------------+     +----------------+     +----------------+
|   Base Model   |     |  LoRA Adapter 1 |     |  LoRA Adapter 2 |
|  (state_dict)  |     |   (A1, B1)     |     |   (A2, B2)     |
+-------+--------+     +-------+--------+     +-------+--------+
        |                     |                     |
        +---------------------+---------------------+
                            |
                            v
                  +-------------------+
                  |   Merger Core     |
                  | (merge function) |
                  +-------------------+
                            |
                            v
                  +-------------------+
                  |  Merged State Dict|
                  +-------------------+
```

## Building It Step by Step

### Step 1 – Install dependencies
```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### Step 2 – Define a minimal base model
```python
# models.py
import torch
import torch.nn as nn

class SimpleMLP(nn.Module):
    def __init__(self, in_features: int, hidden: int, out_features: int):
        super().__init__()
        self.fc1 = nn.Linear(in_features, hidden)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden, out_features)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.fc2(self.relu(self.fc1(x)))
```

### Step 3 – Implement a LoRA adapter
```python
# lora.py
from typing import Dict, Tuple
import torch
import torch.nn as nn

class LoRAAdapter(nn.Module):
    """
    A single LoRA adapter for a linear layer.
    """
    def __init__(self, in_features: int, out_features: int, rank: int, alpha: float = 1.0):
        super().__init__()
        self.rank = rank
        self.alpha = alpha
        # Low‑rank matrices
        self.A = nn.Parameter(torch.randn(rank, in_features) * 0.02)
        self.B = nn.Parameter(torch.zeros(rank, out_features))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, in_features)
        # A: (rank, in_features) -> (batch, rank)
        # B: (rank, out_features) -> (batch, out_features)
        return (x @ self.A.T) @ self.B.T

    def scaling_factor(self) -> float:
        return self.alpha / self.rank
```

### Step 4 – Create two adapters for the same layer
```python
# create_adapters.py
from models import SimpleMLP
from lora import LoRAAdapter
import torch

base = SimpleMLP(784, 256, 10)
# Assume we want to adapt fc1
adapter1 = LoRAAdapter(in_features=784, out_features=256, rank=8, alpha=16)
adapter2 = LoRAAdapter(in_features=784, out_features=256, rank=4, alpha=8)
```

### Step 5 – Write the merge function
```python
# merger.py
from typing import Dict, List
import torch

def merge_lora_weights(base_state: Dict[str, torch.Tensor],
                       adapters: List[Dict[str, torch.Tensor]],
                       target_key: str) -> Dict[str, torch.Tensor]:
    """
    Merge multiple LoRA adapters into a base weight tensor.
    base_state: state_dict of the base model.
    adapters: list of state_dicts, each containing 'A' and 'B' for the same layer.
    target_key: the key in base_state that corresponds to the weight to merge.
    Returns a new state_dict with the merged weight.
    """
    merged = base_state.copy()
    base_w = base_state[target_key]  # shape (out_features, in_features)
    # Accumulate delta = sum_i (alpha_i / r_i) * (B_i @ A_i)
    delta = torch.zeros_like(base_w)
    for adapter_sd in adapters:
        A = adapter_sd['A']  # (rank, in_features)
        B = adapter_sd['B']  # (rank, out_features)
        # Compute outer product B @ A -> (out_features, in_features)
        # B: (rank, out) -> (out, rank) after transpose
        # A: (rank, in) -> (rank, in)
        # Use torch.matmul
        low_rank = torch.matmul(B.T, A)  # (out_features, in_features)
        # Scaling factor
        # We assume alpha and rank are stored in the adapter's state dict
        alpha = adapter_sd.get('alpha', 1.0)
        rank = A.shape[0]
        scale = alpha / rank
        delta += scale * low_rank
    # Add delta to base weight
    merged[target_key] = base_w + delta
    return merged
```

### Step 6 – Run the merge and save
```python
# run_merge.py
import torch
from models import SimpleMLP
from merger import merge_lora_weights

base = SimpleMLP(784, 256, 10)
# Load adapter weights (for demonstration, we use random)
adapter1_sd = {
    'A': torch.randn(8, 784) * 0.02,
    'B': torch.randn(8, 256) * 0.01,
    'alpha': 16.0
}
adapter2_sd = {
    'A': torch.randn(4, 784) * 0.02,
    'B': torch.randn(4, 256) * 0.01,
    'alpha': 8.0
}

base_state = base.state_dict()
adapters = [adapter1_sd, adapter2_sd]

# Merge the weight of fc1
merged_state = merge_lora_weights(base_state, adapters, target_key='fc1.weight')

# Load merged weights back into a new model
merged_model = SimpleMLP(784, 256, 10)
merged_model.load_state_dict(merged_state)

# Save the merged model
torch.save(merged_model.state_dict(), 'merged_model.pt')
print("Merged model saved to merged_model.pt")
```

## Running and Testing It

1. **Setup** – Ensure you have Python 3.9+ and PyTorch installed as shown in Step 1.
2. **Execute** – Place all the code snippets in a single directory and run:
   ```bash
   python run_merge.py
   ```
3. **Verify** – The script prints `"Merged model saved to merged_model.pt"` and creates the file. You can then load the checkpoint and compare the weight of `fc1.weight` before and after merging:
   ```python
   import torch
   original = torch.load('original_model.pt')
   merged = torch.load('merged_model.pt')
   diff = (original['fc1.weight'] - merged['fc1.weight']).norm()
   print(f"Weight difference after merge: {diff.item():.4f}")
   ```
   A non‑zero difference (within numerical tolerance) confirms the merge was applied.
4. **Unit test** – Add a `pytest` test that creates a base model, two adapters, merges, and asserts the merged weight equals `base + sum(scale_i * B_i @ A_i)`.

## Extending It: Your Roadmap to Senior-Level

1. **Configuration Management** – Load adapter hyper‑parameters (rank, alpha) from a YAML or JSON file, enabling reproducible experiments without code changes.  
   *Why it matters*: Decouples experiment setup from logic, a must‑have for ML platforms serving multiple teams.

2. **Persistence Layer** – Store merged models in a versioned object store (e.g., S3, GCS) with metadata, and implement a simple CLI to fetch a specific version.  
   *Why it matters*: Provides auditability and rollback capability, mirroring production ML lifecycle.

3. **Horizontal Scaling** – Distribute the merge computation across multiple GPUs or machines using `torch.distributed` and `DistributedDataParallel`.  
   *Why it matters*: Allows handling large base models that exceed single‑machine memory.

4. **Observability** – Emit structured logs (JSON) and metrics (merge duration, weight norm) to stdout or a Prometheus endpoint.  
   *Why it matters*: Enables debugging and SLA monitoring in a service‑oriented architecture.

5. **Benchmark Harness** – Add a script that measures peak memory usage and wall‑clock time for merging varying numbers of adapters, outputting results to a CSV.  
   *Why it matters*: Provides data to justify infrastructure decisions and compare against baseline implementations.

## Key Takeaways

- You now have a **complete, runnable LoRA weight merger** that demonstrates real PyTorch systems skills.
- The modular design makes it trivial to **extend with persistence, scaling, and observability**, showcasing senior‑level engineering thinking.
- By adding tests and benchmarks, you produce a **portfolio artifact** that speaks to both ML depth and production readiness.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – the original paper that introduced the technique.
- [Hugging Face PEFT Library](https://huggingface.co/docs/peft/) – production‑grade implementation of parameter‑efficient fine‑tuning, including merging utilities.
- [PyTorch Distributed Data Parallel](https://pytorch.org/docs/stable/generated/torch.nn.parallel.DistributedDataParallel.html) – official guide for scaling training/merging across GPUs.
- [MLflow Model Registry](https://mlflow.org/docs/latest/model-registry.html) – for versioning and serving merged models in a MLOps pipeline.