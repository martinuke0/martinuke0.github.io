---
title: "Building Flash Attention From Scratch in NumPy: A CV-Grade Side Project"
date: "2026-09-05T22:00:31.987"
draft: false
tags: ["flash-attention", "numpy", "transformers", "cuda-kernels", "systems-engineering"]
description: "A hands-on build guide for a portfolio-grade flash attention kernel in NumPy covering online softmax, tiling, and benchmarking against a naive reference."
summary: "A complete, runnable walkthrough of implementing flash attention from scratch in NumPy, including online softmax, block tiling, causal masking, and correctness checks — designed as a CV-worthy systems project."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-building-flash-attention-from-scratch-in-numpy-a-cv-grade-side-project.svg"
  alt: "Block-tiled attention computation showing memory access patterns across query, key, and value matrices."
  caption: ""
  relative: false
---

> **TL;DR** — Flash attention is the same math as standard attention, but reorganised so it never materialises the full \(N \times N\) attention matrix in HBM. This guide walks through a from-scratch NumPy implementation that uses online softmax and block tiling, then verifies it against a naive reference. It signals real systems thinking on a CV — GPU kernels, memory bandwidth, and numerical stability — and ships as a weekend-sized project with a clear path to senior-level extensions.

If you are a working or aspiring ML or systems engineer looking for a portfolio piece that actually impresses hiring managers, flash attention is one of the highest signal-to-effort projects you can pick. It is short enough to finish in a weekend, deep enough to teach you real GPU programming concepts, and famous enough that interviewers will immediately recognise what you have built. The 2022 paper from Tri Dao and collaborators is the kind of primary source you cite in a systems interview, and the engineering tricks you learn — online softmax, tiling, kernel fusion — show up across the ML systems stack from vLLM to xFormers to PyTorch's `torch.compile`.

This guide is for engineers who already know what attention is and have written at least one transformer. We will not re-derive scaled dot-product attention from first principles. Instead, we will build the flash version, block by block, with runnable NumPy code.

## Why This Project Stands Out on a CV

Most CVs list "built a transformer" or "fine-tuned an LLM". Those are commodity. A flash attention implementation signals something different, and hiring managers from GPU kernel teams, ML infra, inference platform teams, and quant hedge funds read the same signals:

- **Memory hierarchy literacy.** You are not just calling `softmax(QK^T / sqrt(d)) @ V`. You are reasoning about HBM vs SRAM, why materialising the \(N \times N\) matrix blows the cache for long sequences, and how tiling fixes it. This is the same mental model as cuBLAS, CUTLASS, and any GEMM optimisation work.
- **Numerical stability under composition.** Online softmax (Milakov & Gimelshein, 2018) is the kind of trick that separates people who have shipped numerics from people who only run notebooks. It is also the prerequisite for any streaming softmax implementation, including low-precision softmax in inference engines.
- **Correctness discipline.** A flash attention project is only credible if you verify the kernel against a naive reference at multiple sequence lengths, head dimensions, and mask configurations. Including the test harness in the repo signals the engineering hygiene that production teams expect.
- **Mapping to real roles.** The roles this targets: ML performance engineer, GPU kernel engineer (NVIDIA, AMD, Apple), inference platform engineer (vLLM, TensorRT-LLM), quant research engineer (low-latency attention matters for trading), and ML infra at frontier labs. Even if you apply to a "normal" MLE role, it tells the interviewer you can think about hardware.

The project also has a clean narrative arc for an interview: "I read the paper, found the existing implementations too opaque, wrote the algorithm from scratch in NumPy first to make sure I understood it, then benchmarked it." That arc — paper → naive reference → optimised kernel → benchmark — is exactly how production kernel work is done.

## Architecture Overview

We are building a single forward pass for causal self-attention. The pieces, top to bottom:

- **Inputs.** Three matrices, all `N x d` for a single head: `Q` (queries), `K` (keys), `V` (values). For a real transformer you would have a batch dimension and multiple heads, but we keep the head dimension implicit by flattening it in. The implementation works on any 2D slice.
- **Block tiling.** We split the sequence dimension `N` into blocks of size `B_r` for queries and `B_c` for keys/values. `B_r` and `B_c` are chosen so that a block fits in the on-chip "SRAM" region of the GPU in the real CUDA port. In NumPy they are just loop strides; conceptually they are the SRAM budget.
- **Outer loop over query blocks.** For each query block `i`, we hold `Q_i` resident and stream through all key/value blocks `j`.
- **Inner loop over key/value blocks.** For each `j`, we load `K_j` and `V_j`, compute a partial attention block `S_ij = Q_i @ K_j^T / sqrt(d)`, apply causal masking on the diagonal blocks, update the running softmax statistics, and accumulate into the output `O_i` and the normaliser `L_i`.
- **Online softmax state.** Per query row we maintain a running max `m_i` and a running sum `l_i`. When a new block arrives with max `m_ij`, we rescale `l_i` and `O_i` by `exp(m_i - m_new)`, fold in the new block's contribution, and continue. This is the trick that makes the whole thing a single streaming pass.
- **Final write.** After the inner loop, we divide `O_i` by `l_i` to recover the softmax-weighted output and write it back to the result buffer.
- **Test harness.** A separate script compares the flash output to a naive `softmax(QK^T/sqrt(d) + mask) @ V` reference at several `N` and `d`, with an `np.allclose` check and printed max error.

