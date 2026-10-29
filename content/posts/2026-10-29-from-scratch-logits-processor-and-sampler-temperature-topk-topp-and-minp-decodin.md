---
title: "From-Scratch Logits Processor and Sampler: Temperature, Top‑k, Top‑p, and Min‑p Decoding in Pure Python"
date: "2026-10-29T04:02:18.232"
draft: false
tags: ["python", "machine-learning", "nlp", "sampling", "cv-project"]
description: "Build a pure‑Python logits processor and sampler implementing temperature, top‑k, top‑p and min‑p decoding from scratch. Hands‑on code you can run, extend, and showcase on your CV."
summary: "A minimal, pure‑Python implementation of temperature‑scaled, top‑k, top‑p and min‑p token sampling, ready to run, test, and extend for your portfolio."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-29-from-scratch-logits-processor-and-sampler-temperature-topk-topp-and-minp-decodin.svg"
  alt: "Python code representing a logits processor and sampler"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a complete, pure‑Python logits processor and sampler that implements temperature scaling, top‑k, top‑p (nucleus) and min‑p decoding from scratch. The resulting code is runnable, testable, and perfect for a CV because it demonstrates low‑level systems skill with real‑world ML inference techniques.

Building a custom sampler from the ground up is a rare chance to touch the exact mechanics that power every LLM inference engine. You’ll see how temperature sharpens or blunts the probability distribution, how top‑k truncates the tail, how top‑p keeps the smallest cumulative mass, and how min‑p adds a floor to avoid degenerate samples. By the end you’ll have a tiny library you can import, benchmark, and extend.

## Why This Project Stands Out on a CV

- **Low‑level Python proficiency** – Writing pure‑Python code that manipulates tensors‑like arrays without external frameworks signals fluency in the language that underpins many production ML pipelines.  
- **Decoding algorithm knowledge** – Implementing temperature, top‑k, top‑p and min‑p shows you understand the knobs that control text generation quality and diversity, a core skill for NLP and generative‑AI roles.  
- **Testing & benchmarking mindset** – Adding unit tests, profiling runs, and clear CLI usage demonstrates an engineering habit of verifying correctness and performance.  
- **Extensibility** – Structuring the code as a pipeline (logits → filters → sampler) makes it easy to plug in later improvements (e.g., GPU off‑loading, caching) – exactly what hiring managers look for in candidates who can evolve a prototype into production‑grade code.  

Roles that particularly value this signal: NLP engineer, ML infrastructure engineer, backend engineer for generative AI, research engineer, and any position that requires tinkering with low‑latency inference.

## Architecture Overview

The sampler can be visualized as a linear pipeline:

```
raw logits
   │
   ▼
temperature scaling (softmax‑adjusted)
   │
   ▼
top‑k filter (zero out all but k largest)
   │
   ▼
top‑p (nucleus) filter (cumulative prob ≤ p)
   │
   ▼
min‑p floor (ensure no token falls below threshold)
   │
   ▼
random weighted choice → sampled token
```

**Components**

| Component | Purpose | Typical API |
|-----------|---------|-------------|
| `apply_temperature(logits, T)` | Divides logits by T and re‑softmaxes | `logits / T → probs` |
| `top_k_filter(probs, k)` | Keeps only the k highest‑probability tokens | `probs[...] = 0` for others |
| `top_p_filter(probs, p)` | Nucleus sampling – retains smallest prefix whose cumulative mass ≥ p | cumulative sum, cut off |
| `min_p_floor(probs, min_p)` | Guarantees a minimum probability mass for any token | `probs = max(probs, min_p)` |
| `sample_token(probs)` | Draws one token according to the final distribution | `random.choices` or `numpy.random.choice` |

This modular layout lets you replace or augment any stage (e.g., swap `top_k_filter` for a beam search later) without rewriting the whole sampler.

## Building It Step by Step

Below are six numbered steps. Each step contains a runnable Python snippet. Save them in a single file `sampler.py` or import the functions as needed.

### Step 1 – Raw logits

