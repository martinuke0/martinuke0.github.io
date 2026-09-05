---
title: "Optimizing Triton Kernels for Custom Attention Patterns on H100 GPUs"
date: "2026-09-05T20:00:28.159"
draft: false
tags: ["triton", "gpu-kernels", "h100", "attention-mechanisms", "transformer-inference", "performance-engineering"]
description: "Practical guide to writing and tuning Triton attention kernels for non-standard patterns, from tiling to warp-specialized scheduling on H100."
summary: "A working engineer's guide to squeezing the H100 with custom Triton kernels: tile sizing, swizzle patterns, pipeline stages, and the warp-specialization tricks that make non-vanilla attention fly."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-optimizing-triton-kernels-for-custom-attention-patterns-on-h100-gpus.svg"
  alt: "Stylized diagram of a GPU die with attention tile matrices overlaid in cyan and amber."
  caption: ""
  relative: false
---

> **TL;DR** — FlashAttention is the easy 80% of dense self-attention, but production rarely stays dense. Custom masking, sliding windows, paged KV, and cross-attention with structured sparsity all demand bespoke kernels. On the H100, the levers that matter are tile shape, num_stages, num_warps, warp-specialized producer/consumer splits, and TMA descriptor reuse — not raw FLOPs.

If you've spent the last two years working with transformer inference, you've probably shipped some variant of FlashAttention and called it a day. And for dense, unmasked, single-batch self-attention on Qwen-shaped context lengths, that's the right call. The reference kernels are good, well-tested, and someone else is paying for the maintenance.

The trouble starts the moment attention stops being vanilla. The moment you need:

- A custom mask (causal-prefix, document-mask, hash-based retrieval masking)
- Sliding-window or dilated patterns (Mistral, LongRoPE, recurrent attention layers)
- Paged KV caches with block-level indirection (vLLM-style)
- Cross-attention against a structured key/value tensor
- Hardware-aware sparsity (2:4 fine-grained, block-sparse for long context)

Each of these breaks one of FlashAttention's invariants. So you write your own. And on H100, "writing your own" turns into a Triton-tuning exercise that rewards pattern recognition over theoretical knowledge.

This post is a working engineer's field guide — what to tune, in what order, and which combinations are known to fall on their face on H100.

## Why the H100 Changes the Calculus

The H100 SXM5 isn't just an A100 with more FLOPs. The architectural shifts that matter for attention kernels are:

- **Asynchronous copy via TMA** (`tl.make_block_ptr` + `cp.async.bulk`) replaces the manual `cp.async` ping-pong of Hopper previews
- **Warp-specialization** — producer warps can issue TMA loads while consumer warps do MMA, with explicit `tl.async_task` boundaries
- **Distributed shared memory** (`tl.store_to_shmem` / cluster-level DSMEM) for kernels across SMs
- **FP8 tensor cores** with `mxfp8` and `nvfp4` on the roadmap, but FP16/BF16 still dominate attention

The upshot: the bottleneck for an *unoptimized* H100 attention kernel is memory bandwidth, just like every GPU before it. The difference is that H100 has so much bandwidth (3 TB/s HBM3e) that the only thing left to optimize is **latency hiding** — making sure every cycle, the tensor cores are fed.

