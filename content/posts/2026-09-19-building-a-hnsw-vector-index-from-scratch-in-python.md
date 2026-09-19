

---
title: "Building a HNSW Vector Index from Scratch in Python"
date: "2026-09-19T19:01:36.217"
draft: false
tags: ["vector-search", "hnsw", "python", "systems", "portfolio"]
description: "A practical guide to implementing an approximate nearest neighbor search engine using HNSW, with runnable Python code and production‑grade extensions."
summary: "Learn to build a HNSW‑based vector index from scratch, demonstrating systems skills that catch hiring managers' eyes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-19-building-a-hnsw-vector-index-from-scratch-in-python.svg"
  alt: "A stylized graph of nodes and edges representing an HNSW index"
  caption: ""
  relative: false
---

> **TL;DR** — You will build a fully functional HNSW vector index from scratch in Python, with real insertion, search, and persistence. The implementation is benchmarked against brute‑force search to demonstrate speedup, and it includes hooks for scaling to millions of vectors. This project highlights algorithmic mastery, performance engineering, and production‑oriented design—skills that hiring managers actively seek.

Vector similarity search underpins everything from recommendation engines to image retrieval. While libraries like FAISS and Annoy provide off‑the‑shelf solutions, implementing the core algorithm yourself signals a deep understanding of data structures, probability, and performance tuning—exactly what senior engineering roles look for. In this guide you will construct a Hierarchical Navigable Small World (HNSW) graph from the ground up, test it on real embeddings, and outline a roadmap to turn this prototype into a production service.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – you implement HNSW insertion, layer selection, and greedy search, showing you can reason about probabilistic data structures.
- **Performance engineering** – you profile with `cProfile`, use `numpy` vectorization, and compare against brute‑force to quantify speedup.
- **Systems design** – you design a serializable graph format, consider memory layout, and plan for horizontal scaling.
- **Production readiness** – you add persistence, basic observability, and fault‑tolerant patterns.
- **Role alignment** – directly relevant for Machine Learning Engineer, Vector Database Engineer, Backend Engineer, and Data Infrastructure positions.

## Architecture Overview

The system is composed of the following components:

- **Node** – stores a `numpy` vector, its hierarchical level, and per‑layer adjacency lists.
- **Graph** – maintains the entry point, maximum level, and a list of all nodes.
- **Level generator** – probabilistic `random_level()` function using exponential decay.
- **Insert algorithm** – selects an entry point, traverses to find candidate neighbors, and links them bidirectionally.
- **Search algorithm** – top‑down greedy search followed by a refined bottom‑layer scan.
- **Persistence layer** – serializes the graph to JSON or Protocol Buffers for later reuse.

A simplified textual diagram of the hierarchy:

```
Entry point (top layer)
   |
   v
Layer 2 (few nodes, long edges)
   |
   v
Layer 1 (more nodes, medium edges)
   |
   v
Layer 0 (all nodes, short edges)
```

## Building It Step by Step

### 1. Set up the environment

```bash
python -m venv hnsw-env
source hnsw-env/bin/activate
pip install numpy scipy
```

### 2. Define the core data structures

```python
import numpy as np
import random
import json
from typing import List, Dict, Optional, Tuple

class Node:
    __slots__ = ('vector', 'level', 'neighbors')
    def __init__(self, vector: np.ndarray):
        self.vector = vector.astype(np.float32)
        self.level = 0
        self.neighbors: Dict[int, List['Node']] = {}
```

### 3. Implement random level generation

```python
def random_level(p: float = 0.5, max_level: int = 10) -> int:
    level = 0
    while random.random() < p:
        level += 1
    return min(level, max_level)
```

### 4. Build the HNSW class

```python
class HNSW:
    def __init__(self, M: int = 16, Mmax: int = 16, p: float = 0.5):
        self.M = M
        self.Mmax = Mmax
        self.p = p
        self.nodes: List[Node] = []
        self.entry_point: Optional[Node] = None
        self.max_level = -1

    def _search_layer(self, query: np.ndarray, entry: Node, layer: int, ef: int = 10) -> List[Node]:
        visited = {entry}
        heap = [(np.linalg.norm(query - entry.vector), entry)]
        while heap:
            dist, curr = heap.pop(0)
            for neighbor in curr.neighbors.get(layer, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    d = np.linalg.norm(query - neighbor.vector)
                    if len(heap) < ef or d < heap[-1][0]:
                        heap.append((d, neighbor))
                        heap.sort(key=lambda x: x[0])
        return [node for _, node in heap[:ef]]

    def insert(self, vector: np.ndarray):
        new_node = Node(vector)
        new_node.level = random_level(self.p)
        if self.entry_point is None:
            self.entry_point = new_node
            self.max_level = new_node.level
            self.nodes.append(new_node)
            return
        # traverse from top to the new node's level
        curr = self.entry_point
        for layer in range(self.max_level, new_node.level, -1):
            best = curr
            best_dist = np.linalg.norm(vector - curr.vector)
            for neighbor in curr.neighbors.get(layer, []):
                d = np.linalg.norm(vector - neighbor.vector)
                if d < best_dist:
                    best_dist = d
                    best = neighbor
            curr = best
        # insert at each layer from new_node.level down to 0
        for layer in range(new_node.level, -1, -1):
            neighbors = self._search_layer(vector, curr, layer, ef=self.M)
            new_node.neighbors[layer] = neighbors
            for n in neighbors:
                if layer not in n.neighbors:
                    n.neighbors[layer] = []
                n.neighbors[layer].append(new_node)
                # prune to maintain bounded degree
                if len(n.neighbors[layer]) > self.Mmax:
                    n.neighbors[layer].sort(key=lambda x: np.linalg.norm(n.vector - x.vector))
                    n.neighbors[layer] = n.neighbors[layer][:self.Mmax]
            curr = neighbors[0] if neighbors else curr
        self.nodes.append(new_node)
        if new_node.level > self.max_level:
            self.max_level = new_node.level
            self.entry_point = new_node

    def search(self, query: np.ndarray, k: int = 1, ef: int = 10) -> List[Tuple[Node, float]]:
        if self.entry_point is None:
            return []
        # top‑down greedy descent
        curr = self.entry_point
        for layer in range(self.max_level, 0, -1):
            best = curr
            best_dist = np.linalg.norm(query - curr.vector)
            for neighbor in curr.neighbors.get(layer, []):
                d = np.linalg.norm(query - neighbor.vector)
                if d < best_dist:
                    best_dist = d
                    best = neighbor
            curr = best
        # bottom‑layer search
        candidates = self._search_layer(query, curr, 0, ef=ef)
        candidates.sort(key=lambda n: np.linalg.norm(query - n.vector))
        return [(n, np.linalg.norm(query - n.vector)) for n in candidates[:k]]

    def serialize(self) -> str:
        data = {
            'M': self.M,
            'Mmax': self.Mmax,
            'p': self.p,
            'max_level': self.max_level,
            'nodes': []
        }
        for node in self.nodes:
            node_data = {
                'vector': node.vector.tolist(),
                'level': node.level,
                'neighbors': {}
            }
            for layer, neighs in node.neighbors.items():
                node_data['neighbors'][str(layer)] = [self.nodes.index(n) for n in neighs]
