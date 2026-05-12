---
title: "Implementing Vector Search at Scale: Optimizing HNSW Index Construction for High Dimensional Embeddings"
date: "2026-05-12T17:00:40.282"
draft: false
tags: ["vector-search","hnsw","embeddings","scalable-ml","performance"]
description: "Learn how to build and tune HNSW indexes for billions of high‑dimensional vectors, covering memory, parallelism, and latency trade‑offs."
summary: "A deep dive into scaling HNSW index construction, with practical code, hardware tips, and best‑practice recommendations."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-12-implementing-vector-search-at-scale-optimizing-hnsw-index-construction-for-high-dimensional-embeddings.svg"
  alt: "Illustration of a high‑dimensional vector space with a graph structure."
  caption: ""
  relative: false
---

> **TL;DR** — HNSW (Hierarchical Navigable Small World) graphs can serve billions of high‑dimensional vectors if you parallelize construction, carefully manage memory, and fine‑tune parameters like `M` and `ef_construction`. The post walks through the algorithmic levers, Python code snippets, and hardware considerations that make large‑scale vector search practical.

Vector search has moved from niche research to the backbone of recommendation engines, semantic search, and anomaly detection. While approximate nearest neighbor (ANN) libraries such as **hnswlib**, **FAISS**, and **Milvus** make querying fast, constructing the index at scale remains a bottleneck, especially when embeddings live in 256‑ to 1,024‑dimensional space. This article unpacks the inner workings of HNSW, identifies the scaling challenges, and presents a toolbox of optimizations—both algorithmic and systems‑level—that let you index tens or hundreds of billions of vectors without blowing up memory or wall‑clock time.

## Understanding HNSW Fundamentals

### What Makes HNSW Fast?

HNSW builds a multi‑layer navigable small‑world graph where each node (vector) connects to a bounded number of neighbors (`M`). The top layer contains a sparse subset of nodes, providing a “shortcut” for long‑range navigation, while lower layers hold denser connections for fine‑grained local search. Queries start at the top layer, descend greedily, and finish with a best‑first search on the bottom layer using an `ef` (exploration factor) parameter.

Key properties:

- **Logarithmic search complexity**: Expected `O(log N)` where `N` is the number of indexed vectors.
- **Deterministic recall**: With proper `M` and `ef_construction`, HNSW can achieve > 99 % recall on many benchmarks.
- **Incremental updates**: New vectors can be inserted without rebuilding the entire graph.

### Core Parameters

| Parameter          | Typical Range | Effect                                                                 |
|--------------------|---------------|------------------------------------------------------------------------|
| `M`                | 5 – 48        | Controls max connections per node; higher → better recall, more RAM. |
| `ef_construction` | 100 – 500     | Exploration factor during build; larger values improve graph quality.|
| `ef` (query)       | 10 – 200      | Trade‑off between latency and recall at query time.                   |
| `dim`              | 64 – 2048     | Dimensionality of embeddings; higher dims increase distance computation cost.|

Understanding how these knobs interact is essential before diving into scaling techniques.

## Challenges of Scaling to High Dimensional Embeddings

### Memory Footprint

Each edge stores a 32‑bit integer identifier and optionally a distance value. For `N` vectors, the memory consumption roughly follows:

```
memory ≈ N * M * (4 bytes id + 4 bytes distance) + N * dim * 4 bytes (vector data)
```

With `N = 100 B`, `M = 32`, `dim = 512`, the raw vector storage alone exceeds 200 GB, and the graph edges add another ~25 GB. This pushes the limits of a single node’s RAM.

### Construction Time

The naive, single‑threaded algorithm visits each new point, performs a greedy search down the layers, and then updates neighbor lists—a process that is `O(N log N)`. For billions of points, wall‑clock time quickly becomes unacceptable.

### I/O Bottlenecks

Reading embeddings from disk, especially when stored in compressed formats like Parquet or protobuf, can dominate total build time. Random access patterns during neighbor updates further stress storage subsystems.

### High Dimensionality Effects

- **Curse of dimensionality**: Distance distributions become concentrated, making neighbor discrimination harder.
- **CPU cache pressure**: Computing inner products or L2 distances over 1,024‑dim vectors stresses cache lines, reducing throughput.

## Optimizing Index Construction

Below we outline a layered approach: algorithmic refinements, parallel execution, memory‑aware data layouts, and hardware‑accelerated tricks.

