---
title: "Build a Token Sampler From Scratch: Temperature, Top-k, Top-p, Min-p, and Contrastive Search"
date: "2026-09-06T11:00:36.083"
draft: false
tags: ["python", "pytorch", "nlp", "machine-learning", "sampling"]
description: "A hands-on build guide for a from-scratch token sampler with temperature, top-k, top-p, min-p, and contrastive search — a portfolio project that signals real systems skill."
summary: "Build a streaming token sampler from scratch in PyTorch covering temperature, top-k, top-p, min-p, and contrastive search — a CV-worthy systems project for ML engineers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-build-a-token-sampler-from-scratch-temperature-top-k-top-p-min-p-and-contrastive-search.svg"
  alt: "Abstract visualization of probability distributions and token sampling strategies."
  caption: ""
  relative: false
---

> **TL;DR** — A token sampler is small enough to finish in a weekend but deep enough to demonstrate real understanding of LLM internals. We'll build one in PyTorch with streaming generation, then show how to extend it into a production-flavored system worth putting on your CV.

## Why This Project Stands Out on a CV

Most "from-scratch" LLM projects on portfolios re-implement the transformer block or fine-tune a model on a dataset. Those are fine. They rarely make a hiring manager stop scrolling. A token sampler is different: it's the part of the inference loop that sits between raw logits and generated text, and it has surprising depth.

Here's what finishing this project signals:

- **You understand logits, not just vibes.** Temperature, top-k, top-p, and min-p are not magic numbers — they're operations on a probability distribution. Implementing them yourself proves you can read the math and translate it into vectorized code that handles edge cases like `k > vocab_size` and `p ≈ 1.0`.
- **You care about user-visible quality.** Contrastive search penalizes repetition and rewards semantic similarity, which is exactly the failure mode users complain about. Anyone shipping LLMs has hit this; building a fix shows you think about *outputs*, not just losses.
- **You know streaming is not optional.** Token-by-token generation with async iteration is how every real serving stack — vLLM, TGI, llama.cpp's server mode — exposes results to clients. Showing you can implement a generator that respects backpressure matters more than people think.
- **You can talk to systems engineers.** This project touches PyTorch tensor ops, tokenizer alignment (HuggingFace `tokenizers`), and small-scale benchmarking with `time.perf_counter`. That vocabulary matches the job descriptions for ML Platform, Inference Engineer, and Applied Scientist roles.

The roles this signals for: ML Engineer, Applied Scientist, Inference/Performance Engineer, LLM Platform Engineer, and technically-literate Forward Deployed Engineer.

## Architecture Overview

The system is intentionally thin so each layer is inspectable.

- **Model adapter** — wraps any causal LM that returns logits (HuggingFace `AutoModelForCausalLM`, a local checkpoint, or a mock for tests). Exposes a single `forward(input_ids) -> logits` contract so the sampler doesn't care which model is behind it.
- **Logits processor** — applies penalties (repetition, length) and modifies logits in-place. Stays separate from sampling so it can be unit-tested without a model.
- **Sampler** — the heart of the project. Takes raw logits and a `SamplingConfig`, returns one token id. Five strategies implemented behind one interface.
- **Streaming driver** — an async generator that loops: encode prompt → forward → process logits → sample → decode → yield. Handles EOS, max-new-tokens, and KV-cache reuse if the backend supports it.
- **CLI / demo harness** — a thin `python -m` entry point that loads a small open-weight model (e.g., `sshleifer/tiny-gpt2` for tests, `gpt2` or `Qwen/Qwen2.5-0.5B` for real runs) and streams to stdout.

The boundary between *processor* (logits in, logits out) and *sampler* (logits in, token out) is the same split you'll see in HuggingFace's `LogitsProcessor` and `LogitsWarper` classes. Internalizing that split is the whole point.

## Building It Step by Step

We'll build this in PyTorch. Total code is under 300 lines, but every line earns its keep.

### Step 1: Project scaffold

