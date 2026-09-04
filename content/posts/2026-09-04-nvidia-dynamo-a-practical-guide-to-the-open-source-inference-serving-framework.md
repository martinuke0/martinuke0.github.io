---
title: "NVIDIA Dynamo: A Practical Guide to the Open-Source Inference Serving Framework"
date: "2026-09-04T12:38:10.680"
draft: false
tags: ["nvidia", "dynamo", "llm-inference", "gpu", "kubernetes", "tracing"]
description: "A working engineer's guide to NVIDIA Dynamo — the open-source framework for distributed, low-latency LLM inference serving on GPUs."
summary: "Dynamo disaggregates prefill and decode, distributes KV cache across nodes, and routes traffic intelligently. Here's what it is, how it works, and when to reach for it in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-nvidia-dynamo-a-practical-guide-to-the-open-source-inference-serving-framework.svg"
  alt: "Diagram of a distributed LLM inference cluster with separate prefill and decode workers linked by a KV transfer bus."
  caption: ""
  relative: false
---

> **TL;DR** — NVIDIA Dynamo is an open-source inference serving framework designed for multi-node, multi-GPU LLM deployments. It disaggregates prefill and decode phases, ships KV cache over a high-speed bus, and layers smart scheduling on top — letting you trade latency, throughput, and cost in ways monolithic engines (vLLM, TGI, SGLang) can't easily match.

