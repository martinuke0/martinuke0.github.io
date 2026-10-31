---
title: "Hybrid Vector–Keyword Retriever with Reciprocal Rank Fusion"
date: "2026-10-31T10:03:59.857"
draft: false
tags: ["retrieval", "vector-search", "keyword-search", "rrf", "python", "systems"]
description: "Build a hybrid vector–keyword retriever using reciprocal rank fusion, with runnable Python code and production‑grade extensions for engineers."
summary: "A hands‑on guide to implementing a hybrid retriever that combines dense and sparse signals with RRF, perfect for a portfolio project."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-31-hybrid-vectorkeyword-retriever-with-reciprocal-rank-fusion.svg"
  alt: "Hybrid retriever architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — This post shows how to build a hybrid retriever that fuses dense vector embeddings with traditional BM25 keyword scores using reciprocal rank fusion, yielding robust search results. The implementation is fully runnable in Python, includes evaluation against a labeled set, and highlights the systems skills that catch a recruiter's eye.

Search engines are increasingly expected to understand both the exact wording of a query and its underlying semantics. A hybrid retriever that combines dense (vector) and sparse (keyword) signals is the industry‑standard way to achieve this, and reciprocal rank fusion (RRF) is a simple yet powerful method to merge the two rankings. In this guide you will build such a system from scratch, expose it via a FastAPI service, and learn how to evolve it into a production‑grade component.

## Why This Project Stands Out on a CV

- **End‑to‑end retrieval system design** – you will own the full pipeline: corpus ingestion, indexing, ranking, fusion, and API exposure.
- **Dual‑signal expertise** – demonstrates proficiency in dense embeddings (Sentence Transformers) *and* classic probabilistic retrieval (BM25).
- **Algorithm implementation** – you will code reciprocal rank fusion yourself, showing you understand rank‑level aggregation rather than just calling a library.
- **Evaluation rigor** – includes a labeled test set and metrics like MRR and recall@k, proving you care about measurable performance.
- **Production‑ready packaging** – FastAPI endpoint, Docker‑friendly structure, and clear extension points for scaling, persistence, and observability.
- **Narrative for hiring managers** – the project tells a story of turning raw text into a low‑latency, high‑accuracy search service—exactly the kind of impact that signals senior‑level systems thinking.

## Architecture Overview

The system is composed of five logical blocks:

1. **Document Store** – a simple in‑memory list of `{id, text}` dictionaries (later replaceable with PostgreSQL + pgvector).
2. **Sparse Index** – a BM25 index built with `rank_bm25` that scores documents based on term frequency and document frequency.
3. **Dense Encoder** – a Sentence Transformer model (e.g., `all-MiniLM-L6-v2`) that maps each document and query into a 384‑dimensional vector space.
4. **Fusion Layer** – implements reciprocal rank fusion: for each document, compute `score = Σ 1 / (k + rank_in_list)` across both rankings, then sort by descending score.
5. **API Layer** – a FastAPI application exposing a `/search` endpoint that accepts a query string, runs both retrievers, applies RRF, and returns the top‑k results.

A textual diagram of the flow:

```
Client → FastAPI → [BM25 Retrieval] ↘
                     [Vector Retrieval] → RRF Fusion → Top‑k Results
```

## Building It Step by Step

### 1. Project Setup

Create a directory and a virtual environment:

```bash
mkdir hybrid-retriever
cd hybrid-retriever
python -m venv .venv
source .venv/bin/activate
```

Install the core dependencies:

```bash
pip install fastapi uvicorn rank_bm25 sentence-transformers scikit-learn
```

### 2. Prepare a Corpus

For demonstration we use a small set of technical documents. In production this would be your knowledge base.

```python
# corpus.py
documents = [
    {"id": 1, "text": "PostgreSQL is an ACID-compliant relational database with strong consistency guarantees."},
    {"id": 2, "text": "Redis is an in‑memory data store often used for caching and pub/sub messaging."},
    {"id": 3, "text": "Kafka is a distributed streaming platform that enables high‑throughput, fault‑tolerant pipelines."},
    {"id": 4, "text": "Docker containers package applications with their dependencies for consistent deployment."},
    {"id": 5, "text": "Kubernetes orchestrates containerized workloads, providing scaling, load balancing, and self‑healing."},
]
```

