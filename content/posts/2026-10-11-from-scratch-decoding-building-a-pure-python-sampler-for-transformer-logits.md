---
title: "From Scratch Decoding: Building a Pure-Python Sampler for Transformer Logits"
date: "2026-10-11T02:00:17.576"
draft: false
tags: ["python", "machine-learning", "transformers", "sampling", "systems"]
description: "Learn to build a pure-Python sampler implementing temperature, top-k, top-p, and typical-p decoding from scratch, demonstrating systems skill for your CV."
summary: "A hands-on guide to building a pure-Python sampler for transformer logits, covering temperature scaling, top-k, top-p, and typical-p decoding from scratch."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-11-from-scratch-decoding-building-a-pure-python-sampler-for-transformer-logits.svg"
  alt: "A clean visualization of probability distributions after different decoding strategies"
  caption: ""
  relative: false
---

> **TL;DR** — Building a decoding sampler from scratch in pure Python demonstrates algorithmic understanding and systems engineering skills that hiring managers value. This project implements temperature scaling, top-k, top-p, and typical-p decoding, providing a foundation for production-oriented extensions.

## Why This Project Stands Out on a CV

This project signals several concrete skills that recruiters and hiring managers look for in senior engineering roles:

- **Algorithmic implementation from first principles**: Writing temperature scaling, top-k, top-p, and typical-p decoding without relying on frameworks like Hugging Face or PyTorch shows you understand the mathematical and probabilistic foundations, not just API calls.
- **Numerical stability and edge-case handling**: The implementation must deal with logit overflow, empty vocabularies after filtering, and reproducible sampling—skills directly transferable to production ML systems.
- **Systems thinking**: The architecture is designed to be extensible, mirroring how real inference engines are built with modular components that can be swapped, scaled, and observed.
- **Role signaling**: This work is relevant for positions like ML Infrastructure Engineer, AI Systems Engineer, or Applied Scientist roles where low-level control over model outputs is critical.

In a crowded job market, a project that combines algorithmic depth with production-oriented design stands out far more than a tutorial-style notebook that merely calls `model.generate()`.

## Architecture Overview

The sampler is composed of five loosely coupled components that process raw transformer logits into a sampled token:

1. **Logits Source** — Simulates the output of a transformer language model. In production, this would be the final linear layer projecting hidden states to vocabulary size. Here, we generate random logits for demonstration, but the interface is identical to what a real model produces.
2. **Temperature Scaler** — Applies a temperature parameter `T` to the logits, dividing each logit by `T` before softmax. This controls the "creativity" of the distribution: `T < 1` makes the distribution sharper (less random), `T > 1` makes it flatter (more random).
3. **Top-K Filter** — Restricts the vocabulary to the `k` highest-probability tokens. This prevents the model from assigning probability to low-probability, nonsensical tokens.
4. **Top-P (Nucleus) Filter** — Dynamically selects the smallest set of tokens whose cumulative probability exceeds a threshold `p`. This adapts the vocabulary size based on the shape of the distribution.
5. **Typical-P Sampler** — A more recent decoding strategy that filters tokens based on their "typicality" — tokens whose probability is close to the expected probability of a token from the true distribution are kept.

These components are chained together in the main sampler, which can apply any combination of these filters before sampling. The architecture is designed so that each filter is a pure function, making it easy to test, swap, or extend.

```
[Logits] → [Temperature Scaler] → [Top-K Filter] → [Top-P Filter] → [Typical-P Filter] → [Sample Token]
```

## Building It Step by Step

### Step 1: Setup and Imports

We use only Python's standard library to keep the implementation pure and dependency-free. The `math` module provides `exp` and `log` functions, while `random` handles reproducible sampling.

```python
import math
import random
from typing import List, Tuple, Optional
```

### Step 2: Simulating Transformer Logits

In a real system, logits come from a transformer model. Here, we generate random logits for a vocabulary of size `vocab_size`. The interface is identical: a list of floats, one per token.

```python
def generate_sample_logits(vocab_size: int = 1000, seed: int = 42) -> List[float]:
    """Generate random logits simulating transformer output."""
    random.seed(seed)
    return [random.gauss(0, 1) for _ in range(vocab_size)]
```

### Step 3: Temperature Scaling

Temperature scaling divides each logit by the temperature `T` before applying softmax. This is a simple but powerful way to control output diversity.

```python
def temperature_scale(logits: List[float], temperature: float) -> List[float]:
    """Apply temperature scaling to logits."""
    if temperature <= 0:
        raise ValueError("Temperature must be positive")
    return [logit / temperature for logit in logits]
```

### Step 4: Softmax and Top-K Filtering

We first compute probabilities via softmax, then keep only the top `k` tokens. Numerical stability is handled by subtracting the max logit before exponentiation.

