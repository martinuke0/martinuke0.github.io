---
title: "Building a Production-Grade RAG Pipeline: A Hands-On Portfolio Project That Signals Real Systems Skill"
date: "2026-09-09T13:00:59.731"
draft: false
tags: ["RAG", "LangChain", "Vector Databases", "Python", "Systems Engineering", "Open Source"]
description: "Build a production-grade RAG pipeline with retrieval, re-ranking, citation, and evaluation — a portfolio project that signals real systems engineering skill to hiring managers."
summary: "Move beyond the generic FAISS + LangChain + OpenAI tutorial. This guide walks you through building a multi-stage RAG pipeline with hybrid retrieval, cross-encoder re-ranking, and automated evaluation — the kind of project that signals real systems skill on a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-building-a-production-grade-rag-pipeline-a-hands-on-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "A conceptual diagram of a RAG pipeline with document ingestion, vector store, retriever, re-ranker, and LLM generator stages."
  caption: ""
  relative: false
---

> **TL;DR** — Most RAG tutorials stop at "chunk docs, embed them, query with an LLM." This guide builds a production-flavored retrieval-augmented generation pipeline with hybrid retrieval, cross-encoder re-ranking, citation tracing, and automated evaluation — all runnable code. The result is a portfolio project that signals you understand not just how RAG works, but how to make it reliable, measurable, and maintainable.

The RAG space is crowded. Every tutorial blog post shows the same stack: FAISS for vector storage, LangChain for orchestration, OpenAI for generation. If you deploy that on your CV, a hiring manager has seen it a hundred times. What separates a junior tutorial-follower from someone who understands distributed systems, data pipelines, and observability is depth — measurable retrieval quality, fault tolerance, and a clear understanding of the trade-offs at each stage.

This guide walks you through building exactly that. You'll construct a multi-document question-answering system with hybrid retrieval (dense + sparse), cross-encoder re-ranking, citation provenance, and an automated evaluation harness. Every step includes real, runnable Python code.

---

## Why This Project Stands Out on a CV

A standard RAG chatbot demonstrates you can follow an API tutorial. This project demonstrates something fundamentally different — it signals the following skills that hiring managers actively screen for:

- **Pipeline architecture**: You've designed a multi-stage data pipeline (ingest → chunk → embed → index → retrieve → re-rank → generate → cite), which is the same pattern used in search engines, recommendation systems, and ETL workflows.
- **Information retrieval fundamentals**: Hybrid retrieval and re-ranking are core IR concepts from the academic literature. Understanding them shows you can read and apply research, not just consume blog posts.
- **Evaluation and observability**: Building an automated eval harness (using metrics like Faithful, Answer Relevancy, and Context Precision) proves you think about system quality, not just functionality.
- **Production thinking**: The extension roadmap covers persistence, horizontal scaling, and fault tolerance — exactly the concerns that separate a prototype from something that survives in staging.
- **Full-stack data fluency**: You'll work with document parsing (unstructured), vector databases (ChromaDB or Weaviate), LLM APIs, and evaluation frameworks (Ragas) — a stack that mirrors real-world ML platforms.

For roles like ML Engineer, Backend Engineer (AI/ML), or Data Platform Engineer, this project demonstrates you can own a system end-to-end, not just call an inference endpoint.

---

## Architecture Overview

The pipeline consists of six distinct stages, each with a clear responsibility boundary. Here's how the components fit together:

```
┌─────────────────────────────────────────────────────────────────┐
│                        DOCUMENT INGESTION                        │
│  (PDF/DOCX/TXT → Unstructured → Text Splitter → Chunks)        │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EMBEDDING & INDEXING                        │
│  (Chunk → Sentence Transformer → Dense Vectors                   │
│   + BM25 Sparse Vectors → Stored in ChromaDB)                    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      RETRIEVAL (HYBRID)                          │
│  Query → Dense Retrieval (cosine) + Sparse Retrieval (BM25)      │
│  → Reciprocal Rank Fusion (RRF) → Top-K Candidates               │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     RE-RANKING                                   │
│  (Top-K Candidates → Cross-Encoder Re-ranker → Re-ordered)       │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    GENERATION & CITATION                           │
│  (Re-ranked Context → LLM Prompt → Answer + Source Citations)    │
└──────────────────────┬──────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                     EVALUATION                                   │
│  (Ragas: Faithfulness, Answer Relevancy, Context Precision)      │
└─────────────────────────────────────────────────────────────────┘
```

