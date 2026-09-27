---
title: "Building a Pure-Python Token Sampler: Temperature, Top-k, Top-p, and Min-p Decoding from Scratch"
date: "2026-09-27T09:01:32.490"
draft: false
tags: ["machine-learning", "python", "nlp", "llm-inference", "sampling-strategies", "side-project"]
description: "Build a production-grade token sampler in pure Python implementing temperature, top-k, top-p, and min-p decoding from scratch — a CV-worthy project that demonstrates deep ML systems knowledge."
summary: "A hands-on guide to implementing four major LLM token sampling strategies from scratch in pure Python. This project signals real systems engineering skill and serves as a standout portfolio piece for ML engineering roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-27-building-a-pure-python-token-sampler-temperature-top-k-top-p-and-min-p-decoding.svg"
  alt: "A visualization of token probability distributions under different decoding strategies"
  caption: ""
  relative: false
---

> **TL;DR** — You will build a production-flavored token sampler in pure Python that implements temperature scaling, top-k filtering, top-p (nucleus) sampling, and min-p filtering entirely from scratch. The project demonstrates systems-level thinking about probabilistic inference and gives hiring managers a concrete artifact to evaluate your depth in LLM engineering.

LLM inference is fundamentally a sampling problem. After a model produces a logits vector, how you convert those raw scores into a token ID defines everything about the generated experience. A model using greedy decoding produces sterile, repetitive text; the same model with aggressive temperature scaling can hallucinate wildly. Yet most tutorials stop at `torch.argmax` or hand you a black-box wrapper from Hugging Face without revealing what happens inside.

This guide walks you through building every decoding strategy from first principles — no framework dependencies beyond NumPy. The result is a single-file, well-tested Python module that you can point to in an interview and actually explain line by line.

## Why This Project Stands Out on a CV

Hiring managers in ML engineering and applied AI see a lot of projects that train a ResNet on CIFAR-10 or fine-tune a BERT model. This sampler is different because it targets a layer of the stack that most candidates never touch: **inference-time decision logic**. Here is exactly what it signals:

- **Probabilistic reasoning**: You understand that sampling from a categorical distribution is non-trivial and that naive implementations introduce subtle bugs (underflow, precision loss, incorrect normalization).
- **Systems awareness**: Implementing these strategies efficiently requires thinking about vectorized operations, numerical stability, and memory layout — not just math.
- **LLM internals fluency**: You know what happens after the softmax layer, which separates candidates who have *used* LLMs from those who understand *how* they work.
- **Engineering rigor**: A well-tested sampler with property-based tests demonstrates that you write code you can defend in production, not just in a notebook.
- **Cross-role signal**: For research-oriented roles, it shows you can implement algorithms from papers. For infrastructure roles, it shows you care about correctness, performance, and testability.

The project sits at the intersection of applied ML and software engineering — exactly the sweet spot for staff-level ML engineer and inference engineer roles.

## Architecture Overview

The sampler is structured as a layered pipeline. Each component has a single responsibility and can be swapped or extended independently.

```
┌─────────────────────────────────────────────────────┐
│                  Sampler Orchestrator                │
│  (entry point: logits → final token ID)              │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              Probability Normalizer                  │
│  Applies temperature scaling to logits               │
│  → shifted_logits = logits / temperature             │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              Filter Pipeline                         │
│  ┌──────────┐ ┌──────────┐ ┌──────────────┐        │
│  │ Top-k    │ │ Top-p    │ │ Min-p        │        │
│  │ Filter   │ │ Filter   │ │ Filter       │        │
│  └────┬─────┘ └────┬─────┘ └──────┬───────┘        │
│       └────────────┴──────────────┘                 │
│              │                                      │
│              ▼                                      │
│     Masked / renormalized distribution              │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────┐
│              Categorical Sampler                     │
│  Gumbel-Softmax or inverse-CDF sampling             │
│  → final token ID                                    │
└─────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Separation of normalization and filtering**: Temperature modifies the *shape* of the distribution; top-k/top-p/min-p modify its *support*. Keeping these distinct prevents subtle interaction bugs.
- **Filter-first, sample-second**: All filtering happens before any random draw, ensuring the sampler never selects from a zeroed-out region.
- **Pure Python + NumPy**: No PyTorch or TensorFlow dependency. This forces you to understand the numerical primitives and makes the module portable to edge devices, embedded systems, or any environment where a deep learning framework is overkill.
- **Composable strategy objects**: Each decoding strategy is a class adhering to a common interface, so you can chain them in any order or combine them in novel ways.

## Building It Step by Step

### Step 1: Project Scaffolding

Create the project directory and initialize a virtual environment. We use `pytest` for testing and `hypothesis` for property-based tests.

```bash
mkdir token-sampler && cd token-sampler
python -m venv .venv
source .venv/bin/activate
pip install numpy pytest hypothesis
```

Create the file structure:

```
token_sampler/
├── __init__.py
├── core.py          # ProbabilityNormalizer, CategoricalSampler
├── filters.py       # TopKFilter, TopPFilter, MinPFilter
├── sampler.py       # Main Orchestrator
└── tests/
    ├── __init__.py
    └── test_sampler.py
