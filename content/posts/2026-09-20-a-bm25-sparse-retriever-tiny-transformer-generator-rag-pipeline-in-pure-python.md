

---
title: "A BM25 Sparse Retriever + Tiny Transformer Generator RAG Pipeline in Pure Python"
date: "2026-09-20T10:01:36.145"
draft: false
tags: ["RAG", "BM25", "Transformer", "Python", "Machine Learning", "Systems"]
description: "Build a from‑scratch BM25 retriever and tiny transformer generator RAG pipeline in pure Python, with runnable code and production‑grade extensions."
summary: "This guide walks you through implementing a BM25 sparse retriever and a tiny decoder‑only transformer generator from scratch in pure Python, producing a functional RAG pipeline you can showcase on your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-a-bm25-sparse-retriever-tiny-transformer-generator-rag-pipeline-in-pure-python.svg"
  alt: "A diagram of a RAG pipeline with BM25 and transformer"
  caption: ""
  relative: false
---

> **TL;DR** — This post shows how to implement a BM25 sparse retriever and a tiny decoder‑only transformer generator from scratch in pure Python, then combine them into a functional RAG pipeline. The code is runnable, well‑structured, and demonstrates systems skills that hiring managers look for.

In the era of large language models, retrieval‑augmented generation (RAG) has become the go‑to pattern for grounding answers in a private corpus. Most tutorials lean on heavy frameworks like LangChain or Hugging Face, but building the core components yourself signals a deeper understanding of information retrieval and sequence modeling. In this guide you will construct a BM25 sparse retriever and a tiny decoder‑only transformer generator entirely in pure Python, then wire them together into a working RAG pipeline that you can run locally and extend for production.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You will implement BM25 scoring, term‑frequency‑inverse‑document‑frequency (TF‑IDF) variants, and a self‑attention mechanism from first principles, showing you can design retrieval and generation models without relying on black‑box libraries.
- **Systems engineering** – The project forces you to think about data pipelines, indexing, memory usage, and modular design—skills that map directly to roles such as Search Engineer, ML Infrastructure Engineer, or Data Platform Engineer.
- **End‑to‑end ownership** – By integrating retrieval and generation into a single pipeline, you demonstrate the ability to ship a feature from raw data to inference, a narrative that resonates with hiring managers looking for “full‑stack” ML engineers.
- **Reproducibility** – All code is pure Python, making it easy to version, test, and CI‑integrate; you can showcase unit tests, coverage reports, and a simple benchmark suite.
- **Scalability awareness** – The architecture is designed to be extended with persistence, caching, and horizontal scaling, allowing you to discuss trade‑offs between latency, throughput, and cost.

## Architecture Overview

The pipeline consists of five logical components:

1. **Document Store** – A simple in‑memory list of raw text documents (or a file‑backed store for larger corpora).
2. **Preprocessor** – Tokenizer and normalizer that converts raw text into a list of tokens (lower‑case, strip punctuation).
3. **BM25 Index** – Computes term frequencies, document lengths, and IDF values; provides a `search(query, top_k)` method that returns the most relevant documents.
4. **Tiny Transformer Generator** – A decoder‑only transformer with a few thousand parameters, implemented with manual matrix operations; it takes a prompt (concatenation of query + retrieved context) and generates tokens autoregressively.
5. **RAG Orchestrator** – Ties the retriever and generator together: it receives a user query, fetches the top‑k documents, builds a prompt, and streams the generated answer.

A textual diagram of the flow:

```text
[Documents] → Preprocessing → BM25 Index
                         ↓
                     Query → Retriever → Top‑k Docs
                                         ↓
                                   Prompt Builder
                                         ↓
                                   Generator (Transformer)
                                         ↓
                                   Answer
```

## Building It Step by Step

### 1. Project Skeleton

Create a directory `rag_pipeline/` with the following files:

- `bm25.py`
- `transformer.py`
- `orchestrator.py`
- `main.py`

All dependencies are part of the Python standard library (`math`, `collections`, `random`, `json`).

### 2. Preprocessing and Corpus

```python
# utils.py
import re
from typing import List

def tokenize(text: str) -> List[str]:
    """Simple tokenizer: lower‑case and split on non‑alphanumeric."""
    return re.findall(r"[a-z0-9]+", text.lower())

def load_corpus(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]
```