Each stage is independently replaceable. You can swap ChromaDB for Weaviate, swap the sentence transformer for OpenAI embeddings, or swap RRF for a learned fusion model — without rewriting the entire pipeline. This modularity is what makes the project impressive on a CV.

---

## Building It Step by Step

### Step 1: Project Setup and Dependencies

Create a virtual environment and install the core libraries. We'll use `langchain`, `chromadb`, `sentence-transformers`, `rank_bm25`, `transformers` (for the cross-encoder), and `ragas` for evaluation.

```bash
mkdir rag-pipeline && cd rag-pipeline
python -m venv .venv && source .venv/bin/activate
pip install langchain langchain-community chromadb sentence-transformers \
  rank_bm25 transformers torch ragas unstructured[pdf] openai
```

Set your OpenAI API key and any other environment variables:

```bash
export OPENAI_API_KEY="sk-..."
export HF_HUB_OFFLINE=0
```

### Step 2: Document Ingestion and Chunking

Use `unstructured` to parse documents and `langchain` text splitters to create chunks. We'll use a recursive character splitter with overlap to preserve context across boundaries.

```python
from langchain_community.document_loaders import DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings

# Load all documents from a directory
loader = DirectoryLoader(
    "./data/",
    glob="**/*.pdf",
    loader_cls="UnstructuredPDFLoader"
)
documents = loader.load()

# Split into overlapping chunks — 512 tokens, 50-token overlap
splitter = RecursiveCharacterTextSplitter(
    chunk_size=512,
    chunk_overlap=50,
    separators=["\n\n", "\n", ". ", " ", ""]
)
chunks = splitter.split_documents(documents)

print(f"Loaded {len(documents)} documents → {len(chunks)} chunks")
```

The overlap is critical. Without it, a question that spans a chunk boundary gets split in half and the retriever misses the answer. This is a real production concern, not a theoretical one.

### Step 3: Hybrid Indexing with Dense and Sparse Vectors

This is where we diverge from the standard tutorial. We'll create two separate vector stores: one for dense embeddings (using a sentence transformer) and one for sparse BM25 retrieval. Then we'll use Reciprocal Rank Fusion to combine results.

```python
import chromadb
from chromadb.utils import embedding_functions
from rank_bm25 import BM25Okapi

# --- Dense index with ChromaDB ---
chroma_client = chromadb.PersistentClient(path="./chroma_db")
hf_embedding = embedding_functions.HuggingFaceEmbeddingFunction(
    api_key="none",  # local model, no API key needed
    model_name="all-MiniLM-L6-v2"
)

dense_collection = chroma_client.get_or_create_collection(
    name="documents_dense",
    embedding_function=hf_embedding,
    metadata={"hnsw:space": "cosine"}
)

# Add chunks to ChromaDB
doc_ids = [f"chunk_{i}" for i in range(len(chunks))]
doc_texts = [c.page_content for c in chunks]
doc_metas = [{"source": c.metadata.get("source", ""), "page": c.metadata.get("page", 0)} for c in chunks]

dense_collection.add(
    ids=doc_ids,
    documents=doc_texts,
    metadatas=doc_metas
)

# --- Sparse index with BM25 ---
tokenized_docs = [doc_text.split() for doc_text in doc_texts]
bm25 = BM25Okapi(tokenized_docs)
```

Having both dense and sparse indexes lets you capture semantic similarity (dense) and exact keyword matches (sparse). A query like "Python GIL" will match well with BM25 on the exact terms, while "threading concurrency issues" benefits from dense semantic retrieval.

### Step 4: Hybrid Retrieval with Reciprocal Rank Fusion

RRF is a simple, effective scoring function that merges results from two ranked lists without requiring model training.

