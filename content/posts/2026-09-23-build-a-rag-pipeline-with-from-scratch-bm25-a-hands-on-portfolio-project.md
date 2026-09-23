---
title: "Build a RAG Pipeline with From-Scratch BM25: A Hands-On Portfolio Project"
date: "2026-09-23T10:01:27.443"
draft: false
tags: ["RAG", "BM25", "Information Retrieval", "Python", "Portfolio Project", "Systems Engineering"]
description: "Build a production-flavored RAG pipeline from scratch, implementing BM25 ranking yourself. Learn the architecture, write real code, and land interviews with a project that signals deep systems skill."
summary: "A hands-on guide to building a Retrieval-Augmented Generation pipeline with a from-scratch BM25 scorer. Covers architecture, real Python code, testing, and a senior-level roadmap for extending it into a production-grade system."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-23-build-a-rag-pipeline-with-from-scratch-bm25-a-hands-on-portfolio-project.svg"
  alt: "A terminal showing BM25 retrieval scores alongside a RAG pipeline diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Building a RAG pipeline with a from-scratch BM25 ranker is one of the highest-signal side projects an engineer can ship. It forces you to understand information retrieval at the formula level, demonstrate systems architecture thinking, and produce a working demo that hiring managers can interrogate. This guide walks you through every line of code, the architecture decisions behind them, and a concrete roadmap to push it into senior-engineering territory.

---

## Why This Project Stands Out on a CV

Most portfolio projects fall into one of two traps: they're too shallow (a todo app with a JWT auth layer) or they're too abstract (a research paper with no running code). A from-scratch BM25 RAG pipeline avoids both. Here's what it signals to a hiring manager:

- **Algorithmic depth.** You didn't just call `retrieve_documents()` from a library. You implemented the probabilistic ranking function yourself, which means you understand TF, IDF, saturation curves, and parameter tuning at a level that separates engineers who *use* systems from those who *build* them.
- **Full-stack data systems thinking.** A RAG pipeline touches document ingestion, indexing, retrieval, scoring, and generation. That's a complete data lifecycle — the same pattern that powers search engines, recommendation systems, and enterprise knowledge bases.
- **Production-readiness awareness.** When you extend this project (and the guide below shows you how), you demonstrate you know what it takes to move from a notebook prototype to a service with persistence, observability, and fault tolerance.
- **Relevance across roles.** This project is directly relevant for ML Engineer, Search Engineer, Backend Engineer (data-heavy), and Research Engineer positions. It also pairs well with LLM-focused roles because RAG is the dominant pattern for grounding generative models in proprietary data.

The project occupies a sweet spot: complex enough to be impressive, concrete enough to be built in a weekend, and extensible enough to keep evolving over months.

---

## Architecture Overview

Before writing code, it helps to see how the pieces fit together. A minimal RAG pipeline with a from-scratch BM25 scorer consists of five components:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Document    │────▶│  Preprocessing│────▶│  BM25 Index  │
│  Ingestion   │     │  (chunking,  │     │  (in-memory  │
│  (PDF/TXT)   │     │   tokenization)│    │   or disk)   │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                                          Query → │
                                                 ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  LLM         │◀────│  RAG Orchestrator│◀──│  BM25 Retriever│
