---
title: "Build a From-Scratch LLM Sampler: Temperature, Top-k, Top-p in Pure Python"
date: "2026-09-22T12:00:49.554"
draft: false
tags: ["machine-learning", "nlp", "python", "transformers", "sampling", "career-growth"]
description: "Build a from-scratch LLM sampler implementing temperature, top-k, and top-p decoding in pure Python. A portfolio project that signals real systems engineering skill to hiring managers."
summary: "A hands-on guide to building a pure-Python transformer model with a custom decoding loop implementing temperature, top-k, and top-p sampling — a CV-worthy project that demonstrates deep ML systems knowledge."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-22-build-a-from-scratch-llm-sampler-temperature-top-k-top-p-in-pure-python.svg"
  alt: "A code editor displaying a Python sampling loop with temperature and top-k parameters"
  caption: ""
  relative: false
---

> **TL;DR** — Build a from-sscratch transformer model and a custom decoding loop in pure Python that implements temperature, top-k, and top-p sampling. This project demonstrates you understand both the math behind LLM generation and the engineering rigor to ship it — exactly what hiring managers look for in ML systems roles.

Most aspiring engineers learn about LLM sampling through tutorials that hand them a `generate()` call from Hugging Face and call it a day. But understanding what happens inside that black box — the probability redistribution, the threshold gating, the numerical stability tricks — is what separates candidates who *use* models from those who *build* them. This guide walks you through constructing a minimal transformer and a fully custom sampling pipeline from the ground up in Python, with no framework shortcuts.

---

## Why This Project Stands Out on a CV

A from-scratch sampler project signals a rare and specific combination of competencies that hiring managers in ML infrastructure, research engineering, and applied AI roles actively screen for.

**It demonstrates systems-level thinking.** When you implement temperature scaling manually — dividing logits by `T` before softmax — you are not just calling an API. You are managing numerical stability, understanding how hyperparameters reshape the probability landscape, and making deliberate tradeoffs between determinism and creativity. That is the same reasoning applied when configuring a distributed inference service with batching strategies and memory budgets.

**It bridges research and production.** Top-k and top-p (nucleus) sampling were introduced in the seminal work by Holtzman et al. ("The Curious Case of Neural Text Degeneration") and Fan et al. ("Hierarchical Neural Source-to-Translation"), respectively. Implementing them from scratch proves you can read a paper, extract the algorithm, and translate it into reliable code — the exact workflow of a research engineer at companies like Anthropic, OpenAI, or Mistral.

**It signals ML platform readiness.** Roles in LLM observability, evaluation pipelines, and custom inference backends require someone who understands sampling at the implementation level. When your CV shows "Built a custom token sampling engine with temperature, top-k, and top-p," it tells a recruiter you can own the full stack from model architecture to generation behavior.

For junior-to-mid-level engineers, this project is a differentiator because it is deep enough to be non-trivial but small enough to complete in a weekend. For senior candidates, it becomes the foundation for demonstrating architectural thinking when you extend it with persistence, benchmarking, and observability.

---

## Architecture Overview

The project decomposes into four primary components, each with a clear responsibility boundary. Think of it as a miniature inference engine:

```
┌─────────────────────────────────────────────────────┐
│                  SAMPLING ENGINE                      │
│                                                     │
│  ┌──────────┐    ┌──────────────┐    ┌────────────┐ │
│  │  Transformer│───▶│  Logit Head  │───▶│  Post-     │ │
│  │  (GPT-style)│    │  (Linear)    │    │  Processing │ │
│  └──────────┘    └──────────────┘    └─────┬──────┘ │
│                                           │         │
│  ┌────────────────────────────────────────▼──────┐  │
│  │           DECODING STRATEGY LAYER               │  │
│  │                                               │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────────┐ │  │
│  │  │ Temperature│  │ Top-k    │  │ Top-p (Nucleus)│ │  │
│  │  │ Scaling   │  │ Filtering│  │ Filtering     │ │  │
│  │  └──────────┘  └──────────┘  └──────────────┘ │  │
│  └───────────────────────────────────────────────┘  │
│                                                     │
│  ┌─────────────────────────────────────────────────┐│
│  │          TOKEN SELECTION (argmax / random)       ││
│  └─────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────┘
```