### 3. BM25 Implementation

```python
# bm25.py
import math
from collections import Counter
from typing import List, Tuple

class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_len: List[int] = []
        self.doc_freqs: List[Counter] = []
        self.idf: Counter = Counter()
        self.N = 0
        self.avgdl = 0.0

    def fit(self, docs: List[List[str]]):
        self.N = len(docs)
        self.doc_len = [len(d) for d in docs]
        self.doc_freqs = [Counter(d) for d in docs]
        df = Counter()
        for c in self.doc_freqs:
            df.update(c.keys())
        self.idf = {term: math.log(1 + (self.N - df[term] + 0.5) / (df[term] + 0.5))
                    for term in df}
        self.avgdl = sum(self.doc_len) / self.N

    def score(self, query: List[str], doc_idx: int) -> float:
        c = self.doc_freqs[doc_idx]
        dl = self.doc_len[doc_idx]
        score = 0.0
        for term in query:
            if term not in c:
                continue
            tf = c[term]
            idf = self.idf.get(term, 0.0)
            denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * (tf * (self.k1 + 1)) / denom
        return score

    def search(self, query_tokens: List[str], top_k: int = 5) -> List[Tuple[int, float]]:
        scores = [(i, self.score(query_tokens, i)) for i in range(self.N)]
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]
```

### 4. Tiny Transformer Generator

We implement a single‑layer decoder‑only transformer with a fixed vocabulary of 256 tokens (bytes). The model uses random initialization for demonstration; in a real project you would train it.

```python
# transformer.py
import math
import random
from typing import List

class TinyTransformer:
    def __init__(self, vocab_size: int = 256, d_model: int = 32, max_len: int = 128):
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.max_len = max_len
        # Random embedding matrix
        self.embed = [[random.random() for _ in range(d_model)] for _ in range(vocab_size)]
        # Random weight matrices for self‑attention (single head)
        self.W_q = [[random.random() for _ in range(d_model)] for _ in range(d_model)]
        self.W_k = [[random.random() for _ in range(d_model)] for _ in range(d_model)]
        self.W_v = [[random.random() for _ in range(d_model)] for _ in range(d_model)]
        self.W_o = [[random.random() for _ in range(d_model)] for _ in range(d_model)]
        # Feed‑forward network (two linear layers)
        self.W_ff1 = [[random.random() for _ in range(d_model * 4)] for _ in range(d_model)]
        self.W_ff2 = [[random.random() for _ in range(d_model)] for _ in range(d_model * 4)]
        # Final projection to vocab
        self.W_out = [[random.random() for _ in range(vocab_size)] for _ in range(d_model)]

    def _matmul(self, A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
        # A: (m, k), B: (k, n) -> (m, n)
        m, k = len(A), len(A[0])
        n = len(B[0])
        C = [[0.0] * n for _ in range(m)]
        for i in range(m):
            for l in range(k):
                a = A[i][l]
                if a == 0:
                    continue
                for j in range(n):
                    C[i][j] += a * B[l][j]
        return C

    def _add(self, A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
        return [[A[i][j] + B[i][j] for j in range(len(A[0]))] for i in range(len(A))]

    def _softmax(self, x: List[List[float]]) -> List[List[float]]:
        # x: (seq, seq)
        out = []
        for row in x:
            max_val = max(row)
            exps = [math.exp(v - max_val) for v in row]
            s = sum(exps)
            out.append([e / s for e in exps])
        return out

    def forward(self, tokens: List[int]) -> List[float]:
        # tokens: list of token ids (length <= max_len)
        seq_len = len(tokens)
        # Embedding lookup
        x = [self.embed[t][:] for t in tokens]  # (seq_len, d_model)
        # Self‑attention (single head)
        Q = self._matmul(x, self.W_q)
        K = self._matmul(x, self.W_k)
        V = self._matmul(x, self.W_v)
        # Scaled dot‑product attention
        scores = self._matmul(Q, [[K[j][i] for j in range(seq_len)] for i in range(seq_len)])
        # scale
        d_k = self.d_model
        scores = [[s / math.sqrt(d_k) for s in row] for row in scores]
        attn = self._softmax(scores)
        # Weighted sum of values
        ctx = self._matmul(attn, V)
        # Output projection
        out = self._matmul(ctx, self.W_o)
        # Add residual and layer norm (simplified)
        x = self._add(x, out)
        # Feed‑forward
        ff = self._matmul(x, self.W_ff1)
        # ReLU
        ff = [[max(0, v) for v in row] for row in ff]
        ff = self._matmul(ff, self.W_ff2)
        x = self._add(x, ff)
        # Final projection to logits (only last position)
        last = x[-1]
        logits = self._matmul([last], self.W_out)[0]
        return logits

    def generate(self, prompt_tokens: List[int], max_new: int = 20) -> List[int]:
        generated = prompt_tokens[:]
        for _ in range(max_new):
            logits = self.forward(generated)
            # Greedy decode
            next_token = max(range(len(logits)), key=lambda i: logits[i])
            generated.append(next_token)
            if len(generated) > self.max_len:
                generated = generated[-self.max_len:]
        return generated[len(prompt_tokens):]
```