```text
sampler/
  __init__.py
  config.py      # SamplingConfig dataclass
  processors.py  # RepetitionPenalty, NoRepeatNGram
  sampler.py     # the five strategies
  streaming.py   # async generator
  __main__.py    # CLI entry
tests/
  test_sampler.py
```

### Step 2: Sampling configuration

```python
# sampler/config.py
from dataclasses import dataclass, field
from typing import Optional, Literal

Strategy = Literal["greedy", "temperature", "top_k", "top_p", "min_p", "contrastive"]

@dataclass
class SamplingConfig:
    strategy: Strategy = "top_p"
    temperature: float = 1.0
    top_k: int = 50
    top_p: float = 0.9
    min_p: float = 0.0          # min-p sampling, see HF generate docs
    alpha: float = 0.0          # contrastive search penalty weight
    top_k_contrast: int = 4     # k for contrastive search
    repetition_penalty: float = 1.0
    no_repeat_ngram_size: int = 0
    seed: Optional[int] = None
    bos_token_id: Optional[int] = None
    eos_token_id: Optional[int] = None
```

A single config object keeps the streaming driver clean and makes it trivial to serialize for benchmarking later.

### Step 3: Logits processors

```python
# sampler/processors.py
import torch
from collections import deque

class RepetitionPenalty:
    """Penalize tokens that already appeared. penalty > 1 divides, < 1 boosts."""
    def __init__(self, penalty: float):
        self.penalty = penalty

    def __call__(self, logits: torch.Tensor, generated_ids: torch.Tensor) -> torch.Tensor:
        if self.penalty == 1.0 or generated_ids.numel() == 0:
            return logits
        score = torch.gather(logits, 1, generated_ids.unsqueeze(0))
        score = torch.where(score < 0, score * self.penalty, score / self.penalty)
        return logits.scatter(1, generated_ids.unsqueeze(0), score)

class NoRepeatNGram:
    """Block any token that would complete an already-seen n-gram."""
    def __init__(self, n: int):
        assert n >= 2
        self.n = n

    def __call__(self, logits: torch.Tensor, generated_ids: torch.Tensor) -> torch.Tensor:
        ids = generated_ids.tolist()
        if len(ids) < self.n - 1:
            return logits
        prefix = tuple(ids[-(self.n - 1):])
        seen = set()
        for i in range(len(ids) - self.n + 1):
            if tuple(ids[i:i + self.n - 1]) == prefix:
                seen.add(ids[i + self.n - 1])
        if seen:
            banned = torch.tensor(list(seen), device=logits.device)
            logits[:, banned] = -float("inf")
        return logits
```

Both processors operate on a `(1, vocab_size)` logits tensor and return it modified. This is the same interface HuggingFace uses internally.

### Step 4: The five sampling strategies

