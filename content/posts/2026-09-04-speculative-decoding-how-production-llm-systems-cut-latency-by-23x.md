---
title: "Speculative Decoding: How Production LLM Systems Cut Latency by 2–3x"
date: "2026-09-04T12:40:43.291"
draft: false
tags: ["llm", "inference", "speculative decoding", "transformers", "performance"]
description: "A practitioner's guide to speculative decoding: how a small draft model can cut LLM inference latency 2–3x without changing outputs, with patterns from vLLM, TensorRT-LLM, and Medusa."
summary: "Speculative decoding trades a small draft model for big latency wins — 2–3x faster token generation with mathematically identical outputs. Here's how it works and where production systems use it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-speculative-decoding-how-production-llm-systems-cut-latency-by-23x.svg"
  alt: "Two pipelines merging — a fast draft model feeding into a verifier that accepts or rejects proposed tokens."
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding uses a small "draft" model to propose several tokens ahead, then has the target LLM verify them all in a single forward pass. Accepted tokens are kept; rejected ones are resampled. The output distribution is provably identical to running the target model alone, but generation is typically 2–3x faster because the target's expensive per-call overhead is amortized across many tokens.

## Why Autoregressive Generation Is Slow

Every token from a modern LLM is produced the same way: the model reads the entire KV cache of prior tokens, does a forward pass, samples from the logits, and appends the chosen token to the cache. Two things dominate the cost:

1. **Memory bandwidth.** The attention operation has to stream every previous key and value tensor from HBM on each generation step. For a 70B-parameter model at 8K context, a single decode step can read hundreds of megabytes of weights and KV state.
2. **Launch overhead.** Each step launches its own kernels — attention, MLP, sampling — and many of them are underutilized at small batch sizes.

The arithmetic intensity of one decode token on a 70B model is roughly 1 FLOP per byte moved, which puts it firmly in the regime where you're waiting on memory, not compute. The GPU is bored; you're paying for transfers.

This is the gap speculative decoding fills. It doesn't make the model "think faster" — it makes the expensive target model do **fewer steps** by batching multiple token decisions into a single forward pass.

## The Core Idea

Instead of sampling one token at a time, a speculative decoding system asks a small, cheap model to guess several future tokens. The large target model then scores all of those guesses at once. As long as the draft model is reasonably aligned with the target, the target accepts the guesses — and you've produced N tokens in the time it would normally take to produce one.

The trick is that **acceptance must not change the output distribution**. If the draft model were always right, this would be trivial: run the draft for K steps, run the target on the K draft tokens plus the prefix, accept everything that matches the target's argmax, done. But the draft will be wrong sometimes, and naive argmax acceptance would bias the output.

