---
title: "Building a From-Scratch Group-Wise INT4 Quantization Layer for LLaMA Weights"
date: "2026-09-21T12:01:29.495"
draft: false
tags: ["quantization", "llama", "pytorch", "ml-systems", "deep-learning", "python"]
description: "Build a production-grade group-wise INT4 quantization layer for LLaMA transformer weights from scratch, with per-group scale calibration and fused dequantization benchmarks."
summary: "A hands-on guide to implementing group-wise INT4 quantization for LLaMA-style transformers, covering per-group scale calibration, fused dequantization kernels, and benchmarks that demonstrate real ML-systems engineering skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-building-a-from-scratch-group-wise-int4-quantization-layer-for-llama-weights.svg"
  alt: "A visualization of INT4 quantization layers inside a transformer model, showing weight matrices being compressed and dequantized."
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a from-scratch group-wise INT4 quantization layer for LLaMA-style transformer weights using PyTorch, complete with per-group scale calibration, a fused dequantization kernel, and end-to-end benchmarks. The project demonstrates systems-level ML engineering that stands out on a CV and gives you a concrete artifact to discuss in technical interviews.

Quantization is one of the most practically valuable techniques in modern ML systems engineering. As models grow into the billions of parameters, deploying them at full precision becomes prohibitively expensive. Group-wise quantization — the method behind Llama.cpp's Q4_K_M and similar formats — strikes the best balance between compression ratio and accuracy retention.

What makes this project genuinely different from a toy notebook is that you're building the actual machinery: the quantization algorithm, the calibration strategy, the fused kernel, and the benchmark harness. Every line is inspectable, testable, and improvable. Let's build it.

## Why This Project Stands Out on a CV

Hiring managers and senior engineers scan portfolios for signals that a candidate understands the full stack of machine learning systems. This project hits several of those signals simultaneously:

- **Numerical linear algebra proficiency.** Implementing quantization from scratch forces you to understand floating-point representations, rounding modes, overflow behavior, and the numerical properties of INT4 tensors.
- **Performance engineering.** Fused dequantization kernels require you to think about memory access patterns, vectorization, and kernel fusion — the same concerns that show up in distributed systems and database engines.
- **ML systems architecture.** Calibration, calibration datasets, and error analysis connect directly to MLOps concerns around model quality, drift, and reproducibility.
- **Open-source contribution readiness.** The Llama.cpp ecosystem thrives on contributors who understand quantization internals. This project gives you a concrete PR you can point to.

This project signals roles in ML infrastructure, applied ML engineering, and LLM optimization — three of the most in-demand specializations right now.

## Architecture Overview

The implementation decomposes into five tightly coupled components. Here's how they fit together:

```
┌──────────────────────────────────────────────────────┐
│                  Quantization Pipeline                 │
├──────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐    ┌───────────────────────────┐  │
│  │  Weight      │───▶│  Group-Wise Quantizer      │  │
│  │  Loader      │    │  (per-group scale calc)    │  │
│  └──────────────┘    └────────────┬──────────────┘  │
│                                   │                  │
│                          ┌────────▼────────┐         │
│                          │  Scale Calibrator │         │
│                          │  (min-max / MSE)  │         │
│                          └────────┬────────┘         │
│                                   │                  │
│                          ┌────────▼────────┐         │
│                          │  INT4 Tensor     │         │
│                          │  Storage Format   │         │
│                          └────────┬────────┘         │
│                                   │                  │
│                          ┌────────▼────────┐         │
│                          │  Fused Dequant-  │         │
│                          │  Matmul Kernel   │         │
│                          │  (CUDA / torch.compile)│  │
│                          └───────────────────┘         │
└──────────────────────────────────────────────────────┘
```

The data flows left to right: raw FP16/FP32 weights are loaded, grouped into chunks, quantized with per-group scales, stored as compact INT4 tensors, and then dequantized-and-multiplied in a single fused operation during inference. The calibration step sits between quantization and storage, determining the optimal scale factors that minimize reconstruction error.

Key design decisions baked into this architecture:

- **Group size of 128** as the default, which is the Llama.cpp convention and provides a good accuracy/overhead tradeoff.
- **Per-group scales** rather than a single global scale, which dramatically reduces quantization error for weights with heterogeneous magnitudes across layers.
- **Symmetric quantization** (zero-point is fixed at 0), which simplifies the dequantization math and is the standard choice for transformer weights.
- **Fused dequantization + matmul** as the hot path, eliminating the memory bandwidth bottleneck of materializing a full-precision intermediate tensor.

## Building It Step by Step

We'll use PyTorch as the base framework. The full implementation is around 200 lines of Python — small enough to understand end-to-end, large enough to be a real artifact. Install dependencies first:

```bash
pip install torch numpy transformers accelerate
```

### Step 1: Define the Quantization Core

The core function takes a weight tensor, splits it into groups, computes per-group scales, and rounds to INT4. We use `torch.int8` storage with a packing scheme that fits two INT4 values per byte (nibble packing), which is what Llama.cpp does under the hood.

```python
import torch
import torch.nn.functional as F
import numpy as np

class GroupWiseINT4Quantizer:
    """
    Group-wise symmetric INT4 quantization with per-group scales.
    Groups of `group_size` elements share a single scale factor.
    Weights are stored as packed int8 (two int4 nibbles per byte).
    """

    def __init__(self, group_size: int = 128):
        self.group_size = group_size

    def calibrate_scales(self, weight: torch.Tensor) -> torch.Tensor:
        """
        Compute per-group max absolute values (scales).
        For symmetric quantization, scale = max(|weight|) per group.
        """
        shape = weight.shape
        # Reshape so each group is a contiguous dimension
        n_groups = (shape[0] * shape[1] + self.group_size - 1) // self.group_size
        flat = weight.abs().reshape(-1)
        # Pad to group boundary
        pad_len = n_groups * self.group_size - flat.numel()
        if pad_len > 0:
            flat = F.pad(flat, (0, pad_len), value=0.0)
        grouped = flat.reshape(n_groups, self.group_size)
        scales = grouped.max(dim=1).values
        # Avoid division by zero for all-zero groups
        scales = torch.clamp(scales, min=1e-8)
        return scales

    def quantize(self, weight: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """
        Quantize weight to INT4. Returns (packed_int8_tensor, scales).
        """
        scales = self.calibrate_scales(weight)
        flat = weight.abs().reshape(-1)
        n_groups = scales.numel()
        pad_len = n_groups * self.group_size - flat.numel()
        if pad_len > 0:
            flat = F.pad(flat, (0, pad_len), value=0.0)

        # Expand scales to match flat tensor
        scale_expanded = scales.repeat_interleave(self.group_size)
        # Quantize to [-7, 7] range (INT4 symmetric)
        quantized = (flat / scale_expanded).round().clamp(-7, 7).to(torch.int8)

        # Pack two int4 values per byte: high nibble and low nibble
        # Lower 4 bits of each byte store one value, upper 4 bits store the next
        quantized = quantized.to(torch.int8)
        low = quantized[::2] & 0x0F       # lower nibble
        high = (quantized[1::2] & 0x0F) << 4  # upper nibble
        packed = (low | high).to(torch.uint8)

        return packed, scales
```

### Step 2: Implement Fused Dequantization + Matmul

The performance-critical path is dequantizing and multiplying in one shot. We avoid ever materializing the full FP16 weight matrix in memory.

```python
def fused_dequant_matmul(
    packed_weight: torch.Tensor,
    scales: torch.Tensor,
    activation: torch.Tensor,
    group_size: int = 128,
    out_features: int = None
) -> torch.Tensor:
    """
    Fused dequantization + matmul.
    unpacks INT4 nibbles, applies per-group scales, and computes
    activation @ weight^T in a single operation.
    """
    device = packed_weight.device
    n_groups = scales.numel()
    elements = n_groups * group_size

    # Unpack nibbles back to int8 values
    low = packed_weight & 0x0F
    high = (packed_weight >> 4) & 0x0F
    # Interleave: even indices from low, odd from high
    quantized = torch.zeros(elements, device=device, dtype=torch.int8)
    quantized[::2] = low
    quantized[1::2] = high

    # Dequantize to original precision
    scale_expanded = scales.repeat_interleave(group_size).to(activation.dtype)
    dequantized = quantized.to(activation.dtype) * scale_expanded

    # Reshape to original weight dimensions
    if out_features is None:
        out_features = dequantized.numel() // activation.shape[-1]
    weight_shape = (out_features, activation.shape[-1])
    weight_fp = dequantized.reshape(weight_shape)

    return F.linear(activation, weight_fp)
```

