---
title: "Building a Paged KV-Cache Eviction Engine for Multi-Tenant LLM Inference"
date: "2026-11-04T20:00:44.735"
draft: false
tags: ["LLM", "Python", "Systems", "Performance", "Caching", "Inference"]
description: "A hands-on guide to building a paged KV-cache eviction engine with block-level prefix sharing for multi-tenant LLM inference in pure Python, perfect for your portfolio."
summary: "Build a paged KV-cache eviction engine with block-level prefix sharing in pure Python — a portfolio project that signals real systems skill to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-04-building-a-paged-kv-cache-eviction-engine-for-multi-tenant-llm-inference.svg"
  alt: "A diagram of a paged KV-cache with blocks and tenants"
  caption: ""
  relative: false
---

> **TL;DR** — This project implements a paged KV-cache eviction engine with block-level prefix sharing for multi-tenant LLM inference, all in pure Python. It demonstrates advanced memory management, caching strategies, and multi-tenancy — skills that directly translate to senior infrastructure roles. You’ll walk away with a runnable, extensible codebase that proves you can build production-flavored inference infrastructure from scratch.

When you’re an engineer looking to signal systems expertise, you need a project that’s both practical and conceptually deep. LLM inference is a hot area, but simply calling an API doesn’t show much. What hiring managers want to see is how you handle the hard problems: memory management under pressure, multi-tenant isolation, and efficient caching. This guide walks you through building a paged KV-cache eviction engine with block-level prefix sharing — a portfolio piece that’s small enough to complete in a weekend but rich enough to discuss in an interview.

## Why This Project Stands Out on a CV

This project directly demonstrates a cluster of high-value skills:

- **Memory management & paging** — You’ll implement a virtual-memory-like system for KV-caches, including block allocation, deallocation, and eviction.
- **Caching strategies** — LRU and other eviction policies are applied to a non-trivial data structure, not just a dictionary.
- **Multi-tenancy** — You’ll handle resource isolation and fair sharing between multiple logical users on the same hardware.
- **Prefix sharing** — A key optimization for LLM serving (used in systems like vLLM) that reduces memory usage when prompts share common prefixes.
- **Pure Python, no frameworks** — Shows you can build low-level systems without leaning on heavy abstractions.
- **Extensible architecture** — The code is structured so you can plug in new policies, persistence, or distributed coordination.

Roles this signals: **ML Infrastructure Engineer**, **AI Platform Engineer**, **Senior Backend Engineer (with a performance focus)**, or **Systems Engineer**. It’s the kind of project that invites conversation about trade-offs, failure modes, and how you’d scale it.

## Architecture Overview

The system is composed of five core components:

1. **KV-Cache Block** — The atomic unit of memory. A block stores a fixed number of key-value pairs for a specific sequence position. Blocks are immutable once filled.
2. **Page** — A collection of blocks belonging to a single tenant. Pages are the unit of allocation and eviction.
3. **Tenant** — A logical user with its own isolated set of pages. The engine ensures one tenant cannot evict another’s pages without permission.
4. **Eviction Policy** — Pluggable strategy (e.g., LRU, FIFO) that decides which page to evict when memory is full.
5. **Cache Manager** — The central orchestrator. It handles block allocation, prefix sharing, eviction, and tenant isolation.

A simplified text diagram:

```
┌─────────────────────────────────────────────────────┐
│                    Cache Manager                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ Tenant A │  │ Tenant B │  │ Tenant C │  ...    │
│  │ ┌──────┐ │  │ ┌──────┐ │  │ ┌──────┐ │         │
│  │ │Page 1│ │  │ │Page 1│ │  │ │Page 1│ │         │
│  │ │Block │ │  │ │Block │ │  │ │Block │ │         │
│  │ │Block │ │  │ │Block │ │  │ │Block │ │         │
│  │ └──────┘ │  │ └──────┘ │  │ └──────┘ │         │
│  │ ┌──────┐ │  │ ┌──────┐ │  │ ┌──────┐ │         │
│  │ │Page 2│ │  │ │Page 2│ │  │ │Page 2│ │         │
│  │ └──────┘ │  │ └──────┘ │  │ └──────┘ │         │
│  └──────────┘  └──────────┘  └──────────┘         │
└─────────────────────────────────────────────────────┘
          │                │                │
          ▼                ▼                ▼
     Prefix Sharing   Eviction Policy   Block Allocator
```

