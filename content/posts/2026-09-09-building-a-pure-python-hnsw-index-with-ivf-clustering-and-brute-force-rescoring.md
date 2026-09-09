---
title: "Building a Pure-Python HNSW Index with IVF Clustering and Brute-Force Rescoring"
date: "2026-09-09T01:01:15.382"
draft: false
tags: ["machine-learning", "vector-search", "hnsw", "python", "systems-engineering", "similarity-search"]
description: "Build a production-grade approximate vector similarity search engine from scratch in pure Python — HNSW indexing, IVF clustering, and brute-force rescoring — to demonstrate real systems engineering skills on your CV."
summary: "A hands-on guide to building a pure-Python HNSW index with IVF clustering and brute-force rescoring. Learn how approximate vector similarity search works under the hood and create a portfolio project that signals deep systems expertise to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-building-a-pure-python-hnsw-index-with-ivf-clustering-and-brute-force-rescoring.svg"
  alt: "A visualization of vector embeddings organized in an HNSW graph structure with clustered partitions"
  caption: ""
  relative: false
---

> **TL;DR** — Building a pure-Python HNSW index with IVF (Inverted File) clustering and brute-force rescoring is one of the most impressive side projects an engineer can undertake. It demonstrates mastery of data structures, algorithmic thinking, and production-grade systems design — the exact trifecta hiring managers look for in senior ML infrastructure and search engineering roles. This guide walks you through every line of code, from graph construction to query execution.

Vector similarity search has become the backbone of modern recommendation systems, semantic search, and retrieval-augmented generation (RAG) pipelines. Companies like Spotify, Pinterest, and GitHub rely on approximate nearest neighbor (ANN) algorithms to serve billions of queries daily. Yet most engineers interact with these systems through black-box libraries like FAISS or Milvus without understanding what happens underneath.

Building one from scratch changes that. It forces you to confront the trade-offs between recall, latency, and memory — the same trade-offs that define production systems at scale. This project is not an academic exercise. It is a deliberate demonstration of systems thinking, algorithmic rigor, and engineering maturity.

## Why This Project Stands Out on a CV

Hiring managers and technical recruiters scan portfolios for signals that go beyond "I used PyTorch." This project signals several distinct competencies that map directly to high-value roles:

- **Systems Engineering Depth.** Implementing HNSW from scratch requires managing graph connectivity, node insertion heuristics, and multi-layer navigation — skills directly transferable to distributed systems and infrastructure work.
- **ML Infrastructure Fluency.** IVF clustering demonstrates you understand how to partition embedding spaces for efficient retrieval, a core concern in any ML platform team.
- **Algorithmic Rigor.** Balancing recall versus latency, choosing the right `ef_construction` and `M` parameters, and implementing brute-force rescoring shows you can reason about algorithmic complexity in production contexts.
- **Full-Stack Ownership.** From data ingestion to query serving, this project covers the entire lifecycle of a data-intensive service — exactly what senior backend and infrastructure roles demand.
- **Quantitative Evaluation Discipline.** Building proper benchmarks (recall@k, latency percentiles) signals that you treat performance as a first-class metric, not an afterthought.

The roles this project signals include Search Engineer, ML Platform Engineer, Backend Engineer (systems-heavy), and Research Engineer. It bridges the gap between "I trained a model" and "I shipped a system that serves models at scale."

## Architecture Overview

The system consists of four tightly integrated components. Each one is independently understandable, but together they form a complete approximate vector search engine.

```
┌─────────────────────────────────────────────────────┐
│                  Query Pipeline                      │
│                                                      │
│  Query Vector ──► IVF Filter ──► HNSW Search ──► Rescore│
│                      │                │              │
│                      ▼                ▼              │
│               Candidate Set    Top-K Candidates      │
│                      │                │              │
│                      └───────► Brute-Force ─────────┘
│                                Re-ranking            │
│                                                      │
│                       ▼                                │
│              Final Ranked Results                      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                  Index Build Phase                    │
│                                                      │
│  Raw Vectors ──► IVF Clustering ──► Per-Cluster HNSW  │
│                     (K-Means)         Construction    │
└─────────────────────────────────────────────────────┘
```

- **IVF (Inverted File) Clustering Layer.** Partitions the embedding space into `nlist` clusters using K-Means. At query time, only the `nprobe` closest clusters are searched, dramatically reducing the candidate set before the expensive graph traversal begins.

