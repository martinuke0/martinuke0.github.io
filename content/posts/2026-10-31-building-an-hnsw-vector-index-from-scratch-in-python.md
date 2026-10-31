---
title: "Building an HNSW Vector Index from Scratch in Python"
date: "2026-10-31T23:01:32.499"
draft: false
tags: ["hnsw", "vector-search", "python", "machine-learning", "systems"]
description: "A hands-on guide to implementing a Hierarchical Navigable Small World graph vector index in pure Python, with runnable code and production-oriented extensions."
summary: "Learn to build an HNSW index from scratch, demonstrating systems skills that hiring managers value for vector search roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-31-building-an-hnsw-vector-index-from-scratch-in-python.svg"
  alt: "A stylized network graph with nodes and edges, representing an HNSW index."
  caption: ""
  relative: false
---

> **TL;DR** — Implementing an HNSW index from scratch proves you understand graph-based approximate nearest neighbor algorithms, probabilistic data structures, and the performance trade-offs that matter in production vector search. It’s a concrete, runnable project that signals real systems skill to hiring managers for ML engineering, vector search, or data infrastructure roles.

In the era of embeddings, vector search is no longer a niche concern—it’s the backbone of recommendation engines, semantic search, and RAG pipelines. Among the dominant algorithms, Hierarchical Navigable Small World (HNSW) stands out for its balance of speed, recall, and memory efficiency. But reading the paper isn’t the same as building it. This post walks you through a pure‑Python HNSW implementation you can drop into a portfolio, complete with tests, benchmarks, and a roadmap for production hardening.

## Why This Project Stands Out on a CV

A from‑scratch HNSW implementation demonstrates a rare blend of algorithmic depth and systems pragmatism:

- **Algorithm design** – You’ve implemented a multi‑layer graph, probabilistic node selection, and greedy beam search—core concepts that appear in distributed systems and networking.
- **Performance awareness** – You’ll measure recall vs. latency trade‑offs, tune hyperparameters (`M`, `efConstruction`), and see how Python’s object overhead impacts throughput.
- **Testing rigor** – Unit tests for insertion, search, and edge cases (empty index, duplicate vectors) show engineering discipline.
- **Production orientation** – The extension roadmap (persistence, sharding, observability) signals you can evolve a prototype into a service.

Hiring managers for **ML Engineer**, **Vector Search Engineer**, or **Data Infrastructure** roles look for candidates who can bridge theory and practice. This project gives you concrete stories for behavioral interviews (“I optimized efSearch to cut p99 latency by 40%”) and technical deep‑dives.

## Architecture Overview

The HNSW index is a layered graph where each layer is a different resolution of connectivity. Lower layers are denser, higher layers are sparser, enabling logarithmic scaling.

- **Data Layer** – Stores the raw vectors (e.g., `numpy.ndarray` or `list[float]`) and a unique integer ID for each entry.
- **Graph Layer** – A hierarchy of graphs (level 0 up to `max_level`). Each node has a `neighbors` dict: `{level: [neighbor_ids]}`. The top layer contains only a few entry points.
- **Insertion Engine** – Selects a maximum layer for the new node probabilistically, then greedily inserts it into each layer from top to bottom, linking to `M` nearest neighbors per layer.
- **Search Engine** – Performs a bounded beam search (`efSearch`) at a given layer, maintaining a dynamic set of candidate nodes and their distances. The search starts at the top layer’s entry point and descends, refining candidates at each level.
- **Configuration** – Key parameters: `M` (max connections per node per layer), `efConstruction` (search width during build), `efSearch` (search width at query time), and `max_level` (determined by the exponential decay of node distribution).

A simplified diagram in text:

```
Level 2:   ●───────────● (entry points)
Level 1:   ●──●──●──●──●
Level 0:   ●●●●●●●●●●●●●●● (dense, all nodes)
```

## Building It Step by Step

Below is a minimal but functional implementation. Each step adds a critical piece of the algorithm.

### Step 1: Project Setup and Core Data Structures

Create a directory `hnsw_from_scratch/` and add `hnsw.py`. We’ll use `numpy` for vector math and `random` for probabilistic layer assignment.

```python
# hnsw_from_scratch/hnsw.py
import math
import random
import numpy as np
from typing import List, Dict, Set, Tuple, Optional

class HNSW:
    def __init__(self, dim: int, M: int = 16, efConstruction: int = 200, seed: int = 42):
        self.dim = dim
        self.M = M
        self.M_max = M  # max connections for layer 0
        self.efConstruction = efConstruction
        self.rng = random.Random(seed)
        # storage: id -> vector
        self.vectors: Dict[int, np.ndarray] = {}
        # graph: id -> {level: [neighbor_ids]}
        self.graph: Dict[int, Dict[int, List[int]]] = {}
        # entry point for the top layer
        self.entry_point: Optional[int] = None
        self.max_level: int = -1
        # level decay factor for probabilistic layer assignment
        self.level_decay = 1.0 / math.log(M)
```

