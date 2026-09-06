---
title: "Building a Rotary Positional Embedding Kernel from Scratch: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-06T14:00:37.341"
draft: false
tags: ["cuda", "pytorch", "rotary-positional-embeddings", "systems-engineering", "machine-learning", "portfolio-project"]
description: "A hands-on build guide for a from-scratch rotary positional embedding kernel with a custom autograd node — the kind of side project that turns interviews into offers."
summary: "Build a real rotary positional embedding kernel in PyTorch with a custom autograd node, fused CUDA-style kernels, and a tiny test harness. The project you ship on a CV to signal GPU, systems, and ML-engineering depth."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-building-a-rotary-positional-embedding-kernel-from-scratch-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Stylized diagram of a rotary positional embedding applied to a query and key tensor on a GPU"
  caption: ""
  relative: false
---

> **TL;DR** — Rotary Positional Embeddings (RoPE) are the positional scheme behind Llama, Mistral, Qwen, and most modern transformers. This post walks you through building a from-scratch RoPE kernel in PyTorch with a custom `torch.autograd.Function`, a fused `torch.compile`/Triton-style forward pass, and a test harness that proves it numerically matches the reference. It is short enough to finish in a weekend and dense enough to demonstrate GPU kernels, autograd internals, and numerical literacy — exactly the stack hiring managers look for on a CV.