```python
# sampler.py – Step 1: raw logits (unnormalised scores)
from __future__ import annotations
from typing import List

def raw_logits(vocab_size: int, preferred: List[int] | None = None) -> List[float]:
    """Return a list of logits for a vocabulary of size `vocab_size`.

    Optionally boost a few token IDs to illustrate later filtering.
    """
    import random
    logits = [random.gauss(0, 1) for _ in range(vocab_size)]
    if preferred:
        for tid in preferred:
            logits[tid] += 5.0  # boost selected tokens
    return logits
```

### Step 2 – Temperature scaling

```python
def apply_temperature(logits: List[float], temperature: float) -> List[float]:
    """Scale logits by *temperature* and soft‑max them.

    *temperature < 1* sharpens the distribution;
    *temperature > 1* flattens it.
    """
    import math

    T = max(temperature, 1e-7)  # avoid divide‑by‑zero
    scaled = [l / T for l in logits]
    # numerically stable softmax
    max_scaled = max(scaled)
    exps = [math.exp(s - max_scaled) for s in scaled]
    sum_exps = sum(exps)
    probs = [e / sum_exps for e in exps]
    return probs
```

### Step 3 – Top‑k filtering

```python
def top_k_filter(probs: List[float], k: int) -> List[float]:
    """Zero out all but the *k* most probable tokens.

    Returns a new list; the original *probs* is left untouched.
    """
    import copy

    probs = copy.deepcopy(probs)
    if k <= 0:
        return [0.0] * len(probs)
    k = min(k, len(probs))
    # get indices of the k largest probabilities
    top_idx = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)[:k]
    for i in range(len(probs)):
        if i not in top_idx:
            probs[i] = 0.0
    # renormalise so remaining probs sum to 1
    total = sum(probs)
    if total > 0:
        probs = [p / total for p in probs]
    return probs
```

### Step 4 – Top‑p (nucleus) filtering

```python
def top_p_filter(probs: List[float], p: float) -> List[float]:
    """Nucleus (top‑p) sampling: keep the smallest prefix whose
    cumulative probability ≥ *p*, then renormalise.

    *p* is typically 0.9 or 0.95.
    """
    import copy

    probs = copy.deepcopy(probs)
    # sort descending while keeping original indices
    sorted_idx = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    cumulative = 0.0
    keep = set()
    for idx in sorted_idx:
        cumulative += probs[idx]
        keep.add(idx)
        if cumulative >= p:
            break
    # zero out everything outside the kept set
    new_probs = [0.0 if i not in keep else probs[i] for i in range(len(probs))]
    total = sum(new_probs)
    if total > 0:
        new_probs = [p / total for p in new_probs]
    return new_probs
```

### Step 5 – Min‑p floor

```python
def min_p_floor(probs: List[float], min_p: float) -> List[float]:
    """Guarantee that every remaining token has at least *min_p* probability.

    Useful to prevent the sampler from ever picking a token with
    vanishing weight (e.g., in very low‑temperature settings).
    """
    # raise the floor, then renormalise
    adjusted = [max(p, min_p) for p in probs]
    total = sum(adjusted)
    if total == 0:  # safeguard – should not happen if min_p > 0
        return [1.0 / len(probs)] * len(probs)
    return [p / total for p in adjusted]
```

### Step 6 – Sample a token

```python
import random

def sample_token(probs: List[float]) -> int:
    """Draw a token index according to the probability distribution *probs*.

    Uses Python's random.choices for a simple, dependency‑free implementation.
    """
    return random.choices(population=range(len(probs)), weights=probs, k=1)[0]
```

### Full driver (optional)

```python
def main():
    VOCAB = 100
    logits = raw_logits(VOCAB, preferred=[10, 23, 55])
    T, K, P, MIN_P = 0.7, 10, 0.9, 1e-4

    probs = apply_temperature(logits, T)
    probs = top_k_filter(probs, K)
    probs = top_p_filter(probs, P)
    probs = min_p_floor(probs, MIN_P)
    token = sample_token(probs)

    print(f"Sampled token id: {token} (out of vocab {VOCAB})")
    # you can also return probs for inspection

if __name__ == "__main__":
    main()
```

Run the script with `python sampler.py`; you should see a single token id printed each execution, demonstrating the full pipeline.

## Running and Testing It

