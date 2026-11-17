---
title: "Mastering vLLM's PagedAttention: Continuous Batching for High-Throughput LLM Inference"
date: "2026-11-17T13:01:34.686"
draft: false
tags: ["vLLM", "LLM Inference", "PagedAttention", "Continuous Batching", "GPU Memory", "High-Throughput"]
description: "Learn how vLLM's PagedAttention and continuous batching deliver 10-20x throughput gains over naive LLM serving, with practical architecture insights and production patterns."
summary: "vLLM's PagedAttention treats KV cache like virtual memory pages, eliminating fragmentation and enabling continuous batching that dramatically improves LLM inference throughput."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-17-mastering-vllm.svg"
  alt: "A server rack with glowing GPU indicators representing high-throughput LLM inference"
  caption: ""
  relative: false
---

> **TL;DR** — vLLM's PagedAttention treats the KV cache as a pool of virtual memory pages, eliminating the fragmentation that plagues naive LLM serving. Combined with continuous batching—which adds new requests as soon as a single token is decoded rather than waiting for an entire sequence to finish—this approach delivers 10–20x throughput improvements over static batching. If you're running LLM inference in production, understanding these two mechanisms is the difference between paying for idle GPU memory and squeezing every FLOP out of your hardware.

## Why LLM Inference Is Hard

Serving a large language model is fundamentally different from serving a traditional REST API. When a model generates a response, it must attend to every token it has produced so far. The mechanism for storing these intermediate computations is the **KV cache**—a tensor of key and value vectors that grows linearly with each decoded token. For a 70B-parameter model with a context window of 4,096 tokens, a single request can consume several gigabytes of GPU memory just for this cache. Multiply that by a few hundred concurrent users and you're looking at tens of gigabytes per GPU, easily exceeding the 24–80 GB capacity of a single A100 or H100.

The naive approach is to pre-allocate a fixed block of KV cache for each request at the moment it arrives. This is simple, but it has two crippling problems. First, **fragmentation**: if you allocate a contiguous chunk for each request's maximum possible length, you waste enormous amounts of memory because most requests finish well before hitting the limit. Second, **underutilization**: in a static batch, the GPU sits idle waiting for the longest-running sequence to finish, even if every other request in the batch has already completed.

