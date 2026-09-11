---
title: "Building an IVF-PQ Vector Index from Scratch in Pure Python"
date: "2026-09-11T21:00:43.693"
draft: false
tags: ["vector databases", "python", "machine learning", "systems engineering", "product quantization"]
description: "A hands-on guide to building an IVF-PQ vector index from scratch in pure Python, demonstrating real systems engineering skills for your portfolio."
summary: "Learn how to build an IVF-PQ vector index from scratch using pure Python, implementing k-means clustering and product quantization to achieve scalable similarity search."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-building-an-ivf-pq-vector-index-from-scratch-in-pure-python.svg"
  alt: "Python code and mathematical formulas representing vector indexing."
  caption: ""
  relative: false
---

> **TL;DR** — Build a production-grade IVF-PQ vector index from scratch in pure Python to demonstrate mastery of search algorithms, distributed systems concepts, and memory optimization. This project replaces toy linear scans with coarse-to-fine search, signaling to hiring managers that you understand the engineering trade-offs behind modern vector databases like Milvus and Pinecone.

Vector search is the backbone of modern AI applications, from semantic retrieval to recommendation engines. While calling an API through a managed service like Pinecone or Weaviate is trivial, understanding the underlying mechanics of how billions of vectors are searched in milliseconds is what separates a software engineer from a systems engineer. Building an IVF-PQ (Inverted File with Product Quantization) index from scratch is the ultimate portfolio project. It proves you can bridge the gap between machine learning theory and low-level systems optimization, handling memory constraints, algorithmic complexity, and approximate search logic.

## Why This Project Stands Out on a CV

Hiring managers for ML Infrastructure and Search Engineering roles receive hundreds of resumes featuring standard CRUD applications and simple Flask APIs. An IVF-PQ implementation immediately signals a different caliber of engineer. 

*   **Systems Architecture & Memory Management:** Implementing Product Quantization requires you to compress high-dimensional vectors into compact byte codes. This forces you to think about memory alignment, cache locality, and the trade-off between RAM usage and recall accuracy.
*   **Algorithmic Complexity:** A brute-force search is O(N). By implementing an Inverted File index, you are reducing this complexity to O(log N) or better, demonstrating a deep understanding of how data structures dictate system performance.
*   **ML-to-Production Bridging:** K-means clustering is a standard ML algorithm, but training it to partition a dataset for search routing requires a production mindset. You must handle edge cases, empty clusters, and residual calculations without relying on high-level framework abstractions.
*   **Signals for Senior Roles:** This project demonstrates that you can own a feature from mathematical formulation to optimized code execution, a critical skill for senior backend and infrastructure roles.

## Architecture Overview

The IVF-PQ index operates on a two-stage compression and search paradigm. To build it, you need to understand how data flows from ingestion to query resolution. 

```text
           [Ingestion Pipeline]
                  |
                  v
      [K-Means Clustering (Coarse Quantizer)]
                  |
                  v
      [Residual Calculation & Subspace Splitting]
                  |
                  v
      [Product Quantization (Fine Quantizer)]
                  |
                  v
      [Inverted File Index (Cluster -> PQ Codes)]
```

When a query arrives, the architecture reverses this flow using a coarse-to-fine search strategy:

```text
           [Query Vector]
                  |
                  v
      [Coarse Search: Find nearest clusters]
                  |
                  v
      [Residual Calculation: Query - Cluster Centroid]
                  |
                  v
      [PQ Distance Table Lookup: Asymmetric Distance Calculation]
                  |
                  v
      [Re-ranking & Top-K Results]
```

The core components are:
1.  **Coarse Quantizer:** A K-Means model that partitions the dataset into `n_clusters`. It routes the query to a small subset of relevant clusters rather than scanning the entire dataset.
2.  **Residual Calculator:** Computes the difference between the data points and their assigned cluster centroids. Product Quantization works best on residuals, which are typically lower-variance than the raw data.
3.  **Product Quantizer:** Splits the residual vectors into `m` subspaces and trains a separate K-Means model for each subspace. It replaces each subspace with a single byte (a centroid ID), achieving massive compression.
4.  **Coarse-to-Fine Searcher:** Executes the asymmetric distance calculation (ADC). It computes the distance between the query and the subspace centroids, then uses the pre-computed codebooks to quickly estimate the distance to the stored vectors.

## Building It Step by Step

We will implement the core logic using pure Python and NumPy. No external vector database libraries will be used; we are building the engine itself.

### Step 1: Data Generation and Preprocessing
First, generate a synthetic high-dimensional dataset and normalize it. Normalization ensures that the K-Means algorithm converges properly based on angular similarity rather than magnitude.

```python
import numpy as np

def generate_data(n_samples=10000, n_dims=128):
    # Generate random vectors
    data = np.random.rand(n_samples, n_dims).astype(np.float32)
    # L2 Normalize
    norms = np.linalg.norm(data, axis=1, keepdims=True)
    return data / norms

vectors = generate_data()
```

