---
title: "Building a Mini Search Engine with an Inverted Index and TF-IDF: A Hands-On CV Project"
date: "2026-09-02T17:00:44.436"
draft: false
tags: ["python", "search-engine", "tf-idf", "inverted-index", "portfolio-project", "information-retrieval"]
description: "Build a real, runnable mini search engine in Python with an inverted index and TF-IDF ranking — a side project that demonstrates systems skill on your CV."
summary: "A hands-on build guide for a portfolio-grade search engine: tokenize documents, build an inverted index, rank with TF-IDF, and ship something that actually works. Includes runnable code, tests, and a roadmap of upgrades that turn the toy into production-flavored work."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-building-a-mini-search-engine-with-an-inverted-index-and-tf-idf-a-hands-on-cv-project.svg"
  alt: "A terminal window showing search results from a custom-built mini search engine."
  caption: ""
  relative: false
---

> **TL;DR** — A working search engine is one of the best CV projects you can build in a weekend: it touches data structures, text processing, ranking algorithms, and a query API. In this guide we build one in plain Python with a real inverted index, BM25-style TF-IDF ranking, and a tiny HTTP server, then map out the upgrades that turn the toy into a credible systems project.

## Why This Project Stands Out on a CV

Most CV side projects live in the same boring neighborhood: a to-do app, a weather widget, a Twitter clone. They demonstrate that you can glue a frontend to a backend. They do not demonstrate that you understand how software *thinks*.

A mini search engine is different. Search is one of the few problems where every layer of the stack matters: data structures, algorithms, file I/O, concurrency, ranking heuristics, and user-facing latency. Hiring managers know this. When they see a search project on a CV, they read it as a signal that the candidate can think about systems, not just features.

Specifically, this project demonstrates:

- **Data structure fluency**: the inverted index is the same structure that powers Elasticsearch, Solr, and Lucene. Building one from scratch shows you understand the tradeoffs behind those tools, not just the API.
- **Information retrieval fundamentals**: TF-IDF is the foundation that BM25, learning-to-rank, and modern vector search all build on. Showing you can implement it without a library signals that you understand the math, not just the import.
- **Systems thinking**: the upgrade path from "toy" to "production-flavored" mirrors what a real search team at Spotify, Notion, or Elastic has to think about — sharding, replication, observability, query latency budgets. Talking credibly about that path in an interview is a strong signal for senior and staff roles.
- **Software hygiene**: it gives you a natural place to demonstrate tests, benchmarks, a CLI, a small HTTP API, and clean modular code.

The roles this signals for include: Backend Engineer, Search/Relevance Engineer, Data Platform Engineer, ML Engineer (especially retrieval/RAG), and Site Reliability Engineer. It's a stronger differentiator than yet another CRUD app.

## Architecture Overview

The system is intentionally small but mirrors the shape of a real search pipeline. There are four logical stages, each of which can be swapped or scaled independently.

