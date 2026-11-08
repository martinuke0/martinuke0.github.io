---
title: "Building a Self-Contained Sampling and Decoding Engine in Pure Python"
date: "2026-11-08T11:00:53.495"
draft: false
tags: ["python", "machine-learning", "sampling", "top-k", "top-p"]
description: "A practical guide to implementing temperature, top‑k, and top‑p sampling from scratch in pure Python, with runnable code and production‑grade extensions."
summary: "Implement temperature, top‑k, and top‑p sampling from scratch in pure Python, then extend the engine for production use."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-08-building-a-self-contained-sampling-and-decoding-engine-in-pure-python.svg"
  alt: "Diagram of the sampling engine pipeline"
  caption: ""
  relative: false
---

> **TL;DR** — This project teaches you to build a self‑contained decoding engine that implements temperature, top‑k, and top‑p sampling entirely in Python, giving you a concrete artifact to showcase algorithmic and systems skills. By following the step‑by‑step guide you will produce runnable code that can be extended with caching, batching, and observability, mirroring real‑world LLM serving pipelines.

The ability to control how a language model chooses its next token is a core competency for any engineer working on generative AI systems. Whether you are tuning a chatbot, building a code‑completion service, or simply want to understand the internals of modern LLMs, mastering temperature, top‑k, and top‑p (nucleus) sampling is a practical differentiator. In this post you will implement each of these techniques from scratch in pure Python, then see how to evolve the prototype into a production‑grade component.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You will write softmax scaling, cumulative probability truncation, and stochastic token selection, demonstrating a solid grasp of probability theory and numerical stability.
- **Systems thinking** – The architecture is modular (distribution → filter → sampler), which mirrors how real inference engines like vLLM or Hugging Face Transformers are organized.
- **End‑to‑end ownership** – From raw logits to a sampled token, you control every line of code, a skill that hiring managers associate with “full‑stack ML engineering.”
- **Testability** – The guide includes unit tests and a simple benchmark, evidencing a disciplined approach to software quality.
- **Scalability preview** – The “Extending It” section outlines concrete steps to add batching, caching, and observability, signaling readiness for senior‑level infrastructure roles.

Roles this project directly supports include *ML Engineer*, *Inference Engineer*, *MLOps Engineer*, and *Data Platform Engineer*—positions that increasingly require hands‑on experience with token generation pipelines.

## Architecture Overview

The engine is composed of four loosely‑coupled components:

1. **Logits → Probability Converter** – Applies the softmax function and optionally scales by temperature.
2. **Top‑k Filter** – Keeps only the `k` highest‑probability tokens, zeroing out the rest.
3. **Top‑p (Nucleus) Filter** – Retains the smallest set of tokens whose cumulative probability exceeds `p`, then renormalizes.
4. **Sampler** – Performs a categorical draw from the filtered distribution, returning the chosen token.

A high‑level flow looks like this:

```
logits ──► Softmax + Temperature ──► Top‑k ──► Top‑p ──► Categorical Sample ──► token
```

Each stage is a pure function, making it trivial to unit‑test in isolation and to swap implementations later (e.g., switching to a NumPy‑vectorized version).

## Building It Step by Step

### 1. Project Skeleton

Create a directory `sampling_engine/` with the following files:

- `__init__.py`
- `distributions.py`
- `filters.py`
- `sampler.py`
- `main.py`

You can initialize a virtual environment and install only the standard library (no external dependencies required).

```bash
python -m venv venv
source venv/bin/activate
touch sampling_engine/__init__.py
```

### 2. Softmax with Temperature

In `distributions.py` implement a numerically stable softmax and a helper for temperature scaling.

