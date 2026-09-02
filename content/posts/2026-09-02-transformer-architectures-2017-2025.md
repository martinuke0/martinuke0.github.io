---
title: "Transformer Architectures: 2017 → 2025+"
date: "2026-09-02T21:18:28.901"
draft: false
tags: ["transformers", "deep-learning", "llm", "attention", "architecture"]
description: "An engineer's tour of transformer architectures from the original 2017 paper through 2025, covering attention variants, efficiency tricks, and the patterns shipping in production LLMs."
summary: "From 'Attention Is All You Need' to modern mixture-of-experts and state-space hybrids: how the transformer family has evolved and what working engineers should know about the variants in production today."
showToc: true
TocOpen: false
cover:
  image: ""
  alt: "Abstract visualization of attention heads connecting tokens across a sequence."
  caption: ""
  relative: false
---

> **TL;DR** — The original 2017 transformer was a clean encoder–decoder with scaled dot-product attention. Eight years later, the architecture has fragmented into a family of variants — grouped-query attention, rotary embeddings, mixture-of-experts, and state-space hybrids — each trading memory, throughput, and quality in different ways. Picking the right one today means understanding which subcomponent you're actually buying.

The [original transformer paper](https://arxiv.org/abs/1706.03762) by Vaswani et al. arrived in 2017 with a quietly radical claim: you don't need recurrence or convolution to model sequences. Attention is enough. Almost a decade later, every frontier language model — from the Llama series to Claude, from GPT-4 to open-source MoE models — still routes through some descendant of that paper. What has changed is everything around the attention block.

This post is a tour of that evolution, written for engineers who already know what a softmax is and want to understand which architectural choices matter when you're actually shipping or fine-tuning a model.

## The 2017 Baseline: What We Started With

The encoder–decoder transformer from [Vaswani et al.](https://arxiv.org/abs/1706.03762) had a few ingredients worth naming explicitly, because every later variant mutates one of them:

- **Scaled dot-product attention** with `softmax(QKᵀ / √d_k) V`, plus multi-head attention running `h` parallel projections.
- **Sinusoidal positional encodings** added to the input embeddings.
- **Post-norm residual blocks**: `LayerNorm(x + Sublayer(x))`.
- **Encoder–decoder separation**, with cross-attention bridging them.

That last point is the one most often forgotten. The 2017 transformer was designed for translation, and it had six encoder layers and six decoder layers. Modern decoder-only LLMs (GPT, Llama, Claude, Qwen) throw away the encoder and cross-attention entirely. The architecture didn't survive intact — it survived as a component library.

### Why decoder-only won

The encoder–decoder design made sense for sequence-to-sequence tasks with separate input and output modalities. But for autoregressive language modeling, a single stack of decoder layers is simpler to train and scales more cleanly with parameter count. The pivot is usually dated to GPT-2 and the T5 paper, and it's the dominant pattern in every major model released since 2020.

## Attention Variants: The Real Engineering Battleground

The most consequential changes to the transformer since 2017 have been inside the attention block itself. There are now four variables to think about: how you project queries and keys, how you share parameters across heads, how you mask for causal generation, and how you extend context length.

### Multi-Head vs. Multi-Query vs. Grouped-Query Attention

The original [multi-head attention](https://arxiv.org/abs/1706.03762) gives each of its `h` heads its own Q, K, and V projection. That is `3h` projection matrices per layer. The KV cache during inference therefore stores `h × (seq_len × d_head)` entries per layer.

[Multi-query attention](https://arxiv.org/abs/1911.02150) (MQA), introduced by Shazeer in 2019, shares K and V across all heads — only Q is per-head. That shrinks the KV cache by a factor of `h` and was a huge win for inference throughput, but it cost some quality.

[Grouped-query attention](GQA), used in Llama 2 and most subsequent Meta releases, splits the difference: `g` groups share K/V, with `h/g` heads per group. It's the practical compromise that has become standard — the [Llama 2 paper](https://arxiv.org/abs/2307.09288) showed GQA recovers most of MQA's speedup with negligible quality loss.

```text
Multi-head:    h separate (Q, K, V) projections
Multi-query:   1 shared (K, V), h separate Q
Grouped-query: g shared (K, V), h/g separate Q per group
```

If you are fine-tuning a model and care about inference cost, the GQA vs MHA choice in the base model is something you inherit and can't easily change. It's a permanent architectural tax.

### FlashAttention: rewriting the inner loop

Vanilla attention materializes the full `N × N` attention matrix in HBM. For long sequences, that's both memory-heavy and bandwidth-bound. [FlashAttention](https://arxiv.org/abs/2205.14135) and its successors (FlashAttention-2, FlashAttention-3) rewrite attention as a tiled computation, keeping intermediates in SRAM and never materializing the full matrix. The result is roughly 2–4× faster training on long sequences and a much smaller memory footprint — without changing the math.

This is the single most important systems optimization in the post-2020 transformer stack. When you see a model card claiming support for 100k+ context windows, FlashAttention is almost always load-bearing.

### Sliding window and dilated attention

For very long contexts, even FlashAttention hits a wall: the attention matrix is still `O(N²)` in compute. Two mitigation strategies have shipped in production:

- **[Mistral's sliding window attention](https://arxiv.org/abs/2310.06825)** restricts each token to attending only to a fixed window of recent tokens. Stacked layers give an effective receptive field of `layers × window_size`.
- **Dilated attention** (used in [Longformer](https://arxiv.org/abs/2004.05150) and various long-context variants) skips positions at increasing strides, similar to dilated convolutions.

Both are approximations. Whether the approximation matters depends on the task — sliding window is fine for chat but lossy for retrieval over a million-token document.

## Position Encodings: From Sinusoids to RoPE to ALiBi

Position information has to be injected somewhere, and how you do it shapes what the model can generalize over.

### Rotary Position Embeddings (RoPE)

[RoPE](https://arxiv.org/abs/2104.09864) rotates Q and K vectors by position-dependent angles before the dot product. The elegant property is that the dot product becomes a function of relative position only — the model sees "how far apart" tokens are, not their absolute index.

RoPE is now the default. It's in Llama, Mistral, Gemma, Qwen, and most open-source releases since 2023. The main extension you should know about is **RoPE scaling** for longer contexts: YaRN, NTK-aware scaling, and position interpolation all modify the base frequency spectrum to stretch the effective context window without retraining from scratch.

### ALiBi

[ALiBi](https://arxiv.org/abs/2108.12409) (Attention with Linear Biases) skips learned or sinusoidal positions entirely and just adds a linearly-decreasing bias to attention scores based on distance. It's brutally simple, trains without position embeddings, and extrapolates to longer sequences more gracefully than naive absolute encodings. Some models (the BLOOM family) used it, but RoPE has since won the ecosystem.

### No position encoding at all

Several recent architectures — most notably [Mamba](https://arxiv.org/abs/2312.00752) and the state-space family — don't use positional encodings because their recurrence already encodes order. More on hybrids below.

## Normalization, Residual Streams, and Pre-Norm

The 2017 paper used **post-norm** (`LayerNorm(x + Sublayer(x))`), but every modern LLM I know of uses **pre-norm** (`x + Sublayer(LayerNorm(x))`). Pre-norm is more stable for deep stacks — gradients flow through the residual stream unobstructed — at a modest cost in final-layer representation quality.

Two refinements have appeared:

- **RMSNorm** instead of LayerNorm, dropping the mean-centering step. Used in Llama. Marginal speedup, identical behavior in practice.
- **DeepNorm**, which scales the residual contribution by `α` and the sublayer output by `β`. Used in the original [BLOOM](https://arxiv.org/abs/2211.05100) and some other large models to stabilize thousand-layer training.

These look like small changes, but in deep models they're the difference between a training run that diverges at step 2000 and one that converges.

## Mixture of Experts: Sparse Routing at Scale

The transformer block assumes every token flows through the same parameters. **[Mixture of Experts](https://arxiv.org/abs/2101.03961)** (MoE) breaks that: each token activates only `k` of `N` expert FFNs, chosen by a learned router. The model's total parameter count explodes, but compute per token stays roughly constant.

This is the pattern behind most frontier-scale models now — Mixtral 8x7B, DeepSeek-V3, and reported configurations of GPT-4. A few engineering realities:

- **Routing is load-imbalanced.** Some experts get all the tokens. The standard fix is an auxiliary loss penalizing imbalance, plus capacity factors per expert.
- **Fine-tuning MoEs is harder.** All experts need gradient signal, and routing collapse (everyone sends tokens to expert 1) is a recurring failure mode.
- **Inference serving is non-trivial.** You need to keep all experts in memory but only compute on `k` per token, which means expert parallelism across GPUs — typically with [tensor-parallel](https://arxiv.org/abs/2209.05433) layouts that keep each expert on a single device.

If you're fine-tuning a 7B dense model today, you may not encounter MoE directly. But if you're serving frontier-scale models via an API, you're almost certainly hitting an MoE under the hood, and the latency profile reflects expert dispatch.

## State-Space Hybrids and the 2024+ Frontier

Pure transformers have an `O(N²)` attention problem. State-space models (SSMs) like [Mamba](https://arxiv.org/abs/2312.00752) and [Mamba-2](https://arxiv.org/abs/2405.21060) replace attention with a structured recurrent layer that is `O(N)` in compute and constant in state. They scale much better on long sequences.

The honest 2025 assessment: pure SSMs don't yet match the best transformers on hard reasoning and in-context learning, but they're very competitive on throughput-sensitive workloads (code completion, streaming generation, long-document summarization). The practical response has been **hybrid models** that interleave transformer and SSM blocks:

- **Jamba** (AI21): interleaves Mamba and transformer attention blocks at a 7:1 ratio.
- **Zamba**: similar hybrid pattern at smaller scale.
- Several 2024–2025 frontier models reportedly use attention only on a subset of layers.

This is the frontier right now. The question is not "transformer or SSM" but "which layers need quadratic attention and which can be linear." The answer depends on the workload, and the architecture is being tuned accordingly.

## Patterns in Production: What You're Actually Inheriting

When you download a pretrained checkpoint from HuggingFace — Llama-3.1, Qwen2.5, Mistral-Large, Gemma 2 — you are inheriting a specific bundle of architectural choices. A reasonable checklist when evaluating or fine-tuning:

| Choice | Typical 2024+ default | Why it matters |
|---|---|---|
| Attention type | GQA | Inference KV cache size |
| Position encoding | RoPE | Context length, extrapolation |
| Normalization | RMSNorm, pre-norm | Training stability |
| Attention backend | FlashAttention-2/3 | Long-context feasibility |
| FFN activation | SwiGLU | Quality vs GELU |
| Sparsity | Dense or MoE | Compute vs parameter count |

Almost all of these are baked into the weights. You can't switch MQA → MHA without retraining, and you can't turn off routing in an MoE without a catastrophic quality drop. The exception is the attention backend: you can run a model with FlashAttention, vanilla attention, or a custom kernel without changing the weights.

### The SwiGLU note

The 2017 transformer used ReLU in the FFN. Almost every modern model uses a gated activation, typically **SwiGLU** (`Swish(W₁x) ⊙ W₃x`), which has three projections instead of two. The [Noam Shazeer paper](https://arxiv.org/abs/2002.05202) showed this consistently outperforms plain ReLU FFNs at the same parameter count. It's a small thing, but if you're training from scratch it's a free lunch.

## Key Takeaways

- The 2017 transformer survived as a component library, not a monolithic architecture. Decoder-only stacks, GQA, RoPE, RMSNorm, and SwiGLU have all become defaults.
- **Attention is the variable part.** Grouped-query attention, sliding window, and FlashAttention are the three knobs that most affect inference cost and long-context behavior.
- **Position encoding is mostly RoPE now**, with scaling schemes (YaRN, NTK-aware) for context extension. ALiBi is the main alternative.
- **Pre-norm + RMSNorm** is standard. Post-norm is essentially historical.
- **Mixture of Experts** is how frontier-scale models decouple parameter count from per-token compute, at the cost of routing complexity.
- **Hybrid SSM/attention models** are the 2024+ frontier for long-context workloads, not a replacement for transformers yet.
- Most architectural choices are frozen in pretrained weights. Before fine-tuning, know which ones you've inherited.

## Further Reading

- [Attention Is All You Need — Vaswani et al., 2017](https://arxiv.org/abs/1706.03762)
- [FlashAttention — Dao et al., 2022](https://arxiv.org/abs/2205.14135)
- [GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints (used in Llama 2)](https://arxiv.org/abs/2307.09288)
- [RoFormer / RoPE — Su et al., 2021](https://arxiv.org/abs/2104.09864)
- [Mamba — Gu & Dao, 2023](https://arxiv.org/abs/2312.00752)
- [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538)
- [Mistral 7B paper — sliding window attention and GQA details](https://arxiv.org/abs/2310.06825)