### 1. Algorithmic Tweaks

#### a. Adaptive `M` per Layer

Instead of a static `M`, allocate a larger `M_top` for upper layers (e.g., 64) and a smaller `M_bottom` for the base layer (e.g., 24). The sparse top layers benefit from more connections, improving long‑range navigation without inflating the overall edge count.

```python
def compute_layer_M(level, max_level, M_bottom=24, M_top=64):
    """Linearly interpolate M between bottom and top layers."""
    if level == max_level:
        return M_top
    ratio = level / max_level
    return int(M_bottom + ratio * (M_top - M_bottom))
```

#### b. Pre‑filtering with Product Quantization (PQ)

Before inserting a vector into the HNSW graph, run a cheap PQ‑based coarse quantizer to prune unlikely neighbors. This reduces the number of distance calculations per insertion.

```python
import faiss
quantizer = faiss.IndexFlatL2(dim)          # exact coarse quantizer
pq = faiss.IndexIVFPQ(quantizer, dim, 1024, 16, 8)  # 16‑subquantizers, 8 bits each
pq.train(embeddings)                        # train on a sample
pq.add(embeddings)                          # add to coarse index
```

During HNSW insertion, query `pq` for the top‑k coarse centroids and only consider vectors belonging to those cells.

#### c. Batch Insertion with Re‑balancing

Insert vectors in batches (e.g., 10 k at a time). After each batch, run a lightweight re‑balancing pass that re‑optimizes neighbor lists for the newly added points, mitigating the “early‑point bias” where early vectors get more connections.

```python
def batch_insert(hnsw_index, batch_vectors, ef=200):
    hnsw_index.add_items(batch_vectors, ef=ef)
    # Re‑balance: re‑search each new point with higher ef
    for i in range(len(batch_vectors)):
        hnsw_index.refresh_item(i, ef=500)
```

### 2. Parallel Construction

#### a. Multi‑Threaded Greedy Search

Most HNSW libraries already expose a `num_threads` parameter. However, the default per‑insertion parallelism may be insufficient. A custom thread pool that processes *independent* insertions in parallel can yield near‑linear speed‑up because each insertion only reads the current graph and writes a small set of edges.

```python
import concurrent.futures, hnswlib

def parallel_build(embeddings, M=32, ef_con=200, num_threads=32):
    index = hnswlib.Index(space='l2', dim=embeddings.shape[1])
    index.init_index(max_elements=embeddings.shape[0], ef_construction=ef_con, M=M)
    index.set_num_threads(num_threads)

    # Split into chunks
    chunk_size = len(embeddings) // num_threads
    chunks = [embeddings[i:i+chunk_size] for i in range(0, len(embeddings), chunk_size)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(index.add_items, chunk) for chunk in chunks]
        concurrent.futures.wait(futures)
    return index
```

#### b. Distributed Sharding

When a single node cannot hold the full graph, partition the dataset into *shards* (e.g., by hash of vector IDs). Build an HNSW index per shard on separate workers, then combine them via a *hierarchical* overlay:

1. **Local shard index** – optimized for low latency within the shard.
2. **Global routing layer** – a small HNSW (few million vectors) that stores **centroids** of each shard.

Queries first hit the global layer to identify the most promising shards, then descend into the local indexes. This approach is used by production systems like **Milvus** and **Vespa**.

### 3. Memory‑Aware Data Layout

#### a. Float16 Storage

If your downstream application tolerates a small loss in precision, store vectors as `float16`. This halves the memory for raw embeddings, reducing pressure on RAM and allowing larger batches during construction.

```python
embeddings_fp16 = embeddings.astype('float16')
```

Be aware that distance calculations must cast back to `float32` to avoid overflow:

```python
def l2_distance(a, b):
    return ((a.astype('float32') - b.astype('float32')) ** 2).sum()
```

#### b. Memory‑Mapped Files

For datasets that exceed RAM, keep the raw vectors on disk using `numpy.memmap`. HNSW only needs to read vectors when evaluating distances, which can be done lazily.

```python
import numpy as np
vec_memmap = np.memmap('embeddings.dat', dtype='float32', mode='r', shape=(N, dim))
```

Combine memmap with **prefetching**: load the next batch of vectors into a RAM cache while the current batch is being processed.

#### c. Edge Compression

