---
title: "The LLM Inference Roadmap I Wish More Engineers Followed"
date: "2026-09-02T15:46:40.653"
draft: false
tags: ["llm-inference", "production-engineering", "vllm", "kv-cache", "model-serving", "performance"]
description: "A production-focused LLM inference roadmap covering batching, KV cache, quantization, streaming, and observability, written for working engineers."
summary: "Most teams treat LLM inference like a REST call. This roadmap walks through the layers that actually decide cost and latency in production — from continuous batching to KV cache layout to speculative decoding."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-the-llm-inference-roadmap-i-wish-more-engineers-followed.svg"
  alt: "A diagram showing the stages of an LLM inference request moving from the API edge through the scheduler, KV cache, and GPU."
  caption: ""
  relative: false
---

> **TL;DR** — LLM inference in production is a systems problem, not an API problem. The teams that hit good cost and latency numbers treat batching, KV cache management, quantization, and observability as first-class engineering concerns, not afterthoughts.

---

I've been on a few different sides of the LLM inference stack now — training, fine-tuning, and shipping models behind production endpoints. The gap that surprises me every time is between what the model card implies ("you can serve this with one GPU!") and what actually happens when traffic goes from a notebook demo to a million requests a day.

Most engineers approach inference like any other REST endpoint: pick a model, point a client at it, add retries. That works until the first time you profile the GPU and realize you're spending 70% of your memory on the **KV cache**, your batch size is effectively 1 because you're using naive batching, and your "low-latency" streaming endpoint is making each user wait on the tail of a 200-token generation.

This post is the roadmap I wish someone had handed me two years ago. It's not a survey of every inference technique — it's the stack of decisions that, in my experience, separate teams that ship a working demo from teams that ship a profitable inference service.

## Why Inference Is Harder Than It Looks

A transformer forward pass during inference is autoregressive: each new token depends on every previous token. That creates three properties that don't show up in training:

1. **Latency is sequential.** You can't parallelize across tokens within a single request the way training parallelizes across a batch dimension. A 512-token response is fundamentally 512 sequential decode steps.
2. **Memory is dominated by state, not weights.** During training, activations and gradients dominate. During inference with long contexts or large batches, the **KV cache** — the keys and values stored for every previous token at every layer — dominates. For a 7B model at 4K context, the KV cache is roughly the same size as the model weights in FP16.
3. **Workload is bursty and heterogeneous.** Requests arrive at random, with random prompt lengths and random desired output lengths. Naive batching wastes the majority of GPU cycles waiting for the longest request in the batch to finish.

If you only remember one thing from this post, remember this: **the KV cache is the system.** Everything else — schedulers, quantization, paging — exists to manage it.

## The Stack, From Top to Bottom

Here's the mental model I use. Every layer matters, but each one has different diminishing returns.

| Layer | Question it answers | Tools / examples |
|---|---|---|
| Serving runtime | Where do requests queue, batch, and stream? | vLLM, TGI, SGLang, TensorRT-LLM |
| Scheduler | Which requests run together on which GPU? | Continuous batching, chunked prefill |
| Memory manager | Where do KV tensors live? | PagedAttention, prefix caching |
| Kernels | How do we actually compute attention? | FlashAttention, FlashInfer, xformers |
| Quantization | How do we shrink weights and KV? | INT8/INT4, FP8, KV cache quantization |
| Hardware | What silicon runs it? | H100, A100, L40S, MI300X |
| Observability | What is actually happening in production? | Prometheus, vLLM metrics, custom traces |

You can spend a lot of time on the bottom of the stack and still have a slow system if your scheduler is naive. You can have a perfect scheduler and still miss SLOs if your kernels are un-fused. The order I tackle optimizations in is roughly top-down, because each layer above multiplies the impact of the layer below.

## 1. Stop Using Static Batching

The single highest-leverage change is moving from static (naive) batching to **continuous batching** — sometimes called iteration-level scheduling.

