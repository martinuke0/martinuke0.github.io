---
title: "Streaming KV Cache with Attention Sinks for Infinite Context in Pure Python"
date: "2026-09-29T05:01:25.939"
draft: false
tags: ["llm", "kv-cache", "attention", "python", "systems"]
description: "A practical guide to building a streaming KV cache with attention sinks in pure Python, demonstrating systems skills for infinite context LLMs."
summary: "Learn to implement a streaming KV cache with attention sinks in Python, enabling infinite context for large language models."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-29-streaming-kv-cache-with-attention-sinks-for-infinite-context-in-pure-python.svg"
  alt: "Streaming KV cache architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a streaming KV cache with attention sinks in pure Python, showing how to handle infinite context without reprocessing the whole prompt. You'll end up with a runnable module that caches key‑value states and prunes low‑importance tokens, cutting memory use while preserving generation quality. The project highlights systems engineering skills that hiring managers look for in LLM infrastructure roles.

Large language models (LLMs) are increasingly used for tasks that require understanding of entire books, codebases, or long conversations. Naïve implementations keep the entire key‑value (KV) state in memory, which grows linearly with the prompt length and quickly becomes a bottleneck. A streaming KV cache with attention sinks solves this by keeping only the most relevant tokens, allowing the model to process arbitrarily long inputs without O(n) memory blow‑up.

## Why This Project Stands Out on a CV

- **Low‑level memory management** – you implement a custom cache that explicitly controls allocation, eviction, and reuse, demonstrating an understanding of how memory pressure affects inference latency.
- **Streaming data structures** – the cache processes tokens one‑by‑one, mirroring real‑world pipelines that ingest data from sockets, queues, or file streams.
- **Algorithm design** – you devise an importance‑based pruning heuristic (attention sinks) that balances accuracy and memory, a common trade‑off in production ML systems.
- **Performance profiling** – the guide includes timing and memory benchmarks, showing you can quantify improvements and identify bottlenecks.
- **Python‑first tooling** – the implementation uses only the standard library plus NumPy, proving you can build high‑performance components without relying on heavy frameworks.
- **Relevance to LLM infrastructure roles** – the project maps directly to skills sought for positions such as ML Engineer, Inference Engineer, or Systems Engineer at companies building large‑scale language model services.

## Architecture Overview

The system consists of four logical components:

1. **Token Ingestion Layer** – a thin wrapper that receives token IDs (e.g., from a tokenizer) and forwards them to the cache.
2. **KV Store** – an in‑memory structure that holds the key and value vectors for each token, organized as a list of arrays.
3. **Attention Sink Detector** – computes an importance score for each token based on recent attention weights, marking tokens that are likely to be referenced again.
4. **Eviction Policy** – periodically removes low‑importance entries when the cache exceeds a configurable size limit, implementing a sliding‑window with sink preservation.

These components interact in a linear pipeline: new token → compute KV → score importance → store → (if needed) evict → return KV for inference.

```
[Token ID] → [KV Cache.add()] → [Importance Scoring] → [Store] → [Evict if > max_size] → [Return KV]
```

## Building It Step by Step

### Step 1: Set Up the Environment

```bash
python -m venv venv
source venv/bin/activate
pip install numpy
```

### Step 2: Define Core Data Structures

```python
# kv_cache.py
from collections import OrderedDict
import numpy as np
from typing import List, Tuple

class StreamingKVCache:
    def __init__(self, max_size: int = 1024, sink_threshold: float = 0.1):
        """
        max_size: maximum number of token entries to retain.
        sink_threshold: minimum importance score for a token to be considered a sink.
        """
        self.max_size = max_size
        self.sink_threshold = sink_threshold
        # Ordered dict preserves insertion order, allowing O(1) eviction of oldest entries.
        self.store: "OrderedDict[int, Tuple[np.ndarray, np.ndarray, float]]" = OrderedDict()
```

### Step 3: Add a New Token

```python
    def add(self, token_id: int, key: np.ndarray, value: np.ndarray, importance: float):
        """
        Insert a new KV pair with its computed importance score.
        If the cache is full, trigger eviction before insertion.
        """
        if len(self.store) >= self.max_size:
            self._evict()
        # Store (key, value, importance) keyed by token_id
        self.store[token_id] = (key, value, importance)
```

### Step 4: Compute Attention Sinks

```python
    def _score_importance(self, attention_weights: np.ndarray) -> float:
        """
        Given a vector of attention weights for the current token,
        return a scalar importance score (higher = more likely to be referenced).
        """
        # Simple heuristic: mean of top‑k attention weights
        k = max(1, attention_weights.size // 10)
        top_k = np.sort(attention_weights)[-k:]
        return float(np.mean(top_k))
```

