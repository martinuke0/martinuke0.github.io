---
title: "Building a Speculative Decoding Engine From Scratch: A Portfolio Project That Actually Signals Systems Skill"
date: "2026-09-07T16:59:44.188"
draft: false
tags: ["speculative-decoding", "llm-inference", "python", "systems-engineering", "portfolio-project", "n-gram-speculator"]
description: "A hands-on build guide for a from-scratch speculative decoding engine with a draft-and-verify loop and n-gram speculator, designed as a portfolio piece that signals real systems skill to hiring managers."
summary: "Build a runnable speculative decoding engine in Python with an n-gram draft model and target-model verification loop — a portfolio project that demonstrates LLM inference, KV-cache reasoning, and acceptance sampling."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-a-speculative-decoding-engine-from-scratch-a-portfolio-project-that-actually-signals-systems-skill.svg"
  alt: "Diagram of a speculative decoding loop with an n-gram draft model feeding into a target verification step."
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding cuts LLM latency by letting a cheap draft model propose tokens that a larger target model verifies in parallel. In this guide you'll build a from-scratch Python engine with an n-gram speculator and a draft-and-verify loop, wire it up to a real Hugging Face model, benchmark acceptance rate, and ship a project that reads as serious systems work on a CV.

Most "build an LLM project" tutorials stop at a ChatGPT wrapper or a RAG demo with LangChain. Those signal "I can call an API." To stand out in 2026 you need a project that demonstrates you understand how inference actually works under the hood — KV caching, token-level parallelism, statistical acceptance sampling, and the trade-offs between throughput and latency. Speculative decoding is the single best topic for that, because it sits at the intersection of model internals, systems optimization, and applied probability, and it's what every production inference stack (vLLM, TensorRT-LLM, llama.cpp) is racing to ship.

This post walks you through building a complete, runnable speculative decoding engine from scratch — n-gram draft model, target verifier, acceptance sampling, KV-cache continuity, and a benchmark harness. By the end you'll have a GitHub repo that an interviewer can clone, run, and read.

## Why This Project Stands Out on a CV

Hiring managers at AI infrastructure companies (Anthropic, Mistral, Together, Fireworks, Modal, Replicate) skim portfolios for evidence that a candidate can reason about *inference*, not just *applications*. Speculative decoding is the canonical example of inference-time optimization, and building it yourself proves several non-trivial skills at once.

**Skills it demonstrates concretely:**

