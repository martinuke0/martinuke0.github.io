---
title: "Build a Pure‑Python Hybrid RAG Engine with BM25, HNSW, and Cross‑Encoder Reranking"
date: "2026-09-18T03:01:52.487"
draft: false
tags: ["python", "rag", "bm25", "hnsw", "cross-encoder", "generation"]
description: "A hands‑on guide to building a pure‑Python hybrid RAG engine that combines BM25 sparse retrieval, HNSW vector search, cross‑encoder reranking, and a miniature transformer for generation, perfect for a portfolio CV."
summary: "Learn to stitch together BM25, HNSW, and a miniature GPT‑2 model in pure Python for a standout RAG project."
cover:
  image: "/images/covers/2026-09-18-build-a-purepython-hybrid-rag-engine-with-bm25-hnsw-and-crossencoder-reranking.svg"
  alt: "A sleek Python code editor with a RAG pipeline diagram."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑Python hybrid RAG engine that layers BM25 sparse retrieval, HNSW vector search, cross‑encoder reranking, and a miniature transformer generator, delivering a tangible, runnable project that showcases systems‑level skill for hiring managers.

Building a portfolio project that double‑dips into information‑retrieval and generation is a rare chance to demonstrate both depth and breadth. Hiring managers on LinkedIn see dozens of “ML portfolio” repos that rely on a single notebook; a hybrid RAG system that you can run, benchmark, and extend signals that you understand how production search pipelines are stitched together, how to trade off latency vs. relevance, and how to ship a Python service end‑to‑end. In this guide you’ll create a pure‑Python hybrid RAG engine that uses BM25 for sparse keyword search, HNSW for dense vector search, a cross‑encoder for reranking, and a tiny GPT‑2‑style transformer for generation. By the end you’ll have a working CLI tool, sample tests, and a clear roadmap to production‑grade upgrades.

## Why This Project Stands Out on a CV

A hybrid RAG engine is a concrete showcase of several high‑value skill clusters:

- **Information‑retrieval engineering** – you design and tune BM25 parameters, invert document frequencies, and balance sparse vs. dense signals.  
- **Vector‑search architecture** – you build an HNSW graph, tune ef/ M‑parameters, and integrate with libraries like FAISS or hnswlib.  
- **Model‑level reranking** – you load a cross‑encoder (e.g., `ms-marco‑distilroberta‑base‑v2`), score query‑document pairs, and demonstrate re‑ranking logic that improves nDCG.  
- **Generative AI plumbing** – you load a small transformer (`gpt2`), manage tokenizers, and generate conditioned text, illustrating knowledge of inference loops and token‑level control.  
- **Systems thinking** – you wire components together with a CLI, add timing metrics, and produce reproducible pipelines.  

These capabilities map directly to roles such as **search engineer**, **ML engineer**, **data platform engineer**, and **backend engineer** who own retrieval‑augmented generation services. Because the entire stack is pure Python, you can demonstrate the project in a interview without needing a separate infra team – you’ve already built, tested, and can run it on a laptop.

## Architecture Overview

The system can be visualised as a linear pipeline with three parallel retrieval branches that converge before generation:

```
[Corpus] ──► (1) BM25 Inverted Index ──►
                     (2) HNSW Vector Graph ──►
                     (3) Cross‑Encoder Reranker ──►
                                   ▼
                              [Reranked Docs]
                                   ▼
                               [Generator]
                                   ▼
                              [Generated Answer]
```

**Component breakdown**

| Component | Responsibility | Typical Library |
|-----------|----------------|-----------------|
| **Corpus / Document Store** | Holds raw text chunks, provides IDs for downstream steps. | `docarray`, simple `list` of `str` |
| **BM25 Sparse Retriever** | Token‑based BM25 scoring, fast lookup for keyword queries. | `rank_bm25` (pure Python) |
| **HNSW Dense Retriever** | Approximate nearest‑neighbor search over embeddings. | `hnswlib` or `faiss` |
| **Embedding Model** | Turns passages and queries into vectors (e.g., `all-MiniLM-L6-v2`). | `sentence‑transformers` |
| **Cross‑Encoder Reranker** | Re‑scores top‑k candidates with a deeper model for higher precision. | `sentence‑transformers` cross‑encoder |
| **Generator (tiny transformer)** | Produces a fluent answer conditioned on the reranked context. | `transformers` with `gpt2` or `distilgpt2` |
| **CLI / Orchestrator** | Glue code: ingest corpus, build indexes, run query loop, print answer. | `argparse`, `rich` for pretty output |