```
   Q (N x d)            K (N x d)            V (N x d)
   -----                -----                -----
   |Q1|Q2|Q3|Q4|        |K1|K2|K3|K4|        |V1|V2|V3|V4|     <- blocks of B_r / B_c
   -----                -----                -----

   for each query block i in [1..4]:
       load Q_i  (resides "in SRAM")
       m_i = -inf, l_i = 0, O_i = 0
       for each key/value block j in [1..4]:
           load K_j, V_j
           S_ij = Q_i @ K_j^T / sqrt(d)
           if i >= j (causal):  mask else  -inf
           m_ij = rowmax(S_ij)
           m_new = max(m_i, m_ij)
           P_ij  = exp(S_ij - m_new)
           l_new = exp(m_i - m_new) * l_i + rowsum(P_ij)
           O_i   = exp(m_i - m_new) * O_i + P_ij @ V_j
           m_i, l_i = m_new, l_new
       O[i] = O_i / l_i
```

That is the whole algorithm. The rest of this guide is the code, the tests, and the upgrades.

## Building It Step by Step

We will write three files: `flash_attention.py` (the kernel), `reference.py` (the naive baseline), and `test_flash.py` (the harness). Everything is pure NumPy — no PyTorch, no Triton — so the reader can run it anywhere.

### Step 1 — The naive reference

First the baseline. This is what every flash attention implementation is checked against.

```python
# reference.py
import numpy as np

def naive_attention(Q, K, V, causal: bool = True):
    d = Q.shape[-1]
    scores = (Q @ K.T) / np.sqrt(d)
    if causal:
        N = Q.shape[0]
        mask = np.triu(np.ones((N, N), dtype=bool), k=1)
        scores = np.where(mask, -np.inf, scores)
    weights = np.softmax(scores, axis=-1)
    return weights @ V
```

That is the math. The `N x N` `scores` matrix is what flash attention avoids materialising. On a modern GPU, a sequence of 8192 with head dim 128 means a 8192×8192 fp32 matrix — 268 MB — that has to round-trip through HBM twice. Flash attention avoids it.

### Step 2 — The flash kernel skeleton

Now the interesting file. The structure mirrors the diagram above.

```python
# flash_attention.py
import numpy as np

def flash_attention(Q, K, V, Br: int = 32, Bc: int = 32, causal: bool = True):
    """
    Pure-NumPy flash attention forward pass.
    Shapes: Q, K, V are (N, d). Br, Bc are query/key block sizes.
    """
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)
    O = np.zeros_like(Q)
    L = np.zeros(N, dtype=Q.dtype)  # log-sum-exp, kept for introspection

    Tr = (N + Br - 1) // Br  # number of query blocks

    for i in range(Tr):
        r0, r1 = i * Br, min((i + 1) * Br, N)
        Q_i = Q[r0:r1] * scale              # fold scaling into Q once
        O_i = np.zeros_like(Q_i)
        m_i = np.full(r1 - r0, -np.inf)     # running row max
        l_i = np.zeros(r1 - r0)             # running row sum of exp

        Tc = (N + Bc - 1) // Bc
        for j in range(Tc):
            c0, c1 = j * Bc, min((j + 1) * Bc, N)
            K_j = K[c0:c1]
            V_j = V[c0:c1]

            S_ij = Q_i @ K_j.T              # (Br, Bc)

            if causal:
                # mask keys at positions >= query positions
                rows = np.arange(r0, r1)[:, None]
                cols = np.arange(c0, c1)[None, :]
                S_ij = np.where(cols > rows, -np.inf, S_ij)

            # ---- online softmax update ----
            m_ij = S_ij.max(axis=-1)
            m_new = np.maximum(m_i, m_ij)
            P_ij = np.exp(S_ij - m_new[:, None])

            alpha = np.exp(m_i - m_new)      # rescale factor for old state
            l_new = alpha * l_i + P_ij.sum(axis=-1)

            # rescale old accumulator, then add new block's contribution
            O_i = O_i * alpha[:, None] + P_ij @ V_j

            m_i, l_i = m_new, l_new

        # normalise and write back
        O[r0:r1] = O_i / l_i[:, None]
        L[r0:r1] = m_i + np.log(l_i)

    return O, L
```