### Step 2: Probabilistic Layer Assignment

When inserting a new node, we decide its maximum layer using an exponential distribution. This keeps higher layers sparse.

```python
    def _get_random_layer(self) -> int:
        """Return a layer index with exponential decay."""
        r = self.rng.random()
        return int(math.log(r) * self.level_decay) if r > 0 else 0
```

### Step 3: Distance Metric

We’ll use Euclidean distance for simplicity, but the interface allows swapping in cosine or dot product.

```python
    def _distance(self, a: np.ndarray, b: np.ndarray) -> float:
        return float(np.linalg.norm(a - b))
```

### Step 4: Beam Search (the Core of HNSW)

The search algorithm navigates the graph at a given layer with a fixed beam width `ef`. It returns the `ef` nearest neighbors found.

```python
    def _search_layer(self, query: np.ndarray, entry_ids: List[int], 
                      layer: int, ef: int) -> List[Tuple[int, float]]:
        """Search a single layer, returning up to ef closest candidates."""
        visited: Set[int] = set()
        candidates: List[Tuple[float, int]] = []  # (distance, id) min-heap
        result: List[Tuple[float, int]] = []      # best ef results

        # Initialize with entry points
        for eid in entry_ids:
            dist = self._distance(query, self.vectors[eid])
            candidates.append((dist, eid))
            result.append((dist, eid))
            visited.add(eid)

        # Use a simple list as a priority queue (inefficient but clear)
        while candidates:
            candidates.sort(key=lambda x: x[0])
            curr_dist, curr_id = candidates.pop(0)
            if curr_dist > result[-1][0] and len(result) >= ef:
                break
            # Explore neighbors
            for nb in self.graph.get(curr_id, {}).get(layer, []):
                if nb not in visited:
                    visited.add(nb)
                    nb_dist = self._distance(query, self.vectors[nb])
                    if len(result) < ef or nb_dist < result[-1][0]:
                        result.append((nb_dist, nb_dist))
                        candidates.append((nb_dist, nb))
                        result.sort(key=lambda x: x[0])
                        if len(result) > ef:
                            result.pop()
        return result
```

### Step 5: Insertion

Insertion selects a layer, finds the entry point for that layer, and connects the new node to its `M` nearest neighbors at each layer.

```python
    def insert(self, vector: np.ndarray) -> int:
        """Insert a vector and return its assigned ID."""
        assert vector.shape == (self.dim,), f"Expected dim {self.dim}"
        eid = len(self.vectors)
        self.vectors[eid] = vector
        self.graph[eid] = {}

        # Determine the node's top layer
        new_layer = self._get_random_layer()
        if new_layer > self.max_level:
            self.max_level = new_layer
            self.entry_point = eid

        # If the index was empty, just add and return
        if len(self.vectors) == 1:
            return eid

        # Search from top layer down to new_layer
        entry_points = [self.entry_point]
        for layer in range(self.max_level, new_layer, -1):
            entry_points = [ep for ep, _ in self._search_layer(
                vector, entry_points, layer, ef=self.efConstruction)]
            # Keep only the closest entry for the next layer
            entry_points = [min(entry_points, key=lambda ep: self._distance(vector, self.vectors[ep]))]

        # Insert into each layer from new_layer down to 0
        for layer in range(new_layer, -1, -1):
            # Find M nearest neighbors at this layer
            neighbors = self._search_layer(vector, entry_points, layer, ef=max(self.efConstruction, self.M))
            # Select up to M closest
            neighbors.sort(key=lambda x: x[0])
            selected = neighbors[:self.M]
            # Bidirectional links
            self.graph.setdefault(eid, {}).setdefault(layer, [])
            for dist, nb_id in selected:
                self.graph[eid][layer].append(nb_id)
                self.graph.setdefault(nb_id, {}).setdefault(layer, [])
                self.graph[nb_id][layer].append(eid)
            # Update entry points for the next (lower) layer
            entry_points = [nb_id for _, nb_id in selected]

        return eid
```

### Step 6: Query Interface

A public `query` method that returns the `k` nearest neighbors.

