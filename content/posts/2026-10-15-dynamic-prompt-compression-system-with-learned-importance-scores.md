---
title: "Dynamic Prompt Compression System with Learned Importance Scores"
date: "2026-10-15T15:01:24.475"
draft: false
tags: ["python", "llm", "prompt-engineering", "compression", "cv", "side-project"]
description: "Build a pure‑Python dynamic prompt compressor that learns token importance scores to fit any LLM context window."
summary: "A hands‑on guide to building a from‑scratch prompt compression system that learns token importance and truncates context for fixed‑size LLM windows."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-15-dynamic-prompt-compression-system-with-learned-importance-scores.svg"
  alt: "A sleek Python logo over a compressed text ribbon."
  caption: ""
  relative: false
---

> **TL;DR** — We build a from‑scratch Python system that learns per‑token importance scores and truncates prompts to fit any fixed‑size LLM window, giving you full control over context budget without third‑party black boxes.

Building LLM‑driven products often means hitting the hard ceiling of a model’s context window. Whether you’re prototyping with a 4 K token GPT‑3.5 deployment or working with a 32 K Claude model, you need a reliable way to squeeze useful information into the available space. This post walks you through a **pure‑Python**, minimal‑dependency implementation of a dynamic prompt compressor that learns an importance score for every token and then truncates or summarizes the prompt so it always fits the target window. The result is a portable utility you can ship, extend, and point to on a CV as a concrete signal of systems‑level engineering skill.

## Why This Project Stands Out on a CV

- **Python engineering & minimal‑dependency thinking** – You demonstrate the ability to solve a non‑trivial problem using only the standard library and a single optional package (e.g., NumPy). Employers value engineers who can deliver working code without pulling in heavy frameworks.
- **NLP & token‑level analytics** – Designing and implementing a learned importance score forces you to think about tokenization, frequency statistics, and simple machine‑learning concepts (e.g., TF‑IDF‑style weighting or gradient‑free scoring). This signals familiarity with the inner workings of LLM pipelines.
- **Context‑window engineering** – Many real‑world systems (RAG pipelines, chat agents, function‑calling backends) must respect strict token budgets. Showing you can architect a truncation/ summarization layer is directly relevant to backend, ML‑ops, and prompt‑engineer roles.
- **Production‑ready mindset** – The project naturally leads to considerations of observability, benchmarking, and extensibility—topics that hiring managers look for when differentiating a “toy” script from a genuine engineering artifact.
- **Side‑project visibility** – Because the codebase is tiny (≈150 LOC), it’s easy for a recruiter to clone, run, and inspect the logic in minutes, making it an effective talking point during interviews or LinkedIn posts.

**Roles it signals for:** ML / Prompt Engineer, Backend Engineer (API‑level integration), Data Engineer (pipeline preprocessing), and any position that deals with LLM‑driven user‑facing products.

## Architecture Overview

The system can be decomposed into five loosely‑coupled components:

1. **Tokenizer** – Converts raw user text into a list of token IDs/strings. In the minimal implementation we use a whitespace‑based splitter; a production version would plug in `tiktoken` or `sentencepiece`.
2. **Scorer** – Emits a numeric importance value (0 – 1) for each token. The scorer is a tiny, pure‑Python function that can be swapped out (e.g., frequency‑based, TF‑IDF, or a learned linear model).
3. **Ranker** – Sorts tokens by descending importance and returns the top‑K tokens that fit within the remaining budget.
4. **Truncator** – Takes the original token list and the selected subset, then produces a compressed prompt string. It also appends a short “summary” line if some tokens are dropped.
5. **Controller / CLI** – Orchestrates the flow: read input, invoke tokenizer → scorer → ranker → truncator, and output the final prompt.

```
Text → Tokenizer → Scorer → Ranker → Truncator → Compressed Prompt
```

A text‑diagram of the data flow:

```
+----------+      +----------+      +----------+      +----------+      +----------+
|  Input   | ---> | Tokenizer| ---> |   Scorer | ---> |   Ranker | ---> | Truncator|
+----------+      +----------+      +----------+      +----------+      +----------+
                                        |
                                        v
                                 +---------------+
                                 | Compressed    |
                                 | Prompt Output |
                                 +---------------+
```

The architecture is deliberately simple so that every component can be unit‑tested in isolation and replaced without rip‑pling changes elsewhere.

## Building It Step by Step

Below are **five numbered steps** that produce a runnable script from scratch. Each step includes a concise code snippet with a language tag.

### Step 1 – Scaffold & minimal dependencies

Create a new file `prompt_compressor.py`. The only external dependency we’ll use (optional) is **NumPy** for a lightweight vector operation; otherwise everything else lives in the standard library.

