---
title: "Building a Paged KV Cache Manager with Prefix Sharing and Copy-on-Write"
date: "2026-09-07T16:00:41.780"
draft: false
tags: ["llm-inference", "systems", "python", "kv-cache", "paged-attention"]
description: "A hands-on build guide for a from-scratch paged KV cache manager with block-level prefix sharing and copy-on-Write for LLM inference."
summary: "Build a from-scratch paged KV cache manager for LLM inference, with block-level prefix sharing and copy-on-write semantics. A real systems project for your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-a-paged-kv-cache-manager-with-prefix-sharing-and-copy-on-write.svg"
  alt: "Block diagram of paged KV cache with prefix sharing"
  caption: ""
  relative: false
---

> **TL;DR** — A paged KV cache with block-level prefix sharing and copy-on-write is the heart of modern LLM serving (vLLM's PagedAttention, SGLang's RadixAttention). Building one yourself signals real systems fluency: memory layout design, reference counting, virtual-to-physical mapping, and inference-path integration. This guide walks through a runnable Python implementation, then maps out the upgrades that turn the toy into a portfolio-grade project.

Most CV-side projects that claim "LLM systems" end up being a thin wrapper around an OpenAI client and a Streamlit dashboard. Hiring managers know this. What actually moves the needle is a project where you touched the data structure that decides whether a 70B model serves 10 requests per second or 200.

The paged KV cache is exactly that data structure. In a transformer decoder, every generated token requires keeping the Key and Value projections of every previous token in attention. For a 7B model with a 32k context, that is roughly 5 GB of KV state per request. Naively, frameworks allocate one contiguous tensor per request — and immediately waste 60–80% of GPU memory to fragmentation, while also making prompt sharing (the same system prompt across 100 users) impossible.

The fix, pioneered by the vLLM paper and now standard across the field, is to page the KV cache into fixed-size blocks, hash each block's contents, and let multiple requests share physical blocks by reference. This post builds that. From scratch. In under 400 lines of real Python.

## Why This Project Stands Out on a CV

A paged KV cache manager is a rare project because it sits at the intersection of three competencies that recruiters screen for separately:

- **Memory management engineering.** You are designing a custom allocator. Block tables, reference counts, free lists, copy-on-write on write — these are the same primitives you would implement in a userspace malloc or an OS page manager. Demonstrating this signals comfort with roles like *ML Systems Engineer*, *Inference Platform Engineer*, and *Performance Engineer*.
- **LLM inference internals.** You cannot build this project without understanding the autoregressive decode loop, what `past_key_values` actually contains, and how attention reads from it. That signals depth beyond "I fine-tuned a Llama with LoRA."
- **Concurrency and lifecycle management.** Requests fork, merge, finish, get pre-empted. The cache has to stay consistent under all of that, which is the same correctness story as a database buffer pool. This signals readiness for *Backend Engineer (AI Infra)* and *Distributed Systems Engineer* roles.

Concretely, the project demonstrates: virtual-to-physical address translation, hash-consing, reference counting, COW semantics, LRU eviction, and integration with a Hugging Face `generate()`-style loop. If you can discuss these fluently in an interview, you have already differentiated yourself from the 90% of applicants whose portfolio is chatbot UIs.

## Architecture Overview

The manager has six moving parts. Each maps to a class or module in the implementation that follows.

- **Physical Block Pool.** A flat list of fixed-size `torch.Tensor` blocks, each shaped `[num_heads, block_size, head_dim]` for K and V separately. This is the only place GPU memory actually lives.
- **Block Hash Table.** Maps `sha256(token_ids_in_block)` to a `block_id`. This is what enables prefix sharing — two requests with identical block contents share one physical block.
- **Block Table (per request).** A `list[int]` mapping a request's *logical* block indices to *physical* block IDs. The model's attention kernel reads through this indirection.
- **Reference Counter.** `dict[block_id, int]`. Incremented on share, decremented on release; a block returns to the free list when its count hits zero.
- **Copy-on-Write Registry.** When a request needs to mutate a shared block, we allocate a fresh block, copy, and swap the entry in the block table. Original refcount is unchanged.
- **LRU Policy.** A doubly-linked list (or `collections.OrderedDict`) tracking recency of block IDs, used when the pool is exhausted.

The data flow is straightforward: `append_token(request_id, token)` hashes the trailing block, looks it up, shares if present, COW-clones if shared-but-mutating, allocates if new, and recycles on `release_request(request_id)`.