These problems compound quickly in production. A 2023 study by [vLLM's authors](https://arxiv.org/abs/2306.05669) showed that naive KV cache management can waste over 60% of available GPU memory, directly translating to fewer concurrent users per dollar of infrastructure spend. The industry needed a better abstraction—and vLLM delivered one.

## PagedAttention: Virtual Memory for the KV Cache

### The Fragmentation Problem

To understand why PagedAttention matters, you first need to see what it replaces. In a traditional serving system, the KV cache for a request is allocated as a single contiguous block of GPU memory. If you reserve space for 4,096 tokens but the request only generates 200, you've wasted 95% of that allocation. Worse, if you have 100 requests and each reserves 4,096 slots, you need memory for 409,600 token slots—even if your average request length is 200 tokens.

The operating system solved this exact problem decades ago with virtual memory paging. PagedAttention brings the same idea to LLM inference.

### How PagedAttention Works

PagedAttention divides the KV cache into fixed-size **blocks** (also called pages), typically 16 tokens each. Instead of allocating one contiguous chunk per request, it maintains a **block table**—a per-request mapping from logical block indices to physical GPU memory addresses. When a request needs to store the KV values for tokens 0–15, it gets assigned physical block #42. When it needs tokens 16–31, it might get physical block #17. The blocks don't need to be contiguous in memory.

This has three immediate consequences:

1. **No fragmentation waste.** A request that only needs 200 tokens occupies exactly 13 blocks (200 / 16, rounded up), not a pre-allocated 4,096-token chunk.
2. **Sharing is possible.** Since blocks are referenced by table rather than by address, two requests that share a common prefix (like a system prompt) can point to the same physical blocks. This is a massive win for structured applications like RAG pipelines or few-shot templates.
3. **Swap-in and swap-out are cheap.** If GPU memory is tight, entire blocks can be evicted to CPU memory and restored on demand, just like a OS page fault. vLLM implements this with a unified KV cache manager that tracks free blocks and handles swapping transparently.

### Block Tables and Page Allocation

The block table is the central data structure. For each request, it's essentially an array of pointers:

```
Request A: [block_42, block_17, block_88, ...]
Request B: [block_42, block_33, block_91, ...]  // shares block_42 with A
```

When the model decodes a new token and needs to append its KV values, the scheduler checks if the current block has free slots. If not, it allocates a new physical block from the free list and extends the table. This allocation happens in O(1) time—no large memcpy, no reformatting of existing cache data.

The block size is a tunable parameter. Smaller blocks (e.g., 8 tokens) reduce internal fragmentation but increase table overhead. Larger blocks (e.g., 32 tokens) improve cache locality at the cost of wasting more space on short requests. In practice, vLLM's default of 16 tokens works well across most workloads, but production deployments often tune this based on their p99 latency requirements.

## Continuous Batching: Rethinking Request Scheduling

### Static Batching: The Baseline

In a static batch, the scheduler waits for a batch to fill (or a timeout expires), sends all requests to the GPU together, and then **waits for every single one to finish** before starting the next batch. If your batch has 8 requests and one of them is generating a 2,000-token response while the other seven finish in 50 tokens, the GPU is idle for the duration of that long tail. This is catastrophically inefficient—the equivalent of a restaurant that refuses to seat new customers until every party at the table has finished eating.

### Iterative Batching: A Partial Fix

Some systems tried to fix this with iterative batching: after each token generation step, the scheduler checks which requests have finished and removes them, then adds new requests from the queue. The problem? The KV cache is still monolithic and contiguous, so adding a new request mid-batch requires either pre-allocating space for the maximum possible length (wasting memory) or pausing the batch to reformat the entire cache (killing latency). You get one benefit without the other.

### Continuous Batching: The vLLM Approach

Continuous batching flips the model. Instead of batching requests at the start and waiting for them to finish, vLLM **adds and removes requests at every token generation step**. Here's the flow:

1. The scheduler collects all pending requests and forms an initial batch.
2. The GPU runs one decode step for all requests in the batch.
3. Immediately after, the scheduler removes any requests that have hit their `max_tokens` limit or generated an EOS token.
4. The scheduler pulls new requests from the queue to fill the vacated slots.
5. Repeat from step 2.

Because PagedAttention uses block tables, adding a new request mid-generation is trivial: just allocate its initial blocks and append its block table to the batch's metadata. There's no need to reformat or copy existing KV data. The physical memory layout is decoupled from the logical request grouping.

This has profound implications for throughput. In a static batch, GPU utilization is bounded by the ratio of shortest-to-longest request in the batch. In continuous batching, the GPU is always saturated—every compute cycle processes real tokens for live requests. The only scheduling overhead is the O(1) block allocation per new request, which is negligible compared to the matrix multiplications happening on the GPU.

## Architecture in Production

### Memory Efficiency Gains

The combination of PagedAttention and continuous batching produces memory savings that are best understood with a concrete example. Consider serving a 13B-parameter model on a single A100 80GB GPU:

- **Naive static batching**: Each request reserves ~4 GB for KV cache (assuming 4,096 token context). The GPU can serve at most ~20 concurrent requests, and actual utilization is far lower because most requests finish early.
- **vLLM with PagedAttention**: The same GPU can serve 100+ concurrent requests because blocks are allocated on demand. The effective memory per request drops to ~200 MB for a 200-token response.

The published numbers from vLLM's paper show **up to 24x effective throughput improvement** over a naive baseline, though real-world gains depend heavily on workload characteristics. Short-generation workloads (chatbots, code completion) see the biggest wins because the gap between reserved and actual memory is largest.

### Throughput Benchmarks

vLLM's official benchmarks compare it against Hugging Face Transformers and FasterTransformer across several models. On LLaMA-2-13B with 64 A100 GPUs, vLLM achieves:

- **13,200 tokens/sec** vs. Hugging Face's **640 tokens/sec** (20x improvement)
- **95% GPU memory utilization** vs. Hugging Face's **35%**
- **P99 latency of 2.1 seconds** for 256-token generation vs. Hugging Face's **8.7 seconds**

These numbers are from synthetic benchmarks with uniformly distributed request lengths. In production with a real workload—where some requests are short and others are long—the gains are even more pronounced because continuous batching prevents the long-tail problem from dragging down the entire batch.

### Scheduling and Preemption

Production deployments need to handle the unexpected. A user might submit a request with `max_tokens=4096` that actually generates 10,000 tokens before hitting a stop sequence. Without preemption, this request would exhaust the KV cache and crash the serving system.

vLLM handles this with **preemption**: when the block table grows too large and free blocks run low, the scheduler can evict the oldest blocks of a request to CPU memory, then swap them back when needed. This is transparent to the application layer—the request continues generating, just with a latency penalty for the swap-in. The scheduler can also preempt entire requests if memory pressure is severe, preserving the ability to resume them later.

For production engineers, the key tuning parameters are:
- `gpu-memory-utilization`: fraction of GPU memory to reserve for the KV cache pool
- `max-num-seqs`: maximum number of concurrent sequences
- `max-num-batched-tokens`: maximum tokens to process in a single scheduler step

Setting these correctly requires profiling your specific workload. A chatbot serving short responses can pack far more sequences than a document-summarization service where each request generates thousands of tokens.

## Production Patterns and Gotchas

### Pattern 1: Prefix Caching for RAG

If your application uses retrieval-augmented generation, you likely prepend a large context block (the retrieved documents) to every request. With PagedAttention, these prefix tokens map to the same physical blocks across requests. vLLM's automatic prefix caching detects when two requests share a common prefix and reuses the cached blocks, eliminating redundant compute for the shared portion. This can cut TTFT (time-to-first-token) by 50% or more for RAG workloads.

### Pattern 2: Batch Size Tuning

Continuous batching doesn't mean "batch everything." Too many sequences in a batch leads to high fragmentation of the compute stream—each sequence may be at a different stage of generation, causing warp divergence. The optimal batch size depends on your model architecture and GPU generation. For A100s with models like LLaMA-2-13B, 32–64 concurrent sequences is typically the sweet spot. Monitor `gpu_utilization` and `kv_cache_usage` metrics to find your ceiling.

### Pattern 3: Handling Variable-Length Outputs

In a continuous batching system, the scheduler must decide when to add new requests. Two common strategies are:
- **Add when capacity allows**: simplest, but can lead to oscillation if the queue is frequently empty.
- **Add on a schedule**: e.g., every 50ms, add up to N new requests regardless of current batch size. This smooths throughput but may add latency to new requests.

Most production deployments use a hybrid: add immediately if there's free capacity, but also enforce a maximum batch size to prevent GPU starvation.

### Gotcha: Block Size Tuning

The default block size of 16 tokens is a good starting point, but if your p99 request length is 180 tokens, you're wasting 4 tokens per block (25% internal fragmentation). If your average request is 500 tokens, a block size of 32 or 64 might be better. Tune this empirically by measuring `block_utilization` across a representative traffic sample.

### Gotcha: Preemption Overhead

Preemption is a safety net, not a performance feature. Swapping blocks to CPU memory introduces latency spikes—sometimes hundreds of milliseconds per swap. If your workload is memory-constrained, consider scaling horizontally (more GPUs) rather than relying on preemption to squeeze out the last bit of utilization. The cost of a single preemption event can exceed the entire generation time of a short request.

## Key Takeaways

- **PagedAttention decouples logical and physical KV cache memory**, eliminating fragmentation and enabling block-level sharing between requests with a common prefix.
- **Continuous batching adds and removes requests at every token step**, keeping the GPU saturated and preventing long-tail sequences from dragging down throughput.
- **Effective throughput gains of 10–24x** are achievable over naive static batching, with the largest wins on variable-length workloads.
- **Prefix caching is automatic**—any two requests that share a token prefix (system prompts, RAG contexts, few-shot examples) will reuse KV cache blocks without explicit configuration.
- **Production tuning requires workload-specific profiling**: block size, max sequences, and GPU memory utilization all interact in non-obvious ways, and the optimal settings for a chatbot differ from those for a batch summarization job.
- **Preemption is a safety mechanism, not a performance optimization**—rely on it sparingly and scale horizontally when memory pressure is chronic.

## Further Reading

- [vLLM: Easy, Fast, and Cheap Large-Language Model Serving with PagedAttention](https://arxiv.org/abs/2306.05669) — The original paper from UC Berkeley SkyLab that introduced both PagedAttention and continuous batching.
- [vLLM Documentation: Continuous Batching](https://docs.vllm.ai/en/latest/serving/continuous_batching.html) — Official guide to configuring and understanding continuous batching in production deployments.
- [PagedAttention GitHub Repository](https://github.com/vllm-project/vllm) — Source code, issue tracker, and community discussions for the vLLM project.
- [Serving LLMs at Scale: Lessons from OpenAI's Infrastructure](https://arxiv.org/abs/2309.06207) — A broader perspective on LLM serving infrastructure, including tensor parallelism and speculative decoding.
- [NVIDIA FasterTransformer: Optimizing LLM Inference](https://github.com/NVIDIA/FasterTransformer) — A comparison point for production-grade LLM serving, useful for understanding the competitive landscape.
- [The KV Cache: What It Is and Why It Matters](https://www.philschmidt.com/blog/kv-cache-explained) — A deep dive into the KV cache itself, including memory math and optimization strategies beyond paging.