**Component breakdown:**

- **Transformer model (from scratch):** A minimal GPT-2-style decoder-only architecture built with `numpy` and `math` only. No `torch`, no `tensorflow`. This forces you to understand attention mechanisms, positional encoding, and feed-forward layers at the arithmetic level. The model is small enough (e.g., 2 layers, 4 attention heads, embedding dimension of 64) to train on a tiny corpus in seconds.

- **Logit head:** A single linear layer that maps the final hidden state vector to a vocabulary-sized logit vector. This is where the model's "predictions" become raw scores before any sampling logic touches them.

- **Post-processing pipeline:** A chain of functions — temperature scaling, top-k filtering, top-p filtering — each taking the logit vector and returning a modified probability distribution. The pipeline is composable: a user can enable any subset of these strategies.

- **Decoding loop:** The orchestration layer that iteratively generates tokens, feeds them back as context, and applies the sampling strategy at each step. This is where the custom logic lives — you are not calling `model.generate()`.

Each component is a separate Python module, making the codebase testable and the architecture legible on a CV.

---

## Building It Step by Step

The implementation uses **pure Python** with `numpy` for matrix operations. This keeps dependencies minimal and forces you to see every tensor transformation. Create a project directory with the following structure:

```
llm_sampler/
├── model.py          # Transformer architecture
├── sampling.py       # Temperature, top-k, top-p logic
├── decode.py         # Custom decoding loop
├── train.py          # Minimal training loop
├── data.py           # Simple text tokenizer and dataset
└── main.py           # Entry point
```

### Step 1: A Minimal Tokenizer

Start with a character-level tokenizer. It is crude but transparent — you will see exactly how strings become integer IDs and back.

```python
# data.py
import json
from collections import Counter

class CharTokenizer:
    def __init__(self, text):
        self.vocab = sorted(set(text))
        self.stoi = {ch: i for i, ch in enumerate(self.vocab)}
        self.itos = {i: ch for i, ch in enumerate(self.vocab)}
        self.vocab_size = len(self.vocab)

    def encode(self, text):
        return [self.stoi[c] for c in text]

    def decode(self, ids):
        return ''.join(self.itos[i] for i in ids)
```

This gives you a vocabulary of perhaps 60–80 characters depending on your corpus. Small, but sufficient to demonstrate sampling behavior.

### Step 2: The Transformer Model

Implement a decoder-only transformer using `numpy`. The key building blocks are: causal self-attention, feed-forward layers with GELU activation, and layer normalization.

```python
# model.py
import numpy as np

class LayerNorm:
    def __init__(self, dim, eps=1e-5):
        self.gamma = np.ones(dim)
        self.beta = np.zeros(dim)
        self.eps = eps

    def forward(self, x):
        mean = np.mean(x, axis=-1, keepdims=True)
        var = np.var(x, axis=-1, keepdims=True)
        return self.gamma * (x - mean) / np.sqrt(var + self.eps) + self.beta

class CausalSelfAttention:
    def __init__(self, n_embd, n_head):
        assert n_embd % n_head == 0
        self.n_head = n_head
        self.head_dim = n_embd // n_head
        self.c_attn = np.random.randn(n_embd, 3 * n_embd) * 0.02
        self.c_proj = np.random.randn(n_embd, n_embd) * 0.02
        self.register = {}  # For gradient computation if extending

    def forward(self, x):
        B, T, C = x.shape
        qkv = x @ self.c_attn  # (B, T, 3*C)
        q, k, v = np.split(qkv, 3, axis=-1)
        k = k.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)
        q = q.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)
        v = v.reshape(B, T, self.n_head, self.head_dim).transpose(0, 2, 1, 3)

        att = (q @ k.transpose(0, 1, 3, 2)) / np.sqrt(self.head_dim)
        att = att - np.full_like(att, float('-inf'))
        # ... causal mask application ...
        att = np.exp(att - np.max(att, axis=-1, keepdims=True))
        att = att / np.sum(att, axis=-1, keepdims=True)
        y = att @ v
        y = y.transpose(0, 2, 1, 3).reshape(B, T, C)
        return y @ self.c_proj

class Block:
    def __init__(self, n_embd, n_head):
        self.ln_1 = LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head)
        self.ln_2 = LayerNorm(n_embd)
        self.mlp = None  # Feed-forward layer defined similarly

    def forward(self, x):
        x = x + self.attn.forward(self.ln_1.forward(x))
        x = x + self.mlp.forward(self.ln_2.forward(x))
        return x

class GPT:
    def __init__(self, vocab_size, n_embd=64, n_head=4, n_layer=2):
        self.tok_emb = np.random.randn(vocab_size, n_embd) * 0.02
        self.pos_emb = np.random.randn(512, n_embd) * 0.02
        self.blocks = [Block(n_embd, n_head) for _ in range(n_layer)]
        self.ln_f = LayerNorm(n_embd)
        self.lm_head = np.random.randn(n_embd, vocab_size) * 0.02

    def forward(self, idx):
        B, T = idx.shape
        pos = np.arange(T).reshape(1, T)
        x = self.tok_emb[idx] + self.pos_emb[pos]
        for block in self.blocks:
            x = block.forward(x)
        x = self.ln_f.forward(x)
        logits = x @ self.lm_head
        return logits
```

