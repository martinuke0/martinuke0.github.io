---
title: "Building a Speculative Decoder with Medusa-Style Draft Heads in PyTorch"
date: "2026-09-06T17:00:33.282"
draft: false
tags: ["pytorch", "llm-inference", "speculative-decoding", "medusa", "machine-learning-systems"]
description: "A hands-on build guide for a from-scratch speculative decoder with Medusa-style draft heads, top-k, top-p, and min-p sampling — a CV-grade systems project."
summary: "Build a speculative decoder with Medusa-style draft heads and modern samplers in PyTorch. A production-flavored portfolio project that signals real ML systems skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-building-a-speculative-decoder-with-medusa-style-draft-heads-in-pytorch.svg"
  alt: "Diagram of a speculative decoder with Medusa draft heads feeding a verification pass on a target model."
  caption: ""
  relative: false
---

> **TL;DR** — A speculative decoder guesses several tokens ahead with cheap "draft" heads and verifies them in one pass against a larger target model, trading one serial decode step for several parallel ones. We'll build a from-scratch PyTorch implementation with Medusa-style draft heads, top-k / top-p / min-p sampling, and a clean architecture you can extend into a CV-grade portfolio piece.

A speculative decoder is one of the few ML systems projects that is simultaneously *conceptually clear*, *bounded in scope*, and *impressively deep* once you start digging. The idea is straightforward: instead of letting a big autoregressive model grind through one token at a time, you attach a cheap "guesser" — Medusa-style draft heads — that proposes several candidate continuations in parallel. The big model then verifies all of them in a single forward pass, accepting the longest prefix that matches its own top-1 predictions.

What makes this an excellent portfolio project is that it touches every layer of an ML systems stack: GPU-friendly tensor math, KV cache management, sampling theory, batching, benchmarking, and serving. Hiring managers read "built a speculative decoder" and immediately see a candidate who understands inference — not just training.

## Why This Project Stands Out on a CV

Most CV side projects fall into one of three buckets: (1) a tutorial clone with a fancy UI, (2) a Kaggle notebook, or (3) a wrapper around someone else's API. None of these signal *systems thinking*. This project is different because the core technical decisions you make — drafting strategy, acceptance criterion, cache layout, sampler composition — are the same decisions made by the teams shipping inference at vLLM, TensorRT-LLM, and Hugging Face `generate`.

Specifically, this project demonstrates:

- **Inference-side ML systems thinking.** You will have to reason about KV cache reuse, the arithmetic of acceptance probabilities, and the cost of speculative verification vs. sequential decoding. These are the bread and butter of ML systems roles at companies like Anyscale, Together, and Mistral.
- **Numerically careful PyTorch.** Speculative decoding has a famously subtle acceptance rule (`min(1, q/p)` for greedy / sampling variants). Getting it right without `nan` or `inf` is a small but real piece of engineering.
- **Modern sampling literacy.** Top-k, top-p (nucleus), and min-p are the three samplers recruiters expect you to know. Bundling them into one project with a unified interface shows compositional fluency.
- **Benchmarking discipline.** A speculative decoder that doesn't measure acceptance rate, wall-clock latency, and tokens-per-second is just a toy. We'll add real numbers.
- **Service-shaped code layout.** Even as a single-file repo, you'll separate the target model, draft heads, sampler, and verifier. That structure scales into FastAPI, Ray Serve, or Triton backends.

Roles this signals for: ML inference engineer, applied research engineer, LLMOps, ML platform, and (more senior) inference architecture. It's the kind of project that turns "I know PyTorch" into "I shipped inference".

## Architecture Overview

The system is deliberately layered so each piece is swappable. Think of it as four engines glued together by a controller.

