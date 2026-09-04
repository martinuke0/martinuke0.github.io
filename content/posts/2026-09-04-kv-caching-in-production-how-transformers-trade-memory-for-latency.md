---
title: "KV Caching in Production: How Transformers Trade Memory for Latency"
date: "2026-09-04T12:38:50.911"
draft: false
tags: ["llm", "transformers", "inference", "kv-cache", "production-engineering"]
description: "How KV caching speeds up LLM inference by reusing past attention state, what it costs in GPU memory, and which optimizations actually ship at scale."
summary: "A practitioner's guide to KV caching: what gets cached, why decode steps are cheap, and how production systems like vLLM and TensorRT-LLM squeeze out more throughput."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-kv-caching-in-production-how-transformers-trade-memory-for-latency.svg"
  alt: "Diagram showing token positions feeding a transformer decoder with KV cache blocks reused across steps."
  caption: ""
  relative: false
---

> **TL;DR** — KV caching stores the Key and Value projections of every previous token so autoregressive decoders don't recompute attention for the entire prompt on every step. It turns inference from O(n²) per token into O(n), but the cache itself grows linearly with sequence length and batch size, often becoming the dominant GPU memory consumer at long context lengths.

## Why Decoding Is Slow Without a Cache

A transformer decoder generates one token at a time. After it picks token *t*, it has to pick *t+1*, and *t+2*, and so on. The naive implementation runs a full forward pass for each new token: recompute attention over the entire prompt plus everything generated so far.

For a 2048-token context, generating the 2048th token naively means doing attention over 2047 previous tokens. Generating the 4096th token means doing attention over 4095. The work per step grows linearly with sequence length, and total work for a full response grows quadratically. That math is brutal at long context: decoding a single 32k-token response this way is roughly 16x slower than decoding a 16k one, even though the prompt only doubled.

KV caching fixes this by remembering the work. The Key and Value tensors for every past token are computed once and stashed. On each subsequent step, the decoder only computes Q, K, V for the new token, then attends against the cached history. Attention becomes O(n) per step instead of O(n²), and total decoding becomes O(n²) overall — the same as a single forward pass.

## What Actually Gets Cached

In a standard multi-head attention block, the input hidden state `X` is projected into three matrices:

```text
Q = X @ W_q      # query
K = X @ W_k      # key
V = X @ W_v      # value
```

Attention scores are `softmax(Q @ Kᵀ / √d) @ V`.

For autoregressive decoding, the `Q` matrix only needs to represent the *new* token at each step. But `K` and `V` for *every* past token are still needed so the new query can attend back. That's the cache: a stack of `K` and `V` tensors, one row per past token per head per layer.

Concretely, the per-token cache footprint for a single layer is:

```text
cache_bytes = 2 (K and V)
              × n_heads
              × head_dim
              × dtype_bytes
              × seq_len
```

For Llama-3-70B with 80 heads, head_dim 128, fp16, that works out to **40,960 bytes (40 KB) per token per layer**, or **~3.3 GB per token across all 80 layers**. That number is the single thing that makes long-context serving hard.

## Memory Is the Real Cost

The cache is not free. It lives in GPU HBM and competes with model weights and activations for the same memory pool. At a high level, per request:

```text
total_memory ≈ model_weights + activations + KV_cache + framework_overhead
```

For a 70B model in fp16, weights are ~140 GB. On an H100 with 80 GB of HBM, you can't even load the model on one card, much less serve requests. Add KV cache and it gets worse. The way production systems work around this is multi-GPU tensor parallelism: sharding weights and the KV cache across 8 cards brings per-card memory back into the 20–30 GB range.

Even with sharding, the cache grows per request. A few rough numbers for an 8B model in fp16, batch size 16, 4k context, 32 layers:

| Component | Approximate size |
|-----------|------------------|
| Model weights | 16 GB |
| KV cache (4k ctx, bs=16) | ~8 GB |
| Activations + overhead | ~2 GB |

The cache is now half the weight footprint. Push context to 32k and the cache becomes the dominant consumer — this is why long-context serving is mostly a memory problem, not a compute problem.

## Architecture: How a Cached Forward Pass Actually Flows

Here's the conceptual data flow for a single decode step inside vLLM-style continuous batching:

```text
┌──────────────┐
│ New token(s) │  ← only the freshly generated token(s)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Q/K/V proj   │  ← computes Q, K, V for the new token
└──────┬───────┘
       │
       ├──────────────► Q_k (just the new row)
       │
       ▼
┌──────────────────────────────┐
│ Append K, V to KV cache block │
└──────┬───────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ FlashAttention over cache    │
│ Q_k @ [cached K]ᵀ  →  scores │
│ scores @ [cached V] →  out   │
└──────┬───────────────────────┘
       │
       ▼
   Output projection → logits → sample next token
```

The cache lives in a paged memory pool, indexed by `(request_id, layer_id, block_id)`. Different requests never see each other's cache entries, and a scheduler can preempt a request by writing its cache blocks to CPU memory and swapping them back in later.

### PagedAttention: The Real Production Breakthrough

The naive way to allocate KV cache is one contiguous tensor per request. That fragments memory immediately. A request with a 4096-token context reserves the full 4096-token slot even if only 200 tokens are decoded. Requests with shorter contexts waste the rest of their allocation.

[PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html) (introduced in vLLM) fixes this by treating cache storage like virtual memory. Each request gets a table of fixed-size blocks (e.g., 16 tokens per block), and a block table maps logical positions to physical blocks in a global pool. The allocator hands out blocks on demand, so memory use tracks actual usage, not reserved capacity.