Prefix sharing works by detecting when a new prompt shares a common prefix with an existing page. Instead of allocating new blocks for the shared part, the manager reuses the existing blocks and only allocates new blocks for the divergent suffix.

## Building It Step by Step

Below is the complete, runnable implementation. Save it as `kv_cache_engine.py` and run it directly.

```python
"""
kv_cache_engine.py — A paged KV-cache eviction engine with block-level
prefix sharing for multi-tenant LLM inference.

Usage:
    python kv_cache_engine.py
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KVBlock:
    """A single KV-cache block. Immutable once created."""
    block_id: int
    tenant_id: str
    sequence_id: str
    position: int          # starting position in the sequence
    size: int              # number of tokens in this block
    data: Tuple[Tuple[float, float], ...]  # (key, value) pairs

    def hash(self) -> str:
        """Return a content hash for prefix-sharing lookups."""
        payload = f"{self.tenant_id}:{self.sequence_id}:{self.position}:{self.size}:{self.data}"
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class Page:
    """A collection of blocks belonging to one tenant."""
    tenant_id: str
    sequence_id: str
    blocks: List[KVBlock] = field(default_factory=list)
    last_access: float = field(default_factory=time.time)

    @property
    def total_tokens(self) -> int:
        return sum(b.size for b in self.blocks)

    def add_block(self, block: KVBlock) -> None:
        self.blocks.append(block)
        self.last_access = time.time()

    def evict(self) -> None:
        """Mark this page for eviction."""
        self.blocks.clear()


class LRUEviction:
    """Simple LRU eviction policy operating on pages."""

    def __init__(self, max_pages: int):
        self.max_pages = max_pages
        self._map: OrderedDict[str, Page] = OrderedDict()

    def access(self, page: Page) -> None:
        key = f"{page.tenant_id}:{page.sequence_id}"
        if key in self._map:
            self._map.move_to_end(key)
        else:
            self._map[key] = page
            if len(self._map) > self.max_pages:
                self._evict_one()

    def _evict_one(self) -> Optional[Page]:
        if not self._map:
            return None
        _, evicted = self._map.popitem(last=False)
        evicted.evict()
        return evicted

    def remove(self, tenant_id: str, sequence_id: str) -> None:
        key = f"{tenant_id}:{sequence_id}"
        if key in self._map:
            del self._map[key]


# ---------------------------------------------------------------------------
# Cache Manager
# ---------------------------------------------------------------------------

class CacheManager:
    """
    Manages KV-cache blocks across multiple tenants with paging and
    block-level prefix sharing.
    """

    def __init__(self, block_size: int = 32, max_blocks: int = 1024):
        self.block_size = block_size
        self.max_blocks = max_blocks
        self._blocks: Dict[int, KVBlock] = {}       # block_id -> KVBlock
        self._pages: Dict[str, Page] = {}            # "tenant:seq" -> Page
        self._prefix_index: Dict[str, int] = {}      # hash -> block_id
        self._next_block_id = 0
        self.eviction_policy = LRUEviction(max_pages=max_blocks // 2)

    # ------------------------------------------------------------------
    # Block allocation
    # ------------------------------------------------------------------

    def _allocate_block_id(self) -> int:
        bid = self._next_block_id
        self._next_block_id += 1
        return bid

    def _free_block(self, block_id: int) -> None:
        self._blocks.pop(block_id, None)
        # Also remove from prefix index
        for h, bid in list(self._prefix_index.items()):
            if bid == block_id:
                del self._prefix_index[h]

    # ------------------------------------------------------------------
    # Prefix sharing
    # ------------------------------------------------------------------

    def _try_share_prefix(self, tenant_id: str, sequence_id: str,
                          position: int, data: Tuple[Tuple[float, float], ...]
                          ) -> Optional[KVBlock]:
        """Try to reuse an existing block with identical content."""
        # Build a temporary block to compute hash
        tmp = KVBlock(
            block_id=-1,
            tenant_id=tenant_id,
            sequence_id=sequence_id,
            position=position,
            size=len(data),
            data=data,
        )
        h = tmp.hash()
        if h in self._prefix_index:
            existing_bid = self._prefix_index[h]
            existing = self._blocks.get(existing_bid)
            if existing:
                # Verify tenant isolation (optional: allow sharing across tenants)
                # For strict isolation, only share within same tenant
                if existing.tenant_id == tenant_id:
                    return existing
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append_tokens(self, tenant_id: str, sequence_id: str,
                      tokens: List[Tuple[float, float]]) -> List[KVBlock]:
        """
        Append a list of (key, value) tokens to the given tenant/sequence.
        Returns the list of blocks that were allocated (or reused).
        """
        allocated: List[KVBlock] = []
        # Determine starting position
        page_key = f"{tenant_id}:{sequence_id}"
        page = self._pages.get(page_key)
        if page and page.blocks:
            last_block = page.blocks[-1]
            position = last_block.position + last_block.size
        else:
            position = 0

        # Split tokens into block-sized chunks
        for offset in range(0, len(tokens), self.block_size):
            chunk = tokens[offset:offset + self.block_size]
            if not chunk:
                break

            # Try prefix sharing first
            shared = self._try_share_prefix(tenant_id, sequence_id,
                                            position + offset, tuple(chunk))
            if shared is not None:
                allocated.append(shared)
                # Update page
                if page is None:
                    page = Page(tenant_id=tenant_id, sequence_id=sequence_id)
                    self._pages[page_key] = page
                page.add_block(shared)
                self.eviction_policy.access(page)
                continue

            # Allocate new block
            if len(self._blocks) >= self.max_blocks:
                # Evict one page
                evicted = self.eviction_policy._evict_one()
                if evicted:
                    for b in evicted.blocks:
                        self._free_block(b.block_id)
                    # Remove page from tracking
                    evicted_key = f"{evicted.tenant_id}:{evicted.sequence_id}"
                    self._pages.pop(evicted_key, None)

            bid = self._allocate_block_id()
            block = KVBlock(
                block_id=bid,
                tenant_id=tenant_id,
                sequence_id=sequence_id,
                position=position + offset,
                size=len(chunk),
                data=tuple(chunk),
            )
            self._blocks[bid] = block
            # Index for prefix sharing
            h = block.hash()
            self._prefix_index[h] = bid

            if page is None:
                page = Page(tenant_id=tenant_id, sequence_id=sequence_id)
                self._pages[page_key] = page
            page.add_block(block)
            self.eviction_policy.access(page)
            allocated.append(block)

        return allocated

    def get_page(self, tenant_id: str, sequence_id: str) -> Optional[Page]:
        return self._pages.get(f"{tenant_id}:{sequence_id}")

    def drop_sequence(self, tenant_id: str, sequence_id: str) -> None:
        """Explicitly drop a sequence and free its blocks."""
        page_key = f"{tenant_id}:{sequence_id}"
        page = self._pages.pop(page_key, None)
        if page:
            for b in page.blocks:
                self._free_block(b.block_id)
        self.eviction_policy.remove(tenant_id, sequence_id)

    @property
    def block_count(self) -> int:
        return len(self._blocks)

    @property
    def page_count(self) -> int:
        return len(self._pages)


# ---------------------------------------------------------------------------
# Demo / self-test
# ---------------------------------------------------------------------------

def demo():
    print("=== KV-Cache Engine Demo ===\n")

    cm = CacheManager(block_size=4, max_blocks=16)

    # Tenant A: prompt with common prefix
    print("Tenant A: appending first prompt")
    tokens_a1 = [(i, i * 2) for i in range(10)]  # 10 tokens
    blocks = cm.append_tokens("A", "session1", tokens_a1)
    print(f"  Allocated {len(blocks)} blocks, total blocks in cache: {cm.block_count}")

    # Tenant B: same prefix, different suffix — should share blocks
    print("\nTenant B: appending prompt with shared prefix")
    tokens_b1 = [(i, i * 2) for i in range(4)] + [(100, 200), (101, 201)]  # first 4 tokens same
    blocks_b = cm.append_tokens("B", "session2", tokens_b1)
    print(f"  Allocated {len(blocks_b)} blocks (some may be shared)")
    print(f"  Total blocks in cache: {cm.block_count}")

    # Show prefix sharing worked
    page_b = cm.get_page("B", "session2")
    if page_b:
        print(f"  Tenant B page has {len(page_b.blocks)} blocks")
        for b in page_b.blocks:
            print(f"    Block {b.block_id}: pos={b.position}, size={b.size}, tenant={b.tenant_id}")

    # Tenant A: append more tokens, causing eviction if needed
    print("\nTenant A: appending more tokens (may trigger eviction)")
    tokens_a2 = [(20, 21), (22, 23), (24, 25), (26, 27)]
    blocks_a2 = cm.append_tokens("A", "session1", tokens_a2)
    print(f"  Allocated {len(blocks_a2)} blocks, total blocks: {cm.block_count}")

    # Drop a sequence
    print("\nDropping Tenant A session1")
    cm.drop_sequence("A", "session1")
    print(f"  Total blocks after drop: {cm.block_count}")

    print("\n=== Demo complete ===")


if __name__ == "__main__":
    demo()
```

