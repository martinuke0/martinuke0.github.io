---
title: "Understanding RAG from Scratch"
date: "2025-12-26T16:38:33.138"
draft: false
tags: ["RAG", "retrieval-augmented-generation", "embeddings", "vector-databases", "LLM"]
---

## Introduction

Retrieval-Augmented Generation (RAG) has become a foundational pattern for building accurate, scalable, and fact-grounded applications with large language models (LLMs). At its core, RAG combines a retrieval component (to fetch relevant pieces of knowledge) with a generation component (the LLM) that produces answers conditioned on that retrieved context. This article breaks RAG down from first principles: the indexing and retrieval stages, the augmentation of prompts, the generation step, common challenges, practical mitigations, and code examples to get you started.

This guide is written for engineers, ML practitioners, and technical product managers who want a clear, actionable understanding of how to build and operate RAG systems from scratch.

## Table of Contents

- Introduction
- What is RAG? A concise definition
- The RAG pipeline: Four core steps
  - 1) Ingest & Extract
  - 2) Chunking
  - 3) Embedding & Storing (Indexing)
  - 4) Retrieval, Augmentation, Generation
- Detailed indexing pipeline and strategies
  - Parsing & extraction
  - Chunking strategies
  - Embedding models and trade-offs
  - Vector stores and storage formats
- Query-time pipeline
  - Encoding the query
  - Semantic search and similarity metrics
  - Reranking and filtering
  - Prompt construction and context stitching
  - LLM generation and post-processing
- Common challenges and practical mitigations
  - Challenge 1: Re-indexing for new files
  - Challenge 2: Cost and always-on vector DBs
  - Challenge 3: Memory footprint of embeddings
  - Challenge 4: Interpretability and hallucination
- Architecture patterns & scaling considerations
  - Batch vs incremental indexing
  - Hybrid search: sparse + dense
  - Caching, sharding, and quantization
- Metrics and evaluation
- Minimal end-to-end code example (Python)
- Best practices checklist
- Conclusion
- Resources

## What is RAG? A concise definition

Retrieval-Augmented Generation (RAG) is a method that augments an LLM with externally retrieved documents or document fragments to produce more accurate, grounded outputs. Instead of expecting the model to memorize everything, you query a knowledge store at runtime and provide the most relevant snippets as context for generation.

Key benefits:
- Improves factuality and grounding
- Enables up-to-date information without retraining the LLM
- Reduces hallucinations when retrieval is effective

## The RAG pipeline: Four core steps

Although implementations vary, RAG typically follows these four conceptual steps:

1. Ingest & Extract (Collect content from sources)
2. Chunking (Split content into retrievable segments)
3. Embedding & Storing (Indexing: create and persist numeric representations)
4. Retrieval → Augmentation → Generation (Query, fetch relevant chunks, build prompt, generate answer)

We’ll expand each step in detail.

### 1) Ingest & Extract
Extract raw text from documents (web pages, PDFs, slides, databases, logs). Extraction often includes metadata (source, title, URL, timestamps).

### 2) Chunking
Split extracted text into meaningful chunks (segments) that fit well into the LLM context when retrieved. Chunk size choices depend on:
- Token budget (context window)
- Semantic coherence (don’t cut sentences in half)
- Retrieval granularity (fine vs coarse chunks)

### 3) Embedding & Storing (Indexing)
Convert chunks to embeddings with a model (e.g., sentence-transformers, OpenAI embeddings). Store embeddings and metadata in a vector store (FAISS, Milvus, Pinecone, Chroma, Weaviate, etc.). Indexing often involves:
- Encoding
- Optionally reducing dimensionality
- Building an ANN index (HNSW, IVF+PQ)
- Persisting to disk or managed DB

### 4) Retrieval → Augmentation → Generation
At query time:
- Encode the query into an embedding.
- Use nearest-neighbor search to retrieve top-k relevant chunks.
- Optionally rerank results using cross-encoders or BM25.
- Construct a prompt by combining retrieved contexts + instructions + user query.
- Send prompt to LLM for generation.

## Detailed indexing pipeline and strategies

### Parsing & extraction

- HTML: use libraries like BeautifulSoup or newspaper3k.
- PDFs: use PDFPlumber, PyMuPDF, or Textract for text extraction.
- Slides: extract text from PPTX.
- Databases/CSV: read structured fields and serialize.
- OCR: for images or scanned PDFs, use Tesseract or commercial OCR.

Important: preserve metadata (source, page number, position) for traceability and citations.

### Chunking strategies