│  (Generator) │     │  (prompt     │     │  (top-k docs)  │
│              │     │   assembly)  │     └──────────────┘
└──────────────┘     └──────────────┘
```

Here's what each layer does:

1. **Document Ingestion.** Reads raw files (PDF, TXT, Markdown), splits them into chunks, and stores the raw text plus metadata. This layer is where you decide chunk size, overlap, and how to handle tables or code blocks.
2. **Preprocessing.** Tokenizes text, normalizes terms (lowercasing, stemming or lemmatization), and builds the vocabulary. This is where BM25's assumptions about term independence meet messy real-world text.
3. **BM25 Index.** Constructs the inverted index, computes document frequencies, and pre-calculates IDF weights. The index is the performance-critical component — retrieval latency lives here.
4. **BM25 Retriever.** Given a query, tokenizes it, looks up each term in the inverted index, computes the BM25 score for every document, and returns the top-k results. This is the from-scratch heart of the project.
5. **RAG Orchestrator.** Combines the retrieved documents with the user's query into a prompt, sends it to an LLM (e.g., OpenAI's API, or a local model via Ollama), and returns the generated answer.

The beauty of this architecture is that each component is independently replaceable. Swap BM25 for a dense vector retriever later without touching the orchestrator. That modularity is exactly what production systems demand.

---

## Building It Step by Step

We'll implement this in Python. The core dependencies are `numpy` for numerical work, `rank_bm25` for a reference implementation we'll compare against (and ultimately replace), and `PyPDF2` for PDF parsing. The full BM25 scorer will be written from scratch.

### Step 1: Document Ingestion and Chunking

```python
import re
from dataclasses import dataclass
from pathlib import Path

@dataclass
class DocumentChunk:
    text: str
    source: str
    chunk_index: int

def load_documents(directory: str) -> list[DocumentChunk]:
    """Load all .txt and .pdf files from a directory and chunk them."""
    chunks = []
    path = Path(directory)
    for file_path in path.iterdir():
        if file_path.suffix == ".txt":
            text = file_path.read_text(encoding="utf-8")
        elif file_path.suffix == ".pdf":
            text = _extract_pdf_text(file_path)
        else:
            continue

        chunks.extend(_chunk_text(text, file_path.name))
    return chunks

