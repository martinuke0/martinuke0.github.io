---
title: "Build a Hybrid Sparse-Dense Retriever from Scratch: A CV Project That Actually Signals Systems Skill"
date: "2026-09-07T17:07:16.719"
draft: false
tags: ["retrieval-augmented-generation", "hybrid-search", "bm25", "vector-search", "python"]
description: "A hands-on guide to building a from-scratch hybrid sparse-dense retriever with learned BM25 and embedding fusion, including a streaming generation loop."
summary: "Step-by-step build of a real hybrid retrieval system that combines learned BM25 with dense embeddings, fuses scores, and streams answers — the kind of project that makes hiring managers stop scrolling."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-hybrid-sparse-dense-retriever-from-scratch-a-cv-project-that-actually-signals-systems-skill.svg"
  alt: "Diagram showing sparse and dense retrieval paths merging into a fused ranked list feeding a streaming generation loop."
  caption: ""
  relative: false
---

> **TL;DR** — You'll build a hybrid retriever in under 400 lines of Python that ingests a corpus, indexes it with both learned BM25 and dense embeddings, fuses the two score streams with reciprocal rank fusion, and serves a streaming RAG generation loop. It's the right size to finish in a weekend but exercises enough real systems primitives (indexing, vector search, score fusion, async streaming, observability) to read as production-grade thinking on a CV.

## Why This Project Stands Out on a CV

Most "RAG projects" on portfolios are 200-line wrappers around an OpenAI client plus a vector database call. Hiring managers see them, mentally check a box, and move on. The project below is different in three specific ways:

1. **It implements two retrieval algorithms, not one.** A naive RAG demo uses a single dense retriever. This project runs BM25 *and* embeddings in parallel and fuses them. That choice immediately signals that you understand the tradeoffs — dense retrieval is great for semantic similarity, but it misses exact-term matches (model names, error codes, API paths), and BM25 handles those cleanly. Knowing this is a differentiator between someone who's read one tutorial and someone who's actually shipped search.

2. **It learns the BM25 weights.** Instead of treating BM25 as a black box, you'll fit `k1` and `b` on a labeled set. This signals familiarity with the difference between heuristic search and learned retrieval — the same family of ideas as [LambdaMART](https://en.wikipedia.org/wiki/LambdaMART) and the rankers used inside Elasticsearch.

3. **It streams the answer back.** A streaming generation loop with backpressure, cancellation, and per-token timing is the part of RAG that breaks the most in production. Building one from scratch — even a toy version — shows you've thought about latency, partial failures, and what users actually feel.

The roles this signals for: search engineer, applied ML engineer, ML platform engineer, backend engineer with an ML focus, and junior-to-mid AI engineer. If you're aiming for senior, see the [Extending It](#extending-it-your-roadmap-to-senior-level) section — it's explicitly structured to map onto the expectations at that level.

## Architecture Overview

The system has six components. Keep them mentally separate; the codebase reflects the same boundaries.

- **Corpus loader** — reads documents from disk (plain text or JSONL), normalizes whitespace, and emits a stream of `Document(id, text, metadata)` records.
- **Sparse index (learned BM25)** — tokenizes text, builds an inverted index in memory, and exposes a `query(text, k)` method. The `k1` and `b` parameters are learned from a small labeled set.
- **Dense index (embeddings)** — encodes text with a sentence-transformer model, stores vectors in NumPy or a tiny FAISS/PyNNDescent index, and exposes the same `query(text, k)` interface.
- **Score fusion** — takes the two ranked lists, applies reciprocal rank fusion (RRF) with a configurable `k` constant, and emits a unified top-`k`.
- **Streaming generator** — feeds the fused context to a local LLM (or a remote one with an OpenAI-compatible client) and yields tokens to the caller as an async iterator.
- **Telemetry layer** — wraps every stage with timings, hit counts, and a structured log line per query. Optional OpenTelemetry spans later.

Data flow:

```text
                  ┌──────────────────────┐
   query text ───▶│   SparseIndex (BM25) │──┐
                  └──────────────────────┘  │
                                             ▼
                                       ┌──────────┐
                                       │ RRF fuse │──▶ top-k context
                  ┌──────────────────────┐  ▲
   query text ───▶│  DenseIndex (HNSW)  │──┘
                  └──────────────────────┘
                                             │
                                             ▼
                                   ┌────────────────────┐
                                   │ StreamingGenerator │──▶ token stream
                                   └────────────────────┘
```

The interfaces are deliberately tiny — both indexes expose the same `query(text, k) -> list[ScoredDoc]` — so you can swap implementations later without touching the fusion or generation code.

## Building It Step by Step

You'll write this in a single `retriever.py` (plus a small `train_bm25.py`) so a reviewer can read the whole thing in one sitting. Target Python 3.11+.

### Step 1: Document model and corpus loader

