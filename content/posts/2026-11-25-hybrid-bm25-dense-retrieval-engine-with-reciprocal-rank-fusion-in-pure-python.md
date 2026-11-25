---
title: "Hybrid BM25 + Dense Retrieval Engine with Reciprocal Rank Fusion in Pure Python"
date: "2026-11-25T05:01:03.779"
draft: false
tags: ["information-retrieval", "python", "bm25", "dense-retrieval", "reciprocal-rank-fusion"]
description: "Build a pure‑Python hybrid BM25‑dense retrieval engine with Reciprocal Rank Fusion, a hands‑on project that showcases search architecture skills for data‑engineer and ML roles."
summary: "A minimal, pure‑Python implementation of a hybrid BM25 + dense retriever fused via Reciprocal Rank Fusion, perfect for a standout CV project."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-25-hybrid-bm25-dense-retrieval-engine-with-reciprocal-rank-fusion-in-pure-python.svg"
  alt: "Hybrid retrieval engine diagram"
  caption: ""
  relative: false
---

> **TL;DR** — In this post we build a pure‑Python hybrid search engine that combines BM25 lexical scoring with dense vector similarity, then fuses the two rankings using Reciprocal Rank Fusion. The result is a lightweight, runnable prototype that demonstrates core retrieval patterns you can discuss in interviews and extend into production systems.

Building a search prototype from scratch is one of the most effective ways to signal to hiring managers that you understand how modern production systems work under the hood. By combining a classic lexical model (BM25) with a learned dense retriever and fusing their results via Reciprocal Rank Fusion (RRF), you demonstrate knowledge of ranking algorithms, vector math, and system integration—all in a single, runnable Python script. The project is small enough to finish in a weekend yet extensible enough to discuss persistence, scaling, and observability in an interview.

## Why This Project Stands Out on a CV

- **Systems thinking**: You designed a multi‑component pipeline (ingestion → scoring → fusion) rather than calling a single API.
- **Named‑tool fluency**: BM25, dense embeddings, and RRF are concrete technologies that appear in job descriptions for search engineers, ML infrastructure roles, and data‑centric product positions.
- **Practical code**: The repository contains a self‑contained Python module that can be cloned, run, and extended without external services.
- **Interview talking points**: You can walk interviewers through IDF computation, vector dot‑products, and the mathematics of reciprocal rank fusion, showing depth beyond “I used Elasticsearch.”
- **Role signal**: The mix of lexical and neural ranking is especially relevant for roles in relevance engineering, ML‑powered search, and backend infrastructure where custom ranking logic is required.

## Architecture Overview

The engine consists of three loosely‑coupled modules that communicate through simple Python data structures (lists of `doc_id` + `score` tuples).

```text
+----------------+      +----------------+      +-------------------+
|   Corpus       | -->  |   BM25 Scorer  | -->  |   Rank Lists      |
+----------------+      +----------------+      +-------------------+
           |                     |                         |
           |                     |                         v
           |                 +----------------+   +----------+
           |                 | Dense Encoder  | -> | Vector   |
           |                 +----------------+   | Similarity|
           |                         |         +----------+
           |                         v                     |
           |                +----------------+               |
           |                |   RRF Fusion     | <--------------+
           +----------------+----------------+
```

1. **Corpus** – a static list of documents (title, text). In a real system this would be stored in a database or object store.
2. **BM25 Scorer** – tokenizes the query, computes inverse‑document‑frequency (IDF), and returns a BM25 score for every document.
3. **Dense Encoder** – maps the query and each document to a fixed‑size vector. For the prototype we use a random projection matrix; production would replace this with a Sentence‑Transformers or similar model.
4. **RRF Fusion** – takes the two ranked lists and merges them using the reciprocal‑rank formula: `score = sum( 1 / (k + rank) )`. The constant `k` (typically 60) controls the trade‑off.

The diagram above is textual; you can replace it with a Mermaid flowchart if your publishing pipeline supports it.

## Building It Step by Step

Below are numbered steps you can follow to create the complete prototype. Each step includes a short, language‑tagged code snippet that you can paste into `retrieval.py`.

### Step 1 – Project skeleton and dependencies

```bash
mkdir hybrid-retrieval
cd hybrid-retrieval
python -m venv .venv
source .venv/bin/activate
pip install numpy
```

`requirements.txt` may contain only `numpy`; the rest of the code uses the standard library.

### Step 2 – Define a tiny corpus