def _extract_pdf_text(file_path: Path) -> str:
    """Extract text from a PDF using PyPDF2."""
    from PyPDF2 import PdfReader
    reader = PdfReader(str(file_path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)

def _chunk_text(text: str, source: str, chunk_size: int = 512, overlap: int = 50) -> list[DocumentChunk]:
    """Split text into overlapping chunks of approximately chunk_size characters."""
    chunks = []
    start = 0
    idx = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(DocumentChunk(text=chunk, source=source, chunk_index=idx))
        start += chunk_size - overlap
        idx += 1
    return chunks
```

The chunking strategy here is character-based with a fixed overlap. This is a deliberate simplification — production systems often use sentence-aware or semantic chunking — but it's sufficient for demonstrating the pipeline and keeps the focus on BM25.

### Step 2: Tokenization and Vocabulary Building

```python
import re
from collections import Counter
from typing import List

def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric characters, and filter empty tokens."""
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if len(t) > 1]

class Vocabulary:
    """Builds a term-to-index mapping and tracks document frequencies."""

    def __init__(self):
        self.term_to_id: dict[str, int] = {}
        self.df: dict[int, int] = Counter()  # term_id -> document frequency
        self.num_docs: int = 0

    def build(self, chunks: List[DocumentChunk]):
        """Iterate over all chunks and build the vocabulary."""
        for chunk in chunks:
            tokens = set(tokenize(chunk.text))  # set ensures one count per doc
            self.num_docs += 1
            for term in tokens:
                if term not in self.term_to_id:
                    term_id = len(self.term_to_id)
                    self.term_to_id[term] = term_id
                    self.df[term_id] = 0
                self.df[self.term_to_id[term]] += 1
```

Notice we use `set(tokenize(...))` when counting document frequencies. BM25's IDF component depends on how many *documents* contain a term, not how many times the term appears across all documents. This is a common beginner mistake that silently breaks retrieval quality.

### Step 3: From-Scratch BM25 Implementation

This is the core of the project. The BM25 formula is:

$$
\text{score}(D, Q) = \sum_{i=1}^{n} \text{IDF}(q_i) \cdot \frac{f(q_i, D) \cdot (k_1 + 1)}{f(q_i, D) + k_1 \cdot \left(1 - b + b \cdot \frac{|D|}{\text{avgdl}}\right)}
$$

Where:
- $f(q_i, D)$ is the term frequency of query term $q_i$ in document $D$
- $|D|$ is the document length
- $\text{avgdl}$ is the average document length across the corpus
- $k_1$ controls term frequency saturation (typically 1.2–2.0)
- $b$ controls length normalization (typically 0.75)

```python
import math
from typing import List

class BM25:
    """A from-scratch BM25 ranker."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.vocab: Vocabulary | None = None
        self.doc_lengths: list[int] = []
        self.avgdl: float = 0.0
        self.term_freqs: list[dict[int, int]] = []  # one dict per doc: term_id -> freq
        self.corpus: list[str] = []

    def fit(self, chunks: List[DocumentChunk]):
        """Build the inverted index and pre-compute all statistics."""
        self.vocab = Vocabulary()
        self.vocab.build(chunks)
        self.corpus = [chunk.text for chunk in chunks]
        self.doc_lengths = [len(tokenize(chunk.text)) for chunk in chunks]
        self.avgdl = sum(self.doc_lengths) / len(self.doc_lengths)

        # Build term frequency per document
        self.term_freqs = []
        for chunk in chunks:
            tf = Counter(tokenize(chunk.text))
            self.term_freqs.append({self.vocab.term_to_id[t]: c for t, c in tf.items() if t in self.vocab.term_to_id})

    def _idf(self, term_id: int) -> float:
        """Compute smoothed IDF: log((N - df + 0.5) / (df + 0.5) + 1)."""
        n = self.vocab.num_docs
        df = self.vocab.df[term_id]
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def score(self, query: str, top_k: int = 5) -> list[tuple[int, float]]:
        """Return top_k (doc_index, score) tuples sorted by descending score."""
        assert self.vocab is not None, "Call fit() before score()"
        query_terms = tokenize(query)
        query_term_ids = [self.vocab.term_to_id[t] for t in query_terms if t in self.vocab.term_to_id]

        scores = [0.0] * len(self.corpus)
        for term_id in query_term_ids:
            idf = self._idf(term_id)
            if idf <= 0:
                continue  # term appears in too many docs; skip
            for doc_idx in range(len(self.corpus)):
                tf = self.term_freqs[doc_idx].get(term_id, 0)
                if tf == 0:
                    continue
                doc_len = self.doc_lengths[doc_idx]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * doc_len / self.avgdl)
                scores[doc_idx] += idf * (numerator / denominator)

        # Sort by score descending, return top_k
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        return ranked[:top_k]
```

The key details here:

- **Smoothened IDF** uses the Robertson-Sparck-Jones formula with the +1 smoothing term, which prevents negative scores for terms that appear in many documents.
- **Term frequency saturation** via the $(k_1 + 1)$ numerator and $f + k_1 \cdot (\ldots)$ denominator ensures that repeated terms don't dominate — a document containing a query term 50 times doesn't score 50× higher than one containing it once.
- **Length normalization** with $b$ prevents long documents from always winning simply because they contain more tokens.

### Step 4: RAG Orchestrator

```python
class RAGOrchestrator:
    """Combines BM25 retrieval with LLM generation."""

    def __init__(self, bm25: BM25, chunks: List[DocumentChunk]):
        self.bm25 = bm25
        self.chunks = chunks

    def retrieve(self, query: str, top_k: int = 3) -> list[DocumentChunk]:
        """Retrieve top_k chunks using BM25."""
        ranked = self.bm25.score(query, top_k=top_k)
        return [self.chunks[idx] for idx, _ in ranked]

    def generate(self, query: str, top_k: int = 3) -> str:
        """Retrieve relevant chunks, build a prompt, and call the LLM."""
        retrieved = self.retrieve(query, top_k)
        context = "\n---\n".join(
            f"[Chunk {i+1} from {doc.source}]:\n{doc.text}"
            for i, doc in enumerate(retrieved)
        )
        prompt = (
            f"Answer the question using only the provided context.\n\n"
            f"Context:\n{context}\n\n"
            f"Question: {query}\n\n"
            f"Answer:"
        )
        return self._call_llm(prompt)

    def _call_llm(self, prompt: str) -> str:
        """Call an LLM API. Replace with your provider of choice."""
        import openai
        client = openai.OpenAI()  # configure your API key via env var
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "content", "content": prompt}],
            max_tokens=512,
        )
        return response.choices[0].message.content
