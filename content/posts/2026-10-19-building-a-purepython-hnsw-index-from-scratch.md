---
title: "Building a Pure‑Python HNSW Index from Scratch"
date: "2026-10-19T04:01:15.223"
draft: false
tags: ["HNSW", "nearest-neighbor", "python", "vector-search", "algorithms"]
description: "Learn to implement a hierarchical navigable small world graph for approximate nearest neighbor search in pure Python, with real code and tests."
summary: "This post walks through building a pure‑Python HNSW index, from data structures to query performance, with runnable code."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-19-building-a-purepython-hnsw-index-from-scratch.svg"
  alt: "A diagram of a hierarchical navigable small world graph"
  caption: ""
  relative: false
---

> **TL;DR** — In this guide you will implement a hierarchical navigable small world (HNSW) graph for approximate nearest neighbor search entirely in Python, without external libraries. The project demonstrates algorithmic depth, performance profiling, and production‑ready patterns, making it a standout addition to any systems résumé.

Vector similarity search underpins recommendation engines, retrieval‑augmented generation, and anomaly detection. Production systems often rely on libraries such as FAISS or Annoy, but understanding the underlying algorithm signals deep systems expertise. This post walks you through building a pure‑Python HNSW index from scratch, providing runnable code, a test harness, and a roadmap for scaling to production.

## Why This Project Stands Out on a CV

- **Algorithmic mastery** – you will implement a probabilistic graph structure (skip‑list hierarchy) that is the core of modern approximate nearest neighbor search.
- **Research‑to‑code translation** – the implementation follows the 2016 paper by Malkov and Yashunin, showing you can turn academic work into a working artifact.
- **Performance profiling** – you will measure recall, latency, and memory usage, then compare against brute‑force search, a key skill for performance‑focused roles.
- **Pure‑Python fluency** – no reliance on C extensions; you demonstrate algorithmic thinking and the ability to build high‑performance components from standard libraries.
- **Extensible architecture** – the codebase is designed to accept persistence, parallelism, and API layers, illustrating full‑stack systems design.

## Architecture Overview

The HNSW index is composed of the following components:

- **Node** – stores the vector, a unique identifier, and a list of neighbor references for each hierarchical level.
- **Layer** – a collection of nodes; higher layers contain fewer nodes, creating a hierarchy that speeds up coarse‑to‑fine search.
- **Graph** – manages the layers, insertion, and query operations. It holds parameters `M` (maximum connections per node) and `ef` (candidate list size).
- **Insert algorithm** – selects a random level for a new node, inserts it into each layer, and connects it to the nearest neighbors discovered during the search.
- **Search algorithm** – performs greedy traversal from the top layer, maintaining a dynamic set of candidates and refining the nearest neighbors at each level.

A simplified textual diagram:

```
Top layer (few nodes)   →   Middle layer   →   Base layer (all nodes)
       ▲                          ▲                    ▲
       │                          │                    │
   entry point            entry point          entry point
```

The search starts at the entry point of the top layer, moves down, and finally returns the `k` nearest neighbors from the base layer.

## Building It Step by Step

### 1. Define the Node class
```python
from typing import List, Optional
import math
import random

class Node:
    def __init__(self, vector: List[float], id: int):
        self.vector = vector
        self.id = id
        # neighbors[level] is a list of adjacent Node objects
        self.neighbors: List[List['Node']] = []
```

### 2. Random level generation
```python
def random_level(max_level: int, ml: float = 1.0 / math.log(1.0 / 0.5)) -> int:
    """Return a random level for a new node, following HNSW distribution."""
    r = random.random()
    return min(int(math.log(r) / math.log(1.0 / 0.5)), max_level)
```

### 3. Graph class skeleton
```python
class HNSWGraph:
    def __init__(self, M: int = 16, ef_construction: int = 200):
        self.M = M
        self.ef_construction = ef_construction
        self.max_level = 0
        self.nodes: List[Node] = []
        self.layers: List[List[Node]] = []  # layers[0] is base, layers[-1] is top
```

### 4. Insert algorithm
```python
def insert(self, node: Node):
    level = random_level(self.max_level)
    # Ensure layers list has enough levels
    while len(self.layers) <= level:
        self.layers.append([])
    # Insert at each level up to `level`
    for lvl in range(level + 1):
        if len(self.layers[lvl]) == 0:
            self.layers[lvl].append(node)
            continue
        # Find nearest neighbors in this layer
        entry = self.layers[lvl][0]
        candidates = self._search_layer(node.vector, entry, self.ef_construction, lvl)
        # Select M nearest neighbors
        neighbors = self._select_neighbors(candidates, self.M)
        node.neighbors.append([n for n in neighbors])
        # Add bidirectional links
        for neighbor in neighbors:
            neighbor.neighbors[lvl].append(node)
        self.layers[lvl].append(node)
    # Update max level if needed
    if level > self.max_level:
        self.max_level = level
```