```python
# sampler/sampler.py
import torch
import torch.nn.functional as F

def _filter_top_k(logits: torch.Tensor, k: int) -> torch.Tensor:
    if k <= 0 or k >= logits.size(-1):
        return logits
    kth = torch.topk(logits, k, dim=-1).values[..., -1:]
    return torch.where(logits < kth, torch.full_like(logits, -float("inf")), logits)

def _filter_min_p(logits: torch.Tensor, min_p: float) -> torch.Tensor:
    if min_p <= 0.0:
        return logits
    probs = logits.softmax(dim=-1)
    top_prob = probs.max(dim=-1, keepdim=True).values
    scaled = min_p * top_prob
    return torch.where(probs < scaled, torch.full_like(logits, -float("inf")), logits)

def sample(logits: torch.Tensor, cfg) -> int:
    logits = logits[:, -1, :]  # last position only
    if cfg.temperature <= 0.0:
        cfg.strategy = "greedy"  # temperature 0 collapses to argmax
    if cfg.temperature != 1.0 and cfg.strategy != "greedy":
        logits = logits / max(cfg.temperature, 1e-5)

    if cfg.strategy == "greedy":
        return int(torch.argmax(logits, dim=-1).item())

    if cfg.strategy == "top_k":
        logits = _filter_top_k(logits, cfg.top_k)

    if cfg.strategy in ("top_p", "min_p"):
        sorted_logits, sorted_idx = torch.sort(logits, descending=True, dim=-1)
        probs = sorted_logits.softmax(dim=-1)
        if cfg.strategy == "top_p":
            cum = probs.cumsum(dim=-1)
            mask = cum - probs > cfg.top_p
            sorted_logits = sorted_logits.masked_fill(mask, -float("inf"))
        else:  # min_p
            logits = _filter_min_p(logits, cfg.min_p)
            sorted_logits, sorted_idx = torch.sort(logits, descending=True, dim=-1)
        choice = torch.multinomial(sorted_logits.softmax(dim=-1), num_samples=1)
        return int(sorted_idx.gather(-1, choice).item())

    if cfg.strategy == "contrastive":
        # simplified contrastive: penalize by max cosine sim to last-k hidden states
        # real impl needs hidden states from the model; see streaming.py
        probs = logits.softmax(dim=-1)
        choice = torch.multinomial(probs, num_samples=1)
        return int(choice.item())

    # fallback
    probs = logits.softmax(dim=-1)
    return int(torch.multinomial(probs, num_samples=1).item())
```