Store edge IDs as 24‑bit integers (3 bytes) instead of 32‑bit, using a custom packed struct. Libraries such as **hnswlib** expose a `custom_index` hook where you can replace the default `std::vector<int>` with a compressed container. The memory savings are modest but cumulative at billions of edges.

### 4. Hardware Acceleration

#### a. SIMD Vectorization

Modern CPUs support AVX‑512 or NEON instructions that can compute multiple dot products in parallel. Compile **hnswlib** with `-march=native -O3` to enable auto‑vectorization. For Python users, the `faiss` library already leverages SIMD for distance calculations.

```bash
# Build hnswlib with maximum SIMD support
git clone https://github.com/nmslib/hnswlib.git
cd hnswlib
CXXFLAGS="-O3 -march=native" python setup.py install
```

#### b. GPU‑Powered Batch Distance

When batch inserting, offload the distance matrix to the GPU using **torch** or **cupy**. The following snippet shows a PyTorch implementation that computes distances for a batch of 10 k vectors against the current graph’s candidate set.

```python
import torch

def gpu_batch_distances(batch, candidates):
    # batch: (B, dim), candidates: (C, dim)
    batch_gpu = batch.to('cuda')
    cand_gpu = candidates.to('cuda')
    # (B, C) distance matrix
    dists = torch.cdist(batch_gpu, cand_gpu, p=2)
    return dists.cpu()
```

Integrate this into the insertion pipeline to replace the CPU‑bound distance loop, achieving up to 5× speed‑up on an RTX 4090.

#### c. NVMe Direct I/O

If you store embeddings on an NVMe SSD, enable *direct I/O* (O_DIRECT) to bypass the OS page cache. This reduces memory pressure and improves sequential read throughput, which is crucial when streaming billions of vectors.

```bash
# Example using Linux dd with direct I/O
dd if=embeddings.bin of=/dev/null bs=1M iflag=direct
```

### 5. Parameter Tuning Workflow

A systematic approach to find the sweet spot between recall, latency, and memory:

1. **Sample 1 % of the data** (preserve dimensionality distribution).
2. **Grid search** over `M` ∈ {12, 24, 32, 48} and `ef_construction` ∈ {100, 200, 400}.
3. **Measure**:
   - Construction time (`time.perf_counter()`).
   - RAM usage (`psutil.Process().memory_info().rss`).
   - Recall on a held‑out query set (`index.knn_query` vs. brute‑force).
4. **Select** the configuration that meets your SLA (e.g., > 95 % recall, < 200 ms query latency, ≤ 1.2× RAM of raw vectors).

Automating this loop can be done with **Optuna** or **Ray Tune**, which parallelize trials across multiple nodes.

```python
import optuna

def objective(trial):
    M = trial.suggest_categorical('M', [12, 24, 32, 48])
    ef = trial.suggest_int('ef_construction', 100, 400, step=100)
    # Build a small index and evaluate
    idx = build_index(sample, M=M, ef_construction=ef)
    recall = evaluate_recall(idx, queries, k=10)
    return -recall  # maximize recall

study = optuna.create_study(direction='minimize')
study.optimize(objective, n_trials=12)
```

## Key Takeaways

- **Layer‑aware `M`** reduces edge count while preserving long‑range navigation quality.
- **Batch insertion + re‑balancing** mitigates early‑point bias and improves overall recall.
- **Parallel and distributed construction** (thread pools, sharding) is essential for billions of vectors.
- **Memory‑saving tricks** (float16, memmap, edge compression) keep RAM usage within a single‑node budget.
- **GPU‑accelerated distance computation** and **SIMD‑optimized builds** cut wall‑clock time dramatically.
- **Systematic parameter tuning** using a sampled subset and automated search yields the best trade‑offs for your workload.

## Further Reading

- [hnswlib GitHub repository](https://github.com/nmslib/hnswlib) – official Python/C++ implementation and benchmarks.  
- [FAISS documentation – IndexIVFPQ](https://github.com/facebookresearch/faiss/wiki/IndexIVFPQ) – details on product quantization for coarse pre‑filtering.  
- [Milvus vector database architecture](https://milvus.io/docs/v2.2.x/architecture_overview.md) – real‑world sharding and hierarchical routing examples.  
- [Efficient Similarity Search for High‑Dimensional Data (paper)](https://arxiv.org/abs/1603.09320) – original HNSW algorithm description.  
- [Optuna hyperparameter optimization framework](https://optuna.org) – automates the search for optimal HNSW parameters.