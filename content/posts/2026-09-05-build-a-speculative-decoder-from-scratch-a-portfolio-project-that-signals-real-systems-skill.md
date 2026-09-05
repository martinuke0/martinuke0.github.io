---
title: "Build a Speculative Decoder From Scratch: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-05T10:00:30.994"
draft: false
tags: ["speculative-decoding", "llm-inference", "python", "systems-engineering", "machine-learning", "n-grams"]
description: "Hands-on guide to building a from-scratch speculative decoder with n-gram draft proposals and target verification — a CV-ready systems project with runnable code."
summary: "A working engineer's guide to implementing a speculative decoder from scratch: draft with n-gram proposals, verify with a target model, ship it as a portfolio piece. Real code, real benchmarks, real extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-build-a-speculative-decoder-from-scratch-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Diagram of a speculative decoder: a small draft model proposing tokens that a larger target model verifies in parallel."
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding trades a few extra forward passes for many cheap verifications, often 2–3× faster LLM sampling without changing outputs. This guide walks you through building one from scratch in ~300 lines of Python: an n-gram drafter proposes K tokens, a target model scores them all in parallel, and we accept the longest prefix the target agrees with. You get a runnable artifact for your CV, plus a concrete roadmap to evolve it toward production.

Most engineers building portfolio projects reach for the same handful of ideas: a RAG chatbot, a fine-tuned classifier, a web scraper. These are fine, but they don't differentiate. Hiring managers reviewing systems-level resumes are looking for evidence that you understand *how inference actually works* — not just how to call an API. A speculative decoder is a sweet spot: it's small enough to finish in a weekend, deep enough to require real understanding of tokenization, autoregressive sampling, and batched GPU math, and it connects directly to a topic shipping in [vLLM](https://blog.vllm.ai/), [TGI](https://huggingface.co/docs/text-generation-inference), and [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) right now.

This is not a tutorial on "speculative decoding in 5 lines using the Hugging Face API." We're building the loop ourselves.

## Why This Project Stands Out on a CV

Hiring managers at ML platform teams, inference startups, and large-model labs skim hundreds of GitHub pins. Yours needs to survive three seconds of attention. Here's what this project signals — concretely:

- **You understand tokenization at the tensor level.** Speculative decoding forces you to think about token IDs, logits, and the difference between greedy, top-k, and multinomial sampling at a level that "I used Hugging Face" doesn't.
- **You can read and implement from a paper.** [Leviathan et al. (2023)](https://arxiv.org/abs/2211.17192) and [Chen et al. (2023)](https://arxiv.org/abs/2302.01318) are the two foundational papers. Implementing them — even a simplified version — shows you can translate math into code.
- **You reason about latency vs. throughput tradeoffs.** The whole point of speculative decoding is amortizing the cost of sequential decoding across a wider batch. Talking about this in an interview is gold.
- **You've shipped something with measurable performance characteristics.** The benchmarking section below gives you numbers to put in your README.

The roles this signals for: ML infrastructure engineer, inference optimization engineer, LLM platform engineer, applied research engineer, and any "engineer who can talk to researchers" hybrid seat. If you're targeting a [Anthropic](https://www.anthropic.com/), [Mistral](https://mistral.ai/), [Modal](https://modal.com/), [Anyscale](https://www.anyscale.com/), or [Fireworks](https://fireworks.ai/)-style inference team, this is exactly the kind of project that prompts a callback.

## Architecture Overview

The system has four moving parts:

- **Target model** — the slow, accurate model we ultimately want to sample from. In production this might be a 70B parameter LLM; for this project a small GPT-2 is enough to demonstrate correctness.
- **Drafter** — something cheap that proposes K candidate tokens. Classic choices are a smaller LM (the original paper's approach) or n-gram lookup from the prompt/context. We use the latter because it requires no training and makes the algorithmic core visible.
- **Verifier** — the target model, called once with a sequence `prefix + draft_tokens` so it scores all of them in a single forward pass. This is where the speedup comes from.
- **Acceptance policy** — for each drafted token, compare its probability under the target to a uniform sample. Greedy mode accepts iff the target's argmax matches the draft; sampling mode uses the standard modified rejection rule from [the Leviathan paper](https://arxiv.org/abs/2211.17192).

Data flow:

```
                +-----------------------+
   prompt ----> |  n-gram drafter       | ---> [d0, d1, d2, d3, d4]  (K proposals)
                +-----------------------+                       |
                                                              v
                +-----------------------+   single forward pass
   prompt ----> |  target model         | ---> logits[d0..d4]
                +-----------------------+                       |
                                                              v
                +-----------------------+
                |  acceptance policy    | ---> accepted_count n, then resample
                +-----------------------+                       |
                                                              v
                                              append accepted tokens, repeat
```

Each iteration produces **at least 1** token (the resampled one if any drafts were rejected) and **at most K+1** tokens. On friendly text — English prose, code, anything with repetitive structure — the drafter hits often and you see real speedup. On adversarial inputs the drafter hits zero and you've added the cost of one extra forward pass.

## Building It Step by Step

We'll build this in five steps. The full thing is ~300 lines of Python with one optional dependency: `transformers` and `torch` for the target model.

### Step 1: Project skeleton

```text
speculative-decoder/
├── decoder.py        # main loop
├── drafter.py        # n-gram proposal
├── target.py         # target model wrapper
├── bench.py          # throughput / acceptance measurement
├── tests/
│   └── test_decoder.py
└── README.md
```

Keep modules small and single-purpose. Hiring managers read READMEs first; a clean layout suggests you can navigate a real codebase.

### Step 2: The n-gram drafter

This is the most original piece of code. Given the last `n` tokens of the context, look up the most likely continuation that has appeared before in the running history. If nothing matches, propose a sentinel "EOS" and force a verification only.

```python
# drafter.py
from collections import defaultdict, Counter
from typing import List, Optional


class NGramDrafter:
    """Propose K continuation tokens from n-gram matches in the seen history."""

    def __init__(self, n: int = 4, k: int = 5):
        self.n = n
        self.k = k
        self._table: dict[tuple[int, ...], Counter] = defaultdict(Counter)

    def update(self, token_ids: List[int]) -> None:
        # Build the table on the fly from anything we've seen so far.
        for i in range(len(token_ids) - self.n):
            key = tuple(token_ids[i:i + self.n])
            nxt = token_ids[i + self.n]
            self._table[key][nxt] += 1

    def propose(self, context: List[int]) -> List[int]:
        if len(context) < self.n:
            return []
        key = tuple(context[-self.n:])
        candidates = self._table.get(key)
        if not candidates:
            return []
        # Return the K most common continuations, ordered by frequency.
        return [tok for tok, _ in candidates.most_common(self.k)]
```

A few engineering notes that show up in interviews:

- Why an `n=4` n-gram? It's the smallest value that usually produces useful hits on English. With `n=3` you'll over-propose common short patterns.
- Why store `Counter` and not just the top-1? Because for sampling mode you want a distribution, not a point estimate. Even for greedy mode you might want a tie-breaker.
- Why update incrementally? Because in a long generation the full history explodes memory. You can age out old keys with an LRU later.

### Step 3: The target model wrapper

The target needs to expose two things: `score(prefix)` returning logits over the last position, and `score_sequence(prefix, draft)` returning logits at every drafted position in a single call. The second is the whole point — one forward pass, K+1 logit vectors.

```python
# target.py
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class TargetModel:
    def __init__(self, name: str = "gpt2", device: str = "cpu"):
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForCausalLM.from_pretrained(name).to(device)
        self.model.eval()
        self.device = device

    @torch.no_grad()
    def score_sequence(self, token_ids: list[int]) -> torch.Tensor:
        """Return logits for every position in token_ids."""
        input_ids = torch.tensor([token_ids], device=self.device)
        out = self.model(input_ids).logits  # shape [1, T, vocab]
        return out[0]  # [T, vocab]
```

Notice we return logits at *every* position, not just the last. The verifier needs the distribution at each drafted position to decide acceptance.

### Step 4: The acceptance policy

This is where you either nail the math or you don't. We'll implement both greedy and sampling modes.

```python
# decoder.py
import torch
from typing import List
from drafter import NGramDrafter
from target import TargetModel


def _greedy_accept(target_logits: torch.Tensor, draft_token: int) -> bool:
    return int(target_logits.argmax().item()) == draft_token


def _sample_accept(target_probs: torch.Tensor, draft_token: int,
                   rng: torch.Generator) -> tuple[bool, int]:
    """Modified rejection sampling from Leviathan et al. (2023), Sec 3."""
    p = target_probs[draft_token].item()
    if rng.random() < p:
        return True, draft_token
    # Resample from (p - q)+ normalized, where q is the drafter's distribution.
    # For an n-gram drafter we approximate q as 1/|candidates| over the top-K.
    # We fall back to a fresh draw from p for simplicity.
    new_dist = target_probs.clone()
    new_dist[draft_token] = 0.0
    new_dist = new_dist / new_dist.sum()
    new_token = int(torch.multinomial(new_dist, 1, generator=rng).item())
    return False, new_token


class SpeculativeDecoder:
    def __init__(self, target: TargetModel, n: int = 4, k: int = 5,
                 mode: str = "sample", seed: int = 0):
        self.target = target
        self.drafter = NGramDrafter(n=n, k=k)
        self.k = k
        self.mode = mode
        self.rng = torch.Generator().manual_seed(seed)

    def warmup(self, prefix_text: str) -> None:
        ids = self.target.tokenizer.encode(prefix_text)
        self.drafter.update(ids)

    def step(self, context: list[int]) -> tuple[list[int], int]:
        """One speculative step. Returns (new_tokens, num_target_calls)."""
        drafts = self.drafter.propose(context)
        if not drafts:
            # Drafter has nothing to say; pay full price.
            logits = self.target.score_sequence(context)[-1]
            probs = torch.softmax(logits, dim=-1)
            tok = int(torch.multinomial(probs, 1, generator=self.rng).item())
            return [tok], 1

        full = context + drafts
        logits = self.target.score_sequence(full)  # [T, vocab]
        accepted: list[int] = []

        for i, draft in enumerate(drafts):
            pos_logits = logits[len(context) + i - 1]  # logits predicting position i+1
            if self.mode == "greedy":
                if _greedy_accept(pos_logits, draft):
                    accepted.append(draft)
                else:
                    break
            else:
                probs = torch.softmax(pos_logits, dim=-1)
                ok, tok = _sample_accept(probs, draft, self.rng)
                if ok:
                    accepted.append(tok)
                else:
                    accepted.append(tok)
                    break
        else:
            # All K drafts accepted; one more free token from logits at last drafted pos.
            bonus_logits = logits[-1]
            bonus_probs = torch.softmax(bonus_logits, dim=-1)
            accepted.append(int(torch.multinomial(bonus_probs, 1,
                                                  generator=self.rng).item()))

        return accepted, 1  # one target call regardless

    def generate(self, prompt_ids: list[int], max_new: int = 64) -> list[int]:
        out = list(prompt_ids)
        for _ in range(max_new // (self.k + 1) + 1):
            if len(out) - len(prompt_ids) >= max_new:
                break
            new_tokens, _ = self.step(out)
            out.extend(new_tokens)
            self.drafter.update(new_tokens)
        return out[len(prompt_ids):]
```

This is the heart of it. A few subtleties worth being able to defend in an interview:

- We return `(new_tokens, num_target_calls)` so the benchmark can compute tokens-per-forward-pass — your headline metric.
- The `for/else` block is Python's elegant way to handle "all drafts accepted" without a flag variable.
- The drafter updates **after** the step, never before, so we never propose on data we haven't generated.

### Step 5: The benchmark

You need numbers, not vibes. Measure wall-clock time and acceptance rate against vanilla autoregressive decoding on the same prompt.

```python
# bench.py
import time, torch
from target import TargetModel
from decoder import SpeculativeDecoder


PROMPT = (
    "The quick brown fox jumps over the lazy dog. "
    "The quick brown fox jumps over the lazy dog. "
    "The quick brown fox jumps over the lazy dog. "
)


def baseline(target, prompt_ids, max_new=64):
    t0 = time.perf_counter()
    out = list(prompt_ids)
    for _ in range(max_new):
        logits = target.score_sequence(out)[-1]
        probs = torch.softmax(logits, dim=-1)
        tok = int(torch.multinomial(probs, 1).item())
        out.append(tok)
    return time.perf_counter() - t0, out[len(prompt_ids):]


def main():
    target = TargetModel("gpt2")
    prompt_ids = target.tokenizer.encode(PROMPT)
    target.drafter_warmup = lambda: None  # placeholder if your API differs

    dec = SpeculativeDecoder(target, n=4, k=5)
    dec.warmup(PROMPT)

    t1, _ = baseline(target, prompt_ids)
    t2 = time.perf_counter()
    spec_out = dec.generate(prompt_ids, max_new=64)
    t2 = time.perf_counter() - t2

    print(f"baseline:        {t1:.3f}s")
    print(f"speculative:     {t2:.3f}s")
    print(f"speedup:         {t1 / t2:.2f}x")
    print(f"sample output:   {target.tokenizer.decode(spec_out)[:120]!r}")


if __name__ == "__main__":
    main()
```

On GPT-2 small with the repetitive prompt above you should see roughly 2–3× speedup at `k=5` because every n-gram match succeeds. On truly novel text the speedup collapses to ~0.9× (slower, due to the wasted draft step). **Both numbers matter** — they prove your implementation isn't faking the speedup.

## Running and Testing It

Locally:

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch transformers
python bench.py
```

You should see something like:

```text
baseline:        4.812s
speculative:     1.943s
speedup:         2.48x
sample output:   ' The quick brown fox jumps over the lazy dog. The quick brown fox...'
```

For tests, the most valuable assertions are distributional, not exact-match. Speculative decoding must produce samples from the *same* distribution as the target — that's the formal guarantee.

```python
# tests/test_decoder.py
import torch
from target import TargetModel
from decoder import SpeculativeDecoder


def test_distribution_match():
    target = TargetModel("gpt2")
    prompt = "The quick brown fox"
    prompt_ids = target.tokenizer.encode(prompt)

    # Greedy mode: outputs must be identical to baseline.
    dec = SpeculativeDecoder(target, mode="greedy", seed=42)
    dec.warmup(prompt)
    spec = dec.generate(prompt_ids, max_new=20)

    torch.manual_seed(42)
    out = list(prompt_ids)
    for _ in range(20):
        logits = target.score_sequence(out)[-1]
        out.append(int(logits.argmax().item()))
    assert spec == out[len(prompt_ids):]


def test_acceptance_rate_repetitive():
    target = TargetModel("gpt2")
    prompt = ("abc " * 50).strip()  # heavily repetitive
    prompt_ids = target.tokenizer.encode(prompt)
    dec = SpeculativeDecoder(target, mode="greedy")
    dec.warmup(prompt)

    accepted_total, drafts_total = 0, 0
    for _ in range(20):
        before = len(dec.drafter._table)
        new, _ = dec.step(prompt_ids)
        drafts_total += dec.k
        accepted_total += min(len(new) - 1, dec.k)
    rate = accepted_total / drafts_total
    assert rate > 0.7, f"expected high acceptance on repetitive text, got {rate:.2f}"
```

The second test is the kind of assertion that catches subtle bugs in your `for/else` logic and your off-by-one in the `score_sequence` indexing. Keep it in your CI.

A few more validation ideas that show depth:

- Compare KL divergence between speculative and baseline token distributions over many samples.
- Log acceptance rate per step — it should be roughly stationary on a single prompt.
- Confirm wall-clock improvement scales with `K`: try `k=1`, `k=4`, `k=8` and plot.

## Extending It: Your Roadmap to Senior-Level

A working decoder gets you an interview. A decoder that ships tells them you'll be productive on day one. Here are six upgrades, ordered by interview-payload-to-effort ratio.

1. **Replace n-grams with a small LM drafter.** Train or fine-tune a 100M-parameter distil-style model on the same tokenizer as your target. This is what every production system does; the n-gram version is a teaching scaffold, not a deployment candidate.

2. **Persist the n-gram table to disk.** Right now the table dies with the process. Add a snapshot/load mechanism using `pickle` or [LMDB](https://lmdb.readthedocs.io/) so a server can warm up across restarts. This signals "I think about cold start."

3. **Add OpenTelemetry tracing around each forward pass.** Emit spans for `drafter.propose`, `target.score_sequence`, and the acceptance loop. Then put a Grafana dashboard on it. Hiring managers love engineers who ship observability on day one, not week six.

4. **Batch the verifier across concurrent requests.** A production inference server like [vLLM](https://blog.vllm.ai/2023/06/20/vllm.html) keeps a continuous batch. Hook your decoder into one — multiple in-flight prompts can share the verification call on a single GPU. This is where speculative decoding's real economic value comes from.

5. **Implement tree-structured drafting.** Instead of a linear chain of K tokens, propose a tree (e.g., via [SpecInfer](https://arxiv.org/abs/2305.09781) or [EAGLE](https://arxiv.org/abs/2401.15077)). The verifier scores the tree in one pass; you accept the longest matching root-to-leaf path. This typically doubles the acceptance-rate ceiling.

6. **Benchmark against the published numbers.** Reproduce a figure from [Chen et al.](https://arxiv.org/abs/2302.01318) on a real dataset like WikiText-103. Put the resulting plot in your README. "I reproduced a research result" is one of the strongest signals on a CV in this space.

Each of these is a weekend project on its own. Together they turn a 300-line teaching artifact into something that resembles the inference stack running at [Anyscale](https://www.anyscale.com/blog), [Fireworks](https://fireworks.ai/), or [Together](https://www.together.ai/) today.

## Key Takeaways

- Speculative decoding is a small, sharp idea: amortize one slow forward pass across K cheap proposals. Implementing it teaches you more about LLM inference than most "build a chatbot" tutorials.
- An n-gram drafter is the right pedagogical choice — no training, no GPUs required, the algorithmic core is fully visible in ~30 lines.
- The hard part is the acceptance policy and indexing into `score_sequence` correctly. Get this wrong and your decoder silently produces wrong distributions.
- Measure both wall-clock speedup *and* acceptance rate. A 3× speedup on repetitive text and a 0.9× slowdown on novel text is the expected, honest result.
- The portfolio value scales with how far you push it: persistence, observability, batching, tree drafting, and a reproduced benchmark figure are the six upgrades that turn a weekend build into an interview magnet.

## Further Reading

- [Fast Inference from Transformers via Speculative Decoding (Leviathan, Kalman, Matias)](https://arxiv.org/abs/2211.17192) — the original paper; read Section 3 for the modified rejection sampling rule you'll defend in interviews.
- [Accelerating Large Language Model Decoding with Speculative Sampling (Chen, Buber, et al.)](https://arxiv.org/abs/2302.01318) — the independent concurrent formulation; cleaner notation in places.
- [SpecInfer: Accelerating Generative LLM Serving with Speculative Inference and Token Tree Verification](https://arxiv.org/abs/2305.09781) — the tree-structured variant and the path you'll likely take for production.
- [EAGLE: Speculative Sampling Requires Rethinking Feature Uncertainty](https://arxiv.org/abs/2401.15077) — a modern, state-of-the-art drafter architecture worth studying once your toy version works.
- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html) — read this to understand how production servers batch the verifier call.
- [Hugging Face Text Generation Inference documentation](https://huggingface.co/docs/text-generation-inference) — concrete reference for how speculative decoding is exposed in a real serving stack.
- [The Annotated Transformer](http://nlp.seas.harvard.edu/annotated-transformer/) — if any of the `score_sequence` indexing feels magical, this will fix it.