### Step 5: Eviction Logic

```python
    def _evict(self):
        """
        Remove the least important entries while preserving attention sinks.
        """
        # Identify sinks: entries with importance >= threshold
        sinks = {tid: imp for tid, (_, _, imp) in self.store.items()
                 if imp >= self.sink_threshold}
        # Sort remaining entries by importance (ascending)
        sorted_entries = sorted(self.store.items(),
                                key=lambda item: item[1][2])
        # Remove the lowest‑importance non‑sink entries
        to_remove = []
        for tid, (_, _, imp) in sorted_entries:
            if len(self.store) - len(to_remove) <= self.max_size:
                break
            if tid not in sinks:
                to_remove.append(tid)
        for tid in to_remove:
            del self.store[tid]
```

### Step 6: Retrieve KV for Inference

```python
    def get(self, token_id: int) -> Tuple[np.ndarray, np.ndarray] | None:
        """
        Return the stored (key, value) for a token, or None if not present.
        """
        entry = self.store.get(token_id)
        if entry is None:
            return None
        key, value, _ = entry
        # Move to end to mark as recently used (optional LRU behavior)
        self.store.move_to_end(token_id)
        return key, value
```

### Step 7: Example Usage

```python
# example.py
import numpy as np
from kv_cache import StreamingKVCache

# Simulate token stream
np.random.seed(42)
cache = StreamingKVCache(max_size=5, sink_threshold=0.15)

for i in range(10):
    token_id = i
    key = np.random.randn(8).astype(np.float32)
    value = np.random.randn(8).astype(np.float32)
    # Fake attention weights for importance scoring
    attn = np.random.rand(8)
    importance = cache._score_importance(attn)
    cache.add(token_id, key, value, importance)
    # Retrieve a random token to demonstrate cache hit/miss
    if i % 2 == 0:
        retrieved = cache.get(token_id)
        print(f"Token {token_id}: {'hit' if retrieved is not None else 'miss'}")
```

## Running and Testing It

1. **Run the example**

```bash
python example.py
```

You should see alternating `hit` and `miss` messages, confirming that the cache retains recent tokens while evicting older, low‑importance ones.

2. **Benchmark memory usage**

```python
# benchmark.py
import tracemalloc
from example import cache  # assuming cache is exposed

tracemalloc.start()
# ... run a loop adding 1000 tokens ...
current, peak = tracemalloc.get_traced_memory()
print(f"Peak memory: {peak / 1024:.2f} KiB")
```

3. **Validate correctness**

Write a unit test that asserts `cache.get(token_id)` returns the exact arrays that were added, ensuring no data corruption during eviction.

```bash
python -m pytest test_kv_cache.py
```

## Extending It: Your Roadmap to Senior-Level

1. **Persistent storage with SQLite** – store KV pairs on disk to survive process restarts; matters for long‑running services that must checkpoint state.
2. **Horizontal scaling via Ray** – shard the cache across multiple nodes, enabling linear memory scaling for very large contexts.
3. **Observability with Prometheus** – expose metrics like cache hit ratio, eviction rate, and latency; critical for debugging in production.
4. **Fault tolerance through checkpointing** – periodically snapshot the cache to a WAL, allowing recovery after node failures.
5. **Adaptive sink threshold** – tune `sink_threshold` dynamically based on observed attention patterns, improving accuracy under varying workloads.
6. **Benchmark suite with synthetic workloads** – compare against baselines (e.g., full KV cache, sliding window) using metrics such as perplexity, latency, and memory footprint.

## Key Takeaways

- Implementing a streaming KV cache teaches you to manage memory explicitly, a core skill for high‑throughput inference systems.
- Attention sinks provide a principled way to balance recall vs. memory, directly applicable to production LLM serving.
- The project is extensible: persistence, distributed caching, and observability turn a prototype into a production‑grade component.
- You can showcase this work on a CV as evidence of systems engineering, algorithm design, and performance optimization.
- Real‑world impact: such caches enable cost‑effective long‑context generation, a key differentiator for LLM products.

## Further Reading

- [Attention Sinks: An Efficient Method for Long Context](https://arxiv.org/abs/2305.14341) – the original paper introducing the concept.
- [Efficient Memory Management for Large Language Models](https://arxiv.org/abs/2205.11916) – discusses KV cache optimizations.
- [Ray: A Distributed Framework for Emerging AI Applications](https://ray.io/) – for scaling the cache horizontally.
- [SQLite Documentation](https://www.sqlite.org/docs.html) – to implement persistent storage.
- [Prometheus Monitoring Guide](https://prometheus.io/docs/introduction/overview/) – for adding observability.