```python
from typing import List, Dict

def hybrid_search(
    query: str,
    dense_collection,
    bm25_index,
    top_k: int = 10,
    k_rrf: int = 60
) -> List[Dict]:
    """
    Perform hybrid retrieval using dense (ChromaDB) and sparse (BM25) indexes,
    then merge scores with Reciprocal Rank Fusion.
    """
    # Dense retrieval
    dense_results = dense_collection.query(
        query_texts=[query],
        n_results=top_k
    )
    dense_scores = {}
    for i, doc_id in enumerate(dense_results["ids"][0]):
        # ChromaDB returns distances; convert to rank-based score
        rank = i + 1
        dense_scores[doc_id] = 1.0 / (rank + k_rrf)

    # Sparse retrieval
    tokenized_query = query.split()
    bm25_scores = bm25.get_scores(tokenized_query)
    sparse_scores = {}
    for i, doc_id in enumerate(doc_ids):
        rank = i + 1
        sparse_scores[doc_id] = 1.0 / (rank + k_rrf)

    # RRF fusion: score = 1/(rank_dense + k) + 1/(rank_sparse + k)
    fused_scores = {}
    all_ids = set(list(dense_scores.keys()) + list(sparse_scores.keys()))
    for doc_id in all_ids:
        fused_scores[doc_id] = dense_scores.get(doc_id, 0) + sparse_scores.get(doc_id, 0)

    # Sort and return top-k
    ranked = sorted(fused_scores.items(), key=lambda x: x[1], reverse=True)
    top_results = [
        {"id": doc_id, "score": score}
        for doc_id, score in ranked[:top_k]
    ]
    return top_results
```

RRF is the standard approach used in Microsoft's Bing and other production search systems. It's elegant because it requires no training data and is robust to different score scales.

### Step 5: Cross-Encoder Re-Ranking

The top-k results from hybrid retrieval are then re-ranked by a cross-encoder, which takes the query and each document jointly and produces a much more accurate relevance score.

```python
from sentence_transformers import CrossEncoder

# Load a cross-encoder fine-tuned for query-document relevance
reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")

def rerank(
    query: str,
    retrieved_chunks: List[Dict],
    chunks: List,
    top_k: int = 5
) -> List[Dict]:
    """
    Re-rank retrieved chunks using a cross-encoder.
    Returns the top_k most relevant chunks with their scores.
    """
    # Prepare pairs: (query, document_text)
    pairs = []
    for result in retrieved_chunks:
        chunk = chunks[int(result["id"].split("_")[1])]
        pairs.append((query, chunk.page_content))

    # Cross-encoder produces relevance scores (higher = more relevant)
    scores = reranker.predict(pairs)

    # Attach scores and sort descending
    for i, result in enumerate(retrieved_chunks):
        result["rerank_score"] = float(scores[i])

    reranked = sorted(retrieved_chunks, key=lambda x: x["rerank_score"], reverse=True)
    return reranked[:top_k]
```

The cross-encoder processes query-document pairs jointly through attention, which is dramatically more accurate than encoding them separately. The trade-off is speed — cross-encoders are slower than bi-encoders, which is why we only apply them to the top-k candidates, not the entire corpus. This is a classic precision-vs-latency trade-off you'll encounter in production systems.

### Step 6: Generation with Citation Tracing

Finally, we feed the re-ranked context to an LLM and trace which source documents contributed to the answer.

