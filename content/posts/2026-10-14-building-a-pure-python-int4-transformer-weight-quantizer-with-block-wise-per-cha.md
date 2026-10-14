---
title: "Building a Pure-Python INT4 Transformer Weight Quantizer with Block-Wise Per-Channel Scaling"
date: "2026-10-14T19:01:58.217"
draft: false
tags: ["quantization", "transformer", "python", "machine-learning", "systems"]
description: "Learn to implement a pure-Python INT4 quantizer for transformer weights using block-wise per-channel scaling, perfect for a portfolio project."
summary: "A practical guide to building a pure-Python INT4 quantizer for transformer weights, demonstrating real systems skills for your portfolio."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-14-building-a-pure-python-int4-transformer-weight-quantizer-with-block-wise-per-cha.svg"
  alt: "A visualization of quantized weight tensors with block-wise scaling"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you'll implement a pure-Python INT4 weight quantizer that uses block-wise per-channel scaling, giving you a concrete portfolio piece that showcases low-precision optimization, numerical stability, and production-ready testing. The code runs on any Python 3.10+ environment and can be extended to quantize real transformer models, making it a strong signal for systems and ML engineering roles.

Transformer models have grown to billions of parameters, making memory and compute constraints a first-class concern in production deployments. While frameworks like PyTorch and TensorFlow offer built-in quantization, understanding the underlying algorithm is a valuable skill that signals systems expertise to hiring managers.

## Why This Project Stands Out on a CV

- **Low‑precision integer arithmetic** – You’ll work directly with 4‑bit weights, demonstrating familiarity with the hardware‑aware optimizations that enable edge deployment.
- **Block‑wise per‑channel scaling** – This technique balances quantization error across heterogeneous weight distributions, a nuance that separates toy examples from real‑world model compression.
- **Pure Python implementation** – No external ML frameworks required; you’ll showcase algorithmic clarity, testability, and cross‑platform portability.
- **Numerical stability & error analysis** – You’ll compute mean squared error (MSE) and maximum absolute error, proving you can validate approximations against a float32 baseline.
- **End‑to‑end pipeline** – From weight loading to CLI export, the project mirrors the workflow of an ML infrastructure engineer.
- **Portfolio signal** – Hiring managers for **ML Engineer**, **AI Infrastructure**, and **Systems Engineer** roles look for evidence of model compression, profiling, and production‑ready code.

## Architecture Overview

The quantizer is composed of six cooperating components:

```text
+----------------+    +----------------+    +----------------+
|   Weight Loader|-->| Block Partition|-->| Scale Calculator|
+----------------+    +----------------+    +----------------+
                                 |
                                 v
                          +----------------+
                          |   Quantizer    |
                          +----------------+
                                 |
                                 v
                          +----------------+
                          |   Dequantizer  |
                          +----------------+
                                 |
                                 v
                          +----------------+
                          | Error Evaluator|
                          +----------------+
```

1. **Weight Loader** – Reads a float32 tensor (e.g., from a `.npy` file or a Hugging Face checkpoint) into a NumPy array.
2. **Block Partitioner** – Splits each channel into contiguous blocks of size `B` (a hyper‑parameter).
3. **Scale Calculator** – For each block, computes the per‑channel scaling factor `s = max(|block|) / 7` (since INT4 ranges from ‑8 to 7).
4. **Quantizer** – Maps each weight to the nearest integer in `[-8, 7]` using `round(w / s)`.
5. **Dequantizer** – Reconstructs an approximation `w_hat = q * s`.
6. **Error Evaluator** – Compares `w_hat` against the original `w` to report MSE and max absolute error.

A thin CLI ties these together, allowing users to specify input paths, block size, and output format.

## Building It Step by Step

### 1. Set up the environment

```bash
python -m venv quantizer_env
source quantizer_env/bin/activate
pip install numpy==1.26.4
```

### 2. Define the core data structures

