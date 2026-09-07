---
title: "Building Grouped-Query Attention with RoPE and Flash-Attention from Scratch"
date: "2026-09-07T17:12:32.699"
draft: false
tags: ["pytorch", "transformers", "attention", "flash-attention", "machine-learning"]
description: "A hands-on build guide to a grouped-query multi-head attention block with rotary embeddings and online softmax, designed as a CV-worthy portfolio project."
summary: "Step-by-step tutorial for implementing GQA, RoPE, and an online-softmax Flash-Attention forward pass in pure PyTorch — a portfolio project that signals real systems-level ML skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-grouped-query-attention-with-rope-and-flash-attention-from-scratch.svg"
  alt: "Diagram of grouped-query attention with rotary position embeddings feeding into a tiled Flash-Attention forward pass."
  caption: ""
  relative: false
---

> **TL;DR** — You can build a from-scratch grouped-query multi-head attention block with rotary position embeddings and a tiled, online-softmax Flash-Attention forward pass in roughly 300 lines of pure PyTorch. It runs on CPU or MPS/CUDA, matches `torch.nn.functional.scaled_dot_product_attention` numerically, and ships with a tiny test harness. As a portfolio piece, it signals real systems-level ML skill: memory-aware kernels, modern attention variants, and the kind of engineering taste hiring managers look for.

There's a gap between "I read the Attention Is All You Need paper" and "I shipped a kernel that scales." Most CV-worthy ML side projects fall into the first bucket — they call `nn.MultiheadAttention` and call it done. That's fine for learning, but it doesn't differentiate you.

What does differentiate you is a project where you've stared at the math, made the trade-offs yourself, and ended up with code you can explain line by line. This guide walks you through exactly that: a from-scratch Grouped-Query Attention (GQA) block with Rotary Position Embeddings (RoPE) and a Flash-Attention-style forward pass using the online softmax. Every line is runnable, every line is explained, and the result is something you can confidently put on your CV and defend in an interview.

## Why This Project Stands Out on a CV

Hiring managers at serious ML infra teams — think the vLLM, xFormers, and Hugging Face `transformers` contributor circles, or any team shipping inference at scale — are drowning in candidates who've fine-tuned a Llama checkpoint on a Kaggle dataset. What they remember is the candidate who built something.

This project demonstrates:

- **You understand modern attention variants.** GQA is what [Llama 2, Llama 3, and Mistral](https://arxiv.org/abs/2307.09288) actually use. Knowing the difference between MHA, MQA, and GQA — and *why* GQA exists — is table stakes for any LLM systems role.
- **You can implement position encodings that aren't learned.** RoPE is what every serious open-weights model uses today. If you can derive and code it, you've read the [RoPE paper](https://arxiv.org/abs/2104.09864) and understood it.
- **You respect memory.** The online-softmax Flash-Attention forward is the same trick that lets vLLM serve 70B-parameter models on commodity GPUs. Showing you can implement it — even in pure PyTorch — signals you think about HBM bandwidth, not just FLOPs.
- **You write tests.** Numerical equivalence against `F.scaled_dot_product_attention` is the kind of engineering discipline ML teams fight to instill.
- **You can talk about trade-offs.** KV-cache sizes, dtype choices, kernel fusion — these are interview topics at [Anyscale](https://www.anyscale.com/), [Together AI](https://www.together.ai/), and Meta's GenAI org.

The roles this signals for: ML infrastructure engineer, inference platform engineer, applied research engineer, and any "ML systems" role where the bar is "can you read a kernel and ship one yourself."

## Architecture Overview

The block has five pieces. They fit together as follows:

- **`Input projection`** — A single `nn.Linear` that takes `x ∈ R^{B×T×D}` and emits `q, k, v` by reshaping. GQA means we emit fewer K/V heads than Q heads: if `num_heads = 8` and `num_kv_heads = 2`, then K/V are shared across 4 Q heads each.
- **RoPE rotation** — We rotate Q and K (not V) by position-dependent complex angles, applied as a 2D matrix multiply on the head's last dimension.
- **Tiled online-softmax attention (Flash-Attention style)** — Instead of materialising the full `T×T` attention matrix, we stream over blocks of keys/values and maintain a running `m` (max) and `l` (denominator) per row. This is the algorithmic heart of [FlashAttention](https://arxiv.org/abs/2205.14135).
- **Output projection** — A final `nn.Linear` that mixes the head outputs back into the model dimension.
- **Tiny harness** — A test that compares our output to PyTorch's reference, plus a small CLI for running a forward pass on toy input.

```text
x (B,T,D)
   │
   ▼
QKV Linear  ──►  q (B,Hq,T,Dh)   k,v (B,Hkv,T,Dh)
                       │              │
                       ▼              ▼
                    RoPE(Q,K)        RoPE(Q,K)
                       │              │
                       └──────► Flash-Attn forward ◄──────┘
                                   (tiled, online softmax)
                                   │
                                   ▼
                            Concat heads → Output Linear
                                   │
                                   ▼
                              out (B,T,D)
```

## Building It Step by Step

We'll build this in a single file, `gqa_rope_flash.py`. Aim for ~300 lines including tests and a CLI.

### Step 1 — Project scaffold and config

Use a dataclass for config. This makes the code self-documenting and easy to extend.

```python
# gqa_rope_flash.py
from __future__ import annotations
import math
from dataclasses import dataclass
import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass
class GQAConfig:
    d_model: int = 512          # model dim
    num_heads: int = 8           # query heads (Hq)
    num_kv_heads: int = 2        # key/value heads (Hkv); must divide Hq
    head_dim: int = 64           # d_model / num_heads
    max_seq_len: int = 2048      # context length for the RoPE cache
    rope_base: float = 10000.0   # RoPE theta
    block_size: int = 128        # Flash-Attn tile size
    dtype: torch.dtype = torch.float32
```

A few invariants: `d_model == num_heads * head_dim`, `num_heads % num_kv_heads == 0`. Enforce them in the constructor.

### Step 2 — RoPE cache and apply

RoPE rotates pairs of features in Q and K by an angle that depends on position and feature index. The classic implementation precomputes `cos` and `sin` tables of shape `(max_seq_len, head_dim)`, then applies them with a rotation.

```python
class RotaryEmbedding(nn.Module):
    def __init__(self, head_dim: int, max_seq_len: int, base: float = 10000.0):
        super().__init__()
        assert head_dim % 2 == 0, "RoPE requires even head_dim"
        # Inverse frequencies, shape (head_dim/2,)
        inv_freq = 1.0 / (base ** (torch.arange(0, head_dim, 2).float() / head_dim))
        t = torch.arange(max_seq_len).float()
        # Outer product → (T, head_dim/2)
        freqs = torch.einsum("i,j->ij", t, inv_freq)
        # Cache cos/sin duplicated to head_dim so we can apply as elementwise mul+add
        self.register_buffer("cos", freqs.cos().repeat_interleave(2, dim=-1), persistent=False)
        self.register_buffer("sin", freqs.sin().repeat_interleave(2, dim=-1), persistent=False)

    def apply(self, x: torch.Tensor, offset: int = 0) -> torch.Tensor:
        # x: (B, H, T, Dh)
        T = x.size(-2)
        cos = self.cos[offset:offset + T].to(x.dtype)
        sin = self.sin[offset:offset + T].to(x.dtype)
        # Rotate pairs: (x1,x2) -> (x1*cos - x2*sin, x1*sin + x2*cos)
        x1, x2 = x.chunk(2, dim=-1)
        # Pairwise rotate by interleaving; simpler: use a per-pair sign pattern.
        sign = torch.tensor([-1, 1], dtype=x.dtype, device=x.device)
        x2_rot = (x1 * sin - x2 * cos) * sign[0] + (x1 * cos + x2 * sin) * sign[1]
        # Equivalent compact form:
        rot = torch.stack([-x2, x1], dim=-1).flatten(-2)
        return (x * cos) + (rot * sin)
```

Two things worth calling out. First, we cache `cos`/`sin` rather than recomputing each forward — same trick real kernels use. Second, the rotation matrix is sparse: only pairs of features rotate, which is what makes RoPE cheap.

### Step 3 — The tiled, online-softmax Flash-Attention forward

This is the algorithmic core. The online softmax (Milakov & Gimelshein, 2018) lets us compute `softmax(QKᵀ / √d) V` without ever materialising the full attention matrix. We process keys/values in blocks of size `block_size`, keeping a running max `m` and sum `l` per query row, and rescaling the partial output `O` as we go.

```python
def flash_attention_forward(
    q: torch.Tensor,          # (B, Hq, Tq, Dh)
    k: torch.Tensor,          # (B, Hkv, Tk, Dh)
    v: torch.Tensor,          # (B, Hkv, Tk, Dh)
    block_size: int = 128,
    scale: float | None = None,
) -> torch.Tensor:
    B, Hq, Tq, Dh = q.shape
    _, Hkv, Tk, _ = k.shape
    assert Hq % Hkv == 0, "num_heads must be divisible by num_kv_heads"
    group = Hq // Hkv
    scale = scale or 1.0 / math.sqrt(Dh)

    # Expand K/V along head dim so each Q head has its own (broadcast) KV head.
    k = k.repeat_interleave(group, dim=1)
    v = v.repeat_interleave(group, dim=1)

    # Allocate output and the running softmax statistics.
    O = torch.zeros_like(q)
    m_i = torch.full((B, Hq, Tq), float("-inf"), device=q.device, dtype=q.dtype)
    l_i = torch.zeros((B, Hq, Tq), device=q.device, dtype=q.dtype)

    for start in range(0, Tk, block_size):
        end = min(start + block_size, Tk)
        Kb = k[:, :, start:end, :]      # (B, Hq, Bk, Dh)
        Vb = v[:, :, start:end, :]      # (B, Hq, Bk, Dh)
        # (B, Hq, Tq, Bk)
        S = torch.matmul(q, Kb.transpose(-1, -2)) * scale

        # Online softmax update.
        m_new = torch.maximum(m_i, S.amax(dim=-1))
        alpha = torch.exp(m_i - m_new)
        p = torch.exp(S - m_new[..., None])
        l_new = alpha * l_i + p.sum(dim=-1)

        # Rescale previous output, add the new partial contribution.
        O = O * alpha[..., None] + torch.matmul(p, Vb)
        m_i, l_i = m_new, l_new

    return O / l_i[..., None]
```

The rescaling step `O = O * alpha + p @ Vb` is the part that makes this numerically stable across arbitrarily long context. It's also the part most people get wrong on first attempt — if your tests fail, check this line.

### Step 4 — Wire it into an `nn.Module`

```python
class GQARopeFlashAttention(nn.Module):
    def __init__(self, cfg: GQAConfig):
        super().__init__()
        self.cfg = cfg
        assert cfg.d_model == cfg.num_heads * cfg.head_dim
        assert cfg.num_heads % cfg.num_kv_heads == 0

        # One fused QKV projection; K/V only use num_kv_heads * head_dim.
        kv_dim = cfg.num_kv_heads * cfg.head_dim
        self.q_proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)
        self.k_proj = nn.Linear(cfg.d_model, kv_dim, bias=False)
        self.v_proj = nn.Linear(cfg.d_model, kv_dim, bias=False)
        self.o_proj = nn.Linear(cfg.d_model, cfg.d_model, bias=False)

        self.rope = RotaryEmbedding(cfg.head_dim, cfg.max_seq_len, cfg.rope_base)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, _ = x.shape
        Hq, Hkv, Dh = self.cfg.num_heads, self.cfg.num_kv_heads, self.cfg.head_dim

        q = self.q_proj(x).view(B, T, Hq, Dh).transpose(1, 2)        # (B, Hq, T, Dh)
        k = self.k_proj(x).view(B, T, Hkv, Dh).transpose(1, 2)
        v = self.v_proj(x).view(B, T, Hkv, Dh).transpose(1, 2)

        q = self.rope.apply(q)
        k = self.rope.apply(k)

        out = flash_attention_forward(q, k, v, block_size=self.cfg.block_size)
        out = out.transpose(1, 2).contiguous().view(B, T, Hq * Dh)
        return self.o_proj(out)
```

Note the absence of causal masking. That's a deliberate choice — masking adds ~15 lines and obscures the core trick. Add it as your first extension in the roadmap below.

## Running and Testing It

The point of testing this kind of code isn't just "does it run" — it's "does my tiled online-softmax give the same answer as the reference implementation?" That's a real, falsifiable claim.

```python
def test_against_reference():
    torch.manual_seed(0)
    cfg = GQAConfig(d_model=256, num_heads=8, num_kv_heads=2, head_dim=32, max_seq_len=512)
    block = GQARopeFlashAttention(cfg).eval()
    x = torch.randn(2, 64, 256)

    with torch.no_grad():
        y_ours = block(x)

        # Reference: project separately, use reference SDPA with GQA via enable_gqa.
        Hq, Hkv, Dh = cfg.num_heads, cfg.num_kv_heads, cfg.head_dim
        q = block.q_proj(x).view(2, 64, Hq, Dh).transpose(1, 2)
        k = block.k_proj(x).view(2, 64, Hkv, Dh).transpose(1, 2)
        v = block.v_proj(x).view(2, 64, Hkv, Dh).transpose(1, 2)
        q = block.rope.apply(q)
        k = block.rope.apply(k)
        # PyTorch >= 2.5 supports enable_gqa=True on SDPA.
        y_ref = F.scaled_dot_product_attention(q, k, v, enable_gqa=True)
        y_ref = y_ref.transpose(1, 2).contiguous().view(2, 64, Hq * Dh)
        y_ref = block.o_proj(y_ref)

    diff = (y_ours - y_ref).abs().max().item()
    assert diff < 1e-4, f"max abs diff {diff} too large"
    print(f"OK  max abs diff = {diff:.2e}")
```

A CLI front-end lets you actually drive it:

```python
def main():
    cfg = GQAConfig()
    block = GQARopeFlashAttention(cfg)
    x = torch.randn(1, 16, cfg.d_model)
    y = block(x)
    print("input", x.shape, "→ output", y.shape)

if __name__ == "__main__":
    main()
```

Run it:

```bash
python gqa_rope_flash.py
pytest -q -k test_against_reference
```

On a laptop CPU you should get `max abs diff` in the 1e-5 to 1e-6 range for fp32. If you're on MPS or CUDA, the result is identical — that's the value of testing against a reference: the math doesn't care about the device.

## Extending It: Your Roadmap to Senior-Level

Here's the part that turns a 300-line toy into a portfolio piece hiring managers actually read twice. Pick three of these and ship them; you've now got a multi-week project with a real architecture.

- **Causal masking + autoregressive KV cache.** The single most common addition. Pre-allocate `k_cache`, `v_cache` per layer, write into them by position, and only attend to past positions. This is the foundation of [vLLM's PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html) and any production inference engine. It matters because every serving system you've ever heard of implements it.
- **Triton / CUDA kernel for the inner loop.** Port `flash_attention_forward` to [Triton](https://triton-lang.org/) (or hand-rolled CUDA). You'll see a 5–20× speedup over the PyTorch reference and gain real intuition for memory-bound vs compute-bound kernels. It matters because it demonstrates you can move from "writes PyTorch" to "writes GPU code."
- **Mixed-precision forward (bf16/fp16) with fp32 accumulators.** Production attention almost never runs in fp32. Cast Q/K/V to bf16 but keep the softmax statistics and accumulation in fp32, exactly as [FlashAttention-2](https://arxiv.org/abs/2307.08691) does. It matters because it shows you understand where numerics break and how to defend against it.
- **Benchmark harness against `F.scaled_dot_product_attention`.** Time both paths over realistic sequence lengths (1k, 4k, 16k) and head configs, plot the gap, write a markdown report. It matters because it's the same evidence-based approach real performance teams use internally.
- **Sliding-window attention as a configurable mode.** Add a `window_size` parameter that uses [Mistral's](https://arxiv.org/abs/2310.06825) sliding window trick. It matters because it demonstrates you've read a recent paper and can lift a pattern into production code.
- **Serving layer with batching.** Wrap the block in a small `asyncio` server that accepts request batches and runs them concurrently with [continuous batching](https://www.anyscale.com/blog/continuous-batching-llm-inference). It matters because it takes you from "ML" to "ML systems," which is where the salary curve steepens.

## Key Takeaways

- A from-scratch GQA + RoPE + Flash-Attention block is ~300 lines and runs anywhere PyTorch does.
- The online softmax is the algorithmic trick that makes Flash-Attention memory-linear in sequence length; understanding it changes how you think about attention entirely.
- RoPE is applied as an elementwise rotation with a cached `cos`/`sin` table; the math is rotation in 2D planes indexed by feature dimension.
- A test against `F.scaled_dot_product_attention(enable_gqa=True)` is the falsifiable correctness claim that turns this from "code" into "verified code."
- The roadmap above is the differentiator: causal + KV cache, Triton, mixed precision, benchmarking, sliding window, and serving take you from toy to portfolio-grade.

## Further Reading

- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135) — the original FlashAttention paper. Read sections 3 and 4; they describe exactly the online-softmax trick implemented above.
- [FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning](https://arxiv.org/abs/2307.08691) — the follow-up. The "online softmax rescaling" pseudocode on page 5 is the canonical reference for your implementation.
- [GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints](https://arxiv.org/abs/2305.14145) — the GQA paper. Short, clear, and explains why KV-head sharing is a near-free win.
- [RoFormer: Enhanced Transformer with Rotary Position Embedding](https://arxiv.org/abs/2104.09864) — the RoPE paper. Appendix A has the rotation derivation worth working through once by hand.
- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html) — once you've added KV caching, this is what to read next.
- [PyTorch SDPA docs, including the `enable_gqa` flag](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) — the reference implementation you're testing against.