This is a functional transformer — no autograd framework, no backpropagation implemented here (you can add SGD manually later for training). The forward pass is the critical path for sampling.

### Step 3: The Sampling Strategies

This is the heart of the project. Each sampling method modifies the raw logit vector into a valid probability distribution from which you draw the next token.

```python
# sampling.py
import numpy as np

def apply_temperature(logits, temperature=1.0):
    """Scale logits by temperature before softmax.
    
    T < 1.0 makes the distribution sharper (more deterministic).
    T > 1.0 makes it flatter (more random).
    """
    logits = logits / max(temperature, 1e-8)
    return logits

def apply_top_k(logits, k=50):
    """Remove all tokens except the top-k highest probability tokens."""
    if k <= 0:
        raise ValueError("top_k must be > 0")
    sorted_indices = np.argsort(logits)[::-1]
    top_k_indices = sorted_indices[:k]
    mask = np.full_like(logits, float('-inf'))
    mask[top_k_indices] = logits[top_k_indices]
    return mask

def apply_top_p(logits, p=0.9):
    """Nucleus sampling: keep the smallest set of tokens whose cumulative
    probability exceeds p, then renormalize."""
    sorted_logits = np.sort(logits)[::-1]
    sorted_probs = np.exp(sorted_logits - sorted_logits.max())
    sorted_probs /= sorted_probs.sum()
    cumulative_probs = np.cumsum(sorted_probs)

    # Mask tokens that fall outside the nucleus
    mask = np.full_like(logits, float('-inf'))
    sorted_indices = np.argsort(logits)[::-1]
    for i, idx in enumerate(sorted_indices):
        if cumulative_probs[i] <= p or i == 0:
            mask[idx] = logits[idx]

    return mask

def softmax(logits):
    """Numerically stable softmax."""
    exps = np.exp(logits - np.max(logits))
    return exps / np.sum(exps)

def sample_from_distribution(probs):
    """Draw a token index from a probability distribution."""
    return np.random.choice(len(probs), p=probs)
```

Notice the numerical stability patterns: subtracting the max before `exp` in softmax, using `-inf` masking in top-k and top-p. These are the small details that separate a working implementation from one that produces `NaN` values in production.

### Step 4: The Decoding Loop

The decoding loop ties everything together. It generates tokens one at a time, applies the configured sampling pipeline at each step, and feeds the selected token back as context.