If you've ever watched a 70B-parameter model grind through a long prompt with a packed KV cache and thought "I bet half my GPUs are idle during prefill and the other half are idle during decode" — Dynamo is, broadly speaking, NVIDIA's answer to that thought. Released at GTC 2025 and now stewarded under the [Dynamo GitHub org](https://github.com/ai-dynamo/dynamo), it pulls apart the two phases of autoregressive inference and treats them as independent scaling problems.

This post walks through what Dynamo actually does, how its architecture differs from a vanilla vLLM deploy, and where it fits (and doesn't fit) in a production stack.

## Why Disaggregate Prefill and Decode?

The cost profile of token generation is famously bimodal. Prefill — the phase that ingests your prompt and populates the KV cache — is compute-bound and parallelizes beautifully across the SMs of a single GPU (and, with tensor parallelism, across multiple GPUs). Decode — the phase that emits one token at a time — is memory-bandwidth-bound, with each new token requiring the entire KV cache to be re-read from HBM.

The standard "monolithic" approach sticks both phases on the same worker. This works, but it forces a tradeoff: if you tune for prefill throughput, decode latency suffers; if you tune for decode, prefill latency spikes. Worse, on long contexts the KV cache can balloon to tens of gigabytes, and prefill traffic from one request can evict or stall decode traffic from another ([vLLM's PagedAttention paper](https://arxiv.org/abs/2309.06180) addresses part of this with paging, but the phase-mixing problem remains).

Dynamo's pitch is straightforward: **separate the workers**. Let a pool of "prefill-only" nodes crunch prompts; let a pool of "decode-only" nodes stream tokens; move the KV cache between them over NVLink or InfiniBand. You can scale the two pools independently and stop paying for one phase's bottlenecks with the other's capacity.

## Core Architecture

Dynamo is best understood as four cooperating subsystems. The terminology is consistent across the [README](https://github.com/ai-dynamo/dynamo) and the [GTC 2025 announcements](https://nvidianews.nvidia.com/news/nvidia-dynamo-ai-dynamo).

### The Engine Adapters

Under the hood, Dynamo doesn't replace your favorite inference engine — it wraps it. As of recent releases, the supported backends include vLLM, TensorRT-LLM, and SGLang, exposed through a common Rust-based engine layer. You write a Python "backend" that translates Dynamo's API into your engine's API, and you can swap engines per deployment without touching the rest of the graph.

This is a quietly important decision: it means Dynamo is a **router and runtime**, not a kernel library. If you have vLLM muscle memory and a custom scheduler, you don't have to throw it out.

### The Smart Router

Sitting in front of the workers is a router — `dynamo-router` — implemented in Rust and designed to be substantially faster than a Python-based dispatcher. The router's job is twofold:

1. **Pick a worker** based on its current load, queue depth, and KV-cache occupancy.
2. **Pick a node** for KV-cache-aware routing when a request's context overlaps significantly with cached prefixes (the classic "system prompt" reuse case).

The router exposes Prometheus metrics and can be fronted by your existing gateway (Envoy, NGINX, or an L7 cloud load balancer).

### The KV Cache Transfer Bus

This is the heart of the system and the part that justifies the name "Dynamo." When a prefill worker finishes, it ships the populated KV cache to a decode worker over a high-bandwidth transport. On a single node, that's NVLink. Across nodes, it's typically InfiniBand or RoCE, with the cache moved via NVIDIA's NIXL (NVIDIA Inference Xfer Library) primitives — the same transport stack used in other GPU-aware data-movement projects.

In practice, this means a single user prompt can land on a cheap node for prefill, then be handed to a decoder node that already has the model's weights warm in HBM. You avoid the prefill-induced decode stall and the decode-induced prefill starvation — at the cost of paying for the transfer, which on NVLink is effectively free and on InfiniBand is in the tens-of-microseconds-per-gigabyte range.

### The Distributed Runtime

The orchestration substrate is built on [Rust's Tokio](https://tokio.rs/) async runtime, with Python bindings via PyO3 so that operators and engine authors can stay in Python. Components communicate via NATS-style message passing, which keeps the system Kubernetes-friendly and lets you scale individual services (router, planner, KV coordinator) independently.

## Patterns in Production

So what does a real Dynamo deployment look like? The reference architecture has a few moving parts, each addressable by a separate Kubernetes pod or VM:

- **Frontend / API server** — OpenAI-compatible HTTP endpoint, typically `dynamo-frontend`.
- **Router** — the `dynamo-router` service.
- **Prefill workers** — GPU pods running vLLM/TRT-LLM/SGLang in prefill-only mode.
- **Decode workers** — GPU pods running the same engine in decode-only mode.
- **KV coordinator** — tracks which decode worker holds which cache blocks.
- **Planner** (optional) — observes telemetry and rebalances workers.

### A Reference Deployment

Here's the shape of a Helm-values-style fragment for a disaggregated deploy on H100s:

```yaml
frontend:
  replicas: 2
  image: nvcr.io/nvidia/dynamo/frontend:latest
  service:
    type: LoadBalancer
    port: 8000

router:
  replicas: 3
  image: nvcr.io/nvidia/dynamo/router:latest
  config:
    kv_aware_routing: true
    max_queue_depth: 32

prefill:
  engine: vllm
  replicas: 4
  gpus: 8
  tensor_parallel: 8
  config:
    max_model_len: 32768
    block_size: 16

decode:
  engine: vllm
  replicas: 8
  gpus: 8
  tensor_parallel: 8
  config:
    max_model_len: 32768
    block_size: 16
```

Note that you can have **more decode replicas than prefill replicas** — exactly the point. Decoding scales with concurrent requests (memory-bandwidth-bound), while prefilling scales with aggregate prompt throughput (compute-bound). Most real workloads want the ratio somewhere between 2:1 and 4:1 in favor of decode.

### Pattern: Prefix Caching at Fleet Scale

A common Dynamo pattern is "prefix caching at fleet scale" — the system prompt for a popular assistant is in the KV cache of *some* node in the cluster, and the router knows which one. When a new request arrives with that prefix, the router can pin the request to a decode worker that already has it warm.

This is more powerful than per-engine prefix caching (which vLLM and TRT-LLM each implement internally) because the cache is **shared across the fleet**, not duplicated per worker. For workloads with one large system prompt and many short conversations, this can drop first-token latency dramatically. NVIDIA has published numbers suggesting order-of-magnitude improvements for prefix-heavy chat workloads; see the [Dynamo technical blog](https://nvidianews.nvidia.com/news/nvidia-dynamo-ai-dynamo) for the slide deck.

## How Dynamo Compares

Dynamo isn't the only framework trying to disaggregate. The space has gotten crowded in 2025–2026. A pragmatic comparison:

- **vLLM** — The 800-pound gorilla. vLLM 0.7+ added experimental prefill/decode disaggregation (the `--disagg-mode` flag and the `kv_connector` plugin system). It works but lives inside the vLLM process model, which makes cross-node transfers more awkward than Dynamo's explicit bus.
- **TensorRT-LLM** — NVIDIA's other inference stack. TensorRT-LLM has disaggregation via its own `disaggregated-server` example, which is closer in spirit to Dynamo but tied to TRT-LLM engines and harder to swap.
- **SGLang** — Has a `DistServe` mode that disaggregates prefill and decode. Lightweight and easy to set up, but less feature-complete on KV-aware routing.
- **Mooncake** (from Moonshot AI) — A more research-flavored disaggregation framework, focused on KV cache offloading to a memory pool rather than per-worker GPUs. Great for very long contexts.

Dynamo's advantage is integration and the NVIDIA-blessed transport stack (NIXL, NCCL under the hood). Its disadvantage is that it's a younger project with less community battle-testing than vLLM.

If you're on a single node with one GPU, none of this matters — just run vLLM. If you're scaling out across a DGX rack or a H100/H200 cluster and latency matters more than simplicity, Dynamo is worth the operational overhead.

## KV Cache Transfer: The Hard Part

Most of Dynamo's complexity hides in the KV transfer. Three failure modes to design for:

1. **Hot-spot decode workers.** If your routing hashes requests to the same decode worker (because they share a prefix), that worker becomes the bottleneck. The router's load-aware logic mitigates this, but you should monitor per-worker QPS in Grafana and alert on imbalance.
2. **Stuck cache blocks.** When a decode worker crashes, the KV coordinator needs to invalidate the blocks it held. This is straightforward but easy to miss; an orphaned block being served from a dead worker is a classic silent-failure mode.
3. **Transfer backpressure.** If the prefill pool produces faster than decode can drain, you need either queueing in the KV bus or backpressure to the frontend. NATS subject queues handle this in the reference deployment, but tuning them is workload-specific.

A useful diagnostic is to instrument the transfer with `nsys` or `ncu` and confirm you're actually saturating NVLink/InfiniBand rather than paying for serialization. The Dynamo team has published sample [nsys recipes](https://github.com/ai-dynamo/dynamo/tree/main/examples) worth cribbing.

## Where Dynamo Doesn't Fit

Not every team should reach for Dynamo. A short list of "don't" cases:

- **Single-node, single-GPU.** You don't have disaggregation pressure. Just run vLLM.
- **Triton inference server workloads for non-LLM models.** Dynamo is purpose-built for autoregressive LLMs.
- **CPU-only inference.** The whole architecture assumes GPU-resident KV cache.
- **Teams without GPU-platform muscle.** Operationally, Dynamo is more complex than a vanilla vLLM pod. If you don't have someone who can debug NCCL hangs, you will have a bad time.

For most teams getting started with LLM serving, the right answer is still "spin up vLLM with a sensible Helm chart and call it a day." Dynamo is what you graduate to when your workloads have outgrown the simple answer.

## Key Takeaways

- **Dynamo disaggregates prefill and decode** across independent worker pools, letting each scale to its own bottleneck.
- **The KV transfer bus** (over NVLink/InfiniBand via NIXL) is the unique piece — it moves populated KV caches between prefill and decode workers in tens of microseconds per gigabyte.
- **KV-aware routing** shares a single prefix's cache across the fleet rather than per-worker, which is a big win for system-prompt-heavy chat workloads.
- **It's a router and runtime, not a kernel library.** Existing engines (vLLM, TRT-LLM, SGLang) plug in as backends, so you don't have to abandon them.
- **Operational complexity is real.** Plan for KV coordinator failures, hot-spot decode workers, and transfer backpressure before you go to production.
- **It complements rather than replaces vLLM.** Single-node vLLM is still the right default; Dynamo is the scaling-out answer.

## Further Reading

- [Dynamo GitHub Repository](https://github.com/ai-dynamo/dynamo)
- [NVIDIA Dynamo Announcement at GTC 2025](https://nvidianews.nvidia.com/news/nvidia-dynamo-ai-dynamo)
- [vLLM PagedAttention Paper](https://arxiv.org/abs/2309.06180)
- [NVIDIA Inference Xfer Library (NIXL)](https://github.com/ai-dynamo/nixl)
- [SGLang DistServe Documentation](https://lmsys.org/blog/2024-12-09-sglang-v0-4/)
- [TensorRT-LLM Disaggregated Serving Example](https://github.com/NVIDIA/TensorRT-LLM/tree/main/examples/disaggregated-serving)