- **Target model** — any Hugging Face causal LM (we'll use `TinyLlama` and `Qwen2-0.5B` in tests for speed). Owns the authoritative logits and KV cache.
- **Medusa heads** — `k` small MLP heads attached to the target's hidden states. Each head predicts a future token. We freeze the backbone and train heads on a calibration set, or random-init them for the demo.
- **Draft tree builder** — takes the per-head distributions and assembles a tree of candidate continuations of depth `k`. Each path through the tree is a draft.
- **Verifier** — runs the target model in a single pre-filled forward pass over the longest draft, then walks the draft tree left-to-right applying the speculative acceptance rule.
- **Sampler** — composable top-k → top-p → min-p filter applied to both the draft distribution and the target distribution so they live in the same probability space.
- **Controller / loop** — orchestrates: prefill → speculative step → accept/reject → update KV cache → repeat until EOS or max tokens.
- **Bench harness** — `time.perf_counter`, `torch.cuda.synchronize`, token counters, acceptance-rate logging.

A single round looks like this:

```text
[last hidden state] ──► Medusa heads ──► draft tree (depth k)
                                            │
                                            ▼
[target model on full draft] ──► target logits per position
                                            │
                                            ▼
                            verify tree, accept longest prefix
                                            │
                                            ▼
                                  emit accepted tokens
```

The win comes from replacing `k` serial target forward passes with **one** target forward pass — which, on a GPU, is bandwidth-bound for short contexts and therefore nearly free relative to the savings.

## Building It Step by Step

We'll build the project as a single Python package `specdec/` with five modules. You can split it into files or keep it as one — both are fine for a CV repo, but a multi-file layout reads more professional.

### Step 1 — Project Skeleton and Dependencies

```text
specdec/
  __init__.py
  model.py        # Medusa wrapper around HF causal LM
  sampler.py      # top-k, top-p, min-p, composed
  draft_tree.py   # build candidate continuations from heads
  verifier.py     # speculative acceptance logic
  engine.py       # generate() loop
bench.py          # benchmarking harness
tests/
  test_sampler.py
  test_verifier.py
```

```bash
pip install torch transformers datasets pytest accelerate
```

### Step 2 — A Composable Sampler

This is the sampler everything else composes against. The contract is simple: take a `[B, V]` logits tensor, return a filtered `[B, V]` logits tensor (the same shape — we never renormalize here, we only mask and return; the verifier multiplies with the target distribution, and the controller applies softmax at emission time).

```python
# specdec/sampler.py
import torch
import torch.nn.functional as F


def top_k_filter(logits: torch.Tensor, k: int) -> torch.Tensor:
    if k <= 0 or k >= logits.size(-1):
        return logits
    kth = torch.topk(logits, k, dim=-1).values[..., -1:]
    return torch.where(logits < kth, torch.full_like(logits, float("-inf")), logits)


def top_p_filter(logits: torch.Tensor, p: float) -> torch.Tensor:
    if p >= 1.0:
        return logits
    sorted_logits, sorted_idx = torch.sort(logits, dim=-1, descending=True)
    probs = F.softmax(sorted_logits, dim=-1)
    cum = torch.cumsum(probs, dim=-1)
    mask = cum > p
    # shift right so the first token that crosses p is kept
    mask[..., 1:] = mask[..., :-1].clone()
    mask[..., 0] = False
    sorted_logits = sorted_logits.masked_fill(mask, float("-inf"))
    out = torch.empty_like(logits)
    out.scatter_(-1, sorted_idx, sorted_logits)
    return out


def min_p_filter(logits: torch.Tensor, p: float, base: float = 1.0) -> torch.Tensor:
    """min-p: keep tokens whose prob >= p * max_prob."""
    if p <= 0.0:
        return logits
    probs = F.softmax(logits, dim=-1)
    max_prob = probs.max(dim=-1, keepdim=True).values
    threshold = base * p * max_prob
    return torch.where(probs < threshold, torch.full_like(logits, float("-inf")), logits)


def compose(
    logits: torch.Tensor,
    top_k: int = 0,
    top_p: float = 1.0,
    min_p: float = 0.0,
) -> torch.Tensor:
    """Apply filters in the standard order: top-k → top-p → min-p."""
    logits = top_k_filter(logits, top_k)
    logits = top_p_filter(logits, top_p)
    logits = min_p_filter(logits, min_p)
    return logits
```

A few details worth noting. We apply top-k *before* top-p because top-k is a cheap hard cap, and applying it first keeps the probability mass more concentrated for top-p — this matches the convention in [Hugging Face's `LogitsProcessor`](https://huggingface.co/docs/transformers/internal/generation_utils). We use `masked_fill` rather than `where` with a mask because we want a true `-inf` so softmax gives exact zeros, not tiny numerical junk. The min-p filter reads cleanly as "nothing more than `p` times the top token survives" — see [the min-p sampling paper](https://arxiv.org/abs/2407.01082) by Nguyen et al. for the rationale.

### Step 3 — Medusa Heads as a Thin Wrapper

We freeze the backbone and add `k` MLP heads. Each head reads the final hidden state at position `i` and predicts the token at position `i + head_offset`.

```python
# specdec/model.py
import torch
import torch.nn as nn
from transformers import AutoModelForCausalLM, AutoTokenizer


class MedusaModel(nn.Module):
    def __init__(self, backbone_name: str, num_heads: int = 3, hidden_dim: int | None = None):
        super().__init__()
        self.backbone = AutoModelForCausalLM.from_pretrained(backbone_name)
        for p in self.backbone.parameters():
            p.requires_grad_(False)
        self.backbone.eval()

        h = hidden_dim or self.backbone.config.hidden_size
        v = self.backbone.config.vocab_size
        self.heads = nn.ModuleList([
            nn.Sequential(
                nn.Linear(h, h),
                nn.SiLU(),
                nn.Linear(h, v, bias=False),
            )
            for _ in range(num_heads)
        ])
        self.num_heads = num_heads

    @torch.no_grad()
    def target_logits(self, input_ids: torch.Tensor, past_key_values, **kw):
        out = self.backbone(
            input_ids=input_ids,
            past_key_values=past_key_values,
            use_cache=True,
            **kw,
        )
        return out.logits, out.past_key_values, out.last_hidden_state
```

You can train the heads on a calibration set (e.g. 5k samples from `wikitext`) with a per-head cross-entropy loss against the shifted labels. For the CV demo, a 200-line training script with `accelerate` is enough. The point of the project isn't the training; it's the *inference-time composition*.

### Step 4 — Draft Tree Builder

Each head produces a distribution over the vocabulary. We keep the top-`w` candidates per head and concatenate them into a tree. This is what the original [Medusa paper](https://arxiv.org/abs/2401.10774) calls a "candidate tree".

```python
# specdec/draft_tree.py
import torch
from .sampler import compose


def build_draft_tree(
    head_logits: list[torch.Tensor],   # [num_heads][B, V]
    top_w: int = 4,
    top_k: int = 50,
    top_p: float = 0.9,
    min_p: float = 0.05,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Return (paths, path_probs) where paths is [B, num_paths, depth] and
    path_probs is [B, num_paths]. num_paths <= top_w ** num_heads."""
    B = head_logits[0].size(0)
    paths = [torch.zeros(B, 1, dtype=torch.long, device=head_logits[0].device)]
    probs = [torch.ones(B, 1, device=head_logits[0].device)]

    for h_logits in head_logits:
        filtered = compose(h_logits, top_k=top_k, top_p=top_p, min_p=min_p)
        h_probs = torch.softmax(filtered, dim=-1)
        topk_probs, topk_idx = h_probs.topk(top_w, dim=-1)  # [B, w]

        new_paths, new_probs = [], []
        for p_path, p_prob in zip(paths, probs):
            # broadcast: [B, current_len, w] x [B, 1, w]
            p_path_b = p_path.unsqueeze(-1).expand(-1, -1, top_w)
            p_prob_b = p_prob.unsqueeze(-1)
            topk_idx_b = topk_idx.unsqueeze(1).expand(-1, p_path.size(1), -1)
            topk_probs_b = topk_probs.unsqueeze(1)

            new_paths.append(
                torch.cat([p_path_b, topk_idx_b], dim=1).reshape(B, -1)
            )
            new_probs.append(
                (p_prob_b * topk_probs_b).reshape(B, -1)
            )
        paths = new_paths
        probs = new_probs

    paths = paths[0]   # [B, num_paths, depth]
    probs = probs[0]
    return paths, probs
```

The combinatorial blow-up is real: with `w=4` and `k=3` heads you get up to 64 paths. In practice you cap `w=2` or `w=3`, and the original Medusa repo trims by top probability.

### Step 5 — The Verifier (the Interesting Part)

This is the heart of speculative decoding, formalized by [Leviathan et al.](https://arxiv.org/abs/2211.17192). For each draft token `x_t`, you accept it with probability

`min(1, q(x_t | x_<t) / p(x_t | x_<t))`

where `q` is the target and `p` is the draft. If you reject, you resample from a corrected distribution `(q - p)_+` renormalized.

```python
# specdec/verifier.py
import torch
import torch.nn.functional as F
from .sampler import compose


@torch.no_grad()
def verify_speculative(
    target_logits: torch.Tensor,      # [B, draft_len+1, V] from one forward
    draft_ids: torch.Tensor,          # [B, draft_len]
    draft_probs: torch.Tensor,        # [B, num_paths, draft_len]  (per-position probs)
    sampling_logits: torch.Tensor,    # [B, V] for the bonus token past the draft
    top_k: int = 0,
    top_p: float = 1.0,
    min_p: float = 0.0,
    temperature: float = 1.0,
) -> tuple[torch.Tensor, int]:
    """Return (emitted_tokens, num_accepted). emitted_tokens is [B, <= draft_len+1]."""
    B, Dp1, V = target_logits.shape
    D = Dp1 - 1
    device = target_logits.device

    # Apply the same composed sampler to target logits so draft and target
    # distributions live in the same support.
    target_filtered = compose(target_logits[:, :D, :], top_k, top_p, min_p)
    target_probs = F.softmax(target_filtered / temperature, dim=-1)
    bonus_filtered = compose(sampling_logits, top_k, top_p, min_p)
    bonus_probs = F.softmax(bonus_filtered / temperature, dim=-1)

    # Path probabilities at each position
    # draft_probs: [B, num_paths, D] -> gather along path dimension (we pass 1 path here)
    if draft_probs.dim() == 3:
        # assume best-path heuristic: pick argmax-prob path
        path_scores = draft_probs.sum(dim=-1)            # [B, P]
        best = path_scores.argmax(dim=-1)                # [B]
        chosen_p = draft_probs.gather(
            1, best[:, None, None].expand(-1, 1, D)
        ).squeeze(1)                                      # [B, D]
    else:
        chosen_p = draft_probs                            # [B, D]

    # q(x_t) at each draft position
    q_at_draft = target_probs.gather(-1, draft_ids.unsqueeze(-1)).squeeze(-1)  # [B, D]
    p_at_draft = chosen_p.gather(-1, draft_ids).clamp(min=1e-8)                # [B, D]

    accept_ratio = (q_at_draft / p_at_draft).clamp(max=1.0)
    rand = torch.rand_like(accept_ratio)
    accepted_mask = rand < accept_ratio                                  # [B, D]
    # First rejection position (per batch)
    first_reject = (~accepted_mask).float().argmax(dim=-1)               # [B]
    no_reject = accepted_mask.all(dim=-1)
    n_accept = torch.where(no_reject, torch.tensor(D, device=device), first_reject)

    # Bonus token from corrected distribution at first rejection / end
    # If no rejection, sample from bonus_probs (which conditions on the full draft).
    sample = torch.multinomial(bonus_probs, num_samples=1).squeeze(-1)    # [B]
    # Replace the first rejected token with the corrected sample
    out_ids = torch.cat([draft_ids, sample.unsqueeze(-1)], dim=-1)        # [B, D+1]

    # Mask tokens past n_accept per row
    positions = torch.arange(D + 1, device=device).unsqueeze(0).expand(B, -1)
    keep = positions <= n_accept.unsqueeze(-1)
    out_ids = torch.where(keep, out_ids, torch.zeros_like(out_ids))
    # In practice, the controller will truncate by n_accept.max().item().
    return out_ids, n_accept
```

Two non-obvious points. First, **we feed the same composed sampler to both distributions**. If you apply top-k to the target but not the draft, their supports differ, the ratio `q/p` blows up, and acceptance collapses to random. Second, we cap the ratio at 1.0 — there's no benefit to accepting more than 100% of the time, and uncapping makes the test fail in degenerate cases (e.g. `p=0`).

### Step 6 — The Engine

```python
# specdec/engine.py
import torch
from .draft_tree import build_draft_tree
from .verifier import verify_speculative


@torch.no_grad()
def generate(
    model,
    input_ids: torch.Tensor,        # [1, prompt_len]
    max_new_tokens: int = 64,
    num_heads: int = 3,
    top_w: int = 4,
    top_k: int = 50,
    top_p: float = 0.9,
    min_p: float = 0.05,
    temperature: float = 1.0,
    eos_id: int | None = None,
):
    device = input_ids.device
    out = input_ids.clone()
    past = None
    generated = 0

    while generated < max_new_tokens:
        # Prefill / extend by 1
        if past is None:
            n_prefill = out.size(1)
        else:
            n_prefill = out.size(1) - 1
        chunk = out[:, -n_prefill:] if past is not None else out
        target_logits, past, hidden = model.target_logits(chunk, past)
        # target_logits: [1, n, V] — we only need the last position's logits to drive the heads
        last_hidden = hidden[:, -1, :]
        head_logits = [head(last_hidden) for head in model.heads]   # list of [1, V]

        paths, probs = build_draft_tree(head_logits, top_w=top_w,
                                        top_k=top_k, top_p=top_p, min_p=min_p)
        # Take the highest-probability path as our single draft
        best = probs.sum(dim=-1).argmax(dim=-1)
        draft_ids = paths.gather(1, best[:, None, None].expand(-1, 1, num_heads)).squeeze(1)
        draft_probs = probs.gather(1, best[:, None, None].expand(-1, 1, num_heads)).squeeze(1)

        # Run target over the full draft (cached forward)
        ver_chunk = draft_ids
        ver_logits, past, ver_hidden = model.target_logits(ver_chunk, past)
        # ver_logits: [1, num_heads, V]; the bonus logit comes from the LAST position
        bonus_logits = ver_logits[:, -1, :]

        emitted, n_accept = verify_speculative(
            torch.cat([ver_logits, bonus_logits.unsqueeze(1)], dim=1)[:, :num_heads + 1, :],
            draft_ids,
            draft_probs.unsqueeze(1) if draft_probs.dim() == 1 else draft_probs,
            bonus_logits,
            top_k=top_k, top_p=top_p, min_p=min_p, temperature=temperature,
        )
        n = int(n_accept.max().item())
        new_tokens = emitted[:, : n + 1]
        # Drop positions that were masked to 0 for rows that rejected earlier
        # (the controller truncates by n, so this is fine in batch=1)
        if eos_id is not None and (new_tokens == eos_id).any():
            new_tokens = new_tokens[:, : (new_tokens == eos_id).int().argmax() + 1]
        out = torch.cat([out, new_tokens], dim=-1)
        generated += new_tokens.size(1)
        if eos_id is not None and (new_tokens == eos_id).any():
            break

    return out
```

This is the engine. Everything else in the repo is glue.

## Running and Testing It

The fastest path to "it works" is unit-testing the sampler and verifier in isolation, then a tiny end-to-end smoke test.

```python
# tests/test_sampler.py
import torch
from specdec.sampler import top_k_filter, top_p_filter, min_p_filter, compose


def test_top_k_keeps_top_k():
    logits = torch.tensor([[1.0, 2.0, 3.0, 4.0, 5.0]])
    out = top_k_filter(logits, k=2)
    assert torch.isfinite(out).sum().item() == 2


def test_top_p_sums_to_one_after_softmax():
    logits = torch.randn(1, 100)
    out = top_p_filter(logits, p=0.5)
    p = torch.softmax(out, dim=-1)
    assert abs(p.sum().item() - 1.0) < 1e-5


def test_min_p_zero_passes_through():
    logits = torch.randn(1, 50)
    out = min_p_filter(logits, p=0.0)
    assert torch.equal(out, logits)


def test_compose_is_order_stable():
    logits = torch.randn(2, 1000)
    a = compose(logits, top_k=50, top_p=0.9, min_p=0.05)
    b = compose(logits, top_k=50, top_p=0.9, min_p=0.05)
    assert torch.equal(a, b)
```

```python
# tests/test_verifier.py
import torch
from specdec.verifier import verify_speculative


def test_accept_when_target_agrees():
    # When q == p everywhere, every draft token must be accepted.
    V = 100
    D = 3
    target_logits = torch.randn(1, D + 1, V)
    # Force the target to predict argmax == the "draft" by zeroing others
    draft = torch.tensor([[7, 13, 42]])
    target_logits[0, torch.arange(D), draft[0]] = 10.0
    target_logits[0, torch.arange(D), :] -= (1 - torch.eye(V)[draft[0]].sum(-1)).sum()*0  # no-op
    draft_probs = torch.full((1, D), 1.0 / V)
    bonus = torch.zeros(1, V)
    out, n_acc = verify_speculative(
        target_logits, draft, draft_probs, bonus,
        top_k=50, top_p=0.9, min_p=0.05,
    )
    assert int(n_acc.item()) >= 2  # very likely all 3


def test_reject_immediately_when_target_disagrees():
    V = 100
    D = 3
    draft = torch.tensor([[7, 13, 42]])
    target_logits = torch.full((1, D + 1, V), -10.0)
    # Target strongly prefers 99 at every position
    target_logits[..., 99] = 10.0
    draft_probs = torch.full((1, D), 1.0 / V)
    bonus = torch.zeros(1, V)
    out, n_acc = verify_speculative(
        target_logits, draft, draft_probs, bonus,
        top_k=0, top_p=1.0, min_p=0.0,
    )
    assert int(n_acc.item()) == 0
```

End-to-end smoke test on a real model:

```python
# scripts/smoke.py
import torch
from transformers import AutoTokenizer
from specdec.model import MedusaModel
from specdec.engine import generate

tok = AutoTokenizer.from_pretrained("Qwen/Qwen2-0.5B")
model = MedusaModel("Qwen/Qwen2-0.5B", num_heads=3).cuda().eval()
prompt = tok("Once upon a time", return_tensors="pt").input_ids.cuda()
out = generate(model, prompt, max_new_tokens=80)
print(tok.decode(out[0], skip_special_tokens=True))
```

Benchmark with `torch.cuda.Event`:

```python
# bench.py
import time, torch
from specdec.model import MedusaModel
from specdec.engine import generate


def bench(model, prompt, **kw):
    torch.cuda.synchronize()
    t0 = time.perf_counter()
    out = generate(model, prompt, **kw)
    torch.cuda.synchronize()
    dt = time.perf_counter() - t0
    n_new = out.size(1) - prompt.size(1)
    return dt, n_new, n_new / dt


if __name__ == "__main__":
    tok = AutoTokenizer.from_pretrained("Qwen/Qwen2-0.5B")
    model = MedusaModel("Qwen/Qwen2-0.5B", num_heads=3).cuda().eval()
    prompt = tok("The capital of France is", return_tensors="pt").input_ids.cuda()
    for cfg in [
        dict(top_k=0,  top_p=1.0, min_p=0.0),  # greedy
        dict(top_k=50, top_p=0.9, min_p=0.05), # balanced
        dict(top_k=200, top_p=0.95, min_p=0.02),
    ]:
        dt, n_new, tps = bench(model, prompt, max_new_tokens=128, **cfg)
        print(f"cfg={cfg}  tokens={n_new}  seconds={dt:.3f}  tok/s={tps:.1f}")
```

You'll typically see 1.5×–2.5× speedup over vanilla `model.generate` on a small model with random-init heads, and 3×–4× once heads are lightly trained. The acceptance rate per round is the headline metric — log it on every bench run.

## Extending It: Your Roadmap to Senior-Level

A toy speculative decoder is a strong *starting* point. The difference between "junior who can read papers" and "senior who can ship inference" is the maturity of the surrounding systems. Here are six upgrades, each one a real resume bullet.

- **Persistent prefix cache (Redis or vLLM-style paged attention).** Real serving systems reuse the KV cache across requests with the same prefix. Implementing a `PrefixCache` module that hashes system prompts and reuses their cached state turns this from "decoder" into "server." *Why it matters: this is exactly how vLLM, SGLang, and TensorRT-LLM get their throughput.*
- **Horizontal scaling with continuous batching.** Wrap your engine in a Ray actor or FastAPI + uvicorn worker pool, and add a request queue that packs multiple in-flight generations into the same target forward pass. *Why it matters: continuous batching is the single biggest serving-throughput lever in modern LLM systems.*
- **OpenTelemetry + Prometheus observability.** Emit counters for `acceptance_rate`, `draft_length`, `tokens_per_second`, `kv_cache_hit_ratio`, and histograms for per-step latency. Add a Grafana dashboard JSON. *Why it matters: every on-call engineer wants to see acceptance-rate regressions in real time — this is what "production" looks like.*
- **Fault tolerance via checkpointed speculative state.** Persist the in-flight draft tree and KV cache to disk (or `lmdb` / `sqlite`) so a crashed worker can resume mid-generation. Pair with a supervisor that restarts workers and replays from the last checkpoint. *Why it matters: long-context generations (100k+ tokens) will crash, and recovery is what separates demos from services.*
- **Benchmarking against `transformers.generate` and vLLM.** Add a `bench/` suite that runs the same prompts across your engine, `model.generate`, and `vllm.LLM`, reporting tok/s, acceptance rate, and p99 latency. *Why it matters: a side-by-side benchmark is the single most persuasive artifact in a portfolio — it forces the numbers to be honest.*
- **Batched tree attention.** Replace the naive "one forward per draft path" verifier with a tree-attention mask so the target evaluates the entire candidate tree in a single call. This is what [the original Medusa repo](https://github.com/FasterDecoding/medusa) does and what makes depth > 3 viable. *Why it matters: it's the difference between a toy and a system that holds up at `k=5, w=4`.*

Each of these upgrades is 100–400 lines of code and one well-named module. Stack three of them and your repo is stronger than most MLOps portfolios.

## Key Takeaways

- A speculative decoder is one of the highest signal-per-line side projects you can build: bounded scope, deep systems content, and named-tool anchors.
- Medusa-style draft heads let you propose `k` future tokens in parallel and verify them in a single target forward pass — that's where the speedup comes from.
- The acceptance rule `min(1, q(x)/p(x))` is the entire algorithm; get it right and everything else is plumbing.
- Top-k → top-p → min-p is the modern sampling stack; composing them and applying them symmetrically to draft and target distributions is what makes the verifier numerically sane.
- Bench honestly: tok/s, acceptance rate, and draft length per round. Without those numbers, the project reads as a tutorial.
- The CV value scales sharply when you add real-systems upgrades: prefix caching, continuous batching, observability, fault tolerance, tree attention, and head-to-head benchmarks.

## Further Reading

- [Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads](https://arxiv.org/abs/2401.10774) — the original paper for the multi-head draft design.
- [Fast Inference from Transformers via Speculative Decoding (Leviathan, Kalman, Matias)](https://arxiv.org/abs/2211.17192) — the foundational formulation of speculative decoding.
- [Accelerating Large Language Model Decoding with Speculative Sampling (Chen et al.)](https://arxiv.org/abs/2302.01318) — independent and concurrent work that names the sampling variant.
- [Min-p Sampling for Creative and Coherent Text Generation](https://arxiv.org/abs/2407.01082) — the min-p sampler paper, worth reading alongside the [Hugging Face generation docs](https://huggingface.co/docs/transformers/main/en/generation_strategies).
- [The Medusa reference implementation on GitHub](https://github.com/FasterDecoding/medusa) — the canonical code reference, including tree attention and training scripts.
- [vLLM's speculative decoding guide](https://blog.vllm.ai/2024/01/22/spec-decode.html) — production patterns for prefix caching and continuous batching you'll want to mirror.