A useful mental model from [the Triton `tl.async_task` docs](https://triton-lang.org/main/python-api/generated/triton.language.async_task.html): think of your kernel as a pipeline, not a loop. Every load is a stage, every compute is a stage, and your job is to keep the pipeline full.

## The Standard Optimizer's Playbook

Before reaching for warp-specialization, walk through these in order. Most custom attention kernels are within 15–20% of FlashAttention's throughput after just the first three.

### 1. Tile Shape: `BLOCK_M`, `BLOCK_N`, `BLOCK_K`

Tile shape is 80% of the battle on H100. The tile is the unit of work for a single program, and you want each program to:

- Fit K and V tiles in shared memory together (V is read once per K row, so it pays to keep both resident)
- Have K dimension at least 64 to amortize TMA descriptor setup
- Avoid `BLOCK_M` > 128 unless you have a reason (sm_90 register pressure is real)

A solid starting point for H100 with FP16, head_dim=64 or 128:

```python
# Pre-GA sizing, still works well on H100 SXM
BLOCK_M = 128
BLOCK_N = 64
BLOCK_K = 64  # for head_dim=64; use 32 for head_dim=128
```

For head_dim=128, you'll typically find that `BLOCK_M=64, BLOCK_N=128, BLOCK_K=64` outperforms `BLOCK_M=128` because the larger `BLOCK_N` halves the number of online-softmax passes. The cost is occupancy — measure, don't guess.

### 2. Pipeline Depth: `num_stages`

`num_stages` controls software pipelining — how many iterations of the K-loop are in flight. More stages = more concurrent loads = better latency hiding, up to a point.

| num_stages | When it helps | When it hurts |
|---|---|---|
| 2 | Small tiles, low register pressure | Almost never optimal on H100 |
| 3 | Default for most attention kernels | — |
| 4 | Large head_dim, FP8 | Register spills if you're not careful |
| 5+ | TMA-heavy kernels with light compute | Almost always a regression |

The reason `num_stages=2` is rarely right on H100 is that TMA hides latency so well that you almost always want at least one extra load in flight. The reason `num_stages=5` is rarely right is that you run out of registers before you run out of stages. As [the Triton tutorial on attention](https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html) notes, the sweet spot is usually 3 or 4.

### 3. Warp Count: `num_warps`

The H100 has 4 warp schedulers per SM, and the sweet spot for attention is almost always 4 warps — *not* 8. The reasoning:

- Each warp does an MMA tile of 16×16×16 (or 16×8×16 for FP16)
- 4 warps × one 64-wide MMA tile per warp = full 128-wide MMA, exactly matching the tensor core
- Going to 8 warps splits each MMA tile across more warps, which adds shfl overhead

The exception: very small tiles or very wide `BLOCK_M` (256+). For those, 8 warps can help amortize the per-warp overhead.

### 4. Autotuning — But With Care

Triton's `@triton.autotune` will find a good config, but it's a search, not an oracle. Pitfalls:

```python
@triton.autotune(
    configs=[
        triton.Config({'BLOCK_M': 64,  'BLOCK_N': 64,  'BLOCK_K': 64}, num_warps=4, num_stages=3),
        triton.Config({'BLOCK_M': 128, 'BLOCK_N': 64,  'BLOCK_K': 64}, num_warps=4, num_stages=3),
        triton.Config({'BLOCK_M': 128, 'BLOCK_N': 128, 'BLOCK_K': 32}, num_warps=8, num_stages=3),
        triton.Config({'BLOCK_M': 64,  'BLOCK_N': 128, 'BLOCK_K': 32}, num_warps=4, num_stages=4),
    ],
    key=['HEAD_DIM', 'CAUSAL', 'MASK_TYPE'],
)
```

Note the `key=` argument. If you autotune over all of `Q.shape`, you'll spend an hour re-tuning on every batch size. Anchor on the things that change the optimal config: head dim, mask type, dtype.

## Patterns in Production: Three Kernels Worth Studying

Theory is cheap; here's what real code looks like for three custom-attention scenarios that come up repeatedly.

### Pattern A: Custom Document Mask

Document-masked attention (each token attends only within its own document segment) shows up everywhere — long-context inference, retrieval pipelines, multi-tenant embedding models. The mask isn't causal, it's piecewise-circular.

The naive implementation passes a boolean mask of shape `[SEQ_LEN, SEQ_LEN]`. That's 256 MB at seq=16K in FP16, and the load alone costs more than the compute. Instead:

```python
@triton.jit
def doc_mask_attn_kernel(
    Q, K, V, Out,
    doc_offsets,         # [num_docs + 1] — start indices of each document
    sm_scale,
    stride_qm, stride_qk,
    stride_kn, stride_kk,
    stride_vn, stride_vk,
    stride_om, stride_on,
    HEAD_DIM: tl.constexpr,
    BLOCK_M: tl.constexpr,
    BLOCK_N: tl.constexpr,
):
    start_m = tl.program_id(0)
    # Find which document this query row belongs to via binary search
    doc_idx = tl.searchsorted(doc_offsets, start_m, right=True) - 1
    doc_start = tl.load(doc_offsets + doc_idx)
    doc_end = tl.load(doc_offsets + doc_idx + 1)

    offs_m = start_m * BLOCK_M + tl.arange(0, BLOCK_M)
    offs_n = tl.arange(0, BLOCK_N)
    offs_k = tl.arange(0, HEAD_DIM)

    # Mask in the score loop: tokens outside [doc_start, doc_end) are -inf
    valid_n = (offs_n[None, :] + (start_n * BLOCK_N) >= doc_start) & \
              (offs_n[None, :] + (start_n * BLOCK_N) <  doc_end)
    # ... standard flash-attn inner loop, gated by valid_n ...
```

The trick: precompute `doc_offsets` once on the host (it's `O(num_docs)`), and inside the kernel, **only emit the boundary check on the first K tile**. Inside a document, the mask is constant True and you can skip it entirely. With careful `tl.where` placement, this kernel hits ~92% of FlashAttention's throughput on dense workloads while supporting arbitrary document boundaries.

The autotune key for this kernel should include `MASK_TYPE: tl.constexpr` set to `"doc"` vs `"causal"` vs `"none"`. The optimal `BLOCK_N` is meaningfully different — document attention benefits from larger `BLOCK_N` because there's no triangular structure to exploit.

### Pattern B: Sliding-Window Attention

Mistral-style sliding window (each token attends to ±W neighbors) is structurally simple but kills naive implementations because:

1. The window is small (W=4096 typical), so most attention is masked out
2. The mask pattern is *regular*, which means we can specialize the K-loop bounds

The optimization is straightforward — bound the K-loop:

```python
# In the kernel, start_n becomes a function of start_m and WINDOW:
start_n_min = max(0, (start_m * BLOCK_M - WINDOW) // BLOCK_N)
start_n_max = min(num_n_blocks, (start_m * BLOCK_M + BLOCK_M + WINDOW) // BLOCK_N)

# Then iterate start_n in [start_n_min, start_n_max) instead of [0, num_n_blocks)
for start_n in range(start_n_min, start_n_max):
    # ... standard inner loop, no mask needed for the window itself
```

A second optimization: **precompute the boundary mask per K tile**. The window's boundary is diagonal in the Q-K plane, and you only need the mask on the first and last K tile. Inside the window, the mask is True. Inside the kernel:

```python
at_left_edge  = (start_n == start_n_min)
at_right_edge = (start_n == start_n_max - 1)
needs_mask = at_left_edge | at_right_edge
```

Then `tl.where(needs_mask, masked_score, score)` instead of computing the mask every iteration. This shaves ~8% off a sliding-window kernel at W=4096, seq=32K — meaningful when you're running at 50K tokens/sec.

The deeper lesson: **attention mask regularity is the most under-exploited lever**. Triangular masks, document masks, sliding windows, and prefix-LM masks all have exploitable structure. Spend the engineering time making the mask a `constexpr`, not a runtime tensor.

### Pattern C: Paged KV with Block-Sparse Cross-Attention

This is where it gets hard. vLLM-style paged KV gives you per-sequence-page block tables, and you want to do cross-attention where each query row attends to a different subset of pages (e.g., retrieval, multi-modal, prefix-caching with selective eviction).

The naive approach — gather pages, then run a standard kernel — wastes half the bandwidth because each query block reads its own set of pages. The right approach is a **two-stage kernel**:

1. **Page-gather kernel**: produces a dense "logical KV" layout where each query block's pages are contiguous in memory
2. **Standard attention kernel** on the gathered layout

The gather kernel is a textbook case of memory-bandwidth-bound work:

```python
@triton.jit
def gather_pages(
    K_src, V_src,            # paged tensors, [num_pages, page_size, head_dim]
    K_dst, V_dst,            # dense buffers,    [batch, max_pages_per_seq, page_size, head_dim]
    block_tables,            # [batch, max_pages_per_seq] -> page indices
    stride_src_p, stride_src_s,
    stride_dst_b, stride_dst_p, stride_dst_s,
    BATCH: tl.constexpr,
    MAX_PAGES: tl.constexpr,
    PAGE_SIZE: tl.constexpr,
    HEAD_DIM: tl.constexpr,
):
    pid = tl.program_id(0)
    # pid decodes to (batch_idx, page_slot) — both constants within the program
    page_idx = tl.load(block_tables + pid // MAX_PAGES * MAX_PAGES + (pid % MAX_PAGES))
    # ... bulk copy K[page_idx] -> K_dst[pid]
```

The autotune key here is dominated by `PAGE_SIZE` — typically 16 or 64. Smaller pages mean more gather overhead; larger pages mean more wasted gather bandwidth when blocks are partially filled. vLLM's default of 16 strikes a balance, and [their engineering blog](https://blog.vllm.ai/2023/06/20/vllm.html) walks through the trade-offs in detail.

## Warp-Specialization: When You Actually Need It

Most custom attention kernels don't need warp specialization. The crossover is around 3 of these being true:

- `HEAD_DIM >= 128`
- `BLOCK_M * BLOCK_N >= 16384` (large tiles)
- KV-cache sequence length > 16K (long context)
- FP8 or other quantization where register pressure is extreme

If you do need it, here's the shape:

```python
@triton.jit
def warp_specialized_attn(
    Q, K, V, Out,
    HEAD_DIM: tl.constexpr,
    BLOCK_M: tl.constexpr,
    BLOCK_N: tl.constexpr,
):
    # Producer warp issues TMA loads
    if tl.async_task([0]):
        # Load K[block_n], V[block_n] via TMA
        # Signal consumers via mbarrier
        ...
    # Consumer warps do MMA + softmax
    if tl.async_task([1]):
        # Wait for K/V tile
        # MMA, online softmax
        ...
```

The `tl.async_task` decorator is the entry point. Two things that bite people:

1. **Producer warps must complete before exit.** Use `tl.async_task_wait` or the consumer will read garbage.
2. **Cluster launch.** Warp-specialized kernels typically benefit from `cluster_dims` > 1, but each cluster eats shared memory across SMs.

For most teams, the right answer is to read the [Triton tutorial on warp-specialized persistent kernels](https://triton-lang.org/main/getting-started/tutorials/09-persistent-matmul.html) and then ask: do we *actually* need this? Often the answer is no, and a well-tuned `num_stages=4` non-specialized kernel gets you 95% of the way.

## Common Failure Modes on H100

A short catalog of things that look like kernel bugs but are tuning issues.

### Register Spills (the silent killer)

If your kernel's spills are >0 in `nsys` output, no amount of autotuning will help. The fix is almost always one of:

- Reduce `BLOCK_M` or `BLOCK_N` by 2x
- Reduce `num_stages` by 1
- Replace `tl.exp2` with the native `tl.exp` (counter-intuitively, `exp2` can spill due to its LUT)
- For FP8 kernels, ensure scale tensors are in registers, not loaded per iteration

### Bank Conflicts in Shared Memory

`tl.swizzle2d` and `tl.advance` are the cure. The default block pointer layout has bank conflicts on the V tile for head_dim=128. If you see shared memory transactions dominate your profile, that's the issue.

```python
# After loading V, swizzle to avoid 4-way bank conflicts
v_tile = tl.swizzle2d(v_tile, (1, 1), (8, 8))  # for head_dim=128
```

### TMA Descriptor Reuse

TMA descriptors are expensive to set up (hundreds of cycles). The `block_ptr` API in modern Triton reuses descriptors across iterations of the K-loop, but only if the strides are `constexpr` and you don't recompute `tl.make_block_ptr` inside the loop.

### FP8 Numerical Stability

If you're doing FP8 attention (and you should — see [the Transformer Engine FP8 docs](https://docs.nvidia.com/deeplearning/transformer-engine/), it gives ~1.5x throughput), the trick is per-tile FP32 accumulation of the softmax statistics, not per-row. The math is the same, but the noise floor is dramatically lower for the d-term (`m_i`, `l_i`) when they're computed per-tile.

## Key Takeaways

- **Tile shape dominates.** Get `BLOCK_M`, `BLOCK_N`, `BLOCK_K` right for your workload before touching anything else.
- **`num_stages=3` or `4` is the default.** Don't go to 5+ without measurement.
- **4 warps beats 8 warps** for typical attention tiles on H100. Trust the rule until profiling says otherwise.
- **Custom masks should be `constexpr` whenever possible.** Document, sliding-window, and prefix-LM masks all have exploitable structure.
- **Autotune on shape *invariants*, not shape values.** Use `key=['HEAD_DIM', 'MASK_TYPE']`, not `key=['Q.shape[1]']`.
- **Warp-specialization is a 5–10% optimization, not a 2x one.** Reach for it only after the easy wins.
- **Watch for register spills.** They're the most common reason a "should-be-fast" kernel runs at 60% of expected throughput.
- **Two-stage kernels win for paged/sparse patterns.** A gather pass followed by dense attention often beats a single fused kernel.

## Further Reading

- [Triton Fused Attention Tutorial](https://triton-lang.org/main/getting-started/tutorials/06-fused-attention.html) — the canonical reference, walks through FlashAttention-2 in Triton
- [FlashAttention-2 Paper](https://arxiv.org/abs/2307.08691) — the algorithm almost every modern attention kernel implements
- [FlashAttention-3 Paper](https://arxiv.org/abs/2407.08608) — Hopper-specific tricks including warp specialization and FP8
- [vLLM PagedAttention Blog Post](https://blog.vllm.ai/2023/06/20/vllm.html) — production paged KV, the gathering pattern in detail
- [Transformer Engine FP8 Documentation](https://docs.nvidia.com/deeplearning/transformer-engine/) — the production-grade FP8 path on H100
- [Triton `tl.async_task` API Reference](https://triton-lang.org/main/python-api/generated/triton.language.async_task.html) — the warp-specialization entry point
- [NVIDIA Hopper Architecture Whitepaper](https://resources.nvidia.com/en-us-hopper-architecture) — the underlying hardware: TMA, distributed shared memory, async barriers