The original paper, [*Fast Inference from Transformers via Speculative Decoding*](https://arxiv.org/abs/2211.17192) (Leviathan, Kalman, Matias), resolves this with a clever sampling rule:

For each proposed token, the target model computes a probability `p(x)` and the draft model has computed `q(x)`. You accept the token with probability `min(1, p(x) / q(x))`. If you reject, you resample from a corrected distribution that compensates for the draft model's bias — typically `p'(x) = normalize(max(0, p(x) - q(x)))`.

Crucially, this acceptance-rejection scheme is mathematically proven to produce **the exact same token distribution as sampling from the target model directly**. The user cannot statistically distinguish the outputs.

```text
draft_token_0 ─► verify(p, q) ─► accept  ─► keep token, continue
draft_token_1 ─► verify(p, q) ─► reject  ─► resample from p', stop
draft_token_2 (unused)
```

The moment you hit a rejection, you stop — the corrected resample gives you one new token, and you start drafting again from that point.

## Patterns in Production

### Self-speculative decoding (Medusa, Lookahead)

The simplest deployment story doesn't require a second model. Google's [Medusa](https://github.com/FasterDecoding/medusa) adds several small "heads" to the target model — each one is a lightweight MLP that predicts a token K positions ahead. Because the heads share the backbone, the verification is essentially free: the target's hidden states already contain the information needed to score the proposals.

In practice, Medusa typically achieves 2.1–2.5x speedups on a single A100 with no draft model to manage. The trade-off is that the heads are trained for that specific target model and don't transfer.

Lookahead decoding, from [Sailov and Willett](https://arxiv.org/abs/2402.02057), takes a different approach: it generates several candidate continuations from the same prompt using different random seeds, then lets the target model pick which continuation is real. This is sometimes called "Jacobi decoding" and works surprisingly well on greedy tasks like code completion.

### Draft model pairs (vanilla speculative decoding)

The classical setup: a 7B model drafting for a 70B target, or a 1B model drafting for a 7B target. The pairing problem is real — the draft needs to be topologically similar to the target, otherwise the acceptance rate collapses.

A few practical rules from running this in production:

- **Pick a draft from the same family.** A Llama-3.1-8B drafts well for a Llama-3.1-70B. A Mistral-7B drafting for a Llama-70B is hit-or-miss.
- **Target an acceptance rate of 0.6–0.8.** Below 0.5, you're paying draft cost without enough accepted tokens to amortize. Above 0.85, you're probably using a draft that's too large.
- **Distill if needed.** If you don't have a natural pair, knowledge distillation from the target into a smaller architecture recovers most of the acceptance loss. The [EAGLE](https://arxiv.org/abs/2401.15077) line of work does this at the feature level rather than the logit level.

### Tree-structured drafting (SpecInfer, SpecDec)

A linear chain of K draft tokens gives you one chance to accept per cycle. Tree-structured drafting generates **multiple branches** at each position, giving the verifier K independent candidates per step. The cost is more verifier logits to compute, but the upside is dramatically higher acceptance rates on structured outputs like JSON or code.

[Snowflake's SpecInfer](https://arxiv.org/abs/2305.09781) and the Sequoia tree attention work from MIT show 3–4x speedups on JSON-schema-constrained generation, which is exactly the workload that defeats naive speculation because every prefix has to remain schema-valid.

## Architecture: Where the Savings Come From

The win isn't from faster compute — it's from amortizing the parts of generation that don't scale with token count. Here's a typical decode step profile for a 70B model on an H100:

| Step | Wall time | Scales with batch? |
|------|-----------|--------------------|
| Attention over KV cache | ~12 ms | Yes |
| MLP / linear projections | ~8 ms | Yes |
| Sampling + logit gather | ~3 ms | No |
| Kernel launch + sync | ~2 ms | No |

That last row is roughly **8% of every step** spent on overhead that doesn't grow with the number of tokens you produce. If you can produce 3 accepted tokens per target forward pass, you've turned 12+8+3+2 = 25 ms into (12+8+3*3+2) = 31 ms — but you're delivering 3 tokens instead of 1. Per-token latency drops from 25 ms to ~10 ms.

In [vLLM's speculative decoding implementation](https://blog.vllm.ai/2024/10/17/spec-decode.html), the overhead shows up even more starkly on smaller models. A 1B target model on a single GPU spends ~30% of its decode time on launch and sampling overhead — exactly the regime where speculation pays off the most.

## When It Doesn't Help

Speculative decoding isn't free, and there are workloads where it actively hurts:

- **Long-context prompts where the draft model is far weaker.** A small draft model has effectively zero conditioning on tokens 4K back. If your task requires long-range reasoning, the acceptance rate crashes once you move past the prefix.
- **Batch sizes > 4 with high target utilization.** When the target is already saturating its SMs, you don't have spare capacity for the draft. In that regime, the draft just steals throughput you were already using.
- **High-temperature sampling on very long outputs.** Higher temperature means more variance between draft and target. Acceptance rates drop sharply above T = 1.0, and the breakeven shifts toward larger drafts — which negates the cost benefit.
- **Strictly deterministic, structured outputs (JSON schema with greedy decoding).** Tree-structured drafting handles this; linear speculation doesn't, because a single rejected token halts the whole batch.

## Concrete Numbers

From a few recent production writeups:

- **Google, on TPU v5e with Medusa-2:** 2.18x mean speedup on a PaLM-2-S class model, measured end-to-end on a chat workload. Reported in the [Medusa-2 paper](https://arxiv.org/abs/2402.05931).
- **Anyscale, on A100 with vLLM + draft model:** 2.4x for code completion, 1.7x for general chat, 3.1x for translation. Variation comes from how predictable each workload's tokens are.
- **DeepMind, in the [SpecDec++ paper](https://arxiv.org/abs/2405.05247):** 4–5x on summarization tasks where the draft model is a distilled version of the target itself.

The rule of thumb across the literature: **expect 2–3x, plan for 1.5x, be pleasantly surprised at 4x.** Anything above 5x is either a heavily distilled draft pair or a workload with very predictable token sequences.

## How to Adopt It

If you're serving an open-weights model today, here's the shortest path to a measurable win:

1. **Start with a draft from the same family, 4–10x smaller.** Llama-3.1-8B → 70B, Qwen-2.5-1.5B → 7B, Mistral-7B → 22B.
2. **Measure acceptance rate on your actual traffic.** If it's below 0.5, the draft isn't aligned enough — try a distilled draft or a tree-structured variant.
3. **Use an engine that supports it natively.** [vLLM](https://docs.vllm.ai/en/latest/features/spec_decode.html), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM), [SGLang](https://github.com/sgl-project/sglang), and [llama.cpp](https://github.com/ggerganov/llama.cpp) all ship production-grade implementations.
4. **Watch memory.** The draft model needs its own KV cache and weights. On a single GPU, that can crowd out the target.
5. **A/B test, don't assume.** Speculation changes tail latency in non-obvious ways — the worst-case tail can actually get longer because of rejected cycles.

## Key Takeaways

- Speculative decoding produces the **exact same token distribution** as standard sampling — it's a pure latency optimization, not a quality one.
- The draft model's job is to make proposals; the target model's job is to verify them. The acceptance-rejection step is what preserves correctness.
- **2–3x is the realistic expectation** for well-aligned draft/target pairs on typical chat or code workloads. Up to 5x is possible with distilled drafts or tree-structured speculation.
- Tree-structured drafting is the right answer for structured outputs (JSON, code, tool calls). Linear drafting wins for open-ended prose.
- It's free if you already have a small model from the same family; otherwise the cost of training or distilling a draft needs to be weighed against the latency gain.
- Memory and tail latency are the gotchas, not throughput at the median.

## Further Reading

- [Fast Inference from Transformers via Speculative Decoding (Leviathan et al., 2022)](https://arxiv.org/abs/2211.17192) — the original paper that proved the acceptance-rejection rule preserves the output distribution.
- [Accelerating Large Language Model Decoding with Speculative Sampling (Chen et al., DeepMind, 2023)](https://arxiv.org/abs/2302.01318) — the parallel "speculative sampling" formulation that arrived the same month.
- [vLLM Speculative Decoding Blog Post](https://blog.vllm.ai/2024/10/17/spec-decode.html) — production implementation notes, including how rejection is handled in a batched serving engine.
- [Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads](https://github.com/FasterDecoding/medusa) — Google's head-based approach that needs no separate draft model.
- [EAGLE: Speculative Sampling Requires Rethinking Feature Uncertainty](https://arxiv.org/abs/2401.15077) — a state-of-the-art feature-level draft model that achieves very high acceptance rates.
- [TensorRT-LLM Speculative Decoding Documentation](https://github.com/NVIDIA/TensorRT-LLM/blob/main/docs/source/speculative_decoding.md) — the production reference for NVIDIA-optimized serving.