- **Document store** — A flat directory of plain-text documents (or a JSON/Parquet file). The simplest version reads files from `./corpus/`. A production version would back this with Postgres, S3, or a blob store.
- **Tokenizer / analyzer** — A pure function `tokenize(text) -> list[str]` that lowercases, strips punctuation, removes stopwords, and (optionally) applies stemming. This is the only place language-specific logic lives.
- **Inverted index** — A mapping from term → posting list. Each posting contains the document ID, the term frequency, and document length (needed for ranking). Stored in memory as a dict of dicts; on disk as a JSON or msgpack file.
- **Query engine + ranker** — Takes a query string, tokenizes it, looks up each term's posting list, accumulates a TF-IDF score per document, and returns the top-K results.
- **Optional HTTP front door** — A tiny [FastAPI](https://fastapi.tiangolo.com/) or [Flask](https://flask.palletsprojects.com/) server exposing `GET /search?q=...` so the system is usable, not just a script.

Data flow at build time: `corpus → tokenize → build inverted index → serialize to disk`. At query time: `query → tokenize → lookup postings → score with TF-IDF → return top-K`. This build-vs-query split is exactly the pattern Lucene, Elasticsearch, and Vespa use, and it's worth being able to articulate in an interview.

## Building It Step by Step

We'll build this in a single `minisearch` package with five small modules. Total: about 200 lines of real code. Use Python 3.10+; the only third-party dependency is optional (`fastapi` for the HTTP layer).

### Step 1: Project layout

```
minisearch/
  __init__.py
  tokenizer.py
  index.py
  scorer.py
  engine.py
  server.py        # optional
  cli.py
tests/
  test_engine.py
corpus/            # your .txt files live here
data/              # serialized index lives here
```

### Step 2: The tokenizer

The tokenizer is the only place language-specific decisions live, which makes it easy to swap for different domains later.

```python
# minisearch/tokenizer.py
import re
from typing import Iterable

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "he", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "to", "was", "were", "will", "with",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumerics, drop stopwords and short tokens."""
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in STOPWORDS and len(t) > 1]
```

This is deliberately simple. The Porter stemmer is a one-line swap if you want to handle inflection ("running" vs "run"); the [Natural Language Toolkit](https://www.nltk.org/) has a battle-tested one.

### Step 3: The inverted index

This is the heart of the system. Each term maps to a list of postings; each posting carries everything we need to score without re-reading the source document.

```python
# minisearch/index.py
from collections import defaultdict
from dataclasses import dataclass, field, asdict
import json
from pathlib import Path

from .tokenizer import tokenize


@dataclass
class Posting:
    doc_id: str
    tf: int               # term frequency in this document


@dataclass
class InvertedIndex:
    postings: dict[str, list[Posting]] = field(
        default_factory=lambda: defaultdict(list)
    )
    doc_lengths: dict[str, int] = field(default_factory=dict)
    doc_count: int = 0

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = tokenize(text)
        self.doc_lengths[doc_id] = len(tokens)
        counts: dict[str, int] = defaultdict(int)
        for tok in tokens:
            counts[tok] += 1
        for term, tf in counts.items():
            self.postings[term].append(Posting(doc_id=doc_id, tf=tf))
        self.doc_count += 1

    def save(self, path: Path) -> None:
        payload = {
            "postings": {
                term: [asdict(p) for p in plist]
                for term, plist in self.postings.items()
            },
            "doc_lengths": self.doc_lengths,
            "doc_count": self.doc_count,
        }
        path.write_text(json.dumps(payload))

    @classmethod
    def load(cls, path: Path) -> "InvertedIndex":
        payload = json.loads(path.read_text())
        idx = cls()
        idx.doc_count = payload["doc_count"]
        idx.doc_lengths = payload["doc_lengths"]
        for term, plist in payload["postings"].items():
            idx.postings[term] = [Posting(**p) for p in plist]
        return idx
```

A few things worth noticing. We store term frequency per posting, not per document, so we don't have to re-tokenize at query time. We store document length, which is the key input to length-normalized ranking. And we use `defaultdict` so the index is sparse and append-friendly. The real Lucene goes much further — compressed postings, skip lists, block-max scoring — but the shape is the same.

### Step 4: The TF-IDF scorer

TF-IDF has two parts. Term frequency rewards words that appear often in a document; inverse document frequency penalizes words that appear in almost every document. The canonical formulation lives in the [Stanford IR textbook](https://nlp.stanford.edu/IR-book/) and is summarized well in [the scikit-learn TF-IDF docs](https://scikit-learn.org/stable/modules/feature_extraction_text.html#tfidf-term-weighting).

We use the "sublinear TF" variant, which dampens the effect of repeated terms, and a smoothed IDF.

```python
# minisearch/scorer.py
import math
from collections import Counter

from .index import InvertedIndex


def score_query(
    query_tokens: list[str],
    index: InvertedIndex,
) -> dict[str, float]:
    """Return a {doc_id: score} map for a single query."""
    if not query_tokens:
        return {}

    # Smoothed IDF: log((1 + N) / (1 + df)) + 1
    N = index.doc_count
    idf: dict[str, float] = {}
    for term in set(query_tokens):
        df = len(index.postings.get(term, []))
        idf[term] = math.log((1 + N) / (1 + df)) + 1.0

    scores: dict[str, float] = Counter()
    query_tf = Counter(query_tokens)

    for term, qtf in query_tf.items():
        postings = index.postings.get(term)
        if not postings:
            continue
        for posting in postings:
            # Sublinear TF: 1 + log(tf) if tf > 0 else 0
            tf_norm = 1.0 + math.log(posting.tf) if posting.tf > 0 else 0.0
            # Length normalization: divide by sqrt(doc_length)
            length_norm = math.sqrt(index.doc_lengths[posting.doc_id])
            scores[posting.doc_id] += (
                idf[term] * (tf_norm / length_norm)
            ) * qtf

    return dict(scores)
```

The two non-obvious moves are sublinear TF (without it, a document that says "python" 50 times isn't 50× more relevant than one that says it once) and length normalization (without it, long documents win by brute verbosity). These are exactly the adjustments BM25 formalizes.

### Step 5: The engine

The engine is the orchestrator. It owns the index, exposes a `search()` method, and knows how to build itself from a directory.

```python
# minisearch/engine.py
from pathlib import Path
import heapq

from .index import InvertedIndex
from .scorer import score_query
from .tokenizer import tokenize


class SearchEngine:
    def __init__(self, index: InvertedIndex):
        self.index = index

    @classmethod
    def from_corpus(cls, corpus_dir: Path) -> "SearchEngine":
        idx = InvertedIndex()
        for path in sorted(corpus_dir.glob("*.txt")):
            idx.add_document(doc_id=path.stem, text=path.read_text(encoding="utf-8"))
        return cls(idx)

    def search(self, query: str, k: int = 5) -> list[tuple[str, float]]:
        tokens = tokenize(query)
        scores = score_query(tokens, self.index)
        return heapq.nlargest(k, scores.items(), key=lambda kv: kv[1])
```

Note `heapq.nlargest` instead of a full sort. For `k=5` and a million documents this is the difference between O(N log N) and O(N log k) — a small thing, but it's the kind of detail interviewers notice.

### Step 6: A tiny HTTP front door

A CLI alone is fine; a real HTTP endpoint makes the project look finished. [FastAPI](https://fastapi.tiangolo.com/) gives us this in 15 lines.

```python
# minisearch/server.py
from fastapi import FastAPI
from pydantic import BaseModel

from .engine import SearchEngine

app = FastAPI(title="minisearch")
_engine: SearchEngine | None = None


class SearchHit(BaseModel):
    doc_id: str
    score: float


@app.get("/search", response_model=list[SearchHit])
def search(q: str, k: int = 5) -> list[SearchHit]:
    assert _engine is not None, "engine not loaded"
    return [SearchHit(doc_id=d, score=s) for d, s in _engine.search(q, k=k)]


def configure(engine: SearchEngine) -> None:
    global _engine
    _engine = engine
```

Run it with `uvicorn minisearch.server:app --reload` once you've called `configure(engine)` from a startup hook or a small `__main__` block.

## Running and Testing It

Drop a handful of Wikipedia-style snippets into `corpus/`, one per file. For example, `python.txt`, `rust.txt`, `search.txt`. Then:

```bash
python -m minisearch.cli build ./corpus ./data/index.json
python -m minisearch.cli query "./data/index.json" "fast type safe language" --k 3
```

A minimal `cli.py`:

```python
# minisearch/cli.py
import argparse
import json
from pathlib import Path

from .engine import SearchEngine


def main() -> None:
    p = argparse.ArgumentParser(prog="minisearch")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("corpus", type=Path)
    b.add_argument("out", type=Path)

    q = sub.add_parser("query")
    q.add_argument("index", type=Path)
    q.add_argument("query")
    q.add_argument("--k", type=int, default=5)

    args = p.parse_args()
    if args.cmd == "build":
        engine = SearchEngine.from_corpus(args.corpus)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        engine.index.save(args.out)
        print(f"indexed {engine.index.doc_count} documents")
    elif args.cmd == "query":
        from .index import InvertedIndex
        engine = SearchEngine(InvertedIndex.load(args.index))
        for doc_id, score in engine.search(args.query, k=args.k):
            print(f"{score:7.4f}  {doc_id}")
```

Tests are non-negotiable for a CV project. They prove you can think about edge cases.

```python
# tests/test_engine.py
import math
from pathlib import Path
import tempfile

import pytest

from minisearch.engine import SearchEngine
from minisearch.index import InvertedIndex
from minisearch.scorer import score_query
from minisearch.tokenizer import tokenize


def test_tokenizer_lowercases_and_drops_stopwords():
    assert tokenize("The quick brown Foxes!") == ["quick", "brown", "foxes"]


def test_index_and_score_round_trip(tmp_path: Path):
    idx = InvertedIndex()
    idx.add_document("a", "python is a programming language")
    idx.add_document("b", "rust is a systems programming language")
    idx.add_document("c", "python and rust are both popular")

    scores = score_query(tokenize("python language"), idx)
    assert scores["a"] > 0
    assert scores["b"] > 0
    assert scores["c"] > 0
    # 'language' is in both a and b; length-normalization matters
    assert math.isfinite(scores["a"])


def test_search_engine_topk_ordering(tmp_path: Path):
    with tempfile.TemporaryDirectory() as d:
        corpus = Path(d)
        (corpus / "a.txt").write_text("python python python snake reptile")
        (corpus / "b.txt").write_text("python language programming scripting")
        (corpus / "c.txt").write_text("cooking recipes dinner food")
        engine = SearchEngine.from_corpus(corpus)
        hits = engine.search("python", k=2)
        assert [doc for doc, _ in hits] == ["a", "b"]


def test_engine_persistence(tmp_path: Path):
    idx_path = tmp_path / "idx.json"
    engine = SearchEngine.from_corpus(Path("corpus"))
    engine.index.save(idx_path)
    reloaded = SearchEngine(InvertedIndex.load(idx_path))
    assert reloaded.index.doc_count == engine.index.doc_count
```

Run with `pytest -q`. If the full test suite passes on a fresh clone, hiring managers take the project seriously. If there are no tests, most won't.

## Extending It: Your Roadmap to Senior-Level

This is where the project goes from "weekend hack" to "interview talking point." Each upgrade is a named, well-understood system concern. Pick two or three; don't try to do all of them at once.

- **Add persistence with SQLite or [RocksDB](https://rocksdb.org/) instead of JSON.** Right now the index is reloaded into memory at startup. A real engine keeps posting lists in a columnar store with memory-mapped pages, so the index can be larger than RAM. This signals database and storage-engine literacy.
- **Shard the index across processes with [Ray](https://www.ray.io/) or [Dask](https://www.dask.org/).** Each shard holds a subset of terms; queries fan out, partial scores merge. This is the same shape Elasticsearch uses with its distributed search, and it lets you talk credibly about scatter-gather, partial aggregation, and tail latency.
- **Add a vector retrieval layer with [FAISS](https://github.com/facebookresearch/faiss) or [Qdrant](https://qdrant.tech/).** Pair lexical TF-IDF with dense embeddings and use reciprocal rank fusion to combine rankings. This is the heart of modern hybrid search and RAG retrieval, and it's exactly the pattern [the Vespa docs](https://docs.vespa.ai/) describe.
- **Wire up observability with [OpenTelemetry](https://opentelemetry.io/) and [Prometheus](https://prometheus.io/).** Emit query latency, index size, cache hit rate, and posting-list scan count. Every senior engineer is expected to ship features *and* the metrics that prove the features work.
- **Replace TF-IDF with BM25 and add field boosts.** BM25 is a one-line parameter change but the [original Robertson/Zaragoza paper](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) explains why it dominates naïve TF-IDF. Adding field-level boosts (title vs body) is how Elasticsearch's `multi_match` works under the hood.
- **Benchmark with a real dataset.** Index the [Cranfield collection](https://ir-datasets.com/cranfield.html) or a slice of [MS MARCO](https://microsoft.github.io/MSMARCO/) and report nDCG@10, MRR, and p95 query latency. Numbers turn a demo into evidence.

> A good rule of thumb: if your README shows a benchmark plot, a test suite, and a deployment diagram, you are in the top decile of CV side projects.

## Key Takeaways

- A mini search engine is one of the highest-signal CV projects you can build because it touches data structures, ranking algorithms, and systems concerns that show up in real search teams.
- The core engine has only four moving parts: a tokenizer, an inverted index, a TF-IDF scorer, and a query orchestrator. Roughly 200 lines of Python is enough to build something real.
- TF-IDF is the right starting point because it's simple, well-documented, and is the direct ancestor of BM25 and modern vector retrieval. Once you understand it, you can read the [Lucene scoring docs](https://lucene.apache.org/core/) without flinching.
- The upgrade path — persistence, sharding, hybrid retrieval, observability, BM25, benchmarking — maps directly onto the concerns of real production search systems. Each step is a separate, well-defined commit you can talk about in interviews.
- Tests and a small HTTP API are not optional. They're the difference between a script and a project.

## Further Reading

- [Introduction to Information Retrieval (Stanford IR Book) — Chapters 1–6](https://nlp.stanford.edu/IR-book/) — the canonical text for inverted indexes, TF-IDF, and BM25. Read chapters 1, 2, 4, and 6 at minimum.
- [The Probabilistic Relevance Framework: BM25 and Beyond](https://www.staff.city.ac.uk/~sbrp622/papers/foundations_bm25_review.pdf) — the original Robertson and Zaragoza paper that explains *why* BM25 dominates TF-IDF.
- [Lucene Scoring Formula (Apache Lucene docs)](https://lucene.apache.org/core/) — once you've read the IR book, the Lucene source is the gold standard for what a real implementation looks like.
- [scikit-learn — Text feature extraction (TF-IDF)](https://scikit-learn.org/stable/modules/feature_extraction_text.html#tfidf-term-weighting) — a clean reference implementation of TF-IDF with the exact math spelled out.
- [Vespa Documentation — Hybrid Retrieval](https://docs.vespa.ai/) — the best production-flavored explanation of combining lexical and vector ranking with reciprocal rank fusion.
- [FAISS GitHub repository](https://github.com/facebookresearch/faiss) — the standard library for vector search; pairs naturally with this project as the next step.