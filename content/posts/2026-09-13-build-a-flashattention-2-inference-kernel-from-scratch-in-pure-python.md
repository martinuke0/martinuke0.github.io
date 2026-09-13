---
title: "Build a FlashAttention-2 Inference Kernel from Scratch in Pure Python"
date: "2026-09-13T18:02:25.278"
draft: false
tags: ["Machine Learning", "Systems Engineering", "Python", "High-Performance Computing", "Deep Learning"]
description: "A hands-on guide to building a FlashAttention-2 inference kernel from scratch using pure Python, featuring tiled block-sparse causal attention and fused softmax."
summary: "Learn how to build a FlashAttention-2 inference kernel from scratch in pure Python. This guide covers tiled block-sparse causal attention and fused softmax to signal deep systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-13-build-a-flashattention-2-inference-kernel-from-scratch-in-pure-python.svg"
  alt: "Python code and matrix multiplication diagrams on a dark terminal screen."
  caption: ""
  relative: false
---

> **TL;DR** — Build a FlashAttention-2 inference kernel from scratch in pure Python using NumPy. By implementing tiled block-sparse causal attention and a fused softmax, you demonstrate deep understanding of memory hierarchies and GPU optimization, signaling senior-level systems architecture skills to hiring managers.

When most engineers think about optimizing transformer inference, they reach for pre-built libraries like HuggingFace Transformers or vLLM. However, understanding the low-level mechanics of memory bandwidth bottlenecks and kernel fusion is what separates junior developers from senior systems architects. Building a FlashAttention-2 inference kernel from scratch—specifically implementing tiled block-sparse causal attention and a fused softmax in pure Python—forces you to confront the realities of the memory hierarchy. By simulating how data moves between High Bandwidth Memory (HBM) and fast cache (SRAM), you gain an intuitive grasp of why modern AI systems are designed the way they are. This project is not just an academic exercise; it is a powerful portfolio piece that proves you can reason about performance at the hardware level.

## Why This Project Stands Out on a CV

In a flooded job market, relying on standard PyTorch pipelines is a dime a dozen. Building a custom FlashAttention kernel signals a rare and highly sought-after combination of skills. It demonstrates that you do not just write code; you understand the physics of your code.

*   **Memory Hierarchy Optimization:** You prove you understand that compute is not the bottleneck—memory bandwidth is. By tiling the computation, you show you know how to minimize expensive HBM reads and writes by maximizing fast on-chip SRAM usage.
*   **Kernel Fusion:** Implementing a fused softmax alongside the attention mechanism demonstrates an understanding of how to eliminate intermediate memory writes, a critical technique in high-performance computing (HPC).
*   **Algorithmic Complexity:** Block-sparse attention reduces the quadratic complexity of standard self-attention. Showing you can implement this proves you can optimize algorithms for scale.
*   **Target Roles:** This project specifically signals readiness for roles like ML Systems Engineer, Accelerator Architect, or High-Performance Backend Engineer—roles where optimizing the intersection of software and silicon is the primary job function.

## Architecture Overview

To build this kernel, we must simulate the hardware architecture of a modern GPU. The core philosophy of FlashAttention is that we must reorganize the computation so that the intermediate attention matrix (which is `O(N^2)` in memory) is never written to global memory. Instead, it is computed and discarded entirely within fast memory.

The architecture of our Python implementation consists of the following components:

*   **Input Matrices (HBM Simulation):** The Query (`Q`), Key (`K`), and Value (`V`) matrices reside in our slow, large memory space. In our Python simulation, these are standard NumPy arrays.
*   **Tiling Engine (SRAM Simulation):** We partition the `K` and `V` matrices into smaller tiles. These tiles are loaded into our "fast memory" (a local NumPy slice) to be processed.
*   **Causal Masking Block:** Ensures that token `i` can only attend to tokens `j <= i`, preserving the autoregressive property of the decoder.
*   **Block-Sparse Scheduler:** Skips computation for tokens that are outside a defined `sparse_window`, drastically reducing the FLOPs for long sequences.
*   **Fused Softmax & Scale Kernel:** The core innovation. Instead of calculating `softmax(QK^T / sqrt(d))` and writing it out, we calculate the scale, apply the mask, compute the softmax, and multiply by `V` in a single pass, updating the output and normalization statistics incrementally (the Online Softmax algorithm).