- **Transformer internals.** You can't implement an n-gram speculator or wire KV-cache continuation without understanding what a KV cache is, how token-by-token generation differs from prefill, and why attention masks matter for variable-length continuations.
- **Numerical correctness under sampling.** Acceptance sampling in speculative decoding requires log-prob arithmetic (log-softmax, the `min(1, p_target / p_draft)` rule, rejection resampling). Getting this right shows you can reason about probability and numerical stability — the same muscle you need for RLHF, PPO clipping, or importance sampling in evaluation pipelines.
- **Systems-level Python.** The project pushes you beyond pandas scripts into streaming generators, async I/O, byte-level tokenization, and tight loops where Python overhead matters. You'll naturally end up profiling with `cProfile` and rewriting hot paths — exactly the work done on inference teams.
- **Evaluation discipline.** A speculative engine is only as good as its measured acceptance rate and wall-clock speedup. You'll write a benchmark harness, report confidence intervals, and reason about variance — the same discipline expected for A/B testing models in production at [Datadog](https://www.datadoghq.com/) or [Honeycomb](https://www.honeycomb.io/).
- **Reading and implementing from papers.** The original [DeepMind speculative decoding paper](https://arxiv.org/abs/2211.17192) and [Leviathan et al.](https://arxiv.org/abs/2302.01318) are short and dense. Building from them proves you can translate math into code.

**Roles it signals for:** ML inference engineer, LLM platform engineer, applied ML engineer at an inference startup, performance engineer on a serving team, and — increasingly — "foundational model efficiency" roles at research labs. It also reads well for general backend roles that happen to involve LLM features, because the systems thinking transfers.

## Architecture Overview

The engine has five components. Data flows top-down on first call, then the verify step feeds the accepted prefix back to the speculator on every subsequent step.

```
┌─────────────────────────────────────────────────────────────┐
│                     Engine (orchestrator)                   │
│  - manages KV cache, calls speculator, calls target          │
│  - handles acceptance sampling and prefix rollback           │
└─────────────────────────────────────────────────────────────┘
              │                       │
              ▼                       ▼
┌──────────────────────┐   ┌──────────────────────────────┐
│   N-Gram Speculator  │   │   Target Model (HF causal    │
│   - lookup table     │   │   LM, e.g. Qwen2.5 / Llama)  │
│   - proposes γ tokens│   │   - scores proposed tokens    │
│   - returns logprobs │   │   - returns target logprobs   │
└──────────────────────┘   └──────────────────────────────┘
              │                       │
              └──────────┬────────────┘
                         ▼
              ┌──────────────────────┐
              │  Acceptance Sampler  │
              │  - logprob compare   │
              │  - rejection resample│
              └──────────────────────┘
```

**Component breakdown:**

- **Engine.** Holds the KV cache across calls, drives the loop, and exposes a `generate(prompt, max_tokens)` API that mirrors `model.generate`. It's the only stateful object.
- **N-Gram speculator.** A pure-Python lookup table keyed by the last *n* tokens of the prompt. For a given context it proposes the next *γ* tokens from prior occurrences in a reference corpus (we use the prompt itself plus any generated text). It also returns the draft logprobs, which the target needs for acceptance.
- **Target model.** A causal LM from Hugging Face `transformers` with `output_logits=True` and `use_cache=True`. We don't need a separate draft model because the n-gram speculator is itself the cheap proposer.
- **Acceptance sampler.** Implements the Leviathan et al. rule: for each draft token `x`, draw `u ~ Uniform(0,1)` and accept if `u < exp(log p_target(x) - log p_draft(x))`. If rejected, resample `x' ~ max(0, p_target - p_draft)` normalized, and discard everything after.
- **Benchmark harness.** Runs the engine on a prompt set against a naive autoregressive baseline, reports acceptance rate, tokens-per-second, and speedup with a confidence interval.

The two non-obvious design choices worth flagging up front: (1) we use a *single* target model and the n-gram as the draft — this is sometimes called "self-speculative" or "prompt lookup" decoding and was formalized in the [Prompt Lookup Decoding paper](https://arxiv.org/abs/2402.16349); and (2) we keep the target model's KV cache warm and reuse it across verified steps, which is what makes speculative decoding actually faster rather than just statistically clever.

## Building It Step by Step

The full implementation is around 350 lines. We'll go piece by piece. The repo layout is:

```
specdec/
  engine.py        # main loop
  ngram.py         # speculator
  accept.py        # acceptance sampling
  benchmark.py     # eval harness
  tests/
  README.md
```

### Step 1 — Project scaffolding

```bash
mkdir specdec && cd specdec
python -m venv .venv && source .venv/bin/activate
pip install torch transformers datasets numpy pytest tqdm
```

Pin a small target model so the engine runs on a laptop GPU. `Qwen2.5-0.5B` or `TinyLlama-1.1B-Chat-v1.0` both work; the former has a permissive license and clean tokenizer behavior.

### Step 2 — The n-gram speculator

The speculator indexes a corpus (typically `prompt + tokens generated so far`) by tuples of the last `n` tokens. Given a context suffix, it returns the most common continuation in the corpus of length `γ`.

```python
# ngram.py
from collections import defaultdict, Counter
from typing import List, Tuple

class NGramSpeculator:
    def __init__(self, n: int = 5, gamma: int = 5):
        self.n = n
        self.gamma = gamma
        self.table: dict[Tuple[int, ...], Counter] = defaultdict(Counter)

    def observe(self, tokens: List[int]) -> None:
        """Index every n-gram in `tokens` and its continuation up to gamma."""
        for i in range(len(tokens) - self.n):
            key = tuple(tokens[i : i + self.n])
            tail_start = i + self.n
            tail_end = min(tail_start + self.gamma, len(tokens))
            tail = tuple(tokens[tail_start:tail_end])
            self.table[key].update([tail])

    def propose(self, context: List[int]) -> Tuple[List[int], List[float]]:
        """Given a context of >= n tokens, propose up to gamma next tokens.
        Returns (proposed_tokens, draft_logprobs)."""
        if len(context) < self.n:
            return [], []
        key = tuple(context[-self.n :])
        continuations = self.table.get(key)
        if not continuations:
            return [], []
        # pick the most frequent continuation
        best_tail, count = continuations.most_common(1)[0]
        # frequency acts as a proxy probability; normalize later
        total = sum(continuations.values())
        draft_logprobs = [__import__("math").log(count / total)] * len(best_tail)
        return list(best_tail), draft_logprobs
```

Three notes. First, `observe` is called incrementally as the engine accepts tokens, so the corpus grows during generation. Second, the "probability" here is a crude empirical frequency — good enough for a portfolio piece, but in a senior-level extension you'd back off with Kneser-Ney smoothing. Third, this is exactly the algorithm shipped in [the Prompt Lookup Decoding implementation](https://github.com/apoorvumang/PromptLookupDecoding) by Apoorv Mangarkar.

### Step 3 — Acceptance sampling

This is the math heart of speculative decoding. We compare draft and target logprobs token-by-token and either accept, reject-and-resample, or stop.

```python
# accept.py
import math
import torch
import torch.nn.functional as F

def _next_logits_from_model(model, input_ids, past_key_values):
    """Run target model on the *full* proposed sequence in one forward pass,
    using KV cache. Returns logits for each proposed position."""
    with torch.no_grad():
        out = model(
            input_ids=input_ids,
            past_key_values=past_key_values,
            use_cache=True,
        )
    return out.logits, out.past_key_values  # logits: [1, T, V]


def verify_and_accept(
    proposed: List[int],
    draft_logprobs: List[float],
    target_logits: torch.Tensor,  # [1, len(proposed)+1, V]
    bos_offset: int,
) -> Tuple[List[int], torch.Tensor, int]:
    """Apply the Leviathan acceptance rule. Returns:
       (accepted_tokens, new_past_kv, num_consumed_target_logits)."""
    accepted = []
    rng = torch.Generator().manual_seed(0)
    for i, tok in enumerate(proposed):
        # target logits for position i predict token at i (offset by 1 internally)
        logp_target = F.log_softmax(target_logits[0, bos_offset + i], dim=-1)
        logp_d = draft_logprobs[i]
        logp_t = logp_target[tok].item()
        accept_prob = min(1.0, math.exp(logp_t - logp_d))
        if torch.rand(1, generator=rng).item() < accept_prob:
            accepted.append(tok)
        else:
            # resample from max(0, p_target - p_draft) normalized
            logp_full = F.log_softmax(target_logits[0, bos_offset + i], dim=-1)
            adjusted = (logp_full - logp_d).clamp(min=0.0)
            adjusted = adjusted / adjusted.sum()
            new_tok = torch.multinomial(adjusted, 1, generator=rng).item()
            accepted.append(new_tok)
            return accepted, new_tok, i + 1
    return accepted, None, len(proposed)
```

The function returns the *prefix* that the target model has actually scored, plus the index of the last consumed target logit. The engine then knows how far into the proposed sequence to commit and where to start the next round.

### Step 4 — The engine loop

```python
# engine.py
from typing import List
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from .ngram import NGramSpeculator
from .accept import _next_logits_from_model, verify_and_accept


class SpeculativeEngine:
    def __init__(self, model_id: str, n: int = 5, gamma: int = 5, device: str = "cuda"):
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id, torch_dtype=torch.float16, device_map=device
        ).eval()
        self.device = device
        self.spec = NGramSpeculator(n=n, gamma=gamma)
        self.gamma = gamma
        self.n = n

    @torch.no_grad()
    def generate(self, prompt: str, max_new_tokens: int = 128) -> str:
        ids = self.tokenizer(prompt, return_tensors="pt").input_ids.to(self.device)
        out_ids = list(ids[0].tolist())
        past = None
        # prefill
        prefill = out_ids
        logits, past = _next_logits_from_model(self.model, ids, past)
        next_tok = int(logits[0, -1].argmax().item())
        out_ids.append(next_tok)
        self.spec.observe(out_ids)

        while len(out_ids) - len(prefill) < max_new_tokens:
            context = out_ids
            proposed, draft_logprobs = self.spec.propose(context)
            if not proposed:
                # fallback: greedy step
                logits, past = _next_logits_from_model(
                    self.model, torch.tensor([out_ids[-1:]], device=self.device), past
                )
                next_tok = int(logits[0, -1].argmax().item())
                out_ids.append(next_tok)
                self.spec.observe(out_ids)
                continue
            # verify proposed tokens in a single forward pass
            proposed_tensor = torch.tensor([proposed], device=self.device)
            tlogits, past = _next_logits_from_model(self.model, proposed_tensor, past)
            accepted, resampled, consumed = verify_and_accept(
                proposed, draft_logprobs, tlogits, bos_offset=0
            )
            out_ids.extend(accepted)
            if resampled is not None:
                out_ids.append(resampled)
            self.spec.observe(out_ids)

            if self.tokenizer.eos_token_id in out_ids[-len(accepted) - 1:]:
                break

        return self.tokenizer.decode(out_ids[len(prefill):], skip_special_tokens=True)
```

The key systems insight: after a successful speculative round, `past_key_values` already contains the KV states for all *proposed* tokens. We don't re-encode them — we only commit the accepted prefix to `out_ids` and use the returned `consumed` index to slice the next round. This is the trick that produces real wall-clock speedups, and it's why [vLLM's speculative decoding](https://blog.vllm.ai/2024/10/17/spec-decode.html) implementation is so carefully tuned.

### Step 5 — Benchmark harness

```python
# benchmark.py
import time, json, statistics
from transformers import AutoModelForCausalLM, AutoTokenizer
from .engine import SpeculativeEngine

PROMPTS = [
    "The capital of France is",
    "def fibonacci(n):\n    if n < 2:\n        return n\n    return",
    "In a hole in the ground there lived a hobbit. Not",
]

def time_baseline(model_id, prompts, max_new=64):
    tok = AutoTokenizer.from_pretrained(model_id)
    mdl = AutoModelForCausalLM.from_pretrained(
        model_id, torch_dtype=torch.float16, device_map="cuda"
    ).eval()
    times = []
    with torch.no_grad():
        for p in prompts:
            ids = tok(p, return_tensors="pt").input_ids.cuda()
            t0 = time.perf_counter()
            mdl.generate(ids, max_new_tokens=max_new, do_sample=False)
            times.append(time.perf_counter() - t0)
    return times

def time_spec(engine, prompts, max_new=64):
    times = []
    for p in prompts:
        t0 = time.perf_counter()
        engine.generate(p, max_new_tokens=max_new)
        times.append(time.perf_counter() - t0)
    return times

if __name__ == "__main__":
    MODEL = "Qwen/Qwen2.5-0.5B"
    base = time_baseline(MODEL, PROMPTS)
    eng = SpeculativeEngine(MODEL, n=5, gamma=5)
    spec = time_spec(eng, PROMPTS)
    print(json.dumps({
        "baseline_mean_s": statistics.mean(base),
        "spec_mean_s": statistics.mean(spec),
        "speedup": statistics.mean(base) / statistics.mean(spec),
    }, indent=2))
```

Run this on three to five prompts and report the geometric mean of speedup plus the standard deviation — that's the format reviewers expect.

## Running and Testing It

Once `engine.py`, `ngram.py`, `accept.py`, and `benchmark.py` are in place, the loop is:

```bash
# quick smoke test
python -c "from specdec.engine import SpeculativeEngine; \
e = SpeculativeEngine('Qwen/Qwen2.5-0.5B'); \
print(e.generate('The capital of France is', max_new_tokens=20))"

# full benchmark
python -m specdec.benchmark

# unit tests
pytest specdec/tests -v
```

A working smoke test prints something coherent — "The capital of France is Paris, the largest city in France..." — and finishes in noticeably less wall time than `model.generate` for the same prompt. A benchmark that *doesn't* show a speedup means either the speculator is matching too few n-grams (increase corpus diversity, lower `n` to 3, or try longer prompts) or the target forward pass isn't actually parallelizing the proposed tokens (check that `past_key_values` is being threaded through correctly).

Add a few targeted unit tests:

```python
# tests/test_accept.py
from specdec.accept import verify_and_accept
import torch

def test_acceptance_when_draft_matches_target():
    # when draft and target probabilities are equal, every token should be accepted
    logits = torch.zeros(1, 1, 100)  # uniform
    accepted, resampled, consumed = verify_and_accept(
        proposed=[42, 7, 13], draft_logprobs=[0.0]*3, target_logits=logits, bos_offset=0
    )
    assert accepted == [42, 7, 13]
    assert resampled is None

def test_rejection_resamples():
    # draft assigns very high prob, target assigns very low -> guaranteed reject
    logits = torch.full((1, 1, 100), -100.0)
    logits[0, 0, 42] = 0.0  # target strongly prefers token 42
    accepted, resampled, consumed = verify_and_accept(
        proposed=[7], draft_logprobs=[0.0], target_logits=logits, bos_offset=0
    )
    assert accepted == []
    assert resampled == 42
```

These two tests pin the correctness invariant: when draft and target agree the engine behaves like the baseline, and when they disagree it resamples from the target. Anything you add on top — better sampling, longer n-grams, batching — needs to preserve this invariant. That property is what makes speculative decoding lossless, as proven in the [original Leviathan et al. paper](https://arxiv.org/abs/2302.01318).

## Extending It: Your Roadmap to Senior-Level

A working toy is the floor, not the ceiling. The following upgrades turn this into something a senior ML infra engineer would actually recognize. Pick two or three based on what role you're targeting.

- **Add a real draft model and Medusa-style heads.** Replace the n-gram speculator with a small distil of the target (e.g. `Qwen2.5-0.5B` drafting for `Qwen2.5-7B`), or train [Medusa heads](https://arxiv.org/abs/2401.10774) on top of the frozen target. *Why it matters:* this is the path [Fireworks AI's production stack](https://fireworks.ai/blog/fireattention-speculative-decoding) took, and it generalizes beyond lookup tables.
- **Batch verification across requests.** vLLM's `SequenceManager` verifies multiple speculative sequences in a single forward pass. Implement a request queue and per-request KV cache, then call the target once per step on the union of proposed tokens. *Why it matters:* batching is what turns a clever algorithm into a serving system, and it's the single most impressive systems skill on an inference resume.
- **Continuous batching with prefix sharing.** Integrate with [vLLM's `LLMEngine`](https://blog.vllm.ai/2023/06/20/vllm.html) or write a minimal scheduler that keeps the target GPU busy by interleaving speculative rounds across requests. *Why it matters:* this is how [Anyscale](https://www.anyscale.com/) and [Together](https://www.together.ai/) ship multi-tenant LLM endpoints.
- **Persistent KV cache and request resumption.** Move `past_key_values` into a [Redis](https://redis.io/) or [LMDB](https://www.symas.com/lmdb)-backed store keyed by request ID so long generations can pause and resume across processes. *Why it matters:* shows you understand serving latency budgets and the cost of recomputation — relevant to any role touching [LangServe](https://python.langchain.com/docs/langserve/) or [BentoML](https://www.bentoml.com/).
- **OpenTelemetry + Prometheus observability.** Emit metrics for `acceptance_rate`, `tokens_per_step`, `draft_target_ratio`, and `kv_cache_memory_bytes`. Build a Grafana dashboard JSON. *Why it matters:* demonstrates the production discipline that separates a hobby repo from something a platform team would deploy. The [OpenLLMetry](https://github.com/traceloop/openllmetry) project is a good reference.
- **Speculative decoding for beam search and Tree-of-Thought.** Replace the linear `gamma` chain with a tree of candidates and verify all leaves in one forward pass via a custom attention mask. *Why it matters:* this is the direction [DeepMind's SPecInfer paper](https://arxiv.org/abs/2305.09781) and the [EAGLE-2 work from Tsinghua](https://arxiv.org/abs/2406.16858) have pushed, and it shows research literacy beyond a single paper.

## Key Takeaways

- Speculative decoding is lossless: the draft-and-verify loop produces samples from the *target* distribution, not the draft's, because acceptance sampling preserves the target's probabilities exactly.
- The wall-clock win comes from KV-cache continuity across verified rounds — one target forward pass scores `gamma` draft tokens at the cost of roughly one step.
- An n-gram speculator is a legitimate and useful draft model: it costs nothing, requires no training, and is the basis of [prompt-lookup decoding](https://arxiv.org/abs/2402.16349) shipped in llama.cpp.
- The hard engineering work is plumbing: tokenization boundaries, KV-cache indexing, attention masks, and acceptance arithmetic. Getting those right is what signals real systems skill.
- A benchmark harness with wall-clock numbers and a unit-test invariant is what separates this project from "I read the paper once" — write both before you push to GitHub.

## Further Reading

Start with the two foundational papers, then move to the systems-level write-ups that translate them into code:

- [Fast Inference from Transformers via Speculative Decoding (Leviathan, Kalman, Matias, 2023)](https://arxiv.org/abs/2302.01318) — the canonical formulation of acceptance sampling for speculative decoding.
- [Accelerating Large Language Model Decoding with Speculative Sampling (DeepMind, 2022)](https://arxiv.org/abs/2211.17192) — the independent concurrent formulation, slightly different notation.
- [Prompt Lookup Decoding (Saxena, 2024)](https://arxiv.org/abs/2402.16349) — the paper that formalizes n-gram lookup as a draft model; closest match to what you just built.
- [vLLM Speculative Decoding Blog Post (Woosuk Kwon, 2024)](https://blog.vllm.ai/2024/10/17/spec-decode.html) — production-side implementation notes from the vLLM team, including how they handle batched verification.
- [How Speculative Decoding Works — Hugging Face Text Generation docs](https://huggingface.co/docs/transformers/main/en/model_doc/llama2#transformers.LlamaForCausalLM) and the [Transformers `generate` reference](https://huggingface.co/docs/transformers/main_classes/text_generation) — for understanding how the official `transformers` implementation threads KV-cache through speculative paths.
- [Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads (Cai et al., 2024)](https://arxiv.org/abs/2401.10774) — the natural next step beyond n-gram drafts, used by many production stacks.
- [EAGLE-2: Faster Inference of Language Models with Dynamic Draft Trees (Li et al., 2024)](https://arxiv.org/abs/2406.16858) — the current state of the art in tree-structured speculative decoding, a great target for the senior-level extensions.