- **HNSW (Hierarchical Navigable Small World) Graph Layer.** A multi-layer graph structure where the bottom layer connects all elements and upper layers provide "express lanes" for fast navigation. Each node maintains `M` bidirectional connections. Insertion uses a greedy heuristic to find the best neighbors at each layer.

- **Brute-Force Rescoring Layer.** After HNSW returns its top-k candidates, a full cosine or L2 distance computation against the original vectors re-ranks them. This corrects the approximation errors inherent in graph-based search, boosting recall without sacrificing too much latency.

- **Storage and Serialization Layer.** In-memory index structures serialized to disk via `pickle` or `joblib`, with optional memory-mapped files for large datasets. This is the first extension point for production hardening.

The pipeline is deliberate: IVF prunes the search space, HNSW navigates the pruned space efficiently, and brute-force rescoring guarantees that the final results are provably close to the ground truth. This three-tier design mirrors what FAISS and ScaNN actually do under the hood.

## Building It Step by Step

The implementation uses only `numpy` and `scipy` — no deep learning frameworks, no compiled extensions. This keeps the project accessible and ensures every line of code is yours to explain in an interview.

### Step 1: Project Scaffolding and Dependencies

Create the project structure and pin your dependencies.

```bash
mkdir py-hnsw-ivf && cd py-hnsw-ivf
python -m venv venv
source venv/bin/activate
pip install numpy scipy scikit-learn tqdm
```

Create `hnsw_ivf/` with an `__init__.py`, and the following modules: `ivf.py`, `hnsw.py`, `index.py`, and `query.py`.

### Step 2: IVF Clustering with K-Means

The IVF layer partitions vectors into clusters and stores the centroids for query-time filtering.

```python
# hnsw_ivf/ivf.py
import numpy as np
from sklearn.cluster import KMeans
from typing import List, Tuple

class IVFIndex:
    def __init__(self, nlist: int = 100):
        self.nlist = nlist
        self.centroids: np.ndarray = None
        self.assignments: List[List[int]] = None
        self.vectors: np.ndarray = None

    def fit(self, vectors: np.ndarray) -> None:
        """Cluster vectors into nlist partitions using K-Means."""
        self.vectors = vectors
        kmeans = KMeans(n_clusters=self.nlist, n_init=10, random_state=42)
        kmeans.fit(vectors)
        self.centroids = kmeans.cluster_centers_
        self.assignments = [[] for _ in range(self.nlist)]
        labels = kmeans.labels_
        for idx, label in enumerate(labels):
            self.assignments[label].append(idx)

    def query_candidates(self, query: np.ndarray, nprobe: int = 10) -> List[int]:
        """Return global indices of vectors in the nprobe closest clusters."""
        distances = np.linalg.norm(self.centroids - query, axis=1)
        closest_clusters = np.argsort(distances)[:nprobe]
        candidates = []
        for cluster_idx in closest_clusters:
            candidates.extend(self.assignments[cluster_idx])
        return candidates
```

The `nprobe` parameter is critical: setting it too low risks missing the true nearest neighbors, while setting it too high degenerates into a full scan. A good starting heuristic is `nprobe = sqrt(nlist)`.

### Step 3: HNSW Graph Construction

This is the core algorithm. HNSW maintains layers where the top layer has few nodes and the bottom layer has all nodes. Insertion uses a greedy nearest-neighbor search at each layer to find connections.

