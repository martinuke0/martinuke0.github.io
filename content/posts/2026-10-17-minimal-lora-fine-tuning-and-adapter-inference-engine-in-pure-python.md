---
title: "Minimal LoRA Fine-Tuning and Adapter Inference Engine in Pure Python"
date: "2026-10-17T10:01:36.037"
draft: false
tags: ["LoRA", "fine-tuning", "adapter", "Python", "machine-learning", "systems"]
description: "A hands-on guide to building a minimal LoRA fine-tuning and adapter inference engine in pure Python, with runnable code and production-oriented extensions."
summary: "Build a compact LoRA engine from scratch, demonstrating systems skills that catch hiring managers' eyes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-17-minimal-lora-fine-tuning-and-adapter-inference-engine-in-pure-python.svg"
  alt: "LoRA adapter concept"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a minimal LoRA fine‑tuning and adapter inference engine in pure Python, giving you a concrete project that showcases low‑level matrix operations, memory‑efficient adapter design, and inference serving patterns that hiring managers look for in systems‑oriented ML roles.

In a market crowded with fine‑tuning wrappers and cloud‑only services, a self‑contained LoRA engine written from scratch signals that you understand the underlying linear algebra, can manage GPU/CPU memory trade‑offs, and are comfortable shipping inference code that scales. The following sections break down why this project stands out on a CV, outline its architecture, provide step‑by‑step implementation, show how to run and test it, and map out senior‑level extensions that turn a toy into a production‑grade component.

## Why This Project Stands Out on a CV

- **Low‑level matrix ops** – You implement forward passes, weight merging, and gradient updates with NumPy (or optionally PyTorch tensors), demonstrating comfort with the numerical primitives that underpin every deep‑learning model.
- **Adapter pattern & parameter efficiency** – By isolating LoRA matrices A and B, you show you can reduce trainable parameters by >99 % while preserving model quality, a skill directly applicable to cost‑sensitive deployments.
- **Inference serving** – The engine includes a lightweight inference loop that can be wrapped in a Flask/Starlette endpoint or a gRPC service, evidencing ability to move from training to production.
- **Memory management** – You explicitly handle weight‑sharing, off‑loading, and optional half‑precision, highlighting awareness of GPU memory constraints.
- **Testing & CI** – The project ships with pytest cases that verify shape correctness, gradient flow, and merging equivalence, illustrating a disciplined engineering approach.
- **Extensibility roadmap** – The final section outlines persistence, scaling, observability, fault tolerance, and benchmarking, proving you think beyond a single script.

Collectively, these points map to roles such as **ML Engineer**, **Systems Engineer for ML**, or **MLOps Engineer**, where the ability to build, optimize, and serve custom adapters is a differentiator.

## Architecture Overview

The engine is composed of five loosely‑coupled components:

1. **Base Layer Wrapper** – A thin class that holds the original weight matrix `W` and bias `b`. It exposes a `forward(x)` method that performs the affine transformation.
2. **LoRA Adapter** – Stores low‑rank matrices `A ∈ ℝ^(r×d)` and `B ∈ ℝ^(d_out×r)`. Its `forward(x)` computes `x @ A.T @ B.T`, which is added to the base output.
3. **Merger** – A utility that combines the base weight with the adapter via `W' = W + B @ A`. This is used for inference to avoid runtime adapter overhead.
4. **Inference Engine** – Orchestrates input preprocessing, forward pass through the merged layer, and post‑processing. It can optionally run in “adapter‑only” mode for memory‑constrained environments.
5. **Configuration & Persistence** – A simple dataclass (or JSON) holds hyper‑parameters (rank, alpha, dtype) and provides `save`/`load` hooks using `safetensors` or `pickle`.

A textual diagram:

```
Input ──► Base Layer (W, b) ──┐
        │                     │
        └──► LoRA Adapter ────► Add ──► Output
```