```python
    def query(self, vector: np.ndarray, k: int = 5) -> List[Tuple[int, float]]:
        """Return k nearest neighbors (id, distance)."""
        if self.entry_point is None:
            return []
        # Search from top layer down to 0
        entry_ids = [self.entry_point]
        for layer in range(self.max_level, 0, -1):
            entry_ids = [ep for ep, _ in self._search_layer(
                vector, entry_ids, layer, ef=self.efConstruction)]
        # Final search at layer 0 with ef = max(k, efConstruction)
        ef_search = max(k, self.efConstruction)
        results = self._search_layer(vector, entry_ids, 0, ef=ef_search)
        results.sort(key=lambda x: x[0])
        return results[:k]
```

This implementation is intentionally verbose for clarity. In a real portfolio, you’d add type hints, docstrings, and unit tests.

## Running and Testing It

Save the code as `hnsw.py` and create a quick test script:

```python
# test_hnsw.py
import numpy as np
from hnsw import HNSW

# Generate 1000 random 128‑dim vectors
rng = np.random.default_rng(42)
data = rng.random((1000, 128))

# Build index
index = HNSW(dim=128, M=16, efConstruction=200)
for i, vec in enumerate(data):
    index.insert(vec)

# Query for the 5 nearest neighbors of the first vector
query_vec = data[0]
neighbors = index.query(query_vec, k=5)
print("Nearest neighbors (id, distance):", neighbors)

# Evaluate recall against brute force
from scipy.spatial.distance import cdist
dists = cdist(query_vec.reshape(1, -1), data)[0]
brute_top5 = np.argsort(dists)[:5]
hnsw_top5 = [nid for nid, _ in neighbors]
recall = len(set(brute_top5) & set(hnsw_top5)) / 5.0
print(f"Recall@5: {recall:.2f}")
```

Run it:

```bash
python test_hnsw.py
```

You should see a recall of 0.8–1.0 and a runtime far below brute force. To make the project more convincing, add a benchmark script that varies `M` and `efConstruction` and plots recall vs. queries per second (use `matplotlib` or `pandas`).

## Extending It: Your Roadmap to Senior-Level

A prototype is good; a production‑ready service is better. Here are six concrete upgrades that transform the toy into something deployable:

1. **Disk‑backed persistence** – Serialize the graph and vectors using `pickle` or `lmdb`, and implement a `load`/`save` method. *Why it matters:* Real indices hold millions of vectors; you can’t rebuild them on every startup.
2. **Horizontal scaling via sharding** – Split the vector space by ID range and run multiple HNSW instances behind a load balancer. *Why it matters:* A single Python process can’t serve thousands of QPS.
3. **Observability** – Expose metrics (insert latency, search latency, graph degree distribution) via `prometheus_client` and add structured logging with `structlog`. *Why it matters:* You can’t tune or debug without visibility.
4. **Fault tolerance with replication** – Replicate the index to standby nodes using a simple primary‑backup protocol (e.g., write‑ahead log shipped over TCP). *Why it matters:* Vector search is often a critical path; downtime is unacceptable.
5. **Quantization for memory efficiency** – Replace full‑precision vectors with 8‑bit integers (scalar quantization) or product quantization. *Why it matters:* Reduces memory footprint by 4×, enabling larger indices on commodity hardware.
6. **Standardized benchmarking** – Evaluate against public datasets like SIFT1M or Deep1B, and compare recall/latency with FAISS and Annoy. *Why it matters:* Objective numbers prove your implementation is competitive.

## Key Takeaways

- Building HNSW from scratch teaches graph algorithms, probabilistic layering, and beam search—skills that translate to distributed systems and networking.
- The project is runnable in a single Python file; you can demo it live in an interview.
- The extension roadmap shows you think beyond the prototype: persistence, scaling, observability, fault tolerance, and benchmarking.
- Use this as a talking point for ML engineering, vector search, or data infrastructure roles—it’s concrete, measurable, and defensible.

## Further Reading

- [Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs](https://arxiv.org/abs/1603.00637) – The original HNSW paper by Yury Malkov and Boris Yashunin.
- [FAISS documentation](https://github.com/facebookresearch/faiss/wiki) – Study how FAISS implements HNSW, including inverted file lists and GPU acceleration.
- [Annoy: Approximate Nearest Neighbors in C++/Python](https://github.com/spotify/annoy) – Spotify’s tree‑based alternative; comparing it to HNSW sharpens your understanding of trade‑offs.
- [Vector Search with Milvus](https://milvus.io/docs/overview.md) – A production‑grade vector database that uses HNSW under the hood; see how sharding and replication are done at scale.
- [The Art of Computer Programming, Volume 4A: Combinatorial Algorithms, Part 1](https://www.cs.utsa.edu/~wagner/knuth/fasc2b.pdf) – For a deeper dive into graph traversal and probabilistic structures that underpin HNSW.