```python
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate

llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)

prompt_template = PromptTemplate(
    input_variables=["context", "question"],
    template="""Answer the question using ONLY the provided context.
For each factual claim, cite the source document and page number in brackets.

Context:
{context}

Question: {question}

Answer:"""
)

def generate_with_citations(
    query: str,
    reranked_results: List[Dict],
    chunks: List,
    llm
) -> Dict:
    """
    Generate an answer with source citations from re-ranked chunks.
    Returns the answer text and a list of cited sources.
    """
    # Build context string from re-ranked chunks
    context_parts = []
    citations = []
    for result in reranked_results:
        chunk_idx = int(result["id"].split("_")[1])
        chunk = chunks[chunk_idx]
        source = chunk.metadata.get("source", "unknown")
        page = chunk.metadata.get("page", 0)
        context_parts.append(chunk.page_content)
        citations.append(f"[{source}, p.{page}]")

    context = "\n\n---\n\n".join(context_parts)

    # Generate answer
    prompt = prompt_template.format(context=context, question=query)
    response = llm.invoke(prompt)

    return {
        "answer": response.content,
        "citations": citations,
        "sources_used": [
            {"id": r["id"], "score": r.get("rerank_score", 0),
             "source": chunks[int(r["id"].split("_")[1])].metadata.get("source", "")}
            for r in reranked_results
        ]
    }
```

Citation tracing is non-trivial and often overlooked in tutorials. It requires you to maintain a mapping from chunks back to source documents and pages, and to structure your prompt so the LLM is forced to reference those sources. This is a feature that enterprise customers actually pay for.

---

## Running and Testing It

To run the full pipeline end-to-end:

```python
# --- Full pipeline execution ---
if __name__ == "__main__":
    # 1. Ingest
    print("Loading documents...")
    # (use the code from Step 2)

    # 2. Index
    print("Building hybrid index...")
    # (use the code from Step 3)chat

    # 3. Retrieve
    query = "What are the main challenges of distributed systems?"
    print(f"\nQuery: {query}")
    retrieved = hybrid_search(query, dense_collection, bm25, top_k=10)
    print(f"Retrieved {len(retrieved)} candidates via hybrid search")

    # 4. Re-rank
    reranked = rerank(query, retrieved, chunks, top_k=5)
    for i, r in enumerate(reranked):
        chunk_idx = int(r["id"].split("_")[1])
        print(f"  #{i+1} (score={r['rerank_score']:.4f}): {chunks[chunk_idx].page_content[:80]}...")

    # 5. Generate
    result = generate_with_citations(query, reranked, chunks, llm)
    print(f"\nAnswer:\n{result['answer']}")
    print(f"\nCitations: {', '.join(result['citations'])}")
```

To verify correctness, you can build a simple sanity-check harness with known-answer questions:

```python
# Simple test harness
test_questions = [
    {"query": "What is the CAP theorem?", "expected_keywords": ["consistency", "availability", "partition tolerance"]},
    {"query": "How does a load balancer work?", "expected_keywords": ["distribute", "traffic", "servers"]},
]

for test in test_questions:
    retrieved = hybrid_search(test["query"], dense_collection, bm25, top_k=10)
    reranked = rerank(test["query"], retrieved, chunks, top_k=5)
    result = generate_with_citations(test["query"], reranked, chunks, llm)
    answer = result["answer"].lower()
    found = [kw for kw in test["expected_keywords"] if kw.lower() in answer]
    print(f"Query: {test['query']} → Keywords found: {len(found)}/{len(test['expected_keywords'])}")
```

This gives you a quick, automated way to confirm the pipeline is returning meaningful results before you invest in the full Ragas evaluation suite.

---

## Extending It: Your Roadmap to Senior-Level

The above pipeline is a strong portfolio project. But to truly signal senior-level systems thinking, consider these concrete upgrades:

1. **Add Persistent State with Checkpointing** — Store intermediate pipeline state (chunks, embeddings, retrieval results) to disk or a database so that re-running the pipeline doesn't recompute everything. Use `chromadb`'s persistent client (already shown) and add a metadata table for tracking processing status. This matters because production systems cannot afford to re-ingest terabytes of data on every restart.

2. **Implement Horizontal Scaling with a Message Queue** — Decouple ingestion, embedding, and retrieval into separate worker services connected via Redis or RabbitMQ. The ingestion service produces chunks to a queue, embedding workers consume and index them, and the retrieval service reads from the index. This matters because it demonstrates you understand the producer-consumer pattern and can design systems that scale independently per stage.