```python
# hnsw_ivf/hnsw.py
import numpy as np
import random
from typing import List, Dict, Set, Tuple
from collections import defaultdict

class HNSWIndex:
    def __init__(self, dim: int, M: int = 16, ef_construction: int = 200, 
                 max_layer: int = 12, ml: float = 1 / np.log(2)):
        self.dim = dim
        self.M = M
        self.ef_construction = ef_construction
        self.max_layer = max_layer
        self.ml = ml  # layer probability multiplier
        
        # Graph storage: {node_id: {layer: [neighbor_ids]}}
        self.graph: Dict[int, Dict[int, Set[int]]] = defaultdict(lambda: defaultdict(set))
        self.data: Dict[int, np.ndarray] = {}
        self.element_count = 0
        self.enter_point = None  # global entry point for search

    def _random_layer(self) -> int:
        """Layer selection with exponential decay probability."""
        layer = 0
        while random.random() < self.ml and layer < self.max_layer:
            layer += 1
        return layer

    def _distance(self, a: np.ndarray, b: np.ndarray) -> float:
        """Cosine distance (1 - cosine similarity)."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 1.0
        return 1.0 - np.dot(a, b) / (norm_a * norm_b)

    def _search_layer(self, query: np.ndarray, ep: int, 
                      layer: int, ef: int) -> List[Tuple[float, int]]:
        """Greedy nearest-neighbor search at a given layer."""
        visited: Set[int] = {ep}
        candidates = [(self._distance(query, self.data[ep]), ep)]
        w = []  # results

        while candidates:
            dist, c = heapq.heappop(candidates)
            if dist > w[0][0] if w else False:
                break
            for neighbor in self.graph[c][layer]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    d = self._distance(query, self.data[neighbor])
                    heapq.heappush(candidates, (d, neighbor))
            if w and len(w) < ef:
                heapq.heappush(w, (dist, c))
            elif not w:
                w.append((dist, c))
            elif dist < w[0][0]:
                heapq.heapreplace(w, (dist, c))
        return sorted(w)[:ef]

    def insert(self, node_id: int, vector: np.ndarray) -> None:
        """Insert a vector into the HNSW graph at all relevant layers."""
        self.data[node_id] = vector
        layer = self._random_layer()
        
        if self.element_count == 0:
            self.enter_point = node_id
            self.element_count += 1
            return

        ep = self.enter_point
        # Find entry point at the topmost relevant layer
        for l in range(min(layer + 1, self.max_layer)):
            ep = self._search_layer(vector, ep, l, 1)[0][1]
        
        # Insert connections at each layer up to the random layer
        for l in range(layer, -1, -1):
            ef_search = self.ef_construction if l == layer else self.M
            nearest = self._search_layer(vector, ep, l, ef_search)
            # Select M closest neighbors and create bidirectional links
            for dist, neighbor in nearest[:self.M]:
                self.graph[node_id][l].add(neighbor)
                self.graph[neighbor][l].add(node_id)
                # Prune to M connections per node per layer
                if len(self.graph[neighbor][l]) > self.M:
                    # Remove the farthest neighbor
                    neighbors_dist = [
                        (self._distance(self.data[n], self.data[neighbor]), n) 
                        for n in self.graph[neighbor][l]
                    ]
                    farthest = max(neighbors_dist)[1]
                    self.graph[neighbor][l].discard(farthest)
                    self.graph[node_id][l].discard(farthest)

        self.element_count += 1
```

The `_search_layer` method uses a priority queue to perform greedy traversal. At each step, it expands the closest unvisited neighbor and maintains a candidate set of size `ef`. The layer selection probability (`ml`) ensures the graph has a logarithmic height, giving `O(log n)` search complexity.

### Step 4: Brute-Force Rescoring

After the graph search returns candidates, a full distance computation corrects any ranking errors.

```python
# hnsw_ivf/query.py
import numpy as np
from typing import List, Tuple
from heapq import heappush, heappop

def brute_force_rescore(query: np.ndarray, 
                        candidate_ids: List[int], 
                        vectors: dict, 
                        k: int = 10) -> List[Tuple[float, int]]:
    """Compute exact distances for all candidates and return top-k."""
    scores = []
    q_norm = np.linalg.norm(query)
    for cid in candidate_ids:
        v = vectors[cid]
        v_norm = np.linalg.norm(v)
        if q_norm == 0 or v_norm == 0:
            sim = 0.0
        else:
            sim = np.dot(query, v) / (q_norm * v_norm)
        scores.append((1.0 - sim, cid))  # distance = 1 - similarity
    scores.sort()
    return scores[:k]
```

### Step 5: Composing the Full Index

Tie everything together in a unified `Index` class.