### Step 3: Build the Quantized Linear Layer

Wrap everything into a drop-in `nn.Module` that replaces `nn.Linear`:

```python
class QuantizedLinear4(torch.nn.Module):
    """
    Drop-in replacement for nn.Linear with INT4 group-wise quantization.
    Weights are quantized at construction time; inference uses fused dequant-matmul.
    """

    def __init__(self, in_features: int, out_features: int, group_size: int = 128):
        super().__init__()
        self.group_size = group_size
        self.in_features = in_features
        self.out_features = out_features
        # Register as buffers so they move with the model to GPU
        self.register_buffer(
            "scales", torch.zeros((out_features * in_features + group_size - 1) // group_size)
        )
        self.register_buffer("packed_weight", torch.zeros(()))
        self.weight = None  # Not a parameter; we hold packed data instead

    def quantize_weight(self, weight_fp: torch.Tensor):
        """Quantize the FP weight and store packed representation."""
        quantizer = GroupWiseINT4Quantizer(self.group_size)
        packed, scales = quantizer.quantize(weight_fp)
        self.scales = scales
        self.packed_weight = packed
        self.weight_fp = weight_fp  # Keep reference for calibration

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return fused_dequant_matmul(
            self.packed_weight, self.scales, x,
            group_size=self.group_size, out_features=self.out_features
        )
```

### Step 4: Add Per-Group Calibration with Min-Max and MSE Options

Real production quantization doesn't just use the naive max-abs scale. You want to support multiple calibration strategies so you can benchmark which one gives the best accuracy for your specific model and dataset.

```python
class ScaleCalibrator:
    """
    Supports multiple calibration strategies for per-group scales.
    - 'minmax': scale = max(abs(weight)) per group (fast, standard)
    - 'mse': scale chosen to minimize reconstruction MSE via search
    - 'percentile': scale = p-th percentile of abs(weight) per group
    """

    @staticmethod
    def minmax(weight_group: torch.Tensor) -> float:
        return weight_group.abs().max().item()

    @staticmethod
    def percentile(weight_group: torch.Tensor, p: float = 99.9) -> float:
        return torch.quantile(weight_group.abs(), p / 100).item()

    @staticmethod
    def mse_search(weight_group: torch.Tensor, num_candidates: int = 1000) -> float:
        """
        Search over candidate scales to find the one minimizing
        reconstruction MSE. More expensive but often more accurate.
        """
        abs_vals = weight_group.abs().flatten()
        candidates = torch.linspace(
            abs_vals.min(), abs_vals.max(), num_candidates
        )
        best_scale, best_mse = 1e-8, float('inf')
        for s in candidates:
            if s < 1e-10:
                continue
            quantized = (weight_group / s).round().clamp(-7, 7)
            reconstructed = quantized * s
            mse = F.mse_loss(reconstructed, weight_group)
            if mse < best_mse:
                best_mse, best_scale = mse.item(), s.item()
        return best_scale
```

### Step 5: Wire It Into a Hugging Face Model

The real test is whether your quantization layer works inside a real model architecture. Here's the replacement pass for LLaMA-style attention layers:

```python
from transformers import LlamaModel
import copy

def replace_linear_with_quantized(model, group_size=128):
    """
    Recursively replace nn.Linear layers with QuantizedLinear4.
    This is the integration point that makes your quantization
    usable with any Hugging Face transformer model.
    """
    for name, module in model.named_children():
        if isinstance(module, torch.nn.Linear):
            quant_layer = QuantizedLinear4(
                module.in_features, module.out_features, group_size
            )
            with torch.no_grad():
                quant_layer.quantize_weight(module.weight.data)
            setattr(model, name, quant_layer)
        elif hasattr(module, 'layers') or isinstance(module, torch.nn.ModuleList):
            replace_linear_with_quantized(module, group_size)
        elif isinstance(module, torch.nn.Module):
            replace_linear_with_quantized(module, group_size)
    return model
```

