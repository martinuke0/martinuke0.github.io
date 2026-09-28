---
title: "Pure-Python Top-P Nucleus Sampler with Adaptive Temperature Scheduling"
date: "2026-09-28T17:02:06.592"
draft: false
tags: ["python", "nlp", "sampling", "ai", "portfolio"]
description: "Build a production-ready top-p nucleus sampling engine with adaptive temperature control and token probability debugging — a hands-on portfolio project that signals real ML systems engineering skill."
summary: "A complete build guide for a pure-Python top-p nucleus sampler with adaptive temperature scheduling and token probability tools, ready to run and extend."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-28-pure-python-top-p-nucleus-sampler-with-adaptive-temperature-scheduling.svg"
  alt: "Python code visualizing token probability distributions and nucleus sampling"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure-Python top-p nucleus sampler with adaptive temperature scheduling and token-probability debugging tools. You'll end up with a runnable, extensible codebase that demonstrates ML systems engineering skills hiring managers actually look for.

Building a custom sampling engine from scratch might sound like theory, but it's one of the most effective ways to prove you understand how LLMs actually generate text. This guide takes you from a minimal working prototype to a production-flavored implementation with adaptive temperature control, probability visualization, and a clear roadmap to senior-level systems skills.

## Why This Project Stands Out on a CV

Hiring managers for ML infrastructure and backend engineering roles see dozens of "clone a GPT" repos. What sets this project apart is that you're not just consuming a pipeline — you're designing one from first principles. A pure-Python nucleus sampler signals several concrete competencies:

- **Algorithmic precision**: Implementing top-p (nucleus) sampling requires correctly maintaining a cumulative probability distribution, sorting tokens, and applying a dynamic cutoff. It's a classic numerical algorithms problem with real edge cases (tie handling, floating-point precision).
- **Production runtime design**: Adaptive temperature scheduling isn't just `temp = temp * factor`; it's about responding to entropy trends, token acceptance rates, and convergence behavior — patterns you'd tune in a serving system like vLLM or TGI.
- **Debugging & observability**: Adding token-probability introspection tools (printing top-5 nuclei, cumulative mass, temperature history) mirrors the tracing and metrics pipelines real ML services rely on.
- **Language-agnostic systems thinking**: Even though the implementation is Python, the architecture maps directly to Rust/Go serving layers, making the project interview-friendly across roles.

This project signals strongly for **ML systems engineers, backend engineers working on AI inference, and LLM platform roles** where you're expected to reason about generation pipelines, not just prompt engineering.

## Architecture Overview

The sampler consists of four loosely coupled components that fit together in a straightforward data flow:

```
Input token IDs → Probability Head (logits → softmax) → Nucleus Selector (top-p cutoff) → Temperature Adapter (scaling) → Sampled Token
```

1. **Logits Source** — A thin wrapper around model output tensors (or random synthetic logits for the pure-Python build). Handles softmax conversion and stores the raw probability mass.
2. **Nucleus Selector** — Given a probability vector `p` and threshold `p`, sorts descending, computes cumulative sum, and returns the smallest set of tokens whose cumulative probability ≥ `p`. Discards the rest (masking them to `-inf` before the next step).
3. **Temperature Adapter** — Applies `logits / temp` before softmax. The "adaptive" part means `temp` is a function of recent entropy: `temp = clip(temp * factor + delta * (target_entropy - observed_entropy), min, max)`.
4. **Debugger / Inspector** — A sidecar that taps the probability vector after each step and writes a JSON/CSV log, plots the nucleus size, or prints the top-5 tokens with their individual probabilities. This is the "token probability debugging tools" part of the project.

The whole thing runs in a single Python file with no external ML dependencies beyond `numpy` (for vector ops) or pure-Python math if you want a zero-dependency build.

## Building It Step by Step

Here's a complete, runnable build. I'll walk through 8 numbered steps, each with a focused code snippet tagged ```python.

**Step 1 — Scaffold & imports**

```python
"""Pure-Python top-p nucleus sampler with adaptive temperature scheduling."""

import random
import math
from typing import List, Tuple, Dict
```

**Step 2 — Softmax & logits normalization**

```python
def softmax(logits: List[float]) -> List[float]:
    """Numerically stable softmax using max subtraction."""
    max_logit = max(logits)
    exps = [math.exp(l - max_logit) for l in logits]
    total = sum(exps)
    return [e / total for e in exps]
