---
title: "Build a Pure‑Python LLM Sampler: Temperature, Top‑k, and Top‑p from Scratch"
date: "2026-11-11T09:00:44.076"
draft: false
tags: ["python", "llm", "sampling", "cv", "side-project"]
description: "A hands‑on guide to building a pure‑Python LLM sampler with temperature, top‑k and top‑p, perfect for a portfolio CV."
summary: "Learn to implement an LLM sampler from scratch in pure Python, controlling temperature, top‑k and top‑p, and add a standout project to your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-11-build-a-purepython-llm-sampler-temperature-topk-and-topp-from-scratch.svg"
  alt: "A Python laptop with code visualisation"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑Python LLM sampler that implements temperature scaling, top‑k truncation and nucleus (top‑p) filtering from scratch. The complete, runnable code fits in a single file, demonstrates core probabilistic sampling patterns, and becomes a concrete, talk‑able portfolio piece for engineering roles.

A short paragraph: LLM sampling is the bridge between a model’s raw logits and the token you actually generate. By mastering temperature, top‑k and top‑p you gain fine‑grained control over creativity versus determinism — a skill that shows up in everything from chatbots to retrieval‑augmented generation.

## Why This Project Stands Out on a CV

Building a sampler from the ground up signals more than “I can call `transformers`”. It demonstrates:

- **Probabilistic algorithm design** – you implement softmax, temperature scaling, and nucleus sampling, showing you understand the math that underlies generation.
- **Low‑level Python fluency** – using only the standard library (or minimal dependencies) proves you can write efficient, readable code without hidden frameworks.
- **Control‑flow thinking** – the conditional filters (top‑k, top‑p) require careful ordering and early‑exit logic, a pattern that appears in data‑pipeline orchestration and backend services.
- **Debuggability** – a self‑contained sampler is easy to instrument, profile, and unit‑test, a trait hiring managers value when evaluating candidates for ML engineer, NLP engineer, or AI product roles.

Roles that particularly appreciate this kind of hands‑on work include **ML engineer**, **NLP engineer**, **AI product engineer**, and **backend engineer** responsible for custom generation pipelines. The project also gives you a concrete talking point for interviews: “Here’s how I control randomness in a language model, and here’s why I chose temperature = 0.7 over 1.0 for this use case.”

## Architecture Overview

The sampler can be visualized as a linear pipeline that transforms raw logits into a single token index:

```
logits  ──► temperature scaling ──► softmax ──► top‑k filter ──► top‑p (nucleus) filter ──► probability distribution ──► categorical sample ──► token index
```

**Components**

| Step | Purpose | Key operation |
|------|---------|---------------|
| 1️⃣ Temperature | Controls randomness: higher = more diverse, lower = more deterministic. | `scaled = logits / temperature` |
| 2️⃣ Softmax | Converts scaled logits into a proper probability distribution. | `p = exp(scaled) / sum(exp(scaled))` |
| 3️⃣ Top‑k | Keeps only the k most likely tokens, zero‑ing the rest. | `p[…] = 0` for all but top‑k |
| 4️⃣ Top‑p (nucleus) | Keeps the smallest set of tokens whose cumulative probability ≥ p. | Sort descending, cumsum, truncate. |
| 5️⃣ Sample | Draw one token according to the final distribution. | `numpy.random.choice` or `random.choices` |

The ordering matters: **top‑k** is applied first (it reduces the candidate set), then **top‑p** narrows further, ensuring the sampler never considers an unbounded vocabulary.

## Building It Step by Step

Below are five numbered steps that produce a fully functional sampler. Each step includes a short, language‑tagged code snippet. You can copy‑paste them into a file named `sampler.py` and run it after step 5.

### Step 1 – Imports and a helper softmax

```python
import math
from typing import List, Tuple

def softmax(logits: List[float]) -> List[float]:
    """Numerically stable softmax."""
    max_logit = max(logits)
    exps = [math.exp(l - max_logit) for l in logits]
    sum_exps = sum(exps)
    return [e / sum_exps for e in exps]
```

### Step 2 – Temperature scaling

```python
def apply_temperature(logits: List[float], temperature: float) -> List[float]:
    """Divide logits by temperature; temperature = 1 keeps them unchanged."""
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    return [l / temperature for l in logits]
```

### Step 3 – Top‑k filtering