```python
# quantizer/__init__.py
from typing import Tuple
import numpy as np

class Int4Quantizer:
    def __init__(self, block_size: int = 128):
        self.block_size = block_size
        self.scales: np.ndarray = None  # shape (channels, blocks_per_channel)
        self.quantized: np.ndarray = None  # shape (out_features, in_features), dtype=np.int8
```

### 3. Implement block‑wise per‑channel scaling

```python
def compute_scales(self, weights: np.ndarray) -> np.ndarray:
    """
    weights: float32 array of shape (out_features, in_features)
    returns: float32 array of scales, shape (out_features, blocks_per_channel)
    """
    out_features, in_features = weights.shape
    # Pad to a multiple of block_size for simplicity
    pad = (-in_features) % self.block_size
    if pad:
        weights = np.pad(weights, ((0, 0), (0, pad)), mode='constant')
    blocks = in_features // self.block_size
    # Reshape to (out_features, blocks, block_size)
    reshaped = weights.reshape(out_features, blocks, self.block_size)
    # Compute max absolute value per block
    max_abs = np.max(np.abs(reshaped), axis=-1)  # (out_features, blocks)
    # Scale factor for INT4 (range -8..7)
    scales = max_abs / 7.0
    # Avoid division by zero
    scales[scales == 0] = 1.0
    self.scales = scales
    return scales
```

### 4. Quantize to INT4

```python
def quantize(self, weights: np.ndarray) -> np.ndarray:
    """
    weights: float32 array (out_features, in_features)
    returns: int8 array of same shape (values clipped to -8..7)
    """
    out_features, in_features = weights.shape
    pad = (-in_features) % self.block_size
    if pad:
        weights = np.pad(weights, ((0, 0), (0, pad)), mode='constant')
    blocks = in_features // self.block_size
    reshaped = weights.reshape(out_features, blocks, self.block_size)
    # Expand scales to match each element
    scales_exp = np.repeat(self.scales, self.block_size, axis=-1)  # (out_features, in_features)
    # Round to nearest integer
    q = np.round(weights / scales_exp)
    # Clip to INT4 range
    q = np.clip(q, -8, 7).astype(np.int8)
    # Remove padding if added
    self.quantized = q[:, :in_features]
    return self.quantized
```

### 5. Dequantize and evaluate error

```python
def dequantize(self) -> np.ndarray:
    """
    Reconstruct float approximation from stored quantized weights and scales.
    """
    if self.quantized is None or self.scales is None:
        raise RuntimeError("Call quantize() before dequantize()")
    out_features, in_features = self.quantized.shape
    pad = (-in_features) % self.block_size
    if pad:
        q_padded = np.pad(self.quantized, ((0, 0), (0, pad)), mode='constant')
    else:
        q_padded = self.quantized
    blocks = q_padded.shape[1] // self.block_size
    # Expand scales
    scales_exp = np.repeat(self.scales, self.block_size, axis=-1)
    w_hat = q_padded.astype(np.float32) * scales_exp
    return w_hat[:, :in_features]

def compute_errors(self, original: np.ndarray) -> Tuple[float, float]:
    """
    Returns (MSE, max_abs_error)
    """
    reconstructed = self.dequantize()
    diff = original - reconstructed
    mse = np.mean(diff ** 2)
    max_abs = np.max(np.abs(diff))
    return mse, max_abs
```

### 6. Expose a command‑line interface

```python
# cli.py
import argparse
import numpy as np
from quantizer import Int4Quantizer

def main():
    parser = argparse.ArgumentParser(description="INT4 quantizer for transformer weights")
    parser.add_argument("--input", required=True, help="Path to .npy weight file")
    parser.add_argument("--output", default="quantized.npy", help="Output path for quantized weights")
    parser.add_argument("--block-size", type=int, default=128, help="Block size for per‑channel scaling")
    args = parser.parse_args()

    weights = np.load(args.input).astype(np.float32)
    quantizer = Int4Quantizer(block_size=args.block_size)
    quantizer.compute_scales(weights)
    q = quantizer.quantize(weights)
    np.save(args.output, q)

    mse, max_err = quantizer.compute_errors(weights)
    print(f"Quantization complete. MSE: {mse:.6f}, Max Abs Error: {max_err:.6f}")

if __name__ == "__main__":
    main()
```