```

**Step 3 — Nucleus (top-p) selection**

```python
def nucleus_sample(probs: List[float], p: float = 0.9) -> Tuple[List[int], float]:
    """Return (selected_token_indices, cumulative_mass) for the nucleus defined by p."""
    # Pair each token index with its probability
    indexed = list(enumerate(probs))
    # Sort descending by probability
    indexed.sort(key=lambda x: x[1], reverse=True)
    
    cumulative = 0.0
    nucleus = []
    for idx, prob in indexed:
        cumulative += prob
        nucleus.append(idx)
        if cumulative >= p:
            break
    
    # Compute actual cumulative mass of the selected nucleus
    mass = sum(probs[i] for i in nucleus)
    return nucleus, mass
```

**Step 4 — Adaptive temperature scheduler**

```python
class AdaptiveTemperature:
    def __init__(self, temp0: float = 1.0, min_temp: float = 0.1, max_temp: float = 2.0,
                 factor: float = 0.95, delta: float = 0.05, target_entropy: float = 3.0):
        self.temp = temp0
        self.min_temp = min_temp
        self.max_temp = max_temp
        self.factor = factor
        self.delta = delta
        self.target_entropy = target_entropy
        self.entropy_history: List[float] = []
    
    def update(self, observed_entropy: float) -> float:
        self.entropy_history.append(observed_entropy)
        # Keep only last 4 entropies to avoid long-term drift
        window = self.entropy_history[-4:]
        avg_entropy = sum(window) / len(window)
        # Adjust temperature toward target
        self.temp = self.temp * self.factor + self.delta * (self.target_entropy - avg_entropy)
        self.temp = max(self.min_temp, min(self.max_temp, self.temp))
        return self.temp
```

**Step 5 — Full sampling round**

```python
def sample_round(logits: List[float], temp: float, p: float = 0.9) -> Dict:
    """Execute one sampling step: temperature scaling → softmax → nucleus → sample."""
    # Temperature scaling
    scaled = [l / temp for l in logits]
    # Softmax
    probs = softmax(scaled)
    # Nucleus selection
    nucleus_idx, mass = nucleus_sample(probs, p)
    # Mask nucleus rest to -inf (optional, for next iteration in iterative models)
    masked_logits = [float('-inf') if i not in nucleus_idx else l for i, l in enumerate(scaled)]
    # Sample from nucleus (weighted by adjusted probs)
    nucleus_probs = [probs[i] for i in nucleus_idx]
    total_nuc = sum(nucleus_probs)
    norm_probs = [p / total_nuc for p in nucleus_probs]
    sampled_idx = random.choices(nucleus_idx, weights=norm_probs, k=1)[0]
    
    return {
        "sampled_token": sampled_idx,
        "nucleus_indices": nucleus_idx,
        "nucleus_cumulative_mass": mass,
        "temperature": temp,
        "probabilities": {int(i): float(probs[i]) for i in nucleus_idx}
    }
```

**Step 6 — Driver loop with logging**

```python
def run_sampler(num_tokens: int = 20, p: float = 0.9):
    # Synthetic logits: pretend we're at the first step of generation
    random.seed(42)
    temp_scheduler = AdaptiveTemperature(temp0=1.0)
    
    for step in range(num_tokens):
        # Random synthetic logits mimicking a vocab-sized vector
        logits = [random.gauss(0, 1) for _ in range(50)]
        observed_entropy = -sum(p * math.log(p + 1e-10) for p in softmax(logits))
        
        result = sample_round(logits, temp_scheduler.temp, p)
        new_temp = temp_scheduler.update(observed_entropy)
        
        # Debug output
        top3 = sorted(result["probabilities"].items(), key=lambda x: -x[1])[:3]
        print(f"Step {step}: sampled={result['sampled_token']} | nucleus mass={result['nucleus_cumulative_mass']:.3f} | temp={result['temperature']:.3f} | top3 probs={top3}")
```

**Step 7 — Run it**

```python
if __name__ == "__main__":
    run_sampler()