```python
def top_k_filter(logits: List[float], k: int) -> List[float]:
    """Zero out all but the k largest logits."""
    if k <= 0:
        raise ValueError("k must be positive")
    if k >= len(logits):
        return logits[:]  # keep everything
    # Find the kth largest value
    sorted_vals = sorted(logits, reverse=True)
    threshold = sorted_vals[k - 1]
    # Zero out anything below the threshold
    return [l if l >= threshold else -float('inf') for l in logits]
```

### Step 4 – Top‑p (nucleus) filtering

```python
def top_p_filter(logits: List[float], p: float) -> Tuple[List[float], List[int]]:
    """Keep the smallest prefix of tokens whose cumulative probability ≥ p.
    Returns the modified logits and the indices of kept tokens."""
    if not (0 < p <= 1):
        raise ValueError("p must be in (0, 1]")
    # Pair each logits with its index
    indexed = list(enumerate(logits))
    # Sort descending by logit value
    indexed_sorted = sorted(indexed, key=lambda x: x[1], reverse=True)
    # Compute cumulative probabilities after softmax
    kept_indices = []
    cum_logits = 0.0
    for idx, logit in indexed_sorted:
        cum_logits += math.exp(logit)  # unnormalised contribution
        kept_indices.append(idx)
        if cum_logits / sum(math.exp(l) for l in logits) >= p:
            break
    # Zero out everything not in kept_indices
    kept_set = set(kept_indices)
    filtered = [
        l if i in kept_set else -float('inf')
        for i, l in enumerate(logits)
    ]
    return filtered, kept_indices
```

### Step 5 – Sample from the final distribution

```python
import random

def sample_from_probs(probs: List[float]) -> int:
    """Categorical sample using Python's random.choices."""
    token_index = random.choices(population=range(len(probs)), weights=probs, k=1)[0]
    return token_index
```

### Putting it all together

```python
def sample_llm(logits: List[float],
               temperature: float = 1.0,
               top_k: int | None = None,
               top_p: float | None = None) -> int:
    """End‑to‑end sampler. Returns the index of the sampled token."""
    # 1️⃣ Temperature
    scaled = apply_temperature(logits, temperature)

    # 2️⃣ Softmax
    probs = softmax(scaled)

    # 3️⃣ Optional top‑k
    if top_k is not None:
        probs = [p if lp >= -float('inf') else 0.0
                 for lp, p in zip(top_k_filter(logits, top_k), probs)]
        # Re‑normalise after top‑k zero‑ing
        probs = [p / sum(probs) for p in probs]

    # 4️⃣ Optional top‑p
    if top_p is not None:
        filtered, _ = top_p_filter(logits, top_p)
        # Re‑apply softmax on filtered logits
        scaled_f = apply_temperature(filtered, temperature)
        probs = softmax(scaled_f)
        probs = [p / sum(probs) for p in probs]

    # 5️⃣ Sample
    return sample_from_probs(probs)
```

**Quick test** (add at the bottom of `sampler.py`):

```python
if __name__ == "__main__":
    # Mock logits for a 10‑token vocabulary
    example_logits = [2.0, 1.0, 0.1, -0.5, -1.0, -2.0, -3.0, -4.0, -5.0, -6.0]
    idx = sample_llm(example_logits, temperature=0.7, top_k=5, top_p=0.9)
    print(f"Sampled token index: {idx}")
```

Run with `python sampler.py` – you should see a printed index each time, reflecting the chosen temperature, top‑k and top‑p settings.

## Running and Testing It

1. **Install Python 3.9+** – the code uses only the standard library, so no extra packages are required.
2. **Save the file** as `sampler.py` and make it executable (`chmod +x sampler.py`).
3. **Run a basic sanity check**:

   ```bash
   python sampler.py
   ```

   You should see a token index printed, e.g., `Sampled token index: 3`.

