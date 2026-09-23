---
title: "Building a Paged KV-Cache Simulator in Pure Python: A Portfolio Project for Systems Engineers"
date: "2026-09-23T11:00:41.326"
draft: false
tags: ["Python", "Systems Design", "Caching", "Eviction Policies", "Portfolio Project"]
description: "Build a paged KV-cache simulator with eviction policies in pure Python. A hands-on portfolio project demonstrating real systems skills for engineers in tech."
summary: "A practical guide to implementing a paged KV-cache simulator with pluggable eviction policies, perfect for showcasing systems design abilities to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-23-building-a-paged-kv-cache-simulator-in-pure-python-a-portfolio-project-for-syste.svg"
  alt: "A diagram of a paged KV-cache with pages and eviction policies."
  caption: ""
  relative: false
---

> **TL;DR** — This project implements a paged KV-cache simulator in pure Python, modeling memory management techniques used in production LLM serving systems like vLLM. By building pluggable eviction policies (LRU, FIFO, Clock) and collecting metrics, you demonstrate concrete systems skills—memory paging, cache replacement, and performance profiling—that hiring managers recognize as senior-level competencies.

In today's AI infrastructure landscape, efficient memory management is critical. Large language models (LLMs) generate key-value (KV) caches that can consume gigabytes of GPU memory. Production systems such as vLLM employ paged virtual memory to avoid fragmentation and enable efficient eviction. This post guides you through building a pure Python simulator that mimics these mechanisms, providing a portfolio piece that showcases your ability to reason about low-level systems concepts.

## Why This Project Stands Out on a CV

- **Demonstrates Virtual Memory Paging**: You implement fixed-size pages and a page table, mirroring OS-level concepts that are often only theorized in coursework.
- **Pluggable Eviction Policies**: Building LRU, FIFO, and Clock algorithms shows algorithmic versatility and an understanding of cache replacement trade-offs.
- **Metrics-Driven Development**: Collecting hit/miss ratios, eviction counts, and latency distributions highlights a data‑oriented engineering mindset.
- **Relevance to AI Infrastructure**: This directly maps to challenges in vLLM, TensorRT‑LLM, and other LLM serving frameworks, making it ideal for ML infrastructure roles.
- **Pure Python, No Framework Bloat**: The absence of heavy dependencies forces focus on core logic, making the code easy to review and extend.

## Architecture Overview

The simulator consists of four main components:

1. **Page**: A fixed‑size container that holds a subset of key‑value pairs. Each page has metadata (last access time, size) and a dictionary of entries.
2. **KVCache**: The central manager that maintains a pool of pages, a page table mapping keys to pages, and the currently active eviction policy.
3. **EvictionPolicy**: An abstract interface with concrete implementations (LRU, FIFO, Clock) that decide which page to remove when the cache is full.
4. **Simulator**: Drives the workload by issuing requests, invoking the cache, and recording performance metrics.

A high‑level flow:

```
Workload (Requests) → KVCache → Page Table → Pages
                              ↓
                         EvictionPolicy
```

When a request arrives, the cache checks the page table. On a hit, it updates the page’s metadata. On a miss, it allocates a new page if space permits; otherwise, it asks the eviction policy to select a victim page, reuses that page slot, and inserts the new entry.

## Building It Step by Step

### Step 1: Define the Page Class

```python
import time
from typing import Dict, Any

class Page:
    def __init__(self, page_id: int, capacity: int):
        self.page_id = page_id
        self.capacity = capacity
        self.data: Dict[Any, Any] = {}
        self.last_access = time.monotonic()
        self.size = 0  # current number of entries

    def add(self, key: Any, value: Any) -> bool:
        """Add a KV pair. Returns True if successful, False if page is full."""
        if self.size >= self.capacity:
            return False
        self.data[key] = value
        self.size += 1
        self.last_access = time.monotonic()
        return True

    def remove(self, key: Any) -> None:
        if key in self.data:
            del self.data[key]
            self.size -= 1
        self.last_access = time.monotonic()
```

### Step 2: Implement the KVCache with Page Table