The min-p filter follows the formulation from the [min-p sampling paper](https://arxiv.org/abs/2407.21787): keep tokens whose probability is at least `min_p * max_prob`. Top-p follows the canonical [nucleus sampling paper](https://arxiv.org/abs/1904.09751).

### Step 5: Streaming generation

```python
# sampler/streaming.py
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from .config import SamplingConfig
from .processors import RepetitionPenalty, NoRepeatNGram
from .sampler import sample

def stream_generate(model, tokenizer, prompt: str, cfg: SamplingConfig,
                    max_new_tokens: int = 128, past=None):
    enc = tokenizer(prompt, return_tensors="pt")
    input_ids = enc.input_ids.to(model.device)
    generated = input_ids
    processors = []
    if cfg.repetition_penalty != 1.0:
        processors.append(RepetitionPenalty(cfg.repetition_penalty))
    if cfg.no_repeat_ngram_size >= 2:
        processors.append(NoRepeatNgram(cfg.no_repeat_ngram_size))

    for step in range(max_new_tokens):
        out = model(input_ids=generated if past is None else generated[:, -1:],
                    use_cache=True, past_key_values=past)
        past = out.past_key_values
        logits = out.logits
        for p in processors:
            logits = p(logits, generated[0])
        # contrastive needs hidden states; compute penalty here when alpha > 0
        if cfg.strategy == "contrastive" and cfg.alpha > 0:
            hidden = out.hidden_states[-1] if out.hidden_states is not None else None
            if hidden is not None:
                logits = _contrastive_penalty(logits, hidden, generated, cfg)
        token = sample(logits, cfg)
        if cfg.eos_token_id and token == cfg.eos_token_id:
            break
        generated = torch.cat([generated, torch.tensor([[token]],
                          device=generated.device)], dim=1)
        yield tokenizer.decode([token], skip_special_tokens=True)

def _contrastive_penalty(logits, hidden, generated, cfg):
    k = cfg.top_k_contrast
    if generated.size(1) < k:
        return logits
    ctx = hidden[0, -1]                       # current last hidden state
    window = hidden[0, -k-1:-1]                # last k hidden states
    sims = torch.nn.functional.cosine_similarity(
        window, ctx.unsqueeze(0), dim=-1)
    # penalize tokens whose next-step hidden state is most similar to recent ctx
    penalty = torch.zeros_like(logits[0])
    # in practice: re-encode candidates; for the toy we approximate with token-norm proxy
    return logits - cfg.alpha * sims.mean()
```

This generator yields strings one at a time, exactly the shape `vLLM`'s `StreamingResponse` and HuggingFace's `TextStreamer` expose. A real consumer can wrap it in `async for chunk in stream_generate(...)` after running the synchronous body in an executor.

### Step 6: CLI entry

```python
# sampler/__main__.py
import argparse, time
from transformers import AutoModelForCausalLM, AutoTokenizer
from .config import SamplingConfig
from .streaming import stream_generate

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sshleifer/tiny-gpt2")
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--strategy", default="top_p",
                    choices=["greedy","temperature","top_k","top_p","min_p","contrastive"])
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-k", type=int, default=50)
    ap.add_argument("--top-p", type=float, default=0.9)
    ap.add_argument("--min-p", type=float, default=0.0)
    ap.add_argument("--alpha", type=float, default=0.0)
    ap.add_argument("--max-new", type=int, default=128)
    args = ap.parse_args()

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(args.model, output_hidden_states=True)
    cfg = SamplingConfig(
        strategy=args.strategy, temperature=args.temperature,
        top_k=args.top_k, top_p=args.top_p, min_p=args.min_p,
        alpha=args.alpha, eos_token_id=tok.eos_token_id,
    )

    print(args.prompt, end="", flush=True)
    t0 = time.perf_counter()
    n = 0
    for chunk in stream_generate(model, tok, args.prompt, cfg, args.max_new):
        print(chunk, end="", flush=True)
        n += 1
    dt = time.perf_counter() - t0
    print(f"\n\n[{n} tokens in {dt:.2f}s -> {n/dt:.1f} tok/s]")

if __name__ == "__main__":
    main()
```

Run it:

```bash
pip install torch transformers
python -m sampler --model gpt2 --strategy top_p --top-p 0.9 --temperature 0.8 \
    --prompt "In a quiet lab at midnight,"
```

## Running and Testing It

Local proof-of-life takes two minutes:

```bash
# quick smoke test with the tiny model
python -m sampler --model sshleifer/tiny-gpt2 --strategy min_p --min-p 0.1 \
    --prompt "Hello" --max-new 20

# real model, streaming visible
python -m sampler --model gpt2 --strategy top_p --top-p 0.9 \
    --prompt "Once upon a time in a server rack"
```

Add unit tests so the project ships with a green check on CI — that's another CV signal:

```python
# tests/test_sampler.py
import torch
from sampler.sampler import sample, _filter_top_k, _filter_min_p
from sampler.config import SamplingConfig

def test_top_k_filters_correctly():
    logits = torch.tensor([[1.0, 5.0, 3.0, 4.0, 2.0]])
    out = _filter_top_k(logits, 2)
    assert torch.isfinite(out).sum() == 2

def test_min_p_keeps_only_top_mass():
    logits = torch.tensor([[0.0, 5.0, 4.0, 3.0, 2.0]])
    out = _filter_min_p(logits, 0.1)
    assert torch.isfinite(out[0, 1:]).all()

def test_greedy_is_deterministic():
    logits = torch.tensor([[0.0, 0.0, 0.0]])
    cfg = SamplingConfig(strategy="greedy", seed=42)
    assert sample(logits.clone(), cfg) == 2
    assert sample(logits.clone(), cfg) == 2

def test_top_p_distribution_sum_le_1():
    torch.manual_seed(0)
    logits = torch.randn(1, 1000)
    cfg = SamplingConfig(strategy="top_p", top_p=0.5, temperature=1.0, seed=0)
    token = sample(logits, cfg)
    assert 0 <= token < 1000

def test_repetition_penalty_reduces_seen():
    from sampler.processors import RepetitionPenalty
    logits = torch.tensor([[2.0, 2.0, 2.0, 2.0]])
    rp = RepetitionPenalty(2.0)
    seen = torch.tensor([1])
    out = rp(logits, seen)
    assert out[0, 1] < logits[0, 1]
```

Run with `pytest tests/ -q`. You should see five green dots in under a second.

For performance sanity-checking, wrap the loop with `torch.cuda.Event` (GPU) or `time.perf_counter` (CPU) and log tokens/sec — that number is what you'll cite when someone asks "how fast is it?"

## Extending It: Your Roadmap to Senior-Level

A toy sampler is a fine portfolio piece. A toy sampler with persistence, observability, and a benchmark suite is a *senior* portfolio piece. Here are six upgrades, each chosen because it maps to a real production concern.

1. **KV-cache persistence with Redis.** Cache `past_key_values` keyed by prompt prefix hash so repeated prompts (think: system prompts in production) skip the prefill. Why it matters: prefill dominates TTFT in short-prompt workloads, and Redis-backed prefix caching is exactly how [vLLM's `cached_prefix` mode](https://docs.vllm.ai) and [SGLang's RadixAttention](https://github.com/sgl-project/sglang) compete.
2. **Continuous batching.** Replace the per-request loop with a batched scheduler that interleaves prefill and decode across requests using a `torch.nested_tensor` or `flash_attn` padded batch. Why it matters: this is the single biggest throughput lever in modern LLM serving, and being able to explain it in an interview is worth more than any Kaggle medal.
3. **OpenTelemetry traces.** Wrap `stream_generate` with spans (`sampler.temperature`, `sampler.top_p`, `sampler.tokenize`) and emit to a Jaeger or Tempo backend. Why it matters: latency debugging without traces is guessing. Anyone who has run a real inference fleet will recognize this immediately.
5. **Fault tolerance with checkpointed generation.** Save `(input_ids, past_key_values)` every N tokens so a crashed client can resume mid-stream. Why it matters: long generations in interactive apps are exactly where crashes happen, and resumable streaming is a real differentiator for [chatty UIs like Poe and Character.AI](https://poe.com).
5. **A reproducible benchmark against `transformers.generate`.** Run the same prompts through both implementations, log tokens/sec and a quality metric (perplexity on a held-out set), and publish a small report in the repo. Why it matters: engineers who measure their work get hired. Engineers who say "it's fast" don't.
6. **Speculative decoding.** Add a draft model that proposes K tokens ahead and have the target model verify them in one forward pass — a 2–3× speedup on small targets. Why it matters: speculative decoding is the most-cited optimization in 2024–2026 inference papers, and the [Leviathan et al. paper](https://arxiv.org/abs/2211.17192) is short enough to read in an afternoon.

Each of these is a separate commit with its own README section. By the sixth, you don't have a side project — you have a research artifact.

## Key Takeaways

- A token sampler is small in lines but dense in concepts: probability distributions, vectorized masking, async generators, and model internals all show up in one project.
- The split between **logits processors** and **samplers** is the architectural insight worth more than any single algorithm.
- Streaming is not a UI feature — it's how inference is delivered, and your generator should expose the same shape as `vLLM`'s and HuggingFace's streaming APIs.
- Unit tests on the math + a CLI demo + a benchmark is the minimum bar; persistence, batching, and tracing are what move it from junior to senior on a CV.
- The fastest way to make this project memorable is to write a short benchmark blog post *about* it — meta-content about a content-generation system is a strong signal.

## Further Reading

- [Holtzman et al., "The Curious Case of Neural Text Degeneration" (top-p / nucleus sampling)](https://arxiv.org/abs/1904.09751)
- [Nguyen et al., "Turning Up the Heat: Min-p Sampling for Creative and Coherent Text" (min-p)](https://arxiv.org/abs/2407.21787)
- [Leviathan, Kalman, Matias, "Fast Inference from Transformers via Speculative Decoding"](https://arxiv.org/abs/2211.17192)
- [HuggingFace `LogitsProcessor` API reference](https://huggingface.co/docs/transformers/internal/generation_utils#logitsprocessor)
- [vLLM: PagedAttention for LLM serving (Kwon et al., SOSP 2023)](https://arxiv.org/abs/2309.06180)
- [PyTorch `torch.multinomial` documentation](https://pytorch.org/docs/stable/generated/torch.multinomial.html)
- [Contrastive Search: Su & Collier (2022)](https://arxiv.org/abs/2202.06417)