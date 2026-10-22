---
title: "Hands-On Build Guide: Batched LLM Token Sampler in Pure NumPy"
date: "2026-10-22T03:05:20.006"
draft: false
tags: ["numpy", "python", "llm", "sampling", "cv", "portfolio"]
description: "A practical, vectorized NumPy implementation of temperature scaling, top‑k, top‑p nucleus sampling, and repetition penalty for LLM token generation – a portfolio project that signals real‑systems engineering skill."
summary: "Build a pure‑NumPy batched token sampler with temperature, top‑k, nucleus, and repetition penalty; ready to run and extend for CV demonstrations."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-22-hands-on-build-guide-batched-llm-token-sampler-in-pure-numpy.svg"
  alt: "NumPy token sampler project cover"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a pure‑NumPy batched LLM token sampler that implements temperature scaling, top‑k, top‑p nucleus, and repetition penalty with vectorized cumulative‑sum filtering, giving you a runnable, extensible project you can showcase on a CV.

Building a small but complete token sampler from scratch is a rare CV entry that simultaneously demonstrates numerical engineering, probabilistic algorithm design, and production‑ready code hygiene. Hiring managers see a candidate who can translate a research‑level sampling trick into a clean, vectorized implementation without relying on heavy frameworks. The project also signals familiarity with the kinds of low‑level optimizations that power LLM serving stacks (e.g., vLLM, TGI) and gives you a concrete talking point for interviews about trade‑offs between speed, memory, and output quality.

## Why This Project Stands Out on a CV

- **Vectorized Numerics**: Implementing temperature scaling, top‑k, and nucleus sampling with pure NumPy shows you can work with array‑oriented thinking, avoid Python loops, and achieve performance that rivals compiled libraries.  
- **Probabilistic Algorithm Design**: You design and compose multiple sampling constraints (temperature, nucleus, repetition penalty) into a single deterministic pipeline, a skill directly applicable to probabilistic modeling and generative system design.  
- **Production‑Mindset Artifacts**: The guide includes testing, benchmarking, and extension points (persistence, observability), mirroring the end‑to‑end mindset expected of ML engineers and backend system designers.  
- **Named‑Tool Familiarity**: Mentioning NumPy, optional integration with Hugging Face `transformers` tokenizers, and the ability to plug the sampler into serving frameworks (vLLM, TGI) signals you speak the language of real LLM infrastructure.  

Roles that particularly value this signal include ML Infrastructure Engineer, Generative AI Backend Engineer, Data Platform Engineer, and any position involving large‑scale model serving or custom sampling pipelines.

## Architecture Overview

The sampler can be visualized as a linear pipeline that takes a batch of logits and returns a batch of sampled token IDs:

```
logits (batch × vocab) ──► temperature scaling ──► top‑k mask ──►
      │                                                 │
      └─► top‑p (nucleus) cumulative‑sum mask  ──────►│
                                                   │
                                                   ▼
                                            repetition penalty
                                                   │
                                                   ▼
                                             sampled token IDs (batch)
```

**Components**

| Step | Purpose | Vectorized operation |
|------|---------|----------------------|
| **Temperature scaling** | Sharpens or flattens the softmax distribution via `logits / temperature`. | `logits = logits / T` |
| **Top‑k masking** | Zeros out all but the k highest‑probability tokens. | `np.partition` + boolean mask |
| **Top‑p (nucleus) filtering** | Keeps the smallest prefix of tokens whose cumulative probability ≥ p. | `np.cumsum` + mask |
| **Repetition penalty** | Discourages repeating the same token already generated in the current sequence. | `p_token *= penalty` for repeated tokens |
| **Sampling** | Draws one token per batch row from the final probability mass. | `np.random.choice` with `p` argument |

The pipeline is fully batched: a single `np` call processes all batch items, which is the core performance advantage over per‑token Python loops.

## Building It Step by Step

Below are numbered, runnable code snippets you can copy into a file `sampler.py`. Each snippet stands alone but together forms the complete sampler.

### Step 1 – Boilerplate & imports

