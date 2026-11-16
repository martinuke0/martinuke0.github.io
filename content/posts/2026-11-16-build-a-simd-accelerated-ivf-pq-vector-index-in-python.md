---
title: "Build a SIMD-Accelerated IVF-PQ Vector Index in Python"
date: "2026-11-16T12:01:00.990"
draft: false
tags: ["Vector Databases", "Python", "SIMD", "Machine Learning", "Systems Engineering"]
description: "Learn how to build an Inverted File Index with Product Quantization and SIMD acceleration in Python to demonstrate high-performance systems skills."
summary: "A comprehensive guide to building a production-style vector index from scratch, focusing on memory efficiency and computational speed."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-16-build-a-simd-accelerated-ivf-pq-vector-index-in-python.svg"
  alt: "A conceptual diagram showing vector quantization and inverted file indexing."
  caption: ""
  relative: false
---

> **TL;DR** — Build a high-performance vector search engine using Inverted File Indexing (IVF) and Product Quantization (PQ). This project demonstrates your ability to handle memory constraints, implement lossy compression, and leverage hardware acceleration via NumPy's SIMD backends.

If you want to stand out in a sea of "Titanic dataset" or "Basic CRUD app" portfolios, you need a project that screams *systems thinking*. In the current era of LLMs and RAG (Retrieval-Augmented Generation), vector databases like Milvus, Pinecone, and Weaviate are the backbone of AI infrastructure. However, most engineers only know how to call their APIs.