```python
# prompt_compressor.py
# -------------------------------------------------
# Step 1 – scaffold and optional NumPy import
# -------------------------------------------------
from __future__ import annotations

# If you have NumPy installed, use it for vector math;
# otherwise the code falls back to pure Python lists.
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False
    # Define a tiny stand‑in so the rest of the code stays the same
    class np:  # type: ignore
        @staticmethod
        def array(seq):
            return list(seq)
        @staticmethod
        def mean(arr):
            return sum(arr) / len(arr) if arr else 0.0
```

### Step 2 – Simple whitespace tokenizer

```python
def tokenize(text: str) -> list[str]:
    """
    Very small tokenizer that splits on whitespace and punctuation.
    Returns a list of token strings.
    """
    # Using a regex‑free approach keeps dependencies at zero.
    import re
    # Preserve tokens that contain internal apostrophes (e.g., "don't")
    tokens = re.findall(r"\b\w+(?:'\w+)?\b", text)
    return tokens
```

### Step 3 – Learn per‑token importance scores

We’ll use a **TF‑IDF‑style** heuristic that requires only word‑frequency counting. In a production system you could replace this with a tiny neural net or a learned linear model.

```python
def compute_importance(tokens: list[str], corpus_tokens: list[list[str]]) -> dict[str, float]:
    """
    Compute an importance score (0‑1) for each token based on its
    frequency in the supplied corpus versus the whole vocabulary.
    """
    # 1. Count document frequency across the corpus
    doc_freq: dict[str, int] = {}
    for doc in corpus_tokens:
        for tok in set(doc):               # set → count once per doc
            doc_freq[tok] = doc_freq.get(tok, 0) + 1

    # 2. Total number of documents (for IDF)
    N = len(corpus_tokens) or 1

    # 3. Build score map
    scores: dict[str, float] = {}
    for tok in tokens:
        tf = tokens.count(tok) / len(tokens) if tokens else 0
        idf = -__import__("math").log(doc_freq.get(tok, 0) / N) if doc_freq.get(tok, 0) else 0
        # Normalise to 0‑1 range (simple min‑max over observed scores)
        scores[tok] = tf * idf
    # Normalise globally
    if scores:
        min_s = min(scores.values())
        max_s = max(scores.values())
        if max_s > min_s:
            scores = {k: (v - min_s) / (max_s - min_s) for k, v in scores.items()}
    return scores
```

### Step 4 – Rank and select top‑K tokens

```python
def rank_tokens(scores: dict[str, float], k: int) -> list[str]:
    """
    Return the k tokens with the highest importance scores.
    Ties are broken arbitrarily (first‑found order).
    """
    # Sort by descending score
    sorted_tokens = sorted(scores, key=scores.get, reverse=True)
    return sorted_tokens[:k]
```

### Step 5 – Truncate the prompt, preserving the most important tokens

```python
def truncate_prompt(
    original: str,
    k: int,
    corpus: list[str] | None = None,
) -> str:
    """
    Given an original prompt and a target token budget k,
    return a compressed prompt that keeps the k most important tokens.
    If corpus is provided, importance scores are learned from it;
    otherwise a simple frequency heuristic is used.
    """
    tokens = tokenize(original)

    # Build a minimal corpus if none supplied (use the prompt itself)
    if corpus is None:
        corpus = [tokens]
    else:
        # Ensure corpus tokens are also tokenised lists
        corpus = [tokenize(c) for c in corpus]

    scores = compute_importance(tokens, corpus)
    kept = rank_tokens(scores, k)

    # Preserve order from the original token list but only keep kept tokens
    kept_set = set(kept)
    compressed_tokens = [tok for tok in tokens if tok in kept_set]

    # If we dropped tokens, append a short note
    dropped = len(tokens) - k
    if dropped:
        compressed_tokens.append(f"<dropped_{dropped}_tokens>")

    return " ".join(compressed_tokens)
```

**Putting it all together** – a tiny CLI you can invoke from the terminal:

```python
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python prompt_compressor.py <prompt> <budget_k> [corpus_file]")
        sys.exit(1)

    prompt = sys.argv[1]
    try:
        k = int(sys.argv[2])
    except ValueError:
        print("Budget k must be an integer")
        sys.exit(1)

    corpus_file = sys.argv[3] if len(sys.argv) > 3 else None
    corpus = []
    if corpus_file:
        with open(corpus_file) as f:
            corpus = [line.strip() for line in f if line.strip()]

    result = truncate_prompt(prompt, k, corpus)
    print("=== Compressed prompt ===")
    print(result)
```

## Running and Testing It

1. **Install dependencies** (optional NumPy, otherwise nothing):

   ```bash
   pip install numpy   # optional
   ```

2. **Save the script** as `prompt_compressor.py` and make it executable:

   ```bash
   chmod +x prompt_compressor.py
   ```