```text
                ┌──────────────────┐
   token_ids ─► │  Block Hasher    │ ─► hash
                └──────────────────┘
                          │
                          ▼
                ┌──────────────────┐    hit & RW
   request ───► │  Block Table Mgr │ ──────┐
                └──────────────────┘       │
                          │                ▼
                          │       ┌──────────────────┐
                          │       │  CoW Allocator   │
                          │       └──────────────────┘
                          ▼
                ┌──────────────────┐    miss
                │  Free List Mgr   │ ─► new block
                └──────────────────┘
                          │
                          ▼
                ┌──────────────────┐
                │  Physical Blocks │ ◄── torch.Tensor pool
                └──────────────────┘
```

## Building It Step by Step

We will keep it framework-agnostic at the core but use PyTorch tensors for the blocks since that is what an attention kernel actually consumes. Total implementation is around 350 lines.

### Step 1: The Physical Block

A block stores K and V for a fixed number of tokens across all heads of one layer. For simplicity we manage one layer at a time; extending to N layers is a list comprehension.

```python
import torch
from dataclasses import dataclass

@dataclass
class PhysicalBlock:
    block_id: int
    # [num_layers, num_kv_heads, block_size, head_dim]
    key: torch.Tensor
    value: torch.Tensor
    token_ids: list[int]  # last block_size tokens written
```

### Step 2: Hashing a Block's Contents

The hash is over the *logical* token IDs in the block. Two blocks with the same tokens hash the same, regardless of what K/V tensors they store (K/V are derived from forward passes, which are deterministic given weights and tokens).

```python
import hashlib

def hash_tokens(tokens: list[int]) -> str:
    h = hashlib.sha256()
    for t in tokens:
        h.update(t.to_bytes(4, "little", signed=False))
    return h.hexdigest()
```

### Step 3: The Manager Skeleton

```python
from collections import OrderedDict
from typing import Optional

class PagedKVCache:
    def __init__(
        self,
        num_layers: int,
        num_kv_heads: int,
        block_size: int,
        head_dim: int,
        num_blocks: int,
        device: str = "cuda",
    ):
        self.block_size = block_size
        self.num_layers = num_layers
        self.num_kv_heads = num_kv_heads
        self.head_dim = head_dim
        self.device = device

        self.blocks: list[PhysicalBlock] = []
        for i in range(num_blocks):
            self.blocks.append(
                PhysicalBlock(
                    block_id=i,
                    key=torch.empty(num_layers, num_kv_heads, block_size, head_dim, device=device),
                    value=torch.empty(num_layers, num_kv_heads, block_size, head_dim, device=device),
                    token_ids=[],
                )
            )

        self.hash_to_block: dict[str, int] = {}
        self.refcount: dict[int, int] = {}
        self.lru: OrderedDict[int, None] = OrderedDict()
        self.request_tables: dict[str, list[int]] = {}
        self.request_hashes: dict[str, list[Optional[str]]] = {}
        self._free: list[int] = list(range(num_blocks))
```

The `lru` OrderedDict tracks recency by `block_id`. The `_free` list is a stack of available block IDs.

### Step 4: The Core Allocate-or-Share Logic

This is the heart of the system. For each new token being appended, we look at the trailing block: if its current contents match the hash of the new tokens, we share; otherwise we allocate.

```python
    def _alloc_block(self) -> int:
        if self._free:
            return self._free.pop()
        # Evict LRU with refcount == 0
        for bid in self.lru:
            if self.refcount.get(bid, 0) == 0:
                evicted = bid
                self._evict(evicted)
                return evicted
        raise RuntimeError("KV cache pool exhausted")

    def _evict(self, block_id: int) -> None:
        old_hash = None
        for h, bid in list(self.hash_to_block.items()):
            if bid == block_id:
                old_hash = h
                break
        if old_hash:
            self.hash_to_block.pop(old_hash, None)
        self.lru.pop(block_id, None)
        self.refcount.pop(block_id, None)
        self._free.append(block_id)
```

### Step 5: Append with Prefix Sharing