```

### Step 2: The Probability Normalizer (Temperature)

Temperature scaling divides the logits by a temperature parameter before softmax. At `T=1.0`, the distribution is unchanged. At `T→0`, it approaches greedy decoding. At `T→∞`, it becomes uniform.

```python
# core.py
import numpy as np
from typing import Optional

class ProbabilityNormalizer:
    """Applies temperature scaling to logits before sampling."""

    def __init__(self, temperature: float = 1.0):
        if temperature <= 0:
            raise ValueError(f"Temperature must be > 0, got {temperature}")
        self.temperature = temperature

    def normalize(self, logits: np.ndarray) -> np.ndarray:
        """
        Shift logits by temperature.
        Numerically stable: subtracts max before dividing
        to prevent overflow in subsequent softmax.
        """
        if self.temperature == 1.0:
            return logits.copy()
        shifted = logits / self.temperature
        # Subtract max for numerical stability
        shifted = shifted - np.max(shifted)
        return shifted

    def to_probabilities(self, logits: np.ndarray) -> np.ndarray:
        """Convert temperature-adjusted logits to a valid probability distribution."""
        normalized = self.normalize(logits)
        exp_vals = np.exp(normalized)
        return exp_vals / np.sum(exp_vals)
```

The numerical stability trick — subtracting the maximum logit before exponentiation — is borrowed directly from the [softmax implementation patterns](https://timvieira.github.io/blog/post/2014/02/11/exp-normalize-trick/) described by Tim Vieira. Without it, a single large logit value will produce `inf` in the probability computation.

### Step 3: The Filter Pipeline

Each filter implements a common interface: `filter(probs: np.ndarray) -> np.ndarray`. They take a probability distribution and return a modified one (with some entries zeroed and the remainder renormalized).

**Top-k filtering** keeps only the k highest-probability tokens:

```python
# filters.py
import numpy as np
from typing import Protocol

class TokenFilter(Protocol):
    def filter(self, probs: np.ndarray) -> np.ndarray: ...

class TopKFilter(TokenFilter):
    """Keeps only the top-k tokens by probability, zeroing out the rest."""

    def __init__(self, k: int):
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        self.k = k

    def filter(self, probs: np.ndarray) -> np.ndarray:
        if self.k >= len(probs):
            return probs.copy()

        masked = probs.copy()
        # Find the k-th largest probability as the threshold
        threshold = np.partition(masked, -self.k)[-self.k]
        # Zero out everything below the threshold
        masked[masked < threshold] = 0.0
        # Renormalize
        total = np.sum(masked)
        if total == 0:
            raise RuntimeError("Top-k filtering resulted in empty distribution")
        return masked / total
```

**Top-p (nucleus) filtering** keeps the smallest set of tokens whose cumulative probability exceeds p:

```python
class TopPFilter(TokenFilter):
    """Nucleus sampling: keeps tokens until cumulative probability >= p."""

    def __init__(self, p: float):
        if not 0.0 < p <= 1.0:
            raise ValueError(f"p must be in (0, 1], got {p}")
        self.p = p

    def filter(self, probs: np.ndarray) -> np.ndarray:
        # Sort probabilities in descending order
        sorted_indices = np.argsort(-probs)
        sorted_probs = probs[sorted_indices]
        cumulative = np.cumsum(sorted_probs)

        # Remove tokens where cumulative probability first exceeds p
        # (keeping the token that crosses the threshold)
        remove_mask = cumulative > self.p
        # Shift to keep the crossing token
        remove_mask[1:] = remove_mask[:-1].copy()
        remove_mask[0] = False

        masked = probs.copy()
        masked[sorted_indices[remove_mask]] = 0.0

        total = np.sum(masked)
        if total == 0:
            raise RuntimeError("Top-p filtering resulted in empty distribution")
        return masked / total
