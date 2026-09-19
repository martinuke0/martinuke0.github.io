

---
title: "Building a Pure-Python IVF-PQ Vector Index with On-Disk Storage for RAG Pipelines"
date: "2026-09-19T20:01:23.740"
draft: false
tags: ["vector-search", "python", "rag", "ivf", "pq", "on-disk-storage"]
description: "Learn to build a pure‑Python IVF‑PQ vector index with on‑disk storage, enabling fast approximate retrieval for RAG pipelines and LLM applications."
summary: "This guide walks through implementing an IVF‑PQ index in pure Python, storing data on disk and integrating it into a RAG pipeline for sub‑second similarity search."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-19-building-a-pure-python-ivf-pq-vector-index-with-on-disk-storage-for-rag-pipelines.svg"
  alt: "A diagram of a vector index"
  caption: ""
  relative: false
---

> **TL;DR** — You will implement a pure‑Python IVF‑PQ index that stores vectors on disk, delivering sub‑second approximate nearest‑neighbor retrieval for RAG pipelines. The design combines inverted file clustering with product quantization to compress large collections, and it can be extended with persistence, scaling, and observability.

In the rapidly evolving field of retrieval‑augmented generation (RAG), the ability to quickly find the most relevant documents or embeddings is a bottleneck. While libraries such as FAISS or Annoy provide out‑of‑the‑box solutions, building your own index from first principles signals a deep understanding of vector search, compression, and storage systems—skills that hiring managers value highly. This post walks you through constructing a pure‑Python IVF‑PQ (Inverted File with Product Quantization) index that persists data to disk, integrates with a RAG pipeline, and can be extended to production‑grade features.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – You will implement k‑means clustering, product quantization, and inverted file posting lists, demonstrating mastery of approximate nearest‑neighbor (ANN) search.
- **Systems engineering** – The index is stored on disk with efficient serialization, showing you can handle large datasets that exceed memory.
- **Performance tuning** – You will measure recall‑latency trade‑offs and optimize I/O patterns, a key skill for building low‑latency retrieval services.
- **Relevance to AI roles** – The project directly maps to positions such as ML Engineer, Vector Database Engineer, and AI Infrastructure Engineer, where custom indexing is often required.
- **Extensibility** – By structuring the code with clear modules, you create a foundation for adding sharding, replication, and observability—hallmarks of senior‑level ownership.

## Architecture Overview

The system consists of four logical layers:

1. **Data Ingestion** – Loads raw embeddings (e.g., from OpenAI or Sentence‑Transformers) and normalizes them.
2. **Index Construction** –  
   - *IVF*: Runs k‑means to partition the dataset into `n_lists` clusters.  
   - *PQ*: Splits each vector into `m` sub‑vectors, quantizes each with a separate codebook, producing compressed codes.
3. **On‑Disk Storage** – Stores the quantized codes, cluster assignments, and codebooks in a custom binary format (or pickle) for fast mmap access.
4. **Query Engine** – For a query vector, computes distances to cluster centroids, selects the nearest `n_probe` clusters, and performs asymmetric distance computation (ADC) using the PQ codes.

A simplified text