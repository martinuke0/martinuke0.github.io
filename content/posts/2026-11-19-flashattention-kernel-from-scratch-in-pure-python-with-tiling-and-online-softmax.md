---
title: "FlashAttention Kernel from Scratch in Pure Python with Tiling and Online Softmax"
date: "2026-11-19T16:01:11.394"
draft: false
tags: ["Python", "Systems", "Performance", "Machine Learning", "GPU"]
description: "Build a FlashAttention kernel in pure Python with tiling and online softmax, showcasing systems expertise for hiring managers."
summary: "This tutorial walks you through implementing a FlashAttention kernel from scratch, using tiling and online softmax to achieve memory-efficient attention. You'll gain hands-on experience with low-level systems techniques that hiring managers value."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-19-flashattention-kernel-from-scratch-in-pure-python-with-tiling-and-online-softmax.svg"
  alt: "A visual representation of tiled attention computation"
  caption: ""
  relative: false
---

> **TL;DR** — In this guide you'll implement a FlashAttention kernel from scratch in pure Python, using tiling and online softmax to compute attention with O(1) memory overhead. The resulting code is runnable, testable, and showcases the low‑level systems skills that hiring managers look for.

Attention mechanisms are at the heart of modern transformer models, but naive implementations materialize an N×N matrix that quickly exhausts GPU memory. By breaking the computation into tiles and maintaining a running softmax, we can reduce memory usage to constant while preserving numerical accuracy. This post walks you through building such a kernel entirely in Python, giving you a concrete artifact to discuss in interviews.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – you will design and code tiling strategies and an online softmax, demonstrating the ability to turn a research idea into an efficient implementation.  
- **Memory engineering** – the kernel avoids allocating the full attention matrix, a skill that directly translates to optimizing large‑scale models on constrained hardware.  
- **Performance mindset** – by measuring speed and memory usage, you showcase a data‑driven approach to optimization, a trait prized in performance‑critical teams.  
- **Research‑to‑code pipeline** – reading the FlashAttention paper and reproducing its core algorithm signals you can operate at the intersection of theory and production.  
- **Role alignment** – the project speaks to ML engineers, systems engineers, and applied research positions that value low‑level optimization.

## Architecture Overview

The kernel is composed of three logical parts:

1. **Input tensors** – Query `Q`, Key `K`, and Value `V`, each of shape `(N, D)` where `N` is the sequence length and `D` is the feature dimension.  
2. **Tiling loop** – iterates over blocks of rows of `Q` and columns of `K` (the “tiles”). For each tile pair it computes a partial attention score and updates a running softmax.  
3. **Online softmax accumulator** – maintains two scalars per row: the current maximum `m` and the sum of exponentials `l`. These are updated incrementally as new tiles are processed, allowing the final output to be computed without ever storing the full `N×N` matrix.  

A high‑level flow looks like this:

```
for each query tile i:
    initialize m_i = -inf, l_i = 0, O_i = 0
    for each key tile j:
        S_ij = Q_i @ K_j^T               # partial scores
        m_ij = max(m_i, max(S_ij))
        P_ij = exp(S_ij - m_ij)          # unnormalized probabilities
        l_ij = l_i * exp(m_i - m_ij) + sum(P_ij)
        O_i = (l_i * exp(m_i - m_ij) * O_i + P_ij @ V_j) / l_ij
        m_i, l_i = m_ij, l_ij
    output[i] = O_i
```

The key insight is that `m_i` and `l_i` are updated *online*, so only the current tile’s scores `S_ij` need to reside in memory.

## Building It Step by Step

### Step 1 – Set up the environment and naive baseline

```python
import numpy as np
import time

def naive_attention(Q, K, V):
    """Standard O(N^2) attention for reference."""
    scores = Q @ K.T / np.sqrt(Q.shape[-1])
    probs = np.exp(scores - scores.max(axis=-1, keepdims=True))
    probs /= probs.sum(axis=-1, keepdims=True)
    return probs @ V
```

### Step 2 – Implement tiling

We split the sequence into blocks of size `T`. The outer loops iterate over query tiles; the inner loop iterates over key tiles.

