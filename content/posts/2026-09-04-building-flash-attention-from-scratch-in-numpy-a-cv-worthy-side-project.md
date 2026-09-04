---
title: "Building Flash Attention from Scratch in NumPy: A CV-Worthy Side Project"
date: "2026-09-04T22:00:28.668"
draft: false
tags: ["flash-attention", "numpy", "kernels", "ml-systems", "side-project", "transformers"]
description: "Hands-on build guide for a from-scratch flash attention kernel with tiling and online softmax in pure NumPy — a portfolio project that signals real systems skill."
summary: "A working engineer's guide to implementing Flash Attention from the ground up using tiling and the online softmax trick — runnable NumPy, end-to-end tests, and a roadmap to senior-level extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-building-flash-attention-from-scratch-in-numpy-a-cv-worthy-side-project.svg"
  alt: "Tiled matrix multiplication diagram with softmax rows"
  caption: ""
  relative: false
---

> **TL;DR** — Flash Attention is best understood by implementing it: you tile the Q·Kᵀ matmul into SRAM-sized blocks, fuse the softmax in a single pass using the online (Milakov & Gimelshein) recurrence, and stream the result back into the output buffer. A pure NumPy port is small enough to ship in an afternoon, runs on a laptop, and demonstrates memory-aware kernel design, numerical stability under streaming, and the kind of low-level care that hiring managers look for in systems and ML infra roles.

## Why This Project Stands Out on a CV

Most "I implemented attention" repos on GitHub are ten lines of PyTorch that call `F.scaled_dot_product_attention`. Hiring managers know this. The differentiator is showing you understand *why* that function is fast.

A from-scratch Flash Attention kernel in NumPy demonstrates, in code that any reviewer can read without a GPU:

- **Memory hierarchy awareness.** You have to reason about SRAM vs HBM, register reuse, and the difference between materializing the N×N attention matrix and streaming it through on-chip. The same instinct shows up when you're tuning a RocksDB block cache or sizing a Kafka batch.
- **Numerical stability under streaming.** The online softmax recurrence is one of the cleanest examples of a numerically stable streaming algorithm you'll find — the kind of thing that makes you careful about NaN propagation in production inference pipelines.
- **Kernel fusion as a design choice.** The whole point of Flash Attention is fusion: matmul + mask + softmax + matmul, instead of four separate launches. Talking through that design choice translates directly to fusing PyTorch JIT graphs or writing custom TensorRT plugins.
- **A real benchmark, not a claim.** You'll measure HBM traffic reductions and runtime on actual arrays, the way you'd benchmark a Postgres query plan with `EXPLAIN ANALYZE`.

