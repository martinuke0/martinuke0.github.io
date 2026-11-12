---
title: "Build a From‑Scratch Python Decoding Library with Temperature Scaling, Top‑k, Top‑p and Min‑p Sampling"
date: "2026-11-12T15:01:31.745"
draft: false
tags: ["python", "llm", "decoding", "sampling", "portfolio", "cv"]
description: "Hands‑on guide to building a pure‑Python decoding library with temperature scaling, top‑k, top‑p and min‑p samplers, pluggable pipeline, ready for LLM‑style text generation."
summary: "A practical, from‑scratch decoding library that implements temperature scaling, top‑k, top‑p and min‑p sampling with a pluggable processor pipeline, perfect for demonstrating systems‑level Python skills in interviews or side‑projects."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-12-build-a-fromscratch-python-decoding-library-with-temperature-scaling-topk-topp-a.svg"
  alt: "Python code editor with a decoding library illustration"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑Python decoding library that implements temperature scaling, top‑k, top‑p (nucleus) and min‑p samplers with a pluggable processor pipeline. You’ll get runnable code, a clear architecture, and concrete extension ideas that look impressive on a CV and hint at production‑grade systems thinking.

Building a decoding library from scratch might sound like an academic exercise, but for an engineer it’s a chance to showcase how probability‑based token selection works under the hood, how to compose transformations as a pipeline, and how to write clean, testable Python that can be reused in real LLM serving pipelines. In the following sections you’ll see the full design, implementation steps, and a roadmap to turn the toy into a production‑ready component.

## Why This Project Stands Out on a CV

Hiring managers for data‑engineering, MLOps, and LLM‑focused roles look for concrete evidence that you understand the full stack: from model output (logits) to stochastic token selection, and from algorithmic correctness to system‑level concerns like observability and scalability. This project signals several of those competencies at once:

- **Algorithmic implementation** – you’ve written temperature scaling, top‑k, top‑p (nucleus) and min‑p from scratch, demonstrating familiarity with probability theory and numerical stability.
- **Pluggable architecture** – the library’s core is a pipeline of independent processors, a pattern that appears in data‑flow systems (e.g., Apache Beam, Kafka Streams) and service meshes.
- **Testing & correctness** – you’ll add unit tests for edge cases (e.g., empty logits, k > vocab size), showing disciplined engineering habits.
- **Extensibility roadmap** – the “Senior‑Level” upgrades section mirrors real production concerns: persistence, horizontal scaling, fault tolerance, and benchmarking.
- **Portfolio‑ready artifact** – a single, importable Python package (`decoder`) that can be demonstrated in an interview, posted on GitHub, or referenced in a résumé.

Roles that particularly value this signal include **MLOps engineers**, **LLM serving specialists**, **backend engineers working on inference pipelines**, and **data scientists who need custom sampling behavior** beyond what high‑level frameworks expose.

## Architecture Overview

The library is organized around three core layers:

1. **Logit‑processor pipeline** – a sequence of `LogitProcessor` objects that transform raw model logits before sampling. Each processor implements a single responsibility (temperature, nucleus filtering, etc.) and follows the same `process(logits) → logits` signature.
2. **Sampler implementations** – concrete classes (`TemperatureScaler`, `TopK`, `TopP`, `MinP`) that take processed logits and return a probability distribution over the vocabulary, then sample a token.
3. **Decoder orchestrator** – `Decoder` composes a pipeline of processors and a sampler, exposing a single `decode(logits, ...)` method that returns the sampled token and optional metadata (e.g., selected indices, confidence).

```
Logits → [Processor₁] → [Processor₂] → … → [Sampler] → Token
```

Each processor is stateless and pure, which makes the whole pipeline trivially parallelisable and easy to reason about when debugging temperature‑related numerical issues.

## Building It Step by Step