```python
# retriever.py
from dataclasses import dataclass, field
from typing import Iterator
import json
import re

@dataclass
class Document:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)

def iter_documents(path: str) -> Iterator[Document]:
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            yield Document(
                id=obj["id"],
                text=_normalize(obj["text"]),
                metadata=obj.get("metadata", {}),
            )

_WS = re.compile(r"\s+")
def _normalize(s: str) -> str:
    return _WS.sub(" ", s).strip()
```

The corpus is JSONL so each line is independently parseable — a property you'll thank yourself for when you later stream from S3 or Kafka.

### Step 2: Learned BM25 with an in-memory inverted index

This is the part reviewers will actually read carefully, so keep it tight and commented.

```python
# retriever.py (continued)
import math
from collections import defaultdict, Counter
from typing import Iterable

_TOKEN = re.compile(r"[A-Za-z0-9_]+")

def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text)]

@dataclass
class SparseIndex:
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self):
        self.postings: dict[str, list[tuple[str, int]]] = defaultdict(list)
        self.doc_lens: dict[str, int] = {}
        self.avgdl: float = 0.0
        self.n_docs: int = 0
        self.doc_freq: Counter = Counter()

    def index(self, docs: Iterable[Document]) -> None:
        lens = []
        for d in docs:
            counts = Counter(tokenize(d.text))
            self.doc_lens[d.id] = sum(counts.values())
            lens.append(self.doc_lens[d.id])
            for term, tf in counts.items():
                self.postings[term].append((d.id, tf))
                self.doc_freq[term] += 1
            self.n_docs += 1
        self.avgdl = sum(lens) / max(1, len(lens))

    def query(self, text: str, k: int = 10) -> list[tuple[str, float]]:
        scores: dict[str, float] = defaultdict(float)
        for term in tokenize(text):
            df = self.doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for doc_id, tf in self.postings.get(term, []):
                dl = self.doc_lens[doc_id]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                scores[doc_id] += idf * (tf * (self.k1 + 1)) / denom
        return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
```

The interesting design decisions: in-memory posting lists keyed by term, doc lengths cached for the length-normalization term, and IDF computed in the standard Robertson–Sparck Jones form.

### Step 3: Learning `k1` and `b` from labeled queries

```python
# train_bm25.py
import math, random
from retriever import SparseIndex, Document

def ndcg(rel, pred, k):
    gains = {doc_id: r for doc_id, r in rel.items()}
    dcg = sum((2 ** gains[d] - 1) / math.log2(i + 2) for i, d in enumerate(pred[:k]) if d in gains)
    ideal = sorted(gains.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 2) for i, g in enumerate(ideal))
    return dcg / idcg if idcg > 0 else 0.0

def fit_bm25(docs, queries, k=10, iters=40):
    best = (-1.0, 1.5, 0.75)
    for _ in range(iters):
        k1 = random.uniform(0.9, 2.4)
        b = random.uniform(0.3, 0.9)
        idx = SparseIndex(k1=k1, b=b); idx.index(docs)
        score = sum(ndcg(q[1], [d for d, _ in idx.query(q[0], k)], k) for q in queries) / len(queries)
        if score > best[0]:
            best = (score, k1, b)
    return best
```

Random search over BM25 hyperparameters is what Elasticsearch's [BM25 parameter tuning literature](https://www.elastic.co/blog/practical-bm25-part-2-how-shards-affects-elasticsearch-scoring) effectively recommends at small scale; the trick that makes this beat naive defaults is holding `b` and `k1` jointly rather than sweeping one at a time.

### Step 4: Dense index with sentence-transformers

```python
# retriever.py (continued)
import numpy as np

class DenseIndex:
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)
        self.docs: list[Document] = []
        self.emb: np.ndarray | None = None

    def index(self, docs: list[Document]) -> None:
        self.docs = list(docs)
        self.emb = self.model.encode([d.text for d in self.docs],
                                     normalize_embeddings=True,
                                     show_progress_bar=False)

    def query(self, text: str, k: int = 10) -> list[tuple[str, float]]:
        q = self.model.encode([text], normalize_embeddings=True)
        scores = (self.emb @ q.T).ravel()
        top = np.argpartition(-scores, k)[:k]
        return [(self.docs[i].id, float(scores[i])) for i in top[np.argsort(-scores[top])]]
```

The `normalize_embeddings=True` flag turns cosine similarity into a single matrix multiply — a property you'll want to preserve when you swap in FAISS.

### Step 5: Reciprocal rank fusion

```python
# retriever.py (continued)
def rrf_fuse(sparse: list[tuple[str, float]],
             dense: list[tuple[str, float]],
             k: int = 10, rrf_k: int = 60) -> list[tuple[str, float]]:
    scores: dict[str, float] = defaultdict(float)
    for rank, (doc_id, _) in enumerate(sparse):
        scores[doc_id] += 1.0 / (rrf_k + rank + 1)
    for rank, (doc_id, _) in enumerate(dense):
        scores[doc_id] += 1.0 / (rrf_k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)[:k]
```

