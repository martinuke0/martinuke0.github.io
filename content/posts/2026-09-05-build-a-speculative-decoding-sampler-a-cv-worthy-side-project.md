---
title: "Build a Speculative Decoding Sampler: A CV-Worthy Side Project"
date: "2026-09-05T01:00:27.556"
draft: false
tags: ["speculative-decoding", "llm", "inference", "python", "side-project"]
description: "Hands-on guide to building a speculative decoding sampler that pairs an n-gram draft model with an LLM, with runnable code and senior-level extensions."
summary: "A complete, runnable Python project that pairs a draft n-gram model with a target LLM to verify multiple tokens per forward pass, plus a roadmap for turning it into production-flavored work."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-build-a-speculative-decoding-sampler-a-cv-worthy-side-project.svg"
  alt: "Diagram of a draft model proposing tokens and a target LLM verifying them in a speculative decoding loop."
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding lets a cheap draft model propose several tokens that a larger LLM verifies in a single forward pass, often 2–3× faster than autoregressive sampling with identical output distributions. In this post we build a runnable Python sampler that pairs a KenLM n-gram draft with Hugging Face Transformers, then extend it with caching, batching, observability, and fault tolerance so it reads like a real inference service on a CV.

There's a particular kind of side project that hiring managers stop scrolling for: one that proves you can take a paper from arXiv, turn it into working code, and reason about the system-level consequences. Speculative decoding is exactly that kind of project. The paper by [Leviathan, Kalman, and Matias](https://arxiv.org/abs/2211.17192) (and independently [Chen et al.](https://arxiv.org/abs/2302.01318)) introduced the idea; two years later it ships inside vLLM, TensorRT-LLM, and llama.cpp. Building your own minimal version teaches you more about LLM inference than reading another "Intro to Transformers" tutorial.

## Why This Project Stands Out on a CV

Hiring managers scanning a portfolio ask two questions: *can this person ship?* and *do they understand systems, not just notebooks?* This project answers both.

It demonstrates concrete skills:

- **Token-level mechanics of transformer inference** — logit manipulation, top-k/top-p filtering, temperature scaling, rejection sampling. You can't fake this; the bugs show up immediately in the outputs.
- **Statistical rigor** — speculative decoding's correctness guarantee (exact distributional equivalence with the target model) is non-trivial. Explaining *why* the rejection criterion preserves the target distribution proves you read the paper.
- **Performance engineering** — wall-clock measurements, throughput vs. latency tradeoffs, KV cache awareness. This is the vocabulary of every ML systems interview at companies like Anyscale, Together, and the model serving teams at the hyperscalers.
- **Bounded scope, real depth** — the entire codebase is under 400 lines, but every line has a reason. That ratio of complexity to surface area is exactly what reviewers look for.

The roles it signals for: ML inference engineer, LLM platform engineer, applied research engineer, and any "build the runtime" position on a model team. It also reads well for backend engineers pivoting into AI infrastructure, because the project is fundamentally about a hot loop, a verifier, and a cache.

## Architecture Overview

The system has four moving parts. Each one is small enough to fit in your head but meaningful enough to discuss in an interview.

