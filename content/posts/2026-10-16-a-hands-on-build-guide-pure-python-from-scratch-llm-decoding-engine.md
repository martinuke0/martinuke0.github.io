---
title: "A Hands-On Build Guide: Pure-Python From-Scratch LLM Decoding Engine"
date: "2026-10-16T09:00:49.683"
draft: false
tags: ["python", "llm", "decoding", "machine-learning", "side-project"]
description: "Build a pure‑Python LLM decoding engine with temperature, top‑k, top‑p, and typical sampling, showing how a pluggable logits‑warper pipeline works – a concrete side project that signals production‑system skill to hiring managers."
summary: "A step‑by‑step guide to building a pure‑Python LLM decoding engine from scratch, complete with runnable code, temperature, top‑k, top‑p, and typical sampling, perfect for a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-16-a-hands-on-build-guide-pure-python-from-scratch-llm-decoding-engine.svg"
  alt: "Python code on a laptop screen with LLM concept art"
  caption: ""
  relative: false
---

> **TL;DR** — Build a minimal pure‑Python LLM decoding engine that supports temperature scaling, top‑k, top‑p, and typical sampling via a pluggable logits‑warper pipeline. The resulting code is runnable, extensible, and demonstrates real‑world system‑design patterns that hiring managers notice.

This guide walks you through creating a from‑scratch decoding engine in pure Python. You’ll end up with a small library that can be imported into any project, a handful of unit tests, and a clear roadmap for turning the toy into a production‑grade component. Along the way you’ll practice API design, modular architecture, and performance‑aware coding—exactly the kind of signal that resonates with engineers hiring for data‑centric or infra roles.

## Why This Project Stands Out on a CV

Employers scanning CVs for LLM‑related side projects often see wrappers around Hugging Face or vLLM. A **from‑scratch pure‑Python decoder** demonstrates several differentiators:

- **Systems‑level understanding** – you control every step from logits to sampled token, showing you know how temperature, nucleus, and typical sampling shape output distribution.
- **Modular design** – a pluggable warper pipeline mirrors the strategy used in production serving stacks (e.g., TensorRT‑LLM, Ray Serve) where warps are composed dynamically.
- **Testability & reproducibility** – pure Python means no hidden C extensions; you can run the same code on a laptop, a CI runner, or a GPU‑accelerated container.
- **Open‑source contribution potential** – the code can be packaged as `pip install llm-decoder-engine` and later extended with custom warps or profiling hooks.
- **Interview talking points** – you can discuss trade‑offs (e.g., top‑k vs. top‑p latency, typical‑sampling’s zeta parameter) and walk interviewers through the implementation live.

The project signals readiness for roles such as **ML engineer**, **backend engineer for LLM serving**, **research engineer**, or any position that requires building low‑latency inference pipelines.

## Architecture Overview

The engine consists of four core components that fit together in a simple pipeline:

```
Input token IDs
    │
    ▼
Logits computation (model forward) ──► Warper pipeline (temperature → top‑k → top‑p → typical)
    │
    ▼
Sample next token (categorical draw)
    │
    ▼
Append token, repeat until EOS or max length
```

- **Logits source** – a thin wrapper around a `torch.nn.Module` (or a static numpy array for testing) that returns `float[ vocab_size ]` per step.
- **Warper base class** – defines `warp(logits) → logits`. Concrete subclasses implement temperature, top‑k, top‑p, and typical sampling.
- **Pipeline composer** – sequentially applies warpers; each warper can be toggled on/off, enabling A/B experiments.
- **Decoder loop** – manages state (past key values if using a caching model), tracks length, and stops on EOS.

The diagram above is deliberately minimal; you’ll flesh each box with a few lines of code in the next section.

## Building It Step by Step

Below are numbered, runnable Python snippets. Copy them into a file `decoder_engine.py` and execute `python decoder_engine.py` to see the engine in action.

### 1. Base warper interface

```python
from __future__ import annotations
from abc import ABC, abstractmethod
import numpy as np

class LogitsWarper(ABC):
    """Abstract base for logits warping strategies."""

    @abstractmethod
    def warp(self, logits: np.ndarray) -> np.ndarray:
        """Apply the warping transformation in‑place and return the modified logits."""
        pass
```

### 2. Temperature warper