The result in benchmarks is dramatic: vLLM's paper reports 2–4x throughput improvements over prior serving systems at comparable latency, mostly because wasted KV memory goes from 60–80% down to under 10%.

## Patterns in Production

### Prefix Caching for Repeated Prompts

A lot of traffic is template-shaped: system prompts, RAG context, tool definitions, few-shot examples. The same prefix shows up across thousands of requests. Production servers detect shared prefixes and reuse their KV blocks rather than recomputing.

[SGLang's RadixAttention](https://lmsys.org/blog/2024/01/17/sglang/) implements this with a radix tree over token sequences, allowing prefix sharing across requests and across turns of a multi-turn conversation. Some teams see 5–10x cache hit rates on chat traffic with stable system prompts, which directly translates to lower time-to-first-token.

```python
# Conceptual: prefix matching before forward pass
prefix_hash = hash(token_sequence[:prefix_len])
if cache.has(prefix_hash):
    kv_blocks = cache.get(prefix_hash)   # skip the prefix entirely
    start_position = prefix_len
else:
    kv_blocks = None
    start_position = 0
```

### Multi-Query and Grouped-Query Attention

A standard MHA layer caches `n_heads` Key and Value vectors per token. Multi-Query Attention (MQA) and Grouped-Query Attention (GQA) cut this dramatically by sharing K/V heads across multiple Q heads. Llama-3-8B uses 8 KV heads for 32 query heads, a 4x cache reduction.

This isn't just memory savings — it also means more requests fit on a single GPU, which directly improves throughput. The compute cost is unchanged, but the memory bottleneck relaxes.

### Quantized KV Cache

The KV cache is one of the few tensors where aggressive quantization pays off. INT8 KV cache (as in [the FlexGen paper](https://arxiv.org/abs/2209.12345)) and FP8 KV cache (supported in TensorRT-LLM) halve the cache footprint with minimal quality impact for most workloads. INT4 is more controversial — it works for some models and tanks others.

The trade-off is precision loss accumulating across layers and across sequence length. A position at token 30,000 has had 30,000 quantized writes to its cache. Error compounds.

### Continuous Batching

Old serving loops waited for an entire batch to finish before starting the next one. Continuous batching (pioneered in [Orca](https://www.usenix.org/system/files/osdi22-yu.pdf)) interleaves decode steps across requests: when one request finishes, its slot is immediately filled by a queued request. KV cache allocation has to be dynamic and per-request, which is exactly what PagedAttention enables.

## Failure Modes Worth Knowing

**Cache thrashing under preemption.** If the scheduler preempts a request (because a higher-priority request arrives, or memory is tight), its cache gets evicted. When it resumes, the entire prefix is recomputed. Mitigations include priority-aware scheduling and write-through to host memory.

**Recomputation storms.** A bad change to your prompt template invalidates everyone's prefix cache at once. If 10,000 requests shared a 2000-token system prompt, expect a flash flood of compute as the cache rebuilds. Monitoring prefix-cache hit rate during deploys is worth doing.

**Long-context degradation.** PagedAttention helps with fragmentation, but at 100k+ context lengths the cache itself dominates memory even with GQA. Some teams offload older cache blocks to CPU/NVMe and stream them back during attention — this is "cache offloading," and [Hugging Face's LLM-infinite](https://medium.com/p/7e15a5c43967) is one implementation.

**Fragmentation within a block.** Block size is a tuning knob. Too small (4 tokens) and the block tables bloat. Too big (256 tokens) and small requests waste memory. vLLM defaults to 16, which works for most workloads.

## A Simple Estimate You Can Use

If you're sizing hardware for a serving deployment, here's a back-of-envelope formula:

```text
kv_per_request_gb = 2 × n_layers × n_kv_heads × head_dim × dtype_bytes
                    × seq_len / 1e9

concurrency = (gpu_hbm_gb - weights_gb) / kv_per_request_gb
```

For Llama-3-70B sharded on 8x H100 (80 GB each), with ~18 GB per card for non-weight memory and ~3 KB per token per layer in fp16:
- 8k context → ~200 concurrent requests per replica
- 32k context → ~50 concurrent requests per replica

These numbers are real and they explain why long-context APIs are expensive.

## Key Takeaways

- KV caching is what makes autoregressive decoding tractable: it turns per-step attention from O(n) into O(1) over past tokens, at the cost of storing a per-token, per-layer cache.
- The cache is usually the dominant memory consumer in a serving deployment once context exceeds a few thousand tokens.
- PagedAttention is the breakthrough that made high-throughput serving possible — it eliminates the fragmentation that plagued earlier systems.
- Prefix caching, GQA, and INT8 KV quantization are the three highest-leverage optimizations to ship first.
- The interesting frontier is *where* the cache lives: offloading to CPU/NVMe, sharing across requests via radix trees, and quantization under long contexts.

## Further Reading

- [vLLM: PagedAttention and the end of memory waste](https://blog.vllm.ai/2023/06/20/vllm.html)
- [SGLang: RadixAttention for prefix sharing](https://lmsys.org/blog/2024/01/17/sglang/)
- [Orca: A Distributed Serving System for Transformer-Based Generative Models (OSDI 2022)](https://www.usenix.org/system/files/osdi22-yu.pdf)
- [FlashAttention-2 paper](https://tridao.me/publications/flash2.pdf)
- [FlexGen: High-Throughput Generative Inference of Large Language Models with a Single GPU](https://arxiv.org/abs/2209.12345)
- [TensorRT-LLM documentation: KV cache configuration](https://nvidia.github.io/TensorRT-LLM/performance/performance-tuning-guide/)