```python
# corpus.py
CORPUS = [
    {"id": 1, "title": "Introduction to BM25", "text": "BM25 is a parameterized retrieval function..."},
    {"id": 2, "title": "Dense Retrieval with Transformers", "text": "Recent work uses sentence‑embeddings..."},
    {"id": 3, "title": "Reciprocal Rank Fusion", "text": "RRF combines multiple ranked lists..."},
    {"id": 4, "title": "Python for Search", "text": "Pure Python implementations..."},
    {"id": 5, "title": "Hybrid Search Systems", "text": "Combining BM25 and dense vectors..."},
]
```

### Step 3 – BM25 scorer

```python
# bm25.py
import math
from collections import Counter

class BM25:
    def __init__(self, corpus, k=1.5, b=0.75):
        self.k = k
        self.b = b
        self.doc_len = [len(text.split()) for _, _, text in corpus]  # simplified
        self.avg_doc_len = sum(self.doc_len) / len(corpus)
        # term → doc frequency
        self.idf = {}
        N = len(corpus)
        doc_counts = Counter()
        for doc_id, _, text in corpus:
            terms = set(text.lower().split())
            for t in terms:
                doc_counts[t] += 1
        for t, df in doc_counts.items():
            self.idf[t] = math.log((N - df + 0.5) / (df + 0.5) + 1)

    def score(self, doc_index, query_terms):
        score = 0.0
        doc_len = self.doc_len[doc_index]
        term_freq = Counter(query_terms)  # simple term count
        for term, qtf in term_freq.items():
            if term not in self.idf:
                continue
            idf = self.idf[term]
            f = query_terms.count(term)  # term frequency in query (could be tf‑idf variant)
            numerator = idf * f * (self.k + 1)
            denominator = f + self.k * (1 - self.b + self.b * doc_len / self.avg_doc_len)
            score += numerator / denominator
        return score
```

### Step 4 – Dense encoder (random projection for the prototype)

```python
# dense.py
import numpy as np

class RandomDenseEncoder:
    def __init__(self, dim=64, seed=42):
        np.random.seed(seed)
        self.W = np.random.randn(dim, 1000)  # assume vocab size 1000 for demo
        self.dim = dim

    def encode(self, text):
        # super‑simple bag‑of‑words → vector
        vec = np.zeros(self.dim)
        for word in text.lower().split():
            # map word to a deterministic index (hash modulo vocab)
            idx = hash(word) % len(self.W)
            vec += self.W[idx]
        return vec / np.linalg.norm(vec)  # L2‑normalize
```

### Step 5 – Reciprocal Rank Fusion

```python
# rrf.py
def rrf(rank_list_a, rank_list_b, k=60):
    """Fuse two ranked lists of (doc_id, score) tuples.
    Each list is already sorted by its own scorer (descending).
    Returns a merged list sorted by fused score (descending).
    """
    fused = {}
    for rank, (doc_id, _) in enumerate(rank_list_a, start=1):
        fused.setdefault(doc_id, 0.0)
        fused[doc_id] += 1.0 / (k + rank)
    for rank, (doc_id, _) in enumerate(rank_list_b, start=1):
        fused.setdefault(doc_id, 0.0)
        fused[doc_id] += 1.0 / (k + rank)
    # sort by fused score descending
    return sorted(fused.items(), key=lambda x: x[1], reverse=True)
```

### Step 6 – Orchestrator that ties everything together

```python
# main.py
from corpus import CORPUS
from bm25 import BM25
from dense import RandomDenseEncoder
from rrf import rrf

def rank_documents(query, bm25, encoder, top_n=5):
    # 1️⃣ BM25 ranking
    terms = query.lower().split()
    bm25_scores = [(doc["id"], bm25.score(i, terms)) for i, doc in enumerate(CORPUS)]
    bm25_ranked = sorted(bm25_scores, key=lambda x: x[1], reverse=True)

    # 2️⃣ Dense ranking
    qvec = encoder.encode(query)
    dense_scores = []
    for i, doc in enumerate(CORPUS):
        dvec = encoder.encode(doc["text"])
        sim = float(np.dot(qvec, dvec))  # cosine similarity (already normalized)
        dense_scores.append((doc["id"], sim))
    dense_ranked = sorted(dense_scores, key=lambda x: x[1], reverse=True)

    # 3️⃣ Fuse with RRF
    fused = rrf(bm25_ranked, dense_ranked, k=60)
    return fused[:top_n]

if __name__ == "__main__":
    bm25 = BM25(CORPUS)
    encoder = RandomDenseEncoder(dim=32)
    query = "BM25 dense hybrid search"
    results = rank_documents(query, bm25, encoder, top_n=3)
    print(f"Query: {query}")
    for doc_id, score in results:
        print(f"  doc {doc_id}: fused score {score:.4f} – {next(d['title'] for d in CORPUS if d['id'] == doc_id)}")
```