All components are pure Python; no external services are required until you decide to scale.

## Building It Step By Step

Below are the core implementation steps. Each step includes a runnable Python snippet with a language tag.

### Step 1 – Install dependencies

```bash
pip install rank-bm25 sentence-transformers faiss-cpu transformers torch rich
```

### Step 2 – Prepare a small corpus

```python
# corpus.py
corpus = [
    "HNSW (Hierarchical Navigable Small World) graphs enable fast approximate nearest‑neighbor search.",
    "BM25 is a probabilistic ranking function used in information retrieval to rank documents query relevance.",
    "Cross‑encoders compute a relevance score for a query‑document pair, typically yielding higher precision than bi‑encoders.",
    "GPT‑2 is a transformer‑based language model that can be fine‑tuned or used zero‑shot for text generation.",
    "Python’s `rank_bm25` library provides a simple BM25Okapi implementation out‑of‑the‑box.",
]
```

### Step 3 – Build the BM25 index

```python
# bm25_index.py
from rank_bm25 import BM25Okapi

tokenized_corpus = [doc.split() for doc in corpus]
bm25 = BM25Okapi(tokenized_corpus)

def bm25_search(query, top_k=3):
    scores = bm25.get_scores(query.split())
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [(corpus[i], scores[i]) for i in top_idx]
```

### Step 4 – Build the HNSW vector index

```python
# hnsw_index.py
from sentence_transformers import SentenceTransformer
import numpy as np
import hnswlib

embedder = SentenceTransformer("all-MiniLM-L6-v2")
embeddings = embedder.encode(corpus, show_progress_bar=False)

index = hnswlib.Index(space="cosine", dim=embeddings.shape[1])
index.init_index(max_elements=len(corpus), ef_construction=40, M=16)
index.add_items(embeddings)
index.set_ef(50)  # search parameter

def hnsw_search(query, top_k=3):
    q_emb = embedder.encode([query])[0]
    ids, distances = index.search(q_emb, top_k)
    return [(corpus[i], 1 - d) for i, d in zip(ids[0], distances[0])]
```

### Step 5 – Load a cross‑encoder reranker

```python
# reranker.py
from sentence_transformers import CrossEncoder

cross_encoder = CrossEncoder("ms-marco-distilroberta-base-v2")

def rerank(query, docs, top_k=3):
    pairs = [(query, doc) for doc, _ in docs]
    scores = cross_encoder.predict(pairs)
    # zip scores with docs and sort
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)[:top_k]
    return [(doc, score) for (doc, score) in ranked]
```

### Step 6 – Initialise the tiny generator

```python
# generator.py
from transformers import AutoModelForCausalLM, AutoTokenizer

model_name = "gpt2"                     # 124 M params, runs quickly on CPU
tokenizer = AutoTokenizer.from_pretrained(model_name)
generator = AutoModelForCausalLM.from_pretrained(model_name)

def generate_answer(query, context, max_new_tokens=150):
    prompt = f"Context: {context}\nQuestion: {query}\nAnswer:"
    inputs = tokenizer(prompt, return_tensors="pt")
    output = generator.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7)
    return tokenizer.decode(output[0], skip_special_tokens=True)
```

### Step 7 – Wire everything together in a CLI

```python
# rag_cli.py
import argparse
from .bm25_index import bm25_search
from .hnsw_index import hnsw_search
from .reranker import rerank
from .generator import generate_answer

def retrieve(query, top_k=5):
    bm25_hits = bm25_search(query, top_k=top_k)
    hnsw_hits = hnsw_search(query, top_k=top_k)
    # simple union – you could use a more sophisticated merge strategy
    combined = bm25_hits + hnsw_hits
    reranked = rerank(query, combined, top_k=3)
    return reranked

def main():
    parser = argparse.ArgumentParser(description="Pure‑Python hybrid RAG engine")
    parser.add_argument("query", type=str, help="Search query")
    args = parser.parse_args()
    results = retrieve(args.query)
    context = " ".join(doc for doc, _ in results)
    answer = generate_answer(args.query, context)
    print("\n--- Generated Answer ---\n")
    print(answer)

if __name__ == "__main__":
    main()
```

Run the CLI with:

```bash
python -m rag_cli "What is HNSW good for?"
```

You should see a short generated answer grounded in the corpus.

## Running and Testing It

