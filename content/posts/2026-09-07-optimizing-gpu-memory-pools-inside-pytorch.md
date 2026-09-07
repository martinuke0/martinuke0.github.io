---
title: "Optimizing GPU Memory Pools: Inside PyTorch's CUDA Caching Allocator"
date: "2026-09-07T17:15:15.733"
draft: false
tags: ["pytorch", "cuda", "gpu", "memory-management", "deep-learning"]
description: "A deep dive into PyTorch's CUDA caching allocator: how it pools VRAM, why it matters for LLM training, and how to tune it for production."
summary: "PyTorch's CUDA caching allocator hides the cost of repeated allocations by recycling VRAM in fixed-size blocks. Here's how it works, why it matters at scale, and how to squeeze more performance out of it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-optimizing-gpu-memory-pools-inside-pytorch.svg"
  alt: "Stylized diagram of GPU memory blocks being cached and reused across allocations."
  caption: ""
  relative: false
---

> **TL;DR** — PyTorch's CUDA caching allocator intercepts every `cudaMalloc` and serves it from a per-device block pool, eliminating the 1–10 ms cost of talking to the driver. Understanding block sizes, the LRU eviction path, and tools like `expandable_segments` and `torch.cuda.memory_stats()` is the difference between training a 7B model at 60% GPU utilization and one that fits a 30% longer context window on the same H100.

## Why a "Caching Allocator" Exists at All

The first thing every CUDA learner finds out is that `cudaMalloc` is slow. On modern GPUs it costs anywhere from a few hundred microseconds to several milliseconds, depending on the driver, the size requested, and the current fragmentation state of the heap. For a model with hundreds of millions of parameters and activations that change shape every layer, calling `cudaMalloc` on every forward pass is not a rounding error — it can eat 10–20% of your wall-clock time.

The traditional fix is what every high-performance runtime eventually reinvents: a **memory pool**. PyTorch's [CUDA caching allocator](https://pytorch.org/docs/stable/notes/cuda.html#cuda-memory-management) is its implementation of that pattern, designed to make subsequent allocations of the same shape effectively free.

