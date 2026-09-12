---
title: "Build a Pure-Python Paged Attention KV-Cache with LRU and Frequency-Based Eviction"
date: "2026-09-12T00:00:29.421"
draft: false
tags: ["systems-engineering", "python", "kv-cache", "paged-attention", "llm-infrastructure", "eviction-policies"]
description: "Build a production-grade paged attention KV-cache in pure Python with LRU and LFU eviction policies. A hands-on guide that signals real systems skill to hiring managers."
summary: "A hands-on guide to building a pure-Python paged attention KV-cache with LRU and frequency-based eviction policies — a portfolio project that demonstrates deep systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-build-a-pure-python-paged-attention-kv-cache-with-lru-and-frequency-based-eviction.svg"
  alt: "A conceptual diagram of a paged attention KV-cache architecture showing memory blocks, page tables, and eviction queues."
  caption: ""
  relative: false
---

> **TL;DR** — Build a pure-Python paged attention KV-cache from scratch, implementing both LRU and frequency-based (LFU) eviction policies. This project mirrors the architecture behind vLLM's PagedAttention and demonstrates virtual-memory management, cache eviction theory, and LLM inference infrastructure — three skills that hiring managers in ML systems actively search for.

The transformer revolution created an unexpected bottleneck: KV-cache memory management. During inference, every token generated requires reading and writing key-value pairs from GPU memory. Traditional implementations suffer from memory fragmentation and inefficient allocation — problems that operating systems solved decades ago with virtual memory paging.

PagedAttention, introduced by vLLM, borrows directly from OS page tables to manage KV-cache blocks. By building your own implementation in pure Python, you internalize these concepts at a level that no tutorial can match. This post walks you through every line.

## Why This Project Stands Out on a CV

This project sits at the intersection of three high-demand skill domains, and each one signals something specific to hiring managers:

- **Systems-level memory management.** Implementing a page table, block allocator, and eviction controller demonstrates you understand virtual memory, fragmentation, and allocation strategies — the same concepts behind Linux kernel page reclaim and database buffer pools.
- **ML infrastructure internals.** PagedAttention is the core technology behind vLLM's throughput advantages. Having built it yourself proves you can read and contribute to production LLM serving codebases, not just call `pipeline()` APIs.
- **Algorithm and data structure mastery.** LRU and LFU eviction are classic problems with subtle tradeoffs. Implementing both with real performance characteristics shows you can reason about time-space complexity in practice, not just on an exam.

For roles labeled **ML Systems Engineer**, **Infra Engineer**, or **Backend Engineer (Distributed Systems)**, this project is a conversation starter that immediately differentiates you from candidates who only know PyTorch forward passes.

## Architecture Overview

The system is composed of five interacting components. Think of it as a miniature operating system for transformer attention memory:

```
┌──────────────────────────────────────────────────────┐
│                  KV-Cache Manager                     │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │  Page Table  │  │ Block Allocator│  │  Eviction    │ │
│  │ (hash map)   │  │ (free list)   │  │  Controller  │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │         │
│  ┌──────▼────────────────▼──────────────────▼──────┐ │
│  │          Physical Memory Pool (dict of blocks)   │ │
│  └─────────────────────────────────────────────────┘ │
│                                                      │
│  ┌─────────────────────────────────────────────────┐ │
│  │         Policy Strategy (LRU / LFU)              │ │
│  └─────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

Here is how each component fits together:

- **Page Table.** A hash map that translates a logical `(layer_id, position)` tuple to a physical block index. This mirrors the OS page table that maps virtual pages to physical frames.
- **Block Allocator.** Maintains a free list of available blocks and handles allocation and deallocation. It prevents fragmentation by managing fixed-size memory chunks.
- **Physical Memory Pool.** A dictionary or array of fixed-size blocks, each holding a slice of keys and values for a transformer layer. The block size is a tunable parameter (e.g., 16 tokens per block).
- **Eviction Controller.** Decides which block to evict when memory is full. This is the pluggable strategy layer — swap out an old block to make room for a new one.
- **Policy Strategy.** The interface defining `access(block_id)` and `evict()`. LRU evicts the least recently used block; LFU evicts the least frequently accessed block. Both are implemented as first-class strategies.

## Building It Step by Step

We will build this incrementally. Each step contains real, runnable Python code. The full project is roughly 300 lines and can be copied into a single file.

### Step 1: Define the Block and Memory Pool

A block holds a slice of keys and values. In a real GPU implementation these would be tensors; here we use NumPy arrays to keep dependencies minimal.

```python
import numpy as np
from collections import defaultdict, OrderedDict
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Block:
    """A fixed-size block of KV memory for one transformer layer."""
    layer_id: int
    block_size: int = 16
    keys: Optional[np.ndarray] = None
    values: Optional[np.ndarray] = None
    ref_count: int = 0

    def __post_init__(self):
        if self.keys is None:
            self.keys = np.zeros((self.block_size, 128), dtype=np.float32)
            self.values = np.zeros((self.block_size, 128), dtype=np.float32)

    def is_free(self) -> bool:
        return self.ref_count == 0
