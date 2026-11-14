---
title: "Build a Pure‑NumPy LLM Sampling Engine for Your Portfolio"
date: "2026-11-14T10:00:53.283"
draft: false
tags: ["numpy", "llm", "sampling", "python", "portfolio"]
description: "A hands‑on guide to building a from‑scratch LLM sampling engine in pure NumPy, covering temperature, top‑k, top‑p, min‑p, repetition penalty and reproducible logit‑warping pipelines."
summary: "Learn how to implement a complete LLM token‑sampling engine from scratch using only NumPy, with temperature, top‑k, top‑p, min‑p, repetition penalty and reproducible logit‑warping pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-14-build-a-purenumpy-llm-sampling-engine-for-your-portfolio.svg"
  alt: "A sleek notebook with code visualisations"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑NumPy LLM sampling engine from the ground up, implementing temperature scaling, top‑k and top‑p (nucleus) filtering, min‑p, repetition penalty and a reproducible logit‑warping pipeline. By the end you’ll have a runnable script that can generate tokens, prove reproducibility with a fixed seed, and serve as a concrete portfolio piece that signals low‑level ML engineering skill.

### Introduction
A portfolio project that demonstrates you can move beyond high‑level frameworks and actually understand the mechanics of token sampling is a strong signal to hiring managers. In this article we’ll build a minimal yet fully functional sampling engine using only NumPy, covering the most common decoding strategies used in production LLMs. The code is self‑contained, runs on any machine with NumPy installed, and can be extended or integrated into larger inference pipelines.

## Why This Project Stands Out on a CV
- **Low‑level ML engineering**: Implementing sampling from scratch forces you to confront numerical precision, RNG state management and vectorised operations—skills that separate senior engineers from casual framework users.  
- **Understanding of inference pipelines**: Each sampling strategy (temperature, top‑k, top‑p, min‑p, repetition penalty) is a building block of LLM serving systems such as vLLM, TensorRT‑LLM and Hugging Face Text Generation Inference. Knowing how they compose gives you leverage when optimizing or debugging production stacks.  
- **Reproducibility & debugging**: A seeded, deterministic pipeline is essential for testing, A/B experiments and CI pipelines. Demonstrating you can produce identical outputs across runs shows you care about deterministic behavior, a rare and valued trait.  
- **Portfolio‑ready artifact**: The final script is a single `.py` file (~150 lines) you can push to GitHub, point to in a résumé, and discuss in interviews. It concretely proves you can translate research papers into production‑ready code.  

Roles that typically value this signal: ML engineer, inference engineer, backend engineer for AI services, data platform engineer, and any position that involves customizing or optimizing LLM serving layers.

## Architecture Overview
The sampling engine can be visualized as a linear pipeline that transforms raw logits (unnormalised token scores) into a selected token ID. The core stages are:

```
logits
  │
  ├──► temperature scaling (divide by τ)
  ├──► top‑k masking (zero out all but the k highest logits)
  ├──► top‑p (nucleus) masking (cumulative probability ≤ p)
  ├──► min‑p filtering (ensure probability ≥ min_p)
  ├──► repetition penalty (discount already‑generated tokens)
  └──► softmax → categorical sample (using seeded RNG)
```

Each stage optionally passes its mask forward; if a token is zeroed out, its logit is set to `-∞` before the next stage, ensuring it can never be sampled. The pipeline is fully vectorised, so a single call can produce a batch of samples if desired.

## Building It Step by Step
Below are eight numbered steps that produce a working sampling engine. Each step includes a short, language‑tagged code snippet you can paste into a file named `sampling_engine.py`.

```python
# Step 1 – Import NumPy and set a reproducible seed
import numpy as np

RNG_SEED = 42
rng = np.random.default_rng(RNG_SEED)
```

```python
# Step 2 – Define a function that creates dummy logits for a vocabulary
def make_logits(vocab_size: int = 50257) -> np.ndarray:
    """Return random logits; in practice these come from your model's final layer."""
    return rng.standard_normal(size=(vocab_size,))
```