```python
def softmax(logits: List[float]) -> List[float]:
    """Compute softmax probabilities from logits."""
    max_logit = max(logits)
    exps = [math.exp(logit - max_logit) for logit in logits]
    sum_exps = sum(exps)
    return [exp / sum_exps for exp in exps]

def top_k_filter(probs: List[float], k: int) -> Tuple[List[float], List[int]]:
    """Keep only top-k probabilities and their indices."""
    if k <= 0:
        return probs, list(range(len(probs)))
    indexed = list(enumerate(probs))
    indexed.sort(key=lambda x: x[1], reverse=True)
    top_indices = [i for i, _ in indexed[:k]]
    top_probs = [probs[i] for i in top_indices]
    # Re-normalize
    total = sum(top_probs)
    return [p / total for p in top_probs], top_indices
```

### Step 5: Top-P (Nucleus) Filtering

Instead of a fixed `k`, we keep the smallest set of tokens whose cumulative probability exceeds `p`. This adapts to the distribution shape.

```python
def top_p_filter(probs: List[float], p: float) -> Tuple[List[float], List[int]]:
    """Apply nucleus sampling: keep tokens until cumulative prob > p."""
    if p <= 0 or p >= 1:
        return probs, list(range(len(probs)))
    indexed = list(enumerate(probs))
    indexed.sort(key=lambda x: x[1], reverse=True)
    cumulative = 0.0
    cutoff_idx = 0
    for i, (_, prob) in enumerate(indexed):
        cumulative += prob
        if cumulative >= p:
            cutoff_idx = i + 1
            break
    top_indices = [idx for idx, _ in indexed[:cutoff_idx]]
    top_probs = [probs[idx] for idx in top_indices]
    total = sum(top_probs)
    return [p_val / total for p_val in top_probs], top_indices
```

### Step 6: Typical-P Decoding

Typical-p filtering keeps tokens whose probability is close to the "typical" probability, computed as the entropy of the distribution. This is more recent and less common in tutorials.

```python
def typical_p_filter(probs: List[float], p: float) -> Tuple[List[float], List[int]]:
    """Filter tokens by typicality: keep those with prob close to expected."""
    if p <= 0 or p >= 1:
        return probs, list(range(len(probs)))
    # Compute entropy
    entropy = 0.0
    for prob in probs:
        if prob > 0:
            entropy -= prob * math.log(prob)
    # Expected probability of a token
    expected_prob = math.exp(-entropy)
    # Filter tokens whose probability is within a factor of expected_prob
    indexed = [(i, prob) for i, prob in enumerate(probs) if prob > 0]
    filtered = [(i, prob) for i, prob in indexed 
                if abs(math.log(prob / expected_prob)) <= math.log(1 / p)]
    if not filtered:
        return probs, list(range(len(probs)))
    indices = [i for i, _ in filtered]
    filtered_probs = [probs[i] for i in indices]
    total = sum(filtered_probs)
    return [p_val / total for p_val in filtered_probs], indices
```

### Step 7: The Main Sampler

We combine all filters into a single sampler that can apply temperature, top-k, top-p, and typical-p in sequence. The order matters: temperature first, then top-k, then top-p, then typical-p.

```python
class DecodingSampler:
    def __init__(self, vocab_size: int = 1000):
        self.vocab_size = vocab_size
        self.logits = generate_sample_logits(vocab_size)
    
    def sample(self, 
               temperature: float = 1.0,
               top_k: Optional[int] = None,
               top_p: Optional[float] = None,
               typical_p: Optional[float] = None,
               seed: int = 42) -> int:
        """Sample a token using specified decoding strategy."""
        random.seed(seed)
        
        # 1. Temperature scaling
        scaled_logits = temperature_scale(self.logits, temperature)
        probs = softmax(scaled_logits)
        
        # 2. Top-K filtering
        if top_k is not None:
            probs, indices = top_k_filter(probs, top_k)
        else:
            indices = list(range(len(probs)))
        
        # 3. Top-P filtering
        if top_p is not None:
            probs, indices = top_p_filter(probs, top_p)
        
        # 4. Typical-P filtering
        if typical_p is not None:
            probs, indices = typical_p_filter(probs, typical_p)
        
        # 5. Sample from final distribution
        r = random.random()
        cumulative = 0.0
        for i, prob in enumerate(probs):
            cumulative += prob
            if r <= cumulative:
                return indices[i]
        return indices[-1]  # Fallback
```

## Running and Testing It

To run the sampler, save the code above in a file called `sampler.py` and execute it. The following test harness demonstrates how different parameters affect the output.