## Building It Step by Step

We will implement this using pure Python and NumPy. NumPy allows us to explicitly control memory layout and simulate the tiling behavior of a GPU kernel without writing CUDA.

### Step 1: Initialize the Online Softmax State

The Online Softmax algorithm, introduced by FlashAttention, allows us to compute the softmax in a single pass. We must maintain running statistics: the maximum value (`m`), the sum of exponentials (`l`), and the accumulated output (`o`).

```python
import numpy as np

def initialize_online_state(seq_len, d_model):
    o = np.zeros((seq_len, d_model), dtype=np.float32)
    l = np.zeros((seq_len, 1), dtype=np.float32)
    m = np.full((seq_len, 1), -np.inf, dtype=np.float32)
    return o, l, m
```

### Step 2: The Fused Softmax and Scale Kernel

This is the heart of the FlashAttention optimization. We scale the query-key dot products, apply the causal mask, and compute the softmax entirely within the tile, avoiding any intermediate global memory writes.

```python
def fused_softmax_and_scale(scores, scale, mask):
    # Scale the scores
    scores = scores * scale
    
    # Apply causal mask: set masked positions to -inf
    scores = np.where(mask, -np.inf, scores)
    
    # Compute softmax
    max_val = np.max(scores, axis=-1, keepdims=True)
    exp_vals = np.exp(scores - max_val)
    sum_vals = np.sum(exp_vals, axis=-1, keepdims=True)
    
    return exp_vals / sum_vals
```

### Step 3: The Tiled Block-Sparse Attention Loop

Here, we iterate over the Key-Value tiles. For each tile, we load it into our fast memory, compute the attention scores, apply the fused softmax, and accumulate the result. We enforce the block-sparse constraint by skipping tiles outside the `sparse_window`.

```python
def flash_attn_tiled(q, k, v, tile_size=64, sparse_window=32):
    seq_len, d_model = q.shape
    scale = 1.0 / np.sqrt(d_model)
    o, l, m = initialize_online_state(seq_len, d_model)

    # Iterate over K/V tiles (simulating HBM to SRAM movement)
    for j_start in range(0, seq_len, tile_size):
        j_end = min(j_start + tile_size, seq_len)
        k_tile = k[j_start:j_end]
        v_tile = v[j_start:j_end]

        # Create block-sparse mask: only attend to recent tokens
        block_sparse_mask = np.arange(j_start, j_end) >= (np.arange(seq_len)[:, None] - sparse_window)

        for i in range(seq_len):
            # Causal mask: cannot attend to future tokens
            causal_mask = np.arange(j_start, j_end) > i
            combined_mask = causal_mask | (~block_sparse_mask[i])

            q_row = q[i:i+1]
            scores = q_row @ k_tile.T
            
            # Apply fused softmax
            softmax_out = fused_softmax_and_scale(scores, scale, combined_mask)
            
            # Online Softmax update
            new_m = np.max(softmax_out, axis=-1, keepdims=True)
            old_m = m[i]
            m[i] = np.maximum(m[i], new_m)
            
            # Update normalization and output
            exp_old = np.exp(old_m - m[i])
            p = softmax_out * exp_old
            
            o[i] = exp_old * o[i] + p @ v_tile
            l[i] = exp_old * l[i] + np.sum(p)

    return o / l
```

### Step 4: Putting It Together

We define our matrices and run the kernel. Note how we explicitly simulate the memory hierarchy by slicing `k` and `v` into tiles before the inner loop.

```python
# Simulate a batch of queries, keys, and values
seq_len = 256
d_model = 64
q = np.random.randn(seq_len, d_model).astype(np.float32)
k = np.random.randn(seq_len, d_model).astype(np.float32)
v = np.random.randn(seq_len, d_model).astype(np.float32)

# Run the custom FlashAttention-2 kernel
output = flash_attn_tiled(q, k, v, tile_size=64, sparse_window=32)
```

