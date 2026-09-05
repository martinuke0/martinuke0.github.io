---
title: "Distributed Inference: How Modern AI Systems Scale Beyond a Single GPU"
date: "2026-09-05T18:55:02.684"
draft: false
tags: ["distributed-inference", "model-serving", "llmops", "gpu", "production-ai"]
description: "A practical guide to distributed inference covering tensor, pipeline, and expert parallelism with patterns from vLLM, TensorRT-LLM, and production deployments."
summary: "How modern AI serving systems split a single model across many accelerators. Covers tensor, pipeline, and expert parallelism, KV-cache sharding, and production patterns from vLLM, TensorRT-LLM, and DeepSeek."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-distributed-inference-how-modern-ai-systems-scale-beyond-a-single-gpu.svg"
  alt: "Abstract illustration of a neural network split across multiple GPU nodes connected by high-bandwidth links."
  caption: ""
  relative: false
---

> **TL;DR** — Distributed inference splits a single model across multiple accelerators so it fits in memory and runs fast enough for production traffic. The three core strategies are tensor parallelism (split operators across GPUs), pipeline parallelism (split layers across GPUs), and expert parallelism (route tokens to specialized experts). Picking the right mix, and getting the KV cache right, is what separates a toy demo from a serving system that handles real users.

## Why a single GPU isn't enough anymore

In 2019, a 1.5B-parameter BERT model fit comfortably on a single 16 GB GPU. In 2026, the open-weight frontier is 400B+ parameters, and even small production models routinely pass 70B. A single H100 holds 80 GB of VRAM, which is not enough to host a 400B model in FP16, let alone its KV cache, optimizer states, or activation memory at any reasonable batch size.

