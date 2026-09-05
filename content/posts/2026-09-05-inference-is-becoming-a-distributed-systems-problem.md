---
title: "Inference Is Becoming a Distributed-Systems Problem"
date: "2026-09-05T18:49:46.977"
draft: false
tags: ["distributed-systems", "inference", "llm-infrastructure", "model-serving", "kubernetes"]
description: "As LLMs grow past single-GPU memory, inference turns into a distributed-systems problem: sharding, scheduling, KV-cache coherence, and tail-latency SLOs."
summary: "Once a model fits on one accelerator, inference is mostly GEMMs and kv cache lookups. Once it doesn't, you inherit every problem distributed systems has spent thirty years failing to solve."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-inference-is-becoming-a-distributed-systems-problem.svg"
  alt: "Abstract visualization of model layers sharded across multiple GPU nodes connected by high-bandwidth fabric."
  caption: ""
  relative: false
---

> **TL;DR** — Modern LLM inference is no longer a single-device compute problem; it is a distributed-systems problem with sharded weights, replicated KV caches, prefix sharing across requests, and millisecond-scale scheduling decisions. Engineers who treat it like a Python script hitting `model.generate()` will lose to teams who treat it like a microservice fleet.

## The Quiet Shift Underneath the Hype

Five years ago, "running inference" meant loading a checkpoint into VRAM on one box and calling it a day. A 1.5B parameter model was a 3 GB blob, comfortably resident on a single consumer GPU. A 7B model took ~14 GB, a stretch but still tractable. Latency came down to how fast your GPU could stream tokens through a transformer.

That world is gone.

Today's frontier models — Llama 4, Claude 4, Gemini 2.5, Qwen3 — span hundreds of billions of parameters. Even with aggressive quantization, a 70B-parameter model at INT4 still weighs ~35 GB, which does not fit on a single H100's 80 GB of HBM. A 400B-class model needs four to eight accelerators just for the weights, before you allocate anything for the KV cache, activations, or CUDA workspaces. And the KV cache alone can dwarf the weights at long context: a 400B model serving 200 concurrent requests at 32k tokens consumes more cache memory than the parameters themselves.

So inference stops being a numerical kernel problem and becomes a distributed-systems problem. The same problems we thought we escaped — partitioning, replication, coherence, scheduling, fault tolerance — are back, wearing new clothes.

## What "Distributed Inference" Actually Means

When people say "distributed inference," they collapse three distinct architectures into one phrase. Conflating them is the single biggest source of production bugs I see.

**Tensor parallelism (intra-layer sharding):** The matrices of a single transformer layer are split across N accelerators, typically 2, 4, or 8 devices connected by NVLink or NVSwitch. Each device computes a slice of the output, and they synchronize at the end of every layer via all-reduce. This is what the original Megatron-LM paper introduced, and it is what frameworks like [vLLM's tensor-parallel backend](https://docs.vllm.ai) and [NVIDIA's TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) implement under the hood.

**Pipeline parallelism (inter-layer sharding):** Different transformer layers live on different devices. Request tokens flow through them in assembly-line fashion. Pipeline parallelism has lower interconnect bandwidth requirements than tensor parallelism but introduces bubble overhead and complicates batching because adjacent stages must coordinate.

**Expert parallelism (MoE routing):** In a mixture-of-experts model like Mixtral or Llama 4, only a fraction of the experts are activated per token. Each expert lives on a subset of devices, and tokens are routed across the fleet via all-to-all communication. This is the architecture that makes "trillion-parameter" models cheap enough to serve at all.

In production you usually run all three stacked. A single inference server might be tensor-parallel across 8 GPUs inside one node, pipeline-parallel across 4 nodes, and expert-parallel across an MoE shard dimension on top of that. The control plane has to keep it all straight, and the failure modes multiply.

## The KV Cache Is the New Database

If you only internalize one thing from this post, make it this: **the KV cache is the dominant memory consumer in long-context serving, and it has to be managed like a distributed cache.**

For every request, the model stores past key and value tensors for each layer and each token it has seen. For a 70B model with 80 layers, 128 KV heads, and head dimension 128, serving a single 32k-token request consumes roughly:

`80 × 128 × 128 × 32000 × 2 bytes (fp16) ≈ 8.4 GB`

