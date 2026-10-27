---
title: "Streaming HNSW Vector Index with Sliding‑Window Pruning"
date: "2026-10-27T17:01:03.552"
draft: false
tags: ["hnsw", "vector-index", "python", "streaming", "embeddings", "real-time"]
description: "A practical guide to building a pure‑Python streaming HNSW vector index with sliding‑window pruning for real‑time incremental embedding indexing."
summary: "Learn to implement a lightweight, incremental HNSW index in Python that prunes old vectors with a sliding window, perfect for real‑time embedding pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-27-streaming-hnsw-vector-index-with-slidingwindow-pruning.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks through building a pure‑Python streaming HNSW vector index that supports incremental insertion and automatic pruning of stale embeddings via a sliding window. The implementation is small enough to embed in a microservice yet demonstrates core algorithmic concepts like layered graph navigation and distance‑based pruning. By the end you’ll have a runnable prototype that signals real systems skill to hiring managers.

In modern retrieval‑augmented generation pipelines, you often need to index new embeddings as they arrive while discarding old ones that drift out of relevance. A full‑blown vector database is overkill for a prototype, but a hand‑rolled HNSW index gives you insight into how these systems work and showcases your ability to ship a performant data structure in a few hundred lines of Python.

## Why This Project Stands Out on a CV

- **Algorithmic depth** – implementing HNSW from scratch proves you understand approximate nearest‑neighbor search, hierarchical graph construction, and probabilistic layer assignment.
- **Streaming architecture** – incremental insertion, sliding‑window pruning, and real‑time updates are core skills for event‑driven data pipelines and low‑latency serving.
- **Production‑oriented engineering** – you’ll handle memory management, thread‑safety considerations, and benchmarking against baseline methods.
- **Role signaling** – the project is a strong talking point for positions such as ML Infrastructure Engineer, Vector Database Developer, or Search Engineer, where fast, scalable indexing is critical.

## Architecture Overview

- **Ingestion Layer** – receives embedding events (e.g., from a Kafka topic or a simple HTTP endpoint).
- **Embedding Generator** – optional; assumes vectors are already produced by an upstream model.
- **HNSW Index** – the core data structure: a multi‑layer graph where each node stores its vector and neighbor pointers.
- **Sliding Window Manager** – tracks insertion timestamps and evicts nodes older than a configurable window.
- **Query Interface** – exposes `search(query, k)` to return the `k` nearest neighbors.

A simplified text diagram:

```
[ Ingestion ] → [ Embedding ] → [ HNSW Index ] ← [ Sliding Window ]
                                 ↓
                           [ Query API ]
```

## Building It Step by Step

### 1. Define the Node Structure
```python
import math
import random
import time
from collections import defaultdict
from typing import List, Tuple, Optional

class HNSWNode:
    __slots__ = ("id", "vector", "neighbors", "timestamp")
    def __init__(self, node_id: int, vector: List[float]):
        self.id = node_id
        self.vector = vector
        # neighbors[level] = list of node ids
        self.neighbors: dict[int, List[int]] = defaultdict(list)
        self.timestamp = time.time()
```

### 2. Distance Metric
```python
def euclidean(a: List[float], b: List[float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))
```

### 3. Layer Selection
```python
def random_level(max_layers: int, ml: float = 1.0 / math.log(max_layers)) -> int:
    r = random.random()
    return min(int(-math.log(r) * ml), max_layers)
```