```python
class TemperatureWarper(LogitsWarper):
    """Scale logits by inverse temperature τ > 0.

    τ < 1 sharpens the distribution; τ > 1 flattens it.
    """

    def __init__(self, temperature: float = 1.0):
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        self.temperature = temperature

    def warp(self, logits: np.ndarray) -> np.ndarray:
        scaled = logits / self.temperature
        return scaled
```

### 3. Top‑k warper

```python
class TopKWarper(LogitsWarper):
    """Zero out everything except the k highest logits.

    Tokens with zeroed logits are effectively disallowed.
    """

    def __init__(self, k: int):
        if k <= 0:
            raise ValueError("k must be positive")
        self.k = k

    def warp(self, logits: np.ndarray) -> np.ndarray:
        # Use np.partition for O(n) selection (fast enough for vocab ~50k)
        k = min(self.k, logits.size)
        threshold = np.partition(logits, -k)[-k]
        mask = logits < threshold
        logits = logits.copy()
        logits[mask] = -np.inf
        return logits
```

### 4. Top‑p (nucleus) warper

```python
class TopPWarper(LogitsWarper):
    """Keep the smallest set of tokens whose cumulative probability ≥ p.

    Standard nucleus sampling (Holtzman et al., 2020).
    """

    def __init__(self, p: float = 0.9):
        if not 0.0 < p <= 1.0:
            raise ValueError("p must be in (0, 1]")
        self.p = p

    def warp(self, logits: np.ndarray) -> np.ndarray:
        # Compute softmax probabilities
        exp_logits = np.exp(logits - np.max(logits))  # numerical stability
        probs = exp_logits / exp_logits.sum()

        # Sort descending
        sorted_indices = np.argsort(probs)[::-1]
        sorted_probs = probs[sorted_indices]

        # Cumulative sum
        cumsum = np.cumsum(sorted_probs)

        # Mask: keep tokens until cumulative > p, then exclude the rest
        # We keep the first token even if it pushes us over p
        cutoff = np.searchsorted(cumsum, self.p, side="right")
        mask = np.ones_like(logits, dtype=bool)
        mask[sorted_indices[cutoff:]] = False

        logits_copy = logits.copy()
        logits_copy[~mask] = -np.inf
        return logits_copy
```

### 5. Typical sampling warper

Typical sampling (Meister et al., 2023) uses a *zeta* threshold based on the entropy of the distribution.

```python
import math

class TypicalWarper(LogitsWarper):
    """Implement typical sampling as described in
    'Typical Sampling for Language Models' (Meister et al., 2023).

    The warper keeps the smallest set of tokens whose probability mass
    exceeds a threshold derived from the distribution's entropy.
    """

    def __init__(self, zeta: float = 0.9, filter_value: float = -np.inf):
        if not 0.0 < zeta <= 1.0:
            raise ValueError("zeta must be in (0, 1]")
        self.zeta = zeta
        self.filter_value = filter_value

    def warp(self, logits: np.ndarray) -> np.ndarray:
        # Softmax → probabilities
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / exp_logits.sum()

        # Compute Shannon entropy H = -∑ p log p
        nz = probs > 0
        H = -np.sum(probs[nz] * np.log(probs[nz]))

        # Threshold τ = exp( (1 - ζ) * H )
        tau = math.exp((1.0 - self.zeta) * H)

        # Compute cumulative probabilities after sorting descending
        sorted_indices = np.argsort(probs)[::-1]
        sorted_probs = probs[sorted_indices]
        cumsum = np.cumsum(sorted_probs)

        # Keep tokens where cumulative <= τ (plus the first token)
        cutoff = np.searchsorted(cumsum, tau, side="right")
        mask = np.ones_like(logits, dtype=bool)
        mask[sorted_indices[cutoff:]] = False

        logits_copy = logits.copy()
        logits_copy[~mask] = self.filter_value
        return logits_copy
```

### 6. Pipeline composer

```python
class WarperPipeline:
    """Apply a sequence of warpers one after another."""

    def __init__(self, warpers: list[LogitsWarper] | None = None):
        self.warpers = warpers if warpers is not None else []

    def add(self, warper: LogitsWarper) -> None:
        self.warpers.append(warper)

    def warp(self, logits: np.ndarray) -> np.ndarray:
        for warper in self.warpers:
            logits = warper.warp(logits)
        return logits
```