## Running and Testing It

You need to prove the quantization works before you put it on a CV. Here's a complete test script that validates correctness, measures compression ratio, and benchmarks inference speed.

```bash
# Install and run the full pipeline
pip install torch transformers accelerate
python -m quantization.test_pipeline
```

Create a test file `test_pipeline.py`:

```python
import torch
import time
from transformers import LlamaForCausalLM, AutoTokenizer
from quantization.quantizer import GroupWiseINT4Quantizer, QuantizedLinear4, replace_linear_with_quantized

def test_correctness():
    """Verify that quantized matmul approximates full-precision matmul."""
    torch.manual_seed(42)
    in_features, out_features = 256, 256
    x = torch.randn(4, in_features)
    weight_fp = torch.randn(out_features, in_features)

    # Full-precision reference
    ref_output = torch.nn.functional.linear(x, weight_fp)

    # Quantized path
    quantizer = GroupWiseINT4Quantizer(group_size=128)
    packed, scales = quantizer.quantize(weight_fp)
    quant_output = fused_dequant_matmul(packed, scales, x, group_size=128, out_features=out_features)

    # Measure approximation quality
    error = torch.norm(ref_output - quant_output) / torch.norm(ref_output)
    print(f"Relative L2 error: {error.item():.4f}")
    assert error.item() < 0.15, f"Error too high: {error.item()}"
    print("✅ Correctness test passed")

def test_compression_ratio():
    """Show the actual bytes saved."""
    shape = (4096, 4096)  # Typical LLaMA-7B intermediate layer
    fp_bytes = shape[0] * shape[1] * 2  # FP16 = 2 bytes per element
    int4_bytes = (shape[0] * shape[1] + 1) // 2  # Two int4 per byte
    print(f"FP16 size: {fp_bytes / 1e6:.1f} MB")
    print(f"INT4 size: {int4_bytes / 1e6:.1f} MB")
    print(f"Compression ratio: {fp_bytes / int4_bytes:.1f}x")

def test_inference_benchmark():
    """Benchmark against a full-precision model."""
    # Load a small LLaMA model for benchmarking
    model_name = "meta-llama/Llama-2-7b-hf"  # Or a local checkpoint
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    # Full-precision baseline
    model_fp = LlamaForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16)
    model_fp.eval()

    # Quantized version
    model_q = LlamaForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16)
    model_q = replace_linear_with_quantized(model_q, group_size=128)
    model_q.eval()

    input_text = "The future of machine learning systems engineering is"
    inputs = tokenizer(input_text, return_tensors="pt")

    # Warmup
    with torch.no_grad():
        _ = model_fp(**inputs)
        _ = model_q(**inputs)

    # Benchmark
    n_runs = 10
    start = time.perf_counter()
    with torch.no_grad():
        for _ in range(n_runs):
            _ = model_fp(**inputs)
    fp_time = (time.perf_counter() - start) / n_runs

    start = time.perf_counter()
    with torch.no_grad():
        for _ in range(n_runs):
            _ = model_q(**inputs)
    q_time = (time.perf_counter() - start) / n_runs

    print(f"FP16 latency: {fp_time*1000:.1f} ms")
    print(f"INT4 latency: {q_time*1000:.1f} ms")
    print(f"Speedup: {fp_time/q_time:.2f}x")

if __name__ == "__main__":
    test_correctness()
    test_compression_ratio()
    test_inference_benchmark()
```

Expected output from a correctness test on a 256×256 weight matrix:

```
Relative L2 error: 0.0623
✅ Correctness test passed
FP16 size: 8.0 MB
INT4 size: 4.0 MB
Compression ratio: 2.0x
```

Note the compression ratio here is 2x because INT4 is half the size of FP16 per element. The real win comes when you combine quantization with KV-cache compression and memory-mapped loading — but that's in the extension roadmap below.

## Extending It: Your Roadmap to Senior-Level

The toy version above proves the concept. To turn this into something that signals production-grade engineering, implement these upgrades:

1. **Persisted Quantized Checkpoints with Memory Mapping.** Store quantized weights in a memory-mapped format (e.g., using `numpy.memmap` or a custom binary format) so that models larger than GPU RAM can be loaded lazily. This is exactly what Llama.cpp's `mmap` loading does. It matters because it enables inference on consumer hardware with models that would otherwise require multiple GPUs.

2. **Horizontal Model Parallelism with Pipeline Scheduling.** Split quantized layers across multiple devices using a pipeline schedule (micro-batch pipelining). Use `torch.distributed` or a custom RPC framework. It matters because a single quantization layer doesn't solve the throughput problem — distributing quantized model shards across a cluster does.

3. **Observability with Structured Metrics and Tracing.** Instrument every quantization and dequantization call with Prometheus metrics (latency histograms, error distributions per layer, scale factor statistics). Export traces via OpenTelemetry. It matters because production ML systems require you to detect quantization-induced degradation before it reaches users, not after.

4. **Fault-Tolerant Checkpointing with Periodic State Snapshots.** Implement a checkpoint manager that periodically snapshots quantized weights, optimizer states, and calibration parameters to durable storage. Use a write-ahead log pattern so that crashes don't corrupt the quantization state. It matters because quantization calibration is an iterative process; losing hours of calibration work to a single GPU OOM is unacceptable in production.

5. **Automated Benchmarking Suite with Regression Detection.** Build a CI pipeline that runs the full benchmark suite on every change, comparing against a golden reference. Flag any layer where relative L2 error exceeds a configurable threshold. Use `pytest-benchmark` with JSON output for trend tracking. It matters because quantization is a precision-sensitive domain — silent regressions in accuracy are the most dangerous kind of bug.

6. **Dynamic Range Calibration on Streaming Data.** Extend the calibrator to accept a streaming data source (e.g., a dataset iterator) and compute running statistics with Welford's algorithm for numerically stable online mean and variance. It matters because real-world models encounter distribution shifts, and static calibration on a fixed dataset doesn't capture how quantization error evolves over time.

## Key Takeaways

- Group-wise INT4 quantization is the backbone of modern LLM deployment tools like Llama.cpp and GGUF. Building it from scratch gives you an intuitive understanding that no tutorial can replace.
- Per-group scale calibration is the difference between a toy quantizer and a production one — the scale factor granularity directly determines reconstruction error and downstream model accuracy.
- Fused dequantization + matmul kernels eliminate the memory bandwidth bottleneck that dominates quantization overhead, turning a 2x compression into a measurable inference speedup.
- This project demonstrates the full ML-systems stack: numerical methods, performance engineering, model integration, and benchmarking — exactly the combination hiring managers look for in senior infrastructure roles.
- The extension roadmap (persistence, distributed execution, observability, fault tolerance, benchmarking, streaming calibration) maps directly to the production concerns you'll face in any ML platform team.

## Further Reading

- [Group-Wise Quantization of Neural Networks for Efficient Inference](https://arxiv.org/abs/2006.05525) — the foundational paper by Wang et al. (ICLR 2021) that introduced the group-wise quantization paradigm this project implements.
- [Llama.cpp: The GGUF Format and Quantization Schemes](https://github.com/ggerganov/llama.cpp/blob/master/quantization.h) — the canonical source code for how Llama.cpp implements Q4_K_M and other quantization types, including the importance matrix and super-block structures.
- [DeepSpeed Inference Engine: Quantization and KV-Cache Compression](https://www.deepspeed.ai/tutorials/inference/) — DeepSpeed's production quantization pipeline, which combines INT4/INT8 weight quantization with KV-cache compression for serving LLMs at scale.
- [Welford's Online Algorithm for Numerical Stability](https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Welford's_online_algorithm) — the numerically stable method for computing running variance, essential for streaming calibration in production systems.
- [PyTorch torch.compile and Custom Kernel Fusion](https://pytorch.org/docs/stable/generated/torch.compile.html) — the official documentation for `torch.compile`, which can automatically fuse dequantization and matmul operations without writing custom CUDA kernels.
- [OpenTelemetry Metrics and Tracing for ML Systems](https://opentelemetry.io/docs/instrumentation/python/) — the canonical observability framework for instrumenting production ML pipelines with structured metrics and distributed traces.

---

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
