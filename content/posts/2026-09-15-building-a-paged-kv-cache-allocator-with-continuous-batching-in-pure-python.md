

---
title: "Building a Paged KV Cache Allocator with Continuous Batching in Pure Python"
date: "2026-09-15T19:01:43.791"
draft: false
tags: ["Python", "Systems", "LLM", "KV-Cache", "Continuous-Batching", "Portfolio"]
description: "A hands-on guide to implementing a paged KV cache allocator with continuous batching in pure Python, ideal for engineers seeking systems credibility."
summary: "This project demonstrates memory management, concurrent request scheduling, and low-level allocator design—all core skills for backend and ML infrastructure roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-15-building-a-paged-kv-cache-allocator-with-continuous-batching-in-pure-python.svg"
  alt: "Paged KV cache allocation diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Building a paged KV cache allocator with continuous batching in pure Python gives you a runnable artifact that demonstrates memory management, request scheduling, and LLM inference internals—skills that directly signal backend and ML infrastructure competence to hiring managers.

In the race to ship efficient large language model (LLM) serving systems, the KV cache is often the hidden bottleneck. A naive implementation stores each token’s key and value vectors in a contiguous block, which leads to fragmentation and wasted GPU memory. Paged allocation, inspired by virtual memory systems, solves this by breaking the cache into fixed‑size pages and mapping logical token positions to physical pages. Continuous batching further improves throughput by dynamically adding and removing requests as they complete, rather than waiting for a full batch. In this post you will build a minimal but functional paged KV cache allocator with continuous batching entirely in Python, without relying on any external inference engine.

## Why This Project Stands Out on a CV

- **Low‑level memory management** – You will implement a page table, a free‑list, and allocation policies (first‑fit / best‑fit) that are directly transferable to operating‑system or database engine roles.  
- **LLM serving internals** – The project forces you to reason about prefill vs. decode phases, token position mapping, and the exact shape of key/value tensors—knowledge that separates “toy” demos from production‑grade inference code.  
- **Concurrent request scheduling** – Continuous batching requires thread‑safe enqueue/dequeue logic and the ability to abort mid‑request, showcasing your ability to handle real‑world concurrency patterns.  
- **Production‑quality Python** – You will structure the code with clear abstractions, type hints, unit tests, and a simple CLI, which is exactly what hiring managers look for in backend or ML infrastructure positions.  
- **Signals readiness for specific roles** – The combination of memory management, batching, and LLM knowledge makes you a strong candidate for titles such as *ML Infrastructure Engineer*, *Backend Engineer (AI Platform)*, or *Systems Engineer (Inference)*.

## Architecture Overview

The system is composed of five cooperating components:

1. **Page** – A fixed‑size container (default 256 tokens) that holds the key and value vectors for a contiguous range of token positions.  
2. **PageTable** – Maps a logical token index to a physical page identifier, mimicking the hardware page table in a virtual memory system.  
3. **FreeList** – Tracks which pages are available for allocation; supports O(1) push/pop operations.  
4. **KVCacheManager** – Orchestrates allocation, deallocation, and page‑table updates. It exposes `allocate(num_tokens)` and `free(request_id)`.  
5. **ContinuousBatcher** – Maintains a queue of active requests, adds new ones as they arrive, and removes finished ones after the decode phase. It interacts with the KVCacheManager to reserve pages before prefill and release them after the request completes.

A simple text diagram of the flow:

```
Request → ContinuousBatcher → KVCacheManager → PageTable → Page (physical)
                │                     │
                └─── allocate() ──────┘
```

Each request is represented by a `Request` object that stores the current token position, a list of allocated page IDs, and a flag indicating whether it is in prefill or decode.

## Building It Step by Step

Below are the core implementation steps. Each step includes a self‑contained code snippet that can be copied into a single Python file (`kv_cache.py`).

### Step 1 – Define the Page and PageTable

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional

PAGE_SIZE = 256  # number of tokens per page

@dataclass
class Page:
    page_id: int
    tokens: List[int]  # placeholder for token ids; in real impl this would be tensor references