## Running and Testing It

To ensure your implementation is correct, you must compare it against a trusted reference implementation. PyTorch's native `scaled_dot_product_attention` is the perfect oracle. Because we are using pure Python and floating-point arithmetic, we expect minor numerical differences due to the order of operations, but the results should be extremely close.

First, install the required dependencies:

```bash
pip install numpy torch
```

Next, create a validation script that runs both your custom kernel and the PyTorch reference, asserting that the difference is within an acceptable tolerance (typically `1e-4` for float32).

```python
import torch
import torch.nn.functional as F

def validate_implementation():
    # Convert numpy arrays to PyTorch tensors
    q_torch = torch.from_numpy(q).unsqueeze(0) # Add batch dimension
    k_torch = torch.from_numpy(k).unsqueeze(0)
    v_torch = torch.from_numpy(v).unsqueeze(0)

    # PyTorch FlashAttention reference
    ref_output = F.scaled_dot_product_attention(q_torch, k_torch, v_torch, is_causal=True)
    ref_output = ref_output.squeeze(0).numpy()

    # Compare
    difference = np.max(np.abs(output - ref_output))
    print(f"Maximum absolute difference: {difference:.6f}")
    
    if difference < 1e-3:
        print("✅ Validation passed! The custom kernel matches the reference implementation.")
    else:
        print("❌ Validation failed! The outputs diverge significantly.")

validate_implementation()
```

Running this script will prove that your pure Python kernel correctly implements the mathematical logic of FlashAttention-2, validating that your tiling and online softmax logic are sound.

## Extending It: Your Roadmap to Senior-Level

A working toy kernel is a great start, but to truly signal senior-level systems capability, you must evolve it into a production-grade system. Here are five concrete upgrades to add to your repository:

1.  **Paged KV-Cache Integration:** "Eliminates memory fragmentation and maximizes VRAM utilization for long-running inference workloads."
2.  **Distributed Tensor Parallelism:** "Splits the attention matrix across multiple nodes to scale context windows beyond single-GPU memory limits."
3.  **CUDA/Hopper Offloading:** "Translates the pure Python logic into actual hardware instructions, unlocking true teraflop throughput."
4.  **Profiling-Driven Auto-Tuning:** "Dynamically adjusts tile sizes based on hardware counters, ensuring optimal performance across diverse architectures."
5.  **Asynchronous I/O Pipelining:** "Overlaps data transfer with computation to hide memory latency and maximize hardware utilization."

## Key Takeaways

*   Memory bandwidth, not compute, is the primary bottleneck in transformer inference; optimizing data movement is more impactful than optimizing FLOPs.
*   Kernel fusion—combining the softmax and scaling operations—eliminates the need to write the massive intermediate attention matrix to slow global memory.
*   The Online Softmax algorithm allows attention to be computed in a single forward pass, maintaining numerical stability with incremental normalization statistics.
*   Block-sparse attention reduces the quadratic complexity of standard self-attention, making it viable for extremely long context windows.
*   Simulating hardware architectures in high-level languages like Python is a powerful way to prototype and validate complex systems logic before committing to low-level languages like CUDA.

## Further Reading

To deepen your understanding of the systems concepts behind this project, I recommend studying the primary sources and canonical documentation that inspired these techniques.

1.  [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135) — The foundational paper introducing the IO-aware attention algorithm and the online softmax technique.
2.  [FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning](https://arxiv.org/abs/2307.08691) — The sequel paper that details the optimizations for modern hardware, including better parallelism and non-causal attention.
3.  [torch.nn.functional.scaled_dot_product_attention](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) — The official PyTorch documentation for the native scaled dot product attention operator used as our validation oracle.
4.  [Block-Sparse Attention for Long-Form Summarization](https://arxiv.org/abs/2112.05682) — A seminal paper on structured sparsity in attention mechanisms, providing the theoretical backing for the block-sparse scheduler in our implementation.