### 3. Build the BM25 Index

```python
# bm25_retriever.py
from rank_bm25 import BM25Okapi
from nltk.tokenize import word_tokenize
from corpus import documents

# Tokenize the corpus
corpus_tokens = [word_tokenize(doc["text"].lower()) for doc in documents]
bm25 = BM25Okapi(corpus_tokens)

def bm25_search(query: str, top_k: int = 5):
    query_tokens = word_tokenize(query.lower())
    scores = bm25.get_scores(query_tokens)
    # Pair each score with the document id
    ranked = sorted(zip(scores, [d["id"] for d in documents]), key=lambda x: x[0], reverse=True)
    return ranked[:top_k]
```

### 4. Generate Dense Embeddings

```python
# dense_retriever.py
from sentence_transformers import SentenceTransformer
from corpus import documents
import numpy as np

model = SentenceTransformer("all-MiniLM-L6-v2")

# Pre‑compute document embeddings
doc_texts = [doc["text"] for doc in documents]
doc_embeddings = model.encode(doc_texts, show_progress_bar=True)

def dense_search(query: str, top_k: int = 5):
    query_emb = model.encode([query])[0]
    # Cosine similarity
    similarities = np.dot(doc_embeddings, query_emb) / (
        np.linalg.norm(doc_embeddings, axis=1) * np.linalg.norm(query_emb)
    )
    ranked = sorted(zip(similarities, [d["id"] for d in documents]), key=lambda x: x[0], reverse=True)
    return ranked[:top_k]
```

### 5. Implement Reciprocal Rank Fusion

```python
# rrf.py
def reciprocal_rank_fusion(bm25_ranks, dense_ranks, k=60):
    """
    bm25_ranks: list of (score, doc_id) from BM25
    dense_ranks: list of (score, doc_id) from dense retriever
    k: constant added to rank (default 60 as per the original paper)
    Returns a list of (rrf_score, doc_id) sorted descending.
    """
    from collections import defaultdict
    rrf_scores = defaultdict(float)

    for rank, (_, doc_id) in enumerate(bm25_ranks, start=1):
        rrf_scores[doc_id] += 1.0 / (k + rank)

    for rank, (_, doc_id) in enumerate(dense_ranks, start=1):
        rrf_scores[doc_id] += 1.0 / (k + rank)

    # Sort by descending RRF score
    sorted_rrf = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_rrf
```

### 6. Combine Retrieval and Expose via FastAPI

```python
# main.py
from fastapi import FastAPI, Query
from bm25_retriever import bm25_search
from dense_retriever import dense_search
from rrf import reciprocal_rank_fusion
from corpus import documents

app = FastAPI(title="Hybrid Retriever")

@app.get("/search")
def search(query: str, top_k: int = 5):
    # Get top 10 from each retriever (wider pool for fusion)
    bm25_ranks = bm25_search(query, top_k=10)
    dense_ranks = dense_search(query, top_k=10)

    # Apply RRF
    fused = reciprocal_rank_fusion(bm25_ranks, dense_ranks)

    # Return top_k results with their texts
    results = []
    for doc_id, score in fused[:top_k]:
        doc = next(d for d in documents if d["id"] == doc_id)
        results.append({"id": doc_id, "text": doc["text"], "rrf_score": score})

    return {"query": query, "results": results}
```

### 7. Run the Service

```bash
uvicorn main:app --reload
```

Now you can query the API:

```bash
curl "http://localhost:8000/search?query=streaming+platform&top_k=3"
```

## Running and Testing It

### Local End‑to‑End Test

Create a small script that sends a few queries and prints the rankings:

```python
# test_search.py
import requests

queries = [
    "distributed streaming",
    "container orchestration",
    "in‑memory cache"
]

for q in queries:
    resp = requests.get("http://localhost:8000/search", params={"query": q, "top_k": 3})
    data = resp.json()
    print(f"\nQuery: {q}")
    for r in data["results"]:
        print(f"  ID {r['id']}: {r['text'][:60]}... (RRF {r['rrf_score']:.4f})")
```