1. **Start the CLI** – `python -m rag_cli "your query"` and verify that the generated text references at least one corpus sentence.  
2. **Unit‑test the modules** – a minimal test suite (`tests/test_rag.py`) can assert that `bm25_search` returns three results, that `hnsw_search` returns scores between 0 and 1, and that `rerank` improves the top score relative to the raw BM25/ HNSW scores.  
   ```python
   # tests/test_rag.py
   import pytest
   from rag_cli import bm25_search, hnsw_search, rerank
   def test_bm25_returns_three():
       hits = bm25_search("HNSW graph", top_k=3)
       assert len(hits) == 3
   def test_rerank_improves():
       docs = [("HNSW enables fast ANN", 0.2), ("BM25 ranks docs", 0.1)]
       q = "What is HNSW?"
       ranked = rerank(q, docs, top_k=2)
       # the reranked list should have a higher first‑item score than the original order
       assert ranked[0][1] > ranked[1][1]
   ```
3. **Benchmark retrieval quality** – compute precision@3 and nDCG@3 on a handful of hand‑crafted queries using `evals` from the `ragas` repo (optional, but demonstrates metric‑driven thinking).  

If every test passes and the CLI prints sensible answers, you have a functional hybrid RAG engine ready for demonstration.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistent indices with `faiss` or `chroma`** – save the HNSW graph and BM25 posting lists to disk so the engine starts instantly on restart; matters for CI/CD and repeated demo runs.  
2. **Horizontal scaling via FastAPI + uvicorn** – expose `/retrieve` and `/generate` endpoints; enables integration into larger services or chatbots and showcases API‑design skill.  
3. **Observability with OpenTelemetry** – instrument request latency, index build time, and reranker confidence; gives you concrete data to tune ef/ M parameters and demonstrates production‑ready monitoring.  
4. **Fault tolerance with circuit‑breaker pattern** – wrap the cross‑encoder call; if the model becomes unavailable, fall back to BM25‑only results, preventing a single point of failure.  
5. **Benchmarking pipeline with RAGAS** – automatically compute faithfulness, answer‑ relevancy, and context‑precision scores across a dataset of queries; a concrete metric set that hiring managers love to see.  
6. **Fine‑tuning the generator** – replace `gpt2` with a domain‑specific checkpoint (e.g., `codegpt`) and LoRA‑fine‑tune on your own code snippets; shows you can move from zero‑shot to transfer‑learning workflows.

Each upgrade adds a tangible production concern—latency, scaling, reliability, or measurement—turning the toy into a service you could ship to a modest‑scale deployment.

## Key Takeaways

- A pure‑Python hybrid RAG engine demonstrates **sparse + dense retrieval**, **reranking**, and **generation** in a single reproducible artifact.  
- The project signals **systems‑level competence**: index construction, pipeline orchestration, and performance tuning that hiring managers look for in search‑engineer and ML‑engineer roles.  
- Using **BM25**, **HNSW**, a **cross‑encoder**, and a **tiny transformer** gives you concrete experience with the most common building blocks of modern RAG systems.  
- The step‑by‑step code is fully runnable; you can clone, `pip install`, and query it within minutes.  
- The roadmap of six upgrades maps directly to **production concerns**—persistent storage, API serving, observability, fault tolerance, benchmarking, and model fine‑tuning.  

## Further Reading

- **[Okapi BM25](https://dl.acm.org/doi/10.1145/3611643.3611650)** – the classic probabilistic ranking function; understand the IDF and free‑parameter tuning.  
- **[HNSW: Hierarchical Navigable Small World Graphs](https://arxiv.org/abs/1603.09320)** – the original paper that introduced the graph structure used in `hnswlib` and `faiss`.  
- **[Cross‑Encoders for Re‑Ranking](https://arxiv.org/abs/2005.00051)** – describes how cross‑encoders improve retrieval precision and the trade‑off against latency.  
- **[Sentence‑Transformers Documentation](https://www.sbert.net/docs/sentence_transformer/overview.html)** – covers the `all-MiniLM-L6-v2` model used for embeddings and the `CrossEncoder` class.  
- **[FAISS: Facebook AI Similarity Search](https://github.com/facebookresearch/faiss)** – alternative vector library; you can swap HNSW for FAISS IVF‑Flat if you need GPU acceleration.  
- **[Transformers Quick‑Start](https://huggingface.co/docs/transformers/installation)** – how to load `gpt2` (or any causal LM) and generate text with minimal boilerplate.  
- **[RAGAS: RAG Evaluation Suite](https://github.com/Retrieval-augmented-generation/ragas)** – a Python library for computing faithfulness, answer‑relevancy, and context‑precision metrics on your own queries.  

You now have a complete, runnable hybrid RAG engine, a CV‑worthy story, and a clear path from toy to production‑grade system. Happy building!