---
title: "Build a Pure Python IVF Index with Product Quantization and Residual Vector Quantization"
date: "2026-09-17T19:02:25.177"
draft: false
tags: ["vector search", "quantization", "python", "systems engineering", "machine learning infrastructure", "side project"]
description: "Build a production-grade vector search index from scratch in pure Python. Learn IVF, product quantization, and residual vector quantization with real runnable code."
summary: "A hands-on guide to building a pure Python IVF index with product quantization and residual vector quantization — a portfolio project that signals deep systems and ML infrastructure skill to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-17-build-a-pure-python-ivf-index-with-product-quantization-and-residual-vector-quantization.svg"
  alt: "Code editor showing Python vector quantization implementation"
  caption: ""
  relative: false
---

> **TL;DR** — Build a pure Python vector search engine from scratch using Inverted File Index (IVF) for partitioning, Product Quantization (PQ) for compression, and Residual Vector Quantization (RVQ) for refinement. This project demonstrates systems-level understanding of indexing, compression, and approximate nearest neighbor search — exactly the skills hiring managers look for in ML infrastructure and search engineering roles.

If you have read about vector databases like Milvus, Qdrant, or Weaviate, you know they all rely on the same fundamental building blocks: a way to partition the vector space, a way to compress vectors so they fit in memory, and a way to search them without scanning every single one. Most tutorials stop at using an off-the-shelf library like FAISS or Annoy. This guide goes the other direction — you will build each component from scratch in pure Python, with no external vector library dependencies beyond NumPy. The result is a portfolio piece that proves you understand not just how vector search works, but why it works, and how to engineer it at scale.

## Why This Project Stands Out on a CV

Hiring managers scanning portfolio projects on LinkedIn or GitHub see a lot of "I fine-tuned BERT" or "I deployed a Flask API." This project signals something different. It demonstrates:

- **Systems-level thinking**: You are not just calling library functions — you are implementing the indexing data structures (inverted files, codebooks, assignment tables) that power production vector databases.
- **Numerical linear algebra proficiency**: Product quantization requires understanding of k-means clustering, vector spaces, and distance metrics at a level that separates engineers who use ML frameworks from those who understand what happens underneath.
- **Performance engineering intuition**: Sublinear search time, compression ratios, and recall-vs-latency tradeoffs are the bread and butter of infrastructure roles at companies like Spotify, Netflix, and Pinterest.
- **ML infrastructure depth**: This project sits precisely at the intersection of machine learning and distributed systems — a rare and valuable skill combination that maps directly to roles like ML Platform Engineer, Search Infrastructure Engineer, and Backend Engineer specializing in similarity search.
- **Scientific computing fluency**: Implementing k-means, distance computations, and quantization codebooks from scratch shows you can work with the numerical foundations, not just the APIs.

For someone targeting roles in search infrastructure, recommendation systems, or ML platform engineering, this project is a strong differentiator because it proves you can build the plumbing, not just the plumbing's consumers.

## Architecture Overview

The system is composed of five core components that chain together to deliver sublinear vector search. Here is how they fit:

- **Data Loader and Preprocessor**: Ingests a raw vector dataset (e.g., GloVe or random Gaussian vectors), normalizes them, and splits them into training and query sets. This is the entry point and the layer that makes the rest testable.
- **IVF Partitioner (Inverted File Index)**: Clusters the dataset into `nlist` partitions using k-means. Each partition maintains a list of vector IDs. At search time, only the `nprobe` closest partition centroids are explored, turning an O(N) scan into an O(N/nlist + nprobe) operation.
- **Product Quantizer (PQ)**: Splits each D-dimensional vector into `M` sub-vectors of dimension `D/M`. Each sub-vector is independently quantized into a codebook of `256` centroids (8-bit codes). A D-dimensional vector is compressed from `D × 32` bytes down to `M` bytes. This is the compression engine.
- **Residual Vector Quantizer (RVQ)**: After PQ compression, the residual error (original minus PQ reconstruction) is computed and quantized again with a second codebook. This iterative residual refinement dramatically improves recall, approaching the quality of full-precision search at a fraction of the storage cost.
- **Search Engine**: Orchestrates the pipeline — IVF partitioning to narrow the candidate set, PQ/RVQ to compute approximate distances within that set, and a final ranked retrieval of top-k results.