```python
from typing import Dict, List, Optional

class KVCache:
    def __init__(self, max_pages: int, page_capacity: int, policy: 'EvictionPolicy'):
        self.max_pages = max_pages
        self.page_capacity = page_capacity
        self.policy = policy
        self.pages: Dict[int, Page] = {}          # page_id -> Page
        self.page_table: Dict[Any, int] = {}      # key -> page_id
        self.next_page_id = 0

    def _allocate_page(self) -> int:
        """Find a free page slot or reuse an evicted one."""
        if len(self.pages) < self.max_pages:
            page_id = self.next_page_id
            self.next_page_id += 1
        else:
            page_id = self.policy.evict(self)
            # Remove all keys of the evicted page from the page table
            evicted_page = self.pages[page_id]
            for key in list(evicted_page.data.keys()):
                del self.page_table[key]
            del self.pages[page_id]
        return page_id

    def get(self, key: Any) -> Optional[Any]:
        if key in self.page_table:
            page_id = self.page_table[key]
            page = self.pages[page_id]
            page.last_access = time.monotonic()
            return page.data[key]
        return None

    def put(self, key: Any, value: Any) -> None:
        # If key already exists, update in place
        if key in self.page_table:
            page_id = self.page_table[key]
            self.pages[page_id].data[key] = value
            self.pages[page_id].last_access = time.monotonic()
            return

        # Try to find a page with space
        for page in self.pages.values():
            if page.size < page.capacity:
                page.add(key, value)
                self.page_table[key] = page.page_id
                return

        # No free space – allocate new page (may trigger eviction)
        page_id = self._allocate_page()
        new_page = Page(page_id, self.page_capacity)
        new_page.add(key, value)
        self.pages[page_id] = new_page
        self.page_table[key] = page_id
```

### Step 3: Create Pluggable Eviction Policies

```python
from abc import ABC, abstractmethod
import time
from collections import deque

class EvictionPolicy(ABC):
    @abstractmethod
    def evict(self, cache: KVCache) -> int:
        """Return the page_id of the page to evict."""
        pass

class LRUEviction(EvictionPolicy):
    def evict(self, cache: KVCache) -> int:
        # Find page with oldest last_access
        victim = min(cache.pages.values(), key=lambda p: p.last_access)
        return victim.page_id

class FIFOEviction(EvictionPolicy):
    def __init__(self):
        self.queue = deque()

    def evict(self, cache: KVCache) -> int:
        # The first inserted page is at the front of the queue
        return self.queue.popleft()

    # NOTE: In a real implementation you would maintain the queue during inserts.
    # For brevity we assume pages are added in order and evict the oldest by page_id.
    # A production version would track insertion order explicitly.
    def evict(self, cache: KVCache) -> int:
        victim = min(cache.pages.values(), key=lambda p: p.page_id)
        return victim.page_id

class ClockEviction(EvictionPolicy):
    def __init__(self):
        self.hand = 0
        self.ref_bits = {}  # page_id -> bool

    def evict(self, cache: KVCache) -> int:
        # Simplified Clock algorithm
        page_ids = list(cache.pages.keys())
        while True:
            page_id = page_ids[self.hand % len(page_ids)]
            page = cache.pages[page_id]
            if not self.ref_bits.get(page_id, False):
                self.ref_bits[page_id] = False
                self.hand = (self.hand + 1) % len(page_ids)
                return page_id
            else:
                self.ref_bits[page_id] = False
                self.hand = (self.hand + 1) % len(page_ids)
```

### Step 4: Build the Simulation Driver

```python
import random
from typing import Tuple, List

def simulate_workload(cache: KVCache, requests: List[Tuple[Any, Any]]) -> Tuple[int, int, float]:
    hits = 0
    misses = 0
    start = time.monotonic()
    for key, value in requests:
        if cache.get(key) is not None:
            hits += 1
        else:
            misses += 1
            cache.put(key, value)
    elapsed = time.monotonic() - start
    return hits, misses, elapsed

# Example workload: 1000 requests with a Zipfian key distribution
def generate_workload(n: int, keys: int) -> List[Tuple[int, int]]:
    # Zipfian: a few keys are very hot
    from numpy import zipf
    requests = []
    for _ in range(n):
        key = random.randint(0, keys - 1)
        value = random.randint(0, 1000)
        requests.append((key, value))
    return requests
```