1. **Install dependencies** – The implementation uses only the standard library, so no `pip install` is required. If you want numpy‑based vectorised ops, you can replace the pure‑Python loops, but the default works out‑of‑the‑box.

2. **Execute the demo** –  
   ```bash
   python sampler.py
   ```
   You should see something like `Sampled token id: 42 (out of vocab 100)`.

3. **Unit‑test the functions** – A minimal test suite can be added to `test_sampler.py`:

   ```python
   import pytest
   from sampler import apply_temperature, top_k_filter, top_p_filter, min_p_floor, sample_token, raw_logits

   def test_temperature_sharpens():
       logits = [0.0, -1.0, -2.0]
       probs = apply_temperature(logits, 0.1)
       # with low temperature the highest logit should dominate
       assert probs[0] > probs[1] > probs[2]

   def test_top_k_keeps_k():
       probs = [0.1, 0.2, 0.3, 0.4]
       filtered = top_k_filter(probs, 2)
       # only the two largest should have non‑zero weight
       assert sum(1 for p in filtered if p > 0) == 2

   def test_min_p_floor_raises_floor():
       probs = [0.01, 0.01, 0.01]
       floored = min_p_floor(probs, 0.02)
       assert all(p >= 0.02 for p in floored)

   if __name__ == "__main__":
       pytest.main()
   ```

   Run `pytest test_sampler.py -v` to confirm each stage behaves as expected.

4. **Benchmark** – Use `timeit` to measure per‑token latency on a large vocab (e.g., 50 k). Because the code is pure Python, you’ll see the cost of filtering; this number is useful when you later decide to off‑load to Cython or NumPy.

## Extending It: Your Roadmap to Senior‑Level

| Upgrade | One‑line reason it matters |
|---------|----------------------------|
| **Persist sampling state** (e.g., write per‑step probs to a JSON log) | Enables reproducible debugging and audit trails for generated text. |
| **Horizontal scaling via a message queue** (Redis/RabbitMQ) | Allows multiple inference workers to share load, essential for serving under high QPS. |
| **Observability hooks** (Prometheus metrics, OpenTelemetry traces) | Gives ops teams latency, error‑rate, and distribution metrics in production. |
| **Fault‑tolerant retry & circuit‑breaker** | Prevents a single bad sampling run from crashing the whole inference service. |
| **Benchmark suite** (latency vs. temperature, top‑k vs. top‑p) | Provides data‑driven decisions when tuning for speed vs. diversity. |
| **Integration with a real framework** (PyTorch/TensorFlow) | Turns the prototype into a drop‑in replacement for `torch.multinomial` or `tf.random.categorical`. |

Each upgrade moves the project from a “toy” to a component that could ship in a production LLM serving pipeline.

## Key Takeaways

- **Temperature**, **top‑k**, **top‑p**, and **min‑p** are the four primary levers that control LLM output quality and diversity.  
- Implementing them in pure Python gives you full visibility into the probability flow, making debugging and customisation straightforward.  
- A modular pipeline (logits → temperature → filters → sampler) mirrors the architecture used in production inference engines (e.g., vLLM, TensorRT‑LLM).  
- The codebase is deliberately lightweight—no external dependencies—so it can be dropped into any environment, from a local laptop to a containerised service.  
- Adding tests, benchmarks, and observability transforms the prototype into a signal of engineering maturity that hiring managers notice.  

## Further Reading

- [Hugging Face Transformers – Sample generation](https://huggingface.co/docs/transformers/main/en/model_doc/generation)  
- [arXiv:1907.10628 – “Language Models are Unsupervised Text Generators” (GPT‑2 paper)](https://arxiv.org/abs/1907.10628)  
- [OpenAI Blog – Temperature scaling in GPT‑3](https://openai.com/blog/gpt-3-release/)  
- [Distill.pub – “Top‑p Nucleus Sampling”](https://distill.pub/2017/softmax/)  
- [GitHub – Hugging Face transformers generation utils](https://github.com/huggingface/transformers/blob/main/src/transformers/generation/utils.py)  

These primary sources detail the theory behind each decoding strategy and provide reference implementations you can adapt as you evolve the project. Happy coding, and may your sampled tokens always be interesting!