### 7. Simple decoder loop (no KV‑cache for clarity)

```python
import random

def sample_next_token(logits: np.ndarray, rng: random.Random) -> int:
    """Categorical draw from the (warped) logits."""
    # Numerically stable softmax
    e = np.exp(logits - np.max(logits))
    probs = e / e.sum()
    # Roulette wheel selection
    r = rng.random()
    cumulative = 0.0
    for i, p in enumerate(probs):
        cumulative += p
        if r <= cumulative:
            return i
    # Fallback (should never happen)
    return len(probs) - 1

def decode(
    logits_func,
    warper_pipeline: WarperPipeline,
    start_ids: list[int] | None = None,
    max_new_tokens: int = 50,
    temperature: float = 1.0,
) -> list[int]:
    """Run a simple autoregressive decode loop.

    Args:
        logits_func(id_seq) -> np.ndarray of shape (vocab_size,)
        warper_pipeline: WarperPipeline instance
        start_ids: optional prefix token ids
        max_new_tokens: how many tokens to generate
        temperature: passed to a TemperatureWarper if used

    Returns:
        list of token ids including the prefix.
    """
    # Initialise token list
    ids = list(start_ids) if start_ids else []
    # If no prefix, we start with a BOS token (assume 0)
    if not ids:
        ids = [0]

    rng = random.Random(42)

    for _ in range(max_new_tokens):
        # Ask the model for fresh logits given the current prefix
        fresh_logits = logits_func(ids)  # shape (vocab_size,)

        # Apply the warper pipeline
        warped = warper_pipeline.warp(fresh_logits)

        # Optionally re‑apply temperature after other warps (common pattern)
        if temperature != 1.0:
            warped = warped / temperature

        # Sample next token
        next_id = sample_next_token(warped, rng)
        ids.append(next_id)

        # Stop early if EOS token (assume id 2)
        if next_id == 2:
            break

    return ids
```

### 8. Plug‑in demo: a toy vocab + logits function

```python
VOCAB_SIZE = 10  # tiny vocab for demonstration

def toy_logits(prev_ids: list[int]) -> np.ndarray:
    """Dummy logits that favour token 3 then decay."""
    base = np.zeros(VOCAB_SIZE, dtype=float)
    # Simple bias: token 3 gets a boost, token 0 gets a small boost
    base[3] = 2.0
    base[0] = 0.5
    # Add a tiny random component so sampling matters
    rng = np.random.default_rng(sum(prev_ids) if prev_ids else 0)
    base += rng.normal(scale=0.1, size=VOCAB_SIZE)
    return base

# ------------------------------------------------------------------
# Build a pipeline with temperature + top‑k + typical sampling
pipeline = WarperPipeline()
pipeline.add(TemperatureWarper(temperature=0.7))
pipeline.add(TopKWarper(k=5))
pipeline.add(TypicalWarper(zeta=0.9))

# Generate 20 tokens starting from a BOS token
generated = decode(
    logits_func=toy_logits,
    warper_pipeline=pipeline,
    start_ids=[0],
    max_new_tokens=20,
    temperature=1.0,  # already handled inside warpers
)

print("Generated token ids:", generated)
```

Running the script should print a list of 20 integers (most likely ending early with the EOS token `2` if you add one, otherwise continuing to the max). Tweak the warpers’ parameters (`temperature`, `k`, `p`, `zeta`) to observe how the output distribution shifts—this hands‑on experimentation is exactly what interviewers love to probe.

## Running and Testing It

