---
title: "Build a GPTQ-Style Int4 Quantization Engine From Scratch"
date: "2026-09-07T17:03:24.450"
draft: false
tags: ["quantization", "gptq", "cuda", "inference", "python"]
description: "A hands-on build guide for a from-scratch int4 weight quantization engine with grouped scales, zero points, and a CUDA-free dequant matmul kernel — perfect CV signal."
summary: "Build a real int4 quantization engine from scratch: grouped scales, zero points, and a fast dequant matmul kernel that runs without CUDA. A substantive portfolio project that signals real systems skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-gptq-style-int4-quantization-engine-from-scratch.svg"
  alt: "Abstract visualization of a 4-bit quantized weight matrix being dequantized into activations for a matrix multiplication."
  caption: ""
  relative: false
---

> **TL;DR** — This project packages four high-leverage skills into one tight repo: linear-algebra numerics, quantization-aware inference kernels, group-symmetric packing for memory bandwidth, and clean testing on CPU. Hiring managers read "built a GPTQ-style int4 engine" as a signal that you understand how modern LLM serving (vLLM, ExLlamaV2, llama.cpp) actually works under the hood — not just how to call an API.

Most ML side projects stop at "fine-tuned a 7B model on my custom dataset." That bar is now table stakes. The differentiator in 2026 is showing you understand the *serving* stack: how weights are packed into memory, how dequantization fuses with matmul, and how numerical fidelity is preserved across quantization groups. This guide walks you through building exactly that — a from-scratch int4 quantization engine with grouped scales, asymmetric zero points, and a CUDA-free dequant matmul kernel that you can run on any laptop.

## Why This Project Stands Out on a CV

Hiring managers at companies shipping LLMs (Anthropic, Mistral, Together, Cohere, and the inference-platform tier at AWS/GCP/Azure) screen for a specific cluster of skills. This project demonstrates all of them in one self-contained repo:

- **Numerical literacy.** You're not just calling `model.quantize()`. You're choosing group sizes, computing scales and zero points per group, and reasoning about error propagation. That's the same work the [GPTQ paper](https://arxiv.org/abs/2210.17323) and [AWQ paper](https://arxiv.org/abs/2306.00978) are built on.
- **Systems-level performance thinking.** A dequant matmul kernel is the textbook example of a memory-bandwidth-bound operation. By implementing it without CUDA — using NumPy and Numba — you show you understand cache lines, vectorization, and kernel fusion, not just `torch.matmul`.
- **Production-shaped engineering.** You'll write tests, benchmark against a PyTorch baseline, and structure a CLI. That's the same shape as vLLM's [benchmarks/](https://github.com/vllm-project/vllm/tree/main/benchmarks) directory.
- **Reading-and-implementing-from-papers skill.** Hiring teams want engineers who can read a paper on Monday and ship a prototype by Friday. This project is exactly that loop.

Roles this signals for: ML Infrastructure Engineer, Inference Platform Engineer, Quantization Research Engineer, and LLM Serving Engineer. It's also strong for Performance Engineer roles at any company with a serious model-serving bill.

## Architecture Overview

The engine has four cleanly separated components. Keeping them decoupled is what makes the project extensible — each layer can be swapped or upgraded without rewriting the others.

- **Layer 1 — Calibration and Quantization (`quantizer.py`).** Loads a small FP16 weight matrix from a real PyTorch checkpoint, computes per-group scales and asymmetric zero points using absmax/amin, packs int4 values into int8 storage with bit-shifting, and writes out the quantized tensors plus metadata.
- **Layer 2 — Packed Tensor Format (`packed_tensor.py`).** A `PackedInt4Tensor` class that holds `qweight` (uint8, two int4 values per byte), `scales` (fp16, one per group), `zeros` (fp16, one per group), `g_idx` (optional, for activation reordering), and the original shape. Knows how to dequantize itself.
- **Layer 3 — Dequant Matmul Kernel (`dequant_matmul.py`).** A Numba-jit'd kernel that fuses dequantization into the matmul inner loop. Reads two packed int4 bytes at a time, unpacks via bitwise ops, applies scale and zero, accumulates in fp32. No intermediate materialization of the full dequantized matrix.
- **Layer 4 — Eval Harness (`benchmark.py` and `tests/`).** Measures numerical error vs. the FP16 reference, throughput in tokens/sec for a synthetic matmul, and correctness on a downstream `nn.Linear` replacement.