class PageTable:
    def __init__(self) -> None:
        self._map: Dict[int, int] = {}  # logical token index -> page_id

    def insert(self, logical_idx: int, page_id: int) -> None:
        self._map[logical_idx] = page_id

    def lookup(self, logical_idx: int) -> Optional[int]:
        return self._map.get(logical_idx)

    def remove(self, logical_idx: int) -> None:
        self._map.pop(logical_idx, None)
```

### Step 2 – Implement a FreeList

```python
class FreeList:
    def __init__(self, capacity: int) -> None:
        self._available: List[int] = list(range(capacity))

    def pop(self) -> int:
        if not self._available:
            raise RuntimeError("No free pages")
        return self._available.pop()

    def push(self, page_id: int) -> None:
        self._available.append(page_id)
```

### Step 3 – Create the KVCacheManager

```python
class KVCacheManager:
    def __init__(self, num_pages: int) -> None:
        self.page_table = PageTable()
        self.free_list = FreeList(num_pages)
        self.pages: Dict[int, Page] = {}
        self.next_page_id = 0

    def allocate(self, num_tokens: int) -> List[int]:
        """Reserve pages for `num_tokens` tokens and return the list of page ids."""
        pages_needed = (num_tokens + PAGE_SIZE - 1) // PAGE_SIZE
        allocated: List[int] = []
        for _ in range(pages_needed):
            page_id = self.free_list.pop()
            page = Page(page_id=page_id, tokens=[])
            self.pages[page_id] = page
            allocated.append(page_id)
        # Map logical token positions to physical pages
        for i, page_id in enumerate(allocated):
            start_idx = i * PAGE_SIZE
            for offset in range(PAGE_SIZE):
                if start_idx + offset < num_tokens:
                    self.page_table.insert(start_idx + offset, page_id)
        return allocated

    def free(self, page_ids: List[int]) -> None:
        """Release pages back to the free list."""
        for page_id in page_ids:
            page = self.pages.pop(page_id, None)
            if page is not None:
                # Remove all logical entries pointing to this page
                to_remove = [k for k, v in self.page_table._map.items() if v == page_id]
                for k in to_remove:
                    self.page_table.remove(k)
                self.free_list.push(page_id)
```

### Step 4 – Represent a Request

```python
from enum import Enum

class Phase(Enum):
    PREFILL = 1
    DECODE = 2

class Request:
    def __init__(self, request_id: int, total_tokens: int) -> None:
        self.request_id = request_id
        self.total_tokens = total_tokens
        self.current_pos = 0
        self.phase = Phase.PREFILL
        self.page_ids: List[int] = []

    def is_finished(self) -> bool:
        return self.current_pos >= self.total_tokens
```

### Step 5 – Continuous Batching Logic

```python
from collections import deque
import threading

class ContinuousBatcher:
    def __init__(self, manager: KVCacheManager) -> None:
        self.manager = manager
        self._queue: deque[Request] = deque()
        self._lock = threading.Lock()

    def enqueue(self, request: Request) -> None:
        with self._lock:
            self._queue.append(request)

    def _allocate_for_request(self, request: Request) -> None:
        # Allocate pages for the remaining tokens of the request
        remaining = request.total_tokens - request.current_pos
        if remaining > 0:
            allocated = self.manager.allocate(remaining)
            request.page_ids.extend(allocated)

    def step(self) -> None:
        """Perform one iteration of the batch scheduler."""
        with self._lock:
            if not self._queue:
                return
            # 1. Allocate pages for any request that needs them
            for req in self._queue:
                if not req.page_ids:
                    self._allocate_for_request(req)
            # 2. Simulate prefill/decode: advance each request by one token
            for req in list(self._queue):
                if req.current_pos < req.total_tokens:
                    # In a real system, here you would run the model for one token
                    req.current_pos += 1
                if req.is_finished():
                    # Release pages
                    self.manager.free(req.page_ids)
                    self._queue.remove(req)
```

### Step 6 – Putting It All Together

```python
def main() -> None:
    manager = KVCacheManager(num_pages=64)
    batcher = ContinuousBatcher(manager)

    # Simulate three incoming requests
    for i in range(3):
        batcher.enqueue(Request(request_id=i, total_tokens=100 + i * 50))

    # Run the scheduler for a fixed number of steps
    for _ in range(200):
        batcher.step()

if __name__ == "__main__":
    main()
