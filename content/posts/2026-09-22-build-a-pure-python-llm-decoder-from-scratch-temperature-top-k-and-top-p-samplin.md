---
title: "Build a Pure Python LLM Decoder from Scratch: Temperature, Top-k, and Top-p Sampling"
date: "2026-09-22T18:00:32.279"
draft: false
tags: ["LLM", "Python", "Systems", "Machine Learning", "Sampling", "Decoder"]
description: "Learn to build a pure Python LLM decoder with temperature scaling, top-k, and top-p sampling. Real, runnable code that demonstrates systems skill for hiring managers."
summary: "A hands-on guide to implementing temperature, top-k, and top-p sampling in pure Python, with runnable code that showcases systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-22-build-a-pure-python-llm-decoder-from-scratch-temperature-top-k-and-top-p-samplin.svg"
  alt: "Abstract visualization of token sampling probabilities"
  caption: ""
  relative: false
---

> **TL;DR** — Build a pure Python LLM decoder from scratch that implements temperature scaling, top-k, and top-p (nucleus) sampling. This project demonstrates core systems skills—probability, algorithm design, and low-level inference—that hiring managers recognize as foundational for ML and AI engineering roles. The code is real, runnable, and extensible.

Most engineers building LLM applications today rely on high‑level frameworks like Hugging Face Transformers or LangChain, which abstract away the token generation logic. But the moment you need to debug a hallucination, tune generation quality for a specialized domain, or explain why a model outputs a specific token, that abstraction becomes a wall. Understanding the sampling pipeline—how logits become probabilities, how temperature reshapes the distribution, and how top‑k and top‑p prune the tail—is the difference between calling an API and owning the inference stack.

This post is a hands‑on build guide. You will implement a complete, pure‑Python decoder that takes raw logits and produces tokens using temperature scaling, top‑k filtering, top‑p (nucleus) filtering, and multinomial sampling. No PyTorch, no TensorFlow, no external ML libraries—just the Python standard library. By the end you will have a portfolio piece that signals real systems skill to hiring managers.

## Why This Project Stands Out on a CV

A “build a chatbot with OpenAI” line on a résumé is table stakes. What recruiters actually scan for is evidence that you understand the *machinery* underneath:

- **Probability & statistics in practice** – You manipulate probability distributions, apply softmax, and work with cumulative sums and sampling without a framework doing it for you.
- **Algorithmic efficiency** – Top‑k and top‑p require sorting, thresholding, and renormalization. Implementing these on large vocabularies (50k+ tokens) forces you to think about O(n log n) vs. O(n) approaches.
- **Low‑level inference engineering** – You are effectively writing a custom inference kernel. This skill maps directly to roles where you optimize prompts, build custom sampling loops, or integrate LLMs into latency‑sensitive systems.
- **End‑to‑end ownership** – The project touches data flow (logits → probabilities → tokens), error handling, and deterministic seeding, all of which matter in production MLOps pipelines.

If you are targeting **Machine Learning Engineer**, **AI Engineer**, **MLOps Engineer**, or even **Systems Engineer** positions at companies building with LLMs (Anthropic, Cohere, Mistral, or internal teams at Meta/Google), this project gives you a concrete artifact to discuss in interviews. You can walk through the code and explain exactly how a model’s output distribution is shaped—something most candidates can only vaguely describe.

## Architecture Overview

The decoder is a small, focused pipeline with three components:

```
[Logits Source] ──► [Sampler] ──► [Token Output]
                       │
                       ├── Temperature Scaling
                       ├── Top‑k Filtering
                       ├── Top‑p (Nucleus) Filtering
                       └── Multinomial Sampling
```

1. **Logits Source** – In a real system this is the final layer of a transformer model (e.g., a 7B‑parameter LLM). For this project we simulate it with a random array of shape `(vocab_size,)` or, later, you can plug in a real model via Hugging Face. The key is that logits are raw, unnormalized scores.

2. **Sampler** – The heart of the project. It applies three transformations in sequence:
   - **Temperature scaling** – Divides logits by a temperature parameter `T > 0`, then applies softmax to get a probability distribution. High `T` flattens the distribution (more exploration); low `T` sharpens it (more greed).
   - **Top‑k filtering** – Keeps only the `k` highest‑probability tokens, zeroing out the rest, then renormalizes. This prevents the model from choosing rare, low‑quality tokens.
   - **Top‑p (nucleus) filtering** – Sorts tokens by probability descending, computes the cumulative sum, and keeps the smallest set whose cumulative probability exceeds `p`. This adapts the number of kept tokens dynamically based on the shape of the distribution.

3. **Token Output** – After filtering, a single token is drawn from the final distribution using multinomial sampling. In pure Python this is `random.choices` with weights equal to the filtered probabilities.

The flow is sequential: you can apply temperature alone, top‑k alone, top‑p alone, or combine them. The standard practice is temperature → top‑k → top‑p, though some systems swap top‑k and top‑p.