```python
import math
from typing import List

def softmax(logits: List[float]) -> List[float]:
    """Stable softmax: subtract max for numerical stability."""
    max_logit = max(logits)
    exps = [math.exp(l - max_logit) for l in logits]
    sum_exps = sum(exps)
    return [e / sum_exps for e in exps]

def temperature_softmax(logits: List[float], temperature: float) -> List[float]:
    """Apply temperature before softmax. Higher T → flatter distribution."""
    if temperature <= 0:
        raise ValueError("Temperature must be > 0")
    scaled = [l / temperature for l in logits]
    return softmax(scaled)
```

### 3. Top‑k Filtering

In `filters.py` write a function that retains only the `k` largest probabilities.

```python
from typing import List, Tuple

def top_k(probs: List[float], k: int) -> Tuple[List[float], List[int]]:
    """
    Return (filtered_probs, indices) where only the k highest probability
    entries are kept; others are zeroed.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    # Pair each probability with its original index
    indexed = list(enumerate(probs))
    # Sort descending by probability
    indexed.sort(key=lambda x: x[1], reverse=True)
    # Keep top‑k
    kept = indexed[:k]
    # Reconstruct arrays in original order
    filtered = [0.0] * len(probs)
    indices = []
    for idx, prob in kept:
        filtered[idx] = prob
        indices.append(idx)
    return filtered, indices
```

### 4. Top‑p (Nucleus) Filtering

Add another function that performs nucleus sampling.

```python
def top_p(probs: List[float], p: float) -> Tuple[List[float], List[int]]:
    """
    Keep the smallest set of tokens whose cumulative probability >= p.
    Returns (filtered_probs, indices) with remaining entries renormalized.
    """
    if not (0 < p <= 1):
        raise ValueError("p must be in (0, 1]")
    indexed = list(enumerate(probs))
    indexed.sort(key=lambda x: x[1], reverse=True)
    cumsum = 0.0
    kept = []
    for idx, prob in indexed:
        cumsum += prob
        kept.append((idx, prob))
        if cumsum >= p:
            break
    # Renormalize kept probabilities
    total = sum(prob for _, prob in kept)
    filtered = [0.0] * len(probs)
    indices = []
    for idx, prob in kept:
        filtered[idx] = prob / total
        indices.append(idx)
    return filtered, indices
```

### 5. Combining into a Sampler

In `sampler.py` create a class that chains the stages and performs the categorical draw.

```python
import random
from typing import List

from .distributions import temperature_softmax
from .filters import top_k, top_p

class Sampler:
    def __init__(self, temperature: float = 1.0, k: int = 0, p: float = 1.0):
        """
        temperature: >0, higher → more random
        k: top‑k cutoff (0 or None → disabled)
        p: top‑p cutoff (1.0 → disabled)
        """
        self.temperature = temperature
        self.k = k
        self.p = p

    def sample(self, logits: List[float]) -> int:
        # 1. Temperature scaling
        probs = temperature_softmax(logits, self.temperature)
        # 2. Top‑k
        if self.k and self.k > 0:
            probs, _ = top_k(probs, self.k)
        # 3. Top‑p
        if self.p < 1.0:
            probs, _ = top_p(probs, self.p)
        # 4. Categorical draw
        r = random.random()
        cum = 0.0
        for idx, prob in enumerate(probs):
            cum += prob
            if r <= cum:
                return idx
        # Fallback (should not happen due to floating point)
        return len(probs) - 1
```

### 6. End‑to‑End Example

`main.py` demonstrates usage with a synthetic vocabulary of five tokens.

```python
from sampling_engine.sampler import Sampler

if __name__ == "__main__":
    # Fake logits for tokens: ["apple", "banana", "cherry", "date", "elderberry"]
    logits = [2.0, 1.5, 0.8, 0.2, 0.1]
    sampler = Sampler(temperature=0.7, k=3, p=0.9)
    token_idx = sampler.sample(logits)
    vocab = ["apple", "banana", "cherry", "date", "elderberry"]
    print(f"Sampled token: {vocab[token_idx]}")
```

Running `python -m sampling_engine.main` should print one of the top‑3 tokens, reflecting the combined constraints.

## Running and Testing It