- Character-based chunking (simple): split by N characters with overlap.
- Sentence-aware chunking: split by sentence boundaries and combine into chunks sized by tokens.
- Token-based chunking: use tokenizer (e.g., tiktoken) to ensure chunks fit token limits precisely.
- Semantic chunking: use heuristics or models to split at topical boundaries.

Example heuristic: chunk size 500 tokens with 50-token overlap.

Blockquote for emphasis:
> Chunk quality has a direct impact on retrieval relevance. Too large and you waste context; too small and you lose semantic coherence.

### Embedding models and trade-offs

- sentence-transformers (SBERT family): good quality for many tasks, offline usage.
- OpenAI embeddings (text-embedding-3 or similar): often robust and well-maintained.
- Mistral/Anthropic/LLM-based embeddings (emerging): check costs and latency.

Trade-offs:
- Dimensionality (1536 vs 768 vs 1024) affects index size and compute.
- Model accuracy vs compute cost/latency.
- Use smaller embeddings for large corpora, larger ones for quality-sensitive use cases.

### Vector stores and storage formats

Options:
- Open-source (FAISS, Annoy, HNSWlib, Milvus, Chroma)
- Managed (Pinecone, Weaviate cloud)
- Considerations: persistence, replication, latency, cost, multi-tenancy, query throughput.

Index types:
- Exact (brute force) — slow for large corpora.
- ANN (HNSW, IVF + PQ) — trade memory/accuracy for speed.

## Query-time pipeline

### Encoding the query

- Use the same embedding model used to index documents.
- If using different models, consider mapping/normalization to align spaces.

### Semantic search and similarity metrics

- Common metric: cosine similarity.
- Euclidean (L2) is used with some ANN algorithms.
- Implement hybrid ranking: BM25 (sparse) + dense embeddings for better recall and precision.

### Reranking and filtering

- Cross-encoder reranking: take top-N candidates and rerank by relevance using a model that sees both query and chunk together.
- Heuristic filters: date, source, security labels.
- Deduplication: remove near-duplicate chunks to improve diversity.

### Prompt construction and context stitching

- Combine the top-k retrieved chunks into the prompt with clear separators and source citations.
- Add system instructions that define the expected output format.
- Respect token limits — trim or summarize retrieved content when necessary.

Example prompt structure:
- System instruction (role, constraints)
- Top-k contextual snippets (with citations)
- User query
- Output format request (JSON, bulleted list, etc.)

### LLM generation and post-processing

- Ask the model to cite sources and avoid inventing facts.
- Post-process to verify or run a short factuality check (e.g., verifier LLM or database query).
- Optionally, perform answer reconciliation: compare multiple runs or use ensemble of prompts.

## Common challenges and practical mitigations

Below are the main challenges you hinted at and practical ways to address them.

### Challenge 1: Re-indexing for new files
Issue: Many systems expect periodic full re-indexing, which is inefficient.

Mitigations:
- Incremental indexing: process only new/changed documents using a change log (timestamps or hashes).
- Event-driven ingestion: trigger indexing when files are added/updated.
- Soft deletes and tombstones: mark removed docs instead of full reindex.
- Use deduplication and ID-based upserts in vector stores.

### Challenge 2: Vector DBs are expensive / always-on
Issue: Managed vector DBs can be costly; self-hosting has operational overhead.

Mitigations:
- Use hybrid design: keep cold data on cheaper object storage and only index hot data.
- Use on-disk ANN like FAISS with memory-mapped indexes to reduce RAM pressure.
- Autoscale managed services and use cost-aware TTL for rarely accessed indexes.
- Consider sharding by workspace or tenant for multi-tenant cost control.

### Challenge 3: Embeddings cause large memory footprint
Issue: Storing millions of embeddings consumes RAM/disk.

Mitigations:
- Quantization and compression (PQ, OPQ, Q4/KMeans).
- Lower-dimensional embeddings or PCA reduction after embedding.
- Store embeddings on-disk and use memory-mapped ANN indexes.
- Archive older embeddings or move to secondary storage.

### Challenge 4: Lack of interpretability and hallucinations
Issue: Vector similarity gives no reasoning why a chunk was relevant; LLMs can still hallucinate.

Mitigations:
- Surface provenance: include source metadata with each retrieved chunk and instruct the model to cite it.
- Use rerankers and cross-encoders to improve retrieval precision.
- Add a verification step: have a secondary model check claims against retrieved data.
- Return confidence scores and expose them in the UI.

Blockquote important:
> Always provide provenance and make hallucination mitigation part of your UX: let users see where claims come from.

## Architecture patterns & scaling considerations