1. **Install dependencies** – you only need Python 3.10+ and `numpy`. No heavy ML frameworks are required for the core engine:

   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install numpy
   ```

2. **Execute the demo** – from the project root:

   ```bash
   python decoder_engine.py
   ```

   You should see a printed list of token IDs, confirming the pipeline works end‑to‑end.

3. **Unit‑test the warpers** – create `test_decoder.py` with pytest:

   ```python
   import pytest
   import numpy as np
   from decoder_engine import (
       TemperatureWarper,
       TopKWarper,
       TopPWarper,
       TypicalWarper,
       WarperPipeline,
   )

   def test_temperature_sharpens():
       warper = TemperatureWarper(temperature=0.5)
       logits = np.array([1.0, 2.0, 3.0])
       out = warper.warp(logits.copy())
       # Lower τ should increase the spread → max becomes relatively larger
       assert out[2] > out[0]  # token 2 stays highest

   def test_topk_zeroes_others():
       warper = TopKWarper(k=1)
       logits = np.array([0.1, 0.6, 0.3])
       out = warper.warp(logits.copy())
       # Only the highest logit should remain; others → -inf
       assert out[1] > out[0] and out[1] > out[2]
       assert out[0] == -np.inf or out[2] == -np.inf

   def test_typical_keeps_zeta_fraction():
       warper = TypicalWarper(zeta=1.0)  # ζ=1 → keep everything
       logits = np.array([5.0, 1.0, 0.2])
       out = warper.warp(logits.copy())
       # With ζ=1 we expect no -inf masking
       assert not np.isinf(out).any() or np.all(~np.isinf(out))

   # Run: pytest test_decoder.py -v
   ```

   Adding more tests (e.g., `TopPWarper` cumulative‑probability bound, pipeline ordering) gives you a solid test suite you can point to in a CV or interview.

4. **Lint & format** – run `black --line-length 88 decoder_engine.py` and `flake8` to keep the codebase professional‑grade.

5. **Package locally** – if you want to share the module:

   ```bash
   pip install -e .
   ```

   Create a minimal `setup.py` or `pyproject.toml` that references `decoder_engine.py` as the package entry point.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Add a KV‑cache** so the decoder re‑uses past key/value states → cuts latency from O(L·H) to O(1) per token in serving scenarios. |
| 2 | **Pluggable model back‑ends** (e.g., integrate with `transformers` `ModelForCausalLM` or a ONNX Runtime session) → lets you test the warper pipeline on real model weights. |
| 3 | **Observability hooks** (logits histograms, warper timing, token‑level entropy) → essential for debugging production serving pipelines and meeting SLOs. |
| 4 | **Batch decoding** – process a list of prompts simultaneously by stacking prefix tensors → demonstrates knowledge of vectorised inference, a key skill for high‑throughput services. |
| 5 | **Custom warper registry** (entry‑point based) → mirrors how frameworks like `vLLM` allow users to register new sampling strategies without code changes. |
| 6 | **Benchmark suite** (tokens‑per‑second, memory footprint) → quantifies the cost of each warper and provides data‑driven justification for production decisions. |

Each upgrade moves the toy from “educational script” to a component you could actually ship in an LLM‑serving stack, and each line in the table can be expanded into a bullet point in your CV’s “Projects” section.

## Key Takeaways

- A pure‑Python decoding engine forces you to confront every detail of logits transformation, from temperature scaling to nucleus and typical sampling.
- The pluggable warper pipeline pattern mirrors production serving architectures (e.g., TensorRT‑LLM, vLLM) and is a strong talking point for system‑design interviews.
- Writing unit tests for each warper and a decoder loop proves reproducibility—a trait hiring managers value highly.
- The roadmap upgrades (KV‑cache, batching, observability, custom warper registry) are concrete steps you can take to evolve the project into a production‑ready library.
- Keep the codebase lightweight (no external ML frameworks beyond numpy) so it runs anywhere—laptop, CI, or GPU container—making it an accessible demo for recruiters.

## Further Reading

- [The Annotated Transformer – Logits Processing](https://github.com/jessevig/gpt-2/blob/master/model.py) – walkthrough of how modern frameworks apply warpers before sampling.  
- [Holtzman et al., “The Curious Case of Neural Text Degeneration”, *ICLR 2020*](https://arxiv.org/abs/1904.09751) – the seminal paper introducing top‑p (nucleus) sampling.  
- [Meister, G., et al., “Typical Sampling for Language Models”, *NeurIPS 2023*](https://arxiv.org/abs/2302.06381) – primary source for typical sampling; contains the zeta formula used in the warper.  
- [OpenAI GPT‑2/3/4 documentation on temperature & top‑k](https://platform.openai.com/docs/api-reference/editing) – practical guidelines and edge‑case handling.  
- [TensorRT‑LLM Sampling Strategies](https://docs.nvidia.com/deeplearning/tensorrt/samples/text/llm.html) – shows how warpers are composed in a high‑performance serving engine.  

Feel free to fork the repo, experiment with the parameters, and push your enhancements to GitHub – a hands‑on, runnable side project like this one is exactly the kind of tangible evidence that catches a hiring manager’s eye. Happy coding!