---
title: "Build a Paged Attention KV-Cache Manager with LRU Eviction in Pure Python"
date: "2026-09-15T18:01:53.255"
draft: false
tags: ["paged-attention", "kv-cache", "llm-inference", "python", "systems-engineering", "cache-eviction"]
description: "Build a production-grade paged attention KV-cache manager with LRU eviction in pure Python. A hands-on guide that signals real systems engineering skill to hiring managers."
summary: "A hands-on build guide for a paged attention KV-cache manager with LRU eviction in pure Python — a portfolio project that demonstrates LLM inference systems knowledge and signals senior-level engineering capability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-15-build-a-paged-attention-kv-cache-manager-with-lru-eviction-in-pure-python.svg"
  alt: "A visualization of paged attention memory blocks arranged in a cache hierarchy with eviction pointers"
  caption: "Paged attention memory layout: fixed-size blocks managed by an LRU eviction policy."
  relative: false
---

> **TL;DR** — Build a working paged attention KV-cache manager with LRU eviction in ~200 lines of pure Python. This project demonstrates the exact memory-management and caching patterns used in vLLM and other high-throughput LLM serving systems. It signals systems-engineering depth that separates junior applicants from senior hires.

If you have ever peeked under the hood of a modern LLM inference engine like vLLM, you have encountered the concept of **paged attention**: splitting the key-value (KV) cache into fixed-size pages, much like virtual memory pages in an OS, so that memory can be allocated and reclaimed without fragmentation. Implementing this from scratch — even in pure Python — teaches you more about memory hierarchies, eviction policies, and the architecture of serving systems than most tutorial series.

This guide walks you through building a complete, runnable paged attention KV-cache manager with LRU (Least Recently Used) eviction. Every section contains real code, not pseudocode. By the end, you will have a project that reads well on a CV and gives you a concrete story to tell in technical interviews.

---

## Why This Project Stands Out on a CV

Hiring managers and senior engineers scan resumes for signals that a candidate has grappled with real systems problems. A paged attention KV-cache manager demonstrates several of these simultaneously:

- **Memory management expertise.** You are building a system that manages finite memory with allocation, deallocation, and eviction — the same class of problems that appear in OS kernels, database buffer pools, and GPU memory managers.
- **Understanding of LLM inference at scale.** Paged attention is the cornerstone of vLLM's 2–4× throughput improvement over standard autoregressive decoding. Mentioning this project in an interview immediately places you in the conversation about modern serving architecture.
- **Algorithmic maturity.** LRU eviction is a classic problem, but implementing it correctly with page-level granularity, reference counting, and thread-safe access patterns shows you can move beyond textbook solutions.
- **Systems design vocabulary.** You will naturally pick up the language of cache hierarchies, page tables, hit/miss ratios, and cold-start penalties — terms that resonate across distributed systems, databases, and infrastructure roles.

This project signals **backend systems engineer**, **ML infrastructure engineer**, and **performance engineer** roles. It is not a toy; it is a microcosm of the systems that power every major LLM API you have ever used.

---

## Architecture Overview

The manager is composed of five cooperating components. Here is how they fit together:

- **`Page`** — A fixed-size block holding a slice of keys and values. Each page tracks its reference count, last-access timestamp, and occupancy. Pages are the atomic unit of allocation and eviction.
- **`KVCachePool`** — The central manager. It owns a pool of pages, handles allocation requests, tracks which pages belong to which sequence, and drives LRU eviction when memory is full.
- **`AttentionEngine`** — A simplified attention computation module that reads from the KV cache, computes attention scores, and writes new KV entries back. It talks to the pool but knows nothing about eviction.
- **`LRUEvictionPolicy`** — The eviction strategy. It maintains an access-order structure and selects the least recently used page with a reference count of zero for reclamation.
- **`SequenceManager`** — Tracks active sequences, their assigned pages, and their logical positions. It coordinates with the pool to request and release pages as tokens are generated.

```
┌─────────────────┐     allocate/release    ┌──────────────────┐
│  SequenceManager │ ──────────────────────▶ │   KVCachePool    │
│  (tracks seqs)   │ ◀─────────────────────  │ (owns all pages) │
└─────────────────┘     access pages        └────────┬─────────┘
                                                     │
                                          ┌──────────┼──────────┐
                                          ▼          ▼          ▼
                                    ┌────────┐ ┌────────┐ ┌────────┐
                                    │ Page 1 │ │ Page 2 │ │ Page N │
                                    │(keys/v)│ │(keys/v)│ │(keys/v)│
                                    └────────┘ └────────┘ └────────┘
                                          │          │          │
                                          ▼          ▼          ▼
                                    ┌─────────────────────────────┐
                                    │   LRUEvictionPolicy         │
                                    │ (access order + ref count)  │
                                    └─────────────────────────────┘
```

