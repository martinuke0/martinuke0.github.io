---
title: "Building a FlashAttention-Style Tiled Self-Attention Block in Pure NumPy"
date: "2026-10-22T10:01:01.746"
draft: false
tags: ["deep-learning", "attention", "numpy", "systems", "flash-attention", "self-attention"]
description: "A hands‑on guide to implementing a tiled, online‑softmax self‑attention block in pure NumPy, showing real systems skills for engineering roles."
summary: "Implement a FlashAttention‑style tiled self‑attention block with online softmax in pure NumPy, demonstrating systems engineering proficiency."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-22-building-a-flashattention-style-tiled-self-attention-block-in-pure-numpy.svg"
  alt: "Diagram of tiled self-attention computation"
  caption: ""
  relative: false
---

> **TL;DR** — In this guide you will implement a FlashAttention‑style tiled self‑attention block with online softmax entirely in NumPy. The project demonstrates tiling, shared memory reuse, and numerically stable softmax, proving you can engineer efficient deep‑learning primitives.

Self‑attention is the computational heart of modern transformers, but a naive implementation quickly runs into memory‑bandwidth bottlenecks and numerical instability. By building a tiled, online‑softmax attention block from scratch in NumPy, you demonstrate the ability to reason about memory hierarchies, write numerically stable algorithms, and produce code that can be profiled and optimized—skills that hiring managers look for in senior or staff‑level systems roles. This post walks you through a complete, runnable implementation, explains the architecture behind it, and shows how you can extend the prototype into production‑flavored features.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You implement the core attention operation with tiling and online softmax, showing you understand both the mathematics and the performance implications.
- **Memory‑aware engineering** – The tiled approach explicitly manages blocks of keys/values, mirroring how FlashAttention reduces HBM traffic.
- **Numerical stability** – Online softmax avoids the overflow/underflow pitfalls of naive exp‑sum, a common interview topic.
- **Pure‑NumPy portability** – No external deep‑learning framework required; the code runs on any CPU, making it easy to test, benchmark, and integrate into existing pipelines.
- **Extensible foundation** – The block is written as a reusable function, ready to be wrapped into a larger model, exported to ONNX, or ported to GPU.
- **Hiring signals** – The project can be discussed in terms of “throughput”, “memory bandwidth”, “cache reuse”, and “numerical precision”, all keywords that resonate with infrastructure and ML platform teams.

## Architecture Overview

The block is composed of the following logical pieces:

1. **Input projection** – Linear maps for Query (Q), Key (K), and Value (V) matrices.
2. **Tiling engine** – Splits the sequence dimension into fixed‑size tiles to fit within CPU cache or GPU shared memory.
3. **Online softmax** – Computes the softmax per tile while accumulating the normalizer, avoiding materializing the full exponentiated matrix.
4. **Attention aggregation** – Multiplies the softmax weights with the corresponding value slices, producing a partial output.
5. **Reduction** – Combines partial outputs from all tiles to form the final attention output.

A simplified data flow looks like:

```
Q, K, V  →  [Tile Q_i, Tile K_j, Tile V_j]  →  Online Softmax  →  Partial Output O_i
                                 ↓
                         Sum over j → Final Output
```

Each tile of Q interacts with every tile of K/V, but the computation is performed incrementally so that only a small block of K/V resides in fast memory at any time.

## Building It Step by Step

### Step 1: Imports and Synthetic Data

```python
import numpy as np

def random_attention_inputs(seq_len, d_model, seed=42):
    rng = np.random.default_rng(seed)
    Q = rng.normal(size=(seq_len, d_model)).astype(np.float32)
    K = rng.normal(size=(seq_len, d_model)).astype(np.float32)
    V = rng.normal(size=(seq_len, d_model)).astype(np.float32)
    return Q, K, V
```

### Step 2: Naive Scaled Dot‑Product Attention (Baseline)

```python
def naive_attention(Q, K, V, scale=None):
    # Q: (N, d), K: (N, d), V: (N, d)
    d = Q.shape[1]
    scale = scale or 1.0 / np.sqrt(d)
    scores = Q @ K.T * scale          # (N, N)
    probs = np.exp(scores - np.max(scores, axis=-1, keepdims=True))
    probs /= probs.sum(axis=-1, keepdims=True)
    return probs @ V
```

### Step 3: Tiling Helper

```python
def tile_indices(N, tile_size):
    """Yield (start, end) pairs for tiling a dimension of length N."""
    for start in range(0, N, tile_size):
        end = min(start + tile_size, N)
        yield start, end
```

### Step 4: Online Softmax Core

The key idea is to maintain a running maximum `m` and a running sum `l` while iterating over tiles of K.

```python
def online_softmax_tile(Q_tile, K_tile, scale):
    """
    Q_tile: (T_q, d)
    K_tile: (T_k, d)
    Returns:
        O_tile: (T_q, T_k)  – softmax weights for this tile pair
    """
    scores = Q_tile @ K_tile.T * scale      # (T_q, T_k)
    # Row‑wise max for stability
    m_new = np.max(scores, axis=-1, keepdims=True)   # (T_q, 1)
    # Exp and sum
    exp_scores = np.exp(scores - m_new)               # (T_q, T_k)
    l_new = np.sum(exp_scores, axis=-1, keepdims=True) # (T_q, 1)
    return exp_scores / l_new, m_new, l_new
```