Multiply by 200 concurrent requests and you need ~1.7 TB of cache. That is an order of magnitude more than the weights themselves. vLLM popularized PagedAttention — a virtual-memory-style approach that eliminates fragmentation by treating the KV cache as fixed-size pages rather than contiguous allocations. The paper is worth re-reading every year: [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180).

But paging alone is not enough at fleet scale. You also need:

- **Prefix sharing across requests.** If 200 users all hit the same chatbot with the same 8k-token system prompt, you should store that KV cache once and reference it many times. This is what SGLang's [RadixAttention](https://lmsys.org/blog/2024/01/sglang-inference-engine) and the [Prompt Cache](https://docs.litellm.ai) pattern in production gateways both implement.
- **Cross-instance cache reuse.** In a horizontally scaled cluster, two replicas shouldn't each recompute the same prefix from scratch. Some teams ship the cache to Redis with a hash of the token sequence as the key; others use a dedicated cache tier with RDMA.
- **Eviction under pressure.** When you exceed KV cache capacity, you have to drop something. The naive policy is "oldest request loses," but that punishes long-context users. Prefix-cached blocks should be the last to evict.

Treat the KV cache as the database, treat your HBM as the working set, treat the network as the cold storage. The same trade-offs apply.

## Scheduling Has Become a Hard Real-Time Problem

Pre-LLM serving, request scheduling was a solved problem: round-robin, least-connections, weighted fair queuing. Tokens-per-second fairness? Nobody had heard of it. P99 latency was bounded by network round-trips, not by 200 ms of GPU compute.

LLM serving breaks every assumption those schedulers were built on. A request's runtime depends on its output length, which is not known until the model finishes generating. A 50-token completion and a 2,000-token completion are not comparable units of work. This is why naïve schedulers produce p99 latencies that are 5–10× the median — the long-tailed requests monopolize the batch.

The two scheduling ideas that actually work in production:

**Continuous batching (iteration-level scheduling).** Instead of waiting for the longest request in a batch to finish before starting new ones, the scheduler admits new requests at every decoding step. vLLM, TGI, and TensorRT-LLM all implement variants of this. The original paper is [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/system/files/osdi22-yu.pdf) from OSDI 2022.