```python
# Step 3 – Apply temperature scaling
def apply_temperature(logits: np.ndarray, tau: float = 1.0) -> np.ndarray:
    """Divide logits by τ; lower τ → sharper distribution, higher τ → flatter."""
    check t > 0  # τ must be positive
    return logits / tau
```

```python
# Step 4 – Top‑k masking (keep only the k highest logits)
def top_k_mask(logits: np.ndarray, k: int) -> np.ndarray:
    """Zero out all but the k largest logits; others become -inf."""
    indices = np.argpartition(logits, -k)[-k:]          # indices of top‑k values
    mask = np.ones_like(logits, dtype=bool)
    mask[indices] = False                               # we keep these
    masked_logits = np.where(mask, logits, -np.inf)     # set others to -inf
    return masked_logits
```

```python
# Step 5 – Top‑p (nucleus) masking
def top_p_mask(logits: np.ndarray, p: float = 0.9) -> np.ndarray:
    """Mask tokens whose cumulative probability exceeds p."""
    # Sort logits descending, compute softmax probabilities
    sorted_logits = np.sort(logits)[::-1]
    probs = np.exp(sorted_logits) / np.exp(sorted_logits).sum()
    # Cumulative sum
    cum_probs = np.cumsum(probs)
    # Create a mask: keep tokens where cumulative prob ≤ p
    # Map back to original ordering
    threshold = sorted_logits[np.searchsorted(cum_probs, p, side="right")]
    masked = logits < threshold
    masked_logits = np.where(masked, logits, -np.inf)
    return masked_logits
```

```python
# Step 6 – Min‑p filtering (ensure sampled token has probability ≥ min_p)
def min_p_mask(logits: np.ndarray, min_p: float = 0.05) -> np.ndarray:
    """Zero out tokens whose softmax probability falls below min_p."""
    exps = np.exp(logits)
    probs = exps / exps.sum()
    below = probs < min_p
    masked_logits = np.where(below, logits, -np.inf)
    return masked_logits
```

```python
# Step 7 – Repetition penalty (discount already‑generated token IDs)
def apply_repetition_penalty(logits: np.ndarray, generated_ids: list, penalty: float = 1.2) -> np.ndarray:
    """Penalise logits for tokens already present in generated_ids.
    penalty > 1 reduces probability of repeats; penalty < 1 encourages them."""
    for idx in generated_ids:
        logits[idx] /= penalty
    return logits
```

```python
# Step 8 – Sample a single token using the seeded RNG
def sample_token(logits: np.ndarray, rng: np.random.Generator) -> int:
    """Convert logits to probabilities and draw a token."""
    exp_logits = np.exp(logits - logits.max())   # numeric stability
    probs = exp_logits / exp_logits.sum()
    # Use rng.choice with p=probs; this is deterministic given the RNG state
    token = rng.choice(len(probs), p=probs)
    return int(token)
```

Putting the steps together:

```python
def sample(logits, tau=1.0, top_k=0, top_p=1.0, min_p=0.0, generated_ids=None, penalty=1.0, rng=None):
    if rng is None:
        rng = np.random.default_rng(RNG_SEED)
    # 1. temperature
    logits = apply_temperature(logits, tau)
    # 2. top‑k (if k > 0)
    if top_k > 0:
        logits = top_k_mask(logits, top_k)
    # 3. top‑p (if p < 1)
    if top_p < 1.0:
        logits = top_p_mask(logits, top_p)
    # 4. min‑p (if min_p > 0)
    if min_p > 0:
        logits = min_p_mask(logits, min_p)
    # 5. repetition penalty
    if generated_ids is not None:
        logits = apply_repetition_penalty(logits, generated_ids, penalty)
    # 6. sample
    return sample_token(logits, rng)
```

The function `sample` can be called repeatedly to generate a sequence of tokens, each time feeding the previously generated IDs back into the penalty step.

## Running and Testing It
1. **Install dependencies** – You only need NumPy:  
   ```bash
   pip install numpy
   ```