3. **Run a quick demo**:

   ```bash
   ./prompt_compressor.py \
       "Artificial intelligence is transforming software engineering by enabling code generation, automated testing, and intelligent debugging." \
       30
   ```

   You should see a compressed version that keeps only the 30 most “important” tokens according to the TF‑IDF‑style scorer.

4. **Unit‑test the core functions** (add to the file or a separate `test_` module):

   ```python
   import pytest

   def test_tokenize():
       assert tokenize("Hello world!") == ["Hello", "world"]

   def test_importance_normalisation():
       tokens = ["ai", "code", "engineering", "ai", "testing"]
       corpus = [["ai", "code"], ["engineering", "testing"]]
       scores = compute_importance(tokens, corpus)
       assert 0.0 <= min(scores.values()) and max(scores.values()) <= 1.0

   def test_rank_and_truncate():
       tokens = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
       scores = {t: i for i, t in enumerate(tokens)}  # simple mock scores
       kept = rank_tokens(scores, 4)
       assert kept == ["lazy", "the", "dog", "fox"]  # order depends on mock

   def test_truncate_preserves_budget():
       prompt = "the quick brown fox jumps over the lazy dog"
       compressed = truncate_prompt(prompt, k=5)
       # Count tokens after compression (ignore the dropped note)
       tok_count = len(compressed.split())
       assert tok_count <= 5 + 1  # +1 for the dropped note if any
   ```

   Run with `pytest -q prompt_compressor.py` (or `python -m pytest`).

5. **Verify end‑to‑end behaviour** by comparing the token count of the output to the requested budget `k`. Adjust `k` or the scorer as needed for your target LLM window.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Persist importance models** with `joblib` or `pickle` so the scorer can be reused across runs without recomputation. | Cuts latency in interactive tools and enables offline model analysis. |
| 2 | **Plug in `tiktoken`** (OpenAI’s tokenizer) for accurate token counts, replacing the naive whitespace splitter. | Guarantees the compressor respects the exact token budget of the target model. |
| 3 | **Expose a REST endpoint** (FastAPI or Flask) that accepts JSON `{ "prompt": "...", "budget": N }` and returns the compressed prompt. | Turns the script into a reusable micro‑service for pipelines or chat back‑ends. |
| 4 | **Add observability**: log scorer statistics, token‑budget utilisation, and runtime metrics to Prometheus or Datadog. | Enables proactive capacity planning and quick detection of regressions. |
| 5 | **Benchmark against baselines** (e.g., simple “keep‑first‑N‑tokens” or LangChain’s `trim_messages`). | Provides quantitative proof that learned importance actually improves answer quality or reduces hallucinations. |
| 6 | **Fault‑tolerant pipeline**: wrap the truncator in a retry/circuit‑breaker pattern (e.g., `tenacity`) and validate that the output never exceeds the token limit. | Production systems must survive transient tokeniser errors or model‑parameter changes without crashing. |

Each upgrade moves the project from a “cool demo” to a component you could ship in a real LLM‑driven product.

## Key Takeaways

- **Learned importance scores** give you fine‑grained control over which tokens survive the truncation step, unlike naïve “first‑N” strategies.  
- The entire implementation lives in **≈150 lines of pure Python**, with an optional NumPy import for vector math—perfect for a lightweight, dependency‑minimal side project.  
- **Architecture‑first design** (tokenizer → scorer → ranker → truncator) makes each piece testable and swappable, a pattern that scales to production pipelines.  
- **Real‑world relevance**: context‑window management is a daily pain point for anyone building LLM‑backed chat, RAG, or function‑calling services. Demonstrating you can solve it from scratch signals systems‑engineering maturity.  
- **Extensibility roadmap** (persistence, tokenizer accuracy, API exposure, observability, benchmarking, fault tolerance) shows hiring managers you think beyond the initial prototype.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) – the foundational paper that introduced the transformer architecture and the concept of token‑level attention, which underpins modern LLM context handling.  
- [OpenAI Cookbook – Prompt Engineering](https://github.com/openai/openai-cookbook) – contains practical patterns for prompt truncation, few‑shot formatting, and token‑budget management.  
- [Hugging Face Transformers – Tokenization](https://huggingface.co/docs/transformers/main_classes/tokenizer) – documentation on `tiktoken`, `sentencepiece`, and other tokenizers you can swap into the compressor for exact token counts.  
- [LangChain Prompt Template](https://python.langchain.com/docs/modules/prompt/) – shows how LangChain handles prompt trimming and can inspire additional compression strategies.  
- [Redis Documentation – TTL & Expiry](https://redis.io/docs/latest/commands/expire/) – useful if you decide to persist importance models or cached compressed prompts in a key‑value store for rapid reuse.