This is the central problem distributed inference solves: a model too large for one device must be served as if it were a single endpoint, with predictable latency, throughput, and availability. Modern systems like [vLLM](https://blog.vllm.ai/), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM), [SGLang](https://github.com/sgl-project/sglang), and [DeepSeek's open stack](https://github.com/deepseek-ai) all attack the same problem, but they make different trade-offs about where to draw the boundaries between machines.

Three forces push us toward distribution:

1. **Memory capacity.** A 70B FP16 model is ~140 GB; only one or two of those fit on an H100. An 8xH100 node can host it; a 400B model needs roughly four nodes.
2. **Latency.** A single accelerator cannot decode 200 tokens/second for a long context if the forward pass is sequential. Splitting the model across devices lets you parallelize attention and feed-forward work.
3. **Throughput.** Production traffic is bursty. Spreading a model across many devices means more concurrent users can be served before queues back up.

The challenge is that splitting a model is not free. Every cross-device communication step is a synchronization point, and the cost of moving a tensor across an interconnect can dominate the actual compute if you design the topology poorly.

## The three pillars of model parallelism

Distributed inference usually combines three strategies. Each one attacks a different resource bottleneck, and most production systems use at least two of them.

### Tensor parallelism: split the operator

In tensor parallelism (TP), each individual operator — a matrix multiply, an attention head, a layer norm — is partitioned across multiple devices. For a matrix multiply `Y = X @ W`, you split `W` either row-wise or column-wise across the GPUs, each device computes a slice, and an `all-reduce` combines the partial results.

The reference implementation is [Megatron-LM's tensor parallelism](https://github.com/NVIDIA/Megatron-LM), which described a clean scheme for splitting both attention heads and MLP layers such that every GPU only needs an `all-reduce` at the end of each transformer block, not in the middle. This is critical: in-network reductions are fast on NVLink (intra-node) but expensive over slower interconnects like InfiniBand between nodes.

A practical rule: **tensor parallelism belongs inside a node.** With 8x H100s connected by NVLink, the `all-reduce` overhead is a small fraction of each layer's compute. The moment you try TP-16 across two nodes, the inter-node bandwidth (typically 400–800 Gb/s InfiniBand) becomes the bottleneck and your throughput collapses.

TensorRT-LLM and vLLM both default to tensor-parallel degrees that match a single node (TP=2, TP=4, or TP=8 on an 8-GPU box) before stepping up to higher-level strategies.

### Pipeline parallelism: split the layers

In pipeline parallelism (PP), different layers of the model live on different devices. GPU 0 holds layers 0–7, GPU 1 holds layers 8–15, and so on. A batch is sliced into micro-batches; GPU 0 produces activations for micro-batch 1, sends them to GPU 1 while starting micro-batch 2, and so on. This keeps every GPU busy most of the time, with a small bubble at the start and end.

The classic scheme is the [GPipe pipeline](https://arxiv.org/abs/1811.06965); modern variants like [PipeDream](https://arxiv.org/abs/2006.09503) and the interleaved schedules used by DeepSeek-V3's serving stack improve utilization by reordering micro-batches. The DeepSeek inference system, described in their [open-source release notes](https://github.com/deepseek-ai/DeepSeek-V3), uses a heavily interleaved pipeline schedule specifically to hide cross-node latency.

**Pipeline parallelism is what lets you scale across nodes.** Because activations only need to flow forward (and gradients flow backward during training), you can use slower inter-node links without losing as much efficiency as you would with tensor parallelism.

### Expert parallelism: route tokens to specialists

Mixture-of-experts (MoE) models like Mixtral, DeepSeek-V3, and many production routers only activate a subset of parameters per token. Expert parallelism (EP) places each expert on a different device and routes each token only to the GPUs that hold the experts it needs.

The routing is dynamic, which makes this the trickiest of the three. Hot experts can become throughput bottlenecks, and you need a load balancer that reacts to traffic. DeepSeek-V3's auxiliary-loss-free balancing and its dynamic expert parallelism are documented in the [DeepSeek-V3 technical report](https://arxiv.org/abs/2412.19437); this is the kind of system where distributed inference and model architecture co-evolve.

For non-MoE models, EP is not used — the parallel strategies reduce to TP + PP (and sometimes sequence parallelism for the parts of the model that are not attention/MLP).

## Where KV cache lives is half the battle

If you have ever debugged a vLLM deployment, you have seen the familiar `ValueError: No available memory for the block`. That is not the model weights complaining — it is the KV cache.

For autoregressive decoding, every token generates K and V tensors for every layer of the model, and they have to be kept in memory until the sequence finishes. For a 70B model with 32k context and a batch of 32 sequences, the KV cache can easily exceed 40 GB — often larger than the model weights themselves.

In a distributed setup, this cache has to be **sharded across the same devices that hold the layers that read it.** The patterns differ:

- **Tensor-parallel KV sharding.** Heads are already split across GPUs, so each device only holds the K/V for its own heads. No extra communication, but each device's KV memory scales with `(batch × seq × head_dim)` per layer.
- **Pipeline-parallel KV sharding.** Each layer is on exactly one device, so its KV cache is local. No cross-device traffic during decoding, which is excellent for latency.
- **Sequence parallelism.** For long contexts, you can shard the sequence dimension across devices, with each GPU holding a slice of the K/V tensors. Attention then needs an `all-gather` of K/V across the sequence group. [Ring attention](https://arxiv.org/abs/2310.01889) and the sequence-parallel mode in vLLM are examples.

Production serving systems like vLLM use **PagedAttention**, which virtualizes the KV cache the way an OS virtualizes memory. Blocks of KV can be allocated on demand, swapped to host memory when the device is full, and shared across sequences for prefix caching. The original paper, [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180), is the canonical reference.

A non-obvious production gotcha: when you do prefix caching across replicas, you need to broadcast or gossip the cache keys, otherwise you lose cache hits every time the router sends a user to a different replica. Some shops run a dedicated prefix-cache service backed by Redis for this; others accept the miss rate.

## Architecture: what a production distributed inference stack looks like

Most teams do not build distributed inference from scratch; they compose a serving runtime with a frontend and an orchestrator. A typical layout:

- **Frontend / API gateway.** A stateless HTTP server that handles tokenization, streaming, and request routing. [Triton Inference Server](https://github.com/triton-inference-server/server) and vLLM both ship their own; many teams wrap them with [LiteLLM](https://github.com/BerriAI/litellm) or a custom FastAPI layer for auth, rate limits, and prompt logging.
- **Routing layer.** Distributes requests across replica groups. Strategies range from round-robin to prefix-cache-aware routing. A prefix-aware router that keeps the same user pinned to a replica can lift cache hit rates from 30% to 70%.
- **Replica group.** A set of GPUs that together hold one logical copy of the model. Inside the group, the model is sharded using TP + PP + EP. Each replica group is independent, so you can scale by adding groups.
- **Storage.** Model weights live in object storage (S3, GCS) and are streamed to the GPUs on cold start. Some teams use a model registry like [Hugging Face Hub](https://huggingface.co/docs/hub/index) or a private S3-compatible store.
- **Observability.** Per-replica metrics on queue depth, KV cache utilization, time-to-first-token (TTFT), inter-token latency (ITL), and tokens/second/GPU. [Langfuse](https://langfuse.com/) and [OpenLLMetry](https://github.com/traceloop/openllmetry) are common for end-to-end tracing; the serving runtime exposes Prometheus metrics.

A useful mental model: **TP+PP+EP defines a single logical copy of the model.** Everything outside that — replica groups, routing, prefix caching — is horizontal scaling.

## Patterns in production

Across the systems I have seen running at scale, a few patterns repeat.

**Pattern 1: TP-inside-node, PP-across-nodes.** This is the default in vLLM, TensorRT-LLM, and DeepSeek's reference deployment. A node holds 8 GPUs connected by NVLink; you do TP=8 to get the largest possible model on one node, then add PP across nodes if the model still does not fit. Inter-node links carry activations, not raw operator outputs.

**Pattern 2: Speculative decoding across replicas.** The [spec-dec paper](https://arxiv.org/abs/2211.17192) showed that a small "draft" model can propose tokens and a large "target" model can verify them in batches, often yielding 2–3× speedups. In a distributed setup, the draft model can run on a subset of GPUs (or even on CPU) while the target model runs on the rest. Some production systems assign draft and target to different processes in the same node; others split them across nodes.

**Pattern 3: Disaggregated prefill and decode.** Prefill (processing the prompt) is compute-bound; decode (generating tokens one by one) is memory-bound. Running them on the same GPU wastes resources when you mix long prompts with long generations. The [DistServe paper](https://arxiv.org/abs/2401.09670) proposed splitting them; production implementations from Moonshot, Anyscale, and the vLLM project now support "P/D disaggregation," often with prefill on one node and decode on another, connected by a fast link that transfers KV cache.

**Pattern 4: Continuous batching.** Static batching pads a sequence to the longest in the batch, wasting compute on the shorter ones. Continuous batching (pioneered by [Orca](https://www.usenix.org/system/files/osdi22-yu.pdf) and now standard in vLLM) swaps finished sequences out and new ones in every iteration. In a distributed setup, this lets the serving runtime keep utilization high even with bursty traffic.

**Pattern 5: Heterogeneous replica groups.** Not every model needs an 8xH100 box. A small classifier can run on a single L4, a 13B chat model on a single A100, and a 70B model on 4xA100s. A good inference platform exposes these as distinct "endpoints" rather than forcing one topology. [Modal](https://modal.com/), [Replicate](https://replicate.com/), and [Anyscale Endpoints](https://www.anyscale.com/endpoints) all let you pin a model to a specific GPU configuration per deployment.

## Failure modes that bite in production

Distributed inference introduces a category of failures that do not exist on a single GPU. Worth knowing by name:

- **Stragglers.** When one GPU in a TP group is slightly slower than the others (often due to thermal throttling or a noisy neighbor), the whole group waits. NCCL's `NCCL_IB_HCA` and affinity tuning help; some teams disable the slowest device and redistribute the work.
- **Stuck generations.** If one rank hangs during generation, the entire replica hangs. Heartbeats across the TP/PP group are essential — a single stuck CUDA kernel can freeze the endpoint.
- **KV cache pressure.** Long contexts on a small replica group can OOM even though the weights fit. vLLM's `--gpu-memory-utilization` and `--max-model-len` flags exist for exactly this; misuse is the most common cause of crashes on day one.
- **Router-induced tail latency.** A load balancer that hashes by user ID can accidentally concentrate traffic on one replica. Prefix-aware routing helps but is not a substitute for capacity planning.
- **Weight loading on cold start.** Streaming 400B parameters from S3 to 4 nodes takes minutes; user-facing cold starts need pre-warmed pools.

## Observability: what to actually measure

A useful instrumentation baseline:

- **Time to first token (TTFT).** Dominated by prefill, which is compute-bound. Tracks prompt length and replica utilization.
- **Inter-token latency (ITL).** Dominated by decode, KV cache hits, and TP/PP communication.
- **Tokens per second per GPU.** The unit of efficiency. A healthy TP=8 deployment should hold steady at near-peak utilization under load.
- **KV cache hit rate.** Especially for chatbots with long system prompts. A drop is usually a routing change, not a model change.
- **Queue depth and batch size distribution.** A growing queue with shrinking batches means you are under-provisioned; a steady queue with healthy batches means you are fine.

The [vLLM metrics documentation](https://docs.vllm.ai/en/latest/serving/metrics.html) and [Triton's metrics guide](https://github.com/triton-inference-server/server/blob/main/docs/user_guide/metrics.md) are good starting points; both expose Prometheus endpoints that drop into Grafana cleanly.

## A short checklist for getting started

If you are about to ship a distributed inference system for the first time, the order of operations that tends to work:

1. **Pick a serving runtime.** vLLM or TensorRT-LLM for NVIDIA; [llama.cpp](https://github.com/ggerganov/llama.cpp) or [MLX](https://github.com/ml-explore/mlx) for CPU/Apple Silicon. Don't write your own scheduler yet.
2. **Match TP to your node size.** Start with TP=1 (single GPU), then TP=2 or TP=4 if your model does not fit. Only go past TP=8 (across nodes) when you have to.
3. **Add PP before adding more nodes.** If you need a 70B+ model, PP across two nodes is usually more efficient than a wider TP across two nodes.
4. **Enable continuous batching and PagedAttention.** They are defaults in vLLM and TensorRT-LLM; turn them on explicitly in custom stacks.
5. **Wire up prefix caching and cache-aware routing.** The 2–3× cache-hit lift is the cheapest win you will ever get.
6. **Instrument TTFT, ITL, and KV cache hit rate from day one.** You will tune everything else later, but you cannot tune what you cannot see.

The hardest part of distributed inference is not the parallelism math — it is the operational discipline. Once you have the topology right and the observability in place, scaling out is mostly a matter of how many GPUs your platform team can provision.

## Key Takeaways

- **Distributed inference is a memory problem first.** The model and its KV cache have to fit somewhere; splitting is the only way to make them fit on commodity accelerators.
- **Tensor parallelism belongs inside a node, pipeline parallelism across nodes.** Crossing slow interconnects with TP gradients is the most common performance mistake.
- **KV cache is half the memory budget.** PagedAttention, prefix caching, and cache-aware routing are not optional — they are the difference between a demo and a service.
- **Disaggregated prefill/decode and speculative decoding are the two biggest latency wins** for serving LLMs in 2026, and both require a distributed topology to work well.
- **Observability on TTFT, ITL, and KV utilization beats clever topology.** Most production pain comes from not knowing what your replicas are doing.

## Further Reading

- [vLLM documentation: PagedAttention and distributed inference](https://docs.vllm.ai/)
- [NVIDIA TensorRT-LLM repository](https://github.com/NVIDIA/TensorRT-LLM)
- [DeepSeek-V3 technical report](https://arxiv.org/abs/2412.19437)
- [Megatron-LM tensor parallelism paper](https://arxiv.org/abs/1909.08053)
- [GPipe pipeline parallelism paper](https://arxiv.org/abs/1811.06965)
- [The Llama 3 inference paper (Meta)](https://arxiv.org/abs/2407.21783)