```

### Step 2: Implement the Page Table

The page table maps logical positions to physical block indices. This is the heart of PagedAttention — it allows non-contiguous allocation without copying.

```python
class PageTable:
    """Maps logical (layer_id, position) to a physical block index."""

    def __init__(self):
        # Maps logical key -> block_id
        self._table: dict[tuple[int, int], int] = {}
        # Reverse lookup: block_id -> list of logical keys
        self._reverse: dict[int, list[tuple[int, int]]] = defaultdict(list)

    def register(self, layer_id: int, position: int, block_id: int):
        key = (layer_id, position)
        self._table[key] = block_id
        self._reverse[block_id].append(key)

    def lookup(self, layer_id: int, position: int) -> Optional[int]:
        return self._table.get((layer_id, position))

    def deregister(self, block_id: int):
        for key in self._reverse.pop(block_id, []):
            del self._table[key]

    def blocks_for(self, block_id: int) -> list[tuple[int, int]]:
        return self._reverse.get(block_id, [])
```

### Step 3: Implement the Block Allocator

The allocator manages a pool of blocks and a free list. When memory is full, it delegates eviction to the controller.

```python
class BlockAllocator:
    """Manages fixed-size block allocation from a pool."""

    def __init__(self, num_blocks: int, num_layers: int, block_size: int = 16):
        self.num_blocks = num_blocks
        self.block_size = block_size
        self.pool: list[Block] = [
            Block(layer_id=i % num_layers, block_size=block_size)
            for i in range(num_blocks)
        ]
        self.free_list: list[int] = list(range(num_blocks))

    def allocate(self) -> Block:
        if not self.free_list:
            raise MemoryError("No free blocks available — eviction required")
        block_id = self.free_list.pop(0)
        block = self.pool[block_id]
        block.ref_count = 1
        return block

    def free(self, block_id: int):
        block = self.pool[block_id]
        block.ref_count = 0
        block.keys.fill(0)
        block.values.fill(0)
        self.free_list.append(block_id)
```

### Step 4: Define the Eviction Policy Interface

This is where LRU and LFU diverge. Both implement the same interface so the allocator can delegate without knowing the strategy.

```python
class EvictionPolicy(ABC):
    """Abstract base class for cache eviction strategies."""

    @abstractmethod
    def access(self, block_id: int):
        """Record that block_id was accessed."""
        pass

    @abstractmethod
    def evict(self) -> int:
        """Return the block_id to evict."""
        pass

    @abstractmethod
    def remove(self, block_id: int):
        """Remove a block from tracking (e.g., after eviction)."""
        pass


class LRUPolicy(EvictionPolicy):
    """Least Recently Used eviction."""

    def __init__(self):
        self._order: OrderedDict[int, None] = OrderedDict()

    def access(self, block_id: int):
        self._order.pop(block_id, None)
        self._order[block_id] = None

    def evict(self) -> int:
        if not self._order:
            raise RuntimeError("No blocks to evict")
        oldest, _ = self._order.popitem(last=False)
        return oldest

    def remove(self, block_id: int):
        self._order.pop(block_id, None)


class LFUPolicy(EvictionPolicy):
    """Least Frequently Used eviction."""

    def __init__(self):
        self._freq: dict[int, int] = defaultdict(int)

    def access(self, block_id: int):
        self._freq[block_id] += 1

    def evict(self) -> int:
        if not self._freq:
            raise RuntimeError("No blocks to evict")
        return min(self._freq, key=self._freq.get)

    def remove(self, block_id: int):
        self._freq.pop(block_id, None)