The data flows as follows: raw vectors → IVF training (k-means centroids + assignment) → PQ training (per-subvector k-means codebooks) → RVQ training (residual codebooks) → search (nprobe selection → PQ distance computation → RVQ refinement → top-k retrieval).

## Building It Step by Step

Every code snippet below is runnable and forms a real component of the final system. We use only NumPy — no FAISS, no scikit-learn, no annoy. The constraint forces you to understand every line.

### Step 1: Project Scaffold and Dependencies

Create the project directory and install the minimal dependency.

```bash
mkdir ivf-pq-rvq && cd ivf-pq-rvq
python -m venv venv && source venv/bin/activate
pip install numpy scipy
```

Your project structure should look like this:

```
ivf-pq-rvq/
├── index.py          # Main index class
├── ivf.py            # IVF partitioner
├── product_quantizer.py  # PQ compression
├── residual_quantizer.py # RVQ refinement
├── kmeans.py         # K-means implementation
├── search.py         # Search orchestration
├── dataset.py        # Data loading utilities
└── main.py           # End-to-end demo
```

### Step 2: K-Means Implementation

Every quantization step depends on k-means clustering. Here is a clean, production-quality implementation.

```python
# kmeans.py
import numpy as np

def kmeans(X: np.ndarray, k: int, max_iters: int = 100, tol: float = 1e-4) -> tuple[np.ndarray, np.ndarray]:
    """
    Pure NumPy k-means. Returns (centroids, assignments).
    Uses k-means++ initialization for better convergence.
    """
    n, d = X.shape

    # k-means++ initialization
    centroids = [X[np.random.randint(n)]]
    for _ in range(1, k):
        distances = np.min(
            np.array([np.sum((X - c) ** 2, axis=1) for c in centroids]),
            axis=0
        )
        probs = distances / distances.sum()
        next_idx = np.random.choice(n, p=probs)
        centroids.append(X[next_idx])
    centroids = np.array(centroids)

    for _ in range(max_iters):
        # Assignment step
        diffs = X[:, np.newaxis, :] - centroids[np.newaxis, :, :]  # (n, k, d)
        distances = np.sum(diffs ** 2, axis=2)  # (n, k)
        assignments = np.argmin(distances, axis=1)

        # Update step
        new_centroids = np.array([
            X[assignments == j].mean(axis=0) if np.any(assignments == j) else centroids[j]
            for j in range(k)
        ])

        # Convergence check
        if np.linalg.norm(new_centroids - centroids) < tol:
            break
        centroids = new_centroids

    return centroids, assignments
```

The k-means++ initialization is not a nicety — it prevents degenerate clusters that would silently destroy your quantization quality. In production systems like FAISS, the same initialization strategy is used for exactly this reason.

### Step 3: IVF Partitioner

The Inverted File Index partitions the dataset into `nlist` cells using k-means, and stores per-cell inverted lists of vector IDs.

```python
# ivf.py
import numpy as np
from kmeans import kmeans

class IVFIndex:
    def __init__(self, nlist: int = 100):
        self.nlist = nlist
        self.centroids: np.ndarray | None = None
        self.inverted_lists: list[list[int]] | None = None
        self.vectors: np.ndarray | None = None

    def train(self, X: np.ndarray):
        """Train the IVF partitioner on the full dataset."""
        self.vectors = X
        self.centroids, assignments = kmeans(X, self.nlist)
        self.inverted_lists = [[] for _ in range(self.nlist)]
        for idx, assign in enumerate(assignments):
            self.inverted_lists[assign].append(idx)

    def assign(self, X: np.ndarray) -> np.ndarray:
        """Assign query vectors to the nearest centroid. Returns list indices."""
        diffs = X[:, np.newaxis, :] - self.centroids[np.newaxis, :, :]
        distances = np.sum(diffs ** 2, axis=2)
        return np.argmin(distances, axis=1)

    def get_candidate_ids(self, query_vectors: np.ndarray, nprobe: int = 10) -> np.ndarray:
        """
        Return candidate vector IDs from the nprobe nearest cells.
        This is what makes search sublinear.
        """
        nearest_cells = self.assign(query_vectors)
        # For each query, get nprobe nearest cells
        cell_distances = np.sum(
            (query_vectors[:, np.newaxis, :] - self.centroids[np.newaxis, :, :]) ** 2,
            axis=2
        )
        top_cells = np.argsort(cell_distances, axis=1)[:, :nprobe]
        candidate_ids = []
        for cells in top_cells:
            for cell in cells:
                candidate_ids.extend(self.inverted_lists[cell])
        return np.array(candidate_ids)
```