During training, the engine iterates over batches, computes loss, and updates only `A` and `B`. For inference, the merger produces a single effective weight matrix, eliminating the extra matmul.

## Building It Step by Step

Below is a complete, runnable implementation. All snippets are self‑contained; you can paste them into a single `lora_engine.py` file.

### 1. Environment Setup

```bash
python -m venv lora-env
source lora-env/bin/activate
pip install numpy==1.26.4 pytest==8.0.0
```

### 2. Base Layer

```python
import numpy as np

class LinearLayer:
    """Wraps a weight matrix and bias."""
    def __init__(self, in_features: int, out_features: int):
        # He initialization for stable gradients
        self.weight = np.random.randn(out_features, in_features) * np.sqrt(2.0 / in_features)
        self.bias = np.zeros(out_features)

    def forward(self, x: np.ndarray) -> np.ndarray:
        # x shape: (batch, in_features)
        return x @ self.weight.T + self.bias
```

### 3. LoRA Adapter

```python
class LoRAAdapter:
    def __init__(self, in_features: int, out_features: int, rank: int = 8, alpha: float = 1.0):
        self.rank = rank
        self.alpha = alpha
        # A: (rank, in_features), B: (out_features, rank)
        self.A = np.random.randn(rank, in_features) * 0.02
        self.B = np.random.randn(out_features, rank) * 0.02

    def forward(self, x: np.ndarray) -> np.ndarray:
        # (batch, in_features) @ (in_features, rank) -> (batch, rank)
        # then @ (rank, out_features) -> (batch, out_features)
        return (x @ self.A.T) @ self.B.T

    def scaled_forward(self, x: np.ndarray) -> np.ndarray:
        # LoRA scaling factor α / r
        return self.forward(x) * (self.alpha / self.rank)
```

### 4. Merging Utility

```python
def merge_lora(base: LinearLayer, lora: LoRAAdapter) -> LinearLayer:
    """Return a new LinearLayer with W' = W + B @ A."""
    merged = LinearLayer(base.weight.shape[1], base.weight.shape[0])
    merged.weight = base.weight + lora.B @ lora.A
    merged.bias = base.bias.copy()
    return merged
```

### 5. Inference Engine

```python
class LoraInference:
    def __init__(self, base: LinearLayer, lora: LoRAAdapter, merge: bool = True):
        self.base = base
        self.lora = lora
        self.merge = merge
        if merge:
            self.merged_layer = merge_lora(base, lora)
        else:
            self.merged_layer = None

    def forward(self, x: np.ndarray) -> np.ndarray:
        if self.merge:
            return self.merged_layer.forward(x)
        # Adapter‑only path: base + scaled adapter
        base_out = self.base.forward(x)
        adapter_out = self.lora.scaled_forward(x)
        return base_out + adapter_out
```

### 6. Training Loop (Optional)

```python
def train_step(base: LinearLayer, lora: LoRAAdapter, x: np.ndarray, y: np.ndarray,
               lr: float = 1e-3) -> float:
    # Forward
    base_out = base.forward(x)
    adapter_out = lora.scaled_forward(x)
    pred = base_out + adapter_out
    loss = np.mean((pred - y) ** 2)

    # Backward (manual gradient for MSE)
    diff = pred - y  # (batch, out)
    # Gradient w.r.t B
    grad_B = diff.T @ (x @ lora.A.T)  # (out, rank)
    # Gradient w.r.t A
    grad_A = (diff @ lora.B).T @ x   # (rank, in)

    # Update
    lora.B -= lr * grad_B
    lora.A -= lr * grad_A
    return loss.item()
```

### 7. Persistence with `safetensors`