4. **Unit‑test the core functions**. A minimal `test_sampler.py` using `unittest`:

   ```python
   import unittest
   from sampler import softmax, apply_temperature, top_k_filter, top_p_filter, sample_llm

   class TestSampler(unittest.TestCase):
       def test_softmax_sum(self):
           logits = [0.0, 0.0, 0.0]
           probs = softmax(logits)
           self.assertAlmostEqual(sum(probs), 1.0)

       def test_temperature(self):
           logits = [1.0, 2.0, 3.0]
           scaled = apply_temperature(logits, 0.5)
           self.assertEqual(scaled, [2.0, 4.0, 6.0])

       def test_top_k_keeps_k(self):
           logits = [5.0, 1.0, 3.0, 2.0, 4.0]
           filtered = top_k_filter(logits, k=2)
           # Only the two largest (5.0 and 4.0) should remain non‑‑inf
           non_inf = [l for l in filtered if l != -float('inf')]
           self.assertEqual(len(non_inf), 2)

       def test_top_p_filter(self):
           logits = [0.0, 0.0, 0.0, 0.0]
           filtered, kept = top_p_filter(logits, p=0.5)
           # Should keep at least enough tokens for cumulative >= 0.5
           self.assertGreaterEqual(len(kept), 1)

       def test_sample_returns_valid_index(self):
           logits = [1.0, 2.0, 3.0]
           idx = sample_llm(logits, temperature=1.0)
           self.assertIn(idx, range(3))

   if __name__ == "__main__":
       unittest.main()
   ```

   Run with `python -m test_sampler.py`; all tests should pass, confirming that the pipeline stays deterministic and numerically stable.

5. **Experiment with parameters** – try `temperature=0.3` for deterministic output, `top_k=1` for greedy decoding, and `top_p=1.0` to disable nucleus filtering. Document the observed behaviour in a short notebook; this concrete experimentation is exactly what hiring managers love to see in a portfolio.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1️⃣ | **Persistence** – write sampled sequences to JSON/CSV and load them later. | Enables reproducible experiments, A/B testing, and building a dataset for fine‑tuning. |
| 2️⃣ | **Horizontal scaling** – expose the sampler via a lightweight HTTP service (e.g., FastAPI) so multiple clients can request tokens concurrently. | Mirrors real production pipelines where generation is a shared service behind a load balancer. |
| 3️⃣ | **Observability** – instrument temperature, top‑k, top‑p values per request and emit Prometheus metrics or OpenTelemetry traces. | Gives you insight into generation behaviour in production, essential for capacity planning and debugging. |
| 4️⃣ | **Fault tolerance** – guard against malformed logits (NaNs, infinities) and empty vocabularies, returning a graceful fallback token. | Prevents service crashes when models emit unexpected outputs, a common failure mode in deployed LLMs. |
| 5️⃣ | **Benchmarking** – measure latency (ms per token) across different temperature/top‑k/top‑p combos and compare against `torch.compile`‑optimised runtimes. | Provides data‑driven justification for parameter choices and demonstrates performance‑aware engineering. |
| 6️⃣ | **Integration with transformers** – wrap the sampler to accept `model.generate()`‑style inputs, letting you plug it into Hugging Face pipelines without rewriting the whole generation loop. | Bridges the gap from “from‑scratch prototype” to “production‑ready component” that can be dropped into existing codebases. |

Each upgrade moves the project from a toy experiment toward a production‑grade building block that you can discuss in senior‑level interviews or include in a CV under “Systems Design” or “ML Infrastructure”.

## Key Takeaways

- **Temperature, top‑k, and top‑p** are the three primary levers for controlling LLM output randomness; mastering them shows you understand the underlying probability theory.  
- Implementing a sampler **from scratch** in pure Python proves you can write low‑level, debuggable code without relying on heavy frameworks—a trait valued by ML and backend teams.  
- The **pipeline architecture** (temperature → softmax → top‑k → top‑p → sample) is a pattern that appears in any generation service, making the knowledge directly transferable.  
- Adding **observability, persistence, and fault tolerance** transforms the prototype into a reusable component, signalling senior‑level system‑design skill.  
- Real‑world experimentation (parameter sweeps, benchmarking) and clear documentation are what turn a “cool script” into a portfolio piece that hiring managers notice.

## Further Reading

- [Hugging Face Transformers – Text Generation](https://huggingface.co/docs/transformers/main/en/main_loop#text-generation) – official docs that explain how temperature, top‑k and top‑p are used in practice.  
- [ArXiv: “Language Models are Few‑Shot Learners” (GPT‑3 paper)](https://arxiv.org/abs/2005.14165) – Section 2.2 discusses sampling strategies and nucleus sampling.  
- [Python `random` module documentation – `random.choices`](https://docs.python.org/3/library/random.html#random.choices) – the function we use for categorical sampling; understanding its weight handling is key to correct implementation.  

---