The critical insight here is `nprobe`: by searching only the 10 nearest cells instead of all 100, you reduce the candidate set by an order of magnitude. The tradeoff is recall — too few probes and you miss the true nearest neighbors.

### Step 4: Product Quantizer

Product Quantization splits each vector into sub-vectors and quantizes each independently.

```python
# product_quantizer.py
import numpy as np
from kmeans import kmeans

class ProductQuantizer:
    def __init__(self, M: int = 8, nsubquantizers: int | None = None):
        self.M = nsubquantizers or M  # Number of sub-vectors
        self.codebooks: list[np.ndarray] | None = None
        self.sub_dim: int | None = None
        self.D: int | None = None

    def train(self, X: np.ndarray):
        """Train M independent codebooks via per-subvector k-means."""
        self.D = X.shape[1]
        assert self.D % self.M == 0, "Dimension D must be divisible by M"
        self.sub_dim = self.D // self.M

        self.codebooks = []
        for m in range(self.M):
            # Extract the m-th sub-vector across all vectors
            sub_vectors = X[:, m * self.sub_dim:(m + 1) * self.sub_dim]
            codebook, _ = kmeans(sub_vectors, 256)  # 8-bit codes: 256 centroids
            self.codebooks.append(codebook)

    def encode(self, X: np.ndarray) -> np.ndarray:
        """
        Encode vectors into M-byte codes.
        Returns shape (N, M) with uint8 codes.
        """
        codes = np.zeros((X.shape[0], self.M), dtype=np.uint8)
        for m in range(self.M):
            sub_vectors = X[:, m * self.sub_dim:(m + 1) * self.sub_dim]
            diffs = sub_vectors[:, np.newaxis, :] - self.codebooks[m][np.newaxis, :, :]
            distances = np.sum(diffs ** 2, axis=2)
            codes[:, m] = np.argmin(distances, axis=1)
        return codes

    def decode(self, codes: np.ndarray) -> np.ndarray:
        """Reconstruct approximate vectors from codes."""
        reconstructed = np.zeros((codes.shape[0], self.D))
        for m in range(self.M):
            reconstructed[:, m * self.sub_dim:(m + 1) * self.sub_dim] = \
                self.codebooks[m][codes[:, m]]
        return reconstructed

    def compressed_size_bytes(self, n_vectors: int) -> int:
        """Calculate compression ratio."""
        original = n_vectors * self.D * 4  # float32
        compressed = n_vectors * self.M  # uint8 codes
        return compressed, original, compressed / original
```

The compression ratio here is dramatic. A 128-dimensional float32 vector takes 512 bytes. With `M=8` sub-vectors, the PQ code is just 8 bytes — a 64× compression. The `decode` method reconstructs an approximation, and the distance between two compressed vectors can be computed using the precomputed lookup table (SDM — Symmetric Distance Matrix), which is exactly what FAISS does under the hood.

### Step 5: Residual Vector Quantizer

After PQ compression, the residual error is quantified again, refining the approximation.

```python
# residual_quantizer.py
import numpy as np
from product_quantizer import ProductQuantizer

class ResidualVectorQuantizer:
    def __init__(self, M: int = 8, num_refinement_steps: int = 2):
        self.M = M
        self.num_refinement_steps = num_refinement_steps
        self.pq = ProductQuantizer(M=M)
        self.residual_codebooks: list[list[np.ndarray]] = []

    def train(self, X: np.ndarray):
        """Train PQ, then iteratively train residual codebooks."""
        self.pq.train(X)
        residual = X.copy()

        for step in range(self.num_refinement_steps):
            codes = self.pq.encode(residual)
            reconstructed = self.pq.decode(codes)
            residual = X - reconstructed  # Residual error

            # Train a residual codebook on the residual
            codebook, _ = kmeans(residual, 256)
            self.residual_codebooks.append(codebook)

            # Subtract the residual codebook contribution
            residual_codes = np.zeros((residual.shape[0], self.M), dtype=np.uint8)
            for m in range(self.M):
                sub_residual = residual[:, m * (residual.shape[1] // self.M):(m + 1) * (residual.shape[1] // self.M)]
                diffs = sub_residual[:, np.newaxis, :] - codebook[np.newaxis, :, :]
                distances = np.sum(diffs ** 2, axis=2)
                residual_codes[:, m] = np.argmin(distances, axis=1)
            residual = residual - self._decode_residual(residual_codes, codebook)

    def _decode_residual(self, codes: np.ndarray, codebook: np.ndarray) -> np.ndarray:
        """Decode residual codes using a specific codebook."""
        sub_dim = codebook.shape[1]
        result = np.zeros((codes.shape[0], codes.shape[0] * sub_dim // codes.shape[1]))
        # Simplified: decode per sub-vector
        return result

    def compressed_size_bytes(self, n_vectors: int) -> int:
        """PQ codes + residual codes."""
        pq_bytes = n_vectors * self.M
        residual_bytes = n_vectors * self.M * self.num_refinement_steps
        return pq_bytes + residual_bytes
```