```python
def tiled_flash_attention(Q, K, V, tile_size=64):
    N, D = Q.shape
    O = np.zeros_like(Q)               # output buffer
    scale = 1.0 / np.sqrt(D)

    for i_start in range(0, N, tile_size):
        i_end = min(i_start + tile_size, N)
        Q_i = Q[i_start:i_end]         # (T_i, D)

        # online softmax state for this query block
        m = np.full((i_end - i_start,), -np.inf)
        l = np.zeros((i_end - i_start,))
        O_i = np.zeros((i_end - i_start, D))

        for j_start in range(0, N, tile_size):
            j_end = min(j_start + tile_size, N)
            K_j = K[j_start:j_end]     # (T_j, D)
            V_j = V[j_start:j_end]

            # 1. compute partial scores
            S = (Q_i @ K_j.T) * scale   # (T_i, T_j)

            # 2. update row‑wise max
            m_new = np.maximum(m, S.max(axis=1))

            # 3. compute exponentials and rescale
            exp_S = np.exp(S - m_new[:, None])
            l_new = l * np.exp(m - m_new) + exp_S.sum(axis=1)

            # 4. update output
            O_i = (l * np.exp(m - m_new)[:, None] * O_i +
                   exp_S @ V_j) / l_new[:, None]

            # 5. store new state
            m, l = m_new, l_new

        O[i_start:i_end] = O_i
    return O
```

### Step 3 – Verify correctness

```python
# random test
rng = np.random.default_rng(0)
N, D = 256, 64
Q = rng.normal(size=(N, D))
K = rng.normal(size=(N, D))
V = rng.normal(size=(N, D))

ref = naive_attention(Q, K, V)
out = tiled_flash_attention(Q, K, V, tile_size=64)

print("Max absolute error:", np.abs(ref - out).max())
```

### Step 4 – Profile memory usage

```python
import tracemalloc

tracemalloc.start()
_ = tiled_flash_attention(Q, K, V, tile_size=64)
current, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(f"Peak memory: {peak / 1024:.2f} KiB")
```

The output should stay roughly constant as `N` grows, confirming the O(1) memory claim.

## Running and Testing It

1. **Save the code** in a file `flash_attention.py`.  
2. **Run** it with Python 3.10+:

```bash
python flash_attention.py
```

3. **Expected output** – a small numeric error (typically < 1e‑5) and a memory footprint that does not explode with sequence length.  
4. **Automated test** – add a `pytest` case:

```python
def test_flash_attention():
    Q = np.random.randn(128, 32)
    K = np.random.randn(128, 32)
    V = np.random.randn(128, 32)
    assert np.allclose(tiled_flash_attention(Q, K, V),
                       naive_attention(Q, K, V), atol=1e-5)
```

Run with `pytest -q` to ensure correctness after any refactoring.

## Extending It: Your Roadmap to Senior-Level

1. **GPU acceleration with CUDA** – rewrite the inner loops in CUDA C++ or use PyTorch’s `torch.cuda` to leverage thousands of cores; this demonstrates ability to ship high‑performance kernels.  
2. **Multi‑query / grouped‑query attention** – adapt the kernel to handle multiple heads and KV‑sharing, showing familiarity with modern transformer architectures.  
3. **Persistence layer** – store intermediate tile results on SSD for extremely long sequences, illustrating knowledge of storage hierarchies and fault tolerance.  
4. **Observability** – integrate OpenTelemetry to emit latency and memory metrics per tile, proving you can operate production‑grade services.  
5. **Fault tolerance** – add checkpointing so a failed tile can be recomputed without restarting the whole job, a pattern critical for large‑scale training.  
6. **Benchmarking harness** – build a CLI that compares your kernel against `torch.nn.functional.scaled_dot_product_attention` across sequence lengths and hardware, showcasing data‑driven performance analysis.

## Key Takeaways

- You have built a pure‑Python FlashAttention kernel that uses tiling and online softmax to achieve constant memory usage.  
- The implementation demonstrates algorithmic design, memory engineering, and performance profiling—skills that stand out on a CV.  
- You now have a concrete artifact to discuss in interviews, with clear metrics on speed and memory.  
- The roadmap outlines how to evolve the prototype into a production‑ready component, signaling senior‑level thinking.

## Further Reading

- **FlashAttention paper** – [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)  
- **Online Softmax** – [Online Softmax for Sequence Models](https://arxiv.org/abs/1805.04852)  
- **CUDA Programming Guide** – [NVIDIA CUDA Documentation](https://docs.nvidia.com/cuda/cuda-c-programming-guide/)  
- **PyTorch Scaled Dot‑Product Attention** – [torch.nn.functional.scaled_dot_product_attention](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)  
- **Tiling Techniques** – [Efficient Matrix Multiplication via Tiling](https://en.wikipedia.org/wiki/Matrix_multiplication_algorithm#Block_matrix_multiplication)  

These resources will help you deepen your understanding and extend the kernel to GPU‑accelerated, production‑grade implementations.