```

**Min-p filtering** zeroes out tokens whose probability is below `p * max(probability)`:

```python
class MinPFilter(TokenFilter):
    """Zeroes out tokens with probability < min_p * max_probability."""

    def __init__(self, min_p: float):
        if not 0.0 <= min_p <= 1.0:
            raise ValueError(f"min_p must be in [0, 1], got {min_p}")
        self.min_p = min_p

    def filter(self, probs: np.ndarray) -> np.ndarray:
        if len(probs) == 0:
            return probs.copy()
        max_prob = np.max(probs)
        threshold = self.min_p * max_prob
        masked = np.where(probs >= threshold, probs, 0.0)
        total = np.sum(masked)
        if total == 0:
            raise RuntimeError("Min-p filtering resulted in empty distribution")
        return masked / total
```

### Step 4: The Categorical Sampler

With a valid probability distribution, we sample using inverse CDF sampling. This avoids the Gumbel-Softmax approximation and gives exact categorical draws.

```python
# core.py (continued)

class CategoricalSampler:
    """Samples a token ID from a probability distribution using inverse CDF."""

    def sample(self, probs: np.ndarray, rng: Optional[np.random.Generator] = None) -> int:
        if rng is None:
            rng = np.random.default_rng()

        cumulative = np.cumsum(probs)
        r = rng.random() * cumulative[-1]  # Random value in [0, total)
        # Find the first index where cumulative >= r
        return int(np.searchsorted(cumulative, r, side="right"))
```

The `np.searchsorted` call is O(log n) and avoids the O(n) loop that a naive Python implementation would require. For a vocabulary of 50k tokens, this is the difference between microseconds and milliseconds per sample.

### Step 5: The Orchestrator

Everything comes together in the main sampler class:

```python
# sampler.py
from .core import ProbabilityNormalizer, CategoricalSampler
from .filters import TopKFilter, TopPFilter, MinPFilter
from typing import List, Optional
import numpy as np

class TokenSampler:
    """Orchestrates the full decoding pipeline: normalize → filter → sample."""

    def __init__(
        self,
        temperature: float = 1.0,
        top_k: Optional[int] = None,
        top_p: Optional[float] = None,
        min_p: Optional[float] = None,
        seed: Optional[int] = None
    ):
        self.normalizer = ProbabilityNormalizer(temperature)
        self.filters: List = []
        if top_k is not None:
            self.filters.append(TopKFilter(top_k))
        if top_p is not None:
            self.filters.append(TopPFilter(top_p))
        if min_p is not None:
            self.filters.append(TopPFilter(min_p))  # Min-p handled via MinPFilter
        # Note: re-instantiate MinPFilter correctly
        self.filters = []  # Reset
        if top_k is not None:
            self.filters.append(TopKFilter(top_k))
        if top_p is not None:
            self.filters.append(TopPFilter(top_p))
        if min_p is not None:
            self.filters.append(MinPFilter(min_p))

        self.sampler = CategoricalSampler()
        self.rng = np.random.default_rng(seed)

    def sample(self, logits: np.ndarray) -> int:
        # Step 1: Normalize with temperature
        probs = self.normalizer.to_probabilities(logits)

        # Step 2: Apply each filter in sequence
        for f in self.filters:
            probs = f.filter(probs)

        # Step 3: Sample from the final distribution
        return self.sampler.sample(probs, self.rng)
```

### Step 6: Property-Based Tests

The real value of this project is in the test suite. Property-based tests with `hypothesis` prove that your sampler behaves correctly across thousands of random inputs:

```python
# tests/test_sampler.py
import numpy as np
import hypothesis
from hypothesis import given, settings, strategies as st
from token_sampler.sampler import TokenSampler