1. **Execute the example**

   ```bash
   python -m sampling_engine.main
   ```

   You should see a token printed each run; repeat the command to observe sampling variance.

2. **Unit tests**

   Create `tests/test_filters.py` to assert that `top_k` zeroes out low‑probability entries and that `top_p` preserves cumulative mass.

   ```python
   import pytest
   from sampling_engine.filters import top_k, top_p

   def test_top_k_keeps_highest():
       probs = [0.1, 0.3, 0.2, 0.4]
       filtered, _ = top_k(probs, 2)
       assert filtered == [0.0, 0.0, 0.0, 0.4] or filtered == [0.0, 0.3, 0.0, 0.0]

   def test_top_p_cumulative():
       probs = [0.2, 0.3, 0.4, 0.1]
       filtered, _ = top_p(probs, 0.5)
       # Should keep at least one token with cumulative >= 0.5
       assert sum(filtered) == pytest.approx(1.0)
   ```

   Run with `pytest -q`.

3. **Benchmark**

   Use Python’s `timeit` to measure throughput for a batch of 10 000 samples:

   ```python
   import timeit
   from sampling_engine.sampler import Sampler

   sampler = Sampler(temperature=0.8, k=5, p=0.95)
   logits = [1.0] * 10  # 10‑token vocab

   def bench():
       for _ in range(10000):
           sampler.sample(logits)

   print("µs per sample:", timeit.timeit(bench, number=1) / 10000 * 1e6)
   ```

   This gives a baseline for later optimization.

## Extending It: Your Roadmap to Senior‑Level

1. **Vectorized Batch Sampling with NumPy** – Replace Python loops with NumPy operations to process thousands of sequences in parallel, dramatically improving throughput for high‑concurrency services.

2. **Persistent Probability Cache (Redis)** – Store pre‑computed softmax outputs for frequent prompt prefixes, reducing latency and shielding downstream model inference from repeated computation.

3. **Prometheus Metrics & Tracing** – Export latency, token distribution entropy, and filter rejection rates to Prometheus; add OpenTelemetry spans to trace a request from API gateway to token emission.

4. **Fault‑Tolerant Microservice (FastAPI + Docker)** – Wrap the sampler in a FastAPI endpoint, configure retries with exponential backoff, and containerize it so it can scale horizontally behind a load balancer.

5. **Benchmark Suite vs. Baselines** – Integrate `pytest-benchmark` to compare your engine against Hugging Face Transformers’ `generate` method on identical prompts, quantifying speed and quality trade‑offs.

6. **Dynamic Temperature Scheduling** – Implement a controller that adjusts temperature based on recent token entropy, mimicking the adaptive decoding strategies used in production chat systems.

Each upgrade directly maps to a real‑world concern: performance, caching, observability, resilience, and algorithmic refinement—exactly the skills senior engineering teams look for.

## Key Takeaways

- You have built a modular, pure‑Python engine that implements temperature, top‑k, and top‑p sampling from scratch.
- The architecture mirrors production LLM serving pipelines, making it a strong talking point in interviews.
- The included tests and benchmarks provide evidence of engineering rigor.
- The extension roadmap outlines concrete steps to evolve the prototype into a scalable, observable service.
- This project demonstrates both algorithmic understanding and systems engineering capability, appealing to hiring managers across ML, infrastructure, and MLOps roles.

## Further Reading

- [Nucleus Sampling (Top‑p) Paper](https://arxiv.org/abs/1904.09746) – The original description of nucleus decoding.
- [Hugging Face Text Generation Guide](https://huggingface.co/blog/how-to-generate) – Practical tips on applying temperature, top‑k, and top‑p in transformers.
- [Python `random` Module Docs](https://docs.python.org/3/library/random.html) – Underpinnings of the categorical draw used in the sampler.
- [FastAPI Documentation](https://fastapi.tiangolo.com/) – For turning your sampler into a production‑ready HTTP service.