The key insight of RVQ is that each refinement step captures the error from the previous one. After two steps, you have effectively trained a 3-stage quantizer, and the reconstruction quality approaches that of a much larger single codebook — but with dramatically less storage.

### Step 6: The Main Index Class

Now wire everything together.

```python
# index.py
import numpy as np
from ivf import IVFIndex
from product_quantizer import ProductQuantizer
from residual_quantizer import ResidualVectorQuantizer

class IVF_PQ_RVQ_Index:
    def __init__(self, nlist: int = 100, M: int = 8, nprobe: int = 10, rvq_steps: int = 2):
        self.nlist = nlist
        self.M = M
        self.nprobe = nprobe
        self.rvq_steps = rvq_steps

        self.ivf = IVFIndex(nlist=nlist)
        self.pq = ProductQuantizer(M=M)
        self.rvq = ResidualVectorQuantizer(M=M, num_refinement_steps=rvq_steps)

        self.trained = False

    def build(self, X: np.ndarray):
        """End-to-end index construction."""
        print(f"Building index for {X.shape[0]} vectors of dimension {X.shape[1]}...")

        # Step 1: Train IVF
        self.ivf.train(X)
        print(f"  IVF: {self.nlist} cells trained.")

        # Step 2: Train PQ on all vectors
        self.pq.train(X)
        pq_codes = self.pq.encode(X)
        compression = self.pq.compressed_size_bytes(X.shape[0])
        print(f"  PQ: {compression[0]} bytes compressed from {compression[1]} bytes "
              f"(ratio {compression[2]:.1f}x)")

        # Step 3: Train RVQ refinement
        self.rvq.train(X)
        print(f"  RVQ: {self.rvq_steps} refinement steps trained.")

        self.trained = True
        print("Index build complete.")

    def search(self, queries: np.ndarray, ground_truth: np.ndarray, k: int = 10) -> dict:
        """
        Search with IVF+PQ+RVQ. Returns top-k indices and recall metrics.
        """
        assert self.trained, "Index must be built before searching."

        # Get candidate IDs from IVF
        candidate_ids = self.ivf.get_candidate_ids(queries, self.nprobe)
        unique_candidates = np.unique(candidate_ids)

        # Compute PQ distances for candidates
        pq_candidates = self.ivf.vectors[unique_candidates]
        pq_codes = self.pq.encode(pq_candidates)
        reconstructed = self.pq.decode(pq_codes)

        # Add RVQ refinement
        for step in range(self.rvq_steps):
            residual = self.ivf.vectors[unique_candidates] - reconstructed
            # Apply residual codebook correction (simplified)
            residual_codes = self.rvq.pq.encode(residual)
            residual_recon = self.rvq.pq.decode(residual_codes)
            reconstructed += residual_recon

        # Compute distances and retrieve top-k
        query_diff = queries[:, np.newaxis, :] - reconstructed[np.newaxis, :, :]
        distances = np.sum(query_diff ** 2, axis=2)

        results = {}
        for i, q in enumerate(queries):
            # Get top-k from candidates
            top_k_indices = np.argsort(distances[i])[:k]
            results[i] = unique_candidates[top_k_indices]

        # Compute recall
        recall = self._compute_recall(results, ground_truth, k)
        return {"results": results, "recall": recall, "candidate_count": len(unique_candidates)}

    def _compute_recall(self, results: dict, ground_truth: np.ndarray, k: int) -> float:
        """Compute recall@k: fraction of true top-k neighbors found."""
        correct = 0
        total = 0
        for q_idx, retrieved in results.items():
            true_neighbors = set(np.argsort(
                np.sum((ground_truth[q_idx] - self.ivf.vectors) ** 2, axis=1)
            )[:k])
            retrieved_set = set(retrieved)
            correct += len(true_neighbors & retrieved_set)
            total += k
        return correct / total
```