The design goals, as documented in the PyTorch source and summarized in the [PyTorch internals notes](https://docs.pytorch.org/docs/stable/notes/cuda.html), are:

1. **Avoid `cudaMalloc`** by reusing previously freed blocks.
2. **Reduce fragmentation** by rounding allocations up to a small set of canonical block sizes.
3. **Preserve stream semantics** so asynchronous work on one stream cannot read memory that another stream has already returned to the pool.
4. **Stay out of the way** — the user-facing API (`torch.zeros`, `nn.Linear`) shouldn't have to know any of this is happening.

## The Block Pool: How Memory Is Organized

At the heart of the allocator sits a structure called the **BlockPool**. Each device has one, and each pool holds a free list of `Block` objects, each describing a contiguous region of device memory. A block has three things that matter:

- **size** — the number of bytes it represents
- **stream** — the CUDA stream it was last used on (used for stream-aware recycling)
- **allocated** — whether it's currently in use or free

Free blocks are indexed in two structures: a **size-indexed map** for fast "give me something at least N bytes" lookups, and an **LRU list** so we can evict the coldest blocks when the pool needs to shrink under memory pressure.

Allocations are rounded up to one of a fixed set of **block sizes**: 512 bytes, then doubling roughly up to 2 GB, with an additional "huge" bucket for very large requests. The exact list lives in `BlockPool`'s `kSmallBucketSizes` and friends; you can also see it reflected in [the profiling metrics](https://docs.pytorch.org/docs/stable/notes/cuda.html#memory-stats) under `cuda.memory_stats()`.

```text
Bucket sizes (approximate, in bytes):
  512
  1 KiB
  2 KiB
  ...
  1 GiB
  2 GiB   ("huge", split into 2 GiB + remainder if possible)
```

This rounding is deliberate. It means a `tensor.view(1024, 1024)` and a `tensor.view(2048, 512)` will both land in the same bucket and can share a block — but they will never fragment the pool into thousands of sub-megabyte stragglers.

## The Allocator Hot Path

When you call `torch.empty(1024, 1024, device='cuda')`, here's what happens in microseconds:

1. **Compute the requested size** (1 MiB plus alignment overhead).
2. **Round up** to the next bucket — in this case, 2 MiB.
3. **Look up the bucket** in the size-indexed map.
4. If a free block exists, **pop it**, mark it allocated, and hand it back. Done.
5. If no free block exists, **ask `cudaMalloc`** for 2 MiB, register the resulting pointer as a new block, and hand it back.

The slow path (step 5) is what makes everything else worth it. A well-tuned training loop should hit step 5 a small number of times — typically once per unique tensor shape — and then ride the cache for the rest of the run.

The free path is symmetric but with one twist: blocks are not returned to the free pool until PyTorch's caching allocator is confident they are no longer in use on any stream. This is why you'll sometimes see "reserved" memory stay high even after you `del` a tensor. The allocator needs to wait for the relevant CUDA stream to flush before it can recycle the bytes.

## Stream-Aware Recycling

If you've ever wondered why PyTorch doesn't immediately give freed memory back to the OS, the answer is **stream-aware deferred reuse**. CUDA streams allow work to be reordered in interesting ways, and a block freed on stream A could still be referenced by a pending kernel on stream B if you reused it too eagerly.

The allocator tracks a `stream` per block and only reuses it on compatible streams. This is one of the reasons behind `torch.cuda.synchronize()` recommendations in profiling docs: if you call it before measuring memory, you'll see the actual free pool instead of the in-flight allocations that look "allocated" but are about to be released.

For production, the practical implication is: **don't share a single tensor across streams with very different timing characteristics** unless you're prepared for the allocator to hold its memory longer than you expect.

## The LRU Eviction Path

When the pool needs to shrink — usually because you're allocating something larger than the current free pool can satisfy — the allocator calls `cudaFree` on the coldest blocks first. The LRU list is updated on every allocation and deallocation, so a tensor you've been holding for 100 steps is the last to get evicted.

This behavior is exposed through the `cuda.memory_stats()` interface:

```python
import torch
torch.cuda.memory_stats()
# {'num_alloc_retries': 0,
#  'num_ooms': 0,
#  'num_sync_all_streams': 0,
#  'num_device_alloc': 142,
#  'num_device_free': 138,
#  'allocated_bytes.all.peak': 2147483648,
#  'reserved_bytes.all.peak': 3221225472,
#  ...}
```

Two of those counters are worth watching in production:

- `num_alloc_retries` — how often the allocator had to free other blocks before satisfying a new request. A non-zero value means your working set is bumping up against your reservation ceiling.
- `num_sync_all_streams` — how often the allocator had to synchronize every stream before reusing a block. Frequent sync points in this counter often correlate with slowdowns.

## Patterns in Production: Where the Allocator Pays Off (and Where It Doesn't)

### Where it pays off

**Training loops with fixed shapes.** The classic LLM training step allocates the same shapes of activations, gradients, and optimizer states on every step. After a warm-up of a few iterations, the pool is fully populated with the right blocks and the allocator becomes essentially free.

**Inference servers with batching.** vLLM, SGLang, and similar systems allocate KV caches of the same shape for every sequence. The caching allocator turns what would be millions of `cudaMalloc` calls into a handful.

**Repeated evaluation loops.** When you run the same model on the same eval set repeatedly, you're effectively measuring the warm-cache scenario.

### Where it doesn't

**Highly dynamic shapes.** Mixture-of-experts models, variable-length generation, and ragged input pipelines can produce a long tail of unique block sizes. The pool fills with tiny stragglers and you end up with high `reserved_bytes.all.current` but low `allocated_bytes.all.current` — the textbook fragmentation signature.

**Multi-process sharing.** PyTorch's allocator is per-process. If you spawn N dataloader workers that each load large tensors into CUDA (a common antipattern), each worker has its own pool and you can easily OOM even though the math says it should fit.

**CUDA Graphs capture.** During graph capture, every allocation goes through a special path that pre-reserves a contiguous region. After capture, you're committed to that layout — which is usually great, until the layout doesn't fit your next workload.

## Tuning the Allocator

### 1. `expandable_segments` (PyTorch ≥ 2.8)

The default allocator rounds allocations up to bucket sizes, which can waste VRAM when your tensors vary in size. Setting `expandable_segments=True` lets the allocator carve up segments more flexibly, often giving back 5–15% of peak VRAM for workloads with variable shapes. It's a flag in the [CUDA allocator config docs](https://docs.pytorch.org/docs/stable/notes/cuda.html#cuda-memory-management).

```bash
PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True python train.py
```

### 2. `max_split_size_mb` and `garbage_collection_threshold`

If you're seeing frequent allocator retries, lowering `max_split_size_mb` (the threshold above which a block won't be split to satisfy a smaller request) can keep smaller blocks available for reuse instead of being fragmented out by huge ones. Bumping `garbage_collection_threshold` (default 0.8) makes the allocator more aggressive about returning memory to the driver at the cost of more `cudaMalloc` calls later.