### Step 2: The Coarse Quantizer (K-Means Clustering)
We implement a standard K-Means algorithm to partition the vectors into clusters. This serves as the coarse quantizer. We must handle empty clusters by reinitializing them to the point furthest from the current centroid.

```python
class KMeansCoarseQuantizer:
    def __init__(self, n_clusters=100, max_iters=20):
        self.n_clusters = n_clusters
        self.max_iters = max_iters
        self.centroids = None

    def fit(self, data):
        # Initialize centroids using K-Means++ logic for better convergence
        centroids = [data[np.random.randint(len(data))]]
        for _ in range(1, self.n_clusters):
            dists = np.min(np.linalg.norm(data[:, np.newaxis, :] - centroids, axis=2)**2, axis=1)
            probs = dists / dists.sum()
            cumulative_probs = np.cumsum(probs)
            r = np.random.rand()
            idx = np.searchsorted(cumulative_probs, r)
            centroids.append(data[idx])
        self.centroids = np.array(centroids)

        # Lloyd's Algorithm
        for _ in range(self.max_iters):
            # Assignment step
            diff = data[:, np.newaxis, :] - self.centroids
            dists = np.sqrt(np.sum(diff**2, axis=2))
            labels = np.argmin(dists, axis=1)
            
            # Update step
            new_centroids = np.array([data[labels == i].mean(axis=0) if np.any(labels == i) else self.centroids[i] for i in range(self.n_clusters)])
            if np.allclose(self.centroids, new_centroids):
                break
            self.centroids = new_centroids
            
        self.labels_ = labels
```

### Step 3: The Product Quantizer (Fine Quantization)
Product Quantization splits the residual vectors (data minus their cluster centroid) into `n_subspaces` equal chunks. It trains a separate K-Means model on each chunk, creating a codebook. Each vector is then represented by a sequence of bytes, one per subspace.

```python
class ProductQuantizer:
    def __init__(self, n_subspaces=8, codebook_size=256):
        self.n_subspaces = n_subspaces
        self.codebook_size = codebook_size
        self.codebooks = []

    def fit(self, residuals):
        dim = residuals.shape[1]
        sub_dim = dim // self.n_subspaces
        
        for i in range(self.n_subspaces):
            sub_data = residuals[:, i * sub_dim : (i + 1) * sub_dim]
            # Train a simple K-Means on the subspace
            kmeans = KMeansCoarseQuantizer(n_clusters=self.codebook_size, max_iters=15)
            kmeans.fit(sub_data)
            self.codebooks.append(kmeans.centroids)

    def encode(self, residuals):
        dim = residuals.shape[1]
        sub_dim = dim // self.n_subspaces
        codes = np.zeros((residuals.shape[0], self.n_subspaces), dtype=np.uint8)
        
        for i, codebook in enumerate(self.codebooks):
            sub_data = residuals[:, i * sub_dim : (i + 1) * sub_dim]
            # Find nearest centroid in subspace
            diff = sub_data[:, np.newaxis, :] - codebook
            dists = np.sqrt(np.sum(diff**2, axis=2))
            codes[:, i] = np.argmin(dists, axis=1)
            
        return codes
```

### Step 4: Coarse-to-Fine Search (Asymmetric Distance Calculation)
The final step is the search logic. For a query vector, we first find the nearest coarse clusters. We then calculate the residual of the query relative to those clusters. Finally, we compute the distance between the query residual and the subspace centroids using the pre-computed codebooks, avoiding the need to decompress the stored vectors.

```python
class IVF_PQ_Index:
    def __init__(self, vectors, n_coarse=100, n_subspaces=8):
        self.vectors = vectors
        self.n_coarse = n_coarse
        self.n_subspaces = n_subspaces
        
        # 1. Train Coarse Quantizer
        self.coarse = KMeansCoarseQuantizer(n_clusters=n_coarse)
        self.coarse.fit(vectors)
        
        # 2. Calculate Residuals
        self.residuals = vectors - self.coarse.centroids[self.coarse.labels_]
        
        # 3. Train Product Quantizer on Residuals
        self.pq = ProductQuantizer(n_subspaces=n_subspaces)
        self.pq.fit(self.residuals)
        self.codes = self.pq.encode(self.residuals)
        
        # 4. Build Inverted File
        self.inverted_file = {}
        for idx, label in enumerate(self.coarse.labels_):
            if label not in self.inverted_file:
                self.inverted_file[label] = []
            self.inverted_file[label].append(idx)

    def search(self, query, top_k=10, nprobe=10):
        # Coarse search to find nprobe nearest clusters
        query_residual = query - self.coarse.centroids # Distance to all centroids
        coarse_dists = np.linalg.norm(query_residual, axis=1)
        nearest_clusters = np.argsort(coarse_dists)[:nprobe]
        
        # Asymmetric Distance Calculation (ADC)
        query_subs = np.array_split(query, self.n_subspaces)
        scores = np.zeros(len(self.vectors))
        
        for cluster_idx in nearest_clusters:
            if cluster_idx not in self.inverted_file:
                continue
            indices = self.inverted_file[cluster_idx]
            
            # Calculate distance for each subspace
            for i, sub_query in enumerate(query_subs):
                sub_codes = self.codes[indices, i]
                sub_centroids = self.pq.codebooks[i]
                diff = sub_query - sub_centroids[sub_codes]
                scores[indices] += np.sum(diff**2, axis=1)
                
        # Get top_k results
        top_k_indices = np.argsort(scores)[:top_k]
        return top_k_indices, scores[top_k_indices]
```