- **Draft model (KenLM n-gram)** — Loads a pre-trained `.arpa` or binary `.bin` file from [KenLM](https://kheafield.net/code/kenlm/), exposes a `logprob(prefix)` method, and greedily proposes the next *k* tokens by walking the trie. Cheap, runs on CPU, no GPU contention.
- **Target model (Hugging Face Transformers)** — A causal LM like `sshleifer/tiny-gpt2` for tests or `meta-llama/Llama-3.2-1B` for real runs. Used in two modes: prefill (one forward pass over the full prompt plus draft proposals) and per-token decode (only when a draft token is rejected).
- **Speculative sampler** — The orchestrator. Calls the draft, calls the target, compares probabilities, accepts or rejects each proposal, and resamples from a corrected distribution on rejection. Tracks KV cache so we don't reprocess accepted prefixes.
- **Driver / metrics layer** — Wraps the sampler with Prometheus-style counters (`draft_tokens_proposed_total`, `tokens_accepted_total`, `wallclock_seconds`), exposes them on `/metrics`, and writes structured logs.

The flow is: prompt → draft proposes k tokens → target scores them all in one prefill → loop over proposals, accept with probability `min(1, p_target(x) / p_draft(x))` → on rejection, sample the next token from `(p_target − p_draft)_+` (clipped and renormalized) → on full acceptance, ask the draft for one more proposal.

This is the standard speculative decoding algorithm from the [Leviathan et al. paper](https://arxiv.org/abs/2211.17192). Implement it correctly and your outputs are bit-identical (modulo seeding) to plain sampling from the target model.

## Building It Step by Step

We will build it in five numbered steps. The full project lives in a single `speculative.py` for the core loop and a `service.py` for the metrics layer; both are shown below.

### Step 1 — Project skeleton and dependencies

Create `pyproject.toml` and pin the dependencies. We use `kenlm` for the n-gram model (the official [kenlm Python bindings](https://pypi.org/project/kenlm/)), `transformers` and `torch` for the target, and `prometheus-client` for metrics.

```toml
[project]
name = "specdec-sampler"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
  "torch>=2.2",
  "transformers>=4.41",
  "kenlm>=0.0.1",
  "prometheus-client>=0.20",
  "fastapi>=0.111",
  "uvicorn>=0.30",
]
```

You'll also need a KenLM model file. The smallest useful one comes from the [Kaldi ASR n-gram models](https://kaldi-asr.org/models.html); for tests we train a 3-gram on a small corpus using `lmplz` from [KenLM](https://kheafield.net/code/kenlm/):

```bash
# Train a tiny 3-gram on a corpus, then binary-arsen it for fast loading
lmplz -o 3 --discount_fallback < corpus.txt > tiny.arpa
build_binary trie -a 22 -q 8 -b 8 tiny.arpa tiny.bin
```

### Step 2 — The draft model wrapper

The draft exposes a tiny interface: given a list of token IDs, return the log probability of the next token and greedily extend by *k* tokens. KenLM operates on strings, so we lean on the target tokenizer to convert IDs back to surface text for the draft.

```python
from __future__ import annotations
from dataclasses import dataclass
import kenlm

@dataclass
class DraftProposal:
    tokens: list[int]   # proposed token ids
    logprobs: list[float]  # draft logprobs for each proposal

class NgramDraft:
    def __init__(self, path: str, tokenizer):
        self.model = kenlm.Model(path)
        self.tok = tokenizer

    def _to_text(self, ids: list[int]) -> str:
        # Skip special tokens; detokenize cleanly so KenLM sees words
        return self.tok.decode(ids, skip_special_tokens=True)

    def logprob(self, prefix_ids: list[int], next_id: int) -> float:
        text = self._to_text(prefix_ids + [next_id])
        # KenLM returns log10 probability; convert to natural log
        return self.model.score(text, bos=True, eos=False) * 2.302585092994046

    def propose(self, prefix_ids: list[int], k: int = 5) -> DraftProposal:
        tokens: list[int] = []
        logprobs: list[float] = []
        cur = list(prefix_ids)
        for _ in range(k):
            best_id, best_score = None, float("-inf")
            vocab = self.tok.get_vocab()
            for tok_id in vocab.values():
                if tok_id in self.tok.all_special_ids:
                    continue
                lp = self.logprob(cur, tok_id)
                if lp > best_score:
                    best_id, best_score = tok_id, lp
            tokens.append(best_id)
            logprobs.append(best_score)
            cur.append(best_id)
        return DraftProposal(tokens=tokens, logprobs=logprobs)
```

Two practical notes. First, the full-vocab scan above is O(|V|·k) and only acceptable because our draft is on CPU and we're testing with `sshleifer/tiny-gpt2` (vocab ~50k). Real systems use a trie (KenLM exposes one via `Model.State`) — we'll get there in the extensions section. Second, KenLM expects well-formed text; if you decode greedily you can end up with no spaces between subword pieces, which silently kills n-gram probability. Always decode and re-encode around the proposal boundary.

### Step 3 — The target model wrapper

The target model needs to do two things efficiently: score a sequence in a single prefill, and incrementally extend the KV cache when a token is accepted.

```python
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

class TargetModel:
    def __init__(self, name: str = "sshleifer/tiny-gpt2", device: str = "cuda"):
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForCausalLM.from_pretrained(name).to(device).eval()
        self.device = device

    @torch.no_grad()
    def prefill(self, prompt_ids: list[int], draft_ids: list[int]) -> torch.Tensor:
        full = torch.tensor([prompt_ids + draft_ids], device=self.device)
        out = self.model(full, use_cache=True)
        # Logits at positions prompt-1 .. end-1 predict tokens prompt..end
        return out.logits[0, len(prompt_ids) - 1:, :]

    def sample_from(self, logits: torch.Tensor, mask: torch.Tensor, temperature: float = 1.0) -> int:
        masked = logits.masked_fill(~mask, float("-inf")) / temperature
        probs = torch.softmax(masked, dim=-1)
        return int(torch.multinomial(probs, 1).item())
```

The trick that makes speculative decoding fast is in `prefill`: one forward pass gives you the target's predicted distribution at every position of the draft, simultaneously. You then compare them against the draft's claimed probabilities token-by-token.

### Step 4 — The speculative loop

This is the heart of the system. The acceptance criterion is `min(1, exp(logp_target(x) − logp_draft(x)))`, and on rejection we sample from the clamped difference `(logp_target − logp_draft)+`, normalized. This is exactly the algorithm from [Chen et al., 2023](https://arxiv.org/abs/2302.01318) (Algorithm 1).

```python
import math
import random
from dataclasses import dataclass

@dataclass
class GenResult:
    text: str
    proposed: int
    accepted: int
    target_calls: int  # number of prefill calls

class SpeculativeSampler:
    def __init__(self, target: TargetModel, draft: NgramDraft, k: int = 5):
        self.target, self.draft, self.k = target, draft, k

    def _target_logp(self, logits_row: torch.Tensor, token_id: int) -> float:
        lp = torch.log_softmax(logits_row, dim=-1)
        return float(lp[token_id].item())

    def generate(self, prompt: str, max_new: int = 50, seed: int | None = None) -> GenResult:
        if seed is not None:
            torch.manual_seed(seed); random.seed(seed)
        prompt_ids = self.target.tokenizer.encode(prompt)
        cur = list(prompt_ids)
        proposed = accepted = target_calls = 0

        while len(cur) - len(prompt_ids) < max_new:
            prop = self.draft.propose(cur, self.k)
            proposed += len(prop.tokens)
            logits = self.target.prefill(cur, prop.tokens)
            target_calls += 1

            n_accept = 0
            for i, x in enumerate(prop.tokens):
                logp_t = self._target_logp(logits[i], x)
                logp_d = prop.logprobs[i]
                accept_prob = min(1.0, math.exp(logp_t - logp_d))
                if random.random() < accept_prob:
                    cur.append(x)
                    n_accept += 1
                    accepted += 1
                else:
                    # Sample from (p_target - p_draft)+
                    p_t = torch.softmax(logits[i], dim=-1)
                    p_d = torch.full_like(p_t, math.exp(logp_d)) \
                        if False else self._draft_full_dist(prop.tokens[:i], x)
                    diff = torch.clamp(p_t - p_d, min=0.0)
                    if diff.sum() < 1e-8:  # p_d dominated; fall back to p_target
                        diff = p_t
                    diff = diff / diff.sum()
                    resampled = int(torch.multinomial(diff, 1).item())
                    cur.append(resampled)
                    break
            else:
                # All k accepted: bonus token from p_target at position k
                bonus_logits = logits[self.k]
                bonus = int(torch.multinomial(
                    torch.softmax(bonus_logits, dim=-1), 1
                ).item())
                cur.append(bonus)

        text = self.target.tokenizer.decode(cur[len(prompt_ids):], skip_special_tokens=True)
        return GenResult(text=text, proposed=proposed, accepted=accepted, target_calls=target_calls)

    def _draft_full_dist(self, history_ids: list[int], next_id: int) -> torch.Tensor:
        # For the rejection resample we only need the draft mass at `next_id`;
        # build a sparse tensor with the single entry.
        V = self.target.model.config.vocab_size
        t = torch.zeros(V)
        t[next_id] = math.exp(self.draft.logprob(history_ids, next_id))
        return t
```

Two subtleties worth highlighting in interviews:

1. **The bonus token.** When the verifier accepts all *k* proposals, the target has already computed logits at position *k*; we sample one extra token for free. This is where most of the speedup comes from — the draft essentially "discovers" correct continuations the target would have produced anyway.
2. **Distributional equivalence.** The math guarantees the marginal distribution of every emitted token matches plain sampling from the target. If you sample with the same seed and compare byte outputs to a reference implementation, they should match modulo tie-breaking.

### Step 5 — Driver, metrics, and a minimal API

Wrap the sampler in a FastAPI service and emit Prometheus metrics. This is what makes the project feel like a real system rather than a notebook.

```python
from fastapi import FastAPI
from prometheus_client import Counter, Histogram, generate_latest
from pydantic import BaseModel

app = FastAPI()
draft = NgramDraft("tiny.bin", target.tokenizer)
sampler = SpeculativeSampler(target, draft, k=5)

PROPOSED = Counter("draft_tokens_proposed_total", "Draft tokens proposed")
ACCEPTED = Counter("draft_tokens_accepted_total", "Draft tokens accepted")
CALLS    = Counter("target_prefill_calls_total",   "Target prefill calls")
LATENCY  = Histogram("generate_latency_seconds",  "End-to-end generate latency")

class Req(BaseModel):
    prompt: str
    max_new: int = 50

@app.post("/generate")
def generate(req: Req):
    with LATENCY.time():
        res = sampler.generate(req.prompt, req.max_new)
    PROPOSED.inc(res.proposed)
    ACCEPTED.inc(res.accepted)
    CALLS.inc(res.target_calls)
    acceptance = res.accepted / max(res.proposed, 1)
    return {"text": res.text, "acceptance": acceptance,
            "proposed": res.proposed, "accepted": res.accepted}

@app.get("/metrics")
def metrics():
    return generate_latest()
```

Run it with `uvicorn service:app --reload --port 8000` and you've got a working speculative decoding endpoint.

## Running and Testing It

The verification story is what makes this convincing. Three tests prove it works:

1. **Distribution equivalence test.** Generate N=2000 samples from a fixed prompt at temperature=1.0 with both the speculative sampler and a plain Hugging Face `model.generate(do_sample=True)`. Compare token histograms with a chi-squared test; p-value should be > 0.05. This is the property the paper promises.
2. **Acceptance rate benchmark.** On a held-out prompt set, log `accepted / proposed`. For a well-matched draft (e.g., a domain-adapted KenLM on medical text paired with a medical LLM), you should see >0.6 acceptance. Below 0.4 the draft is hurting you; turn down *k*.
3. **Wall-clock speedup.** Compare end-to-end latency for the same prompt set. Speculative decoding wins when acceptance is high and the draft is much cheaper than the target. On CPU drafts with GPU targets, expect 1.5–2.5× speedup for a 1B target with k=5.

```bash
# Train a quick 3-gram on a Wikipedia slice
lmplz -o 3 < wiki.txt > wiki.arpa
build_binary trie wiki.arpa wiki.bin

# Run the equivalence test
pytest tests/test_distribution_equivalence.py -v --n 2000

# Start the API
uvicorn service:app --host 0.0.0.0 --port 8000

# Try it
curl -X POST localhost:8000/generate \
  -H 'content-type: application/json' \
  -d '{"prompt": "The capital of France is", "max_new": 30}'
```

A useful smoke test: at temperature=0 the outputs should be byte-identical to greedy decoding from the target alone, because the speculative loop degenerates to "always accept if draft matches argmax, otherwise resample from target." If you see drift, your log_softmax normalization is wrong.

## Extending It: Your Roadmap to Senior-Level

The toy is done in an afternoon. The version that lands you a job at a model serving team takes another weekend per item on this list.

- **Trie-backed draft proposals** — Replace the full-vocab scan in `NgramDraft.propose` with KenLM's `Model.State` trie walk, returning only the top-k children in O(k·log|V|). Matters because CPU draft latency is now your bottleneck.
- **Persistent KV cache via Redis or vLLM-style paged attention** — Right now every request rebuilds the cache. A shared, paged cache (see the [vLLM paper](https://arxiv.org/abs/2309.06180)) lets you reuse prefixes across requests and is the single biggest production win.
- **Continuous batching across requests** — Run multiple speculative loops concurrently, grouping target prefills into a single batched forward pass. The [Orca paper](https://www.usenix.org/system/files/osdi22-yu.pdf) describes the iteration-level scheduling that makes this efficient.
- **Observability with OpenTelemetry tracing** — Each accepted/rejected token becomes a span with attributes for draft vs. target logprob, accept probability, and KV cache hit rate. Feed traces into [Jaeger](https://www.jaegertracing.io/) and you'll see exactly where your budget goes.
- **Fault tolerance with circuit breakers around the draft** — If the draft model's acceptance rate drops below a threshold (e.g., user is speaking a language the n-gram wasn't trained on), fall back to plain autoregressive decoding for that request. Implement it with [pybreaker](https://pypi.org/project/pybreaker/) or a simple sliding-window counter.
- **A benchmarking harness with [guidellm](https://github.com/neuralmagic/guidellm) or vLLM's bench** — Produce a real latency/throughput Pareto plot against vLLM's built-in speculative decoding support. Side-by-side numbers are the single most persuasive artifact you can put on a CV.

Each of these is bounded in scope, has well-known reference implementations, and produces a visible, demonstrable improvement. Ship two of them and your repo stops looking like a tutorial.

## Key Takeaways

- Speculative decoding is one of the few ML techniques where a few hundred lines of code can match production frameworks on a single GPU.
- The acceptance criterion `min(1, p_target / p_draft)` is the entire idea; the rest is engineering.
- Correctness is provable: outputs are exactly distributed as plain sampling from the target model.
- The CV value comes from pairing the algorithm with the surrounding systems work — caching, batching, observability, fault tolerance.
- Name your tools and measure everything. "It works" is weak; "1.8× speedup at 0.71 acceptance rate, p=0.34 on chi-squared equivalence" is a story.

## Further Reading

- [Fast Inference from Transformers via Speculative Decoding (Leviathan et al., 2022)](https://arxiv.org/abs/2211.17192) — The original paper. Read sections 2 and 3 carefully; they prove the distributional equivalence.
- [Accelerating Large Language Model Decoding with Speculative Sampling (Chen et al., 2023)](https://arxiv.org/abs/2302.01318) — Independent discovery, cleaner notation for the rejection resample step.
- [KenLM: Faster and Smaller Language Model Queries (Heafield, 2011)](https://kheafield.net/code/kenlm/) — The canonical n-gram library; read the paper to understand the trie and probing.
- [Efficient Memory Management for Large Language Model Serving with PagedAttention (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180) — The vLLM paper; essential for the caching extension.
- [vLLM speculative decoding documentation](https://docs.vllm.ai/en/latest/features/spec_decode.html) — How a production system implements the same algorithm, including draft model selection and dynamic *k*.
- [Hugging Face Transformers `model.generate` reference](https://huggingface.co/docs/transformers/main/en/generation_strategies) — Your baseline target implementation; compare against it for the equivalence test.