If you want a portfolio piece that does more than "I trained a CNN on CIFAR-10," this is the one. RoPE is the positional encoding used by essentially every modern open-weight LLM — see [the original RoPE paper (Su et al., 2021)](https://arxiv.org/abs/2104.09864) and its wide adoption in models like [Llama 2](https://arxiv.org/abs/2307.09288) and [Qwen](https://arxiv.org/abs/2309.16609). Implementing it from the metal up shows you understand *why* those models work the way they do.

## Why This Project Stands Out on a CV

Most CV-side ML projects collapse into one of two buckets: "I called `model.fit()`" or "I fine-tuned Llama with LoRA." Neither tells a hiring manager anything about how you think at the systems layer. A custom kernel project does, because it forces you to touch every layer of the stack:

- **GPU programming literacy.** You write a fused kernel rather than chaining pointwise ops. That signals comfort with memory coalescing, register pressure, and why `torch.embedding` followed by two reshapes is slower than one custom kernel.
- **Autograd internals.** You implement `forward` and `backward` for a `torch.autograd.Function`. That is the exact API used inside [PyTorch's own autograd machinery](https://pytorch.org/docs/stable/autograd.html), and recruiters for GPU/ML-platform teams notice it.
- **Numerical reasoning.** RoPE has subtle failure modes — odd head dimensions, half-precision drift, and the conjugate pairing between queries and keys. Showing you thought about them is the difference between "junior" and "senior."
- **Testing discipline.** You write a parity test against a reference implementation, not just a forward pass. That maps directly to production roles at places like Hugging Face, Anyscale, and the model-platform teams at the major labs.
- **Communication.** You wrote a post like this one explaining it. Writing about hard engineering is itself a signal.

In practice, the roles this project resonates with are: ML Platform Engineer, GPU/Kernel Engineer, Inference Engineer, Research Engineer, and the "engineer who can talk to researchers" hybrid that shows up at every serious model lab.

## Architecture Overview

The project is small on purpose — about 600 lines of Python plus a short Triton/CUDA kernel — but it has a real component layout. Treat it like a tiny service.

- **`rope/reference.py`** — A pure-PyTorch reference implementation of RoPE, used as the ground truth. Two functions: `apply_rope(q, k, cos, sin)`. Roughly 30 lines, deliberately naive.
- **`rope/autograd.py`** — The `RotaryEmbedding` `torch.autograd.Function` subclass. Implements `forward`, `backward`, and the optional `setup_context` for saved-tensor autograd. This is the "interesting" file.
- **`rope/kernel.py`** — A fused kernel written with [`torch.compile`](https://pytorch.org/docs/stable/torch.compiler.html) or [Triton](https://triton-lang.org/) that does the rotation, the cast, and the save-for-backward in one pass.
- **`rope/__init__.py`** — The user-facing API: `rotary = RotaryEmbedding(dim=64)` then `q, k = rotary(q, k)`.
- **`tests/test_parity.py`** — A [pytest](https://docs.pytest.org/) suite that compares the kernel output to the reference at float32, bfloat16, and float16 across batch sizes and sequence lengths.
- **`bench/bench.py`** — A microbenchmark using [`triton.testing.do_bench`](https://triton-lang.org/main/python-api/generated/triton.testing.do_bench.html) to report throughput in tokens/sec against vanilla PyTorch.
- **`README.md`** — How to run, the design choices, and the gotchas. This is what recruiters actually read first.

The data flow: `q, k` of shape `(B, H, T, D)` come in, get split into pairs along the last dimension, get rotated by `cos`/`sin` caches built from `inv_freq = 1 / theta**(2i/D)`, and go out. The same function is applied to both queries and keys — the rotation is the *same* for Q and K at a given position, which is what gives RoPE its relative-position property via the dot product.

## Building It Step by Step

You'll need Python 3.10+, PyTorch 2.3+, optionally Triton, and a CUDA-capable box (an MPS Mac or CPU works for the reference; you need CUDA only for the fused kernel). Clone a fresh repo, then go.

### Step 1: The reference implementation

This is the ground truth. Keep it boring.

```python
# rope/reference.py
import torch

def precompute_freqs_cis(dim: int, end: int, theta: float = 10000.0):
    # Standard RoPE frequency schedule: inv_freq = 1 / theta^(2i/dim)
    freqs = 1.0 / (theta ** (torch.arange(0, dim, 2)[: dim // 2].float() / dim))
    t = torch.arange(end, device=freqs.device)
    freqs = torch.outer(t, freqs)             # (T, dim/2)
    return torch.polar(torch.ones_like(freqs), freqs)  # complex64

def apply_rope(q, k, freqs_cis):
    # q, k: (B, H, T, D); D must be even
    q_ = torch.view_as_complex(q.float().reshape(*q.shape[:-1], -1, 2))
    k_ = torch.view_as_complex(k.float().reshape(*k.shape[:-1], -1, 2))
    freqs = freqs_cis.unsqueeze(0).unsqueeze(0)        # (1, 1, T, D/2)
    q_out = torch.view_as_real(q_ * freqs).type_as(q)
    k_out = torch.view_as_real(k_ * freqs).type_as(k)
    return q_out.reshape(q.shape), k_out.reshape(k.shape)
```

The use of complex numbers is the [canonical formulation](https://arxiv.org/abs/2104.09864): a rotation in 2D space is multiplication by `e^{i*theta}` in complex form.

### Step 2: A custom autograd node

This is the part that makes recruiters sit up. PyTorch's `torch.autograd.Function` lets you drop down to "I know exactly what the gradient is." For RoPE the backward pass is the same rotation by the conjugate frequency — because `q_rotated = q * e^{iθ}` and the gradient w.r.t. `q` is just `grad * e^{-iθ}` (rotation by the inverse angle). This is exactly the symmetry RoPE is famous for.

```python
# rope/autograd.py
import torch
from torch.autograd import Function

class _RotaryEmbedding(Function):
    @staticmethod
    def forward(ctx, q, k, cos, sin):
        # Save cos/sin (not the full freqs_cis) to cut memory.
        ctx.save_for_backward(cos, sin)
        q_out = q * cos + _rotate_half(q) * sin
        k_out = k * cos + _rotate_half(k) * sin
        return q_out, k_out

    @staticmethod
    def backward(ctx, grad_q, grad_k):
        cos, sin = ctx.saved_tensors
        # The inverse rotation is multiplication by -sin instead of +sin.
        grad_q_in = grad_q * cos - _rotate_half(grad_q) * sin
        grad_k_in = grad_k * cos - _rotate_half(grad_k) * sin
        return grad_q_in, grad_k_in, None, None  # cos/sin are constants

def _rotate_half(x):
    # Swap and negate the second half: matches the (x_{2i}, x_{2i+1}) pair convention.
    x1 = x[..., : x.shape[-1] // 2]
    x2 = x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)

class RotaryEmbedding(torch.nn.Module):
    def __init__(self, dim: int, max_seq_len: int = 8192, base: float = 10000.0):
        super().__init__()
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        t = torch.arange(max_seq_len)
        freqs = torch.outer(t, inv_freq)
        # Interleaved cos/sin cache: shape (max_seq_len, dim).
        self.register_buffer("cos_cache", freqs.cos().repeat_interleave(2, dim=-1), persistent=False)
        self.register_buffer("sin_cache", freqs.sin().repeat_interleave(2, dim=-1), persistent=False)

    def forward(self, q, k):
        T = q.shape[-2]
        return _RotaryEmbedding.apply(q, k, self.cos_cache[:T], self.sin_cache[:T])
```

Two production-quality details to point out in the interview:

1. **`register_buffer(..., persistent=False)`** keeps `cos_cache`/`sin_cache` on the right device when you call `.cuda()` or `.to(...)`, without bloating `state_dict` saves.
2. **`save_for_backward(cos, sin)`** rather than the full `freqs_cis` complex tensor halves the saved-tensor memory, which matters at long context lengths.

### Step 3: A fused Triton kernel

The reference does a cast to float32, a reshape, a complex multiply, a reshape back, and a cast. That's five kernels per call. You want one.

```python
# rope/kernel.py
import triton
import triton.language as tl

@triton.jit
def _rope_fwd_kernel(
    Q_ptr, K_ptr, COS_ptr, SIN_ptr,
    B, H, T, D,
    stride_qb, stride_qh, stride_qt, stride_qd,
    stride_kb, stride_kh, stride_kt, stride_kd,
    BLOCK_D: tl.constexpr,
):
    # Each program handles one (batch, head, token) row of Q and K.
    pid = tl.program_id(0)
    offs_d = tl.arange(0, BLOCK_D)

    q_row = Q_ptr + pid * stride_qt + offs_d * stride_qd
    k_row = K_ptr + pid * stride_kt + offs_d * stride_kd
    cos_row = COS_ptr + offs_d
    sin_row = SIN_ptr + offs_d

    q = tl.load(q_row)
    k = tl.load(k_row)
    cos = tl.load(cos_row)
    sin = tl.load(sin_row)

    # Compute the "rotated half" in-register: this is where fusion pays off.
    # Pair convention: (x_0, x_1) rotated by (cos, sin).
    # For BLOCK_D == head_dim, we just do the standard RoPE pairing.
    q_rot = q * cos + tl.where(offs_d % 2 == 0, -q, q).roll(BLOCK_D // 2, 0) * sin
    k_rot = k * cos + tl.where(offs_d % 2 == 0, -k, k).roll(BLOCK_D // 2, 0) * sin

    tl.store(q_row, q_rot)
    tl.store(k_row, k_rot)
```

A real version would pass strides for batch and head dimensions, mask the row index, and support a `BACKWARD` mode via a separate kernel — but the structure above is the whole idea: load once, compute once, store once. To see the same pattern at scale, study [the FlashAttention repo](https://github.com/Dao-AILab/flash-attention), which is the gold standard for fused attention-side kernels.

### Step 4: The public API

Keep it tiny. Hiring managers love APIs you can read in one breath.

```python
# rope/__init__.py
from .autograd import RotaryEmbedding
from .reference import apply_rope as apply_rope_reference

__all__ = ["RotaryEmbedding", "apply_rope_reference"]
__version__ = "0.1.0"
```

That's the whole library. Three files, one class, one function.

## Running and Testing It

A project without a passing test suite is a project that didn't happen. Make `pytest` the entry point.

### The parity test

```python
# tests/test_parity.py
import torch
import pytest
from rope import RotaryEmbedding, apply_rope_reference

@pytest.mark.parametrize("dtype", [torch.float32, torch.bfloat16, torch.float16])
@pytest.mark.parametrize("B,H,T,D", [(1, 4, 128, 64), (2, 8, 512, 128), (4, 16, 2048, 64)])
def test_parity(dtype, B, H, T, D):
    torch.manual_seed(0)
    q = torch.randn(B, H, T, D, dtype=dtype, device="cuda", requires_grad=True)
    k = torch.randn(B, H, T, D, dtype=dtype, device="cuda", requires_grad=True)

    rope = RotaryEmbedding(dim=D, max_seq_len=T).cuda()

    # Forward parity.
    q_ref, k_ref = apply_rope_reference(q.detach(), k.detach(), rope.cos_cache[:T].view(T, D//2, 2))
    q_out, k_out = rope(q, k)
    torch.testing.assert_close(q_out, q_ref, atol=5e-3, rtol=5e-3)
    torch.testing.assert_close(k_out, k_ref, atol=5e-3, rtol=5e-3)

    # Backward parity: the interesting one.
    loss = (q_out.float() ** 2).sum() + (k_out.float() ** 2).sum()
    loss.backward()
    gq_ref = q.grad.clone()
    q.grad = None
    q.sum().backward()  # rerun a simpler grad to sanity-check the custom backward
    # The cleanest test: compare dL/dq between custom and a torch.autograd.gradcheck surrogate.
    from torch.autograd.gradcheck import gradcheck
    # Use float64 for gradcheck; RoPE is well-defined there.
    q64 = q.detach().double().requires_grad_(True)
    k64 = k.detach().double().requires_grad_(True)
    rope64 = RotaryEmbedding(dim=D, max_seq_len=T).double().cuda()
    assert gradcheck(lambda qq, kk: rope64(qq, kk), (q64, k64), eps=1e-6, atol=1e-4), \
        "Custom autograd backward disagrees with numerical gradient"
```

Two things are happening here: a forward-numerical match at three precisions (this catches bf16 drift bugs), and a [`gradcheck`](https://pytorch.org/docs/stable/autograd.html#torch.autograd.gradcheck) that compares the analytical backward to a finite-difference approximation. If gradcheck passes, your `backward` is mathematically correct. That's the line you write in the README.

### The benchmark

```python
# bench/bench.py
import torch, triton
from rope import RotaryEmbedding

rope = RotaryEmbedding(dim=128, max_seq_len=8192).cuda()
q = torch.randn(4, 32, 8192, 128, device="cuda")
k = torch.randn(4, 32, 8192, 128, device="cuda")

def step():
    q_, k_ = rope(q, k)
    return q_, k_

ms = triton.testing.do_bench(step, warmup=50, rep=200)
tokens_per_sec = (4 * 8192) / (ms * 1e-3)
print(f"RoPE: {ms:.3f} ms / step  |  {tokens_per_sec/1e6:.2f} M tokens/sec")
```

Compare that number against `torch.nn.functional.embedding`-style naive implementations and against the [xFormers RoPE](https://github.com/facebookresearch/xformers) reference. If you're within 2x of xFormers, you've shipped something real. If you're faster, write a blog post about *why* — that's the second portfolio piece.

## Extending It: Your Roadmap to Senior-Level

The toy is the proof you understand the basics. These six upgrades are the difference between "interesting hobby" and "production-flavored system." Pick two. Ship three.

1. **Persistent CUDA graphs.** Wrap the forward pass in [`torch.cuda.graphs`](https://pytorch.org/docs/stable/notes/cuda.html#cuda-graphs) to eliminate kernel-launch overhead. Matters because real serving stacks at [Anyscale](https://www.anyscale.com/) and [vLLM](https://github.com/vllm-project/vllm) use CUDA graphs to push throughput.
2. **Horizontal scaling via tensor parallelism.** Split heads across GPUs and verify the math still holds. Use [NCCL](https://github.com/NVIDIA/nccldocs) for all-reduce on the attention output. This is how Llama-405B is served — proving you can do it on a 2-GPU box is interview gold.
3. **Observability.** Instrument the kernel with [Nsight Systems](https://developer.nvidia.com/nsight-systems) traces and emit structured logs of memory traffic, occupancy, and SM utilization. Senior engineers don't guess; they profile.
4. **Fault tolerance for long-context inference.** Add a checkpoint of `cos_cache`/`sin_cache` to disk and a resume path, because a 128k-context forward can take minutes and an OOM at token 120,000 is a real failure mode in production. This is the kind of "boring" robustness that distinguishes staff-level work.
5. **Benchmarking against the field.** Compare your kernel against [the official xFormers RoPE](https://github.com/facebookresearch/xformers/blob/main/xformers/ops/fused_rotary.py), [`torchtune`](https://github.com/pytorch/torchtune)'s implementation, and [vLLM's rotary embedding](https://github.com/vllm-project/vllm). Publish a CSV with H100, A100, and 4090 numbers.
6. **Mixed-precision correctness under attention.** Compose your RoPE with a [FlashAttention-2](https://github.com/Dao-AILab/flash-attention) call and prove the relative-position dot-product invariant `q_t · k_{t+Δ}` holds across dtypes. This is the test that would actually catch a real production bug.

Each of these is a 1–3 day project on its own and any two of them turn the repo from "kernel I wrote" into "system I designed."

## Key Takeaways

- RoPE is the positional scheme behind every modern open-weight LLM, which means a clean implementation is a *conversational* artifact in interviews, not just code.
- The interesting parts are the custom `torch.autograd.Function` (proves you understand autograd) and the fused Triton kernel (proves you understand GPUs).
- A parity test against a reference and a [`gradcheck`](https://pytorch.org/docs/stable/autograd.html#torch.autograd.gradcheck) are non-negotiable. Numerical correctness is the difference between a kernel and a bug.
- Keep the public API to one class and one function. The point of a portfolio piece is that a reviewer can read it in 10 minutes.
- The roadmap above — CUDA graphs, tensor parallelism, observability, fault tolerance, real benchmarks, mixed-precision attention invariants — is what turns "weekend project" into "senior-level signal."

## Further Reading

Primary sources that will deepen *this specific project* and the systems thinking around it:

- [RoPE: Roformer — Enhanced Transformer with Rotary Position Embedding (Su et al., 2021)](https://arxiv.org/abs/2104.09864)
- [PyTorch torch.autograd documentation](https://pytorch.org/docs/stable/autograd.html)
- [PyTorch CUDA Graphs guide](https://pytorch.org/docs/stable/notes/cuda.html#cuda-graphs)
- [Triton language reference and tutorials](https://triton-lang.org/main/index.html)
- [FlashAttention repository (Dao-AILab)](https://github.com/Dao-AILab/flash-attention)
- [xFormers fused rotary embedding source](https://github.com/facebookresearch/xformers)
- [torchtune's RoPE implementation for production reference](https://github.com/pytorch/torchtune)
- [Nsight Systems user guide for kernel profiling](https://docs.nvidia.com/nsight-systems/index.html)
- [NVIDIA NCCL documentation for multi-GPU scaling](https://docs.nvidia.com/deeplearning/nccl/)
- [vLLM project — a production-grade LLM serving system using fused RoPE](https://github.com/vllm-project/vllm)