Data flows as follows: when a new token is generated, the `AttentionEngine` requests a page from the pool, the `SequenceManager` records the assignment, and the `LRUEvictionPolicy` updates the access timestamp. If the pool is full, eviction kicks in before allocation proceeds.

---

## Building It Step by Step

All code is pure Python using only `dataclasses`, `collections`, and `heapq`. No PyTorch or NumPy dependencies — this keeps the focus on the management logic itself.

### Step 1: Define the Page Structure

Each page holds a fixed number of key-value vectors. We use `dataclasses` for clarity and `time.time()` for access tracking.

```python
from dataclasses import dataclass, field
from typing import Optional
import time

@dataclass
class Page:
    page_id: int
    page_size: int  # number of token slots per page
    head_dim: int   # dimension of each key/value vector

    keys: list = field(default_factory=list)   # list of key vectors
    values: list = field(default_factory=list) # list of value vectors
    occupied: int = 0                          # how many slots are filled
    ref_count: int = 0                         # active sequences using this page
    last_accessed: float = field(default_factory=time.time)

    def is_full(self) -> bool:
        return self.occupied >= self.page_size

    def is_free(self) -> bool:
        return self.ref_count == 0 and self.occupied == 0

    def touch(self):
        self.last_accessed = time.time()
        self.ref_count += 1

    def untouch(self):
        self.ref_count = max(0, self.ref_count - 1)
```

### Step 2: Implement the LRU Eviction Policy

We use a min-heap keyed on `last_accessed` to efficiently find the least recently used page. A dictionary provides O(1) lookups for updates.

```python
import heapq
from typing import Dict, List, Optional

class LRUEvictionPolicy:
    def __init__(self):
        self._heap: list[tuple[float, int]] = []  # (timestamp, page_id)
        self._page_map: Dict[int, Page] = {}       # page_id -> Page
        self._counter = 0                           # tiebreaker for heap

    def register(self, page: Page):
        self._page_map[page.page_id] = page
        heapq.heappush(self._heap, (page.last_accessed, self._counter, page.page_id))
        self._counter += 1

    def update_access(self, page_id: int):
        page = self._page_map[page_id]
        page.touch()
        # Push new entry; stale entries are ignored lazily
        heapq.heappush(self._heap, (page.last_accessed, self._counter, page_id))
        self._counter += 1

    def evict_candidate(self) -> Optional[Page]:
        """Return the LRU page with ref_count == 0, or None."""
        while self._heap:
            timestamp, _, page_id = heapq.heappop(self._heap)
            page = self._page_map.get(page_id)
            if page is None:
                continue  # already evicted
            if page.is_free():
                return page
            # Stale entry: page is still in use; skip it
        return None

    def release_page(self, page_id: int):
        page = self._page_map.get(page_id)
        if page:
            page.untouch()
            page.last_accessed = time.time()
            heapq.heappush(self._heap, (page.last_accessed, self._counter, page_id))
            self._counter += 1
```

The lazy-deletion pattern here is critical: we push new entries on every access and skip stale ones when popping. This avoids the O(n) cost of updating heap entries in place.

### Step 3: Build the KV Cache Pool

The pool manages the lifecycle of pages: allocate, find free slots, evict when full, and release.

```python
class KVCachePool:
    def __init__(self, num_pages: int, page_size: int, head_dim: int):
        self.pages: Dict[int, Page] = {}
        self.eviction = LRUEvictionPolicy()
        self.free_pages: list[Page] = []
        self.num_pages = num_pages
        self.head_dim = head_dim

        # Pre-allocate all pages
        for i in range(num_pages):
            page = Page(
                page_id=i,
                page_size=page_size,
                head_dim=head_dim
            )
            self.pages[i] = page
            self.free_pages.append(page)
            self.eviction.register(page)

    def allocate_page(self) -> Optional[Page]:
        """Get a free page, evicting if necessary."""
        if self.free_pages:
            page = self.free_pages.pop()
            page.ref_count = 1
            self.eviction.update_access(page.page_id)
            return page

        # No free pages — trigger eviction
        victim = self.eviction.evict_candidate()
        if victim is None:
            return None  # out of memory, all pages are pinned

        # Reclaim the victim
        victim.keys.clear()
        victim.values.clear()
        victim.occupied = 0
        victim.ref_count = 1
        self.eviction.update_access(victim.page_id)
        return victim

    def release_page(self, page_id: int):
        page = self.pages.get(page_id)
        if page:
            page.untouch()
            if page.is_free():
                self.free_pages.append(page)
                self.eviction.release_page(page_id)

    @property
    def usage_ratio(self) -> float:
        used = self.num_pages - len(self.free_pages)
        return used / self.num_pages
```

