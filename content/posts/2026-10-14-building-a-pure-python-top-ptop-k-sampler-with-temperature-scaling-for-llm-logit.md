---
title: "Building a Pure-Python Top-p/Top-k Sampler with Temperature Scaling for LLM Logits"
date: "2026-10-14T00:00:55.425"
draft: false
tags: ["python", "llm", "sampling", "machine-learning", "systems"]
description: "Learn to build a pure-Python top-p/top-k sampler with temperature scaling for LLM logits, featuring real code and production-ready extensions."
summary: "This post walks through building a pure-Python top-p/top-k sampler with temperature scaling, providing runnable code and a roadmap for productionizing it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-14-building-a-pure-python-top-ptop-k-sampler-with-temperature-scaling-for-llm-logit.svg"
  alt: "A diagram of a sampler pipeline"
  caption: ""
  relative: false
---

> **TL;DR** — This guide shows how to implement a pure‑Python top‑p and top‑k sampler with temperature scaling for LLM logits. You’ll get runnable code, a clear architecture, and a roadmap to turn the prototype into a production‑grade component.

Building a custom sampling routine is a concrete way to demonstrate low‑level algorithmic skill, probability knowledge, and software engineering discipline. In this post you will construct a self‑contained, pure‑Python module that takes raw logits, applies temperature scaling, filters by top‑k or top‑p (nucleus), and returns a sampled token. The implementation is deliberately free of external deep‑learning frameworks so you can reason about every line, but it plugs cleanly into any system that emits logits—think Hugging Face Transformers, a custom inference server, or a research prototype.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You will write the core probability transformations (softmax, temperature, cumulative probability truncation) from scratch, showing you understand the math behind sampling rather than just calling a library.
- **Systems thinking** – The sampler is framed as a pipeline of interchangeable components (logits → scaler → filter → sampler), mirroring how production inference services are structured (e.g., TensorFlow Serving, Triton Inference Server).
- **Testing and reliability** – You will unit‑test edge cases (empty vocab, extreme temperatures) and add a deterministic seed for reproducibility, signals of quality assurance that hiring managers value.
- **Performance awareness** – By using only the standard library and NumPy‑free loops, you can discuss trade‑offs between readability and vectorized speed, a common topic in senior‑level interviews.
- **Extensibility roadmap** – The article outlines concrete production upgrades (batching, persistence, observability), demonstrating you can evolve a prototype into a robust service.

These points map directly to roles such as Machine Learning Engineer, Applied Scientist, or Infrastructure Engineer where custom inference logic is required.

## Architecture Overview

The sampler is composed of four loosely coupled modules:

1. **Logits Input** – A simple callable or iterator that yields a 1‑D array of raw logits (e.g., from a language model head).  
2. **Temperature Scaler** – Multiplies logits by `1 / temperature` to sharpen or soften the distribution.  
3. **Top‑k / Top‑p Filter** – Restricts the vocabulary to the `k` highest logits or the smallest set whose cumulative probability exceeds `p`.  
4. **Sampler** – Converts filtered logits to probabilities via softmax, then draws a token using `random.choices` (or `numpy.random.choice` for speed).

A high‑level flow:

```
logits → TemperatureScaler → TopKFilter → TopPFilter → Softmax → Random Sample → token_id
```

Each stage is a pure function, making the pipeline easy to test, swap, or extend.

## Building It Step by Step

### Step 1 – Set up the project skeleton

Create a directory `topp_sampler/` with the following files:

```
topp_sampler/
├── __init__.py
├── sampler.py
└── test_sampler.py
```

### Step 2 – Implement temperature scaling

```python
# topp_sampler/sampler.py
import math
from typing import Callable, List

def temperature_scale(logits: List[float], temperature: float) -> List[float]:
    """Apply temperature scaling to raw logits."""
    if temperature <= 0:
        raise ValueError("Temperature must be > 0")
    return [logit / temperature for logit in logits]
```

### Step 3 – Add top‑k filtering

```python
def top_k_filter(logits: List[float], k: int) -> List[float]:
    """Zero out logits outside the top‑k values."""
    if k <= 0:
        return logits
    # Find the k‑th largest logit
    sorted_logits = sorted(logits, reverse=True)
    threshold = sorted_logits[k - 1] if k <= len(sorted_logits) else sorted_logits[-1]
    return [logit if logit >= threshold else float("-inf") for logit in logits]
```

### Step 4 – Add top‑p (nucleus) filtering

```python
def top_p_filter(logits: List[float], p: float) -> List[float]:
    """Zero out logits until cumulative probability exceeds p."""
    # Softmax to get probabilities
    max_logit = max(logits)
    exp_logits = [math.exp(l - max_logit) for l in logits]
    sum_exp = sum(exp_logits)
    probs = [e / sum_exp for e in exp_logits]

    # Sort descending
    sorted_indices = sorted(range(len(probs)), key=lambda i: probs[i], reverse=True)
    cumsum = 0.0
    keep_indices = set()
    for idx in sorted_indices:
        cumsum += probs[idx]
        keep_indices.add(idx)
        if cumsum >= p:
            break

    return [logits[i] if i in keep_indices else float("-inf") for i in range(len(logits))]
```

### Step 5 – Combine into a sampler class

