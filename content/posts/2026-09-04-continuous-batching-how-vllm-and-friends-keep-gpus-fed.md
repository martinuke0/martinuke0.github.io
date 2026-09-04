---
title: "Continuous Batching: How vLLM and Friends Keep GPUs Fed"
date: "2026-09-04T12:39:25.353"
draft: false
tags: ["llm-inference", "vllm", "continuous-batching", "gpu", "pytorch"]
description: "Continuous batching keeps GPU utilization high under variable LLM request lengths. Here's how it works under the hood and where it shines in production."
summary: "A working engineer's guide to continuous batching for LLM inference: why static batching wastes GPU cycles, how iteration-level scheduling works, and what tools like vLLM and TGI actually do differently."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-continuous-batching-how-vllm-and-friends-keep-gpus-fed.svg"
  alt: "Abstract illustration of GPU scheduling slots filled and freed across inference steps."
  caption: ""
  relative: false
---

> **TL;DR** — Continuous batching schedules requests at every decode step instead of waiting for an entire batch to finish, so short prompts don't leave long ones holding GPU slots idle. Production engines like vLLM, TGI, and TensorRT-LLM use this trick (often alongside PagedAttention) to push tokens-per-second-per-GPU up by 10x or more versus naive static batching.

## Why Static Batching Breaks Down

The first wave of LLM serving stacks borrowed from CNN serving: pack a batch of N requests, run them together, return when the last one finishes. For BERT-style classifiers that's fine — every request takes the same number of forward passes. For an autoregressive decoder, it's catastrophic.

