---
title: "Serving LLMs in Production: A Practical Guide to Latency, Throughput, and Cost"
date: "2026-09-04T12:42:48.663"
draft: false
tags: ["llm-inference", "production-engineering", "vllm", "quantization", "gpu-optimization"]
description: "Hands-on patterns for serving LLMs in production: batching, quantization, KV cache tuning, and observability without burning your GPU budget."
summary: "A production-focused walkthrough of how to serve large language models efficiently, covering batching strategies, quantization, KV cache management, and the observability you actually need."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-serving-llms-in-production-a-practical-guide-to-latency-throughput-and-cost.svg"
  alt: "Abstract visualization of a GPU pipeline routing inference requests across multiple LLM instances."
  caption: ""
  relative: false
---

> **TL;DR** — Serving LLMs in production is mostly a memory-bandwidth problem, not a compute one. The wins come from continuous batching, KV cache paging, weight quantization, and disciplined observability — not from buying more GPUs.

If you've ever watched a single A100 sit at 40% utilization while requests pile up in a queue, you've already learned the central lesson of LLM inference: GPUs are memory-bandwidth bound, not compute bound. The arithmetic intensity of decoding is tiny — one token per forward pass per request — so the bottleneck is moving weights and KV cache into the tensor cores, not multiplying them. Everything in this post flows from that observation.

This guide walks through the patterns that actually move latency, throughput, and cost in production. It assumes you already know how to call an LLM and want to stop treating inference as a black box.

## Why LLM Serving Is Different

Traditional web serving is a latency story: shrink the critical path, parallelize the I/O, cache aggressively. LLM serving is a *memory locality* story. Two properties dominate everything:

1. **Autoregressive decoding is sequential.** You cannot generate token `t+1` until the model has produced token `t`. Each step is a full forward pass, but the work per step shrinks as the KV cache dominates the arithmetic.
2. **Prefill and decode have opposite shapes.** Prefill (processing the prompt) is compute-bound and parallelizable. Decode (generating tokens one at a time) is memory-bound and serial. A production server has to handle both, and most requests spend far longer in decode than in prefill.

This split is why naive serving stacks — REST servers that handle one request at a time per worker — collapse under load. You are paying for an H100 to stream 80 GB of weights once per token, while the actual matrix multiplies occupy a sliver of the GPU's time.

The dominant production stack today — **vLLM**, **TGI**, **TensorRT-LLM**, **SGLang**, **llama.cpp** for smaller models — all attack this same problem with overlapping techniques. Let's go through them.

## The Four Levers That Actually Matter

There are dozens of knobs you can turn, but in practice four levers explain ~90% of the variance between a hobbyist deployment and a production one.

### 1. Continuous (Iterative) Batching