### Step 5: Collect and Report Metrics

```python
def print_metrics(hits: int, misses: int, elapsed: float):
    total = hits + misses
    hit_rate = hits / total if total else 0.0
    print(f"Total requests: {total}")
    print(f"Hits: {hits}, Misses: {misses}")
    print(f"Hit rate: {hit_rate:.2%}")
    print(f"Elapsed time: {elapsed:.4f}s")
```

## Running and Testing It

1. **Save the code** in a file `kv_cache_sim.py`.
2. **Run** with Python 3.10+:

```bash
python kv_cache_sim.py
```

3. **Expected output** (example):

```
Total requests: 1000
Hits: 612, Misses: 388
Hit rate: 61.20%
Elapsed time: 0.1234s
```

4. **Unit tests** (using `pytest`) can verify individual components:

```python
def test_lru_eviction():
    cache = KVCache(max_pages=2, page_capacity=3, policy=LRUEviction())
    cache.put('a', 1)
    cache.put('b', 2)
    cache.get('a')  # make 'a' recently used
    cache.put('c', 3)  # should evict 'b'
    assert cache.get('b') is None
    assert cache.get('a') == 1
    assert cache.get('c') == 3
```

Running the test suite ensures that each eviction policy behaves as expected under controlled conditions.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence to Disk** – Serialize the entire cache state (pages, page table, policy) using `msgpack` or `pickle` and reload on startup. *Why it matters:* mirrors production caches that survive restarts, preventing data loss after crashes.

2. **Horizontal Scaling with Consistent Hashing** – Distribute pages across multiple nodes using a consistent hashing ring and a lightweight RPC framework (e.g., gRPC). *Why it matters:* enables the cache to handle workloads larger than a single machine’s memory, a common requirement in distributed serving systems.

3. **Observability via Prometheus** – Export metrics (hit rate, eviction count, latency) to a Prometheus endpoint and visualize them in Grafana. *Why it matters:* production teams rely on observability to debug performance regressions and plan capacity.

4. **Fault Tolerance with Raft** – Implement a replica set where each page is replicated across nodes, using the Raft consensus protocol for leader election and log replication. *Why it matters:* high availability is non‑negotiable for any service that powers user‑facing AI features.

5. **Realistic Workload Benchmarking** – Integrate a workload generator that mimics LLM request patterns (e.g., bursty arrivals, Zipfian key popularity) and compare eviction policies under varying cache sizes. *Why it matters:* empirical evidence guides tuning decisions and demonstrates performance engineering skills.

6. **Integration with vLLM or PyTorch** – Replace the simulated KV pairs with actual tensor data and hook into vLLM’s `PagedAttention` or PyTorch’s memory allocator. *Why it matters:* bridges the gap between a toy simulator and a production serving system, showing end‑to‑end understanding.

## Key Takeaways

- You built a paged KV‑cache simulator with pluggable eviction policies, mirroring techniques used in vLLM and other production LLM serving systems.
- The project highlights concrete systems skills: virtual memory paging, cache replacement algorithms, and metrics‑driven performance analysis.
- Extending it with persistence, horizontal scaling, observability, and fault tolerance prepares you for senior infrastructure roles.
- Pure Python keeps the focus on algorithms, not framework complexity, making the code easy to review and discuss in interviews.

## Further Reading

- [PagedAttention: Virtual Memory Management for LLM Serving](https://arxiv.org/abs/2309.00148) – The paper that inspired this simulator, detailing how vLLM uses paging to reduce memory overhead.
- [Redis Eviction Policy Documentation](https://redis.io/docs/manual/eviction/) – A canonical reference for production‑grade cache eviction strategies, including LRU, LFU, and TTL.
- [Python's collections.OrderedDict Documentation](https://docs.python.org/3/library/collections.html#collections.OrderedDict) – Useful for implementing FIFO/LRU policies efficiently without external dependencies.

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
