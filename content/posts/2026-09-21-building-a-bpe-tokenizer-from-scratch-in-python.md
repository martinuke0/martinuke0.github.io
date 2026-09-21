

---
title: "Building a BPE Tokenizer from Scratch in Python"
date: "2026-09-21T01:02:16.530"
draft: false
tags: ["nlp", "tokenization", "python", "bpe", "systems"]
description: "A hands-on guide to implementing a byte-level BPE tokenizer in Python, with real code, tests, and production-ready extensions for your portfolio."
summary: "Implement a byte-level BPE tokenizer from scratch, test it, and extend it to production-grade tooling."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-building-a-bpe-tokenizer-from-scratch-in-python.svg"
  alt: "Cover image showing BPE tokenization process"
  caption: ""
  relative: false
---

> **TL;DR** — Building a BPE tokenizer from scratch demonstrates deep understanding of subword segmentation, algorithmic efficiency, and production-ready NLP pipelines. This project gives you a concrete artifact that showcases algorithmic skill, testability, and extensibility, making it stand out to hiring managers.

In the race to build language models, tokenization is the first bottleneck. A well‑implemented byte‑pair encoding (BPE) tokenizer compresses text into a compact vocabulary, reduces out‑of‑vocabulary issues, and directly impacts model performance. In this post you will build a minimal but fully functional BPE tokenizer in Python, test it on real corpora, and then see how to evolve it into a production‑grade component. The code is runnable, the tests are included, and the architecture is designed for extension—exactly the kind of portfolio piece that signals systems engineering maturity.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – you implement the core BPE merge loop, frequency counting, and vocabulary construction from first principles, showing you can reason about complexity and trade‑offs.
- **Production readiness** – the tokenizer is packaged as a reusable Python module, supports serialization, and includes unit tests, demonstrating engineering discipline.
- **Scalability awareness** – by discussing extensions like multiprocessing, streaming, and persistence, you hint at experience with large‑scale data pipelines.
- **Domain relevance** – BPE is the de‑facto standard in modern NLP (used by GPT, BERT, T5), so the project directly ties to hiring‑relevant skills.
- **Portfolio signal** – a side project that ships a working artifact, includes benchmarks, and can be extended with observability and fault tolerance is a strong indicator of senior‑level potential.

## Architecture Overview

The tokenizer is composed of four logical layers:

1. **Corpus Loader** – reads raw text files (plain text, JSON, or streaming) and yields a sequence of byte strings.
2. **Preprocessor** – converts each byte string into a list of integer IDs (0‑255) representing the raw bytes.
3. **BPE Trainer** – iteratively computes pair frequencies, selects the most frequent pair, merges it into a new token, and updates the vocabulary until a target size is reached.
4. **Tokenizer / Detokenizer** – uses the learned merges to encode new text into token IDs and decode token IDs back to the original byte sequence.

A simple text diagram:

```
Raw Text → [Byte Encoder] → Byte IDs → [BPE Trainer] → Merge Table → [Tokenizer] → Token IDs
```

The merge table is stored as a list of `(pair, new_id)` tuples, which can be serialized to JSON or a binary format for later use.

## Building It Step by Step

Below is a complete, runnable implementation. Save it as `bpe_tokenizer.py` and run with Python 3.9+.

### Step 1 – Project Setup

Create a virtual environment and install the only dependency:

```bash
python -m venv bpe-env
source bpe-env/bin/activate
pip install pytest
```

### Step 2 – Load and Preprocess the Corpus

```python
import json
from pathlib import Path
from typing import Iterable, Iterator

def load_corpus(paths: Iterable[Path]) -> Iterator[str]:
    """Yield raw text from one or more files."""
    for p in paths:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                yield line.strip()

def text_to_bytes(text: str) -> list[int]:
    """Convert a string to a list of byte IDs (0‑255)."""
    return list(text.encode("utf-8"))
```

### Step 3 – Compute Pair Frequencies

```python
from collections import Counter
from typing import Tuple

def get_pair_freqs(seq: list[int]) -> Counter:
    """Return a Counter of adjacent token pairs."""
    return Counter(zip(seq, seq[1:]))
```

### Step 4 – The BPE Merge Loop

```python
class BPETokenizer:
    def __init__(self, vocab_size: int = 5000):
        self.vocab_size = vocab_size
        self.merges: list[Tuple[int, int, int]] = []  # (left, right, new_id)
        self.id_to_token: dict[int, bytes] = {}
        self.token_to_id: dict[bytes, int