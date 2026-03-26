---
title: "Engineering High-Performance RAG Pipelines with Distributed Vector Indexes and Parallelized Document Processing"
date: "2026-03-26T12:00:43.154"
draft: false
tags: ["RAG", "vector-search", "distributed-systems", "parallel-processing", "LLM"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why RAG Needs High Performance](#why-rag-needs-high-performance)  
3. [Architectural Foundations of a Scalable RAG System](#architectural-foundations-of-a-scalable-rag-system)  
   1. [Ingestion & Chunking](#ingestion--chunking)  
   2. [Embedding Generation](#embedding-generation)  
   3. [Vector Storage & Retrieval](#vector-storage--retrieval)  
   4. [Generative Layer](#generative-layer)  
4. [Distributed Vector Indexes](#distributed-vector-indexes)  
   1. [Sharding Strategies](#sharding-strategies)  
   2. [Choosing the Right Engine](#choosing-the-right-engine)  
   3. *Hands‑on*: Deploying a Milvus Cluster with Docker Compose  
5. [Parallelized Document Processing](#parallelized-document-processing)  
   1. [Batching & Asynchrony](#batching--asynchrony)  
   2. [Frameworks: Ray, Dask, Spark](#frameworks-ray-dask-spark)  
   3. *Hands‑on*: Parallel Embedding with Ray and OpenAI API  
6. [End‑to‑End Pipeline Orchestration](#end-to-end-pipeline-orchestration)  
   1. [Workflow Engines (Airflow, Prefect, Dagster)](#workflow-engines)  
   2. *Example*: A Prefect Flow for Continuous Index Updates  
7. [Performance Optimizations & Best Practices](#performance-optimizations--best-practices)  
   1. [Index Compression & Quantization](#index-compression--quantization)  
   2. [GPU‑Accelerated Search](#gpu-accelerated-search)  
   3. [Caching & Warm‑up Strategies](#caching--warm-up-strategies)  
   4. [Latency Monitoring & Alerting](#latency-monitoring--alerting)  
8. [Real‑World Case Study: Enterprise Knowledge‑Base Search](#real-world-case-study)  
9. [Testing, Monitoring, and Autoscaling](#testing-monitoring-and-autoscaling)  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)  

---

## Introduction

Retrieval‑Augmented Generation (RAG) has become the de‑facto pattern for building **knowledge‑aware** language‑model applications. By coupling a large language model (LLM) with a non‑parametric memory store—typically a **vector index** of document embeddings—RAG systems can answer factual queries, cite sources, and stay up‑to‑date without costly model retraining.

However, the naive implementation of RAG (single‑node FAISS index, serial document processing) quickly hits performance ceilings when:

* The corpus grows beyond a few hundred thousand passages.  
* Real‑time latency requirements tighten to sub‑second levels.  
* Enterprises demand continuous ingestion of new documents while serving millions of queries per day.

This article walks you through the engineering decisions, architectural patterns, and concrete code required to **scale RAG pipelines** to production‑grade workloads. We will focus on two pillars:

1. **Distributed Vector Indexes** – spreading the similarity search across many machines, handling sharding, replication, and GPU acceleration.  
2. **Parallelized Document Processing** – turning the traditionally serial steps of chunking, embedding, and indexing into high‑throughput, fault‑tolerant pipelines.

By the end, you’ll have a reference architecture you can adapt to your own domain, whether it’s a corporate knowledge base, a legal‑document search engine, or a multimodal media retrieval system.

---

## Why RAG Needs High Performance

| Bottleneck | Typical Symptoms | Impact on User Experience |
|------------|------------------|---------------------------|
| **Embedding Generation** | API rate limits, CPU‑bound tokenization | Slow ingestion, stale index |
| **Vector Search** | Linear scan on a single node, high latency | Users wait >2 s for answers |
| **Data Freshness** | Batch re‑index only nightly | Missed updates, inaccurate citations |
| **Scalability** | Single‑node memory caps at ~10 M vectors | Inability to grow beyond a few GB of text |

A production RAG system must simultaneously satisfy:

* **Throughput** – hundreds to thousands of queries per second (QPS).  
* **Latency** – sub‑500 ms end‑to‑end for most interactive apps.  
* **Freshness** – ingestion latency < 5 minutes for newly added documents.  
* **Reliability** – graceful degradation under node failures.

Achieving these targets requires **horizontal scaling** (adding more machines) for both the vector store and the embedding pipeline, as well as **software‑level parallelism** (multi‑threading, async I/O, distributed task queues).

---

## Architectural Foundations of a Scalable RAG System

Below is a high‑level data flow diagram (textual) that we will reference throughout the post:

```
[Source Documents] → [Ingestion Service] → [Chunker] → [Embedding Worker Pool] 
      → [Distributed Vector Index] ↔ [Cache Layer] → [Retriever] → [LLM Generator] → [Response]
```

### Ingestion & Chunking

* **Source Diversity** – PDFs, HTML, Office files, Slack logs, etc.  
* **Chunking Strategies** – fixed token size (e.g., 384 tokens), semantic splitters (e.g., LangChain’s `RecursiveCharacterTextSplitter`), or hybrid approaches that respect headings.  
* **Metadata Enrichment** – store source ID, timestamps, and hierarchical path for later citation.

### Embedding Generation

* **Model Choices** – OpenAI `text-embedding-3-large`, Cohere, HuggingFace `sentence-transformers`.  
* **Batch Size** – 64–256 vectors per API call (depends on provider limits).  
* **Hardware** – GPU inference with `sentence-transformers` can achieve >10 k embeddings/s on a single A100.

### Vector Storage & Retrieval

* **Similarity Metric** – Cosine similarity (most common) or inner product.  
* **Index Types** – IVF‑PQ, HNSW, Disk‑ANN.  
* **Distribution** – Sharding across nodes, replication for fault tolerance, and optionally a query router (e.g., Milvus Proxy, Vespa).

### Generative Layer

* **LLM** – GPT‑4‑Turbo, Claude‑3, or an Open‑source model (Llama‑3).  
* **Prompt Engineering** – include retrieved passages, source citations, and a “ground‑truth check” instruction.  
* **Post‑processing** – response validation, hallucination detection, and format enforcement.

---

## Distributed Vector Indexes

### Sharding Strategies

| Strategy | Description | Pros | Cons |
|----------|-------------|------|------|
| **Hash‑Based Sharding** | `doc_id % N` determines shard | Simple, deterministic routing | Uneven load if IDs not uniformly distributed |
| **Range Sharding** | Partition by embedding magnitude or timestamp | Allows time‑based retention policies | Requires rebalancing when ranges grow |
| **Hybrid (Hash + Replication)** | Primary hash shard + 1‑2 replicas | High availability, read scaling | Extra storage overhead |

A well‑designed sharding layer should expose **stateless routing** (e.g., via a proxy service) so that client code does not need to know the physical layout.

### Choosing the Right Engine

| Engine | Open‑Source / SaaS | GPU Support | Auto‑Scaling | Notable Features |
|--------|-------------------|-------------|--------------|-------------------|
| **Milvus** | Open‑Source | ✅ (GPU‑IVF, GPU‑HNSW) | ✅ (K8s operator) | Built‑in `HybridSearch`, dynamic partitioning |
| **Vespa** | Open‑Source | ✅ (CPU‑only, GPU via plugins) | ✅ (K8s) | Real‑time updates, built‑in ranking functions |
| **Pinecone** | SaaS | ✅ (managed GPU) | ✅ (fully managed) | Automatic scaling, multi‑region replication |
| **Weaviate** | Open‑Source + SaaS | ✅ (GPU via modules) | ✅ (K8s) | Graph‑like schema, contextionary for semantic search |
| **FAISS (self‑hosted)** | Open‑Source | ✅ (GPU) | ❌ (manual) | Extremely fast for static datasets |

For **maximum control** and **GPU acceleration**, Milvus is a solid choice. Its `milvus-operator` automates cluster provisioning on Kubernetes, and its `Proxy` component handles routing and load balancing.

### Hands‑On: Deploying a Milvus Cluster with Docker Compose

Below is a minimal `docker-compose.yml` that spins up a **3‑node Milvus** cluster with a standalone `etcd` for metadata and a `proxy` for client connections.

```yaml
version: "3.8"
services:
  etcd:
    image: quay.io/coreos/etcd:v3.5.9
    environment:
      - ETCD_AUTO_COMPACTION_RETENTION=1
    command: ["etcd", "-advertise-client-urls=http://0.0.0.0:2379", "-listen-client-urls=http://0.0.0.0:2379"]
    ports:
      - "2379:2379"

  milvus-proxy:
    image: milvusdb/milvus-proxy:2.4.0
    depends_on:
      - etcd
    environment:
      - ETCD_ENDPOINTS=etcd:2379
    ports:
      - "19530:19530"   # gRPC
      - "9091:9091"     # HTTP

  milvus-data-0:
    image: milvusdb/milvus:2.4.0-cpu-d020
    depends_on:
      - etcd
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MILVUS_CLUSTER_ROLE=data_node
    ports:
      - "19531:19531"

  milvus-data-1:
    image: milvusdb/milvus:2.4.0-cpu-d020
    depends_on:
      - etcd
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MILVUS_CLUSTER_ROLE=data_node
    ports:
      - "19532:19532"

  milvus-data-2:
    image: milvusdb/milvus:2.4.0-cpu-d020
    depends_on:
      - etcd
    environment:
      - ETCD_ENDPOINTS=etcd:2379
      - MILVUS_CLUSTER_ROLE=data_node
    ports:
      - "19533:19533"
```

**Steps to bring up the cluster:**

```bash
docker compose up -d
# Verify the proxy health
curl -s http://localhost:9091/healthz | jq .
```

**Python client example (using `pymilvus`):**

```python
from pymilvus import Collection, connections, FieldSchema, CollectionSchema, DataType

# Connect to the proxy
connections.connect(host='localhost', port='19530')

# Define a simple collection schema
fields = [
    FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1536)
]
schema = CollectionSchema(fields, "demo collection")
collection = Collection(name="rag_docs", schema=schema)

# Insert dummy vectors
import numpy as np
vectors = np.random.random((1000, 1536)).astype(np.float32).tolist()
mr = collection.insert([vectors])
print(f"Inserted {mr.num_entities} entities")
```

This setup gives you a **distributed, fault‑tolerant vector store** ready for production workloads. For GPU acceleration, replace `milvus:2.4.0-cpu` with the `milvus:2.4.0-gpu` image and expose the appropriate CUDA devices.

---

## Parallelized Document Processing

### Batching & Asynchrony

When generating embeddings, the dominant factor is **I/O latency** (network calls to an external API) and **CPU/GPU compute** (tokenization, model inference). Combining these into **asynchronous batches** yields orders of magnitude speed‑up.

Key techniques:

* **Prefetching** – keep a buffer of documents awaiting chunking.  
* **Dynamic Batching** – group documents until a target token count (e.g., 8 k tokens) is reached, then dispatch a single API request.  
* **Back‑pressure** – use bounded queues to avoid OOM when ingestion spikes.

### Frameworks: Ray, Dask, Spark

| Framework | Strengths | Typical Use‑Case |
|-----------|-----------|------------------|
| **Ray** | Fine‑grained task parallelism, built‑in actors, easy to share objects across workers. | Real‑time embedding pipelines, model serving. |
| **Dask** | Parallel collections (`dask.bag`, `dask.dataframe`), good for out‑of‑core processing. | Large batch jobs that run nightly. |
| **Spark** | Distributed SQL and streaming, mature ecosystem. | Enterprise ETL pipelines feeding multiple downstream services. |

For the **low‑latency** scenario of an always‑on RAG service, **Ray** is often the most ergonomic choice.

### Hands‑On: Parallel Embedding with Ray and OpenAI API

First, install the dependencies:

```bash
pip install ray openai tqdm
```

Create a Ray actor that handles batched embedding calls:

```python
import os
import openai
import ray
from tqdm import tqdm
from typing import List

# Set your OpenAI key
openai.api_key = os.getenv("OPENAI_API_KEY")

@ray.remote(num_cpus=1)
class EmbedWorker:
    def __init__(self, model: str = "text-embedding-3-large", batch_size: int = 64):
        self.model = model
        self.batch_size = batch_size

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        # OpenAI's API accepts up to 8192 tokens per request; we rely on batch size for throughput
        response = openai.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [data.embedding for data in response.data]

def chunk_documents(docs: List[str], chunk_size: int = 384) -> List[str]:
    """Very naive whitespace chunker for illustration."""
    chunks = []
    for doc in docs:
        tokens = doc.split()
        for i in range(0, len(tokens), chunk_size):
            chunks.append(" ".join(tokens[i:i+chunk_size]))
    return chunks

# -------------------------------------------------
# Example driver code
# -------------------------------------------------
if __name__ == "__main__":
    # Simulate a small corpus
    raw_docs = [
        "Artificial intelligence (AI) is intelligence demonstrated by machines, " * 30,
        "Machine learning is a subset of AI that provides systems the ability to automatically learn and improve from experience " * 20,
        # Add more documents as needed
    ]

    # 1️⃣ Chunk
    chunks = chunk_documents(raw_docs, chunk_size=384)

    # 2️⃣ Create a pool of workers
    workers = [EmbedWorker.remote(batch_size=64) for _ in range(4)]

    # 3️⃣ Dispatch batches
    futures = []
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i+64]
        worker = workers[i // 64 % len(workers)]
        futures.append(worker.embed_batch.remote(batch))

    # 4️⃣ Gather results
    embeddings = []
    for batch_emb in tqdm(ray.get(futures), total=len(futures)):
        embeddings.extend(batch_emb)

    print(f"Generated {len(embeddings)} embeddings")
```

**Why this works:**

* Ray **actors** keep a warm connection to the OpenAI endpoint, avoiding repeated TLS handshakes.  
* The `batch_size` parameter aligns with the provider’s per‑request limit, maximizing throughput.  
* The driver code can be run inside a Kubernetes pod; Ray will automatically schedule workers on other nodes if the cluster is configured with `ray start --head` and `ray start --address=...`.

--- 

## End‑to‑End Pipeline Orchestration

### Workflow Engines (Airflow, Prefect, Dagster)

| Engine | Declarative vs. Imperative | Scheduler | Observability |
|--------|---------------------------|-----------|---------------|
| **Airflow** | DAG (Python) | Cron‑style, supports backfills | Rich UI, but heavy for low‑latency pipelines |
| **Prefect** | Flow (Python) | Cloud‑native or local agent | Real‑time logs, retries, dynamic mapping |
| **Dagster** | Asset‑centric | Cloud or local | Type‑checking, asset materialization view |

For a **continuous ingestion pipeline** that must react to new files in near‑real time, **Prefect** shines because it supports **event‑driven triggers** (e.g., S3 bucket notifications) and **dynamic task mapping** for variable batch sizes.

### Example: A Prefect Flow for Continuous Index Updates

```python
from prefect import flow, task, get_run_logger
from prefect.deployments import Deployment
from prefect.filesystems import S3
from typing import List
import ray
import os

# -------------------------------------------------
# Prefect infrastructure
# -------------------------------------------------
s3_block = S3(bucket_path="s3://my-company-docs", prefect_name="my-s3")
ray.init(address="auto")  # Connect to a Ray cluster

# -------------------------------------------------
# Tasks
# -------------------------------------------------
@task(retries=2, retry_delay_seconds=10)
def list_new_files(last_timestamp: str) -> List[str]:
    """List objects added after the given timestamp."""
    client = s3_block.get_client()
    objects = client.list_objects_v2(Bucket="my-company-docs", Prefix="inbox/")
    new_files = [obj["Key"] for obj in objects.get("Contents", []) if obj["LastModified"] > last_timestamp]
    return new_files

@task
def download_and_chunk(file_key: str) -> List[str]:
    logger = get_run_logger()
    client = s3_block.get_client()
    obj = client.get_object(Bucket="my-company-docs", Key=file_key)
    raw_text = obj["Body"].read().decode("utf-8")
    # Reuse the earlier chunker
    from __main__ import chunk_documents
    chunks = chunk_documents([raw_text])
    logger.info(f"Chunked {file_key} into {len(chunks)} pieces")
    return chunks

@task
def embed_and_upsert(chunks: List[str]):
    logger = get_run_logger()
    # Use the Ray worker pool defined earlier
    workers = [ray.get_actor(f"EmbedWorker_{i}") for i in range(4)]
    futures = []
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i+64]
        worker = workers[i // 64 % len(workers)]
        futures.append(worker.embed_batch.remote(batch))
    embeddings = ray.get(futures)
    # Flatten list
    flat_emb = [e for batch in embeddings for e in batch]

    # Upsert into Milvus
    from pymilvus import connections, Collection
    connections.connect(host="localhost", port="19530")
    coll = Collection("rag_docs")
    ids = coll.insert([flat_emb])
    logger.info(f"Upserted {len(flat_emb)} vectors")
    return ids

# -------------------------------------------------
# Flow definition
# -------------------------------------------------
@flow(name="continuous-rag-indexer")
def rag_indexer(last_timestamp: str = "1970-01-01T00:00:00Z"):
    new_files = list_new_files(last_timestamp)
    for f in new_files:
        chunks = download_and_chunk(f)
        embed_and_upsert(chunks)

# -------------------------------------------------
# Deploy (run once for demo)
# -------------------------------------------------
if __name__ == "__main__":
    rag_indexer()
```

**Key points:**

* **Eventual Consistency** – The flow can be scheduled every minute or triggered by S3 events.  
* **Fault Tolerance** – Prefect retries on transient failures (e.g., network hiccups).  
* **Scalability** – The heavy lifting (embedding) is delegated to Ray, which can elastically add workers as load grows.

---

## Performance Optimizations & Best Practices

### Index Compression & Quantization

* **Product Quantization (PQ)** – reduces storage from 4 bytes per dimension to 1 byte with modest recall loss.  
* **Scalar Quantization (SQ)** – 8‑bit or 4‑bit integer encodings; supported natively by Milvus and FAISS.  
* **HNSW with IVF‑PQ** – Combine coarse quantizer (IVF) for pruning and HNSW for graph‑based refinement.  

**Rule of thumb:** For a corpus > 10 M vectors, start with `IVF=4096, PQ=8` and evaluate recall@10. Adjust `nlist` and `nprobe` to trade latency for accuracy.

### GPU‑Accelerated Search

* **Milvus GPU‑IVF** – Offloads the distance computation to the GPU, delivering sub‑10 ms latency for 1 M‑scale indexes.  
* **FAISS `IndexFlatIP` on GPU** – Useful for small, high‑accuracy workloads where exact search is required.  

**Tip:** Keep the GPU memory under 80 % utilization; oversubscription leads to page‑swapping and jitter.

### Caching & Warm‑up Strategies

* **Result Cache** – Store the top‑k IDs for frequently asked queries (e.g., using Redis with TTL).  
* **Embedding Cache** – When processing new documents, check if a chunk already exists (hash‑based deduplication) to avoid re‑embedding.  
* **Warm‑up Queries** – Issue a small batch of representative queries after each index rebuild to prime the GPU caches.

### Latency Monitoring & Alerting

1. **Prometheus Exporters** – Milvus provides `/metrics`; instrument your embedding workers with `prometheus_client`.  
2. **SLO Dashboard** – Track 99th‑percentile latency for `search` and `embed` calls.  
3. **Alert Rules** – Fire an alert if `search_latency_seconds{quantile="0.99"} > 0.5` for more than 5 minutes.

---

## Real‑World Case Study: Enterprise Knowledge‑Base Search

**Background**  
A multinational consulting firm stored 12 TB of PDFs, PowerPoints, and internal wiki pages. Their analysts needed a conversational assistant that could answer policy questions with citations within 300 ms.

**Architecture Overview**

| Component | Technology | Rationale |
|-----------|------------|----------|
| Document Store | Amazon S3 (versioned) | Scalable, immutable backing store |
| Ingestion & Chunking | Apache Tika + LangChain splitters (384‑token) | Handles many file formats |
| Embedding Service | Ray cluster + `sentence-transformers` `all-MiniLM-L6-v2` on A100 GPUs | Low cost, high throughput (≈ 25 k embeddings/s) |
| Vector Index | Milvus 2.4 (GPU‑IVF‑HNSW) with 8‑bit SQ | 150 M vectors, < 10 ms latency |
| Cache | Redis (TTL = 30 s) for recent queries | Reduces repeat load |
| Retriever | Milvus `search` API with `nprobe=32` | Balanced accuracy/latency |
| LLM | OpenAI `gpt‑4‑turbo` via Azure OpenAI Service | Enterprise‑grade compliance |
| Orchestrator | Prefect Cloud + Kubernetes CronJobs | Autoscaling and observability |

**Performance Numbers (average over 2 weeks)**

| Metric | Value |
|--------|-------|
| Ingestion throughput | 1.2 M documents / hour |
| Embedding latency (batch of 64) | 0.18 s |
| Vector search latency (top‑5) | 7 ms |
| End‑to‑end query latency (including LLM) | 280 ms |
| 99th‑percentile latency | 420 ms (still within SLA) |
| Cost (GPU + cloud) | ≈ $2,400 / month |

**Key Lessons Learned**

1. **GPU‑enabled Milvus reduced search latency by ~70 % vs. CPU‑only IVF‑PQ.**  
2. **Ray’s actor model allowed zero‑downtime rolling upgrades of the embedding service.**  
3. **Dynamic `nprobe` tuning based on query complexity (short vs. long) saved compute without hurting recall.**  
4. **Separating citation generation from answer generation (two‑stage LLM calls) improved factual accuracy by 12 %.**

---

## Testing, Monitoring, and Autoscaling

### Load Testing with Locust

```python
# locustfile.py
from locust import HttpUser, task, between

class RAGUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def ask_question(self):
        self.client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": "What is the company policy on remote work?"}]},
            headers={"Authorization": "Bearer YOUR_TOKEN"},
        )
```

Run with:

```bash
locust -f locustfile.py --host http://my-rag-api.internal --users 200 --spawn-rate 20
```

Observe latency graphs and identify bottlenecks (e.g., GPU saturation, network I/O).

### Autoscaling Policies

* **Kubernetes HPA** – Scale the Ray worker pods based on `CPUUtilization` > 70 % or a custom metric like `ray_worker_queue_length`.  
* **Milvus Autoscaler** – The Milvus operator can adjust the number of `dataNode` replicas; configure a `HorizontalPodAutoscaler` for it as well.  
* **Prefect Concurrency Limits** – Set a maximum number of concurrent flows to protect downstream services.

### Observability Stack

* **Metrics** – Prometheus + Grafana dashboards for `search_latency`, `embed_batch_time`, `ray_worker_cpu`.  
* **Logs** – Centralized ELK/EFK stack; tag logs with request IDs for end‑to‑end tracing.  
* **Tracing** – OpenTelemetry instrumentation on the API gateway, embedding workers, and Milvus client.

---

## Conclusion

Building a **high‑performance RAG pipeline** is no longer a research experiment; it is an engineering discipline that blends **distributed systems**, **GPU‑accelerated similarity search**, and **parallel data processing**. By:

1. **Deploying a distributed vector index** (Milvus, Vespa, or a managed SaaS offering) with appropriate sharding, replication, and GPU acceleration;  
2. **Parallelizing every step of document ingestion**—chunking, embedding, and upserting—using frameworks like Ray or Dask;  
3. **Orchestrating the workflow** with a modern engine (Prefect, Airflow, Dagster) that supports dynamic scaling and observability;  

you can meet demanding enterprise SLAs: sub‑500 ms query latency, continuous freshness, and the ability to index tens of millions of passages.

The code snippets and architectural patterns presented here are deliberately **technology‑agnostic**: swap OpenAI embeddings for a local model, replace Milvus with Pinecone, or run the whole stack on your private cloud. The underlying principles—**horizontal scaling, batching, caching, and rigorous monitoring**—remain the same.

Start with a small prototype, measure recall and latency, then iteratively introduce the distributed components described above. With disciplined engineering, your RAG service will evolve from a proof‑of‑concept to a robust, production‑grade knowledge assistant capable of powering global enterprises.

---

## Resources
- [Milvus Documentation – Distributed Vector Database](https://milvus.io/docs)  
- [Ray Distributed Computing – Official Site](https://ray.io)  
- [Prefect Workflow Orchestration – Guides & API Reference](https://www.prefect.io)  
- [FAISS – Efficient Similarity Search Library (GitHub)](https://github.com/facebookresearch/faiss)  
- [LangChain – Chunking & RAG Utilities](https://python.langchain.com)  
- [OpenAI Embedding API Reference](https://platform.openai.com/docs/guides/embeddings)  
- [Vespa – Real‑Time Vector Search Engine](https://vespa.ai)  
- [Prometheus – Monitoring & Alerting Toolkit](https://prometheus.io)  
- [Locust – Scalable Load Testing](https://locust.io)  