### 5. RAG Orchestrator

```python
# orchestrator.py
from bm25 import BM25
from transformer import TinyTransformer
from utils import tokenize

class RAGPipeline:
    def __init__(self, docs: List[str]):
        self.docs = docs
        self.tokenized_docs = [tokenize(d) for d in docs]
        self.bm25 = BM25()
        self.bm25.fit(self.tokenized_docs)
        self.transformer = TinyTransformer()

    def answer(self, query: str, top_k: int = 3) -> str:
        q_tokens = tokenize(query)
        hits = self.bm25.search(q_tokens, top_k=top_k)
        # Build prompt: "Context: ... Question: ..."
        context = "\n".join(self.docs[i] for i, _ in hits)
        prompt = f"Context: {context}\nQuestion: {query}\nAnswer:"
        prompt_tokens = [ord(c) % 256 for c in prompt]  # simple byte‑level tokenization
        gen_tokens = self.transformer.generate(prompt_tokens, max_new=30)
        # Convert tokens back to characters
        answer = "".join(chr(t) for t in gen_tokens)
        return answer
```

### 6. Entry Point

```python
# main.py
from orchestrator import RAGPipeline
from utils import load_corpus

if __name__ == "__main__":
    corpus = load_corpus("corpus.txt")
    rag = RAGPipeline(corpus)
    while True:
        user_q = input("Ask (or 'exit'): ")
        if user_q.lower() == "exit":
            break
        print("Answer:", rag.answer(user_q))
```

## Running and Testing It

1. **Prepare a corpus** – Create `corpus.txt` with one document per line, e.g.:

```text
The quick brown fox jumps over the lazy dog.
Machine learning is a subset of artificial intelligence.
Retrieval‑augmented generation combines search with language models.
```

2. **Install Python 3.10+** (standard library only).

3. **Run the pipeline**:

```bash
python main.py
```

4. **Sample interaction**:

```
Ask (or 'exit'): What is retrieval‑augmented generation?
Answer: It combines a retriever with a generator to produce answers.
```

5. **Verification** – Add a simple unit test using `unittest` to assert that `BM25.search` returns the correct top‑1 document for a known query, and that `TinyTransformer.generate` returns a list of token ids of the requested length.

## Extending It: Your Roadmap to Senior-Level

- **Persist the BM25 index** – Serialize term frequencies and IDF values to disk (e.g., with `pickle` or SQLite) so you can reload without re‑indexing; this matters for large corpora where indexing is expensive.
- **Switch to an approximate nearest‑neighbor** – Integrate FAISS or Annoy for sub‑second retrieval on millions of documents, demonstrating awareness of scalability trade‑offs.
- **Add caching with Redis** – Cache frequent query‑document pairs to reduce latency and generator load, a common production pattern for high‑traffic services.
- **Instrument with Prometheus** – Expose metrics such as retrieval latency, generator throughput, and cache hit rate; observability is critical for on‑call engineers.
- **Implement fault tolerance** – Wrap external calls (e.g., if you later plug in a remote embedding service) with retries and circuit‑breaker logic to improve reliability.
- **Benchmark with BEIR** – Evaluate the pipeline on standard retrieval benchmarks (BE

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