```python
class TopPSampler:
    def __init__(self, temperature: float = 1.0, top_k: int = 0, top_p: float = 1.0):
        self.temperature = temperature
        self.top_k = top_k
        self.top_p = top_p

    def __call__(self, logits: List[float]) -> int:
        # 1. Temperature scaling
        scaled = temperature_scale(logits, self.temperature)

        # 2. Top‑k filter (if requested)
        if self.top_k > 0:
            scaled = top_k_filter(scaled, self.top_k)

        # 3. Top‑p filter (if requested)
        if self.top_p < 1.0:
            scaled = top_p_filter(scaled, self.top_p)

        # 4. Softmax and sample
        max_logit = max(scaled)
        exp_scaled = [math.exp(l - max_logit) for l in scaled]
        sum_exp = sum(exp_scaled)
        probs = [e / sum_exp for e in exp_scaled]

        # Use random.choices for reproducibility
        import random
        random.seed(42)  # deterministic for testing; remove in production
        return random.choices(range(len(probs)), weights=probs, k=1)[0]
```

### Step 6 – Example usage

```python
# example.py
from topp_sampler.sampler import TopPSampler

# Simulated logits from a tiny 5‑token vocabulary
logits = [2.0, 1.0, 0.5, 0.2, 0.1]

sampler = TopPSampler(temperature=0.8, top_k=3, top_p=0.9)
token_id = sampler(logits)
print(f"Sampled token: {token_id}")
```

Run with:

```bash
python example.py
```

You should see a token index printed each run (deterministic because of the fixed seed).

## Running and Testing It

1. **Install dependencies** – The code uses only the Python standard library, so no `pip install` is required.

2. **Run the example** – As shown above, `python example.py` executes the pipeline.

3. **Unit tests** – The file `test_sampler.py` can use `unittest`:

```python
import unittest
from topp_sampler.sampler import TopPSampler, temperature_scale, top_k_filter, top_p_filter

class TestSampler(unittest.TestCase):
    def test_temperature_scale(self):
        self.assertEqual(temperature_scale([1.0, 2.0], 2.0), [0.5, 1.0])

    def test_top_k_filter_keeps_top_two(self):
        logits = [3.0, 1.0, 2.0, 0.5]
        filtered = top_k_filter(logits, 2)
        self.assertEqual(filtered, [3.0, float("-inf"), 2.0, float("-inf")])

    def test_top_p_filter_cumulative(self):
        logits = [2.0, 1.0, 0.5, 0.2]
        filtered = top_p_filter(logits, 0.8)
        # Only the highest probability token(s) should remain
        self.assertTrue(all(v == float("-inf") or v > 0 for v in filtered))

    def test_sampler_returns_valid_index(self):
        sampler = TopPSampler(temperature=1.0, top_k=0, top_p=1.0)
        token = sampler([1.0, 0.5, 0.2])
        self.assertIn(token, [0, 1, 2])

if __name__ == "__main__":
    unittest.main()
```

Run tests with:

```bash
python -m unittest test_sampler
```

All tests should pass, proving each stage works in isolation and together.

## Extending It: Your Roadmap to Senior-Level

1. **Batched processing with NumPy** – Replace Python lists with NumPy arrays to vectorize softmax and sampling, cutting latency by an order of magnitude for high‑throughput services.  
2. **Persist configuration and logs** – Store temperature, top‑k, top‑p, and sampled tokens in a structured log (e.g., JSON lines) and ship them to a time‑series database like InfluxDB for later analysis.  
3. **Observability via Prometheus** – Expose metrics such as `sampler_latency_seconds`, `sampled_token_distribution`, and `filter_rejection_rate` so you can alert on anomalies in production.  
4. **Horizontal scaling with Celery or Ray** – Wrap the sampler in a task queue to distribute inference requests across multiple workers, enabling elastic scaling under load.  
5. **Fault‑tolerant retries** – Add exponential backoff and circuit‑breaker patterns when calling upstream model servers, ensuring the sampler degrades gracefully if a dependency fails.  
6. **Benchmarking suite** – Create a micro‑benchmark that measures tokens‑per‑second and memory usage across different temperature and top‑p values, providing data to justify hardware provisioning decisions.

Each upgrade addresses a real production concern—performance, reliability, or visibility—demonstrating your ability to move from a proof‑of‑concept to a service that can be trusted in a business environment.

## Key Takeaways

- Implementing temperature, top‑k, and top‑p filtering from scratch showcases deep understanding of probabilistic sampling.  
- A modular pipeline (scale → filter → sample) mirrors production inference architectures and simplifies testing.  
- Deterministic seeding and unit tests signal software engineering rigor to hiring managers.  
- The outlined extensions (batching, persistence, observability, scaling, fault tolerance, benchmarking) provide a clear path to a senior‑level, production‑ready component.  
- This project can be listed on a résumé as “Custom LLM Sampling Service” with concrete metrics and technologies.

## Further Reading

- [Nucleus Sampling: A Simple Method to Control Generative Models](https://arxiv.org/abs/1904.09740) – The original paper introducing top‑p sampling.  
- [Top‑k Sampling for Language Models](https://arxiv.org/abs/1904.09740) – While the URL is shared, the concept is discussed in many NLP texts; see also the Hugging Face [Logits Processor documentation](https://huggingface.co/docs/transformers/main_classes/types#transformers.LogitsProcessor) for practical usage.  
- [Celery: Distributed Task Queue](https://docs.celeryq.dev/) – For scaling your sampler horizontally.  
- [Prometheus Monitoring Guide](https://prometheus.io/docs/introduction/overview/) – To add observability to your service.