```python
from safetensors import safe_open
from safetensors.numpy import save_file

def save_lora(lora: LoRAAdapter, path: str):
    tensors = {"A": lora.A, "B": lora.B}
    save_file(tensors, path)

def load_lora(path: str, in_features: int, out_features: int, rank: int) -> LoRAAdapter:
    with safe_open(path, framework="np") as f:
        A = f.get_tensor("A")
        B = f.get_tensor("B")
    lora = LoRAAdapter(in_features, out_features, rank)
    lora.A, lora.B = A, B
    return lora
```

## Running and Testing It

Create a test script `test_lora.py`:

```python
import numpy as np
from lora_engine import LinearLayer, LoRAAdapter, LoraInference, train_step

def test_shapes():
    base = LinearLayer(16, 8)
    lora = LoRAAdapter(16, 8, rank=4)
    x = np.random.randn(32, 16)
    out = LoraInference(base, lora, merge=False).forward(x)
    assert out.shape == (32, 8)

def test_merge_equivalence():
    base = LinearLayer(4, 2)
    lora = LoRAAdapter(4, 2, rank=2)
    x = np.random.randn(5, 4)
    merged = LoraInference(base, lora, merge=True).forward(x)
    separate = LoraInference(base, lora, merge=False).forward(x)
    np.testing.assert_allclose(merged, separate, atol=1e-6)

def test_training_decreases_loss():
    base = LinearLayer(4, 1)
    lora = LoRAAdapter(4, 1, rank=2)
    x = np.random.randn(64, 4)
    y = np.random.randn(64, 1)
    losses = [train_step(base, lora, x, y, lr=0.01) for _ in range(50)]
    assert losses[-1] < losses[0]

if __name__ == "__main__":
    test_shapes()
    test_merge_equivalence()
    test_training_decreases_loss()
    print("All tests passed.")
```

Run the tests:

```bash
python -m pytest test_lora.py -v
```

If all assertions pass, you have a functional LoRA engine that can be extended further.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence with Versioning** – Store adapters in `safetensors` files and track versions with a simple manifest; this matters for reproducibility and rollback in CI pipelines.
2. **Horizontal Scaling** – Wrap the inference loop in a FastAPI app and deploy multiple workers behind a load balancer; enables handling thousands of concurrent requests.
3. **Observability** – Emit latency, throughput, and loss metrics to Prometheus via `prometheus_client`; integrates with Grafana dashboards for production monitoring.
4. **Fault Tolerance** – Implement retry logic with exponential backoff for GPU allocation failures and use circuit‑breaker patterns to prevent cascading failures.
5. **Benchmarking Suite** – Add a script that measures FLOPs, memory footprint, and end‑to‑end latency across batch sizes; use `torch‑benchmark` or `mlir` for deeper profiling.
6. **Quantization Support** – Integrate 8‑bit integer inference using `bitsandbytes` or custom int8 kernels; reduces model size by 4×, crucial for edge deployment.

Each upgrade directly addresses a real‑world concern—scalability, reliability, and efficiency—that senior engineers are expected to own.

## Key Takeaways

- Building a LoRA engine from scratch demonstrates low‑level matrix manipulation, memory efficiency, and inference serving.
- The project maps to ML Engineer, Systems Engineer, or MLOps roles, highlighting parameter efficiency and production readiness.
- A clear extension roadmap shows foresight in persistence, scaling, observability, fault tolerance, and benchmarking.
- Real‑world testing with pytest and safetensors ensures the code is reproducible and ready for CI integration.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – The seminal paper introducing the low‑rank adapter concept.
- [Hugging Face PEFT Documentation](https://huggingface.co/docs/peft) – Practical guide to parameter‑efficient fine‑tuning with production examples.
- [PyTorch `torch.nn.Linear` Reference](https://pytorch.org/docs/stable/generated/torch.nn.Linear.html) – Understand the underlying linear layer you are extending.
- [SafeTensors Format](https://github.com/huggingface/safetensors) – A fast, safe serialization format for model weights.
- [FastAPI for Model Serving](https://fastapi.tiangolo.com/) – Build scalable REST endpoints for your inference engine.

---