- Batch vs incremental indexing: batch for large backfills, incremental for streaming updates.
- Hybrid search: combine BM25 for recall with dense embeddings for semantic relevance.
- Sharding: distribute indices by domain or tenant.
- Caching: cache query embeddings and top-k results to reduce repeated search costs.
- Quantization & ANN: reduce storage and speed up retrieval with PQ/HNSW.
- Monitoring: track latency, retrieval accuracy, token usage, and hallucination incidents.

## Metrics and evaluation

Track both system-level and ML metrics:
- Recall@k, Precision@k, MRR (mean reciprocal rank)
- Latency (indexing, retrieval, total response time)
- Cost per query (embedding cost + vector DB cost + LLM tokens)
- Hallucination rate (manual or automated checks)
- User satisfaction / task success (product metric)

Use test suites with ground-truth Q&A pairs to evaluate end-to-end RAG performance.

## Minimal end-to-end code example (Python)

Below is a simple example: extract text, chunk, embed with sentence-transformers, index with FAISS, and query. This is a minimal demo—production systems require more robustness.

```python
# Requirements:
# pip install sentence-transformers faiss-cpu tiktoken

from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import tiktoken  # optional for token-aware chunking
import math

# 1) Simple chunker
def simple_chunk(text, max_chars=2000, overlap=200):
    start = 0
    chunks = []
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
        if start < 0:
            start = 0
    return chunks

# 2) Embed and index
model = SentenceTransformer('all-MiniLM-L6-v2')  # small & fast
documents = {
    "doc1": "Long text from doc 1 ...",
    "doc2": "Long text from doc 2 ..."
}
all_chunks = []
metadata = []

for doc_id, text in documents.items():
    for i, chunk in enumerate(simple_chunk(text, max_chars=800, overlap=100)):
        all_chunks.append(chunk)
        metadata.append({"doc_id": doc_id, "chunk_id": i})

embs = model.encode(all_chunks, convert_to_numpy=True)

# Build FAISS index (L2 distance on normalized vectors => cosine)
d = embs.shape[1]
index = faiss.IndexFlatIP(d)  # inner product = cosine if normalized
# normalize
norms = np.linalg.norm(embs, axis=1, keepdims=True)
embs_norm = embs / (norms + 1e-10)
index.add(embs_norm)

# 3) Query
def query_rag(q, top_k=5):
    q_emb = model.encode([q], convert_to_numpy=True)
    q_emb = q_emb / (np.linalg.norm(q_emb, axis=1, keepdims=True) + 1e-10)
    scores, ids = index.search(q_emb, top_k)
    results = []
    for score, idx in zip(scores[0], ids[0]):
        results.append({"score": float(score), "text": all_chunks[idx], "meta": metadata[idx]})
    return results

q = "Explain the main idea from doc1"
print(query_rag(q, top_k=3))
```

Next steps: build a prompt by concatenating the top-k texts with citations and call your preferred LLM (OpenAI, Anthropic, local LLM) to generate the final answer.

## Best practices checklist

- Use token-aware chunking to optimize context usage.
- Keep provenance metadata for every chunk (source, page, timestamp).
- Combine sparse and dense retrieval for robust recall.
- Implement incremental indexing; avoid full reindexes when possible.
- Quantize or compress embeddings for large corpora to save cost.
- Rerank top-k candidates using a cross-encoder for precision-critical flows.
- Limit and control LLM output format via system prompts and output templates.
- Monitor hallucinations and set up human-in-the-loop review for high-risk domains.

## Conclusion

RAG is a practical, powerful architecture for combining retrieval and generation. By separating knowledge storage (index) from reasoning (LLM), you get a system that can stay up-to-date and grounded without retraining the model every time knowledge changes. The core building blocks—ingest & extract, chunking, embedding & storing, retrieval & augmentation, and generation—are conceptually simple but require careful engineering to handle real-world scale, cost, and correctness constraints.

When building a RAG system, prioritize good chunking and provenance, choose cost-effective embedding and vector storage strategies, and add verification steps to reduce hallucination. With these patterns and practices, RAG can substantially improve factuality and usefulness of LLM-driven apps.

## Resources

- Original RAG paper (Facebook AI Research) — for conceptual background
- SentenceTransformers: https://www.sbert.net
- FAISS: https://github.com/facebookresearch/faiss
- Pinecone, Weaviate, Milvus, Chroma — vector DB providers
- BM25 and sparse retrieval resources (e.g., Whoosh, Elasticsearch)
- tiktoken for token-aware chunking (OpenAI tokenizer)

If you'd like, I can:
- Provide a production-ready template using a managed vector DB + OpenAI/Anthropic embeddings and generator.
- Show a detailed incremental-indexing pattern (event-driven) with code.
- Walk through building provenance-aware prompts and a reranker.

Which follow-up would you like next?