Run it:

```bash
python test_search.py
```

### Evaluation Metrics

To quantify performance, you need a labeled set. For each query, annotate the relevant document IDs. Then compute:

```python
# evaluate.py
from sklearn.metrics import ndcg_score
import numpy as np

def compute_mrr(retrieved_ids, relevant_ids):
    for i, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / i
    return 0.0

def compute_recall_at_k(retrieved_ids, relevant_ids, k):
    return len(set(retrieved_ids[:k]) & set(relevant_ids)) / len(relevant_ids)

# Example labeled data
labels = {
    "distributed streaming": {3},
    "container orchestration": {5},
    "in‑memory cache": {2}
}

# After obtaining results from /search, compute metrics
```

A simple script that calls the API, extracts the ordered IDs, and averages MRR and Recall@5 will give you a concrete number to include on your résumé.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence with PostgreSQL + pgvector** – Store documents and embeddings in a relational DB, enabling efficient ANN search via pgvector’s `ivfflat` index. This moves you from in‑memory prototypes to a durable, queryable store.
2. **Horizontal Scaling via Kubernetes** – Package the FastAPI app as a Docker image, deploy multiple replicas behind a load balancer, and use a distributed cache (Redis) for query results. This demonstrates you can handle traffic spikes and stateless scaling.
3. **Observability Stack** – Instrument the service with OpenTelemetry, expose Prometheus metrics (latency, hit‑rate), and build Grafana dashboards. Observability is a hallmark of mature production systems.
4. **Fault Tolerance & Resilience** – Add retry logic with exponential backoff for the embedding model calls, and implement a circuit‑breaker around the BM25 index if it ever becomes unavailable. This shows you anticipate failure modes.
5. **Benchmarking with Locust** – Write a load‑test script that simulates concurrent users issuing queries, measuring throughput (requests/sec) and p99 latency. Benchmark data is compelling evidence of performance claims.
6. **Caching Layer** – Cache frequent query‑result pairs in Redis with a TTL, reducing latency and load on the underlying retrievers. Caching is a classic technique for improving user‑perceived responsiveness.

## Key Takeaways

- Building a hybrid retriever combines **dense** (semantic) and **sparse** (lexical) signals, each covering different failure modes.
- **Reciprocal rank fusion** is a parameter‑light, mathematically grounded way to merge rankings without training a separate model.
- The project showcases **full‑stack retrieval engineering**: indexing, ranking, fusion, API design, evaluation, and production‑grade extensions.
- By adding persistence, scaling, observability, and resilience, you transform a prototype into a **deployable microservice** that can be discussed in interviews as a real system.
- Including **metrics** (MRR, recall@k) and **benchmark results** turns the project from a code sample into a performance‑validated artifact.

## Further Reading

- **Reciprocal Rank Fusion Paper** – The original SIGIR 2010 paper that introduced RRF: [Reciprocal Rank Fusion Outperforms Condorcet and Range Voting](https://www.cs.umd.edu/~gasg/sigir2010/RRF.pdf).
- **BM25 Wikipedia** – A concise overview of the probabilistic model underlying keyword retrieval: [BM25](https://en.wikipedia.org/wiki/BM25).
- **Sentence Transformers Documentation** – Learn how to fine‑tune and deploy dense encoders: [sbert.net](https://www.sbert.net/).
- **FastAPI Official Guide** – Build robust, async APIs with automatic OpenAPI docs: [FastAPI](https://fastapi.tiangolo.com/).
- **pgvector Extension** – Add vector similarity search to PostgreSQL: [pgvector GitHub](https://github.com/pgvector/pgvector).
- **Kubernetes Production Guide** – Deep dive into scaling, self‑healing, and rolling updates: [Kubernetes Docs](https://kubernetes.io/docs/home/).

These resources will help you deepen your understanding of each component and guide the next steps toward a production‑ready retrieval service.

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
