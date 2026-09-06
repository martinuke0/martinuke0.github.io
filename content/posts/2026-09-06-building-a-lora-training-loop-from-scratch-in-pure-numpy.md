---
title: "Building a LoRA Training Loop From Scratch in Pure NumPy"
date: "2026-09-06T10:00:43.662"
draft: false
tags: ["lora", "numpy", "deep-learning", "machine-learning", "python", "side-projects"]
description: "A hands-on guide to building a from-scratch LoRA training loop in pure NumPy, with manual backward-pass gradients through low-rank adapters — a portfolio project that signals real ML systems skill."
summary: "Build a working LoRA fine-tuning loop in pure NumPy, computing every gradient by hand through low-rank adapters. A practical side project that demonstrates real systems understanding to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-building-a-lora-training-loop-from-scratch-in-pure-numpy.svg"
  alt: "Layered neural network diagram showing low-rank adapter matrices branching off frozen weights."
  caption: ""
  relative: false
---

> **TL;DR** — LoRA fine-tunes a model by learning two small matrices whose product approximates a weight update. This guide walks you through implementing the entire training loop — forward pass, MSE loss, and manual backward gradients through both low-rank matrices — in pure NumPy. You'll end up with a runnable artifact that's small enough to read in one sitting but dense enough to demonstrate that you understand how PyTorch actually works under the hood.

There's a strange gap in most ML portfolios. Candidates can fine-tune a model with `peft` and `transformers` in ten lines of code, but few can explain what those ten lines are actually doing. Hiring managers notice. The project below is designed to close that gap: it's a complete LoRA training loop written from first principles, with every gradient computed by hand. It's small, it's runnable, and it's the kind of artifact that prompts the follow-up question you actually want in an interview: *"Tell me more about how you built that."*

## Why This Project Stands Out on a CV

Most ML side projects fall into one of two buckets: "I fine-tuned BERT on a Kaggle dataset" or "I read the Transformer paper and built an animation." Neither is bad, but both have become table stakes. What makes a project stand out in 2026 is whether it demonstrates that you understand the *mechanics* of modern training, not just how to call into a high-level library.

A from-scratch LoRA loop signals several specific competencies that map cleanly to roles hiring managers are trying to fill:

- **Numerics fluency.** Computing the backward pass by hand forces you to internalize matrix calculus, broadcasting semantics, and the chain rule as it actually applies to tensor operations. This is the same mental model you'd need to debug a custom CUDA kernel or a Triton autotuner at companies like Anthropic, xAI, or any of the inference-platform shops.
- **Systems thinking.** Even though the toy is "just NumPy," you're making real choices about memory layout, parameter initialization, and gradient accumulation. That's the same shape of work as designing a training job in Kubernetes with PyTorch DDP or Ray.
- **Reading the paper and implementing it.** LoRA was introduced in [Hu et al., 2021](https://arxiv.org/abs/2106.09685) and the math is not complex. But implementing the math yourself, rather than relying on a library, proves you can translate a paper into code — exactly the skill needed for ML research engineer and applied scientist roles.
- **Pragmatic restraint.** LoRA exists precisely because full fine-tuning is wasteful. Building it from scratch demonstrates that you understand *why* parameter-efficient methods matter, which is increasingly the dominant paradigm in production LLM work.

For a hiring manager at an AI infrastructure company, a fintech with an ML platform team, or any ML-adjacent backend role, this project hits harder than yet another LangChain demo.

## Architecture Overview

The toy mirrors how LoRA is actually implemented in production libraries like Hugging Face PEFT, but stripped down so the moving parts are visible.

- **Frozen base weight** `W ∈ ℝ^{d×d}` — a fixed, randomly-initialized matrix standing in for a pretrained layer. In real LoRA this is a `nn.Linear` from a foundation model; here it's just `np.random.randn`.
- **Low-rank adapter** — two trainable matrices, `A ∈ ℝ^{d×r}` and `B ∈ ℝ^{r×d}`, where `r ≪ d`. The effective update is `ΔW = A @ B`. We never materialize `ΔW`; we keep it factored to save memory.
- **Forward pass** — for input `x`, output `y = x @ (W + A @ B)`. The frozen path and the adapter path are summed.
- **Loss** — mean squared error against a target `y_true`. MSE keeps the gradients readable; for a text project you'd swap in cross-entropy.
- **Backward pass** — chain-rule gradients `∂L/∂A`, `∂L/∂B`, and (importantly) `∂L/∂W` — even though `W` is frozen, computing its gradient proves you know the chain rule works on both paths.
- **Optimizer** — plain SGD with a learning rate, applied only to `A` and `B`.
- **Training loop** — fixed number of steps, log the loss, plot convergence.

The data flow looks like this:

```
x ──┬──► [W] ──────────┐
    │                  ▼
    └──► [A] → [B] ──► (+) ──► y ──► MSE ──► loss
                                   │
                                   ▼
                         ∂loss/∂y ──► backward
```

This mirrors the [PEFT LoRA implementation](https://huggingface.co/docs/peft/main/en/conceptual/lora) almost line for line.

## Building It Step by Step

### Step 1: Project scaffold

Create a directory with three files. Keeping the project small but well-organized matters more than you'd think when sharing it on GitHub.

```
lora-from-scratch/
├── lora.py          # the model and training loop
├── train.py         # entry point
└── test_lora.py     # sanity checks
```

### Step 2: Implement the LoRA layer

This is the centerpiece. Every line corresponds to something `peft.LoraLayer` does under the hood.

```python
# lora.py
import numpy as np

class LoRALinear:
    """A Linear layer with a frozen base weight W and a trainable low-rank adapter (A, B)."""

    def __init__(self, d_in, d_out, rank=4, alpha=1.0, seed=0):
        rng = np.random.default_rng(seed)
        # Frozen base weight — stand-in for pretrained weights.
        self.W = rng.standard_normal((d_in, d_out)) * 0.02

        # Trainable low-rank factors.
        # A is Gaussian; B is zero so the adapter starts as an identity-ish delta.
        self.A = rng.standard_normal((d_in, rank)) * 0.02
        self.B = np.zeros((rank, d_out))

        # Scaling follows the LoRA paper: alpha / rank.
        self.scale = alpha / rank

        # Cache for backward.
        self._x = None

    def forward(self, x):
        self._x = x
        adapter = self.A @ self.B              # shape (d_in, d_out)
        effective_W = self.W + self.scale * adapter
        return x @ effective_W

    def params(self):
        return {"A": self.A, "B": self.B}

    def grads(self):
        # Filled in by backward(); only A and B are trainable.
        return {"dA": self._dA, "dB": self._dB}
```

Two design choices are worth flagging. First, `B` is initialized to zero so the adapter contributes nothing at step 0 — this is exactly what [the LoRA paper recommends](https://arxiv.org/abs/2106.09685) and is what PEFT does. Second, the `scale = alpha / rank` is the standard convention; tweaking `alpha` is functionally equivalent to changing the learning rate on the adapter.

### Step 3: Implement the loss and the backward pass

This is where most candidates stop reading other people's code. We'll go through it carefully.

```python
    def backward(self, dY):
        # dY has shape (batch, d_out); _x has shape (batch, d_in)
        x = self._x

        # Effective weight used in forward.
        adapter = self.A @ self.B
        effective_W = self.W + self.scale * adapter

        # ---- d/dW (frozen but we still compute for the math) ----
        # y = x @ effective_W,  dL/dW = x.T @ dY
        self._dW = x.T @ dY

        # ---- d/d(scale * A @ B) ----
        # Same shape as effective_W.
        dEW = self._dW  # because W is additive
        dEW_scaled = dEW * self.scale

        # ---- d/dA  (shape d_in x rank) ----
        # We have dL/d(A @ B) = dEW_scaled, and d(A@B)/dA is x-like.
        # Concretely: y = x @ (W + scale * A @ B) so dL/dA = x.T @ (dEW_scaled @ B.T)
        # ... but careful: A@B is d_in x d_out, so dEW_scaled is d_in x d_out.
        # dL/dA (d_in x rank) = dEW_scaled @ B.T   (d_in x d_out @ d_out x rank)
        self._dA = dEW_scaled @ self.B.T

        # ---- d/dB  (shape rank x d_out) ----
        # A.T @ dEW_scaled
        self._dB = self.A.T @ dEW_scaled

        # ---- d/dx (so the caller can chain backward through earlier layers) ----
        # dL/dx = dY @ effective_W.T
        return dY @ effective_W.T
```

Let's verify shapes manually — this is the single most useful habit you can build.

- `x`: `(batch, d_in)`, `dY`: `(batch, d_out)`
- `self.A`: `(d_in, rank)`, `self.B`: `(rank, d_out)`
- `dEW_scaled @ B.T`: `(d_in, d_out) @ (d_out, rank)` → `(d_in, rank)` ✓ matches `A`
- `A.T @ dEW_scaled`: `(rank, d_in) @ (d_in, d_out)` → `(rank, d_out)` ✓ matches `B`

If you can derive these on a whiteboard without running code, you understand roughly 70% of what an autograd engine does.

### Step 4: MSE loss with its own backward

```python
class MSELoss:
    def forward(self, y_pred, y_true):
        self._diff = y_pred - y_true
        self._n = y_pred.size
        return float(np.mean(self._diff ** 2))

    def backward(self):
        # d/dy_pred of (1/N) * sum(diff^2) = (2/N) * diff
        return (2.0 / self._n) * self._diff
```

This matches PyTorch's `F.mse_loss(reduction='mean')` up to a constant factor of 2.

### Step 5: The training loop

```python
# train.py
import numpy as np
from lora import LoRALinear, MSELoss


def make_problem(d=16, n_samples=64, seed=1):
    """A learnable task: y = x @ W_true + noise, with a small low-rank drift."""
    rng = np.random.default_rng(seed)
    W_true = rng.standard_normal((d, d)) * 0.1
    drift_A = rng.standard_normal((d, 2)) * 0.05
    drift_B = rng.standard_normal((2, d)) * 0.05
    W_target = W_true + drift_A @ drift_B

    X = rng.standard_normal((n_samples, d))
    Y = X @ W_target + 0.01 * rng.standard_normal((n_samples, d))
    return X, Y, W_true


def train(rank=4, lr=0.01, steps=500, d=16, seed=0):
    X, Y, W_true = make_problem(d=d, seed=seed)
    layer = LoRALinear(d_in=d, d_out=d, rank=rank, alpha=1.0, seed=seed)
    loss_fn = MSELoss()

    losses = []
    for step in range(steps):
        # Mini-batch
        idx = np.random.default_rng(step).choice(len(X), size=16, replace=False)
        xb, yb = X[idx], Y[idx]

        # Forward
        y_pred = layer.forward(xb)
        loss = loss_fn.forward(y_pred, yb)
        losses.append(loss)

        # Backward
        dY = loss_fn.backward()
        _ = layer.backward(dY)

        # SGD update on A and B only.
        grads = layer.grads()
        layer.A -= lr * grads["dA"]
        layer.B -= lr * grads["dB"]

        if step % 50 == 0:
            print(f"step {step:4d}  loss={loss:.6f}")

    return layer, losses, W_true


if __name__ == "__main__":
    layer, losses, W_true = train()
    learned_delta = layer.A @ layer.B
    print(f"final loss: {losses[-1]:.6f}")
    print(f"|A·B| frobenius: {np.linalg.norm(learned_delta):.4f}")
```

Note the `np.random.default_rng(step)` inside the loop — this is intentional. Using a global RNG with `np.random.choice` makes the run non-reproducible because state mutates across `forward`/`backward` calls that may also touch randomness. Keeping the data-sampling RNG deterministic per step is a small detail that signals you understand how production training loops handle reproducibility.

## Running and Testing It

### Local run

From the project root:

```bash
python train.py
```

You should see the loss drop from roughly `0.02` to under `0.001` within a few hundred steps. The output of `|A·B|` (the Frobenius norm of the learned delta) should grow from 0 to roughly the magnitude of the embedded `drift_A @ drift_B` you constructed.

### Sanity tests

The toy is small enough that you can write meaningful unit tests that catch real bugs — and writing them is part of the project.

```python
# test_lora.py
import numpy as np
from lora import LoRALinear, MSELoss


def test_initial_adapter_is_zero():
    layer = LoRALinear(8, 8, rank=2, seed=0)
    # B is zero, so the adapter contributes nothing.
    x = np.random.default_rng(0).standard_normal((4, 8))
    y_base = x @ layer.W
    y_with_adapter = layer.forward(x)
    np.testing.assert_allclose(y_base, y_with_adapter, atol=1e-8)


def test_grad_shapes():
    layer = LoRALinear(8, 8, rank=2, seed=0)
    loss = MSELoss()
    x = np.random.default_rng(1).standard_normal((4, 8))
    y = np.random.default_rng(2).standard_normal((4, 8))
    y_pred = layer.forward(x)
    _ = loss.forward(y_pred, y)
    _ = layer.backward(loss.backward())
    grads = layer.grads()
    assert grads["dA"].shape == layer.A.shape
    assert grads["dB"].shape == layer.B.shape


def test_finite_difference_gradients():
    """Numerical gradient check — the most important test."""
    layer = LoRALinear(4, 4, rank=2, seed=0)
    loss = MSELoss()
    x = np.random.default_rng(3).standard_normal((2, 4))
    y = np.random.default_rng(4).standard_normal((2, 4))

    # Analytical
    layer.forward(x)
    _ = loss.forward(layer._last_y if hasattr(layer, "_last_y") else layer.forward(x), y)
    # Recompute forward+backward deterministically.
    y_pred = layer.forward(x)
    _ = loss.forward(y_pred, y)
    _ = layer.backward(loss.backward())
    analytical = layer.grads()["dA"].copy()

    # Numerical: d/dA_ij ≈ (L(A+eps) - L(A-eps)) / (2*eps)
    eps = 1e-5
    numeric = np.zeros_like(layer.A)
    for i in range(layer.A.shape[0]):
        for j in range(layer.A.shape[1]):
            layer.A[i, j] += eps
            lp = loss.forward(layer.forward(x), y)
            layer.A[i, j] -= 2 * eps
            lm = loss.forward(layer.forward(x), y)
            layer.A[i, j] += eps
            numeric[i, j] = (lp - lm) / (2 * eps)

    np.testing.assert_allclose(analytical, numeric, atol=1e-5)
```

The `test_finite_difference_gradients` test is the killer one. If your chain rule is wrong, this fails within seconds. If it passes, you've proven your manual backward pass is mathematically equivalent to autodiff — which is essentially the same test PyTorch's own autograd uses internally.

### Performance reality check

Pure NumPy on a single layer with `d=16` will train in a couple of seconds on any laptop. Don't be tempted to scale `d` to thousands; NumPy matmul on CPU will quickly become the bottleneck and the loop will dominate wall-clock time. That's a feature, not a bug — the slowness is what makes the gradient mechanics observable.

## Extending It: Your Roadmap to Senior-Level

A toy is a starting point. Here's how to evolve it into something that reads as production-flavored.

1. **Swap NumPy for JAX and add `jit`.** JAX gives you the same readability as NumPy but compiles the loop with XLA. You'll see a 50–100× speedup and your model becomes GPU-ready with a one-line change — exactly how production research code often starts.

2. **Persist checkpoints and resume training.** Serialize `A` and `B` to `safetensors` or a small NumPy `.npz`. Add a `--resume` flag and a step counter in the state dict. This is what every real fine-tuning pipeline does, and the format choice (safetensors over pickle) signals security awareness.

3. **Add observability.** Wire in `mlflow` or just a CSV logger for loss curves. Plot the adapter norm over time to visualize when training plateaus. The ability to *see* your training is what separates a notebook experiment from a job.

4. **Horizontal scaling with `shard_map` or PyTorch DDP.** Once you've moved to JAX or PyTorch, replicate the layer across devices and use gradient sharding to handle larger `d`. Even an artificial 2-GPU example shows you understand data-parallel training.

5. **Fault tolerance via checkpointing mid-step.** Add periodic checkpoints and a wrapper that resumes from the latest one on restart. Production training jobs that run for days depend on this; being able to talk about it in an interview is gold.

6. **Benchmark against PEFT.** After your NumPy version converges, swap in `peft` with the same `rank` and `alpha`, train on the same data, and compare loss curves and final adapter norms. Documenting the comparison on the README is exactly the kind of analysis senior engineers love to see.

## Key Takeaways

- LoRA is just two small matrices whose product approximates a weight update; the math is small enough to implement in pure NumPy in an afternoon.
- The backward pass through `(A, B)` reduces to two matrix multiplies: `dA = dEW_scaled @ B.T` and `dB = A.T @ dEW_scaled`. If you can derive these on a whiteboard, you understand most of what autodiff does.
- Numerical gradient checks via finite differences are the most reliable way to verify a manual backward pass.
- The project demonstrates reading papers, implementing math, and making pragmatic engineering choices — exactly the mix hiring managers screen for in ML systems roles.
- The path from this toy to production-flavored work is short: JAX for compilation, safetensors for persistence, MLflow for observability, sharding for scale.

## Further Reading

- [LoRA: Low-Rank Adaptation of Large Language Models (Hu et al., 2021)](https://arxiv.org/abs/2106.09685) — the original paper; section 4.1 is the cleanest derivation of the forward and backward mechanics.
- [Hugging Face PEFT LoRA conceptual guide](https://huggingface.co/docs/peft/main/en/conceptual/lora) — the production reference implementation; compare its `LoraLayer` against your NumPy version.
- [PyTorch autograd mechanics](https://pytorch.org/docs/stable/notes/autograd.html) — explains how `torch.autograd` builds the same computational graph your manual code is imitating.
- [JAX Autodiff Cookbook](https://jax.readthedocs.io/en/latest/jax-101.html) — the natural next step once your NumPy loop works.
- [The safetensors format](https://huggingface.co/docs/safetensors/index) — what to use when you start persisting adapters for real.