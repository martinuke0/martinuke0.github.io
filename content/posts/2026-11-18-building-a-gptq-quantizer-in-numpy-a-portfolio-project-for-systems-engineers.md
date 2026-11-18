---
title: "Building a GPTQ Quantizer in NumPy: A Portfolio Project for Systems Engineers"
date: "2026-11-18T06:01:28.803"
draft: false
tags: ["quantization", "gptq", "numpy", "machine-learning", "side-project", "systems"]
description: "Learn to build a from-scratch int4 weight quantizer using GPTQ with grouped scales and fake-quant dequant in pure NumPy. A hands-on project that showcases real systems skills for hiring managers."
summary: "A practical guide to implementing GPTQ quantization in NumPy, demonstrating systems-level skills for engineering roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-18-building-a-gptq-quantizer-in-numpy-a-portfolio-project-for-systems-engineers.svg"
  alt: "Abstract visualization of quantized neural network weights"
  caption: ""
  relative: false
---

> **TL;DR** — GPTQ quantization compresses neural network weights to 4-bit integers using second-order Hessian-based error compensation, and you can implement it from scratch in pure NumPy. This project demonstrates systems engineering skills like numerical precision management, algorithmic efficiency, and model compression, making it stand out on any CV. By building a grouped-scale fake-quant dequant loop, you'll have a runnable artifact that proves you understand the intersection of ML and systems.

Quantization is a critical technique for deploying large language models on resource-constrained devices. Among various methods, GPTQ stands out for its ability to compress weights to 4-bit integers with minimal accuracy loss by leveraging second-order information. In this post, we'll build a from-scratch implementation of GPTQ in pure NumPy, including grouped scales and a fake-quant dequant loop. This project is designed to be a portfolio piece that signals real systems skill to hiring managers.

## Why This Project Stands Out on a CV

This project demonstrates several high-value skills that are often hard to showcase in a traditional resume. First, it involves numerical linear algebra—computing Hessian approximations and managing numerical stability—which is core to many advanced ML roles. Second, it requires algorithmic design: the GPTQ algorithm greedily quantizes columns in an order determined by sensitivity and compensates errors using second-order information, which shows you can implement research-level optimizations. Third, it highlights memory efficiency and systems thinking, as you'll handle large matrices in-place and optimize for speed and footprint. 

For hiring managers, this signals that you understand model compression, a key concern for deploying AI in production. It's relevant for roles like ML Engineer, AI Infrastructure Engineer, or Systems Researcher, where practical implementation of quantization techniques is essential. Unlike theoretical knowledge, this project provides a concrete, runnable artifact that you can discuss in interviews with real code and metrics.

## Architecture Overview

The implementation consists of several key components that work together to achieve int4 quantization:

- **Weight Matrix (W)**: A float32 matrix representing the neural network weights to be quantized. In practice, this could be from a transformer model, but for our example, we'll use a randomly generated matrix.
- **Calibration Data (X)**: A set of input activations used to compute the Hessian approximation. This data captures the sensitivity of the loss to weight changes.
- **Hessian Approximation (H)**: Computed as \( H = X^T X \), this matrix encodes second-order information about the loss surface. It's used to determine the quantization order and compensate errors.
- **GPTQ Quantizer**: The core algorithm that processes columns sequentially, using the Hessian to guide error compensation. It incorporates grouped scales to handle varying weight ranges efficiently.
- **Grouped Scales**: Columns are divided into groups (e.g., every 128 columns), and each group has its own scale factor for int4 representation. This improves accuracy over a single global scale.
- **Fake-Quant Dequant Loop**: A validation step that simulates the quantization process by rounding to int4 and dequantizing back to float, allowing us to measure reconstruction error without affecting the original model.

The flow is as follows: we compute the Hessian from calibration data, sort columns by sensitivity (derived from the Hessian), quantize each column while propagating errors to remaining columns, and finally validate with a dequantization loop. This architecture mirrors production systems like GPTQ's integration with Hugging Face Transformers, but here we build it from scratch for educational value.

## Building It Step by Step

Let's implement the GPTQ quantizer step by step in pure NumPy. We'll assume a simple scenario with a random weight matrix and calibration data, but the code is modular for real-world use.

**Step 1: Setup and Imports**
```python
import numpy as np
import time
```

