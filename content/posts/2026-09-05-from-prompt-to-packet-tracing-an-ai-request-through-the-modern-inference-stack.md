---
title: "From Prompt to Packet: Tracing an AI Request Through the Modern Inference Stack"
date: "2026-09-05T18:47:54.176"
draft: false
tags: ["ai-infrastructure", "kubernetes", "gpu", "networking", "observability", "finops"]
description: "A full-stack trace of an AI agent request across the gateway, inference layer, GPU scheduler, and networking plane — with observability and FinOps hooks."
summary: "We follow a single agent request from the user prompt down through the AI gateway, inference server, GPU/Kubernetes scheduler, and east-west networking — then turn around and look at how observability, security, and FinOps wrap around the whole thing."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-from-prompt-to-packet-tracing-an-ai-request-through-the-modern-inference-stack.svg"
  alt: "Layered diagram of an AI inference request flowing from a user app through gateway, inference, GPU, and network layers."
  caption: ""
  relative: false
---

> **TL;DR** — A production AI request crosses at least nine distinct layers — app, agent runtime, gateway, inference server, GPU scheduler, container orchestrator, fabric, observability, and FinOps — and each one is a place where latency, cost, or security can leak. Tracing the path end to end is the only way to debug tail latency, right-size capacity, and defend against the new attack surface that agents open up.

## Why "the model" isn't the bottleneck anymore

Five years ago, the hard part of shipping an AI feature was getting the model to do the thing. Today, the hard part is everything around the model. A typical agent request on a modern stack will touch:

1. The application frontend (often a chat UI or an API consumer).
2. An agent runtime that plans tool calls, retrieves context, and loops.
3. An AI gateway that handles auth, rate limits, prompt templating, and routing.
4. An inference server (vLLM, TGI, TensorRT-LLM, Triton) running on a GPU.
5. A Kubernetes scheduler + GPU operator (Karpenter, NVIDIA device plugin, time-slicing).
6. The data center fabric (RDMA, RoCE, NCCL collectives, east-west traffic).
7. An observability plane (OpenTelemetry, DCGM, eBPF).
8. A security layer (prompt firewalls, egress controls, secrets, mTLS).
9. A FinOps loop (token accounting, GPU utilization, chargeback).

Each of those layers has its own failure modes, its own dashboards, and its own on-call pager. If you treat "the LLM" as a black box you call over HTTP, you will be blindsided by at least four of them.

Let's follow a single request from the moment a user hits Enter to the moment the tokens stream back.

## The application and agent layer

The request usually starts in something boring — a React app, a Slack bot, or a backend service calling a typed SDK. What changed in 2024–2026 is that the SDK is no longer a thin wrapper around `/v1/chat/completions`. It's an **agent runtime**.

The runtime does three things that matter for the rest of the stack:

- **Plans a trajectory.** Given a user goal, it picks tools (search, SQL, code execution, calendar API) and assembles a multi-step plan. Frameworks like [LangGraph](https://langchain-ai.github.io/langgraph/), the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/), and [CrewAI](https://docs.crewai.com/) all expose this loop explicitly.
- **Manages context.** It stuffs tool results, retrieved documents, and prior messages into a growing prompt window. This is where your token bill explodes if you're not careful.
- **Streams back to the user.** Server-sent events, websockets, or gRPC streams — the wire format here determines what your gateway can actually see.

A single "user message" can fan out into **dozens** of LLM calls plus hundreds of retrieval calls. From the perspective of everything downstream, this looks like a thundering herd, not a single request. That changes how you size everything below.

## The AI gateway

Before any of those sub-requests hit a GPU, they hit a gateway. This is one of the more important architectural patterns to land in the last two years — and one of the more underappreciated.

A purpose-built AI gateway (Kong's [AI Gateway plugin](https://docs.konghq.com/hub/kong-inc/ai-proxy/), [Portkey](https://portkey.ai/docs), [LiteLLM](https://docs.litellm.ai/docs/simple_proxy), [Envoy AI Gateway](https://aigateway.envoyproxy.io/), or [Cloudflare AI Gateway](https://developers.cloudflare.com/ai-gateway/)) sits between your agents and your model providers — and increasingly, your self-hosted models too. It does:

- **Authentication and tenant isolation.** OAuth, API keys, per-team rate limits, and PII tagging before anything leaves the perimeter.
- **Prompt templating and caching.** Centralized system prompts, semantic cache lookups (often backed by Redis or a vector DB), and response caching by prefix.
- **Routing and failover.** Route "easy" traffic to a small local model, "hard" traffic to a frontier model in another region, fall back automatically when a provider has an incident.
- **Token and cost metering.** Every request gets tagged with model, prompt tokens, completion tokens, cached tokens, and dollar cost. This is the seed data for everything in FinOps later.
- **Safety.** Prompt-injection detection, jailbreak heuristics, output filtering, and redaction. The OWASP-published [LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) is the working threat model here.

The gateway is also where you set the **SLO** for the whole system. p99 latency to the gateway is what your users actually feel, and it's the only thing that gives you a stable target when the underlying inference layer is being noisy-neighbor'd by other tenants.

## The inference server

Past the gateway, traffic lands on an inference server. This is the piece that actually runs the model on a GPU. The dominant open-source options in 2026 are:

- **[vLLM](https://docs.vllm.ai/)** — PagedAttention, continuous batching, the de facto default for dense and MoE transformer serving.
- **[TGI](https://huggingface.co/docs/text-generation-inference)** (Text Generation Inference) — Hugging Face's serving stack, solid for HuggingFace-hosted models.
- **[TensorRT-LLM](https://nvidia.github.io/TensorRT-LLM/)** — NVIDIA's optimized engine, best raw perf but more build complexity.
- **[Triton Inference Server](https://github.com/triton-inference-server/server)** — NVIDIA's framework-agnostic server, strong for multi-model ensembles and custom backends.
- **[SGLang](https://github.com/sgl-project/sglang)** — RadixAttention, structured generation, fast for agent workloads with heavy prompt reuse.

What they all have in common is that they're **stateful, long-lived, GPU-pinned** processes. You can't horizontally autoscale them like a web service — you can only scale the *number of replicas*, each of which holds a whole model in VRAM. This is the single biggest source of capacity pain in the stack.

Two metrics matter here more than anything else:

- **Time to first token (TTFT).** How long until the user sees the first character. Driven by prompt processing (prefill) and KV-cache warmup.
- **Inter-token latency (ITL).** How long between subsequent tokens. Driven by decode throughput, which is bounded by memory bandwidth on the GPU.

A 70B model in INT4 on an H100 sits at roughly 80–150 tok/s/req depending on batch size. Bump the batch and ITL rises. This is the fundamental throughput/latency tradeoff you tune on this layer.

## GPU scheduling and Kubernetes

Underneath the inference server is Kubernetes — and under Kubernetes, the GPU.

The job of the GPU layer is deceptively hard: you need to place multi-GPU workloads on nodes that have *the right shape* of GPUs connected with *the right topology*, hold them there for the lifetime of a model load (which can be 30+ seconds for a large model), and not let one tenant's idle VRAM starve another's queue.

Three components do most of the work:

- **[NVIDIA Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)** (or the newer [DRA driver](https://kubernetes.io/docs/concepts/scheduling-eviction/dynamic-resource-allocation/)) — advertises GPUs to the kubelet as a schedulable resource (`nvidia.com/gpu: 8`). Time-slicing and MIG partitioning are configured here.
- **[Karpenter](https://karpenter.sh/)** — node autoscaler that provisions GPU instances just-in-time. Critical for spot-priced H100s and for draining bad nodes fast.
- **[Kueue](https://kueue.sigs.k8s.io/)** or **[Volcano](https://volcano.sh/)** — batch/job schedulers that understand gang scheduling. A 70B model that needs 8 GPUs must land on 8 GPUs that talk to each other across NVLink, not across PCIe.

The failure modes are very specific to AI workloads:

- **Preemption storms.** A spot node disappears mid-request; all in-flight generations fail. You need graceful draining plus retry at the agent layer.
- **Fragmentation.** Eight H100s scattered across nodes can't serve a 70B model. Topology-aware scheduling is non-optional.
- **Cold starts.** Loading a 70B checkpoint from object storage takes 30–90 seconds. Either you pay that on every scale-up, or you build a model cache (local NVMe, or [CoreWeave's Fluid](https://github.com/coreweave/fluid)-style tiering).

## The networking layer

Once your pods have GPUs, the GPUs have to talk. LLM inference is one of the most network-hungry workloads in production computing, and almost nobody talks about it.

Three distinct traffic patterns show up:

1. **North-south: client → inference.** Standard HTTP/gRPC, often over a service mesh. Fine.
2. **East-west: tensor parallel.** When a single model spans multiple GPUs, every forward pass ships activations across **NVLink** intra-node (good) or **InfiniBand/RoCE** inter-node (painful). NCCL collectives here can consume 200–400 Gbps per node pair.
3. **East-west: prefill/decode disaggregation.** A newer pattern where prefill runs on one pool of GPUs and decode on another, with KV-cache state shipped between them. This is what [Mooncake](https://github.com/kvcache-ai/Mooncake) and the [distServe](https://github.com/LINs-lab/distserve) paper popularized.

The data center fabric is now the bottleneck for multi-node inference. Two consequences:

- **Topology-aware scheduling matters at the network layer too.** If your scheduler places prefill on node A and decode on node B without checking that they share a leaf-spine rail, you get a 30% throughput cliff. [Rail-optimized](https://www.nvidia.com/en-us/networking/) designs (where each "rail" is a single-spine switch) are the common fix.
- **RoCE vs. InfiniBand matters.** RoCE is cheaper and runs on Ethernet; InfiniBand is faster but lock-in. NCCL will auto-tune either, but the lossless-PFC configuration on your Ethernet switches will eat a week of your life the first time you set it up. The [NVIDIA networking docs](https://docs.nvidia.com/networking/) are the canonical reference.

## Observability: the layer that glues it together

You can't fix what you can't see, and AI workloads have a *lot* to see. The observability stack has to cover all of the above, plus a few things unique to inference.

The three pillars, applied to inference:

- **Metrics.** GPU utilization, SM occupancy, KV-cache hit rate, queue depth, TTFT, ITL, tokens/second/dollar. [NVIDIA DCGM](https://github.com/NVIDIA/dcgm) exports the GPU-side ones; the inference server exports the model-side ones. Stitch them together in Prometheus or [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/).
- **Logs.** Prompt + completion logs are gold for debugging, but they're also a **liability** if they leak PII. Pipe them through a redaction layer before they hit your log store.
- **Traces.** This is where OpenTelemetry shines. Propagate a trace context from the agent runtime, through the gateway, into the inference server's span attributes, and you can finally see "this user request took 14 seconds and 11 of them were KV-cache misses." The [OpenInference](https://github.com/Arize-OpenInference/open-inference) semantic conventions are the de facto standard for LLM spans.

A few patterns specifically worth implementing:

- **Per-tenant dashboards.** Aggregate TTFT/ITL by team, by prompt template, by model version. Cost spikes usually show up here before they show up in the bill.
- **Continuous evaluations.** Sample 1% of completions, run an LLM-as-judge or a regression test, and alert when quality drifts. Inference without eval is just a faster way to serve worse answers.
- **SLO-based alerting.** Alert on TTFT p99 *per tenant*, not on cluster-wide GPU utilization. The latter is meaningless when one team is starving another.

## Security: the new attack surface

Agents introduce an attack surface that traditional appsec doesn't have a vocabulary for. The biggest categories:

- **Prompt injection.** Adversarial content in retrieved documents or tool outputs hijacks the model. Mitigations: structured tool I/O, dual-LLM patterns (see the [CaMeL paper](https://arxiv.org/abs/2503.x)), output schema validation, and the [OWASP LLM Top 10](https://owasp.org/www-project-top-10-for-large-language-model-applications/) as a baseline.
- **Egress exfiltration.** An agent with a "fetch URL" tool can be tricked into POSTing your data to an attacker. Lock down egress to an allowlist at the gateway or service mesh.
- **Secrets in prompts.** Users paste API keys into chat boxes. Your gateway needs a redaction pass, and your inference logs need to be excluded from anything user-facing.
- **Supply chain on the model.** You're pulling weights from HuggingFace. Pin a hash, scan with [ModelScan](https://github.com/protectai/modelscan), and treat model files like container images — verify signatures.
- **mTLS and tenant isolation.** Multi-tenant GPU clusters need network policies and (ideally) per-tenant network namespaces. A noisy neighbor that can read your KV-cache traffic is a real risk on shared InfiniBand fabrics.

The gateway is your chokepoint for most of this. If your security controls aren't sitting at the gateway, they're not really controls — they're suggestions.

## FinOps: GPUs are not CPUs

The final layer is the one finance cares about most, and the one engineers are worst at estimating. GPUs are expensive, lumpy, and priced like a used car.

Three levers matter:

1. **Utilization.** An idle H100 costs $3–5/hour depending on the provider and burns the same whether it serves 0 tokens or 30,000. Pushing steady-state utilization from 30% to 70% roughly halves your $/token. Time-slicing, MIG, and right-sizing model replicas are the main levers.
2. **Batching and caching.** Every cached completion you serve is a request you don't pay inference cost for. Semantic caches at the gateway can cut spend 20–40% on workloads with repeated prompts (customer support, RAG over a small corpus).
3. **Model right-sizing.** A 7B model with a good prompt beats a 70B model with a lazy one about half the time. Track quality-adjusted cost, not raw cost.

The data model that ties this together:

- **Tag every request** with model, tenant, prompt template, cached vs uncached, input/output tokens, and dollar cost (use the provider's published rates for hosted models; use the amortized hardware cost for self-hosted).
- **Roll up daily and weekly** by team and by product feature.
- **Chargeback or showback** to product owners. Engineers who can see their GPU spend make better decisions than engineers handed a corporate-wide number.

Tools like [OpenCost](https://opencost.io/) (with its [GPU support](https://github.com/opencost/opencost)) and the various cloud-provider-native dashboards will get you 60% of the way. The last 40% is custom tagging and a willingness to push back on teams who want a frontier model for a classification task.

## Patterns in production

A few patterns show up over and over across mature AI infrastructure teams:

- **Gateway-first.** Every team routes through the same AI gateway. No exceptions. This is the only way to get a coherent cost and security story.
- **Disaggregated prefill/decode for high QPS.** If you're serving more than a few hundred tokens/sec, the latency win from splitting prefill and decode across different GPU pools is usually worth the networking complexity.
- **Topology-aware everything.** Schedulers, service mesh routing, and even your DNS need to know about NVLink rails and InfiniBand topology. If they don't, you're leaving 20–40% of GPU spend on the table.
- **Eval before deploy.** Every model upgrade goes through a held-out eval set and a shadow traffic period. Latency regressions are easy to catch; quality regressions are not.
- **Treat the gateway SLO as the product SLO.** If the gateway is healthy, the user is happy. Everything else is internal.

## Key Takeaways

- An AI request crosses at least nine layers; debugging tail latency means instrumenting all of them, not just the model.
- The AI gateway is the single most leveraged piece of infrastructure you can add — it's where auth, caching, routing, cost metering, and safety all meet.
- Inference servers are stateful, GPU-pinned, and slow to scale; size for steady-state, not peak, and accept that you'll over-provision.
- GPU scheduling on Kubernetes needs topology awareness, gang scheduling, and graceful draining or you will get preemption storms.
- East-west traffic (tensor parallel, prefill/decode disaggregation) is the new bottleneck; rail-optimized fabrics and RoCE/InfiniBand tuning matter more than people expect.
- Observability must stitch GPU metrics (DCGM), inference metrics, and OpenTelemetry traces together with tenant-level slicing.
- Agents open a new attack surface; put your controls at the gateway and treat model weights as a supply-chain artifact.
- FinOps only works if every request is tagged end to end; cost without attribution is just a bill.

## Further Reading

- [NVIDIA Dynamo — A datacenter-scale distributed inference serving framework for generative AI](https://github.com/ai-dynamo/dynamo)
- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html)
- [Karpenter documentation — GPU node provisioning](https://karpenter.sh/docs/)
- [OpenInference semantic conventions for LLM observability](https://github.com/Arize-OpenInference/open-inference)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [OpenCost — Kubernetes cost monitoring with GPU support](https://opencost.io/)
- [Mooncake: KVCache-centric Disaggregated Architecture for LLM Serving](https://github.com/kvcache-ai/Mooncake)