## Running and Testing It

To verify your index works correctly, you must measure its Recall@K against a brute-force search. A brute-force search computes the exact L2 distance between the query and every vector in the dataset, serving as the ground truth.

```python
def brute_force_search(query, vectors, top_k=10):
    dists = np.linalg.norm(vectors - query, axis=1)
    return np.argsort(dists)[:top_k]

# Initialize index
index = IVF_PQ_Index(vectors, n_coarse=50, n_subspaces=8)

# Test with a random query
query = vectors[0] # Use an existing vector as a query for easy verification

# Run approximate search
approx_results, _ = index.search(query, top_k=10, nprobe=20)

# Run exact search
exact_results = brute_force_search(query, vectors, top_k=10)

# Calculate Recall@10
intersection = len(set(approx_results) & set(exact_results))
recall = intersection / 10
print(f"Recall@10: {recall:.2f}")
```

When you run this locally, you should expect a Recall@10 between 0.85 and 0.95 depending on the number of clusters (`nprobe`) you search. If the recall is low, increase `nprobe` to visit more coarse clusters at the cost of higher latency. If the recall is 1.0, you are likely over-probing and losing the performance benefits of the index.

## Extending It: Your Roadmap to Senior-Level

A basic IVF-PQ index is a great proof of concept, but to make it production-flavored and truly impressive on a CV, you need to add the systems engineering layers that keep distributed databases alive.

1.  **Memory-Mapped Persistence:** Save the centroids, codebooks, and inverted file indices to disk using `numpy.memmap`. *Why it matters:* It allows the index to handle datasets larger than the available RAM, a strict requirement for any billion-scale vector database.
2.  **Parallel Query Processing:** Implement a multiprocessing pool to handle multiple queries simultaneously, partitioning the `nprobe` clusters across CPU cores. *Why it matters:* Maximizes hardware utilization and ensures low tail latency (p99) under high concurrent query loads.
3.  **Dynamic Indexing (Incremental K-Means):** Allow new vectors to be added to the index without retraining the entire K-Means model from scratch. *Why it matters:* Production systems cannot afford downtime for periodic batch retraining; they require real-time data ingestion.
4.  **GPU Acceleration via CuPy:** Replace NumPy operations with CuPy equivalents to offload the distance matrix calculations to the GPU. *Why it matters:* Reduces coarse quantization and search latency by orders of magnitude, which is critical for real-time recommendation systems.
5.  **Observability and Prometheus Metrics:** Instrument the search function to emit metrics like query latency, recall rate, and memory usage to a Prometheus endpoint. *Why it matters:* Provides the visibility required to maintain Service Level Objectives (SLOs) and diagnose performance regressions in a live environment.

## Key Takeaways

*   **Algorithmic Optimization is Systems Engineering:** Implementing IVF-PQ proves you understand that reducing O(N) complexity to sub-linear requires careful data structure design, not just better hardware.
*   **The Accuracy-Speed Trade-off is Quantifiable:** By adjusting `nprobe` and `n_subspaces`, you directly control the RAM-to-recall curve, a fundamental concept in approximate nearest neighbor search.
*   **Compression is a First-Class Citizen:** Product Quantization demonstrates that modern systems must aggressively compress data to fit within memory bandwidth constraints, trading a few bits of precision for massive throughput gains.
*   **Bridging ML and Backend is a Rare Skill:** Training a K-Means model is ML; serving it with microsecond latency via an inverted file is backend engineering. This project proves you can do both.

## Further Reading

To deepen your understanding of the algorithms and evolve this project into a production-grade system, study the primary sources and canonical documentation below:

1.  [Product Quantization for Nearest Neighbor Search by Jegou et al.](https://lear.inrialpes.fr/pubs/2011/JDS11/jegou2011product.pdf) — The foundational paper that introduced the asymmetric distance calculation (ADC) used in this project.
2.  [FAISS: A Library for Efficient Similarity Search and Clustering of Dense Vectors](https://github.com/facebookresearch/faiss) — The canonical open-source implementation by Meta. Studying their `IndexIVFPQ` source code will reveal production-grade optimizations for GPU batching and memory management.
3.  [ScaNN: Scalable Nearest Neighbors](https://research.google/pubs/pub48717/) — Google's paper on improved partitioning and distance measures, which builds directly upon the IVF-PQ paradigm to achieve state-of-the-art recall-latency trade-offs.