Building a simplified version of an IVF-PQ index—the same architecture that powers the core of [FAISS (Facebook AI Similarity Search)](https://github.com/facebookresearch/faiss)—proves you understand the trade-off between precision, memory, and latency. This guide will walk you through implementing this in Python, using NumPy to ensure we hit the underlying C/SIMD optimizations.

## Why This Project Stands Out on a CV

Hiring managers for Backend, ML Platform, or Infrastructure roles look for "mechanical sympathy"—an understanding of how software interacts with hardware. This project signals several high-value competencies:

*   **Algorithmic Complexity:** You aren't just using a library; you are implementing K-Means clustering for IVF and quantization for PQ.
*   **Memory Management:** By implementing Product Quantization, you demonstrate an understanding of how to compress high-dimensional embeddings to fit in RAM.
*   **Performance Optimization:** Using NumPy's vectorized operations shows you know how to avoid Python's GIL and leverage SIMD (Single Instruction, Multiple Data) instructions for distance calculations.
*   **Domain Expertise:** It positions you as someone who understands the "plumbing" of modern AI, making you a prime candidate for LLMOps or Vector DB engineering roles.

## Architecture Overview

The IVF-PQ architecture is designed to solve the "curse of dimensionality." A brute-force search (Flat index) takes $O(N \cdot D)$ time, which is untenable for millions of vectors. We optimize this through two primary mechanisms:

*   **IVF (Inverted File Index):** This is the "coarse quantizer." We partition the vector space into $K$ Voronoi cells using K-Means. At query time, we only search the vectors in the cells closest to the query vector, reducing the search space from $N$ to $N/K$.
*   **PQ (Product Quantization):** This is the "fine quantizer." Instead of storing a 128-float vector (512 bytes), we split the vector into $M$ sub-vectors. Each sub-vector is quantized to a centroid ID (usually 1 byte). This compresses the vector by a factor of 16x to 64x.
*   **Asymmetric Distance Computation (ADC):** This is the "magic" part. We don't decompress the vectors to calculate distance. Instead, we precompute a lookup table of distances between the query sub-vectors and the PQ centroids, then sum these values.

**The Data Flow:**
`Input Vectors` $\rightarrow$ `K-Means (IVF)` $\rightarrow$ `Sub-space Quantization (PQ)` $\rightarrow$ `Inverted Lists` $\rightarrow$ `Query (ADC)` $\rightarrow$ `Top-K Results`.

## Building It Step by Step

We will use `numpy` for the heavy lifting. Ensure you have it installed: `pip install numpy scikit-learn`.

### Step 1: The Coarse Quantizer (IVF)
The first step is to cluster the data. We use `KMeans` from `scikit-learn` to define our Voronoi cells.

```python
import numpy as np
from sklearn.cluster import KMeans

class IVFIndex:
    def __init__(self, n_list=100):
        self.n_list = n_list
        self.centroids = None
        self.buckets = {}

    def train(self, data):
        # Cluster the data into n_list centroids
        kmeans = KMeans(n_clusters=self.n_list, n_init=10, random_state=42)
        kmeans.fit(data)
        self.centroids = kmeans.cluster_centers_
        
        # Assign each vector to the nearest centroid
        labels = kmeans.predict(data)
        for idx, label in enumerate(labels):
            if label not in self.buckets:
                self.buckets[label] = []
            self.buckets[label].append(idx)
```

### Step 2: Product Quantization (PQ)
Now we implement the compression. We split a vector of dimension $D$ into $M$ segments of size $D/M$. For each segment, we create a small codebook of 256 centroids.

```python
class PQEncoder:
    def __init__(self, d, m=8):
        self.d = d  # Total dimension
        self.m = m  # Number of sub-vectors
        self.sub_d = d // m
        self.codebooks = [] # List of centroids for each sub-space

    def train(self, data):
        for i in range(self.m):
            # Extract the i-th sub-vector from all data points
            start, end = i * self.sub_d, (i + 1) * self.sub_d
            sub_vectors = data[:, start:end]
            
            # Create 256 centroids for this sub-space
            kmeans = KMeans(n_clusters=256, n_init=10, random_state=42)
            kmeans.fit(sub_vectors)
            self.codebooks.append(kmeans.cluster_centers_)
        
        self.codebooks = np.array(self.codebooks) # Shape: (m, 256, sub_d)

    def encode(self, vector):
        codes = []
        for i in range(self.m):
            start, end = i * self.sub_d, (i + 1) * self.sub_d
            sub_vec = vector[start:end]
            
            # Find nearest centroid in the i-th codebook
            distances = np.linalg.norm(self.codebooks[i] - sub_vec, axis=1)
            codes.append(np.argmin(distances))
        return np.array(codes, dtype=np.uint8)
```

### Step 3: The Integrated IVF-PQ Index
We now combine these. The `IVFIndex` will store the `PQ` codes instead of the raw vectors.

```python
class IVFPQIndex:
    def __init__(self, d, n_list=100, m=8):
        self.d = d
        self.ivf = IVFIndex(n_list=n_list)
        self.pq = PQEncoder(d, m=m)
        self.data_codes = {} # bucket_id -> list of PQ codes

    def fit(self, data):
        # 1. Train IVF centroids
        self.ivf.train(data)
        # 2. Train PQ codebooks
        self.pq.train(data)
        
        # 3. Quantize and store
        labels = np.argmin(np.linalg.norm(data[:, np.newaxis] - self.ivf.centroids, axis=2), axis=1)
        for idx, label in enumerate(labels):
            code = self.pq.encode(data[idx])
            if label not in self.data_codes:
                self.data_codes[label] = []
            self.data_codes[label].append(code)
        
        # Convert bucket lists to numpy arrays for SIMD speed
        for label in self.data_codes:
            self.data_codes[label] = np.array(self.data_codes[label])

    def search(self, query, k=5, nprobe=1):
        # 1. Find the nprobe closest IVF buckets
        dist_to_centroids = np.linalg.norm(self.ivf.centroids - query, axis=1)
        closest_buckets = np.argsort(dist_to_centroids)[:nprobe]
        
        # 2. Asymmetric Distance Computation (ADC)
        # Precompute lookup table: (m, 256)
        # This is where SIMD happens via NumPy broadcasting
        lookup_table = np.zeros((self.pq.m, 256))
        for i in range(self.pq.m):
            start, end = i * self.pq.sub_d, (i + 1) * self.pq.sub_d
            sub_query = query[start:end]
            lookup_table[i] = np.linalg.norm(self.pq.codebooks[i] - sub_query, axis=1)
        
        best_scores = []
        for bucket_id in closest_buckets:
            if bucket_id not in self.data_codes: continue
            
            codes = self.data_codes[bucket_id] # Shape: (num_vecs, m)
            # Use advanced indexing to sum distances from lookup table
            # This replaces a Python loop with a vectorized C operation
            distances = np.sum(lookup_table[np.arange(self.pq.m), codes], axis=1)
            
            # Store (distance, original_index_relative_to_bucket)
            # For simplicity, we just store the distance here
            best_scores.extend(distances)
            
        return np.argsort(best_scores)[:k]
```

## Running and Testing It

To prove this works, you should generate a synthetic dataset of high-dimensional vectors and compare the IVF-PQ results against a brute-force search.

```python
if __name__ == "__main__":
    # Hyperparameters
    D = 128       # Vector dimension
    N = 10000     # Number of vectors
    M = 8         # PQ segments
    N_LIST = 50   # IVF clusters
    
    # Generate random data
    data = np.random.random((N, D)).astype(np.float32)
    query = np.random.random((D,)).astype(np.float32)
    
    # Initialize and fit index
    index = IVFPQIndex(d=D, n_list=N_LIST, m=M)
    index.fit(data)
    
    # Search
    results = index.search(query, k=5, nprobe=2)
    print(f"Top 5 nearest neighbor indices: {results}")
    
    # Brute force for validation
    bf_dist = np.linalg.norm(data - query, axis=1)
    print(f"Brute force top 5: {np.argsort(bf_dist)[:5]}")
```

**How to validate performance:**
1.  **Memory Check:** Compare `data.nbytes` (raw) with the size of the `data_codes` dictionary. You should see a massive reduction.
2.  **Latency Check:** Use `time.time()` to compare the `search` method against a full `np.linalg.norm` over the entire dataset.
3.  **Recall Check:** Calculate how many of the Top-10 brute-force results appear in your IVF-PQ Top-10. This is your "Recall@10" metric.

## Extending It: Your Roadmap to Senior-Level

A working prototype is a "Junior" project. To make this a "Senior" project, you need to address production concerns. Implement these upgrades one by one:

1.  **Disk Persistence (Memory Mapping):** Use `numpy.memmap` to store the inverted lists on disk. *Reason: Production indices are too large for RAM.*
2.  **Multi-threaded Querying:** Use `concurrent.futures` to search multiple IVF buckets in parallel. *Reason: Reduces query latency on multi-core CPUs.*
3.  **SIMD via Numba:** Replace the ADC loop with a `@njit(parallel=True)` decorated function from the [Numba library](https://numba.pydata.org/). *Reason: Bypasses the Python interpreter entirely for near-C speeds.*
4.  **Dynamic Updates:** Implement a method to add new vectors to the index without retraining the entire K-Means model. *Reason: Real-world data is streaming, not static.*
5.  **Benchmarking Suite:** Create a script that plots "Recall vs. Latency" as you vary `nprobe`. *Reason: Demonstrates you understand the fundamental trade-offs of approximate nearest neighbor (ANN) search.*
6.  **Integration with FastAPI:** Wrap the index in a REST API that accepts a vector and returns the Top-K IDs. *Reason: Shows you can build a deployable microservice.*

## Key Takeaways

*   **IVF** reduces the search space by clustering vectors into Voronoi cells, allowing us to skip the vast majority of the dataset.
*   **Product Quantization** compresses vectors by splitting them into sub-spaces and storing only the index of the nearest centroid.
*   **Asymmetric Distance Computation (ADC)** allows us to calculate distances between a raw query and compressed vectors using a precomputed lookup table.
*   **Vectorization** is the key to performance in Python; using NumPy's broadcasting and indexing is what enables SIMD acceleration.
*   **Approximate Nearest Neighbor (ANN)** search is always a trade-off between speed, memory, and accuracy (recall).

## Further Reading

*   [The original PQ Paper: Product Quantization for Nearest Neighbor Search](https://hal.inria.fr/hal-00541461) — The foundational text for PQ.
*   [FAISS Documentation](https://faiss.ai/) — The industry standard implementation; study their index types (IVFFlat, IVF PQ).
*   [The "HNSW" Paper](https://arxiv.org/abs/1603.09320) — To understand the alternative to IVF (Graph-based indexing).
*   [NumPy User Guide on Broadcasting](https://numpy.org/doc/stable/user/basics.broadcasting.html) — Essential for mastering the SIMD-like behavior used in the ADC step.