Three details worth pausing on:

- **Scaling fold.** Multiplying `Q` by `1/sqrt(d)` once outside the inner loop saves one elementwise op per block. The CUDA version uses `__fdivide` or a fused multiply.
- **Causal mask is block-local.** Only diagonal blocks need masking. Off-diagonal blocks are either fully visible (above the diagonal in the `(i, j)` plane, where `j < i`) or fully masked (`j > i`). The kernel above masks every block defensively; a production version would short-circuit with `if j <= i` to skip the masked blocks entirely.
- **The rescale is the whole trick.** When a new maximum `m_ij` exceeds the running `m_i`, every prior accumulator has to be rescaled by `exp(m_i - m_new)`. Without this, you cannot stream blocks in any order — which is exactly the property flash attention needs.

### Step 3 — A small numerical caveat

Naive softmax subtracts the global max per row to avoid overflow. Online softmax is the same idea, but applied across streamed blocks. The invariant you are maintaining is:

```
  O_i / l_i   ==   softmax(Q_i @ K_all^T / sqrt(d)) @ V_all
```

Test it before you trust the kernel. That is the next step.

### Step 4 — The correctness harness

```python
# test_flash.py
import numpy as np
from reference import naive_attention
from flash_attention import flash_attention

def check(N, d, Br=32, Bc=32, causal=True, seed=0):
    rng = np.random.default_rng(seed)
    Q = rng.standard_normal((N, d)).astype(np.float32)
    K = rng.standard_normal((N, d)).astype(np.float32)
    V = rng.standard_normal((N, d)).astype(np.float32)

    ref = naive_attention(Q, K, V, causal=causal)
    out, L = flash_attention(Q, K, V, Br=Br, Bc=Bc, causal=causal)

    err = np.max(np.abs(out - ref))
    ok = np.allclose(out, ref, atol=1e-5, rtol=1e-4)
    print(f"N={N:5d} d={d:3d} Br={Br:3d} Bc={Bc:3d} "
          f"causal={causal}  max_err={err:.2e}  ok={ok}")
    assert ok, "mismatch — check online softmax update"

if __name__ == "__main__":
    for N in [128, 257, 512, 1024]:        # 257 forces ragged tail blocks
        for d in [16, 32, 64, 128]:
            check(N, d, Br=32, Bc=32)
            check(N, d, Br=16, Bc=64)      # asymmetric tiling
    check(2048, 64, Br=64, Bc=64, causal=False)
    print("all checks passed")
```

Run it with `python test_flash.py`. The `257` case is deliberate — it forces the last query block to be smaller than `Br`, which is the place most naive implementations break.

## Running and Testing It

You should be able to clone, run, and verify the kernel on any laptop with NumPy.

```bash
python -m venv .venv && source .venv/bin/activate
pip install numpy
python test_flash.py
```

Expected output: every line shows `max_err` on the order of `1e-6` to `1e-5` and `ok=True`, then a final `all checks passed`. If anything fails, the failure almost always points to one of three bugs:

- **Forgetting to rescale `l_i`.** Symptom: errors grow with sequence length because accumulated normaliser drifts.
- **Mixing `m_i` and `m_new`.** Symptom: `nan` on rows whose first block has all `-inf` (causal mask on the very first key block).
- **Off-by-one in causal masking.** Symptom: errors on the diagonal block only.

A useful smoke test before the harness is just running both kernels on `N=64, d=8` and printing outputs side by side:

```python
N, d = 64, 8
Q = np.random.randn(N, d)
K = np.random.randn(N, d)
V = np.random.randn(N, d)
ref = naive_attention(Q, K, V)
out, _ = flash_attention(Q, K, V, Br=16, Bc=16)
print("ref[0,:4]  =", ref[0, :4])
print("out[0,:4]  =", out[0, :4])
```

Once this matches to 5 decimal places, you have a working reference. Add a tiny benchmark next:

```python
# benchmark.py
import time, numpy as np
from reference import naive_attention
from flash_attention import flash_attention

N, d = 2048, 64
Q, K, V = (np.random.randn(N, d) for _ in range(3))

for _ in range(3):
    t0 = time.perf_counter(); naive_attention(Q, K, V); t_naive = time.perf_counter() - t0
    t0 = time.perf_counter(); flash_attention(Q, K, V, Br=64, Bc=64); t_flash = time.perf_counter() - t0
    print(f"naive={t_naive*1e3:7.2f} ms   flash={t_flash*1e3:7.2f} ms")
```