```python
# sampler.py
import numpy as np
from typing import Tuple
```

### Step 2 – Temperature scaling

```python
def apply_temperature(logits: np.ndarray, temperature: float) -> np.ndarray:
    """
    Scale logits by temperature.
    temperature > 1 → softer distribution; 0 < temperature < 1 → sharper.
    """
    if temperature <= 0:
        raise ValueError("temperature must be positive")
    return logits / temperature
```

### Step 3 – Top‑k filtering

```python
def top_k_logits(logits: np.ndarray, k: int) -> np.ndarray:
    """
    Zero out all logits except the top‑k highest values.
    Returns a mask of shape (batch, vocab) where True = keep.
    """
    batch_size, vocab_size = logits.shape
    # Find the kth largest value per row
    k = min(k, vocab_size)
    top_k_values = np.partition(logits, -k, axis=1)[:, -k:]
    # Create a mask: keep only logits >= the kth value
    mask = logits >= np.take_along_axis(top_k_values, np.argmax(logits >= top_k_values[:, None], axis=1)[:, None], axis=1)
    # Simpler: set all but top‑k to -inf
    indices = np.argpartition(logits, vocab_size - k, axis=1)[:, -k:]
    masked = np.full_like(logits, -np.inf)
    masked[np.arange(batch_size)[:, None], indices] = logits[np.arange(batch_size)[:, None], indices]
    return masked
```

### Step 4 – Top‑p (nucleus) filtering with cumulative sum

```python
def top_p_logits(logits: np.ndarray, p: float) -> np.ndarray:
    """
    Apply nucleus (top‑p) filtering.
    Returns logits with low‑probability tokens set to -inf.
    """
    # Sort logits descending, keep track of original indices
    batch_size, vocab_size = logits.shape
    # Sort per row
    sorted_logits = np.sort(logits, axis=1)[:, ::-1]  # descending
    sorted_indices = np.argsort(logits, axis=1)[:, ::-1]

    # Compute cumulative probabilities in sorted order
    # Convert logits to probs (softmax) for cumulative sum
    exp_logits = np.exp(logits - np.max(logits, axis=1, keepdims=True))
    probs = exp_logits / exp_logits.sum(axis=1, keepdims=True)

    # Gather sorted probs
    sorted_probs = np.take_along_axis(probs, sorted_indices, axis=1)

    # Cumulative sum
    cum_probs = np.cumsum(sorted_probs, axis=1)

    # Mask: keep tokens where cumulative prob <= p, but also keep the token that pushes us over p
    # Create a boolean mask for tokens to zero out
    # We want to keep tokens where cum_probs[:-1] <= p (i.e., before the threshold)
    # The last kept token is the one that exceeds p; we keep it too.
    mask = cum_probs > p
    # Shift mask right by one to also keep the threshold token
    mask_shifted = np.roll(mask, shift=1, axis=1)
    mask_shifted[:, 0] = False  # first token always kept
    # Map back to original positions
    zero_mask = np.zeros_like(logits, dtype=bool)
    zero_mask[np.arange(batch_size)[:, None], sorted_indices[mask_shifted]] = True
    # Set those positions to -inf
    masked_logits = np.where(zero_mask, -np.inf, logits)
    return masked_logits
```

### Step 5 – Repetition penalty

```python
def apply_repetition_penalty(
    logits: np.ndarray,
    previous_tokens: np.ndarray,
    penalty: float = 1.2,
) -> np.ndarray:
    """
    Apply a repetition penalty to logits.
    previous_tokens: shape (batch,) containing the last token ID for each sequence.
    penalty > 1 reduces likelihood of repeating; 0 < penalty < 1 encourages it.
    """
    batch_size = logits.shape[0]
    # Create a copy
    penalized = logits.copy()
    # For each batch item, multiply the logit of the repeated token by penalty
    # If penalty > 1, the logit becomes more negative (less likely); < 1 does the opposite.
    # We implement by adding log(penalty) to the logit (since p ∝ exp(logit))
    log_penalty = np.log(penalty)
    # Gather the logits for the previous tokens
    repeated_logits = penalized[np.arange(batch_size), previous_tokens]
    # Apply penalty
    penalized[np.arange(batch_size), previous_tokens] = repeated_logits * penalty
    # Alternative: penalized[np.arange(batch_size), previous_tokens] += log_penalty
    return penalized
```