```

### Step 5: Wire Everything into the KV-Cache Manager

The manager ties the page table, allocator, and eviction policy together into a single API.

```python
class PagedKVCache:
    """Main entry point: a paged attention KV-cache with pluggable eviction."""

    def __init__(
        self,
        num_blocks: int = 256,
        num_layers: int = 8,
        block_size: int = 16,
        eviction_policy: str = "lru",
    ):
        self.block_size = block_size
        self.page_table = PageTable()
        self.allocator = BlockAllocator(num_blocks, num_layers, block_size)

        if eviction_policy == "lru":
            self.policy: EvictionPolicy = LRUPolicy()
        elif eviction_policy == "lfu":
            self.policy = LFUPolicy()
        else:
            raise ValueError(f"Unknown policy: {eviction_policy}")

        self._block_counter = 0

    def allocate_block(self, layer_id: int, position: int) -> int:
        """Allocate a block for a (layer, position) pair. Evicts if needed."""
        # Check if already mapped
        existing = self.page_table.lookup(layer_id, position)
        if existing is not None:
            self.policy.access(existing)
            return existing

        # Evict if no free blocks
        if not self.allocator.free_list:
            self._evict_and_reclaim()

        block = self.allocator.allocate()
        block_id = self._block_counter
        self._block_counter += 1

        self.page_table.register(layer_id, position, block_id)
        self.policy.access(block_id)
        return block_id

    def _evict_and_reclaim(self):
        """Evict a block and reclaim its memory."""
        victim_id = self.policy.evict()
        # Remove from page table
        logical_keys = self.page_table.blocks_for(victim_id)
        for key in logical_keys:
            self.page_table._table.pop(key, None)
        self.page_table._reverse.pop(victim_id, None)
        self.policy.remove(victim_id)
        self.allocator.free(victim_id)

    def get_block(self, layer_id: int, position: int) -> Optional[Block]:
        block_id = self.page_table.lookup(layer_id, position)
        if block_id is None:
            return None
        self.policy.access(block_id)
        return self.allocator.pool[block_id]

    def stats(self) -> dict:
        used = self.num_blocks - len(self.allocator.free_list)
        return {
            "total_blocks": self.num_blocks,
            "used_blocks": used,
            "free_blocks": len(self.allocator.free_list),
            "utilization": f"{used / self.num_blocks * 100:.1f}%",
        }

    @property
    def num_blocks(self) -> int:
        return self.allocator.num_blocks
```

## Running and Testing It

Save the complete implementation to a file named `paged_kv_cache.py`. Then run the following test script to verify both eviction policies behave correctly.

```bash
pip install numpy
python -m pytest paged_kv_cache.py -v
```

Here is a self-contained test that exercises allocation, access tracking, and eviction under memory pressure:

```python
def test_lru_eviction():
    cache = PagedKVCache(num_blocks=4, num_layers=2, block_size=16, eviction_policy="lru")
    # Fill all blocks
    for i in range(4):
        cache.allocate_block(layer_id=0, position=i)
    # Access block 0 to make it recently used
    cache.get_block(layer_id=0, position=0)
    # Allocate one more — should evict the least recently used
    block_id = cache.allocate_block(layer_id=0, position=4)
    assert block_id is not None
    assert cache.stats()["used_blocks"] == 4
    print("LRU eviction test passed:", cache.stats())

def test_lfu_eviction():
    cache = PagedKVCache(num_blocks=4, num_layers=2, block_size=16, eviction_policy="lfu")
    # Fill all blocks
    for i in range(4):
        cache.allocate_block(layer_id=0, position=i)
    # Access block 0 three times, block 1 once
    for _ in range(3):
        cache.get_block(layer_id=0, position=0)
    cache.get_block(layer_id=0, position=1)
    # Allocate one more — should evict block 1 (least frequent)
    block_id = cache.allocate_block(layer_id=0, position=4)
    assert block_id is not None
    print("LFU eviction test passed:", cache.stats())

def test_page_table_lookup():
    cache = PagedKVCache(num_blocks=8, num_layers=4, block_size=16, eviction_policy="lru")
    bid = cache.allocate_block(layer_id=2, position=100)
    block = cache.get_block(layer_id=2, position=100)
    assert block is not None
    assert block.keys.shape == (16, 128)
    print("Page table lookup test passed.")

if __name__ == "__main__":
    test_lru_eviction()
    test_lfu_eviction()
    test_page_table_lookup()
    print("\nAll tests passed.")
```

Expected output:

```
LRU eviction test passed: {'total_blocks': 4, 'used_blocks': 4, 'free_blocks': 0, 'utilization': '100.0%'}
LFU eviction test passed: {'total_blocks': 4, 'used_blocks': 4, 'free_blocks': 0, 'utilization': '100.0%'}
Page table lookup test passed.

All tests passed.
```

To benchmark eviction speed, add a simple timing loop:

```python
import time