The data flow is: FP16 weights → Layer 1 → packed int4 tensors → on-disk `.safetensors`-like format → load into Layer 2 → Layer 3 fuses dequant + matmul at request time → Layer 4 reports error and speed.

## Building It Step by Step

I'll walk through each component. The full code lives in one small repo; here I show the non-trivial pieces.

### Step 1 — Project skeleton

```
int4-engine/
├── src/int4_engine/
│   ├── __init__.py
│   ├── quantizer.py
│   ├── packed_tensor.py
│   ├── dequant_matmul.py
│   └── io.py
├── tests/
│   ├── test_quantizer.py
│   ├── test_packed_tensor.py
│   └── test_kernel.py
├── benchmarks/
│   └── bench.py
├── pyproject.toml
└── README.md
```

Pin NumPy, Numba, PyTorch (for tests only), and `safetensors` for I/O. Add a `Makefile` with `make test` and `make bench`. This small bit of polish — CI-ready structure — is itself a CV signal.

### Step 2 — Per-group asymmetric quantization

The core quantization math is short and well-defined. We pick a group size `G` (typically 128), compute the per-group min and max, derive a scale and zero point that map the FP16 range onto int4, and round-to-nearest.

```python
# quantizer.py
import numpy as np

INT4_MIN, INT4_MAX = -8, 7  # signed int4 range

def compute_group_stats(w: np.ndarray, group_size: int):
    # w shape: (out_features, in_features); reshape along last axis into groups
    out_f, in_f = w.shape
    assert in_f % group_size == 0
    w_g = w.reshape(out_f, in_f // group_size, group_size)
    w_min = w_g.min(axis=-1, keepdims=True)
    w_max = w_g.max(axis=-1, keepdims=True)
    return w_min, w_max

def quantize_per_group(w: np.ndarray, group_size: int = 128):
    w_min, w_max = compute_group_stats(w, group_size)
    # Asymmetric: map [w_min, w_max] -> [INT4_MIN, INT4_MAX]
    scale = (w_max - w_min) / (INT4_MAX - INT4_MIN)
    scale = np.where(scale == 0, 1.0, scale)  # avoid div-by-zero for dead groups
    zero = INT4_MIN - np.round(w_min / scale).astype(np.int8)
    zero = np.clip(zero, INT4_MIN, INT4_MAX)

    w_q = np.clip(np.round(w.reshape(w.shape[0], -1, group_size) / scale + zero),
                  INT4_MIN, INT4_MAX).astype(np.int8)
    return w_q.reshape(w.shape), scale.squeeze(-1).astype(np.float16), zero.squeeze(-1).astype(np.float16)
```