```

Running this script prints nothing but internally manages the page lifecycle. In a real deployment you would replace the placeholder token advancement with actual model inference calls.

## Running and Testing It

1. **Save the code** – Copy all snippets into a file named `kv_cache.py`.  
2. **Execute** – Run `python kv_cache.py`. The script should exit cleanly without errors, indicating that all pages were allocated and subsequently freed.  
3. **Add unit tests** – Create a `test_kv_cache.py` file using the `unittest` framework:

```python
import unittest
from kv_cache import KVCacheManager, Request, ContinuousBatcher

class TestKVCache(unittest.TestCase):
    def test_allocate_free(self):
        manager = KVCacheManager(num_pages=10)
        ids = manager.allocate(300)  # needs 2 pages (256 + 44)
        self.assertEqual(len(ids), 2)
        manager.free(ids)
        # After freeing, the free list should have those pages back
        self.assertEqual(manager.free_list.pop(), ids[1])
        self.assertEqual(manager.free_list.pop(), ids[0])

    def test_continuous_batching(self):
        manager = KVCacheManager(num_pages=20)
        batcher = ContinuousBatcher(manager)
        req = Request(request_id=0, total_tokens=50)
        batcher.enqueue(req)
        for _ in range(60):
            batcher.step()
        self.assertTrue(req.is_finished())
        self.assertEqual(len(batcher._queue), 0)

if __name__ == "__main__":
    unittest.main()
```

Run the tests with `python -m unittest test_kv_cache.py`. All tests should pass, providing concrete evidence that the allocator works.

## Extending It: Your Roadmap to Senior-Level

1. **Persist pages to disk** – Write pages to a SQLite database or a memory‑mapped file so that the cache survives restarts. *Why it matters:* enables checkpointing and recovery in production inference services.  
2. **Horizontal scaling** – Partition the page space across multiple worker processes using a distributed hash table (e.g., Redis or Apache Ignite). *Why it matters:* allows the cache to scale beyond a single machine’s memory.  
3. **Observability** – Expose allocation rate, page faults, and queue latency via Prometheus metrics and a `/metrics` endpoint. *Why it matters:* operators need visibility to detect memory leaks or scheduling bottlenecks.  
4. **Fault tolerance** – Implement a heartbeat mechanism that detects lost requests and triggers page reclamation. *Why it matters:* prevents memory leaks in long‑running serving clusters.  
5. **Benchmarking suite** – Build a harness that measures throughput (tokens/sec) and latency (p50/p99) under varying batch sizes and page sizes. *Why it matters:* quantifies the benefit of paged allocation over contiguous caching.  
6. **Integration with an actual model** – Replace the dummy token advancement with a call to a lightweight transformer (e.g., using `transformers` + `torch`) to see real KV cache usage. *Why it matters:* validates the allocator in a realistic inference pipeline.

## Key Takeaways

- A paged KV cache eliminates fragmentation and enables fine‑grained memory reuse, directly improving GPU utilization.  
- Continuous batching increases throughput by overlapping prefill and decode phases across multiple requests.  
- Implementing these mechanisms in pure Python demonstrates core systems skills: page tables, free‑list management, and concurrent request scheduling.  
- The project is a springboard for senior‑level enhancements such as persistence, scaling, and observability.  
- Hiring managers recognize this combination of low‑level allocation, LLM internals, and production‑grade code as a strong indicator of backend/ML infrastructure readiness.

## Further Reading

- [PagedAttention: A Virtual Memory Approach to Efficient LLM Serving](https://arxiv.org/abs/2309.06180) – The original paper that introduced paged KV caching.  
- [vLLM: Easy, Efficient, and Effective LLM Serving](https://arxiv.org/abs/2305.07879) – Describes continuous batching and production‑scale implementation.  
- [Hugging Face Transformers Documentation – LLM Tutorial](https://huggingface.co/docs/transformers/main/en/llm_tutorial) – Walks through KV cache usage in popular models.  
- [Python `threading` Module – Official Docs](https://docs.python.org/3/library/threading.html) – Reference for building thread‑safe schedulers.  
- [SQLite in Python](https://docs.python.org/3/library/sqlite3.html) – A practical choice for persisting page metadata.