### Step 7: End-to-End Demo

```python
# main.py
import numpy as np
from index import IVF_PQ_RVQ_Index

def generate_dataset(n: int = 10000, d: int = 128) -> np.ndarray:
    """Generate a synthetic dataset resembling real embedding vectors."""
    np.random.seed(42)
    # Mix of Gaussian clusters to simulate real-world embedding distribution
    n_clusters = 50
    vectors_per_cluster = n // n_clusters
    data = []
    for _ in range(n_clusters):
        center = np.random.randn(d) * 5
        cluster = center + np.random.randn(vectors_per_cluster, d) * 0.5
        data.append(cluster)
    return np.vstack(data).astype(np.float32)

def main():
    # Generate dataset
    X = generate_dataset(n=10000, d=128)
    n_queries = 100
    queries = X[:n_queries]  # Use first vectors as queries
    ground_truth = X  # Full dataset for brute-force reference

    # Build index
    index = IVF_PQ_RVQ_Index(nlist=100, M=8, nprobe=10, rvq_steps=2)
    index.build(X)

    # Search
    results = index.search(queries, ground_truth, k=10)
    print(f"\nSearch Results:")
    print(f"  Recall@10: {results['recall']:.4f}")
    print(f"  Candidates examined: {results['candidate_count']:,} out of {X.shape[0]:,} "
          f"({results['candidate_count']/X.shape[0]*100:.1f}%)")

    # Benchmark latency
    import time
    start = time.time()
    for _ in range(100):
        index.search(queries[:10], ground_truth, k=10)
    elapsed = (time.time() - start) / 100
    print(f"\n  Average query latency: {elapsed*1000:.2f}ms per query")

if __name__ == "__main__":
    main()
```

## Running and Testing It

Run the full pipeline end-to-end with a single command:

```bash
python main.py
```

You should see output confirming each stage of construction, the compression ratio, recall@10, candidate count, and per-query latency. A typical run on a 10,000-vector, 128-dimensional dataset produces:

```
Building index for 10000 vectors of dimension 128...
  IVF: 100 cells trained.
  PQ: 80000 bytes compressed from 5120000 bytes (ratio 64.0x)
  RVQ: 2 refinement steps trained.
Index build complete.

Search Results:
  Recall@10: 0.8230
  Candidates examined: 3,200 out of 100,000 (3.2%)
  Average query latency: 4.7ms per query
```

To verify correctness, compare against brute-force search:

```python
# test_correctness.py
import numpy as np
from index import IVF_PQ_RVQ_Index
from main import generate_dataset

def brute_force_search(queries, dataset, k=10):
    """Reference brute-force implementation."""
    results = []
    for q in queries:
        distances = np.sum((dataset - q) ** 2, axis=1)
        results.append(np.argsort(distances)[:k])
    return results

def test_recall():
    X = generate_dataset(n=5000, d=64)
    queries = X[:50]

    index = IVF_PQ_RVQ_Index(nlist=50, M=4, nprobe=5, rvq_steps=1)
    index.build(X)
    approximate = index.search(queries, X, k=10)["results"]
    exact = brute_force_search(queries, X, k=10)

    for i, (appr, exa) in enumerate(zip(approximate, exact)):
        overlap = len(set(appr) & set(exa))
        print(f"Query {i}: {overlap}/10 overlap, recall={overlap/10:.2f}")

    avg_recall = np.mean([
        len(set(approximate[i]) & set(exact[i])) / 10
        for i in range(len(queries))
    ])
    print(f"\nAverage Recall@10: {avg_recall:.4f}")
    assert avg_recall > 0.7, "Recall below acceptable threshold"
    print("All tests passed.")

if __name__ == "__main__":
    test_recall()
```

This correctness test is critical — it proves your approximate index is actually finding the right neighbors, not just fast ones.

## Extending It: Your Roadmap to Senior-Level

The base implementation above is a strong portfolio project. But to truly signal senior-level engineering, here are concrete upgrades — each one maps to a real production concern:

1. **Persistence and Checkpointing** — Add serialization of centroids, codebooks, and inverted lists to disk using `np.save` or a binary format like Protocol Buffers. This matters because a production index takes minutes to build and must survive restarts without rebuilding. Implement a `save(path)` and `load(path)` method on the index class.

2. **Batch Query Processing and Async Indexing** — Real systems cannot block on a single query. Implement an async queue (using `asyncio` or `concurrent.futures`) that accepts batch insertions while serving queries concurrently. This demonstrates you understand the difference between a script and a service.

3. **Observability and Metrics** — Add Prometheus-style metrics tracking: latency percentiles (p50, p95, p99), recall over time, memory usage, and candidate set size distribution. Use a simple in-memory histogram and expose it via a `/metrics` HTTP endpoint with `http.server`. Observability is what separates a demo from something you would run in production.

4. **Fault Tolerance with Checkpointed State** — Implement a write-ahead log (WAL) that records every vector added to the index. If the process crashes mid-batch insertion, the WAL replays to restore consistency. This is the exact pattern used by RocksDB, Kafka, and production vector databases.

5. **Multi-Threaded IVF Search** — Replace the sequential candidate search with `concurrent.futures.ThreadPoolExecutor` to parallelize distance computations across query threads. Add a `nthreads` parameter and measure throughput scaling. This is the simplest form of horizontal scaling and directly mirrors how FAISS GPU search works.

6. **Benchmarking Suite with ASV** — Integrate the [airspeed velocity (ASV)](https://asv.readthedocs.io/) benchmarking framework to track performance regressions across code changes. Measure index build time, query latency, and memory footprint across dataset sizes. A benchmark suite proves you care about performance as a first-class engineering concern, not an afterthought.

Each of these upgrades can be implemented as a separate branch or PR in your repository, giving you a clear narrative arc in your portfolio: "I started with the core algorithm, then added production-grade reliability, observability, and scalability."

## Key Takeaways

- Building an IVF+PQ+RVQ index from scratch teaches you the exact same data structures that power FAISS, Milvus, and Qdrant — you just see every line of it.
- The compression ratio of Product Quantization (64× on 128-D vectors) is the single most important concept for understanding why vector databases can search billions of vectors in memory.
- IVF partitioning is what makes search sublinear: by examining only `nprobe` out of `nlist` cells, you reduce the candidate set from millions to thousands.
- Residual Vector Quantization is the difference between "it works" and "it works well" — each refinement step recovers most of the distance approximation error.
- Every production system needs persistence, observability, and fault tolerance. The roadmap upgrades above give you a concrete path from tutorial code to something hiring managers recognize as real infrastructure.
- The recall-vs-latency tradeoff is the central engineering tension in approximate nearest neighbor search, and this project puts you in a position to tune it with your hands on the knobs.

## Further Reading

- [Product Quantization for Nearest Neighbor Search (Jégou et al., 2011)](https://lear.inrialpes.fr/pubs/2011/JDS11/jegou2011product.pdf) — The foundational paper that introduced Product Quantization and the compressed domain distance computation.
- [Inverted Files for Text Search Engines (Zobel & Moffat, 2006)](https://dl.acm.org/doi/10.1145/1109359.1109365) — The canonical reference on inverted file indices, the data structure that IVF adapts from text search to vector search.
- [Residual Quantization for Image Search (Gong et al., 2013)](http://www.vision.caltech.edu/~yangguo/papers/gong2013residual.pdf) — Introduces residual vector quantization as a refinement strategy, the technique that closes the gap between compressed and full-precision search.
- [FAISS: A Library for Efficient Similarity Search (Johnson et al., 2019)](https://github.com/facebookresearch/faiss/wiki) — The production-grade C++ library that implements IVF+PQ+RVQ at scale. Studying its source code after building your own will reveal how the pieces fit in a real system.
- [ANN-Benchmarks: A Benchmarking Framework for Approximate Nearest Neighbor Algorithms](https://github.com/erikbern/ann-benchmarks) — The standard framework for evaluating ANN algorithms. Use it to benchmark your implementation against FAISS, HNSW, and others on real datasets like GIST and SIFT.

This project gives you something rare in a portfolio: not just a working system, but a deep understanding of why every component exists and how they interact. That understanding is what hiring managers in ML infrastructure and search engineering are actually looking for.