**Step 2: Generate Sample Data**
We'll create a random weight matrix and calibration data to simulate a realistic scenario.
```python
# Set seed for reproducibility
np.random.seed(42)

# Generate a weight matrix (e.g., 1024x1024 for a toy model)
W = np.random.randn(1024, 1024).astype(np.float32)

# Generate calibration data: 128 samples of dimension 1024
X = np.random.randn(128, 1024).astype(np.float32)
```

**Step 3: Compute Hessian Approximation**
The Hessian is approximated as the outer product of calibration inputs, which captures curvature information.
```python
# Compute Hessian: H = X^T X, averaged over samples for stability
H = (X.T @ X) / X.shape[0]
```

**Step 4: Implement GPTQ Quantization**
This is the core algorithm. We'll sort columns by sensitivity (diagonal of the inverse Hessian), then quantize each column while compensating errors using the Hessian. Grouped scales are applied every 128 columns.
```python
def gptq_quantize(W, H, group_size=128, bits=4):
    """
    Quantize weight matrix W using GPTQ with grouped scales.
    
    Args:
        W: float32 weight matrix of shape (rows, cols)
        H: Hessian matrix of shape (cols, cols)
        group_size: number of columns per scale group
        bits: bit-width for quantization (default 4)
    
    Returns:
        W_q: quantized weights as int4 values
        scales: scale factors for each group
        perm: permutation used for column ordering
    """
    rows, cols = W.shape
    
    # Compute sensitivity: diagonal of inverse Hessian (add epsilon for stability)
    H_inv = np.linalg.inv(H + 1e-6 * np.eye(cols))
    sensitivity = np.diag(H_inv)
    
    # Sort columns by sensitivity in descending order
    perm = np.argsort(-sensitivity)
    W_sorted = W[:, perm]
    H_sorted = H[perm][:, perm]
    
    # Initialize quantized weights and error accumulator
    W_q = np.zeros_like(W_sorted, dtype=np.int32)  # Store as int for now
    E = np.zeros_like(W_sorted)  # Error to compensate
    
    # Determine number of groups and precompute scales
    num_groups = (cols + group_size - 1) // group_size
    scales = np.zeros(num_groups, dtype=np.float32)
    
    # Precompute scale for each group based on max absolute value
    for g in range(num_groups):
        start = g * group_size
        end = min((g + 1) * group_size, cols)
        group_w = W_sorted[:, start:end]
        max_val = np.max(np.abs(group_w))
        # Symmetric int4 range: [-7, 7] for 4 bits (using 2^3 - 1)
        scales[g] = max_val / (2**(bits-1) - 1) if max_val > 0 else 1.0
    
    # Quantize columns sequentially
    for i in range(cols):
        # Get current column with error compensation
        col = W_sorted[:, i] - E[:, i]
        group_idx = i // group_size
        scale = scales[group_idx]
        
        # Quantize to int4: round and clip to symmetric range
        q_col = np.clip(np.round(col / scale), -2**(bits-1), 2**(bits-1)-1)
        W_q[:, i] = q_col
        
        # Dequantize to compute error
        col_deq = q_col * scale
        error = col - col_deq
        
        # Propagate error to remaining columns using Hessian
        # The error in column i affects column j proportional to H_sorted[i, j] / H_sorted[i, i]
        if i < cols - 1:
            # Update error for future columns: E[:, i+1:] += outer(error, factor)
            factor = H_sorted[i, i+1:] / (H_sorted[i, i] + 1e-8)
            E[:, i+1:] += np.outer(error, factor)
    
    # Unsort the columns to original order
    inv_perm = np.argsort(perm)
    W_q_unsorted = W_q[:, inv_perm]
    
    return W_q_unsorted, scales, perm
```

**Step 5: Fake-Quant Dequant Loop for Validation**
This step simulates the quantized model by dequantizing back to float and measuring reconstruction error.
```python
def fake_quant_dequant(W_q, scales, perm, group_size=128, bits=4):
    """
    Dequantize int4 weights back to float32 for validation.
    
    Args:
        W_q: quantized weights from gptq_quantize
        scales: scale factors per group
        perm: column permutation used
        group_size: size of each scale group
        bits: bit-width
    
    Returns:
        W_deq: dequantized float32 matrix
    """
    cols = W_q.shape[1]
    W_deq = np.zeros((W_q.shape[0], cols), dtype=np.float32)
    
    # Dequantize each column using its group scale
    for i in range(cols):
        group_idx = i // group_size
        scale = scales[group_idx]
        W_deq[:, i] = W_q[:, i] * scale
    
    # Unsort to original column order
    inv_perm = np.argsort(perm)
    W_deq = W_deq[:, inv_perm]
    
    return W_deq
```