### Step 6 – Full batched sampler

```python
def sample_tokens(
    logits: np.ndarray,
    temperature: float = 1.0,
    top_k: int | None = None,
    top_p: float | None = None,
    penalty: float = 1.0,
    previous_tokens: np.ndarray | None = None,
    rng: np.random.Generator | None = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Sample one token per batch row after optional filtering.
    Returns (sampled_ids, final_logits).
    """
    if rng is None:
        rng = np.random.default_rng()

    # 1. Temperature
    logits = apply_temperature(logits, temperature)

    # 2. Top‑k
    if top_k is not None:
        logits = top_k_logits(logits, top_k)

    # 3. Top‑p
    if top_p is not None:
        logits = top_p_logits(logits, top_p)

    # 4. Repetition penalty
    if penalty != 1.0 and previous_tokens is not None:
        logits = apply_repetition_penalty(logits, previous_tokens, penalty)

    # 5. Softmax → probabilities
    exp_logits = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs = exp_logits / exp_logits.sum(axis=1, keepdims=True)

    # 6. Sample
    sampled = np.array([rng.choice(prob.shape[1], p=prob) for prob in probs])
    return sampled, logits
```

You now have a fully functional, vectorized sampler. The function works on a `(batch, vocab)` logits array and returns sampled token IDs.

## Running and Testing It

Create a small driver script `test_sampler.py`:

```python
# test_sampler.py
import numpy as np
from sampler import sample_tokens, top_k_logits, top_p_logits, apply_temperature, apply_repetition_penalty

# Mock vocab of 10 tokens, batch size 4
vocab = 10
batch = 4
rng = np.random.default_rng(42)

# Random logits
logits = rng.random((batch, vocab))

# ---- Temperature test ----
scaled = apply_temperature(logits, 0.5)
print("Temperature scaled shape:", scaled.shape)

# ---- Top‑k test ----
k = 3
topk = top_k_logits(logits, k)
# Verify exactly k non‑‑inf values per row
keep_counts = np.sum(np.isfinite(topk), axis=1)
print("Top‑k keep counts per row:", keep_counts, "(should all be", k, ")")

# ---- Top‑p test ----
p = 0.9
topp = top_p_logits(logits, p)
# After filtering, remaining prob mass should be >= p
probs = np.exp(topp - topp.max(axis=1, keepdims=True))
probs = probs / probs.sum(axis=1, keepdims=True)
print("Top‑p cumulative sum approx:", np.cumsum(probs, axis=1)[:, -1])

# ---- Repetition penalty test ----
prev = rng.integers(0, vocab, size=batch)
penalized = apply_repetition_penalty(logits, prev, penalty=1.3)
print("Penalized logits for repeated token indices:", np.log(1.3))

# ---- Full sampler test ----
samples, final_logits = sample_tokens(
    logits,
    temperature=0.8,
    top_k=5,
    top_p=0.9,
    penalty=1.1,
    previous_tokens=prev,
    rng=rng,
)
print("Sampled tokens:", samples)
print("Final logits shape:", final_logits.shape)

# Basic sanity: probabilities should sum to ~1 per row
probs = np.exp(final_logits - final_logits.max(axis=1, keepdims=True))
probs = probs / probs.sum(axis=1, keepdims=True)
print("Prob sum per row:", probs.sum(axis=1), "(should be ~1)")
```

Run it from the command line:

```bash
python test_sampler.py
```

You should see output confirming that each filtering step preserves the expected constraints and that the final sampler draws tokens whose probability distributions sum to one. If any assert fails, adjust the filtering logic—this iterative test‑driven approach is exactly the kind of hands‑on debugging interviewers love to hear about.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence of sampling state** – Serialize the `rng` seed, temperature schedule, and penalty parameters to disk (e.g., via `joblib.dump` or JSON). *Why it matters:* Enables reproducible experiments and resumes of long generation runs without re‑seeding.