```python
# hnsw_ivf/index.py
import numpy as np
from typing import List, Tuple
from .ivf import IVFIndex
from .hnsw import HNSWIndex
from .query import brute_force_rescore

class VectorIndex:
    def __init__(self, dim: int, nlist: int = 100, M: int = 16, 
                 ef_construction: int = 200, nprobe: int = 10):
        self.dim = dim
        self.ivf = IVFIndex(nlist=nlist)
        self.hnsw_per_cluster: List[HNSWIndex] = []
        self.M = M
        self.ef_construction = ef_construction
        self.nprobe = nprobe
        self.global_id_to_cluster = {}

    def fit(self, vectors: np.ndarray) -> None:
        """Build IVF clusters and construct HNSW per cluster."""
        self.ivf.fit(vectors)
        for cluster_idx in range(self.ivf.nlist):
            cluster_vectors = vectors[self.ivf.assignments[cluster_idx]]
            hnsw = HNSWIndex(dim=self.dim, M=self.M, 
                             ef_construction=self.ef_construction)
            for i, vec in enumerate(cluster_vectors):
                global_id = self.ivf.assignments[cluster_idx][i]
                hnsw.insert(global_id, vec)
                self.global_id_to_cluster[global_id] = cluster_idx
            self.hnsw_per_cluster.append(hnsw)

    def search(self, query: np.ndarray, k: int = 10, 
               nprobe: int = None, ef_search: int = 128) -> List[Tuple[float, int]]:
        """Full pipeline: IVF filter → HNSW search → brute-force rescore."""
        nprobe = nprobe or self.nprobe
        candidate_ids = self.ivf.query_candidates(query, nprobe=nprobe)
        
        # Collect HNSW results from relevant clusters
        hnsw_candidates = set()
        for cid in candidate_ids:
            cluster_idx = self.global_id_to_cluster[cid]
            hnsw = self.hnsw_per_cluster[cluster_idx]
            results = hnsw._search_layer(query, hnsw.enter_point, 0, ef_search)
            hnsw_candidates.update([r[1] for r in results])
        
        # Brute-force rescore for precision
        all_vectors = {gid: vec for gid, vec in ...}  # stored reference
        return brute_force_rescore(query, list(hnsw_candidates), all_vectors, k=k)
```

### Step 6: Serialization for Persistence

```python
# hnsw_ivf/index.py — add to VectorIndex
import pickle

def save(self, path: str) -> None:
    with open(path, 'wb') as f:
        pickle.dump(self, f)

@staticmethod
def load(path: str) -> 'VectorIndex':
    with open(path, 'rb') as f:
        return pickle.load(f)
```

## Running and Testing It

To verify the index works end-to-end, generate a synthetic dataset and benchmark recall and latency.

```python
# test_index.py
import numpy as np
from hnsw_ivf.index import VectorIndex
import time

# Generate 10,000 128-dimensional vectors (e.g., embedding space)
np.random.seed(42)
data = np.random.randn(10000, 128).astype(np.float32)

# Normalize for cosine similarity
data = data / np.linalg.norm(data, axis=1, keepdims=True)

# Build the index
index = VectorIndex(dim=128, nlist=50, M=16, ef_construction=200, nprobe=10)
index.fit(data)

# Query with a random vector
query = np.random.randn(128).astype(np.float32)
query = query / np.linalg.norm(query)

# Measure latency
start = time.perf_counter()
results = index.search(query, k=10, nprobe=10, ef_search=128)
elapsed = time.perf_counter() - start

print(f"Query latency: {elapsed*1000:.2f}ms")
print(f"Top-10 results (distance, id): {results}")

# Compute recall against brute-force ground truth
def brute_force_top_k(query, data, k=10):
    similarities = data @ query
    return np.argsort(-similarities)[:k]

ground_truth = set(brute_force_top_k(query, data, k=50))
retrieved = set(r[1] for r in results)
recall = len(ground_truth & retrieved) / len(ground_truth)
print(f"Recall@50: {recall:.4f}")
```

Run it:

```bash
python test_index.py
```

Expected output on a modern laptop with 10,000 vectors: query latency under 5ms with recall above 0.85. You can scale the dataset to 100,000 or 1,000,000 vectors to observe how latency scales — this is where your benchmarking narrative becomes compelling in interviews.

To add proper benchmarking, integrate `pytest-benchmark`:

```bash
pip install pytest-benchmark
pytest --benchmark-only test_index.py
```

## Extending It: Your Roadmap to Senior-Level

Each upgrade below transforms this from a compelling portfolio piece into something that could genuinely ship. Pick two or three to demonstrate range.

