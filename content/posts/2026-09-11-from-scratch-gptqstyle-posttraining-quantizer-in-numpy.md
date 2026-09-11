

---
title: "From Scratch: GPTQ‑Style Post‑Training Quantizer in NumPy"
date: "2026-09-11T03:01:18.767"
draft: false
tags: ["quantization", "numpy", "machine-learning", "systems", "portfolio"]
description: "Build a GPTQ-style post-training quantizer in NumPy with block-wise INT4 weight quantization, optimal scaling, zero-point calibration, and fake-quant inference."
summary: "This guide walks you through implementing a GPTQ-style post-training quantizer entirely in NumPy. The resulting script compresses transformer weights and measures accuracy impact, showcasing your ability to ship low-level ML infrastructure."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-from-scratch-gptqstyle-posttraining-quantizer-in-numpy.svg"
  alt: "A neural network weight matrix visualized as a heatmap."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a GPTQ‑style post‑training quantizer entirely in NumPy, covering block‑wise INT4 weight quantization, optimal scaling and zero‑point calibration, and a fake‑quant inference loop. By the end you will have a runnable script that can compress a transformer weight matrix and measure the resulting accuracy drop, giving you a concrete artifact to showcase on your résumé.

Post‑training quantization is a practical technique for shrinking deep‑learning models without retraining. In this tutorial we implement a simplified version of the GPTQ algorithm from scratch using only NumPy, focusing on the core math that turns floating‑point weights into 4‑bit integers while keeping the model's output nearly unchanged. The code is intentionally minimal so you can see every operation, yet it is complete enough to run on a synthetic weight matrix and report the reconstruction error.

## Why This Project Stands Out on a CV

- **Low‑level numerical engineering** – you write the scaling, rounding, and de‑quantization loops yourself, proving you understand how data moves through a compute kernel.
- **Algorithmic depth** – the project requires computing per‑block optimal scale and zero‑point, a skill that maps directly to work on model compression, edge deployment, and high‑performance inference.
- **Systems thinking** – you ship a self‑contained script that can be integrated into a larger training pipeline, showing you can bridge research code and production tooling.
- **Relevant roles** – this artifact speaks to positions such as ML Engineer, Systems Engineer, Performance Engineer, or MLOps Engineer, where squeezing models onto constrained hardware is a core responsibility.

## Architecture Overview

The quantizer is composed of five logical pieces:

1. **Weight matrix** – a 2‑D NumPy array representing a transformer’s linear layer.
2. **Block partitioner** – splits the matrix into fixed‑size blocks (e.g., 128×128) along the input dimension.
3. **Scale & zero‑point calculator** – for each block, computes the optimal scale `s` and integer zero‑point `z` that minimize quantization error.
4. **Quantize / de‑quantize functions** – map floating‑point values to 4‑bit integers and back, using the block‑wise `s` and `z`.
5. **Fake‑quant inference loop** – runs a forward pass through the quantized weights without actually converting to 4‑bit storage, allowing you to measure the impact on output.

These components interact in a linear pipeline: **Weight → Block → Scale/Zero‑point → Quantize → De‑quantize → Output → Error metric**.

## Building It Step by Step

Below are the core steps, each with a runnable Python snippet. The code uses only NumPy, so you can paste it into a single file `quantizer.py`.

### Step 1: Setup and Synthetic Weight Matrix

```python
import numpy as np

# Create a synthetic weight matrix (e.g., 512 x 512)
np.random.seed(42)
W = np.random.randn(512, 512).astype(np.float32)
```

### Step 2: Define Block Size and Reshape

```python
block_size = 128  # number of columns per block

# Ensure the number of columns is divisible by block_size
assert W.shape[1] % block_size == 0, "Columns must be divisible by block_size"

# Reshape to (rows, num_blocks, block_size) for easy block‑wise ops
rows, cols = W.shape
num_blocks = cols // block_size
W_blocks = W.reshape(rows, num_blocks, block_size)
```

### Step 3: Compute Optimal Scale and Zero‑Point per Block

We use the **GPTQ** approach: for each block, find the scale that minimizes the L2 error after rounding, then derive the zero‑point.

```python
def compute_scale_zero_point(block):
    # block: (rows, block_size)
    # Find min/max for the block
    w_min = block.min()
    w_max = block.max()
    
    # We'll search for the scale that minimizes quantization error
    # In practice, a simple grid search or analytic formula works.
    # Here we use a coarse grid for illustration.
    best_scale = None
    best_zero = None
    best_error = np.inf
    
    # Candidate scales: linear space between (w_max - w_min) / 15 and that value * 2
    # 15 = 2^4 - 1 for INT4
    qmax = 15
    for scale in np.linspace((w_max - w_min) / qmax, 2 * (w_max - w_min) / qmax, 50):
        zero = -w_min / scale  # integer zero‑point
        zero = np.clip(zero, 0, qmax)  # keep within [0, qmax]
        
        # Quantize
        q = np.round(block / scale + zero)
        q = np.clip(q, 0, qmax)
        
        # De‑quantize
        dq = (q - zero) * scale
        
        # Error
        error = np.mean((block - dq) ** 2)
        if error < best_error:
            best_error = error
            best_scale = scale
            best_zero = zero
    
    return best_scale, best_zero

# Compute for each block
scales = np.zeros((num_blocks,), dtype=np.float32)
zeros  = np.zeros((num_blocks,), dtype=np.float32)

for i in range(num_blocks):
    scales[i], zeros[i] = compute_scale_zero_point(W_blocks[:, i, :])
```

### Step 4: Quantize and De‑quantize Functions

```python
def quantize_dequantize(block, scale, zero):
    qmax = 15
    q = np.round(block / scale + zero)
    q = np.clip(q, 0, qmax)
    dq = (q - zero) * scale
    return dq

# Apply to all blocks
W_q_blocks = np.empty_like(W_blocks)
for i in range(num_blocks):
    W_q_blocks[:, i, :] = quantize_dequantize(
        W_blocks[:, i, :], scales[i], zeros[i]
    )

# Reshape back to original dimensions
W_q = W_q_blocks.reshape(rows, cols)
```

### Step 5: Evaluate Reconstruction Error

```python
# Mean squared error between original and quantized weights
mse = np.mean((W - W_q) ** 2)
print(f"Quantization MSE: {mse:.6e}")

# Optional: relative error
rel_error = np.linalg.norm(W - W_q) / np.linalg.norm(W)
print(f"Relative L2 error: {rel_error:.6e}")
```

### Step 6: Fake‑Quant Inference Loop

This loop simulates using the quantized weights in a forward pass without actually storing 4‑bit integers.

```python
def fake_quant_forward(input_vec, W, scales, zeros, block_size):
    """
    Simulates a linear layer: output = input @ W^T
    using the block‑wise quantized weights.
    """
    rows, cols = W.shape
    num_blocks = cols // block_size
    output = np.zeros(input_vec.shape[0], dtype=np.float32)
    
    for i in range(num_blocks):
        start = i * block_size
        end = start + block_size
        # Slice the weight block
        W_block = W[:, start:end]
        scale = scales[i]
        zero = zeros[i]
        # Quantize‑de