Consider a batch of 64 requests where 63 finished generating after 30 tokens and one is still going at 800 tokens. With static batching, those 63 finished requests have already shipped their responses, but the GPU keeps crunching the 64th sequence alone. You're paying for the whole batch's worth of memory and compute to serve a single straggler. This problem is well-known; it's the throughput killer that motivated the design of [vLLM's PagedAttention paper](https://arxiv.org/abs/2309.06180) and [the Anyscale write-up on continuous batching](https://www.anyscale.com/blog/continuous-batching-llm-inference).

The waste compounds in production. Traffic to a chat API is heavily skewed: most responses are a few hundred tokens, a long tail runs to several thousand. Static batching on that mix gives you the worst of both worlds — high tail latency and low steady-state throughput.

## What Continuous Batching Actually Is

Continuous batching (sometimes called "iteration-level scheduling") treats the decode loop differently. Instead of waiting for the whole batch to terminate, the scheduler reconsiders membership **after every single token-generation step**.

Concretely:

1. Fill a prefill batch from the waiting queue (long-context prompts that need the full forward pass).
2. Run one decode step across all currently active sequences.
3. Check each sequence: did it emit an EOS, exceed `max_tokens`, or get cancelled? If so, free its slot.
4. Pull fresh requests from the queue into the freed slots.
5. Go to step 2.

That's it. No batch boundaries in time, just a constantly-rotating population of sequences that share the same KV cache buffers. The technique was popularized for LLMs in the [AnyScale / Ray "How continuous batching enables 23x throughput" post](https://www.anyscale.com/blog/continuous-batching-llm-inference) and is now the default in every serious open-source engine.

The mental shift: stop thinking of a "batch" as a cohort of requests that travel together. Think of it as a **rolling set of sequences sharing GPU resources at this instant**.

## Architecture: Where the Scheduler Lives

A continuous-batching engine has three big moving parts:

- **Request queue** — incoming prompts with their sampling params, priority, and arrival timestamp.
- **Scheduler** — decides which queued requests get admitted next and which active sequences get evicted (only matters under memory pressure).
- **Worker** — owns the model weights and KV cache on the GPU; runs prefill and decode kernels.

```text
                 ┌──────────────┐
   HTTP/gRPC ──▶ │ Request Queue│
                 └──────┬───────┘
                        │   admitted
                        ▼
   ┌────────────┐  pop  ┌────────────┐
   │ Scheduler  │◀─────▶│   Worker   │  KV cache + model
   │ (per step) │ step  │   (GPU)    │
   └────────────┘ done  └────────────┘
                        │
                        ▼
                  streaming tokens
                  to clients
```

The scheduler's job looks small, but it's where most production correctness bugs hide: preemption policy, fairness across tenants, draining partial sequences on shutdown, and the order in which decode tokens are returned to each client.

## Prefill vs. Decode: The Hidden Cost

A continuous batcher has to balance two very different GPU workloads:

- **Prefill** — the initial forward pass over the prompt. Compute-bound, quadratic-ish in prompt length, no KV cache yet. A 4k-token prompt can dominate a step.
- **Decode** — one new token per active sequence. Memory-bandwidth-bound; you spend most of the time reading model weights and KV cache.

Naively mixing the two in the same step causes "bubbles" — long prefills stall decoders, and decoders leave the prefill underutilized once it joins. The fix, popularized by vLLM, is **chunked prefill**: split a long prefill into manageable slices and interleave them with decode steps. [The vLLM docs cover the trade-offs](https://docs.vllm.ai/en/latest/serving/engine_args.html).

In practice, good engines expose knobs like:

```yaml
scheduler:
  max_num_seqs: 256
  max_num_batched_tokens: 8192
  chunked_prefill: true
```

Tune `max_num_batched_tokens` to bound how much prefill can enter a single step. Too high and decode latency spikes; too low and you're underutilizing the GPU on prompt-heavy loads.

## PagedAttention: The Other Half of the Story

Continuous batching frees slots quickly. But freed slots are useless if your KV cache is laid out as one big contiguous tensor per sequence. That's where [PagedAttention](https://arxiv.org/abs/2309.06180) (from the same vLLM team) comes in.

Instead of allocating `max_seq_len` worth of KV cache per request upfront, vLLM breaks the cache into fixed-size pages (typically 16 tokens). Each sequence holds a page table mapping logical positions to physical pages. When a sequence finishes, its pages return to a free list instantly.

This matters because:

- **Memory fragmentation drops** — you stop reserving 4k-token buffers for sequences that might end at 200 tokens.
- **Preemption becomes cheap** — if the cache fills up, you can swap a sequence's pages to CPU and reload later, the way an OS swaps memory.
- **Batch size scales** — more sequences fit on the same GPU, which means more decode tokens per step.

Continuous batching without PagedAttention leaves memory wasted. PagedAttention without continuous batching wastes compute. The two were designed together and ship together in [vLLM](https://github.com/vllm-project/vllm), [TGI](https://github.com/huggingface/text-generation-inference), and [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM).

## Patterns in Production

A few configurations I keep seeing land well:

### 1. Token-aware load balancing

Front the engine with a router that doesn't just round-robin requests but tracks **in-flight tokens per replica**. A replica handling one 8k-token prefill is far more loaded than one handling forty 200-token decodes. vLLM exposes this signal via its `/metrics` endpoint; Prometheus + a custom router consume it.

### 2. Speculative decoding on top

[Speculative decoding](https://arxiv.org/abs/2211.17192) drafts several tokens with a small model and verifies them with the big one. It plays beautifully with continuous batching because the draft and verify steps both fit inside the same per-step scheduler tick. Many production setups report 2–3x additional throughput on top of continuous batching alone.

### 3. Prefix caching for system prompts

If 40% of your traffic shares a 1k-token system prompt, you're doing 40% redundant prefill work. vLLM's `enable_prefix_caching` (also called "automatic prefix caching") hashes prompt prefixes and reuses their KV pages across requests. Combined with continuous batching, this is the single biggest win for chat workloads with long system prompts.

### 4. Disaggregated prefill/decode

The newest pattern, used at scale by the [DistServe paper](https://arxiv.org/abs/2401.09670) and partially by [Moonshot's reports](https://medium.com/@moonshotwonderland), splits the two phases onto different GPU pools. Prefill is compute-heavy and tolerates batching; decode is latency-sensitive and benefits from a dedicated, lightly-loaded pool. Continuous batching still runs inside each pool.

## Where It Falls Short

Continuous batching is not magic. Real failure modes:

- **Stateful fine-tuning inference** — beam search with shared KV caches across branches gets awkward when branches exit mid-batch. Most engines handle this with care but it's a known sharp edge.
- **Tight latency SLOs on the first token** — TTFT (time to first token) is dominated by prefill. Continuous batching helps throughput but doesn't shorten prefill. For TTFT-sensitive workloads (autocomplete, voice), you end up tuning prefill batching separately.
- **Fairness across tenants** — when the GPU is saturated, a long request can starve new short ones. Engines need explicit preemption policies; without them, small requests sit in the queue while big ones camp on slots.

These are solvable, but each requires reading the scheduler source. There's no "fair by default" mode that survives contact with a real traffic mix.

## A Minimal Mental Model

If you remember nothing else, remember this loop:

```python
while gpu_has_capacity():
    free_slots = evict_finished_sequences()
    admit_prefills_and_decodes(free_slots)
    one_decode_step()           # every active seq gets +1 token
    stream_results_to_clients() # for those that just finished
```

Every line is a knob. `evict_finished_sequences` is where PagedAttention lives. `admit_prefills_and_decodes` is where chunked prefill lives. `one_decode_step` is where speculative decoding hooks in. The rest of the engineering is plumbing: HTTP/gRPC servers, metrics, multi-GPU tensor parallelism, and the inevitable edge cases around cancellation and timeouts.

## Key Takeaways

- Static batching wastes GPU cycles on stragglers; continuous batching reschedules after every decode step.
- Continuous batching + PagedAttention are the standard pairing in modern open-source LLM serving engines.
- Chunked prefill, prefix caching, and speculative decoding are the three highest-leverage optimizations to layer on top.
- Disaggregated prefill/decode is the emerging production pattern at very large scale.
- Continuous batching optimizes throughput, not TTFT — for latency-critical paths, you need to think about prefill scheduling separately.

## Further Reading

- [How continuous batching enables 23x throughput in LLM inference — Anyscale](https://www.anyscale.com/blog/continuous-batching-llm-inference)
- [PagedAttention paper (vLLM)](https://arxiv.org/abs/2309.06180)
- [vLLM documentation — engine arguments and scheduling](https://docs.vllm.ai/en/latest/serving/engine_args.html)
- [HuggingFace Text Generation Inference](https://github.com/huggingface/text-generation-inference)
- [NVIDIA TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM)
- [DistServe: Disaggregating Prefill and Decoding for Goodput-optimized Large Language Model Serving](https://arxiv.org/abs/2401.09670)
- [Fast Inference from Transformers via Speculative Decoding](https://arxiv.org/abs/2211.17192)