In static batching, you wait for a full batch of N requests, run them all to completion, then start the next batch. If one request wants 50 tokens and another wants 500, you wait for the 500-token one. Your GPU sits at 5% utilization on most iterations.

In continuous batching (introduced to the open-source world by vLLM, building on the [Orca paper](https://www.usenix.org/system/files/osdi22-yu.pdf)), the scheduler swaps requests in and out **at every token iteration**. The moment one request finishes, a new one takes its slot. GPU utilization stays high, p99 latency drops, and effective throughput can increase 10x–20x.

Concretely, in [vLLM](https://blog.vllm.ai/2023/06/20/vllm.html) this looks like:

```bash
vllm serve meta-llama/Meta-Llama-3-8B-Instruct \
  --max-num-seqs 256 \
  --max-model-len 8192 \
  --enable-prefix-caching \
  --gpu-memory-utilization 0.92
```

The `--max-num-seqs` flag controls how many requests can be in flight at once. The scheduler fills slots greedily from the waiting queue every iteration.

If you're still using `transformers.generate` with a `DataLoader` in production, this is the single biggest win available to you.

### A Word on Prefill vs. Decode

Modern schedulers split each request into two phases:

- **Prefill:** process the entire prompt at once to fill the KV cache. This is compute-bound and parallelizable.
- **Decode:** generate one token at a time, attending to the growing KV cache. This is memory-bandwidth bound.

Mixing prefill and decode in the same batch causes **prefill bubbles** — a long prefill stalls all decodes in the batch. Chunked prefill (in SGLang, vLLM, and TensorRT-LLM) splits the prefill into small chunks that interleave with decode steps, smoothing the latency at the cost of a bit more total compute.

## 3. Treat the KV Cache Like a Memory System

Once you have continuous batching, your next bottleneck is almost always KV cache memory. Here's the math that should scare you into caring about it:

For a Llama-3-8B model with 32 layers, 8 KV heads, head dim 128, FP16, and 4096 context:

- Per-token KV cache ≈ `2 × 32 × 8 × 128 × 2 bytes` = **131 KB per token**
- At 4096 context, that's **~512 MB per request**
- A single H100 with 80 GB can therefore hold ~150 requests at full context, *before* weights

You will run out of memory long before you run out of FLOPs.

### PagedAttention

The breakthrough insight from the [vLLM PagedAttention paper](https://arxiv.org/abs/2309.06180) is that the KV cache should be managed like virtual memory: stored in fixed-size pages and mapped via a per-request page table.

Why this matters:

- **No fragmentation.** Requests of different lengths pack tightly into pages.
- **Copy-on-write prefix sharing.** If 10 requests share a 2000-token system prompt, they share one physical set of pages and only allocate new pages for the divergent suffix.
- **Beam search and parallel sampling** become cheap because forked requests can share prefix pages.

In practice, prefix caching (sometimes called "automatic prefix caching") is one of the most underused features in production. If your workload has a long system prompt, a few-shot examples, or repeated chat templates, enabling it can double throughput overnight.

### KV Cache Quantization

Once pages are paged, the next question is how many bits each entry takes. Quantizing the KV cache to INT8 or even INT4 is an active area — see [KIVI](https://arxiv.org/abs/2402.02750) and the [Atom](https://arxiv.org/abs/2310.19102) method — but FP8 KV cache is shipping today in TensorRT-LLM and vLLM on Hopper-class hardware. Plan to budget for it in any long-context workload.

## 4. Quantization Is Not Just About Weights

Most engineers know about weight quantization (INT4, GPTQ, AWQ, etc.). The trick is that **activation and KV precision matter as much, sometimes more**, especially for decode.

| Precision | Where it helps | Quality risk |
|---|---|---|
| FP16 / BF16 weights | Baseline | None |
| INT8 weights (W8A16) | Most workloads, near-zero quality loss | Minimal |
| INT4 weights (GPTQ/AWQ) | Memory-bound serving | Small for most chat models |
| FP8 weights + FP8 KV | Hopper-class GPUs | Small, usually negligible |
| INT4 KV cache | Long-context, high concurrency | Measurable on reasoning tasks |

A practical path I've seen work well:

1. Start with BF16 to establish a quality baseline and latency floor.
2. Move to FP8 weights if you're on H100. It's free performance.
3. Try INT4 weights (AWQ is the current favorite for quality) if you need more requests per GPU.
4. Quantize KV only after you're sure weight quantization hasn't broken you.

The warning sign to watch for is **repetition loops and reasoning collapse** at very long contexts. INT4 KV often degrades there before it degrades on short prompts.

## 5. Kernels: Why You Can't Roll Your Own Attention

Even with a perfect scheduler and paged memory, a naive attention kernel will tank your throughput. Modern attention is dominated by **FlashAttention** and its descendants.

The original [FlashAttention paper](https://arxiv.org/abs/2205.14135) showed that the standard attention implementation is severely memory-bandwidth-bound: it materializes the full `N x N` attention matrix, which is O(N²) in HBM traffic. FlashAttention fuses the softmax with the matmul and keeps intermediates in SRAM, reducing HBM traffic to O(N).

For inference specifically, you need the **decode-optimized** variant. During decode, the query is a single token but keys and values span the whole context. That's a tall, skinny matmul where most of the time is spent loading KV from HBM. FlashAttention-2's decode path, [FlashInfer](https://github.com/flashinfer-ai/flashinfer), and [FlashAttention's decode kernels](https://github.com/Dao-AILab/flash-attention) all target this.

Practical advice:

- Don't write your own attention. Ever.
- Pick a serving runtime that already calls the right kernels for your hardware.
- Profile with `nvidia nsight` or `torch.profiler` to confirm attention isn't a hotspot — if it is, your runtime is misconfigured.

## 6. Speculative Decoding: Trading Compute for Latency

Once your system is well-tuned, you'll find that **time-to-first-token** is fine but **time-per-output-token** (TPOT) is your tail-latency problem. Each decode step is fundamentally sequential and memory-bound. Speculative decoding attacks exactly this.

The idea, from the [Google paper](https://arxiv.org/abs/2211.17192) and [DeepMind's work](https://arxiv.org/abs/2302.01318), is simple:

1. A small "draft" model proposes K tokens cheaply.
2. The large "target" model verifies all K in a single forward pass.
3. Accept the longest prefix that matches the target's distribution; resample from there.

In production this looks like a 2x–3x speedup on latency with **identical output distribution** — no quality regression, because the verification step guarantees the math works out.

Variants worth knowing:

- **Self-speculative decoding:** use early-exit layers of the same model as the drafter. No second model needed.
- **Medusa:** add extra "head" layers that propose multiple tokens from the same model's hidden state. Used in production by [FasterTransformer](https://github.com/microsoft/fast_speech/tree/main/Medusa) derivatives.
- **EAGLE / EAGLE-2:** treat the drafter as a learned autoregressor over hidden states. State of the art on most benchmarks.

The catch: speculative decoding helps most when the draft model's predictions are accepted at high rates (60%+). On tasks where the model is genuinely uncertain — creative writing, math — acceptance rates drop and the speedup shrinks. Measure on your own workload before committing.

## 7. Streaming, Batching Tokens, and Output Semantics

"Streaming" in LLM serving is not just a UI feature. It's a scheduling primitive.

When you stream tokens as they're decoded, you can:

- Begin rendering partial responses to the user (perceived latency drops dramatically).
- Implement early termination if a user cancels.
- Apply different SLOs to TTFT (time to first token) and TPOT.

Most serving frameworks expose this via Server-Sent Events. A typical vLLM streaming client:

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="EMPTY")

stream = client.chat.completions.create(
    model="meta-llama/Meta-Llama-3-8B-Instruct",
    messages=[{"role": "user", "content": "Write a haiku about GPUs."}],
    stream=True,
)

for chunk in stream:
    delta = chunk.choices[0].delta.content or ""
    print(delta, end="", flush=True)
```

Under the hood, the scheduler marks this request as "decode-only" after prefill and pushes tokens into the SSE stream as they're generated. If you build your own serving layer, **don't return the full response at the end**. You're giving up 80% of the latency win.

## 8. Observability: Metrics That Map to User Pain

The metrics that matter, in roughly descending order:

1. **Time to first token (TTFT)** — perceived responsiveness. Target <300ms for chat workloads.
2. **Time per output token (TPOT)** — generation speed. Target 30–80ms depending on model size.
3. **Inter-token latency p99** — jitter. The killer of "feels smooth" UX.
4. **Requests in flight / GPU** — saturation. If you're below 50, you have headroom; if you're at the cap, you need more replicas or smaller models.
5. **KV cache utilization** — if you're evicting prefixes aggressively, you're paying recompute cost.
6. **Prefix cache hit rate** — should be >50% on chat workloads with system prompts.
7. **Speculative acceptance rate** — if below 50%, your drafter isn't aligned.

Expose these as Prometheus metrics and **alert on TTFT p99 and prefix hit rate**. Most teams only alert on error rate, which means they learn about a regression only when users complain.

vLLM exposes most of these out of the box on `/metrics`. Grafana dashboards in the [vLLM repo](https://github.com/vllm-project/vllm/tree/main/examples) are a fine starting point.

## Patterns in Production

A few patterns I keep seeing on teams that ship well:

**Tiered models.** Route easy queries (FAQ, classification) to a small fast model, hard queries to a large slow model. The small model handles 70–90% of traffic and costs almost nothing. The large model is reserved for cases where it actually moves the needle.

**Aggressive prefix caching with cache warming.** Pre-populate the KV cache with system prompts and RAG context at boot. The first user after a deploy waits as long as the hundredth.

**Bounded output lengths.** Cap max_tokens per request at the API layer. A single 32k-token runaway request will evict everyone else's KV and tank p99.

**Disaggregation on multi-GPU.** On large models (70B+), splitting prefill and decode onto separate GPU pools gives massive throughput wins. See [DistServe](https://arxiv.org/abs/2401.09670) and the [Mooncake](https://github.com/kvcache-ai/Mooncake) architecture.

**Right-sizing the model.** The cheapest performance win is a smaller model. A well-tuned 8B will beat a misconfigured 70B on cost-per-useful-answer almost every time. Measure useful answers, not tokens.

## Key Takeaways

- **Continuous batching is table stakes.** If your serving runtime doesn't iterate at the token level, you're leaving 5x–20x throughput on the table.
- **The KV cache is the system.** Page it, share it via prefix caching, and budget memory for it before you budget for weights.
- **Quantize deliberately.** Start with FP8 if you can, INT4 weights if you must, and quantize KV only after measuring quality on real prompts.
- **Use proven attention kernels.** FlashAttention and FlashInfer exist for a reason; never roll your own.
- **Speculative decoding buys you latency without quality cost** — but only when acceptance rates are healthy.
- **Stream from the first token.** Both for UX and because it gives you cancellation and tighter SLOs.
- **Observe TTFT p99, prefix cache hit rate, and inter-token jitter.** These are your early-warning system.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — the paper that introduced paged KV cache and made continuous batching mainstream.
- [Orca: A Distributed Serving System for Transformer-Based Generative Models](https://www.usenix.org/system/files/osdi22-yu.pdf) — the original continuous-batching paper, foundational reading.
- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135) — the kernel work that makes modern attention possible.
- [DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving](https://arxiv.org/abs/2401.09670) — the architecture to reach for on 70B+ models.
- [Fast Inference from Transformers via Speculative Decoding (DeepMind)](https://arxiv.org/abs/2211.17192) — the canonical speculative decoding reference.
- [TensorRT-LLM documentation](https://nvidia.github.io/TensorRT-LLM/) — NVIDIA's production stack, worth studying for kernel-level patterns even if you don't deploy on it.
- [vLLM blog: How continuous batching enables 23x throughput](https://blog.vllm.ai/2023/06/20/vllm.html) — a short, concrete walkthrough of why iteration-level scheduling matters.