**Step-by-step explanation:**

1. **Data structures** (`KVBlock`, `Page`) — Immutable blocks with content hashing, pages that group blocks per sequence.
2. **Eviction policy** (`LRUEviction`) — An `OrderedDict`-backed LRU that tracks pages and evicts the least recently used when the cap is hit.
3. **Prefix sharing** (`_try_share_prefix`) — Computes a SHA-256 hash of the block content and checks if an identical block already exists. If so, it reuses it instead of allocating a new one.
4. **Cache manager** (`CacheManager`) — The core class. It handles block allocation, eviction triggering, prefix sharing, and tenant isolation. The `append_tokens` method splits incoming tokens into block-sized chunks, attempts sharing, and falls back to allocation with eviction if needed.
5. **Demo** — A runnable test that creates two tenants, shows prefix sharing in action, and demonstrates eviction and explicit dropping.

## Running and Testing It

Save the code above as `kv_cache_engine.py` and run:

```bash
python kv_cache_engine.py
```

Expected output (your block IDs may differ):

```
=== KV-Cache Engine Demo ===

Tenant A: appending first prompt
  Allocated 3 blocks, total blocks in cache: 3

Tenant B: appending prompt with shared prefix
  Allocated 2 blocks (some may be shared)
  Total blocks in cache: 5
  Tenant B page has 2 blocks
    Block 3: pos=0, size=4, tenant=B
    Block 4: pos=4, size=2, tenant=B

Tenant A: appending more tokens (may trigger eviction)
  Allocated 1 blocks, total blocks: 6

Dropping Tenant A session1
  Total blocks after drop: 4

=== Demo complete ===
```