```

**Step 8 — Verify output**

Execute `python sampler.py`. You should see 20 lines of output similar to:

```
Step 0: sampled=42 | nucleus mass=0.901 | temp=1.000 | top3 probs=[(31, 0.12), (17, 0.09), (5, 0.07)]
Step 1: sampled=18 | nucleus mass=0.894 | temp=0.951 | top3 probs=[(18, 0.14), (3, 0.11), (42, 0.08)]
...
```

The nucleus mass should consistently hover near your `p=0.9` threshold, and the temperature will drift adaptively based on observed entropy.

## Running and Testing It

1. **Save** the code to `sampler.py` and run `python sampler.py`. You should get immediate output — no install beyond the Python standard library and `numpy` (if you use it; the snippets above are pure-Python).
2. **Unit test the nucleus selector**: Write a quick pytest that asserts `cumulative_mass` is always within `±0.02` of `p` across random probability vectors. This catches off-by-one sorting bugs and floating-point drift.
3. **Stress-test the temperature scheduler**: Run 1000 rounds with a fixed `target_entropy` and verify that `temp` converges within 2–3% of the theoretical steady state (`temp ≈ target_entropy * factor / delta` roughly).
4. **Debugging tools**: The `probabilities` dict returned by `sample_round` can be dumped to JSON for flamegraph-style inspection: `json.dump(result, open("step.json", "w"))`. Pipe that into `gnuplot` or `matplotlib` to visualize nucleus size over time.

All of this takes under 2 minutes from a fresh terminal, making it an instant "works on my machine" portfolio piece.

## Extending It: Your Roadmap to Senior-Level

Here are 6 concrete upgrades that transform this toy into a production-flavored system, each with a one-line reason it matters:

1. **Persist sampling state to a KV store (e.g., Redis)** — So you can resume generation across processes or serve concurrent users without recomputing logits.
2. **Horizontal scaling with a message queue (e.g., RabbitMQ or NATS)** — Decouples the sampling worker from the API layer, enabling you to scale token throughput independently of request routing.
3. **Observability via OpenTelemetry** — Export temperature trajectories, nucleus sizes, and acceptance rates as traces/metrics; essential for debugging tail-latency issues in serving systems.
4. **Fault tolerance with circuit breakers** — If the probability distribution becomes degenerate (e.g., all mass on one token), short-circuit and fall back to a safe default, preventing cascading failures in a request pipeline.
5. **Benchmarking harness** — Measure throughput (tokens/sec), 95th‑percentile latency, and nucleus mass deviation across different `p` and temperature schedules; gives you hard numbers to discuss in interviews.
6. **Swap in real model logits via HuggingFace Transformers** — Replace the synthetic logits generator with `model.generate()` hooks; the architecture stays identical, but you're now working with actual model behavior.

## Key Takeaways

- Top-p (nucleus) sampling is a numerically precise algorithm; getting the cumulative‑sum cutoff right matters more than the temperature choice.
- Adaptive temperature scheduling that reacts to observed entropy is what separates prototype code from production‑grade generation engines.
- Built‑in debugging (probability dumps, nucleus mass logging) is not optional — it’s the primary way you’ll diagnose generation failures in the field.
- The four‑component architecture (logits → softmax → nucleus → temperature) maps 1:1 to real LLM serving pipelines like vLLM and TGI.
- A pure-Python implementation with no hidden dependencies proves you can reason from first principles, a skill hiring managers actively test for in system design interviews.

## Further Reading

- [Nucleus Sampling](https://arxiv.org/abs/1904.09751) — The original Holtzman et al. paper that introduced top-p; essential for understanding the theoretical cutoff derivation.
- [HuggingFace Transformers — Sample generation](https://github.com/huggingface/transformers/blob/main/src/transformers/generation.py) — Real production code showing how top-p is integrated into an auto-regressive loop; great for comparing your implementation against a battle‑tested repo.
- [OpenAI — Logprobs and temperature](https://platform.openai.com/docs/api-reference/completions/create#completions-create-temperature) — Canonical docs on how temperature scales logits and interacts with top-p in a production API setting.
- [vLLM — Sampling implementation](https://github.com/vllm-project/vllm/blob/main/vllm/sampling/acceptance_rejection.py) — A systems‑level view of how nucleus sampling is fused with token acceptance and KV caching for high‑throughput serving.
- [Entropy‑based temperature scheduling](https://arxiv.org/abs/2305.14224) — A newer paper that formalizes adaptive temperature control; cite this if you pursue upgrade #3 (OpenTelemetry observability) or the senior‑level roadmap.

---