## Running and Testing It

1. **Generate a sample weight tensor** (e.g., from a small transformer):

```bash
python -c "import numpy as np; np.random.seed(0); w = np.random.randn(768, 768).astype('float32'); np.save('sample_weight.npy', w)"
```

2. **Run the quantizer**:

```bash
python cli.py --input sample_weight.npy --output quantized_weight.npy --block-size 128
```

3. **Inspect results**:

```python
import numpy as np
orig = np.load('sample_weight.npy')
q = np.load('quantized_weight.npy')
print("Original dtype:", orig.dtype)
print("Quantized dtype:", q.dtype)
```

4. **Automated unit test** (using `pytest`):

```python
# test_quantizer.py
import numpy as np
from quantizer import Int4Quantizer

def test_roundtrip():
    w = np.random.randn(512, 512).astype(np.float32)
    q = Int4Quantizer(block_size=64)
    q.compute_scales(w)
    q.quantize(w)
    mse, max_err = q.compute_errors(w)
    assert mse < 0.01, f"MSE too high: {mse}"
    assert max_err < 0.5, f"Max error too high: {max_err}"
```

Run with `pytest -v test_quantizer.py`. A passing test proves the pipeline is functional and reproducible.

## Extending It: Your Roadmap to Senior-Level

1. **Persist scales alongside weights** – Store `scales` in a separate `.npz` file or embed them in a custom binary format; this matters for inference engines that need to reconstruct tensors without recomputing scaling factors.
2. **GPU acceleration with CuPy or CUDA kernels** – Move the block‑wise reduction to a CUDA kernel, cutting quantization time from seconds to milliseconds on large models; essential for CI pipelines that quantize nightly.
3. **Integration with PyTorch’s `torch.quantization`** – Expose a `torch.nn.Module` wrapper that uses your INT4 weights, enabling drop‑in replacement in existing training scripts and demonstrating framework fluency.
4. **Benchmarking suite** – Add a script that measures memory footprint, latency, and throughput before/after quantization on a reference transformer (e.g., BERT‑base); quantitative evidence strengthens any performance‑oriented narrative.
5. **Observability with structured logging** – Emit JSON logs capturing block size, scale ranges, and error metrics; this mirrors production ML platforms that aggregate metrics in Prometheus or Grafana.
6. **Fault‑tolerant CLI** – Implement retries for file I/O, graceful handling of corrupted weight files, and a `--dry‑run` flag; shows awareness of operational robustness expected in senior roles.

## Key Takeaways

- You now have a **pure‑Python INT4 quantizer** that uses block‑wise per‑channel scaling, a technique that balances compression with accuracy.
- The implementation is **modular**, **tested**, and **CLI‑driven**, providing a clear portfolio artifact.
- It demonstrates **low‑precision arithmetic**, **numerical error analysis**, and **end‑to‑end ML infrastructure skills**.
- The project can be **extended** with persistence, GPU kernels, framework integration, and observability to showcase senior‑level engineering maturity.

## Further Reading

- [LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale](https://arxiv.org/abs/2208.01233) – seminal paper on mixed‑precision quantization.
- [GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2305.14314) – details block‑wise quantization and error compensation.
- [Hugging Face Transformers Quantization Guide](https://huggingface.co/docs/transformers/main/en/tasks/quantization) – practical integration with popular models.
- [PyTorch Quantization Documentation](https://pytorch.org/docs/stable/quantization.html) – official API reference for static and dynamic quantization.
- [NVIDIA TensorRT Quantization Workflow](https://www.nvidia.com/en-us/deep-learning-ai/resources/accelerating-inference/tensorrt/) – production‑grade INT8/INT4 deployment on GPUs.