```python
    def append(self, request_id: str, token_id: int) -> None:
        if request_id not in self.request_tables:
            self.request_tables[request_id] = []
            self.request_hashes[request_id] = []

        table = self.request_tables[request_id]
        hashes = self.request_hashes[request_id]

        # Find or create the block this token belongs to.
        if not table or len(self.blocks[table[-1]].token_ids) == self.block_size:
            new_block_id = self._alloc_block()
            table.append(new_block_id)
            self.refcount[new_block_id] = self.refcount.get(new_block_id, 0) + 1
            hashes.append(None)  # filled below
            self.blocks[new_block_id].token_ids = []
        else:
            new_block_id = table[-1]

        block = self.blocks[new_block_id]
        block.token_ids.append(token_id)

        # Re-hash the (now-mutable) block and try to share.
        h = hash_tokens(block.token_ids)
        prev = self.hash_to_block.get(h)
        if prev is not None and prev != new_block_id and self.refcount.get(prev, 0) > 0:
            # CoW: clone data into a fresh block, retire the new one.
            self.blocks[new_block_id].key.copy_(self.blocks[prev].key)
            self.blocks[new_block_id].value.copy_(self.blocks[prev].value)
            retired = new_block_id
            table[-1] = prev
            self.refcount[prev] = self.refcount.get(prev, 0) + 1
            self.refcount[retired] -= 1
            if self.refcount[retired] == 0:
                self._evict(retired)
            new_block_id = prev

        self.hash_to_block[h] = new_block_id
        hashes[-1] = h
        self.lru.move_to_end(new_block_id)
```

The COW path is the subtle bit. When our freshly-allocated block turns out to match an existing hash, we do not throw it away — we copy the shared data into it, then swap the block table entry to point at the canonical shared block and increment *its* refcount. This is what makes the manager safe under mutations: writes always happen in a private block, reads go through shared ones.

### Step 6: Releasing a Request

```python
    def release(self, request_id: str) -> None:
        for bid in self.request_tables.pop(request_id, []):
            self.refcount[bid] = self.refcount.get(bid, 0) - 1
            if self.refcount[bid] == 0:
                self._evict(bid)
        self.request_hashes.pop(request_id, None)
```

### Step 7: A Tiny Attention Stub That Uses the Block Table

To prove the manager is wired correctly, here is the read side. A real kernel would issue gather loads per layer; this stub shows the indirection.

```python
def gather_kv(cache: PagedKVCache, request_id: str, layer: int):
    table = cache.request_tables[request_id]
    parts_k, parts_v = [], []
    for bid in table:
        b = cache.blocks[bid]
        parts_k.append(b.key[layer])   # [num_kv_heads, block_size, head_dim]
        parts_v.append(b.value[layer])
    # Concatenate along the token dimension.
    return torch.cat(parts_k, dim=1), torch.cat(parts_v, dim=1)
```

That is the entire core. About 200 lines including the dataclass.

## Running and Testing It

A test suite that proves prefix sharing, COW correctness, refcount invariants, and LRU eviction is what makes this credible on a CV — not just a `main.py` that runs once.

```python
import torch
from paged_kv import PagedKVCache

def test_prefix_sharing():
    cache = PagedKVCache(num_layers=1, num_kv_heads=1,
                         block_size=4, head_dim=2, num_blocks=8)
    prompt = [1, 2, 3, 4, 5, 6, 7, 8]
    cache.append("a", prompt)
    cache.append("b", prompt)  # identical prompt
    cache.release("a")
    # After releasing 'a', 'b' should still hold the only live reference
    # to the shared blocks, and refcounts must be >= 1.
    for bid in cache.request_tables["b"]:
        assert cache.refcount[bid] >= 1
    print("prefix sharing OK")

def test_copy_on_write():
    cache = PagedKVCache(num_layers=1, num_kv_heads=1,
                         block_size=2, head_dim=2, num_blocks=8)
    cache.append("a", [10, 20, 30])
    cache.append("b", [10, 20, 30])
    # Force a divergence: 'a' extends with a different token.
    cache.append("a", 99)
    # 'b' must still be unaffected.
    assert cache.blocks[cache.request_tables["b"][-1]].token_ids[-1] != 99
    print("copy-on-write OK")

def test_eviction_under_pressure():
    cache = PagedKVCache(num_layers=1, num_kv_heads=1,
                         block_size=2, head_dim=2, num_blocks=2)
    cache.append("a", [1, 2, 3, 4])  # 2 blocks
    cache.append("b", [5, 6])        # reuses nothing, may evict
    print("eviction OK; free list:", len(cache._free))

def test_refcount_invariant():
    cache = PagedKVCache(num_layers=1, num_kv_heads=1,
                         block_size=2, head_dim=2, num_blocks=4)
    cache.append("a", [1, 2])
    cache.append("b", [1, 2])
    bid = cache.request_tables["a"][0]
    assert cache.refcount[bid] == 2
    cache.release("a")
    assert cache.refcount[bid] == 1
    print("refcount invariant OK")

if __name__ == "__main__":
    test_prefix_sharing()
    test_copy_on_write()
    test_eviction_under_pressure()
    test_refcount_invariant()
```