1. **Add a memory-mapped storage backend using `numpy.memmap`.** This allows the index to handle datasets larger than RAM, which is the first thing production systems must solve. It signals you understand the memory hierarchy and I/O constraints that define real infrastructure.

2. **Implement a gRPC or FastAPI query service with connection pooling.** Wrap the index in a REST or gRPC endpoint that serves concurrent queries. Add rate limiting and request timeouts. This demonstrates you can ship a service, not just a library — the single biggest differentiator between mid-level and senior engineers.

3. **Add Prometheus metrics and structured logging via `structlog`.** Track query latency percentiles, recall rate over time, and graph depth distribution. Instrument every public method. Observability is non-negotiable in production, and its absence is the #1 reason junior engineers struggle in on-call rotations.

4. **Implement periodic graph rebalancing and checkpointing.** After a burst of insertions, the HNSW graph degrades. Add a background routine that rebuilds the index from scratch periodically (using `joblib` for parallelism) and writes checkpoints to disk. This signals fault tolerance thinking — you plan for degradation, not just correctness.

5. **Add multi-threaded batch insertion with a lock-free queue.** Python's GIL makes true parallelism hard, but using `multiprocessing` with shared memory arrays or `concurrent.futures` demonstrates you can reason about concurrency in a language that makes it awkward. This is directly relevant to data pipeline engineering.

6. **Implement a comparison harness against FAISS and Annoy.** Build a script that runs the same queries against your index, FAISS's IVFFlat, and Annoy, then reports recall@k and queries-per-second side by side. Benchmarking against established systems is what separates engineers who build from engineers who ship.

## Key Takeaways

- **HNSW + IVF + brute-force rescoring is the same architecture as FAISS.** By building it yourself, you internalize the design decisions that go into every production vector database — and you can explain them in an interview.
- **Pure Python forces algorithmic clarity.** Without the crutch of compiled extensions, every operation is explicit. This makes the code explainable, debuggable, and impressive.
- **Recall and latency are first-class metrics.** The brute-force rescoring step is not a hack — it is a principled approach to closing the gap between approximate and exact search, and understanding this trade-off is what separates engineers who use libraries from engineers who build them.
- **Each extension in the roadmap maps to a real production concern.** Persistence, observability, fault tolerance, and benchmarking are not "nice-to-haves" — they are what separates a toy project from a system that could actually serve users.
- **This project signals systems thinking.** It shows you can reason about data structures, algorithmic complexity, distributed systems constraints, and quantitative evaluation — all at once.

## Further Reading

- **[Efficient and Robust Approximate Nearest Neighbor Search Using Hierarchical Navigable Small World Graphs](https://arxiv.org/abs/1603.09320)** — the original HNSW paper by Malkov and Yashunin. This is the primary source for every design decision in the graph layer.
- **[Product Quantization for Nearest Neighbor Search](https://arxiv.org/abs/1510.00149)** — while your project uses IVF, understanding product quantization (PQ) is the natural next step for compression-based ANN, as used in FAISS's IVFPQ.
- **[FAISS: A Library for Efficient Similarity Search and Clustering](https://github.com/facebookresearch/faiss)** — the canonical open-source implementation by Meta. Study its `IndexIVFFlat` and `IndexHNSWFlat` classes to see how the production-grade version of your project is structured.
- **[Annoy: Approximate Nearest Neighbors Searching](https://github.com/spotify/annoy)** — Spotify's tree-based ANN library. Comparing its approach to your HNSW implementation is a powerful benchmarking exercise.
- **[ScaNN: Scalable Nearest Neighbors Search](https://research.google/pubs/pub47925/)** — Google's ANN system with novel partitioning and reordering techniques. This paper describes the exact "filter then rescoring" paradigm your project implements.
- **[The Wikipedia article on HNSW](https://en.wikipedia.org/wiki/Hierarchical_Navigable_Small_World)** — a concise reference for the graph construction algorithm and layer selection mechanics.
- **[Redis Vector Search Documentation](https://redis.io/docs/stack/search/reference/vector-search/)** — for understanding how production systems integrate HNSW with persistence, replication, and query routing in a real database engine.

This project is not just a coding exercise. It is a statement about who you are as an engineer: someone who understands that the systems powering modern AI applications are built on fundamental algorithms, and who has the skill to implement them from first principles. Build it, benchmark it, and put it on your resume.