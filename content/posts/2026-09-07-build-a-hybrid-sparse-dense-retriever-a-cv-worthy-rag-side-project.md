---
title: "Build a Hybrid Sparse-Dense Retriever: A CV-Worthy RAG Side Project"
date: "2026-09-07T17:10:03.951"
draft: false
tags: ["retrieval-augmented-generation", "hnsw", "bm25", "vector-search", "engineering-portfolio"]
description: "A hands-on build guide for a hybrid BM25 + embedding reranker retriever with a from-scratch HNSW index — a portfolio project that signals real systems skill."
summary: "Hands-on build guide for a hybrid sparse-dense retriever (BM25 + embedding reranking) with a from-scratch HNSW vector index. Real runnable code, architecture diagrams, and a roadmap to senior-level."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-hybrid-sparse-dense-retriever-a-cv-worthy-rag-side-project.svg"
  alt: "Diagram of a hybrid retriever with sparse and dense branches feeding a reranker."
  caption: ""
  relative: false
---

> **TL;DR** — A hybrid retriever combines BM25's lexical precision with dense embeddings' semantic recall, then reranks the top candidates with a cross-encoder. Building one from scratch — including your own HNSW index — demonstrates systems thinking that few CVs show: graph algorithms, ANN tuning, recall/precision trade-offs, and the kind of end-to-end engineering that hiring managers at search and AI teams actually look for.

## Why This Project Stands Out on a CV

Most "AI engineering" portfolios stop at "I called `OpenAI()` and streamed tokens." That signal is now table stakes. The projects that get callbacks in 2026 are the ones that show you understand the *machinery underneath* the API call. A hybrid sparse-dense retriever with a from-scratch HNSW index does exactly that.

Here is what the project concretely demonstrates:

- **Vector search fundamentals.** You have implemented, not just consumed, an approximate nearest neighbor algorithm. HNSW (Hierarchical Navigable Small Worlds) is the algorithm behind Pinecone, Weaviate, Qdrant, and pgvector's HNSW index — knowing its internals (`ef_construction`, `M`, layer assignment via random levels, neighbor pruning) means you can debug, tune, and reason about any vector DB you'll encounter at work. See the original [Malkov & Yashunin 2018 paper](https://arxiv.org/abs/1603.09320) for the source of truth.
- **Hybrid retrieval engineering.** Real production search is rarely "embeddings only." Teams at Elastic, Vespa, and Pinecone all run hybrid BM25 + dense pipelines because the failure modes of each method are complementary. Showing you know how to combine them — and *why* a cross-encoder reranker closes the gap — is a signal you've read the retrieval literature, not just the LangChain docs.
- **End-to-end systems thinking.** You'll wire together tokenization, inverted index maintenance, embedding generation, ANN search, and result fusion. That is the same shape as a production search service, just scoped down.
- **Roles it signals for:** ML Engineer (retrieval/RAG), Search Engineer, Applied AI Engineer, Backend Engineer with AI focus, and increasingly "Founding Engineer" roles at startups building search-heavy products.

The kicker: it is genuinely buildable in a weekend by one engineer. That ratio — high signal, low cost — is exactly what makes a side project worth doing.

## Architecture Overview

The system has four components that compose cleanly. Think of it as a pipeline with two parallel first-stage retrievers feeding a single reranker.

- **Corpus loader** — reads a document collection (e.g., a folder of `.txt` files, a JSONL dump, or a HuggingFace dataset) and yields normalized documents with a stable `doc_id`.
- **Sparse branch: BM25 index** — a from-scratch inverted index. For each document, tokenize, lowercase, optionally stem, compute term frequencies, then build a postings list `(term → [(doc_id, tf), ...])` along with document frequencies. At query time, score every document using the [Robertson-Sparck Jones BM25 formula](https://en.wikipedia.org/wiki/Okapi_BM25) and return the top-N.
- **Dense branch: HNSW index** — your own implementation. Documents are embedded once at index time using a sentence-transformer. At query time, embed the query, then perform greedy walk + neighbor expansion across the HNSW graph to find the top-N nearest vectors by cosine similarity.
- **Fusion + reranker** — merge the BM25 and HNSW candidate lists using reciprocal rank fusion, then send the top-K (e.g., 20) to a cross-encoder reranker (`cross-encoder/ms-marco-MiniLM-L-6-v2`) for the final ranking.

Text diagram of the request path:

```
                  ┌──────────────┐
        query ───►│   Tokenize   │
                  └──────┬───────┘
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
     ┌─────────────┐          ┌──────────────┐
     │  BM25 Index │          │  HNSW Index  │
     │ (inverted)  │          │  (embeddings)│
     └──────┬──────┘          └──────┬───────┘
            │ top-N_s                │ top-N_d
            └────────────┬───────────┘
                         ▼
                 ┌───────────────┐
                 │ Reciprocal    │
                 │ Rank Fusion   │
                 └──────┬────────┘
                        │ top-K
                        ▼
                ┌───────────────┐
                │ Cross-Encoder │
                │ Reranker      │
                └──────┬────────┘
                       │ final
                       ▼
                 ranked results
```

The reason this design is interesting: BM25 is fast and exact (inverted index + sorted postings) but fails on paraphrases and vocabulary mismatch. Dense retrieval is great on semantics but can be fooled by keyword-specific queries and has recall cliffs at small corpus sizes. The reranker, being a cross-encoder, sees both query and document together and produces the highest-quality scores — but it is too expensive to run over the whole corpus. Hybrid retrieval narrows the candidate set so the reranker can be used selectively.

## Building It Step by Step

We will build this as a single-file Python project first (`retriever.py`), then split it into modules. Keep your file layout like this:

```
hybrid-retriever/
├── retriever/
│   ├── __init__.py
│   ├── bm25.py
│   ├── hnsw.py
│   ├── embed.py
│   └── hybrid.py
├── app.py              # tiny CLI / demo
├── tests/
└── requirements.txt
```

`requirements.txt`:

```text
sentence-transformers>=2.7
numpy>=1.26
rank-bm25>=0.2
torch>=2.2
```

### Step 1 — BM25 from scratch

The most useful thing you can do is write BM25 yourself once. It removes the magic. We need term frequencies, document frequencies, document lengths, and the average document length.

```python
# retriever/bm25.py
import math
import re
from collections import defaultdict
from typing import Iterable

TOKEN_RE = re.compile(r"[a-z0-9]+")

def tokenize(text: str) -> list[str]:
    return TOKEN_RE.findall(text.lower())

class BM25:
    """From-scratch BM25 (Robertson-Sparck Jones) index."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = []
        self.doc_lens: list[int] = []
        self.avgdl: float = 0.0
        self.df: dict[str, int] = defaultdict(int)
        self.tf: list[dict[str, int]] = []  # per-doc term frequencies
        self.idf: dict[str, float] = {}

    def fit(self, documents: Iterable[str]) -> None:
        for text in documents:
            tokens = tokenize(text)
            self.docs.append(tokens)
            self.doc_lens.append(len(tokens))
            tf = defaultdict(int)
            for t in tokens:
                tf[t] += 1
                self.df[t] += 1
            self.tf.append(dict(tf))

        n = len(self.docs) or 1
        self.avgdl = sum(self.doc_lens) / n
        # IDF with the standard +1 smoothing
        for term, df in self.df.items():
            self.idf[term] = math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, top_n: int = 50) -> list[tuple[int, float]]:
        q_tokens = tokenize(query)
        scores = [0.0] * len(self.docs)
        for q in q_tokens:
            if q not in self.df:
                continue
            idf = self.idf[q]
            for doc_id, tf_doc in enumerate(self.tf):
                if q not in tf_doc:
                    continue
                tf = tf_doc[q]
                dl = self.doc_lens[doc_id]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[doc_id] += idf * (tf * (self.k1 + 1)) / denom
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in ranked[:top_n] if s > 0]
```

Two details to call out in your README when you ship this: (1) the IDF formula is the one with `+0.5` smoothing from the original BM25 papers — never use plain `log(N/df)`, it goes negative for common terms; (2) we store TF per document, not a global postings list, because our corpus is small. For a real corpus, switch to a true postings index.

### Step 2 — HNSW from scratch

This is the centerpiece. HNSW is a graph where each node (a vector) has short-range links to neighbors at its level, and a few long-range links to neighbors at higher levels. Search starts at a single entry point at the top level, greedily walks to the nearest neighbor, then descends a level and repeats. The trick is the insertion procedure, which uses an `ef_construction` beam search to pick the best M neighbors to link to, and assigns each node a random maximum layer drawn from an exponentially decaying distribution.

```python
# retriever/hnsw.py
import heapq
import math
import random
from typing import Iterable

import numpy as np

class HNSW:
    """Minimal HNSW index over cosine similarity."""

    def __init__(self, dim: int, M: int = 16, ef_construction: int = 200,
                 ef_search: int = 50, ml: float = 1.0 / math.log(2.0)):
        self.dim = dim
        self.M = M
        self.M_max0 = 2 * M
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.ml = ml
        self.vectors: list[np.ndarray] = []
        self.norm: list[float] = []
        # per-node neighbor lists: graph[level] -> list of (neighbor_id, distance)
        self.graph: list[list[list[tuple[int, float]]]] = []
        self.max_layer: int = -1
        self.entry: int = -1

    def _dist(self, i: int, vec: np.ndarray) -> float:
        # cosine distance = 1 - cosine similarity
        a = self.vectors[i] / (self.norm[i] + 1e-12)
        return 1.0 - float(np.dot(a, vec))

    def _random_level(self) -> int:
        return int(math.floor(-math.log(random.random()) * self.ml))

    def _search_layer(self, q: np.ndarray, entry_ids: list[int],
                      ef: int, level: int) -> list[tuple[int, float]]:
        visited = set(entry_ids)
        candidates: list[tuple[float, int]] = []  # (dist, id) min-heap
        results: list[tuple[float, int]] = []     # (dist, id) max-heap via negative
        for eid in entry_ids:
            d = self._dist(eid, q)
            heapq.heappush(candidates, (d, eid))
            heapq.heappush(results, (-d, eid))
        while candidates:
            d, curr = heapq.heappop(candidates)
            farthest = -results[0][0]
            if d > farthest and len(results) >= ef:
                break
            for nbr, _ in self.graph[curr][level]:
                if nbr in visited:
                    continue
                visited.add(nbr)
                d_n = self._dist(nbr, q)
                if d_n < farthest or len(results) < ef:
                    heapq.heappush(candidates, (d_n, nbr))
                    heapq.heappush(results, (-d_n, nbr))
                    if len(results) > ef:
                        heapq.heappop(results)
        return [(nid, -d) for d, nid in results]

    def add(self, vec: np.ndarray) -> int:
        v = vec.astype(np.float32)
        norm = float(np.linalg.norm(v))
        idx = len(self.vectors)
        self.vectors.append(v)
        self.norm.append(norm)
        level = self._random_level()
        self.graph.append([[] for _ in range(level + 1)])

        if self.entry == -1:
            self.entry = idx
            self.max_layer = level
            return idx

        ep = self.entry
        for L in range(self.max_layer, level, -1):
            res = self._search_layer(v, [ep], 1, L)
            ep = res[0][0]

        ep_ids = [ep]
        for L in range(min(level, self.max_layer), -1, -1):
            res = self._search_layer(v, ep_ids, self.ef_construction, L)
            M = self.M_max0 if L == 0 else self.M
            neighbors = sorted(res, key=lambda x: x[1])[:M]
            self.graph[idx][L] = neighbors
            for nid, _ in neighbors:
                existing = self.graph[nid][L]
                existing.append((idx, self._dist(nid, v)))
                existing.sort(key=lambda x: x[1])
                self.graph[nid][L] = existing[:M]
            ep_ids = [nid for nid, _ in res]

        if level > self.max_layer:
            self.entry = idx
            self.max_layer = level
        return idx

    def fit(self, vectors: Iterable[np.ndarray]) -> None:
        for v in vectors:
            self.add(v)

    def query(self, q: np.ndarray, k: int = 10) -> list[tuple[int, float]]:
        if self.entry == -1:
            return []
        q = q / (float(np.linalg.norm(q)) + 1e-12)
        ep = self.entry
        for L in range(self.max_layer, 0, -1):
            res = self._search_layer(q, [ep], 1, L)
            ep = res[0][0]
        res = self._search_layer(q, [ep], self.ef_search, 0)
        return sorted(res, key=lambda x: x[1])[:k]
```

Two things hiring managers will look for: the exponentially decaying level assignment (`_random_level`) and the neighbor pruning during insertion. If you do both correctly and your graph connects at the bottom layer, recall will be solid. Tune `M` and `ef_construction` together — see the guidance in the [HNSW paper](https://arxiv.org/abs/1603.09320) and the [FAISS HNSW docs](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-index-parameters-for-large-scale-similarity-search) for starting points.

### Step 3 — Dense embeddings

Use a sentence-transformer. For most CV projects, `all-MiniLM-L6-v2` is the right tradeoff between quality and speed.

```python
# retriever/embed.py
import numpy as np
from sentence_transformers import SentenceTransformer

class Embedder:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)

    def encode(self, texts: list[str], batch_size: int = 64,
               normalize: bool = True) -> np.ndarray:
        vecs = self.model.encode(
            texts, batch_size=batch_size, convert_to_numpy=True,
            normalize_embeddings=normalize, show_progress_bar=True
        )
        return vecs.astype(np.float32)
```

### Step 4 — Hybrid fusion + reranker

Reciprocal rank fusion is the simplest thing that does the job. Cross-encoder reranking is where the gains come from.

```python
# retriever/hybrid.py
from sentence_transformers import CrossEncoder
from .bm25 import BM25
from .hnsw import HNSW
from .embed import Embedder

def rrf(ranked_lists: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion across multiple ranked doc_id lists."""
    scores: dict[int, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=scores.get, reverse=True)

class HybridRetriever:
    def __init__(self):
        self.bm25 = BM25()
        self.embedder = Embedder()
        self.index = HNSW(dim=384)  # all-MiniLM-L6-v2 dim
        self.reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        self.docs: list[str] = []
        self.ids: list[str] = []

    def index_documents(self, ids: list[str], texts: list[str]) -> None:
        self.ids = list(ids)
        self.docs = list(texts)
        self.bm25.fit(texts)
        vecs = self.embedder.encode(texts)
        self.index.fit(v for v in vecs)

    def retrieve(self, query: str, n_sparse: int = 50, n_dense: int = 50,
                 n_final: int = 10) -> list[dict]:
        sparse = self.bm25.score(query, top_n=n_sparse)
        qvec = self.embedder.encode([query])[0]
        dense = self.index.query(qvec, k=n_dense)

        sparse_ids = [i for i, _ in sparse]
        dense_ids = [i for i, _ in dense]
        fused = rrf([sparse_ids, dense_ids])

        # Build a lookup of pre-rerank scores for display
        sparse_score = {i: s for i, s in sparse}
        dense_score = {i: s for i, s in dense}

        top_for_rerank = fused[:max(20, n_final)]
        pairs = [(query, self.docs[i]) for i in top_for_rerank]
        rerank_scores = self.reranker.predict(pairs)

        ordered = sorted(zip(top_for_rerank, rerank_scores),
                         key=lambda x: x[1], reverse=True)[:n_final]
        return [
            {
                "doc_id": self.ids[i],
                "score": float(s),
                "sparse_pre": sparse_score.get(i),
                "dense_pre": dense_score.get(i),
                "text": self.docs[i][:400],
            }
            for i, s in ordered
        ]
```

### Step 5 — Demo app

```python
# app.py
from retriever.hybrid import HybridRetriever

CORPUS = [
    ("doc1", "HNSW is a graph-based approximate nearest neighbor algorithm."),
    ("doc2", "BM25 is a lexical retrieval function used in search engines."),
    ("doc3", "Reciprocal rank fusion combines multiple ranked result lists."),
    ("doc4", "Cross-encoders rerank query-document pairs more accurately "
             "than bi-encoders but are slower."),
    ("doc5", "Vector databases like Pinecone use HNSW under the hood."),
]

def main() -> None:
    r = HybridRetriever()
    r.index_documents([d[0] for d in CORPUS], [d[1] for d in CORPUS])
    for q in ["graph-based vector search", "lexical scoring for retrieval"]:
        print(f"\nQ: {q}")
        for hit in r.retrieve(q, n_final=3):
            print(f"  - {hit['doc_id']} (score={hit['score']:.3f}) {hit['text']}")

if __name__ == "__main__":
    main()
```

If `doc5` outranks `doc1` on the first query and `doc2` outranks `doc3` on the second, your pipeline is working.

## Running and Testing It

A portfolio project needs a real test suite, not a notebook. Two kinds of tests matter:

1. **Unit tests on the BM25 and HNSW logic** — verify BM25 returns the right score on a hand-computed example, and HNSW returns a near-optimal neighbor on a small synthetic set.
2. **End-to-end relevance tests** — for a fixed corpus, assert that the retriever ranks known relevant documents in the top-K for a set of queries.

```python
# tests/test_bm25.py
from retriever.bm25 import BM25, tokenize

def test_tokenize_lowercases_and_alphanumerics():
    assert tokenize("HNSW, Rocks!") == ["hnsw", "rocks"]

def test_bm25_ranks_exact_match_first():
    docs = ["the quick brown fox", "lazy dog sleeping", "fox and dog"]
    bm = BM25()
    bm.fit(docs)
    top = bm.score("quick brown fox", top_n=3)
    assert top[0][0] == 0  # doc 0 wins
```

```python
# tests/test_hnsw.py
import numpy as np
from retriever.hnsw import HNSW

def test_hnsw_finds_nearest_in_tiny_corpus():
    rng = np.random.default_rng(0)
    vecs = rng.random((100, 8), dtype=np.float32)
    idx = HNSW(dim=8, M=8, ef_construction=50, ef_search=50)
    idx.fit(v for v in vecs)
    q = vecs[7] + 0.001 * rng.random(8).astype(np.float32)
    hits = idx.query(q, k=1)
    assert hits[0][0] == 7
```

```bash
# Run everything
pytest -q
python app.py
```

For relevance tests at the corpus level, drop in a small labeled set (5–20 query/relevant-doc pairs is plenty for a demo) and assert `@k >= 0.8` for a sensible k. Mention `pytest-benchmark` in your README for measuring HNSW query latency on your laptop — that single number (`p95 < 5ms for 10k vectors on CPU`) is the kind of evidence that makes a CV bullet point credible instead of hand-wavy.

## Extending It: Your Roadmap to Senior-Level

This is where the project graduates from "toy" to "production-flavored." Each item below has a clear senior-engineer signal attached. Treat this as the upgrade ladder for your README.

- **Persistence with a real storage layer.** Snapshot the BM25 index to a `sqlite` table and dump the HNSW vectors plus graph adjacency lists to a single `.npz`/`.parquet` file, then load lazily on startup. *Why it matters:* production search services survive restarts and can roll back.
- **Horizontal scaling via sharding.** Split the corpus into N shards (by hash of `doc_id`) and run a separate BM25 + HNSW index per shard, with a coordinator that fans out queries and merges results. *Why it matters:* this is how Vespa and Elasticsearch actually shard inverted indexes and ANN graphs in real deployments.
- **Observability with structured logs and metrics.** Emit per-stage timings (BM25 ms, HNSW ms, reranker ms, candidates in/out) as Prometheus counters and histograms, and write each query and top-K to a structured log. *Why it matters:* you cannot tune what you cannot measure, and interviewers will ask how you debug retrieval quality regressions.
- **Fault tolerance with retry and graceful degradation.** Wrap the reranker call in a retry with exponential backoff and circuit breaker; if it fails, return the fused pre-rerank top-K instead. *Why it matters:* expensive models fail in production; a senior engineer designs for that, not around it.
- **Benchmarking against a real dataset.** Run your retriever on BEIR (e.g., `scifact`, `fiqa`, `nfcorpus`) using the [`beir` library](https://github.com/beir-cellar/beir) and report nDCG@10 against BM25-only and dense-only baselines. *Why it matters:* numbers on a public benchmark are far more convincing than "it works on my laptop."
- **Quantization and approximate vector search trade-offs.** Replace your float32 vectors with `int8` quantized versions (scalar or product quantization) and measure recall loss vs. memory savings. *Why it matters:* this is the main lever FAISS, pgvector, and Qdrant use to scale to millions of vectors per machine.

Pick two of these for your initial push, write them well, and your project stops looking like a tutorial and starts looking like a system.

## Key Takeaways

- A hybrid BM25 + dense + rerank pipeline is the de facto production retrieval architecture in 2026, and writing one yourself shows you understand the trade-offs rather than the API.
- Implementing HNSW from scratch is a strong CV signal because it forces you to understand graph-based ANN: random level assignment, neighbor pruning, and the role of `M` and `ef_construction`.
- BM25 looks simple but has subtle correctness traps (IDF smoothing, per-doc length normalization) — getting them right is its own signal.
- Reciprocal rank fusion is the easiest first-stage merger; the cross-encoder reranker is where most of the quality lift comes from in practice.
- A portfolio project stands out when it ships with tests, a benchmark, observability, and a clear roadmap — not when it has the most code.

## Further Reading

- [Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs (Malkov & Yashunin, 2018)](https://arxiv.org/abs/1603.09320) — the original HNSW paper; read this before tuning `M` or `ef`.
- [Okapi BM25 — Wikipedia overview with the original formulas](https://en.wikipedia.org/wiki/Okapi_BM25) — fast refresher on BM25 and its IDF derivation.
- [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks (Reimers & Gurevych, 2019)](https://arxiv.org/abs/1908.10084) — the paper behind the `sentence-transformers` library you are using.
- [BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models](https://github.com/beir-cellar/beir) — the dataset suite for evaluating your hybrid retriever against published baselines.
- [FAISS HNSW guidelines for choosing index parameters](https://github.com/facebookresearch/faiss/wiki/Guidelines-to-choose-index-parameters-for-large-scale-similarity-search) — practical tuning advice from the team that maintains the reference HNSW implementation.
- [Reciprocal Rank Fusion (Cormack et al., 2009)](https://plg.uwaterloo.ca/~gvcormac/cormack_clark_buettcher_2009.pdf) — the paper behind RRF, the simplest thing that works for combining ranked lists.
- [Cross-Encoders and Bi-Encoders for Re-ranking (Sentence-Transformers docs)](https://www.sbert.net/examples/applications/cross-encoder/README.html) — canonical reference for the reranker step in your pipeline.