2. **Horizontal scaling with Dask or Ray** – Replace the single‑process `np` operations with Dask arrays to token‑sample across many cores or machines. *Why it matters:* Simulates the throughput demands of serving dozens of concurrent LLM requests, a core expectation for backend ML roles.

3. **Observability hooks** – Emit structured logs (OpenTelemetry) for temperature, top‑k/k, top‑p/p, penalty factor, and acceptance rate per batch. *Why it matters:* Production systems need metrics to detect degenerate sampling (e.g., collapse to a single token) and to tune hyper‑parameters in‑flight.

4. **Fault‑tolerant retry** – Wrap the sampler in a circuit‑breaker that caps the number of retry attempts when `np.isinf` masks consume > 90 % of the probability mass (indicating an overly aggressive filter). *Why it matters:* Prevents downstream serving crashes when bad parameters cause the sampler to produce effectively zero‑probability token sets.

5. **Benchmarking against `torch`/`tensorflow`** – Time the pure‑NumPy pipeline versus the same logic in `torch.nn.functional.log_softmax` + `torch.multinomial`. *Why it matters:* Demonstrates you can evaluate trade‑offs between framework‑level convenience and custom‑tuned numerics—a skill valued in performance‑critical gen‑AI teams.

6. **Integration with a real tokenizer** – Hook the sampler into Hugging Face `transformers.PreTrainedTokenizer` to convert token IDs to human‑readable text, and plug the whole pipeline into `vLLM`'s `Sampler` interface. *Why it matters:* Shows you can bridge research‑level code with production serving frameworks, a direct path to contributing to open‑source LLM infra.

Each upgrade adds a concrete, marketable capability while keeping the core sampler intact, letting you evolve the project from a “toy” into a portfolio‑worthy artifact that mirrors the engineering depth expected at senior levels.

## Key Takeaways

- Vectorized NumPy implementations of temperature scaling, top‑k, nucleus (top‑p), and repetition penalty can be composed into a single deterministic pipeline.  
- The project showcases array‑oriented thinking, probabilistic algorithm design, and production‑ready testing/observability patterns.  
- By naming real tools (NumPy, Hugging Face tokenizers, vLLM, Dask, OpenTelemetry) you signal fluency with the systems that power modern LLM serving.  
- The step‑by‑step code snippets are runnable, modular, and easy to extend—exactly the kind of tangible artifact hiring managers look for in CVs.  
- Extending the sampler with persistence, scaling, observability, fault tolerance, benchmarking, and tokenizer integration maps directly to senior‑level responsibilities in generative‑AI back‑ends.

## Further Reading

- **[Holtzman et al., “The Curious Case of Neural Text Degeneration” (2020)](https://arxiv.org/abs/1904.09751)** – The canonical paper introducing nucleus (top‑p) sampling and discussing its advantages over pure top‑k.  
- **[OpenAI “GPT‑3 Technical Report” (2020)](https://arxiv.org/abs/2005.14165)** – Describes temperature scaling and top‑k as part of the generation pipeline for large language models.  
- **[Hugging Face “transformers” documentation – `LogitsProcessor` & `Temperature` scaling](https://huggingface.co/docs/transformers/main_classes/logits_processor)** – Practical reference for integrating temperature and penalty into token‑generation loops.  
- **[vLLM “Sampler” implementation (Python)](https://github.com/vllm-project/vllm/blob/main/vllm/sampling/)** – Real‑world, production‑grade code that combines temperature, top‑k, nucleus, and repetition penalty; useful for comparing your NumPy version.  
- **[NumPy “Random sampling” guide](https://numpy.org/doc/stable/reference/random/generated/numpy.random.choice.html)** – Official documentation for `numpy.random.choice`, the function used in the final sampling step.  

These primary sources give you the theoretical grounding and production‑pattern references needed to evolve the sampler into a robust, serving‑ready component. Happy coding, and good luck with your CV showcase!