**Two-level scheduling with prefill-decode disaggregation.** Prefill (the prompt-computation phase) is compute-bound and parallelism-friendly; decode (the per-token generation phase) is memory-bandwidth-bound and latency-sensitive. Running them on the same GPU forces a compromise. The fix is to run prefill on a "compute" pool and decode on a "memory" pool, with KV cache transfer over the interconnect. [DistServe](https://arxiv.org/abs/2401.09670) and the production architecture described in [Moonshot's Kimi inference paper](https://arxiv.org/abs/2404.06642) both formalize this.

If you skip this, you will watch your p99 latency oscillate wildly under load and have no good way to explain it to your SRE team.

## Patterns in Production

Here are three architectures that actually ship today, drawn from public talks and papers. None of them are theoretical.

**Anthropic-style multi-region fallback with prefix sharing.** Inference traffic is routed through a global gateway that hashes the system prompt and routes to the closest replica that already has that prefix cached in HBM. Cold-prefix requests get a small latency penalty as the cache warms; warm-prefix requests hit single-digit-millisecond p50. The cache invalidation problem (when a model version rolls out) is solved by versioning the prefix hash with the model checkpoint ID.

**Meta's "tensor parallel at 8, pipeline parallel at 32" pattern.** For Llama 4-class serving, Meta's published stack uses 8-way tensor parallelism inside a node (NVLink-connected) and pipeline parallelism across nodes over RoCE/InfiniBand. The trick is that pipeline parallelism requires careful micro-batching to avoid bubbles — typically 4 to 8 micro-batches per pipeline stage.

**MoE inference with expert offloading.** For very large MoE models, hot experts live in HBM but cold experts sit in CPU RAM or even NVMe. When a request routes to a cold expert, you pay a millisecond-scale miss penalty. Production systems like DeepSeek-V3's reported architecture use a small predictor to keep the most likely experts warm. See [DeepSeek-V3 Technical Report](https://arxiv.org/abs/2412.19437).

```python
# Pseudocode for a continuous-batching scheduler
def schedule_step(running_requests, waiting_requests):
    # 1. Continue all decode-phase requests in their slots
    slots = []
    for req in running_requests:
        if req.has_tokens_left():
            slots.append(req)
        else:
            req.complete()

    # 2. Admit new requests into free slots
    free_slots = MAX_BATCH_SIZE - len(slots)
    for req in waiting_requests[:free_slots]:
        slots.append(req.admit())

    # 3. Run a single forward pass on the packed batch
    outputs = model.forward(pack(slots))
    distribute_outputs(outputs, slots)
```

## Failure Modes You Will Hit

Once you have multiple accelerators, multiple nodes, and a network between them, you inherit every distributed-systems failure mode. Here is the shortlist of incidents I have personally debugged or seen postmortems for.

- **Silent weight corruption from NaN propagation in all-reduce.** One device produces NaNs, the all-reduce happily broadcasts them, and every replica silently serves garbage. Fix: checksum the all-reduce output and trip a circuit breaker.
- **KV cache desync after a partial prefill failure.** Node 2 of a 4-node pipeline succeeds, nodes 3 and 4 fail. You retry the request, but the KV cache on node 2 is stale. Fix: epoch-stamp KV cache blocks and discard on retry.
- **Scheduler-induced thundering herd.** Your eviction policy drops 5,000 requests at once when you hit memory pressure. They all retry simultaneously and immediately re-overload the cluster. Fix: jitter the retry, and shed load at the gateway with token-bucket admission control rather than at the model server.
- **Long-tail latency from speculative decoding mis-speculation.** Draft tokens get rejected, the verify pass takes longer than a normal decode step, and your p99 balloons. Fix: cap the speculation horizon dynamically based on observed acceptance rate.

The fix for almost every one of these is the same fix that fixed distributed systems thirty years ago: observability. Per-request traces that span the gateway, scheduler, all-reduce collectives, and KV cache tier. If you cannot reconstruct a single request's journey from ingress to egress, you cannot debug production inference.

## The Tooling Stack Has Consolidated

You no longer need to roll your own. The infrastructure layer has stabilized around a small number of components:

- **Model servers:** vLLM, TensorRT-LLM, SGLang, HuggingFace TGI. Pick based on your hardware and quantization story.
- **Orchestration:** Kubernetes with custom resource definitions for accelerators (the [GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html) and its ilk), or purpose-built systems like [Modal](https://modal.com) and [Anyscale](https://www.anyscale.com) that hide the Kubernetes complexity.
- **Network fabric:** RoCE v2 over 200/400 GbE, or InfiniBand HDR/NDR for the latency-sensitive collectives. The NVLink domain stays inside the node.
- **Observability:** Distributed tracing across the inference path, plus per-iteration metrics — token throughput, KV cache utilization, speculation acceptance rate.
- **Gateway:** A token-aware load balancer that understands prefix hashing and routes to warm replicas. [LiteLLM](https://github.com/BerriAI/litellm) and the open-source [llm-gateway](https://github.com/Portkey-AI/gateway) projects are reasonable starting points.

The orchestration layer is where the most work remains. Kubernetes was designed for stateless web services; inference pods are anything but stateless. Their state is hundreds of gigabytes of KV cache that you would very much like to keep warm across pod restarts.

## Key Takeaways

- Inference is now a distributed-systems problem because the model, its KV cache, and its compute requirements no longer fit on a single device.
- Tensor, pipeline, and expert parallelism solve different bottlenecks and are usually stacked in production.
- The KV cache is the dominant memory consumer in long-context serving and should be engineered like a distributed cache, with prefix sharing, versioning, and eviction policies.
- Scheduling is now a hard real-time problem requiring continuous batching and prefill/decode disaggregation; naïve round-robin will destroy your p99 latency.
- Treat weight all-reduces, KV cache transfers, and speculative decoding as distributed-systems primitives with their own failure modes; invest in observability accordingly.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)
- [Orca: A Distributed Serving System for Transformer-Based Generative Models (OSDI 2022)](https://www.usenix.org/system/files/osdi22-yu.pdf)
- [SGLang: Efficient Execution of Structured Language Model Programs](https://lmsys.org/blog/2024/01/sglang-inference-engine)
- [DistServe: Disaggregating Prefill and Decoding for Good Throughput-Latency Trade-off](https://arxiv.org/abs/2401.09670)
- [DeepSeek-V3 Technical Report](https://arxiv.org/abs/2412.19437)
- [NVIDIA TensorRT-LLM Documentation](https://github.com/NVIDIA/TensorRT-LLM)
- [GPU Operator for Kubernetes](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)