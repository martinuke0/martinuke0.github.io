---
title: "Building a FlashAttention-Style Tiled Self-Attention Block in NumPy"
date: "2026-10-22T00:00:36.058"
draft: false
tags: ["machine-learning", "systems", "numpy", "transformers", "performance"]
description: "Implement a tiled self-attention block with numerically stable online softmax, KV caching, and memory/complexity benchmarks using pure NumPy."
summary: "This post walks through building a FlashAttention-style tiled self-attention block in NumPy, covering online softmax, KV caching, and performance benchmarks."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-22-building-a-flashattention-style-tiled-self-attention-block-in-numpy.svg"
  alt: "Illustration of a tiled self-attention block with KV cache"
  caption: ""
  relative: false
---

> **TL;DR** — You will implement a FlashAttention‑style tiled self‑attention block from scratch in NumPy, including a numerically stable online softmax and a KV cache. The project ships with benchmarks that quantify the memory and computational savings of tiling, giving you a concrete portfolio piece that signals real systems skill.

The rise of large transformer models has turned efficient attention from a research curiosity into a production requirement. While frameworks like PyTorch hide the underlying kernels, hiring managers often look for evidence that a candidate can reason about memory hierarchies, algorithmic stability, and I/O trade‑offs. In this guide you will build a self‑contained, NumPy‑only implementation that mirrors the key ideas of [FlashAttention](https://arxiv.org/abs/2205.14135) — tiling, online softmax, and KV caching — and then measure its complexity.

## Why This Project Stands Out on a CV

- **Low‑level algorithm design** – you write an online softmax that avoids materializing the full attention matrix, demonstrating numerical know‑how.
- **Memory engineering** – tiling and KV caching show you can control allocation patterns, a skill prized in systems‑oriented ML roles.
- **Performance benchmarking** – you produce concrete numbers (FLOPs, bytes, latency) that speak to scalability.
- **Cross‑framework portability** – the implementation is pure NumPy, proving you are not tied to a single deep‑learning stack.
- **Portfolio narrative** – the project can be extended to GPU kernels, distributed inference, or integration with [Hugging Face](https://huggingface.co) pipelines, illustrating a growth path.

These points map directly to job descriptions that ask for “experience with efficient attention mechanisms”, “profiling of memory‑bound workloads”, or “building custom ops for LLM inference”.

## Architecture Overview

The block is composed of five cooperating parts:

1. **Projection layer** – linear maps of input `X` into queries `Q`, keys `K`, and values `V`.
2. **Tiling engine** – splits the sequence length `L` into fixed‑size tiles `T` to keep intermediate tensors in cache.
3. **Online softmax** – computes the attention weights incrementally per tile, maintaining a running maximum and sum for numerical stability.
4. **KV cache** – stores past keys and values so that incremental decoding (autoregressive generation) can reuse them without recomputation.
5. **Benchmark harness** – measures FLOPs, memory footprint, and wall‑time for varying `L` and `T`.

A textual diagram of the data flow:

```
X ──► Linear ──► Q, K, V
            │
            ▼
      ┌─────────────┐
      │  Tiling     │
      │ (split L)   │
      └──────┬──────┘
             │
      ┌──────▼──────┐
      │ Online      │
      │ Softmax     │
      │ (per tile)  │
      └──────┬──────┘
             │
      ┌──────▼──────┐
      │ KV Cache    │
      │ (store K,V) │
      └──────┬──────┘
             │
      ┌──────▼──────┐
      │ Output      │
      │ (weighted V)│
      └─────────────┘
```

## Building It Step by Step

### Step 1 – Basic Scaled Dot‑Product Attention

Start with the textbook formula, then replace it with a tiled version.

```python
import numpy as np

def naive_attention(Q, K, V, scale=None):
    """
    Q: (L, d)
    K: (L, d)
    V: (L, d)
    Returns attention output (L, d)
    """
    if scale is None:
        scale = 1.0 / np.sqrt(Q.shape[-1])
    scores = Q @ K.T * scale          # (L, L)
    weights = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
    weights /= weights.sum(axis=-1, keepdims=True)
    return weights @ V
```

### Step 2 – Numerically Stable Online Softmax

The naive softmax materializes an `L×L` matrix, which is prohibitive for long sequences. The online variant processes one tile at a time while keeping a running maximum and sum.

```python
def online_softmax_tile(Q_tile, K_tile, scale):
    """
    Q_tile: (T, d)
    K_tile: (T, d)
    Returns:
        weights: (T, T) softmax matrix for this tile
        max_score: (T,) row‑wise maximum
        sum_exp: (T,) row‑wise sum of exponentials
    """
    scores = Q_tile @ K_tile.T * scale          # (T, T)
    max_score = np.max(scores, axis=-1)         # (T,)
    shifted = scores - max_score[:, None]
    exps = np.exp(shifted)
    sum_exp = np.sum(exps, axis=-1)             # (T,)
    weights = exps / sum_exp[:, None]
    return weights, max_score, sum_exp
```

### Step 3 – Tiled Attention with Online Softmax

Combine tiling with the online softmax to avoid ever forming the full `L×L` matrix.

```python
def tiled_attention(Q, K, V, tile_size=64):
    L, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    output = np.zeros_like(V)

    # Running statistics for each query row
    global_max = np.full(L, -np.inf)
    global_sum = np.zeros(L)

    for i in range(0, L, tile_size):
        i_end = min(i + tile_size, L)
        Q_tile = Q[i:i_end]                     # (T, d)

        for j in range(0, L, tile_size):
            j_end = min(j + tile_size, L)
            K_tile = K[j:j_end]                 # (T_k, d)
            V_tile = V[j:j_end]                 # (T_k, d)

            # Compute partial scores
            scores = Q_tile @ K_tile.T * scale   # (T_q, T_k)

            # Update global max
            tile_max = np.max(scores, axis=-1)   # (T_q,)
            new_max = np.maximum(global_max[i:i_end], tile_max)

            # Rescale previous sums
            old_scale = np.exp(global_max[i:i_end] - new_max)
            global_sum[i:i_end] *= old_scale

            # Add contribution of this tile
            shifted = scores - new_max[:, None]
            exps = np.exp(shifted)
            global_sum[i:i_end] += np.sum(exps, axis=-1)

            # Update global max for next iteration
            global_max[i:i_end] = new_max

            # Accumulate weighted values
            weights_tile = exps / global_sum[i:i_end, None]
            output[i:i_end] += weights_tile @ V_tile

    return output
```

### Step 4 – KV Cache for Autoregressive Decoding

During generation, each new token only needs to attend to all previous keys and values. Storing them avoids recomputing the whole attention.

```python
class KVCache:
    def __init__(self, max_len: int, d: int):
        self.max_len = max_len
        self.d = d
        self.K = np.zeros((max_len, d))
        self.V = np.zeros((max_len, d))
        self.cur_len = 0

    def update(self, k: np.ndarray, v: np.ndarray):
        """Append new key/value vectors."""
        seq_len = k.shape[0]
        if self.cur_len + seq_len > self.max_len:
            raise ValueError("Cache overflow")
        self.K[self.cur_len:self.cur_len + seq_len] = k
        self.V[self.cur_len:self.cur_len + seq_len] = v
        self.cur_len += seq_len

    def get(self):
        return self.K[:self.cur_len], self.V[:self.cur_len]
```

Usage during decoding:

```python
def decode_step(Q_new, kv_cache, scale):
    """
    Q_new: (1, d) – query for the new token
    """
    K_past, V_past = kv_cache.get()
    scores = Q_new @ K_past.T * scale
    weights = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
    weights /= weights.sum(axis=-1, keepdims=True)
    return weights @ V_past
```

### Step 5 – Memory and Complexity Benchmarks

Quantify the benefit of tiling and caching.

```python
import time

def benchmark(L, d, tile_size):
    rng = np.random.default_rng(0)
    Q = rng.standard_normal((L, d))
    K = rng.standard_normal((L, d))
    V = rng.standard_normal((L, d))

    # Warm‑up
    _ = tiled_attention(Q, K, V, tile_size)

    start = time.perf_counter()
    out = tiled_attention(Q, K, V, tile_size)
    elapsed = time.perf_counter() - start

    # FLOPs: 2 * L^2 * d (matmul) + O(L*d) for softmax
    flops = 2 * L**2 * d
    # Memory: Q,K,V each L*d, plus output L*d → 4*L*d bytes (float64)
    mem = 4 * L * d * 8

    return flops, mem, elapsed

# Example
flops, mem, sec = benchmark(L=1024, d=64, tile_size=64)
print(f"FLOPs: {flops:.2e}, Memory: {mem/1e6:.2f} MB, Time: {sec:.4f}s")
```

Running the benchmark across a sweep of `L` values produces curves that illustrate the `O(L²)` scaling of naive attention versus the `O(L·T)` behavior of the tiled version.

## Running and Testing It

1. **Save the code** in a file `tiled_attention.py`.
2. **Run the benchmark**:

```bash
python tiled_attention.py
```

3. **Validate correctness** against the naive implementation:

```python
def test_correctness():
    rng = np.random.default_rng(42)
    L, d = 128, 32
    Q = rng.standard_normal((L, d))
    K = rng.standard_normal((L, d))
    V = rng.standard_normal((L, d))

    naive = naive_attention(Q, K, V)
    tiled = tiled_attention(Q, K, V, tile_size=32)

    assert np.allclose(naive, tiled, atol=1e-5), "Outputs differ!"
    print("Correctness test passed.")

test_correctness()
```

If the assertion passes, the tiled kernel matches the reference within floating‑point tolerance.

## Extending It: Your Roadmap to Senior‑Level

1. **GPU acceleration with CuPy** – replace NumPy arrays with CuPy arrays to run on CUDA, illustrating knowledge of heterogeneous computing.
2. **Mixed‑precision training** – implement FP16/BF16 kernels and loss scaling, a requirement for large‑scale LLM training.
3. **Distributed KV cache** – shard the cache across multiple machines using [Ray](https://www.ray.io) or [Horovod](https://github.com/horovod/horovod), demonstrating scalability.
4. **Profiling integration** – hook into [TensorBoard](https://tensorboard.dev) or [Weights & Biases](https://wandb.ai) to log memory usage and step time, showing observability.
5. **Fault‑tolerant inference** – add checkpointing of the KV cache to disk (e.g., using [Joblib](https://joblib.readthedocs.io)) so that a crash can resume without recomputation.
6. **Custom Triton kernel** – rewrite the tiled loop in [Triton](https://github.com/openai/triton) to achieve performance closer to hand‑written CUDA, highlighting low‑level optimization skills.

Each upgrade addresses a real production concern: speed, reliability, or operational visibility.

## Key Takeaways

- **Tiling** reduces peak memory from `O(L²)` to `O(L·T)`, making long sequences feasible.
- **Online softmax** provides numerical stability without materializing the full weight matrix.
- **KV cache** enables efficient autoregressive decoding by reusing past keys and values.
- **Pure NumPy** implementation proves algorithmic understanding without relying on opaque libraries.
- **Benchmark suite** quantifies the trade‑off between compute and memory, a critical skill for systems roles.

## Further Reading

- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135) – the original paper that inspired the tiled approach.
- [NumPy User Guide – Broadcasting and Vectorization](https://numpy.org/doc/stable/user/basics.html) – foundational knowledge for efficient array operations.
- [PyTorch Scaled Dot‑Product Attention Documentation](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) – reference for the mathematical formulation.
- [Hugging Face Transformers – Model Optimization](https://huggingface.co/docs/transformers/perf_inference) – practical tips for deploying efficient attention in production.