RRF is the right default because it's parameter-light, evidence-free (no score calibration needed), and well-documented in [Cormack et al.'s original paper](https://dl.acm.org/doi/10.1145/1571941.1571946). When you later need a learned fusion, replace this function — its callers won't notice.

### Step 6: Streaming generation loop

```python
# retriever.py (continued)
import asyncio, time
from typing import AsyncIterator

class StreamingGenerator:
    def __init__(self, client):
        self.client = client  # any object with `stream(messages) -> AsyncIterator[str]`

    async def stream(self, query: str, context_docs: list[Document],
                     sparse_ms: float, dense_ms: float) -> AsyncIterator[dict]:
        prompt = self._build_prompt(query, context_docs)
        first = True
        tokens = 0
        start = time.perf_counter()
        async for token in self.client.stream([{"role": "user", "content": prompt}]):
            if first:
                yield {"event": "ttft", "ms": (time.perf_counter() - start) * 1000,
                       "sparse_ms": sparse_ms, "dense_ms": dense_ms}
                first = False
            tokens += 1
            yield {"event": "token", "data": token}
        yield {"event": "done", "tokens": tokens, "total_ms": (time.perf_counter() - start) * 1000}

    def _build_prompt(self, query: str, docs: list[Document]) -> str:
        ctx = "\n\n".join(f"[{i+1}] {d.text}" for i, d in enumerate(docs))
        return f"Answer using only the context below.\n\nContext:\n{ctx}\n\nQuestion: {query}\nAnswer:"
```

This is where most portfolio projects stop emitting intermediate events. Yielding structured dicts instead of bare strings lets a frontend render TTFT and retrieval timing separately — that's the kind of decision that reads as production thinking.

### Step 7: The orchestrator that ties it all together

```python
# retriever.py (continued)
class HybridRetriever:
    def __init__(self, sparse: SparseIndex, dense: DenseIndex, generator: StreamingGenerator):
        self.sparse = sparse
        self.dense = dense
        self.generator = generator

    async def ask(self, query: str, k: int = 5) -> AsyncIterator[dict]:
        t0 = time.perf_counter()
        sparse_hits = self.sparse.query(query, k=k * 4)
        sparse_ms = (time.perf_counter() - t0) * 1000

        t1 = time.perf_counter()
        dense_hits = self.dense.query(query, k=k * 4)
        dense_ms = (time.perf_counter() - t1) * 1000

        fused = rrf_fuse(sparse_hits, dense_hits, k=k)
        id_to_doc = {d.id: d for d in self.dense.docs}
        context = [id_to_doc[doc_id] for doc_id, _ in fused if doc_id in id_to_doc]

        async for ev in self.generator.stream(query, context, sparse_ms, dense_ms):
            yield ev
```

That's the whole pipeline — roughly 350 lines including comments. The exact number doesn't matter; what matters is that every section is short enough to be reviewed in isolation.

## Running and Testing It

### 1. Create a toy corpus

```bash
mkdir -p data && cat > data/corpus.jsonl <<'EOF'
{"id":"d1","text":"FastAPI is a modern Python web framework built on Starlette."}
{"id":"d2","text":"BM25 is a ranking function used by search engines."}
{"id":"d3","text":"FAISS provides efficient similarity search over dense vectors."}
{"id":"d4","text":"Reciprocal rank fusion combines ranked lists without score calibration."}
{"id":"d5","text":"Streaming responses reduce time-to-first-token in LLM APIs."}
EOF
```

### 2. Smoke-test the indexes

```python
# smoke_test.py
import asyncio
from retriever import SparseIndex, DenseIndex, StreamingGenerator, HybridRetriever, iter_documents

class FakeClient:
    async def stream(self, messages):
        for word in ("Based ", "on ", "the ", "context, ", "yes."):
            yield word

async def main():
    docs = list(iter_documents("data/corpus.jsonl"))
    sparse = SparseIndex(); sparse.index(docs)
    dense = DenseIndex(); dense.index(docs)
    gen = StreamingGenerator(FakeClient())
    hr = HybridRetriever(sparse, dense, gen)

    async for ev in hr.ask("What is BM25?"):
        print(ev)

asyncio.run(main())
```

You should see an `event: ttft` line, then five `event: token` lines, then an `event: done` line with `tokens=5`.

### 3. Quantitative evaluation

Write 10–20 labeled queries into `data/eval.jsonl` with the form `{"query": "...", "relevant": ["d2", "d4"]}`, then compute Recall@k and MRR for sparse, dense, and fused retrieval:

```python
# eval.py
def recall_at_k(pred, rel, k):
    return len(set(d for d, _ in pred[:k]) & set(rel)) / max(1, len(rel))

# run for each index; expect RRF > sparse > dense on keyword-heavy queries,
# dense > sparse on paraphrase queries, and RRF to win on average.
```

If you want a more credible signal, also run [BEIR-style evaluation](https://github.com/beir-cellar/beir) on a public dataset like FiQA or SciFact. That single line on your CV — *"evaluated on BEIR"* — moves the project from "tutorial" to "engineer who benchmarks."

### 4. A minimal CLI

```bash
# cli.py
import asyncio, json, sys
from retriever import SparseIndex, DenseIndex, StreamingGenerator, HybridRetriever, iter_documents

async def main():
    docs = list(iter_documents(sys.argv[1]))
    sparse = SparseIndex(); sparse.index(docs)
    dense = DenseIndex(); dense.index(docs)
    # point StreamingGenerator at your real client here
    gen = StreamingGenerator(YourOpenAIClient())
    hr = HybridRetriever(sparse, dense, gen)
    async for ev in hr.ask(" ".join(sys.argv[2:])):
        print(json.dumps(ev))

asyncio.run(main())
```

Run it with `python cli.py data/corpus.jsonl "What is BM25?"`. Wrap it in a `make serve` target and you've got something that feels like a real product.

## Extending It: Your Roadmap to Senior-Level

Each item below is a one-weekend upgrade that maps to a concrete skill senior candidates are expected to have.

- **Persist both indexes to disk and reload on startup.** Use `pickle` for the BM25 posting lists and `faiss.write_index` for the dense vectors. *Why it matters:* demonstrates that you think about cold-start time and the difference between build-time and serve-time cost.
- **Swap the NumPy dense index for FAISS with an IVF or HNSW structure.** *Why it matters:* this is what every production vector search system does; knowing when to choose HNSW over IVF-PQ is a senior-level decision driven by recall vs. memory tradeoffs.
- **Add a real learned fusion layer.** Train a small cross-encoder or a lightweight LambdaMART model on the labeled queries you already have, replacing RRF. *Why it matters:* shows the progression from heuristic fusion (RRF) to learned reranking — exactly the journey from Elasticsearch to Vespa or from naive RAG to production RAG.
- **Add structured observability.** Emit OpenTelemetry spans for `sparse.search`, `dense.search`, `fuse`, and `generate`, plus a `gen_ai.*` attribute set that follows the [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/). *Why it matters:* hiring managers for platform roles explicitly screen for telemetry fluency.
- **Wrap the streaming loop in a fault-tolerant HTTP server with cancellation.** Use FastAPI's `StreamingResponse` and propagate `request.is_disconnected()` to abort generation on client drop. *Why it matters:* wasted LLM tokens from a disconnected client is one of the most common production cost bugs.
- **Benchmark end-to-end with `locust` or `k6` and a small Redis cache for embeddings.** Track TTFT, tokens/sec, and cache hit rate. *Why it matters:* a CV line that says *"sustained 80 rps with p95 TTFT under 600ms on a single A10G"* is dramatically more persuasive than a screenshot of `curl localhost:8000`.

Do three of these, ship it on GitHub with a `README.md` that includes the BEIR numbers, and your portfolio section stops being decoration.

## Key Takeaways

- A hybrid retriever that learns BM25 weights and fuses them with dense embeddings is the right size for a weekend project but exercises production-shaped thinking.
- The codebase should have sharp interfaces (`SparseIndex.query`, `DenseIndex.query`, `StreamingGenerator.stream`) so future swaps don't ripple.
- RRF is the correct default fusion method; a learned cross-encoder reranker is the obvious next step.
- Streaming responses are the part of RAG that breaks most in production — yield TTFT, retrieval timings, and per-token events as structured payloads.
- Persist, benchmark, observe, and add fault tolerance. Each of these is one weekend away and reads as senior-level work.

## Further Reading

- [Original BM25 paper — Robertson et al., "Okapi at TREC-3"](https://trec.nist.gov/pubs/trec3/papers/city.ps.gz) — the canonical reference for the ranking function you implemented.
- [Reciprocal Rank Fusion — Cormack et al., 2009](https://dl.acm.org/doi/10.1145/1571941.1571946) — the paper behind the `1 / (k + rank)` formula.
- [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084) — the model family your dense index uses by default.
- [FAISS: A library for efficient similarity search and clustering of dense vectors](https://arxiv.org/abs/1702.08734) — the standard upgrade path from NumPy inner products.
- [BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models](https://arxiv.org/abs/2104.08663) — the dataset family to evaluate your retriever on.
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) — the spec to follow when you add spans for retrieval and generation.
- [Designing Data-Intensive Applications — Kleppmann](https://dataintensive.net/) — the book to read when you start thinking about persistence, replication, and scaling.