The roles this signals for: ML infrastructure, kernel engineer, performance engineer, training systems, CUDA/HIP porting, and any backend role where "I make the hot path faster" is a quarter's worth of work. It's also a strong interview talking point — the [Flash Attention paper](https://arxiv.org/abs/2205.14135) and [Flash Attention 2](https://arxiv.org/abs/2307.08691) come up regularly in systems screens.

## Architecture Overview

The kernel is structured exactly like the GPU version, just with a `np.ndarray` standing in for on-chip SRAM. The trick is to keep the mental model honest so that porting to CUDA later is a mechanical exercise.

- **Inputs**: `Q`, `K`, `V` as `[B, H, N, d]` tensors where `B`=batch, `H`=heads, `N`=sequence, `d`=head dim. We work on a single head for clarity.
- **Block size `Bc`**: column block size for `K`/`V` (keys streaming through SRAM).
- **Block size `Br`**: row block size for `Q` (rows being scored).
- **`acc`**: the running output accumulator, shape `[Br, d]`.
- **`m`**: running row-wise max, shape `[Br]`.
- **`l`**: running row-wise normalizer (the sum of exp(x - m)), shape `[Br]`.
- **Outer loop**: iterate over `K`/`V` blocks of size `Bc`.
- **Inner loop**: load a `Q` block of size `Br`, compute `S = Q·Kᵀ`, mask, and apply the **online softmax update** that folds the new block's statistics into `m`, `l`, `acc` in one pass.
- **Finalize**: divide `acc` by `l` to get the softmax-weighted output, never having materialized the full `[N, N]` score matrix.

The data flow mirrors the CUDA implementation in the official paper, where SRAM is the limiting resource and HBM traffic is the thing you minimize.

## Building It Step by Step

We'll build this incrementally, with tests after each stage. The whole thing is ~120 lines.

### Step 1 — The reference implementation

Start with a correct-but-naive baseline so you have something to compare against. This is the same pattern as writing a `brute_force` test before optimizing.

```python
import numpy as np

def attention_reference(Q, K, V, mask=None):
    # Q, K, V: [N, d]. mask: [N, N] or None.
    d = Q.shape[-1]
    scores = Q @ K.T / np.sqrt(d)              # [N, N]
    if mask is not None:
        scores = np.where(mask == 0, -1e9, scores)
    scores -= scores.max(axis=-1, keepdims=True)
    p = np.exp(scores)
    p /= p.sum(axis=-1, keepdims=True)
    return p @ V                                 # [N, d]
```

### Step 2 — The online softmax recurrence

The key insight from [Milakov & Gimelshein (2018)](https://arxiv.org/abs/1802.03881) is that you can compute a softmax over a concatenation of blocks using only the per-block max and sum, plus the running global max. Define:

- `m_new = max(m_old, m_block)`
- `l_new = exp(m_old - m_new) * l_old + exp(m_block - m_new) * l_block`
- `acc_new = exp(m_old - m_new) * acc_old + exp(m_block - m_new) * (p_block @ V_block)`

Then the final `softmax @ V` is just `acc_new / l_new` once everything has been folded in. This is the same recurrence that powers [OnlineNormalizerCalculation](https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance#Online_algorithm) and shows up in Welford's algorithm for streaming mean/variance.

### Step 3 — The tiled, fused kernel

```python
def flash_attention_np(Q, K, V, Br=64, Bc=64, mask=None):
    N, d = Q.shape
    scale = 1.0 / np.sqrt(d)

    O   = np.zeros_like(Q)        # final output
    m   = np.full((N,), -np.inf)  # running max
    l   = np.zeros((N,))          # running denominator
    acc = np.zeros((N, d))        # un-normalized output

    # Tr = number of row blocks, Tc = number of column blocks
    Tr = (N + Br - 1) // Br
    Tc = (N + Bc - 1) // Bc

    for j in range(Tc):
        # Load K, V blocks for this column tile
        k_start, k_end = j * Bc, min((j + 1) * Bc, N)
        Kj = K[k_start:k_end]            # [Bc, d]
        Vj = V[k_start:k_end]            # [Bc, d]

        for i in range(Tr):
            r_start, r_end = i * Br, min((i + 1) * Br, N)
            Qi = Q[r_start:r_end]        # [Br, d]
            Oi = acc[r_start:r_end]      # running output rows
            mi = m[r_start:r_end]
            li = l[r_start:r_end]

            # 1) Compute scores for this tile pair
            Sij = (Qi @ Kj.T) * scale     # [Br, Bc]
            if mask is not None:
                Mij = mask[r_start:r_end, k_start:k_end]
                Sij = np.where(Mij == 0, -1e9, Sij)

            # 2) Online softmax update
            m_block = Sij.max(axis=-1)                        # [Br]
            m_new   = np.maximum(mi, m_block)
            alpha   = np.exp(mi - m_new)                      # [Br]
            beta    = np.exp(Sij - m_new[:, None])            # [Br, Bc]

            # 3) Update running stats and accumulator
            l_new   = alpha * li + beta.sum(axis=-1)
            acc[r_start:r_end] = (alpha[:, None] * Oi
                                  + beta @ Vj)
            m[r_start:r_end] = m_new
            l[r_start:r_end] = l_new

    O = acc / l[:, None]
    return O
```

Two things worth pointing out:

1. We never allocated an `[N, N]` matrix — only `[Br, Bc]` tiles. That's the HBM-traffic win.
2. The rescaling by `alpha` is what keeps everything numerically stable even when a later tile has a much larger max than an earlier one. Without it, `acc` would silently underflow.

### Step 4 — Causal masking for autoregressive models

For decoder-only models like the Llama family, the mask is lower-triangular. You can pass `mask=np.tril(np.ones((N, N)))` and the kernel above handles it for free. For a more realistic test, use a causal mask:

```python
N = 128
mask = np.tril(np.ones((N, N), dtype=np.int32))
O_ref = attention_reference(Q, K, V, mask=mask)
O_fast = flash_attention_np(Q, K, V, Br=32, Bc=32, mask=mask)
assert np.allclose(O_ref, O_fast, atol=1e-5, rtol=1e-5)
```

## Running and Testing It

A project that can't be verified in one command won't get starred. Put this in `tests/test_flash.py` and wire it up with pytest.

```python
import numpy as np
import pytest
from flash_attention_np import flash_attention_np, attention_reference

@pytest.mark.parametrize("N", [16, 64, 128, 257])  # non-power-of-two too
@pytest.mark.parametrize("d", [16, 32, 64])
def test_correctness(N, d):
    rng = np.random.default_rng(0)
    Q = rng.normal(size=(N, d)).astype(np.float32)
    K = rng.normal(size=(N, d)).astype(np.float32)
    V = rng.normal(size=(N, d)).astype(np.float32)
    O_ref = attention_reference(Q, K, V).astype(np.float32)
    O = flash_attention_np(Q, K, V, Br=32, Bc=32).astype(np.float32)
    assert np.allclose(O, O_ref, atol=1e-5, rtol=1e-5)

def test_causal_mask():
    rng = np.random.default_rng(1)
    N, d = 96, 32
    Q, K, V = (rng.normal(size=(N, d)) for _ in range(3))
    mask = np.tril(np.ones((N, N)))
    O_ref = attention_reference(Q, K, V, mask=mask)
    O = flash_attention_np(Q, K, V, Br=32, Bc=32, mask=mask)
    assert np.allclose(O, O_ref, atol=1e-5, rtol=1e-5)

def test_numerical_stability():
    # Inputs with huge scale — naive softmax would overflow, ours must not.
    rng = np.random.default_rng(2)
    Q = rng.normal(size=(256, 32)) * 50
    K = rng.normal(size=(256, 32)) * 50
    V = rng.normal(size=(256, 32))
    O = flash_attention_np(Q, K, V, Br=32, Bc=32)
    assert np.isfinite(O).all()
```

For runtime verification, this is the kind of benchmark that belongs in the README. Use `triton.testing.do_bench` if you want to mirror what real kernel authors do, or stick with `time.perf_counter`:

```python
import time

def bench(fn, *args, repeats=20):
    fn(*args)  # warmup
    t0 = time.perf_counter()
    for _ in range(repeats):
        out = fn(*args)
    return (time.perf_counter() - t0) / repeats, out

N, d = 1024, 64
rng = np.random.default_rng(3)
Q, K, V = (rng.normal(size=(N, d)) for _ in range(3))

t_ref, _ = bench(attention_reference, Q, K, V)
t_fast, _ = bench(flash_attention_np, Q, K, V, Br=64, Bc=64)
print(f"reference: {t_ref*1e3:.2f} ms  fused: {t_fast*1e3:.2f} ms")
```

Pure NumPy won't be faster than the reference — the win is *memory traffic*, which only shows up once you port to GPU. But you *can* demonstrate the structural property that matters: peak allocated memory for the score matrix drops from `O(N²)` to `O(Br·Bc)`.

```python
import tracemalloc

tracemalloc.start()
attention_reference(Q, K, V)
peak_ref = tracemalloc.get_traced_memory()[1]

tracemalloc.reset_peak()
flash_attention_np(Q, K, V, Br=32, Bc=32)
peak_fast = tracemalloc.get_traced_memory()[1]
print(f"reference peak: {peak_ref/1e6:.1f} MB  fused peak: {peak_fast/1e6:.1f} MB")
```

On `N=4096, d=64` you'll see the fused version use roughly `Br·Bc·4` bytes of score buffer regardless of `N` — that's the whole point.

## Extending It: Your Roadmap to Senior-Level

A weekend project gets you the repo. The upgrades below turn it into something a staff engineer would actually respect on a CV.

1. **Port the inner loop to Triton.** Keep the NumPy reference for tests, port `flash_attention_np` block-by-block to [Triton](https://triton-lang.org/) kernels. You'll get a 5–20× speedup on a single A100 and learn how `tl.dot`, `tl.exp`, and SRAM tiles compose — the same primitives used inside [vLLM's](https://github.com/vllm-project/vllm) PagedAttention.

2. **Add multi-head and batched inputs.** Promote everything to `[B, H, N, d]`. This is the boring engineering that production kernels live or die on, and it's where you'll learn about strides, broadcasting, and avoiding accidental `O(B·H)` memory blowups — the same shape of bug that shows up in [PyTorch's `einops`](https://github.com/arogozhnikov/einops) reshapes.

3. **Wire up deterministic benchmarking with `triton.testing.do_bench`.** Plot runtime and memory bandwidth against `N` and `Br`. Hiring managers love a kernel repo with a graph in the README. The [PyTorch profiler](https://docs.pytorch.org/tutorials/recipes/recipes/profiler_recipe.html) and NVIDIA's [`nsys`](https://developer.nvidia.com/nsys-cli) are the gold standards here.

4. **Add a backward pass (Flash Attention 2 style).** Implement `dQ`, `dK`, `dV` using the same tiling logic. This is where most tutorials stop, and it's also where the [FlashAttention repo](https://github.com/Dao-AILab/flash-attention) shines — the backward pass re-runs the forward statistics to avoid storing intermediates.

5. **Benchmark against `F.scaled_dot_product_attention`.** On a GPU Triton port, you should land within 1.3× of PyTorch's built-in for moderate `N`. Document the gap and explain *why*: missing CUDA Graphs, missing fp8, missing warp-specialization — all of which are real kernel engineering terms you can now speak fluently in an interview.

6. **Containerize with CUDA + a small HTTP demo.** Wrap the kernel in a FastAPI service that accepts `[N, d]` JSON, runs attention, and returns timings. Add Prometheus metrics for `request_duration_seconds` and a Grafana dashboard JSON in `monitoring/`. The "kernel" is the interesting bit; the "service around it" is what shows you can ship.

## Key Takeaways

- Flash Attention is a **fusion and memory-traffic** problem, not a math problem. The math is unchanged; the win is never materializing the `[N, N]` score matrix.
- The **online softmax recurrence** is what makes streaming stable. `m_new = max(m_old, m_block)` plus the corresponding rescaling is the whole trick.
- A NumPy port is the right scope for a CV project: small enough to review, real enough to teach, and a natural stepping stone to a [Triton](https://triton-lang.org/) or CUDA port.
- Memory peaks drop from `O(N²)` to `O(Br·Bc)`. Prove that with `tracemalloc` and put the number in the README.
- The differentiator is **showing your work**: tests, a benchmark plot, a backward pass, and a service. That's what turns a tutorial clone into a systems signal.

## Further Reading

- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness (Dao et al., 2022)](https://arxiv.org/abs/2205.14135) — the original paper; section 2.1 walks through the tiled algorithm you'll be implementing.
- [FlashAttention-2: Faster Attention with Better Parallelism and Work Partitioning (Dao, 2023)](https://arxiv.org/abs/2307.08691) — the production version, with the backward-pass strategy.
- [Online normalizer calculation for softmax (Milakov & Gimelshein, 2018)](https://arxiv.org/abs/1802.03881) — the streaming softmax recurrence this whole kernel rests on.
- [Triton language documentation](https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html) — the canonical "fused attention" tutorial, and the natural target for a follow-up port.
- [PyTorch `torch.nn.functional.scaled_dot_product_attention` reference](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html) — what every modern backend dispatches to; understanding its dispatch keys is its own lesson.
- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — how production systems extend the same ideas to KV-cache paging.