On CPU, NumPy flash will not beat naive — both are bound by BLAS and you have added Python loop overhead. The benchmark here is mostly a sanity check that flash is *not dramatically slower*. The real speedup only appears on a GPU with kernel fusion; see the extensions below.

## Extending It: Your Roadmap to Senior-Level

The NumPy version is the on-ramp. Each of these upgrades turns it from a teaching artifact into something closer to what a real inference platform team ships.

- **Port to a Triton or CUDA kernel.** Triton is the lowest-friction path; the NumPy version maps almost line-for-line into a `@triton.jit` function with `tl.exp`, `tl.max`, and block pointers. On an A100 you will see the 2–4× speedup the original paper claims. Reason it matters: this is the literal job description of an ML performance engineer.
- **Add a backward pass.** Flash attention's famous contribution is not just the forward — it is that the backward pass is also a single kernel that recomputes `S_ij` and `P_ij` from saved `Q_i, K_j, V_j, O_i, L_i` instead of storing the full attention matrix. Reason it matters: training memory. The same trick is what makes 8k-context fine-tuning feasible on a single GPU.
- **Multi-head and batched dimensions.** Promote `(N, d)` to `(B, H, N, d)` and add a launcher that tiles over batch and head in addition to sequence. Reason it matters: every real deployment is batched; a single-head kernel is a toy.
- **Half-precision and mixed precision.** Cast inputs to fp16 or bf16 inside the kernel, keep the accumulator in fp32, and benchmark against an fp32 baseline. Reason it matters: production attention almost never runs in fp32; the numerical-stability story changes when you do this and your code has to handle it.
- **Persistence and warm-start.** Wrap the kernel in a server (FastAPI, gRPC) that loads `Q, K, V` from a shared store, computes attention for a request, caches the `(Br, Bc)` schedule keyed on `(N, d)`, and times out gracefully. Reason it matters: this is the form factor every inference service uses (vLLM, TensorRT-LLM servers, SGLang).
- **Observability and fault tolerance.** Emit per-step timings (block index, tile sizes, memory estimate), log to OpenTelemetry, and add a fallback that switches to the naive kernel if the flash kernel returns NaN — the same defensive pattern PyTorch's `torch.compile` uses. Reason it matters: a kernel that cannot degrade gracefully will never ship.

If you ship even two of these on top of the NumPy base, you have a project that holds its own against open-source contributions to xFormers or unsloth.

## Key Takeaways

- Flash attention is standard attention with the \(N \times N\) matrix kept in registers/SRAM instead of HBM — the math is identical, the data movement is what changes.
- Online softmax (Milakov & Gimelshein) is the streaming trick that makes the tiling work: maintain a running max and sum, rescale the accumulator when a new block has a higher max.
- Block sizes `B_r` and `B_c` are a hardware budget, not an arbitrary tuning knob — in CUDA they are chosen so that `Q_i`, `K_j`, `V_j`, `S_ij`, and `P_ij` together fit in SRAM.
- The NumPy version is a pedagogical device; the real project lands when you port it to Triton or CUDA and add the backward pass.
- The CV signal is not "I implemented attention" — it is "I read a paper, wrote a streaming algorithm, verified numerical correctness, and benchmarked it". That arc is what senior interviewers recognise.

## Further Reading

- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness — Tri Dao et al., 2022](https://arxiv.org/abs/2205.14135) — the paper this project is built from, with the full algorithm and IO analysis.
- [FlashAttention-2: Towards Faster Training of Transformer Models — Tri Dao, 2023](https://arxiv.org/abs/2307.08691) — the follow-up that reworks the work partitioning for better GPU utilisation; the next upgrade after the v1 kernel.
- [Online normalizer calculation for softmax — Maxim Milakov and Natalia Gimelshein, 2018](https://arxiv.org/abs/1805.02867) — the streaming softmax paper that flash attention builds on; short and worth the hour.
- [Triton documentation — block pointers and tl programming model](https://triton-lang.org/main/index.html) — the canonical path to porting this NumPy kernel to a real GPU.
- [The Illustrated Transformer — Jay Alammar](https://jalammar.github.io/illustrated-transformer/) — if a reader has not internalised what attention is at the matrix level, this is the fastest way to get there.
- [CUTLASS: CUDA Templates for Linear Algebraic Subroutines — NVIDIA](https://github.com/NVIDIA/cutlass) — the production GEMM library that flash attention's tiling strategy is a special case of; studying CUTLASS teaches you the broader kernel-design idiom.