**Step 6: Run the Full Pipeline**
Combine all steps and measure performance.
```python
# Perform quantization
start_time = time.time()
W_q, scales, perm = gptq_quantize(W, H)
quant_time = time.time() - start_time

# Dequantize for validation
W_deq = fake_quant_dequant(W_q, scales, perm)

# Compute mean squared error (MSE) as a quality metric
mse = np.mean((W - W_deq) ** 2)
relative_error = mse / np.mean(W ** 2)

print(f"Quantization completed in {quant_time:.2f} seconds")
print(f"Mean Squared Error: {mse:.6f}")
print(f"Relative Error: {relative_error:.6f}")
print(f"Compression ratio: {32 / 4}x (from 32-bit float to 4-bit int)")
```

## Running and Testing It

To run this project locally, save the code above into a Python file (e.g., `gptq_quantizer.py`) and execute it with Python 3.8+ and NumPy installed (`pip install numpy`). The script will output the quantization time, MSE, and relative error, providing immediate feedback on the algorithm's effectiveness.

For testing, you can vary parameters like matrix size, group size, or bit-width to observe trade-offs. For example, reducing group size often improves accuracy at the cost of overhead. A good practice is to compare against a baseline like simple min-max quantization to highlight GPTQ's error compensation benefits. You can also visualize the weight distribution before and after quantization using matplotlib to see how well the int4 representation preserves the original range.

To prove it works in a production-like scenario, integrate it with a small neural network (e.g., a multi-layer perceptron) and measure accuracy drop on a task like MNIST classification. This demonstrates end-to-end viability and strengthens your portfolio narrative.

## Extending It: Your Roadmap to Senior-Level

This basic implementation is a starting point. Here are concrete upgrades that transform it into a production-flavored tool, each with a reason it matters:

1. **Persistence with HDF5 or Pickle**: Save quantized weights and scales to disk in a format like HDF5, enabling reuse without recomputation. This matters for efficiency in CI/CD pipelines and model serving.

2. **Horizontal Scaling with Multiprocessing**: Parallelize quantization across multiple CPU cores or machines using Python's `multiprocessing` library. This is critical for handling large models where single-threaded quantization is a bottleneck.

3. **Observability with Logging and Metrics**: Integrate structured logging (e.g., with `structlog`) and export metrics to Prometheus. Track per-layer error, memory usage, and quantization time to diagnose issues in production.

4. **Fault Tolerance via Checkpointing**: Implement periodic checkpointing during long quantization runs, allowing recovery from failures without restarting. This ensures reliability when processing models with millions of parameters.

5. **Benchmarking with Profiling Tools**: Use `cProfile` or `memory_profiler` to identify hotspots and memory leaks. Benchmark on different hardware (e.g., CPU vs. GPU with NumPy alternatives) to optimize for cost and speed.

6. **Integration with Real Models**: Extend the code to work with actual transformer weights from libraries like Hugging Face Transformers, adding support for pruning and mixed-precision. This bridges the gap between toy examples and industry applications.

## Key Takeaways

- GPTQ quantization uses second-order Hessian information to compensate errors sequentially, achieving high compression with minimal accuracy loss.
- Implementing it in NumPy teaches core systems skills: numerical stability, memory management, and algorithm optimization.
- Grouped scales improve int4 representation by adapting to local weight ranges, a technique used in production quantization systems.
- This project serves as a tangible portfolio piece that demonstrates ML and systems integration, appealing to hiring managers.
- Extensions like persistence, scaling, and observability showcase readiness for real-world deployment.

## Further Reading

- **GPTQ Paper**: Frantar et al. "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers" ([arXiv:2210.17323](https://arxiv.org/abs/2210.17323)) — the primary source for the algorithm.
- **Hessian Approximation in Quantization**: "Hessian-based sensitivity analysis for neural network quantization" ([IEEE Xplore](https://ieeexplore.ieee.org/document/9413587)) — deeper dive into second-order methods.
- **NumPy Documentation**: [NumPy User Guide](https://numpy.org/doc/stable/user/index.html) — essential for efficient array operations and numerical computing.
- **Model Compression Survey**: "A Survey of Quantization Techniques for Neural Networks" ([arXiv:2112.13819](https://arxiv.org/abs/2112.13819)) — broader context for quantization methods.
- **Hugging Face Transformers**: [Transformers Documentation](https://huggingface.co/docs/transformers/index) — for integrating quantization with real models.