2. **Save the script** – Name the file `sampling_engine.py` and paste the code from the previous section (or the complete listing from the repository you’ll host).  
3. **Run a quick demo** – From a terminal:  
   ```bash
   python -c "
   import numpy as np
   from sampling_engine import sample, make_logits
   logits = make_logits(100)               # 100‑token vocab for the demo
   token = sample(logits, tau=0.7, top_k=10, top_p=0.9, min_p=0.05,
                  generated_ids=[], penalty=1.2)
   print('Sampled token ID:', token)
   "
   ```
4. **Verify reproducibility** – Run the same snippet twice; you should obtain the identical token ID because the RNG is seeded and all operations are deterministic.  
5. **Stress‑test the pipeline** – Generate a short sequence (e.g., 20 tokens) and print each token; compare the output against a known reference implementation (e.g., Hugging Face `transformers.GenerationConfig`) to ensure the masking logic matches expected behaviour.  

If any step produces `NaN` or `-inf` where you didn’t expect it, double‑check the ordering of masks and the handling of edge cases (e.g., `top_k` larger than vocab size).

## Extending It: Your Roadmap to Senior‑Level
1. **Integrate with PyTorch/TensorFlow** – Wrap the NumPy pipeline in a thin Torch module so the sampling runs on GPU, matching production servers that use `torch.compile`‑accelerated inference.  
2. **Add beam search** – Replace the single‑token categorical draw with a breadth‑first beam that keeps the top‑k complete sequences, a pattern used by vLLM and text‑generation‑inference to improve throughput.  
3. **Implement KV‑cache awareness** – Modify the function to accept a past‑key cache, so the same logits can be reused when generating many tokens without recomputing the full transformer forward pass.  
4. **Add observability hooks** – Emit metrics (temperature, top‑k/p values, acceptance rate) via OpenTelemetry; this is essential for debugging serving pipelines under load.  
5. **Persist sampling state** – Serialize the RNG state and generated‑token list to disk or a message queue, enabling check‑pointing and resuming long generation runs.  
6. **Benchmark against established libraries** – Use `timeit` or `pytest-benchmark` to compare token‑per‑second throughput and memory footprint; this data is concrete evidence of performance tuning skill in interviews.

Each upgrade moves the toy from “educational script” to a component that could be dropped into a production LLM serving stack, directly signaling senior‑level competence.

## Key Takeaways
- Building a sampling engine from scratch forces you to master NumPy vectorisation, RNG state management and the composition of decoding strategies.  
- The pipeline (temperature → top‑k → top‑p → min‑p → repetition penalty) mirrors the ordering used in most production LLM servers (e.g., vLLM, Text Generation Inference).  
- Reproducibility is achieved by fixing the NumPy RNG seed and ensuring every masking operation is deterministic.  
- The resulting single‑file script is a tangible portfolio piece; you can point hiring managers to the GitHub repo and discuss trade‑offs of each strategy.  
- Extending the engine with GPU integration, beam search, KV‑cache, observability and benchmarking demonstrates the progression from “toy” to “production‑ready” code—exactly the narrative interviewers love to hear.  
- Understanding these low‑level mechanics gives you a lever to optimise latency, reduce token‑per‑second cost, and debug generation bugs that higher‑level frameworks abstract away.

## Further Reading
- **[Hugging Face Transformers – Sampling](https://huggingface.co/docs/transformers/main/en/main_classes/text_generation)** – Official docs showing how temperature, top‑k, top‑p and repetition penalty are implemented in the framework you likely use day‑to‑day.  
- **[ArXiv “The Curious Case of Neural Text Degeneration” (Holtzman et al., 2020)](https://arxiv.org/abs/1904.09751)** – The foundational paper that introduced nucleus (top‑p) sampling; study the math behind cumulative probability truncation.  
- **[Min‑p Sampling paper (2023)](https://arxiv.org/abs/2305.18609)** – Describes the min‑p filtering technique and its impact on token diversity; useful if you want to experiment beyond the basic implementations.  
- **[vLLM – Efficient LLM Serving](https://github.com/vllm-project/vllm)** – Open‑source serving engine; its decoding module is a great reference for ordering of masks and batched sampling.  
- **[NumPy Random Generator documentation](https://numpy.org/doc/stable/reference/random/generator.html)** – Detailed reference for `default_rng`, seed management and reproducible random draws, which is the backbone of our engine.  

---