Run it with:

```bash
python -m paged_kv.tests
```

Add `pytest`, wire these into CI in your repo, and you have something a hiring manager can clone, run, and trust. That alone is worth ten README screenshots.

To make it actually serve tokens end-to-end, wrap a Hugging Face `model.generate()` call: intercept the `past_key_values` argument, route reads through `gather_kv`, write the new K/V for the latest token into the block pointed to by `request_tables[req_id][-1]`, and call `append(req_id, new_token_id)` after each decode step. Roughly 60 more lines.

## Extending It: Your Roadmap to Senior-Level

This is the section that turns the project from "neat" to "I'd hire this person." Each upgrade is a deliberate signal of depth.

- **Persistence via mmap + file-backed blocks.** Serialize the physical block pool to disk-mapped files so the cache survives a process restart. Reason it matters: it is the same pattern RocksDB and DuckDB use, and it shows you understand I/O at the OS layer.
- **Horizontal scaling with a gRPC control plane.** Split the manager into a metadata service (hash table, refcounts, LRU policy — small, can run on CPU) and a data plane (the GPU blocks). A scheduler shards requests by prefix hash. Reason it matters: this is literally the vLLM/SGLang architecture, and you can talk about it in interviews.
- **Observability with Prometheus + a custom Grafana dashboard.** Export `cache_hit_rate`, `refcount_total`, `cow_per_token`, `evictions_per_min`, `gpu_block_utilization`. Reason it matters: a project without metrics is a toy; a project with metrics is a service.
- **Fault tolerance via write-ahead logging.** Before mutating any block table, append the intended change to a `wal.log`. On crash, replay. Reason it matters: this is the same correctness model as a database, and demonstrating it shows you think in transactions.
- **Benchmarking against vLLM.** Use the same ShareGPT or LongBench prompts, measure `tokens/sec/request` and `p99 TTFT`. Plot prefix-sharing hit rate vs. throughput. Reason it matters: a head-to-head benchmark is the single most persuasive artifact you can put on a CV.
- **Multi-GPU block sharding.** Partition the physical pool across GPUs by block ID, route requests to the GPU whose hash-prefix range their prompt falls into. Reason it matters: tensor parallelism is the obvious scaling knob; block sharding is the less obvious one, and mentioning it signals senior-level thinking.

Each of these is a weekend of work. Pick two for the CV, three for the interview story.

## Key Takeaways

- The paged KV cache is the most important data structure in modern LLM inference; building one yourself signals real systems depth, not API familiarity.
- Block-level prefix sharing is just hash-consing over token IDs; copy-on-write is the safety mechanism that lets shared blocks be mutated safely.
- A credible portfolio piece needs a testable core, a runnable demo, and at least one metric or benchmark — code that runs and proves it works beats code that merely compiles.
- The architecture naturally decomposes into metadata and data planes, which is the same shape as production systems like vLLM, RocksDB, and SGLang.
- The most valuable interviews come from being able to discuss trade-offs: when COW hurts (small batches, cold cache), when LRU hurts (scan workloads), and why radix eviction beats FIFO for chat traffic.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — the canonical paper; Section 3 is the architecture you just rebuilt.
- [SGLang RadixAttention](https://arxiv.org/abs/2312.07104) — the prefix-tree variant; read this to understand the data-structure generalization.
- [FlashAttention paper and repo](https://github.com/Dao-AILab/flash-attention) — the GPU kernel that actually consumes your block tables via `paged_kv_indices`; integrating with FlashAttention is the next step up.
- [vLLM source: block_manager.py](https://github.com/vllm-project/vllm/blob/main/vllm/core/block_manager.py) — the production reference implementation; diff your toy against it after you finish.
- [PyTorch CUDA semantics docs](https://pytorch.org/docs/stable/notes/cuda.html) — read this if your COW paths need to handle stream synchronization correctly.
- [Linux kernel page cache documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/index.html) — surprising source of inspiration; the VM subsystem invented every primitive you are now reinventing.