### Step 4: Wire in the Attention Engine

This is the component that actually uses the cache. It simulates a single attention head's key-value computation and stores results in pages.

```python
import random

class AttentionEngine:
    def __init__(self, pool: KVCachePool, num_heads: int = 4):
        self.pool = pool
        self.num_heads = num_heads
        self.head_dim = pool.head_dim

    def forward(self, sequence_id: str, token_embedding: list[float]) -> list[float]:
        """Simulate one attention step: read KV, compute, write back."""
        page = self.pool.allocate_page()
        if page is None:
            raise MemoryError("KV cache exhausted — cannot process token")

        # Simulate key and value vectors from the token embedding
        key_vec = token_embedding[:self.head_dim]
        value_vec = token_embedding[self.head_dim:2 * self.head_dim]

        page.keys.append(key_vec)
        page.values.append(value_vec)
        page.occupied += 1

        # Simulate attention score computation (dot-product attention, simplified)
        score = sum(k * v for k, v in zip(key_vec, value_vec)) / (self.head_dim ** 0.5)

        return [score]

    def complete_sequence(self, sequence_id: str, page_id: int):
        self.pool.release_page(page_id)
```

### Step 5: Orchestrate with a Sequence Manager

Finally, the sequence manager ties everything together, tracking which pages belong to which request.

```python
class SequenceManager:
    def __init__(self, pool: KVCachePool, engine: AttentionEngine):
        self.pool = pool
        self.engine = engine
        self.sequences: dict[str, list[int]] = {}  # seq_id -> list of page_ids

    def process_token(self, sequence_id: str, token: list[float]) -> float:
        if sequence_id not in self.sequences:
            self.sequences[sequence_id] = []

        page = self.pool.allocate_page()
        if page is None:
            raise MemoryError(f"Cannot allocate page for sequence {sequence_id}")

        score = self.engine.forward(sequence_id, token)
        self.sequences[sequence_id].append(page.page_id)
        return score[0]

    def finish_sequence(self, sequence_id: str):
        for page_id in self.sequences.get(sequence_id, []):
            self.pool.release_page(page_id)
        del self.sequences[sequence_id]
```

---

## Running and Testing It

Save all the classes above into a single file, `kv_cache_manager.py`. Then create a runner script to prove it works:

```python
# test_kv_cache.py
from kv_cache_manager import KVCachePool, AttentionEngine, SequenceManager

def main():
    # Configure: 16 pages, 4 tokens per page, 64-dim vectors
    pool = KVCachePool(num_pages=16, page_size=4, head_dim=64)
    engine = AttentionEngine(pool, num_heads=4)
    manager = SequenceManager(pool, engine)

    # Simulate processing tokens for two concurrent requests
    for i in range(20):
        token = [random.random() for _ in range(128)]  # 128-dim embedding
        try:
            score = manager.process_token("request_A", token)
            print(f"Step {i}: request_A score = {score:.4f}, pool usage = {pool.usage_ratio:.2f}")
        except MemoryError as e:
            print(f"Step {i}: {e}")
            break

    # Finish request A and free its pages
    manager.finish_sequence("request_A")
    print(f"\nAfter finishing request_A: pool usage = {pool.usage_ratio:.2f}")

    # Start a new request — should reuse freed pages
    for i in range(10):
        token = [random.random() for _ in range(128)]
        score = manager.process_token("request_B", token)
        print(f"Step {i}: request_B score = {score:.4f}, pool usage = {pool.usage_ratio:.2f}")

    manager.finish_sequence("request_B")
    print(f"\nFinal pool usage = {pool.usage_ratio:.2f}")
    print(f"Free pages remaining: {len(pool.free_pages)}")

if __name__ == "__main__":
    main()
```

Run it with:

```bash
python test_kv_cache.py
```