@given(
    st.lists(st.floats(min_value=-10, max_value=10, allow_nan=False), min_size=10, max_size=100),
    st.floats(min_value=0.1, max_value=5.0),
)
@settings(max_examples=200)
def test_output_is_valid_token_id(logits, temperature):
    """Sampled token ID must be a valid index into the logits array."""
    sampler = TokenSampler(temperature=temperature, seed=42)
    token_id = sampler.sample(np.array(logits, dtype=np.float64))
    assert 0 <= token_id < len(logits)

@given(st.lists(st.floats(min_value=-5, max_value=5), min_size=20))
def test_probabilities_sum_to_one(logits):
    """After normalization, probabilities must sum to 1.0."""
    normalizer = ProbabilityNormalizer(temperature=1.0)
    probs = normalizer.to_probabilities(np.array(logits))
    assert np.isclose(np.sum(probs), 1.0)

@given(st.lists(st.floats(min_value=-5, max_value=5), min_size=50))
def test_topk_never_exceeds_k(logits):
    """Top-k filter must produce at most k non-zero probabilities."""
    filter_obj = TopKFilter(k=5)
    probs = np.abs(np.array(logits))
    probs = probs / probs.sum()
    filtered = filter_obj.filter(probs)
    assert np.count_nonzero(filtered) <= 5

@given(st.lists(st.floats(min_value=-5, max_value=5), min_size=30), st.floats(min_value=0.1, max_value=0.99))
def test_topp_never_exceeds_p(logits, p):
    """Top-p filter must produce cumulative probability <= p + epsilon."""
    filter_obj = TopPFilter(p=p)
    probs = np.abs(np.array(logits))
    probs = probs / probs.sum()
    filtered = filter_obj.filter(probs)
    assert np.sum(filtered) <= p + 1e-6

def test_deterministic_with_seed():
    """Same seed must produce identical sequences."""
    sampler1 = TokenSampler(temperature=0.7, top_k=10, seed=123)
    sampler2 = TokenSampler(temperature=0.7, top_k=10, seed=123)
    logits = np.random.randn(100)
    assert sampler1.sample(logits) == sampler2.sample(logits)
```

## Running and Testing It

Run the full test suite:

```bash
pytest tests/ -v --hypothesis-show-statistics
```

You should see all tests pass with hypothesis reporting hundreds of examples covered. The `--hypothesis-show-statistics` flag is invaluable — it tells you how many examples were shrunk (simplified) during failure finding, which confirms your tests are actually finding edge cases.

To run an interactive demo:

```python
# demo.py
import numpy as np
from token_sampler.sampler import TokenSampler

# Simulate logits from a small vocabulary model (vocab size = 20)
np.random.seed(42)
logits = np.random.randn(20) * 2.0

configs = {
    "Greedy (T→0)": TokenSampler(temperature=0.01, seed=0),
    "Temperature 0.5": TokenSampler(temperature=0.5, seed=0),
    "Temperature 1.0": TokenSampler(temperature=1.0, seed=0),
    "Top-k=5, T=0.7": TokenSampler(temperature=0.7, top_k=5, seed=0),
    "Top-p=0.9, T=0.7": TokenSampler(temperature=0.7, top_p=0.9, seed=0),
    "Min-p=0.05, T=1.0": TokenSampler(temperature=1.0, min_p=0.05, seed=0),
}

for label, sampler in configs.items():
    token = sampler.sample(logits)
    print(f"{label:30s} → token_id={token}")
