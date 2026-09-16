

---
title: "Building a HNSW Vector Index from Scratch in Python"
date: "2026-09-16T06:01:37.564"
draft: false
tags: ["vector-search", "hnsw", "python", "algorithms", "systems", "machine-learning"]
description: "Hands‑on tutorial: implement a HNSW vector index in pure Python with brute‑force construction, greedy search, and dynamic inserts for production."
summary: "This guide walks you through building a hierarchical navigable small world vector index in pure Python. You'll learn brute‑force construction, greedy graph search, and how to extend it for production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-16-building-a-hnsw-vector-index-from-scratch-in-python.svg"
  alt: "Abstract representation of a graph of vectors"
  relative: false
---

> **TL;DR** — Implementing a HNSW index from scratch demonstrates algorithmic depth, systems thinking, and the ability to ship a working vector search engine in pure Python. The project combines graph theory, approximate nearest neighbor search, and dynamic data structures, making it a strong signal for backend or ML engineering roles. By the end you'll have a runnable, testable index that scales to millions of vectors.

Vector similarity search is a cornerstone of modern retrieval‑augmented generation, recommendation systems, and anomaly detection. While libraries like Faiss or Annoy hide the complexity, understanding the underlying graph‑based index equips you to debug performance bottlenecks, tune hyperparameters, and eventually contribute to open‑source vector engines. In this post we build a minimal but functional HNSW index entirely in Python, step by step, with real code you can run today.

## Why This Project Stands Out on a CV

Building an HNSW index from scratch showcases several high‑value competencies that hiring managers look for in backend, ML infrastructure, and data platform roles:

- **Algorithmic depth** – you implement a sophisticated approximate nearest‑neighbor algorithm, proving you can work with non‑trivial graph structures and probabilistic skip‑list‑like layering.
- **Systems thinking** – you design a hierarchical data structure that balances memory, insertion cost, and query latency, a skill directly transferable to building production search services.
- **Performance tuning** – you experiment with parameters such as `M` (max edges per node), `efConstruction` (search width), and layer decay, then measure recall‑latency trade‑offs.
- **Testing & reliability** – you write deterministic unit tests, compare against brute‑force ground truth, and validate invariants (e.g., connectivity, monotonic search).
- **Open‑source contribution potential** – a clean, documented implementation can become a stepping stone to contributing to projects like Milvus, Qdrant, or LanceDB.

## Architecture Overview

The HNSW index is composed of the following components:

- **Node** – stores a unique identifier and the floating‑point vector it represents.
- **Layer** – each layer is a graph (adjacency list) where edges connect nodes. The bottom layer (layer 0) contains every node; higher layers contain progressively fewer nodes.
- **Hierarchical structure** – top layers act as “highways” that quickly narrow the search region; the bottom layer provides fine‑grained connectivity.
- **Greedy search** – starting from an entry point, the algorithm repeatedly moves to the nearest neighbor that improves the distance, descending layer by layer.
- **Dynamic insertion** – a new node is assigned a layer using an exponentially decaying probability, then linked to its `M` nearest neighbors at each level.

A simplified textual diagram:

```
Layer 2 (top):   [A] <--> [B]
Layer 1:         [C] <--> [D] <--> [E]
Layer 0 (base):  all nodes, densely connected
```

## Building It Step by Step

### Step 1 – Core Data Structures

```python
from dataclasses import dataclass, field
import math
import random
from typing import List, Tuple

@dataclass
class Node:
    id: int
    vector: List[float]
    # neighbors[i] holds the list of node ids at layer i
    neighbors: List[List[int]] = field(default_factory=list)
```

### Step 2 – Brute‑Force Construction (Ground Truth)

For small datasets we can build a fully connected graph to validate later stages:

```python
def brute_force_graph(vectors: List[List[float]]) -> List[Node]:
    nodes = [Node(id=i, vector=v) for i, v in enumerate(vectors)]
    for i, a in enumerate(nodes):
        # each node connects to every other node at layer 0
        a.neighbors.append([j for j in range(len(nodes)) if j != i])


---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