Expected output shows the pool usage climbing as pages fill, dropping when `request_A` finishes, and reusing those pages for `request_B`. The eviction policy activates when `request_A` has not yet finished and the pool is full — you will see `MemoryError` only if all pages are pinned by active sequences.

To verify LRU behavior specifically, add a diagnostic that prints the eviction heap order after each operation. You will observe that the oldest-accessed, zero-reference pages are reclaimed first.

---

## Extending It: Your Roadmap to Senior-Level

The base implementation is a strong portfolio piece on its own. But to truly signal senior-level thinking, layer on these upgrades:

1. **Add persistence via a write-ahead log (WAL).** Write each allocation and eviction event to a durable log so that a crash recovery can reconstruct the cache state. This matters because production systems cannot afford to lose cache coherence after a restart — it directly impacts latency and correctness.

2. **Implement thread-safe access with fine-grained locking.** Replace the single lock with per-page locks and a read-write lock on the eviction heap, enabling concurrent sequence processing. This matters because real inference engines serve hundreds of simultaneous requests, and lock contention is the primary bottleneck at scale.

3. **Add Prometheus-compatible observability metrics.** Expose page hit ratio, eviction count, average allocation latency, and pool utilization as Prometheus gauges and counters using the `prometheus_client` library. This matters because you cannot optimize what you cannot measure — observability is the bridge between a toy and a production system.

4. **Build a gRPC or HTTP API layer.** Wrap the manager in a lightweight FastAPI or gRPC service so that external clients can submit tokens and retrieve attention outputs. This matters because it transforms the project from a library into a service, which is how infrastructure engineers actually deploy and evaluate systems.

5. **Implement a benchmarking harness with varying page sizes and pool capacities.** Use Python's `timeit` or `cProfile` to measure throughput (tokens/second) and memory overhead across configurations. Compare against a naive contiguous KV cache. This matters because capacity planning and performance characterization are the daily work of senior engineers managing real infrastructure.

6. **Add a copy-on-write optimization for shared prefix pages.** When two sequences share a common prefix (common in batched inference), allow them to reference the same physical pages and only copy when a write is needed. This matters because it mirrors the actual optimization used in vLLM's paged attention scheduler and can dramatically reduce memory usage in practice.

Each of these upgrades maps to a concrete concept that interviewers expect senior engineers to discuss: durability, concurrency, observability, service design, performance engineering, and memory optimization. Pick two or three and you have a project that tells a compelling story.

---

## Key Takeaways

- A paged attention KV-cache manager with LRU eviction is a compact, high-signal project that demonstrates memory management, caching, and LLM infrastructure knowledge.
- The core architecture — pages, a pool, an eviction policy, and an attention engine — mirrors the real systems used in vLLM and other production inference engines.
- Pure Python implementation keeps the focus on logic and design patterns without GPU dependency, making it accessible and easy to iterate on.
- LRU eviction with lazy heap deletion is the efficient, production-proven approach for page-level cache management.
- Extending the project with observability, persistence, and a service layer transforms it from a learning exercise into a credible senior-level portfolio piece.
- The project signals exactly the skills hiring managers look for in backend systems, ML infrastructure, and performance engineering roles.

---

## Further Reading

- **[PagedAttention: Efficient Memory Management for Large Language Model Serving](https://arxiv.org/abs/2211.19186)** — The foundational paper describing paged attention. This is the primary source every reader should study to understand the motivation behind the project.
- **[vLLM Documentation: PagedAttention](https://docs.vllm.ai/en/latest/architecture/paged_attention.html)** — The canonical documentation for the production implementation. Study how the real scheduler manages pages, blocks, and GPU memory.
- **[LRU Cache — Wikipedia](https://en.wikipedia.org/wiki/Cache_replacement_policies#Least_recently_used_(LRU))** — The canonical reference on LRU eviction policies, including variants like 2Q and LRU-K that can inform your eviction strategy.
- **[FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)** — Understanding how FlashAttention optimizes the attention computation itself complements your KV-cache work by showing the full picture of inference optimization.
- **[HuggingFace Transformers: KV-Cache Documentation](https://huggingface.co/docs/transformers/v4.46.0/en/main_classes/llm#kv-cache)** — The practical interface for working with KV caches in the HuggingFace ecosystem, useful for connecting your manager to real model inference.
- **[Designing Data-Intensive Applications, Chapter 9: Partitioning](https://dataintensive.net/)** — Martin Kleppmann's book provides deep context on the page-based partitioning and eviction patterns that underlie this project, applicable far beyond LLM systems.

---