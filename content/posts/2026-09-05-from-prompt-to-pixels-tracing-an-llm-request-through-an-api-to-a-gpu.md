---
title: "From Prompt to Pixels: Tracing an LLM Request Through an API to a GPU"
date: "2026-09-05T18:47:13.903"
draft: false
tags: ["llm", "inference", "gpu", "api-design", "mlops"]
description: "A working engineer's tour of what happens between sending an LLM prompt and the GPU kernels that produce the answer, covering HTTP, batching, KV cache, and CUDA."
summary: "We follow a single chat completion request from a client SDK down through the inference server, into the model runner, and finally into the CUDA kernels that execute on a GPU — with the bottlenecks and knobs along the way."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-from-prompt-to-pixels-tracing-an-llm-request-through-an-api-to-a-gpu.svg"
  alt: "Abstract visualization of tokens flowing from an API request into a GPU as parallel compute lanes."
  caption: ""
  relative: false
---

> **TL;DR** — An LLM API call looks like one HTTP request, but behind it sits a request router, a scheduler, a token-level batching loop, a quantized model loader, and ultimately CUDA kernels that are heavily memory-bound. The interesting engineering happens in those layers, and understanding them is what separates "the model is slow" from "I know exactly which lever to pull."

## Why the path matters

If you've shipped anything built on an LLM — a chatbot, a code reviewer, a retrieval-augmented search box — you've probably hit one of three walls: latency on the first token, throughput per dollar, or a tail-latency spike at 3 a.m. that pages someone. Each wall lives at a specific hop along the path from prompt to GPU, and most "model improvements" you can apply (quantization, speculative decoding, prefix caching, prompt compression) only make sense once you can name the hop they affect.

This post traces a single request from the moment your client code calls `chat.completions.create(...)` to the moment CUDA writes a token id back into host memory. We'll stop at each hop, name the moving parts, and call out the knobs that production teams actually turn.

## Hop 1: The HTTP edge

The journey begins at a load balancer in front of an inference fleet. At the edge you'll typically find one of three things:

- A managed endpoint (OpenAI, Anthropic, Google) where the LB is opaque to you but the SLA is the contract.
- A self-hosted front-end like [LiteLLM](https://github.com/BerriAI/litellm), [vLLM's OpenAI-compatible server](https://docs.vllm.ai), or [NVIDIA Triton + FastAPI](https://docs.nvidia.com/deeplearning/triton-inference-server), which speak the same `/v1/chat/completions` shape so existing SDKs "just work."
- A custom gateway (Envoy, Kong, or a thin FastAPI service) where you've added auth, rate limiting, and audit logging.

What the edge does:

1. **Authn / authz** — validates an API key or JWT and attaches a tenant or team id to the request.
2. **Rate limiting & quotas** — token bucket per tenant, often computed against *expected* output tokens, since you can't know exactly until the model decodes.
3. **Request normalization** — the OpenAI Chat Completions schema is a thin contract; behind it the server often rewrites the `messages` array into a single prompt with a chat template, adds system prompts for safety, and computes the total prompt token count.
4. **Routing** — picks a backend instance. Sophisticated routers route by model size, current queue depth, or even by which instance already has the prompt in its prefix cache.

A minimal OpenAI-compatible request looks like this:

```bash
curl https://api.your-llm.example/v1/chat/completions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.1-70b-instruct",
    "messages": [
      {"role": "system", "content": "You are a senior backend engineer."},
      {"role": "user", "content": "Why is my p99 latency 4 seconds?"}
    ],
    "max_tokens": 512,
    "stream": true
  }'
```

`stream: true` is the single biggest UX lever for chat workloads. Without it, the client blocks until the entire generation is done; with it, the server starts emitting Server-Sent Events as soon as the first token is ready. That changes which hop actually controls perceived latency.

## Hop 2: The inference server

Once a request lands on a backend node, the **inference server** (vLLM, TGI, SGLang, TensorRT-LLM) owns the next several hops. It is *not* a thin proxy — it's a runtime with its own scheduler.

The server's job, in order:

1. **Tokenize the prompt.** Tokenization is fast but not free. A 10k-token prompt with a BPE tokenizer takes a few milliseconds; a 200k-token long-context prompt can take 50–100 ms. Production servers cache compiled tokenizers and warm them at boot.
2. **Check the prefix cache / KV cache reuse.** If another request recently had a long common prefix (think: system prompt + RAG context header), the server may reuse the cached key/value tensors and skip recomputing attention for those tokens. This is one of the largest throughput wins in multi-turn chat and RAG systems — [vLLM's automatic prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html) is the canonical example.
3. **Enqueue the request.** The server hands the request to a scheduler. This is where the magic of *continuous batching* lives.

### Continuous batching vs. static batching

Older serving setups used **static batching**: pack N requests, run them until the longest one finishes, then return. The shorter requests waste GPU time waiting. This is why naive HF Transformers deployments look so slow.

Modern servers use **continuous batching** (sometimes called *iteration-level scheduling*): at every decoding step, the scheduler looks at all in-flight requests, evicts those that finished (`<eos>` or `max_tokens`), and slots new prefill or decode requests in. GPUs in LLM serving are *batched* at the token level — every active sequence contributes its tokens to the next forward pass. The effect, per the [vLLM paper](https://arxiv.org/abs/2309.06180), is often a 10–20x throughput improvement on chat traffic.

There are three queues the scheduler juggles:

- **Waiting** — requests still being prefilled (the prompt is being processed).
- **Running** — requests currently generating tokens.
- **Swapped** — preempted requests whose KV cache was spilled to CPU because the GPU ran out of KV memory.

Preemption is the production gotcha. When memory pressure rises, the scheduler may choose between *recompute* (drop the KV cache and re-decode from the prompt next time) or *swap* (copy the KV cache to host RAM and page it back in later). Recompute is cheaper in memory bandwidth but more expensive in FLOPs when the request resumes; swap is the opposite. Pick by request length.

## Hop 3: The model runner and weight loader

The scheduler hands a batch to the model runner. At this hop we transition from Python orchestration to compiled compute.

Before the first request ever runs, the loader:

1. **Reads weights from disk** — typically safetensors or a sharded checkpoint.
2. **Quantizes on load** — converts FP16/BF16 weights to INT8, INT4 (GPTQ, AWQ), or FP8, depending on the hardware. Quantization trades a small amount of quality for 2–4x less memory and memory bandwidth, which is exactly what LLM inference is bottlenecked on. The [TensorRT-LLM quantization guide](https://github.com/NVIDIA/TensorRT-LLM) is the reference for what's possible on Hopper and Ada GPUs.
3. **Builds the execution graph** — fuses attention, normalizes, and gating into optimized CUDA or TensorRT engines. This compilation step can take 30–120 seconds at boot and is why warm-up matters.

At runtime, the runner:

- Allocates a **KV cache** sized by `max_num_seqs × max_model_len × num_layers × num_heads × head_dim × 2 (k,v) × dtype_bytes`. For a 70B model with 8k context and 64 concurrent sequences, that's tens of gigabytes — the dominant memory consumer in production.
- Manages a **CUDA graph** for the decode step. A prefill pass is one big kernel launch across the whole prompt; a decode step launches ~tens of small kernels per layer for a single token. CUDA graphs let the runtime record the entire decode loop once and replay it with near-zero CPU overhead, which is critical because decode is latency-sensitive.

## Hop 4: The actual CUDA — prefill vs. decode

Once the batch reaches the GPU, two very different workloads run. Conflating them is the most common mistake newcomers make.

### Prefill

The prefill pass ingests the entire prompt and computes attention for every prompt token against every other prompt token. This is **compute-bound**: it's essentially a big matmul on the prompt length dimension. GPUs love this — tensor cores are fully utilized.

For a 4k-token prompt on a 70B model, prefill might generate the first output token in 200–800 ms on an H100. This is the *time-to-first-token* (TTFT) that users feel.

Optimization knobs at this hop:

- **Chunked prefill** — instead of treating the whole prompt as one block, split it into chunks that share the GPU with active decode requests. vLLM and SGLang both implement this; it raises throughput at the cost of a small TTFT hit.
- **FlashAttention / FlashInfer** — fused, IO-aware attention kernels that avoid materializing the full N×N attention matrix. [FlashAttention](https://github.com/Dao-AILab/flash-attention) is essentially mandatory in any modern serving stack.
- **Speculative decoding** — a small draft model proposes tokens, the large model verifies them in one forward pass. Can cut latency 2–3x on workloads where the draft model is good at the task. See the [speculative execution docs in vLLM](https://docs.vllm.ai).

### Decode

Decode produces one token at a time, but each token still requires a full forward pass through every layer. The arithmetic intensity is terrible — a 70B model doing 1 token of decode uses 70B FLOPs to produce 2–4 bytes of output. This is **memory-bandwidth bound**: the GPU spends most of its time streaming weights from HBM.

That's why quantizing weights helps so much: it shrinks the bytes you have to stream per token. A 70B model at FP16 is ~140 GB; at INT4 it's ~35 GB, which both fits in cheaper GPUs and reads 4x faster.

Decode also writes a growing KV cache. Each new token must attend to every previous token in the sequence, so the KV cache is read once per layer per generated token. KV-cache layout is a hot research area — paged KV (à la vLLM's [PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html)) avoids the fragmentation that crippled earlier systems.

### A peek at the kernels

You don't need to write CUDA to reason about the kernels, but it helps to know which ones are on the hot path. A decode step on a transformer block typically runs:

```text
1. RMSNorm                — elementwise, bandwidth bound
2. QKV projection         — one big GEMM, tensor-core bound
3. RoPE                   — elementwise on Q and K
4. Attention              — FlashAttention kernel, mostly bandwidth on KV
5. Output projection      — GEMM
6. RMSNorm
7. MLP gate/up projections — two GEMMs
8. SwiGLU                 — elementwise
9. MLP down projection    — GEMM
10. Residual add          — elementwise
```

Each one is a separate kernel launch — unless you're using CUDA graphs to replay the whole sequence. Profile your serving stack with [Nsight Systems](https://developer.nvidia.com/nsight-systems) at least once; the gap between "the model is slow" and "step 4 is dominating because KV is in HBM and you're at 60% of peak bandwidth" is enormous.

## Hop 5: Streaming back to the client

Once the runner produces a token id, it has to get back to your browser, IDE plugin, or backend service. Streaming matters here in two ways:

- **Perceived latency.** Streaming means TTFT ≈ wall-clock for the first token. Non-streaming means TTFT + full-generation time.
- **Backpressure.** If your client is slow, the server will buffer. Most servers cap this with a per-request timeout; some will preempt the request if the socket is unhealthy for too long.

The wire protocol is usually SSE over HTTP/1.1 or HTTP/2, or WebSockets for bidirectional use cases. Each chunk is small — typically 20–80 bytes of JSON like:

```text
data: {"id":"chatcmpl-abc","object":"chat.completion.chunk","choices":[{"delta":{"content":"The"},"index":0}]}
```

For multi-region deployments, route streaming responses through the same edge to avoid TCP middlebox issues; some NATs idle-kill HTTP/1.1 streams after 60 s, which will silently break a long generation. HTTP/2 or HTTP/3 generally handle this better.

## Architecture: what good production stacks look like

Putting the hops together, a production architecture for self-hosted LLMs in 2026 typically looks like this:

```text
                  ┌──────────────────────────────────────┐
   Client SDK ──▶ │  Edge: Envoy + auth + rate limiting  │
                  └──────────────┬───────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────┐
                  │  Gateway: LiteLLM / vLLM API server  │
                  │  - routes by model                   │
                  │  - manages prefix cache              │
                  └──────────────┬───────────────────────┘
                                 │
                ┌────────────────┼─────────────────┐
                ▼                ▼                 ▼
        ┌────────────┐    ┌────────────┐    ┌────────────┐
        │ GPU node 0 │    │ GPU node 1 │    │ GPU node 2 │
        │ vLLM proc  │    │ vLLM proc  │    │ vLLM proc  │
        │ TensorRT   │    │ TensorRT   │    │ TensorRT   │
        │ engines    │    │ engines    │    │ engines    │
        └────────────┘    └────────────┘    └────────────┘
                │                │                 │
                └────────────────┴─────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────┐
                  │  Observability: Prometheus + OTel    │
                  │  - TTFT, ITL, throughput per model   │
                  └──────────────────────────────────────┘
```

Key patterns that show up across teams running this stack:

- **Heterogeneous fleets.** Small models (7B–13B) on L4s for cheap classification and routing; large models (70B+) on H100s or H200s for the hard questions. The gateway picks the model by intent, not by accident.
- **Prefix caching across requests.** Aggressive normalization of system prompts (e.g., always include the same 200-token guardrail text first) so the KV cache hit rate stays high. This is the single highest-leverage change many teams can make.
- **Speculative decoding for long prompts.** A small draft model drafts cheap tokens; the big model verifies. Combined with prefix caching, this can drop tail latency by half on summarization workloads.
- **Bounded queues.** `max_num_seqs` per GPU is set so the scheduler can never admit more work than fits in KV cache + a safety margin. Over-admission is the #1 cause of thrashing in self-hosted stacks.
- **Decoding observability.** Three numbers matter more than anything else: TTFT (prefill + queue), inter-token latency (decode steady state), and effective tokens-per-second-per-GPU. If you only have one Grafana panel, make it the third one.

## Key Takeaways

- The path from a chat completion request to a GPU is **at least five distinct hops**, and each one has its own bottleneck: edge (auth, quota, routing), inference server (tokenization, prefix cache, scheduling), model runner (quantization, KV cache, CUDA graphs), CUDA kernels (prefill vs. decode character), and streaming back (backpressure, wire protocol).
- **Continuous batching and paged KV cache** are the two innovations that made self-hosted LLMs economically reasonable; if your stack doesn't have both, that's your throughput ceiling.
- **Decode is memory-bandwidth bound; prefill is compute bound.** Quantization, KV-cache layout, and FlashAttention help decode; bigger prompts and speculative decoding help prefill.
- **TTFT and inter-token latency are separate metrics.** Optimizing one without measuring the other is how teams ship "the model is faster now!" but get worse UX.
- **CUDA graphs and warm-up matter.** Cold-start cost on a quantized 70B model can be 30–60 seconds; your autoscaler needs to know about it, or you'll burn tokens on cold paths.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html)
- [FlashAttention: Fast and memory-efficient exact attention with IO-awareness](https://github.com/Dao-AILab/flash-attention)
- [How continuous batching enables 23x throughput in LLM inference](https://www.anyscale.com/blog/continuous-batching-llm-inference)
- [NVIDIA TensorRT-LLM documentation](https://github.com/NVIDIA/TensorRT-LLM)
- [Nsight Systems: a profiler for GPU-accelerated applications](https://developer.nvidia.com/nsight-systems)