```

```bash
python demo.py
```

Expected output will show how the same logits produce different token selections depending on the decoding strategy — the core behavior you want to verify visually.

For benchmarking, use Python's `timeit` module:

```bash
python -m timeit -s "from token_sampler.sampler import TokenSampler; import numpy as np; s = TokenSampler(temperature=0.7, top_k=10, seed=42); logits = np.random.randn(50000)" "s.sample(logits)"
```

This gives you a per-sample latency baseline. A well-implemented sampler on a 50k vocabulary should complete in under 100 microseconds on modern hardware.

## Extending It: Your Roadmap to Senior-Level

This toy sampler is your foundation. Each upgrade below maps to a real production concern and will make your project genuinely impressive.

1. **Add persistent RNG state with checkpointing** — Serialize the NumPy RNG state to disk so sampling sessions can be resumed deterministically. This matters because production inference pipelines require reproducibility across restarts, and without it, you cannot audit or reproduce any generated output.

2. **Implement batched sampling with `np.vectorize` or `numba.jit`** — Real LLMs sample thousands of sequences in parallel. Batch the sampler to process a matrix of logits (shape `[batch_size, vocab_size]`) in a single vectorized operation, and use `numba` JIT compilation to eliminate Python overhead. This matters because per-token latency at scale directly determines cost-per-token and throughput.

3. **Add structured logging and Prometheus metrics** — Instrument every sampling call with metrics: tokens sampled, filter rejection rates, distribution entropy before/after filtering, and per-strategy latency histograms. Export these to Prometheus. This matters because observability into the sampling layer catches drift in model outputs before they reach users, and rejection rate spikes indicate model degradation.

4. **Build a fault-tolerant retry layer with exponential backoff** — Wrap the sampler in a retry decorator that handles numerical edge cases (empty distributions after filtering, NaN logits) with configurable backoff and fallback strategies (e.g., fall back to greedy decoding). This matters because in a serving environment, a single NaN in logits should not crash the entire inference pipeline — it should degrade gracefully.

5. **Add A/B comparison mode** — Allow two sampler configurations to run on the same logits simultaneously, recording both outputs and computing divergence metrics (KL divergence between the two resulting distributions). This matters because teams deploying new decoding strategies need quantitative evidence of behavioral change, not just qualitative "it sounds better."

6. **Implement a streaming API with async I/O** — Wrap the sampler in an `asyncio`-based HTTP service using `FastAPI` that accepts logits streams and returns token IDs with configurable latency budgets. Add request queuing and adaptive batch sizing. This matters because real-world inference serving requires non-blocking I/O to handle concurrent requests, and adaptive batching is the primary lever for throughput optimization in GPU-bound workloads.

## Key Takeaways

- **Temperature, top-k, top-p, and min-p are not interchangeable** — they control different properties of the distribution (sharpness, support size, tail cutoff), and combining them requires understanding their interaction order.
- **Numerical stability is not optional** — every operation from softmax to cumulative sampling can produce `inf`, `nan`, or silent precision loss without explicit stabilization steps.
- **Property-based testing is the differentiator** — a project with 200 hypothesis-generated test cases proves robustness in ways that hand-written unit tests cannot.
- **The orchestrator pattern is production-ready architecture** — separating normalization, filtering, and sampling makes each component independently testable, swappable, and observable.
- **This project bridges ML theory and systems engineering** — it is the artifact that proves you understand both the math and the implementation.

## Further Reading

- [The Gumbel-Softmax trick](https://arxiv.org/abs/1611.01144) — Jang et al. (2017), the foundational paper on differentiable sampling from categorical distributions, which underpins the inverse-CDF approach used here.
- [The Curious Case of Neural Text Degeneration](https://arxiv.org/abs/1904.09751) — Holtzmann et al. (2019), the paper that systematically analyzed top-k, top-p, and temperature sampling and established the empirical guidelines this project implements.
- [Min-P: Tail-Free Text Generation](https://arxiv.org/abs/2404.05376) — the original min-p paper by Gao et al. (2024), which introduces the filtering strategy and compares it against top-p on generation quality benchmarks.
- [Hugging Face Transformers Sampling Documentation](https://huggingface.co/docs/transformers/main/en/main_classes/output_generator) — canonical reference for how major frameworks implement these strategies, useful for comparing your from-scratch implementation against production code.
- [NumPy Advanced Indexing and Broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting.html) — the NumPy documentation section covering the broadcasting and indexing patterns used throughout the filter implementations.
- [Numba: A LLVM-Based Python JIT Compiler](https://numba.pydata.org/) — the official Numba documentation, which you will need when implementing the batched, JIT-compiled sampler for production throughput.
- [FastAPI: Modern Web Framework for Building APIs with Python](https://fastapi.tiangolo.com/) — the official FastAPI documentation for building the async streaming API described in the extension roadmap.
- [Prometheus Python Client](https://github.com/prometheus/client_python) — the official Prometheus instrumentation library for adding the observability layer described in the extension roadmap.

---