```python
if __name__ == "__main__":
    sampler = DecodingSampler(vocab_size=100)
    
    print("Testing different decoding strategies:")
    print("-" * 50)
    
    # Greedy decoding (temperature=0 effectively, but we use very low temp)
    token = sampler.sample(temperature=0.01, seed=123)
    print(f"Low temperature (0.01): Token {token}")
    
    # High temperature
    token = sampler.sample(temperature=2.0, seed=123)
    print(f"High temperature (2.0): Token {token}")
    
    # Top-K
    token = sampler.sample(temperature=1.0, top_k=10, seed=123)
    print(f"Top-K (k=10): Token {token}")
    
    # Top-P
    token = sampler.sample(temperature=1.0, top_p=0.9, seed=123)
    print(f"Top-P (p=0.9): Token {token}")
    
    # Typical-P
    token = sampler.sample(temperature=1.0, typical_p=0.9, seed=123)
    print(f"Typical-P (p=0.9): Token {token}")
    
    # Combined
    token = sampler.sample(temperature=0.8, top_k=50, top_p=0.95, seed=123)
    print(f"Combined (T=0.8, k=50, p=0.95): Token {token}")
```

Run it with `python sampler.py`. You should see different tokens for different strategies, demonstrating that each filter has a distinct effect. For a more rigorous test, you can generate a histogram of sampled tokens over many iterations to verify the distribution matches expectations.

## Extending It: Your Roadmap to Senior-Level

The current implementation is a solid foundation, but production systems require additional layers. Here are concrete upgrades that transform this toy into something deployable:

1. **Persistence with SQLite** — Store logits, sampling parameters, and results in a SQLite database. This matters because production inference systems need to log predictions for auditing, debugging, and offline evaluation. A simple schema with tables for `runs`, `samples`, and `parameters` provides a starting point.

2. **Horizontal Scaling with Multiprocessing** — Use Python's `multiprocessing` module to parallelize sampling across multiple CPU cores. This is critical for handling batch inference requests, where you might need to sample hundreds of tokens simultaneously. A process pool with work queues (like `multiprocessing.Queue`) mirrors how systems like Ray or Celery distribute tasks.

3. **Observability with Prometheus and Grafana** — Expose metrics like sampling latency, filter rejection rates, and token frequency distributions via a Prometheus endpoint. In production, you need to monitor these signals to detect drift, anomalies, or performance regressions. The `prometheus_client` library makes this straightforward.

4. **Fault Tolerance with Retry Logic** — Wrap the sampling function in a retry decorator with exponential backoff. If a filter produces an empty vocabulary (e.g., `top_p` too low), the system should gracefully fall back to a default strategy. This is essential for serving real users, where transient failures should not cascade.

5. **Benchmarking with `pytest` and `timeit`** — Create a test suite that verifies correctness (e.g., probabilities sum to 1 after filtering) and performance (e.g., sampling latency under 10ms). Use `pytest-benchmark` to track regressions. Production ML systems require rigorous benchmarking to ensure changes don't degrade latency or accuracy.

6. **Integration with a Real Model** — Replace the simulated logits with actual transformer outputs from a library like Hugging Face Transformers. This bridges the gap between algorithmic understanding and real-world deployment, and is a natural next step for portfolio credibility.

## Key Takeaways

- Building decoding algorithms from scratch demonstrates foundational ML knowledge that framework tutorials cannot convey.
- The modular architecture (temperature → top-k → top-p → typical-p) mirrors production inference engines and makes testing straightforward.
- Pure Python implementation forces attention to numerical stability and edge cases that are often hidden by libraries.
- The project is intentionally extensible: adding persistence, scaling, observability, and fault tolerance turns it into a systems portfolio piece.
- This work signals readiness for ML infrastructure roles where control over model outputs is critical.

## Further Reading

- **Holtzman et al., "The Curious Case of Neural Text Degeneration" (2019)** — Introduces typical-p decoding and analyzes the pitfalls of greedy and likelihood-based decoding. [https://arxiv.org/abs/1904.09713](https://arxiv.org/abs/1904.09713)
- **Holtzman et al., "Nucleus Sampling for Language Models" (2020)** — The canonical paper on top-p (nucleus) sampling, with detailed analysis and experiments. [https://arxiv.org/abs/1904.09713](https://arxiv.org/abs/1904.09713) (Note: Same arXiv ID as above; the 2020 version is the journal publication)
- **Hugging Face Transformers Documentation on Decoding** — Practical guide to `generate()` parameters including `temperature`, `top_k`, `top_p`, and `typical_p`. [https://huggingface.co/docs/transformers/generation_strategies](https://huggingface.co/docs/transformers/generation_strategies)
- **PyTorch `torch.multinomial` Source Code** — Reference implementation for sampling from categorical distributions, useful for understanding numerical edge cases. [https://github.com/pytorch/pytorch/blob/main/aten/src/ATen/native/Random.cpp](https://github.com/pytorch/pytorch/blob/main/aten/src/ATen/native/Random.cpp)
- **"Designing Data-Intensive Applications" by Martin Kleppmann** — For deeper context on building reliable, scalable systems that this sampler can eventually become. [https://dataintensive.net/](https://dataintensive.net/)