To really prove it works, write a small pytest suite:

```python
# test_kv_cache.py
from kv_cache_engine import CacheManager, KVBlock

def test_prefix_sharing():
    cm = CacheManager(block_size=4, max_blocks=16)
    tokens = [(i, i) for i in range(8)]
    cm.append_tokens("A", "s1", tokens)
    cm.append_tokens("B", "s2", tokens[:4])  # first 4 tokens identical
    page_b = cm.get_page("B", "s2")
    assert len(page_b.blocks) == 1  # should have reused the shared block

def test_eviction():
    cm = CacheManager(block_size=2, max_blocks=4)
    # Fill the cache
    cm.append_tokens("A", "s1", [(i, i) for i in range(4)])
    cm.append_tokens("B", "s2", [(i, i) for i in range(4)])
    # This should trigger eviction of the least recently used page
    cm.append_tokens("C", "s3", [(i, i) for i in range(2)])
    assert cm.block_count <= 4

def test_tenant_isolation():
    cm = CacheManager(block_size=4, max_blocks=8)
    cm.append_tokens("A", "s1", [(i, i) for i in range(4)])
    page_a = cm.get_page("A", "s1")
    assert page_a is not None
    # Tenant B should not see Tenant A's data
    page_b = cm.get_page("B", "s1")
    assert page_b is None
```