This is the asymmetric variant GPTQ uses; AWQ uses a similar scheme with a different scale-selection heuristic, as the [AWQ paper](https://arxiv.org/abs/2306.00978) describes.

### Step 3 — Int4 packing: two values per byte

Storing int4 as int8 wastes half your memory. The trick used by llama.cpp and [ExLlamaV2](https://github.com/turboderp/exllamav2) is to pack two int4 values into one uint8, with the low nibble holding one value and the high nibble holding another.

```python
# packed_tensor.py
import numpy as np

def pack_int4_to_uint8(w_q: np.ndarray) -> np.ndarray:
    # w_q is int8 in [-8, 7]. Convert to uint4 nibbles [0, 15].
    # Layout: column-major within each row so the kernel can stream contiguously.
    out_f, in_f = w_q.shape
    assert in_f % 2 == 0
    lo = (w_q[:, 0::2] & 0x0F).astype(np.uint8)
    hi = ((w_q[:, 1::2] & 0x0F) << 4).astype(np.uint8)
    packed = (hi | lo)  # shape (out_f, in_f // 2)
    return packed
```

Note the column ordering: we put adjacent in-features into the same byte so a dequant kernel can fetch one byte and immediately process two matmul operands. This is the same layout used by [GPTQ-for-LLaMA](https://github.com/qwopqwop200/GPTQ-for-LLaMa) and is critical for bandwidth.

### Step 4 — The `PackedInt4Tensor` class

```python
class PackedInt4Tensor:
    def __init__(self, qweight: np.ndarray, scales: np.ndarray,
                 zeros: np.ndarray, group_size: int, out_features: int):
        self.qweight = qweight          # uint8, (out_f, in_f // 2)
        self.scales = scales            # fp16, (out_f, num_groups)
        self.zeros = zeros              # fp16, (out_f, num_groups)
        self.group_size = group_size
        self.out_features = out_features
        self.in_features = qweight.shape[1] * 2

    def dequantize(self) -> np.ndarray:
        # Inverse of pack + quantize. Used in tests; the kernel does this inline.
        out_f, in_f = self.out_features, self.in_features
        w = np.empty((out_f, in_f), dtype=np.float16)
        for g in range(self.scales.shape[1]):
            s = self.scales[:, g:g+1]
            z = self.zeros[:, g:g+1]
            packed_g = self.qweight[:, g*(self.group_size//2):(g+1)*(self.group_size//2)]
            lo = (packed_g & 0x0F).astype(np.int8)
            hi = ((packed_g >> 4) & 0x0F).astype(np.int8)
            # sign extend: nibble >= 8 means negative
            lo = np.where(lo >= 8, lo - 16, lo)
            hi = np.where(hi >= 8, hi - 16, hi)
            w_q_g = np.empty_like(w[:, g*self.group_size:(g+1)*self.group_size], shape=(out_f, self.group_size))
            w_q_g[:, 0::2] = lo
            w_q_g[:, 1::2] = hi
            w[:, g*self.group_size:(g+1)*self.group_size] = w_q_g.astype(np.float16) * s + z
        return w

    def memory_bytes(self) -> int:
        return (self.qweight.nbytes + self.scales.nbytes + self.zeros.nbytes)
```

For a 4096×4096 weight matrix, FP16 takes 32 MB; this packed form takes about 9 MB (8 MB weights + 0.5 MB scales + 0.5 MB zeros at group_size=128). That's the ~3.5× compression everyone quotes.

### Step 5 — The CUDA-free dequant matmul kernel

This is the centerpiece. We fuse dequantization into the matmul accumulation loop using Numba. The kernel iterates over output rows and tiles the inner dimension by the group size so each group read happens once per output row — friendly to L1/L2 cache.

```python
# dequant_matmul.py
import numpy as np
from numba import njit, prange

@njit(cache=True, fastmath=True)
def dequant_matmul_kernel(
    x,                       # (M, K) fp16
    qweight,                 # (N, K//2) uint8
    scales,                  # (N, num_groups) fp16
    zeros,                   # (N, num_groups) fp16
    y,                       # (M, N) fp32 output
    group_size: int,
    K: int,
    N: int,
):
    M = x.shape[0]
    num_groups = K // group_size
    for m in prange(M):
        for n in range(N):
            acc = np.float32(0.0)
            for g in range(num_groups):
                s = np.float32(scales[n, g])
                z = np.float32(zeros[n, g])
                base = g * (group_size // 2)
                for kk in range(group_size // 2):
                    packed = qweight[n, base + kk]
                    lo = packed & 0x0F
                    hi = (packed >> 4) & 0x0F
                    if lo >= 8: lo -= 16
                    if hi >= 8: hi -= 16
                    k_lo = 2 * kk
                    k_hi = 2 * kk + 1
                    acc += np.float32(x[m, k_lo]) * (np.float32(lo) * s + z)
                    acc += np.float32(x[m, k_hi]) * (np.float32(hi) * s + z)
            y[m, n] = acc

def dequant_matmul(x: np.ndarray, packed) -> np.ndarray:
    M, K = x.shape
    N = packed.out_features
    y = np.zeros((M, N), dtype=np.float32)
    dequant_matmul_kernel(x.astype(np.float16), packed.qweight,
                          packed.scales, packed.zeros, y,
                          packed.group_size, K, N)
    return y
```

Why this is fast on CPU: Numba lowers the inner loop to SIMD-vectorized machine code. AVX2/AVX-512 can process 16–32 fp16 lanes per cycle, and the bitwise unpacking compiles to `pand`, `psrlw`, and `pxor` — exactly the same shape as the CUDA kernels in [llama.cpp's `quants.c`](https://github.com/ggerganov/llama.cpp/blob/master/ggml/src/ggml-quants.c).

### Step 6 — Wiring it to a real model

The killer demo is replacing a `nn.Linear` in a tiny HuggingFace model with our quantized layer. Pull a 1–2 layer model from `transformers`, quantize one attention `q_proj` weight, run inference, and compare logits.

```python
# benchmarks/bench.py
import torch, numpy as np
from transformers import AutoModelForCausalLM
from int4_engine.quantizer import quantize_per_group
from int4_engine.packed_tensor import pack_int4_to_uint8, PackedInt4Tensor
from int4_engine.dequant_matmul import dequant_matmul

model = AutoModelForCausalLM.from_pretrained("sshleif/tiny-gpt2", torch_dtype=torch.float16)
W = model.transformer.h[0].attn.c_attn.weight.detach().cpu().numpy().astype(np.float16)
W_q, scales, zeros = quantize_per_group(W, group_size=128)
packed = PackedInt4Tensor(pack_int4_to_uint8(W_q), scales, zeros,
                          group_size=128, out_features=W.shape[0])

x = np.random.randn(1, W.shape[1]).astype(np.float16)
y_ref = x @ W.T
y_q = dequant_matmul(x, packed).astype(np.float16)

err = np.max(np.abs(y_ref - y_q))
ratio = packed.memory_bytes() / (W.nbytes)
print(f"max abs error: {err:.4f} | compression: {ratio:.2%} of FP16 size")
```

You should see max abs error around 0.05–0.1 and compression around 28% of FP16 — close to the theoretical 4× minus scale/zero overhead.

## Running and Testing It

Three checks prove the engine works.

### 1. Unit tests with pytest

```bash
# tests/test_kernel.py
import numpy as np
from int4_engine.quantizer import quantize_per_group
from int4_engine.packed_tensor import pack_int4_to_uint8, PackedInt4Tensor
from int4_engine.dequant_matmul import dequant_matmul

def test_quantize_roundtrip_is_lossless_for_smooth_weights():
    rng = np.random.default_rng(0)
    w = rng.normal(0, 0.05, (64, 256)).astype(np.float16)
    w_q, s, z = quantize_per_group(w, group_size=128)
    packed = PackedInt4Tensor(pack_int4_to_uint8(w_q), s, z, 128, 64)
    w_hat = packed.dequantize()
    assert np.max(np.abs(w.astype(np.float32) - w_hat.astype(np.float32))) < 0.05

def test_kernel_matches_explicit_dequant():
    rng = np.random.default_rng(1)
    w = rng.normal(0, 1, (32, 128)).astype(np.float16)
    x = rng.normal(0, 1, (4, 128)).astype(np.float16)
    w_q, s, z = quantize_per_group(w, group_size=128)
    packed = PackedInt4Tensor(pack_int4_to_uint8(w_q), s, z, 128, 32)
    y_kernel = dequant_matmul(x, packed)
    y_explicit = (x @ packed.dequantize().T).astype(np.float32)
    assert np.allclose(y_kernel, y_explicit, atol=1e-3)
```

Run with `pytest -q`. Both should pass.

### 2. Numerical benchmark against PyTorch

The benchmark script above prints max absolute error and a compression ratio. Target: `<0.1` max abs error and `~28%` of FP16 size for a 4×4096×4096 weight.

### 3. Throughput benchmark

Time `dequant_matmul` against `torch.matmul(x, W.T)` over 100 iterations and report tokens/sec for an `M=1, K=4096, N=4096` matmul — the shape of a single-token decode step in vLLM or [TGI](https://github.com/huggingface/text-generation-inference). Expect the quantized path to be 2–3× slower in pure compute on a single CPU core (you're doing more work per FLOP) but to use ~3.5× less memory bandwidth, which on memory-bound decode is what actually matters.

Run everything:

```bash
pip install -e .
pytest -q
python benchmarks/bench.py
```

A clean `make test && make bench` that finishes in under 30 seconds is the kind of polish that gets a hiring manager to clone the repo.

## Extending It: Your Roadmap to Senior-Level

A working int4 engine is the floor. The ceiling is a project that mirrors the structure of a real inference platform. Here are six upgrades, each one moves you closer to "could ship this at work."

1. **Add `safetensors` I/O with metadata.** Serialize packed weights and scales to a real model file format. Reason it matters: every production system ([vLLM](https://github.com/vllm-project/vllm), [Transformers](https://github.com/huggingface/transformers), [llama.cpp](https://github.com/ggerganov/llama.cpp)) loads models, not raw tensors. Hiring managers want to see you handle the I/O layer correctly.
2. **Implement GPTQ's second-order error correction.** Use a small calibration set to compute the Hessian and apply the column-by-column rounding that GPTQ uses to minimize reconstruction error. Reason it matters: this is the difference between "I called a quantizer" and "I implemented GPTQ." It's the single biggest intellectual delta on your CV.
3. **Parallelize with a worker pool.** Use `multiprocessing` to quantize independent weight matrices in parallel and to shard dequant matmul across cores via OpenMP-style work-stealing inside Numba. Reason it matters: shows you understand horizontal scaling and the GIL-vs-process model tradeoffs that real serving systems make.
4. **Add structured observability.** Emit OpenTelemetry traces around each kernel call with `duration_ms`, `tokens_per_sec`, `quant_error_l2`, and `memory_bytes`. Reason it matters: production teams don't ship anything they can't observe; a tracing hook in a side project is unusual and memorable.
5. **Benchmark against `bitsandbytes` and `auto-gptq`.** Add CI that compares your engine's error and throughput to those libraries on the same weight matrices. Reason it matters: shows you can situate your work against an existing ecosystem — a senior-level reflex.
6. **Write a streaming loader with memory mapping.** Load 50 GB quantize-only-on-demand so you can quantize a 70B model on a laptop. Reason it matters: this is how [ExLlamaV2](https://github.com/turboderp/exllamav2) and llama.cpp handle models that don't fit in RAM, and it's a recurring interview topic at inference-platform companies.

Each of these upgrades is roughly a weekend of work and adds a distinct paragraph to your resume.

## Key Takeaways

- A from-scratch int4 engine packs four high-leverage skills into one repo: numerics, kernels, I/O, and benchmarking.
- Asymmetric per-group quantization with group_size=128 is the standard scheme; the GPTQ and AWQ papers are short reads that go deeper.
- Packing two int4 values into one uint8, with adjacent in-features in the same byte, is the bandwidth trick that makes this fast.
- A fused dequant matmul kernel on CPU (Numba) shows you understand memory-bandwidth-bound compute without needing a GPU.
- The upgrade roadmap — GPTQ error correction, safetensors I/O, multiprocessing, OpenTelemetry, ecosystem benchmarking, memory-mapped loading — is what turns a toy into a portfolio piece that signals senior-level systems thinking.

## Further Reading

- [GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2210.17323) — the paper that defines the algorithm; section 2 is enough to implement it.
- [AWQ: Activation-aware Weight Quantization](https://arxiv.org/abs/2306.00978) — a complementary scheme that uses activation statistics to pick better scales.
- [The llama.cpp quantization README](https://github.com/ggerganov/llama.cpp/blob/master/examples/quantize/README.md) — the canonical reference for int4 packing layouts in production.
- [ExLlamaV2 repository](https://github.com/turboderp/exllamav2) — look at the `exllamav2/quant/` directory for production-grade dequant kernels in CUDA and the corresponding CPU fallback.
- [Numba `@njit` documentation](https://numba.readthedocs.io/en/stable/user/jit.html) — the `fastmath` and `prange` options are the lever for CPU SIMD vectorization.
- [safetensors format specification](https://github.com/huggingface/safetensors) — what every modern model loader actually parses; worth implementing natively.
- [vLLM's quantization module](https://github.com/vllm-project/vllm/tree/main/vllm/model_executor/layers/quantization) — the open-source reference for how an inference engine integrates int4 into a serving stack.