### 3. `torch.cuda.empty_cache()`

This is the explicit "flush the pool back to the driver" button. It's useful between two distinct phases — say, profiling and eval, or two unrelated inference requests — but it's almost never useful inside a training loop. If you're calling it inside your step function, you almost certainly have a bug.

### 4. Memory snapshotting for debugging

`torch.cuda.memory_snapshot()` returns a structured view of every live allocation. Combined with the optional `trace_allocator` (in [the memory debugging docs](https://docs.pytorch.org/docs/stable/notes/cuda.html#debugging)), it's the fastest way to find that "who allocated 4 GB and never freed it?" tensor.

## A Mini Profiling Recipe

When a workload is mysteriously slow or OOMing, this sequence usually finds the answer in under five minutes:

```python
import torch

# Baseline
torch.cuda.reset_peak_memory_stats()

# Warm-up
for batch in loader:
    loss = model(batch)
    loss.backward()
    optimizer.step()
    optimizer.zero_grad()

torch.cuda.synchronize()
print(torch.cuda.memory_summary())

# Steady-state
torch.cuda.reset_peak_memory_stats()
for batch in loader:
    loss = model(batch)
    loss.backward()
    optimizer.step()
    optimizer.zero_grad()
    if step % 50 == 0:
        s = torch.cuda.memory_stats()
        print(step, s['num_alloc_retries'], s['allocated_bytes.all.current'])

torch.cuda.synchronize()
print(torch.cuda.memory_summary())
```

You're looking for three things:

1. `num_alloc_retries` should be near zero. Non-zero means you're working at the edge of your reservation.
2. `allocated_bytes.all.peak` should be well below `reserved_bytes.all.peak`. A small gap means clean allocation; a big gap means fragmentation.
3. `num_sync_all_streams` should be near zero in steady state. A non-zero value often correlates with cross-stream data dependencies.

## A Concrete Production Win

A team training a 7B-parameter model on 8×H100 reported persistent OOMs at sequence length 8192 that went away at 4096. The math said it should fit. Profiling with the recipe above showed `num_alloc_retries` climbing into the thousands per step, with `reserved_bytes.all.peak` 30% higher than `allocated_bytes.all.peak`. Switching to `expandable_segments:True` reclaimed the 30%, and 8192 just worked — no code changes, no smaller batch size. That is, in one sentence, why understanding the caching allocator pays off.

## Key Takeaways

- PyTorch's caching allocator serves almost every CUDA allocation from a per-device block pool, avoiding the 1–10 ms cost of `cudaMalloc` in the hot path.
- Blocks are rounded to canonical bucket sizes to prevent fragmentation; the tradeoff is some wasted bytes inside each block.
- The allocator is stream-aware, which is why freed memory sometimes stays "reserved" longer than you'd expect.
- `num_alloc_retries`, `allocated_bytes.all.peak`, and `reserved_bytes.all.peak` from `torch.cuda.memory_stats()` are the three counters to watch in production.
- `expandable_segments:True` is the single biggest win for workloads with variable tensor shapes; it can give back 5–15% of peak VRAM with no code change.

## Further Reading

- [PyTorch CUDA memory management documentation](https://docs.pytorch.org/docs/stable/notes/cuda.html#cuda-memory-management)
- [PyTorch CUDA memory debugging documentation](https://docs.pytorch.org/docs/stable/notes/cuda.html#debugging)
- [PyTorch CUDA semantics notes](https://docs.pytorch.org/docs/stable/notes/cuda.html)
- [NVIDIA CUDA Programming Guide — Memory management](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#memory-management)