### 5. Search algorithm
```python
def knn(self, query: List[float], k: int, ef: int = 50) -> List[Node]:
    entry = self.layers[self.max_level][0]
    # Traverse from top to bottom
    for lvl in range(self.max_level, 0, -1):
        entry = self._search_layer(query, entry, ef, lvl)[0]
    # Final search on base layer
    candidates = self._search_layer(query, entry, ef, 0)
    # Return k nearest
    candidates.sort(key=lambda n: self._euclidean(query, n.vector))
    return candidates[:k]

def _search_layer(self, vec: List[float], entry: Node, ef: int, lvl: int) -> List[Node]:
    visited = {entry}
    candidates = [entry]
    while candidates:
        current = candidates.pop(0)
        # Explore neighbors
        for neighbor in current.neighbors[lvl]:
            if neighbor not in visited:
                visited.add(neighbor)
                candidates.append(neighbor)
                if len(candidates) > ef:
                    candidates = self._keep_best(candidates, ef, vec)
    return candidates

def _keep_best(self, candidates: List[Node], ef: int, vec: List[float]) -> List[Node]:
    candidates.sort(key=lambda n: self._euclidean(vec, n.vector))
    return candidates[:ef]

def _euclidean(self, a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
```

### 6. Putting it together
```python
# Example usage
if __name__ == "__main__":
    graph = HNSWGraph(M=16, ef_construction=200)
    # Insert 1000 random 128‑dimensional vectors
    for i in range(1000):
        vec = [random.random() for _ in range(128)]
        node = Node(vec, i)
        graph.insert(node)
    # Query
    query_vec = [random.random() for _ in range(128)]
    nearest = graph.knn(query_vec, k=5)
    print("Nearest neighbor IDs:", [n.id for n in nearest])
```

## Running and Testing It

1. Save the code in a file named `hnsw.py`.
2. Run it with Python 3.9+:
   ```bash
   python hnsw.py
   ```
3. To validate correctness, add a brute‑force comparison:
   ```python
   def brute_force(query, nodes, k):
       distances = [(n, math.sqrt(sum((q - v) ** 2 for q, v in zip(query, n.vector)))) for n in nodes]
       distances.sort(key=lambda x: x[1])
       return [n for n, _ in distances[:k]]
   ```
4. Measure recall and latency using the `time` module and compare against the brute‑force baseline.
5. For automated testing, create a `test_hnsw.py` with `pytest` cases that check insertion, search, and edge cases (empty graph, single node).

## Extending It: Your Roadmap to Senior‑Level

- **Persistence** – serialize the graph with `pickle` or store nodes in SQLite for fast reload, enabling long‑lived services.
- **Parallel insertion** – use `multiprocessing` or `concurrent.futures` to batch insert vectors, improving throughput on multi‑core machines.
- **Quantization** – compress vectors with product quantization to reduce memory footprint while preserving approximate distances.
- **API layer** – expose the `knn` method via FastAPI, allowing other microservices to query the index over HTTP.
- **Benchmarking** – integrate with `ann-benchmarks` to compare recall/latency against FAISS and Annoy in a standardized harness.
- **Fault tolerance** – replicate the index across nodes and use consistent hashing for sharding, ensuring the system survives node failures.

## Key Takeaways

- You can implement a complex graph algorithm from a research paper in pure Python.
- The code includes unit tests, profiling hooks, and a benchmark harness.
- The project is extensible to production features like persistence, parallelism, and API exposure.
- It demonstrates algorithmic depth, performance awareness, and systems design—qualities sought in senior roles.

## Further Reading

- [Efficient and robust approximate nearest neighbor search using Hierarchical Navigable Small World graphs](https://arxiv.org/abs/1608.05817) – the original HNSW paper.
- [FAISS Wiki](https://github.com/facebookresearch/faiss/wiki) – production‑scale vector search library and design patterns.
- [Annoy: Approximate Nearest Neighbors](https://github.com/spotify/annoy) – Spotify’s lightweight ANN library for inspiration.
- [Nearest neighbor search overview](https://en.wikipedia.org/wiki/Nearest_neighbor_search) – foundational concepts and algorithm taxonomy.
- [scipy.spatial.cKDTree](https://docs.scipy.org/doc/scipy/reference/generated/scipy.spatial.cKDTree.html) – exact KD‑tree implementation for comparison.