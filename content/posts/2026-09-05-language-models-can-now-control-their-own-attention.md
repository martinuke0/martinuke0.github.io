---
title: "Language Models Can Now Control Their Own Attention"
date: "2026-09-05T19:00:40.049"
draft: false
tags: ["llm", "attention", "transformers", "mechanistic-interpretability", "inference"]
description: "A practical look at attention output gating, sparse attention, and self-reflective decoding, with production tradeoffs and code."
summary: "New techniques let language models decide for themselves where to attend, cutting inference cost without retraining. We break down how gating, sparse kernels, and self-reflective decoding work in production systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-language-models-can-now-control-their-own-attention.svg"
  alt: "Abstract visualization of attention weights flowing through a transformer."
  caption: ""
  relative: false
---

> **TL;DR** — A new class of techniques lets language models gate and route their own attention, deciding which tokens matter before the quadratic cost is paid. Attention output gating, learned top-k routing, and self-reflective decoding can cut inference FLOPs by 30–60% on long-context workloads without degrading quality, and they are quietly landing in serving stacks like vLLM, TensorRT-LLM, and llama.cpp.

For years, the transformer architecture has been a polite guest in someone else's house: it attends everywhere, all the time, and pays for every pairwise interaction. That changed in the last 18 months. A handful of techniques — gathered under the loose banner of **attention output gating** — let the model itself decide which attention outputs to keep, route, or throw away. The result is not a new architecture but a new degree of freedom: the model gets to be a little cheap about where it looks.

This post walks through how that control actually works, what it costs, where it is already shipping, and what to watch out for if you try it on your own stack.

## Why "Attention Everywhere" Was Always the Wrong Default

The original transformer treats every token as a potential conversation partner with every other token. For a 4k context that is 16 million attention scores per layer. For a 128k context it is over a billion. Most of those scores are noise: a stopword in the system prompt does not need to talk to the last token of a 30-page PDF.

Engineers have known this for a while. The historical fixes were external:

- **Sliding window attention** ([Mistral's approach](https://mistral.ai/news/announcing-mistral-7b/)) caps each token's view to the last N tokens.
- **Global + local hybrid attention** ([Longformer's design](https://arxiv.org/abs/2004.05150)) marks a few tokens as global and lets everyone see them.
- **Multi-Query / Grouped-Query Attention** ([GQA paper](https://arxiv.org/abs/2305.13245)) shares key/value heads across query heads.

All of these are *static* — the schedule is decided at design time, not by the model. Attention output gating is different. The model looks at the query, looks at the keys, and decides in real time which outputs are worth keeping.

## Three Patterns That Actually Ship

There is no single "self-controlled attention" technique. There is a family of related ideas. The three patterns that matter for production work today are attention output gating, learned top-k routing, and self-reflective decoding.

### Attention Output Gating

The simplest idea: keep the standard multi-head attention block, but multiply its output by a learned per-head gate before the residual stream. The gate is a small linear projection that reads the query, the previous layer's hidden state, or both, and emits a scalar per head.

Mechanically, each attention head now produces:

```
output = sigmoid(gate) * attn_output
```

Where `gate` is computed from a cheap projection of the input. If the gate is near zero, the head's contribution is suppressed. Because the projection is small (one linear layer per head, or shared), the overhead is trivial — usually under 2% of the attention FLOPs.

The interesting thing is what the model learns to do with it. Empirically, gating-trained models:

- Suppress heads during filler or repeated phrases.
- Boost heads during transitions between semantic sections.
- Route "thinking" heads differently from "retrieval" heads depending on the prompt.

A clean reference implementation looks like this:

```python
import torch
import torch.nn.functional as F

class GatedMultiHeadAttention(torch.nn.Module):
    def __init__(self, d_model, n_heads, gate_input="q"):
        super().__init__()
        self.n_heads = n_heads
        self.qkv = torch.nn.Linear(d_model, 3 * d_model, bias=False)
        self.out = torch.nn.Linear(d_model, d_model, bias=False)
        # Gate projector: from per-head query to a per-head scalar
        self.gate_proj = torch.nn.Linear(d_model, n_heads, bias=True)

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = self.qkv(x).chunk(3, dim=-1)
        H = self.n_heads
        q = q.view(B, T, H, -1).transpose(1, 2)  # [B, H, T, Dh]
        k = k.view(B, T, H, -1).transpose(1, 2)
        v = v.view(B, T, H, -1).transpose(1, 2)

        attn = F.scaled_dot_product_attention(q, k, v)  # [B, H, T, Dh]

        # Compute per-head gate from the query
        gate_in = q.mean(dim=2)                         # [B, H, Dh]
        gate = torch.sigmoid(self.gate_proj(gate_in))   # [B, H]

        # Broadcast and apply
        attn = attn * gate.unsqueeze(-1).unsqueeze(-1)

        attn = attn.transpose(1, 2).contiguous().view(B, T, D)
        return self.out(attn)
```

The catch: naive sigmoid gating is *soft*. It rarely makes a head exactly zero, so it does not save FLOPs — only quality. To save FLOPs, you pair gating with the next pattern.

### Learned Top-k Routing

This is where the cost savings live. Instead of computing all N×N attention scores and then gating, you compute a small candidate set *first* and only run full attention against those candidates.

The mechanism is roughly:

1. Project each query into a low-dimensional "router" space (a vector of 32–128 dims).
2. Project each key into the same space.
3. For each query, pick the top-k keys by router score (k ≈ 64–256 for an 8k context).
4. Run full attention only against those k keys.

This is the design behind [Routing Transformers](https://arxiv.org/abs/2003.05997) and the more recent [MoA (Mixture of Attention) paper](https://arxiv.org/abs/2402.08562), and it is closely related to the cluster-attention work in [Scatterbrain](https://arxiv.org/abs/2310.18065). The "learned" part is critical: the router weights are trained end-to-end with the rest of the model, so the model learns which tokens are likely candidates for attention before paying for them.

In production terms, this is what unlocks the cost reduction:

| Pattern | Compute (8k ctx) | Quality vs. dense | Where it ships |
| --- | --- | --- | --- |
| Dense MHA | O(N²) | 1.00 | Reference |
| Sliding window | O(N·W) | 0.93–0.96 | Mistral, Phi-3 |
| GQA only | O(N²·Hkv) | 1.00 | Llama-2/3 |
| **Top-k routing** | O(N·k) | 0.97–0.99 | vLLM experimental, some internal stacks |
| **Soft gating (no FLOP savings)** | O(N²) | 1.01 | Easy to add to any HF model |

A representative top-k router looks like:

```python
class TopKRouterAttention(torch.nn.Module):
    def __init__(self, d_model, n_heads, router_dim=64, top_k=128):
        super().__init__()
        self.top_k = top_k
        self.qkv = torch.nn.Linear(d_model, 3 * d_model, bias=False)
        self.out = torch.nn.Linear(d_model, d_model, bias=False)
        self.q_router = torch.nn.Linear(d_model, router_dim, bias=False)
        self.k_router = torch.nn.Linear(d_model, router_dim, bias=False)

    def forward(self, x):
        B, T, D = x.shape
        q, k, v = self.qkv(x).chunk(3, dim=-1)
        # Routers are per-head; here we simplify to one shared router
        q_r = self.q_router(x)  # [B, T, R]
        k_r = self.k_router(x)  # [B, T, R]

        # Score every (query, key) pair in router space
        router_logits = q_r @ k_r.transpose(-2, -1)  # [B, T, T]
        # Pick top-k keys per query
        topk = router_logits.topk(self.top_k, dim=-1).indices  # [B, T, k]

        # Now gather only those keys/values and run full attention
        # (gather + SDPA is left as an exercise; PyTorch >=2.3
        # supports block-diagonal masks that approximate this efficiently)
        # ...
        return self.out(attn)
```

The hard part is not the model. It is the kernel. On an H100 you can write a custom CUDA extension that does the gather + SDPA in one pass; on a CPU or a phone you typically use a sparse kernel from [xFormers](https://github.com/facebookresearch/xformers) or [FlashAttention's block-sparse mode](https://github.com/Dao-AILab/flash-attention).

### Self-Reflective Decoding

The third pattern is the most unusual. Instead of changing the attention block, you let the model *talk to itself* about what to attend to before generating a token. The technique, popularized by [Self-RAG](https://arxiv.org/abs/2310.11511) and extended in [REST](https://arxiv.org/abs/2311.08240), works like this:

1. Insert special reflection tokens into the prompt: `<retrieve>`, `<isrel>`, `<issup>`.
2. The model emits these tokens during generation, and they control behavior:
   - `<retrieve>` triggers a vector-DB lookup and injects new context.
   - `<isrel>` asks the model to score whether the retrieved context is relevant.
   - `<issup>` asks whether the proposed answer is supported by the context.
3. The scores gate whether the generated token is accepted.

This is not attention output gating in the strict sense — it operates at the *decoding* layer, not inside the transformer block. But the effect is similar: the model chooses to attend (via retrieval) only when it judges a question to be knowledge-heavy, and skips the cost otherwise.

In retrieval-heavy pipelines this can reduce RAG calls by 40–70% with no quality loss, as reported in [the Self-RAG paper](https://arxiv.org/abs/2310.11511) and replicated in several LangChain and LlamaIndex tutorials.

## Patterns in Production: Where the Wins Land

Let me anchor this in three real systems rather than abstractions.

### Long-context code completion (Cursor, Copilot-style)

A code completion engine streams a long file context — often 16k–64k tokens. Most of that context is irrelevant to the next completion. A top-k router with `k=128` against a 16k window cuts attention compute by roughly 99%, and because the router is trained on code, it learns to favor syntactically and semantically nearby tokens (function definitions, recent edits, the cursor's enclosing scope).

### Retrieval-augmented chatbots with cached corpora

A chatbot with a 200-document KB does not need to attend to all 200 documents on every turn. Self-reflective decoding with a `<retrieve>` gate lets the model skip retrieval when the question is chitchat ("thanks!") and fire it only when the question is knowledge-seeking ("what's our SLA for tier-3 customers?"). At a 200-document scale this saves both retrieval cost and context-window cost.

### Multi-tenant serving on a single GPU

When you serve many small requests on one GPU, the bottleneck is KV-cache memory, not compute. Attention output gating does not help here directly — but the *information* the gate produces (which heads are useful on this prompt) can be used to decide whether to use a smaller model variant or skip layers. Several serving stacks now expose `head_pruning` hints derived from gated attention, as discussed in [TensorRT-LLM's layer skipping docs](https://nvidia.github.io/TensorRT-LLM/).

## The Tradeoffs Nobody Puts in the README

These techniques are real, but they are not free.

**Training cost.** Top-k routers and gates must be learned during pretraining or fine-tuning. You cannot bolt them onto a finished Llama-3 checkpoint without retraining. Gating alone can be added cheaply (fine-tune a gate linear, freeze the rest), but routing changes the attention pattern and needs full retraining to converge.

**Kernel support.** Sparse attention is fast on a 2024-vintage H100; it is slow or unavailable on older GPUs, TPUs, and most CPUs. vLLM added experimental block-sparse kernels in late 2024; llama.cpp added a [similar feature](https://github.com/ggerganov/llama.cpp) for ARM in 2025. Before deploying, benchmark your actual hardware.

**Quality cliffs at small k.** Top-k routing has a sharp knee. On retrieval-style tasks, k=128 against 8k context gives 99% of dense quality. On reasoning-heavy tasks (math, code with long dependencies), you may need k=512 or 1024, which collapses most of the savings.

**Evaluation rigor.** It is easy to make a model look better by gating away the things it was bad at. The mechanism papers like [Mixture of Attention Heads](https://arxiv.org/abs/2210.07644) show that naive gating can degrade chain-of-thought reasoning on MMLU by 2–4 points. Always evaluate on a hard benchmark — GSM8K, MATH, HumanEval, MT-Bench — not just perplexity.

**Determinism.** Gated models with stochastic routers break bitwise reproducibility. For regulated workloads (medical, legal) this is a non-starter unless the router is made deterministic via temperature-0 sampling.

## How to Try It on Your Own Stack

If you want to experiment, the lowest-friction path is:

1. **Start with soft gating.** Take any HuggingFace causal LM, add a `GatedMultiHeadAttention` layer wrapper, and fine-tune for a few hundred steps on a domain corpus. This costs almost nothing and teaches you whether gating is even useful for your workload. The [Mechanistic Interpretability team's notebook](https://github.com/neelnanda-io/TransformerLens) has a clean reference.

2. **Add a router to a small model.** Fine-tune a 1B–3B parameter model from scratch (or from a public checkpoint with the schedule changed) using top-k routing. Train on the same data distribution you care about — routing is sensitive to data.

3. **Self-reflective decoding is plug-and-play.** No retraining needed. Wrap your existing model with the reflection-token logic from the [Self-RAG repo](https://github.com/AkariAsai/self-rag) and instrument the gating tokens.

4. **Measure on your real prompts.** Use [LongBench](https://github.com/THUDM/LongBench) or [RULER](https://github.com/NVIDIA/RULER) for long-context evaluation, and a domain-specific eval for everything else. Public benchmarks are not enough.

## Key Takeaways

- Attention output gating, learned top-k routing, and self-reflective decoding are three distinct techniques that share a theme: the model chooses where its attention budget goes.
- Soft gating is a quality lever with no FLOP savings; top-k routing is the lever that actually cuts cost; self-reflective decoding is the lever for retrieval-heavy RAG pipelines.
- Production savings of 30–60% on long-context workloads are realistic, but only with kernel support and proper evaluation.
- These techniques require either pretraining changes or fine-tuning — there is no free lunch bolt-on for finished checkpoints.
- The hard part is not the model code; it is the sparse kernel, the router training schedule, and the eval discipline.

## Further Reading

- [Attention Is All You Need — the original transformer paper](https://arxiv.org/abs/1706.03762)
- [Routing Transformers: Sparse Attention via Cluster Routing](https://arxiv.org/abs/2003.05997)
- [Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection](https://arxiv.org/abs/2310.11511)
- [FlashAttention block-sparse kernels](https://github.com/Dao-AILab/flash-attention)
- [TensorRT-LLM documentation](https://nvidia.github.io/TensorRT-LLM/)
- [Mechanistic Interpretability in TransformerLens](https://github.com/neelnanda-io/TransformerLens)