Classic static batching waits for every request in a batch to finish before starting the next batch. If one request generates 50 tokens and another generates 500, the GPU sits idle for the slow one. Continuous batching — popularized by the [vLLM paper](https://arxiv.org/abs/2309.06180) and now standard in most servers — inserts and removes requests at every decode step.

The result is dramatic. Throughput on shared workloads typically improves 10x–25x over naive static batching because the GPU's memory bandwidth is the real constraint, and continuous batching keeps it fed.

```text
Static batching:        [req1][req1][req1] [req2][req2]  idle    [req3][req3]
Continuous batching:   [r1][r2][r3][r1][r2][r1][r3][r2][r1]...  (mixed every step)
```

vLLM exposes this as the default scheduler; TGI calls it "dynamic batching." If your server doesn't do this, fix it before you tune anything else.

### 2. KV Cache Paging (PagedAttention)

The KV cache for a 70B model at 4K context can easily reach 10+ GB per request. Naive implementations pre-allocate a contiguous block per request, which fragments memory and caps concurrency.

PagedAttention — again from the vLLM team — borrows the virtual-memory idea from operating systems: the cache is stored in fixed-size pages, and a request's pages are mapped through an indirection table. This eliminates fragmentation and enables near-optimal memory utilization.

In practice this means:

- You can serve far more concurrent requests on the same GPU.
- Prefix sharing across requests (e.g., a shared system prompt) becomes essentially free.
- Memory waste drops from 60–80% to single-digit percentages.

### 3. Quantization

Quantization is the highest-leverage cost optimization, because it shrinks the weights *and* the KV cache. The trade-off is quality, and the trade-off has gotten very favorable.

| Format | Bits/weight | Typical quality loss | When to use |
|---|---|---|---|
| FP16/BF16 | 16 | baseline | Default for H100/A100 |
| INT8 (W8A8) | 8 | <1% on most benchmarks | Safe default for cost reduction |
| FP8 (E4M3) | 8 | <1% on H100 native | Best price/quality on Hopper |
| INT4 / AWQ / GPTQ | 4 | 1–3%, recoverable with calibration | When you need maximum tokens/$, or to fit a big model on smaller GPUs |
| INT3 / 2-bit | 2–3 | noticeable, task-dependent | Edge or high-volume evals |

The current sweet spot for production is **FP8 on Hopper** (H100, H200) or **AWQ INT4** when you must squeeze a 70B into a single 24 GB card. [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) and vLLM both ship first-class FP8 and INT4 paths. Note that activation precision (the "A" in W8A8) matters as much as weight precision — naive INT8 quantization that ignores activations is where most of the quality regressions come from.

### 4. Speculative Decoding

Speculative decoding uses a small draft model to propose tokens that a larger target model verifies in a single batched forward pass. Because the verifier can check many tokens at once, the wall-clock per token drops sharply even though the FLOPs go up.

The classic recipe — a 1B draft + a 70B target — routinely delivers 2x–3x decode speedups on chat workloads. vLLM, TGI, and [SGLang](https://github.com/sgl-project/sglang) all support it. The trade-off is doubled VRAM for the draft model and additional prefill latency for the small model, so it's not free — but for chat-heavy traffic it's almost always worth it.

## Architecture: How a Production LLM Stack Looks

Most teams converge on a similar shape once they get past a few thousand QPS or care about tail latency.

```text
                 ┌──────────────────────┐
                 │   API Gateway / LB   │
                 │  (auth, rate limit)  │
                 └──────────┬───────────┘
                            │
              ┌─────────────┴──────────────┐
              │   Routing / Priority Layer │   ← sticky sessions, canary, prefix-aware routing
              └─────────────┬──────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
   ┌─────────┐          ┌─────────┐          ┌─────────┐
   │ Inference│          │ Inference│          │ Inference│
   │  Node 1  │          │  Node 2  │          │  Node 3  │
   │ vLLM/TGI │          │ vLLM/TGI │          │ vLLM/TGI │
   └────┬─────┘          └────┬─────┘          └────┬─────┘
        │                    │                    │
        └────────────────────┴────────────────────┘
                             │
                  ┌──────────┴──────────┐
                  │  Telemetry / Cache  │   ← token-level metrics, Redis/Semantic cache
                  └─────────────────────┘
```

Key choices you'll need to make:

- **Routing**: stateful models require sticky routing by request *or* by prefix. Round-robin will work, but prefix-aware routing (e.g., [llm-d](https://llm-d.ai/), or vendor-specific solutions like Anyscale's router) dramatically improves prefix-cache hit rates for chat workloads with long shared system prompts.
- **Queuing**: every production deployment needs a bounded queue with explicit rejection. Adopting a load-shedding policy (HTTP 429 when the queue is full) is far better than letting p99 latency explode.
- **Autoscaling**: GPU pods autoscale slowly. Plan a warm pool sized to your peak, not your average.
- **Caching**: a semantic or exact-prefix cache in front of the model often eliminates 20–40% of traffic for chat and RAG applications. The cache key must include the full effective prompt — system prompt + tools + retrieved context — to be safe.

A subtle but important architectural point: **separate prefill and decode onto different GPU pools** if you're running at scale. This is the disaggregated serving pattern in [Moonshot's DistServe paper](https://arxiv.org/abs/2401.09670) and shipped by DeepSeek and others. Prefill is compute-heavy and bursty; decode is memory-heavy and steady. Mixing them on the same GPU makes both worse.

## Choosing Hardware

Three numbers determine whether a model will fit and perform on a GPU: **VRAM**, **memory bandwidth**, and **NVLink/fabric bandwidth** for tensor-parallel setups.

| GPU | VRAM | BW (TB/s) | Sweet spot |
|---|---|---|---|
| H100 SXM | 80 GB | 3.35 | 70B FP8, 13B FP16 |
| H200 SXM | 141 GB | 4.8 | 70B FP16, large context |
| B200 | 192 GB | 8.0 | frontier models |
| L40S | 48 GB | 0.86 | 8B–13B INT4/INT8 |
| A10G | 24 GB | 0.6 | 7B INT4, small batch |

The single biggest trap is using a high-FLOP, low-bandwidth card (like an L4) for autoregressive decoding. The L40S is the cheapest card that still feels good for 13B-class models; below that you're firmly in CPU-or-quantization territory. For throughput-bound workloads, total VRAM × bandwidth across the cluster is the right unit of capacity, not FLOPs.

If you're running an NVLink-connected box (DGX H100, HGX H200), tensor parallelism is essentially free; beyond one box, consider **pipeline parallelism** or a serving layer like [llm-d](https://llm-d.ai/) and [NVIDIA Dynamo](https://github.com/ai-dynamo/dynamo) that handle cross-node scheduling.

## Observability: What to Actually Measure

Most teams instrument three metrics and miss the ones that matter. For LLM serving, track:

- **Time to first token (TTFT)** — dominated by prefill; sensitive to prompt length, KV cache pressure, and queue depth.
- **Inter-token latency (ITL)** — the median ms between successive tokens; the real user-perceived speed.
- **Tokens/sec/request** and **tokens/sec/GPU** — request-level throughput vs. cluster-level throughput.
- **KV cache utilization** — fraction of allocated KV blocks in use; if it sits above 90%, you're about to start rejecting requests.
- **Queue depth and prefill queue wait** — leading indicator of saturation.
- **Speculative-acceptance rate** — if you're using speculative decoding, drops below ~50% mean the draft model is hurting more than helping.
- **Prefix-cache hit rate** — directly translates to cost savings.

OpenTelemetry has standardized semantic conventions for generative AI metrics ([gen_ai.server.*](https://opentelemetry.io/docs/specs/semconv/gen-ai/)), and vLLM, TGI, and Triton all export Prometheus endpoints that align. Wire these into Grafana before you ship; everything else is debugging in the dark.

A practical pattern: emit a **trace span per request** that includes the prompt token count, output token count, TTFT, ITL, and finish reason. Aggregate these into per-tenant dashboards. When a customer complains about latency, you'll have the data to say whether it's the model, their prompts, or your infrastructure.

## Common Production Failure Modes

After watching a few deployments go live, the same handful of issues show up repeatedly.

### OOM under bursty traffic
KV cache is allocated per request. A burst of long-context requests can blow past memory headroom. Mitigations: cap `max_model_len` and `max_num_seqs`, enable prefix caching, and **always** leave 10–15% VRAM free.

### Tail latency from long generations
A single user asking for 4,000 tokens will hold a KV slot for the entire decode. Add an output token budget — both at the API layer and enforced server-side — and return a continuation token if you must support long outputs.

### P99 collapse from prefill queueing
Long prompts starve decode slots. Set a `max_num_prefill_seqs` so prefills can't monopolize a batch, or adopt disaggregated serving.

### Quantization regressions on edge cases
INT4 can drift on reasoning, math, or non-English tasks. Run a regression suite before flipping quantization in prod, and keep the FP16 path available for high-value traffic.

### Cost surprises from speculative decoding
If acceptance rates drop, you've added FLOPs without latency gains. Monitor and disable per-route if the draft model isn't helping.

### Prefix-cache poisoning
If you cache by exact prompt hash and a downstream retriever injects untrusted content, a cache hit can serve a manipulated payload. Treat cache hits with the same input-validation rigor as misses.

## Key Takeaways

- LLM serving is a **memory-bandwidth** problem, not a compute problem. Optimize accordingly.
- **Continuous batching** and **PagedAttention** are non-negotiable; if your stack doesn't have them, switch stacks.
- **Quantization** (FP8 on Hopper, AWQ INT4 elsewhere) is the single highest-leverage cost optimization.
- **Speculative decoding** gives 2x–3x decode speedups for chat; measure acceptance rates and disable when it stops paying off.
- Production architecture needs **prefix-aware routing**, **bounded queues**, **separated prefill/decode**, and **real observability** — not just a load balancer pointing at a vLLM pod.
- Track **TTFT, ITL, KV utilization, and prefix-cache hit rate** in addition to throughput.
- The right hardware question is *bandwidth × VRAM*, not FLOPS.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)
- [TensorRT-LLM: A Highly Optimized LLM Serving Stack from NVIDIA](https://github.com/NVIDIA/TensorRT-LLM)
- [How continuous batching enables 23x throughput in LLM inference](https://www.anyscale.com/blog/continuous-batching-llm-inference)
- [Disaggregated Serving: Prefill and Decode on Separate GPUs (DistServe)](https://arxiv.org/abs/2401.09670)
- [Speculative decoding paper (Leviathan et al., 2023)](https://arxiv.org/abs/2211.17192)
- [OpenTelemetry Semantic Conventions for Generative AI](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [SGLang: Efficient Execution of Structured Language Model Programs](https://github.com/sgl-project/sglang)