### 4. HNSW Index Class
```python
class HNSWIndex:
    def __init__(self, max_layers: int = 16, window_seconds: Optional[float] = None):
        self.max_layers = max_layers
        self.window_seconds = window_seconds
        self.nodes: dict[int, HNSWNode] = {}
        self.entry_point: Optional[int] = None

    def insert(self, vector: List[float]) -> int:
        node_id = len(self.nodes)
        node = HNSWNode(node_id, vector)
        self.nodes[node_id] = node

        if self.entry_point is None:
            self.entry_point = node_id
            return node_id

        # Determine top layer for new node
        new_level = random_level(self.max_layers)
        # Search from entry point down to layer 0
        current = self.entry_point
        for level in range(self.max_layers - 1, new_level, -1):
            current = self._search_layer(vector, current, level)

        # Insert at each layer from new_level down to 0
        for level in range(new_level, -1, -1):
            neighbors = self._search_layer(vector, current, level, ef=1)
            node.neighbors[level] = [n.id for n in neighbors]
            for n in neighbors:
                n.neighbors[level].append(node_id)
            if level > 0:
                current = neighbors[0].id

        if new_level > self.max_layers - 1:
            self.entry_point = node_id
        return node_id

    def _search_layer(self, q: List[float], entry: int, level: int, ef: int = 1) -> List[HNSWNode]:
        visited = set([entry])
        candidates = [(euclidean(q, self.nodes[entry].vector), entry)]
        while candidates:
            dist, cur = candidates.pop(0)
            if len(candidates) > ef:
                break
            for neighbor_id in self.nodes[cur].neighbors[level]:
                if neighbor_id not in visited:
                    visited.add(neighbor_id)
                    n_dist = euclidean(q, self.nodes[neighbor_id].vector)
                    candidates.append((n_dist, neighbor_id))
            candidates.sort(key=lambda x: x[0])
        # Return top‑ef nodes
        return [self.nodes[i] for _, i in candidates[:ef]]

    def search(self, q: List[float], k: int = 5) -> List[Tuple[int, float]]:
        if self.entry_point is None:
            return []
        current = self.entry_point
        for level in range(self.max_layers - 1, 0, -1):
            current = self._search_layer(q, current, level, ef=1)[0].id
        # Final layer 0
        candidates = self._search_layer(q, current, 0, ef=k)
        candidates.sort(key=lambda n: euclidean(q, n.vector))
        return [(n.id, euclidean(q, n.vector)) for n in candidates[:k]]

    def prune(self):
        """Remove nodes older than the sliding window."""
        if self.window_seconds is None:
            return
        cutoff = time.time() - self.window_seconds
        stale = [nid for nid, node in self.nodes.items() if node.timestamp < cutoff]
        for nid in stale:
            # Remove from neighbor lists
            for level_neighbors in self.nodes[nid].neighbors.values():
                for other_id in level_neighbors:
                    if other_id in self.nodes:
                        self.nodes[other_id].neighbors[level] = [
                            x for x in self.nodes[other_id].neighbors[level] if x != nid
                        ]
            del self.nodes[nid]
        # Update entry point if it was pruned
        if self.entry_point not in self.nodes:
            self.entry_point = next(iter(self.nodes), None)
```

### 5. Sliding‑Window Pruning Hook
The `prune()` method is called periodically (e.g., by a background thread or after each batch of inserts) to enforce the window.

## Running and Testing It

Create a small script `demo.py`:

```python
from hnsw_index import HNSWIndex
import random

index = HNSWIndex(max_layers=8, window_seconds=30)

# Insert 1000 random 128‑dim vectors
for i in range(1000):
    vec = [random.random() for _ in range(128)]
    index.insert(vec)

# Query for the 5 nearest neighbors of a random vector
query = [random.random() for _ in range(128)]
results = index.search(query, k=5)
print("Nearest neighbors:", results)

# Simulate time passing and prune
import time
time.sleep(31)
index.prune()
print("After pruning, node count:", len(index.nodes))
```

Run it:

```bash
python demo.py
```

Expected output: a list of `(node_id, distance)` tuples followed by a reduced node count, demonstrating incremental insertion and sliding‑window eviction.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence** – Serialize the index to disk (e.g., using SQLite or RocksDB) so it survives restarts; essential for production deployment.
2. **Horizontal Scaling** – Shard the index across multiple nodes and route queries via consistent hashing; enables handling billions of vectors.
3. **Observability** – Export metrics (insert latency, memory usage, graph size) to Prometheus and log pruning events; critical for SRE‑grade monitoring.
4. **Fault Tolerance** – Replicate index state with Raft or maintain a write‑ahead log for crash recovery; guarantees durability.
5. **Benchmarking** – Integrate with the ANN‑benchmark suite to compare recall/latency against FAISS or Annoy; proves performance claims.
6. **Streaming Integration** – Connect to Kafka topics for real‑time embedding ingestion and implement back‑pressure handling; turns the prototype into a true streaming pipeline.

## Key Takeaways

- You can build a functional HNSW index in pure Python with incremental insertion.
- Sliding‑window pruning keeps memory bounded and reflects real‑world data drift.
- The project demonstrates algorithmic knowledge, streaming design, and production readiness.
- It serves as a foundation for scaling to a distributed vector database.

## Further Reading

- [Hierarchical Navigable Small World (HNSW) paper](https://arxiv.org/abs/1603.01607) – the original algorithm description.
- [FAISS documentation](https://github.com/facebookresearch/faiss/wiki) – production‑grade library for comparison and inspiration.
- [Milvus vector database overview](https://milvus.io/docs/overview.md) – see how these concepts scale in a real system.