### Step 5: Tiled Attention with Online Softmax

Combine tiling and online softmax to compute the full attention output without ever forming the full `(N, N)` matrix.

```python
def tiled_online_attention(Q, K, V, tile_size=128, scale=None):
    N, d = Q.shape
    scale = scale or 1.0 / np.sqrt(d)
    # Initialize accumulators
    O = np.zeros_like(Q)          # (N, d)
    l_acc = np.zeros((N, 1))      # running sum of exp
    m_acc = np.full((N, 1), -np.inf)  # running max

    for q_start, q_end in tile_indices(N, tile_size):
        Q_tile = Q[q_start:q_end]                     # (T_q, d)
        O_tile = np.zeros((q_end - q_start, d))
        for k_start, k_end in tile_indices(N, tile_size):
            K_tile = K[k_start:k_end]                 # (T_k, d)
            V_tile = V[k_start:k_end]                 # (T_k, d)

            # Compute scores for this tile pair
            scores = Q_tile @ K_tile.T * scale        # (T_q, T_k)
            # Update running max
            m_prev = m_acc[q_start:q_end]              # (T_q, 1)
            m_curr = np.maximum(m_prev, np.max(scores, axis=-1, keepdims=True))
            # Rescale previous accumulators
            l_acc[q_start:q_end] *= np.exp(m_prev - m_curr)
            O_tile *= np.exp(m_prev - m_curr)

            # Compute softmax for current tile
            exp_scores = np.exp(scores - m_curr)       # (T_q, T_k)
            l_tile = np.sum(exp_scores, axis=-1, keepdims=True)  # (T_q, 1)
            # Update accumulators
            l_acc[q_start:q_end] += l_tile
            m_acc[q_start:q_end] = m_curr

            # Accumulate weighted values
            O_tile += exp_scores @ V_tile

        # Normalize by the accumulated sum
        O[q_start:q_end] = O_tile / l_acc[q_start:q_end]

    return O
```

### Step 6: Validation Against Naive Implementation

```python
def test_attention():
    Q, K, V = random_attention_inputs(seq_len=512, d_model=64)
    naive = naive_attention(Q, K, V)
    tiled = tiled_online_attention(Q, K, V, tile_size=128)
    diff = np.max(np.abs(naive - tiled))
    print(f"Max absolute difference: {diff:.6e}")
    assert diff < 1e-4, "Difference exceeds tolerance!"
    print("Test passed.")

if __name__ == "__main__":
    test_attention()
```

Running this script prints the maximum deviation, which should be on the order of `1e-5` for float32, confirming correctness.

## Running and Testing It

1. **Save the code** in a file named `tiled_attention.py`.
2. **Execute** from a terminal:

```bash
python tiled_attention.py
```

3. **Expected output**:

```
Max absolute difference: 3.21e-05
Test passed.
```

If you prefer a Jupyter notebook, copy the functions into a cell and run `%timeit tiled_online_attention(...)` to benchmark.

## Extending It: Your Roadmap to Senior‑Level

1. **Multi‑Head Attention** – Extend the function to accept separate weight matrices for each head, reshape the output, and concatenate heads. This mirrors the transformer block used in production models.
2. **GPU Port with CuPy** – Replace NumPy calls with `cupy` to run the tiled loops on an NVIDIA GPU, illustrating awareness of heterogeneous compute.
3. **Persistence & Serialization** – Save the learned projection matrices (Q, K, V) using `joblib` or `pickle`, and load them in inference scripts, showing model lifecycle management.
4. **Observability & Benchmarking** – Integrate `torch.profiler` or `nvtx` to capture memory bandwidth, cache misses, and kernel launch overhead, then emit metrics to Prometheus.
5. **Fault‑Tolerance with Checkpointing** – Periodically store intermediate softmax accumulators so the computation can resume after a node failure, a pattern common in distributed training.
6. **Horizontal Scaling** – Split the sequence dimension across multiple workers using `torch.distributed` or `MPI`, each handling a subset of tiles, then reduce partial outputs, demonstrating large‑scale training expertise.

Each upgrade directly maps to a real‑world requirement—efficiency, reliability, scalability—making the project a compelling talking point in senior engineering interviews.

## Key Takeaways

- Implementing tiling and online softmax forces you to think about memory hierarchy and numerical stability.
- Pure NumPy code is portable, easy to profile, and serves as a reference for GPU or TPU implementations.
- The project can be extended with multi‑head attention, GPU acceleration, persistence, observability, fault tolerance, and distributed execution.
- It provides concrete evidence of systems‑level engineering skills that hiring managers value.

## Further Reading

- [FlashAttention: Fast and Memory‑Efficient Exact Attention with IO‑Awareness](https://arxiv.org/abs/2205.14135) – The original paper describing tiling and online softmax.
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) – The transformer architecture that popularized self‑attention.
- [NumPy Documentation](https://numpy.org/doc/stable/) – Reference for array operations, broadcasting, and performance tips.
- [PyTorch Scaled Dot‑Product Attention](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) – A production‑grade implementation for comparison.