## Building It Step by Step

We will write a single Python file, `decoder.py`, that contains a `Sampler` class and a small demo. The code uses only the standard library (`math`, `random`, `itertools`).

### Step 1: Set up the skeleton

Create `decoder.py` and import the needed modules. We will also define a helper for the softmax function.

```python
import math
import random
from typing import List, Tuple

def softmax(logits: List[float]) -> List[float]:
    """Compute softmax probabilities from logits."""
    max_logit = max(logits)
    exps = [math.exp(l - max_logit) for l in logits]
    sum_exps = sum(exps)
    return [e / sum_exps for e in exps]
```

The `max_logit` subtraction is a numerical stability trick to prevent overflow when logits are large.

### Step 2: Temperature scaling

Add a method to the `Sampler` class that scales logits by temperature and returns the resulting probabilities.

```python
class Sampler:
    def __init__(self, vocab_size: int, seed: int = 42):
        self.vocab_size = vocab_size
        random.seed(seed)

    def temperature_scale(self, logits: List[float], temperature: float) -> List[float]:
        """Apply temperature scaling to logits and return probabilities."""
        if temperature <= 0:
            raise ValueError("Temperature must be > 0")
        scaled = [l / temperature for l in logits]
        return softmax(scaled)
```

A temperature of `1.0` leaves the distribution unchanged. Values below `1.0` make the distribution sharper; values above `1.0` make it flatter.

### Step 3: Top‑k filtering

Top‑k keeps only the `k` tokens with the highest probabilities. We need to find the kth largest probability, zero out anything below it, and renormalize.

```python
    def top_k_filter(self, probs: List[float], k: int) -> List[float]:
        """Keep only top‑k probabilities and renormalize."""
        if k <= 0 or k >= len(probs):
            return probs
        # Find the kth largest probability threshold
        sorted_probs = sorted(probs, reverse=True)
        threshold = sorted_probs[k - 1]
        filtered = [p if p >= threshold else 0.0 for p in probs]
        total = sum(filtered)
        if total == 0:
            return probs  # fallback, should not happen
        return [p / total for p in filtered]
```

This implementation is O(n log n) due to sorting. For a production system with a large vocabulary you would use a heap or partition to find the threshold in O(n).

### Step 4: Top‑p (nucleus) filtering

Top‑p dynamically selects a subset of tokens whose cumulative probability exceeds a threshold `p`. The number of tokens kept varies depending on the distribution.

```python
    def top_p_filter(self, probs: List[float], p: float) -> List[float]:
        """Keep the smallest set of tokens with cumulative probability >= p."""
        if p <= 0 or p >= 1:
            return probs
        # Sort tokens by probability descending
        sorted_pairs = sorted(enumerate(probs), key=lambda x: x[1], reverse=True)
        cumulative = 0.0
        keep_indices = set()
        for idx, prob in sorted_pairs:
            cumulative += prob
            keep_indices.add(idx)
            if cumulative >= p:
                break
        filtered = [probs[i] if i in keep_indices else 0.0 for i in range(len(probs))]
        total = sum(filtered)
        if total == 0:
            return probs
        return [f / total for f in filtered]
```

Nucleus sampling is particularly effective because it adapts to the shape of the distribution: when the model is confident, few tokens are kept; when it is uncertain, many tokens remain.

### Step 5: Multinomial sampling

With the final probability distribution, draw a single token.

```python
    def sample(self, probs: List[float]) -> int:
        """Sample a token index from the probability distribution."""
        return random.choices(range(len(probs)), weights=probs, k=1)[0]
```

`random.choices` uses the cumulative distribution method, which is O(n). For high‑performance sampling you would use the Gumbel‑max trick or alias sampling, but this is perfectly adequate for a portfolio project.

### Step 6: Putting it all together

Now we create a `generate` method that chains the filters and returns a token. We also add a demo that simulates logits and prints a few generated tokens.

```python
    def generate(
        self,
        logits: List[float],
        temperature: float = 1.0,
        top_k: int = 0,
        top_p: float = 1.0,
    ) -> int:
        """Full pipeline: temperature → top‑k → top‑p → sample."""
        probs = self.temperature_scale(logits, temperature)
        if top_k > 0:
            probs = self.top_k_filter(probs, top_k)
        if top_p < 1.0:
            probs = self.top_p_filter(probs, top_p)
        return self.sample(probs)


# --- Demo ---
if __name__ == "__main__":
    VOCAB_SIZE = 100
    sampler = Sampler(vocab_size=VOCAB_SIZE, seed=42)

    # Simulate logits from a model
    mock_logits = [random.gauss(0, 1) for _ in range(VOCAB_SIZE)]

    print("Generating 10 tokens with temperature=0.8, top_k=10, top_p=0.9")
    for _ in range(10):
        token = sampler.generate(mock_logits, temperature=0.8, top_k=10, top_p=0.9)
        print(f"Token: {token}")
```