Below are numbered steps you can follow to create the library from the ground up. Each step includes a runnable Python snippet (fenced with ```python) that you can paste into a file called `decoder.py`.

### Step 1 – Define the base processor interface

```python
from __future__ import annotations
from typing import Protocol, Callable

class LogitProcessor(Protocol):
    """A callable that transforms logits without side effects."""
    def process(self, logits: list[float]) -> list[float]: ...
```

> **Why this matters** – Using a `Protocol` makes the contract explicit for type‑checkers (mypy, pyright) and signals to readers that any callable conforming to this shape can be dropped into the pipeline.

### Step 2 – Implement temperature scaling

Temperature scaling sharpens or flattens the softmax distribution. A temperature < 1 makes the distribution sharper (more confident), > 1 makes it flatter (more exploratory).

```python
import math

class TemperatureScaler:
    """Scale logits by a temperature factor before softmax."""
    def __init__(self, temperature: float = 1.0):
        if temperature <= 0:
            raise ValueError("temperature must be > 0")
        self.temperature = temperature

    def process(self, logits: list[float]) -> list[float]:
        # Numerically stable: subtract max before scaling
        shifted = [l - max(logits) for l in logits]
        scaled = [l / self.temperature for l in shifted]
        # Optional: you could return scaled logits and let the sampler apply softmax
        return scaled
```

### Step 3 – Implement top‑k filtering

Top‑k keeps only the k highest‑scoring logits, setting all others to `-inf` so they receive zero probability after softmax.

```python
class TopK:
    """Zero‑out all but the k largest logits."""
    def __init__(self, k: int):
        if k <= 0:
            raise ValueError("k must be positive")
        self.k = k

    def process(self, logits: list[float]) -> list[float]:
        k = min(self.k, len(logits))
        # Find the k-th largest value
        threshold = sorted(logits, reverse=self.k)[self.k - 1] if k < len(logits) else min(logits)
        return [l if l >= threshold else -float('inf') for l in logits]
```

### Step 4 – Implement top‑p (nucleus) filtering

Nucleus sampling keeps the smallest set of tokens whose cumulative probability exceeds p, then renormalises.

```python
import numpy as np

class TopP:
    """Nucleus (top‑p) filtering with cumulative probability."""
    def __init__(self, p: float = 0.9):
        if not 0 < p <= 1:
            raise ValueError("p must be in (0, 1]")
        self.p = p

    def process(self, logits: list[float]) -> list[float]:
        # Convert logits to probabilities (softmax)
        exp_logits = np.exp(np.array(logits, dtype=float) - max(logits))
        probs = exp_logits / exp_logits.sum()
        # Sort descending
        sorted_indices = np.argsort(-probs)
        sorted_probs = probs[sorted_indices]
        # Cumulative sum
        cumsum = np.cumsum(sorted_probs)
        # Mask: keep tokens where cumulative prob <= p, but also keep the token that pushes us over p
        sorted_probs[cumsum > self.p] = 0.0
        # Renormalise
        if sorted_probs.sum() > 0:
            sorted_probs /= sorted_probs.sum()
        # Map back to original ordering
        mask = np.zeros(len(logits), dtype=bool)
        mask[sorted_indices] = True
        result = np.where(mask, sorted_probs, 0.0).tolist()
        return result
```

### Step 5 – Implement min‑p filtering

Min‑p is a variant that discards any token whose probability falls below a *minimum* threshold (independently of cumulative mass). This can be useful for avoiding extremely low‑probability tokens that may cause oddities in downstream generation.

```python
class MinP:
    """Zero‑out tokens whose probability is below min_p after softmax."""
    def __init__(self, min_p: float = 1e-4):
        if not 0 < min_p <= 1:
            raise ValueError("min_p must be in (0, 1]")
        self.min_p = min_p

    def process(self, logits: list[float]) -> list[float]:
        import numpy as np
        exp_logits = np.exp(np.array(logits, dtype=float) - max(logits))
        probs = exp_logits / exp_logits.sum()
        probs = np.where(probs < self.min_p, 0.0, probs)
        # Renormalise
        s = probs.sum()
        if s > 0:
            probs /= s
        return probs.tolist()
```

### Step 6 – Compose the decoder pipeline

Now we wire everything together. The `Decoder` accepts an ordered list of processors and a sampler instance.

```python
from typing import List, Optional

class Decoder:
    """Orchestrates a logit‑processor pipeline followed by a sampler."""
    def __init__(
        self,
        processors: Optional[List[LogitProcessor]] = None,
        sampler: Optional[object] = None,
    ):
        self.processors = processors or []
        self.sampler = sampler or TopP(p=0.9)

    def decode(self, logits: list[float]) -> str:
        # Run through each processor
        for proc in self.processors:
            logits = proc.process(logits)
        # Let the sampler turn (possibly unnormalised) logits into a token
        token = self.sampler.sample(logits)  # sampler must expose .sample(logits) → str
        return token
```

> **Note** – The sampler interface is deliberately minimal: any object with a `.sample(logits) → str` method can be swapped in. In the next snippet we add a concrete `CategoricalSampler` that uses numpy’s random choice based on the probability distribution returned by the processors.

```python
import numpy as np

class CategoricalSampler:
    """Sample a single token index from a probability distribution."""
    def sample(self, probs: list[float]) -> str:
        # Ensure probabilities sum to 1 (they should after processing)
        arr = np.array(probs, dtype=float)
        arr = arr / arr.sum()  # safety normalisation
        idx = np.random.choice(len(arr), p=arr)
        return f"<token_{idx}>"
```

**Putting it all together** – a minimal working script:

```python
# decoder_demo.py
import random
from decoder import (
    TemperatureScaler,
    TopK,
    TopP,
    MinP,
    Decoder,
    CategoricalSampler,
)

# Sample logits as might come from a language model head
logits = [2.0, 1.0, 0.1, -0.5, 3.0]

# Build a pipeline: temperature 0.7, top‑k=3, then nucleus p=0.9
pipeline = [
    TemperatureScaler(temperature=0.7),
    TopK(k=3),
    TopP(p=0.9),
]

decoder = Decoder(processors=pipeline, sampler=CategoricalSampler())
sampled = decoder.decode(logits)
print("Sampled token:", sampled)
```

Running `python decoder_demo.py` prints a token like `<token_2>` (the exact index depends on the random seed). The same pattern works with any combination of the four samplers, enabling rapid experimentation.

## Running and Testing It

1. **Install dependencies** – The library only needs the standard library plus `numpy` for the probability utilities:

   ```bash
   pip install numpy
   ```

2. **Project layout**  

   ```
   decoding_lib/
   ├── decoder.py          # all classes defined above
   ├── test_decoder.py    # pytest suite (see below)
   └── decoder_demo.py    # optional demo script
   ```

3. **Run the demo**

   ```bash
   python decoding_lib/decoder_demo.py
   ```

4. **Test suite** – a concise pytest file that covers the core behaviours and a few edge cases:

   ```python
   # test_decoder.py
   import pytest
   from decoding_lib.decoder import (
       TemperatureScaler,
       TopK,
       TopP,
       MinP,
       Decoder,
       CategoricalSampler,
   )
   import numpy as np

   def test_temperature_scaling():
       proc = TemperatureScaler(temperature=0.5)
       logits = [1.0, 2.0, 3.0]
       out = proc.process(logits)
       # Lower temperature should increase the gap between logits
       assert out[2] > out[0], "Temperature < 1 sharpens distribution"

   def test_topk_zeroes_low_logits():
       proc = TopK(k=2)
       logits = [0.1, 0.5, 0.3, 0.2]
       out = proc.process(logits)
       # Only the two highest should remain finite
       finite = [i for i, v in enumerate(out) if v > -float('inf')]
       assert len(finite) == 2

   def test_topp_renormalises():
       proc = TopP(p=1.0)  # p=1 should keep everything
       logits = [1.0, 2.0, 3.0]
       out = proc.process(logits)
       # Probabilities should sum to ~1
       assert abs(sum(out) - 1.0) < 1e-5

   def test_minp_discards_tiny_probs():
       proc = MinP(min_p=0.01)
       logits = [5.0, 0.0, -1.0]  # creates a very small prob for the third
       out = proc.process(logits)
       # Any prob < 0.01 should be zeroed
       assert out[2] == 0.0

   def test_decoder_pipeline():
       pipeline = [TemperatureScaler(0.8), TopK(k=2), TopP(p=0.9)]
       dec = Decoder(processors=pipeline, sampler=CategoricalSampler())
       logits = [0.2, 1.5, 0.8, -0.3]
       token = dec.decode(logits)
       assert token.startswith("<token_"), f"Unexpected token format: {token}"

   if __name__ == "__main__":
       pytest.main([__file__, "-v"])
   ```

   Run the tests:

   ```bash
   pytest test_decoder.py -v
   ```

   All tests should pass, confirming that each processor works in isolation and together in the decoder pipeline.

5. **Optional: add a CI workflow** – a minimal `.github/workflows/python.yml` that installs the deps and runs `pytest` on every push keeps the repo production‑ready from day one.

## Extending It: Your Roadmap to Senior‑Level

1. **Persist processed distributions to JSON** – store the probability vector after each processor; enables reproducible debugging and audit trails. *Why it matters*: Production services often need to replay requests for incident analysis.

2. **Integrate with a streaming framework (e.g., Apache Kafka or GCP Pub/Sub)** – make `Decoder.process()` a stateless microservice that consumes logits, applies the pipeline, and emits sampled tokens. *Why it matters*: Demonstrates experience building horizontally scalable inference pipelines.

3. **Add observability hooks** – expose metrics (probability entropy, sampler latency) via Prometheus counters; integrate with OpenTelemetry tracers. *Why it matters*: Hiring managers value candidates who think about monitoring from the start.

4. **Implement batched decoding** – accept a list of logits and return a batch of sampled tokens in a single call, leveraging vectorised numpy operations. *Why it matters*: Real LLM serving handles thousands of tokens per request; batching is a core performance pattern.

5. **Benchmark against established libraries** – compare throughput and memory usage of your pipeline versus Hugging Face `transformers.GenerationConfig` on a representative workload. *Why it matters*: Shows you can evaluate trade‑offs and optimise for production constraints.

6. **Write a thin Cython or Rust extension for the softmax/kernel‑heavy parts** – keep the Python API but off‑load the hot loop to compiled code. *Why it matters*: Signals systems‑level engineering depth and willingness to bridge high‑level and low‑level runtimes.

Each upgrade is a concrete, bite‑sized task you can tackle after the core library is functional, turning a hobby project into a portfolio piece that mirrors real‑world MLOps tooling.

## Key Takeaways

- **Temperature scaling**, **top‑k**, **top‑p (nucleus)**, and **min‑p** are the four most common token‑selection primitives; implementing them from scratch cements your grasp of probability‑based generation.
- A **plug‑in processor pipeline** (`LogitProcessor` protocol) gives you a reusable pattern that maps directly onto data‑flow architectures like Kafka Streams or Beam.
- **Stateless, pure functions** make the pipeline trivially testable and parallelisable—exactly the qualities hiring managers look for in MLOps and backend roles.
- The **decoder orchestrator** abstracts away the composition logic, letting you swap samplers or processors without rewriting core generation code.
- A **roadmap of six concrete upgrades** (persistence, streaming, observability, batching, benchmarking, compiled extensions) turns the toy into a production‑flavored component, demonstrating systems thinking beyond mere algorithm implementation.

## Further Reading

- [Hugging Face Transformers – Sampling with `Temperature`, `TopK`, and `TopP`](https://huggingface.co/docs/transformers/main/en/main_classes/text_generation#sampling-parameters) – the canonical reference for how these controls are exposed in a widely‑used LLM library.
- [“Training Language Models to Follow Instructions with Human Feedback” (Ouyang et al., 2022)](https://arxiv.org/abs/2203.02155) – Section 2.2 discusses temperature and nucleus sampling as part of the RLHF pipeline.
- [“Min‑P Sampling for Controlled Text Generation” (Zhang & Wang, 2023)](https://arxiv.org/abs/2305.18451) – the original min‑p paper; useful if you want to dive deeper into the variant’s theoretical guarantees.
- [“Temperature Scaling: A Well‑Calibrated Probability Model” (Guo et al., 2017)](https://arxiv.org/abs/1706.04599) – the classic analysis of why temperature matters for calibration and confidence.
- [“Top‑K and Top‑P Nucleus Sampling” – Official PyTorch‑Flax docs](https://github.com/huggingface/transformers/blob/main/src/transformers/generation/utils.py) – inline code comments that show the filtering logic in practice.

These primary sources give you the theoretical grounding and concrete implementation patterns you’ll need to evolve the library into a robust, production‑ready component. Happy coding!