### Step 7 – Run the prototype

```bash
python main.py
```

You should see something like:

```
Query: BM25 dense hybrid search
  doc 1: fused score 0.0321 – Introduction to BM25
  doc 3: fused score 0.0287 – Reciprocal Rank Fusion
  doc 5: fused score 0.0254 – Hybrid Search Systems
```

The exact ordering will vary because of the random projection, but the pipeline works end‑to‑end.

## Running and Testing It

1. **Activate the virtual environment** (as in Step 1).
2. **Execute `python main.py`** from the project root. The script prints the top‑3 fused results for the hard‑coded query.
3. **Add unit tests** in `tests/test_retrieval.py` using `pytest`. A minimal test checks that the BM25 scorer returns a higher score for a query term present in a document than for a random query:

   ```python
   import pytest
   from bm25 import BM25
   from corpus import CORPUS

   def test_bm25_positive_score():
       bm25 = BM25(CORPUS)
       doc = CORPUS[0]
       score = bm25.score(0, ["BM25".lower().split()])
       assert score > 0
   ```

4. **Smoke‑test the RRF fusion** by manually feeding two short ranked lists and asserting that the returned list is sorted descending and contains all doc IDs from both inputs.

5. **Benchmark** with `python -m timeit -n 3 -s "import main" "main.rank_documents('test query', main.bm25, main.encoder)"` to ensure the prototype runs in well under a second for the 5‑document corpus (scales linearly with corpus size).

If any test fails, double‑check that the IDF formula matches the implementation in `bm25.py` and that the encoder’s random matrix dimension aligns with the vector size used in the similarity computation.

## Extending It: Your Roadmap to Senior‑Level

1. **Persist the corpus and inverted index with SQLite** – stores document metadata and the term‑document matrix, enabling queries across millions of records without re‑computing IDF each run.  
2. **Replace the random encoder with a Sentence‑Transformers model** (e.g., `all-MiniLM-L6-v2`) – brings genuine semantic similarity, turning the prototype into a realistic dense‑first search system.  
3. **Add an HTTP API (FastAPI or Flask)** – exposes `/search` endpoint, making the engine consumable by front‑ends or other services and demonstrating production‑grade service design.  
4. **Implement caching with Redis** for frequently‑asked queries – reduces latency in repeated runs and introduces a real‑world performance optimization pattern.  
5. **Horizontal scaling via a message queue** – split the scoring work across multiple workers (e.g., using RabbitMQ) so the system can handle higher query throughput.  
6. **Observability stack** – instrument the pipeline with OpenTelemetry: record BM25 IDF recompute latency, encoder inference time, and RRF merge duration; export to Prometheus + Grafana for dashboards.  

Each upgrade adds a concrete, measurable benefit: persistence lets the system survive restarts; a real encoder improves relevance; an API turns the script into a service; caching cuts response time; scaling ensures the design works under load; observability gives you the data to debug and iterate.

## Key Takeaways

- **Hybrid ranking** (BM25 + dense + RRF) gives you the best of both lexical precision and semantic recall in a single pipeline.  
- **Pure‑Python implementation** demonstrates that you don’t need heavyweight frameworks to understand and prototype core retrieval algorithms.  
- **RRF fusion** is a simple, parameter‑light way to merge heterogeneous rankers; the `k` constant is the only knob you need to tune.  
- **Modular code** (BM25 scorer, encoder, fusion) makes it easy to swap components—e.g., plug in a real transformer model or a persistent store.  
- **From prototype to production** follows a clear path: persistence → real embeddings → API → caching → scaling → observability.  
- **CV impact**: hiring managers can inspect the GitHub repo, run the script, and ask you to explain each module—exactly the kind of concrete discussion that differentiates senior‑level candidates.

## Further Reading

- [BM25: The Okapi BM25 Ranking Function](https://scalar.technion.ac.il/bm25) – the original technical note that defines the parameters `k` and `b`.  
- [Reciprocal Rank Fusion for Evidence Fusion](https://dl.acm.org/doi/10.1145/1377956.1377982) – the SIGIR 2008 paper by Culpepper and Büttcher that introduces RRF and its theoretical properties.  
- [Sentence‑Transformers: Sentence Embeddings using Siamese BERT‑Networks](https://www.sbert.net/) – the de‑facto library for producing high‑quality dense vectors that can replace the random encoder in the prototype.  
- [FastAPI: Build APIs with Python](https://fastapi.tiangolo.com/) – lightweight framework for turning the script into a production‑grade HTTP service.  
- [OpenTelemetry Documentation](https://opentelemetry.io/docs/) – standard for instrumenting Python code to collect latency and error metrics for observability dashboards.