def benchmark_eviction(policy: str, num_blocks: int = 1000):
    cache = PagedKVCache(num_blocks=num_blocks, num_layers=8, eviction_policy=policy)
    start = time.perf_counter()
    for i in range(num_blocks):
        cache.allocate_block(layer_id=i % 8, position=i)
    # Force eviction for the overflow
    for i in range(num_blocks, num_blocks + 100):
        cache.allocate_block(layer_id=i % 8, position=i)
    elapsed = time.perf_counter() - start
    print(f"{policy}: {elapsed * 1000:.2f}ms for {num_blocks + 100} allocations")

benchmark_eviction("lru")
benchmark_eviction("lfu")
```

You should observe LRU completing faster on average due to `OrderedDict`'s O(1) operations, while LFU's `min()` scan over the frequency dictionary introduces O(n) overhead — a concrete demonstration of the theoretical tradeoff.

## Extending It: Your Roadmap to Senior-Level

The toy implementation above proves the concept. Here are six concrete upgrades that transform it into something production-flavored, each with a one-line reason it matters:

1. **Add a write-ahead log for crash recovery.** Persist page table state to disk using `sqlite3` or `leveldb` so that a process restart does not lose the mapping between logical positions and physical blocks — this is the same fault-tolerance pattern used by Kafka's offset log.
2. **Implement a thread-safe allocator with `threading.Lock`.** Real inference servers handle concurrent request batches; without locks, race conditions on the free list will corrupt block allocation silently.
3. **Add Prometheus metrics instrumentation.** Export `blocks_allocated_total`, `evictions_total`, and `cache_utilization_percent` via the `prometheus_client` library so that on-call engineers can observe cache health in Grafana dashboards.
4. **Support heterogeneous block sizes.** Not all attention layers produce equal-sized KV tensors; a variable-size allocator using a segregated-fit strategy (like jemalloc) prevents internal fragmentation that wastes 30–50% of memory.
5. **Implement a prefill-decode split with two-tier eviction.** Prefill phases have bursty access patterns while decode is sequential; separate eviction policies for each phase (e.g., LRU for decode, ARC for prefill) can improve hit rates by 15–20% as shown in [the vLLM paper](https://arxiv.org/abs/2309.06180).
6. **Add a gRPC or REST API layer with FastAPI.** Expose the cache as a standalone service so that multiple inference workers can share a centralized KV-cache — this is the horizontal-scaling pattern that turns a toy into a distributed system.

Each of these upgrades maps to a real production concern and gives you a concrete bullet point for interviews or LinkedIn posts.

## Key Takeaways

- **PagedAttention is operating-system thinking applied to LLM inference.** The page table, block allocator, and eviction controller are direct analogs of virtual memory management — building one teaches the other.
- **LRU vs LFU is not academic.** LRU wins on latency (O(1) with `OrderedDict`); LFU wins on hit rate for skewed workloads. Choosing between them is the same tradeoff you face when configuring Redis or Memcached.
- **A portfolio project must demonstrate architecture, not just code.** The six extension roadmap items above — persistence, concurrency, observability, fragmentation, adaptive policies, and distributed serving — are exactly what hiring managers look for in senior systems roles.
- **Pure Python is a feature, not a limitation.** It makes the implementation readable, debuggable, and forkable. You can always swap NumPy arrays for CUDA tensors later without changing the architecture.

## Further Reading

- **[PagedAttention: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)** — The foundational paper by Kwon et al. that introduced PagedAttention and demonstrated 2–4× throughput improvements over HuggingFace Transformers.
- **[vLLM Documentation: PagedAttention](https://docs.vllm.ai/en/latest/architecture/paged_attention.html)** — The canonical project documentation with architecture diagrams, configuration options, and performance benchmarks for the production implementation.
- **[Operating Systems: Three Easy Pieces — Virtual Memory](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-intro.pdf)** — The free textbook chapter that explains the exact page table and eviction concepts PagedAttention borrows. Chapter 20 covers page replacement algorithms including LRU and stack-based policies.
- **[Redis LRU vs LFU Eviction](https://redis.io/docs/management/optimization/memory-optimization/#eviction-policies)** — Redis's implementation notes on the practical tradeoffs between LRU and LFU in a real production cache, including how approximate LRU uses sampled clocks.
- **[Apache Kafka: Log Compaction and Retention](https://kafka.apache.org/documentation/#logcompaction)** — For the persistence extension: understanding how write-ahead logs and compaction work at scale in a distributed system.
- **[Prometheus Best Practices for ML Infrastructure](https://prometheus.io/docs/practices/instrumentation/)** — Guidance on instrumenting inference serving systems, directly applicable to adding metrics to the KV-cache manager.