Run it with `python decoder.py`. You will see a sequence of token indices. Change the temperature, top‑k, or top‑p values and observe how the diversity of the output changes.

## Running and Testing It

To run the project locally:

1. Save the code above as `decoder.py`.
2. Ensure you have Python 3.8+ installed.
3. Execute `python decoder.py`.

You should see 10 token indices printed. To verify the filters are working, add a small test that checks the shape of the probability distribution after each step. For example:

```python
def test_filters():
    s = Sampler(vocab_size=10, seed=0)
    logits = [1.0, 2.0, 3.0, 4.0, 5.0, 0.0, -1.0, -2.0, -3.0, -4.0]
    probs = s.temperature_scale(logits, temperature=0.5)
    assert len(probs) == 10
    assert all(p >= 0 for p in probs)
    assert abs(sum(probs) - 1.0) < 1e-6

    filtered_k = s.top_k_filter(probs, k=3)
    nonzero = sum(1 for p in filtered_k if p > 0)
    assert nonzero <= 3

    filtered_p = s.top_p_filter(probs, p=0.8)
    # At least one token should be kept
    assert any(p > 0 for p in filtered_p)
    print("All tests passed!")

test_filters()
```

This proves that each stage produces a valid probability distribution and that the filters correctly restrict the vocabulary.

## Extending It: Your Roadmap to Senior-Level

The basic decoder is a solid portfolio piece, but you can turn it into something that resembles a production inference engine. Here are six concrete upgrades, each with a one‑line reason it matters:

1. **Add a KV cache for autoregressive generation** – Store key‑value pairs from previous tokens to avoid recomputation, reducing latency from O(n²) to O(n) per token. *Matters because production LLMs serve multiple users and must minimize per‑token cost.*
2. **Integrate with a real model via Hugging Face Transformers** – Replace the mock logits with output from a small model like `distilgpt‑2`. *Matters because you need to prove the sampler works on actual model outputs, not synthetic data.*
3. **Batch multiple sequences for throughput** – Process multiple prompts in parallel by stacking logits into a matrix and vectorizing the filter operations with NumPy. *Matters because serving systems must handle concurrent requests efficiently.*
4. **Add observability with OpenTelemetry** – Emit metrics for sampling latency, filter rejection rates, and token distribution entropy. *Matters because debugging generation quality in production requires visibility into the sampling pipeline.*
5. **Implement fault‑tolerant retries with circuit breakers** – Wrap the generation loop in a retry mechanism that handles transient failures from a model server or GPU OOM. *Matters because inference is often the critical path in user‑facing applications.*
6. **Benchmark with a synthetic load test** – Use `locust` or a simple threaded script to measure tokens‑per‑second and p99 latency under varying concurrency. *Matters because hiring managers want evidence that your code can meet SLA targets.*

Each of these upgrades can be added incrementally and documented in your GitHub repo, turning a toy decoder into a showcase of production‑ready engineering.

## Key Takeaways

- Implementing temperature, top‑k, and top‑p sampling from scratch demonstrates probability manipulation, algorithm design, and low‑level inference skills that set you apart from API‑only practitioners.
- The pure‑Python approach forces you to confront numerical stability, distribution renormalization, and sampling correctness—topics that remain hidden behind frameworks.
- This project maps directly to ML Engineer, AI Engineer, and MLOps roles at companies building with LLMs, and gives you a concrete artifact to discuss in interviews.
- Extend it with KV caching, real model integration, batching, observability, fault tolerance, and benchmarking to signal senior‑level systems thinking.
- Always anchor your implementation to named tools (Hugging Face, OpenTelemetry, Locust) and concrete failure modes (GPU OOM, latency spikes) when discussing it with hiring managers.

## Further Reading

- **Nucleus Sampling (Top‑p)** – Holtzman et al., 2019. The original paper introducing top‑p filtering for more coherent text generation. [https://arxiv.org/abs/1904.09743](https://arxiv.org/abs/1904.09743)
- **Top‑k Sampling** – Fan et al., 2018. The work that popularized top‑k filtering for neural text generation. [https://arxiv.org/abs/1805.09080](https://arxiv.org/abs/1805.09080)
- **Hugging Face Transformers – Generation Utilities** – Canonical source for how a production library implements these samplers. Study `generate()` and `LogitsProcessor` for real‑world patterns. [https://huggingface.co/transformers/](https://huggingface.co/transformers/)
- **PyTorch Multinomial Documentation** – Understanding the underlying sampling primitive helps when optimizing for speed. [https://pytorch.org/docs/stable/generated/torch.multinomial.html](https://pytorch.org/docs/stable/generated/torch.multinomial.html)
- **OpenTelemetry for Python** – The standard for adding observability to your inference pipeline. [https://opentelemetry.io/docs/instrumentation/python/](https://opentelemetry.io/docs/instrumentation/python/)
- **Locust Load Testing Framework** – Use it to benchmark your decoder under concurrent load. [https://locust.io/](https://locust.io/)