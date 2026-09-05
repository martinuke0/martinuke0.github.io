---
title: "Mooncake: Turning KV Cache into a Distributed LLM Serving Layer"
date: "2026-09-05T18:59:47.184"
draft: false
tags: ["llm-infrastructure", "kv-cache", "distributed-systems", "moonshot-ai", "inference-optimization"]
description: "How Moonshot AI's Mooncake architecture decouples KV cache from GPU memory to slash LLM inference latency and cost."
summary: "Mooncake reframes KV cache as a first-class distributed resource. This post walks through its architecture, the KV store design, and why prefilling and decoding benefit so differently from cache disaggregation."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-mooncake-turning-kv-cache-into-a-distributed-llm-serving-layer.svg"
  alt: "Diagram of disaggregated LLM serving with a shared KV cache pool across prefill and decode nodes."
  caption: ""
  relative: false
---

> **TL;DR** — Mooncake is Moonshot AI's serving stack for Kimi's trillion-token workloads. It treats the KV cache as a distributed, network-attached resource, separating the attention context store from GPU HBM. The result: a 75% reduction in time-to-first-token under bursty load and a multi-x throughput win on long-context traffic compared to tightly-coupled prefill/decode pipelines.

If you have ever watched a 70B-parameter model melt under a thousand-user spike, you already know the bottleneck is not the matrix multiplies. It is the attention state. Every token a model emits requires keeping the key and value tensors of every prior token resident in fast memory, and on modern transformers that state is enormous: tens of megabytes per request, per layer, per head. Naive serving keeps that state in GPU HBM next to the weights, which means context length, batch size, and weight residency are all fighting over the same megabytes.

Mooncake, the architecture Moonshot AI published in 2024 and has since iterated on for the Kimi chat product, takes a different bet. It treats the KV cache as its own distributed object, an attention state store that any GPU in the cluster can attach to and detach from over the network. Prefill happens on nodes optimized for compute. Decode happens on nodes optimized for memory bandwidth. The KV cache lives in between, in a pool of DRAM and SSDs managed by a custom store.

This post walks through the architecture, the reasoning behind the disaggregation, and the production numbers Moonshot reported. The core idea is simple enough that you can sketch it on a whiteboard; the interesting part is what it forces you to reconsider about batching, scheduling, and the meaning of "the same request" inside a serving system.

## Why KV Cache Is the Real Bottleneck

Before looking at Mooncake, it is worth being precise about what the KV cache actually costs. In a transformer with $L$ layers, hidden size $H$, $H/h$ heads, and sequence length $S$, the KV cache for one request occupies $2 \cdot L \cdot S \cdot H \cdot \text{sizeof(dtype)}$ bytes. For a 70B-class model with $L{=}80$, $H{=}12{,}288$, and fp16 weights, that is roughly $0.04 \cdot S$ bytes per token. At 32K context, that is 1.3 GB per request, just for the attention state, on top of the ~140 GB the weights already consume on a pair of H100s.

That arithmetic explains three recurring production pains:

1. **Long context is expensive in a way that is not visible in FLOPs.** A 100K-context request does not demand 10x more compute than a 10K-context request; it demands roughly 10x more attention memory.
2. **Batching is capacity-bound, not compute-bound.** You can easily get to a regime where the GPU is underutilized on matrix multiplies but cannot accept another request because the KV cache is full.
3. **Prefill and decode have opposite memory profiles.** Prefill needs the KV cache briefly and writes linearly with prompt length; decode reads the cache on every step and writes one new row per step, but holds it for the whole conversation.

Serving stacks that pack prefill and decode into the same engine, the default in vLLM, TGI, and TensorRT-LLM until very recently, end up making the worst of both worlds: scheduling has to reserve the maximum possible KV footprint for a request, even though decode-only phases use a sliver of that footprint most of the time.

## The Core Idea: Decouple State from Compute

Mooncake's headline move is to physically separate where attention state lives from where attention compute happens. The architecture has three logical tiers:

- **Prefill nodes**, GPU-rich machines that accept incoming prompts, run the prefill pass, and write the resulting KV cache into the central store. They are optimized for high arithmetic intensity.
- **Decode nodes**, also GPU machines, that pull KV cache segments from the store on a per-request basis, attach them to local GPU memory, run one decode step, write back the new K/V row, and emit the token.
- **KV cache store**, a distributed in-memory store (with SSD tiering for cold requests) that holds attention state keyed by request ID and exposes append-only, range-read, and reclaim semantics.

The store is the new thing. Everything else looks like a normal disaggregated serving topology that NVIDIA's [Dynamo](https://github.com/ai-dynamo/dynamo) and others have explored, but the explicit decision to make KV cache a network object — with its own replication, eviction, and bandwidth guarantees — is what lets Mooncake do tricks like load-balanced prefill across the cluster without copying KV cache through a coordinator, or hand off a request between decode nodes mid-stream when load shifts.

A useful way to think about it: Mooncake is to KV cache what a content-addressable storage layer is to blobs. The store does not care which GPU wrote a particular entry; it cares about idempotency, range reads, and reclaim.

## Inside the Mooncake Store

The store is a custom service, not Redis, not etcd, and not a generic object store. Moonshot's paper describes it as a "hot" tier in DRAM with a "warm" SSD tier underneath, with a slab-allocator-like layout that knows about per-request token locality. Three design choices are worth dwelling on.

### 1. KV cache is segment-addressed, not page-addressed

Requests have natural spatial locality — a decode node wants K/V rows for tokens $t, t{-}1, t{-}2, \dots$ in sequence order on every step. The store exposes the cache as contiguous, growing segments keyed by request ID and layer, and exposes operations like "extend segment by $k$ tokens" and "read tokens $[a, b)$ for layer $L$". That maps well to how attention kernels actually access memory and avoids the per-token RPC overhead that a naïve key-value API would impose.

This is also why context transfer between a prefill node and a decode node can be done as a series of bulk writes rather than a serialized stream of single-token appends. The prefill node computes the entire K/V projection for the prompt, then issues a "write segment of size $S$" call to the store. The decode node, when it picks up the request, issues a "read segment of size $S$" and gets back a contiguous buffer it can DMA into GPU memory.

### 2. Transfers are RDMA-first, TCP-fallback

Inside one rack, the store uses RDMA, typically RoCEv2 on ConnectX-6 or later, to move cache segments between prefill GPU memory and the store pool and between the store pool and decode GPU memory. RDMA is non-negotiable here: a 32K-context, 80-layer KV segment at fp16 is ~63 MB, and you do not want to round-trip that through a kernel TCP stack on the critical path of every handoff. Cross-rack, the store falls back to TCP with compression, accepting the latency hit because cross-rack prefill/decode is already a slow path.

The paper reports RDMA read latencies in the low hundreds of microseconds for typical segment sizes, which is small compared to a single H100 decode step (5–15 ms for a 70B model at reasonable batch sizes). That is the budget that makes disaggregation economically interesting: if every handoff cost 20 ms, you would not disaggregate.

### 3. Eviction is request-aware, not size-aware

Most caches evict on size or recency. The Mooncake store evicts on request liveness. A request that is actively being decoded is pinned; a request whose client disconnected is reclaimable; a request that has not been touched for $N$ minutes and is not in any active decode batch becomes a candidate to be moved to the SSD tier.

This matters because long-context requests can have KV caches that are larger than the entire hot tier. If eviction were LRU, a long-tail request would constantly push hot short-context requests out and tank their hit rates. The liveness-aware policy keeps the working set honest: only requests that are actually generating tokens stay in DRAM.

## The Scheduler: Putting It Together

The disaggregation only pays off if the scheduler can keep both pools busy without thrashing. Mooncake's scheduler is built around three queues:

- **Pending prefill queue.** New requests and "context-extension" requests (continuation tokens appended to an existing conversation). Prefill nodes pull from here.
- **Pending decode queue.** Requests that have a valid KV cache segment in the store and need another decode step. Decode nodes pull from here.
- **Overflow queue.** Requests whose KV cache has been evicted to SSD. A small number of "rehydrate" workers pull from here, reload the cache from SSD to DRAM, and re-inject the request into the decode queue.

What is interesting is that prefill nodes are load-balanced through the store, not through a central metadata service. A prefill node that finishes a job advertises its capacity by issuing a "ready for next prompt of up to $k$ tokens" message; the scheduler matches that against the pending prefill queue. Because the KV cache write happens directly from the prefill node's GPU memory to the store, there is no coordinator in the critical path of cache placement. The coordinator only decides "which prompt goes where", and "where" is just a node ID; the cache arrives in the store through a separate data path.

For decode, the scheduler's hardest problem is cache locality. If request $R$'s KV cache lives on store node $S_1$ and the decode node that picks up $R$ is physically close to $S_1$, you get RDMA bandwidth; if $R$ gets assigned to a decode node across the rack, you get TCP and compression. The scheduler uses a placement hint computed from request ID (consistent hashing against the store's segment placement) so that the same request tends to land on decode nodes near its cache. This is the same trick consistent-hashing caches use to avoid thrashing, applied to a moving target.

## Architecture: A Production Walk-Through

Let us trace one realistic scenario: a user starts a 20K-token conversation with Kimi, sends a 500-token follow-up, and the cluster experiences a 10x traffic spike at the same moment.

1. **Initial 20K prompt arrives.** The scheduler places it on a prefill node with the cheapest expected finish time. The prefill node computes the K/V cache for all 20K tokens and writes the segment to the store via RDMA. The scheduler hands the request off to the decode queue, pinned to decode nodes near the store node holding the segment.
2. **First tokens stream out.** Decode nodes run steps. Each step reads the segment, runs attention, and appends one new row. The append is a small write, well within RDMA bandwidth.
3. **500-token follow-up arrives.** This is the interesting case. It is a context-extension request, not a fresh prefill. The prefill node only needs to compute the K/V cache for the new 500 tokens and append it to the existing segment. Mooncake exposes this as an "extend segment by 500 tokens" operation, and the store guarantees that the original 20K-token segment stays readable throughout.
4. **Traffic spike hits.** New requests flood in. The scheduler starts pulling in additional prefill and decode nodes. Existing long-context requests' KV caches are already in the store, so newly-spun-up decode nodes can pick them up without re-priming. This is the key win: in a tightly-coupled architecture, a new decode worker would either need to copy KV state from another worker (slow) or re-prefill the prompt from scratch (catastrophically expensive). In Mooncake, the state is already in a shared resource.
5. **Spike ends.** Some decode nodes go idle. Their in-flight requests stay in the decode queue and get picked up by other nodes. The KV cache in the store does not move; only the compute moves.

The thing to take away from this trace is that almost every component is decoupled. Prefill and decode share no GPU memory. Decode workers share no GPU memory with each other. The only shared resource is the store, and the store's interface is narrow enough (segments, append, read, reclaim) that it can be implemented in a few thousand lines of C++ and tuned aggressively.

## Patterns in Production

A few patterns have emerged in Mooncake-style deployments that are worth naming explicitly, because they will probably show up in whatever your team's serving stack evolves into over the next year.

**Cache-aware request routing.** Route a request to the decode pool whose nodes have the best network locality to the store node currently holding the request's cache. This sounds obvious; in practice it requires exposing placement hints from the store to the scheduler, which most serving stacks do not do.

**Segmented prefill.** For very long prompts, do not prefill in one shot. Prefill the first $K$ tokens, write to the store, hand off to decode, then come back and continue prefill on the next chunk while the first chunk is already generating. Mooncake reports this technique, sometimes called "chunked prefill" in vLLM-adjacent contexts, lets long-context requests coexist with short ones without one starving the other.

**Idle eviction with sticky rehydrate.** Long-context requests that go idle (the user closed the tab) should not occupy DRAM forever. The liveness-aware eviction moves them to SSD, and a rehydrate worker brings them back when the user returns. The cost is a multi-second warm-up; the benefit is that the hot tier stays usable for active requests.

**RDMA-aware bin-packing.** Pack decode nodes onto the same leaf-spine boundary as the store nodes whose segments they will read. In a real deployment, the network topology matters as much as the GPU count.

## What the Numbers Actually Look Like

Moonshot's paper (["Mooncake: Trading More Storage for Less Computation in KVCache"](https://arxiv.org/abs/2407.00079)) reports several concrete wins over a tightly-coupled baseline:

- Under bursty traffic (10x average load for short periods), time-to-first-token improved by ~75% relative to a baseline where prefill and decode share the same engine. The win comes from being able to spin up decode capacity without re-priming KV state.
- Aggregate throughput at long context (32K+) improved by several times, because prefill and decode no longer contend for the same GPU memory and can be sized independently.
- P99 TTFT stayed under a few hundred milliseconds even at 10x load spikes, where the baseline degraded into multi-second territory.

These numbers are not universal — they assume RDMA networking, Kimi-class traffic mixes, and a store implemented in the way Moonshot describes — but the qualitative shape, "spikes stop hurting as much, long context stops costing as much", has shown up in similar disaggregated designs at other labs.

## Limitations and Open Problems

Mooncake is not a free lunch, and being honest about the costs is what makes the architecture worth taking seriously.

- **RDMA is table stakes.** Without it, the disaggregation tax eats the disaggregation benefit. Cloud GPU providers that do not expose RDMA between GPU instances make this architecture hard to run.
- **The store is a single point of failure for state.** Replication helps, but a distributed store with strong consistency adds latency to writes. Moonshot's design leans on idempotent, append-only writes to keep this tractable.
- **Long-tail contexts are still hard.** A single 1M-token request still needs a 40 GB cache segment. Even with SSD tiering, the bandwidth budget for moving that segment around is not free, and scheduling fairness across one giant request and many small ones is an unsolved research problem.
- **Engine fragmentation.** The serving ecosystem is splitting into "engines that disaggregate" and "engines that don't". Vendors that ship a tightly-coupled engine are now racing to add disaggregation as a bolt-on, and that integration is harder than it looks.

## Key Takeaways

- The KV cache, not the matrix multiplies, is the dominant memory cost in modern LLM serving, and it grows linearly with context length.
- Mooncake's central insight is to treat the KV cache as a distributed, network-attached resource rather than a per-GPU HBM allocation.
- The store exposes segment-level semantics, uses RDMA where it can, and evicts by request liveness rather than by recency.
- Disaggregation decouples prefill capacity, decode capacity, and storage capacity, which makes traffic spikes survivable and long-context traffic affordable.
- The win is largest where RDMA is available and traffic is bursty or long-tailed, which is exactly the regime most consumer chat products live in.

## Further Reading

- [Mooncake: Trading More Storage for Less Computation in KVCache (arXiv)](https://arxiv.org/abs/2407.00079) — the original paper with the architecture details and benchmark numbers.
- [vLLM PagedAttention paper (SOSP 2023)](https://arxiv.org/abs/2309.06180) — the foundation Mooncake builds on; PagedAttention showed that KV cache can be virtualized like memory.
- [NVIDIA Dynamo (GitHub)](https://github.com/ai-dynamo/dynamo) — a parallel disaggregated serving effort from NVIDIA with a similar prefill/decode split.
- [How vLLM handles chunked prefill (docs)](https://docs.vllm.ai/en/latest/serving/chunked_prefill.html) — the closest "out-of-the-box" analogue to Mooncake's segmented prefill pattern.
- [RoCEv2 deployment guide (Mellanox)](https://docs.nvidia.com/networking/display/rdmaawareprogrammingv17) — practical background for the RDMA transport Mooncake depends on.