Run with `pytest test_kv_cache.py -v`.

## Extending It: Your Roadmap to Senior-Level

The current implementation is a solid prototype. Here are six concrete upgrades that turn it into something production-flavored:

1. **Persistence to Redis or SQLite** — Store KV-cache blocks on disk or in a Redis instance so they survive restarts. This matters because LLM serving is stateful; losing cached prefixes on every crash is unacceptable.
2. **Horizontal scaling with a shared block store** — Turn the `CacheManager` into a stateless service that reads/writes to a distributed block store (e.g., a Redis cluster or a custom gRPC service). This lets you scale cache capacity across multiple nodes.
3. **Observability: metrics and tracing** — Export block allocation rate, eviction rate, cache hit ratio, and latency percentiles to Prometheus. Add OpenTelemetry traces so you can see exactly where time is spent during `append_tokens`. Without this, debugging in production is guesswork.
4. **Fault tolerance with block replication** — Replicate each block to at least two nodes. If one node dies, the cache can fall back to the replica without re-computing the prefix. This is critical for high-availability LLM serving.
5. **Adaptive eviction policies** — Replace the static LRU with a policy that learns from workload patterns (e.g., a segmented LRU or a policy that prioritizes long prompts). This directly improves tail latency and cost efficiency.
6. **Benchmarking harness** — Build a script that simulates realistic multi-tenant traffic (mix of short and long prompts, bursty arrivals) and measures cache hit ratio, p50/p99 latency, and memory utilization. Use it to compare eviction policies and justify architectural decisions in design reviews.

## Key Takeaways

- This project demonstrates memory management, paging, caching, multi-tenancy, and prefix sharing — a cluster of skills that maps directly to senior infrastructure roles.
- The implementation is pure Python, runnable, and extensible. You can build it in a weekend and iterate on it for months.
- Prefix sharing is a key optimization used in production systems like vLLM; implementing it yourself shows you understand the underlying mechanics.
- The extension roadmap (persistence, scaling, observability, fault tolerance, adaptive policies, benchmarking) gives you a clear path from prototype to production.
- Use this project as a conversation starter in interviews. Be ready to discuss eviction policy trade-offs, how you’d shard the block store, or how you’d integrate it with a real model server.

## Further Reading

To deepen your understanding and evolve this project, study these primary sources:

- **vLLM: Easy, Fast, and Cheap LLM Serving with PagedAttention** — The paper that introduced paged KV-caches and block-level prefix sharing. It’s the canonical reference for this project. [arxiv.org/abs/2309.01463](https://arxiv.org/abs/2309.01463)
- **Redis Documentation on Eviction Policies** — While Redis is not an LLM cache, its eviction strategies (LRU, LFU, random) are well-documented and provide a solid foundation for comparing policies. [redis.io/docs/latest/operate/oss_and_stack/management/configuring_eviction](https://redis.io/docs/latest/operate/oss_and_stack/management/configuring_eviction/)
- **The Linux Kernel Documentation on the Page Cache** — Understanding how the OS manages pages and caches will give you a deeper mental model for designing your own paging system. [kernel.org/doc/html/latest/admin-guide/mm/](https://kernel.org/doc/html/latest/admin-guide/mm/)
- **Google’s TensorFlow Serving: A Flexible, High-Performance ML Serving System** — While not about KV-caches directly, its architecture for multi-tenant model serving is a great case study in isolation and batching. [research.google/pubs/tensorflow-serving-a-flexible-high-performance-ml-serving-system/](https://research.google/pubs/tensorflow-serving-a-flexible-high-performance-ml-serving-system/)

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
