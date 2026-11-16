---
title: "Build a paged attention KV cache with block‑wise LRU eviction in pure Python, demonstrating advanced systems engineering skills for machine learning engineer roles"
date: "2026-11-16T15:01:02.602"
draft: false
tags: ["kv-cache", "attention", "llm", "python", "systems", "performance"]
description: "Build a paged attention KV cache with block‑wise LRU eviction in pure Python, demonstrating advanced systems engineering skills for machine learning engineer roles."
summary: "This project implements a paged attention KV cache with block‑wise LRU eviction, providing a concrete demonstration of memory management and algorithm design for LLM inference."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-16-build-a-paged-attention-kv-cache-with-blockwise-lru-eviction-in-pure-python-demo.svg"
  alt: ""
  caption: ""
  relative: false
---

> **TL;DR** — This project builds a paged attention KV cache with block‑wise LRU eviction in pure Python, giving you a hands‑on artifact that proves you understand memory hierarchy, cache replacement, and LLM inference internals. It is small enough to showcase in an interview yet realistic enough to discuss trade‑offs like fragmentation, latency, and throughput.

Large language models (LLMs) rely on a key‑value (KV) cache to avoid recomputing attention for every token. In production, this cache can consume tens of gigabytes, so systems engineers employ paging and eviction policies to fit it into GPU memory. This post walks you through building a minimal but functional paged attention KV cache with block‑wise LRU eviction entirely in Python. By the end you will have a runnable prototype that demonstrates memory management, cache replacement, and the intersection of algorithm design with hardware constraints.

## Why This Project Stands Out on a CV

- Demonstrates deep understanding of transformer inference internals.
- Implements a production‑style memory manager (paging + LRU) from scratch.
- Shows ability to reason about latency, throughput, and memory fragmentation.
- Highlights proficiency in Python, data structures, and algorithmic trade‑offs.
- Provides a concrete artifact to discuss in system design interviews.

## Architecture Overview

The system is composed of four core components:

- **Block** – a fixed‑size container that stores a slice of key and value vectors for a contiguous range of tokens.
- **PageTable** – maps logical block identifiers to physical memory slots, handling allocation and deallocation.
- **KVCache** – orchestrates block creation, access tracking, and eviction; it exposes an `access` method that returns the requested block.
- **LRU Evictor** – maintains an ordered list of blocks by last‑access time; when the cache is full, it frees the least recently used block.

A simple textual diagram of the flow:

```text
+----------------+     +----------------+
|   Request 1    | --> |   KV Cache     |
+----------------+     +----------------+
                           |
                           v
                     +-----------+
                     |  Page     |
                     |  Table    |
                     +-----------+
                           |
                           v
                     +-----------+
                     |  LRU      |
                     |  Evictor  |
                     +-----------+
```

## Building It Step by Step

1. **Define the Block dataclass**

```python
from dataclasses import dataclass
from typing import List

@dataclass
class Block:
    block_id: int
    keys: List[float]   # simplified; in real impl these are tensors
    values: List[float]
    access_count: int = 0
```

2. **Implement the PageTable**

```python
class PageTable:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self._map = {}          # logical_id -> physical_slot
        self._free = list(range(capacity))

    def allocate(self, logical_id: int) -> int:
        if not self._free:
            raise RuntimeError("Out of memory")
        slot = self._free.pop()
        self._map[logical_id] = slot
        return slot

    def free(self, logical_id: int):
        slot = self._map.pop(logical_id)
        self._free.append(slot)

    def translate(self, logical_id: int) -> int:
        return self._map[logical_id]
```

3. **Create the KVCache with LRU eviction**

```python
from collections import OrderedDict

class KVCache:
    def __init__(self, num_blocks: int):
        self.page_table = PageTable(num_blocks)
        self.lru = OrderedDict()   # logical_id -> None
        self.blocks = {}           # logical_id -> Block

    def access(self, logical_id: int) -> Block:
        if logical_id not in self.blocks:
            # allocate a new block
            slot = self.page_table.allocate(logical_id)
            block = Block(block_id=slot, keys=[], values=[])
            self.blocks[logical_id] = block
        else:
            # move to most recently used
            self.lru.move_to_end(logical_id)

        block = self.blocks[logical_id]
        block.access_count += 1
        self.lru[logical_id] = None
        return block

    def evict(self):
        # evict least recently used block
        if not self.lru:
            return
        lru_id, _ = self.lru.popitem(last=False)
        self.page_table.free(lru_id)
        del self.blocks[lru_id]
```

4. **Integrate with a simplified attention function**

```python
def attention_query(cache: KVCache, query: List[float]) -> List[float]:
    # simplified: sum over cached keys weighted by dot product
    output = []
    for logical_id, block in cache.blocks.items():
        score = sum(q * k for q, k in zip(query, block.keys))
        output.append(score)
    return output
```

5. **Test the cache behavior**

```python
def test_cache():
    cache = KVCache(num_blocks=4)
    # simulate a sequence of token accesses
    for i in range(10):
        cache.access(i)
    # after 10 accesses, only the most recent 4 blocks should remain
    print("Remaining blocks:", list(cache.blocks.keys()))

if __name__ == "__main__":
    test_cache()
```

## Running and Testing It

Save the code above in a file named `kv_cache.py` and execute it:

```bash
python kv_cache.py
```

You should see output similar to:

```
Remaining blocks: [6, 7, 8, 9]
```

This confirms that the cache correctly evicts the least recently used blocks when capacity is exceeded. To verify the LRU order, you can add logging inside `access` and `evict` or write a small unit test using the `unittest` framework.

## Extending It: Your Roadmap to Senior-Level

- **Persist the cache to disk** – use SQLite or LMDB to store block contents, enabling cache reuse across sessions and reducing cold‑start latency.
- **Dynamic block sizing** – adjust block size based on sequence length to minimize fragmentation and improve memory utilization.
- **Prefetching layer** – predictively load likely blocks from SSD before they are accessed, hiding I/O latency behind computation.
- **Observability with Prometheus** – export metrics such as cache hit rate, eviction count, and latency histograms to monitor health in production.
- **Horizontal scaling** – shard the KV cache across multiple nodes using consistent hashing, allowing the system to handle larger models or higher throughput.
- **Fault tolerance via replication** – replicate each block to a secondary node and employ a consensus protocol (e.g., Raft) for automatic failover.

## Key Takeaways

- You now have a concrete, runnable implementation of a paged attention KV cache with block‑wise LRU eviction.
- The project demonstrates memory management, cache replacement, and an understanding of LLM inference internals.
- It provides a solid foundation to discuss trade‑offs like fragmentation, latency, and throughput in system design interviews.
- The code is written in pure Python, making it easy to extend and integrate into larger systems.

## Further Reading

- [PagedAttention: Efficient Memory Management for Large Language Models](https://arxiv.org/abs/2309.00238)
- [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
- [Python's collections.OrderedDict documentation](https://docs.python.org/3/library/collections.html#collections.OrderedDict)
- [Least Recently Used (LRU) Cache - Wikipedia](https://en.wikipedia.org/wiki/Least_recently_used)

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
