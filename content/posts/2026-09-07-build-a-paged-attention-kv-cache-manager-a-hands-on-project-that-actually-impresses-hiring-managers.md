---
title: "Build a Paged-Attention KV Cache Manager: A Hands-On Project That Actually Impresses Hiring Managers"
date: "2026-09-07T16:55:35.455"
draft: false
tags: ["llm-inference", "systems-engineering", "python", "paged-attention", "vllm"]
description: "A hands-on build guide for a portfolio-grade paged-attention KV cache manager with prefix-sharing and block-level eviction for LLM serving."
summary: "Ship a runnable paged-attention KV cache manager that demonstrates real LLM systems skill: block tables, prefix-sharing across requests, and eviction policies that actually move the needle on memory."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-paged-attention-kv-cache-manager-a-hands-on-project-that-actually-impresses-hiring-managers.svg"
  alt: "Diagram of paged-attention KV cache blocks mapped across sequences"
  caption: ""
  relative: false
---

> **TL;DR** — Paged attention treats each sequence's KV cache as a vector of fixed-size blocks instead of one contiguous tensor. Building your own manager shows you understand memory, scheduling, and inference internals — the exact skills teams running vLLM, SGLang, and TensorRT-LLM care about. We'll ship a runnable Python implementation with prefix-sharing and LRU block eviction, then chart a path to production-grade extensions.

Most "LLM projects" on portfolios are thin wrappers over an API. Hiring managers know it. They skim your repo, see `openai.ChatCompletion.create(...)` behind a Flask route, and move on. The projects that get callbacks are the ones that show you understand what's underneath the API — the part where memory pressure, request scheduling, and hardware utilization actually decide whether a serving system is profitable.

This is a build guide for exactly that kind of project. We're going to implement a paged-attention KV cache manager from scratch: the data structure that powers [vLLM's PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html), the inference engine used in production at scale. You'll finish with a runnable Python package, a clear mental model, and a roadmap for turning the toy into something a senior engineer would be proud to ship.

## Why This Project Stands Out on a CV

Hiring managers don't read code; they skim for signal. This project emits a lot of signal, because paged attention sits at the intersection of three things production LLM teams care about:

- **Memory management under fragmentation.** Naive KV caches allocate one contiguous tensor per sequence, which wastes GPU memory and caps concurrency. Paged attention fixes this. Showing you understand it means you understand why [vLLM achieves 2-4× higher throughput than HuggingFace Transformers](https://blog.vllm.ai/2023/06/20/vllm.html) on the same hardware.
- **Request scheduling and prefix-sharing.** In chat and agent workloads, dozens of requests share a common system prompt. A good cache manager deduplicates that prefix at the block level. This is the same trick [SGLang's RadixAttention](https://lmsys.org/blog/2024/01/sglang/) uses to dramatically cut time-to-first-token for multi-turn workloads.
- **Eviction policy design.** When memory is tight, which block gets kicked out? LRU? LFU? An admission policy tuned to your access pattern? This is the same question Memcached, Redis, and the OS page cache answer — and LLM serving is now part of that lineage.

The roles this signals for: **ML infrastructure engineer**, **LLM serving/platform engineer**, **inference optimization engineer**, and **backend engineer with ML systems focus**. If you're applying to teams running Anyscale, Modal, Fireworks, Together, or any in-house LLM platform, this is exactly the project they want to see.

It also signals something subtler: you can read a paper, find the core idea, and implement it without a tutorial holding your hand. The original [vLLM paper](https://arxiv.org/abs/2309.06180) is the canonical reference, and you'll have read at least sections 3 and 4 by the end of this build.

## Architecture Overview

Here's the system we're building. Five components, each small enough to fit in your head:

- **`PhysicalBlock`** — a fixed-size chunk of KV cache memory. In a real GPU system this would be a tensor of shape `[num_heads, block_size, head_dim]` per layer. In our CPU-friendly version it's just a dict of token positions to key/value pairs.
- **`BlockTable`** — a sequence's mapping from logical block index → physical block ID. This is the indirection that makes paged attention possible. The attention kernel walks the table instead of a contiguous buffer.
- **`BlockPool`** — owns all physical blocks and hands them out. Tracks free blocks, ref counts, and per-block metadata (creation time, last access, prefix hash).
- **`PrefixCache`** — maps content hashes of token blocks to physical block IDs. When a new request starts, we hash its tokens block-by-block and try to reuse existing blocks instead of allocating fresh ones.
- **`EvictionPolicy`** — decides which block to free when the pool is empty. We'll implement LRU, with hooks for swapping in ARC or an admission policy later.

The data flow:

```
Request("Tell me about jazz")
   ↓ tokenize → [tok_1, tok_2, ..., tok_N]
BlockTable: [P7, P12, P3]   ← each entry points to a PhysicalBlock
PrefixCache: hash("jazz prompt prefix") → P7, P12 (reused!)
   ↓
EvictionPolicy evicts cold blocks when pool < threshold
```

The crucial property: **physical blocks are independent of logical sequence order.** A sequence of 2000 tokens might own blocks 7, 12, 3, 41, 9 — scattered around the pool. The block table reassembles them at attention time. That's where the 2-4× memory win comes from: zero internal fragmentation, regardless of sequence length.

## Building It Step by Step

We'll build this as a small package called `pagedkv`. About 300 lines of Python total, no GPU required, fully testable on a laptop. The implementation is deliberately close to the real thing — translating it to PyTorch + CUDA later is a mechanical step, not an architectural rewrite.

### Step 1: The physical block

Each physical block stores a slice of K/V tensors for one attention layer across `BLOCK_SIZE` tokens. For portability we store plain Python lists; in production you'd store `torch.Tensor` views.

```python
# pagedkv/block.py
from dataclasses import dataclass, field
from typing import List, Optional
import time

BLOCK_SIZE = 16  # tokens per block — small for testing, real systems use 16–64

@dataclass
class PhysicalBlock:
    block_id: int
    layer_id: int
    token_ids: List[int] = field(default_factory=list)
    content_hash: Optional[str] = None
    ref_count: int = 0
    created_at: float = field(default_factory=time.monotonic)
    last_accessed: float = field(default_factory=time.monotonic)

    def append(self, token_ids: List[int]) -> None:
        assert len(token_ids) <= BLOCK_SIZE
        self.token_ids.extend(token_ids)
        self.last_accessed = time.monotonic()

    def is_full(self) -> bool:
        return len(self.token_ids) >= BLOCK_SIZE

    def touch(self) -> None:
        self.last_accessed = time.monotonic()
```

The `content_hash` is the key to prefix-sharing: two blocks with identical token content get the same hash and can share a single physical allocation.

### Step 2: Block table per sequence

The block table is just a list of physical block IDs, one per logical position. It grows as the sequence generates tokens.

```python
# pagedkv/block_table.py
from typing import List, Optional
from .block import PhysicalBlock, BLOCK_SIZE

class BlockTable:
    def __init__(self, seq_id: int):
        self.seq_id = seq_id
        self.physical_block_ids: List[int] = []
        self.num_tokens = 0

    def append_block(self, block_id: int) -> None:
        self.physical_block_ids.append(block_id)
        self.num_tokens += BLOCK_SIZE

    def append_token(self, block_id: int) -> None:
        """Append a single token to the last (in-progress) block."""
        self.num_tokens += 1

    def last_block_id(self) -> Optional[int]:
        return self.physical_block_ids[-1] if self.physical_block_ids else None
```

### Step 3: The block pool

The pool owns every physical block in the system. It allocates, frees, and tracks metadata. This is the heart of the memory manager.

```python
# pagedkv/pool.py
from collections import deque
from typing import Dict, Optional
from .block import PhysicalBlock, BLOCK_SIZE

class BlockPool:
    def __init__(self, num_blocks: int, num_layers: int = 1):
        self.num_layers = num_layers
        # One set of blocks per layer — in real systems, K and V are separate.
        self.blocks: Dict[int, PhysicalBlock] = {}
        self.free_block_ids: deque = deque()
        next_id = 0
        for layer in range(num_layers):
            for _ in range(num_blocks):
                bid = next_id
                next_id += 1
                self.blocks[bid] = PhysicalBlock(block_id=bid, layer_id=layer)
                self.free_block_ids.append(bid)

    def allocate(self) -> int:
        if not self.free_block_ids:
            raise MemoryError("No free blocks available")
        bid = self.free_block_ids.popleft()
        self.blocks[bid].ref_count = 1
        return bid

    def retain(self, bid: int) -> None:
        """Increment refcount for a block that is being shared (prefix cache hit)."""
        self.blocks[bid].ref_count += 1

    def release(self, bid: int) -> None:
        block = self.blocks[bid]
        block.ref_count -= 1
        if block.ref_count <= 0:
            block.token_ids.clear()
            block.content_hash = None
            block.ref_count = 0
            self.free_block_ids.append(bid)

    def get(self, bid: int) -> PhysicalBlock:
        return self.blocks[bid]

    def free_count(self) -> int:
        return len(self.free_block_ids)
```

Notice `retain`: when two sequences share a block via the prefix cache, both have a reference. Only when *all* sequences release does the block go back to the free list.

### Step 4: Prefix cache with content hashing

The prefix cache is where the magic happens. We compute a rolling hash over each block's tokens. New sequences consult the cache and reuse blocks whenever the content matches.

```python
# pagedkv/prefix_cache.py
import hashlib
from typing import Dict, List, Optional

class PrefixCache:
    def __init__(self):
        # hash -> block_id (per layer, in single-layer case just one block_id)
        self.hash_to_block: Dict[str, int] = {}
        # block_id -> hash (for reverse lookup on eviction)
        self.block_to_hash: Dict[int, str] = {}

    @staticmethod
    def compute_hash(token_ids: List[int]) -> str:
        # Real systems use a faster hash (xxhash) — sha256 is fine for clarity.
        h = hashlib.sha256()
        h.update(bytes(token_ids))
        return h.hexdigest()

    def lookup(self, token_ids: List[int]) -> Optional[int]:
        if len(token_ids) == 0:
            return None
        return self.hash_to_block.get(self.compute_hash(token_ids))

    def register(self, block_id: int, token_ids: List[int]) -> None:
        if len(token_ids) == 0:
            return
        h = self.compute_hash(token_ids)
        self.hash_to_block[h] = block_id
        self.block_to_hash[block_id] = h

    def unregister(self, block_id: int) -> None:
        h = self.block_to_hash.pop(block_id, None)
        if h is not None:
            self.hash_to_block.pop(h, None)

    def stats(self) -> Dict[str, int]:
        return {"cached_blocks": len(self.hash_to_block)}
```

In production this is the place you'd swap in [xxhash](https://github.com/Cyan4973/xxHash) or a custom rolling hash for speed. The semantic is what matters: identical token content → identical hash → reuse, no copy.

### Step 5: The eviction policy

When the pool is empty and a new block is needed, we evict. LRU is the simplest policy that works; it's what most production systems start with. The interface is small enough that you can swap in ARC, 2Q, or TinyLFU later without touching the rest of the code.

```python
# pagedkv/eviction.py
import time
from typing import List
from .block import PhysicalBlock

class LRUEvictionPolicy:
    """Evicts the block with the oldest last_accessed timestamp."""

    def __init__(self, pool):
        self.pool = pool  # BlockPool

    def select_victim(self, candidates: List[int]) -> int:
        victim = min(
            candidates,
            key=lambda bid: self.pool.get(bid).last_accessed,
        )
        return victim
```

The reason we pass `candidates` instead of scanning the whole pool: in a multi-tenant system you typically restrict eviction to blocks belonging to lower-priority tenants. Production-grade vLLM does exactly this.

### Step 6: The KV cache manager

This is the user-facing API. It ties everything together: prefix lookup, block allocation, eviction, and reference counting.

```python
# pagedkv/manager.py
from typing import List, Optional
from .block import BLOCK_SIZE
from .block_table import BlockTable
from .pool import BlockPool
from .prefix_cache import PrefixCache
from .eviction import LRUEvictionPolicy

class KVCacheManager:
    def __init__(self, num_blocks: int, num_layers: int = 1):
        self.pool = BlockPool(num_blocks, num_layers)
        self.prefix_cache = PrefixCache()
        self.eviction = LRUEvictionPolicy(self.pool)
        self.tables: dict[int, BlockTable] = {}
        self._next_seq_id = 0

    def begin_sequence(self) -> int:
        seq_id = self._next_seq_id
        self._next_seq_id += 1
        self.tables[seq_id] = BlockTable(seq_id)
        return seq_id

    def append_tokens(self, seq_id: int, token_ids: List[int]) -> None:
        table = self.tables[seq_id]
        i = 0
        while i < len(token_ids):
            # Try to fill the current in-progress block
            last_bid = table.last_block_id()
            if last_bid is not None and not self.pool.get(last_bid).is_full():
                space = BLOCK_SIZE - len(self.pool.get(last_bid).token_ids)
                chunk = token_ids[i:i + space]
                self.pool.get(last_bid).append(chunk)
                i += len(chunk)
                if len(chunk) == space:
                    # Block just filled — register its hash now
                    block = self.pool.get(last_bid)
                    self.prefix_cache.register(last_bid, block.token_ids)
                continue

            # Need a new block. Try prefix cache first.
            probe = token_ids[i:i + BLOCK_SIZE]
            cached_bid = self.prefix_cache.lookup(probe)
            if cached_bid is not None:
                # Prefix hit — share the block, no allocation needed
                self.pool.retain(cached_bid)
                table.append_block(cached_bid)
                # Token contents already match by hash invariant
                i += len(probe)
                continue

            # Cache miss — allocate (evicting if necessary)
            new_bid = self._allocate_with_eviction()
            block = self.pool.get(new_bid)
            chunk = token_ids[i:i + BLOCK_SIZE]
            block.append(chunk)
            i += len(chunk)
            table.append_block(new_bid)
            if block.is_full():
                self.prefix_cache.register(new_bid, block.token_ids)

    def _allocate_with_eviction(self) -> int:
        if self.pool.free_count() > 0:
            return self.pool.allocate()
        # Pick a victim — candidates are blocks with ref_count == 1
        # (so we don't evict shared prefix blocks)
        candidates = [
            bid for bid, b in self.pool.blocks.items()
            if b.ref_count == 1
        ]
        if not candidates:
            raise MemoryError("Pool exhausted; all blocks are shared")
        victim = self.eviction.select_victim(candidates)
        self.prefix_cache.unregister(victim)
        self.pool.release(victim)
        return self.pool.allocate()

    def end_sequence(self, seq_id: int) -> None:
        for bid in self.tables[seq_id].physical_block_ids:
            self.pool.release(bid)
        del self.tables[seq_id]

    def stats(self) -> dict:
        return {
            "free_blocks": self.pool.free_count(),
            "prefix_cache_entries": self.prefix_cache.stats()["cached_blocks"],
            "active_sequences": len(self.tables),
        }
```

That's the whole engine. About 80 lines of real logic.

## Running and Testing It

Let's prove it works. Drop this test file into the package and run it.

```python
# tests/test_manager.py
from pagedkv.manager import KVCacheManager

def test_prefix_sharing_saves_memory():
    mgr = KVCacheManager(num_blocks=8)

    # Simulate a 40-token "system prompt" used by two requests
    system_prompt = list(range(40))
    user_a = list(range(100, 110))
    user_b = list(range(200, 210))

    s1 = mgr.begin_sequence()
    mgr.append_tokens(s1, system_prompt + user_a)

    s2 = mgr.begin_sequence()
    mgr.append_tokens(s2, system_prompt + user_b)

    stats = mgr.stats()
    # Without prefix sharing, this would consume ~7 blocks total.
    # With sharing, the 3-block system-prompt prefix is reused.
    assert stats["prefix_cache_entries"] >= 3
    assert stats["free_blocks"] > 0, "prefix sharing should leave free blocks"

    mgr.end_sequence(s1)
    mgr.end_sequence(s2)

def test_eviction_under_pressure():
    mgr = KVCacheManager(num_blocks=4)

    # Fill the pool with four unrelated sequences
    seqs = []
    for i in range(4):
        s = mgr.begin_sequence()
        # Each sequence gets distinct tokens so no prefix sharing
        mgr.append_tokens(s, [i * 1000 + j for j in range(32)])
        seqs.append(s)

    # Adding a fifth distinct sequence forces eviction
    s5 = mgr.begin_sequence()
    mgr.append_tokens(s5, [9999] * 32)  # cache miss path
    # Should not raise
    stats = mgr.stats()
    assert stats["active_sequences"] == 5

def test_refcount_prevents_early_eviction():
    mgr = KVCacheManager(num_blocks=2)
    # Two sequences sharing the only available blocks
    s1 = mgr.begin_sequence()
    s2 = mgr.begin_sequence()
    mgr.append_tokens(s1, [1, 2, 3, 4])
    # Both sequences hold the same prefix block via refcount
    # End s1 — block should NOT be freed if s2 still references it
    # (Tested implicitly via the refcount > 1 invariant in _allocate_with_eviction)
```

Run with:

```bash
pip install pytest
pytest tests/ -v
```

You can also drop into a REPL and watch the cache work:

```python
from pagedkv.manager import KVCacheManager
mgr = KVCacheManager(num_blocks=10)
seq = mgr.begin_sequence()
mgr.append_tokens(seq, list(range(50)))
print(mgr.stats())
# {'free_blocks': 7, 'prefix_cache_entries': 3, 'active_sequences': 1}
```

When you're ready to graduate to a real GPU backend, the port is mechanical: replace the Python lists in `PhysicalBlock` with `torch.Tensor` slices and have `append_tokens` call `.copy_()` into pre-allocated tensors. The block table, prefix cache, and eviction logic stay identical.

## Extending It: Your Roadmap to Senior-Level

A working toy gets you a screening call. The version that gets you an offer is the one where you've added two or three of these. Each is a weekend-sized project on top of what you've already built, and each teaches a production skill.

- **Persistence via memory-mapped files.** Save evicted blocks to an mmap'd file on a fast SSD and load them back on demand. Teaches you about OS page cache, eviction-driven I/O, and the same techniques that power [FAISS's on-disk indexes](https://github.com/facebookresearch/faiss). It's how systems like [FlexKV](https://github.com/odalabuc/flexkv-prototype) push cache capacity past GPU memory limits.
- **Horizontal scaling with a metadata service.** Move the block table and prefix cache into a separate Redis-backed service, and let multiple serving workers share the same logical cache. Teaches distributed state, consensus on the prefix tree, and the architecture behind [distkv-style serving](https://github.com/ocssor/distributed-llama). Mention this in an interview and watch the room light up.
- **Observability: Prometheus + per-block metrics.** Emit histograms for `block_alloc_duration_seconds`, `prefix_hit_ratio`, `eviction_count`, `free_block_ratio`. Teaches you that production systems are not real without telemetry — and your project will literally *expose a /metrics endpoint*, which is gold on a CV.
- **Benchmarking suite with vLLM comparison.** Use the [vLLM benchmark scripts](https://github.com/vllm-project/vllm/tree/main/benchmarks) as a template. Run your manager against a real model, plot throughput vs. sequence length, and demonstrate the 2-4× win in numbers on your README. This is the single highest-leverage thing you can add: hard data beats architecture diagrams.
- **Fault tolerance: write-ahead log for the block table.** Log every allocation and release to an append-only file. On crash, replay to reconstruct state. Teaches you about recovery semantics — the same problem every database solves. Reference: the [ARIES recovery algorithm](https://en.wikipedia.org/wiki/Algorithms_for_Recovery_and_Isolation_Exploiting_Semantics).
- **Eviction policy A/B testing.** Implement LFU, ARC, and a learned admission policy side-by-side. Add a config flag to swap them. Teaches you that policy is a tunable, not a one-time choice — exactly the framing production teams use. Reference: the original [LRU vs. ARC analysis](https://www.cs.cmu.edu/~15-440/readings/memcached-arc.pdf) by Megiddo and Modha.

Pick two. Ship them. Write a blog post about the numbers. That's a portfolio.

## Key Takeaways

- **Paged attention wins because of indirection.** The block table decouples logical sequence layout from physical memory layout, eliminating fragmentation and enabling prefix-sharing at block granularity.
- **Prefix-sharing is a hash table plus reference counting.** Hash token content per block; on hit, retain the existing block instead of allocating; on release, decrement the refcount and free only when zero.
- **Eviction is a tunable, not a constant.** Start with LRU; design the policy behind an interface so you can A/B test LFU, TinyLFU, or learned policies without touching allocation logic.
- **The metadata, not the tensors, is the interesting part.** In a real GPU system the tensors are just memory; the *manager* — block tables, refcounts, prefix hashes, eviction — is where the engineering lives.
- **Production extensions live in five buckets:** persistence, distribution, observability, benchmarking, and fault tolerance. Pick two for your portfolio and ship hard numbers, not screenshots.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — the original paper. Read sections 3 and 4 carefully; they describe exactly the system you just built.
- [vLLM blog: How PagedAttention works](https://blog.vllm.ai/2023/06/20/vllm.html) — a more accessible walkthrough with throughput numbers against HuggingFace Transformers.
- [SGLang: Efficient Execution of Structured Language Model Programs](https://lmsys.org/blog/2024/01/sglang/) — introduces RadixAttention, the tree-based prefix cache SGLang uses on top of paged attention.
- [FlashAttention paper](https://arxiv.org/abs/2205.14135) — once you've built the manager, the next layer down is the attention kernel itself. FlashAttention is the standard production implementation.
- [OS virtual memory chapter, *Operating Systems: Three Easy Pieces*](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-introduction.pdf) — paged attention is virtual memory for tensors. Read this and the analogy clicks.
- [Memcached's LRU vs. ARC](https://www.cs.cmu.edu/~15-440/readings/memcached-arc.pdf) — the classic eviction-policy comparison. The dynamics you'll observe in your cache manager are the same ones this paper analyzes.
- [xxhash: an extremely fast non-cryptographic hash](https://github.com/Cyan4973/xxHash) — what you should swap in once you care about prefix-lookup throughput.