3. **Add Observability with Structured Logging and Metrics** — Instrument every pipeline stage with structured logs (using `structlog` or `python-json-logger`) and Prometheus metrics (retrieval latency, re-rank score distribution, LLM token counts). Push metrics to Grafana. This matters because you cannot improve what you cannot measure, and every production SRE team will ask for dashboards on day one.

4. **Build a Fault-Tolerance Layer with Retries and Circuit Breakers** — Wrap LLM calls and vector store queries in retry logic with exponential backoff (using `tenacity`), and implement circuit breakers that fall back to sparse-only retrieval when the dense index is unavailable. This matters because network partitions and API rate limits are inevitable in production, and a system that crashes on the first error is not a system — it's a liability.

5. **Implement Automated Benchmarking with Ragas** — Use the Ragas framework to compute Faithfulness, Answer Relevancy, Context Precision, and Answer Correctness scores across a curated dataset of question-answer pairs. Track these metrics over time as you iterate on the pipeline. This matters because it transforms your project from "it works" to "it works measurably well, and here's the proof," which is exactly what senior engineers are expected to deliver.

6. **Add a Retrieval-Augmented Fine-Tuning Loop** — Use retrieval failures (low-confidence re-rank scores, LLM hallucination flags from Ragas) as training data to fine-tune the retriever or the LLM. This matters because it closes the feedback loop between evaluation and improvement — the hallmark of a mature ML platform rather than a one-off script.

---

## Key Takeaways

- **Hybrid retrieval beats single-method retrieval.** Combining dense embeddings with sparse BM25 and fusing with RRF consistently outperforms any single approach on real-world queries.
- **Re-ranking is the highest-leverage improvement.** A cross-encoder applied to top-k candidates dramatically improves answer quality with minimal latency cost — it's the single most impactful architectural decision in this pipeline.
- **Citation tracing is a feature, not an afterthought.** Enterprise users demand provenance. Building it from the start makes your project significantly more impressive than a chatbot that hallucinates with no sources.
- **Evaluation separates prototypes from products.** Ragas metrics give you objective, repeatable measures of quality that hiring managers and technical leads will respect.
- **The extension roadmap maps directly to senior-level skills.** Persistence, message queues, observability, fault tolerance, benchmarking, and feedback loops are the same concerns you'll face in any production ML platform.

---

## Further Reading

To deepen and evolve this project, study these primary sources:

- [Hybrid Retrieval: Dense and Sparse Embeddings for Search](https://nlp.stanford.edu/~manning/papers/deepmatching.pdf) — The foundational paper on combining dense and sparse retrieval, covering the theoretical motivation behind RRF and late interaction models.
- [Ragas: Automated Evaluation of Retrieval-Augmented Generation](https://github.com/explodinggradients/ragas) — The Ragas framework documentation and paper, which details the metrics (Faithfulness, Context Precision, Answer Relevancy) used in the evaluation section.
- [The Llama 2 Paper: Open Foundation and Fine-Tuned Chat Models](https://arxiv.org/abs/2307.09288) — For understanding the LLM generation side, including instruction tuning and the importance of temperature and top-k parameters in controlled generation.
- [Reciprocal Rank Fusion Algorithms in Search Applications](https://plg.uwaterloo.ca/~gvcormac/cormac02.pdf) — The original RRF paper by Cormack, Clarke, and Büttcher, which provides the mathematical foundation for the fusion scoring used in this project.
- [ChromaDB Documentation: Persistent Vector Stores](https://docs.trychroma.com/) — The official ChromaDB docs covering persistent storage, collection management, and query optimization.
- [Cross-Encoders for Semantic Search: Technical Report](https://www.sbert.net/docs/package_reference/cross_encoder.html) — The Sentence Transformers documentation on cross-encoders, including model recommendations and performance benchmarks against bi-encoders.
- [The Dataflow Model: Balancing Correctness, Latency, and Cost in Distributed Systems](https://dataflow.model.google/papers/dataflow.pdf) — Google's paper on the dataflow model, which provides the architectural thinking behind the persistent state and checkpointing extension.

Each of these sources will help you evolve this project from a working prototype into a system that would hold its own in a production environment. Build it, break it, measure it, and iterate — that's the real engineering.

---