```

This orchestrator is deliberately thin. The real engineering lives in the retrieval and indexing layers — that's where the from-scratch BM25 differentiates your project from someone who just calls LangChain's `RetrievalQA` chain.

---

## Running and Testing It

To verify the pipeline works end-to-end, you need a test corpus and assertions on retrieval quality.

### Local Setup

```bash
# Create a virtual environment
python -m venv venv && source venv/bin/activate

# Install dependencies
pip install numpy PyPDF2 openai rank_bm25

# Place your documents in a data/ directory
mkdir -p data && cp your_docs/*.txt data/
```

### Smoke Test

```python
from rag_pipeline import load_documents, BM25, RAGOrchestrator

# Load and index
chunks = load_documents("data")
print(f"Indexed {len(chunks)} chunks from {len(set(c.source for c in chunks))} documents.")

bm25 = BM25()
bm25.fit(chunks)

# Test retrieval
query = "What is the company's remote work policy?"
results = bm25.score(query, top_k=3)
for idx, score in results:
    print(f"[Score: {score:.4f}] {chunks[idx].source} (chunk {chunks[idx].chunk_index})")
    print(f"  Preview: {chunks[idx].text[:120]}...\n")

# Full RAG test
orchestrator = RAGOrchestrator(bm25, chunks)
answer = orchestrator.generate(query, top_k=3)
print(f"\nAnswer: {answer}")
```

### Validation Strategy

Don't rely on eyeballing output. Build a small set of known-question / known-answer pairs and assert that the correct chunk ranks first:

```python
def test_retrieval_accuracy(bm25, chunks):
    """Verify that specific queries retrieve the expected chunk as top result."""
    test_cases = [
        ("remote work policy", 2),   # expect chunk 2 to rank first
        ("quarterly revenue 2024", 5),
        ("PTO accrual rules", 7),
    ]
    for query, expected_chunk_idx in test_cases:
        top = bm25.score(query, top_k=1)[0]
        assert top[0] == expected_chunk_idx, (
            f"Query '{query}': expected chunk {expected_chunk_idx}, got {top[0]}"
        )
    print("All retrieval accuracy tests passed.")
```

This kind of deterministic test is what turns a weekend project into something you can point to in an interview and say, "I wrote tests for it."

---

## Extending It: Your Roadmap to Senior-Level

The base pipeline is impressive on its own, but the extensions are what separate it from a toy and position it as a genuine systems project. Here are six concrete upgrades:

1. **Persistent Index with Redis or SQLite.** Store the inverted index, document frequencies, and term-to-ID mappings in Redis or SQLite so you don't rebuild from scratch on every restart. *It matters because* rebuilding a BM25 index over millions of documents can take minutes; serving that latency in production is unacceptable.

2. **Horizontal Scaling with Ray Serve.** Wrap the BM25 scorer as a Ray Serve deployment so multiple retriever instances can handle concurrent queries. *It matters because* search workloads are inherently parallel, and demonstrating you can distribute retrieval across nodes is a senior-level systems skill.

3. **Observability with Prometheus and Grafana.** Instrument the retriever to emit metrics: query latency (p50, p95, p99), recall@k over a validation set, and cache hit rate. *It matters because* in production, you can't improve what you can't measure — and hiring managers who have scaled systems know this.

4. **Hybrid Retrieval: BM25 + Dense Vectors.** Add a sentence-transformers-based dense retriever alongside BM25, and fuse scores using reciprocal rank fusion (RRF). *It matters because* sparse and dense retrieval are complementary — BM25 excels at keyword matching while dense vectors capture semantic similarity.

5. **Fault Tolerance with Checkpointing and Retries.** Implement checkpointed indexing (save progress after each document) and exponential backoff retries for LLM API calls. *It matters because* real pipelines fail — documents corrupt, APIs rate-limit, and nodes crash. Recovery logic is what separates prototypes from production.

6. **Benchmarking Suite with Custom Queries.** Build a benchmark harness that measures mean reciprocal rank (MRR) and normalized discounted cumulative gain (NDCG@k) against a labeled query set. *It matters because* tuning BM25 parameters ($k_1$, $b$) without metrics is guessing; with NDCG, it's engineering.

Each of these maps directly to a concept tested in senior engineering interviews: distributed systems, observability, reliability, and performance optimization.

---

## Key Takeaways

- **BM25 from scratch forces deep understanding.** Implementing the formula yourself — not just calling `rank_bm25.BM25Okapi` — teaches you term frequency saturation, length normalization, and IDF smoothing in a way that API calls never will.
- **Modular architecture is the real signal.** The separation of ingestion, indexing, retrieval, and generation means you can swap components. That modularity is what production systems demand and what interviewers look for.
- **Tests and metrics separate prototypes from projects.** A deterministic retrieval accuracy test and an NDCG benchmark transform this from a "cool weekend project" into demonstrable engineering rigor.
- **The extension roadmap maps to senior-level skills.** Persistence, horizontal scaling, observability, fault tolerance, and benchmarking are the exact pillars of production-grade systems engineering.
- **This project is directly relevant to current hiring demand.** RAG is the dominant pattern for grounding LLMs in proprietary data, and understanding retrieval at the algorithm level makes you a stronger candidate for ML Engineer, Search Engineer, and Backend roles alike.

---

## Further Reading

To deepen and evolve this project, study these primary sources:

- **["The Probabilistic Relevance Framework: Retrieval Models and the Information Scientist"](https://plg.uwaterloo.ca/~gvcormac/cs846/papers/robertson-probabilistic-relevance.pdf)** — Robertson and Walker's foundational paper that establishes the probabilistic derivation behind BM25. Essential reading for understanding *why* the formula takes its specific form.

- **["Introduction to Information Retrieval" by Manning, Raghavan, and Schütze](https://nlp.stanford.edu/IR-book/)** — The canonical textbook. Chapters 6 and 8 cover the probabilistic retrieval framework and BM25 in depth, with rigorous mathematical treatment.

- **[BM25: The Practical Explanation](https://www.youtube.com/watch?v=p1Y2Nk1fDOA)** — While not a paper, this accompanies the original [1994 SIGIR paper by Robertson, Walker, Jones, and Harmsworth](https://dl.acm.org/doi/10.1145/170985.170995) that introduced BM25 as a practical parameterization.

- **[FAISS: Facebook AI Similarity Search](https://github.com/facebookresearch/faiss)** — If you pursue the hybrid retrieval extension (BM25 + dense vectors), FAISS is the standard library for efficient similarity search and provides GPU-accelerated indexing.

- **[Ray Serve Documentation](https://docs.ray.io/en/latest/serve/)** — For the horizontal scaling extension, Ray Serve provides a production-grade framework for deploying Python inference models as scalable HTTP services.

- **[Reciprocal Rank Fusion in Learning to Rank](https://www.microsoft.com/en-us/research/publication/reciprocal-rank-fusion-for-dense-retrieval-in-microsofts-bing-search-engine/)** — Microsoft Research's paper on RRF, the standard technique for fusing sparse and dense retrieval scores in modern RAG pipelines.

- **[Prometheus Best Practices](https://prometheus.io/docs/practices/naming/)** — For the observability extension, Prometheus's official naming and instrumentation conventions are the industry standard for metric design.

---

This project gives you something rare: a side project that you can *build* in a weekend, *explain* in an interview, and *extend* for months. That's the trifecta that gets callbacks. Start with the BM25 implementation, write the tests, and then iterate through the roadmap. Your future hiring manager will notice.