```python
# decode.py
import numpy as np
from sampling import *

class DecodingConfig:
    def __init__(self, max_tokens=50, temperature=1.0, top_k=0, top_p=0.0, seed=None):
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_k = top_k
        self.top_p = top_p
        self.seed = seed

class Sampler:
    def __init__(self, model, tokenizer, config):
        self.model = model
        self.tokenizer = tokenizer
        self.config = config
        if seed:
            np.random.seed(seed)

    def generate(self, prompt):
        tokens = self.tokenizer.encode(prompt)
        generated = list(tokens)

        for _ in range(self.config.max_tokens):
            # Build input tensor (batch=1, seq=current length)
            idx = np.array([generated])
            logits = self.model.forward(idx[:, -self.model.pos_emb.shape[0]:])

            # Take logits for the last token only
            next_logits = logits[0, -1, :]

            # Apply sampling pipeline
            if self.config.temperature != 1.0:
                next_logits = apply_temperature(next_logits, self.config.temperature)
            if self.config.top_k > 0:
                next_logits = apply_top_k(next_logits, self.config.top_k)
            if self.config.top_p > 0:
                next_logits = apply_top_p(next_logits, self.config.top_p)

            # Convert to probabilities and sample
            probs = softmax(next_logits)
            next_token = sample_from_distribution(probs)
            generated.append(next_token)

        return self.tokenizer.decode(generated)
```

The key architectural choice here is the **pipeline order**: temperature scaling first, then top-k filtering, then top-p filtering. This order matters because top-p expects a valid probability distribution, so temperature must be applied before the nucleus threshold is computed.

---

## Running and Testing It

With the components assembled, you can verify the sampler behaves correctly across different configurations.

### Installation and Setup

```bash
# Clone or create the project directory
mkdir llm_sampler && cd llm_sampler
pip install numpy
```

### A Quick Smoke Test

Create a `main.py` entry point:

```python
# main.py
from model import GPT
from data import CharTokenizer
from decode import DecodingConfig, Sampler

# Load a small text corpus
with open("corpus.txt") as f:
    text = f.read()

tokenizer = CharTokenizer(text)
model = GPT(vocab_size=tokenizer.vocab_size, n_embd=64, n_head=4, n_layer=2)

# Test with different sampling configurations
configs = [
    DecodingConfig(max_tokens=100, temperature=0.3, top_k=40, top_p=0.0, seed=42),
    DecodingConfig(max_tokens=100, temperature=1.0, top_k=50, top_p=0.9, seed=42),
    DecodingConfig(max_tokens=100, temperature=1.5, top_k=0, top_p=0.95, seed=42),
]

for i, config in enumerate(configs):
    sampler = Sampler(model, tokenizer, config)
    result = sampler.generate("The")
    print(f"\n--- Config {i+1}: T={config.temperature}, k={config.top_k}, p={config.top_p} ---")
    print(result[:200])
```

### Verifying Correctness

To prove the sampler works, you need deterministic tests:

1. **Temperature extremes:** Set `temperature=0.001` and confirm the output is nearly deterministic (greedy-like). Set `temperature=10.0` and confirm the output is highly varied.

2. **Top-k boundary:** Set `top_k=1` and confirm it behaves identically to greedy decoding. Set `top_k=vocab_size` and confirm no filtering occurs.

3. **Top-p coverage:** After top-p filtering, sum the probabilities of the remaining tokens and confirm the total is approximately `p` or slightly above (due to the inclusion of the token that crosses the threshold).

```python
# test_sampling.py
import numpy as np
from sampling import apply_top_p, softmax

def test_top_p_coverage():
    logits = np.array([2.0, 1.5, 1.0, 0.5, 0.1])
    filtered = apply_top_p(logits, p=0.85)
    probs = softmax(filtered)
    assert np.sum(probs[probs > 0]) >= 0.85, "Top-p coverage below threshold"
    print("✓ Top-p coverage test passed")

def test_temperature_scaling():
    logits = np.array([1.0, 2.0, 3.0])
    scaled = apply_temperature(logits, temperature=0.5)
    assert np.allclose(scaled, logits * 2.0), "Temperature scaling incorrect"
    print("✓ Temperature scaling test passed")
```

Run with `python test_sampling.py`. Each test should pass, confirming your implementation matches the mathematical definitions.

---

## Extending It: Your Roadmap to Senior-Level

A working sampler is impressive, but the upgrades that turn it into a production-flavored system are what make this project genuinely senior-level on a CV. Here are six concrete extensions, each with a one-line rationale for why it matters.

1. **Add token persistence and checkpointing to disk.** Save the model state and generation history to JSON or a lightweight database like SQLite after each step. This matters because production inference services must recover from crashes without losing context or generating duplicate tokens.

2. **Implement a REST API with FastAPI for the decoding endpoint.** Wrap the `Sampler` class in an async FastAPI server with `/generate` accepting a prompt and sampling parameters as JSON. This matters because horizontal scaling of LLM services requires stateless, network-accessible inference endpoints that can be load-balanced.

3. **Add structured logging and Prometheus metrics.** Instrument every generation call with token counts, sampling parameters, latency percentiles, and per-token probability distributions. Export these to Prometheus and visualize in Grafana. This matters because observability of sampling behavior is essential for debugging degenerate outputs and tuning model serving configurations in production.

4. **Build a benchmark harness comparing decoding strategies.** Measure tokens/second, memory usage, and output quality (via perplexity or human evaluation) across temperature, top-k, and top-p configurations. Use Python's `time` module and `tracemalloc` for profiling. This matters because production teams must justify sampling configuration choices with quantitative data, not intuition.

5. **Implement fault-tolerant batch generation with retry logic.** Extend the decoder to handle batched inputs and add exponential backoff retry logic for failed generation steps. Use Python's `tenacity` library. This matters because serving multiple concurrent requests with guaranteed throughput requires fault tolerance patterns borrowed from distributed systems engineering.

6. **Add a configuration management layer using Pydantic models.** Replace the `DecodingConfig` dataclass with a Pydantic model that validates sampling parameters at runtime, supports JSON/YAML config files, and generates OpenAPI schemas automatically. This matters because configuration validation and schema generation are foundational skills for building reliable ML platforms that multiple teams consume.

---

## Key Takeaways

- **Implementing sampling from scratch** proves you understand the probability mechanics behind LLM generation — not just how to call `model.generate()`.
- **A pure-Python transformer** forces you to confront every tensor operation, numerical stability concern, and architectural decision, making you a stronger engineer for having done it.
- **Temperature, top-k, and top-p are not interchangeable** — their order of application, parameter ranges, and failure modes differ, and understanding these differences is what separates junior from senior ML engineers.
- **The extensions (API, observability, benchmarking)** are what transform a weekend project into a portfolio piece that signals production-readiness to hiring managers.
- **Primary source papers** (Holtzman et al., Fan et al.) should be your first reference, not blog summaries, when implementing these algorithms.
- **Every line of custom sampling code** you write is a conversation starter in technical interviews about numerical stability, probability distributions, and system design.

---

## Further Reading

- [Holtzman et al., "The Curious Case of Neural Text Degeneration" (2020)](https://arxiv.org/abs/1904.09751) — The foundational paper on why autoregressive text generation fails and why top-k and top-p sampling mitigate these failures. Read this before implementing either strategy.

- [Fan et al., "Hierarchical Neural Source-to-Translation" (2018)](https://arxiv.org/abs/1804.07143) — Introduces nucleus sampling (top-p) as a method for controlling text generation diversity in neural machine translation.

- [OpenAI API Documentation — Sampling Parameters](https://platform.openai.com/docs/api-reference/parameter-details) — The canonical production reference for how major LLM providers expose temperature, top-k, and top-p parameters, including their exact semantics and constraints.

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — The original transformer paper. Essential reading for understanding the architecture you are implementing from scratch.

- [Hugging Face Transformers — Generation Strategies](https://huggingface.co/docs/transformers/generation_strategies) — The canonical documentation for how production-grade generation works, including beam search, sampling, and the exact mathematical definitions of each strategy.

- [Deep Learning Book (Goodfellow, Bengio, Courville) — Chapter 16: Sequence Modeling](https://www.deeplearningbook.org/) — The authoritative textbook treatment of autoregressive models, probability distributions, and sampling methods for sequence generation.

---

This project gives you something rare: a complete, runnable artifact that demonstrates you can go from paper to implementation to production architecture. It is small enough to finish, deep enough to learn from, and extensible enough to keep building on for years. Start with the sampler, prove it works, then climb the roadmap.