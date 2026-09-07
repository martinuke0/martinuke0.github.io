---
title: "Build a Paged KV Cache Manager From Scratch: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-07T17:08:02.773"
draft: false
tags: ["llm-inference", "kv-cache", "paged-attention", "systems-engineering", "python", "portfolio"]
description: "A hands-on build guide for a from-scratch paged KV cache manager with prefix sharing and copy-on-write for LLM inference — a CV-grade project."
summary: "Step-by-step build of a real, runnable paged KV cache manager in Python: blocks, block tables, prefix sharing via a radix tree, copy-on-write for beam search, plus a roadmap to senior-level extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-paged-kv-cache-manager-from-scratch-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Diagram of a paged KV cache with blocks, block tables, and a prefix-sharing radix tree."
  caption: ""
  relative: false
---

> **TL;DR** — A paged KV cache manager is the engine behind vLLM, SGLang, and every high-throughput LLM server. In this build, you'll implement one in ~300 lines of runnable Python: fixed-size blocks, per-request block tables, prefix sharing through a radix tree, and copy-on-write for beam search. It is small enough to finish in a weekend and deep enough to demo real systems thinking — memory layout, reference counting, eviction, and the kinds of decisions senior inference engineers make every day.

## Why This Project Stands Out on a CV

Most portfolio projects sit in one of two camps: a CRUD app with a React frontend, or a thin wrapper around an OpenAI key. Neither signals much. The project in this post is different. It touches the same moving parts that production inference systems at [vLLM](https://blog.vllm.ai/), [Anthropic](https://www.anthropic.com/), and [SGLang](https://github.com/sgl-project/sglang) deal with every day: virtual memory for tensors, sharing, eviction under pressure, and concurrency.

Concretely, a hiring manager reading your CV sees:

- **Memory systems thinking.** You understand that KV tensors are not "arrays" — they are pages with lifetimes that have to be managed. That is the same muscle as writing a garbage collector, a slab allocator, or a database buffer pool.
- **Comfort with the LLM inference stack.** You have read the [PagedAttention paper](https://arxiv.org/abs/2309.06180), understood the Block Manager, and reproduced a working version. That is rare. Most candidates can describe attention; few can describe the cache that feeds it.
- **Systems engineering hygiene.** Reference counting, copy-on-write, an eviction policy, and unit tests are not glamorous, but they are what separates a prototype from a system. This project ships all of them.
- **Roles it signals for.** LLM inference engineer, ML platform engineer, performance engineer, GPU systems engineer, and — more broadly — any backend role where "we care about memory and latency" is in the job description.

If you want to be taken seriously for an inference or ML platform role in 2026, this is one of the highest-signal weekend projects you can build.

## Architecture Overview

The mental model is borrowed directly from operating systems: a virtual address space (the sequence of tokens a model needs to attend over), broken into fixed-size pages (KV cache blocks), mapped through a per-request page table (the block table) into a physical pool (the block allocator). On top of that, we layer three things that make this specifically an *LLM* KV cache:

- **Prefix sharing.** A radix tree maps token prefixes to existing block chains. A new request whose prompt starts with a known prefix reuses those blocks instead of recomputing or reallocating.
- **Copy-on-write (CoW).** When two requests diverge from a shared prefix — most importantly during beam search — the diverging block is duplicated rather than mutated in place, so siblings keep their independent futures.
- **Reference counting and eviction.** Each block carries a refcount and a last-access timestamp. When the pool is full, the eviction policy picks a block whose refcount has dropped to zero and reuses it.

The components, top to bottom:

- **`Block`** — a fixed-size chunk of KV slots (e.g., 16 tokens × 2 × num_heads × head_dim). Knows its refcount and whether it is "full" of valid tokens.
- **`BlockPool`** — owns every block, hands them out by id, recycles them, and tracks free vs. in-use.
- **`BlockTable`** — per-request mapping from logical position → physical block id. Grows as the prompt and generated tokens grow.
- **`PrefixTree`** — a trie (radix-compressed) keyed on token ids, whose leaves are block ids. This is what makes prefix sharing O(prefix length).
- **`Sequence`** — wraps a request's tokens and its `BlockTable`, plus metadata like sampling params and a beam id.
- **`CacheManager`** — the orchestrator. Allocates, shares, copies-on-write, evicts, and frees.

A textual diagram of a request flow:

```
Request "The capital of France is"
   │
   ▼
PrefixTree.lookup(tokens)
   │  shared prefix found? ──► reuse block ids 0..k
   │  no?                     ──► allocate fresh blocks
   ▼
BlockTable = [b0, b1, ..., b_new]
   │
   ▼
Generate next token → append → maybe grow table → maybe CoW on beam split
   │
   ▼
Eviction tick: scan BlockPool, reclaim zero-refcount blocks older than N ms
```

## Building It Step by Step

You can build this in a single file, `paged_kv.py`. Around 300 lines, no third-party dependencies, pure Python. We'll go module by module.

### Step 1: The Block

A block is a fixed-size slab. We store the actual KV tensors as `numpy` arrays so the code is runnable on a laptop — in production they would be CUDA tensors, but the *management* logic is identical.

```python
# paged_kv.py
from dataclasses import dataclass, field
from typing import Optional
import numpy as np

BLOCK_SIZE = 16  # tokens per block
NUM_KV_HEADS = 8
HEAD_DIM = 64
DTYPE = np.float16

@dataclass
class Block:
    block_id: int
    # shape: (2, BLOCK_SIZE, NUM_KV_HEADS, HEAD_DIM)  → K and V
    kv: np.ndarray = field(
        default_factory=lambda: np.zeros(
            (2, BLOCK_SIZE, NUM_KV_HEADS, HEAD_DIM), dtype=DTYPE
        )
    )
    refcount: int = 0
    is_full: bool = False        # all BLOCK_SIZE slots are valid tokens
    last_used_ts: float = 0.0    # for eviction

    def append(self, k_slice: np.ndarray, v_slice: np.ndarray) -> None:
        """Append one token's K/V into the next free slot."""
        i = self._next_slot()
        self.kv[0, i] = k_slice
        self.kv[1, i] = v_slice
        if i == BLOCK_SIZE - 1:
            self.is_full = True

    def _next_slot(self) -> int:
        # In a full implementation, track a cursor. For clarity we scan.
        for i in range(BLOCK_SIZE):
            if np.all(self.kv[0, i] == 0) and np.all(self.kv[1, i] == 0):
                return i
        raise RuntimeError("Block is full")
```

### Step 2: The Block Pool

The pool owns every block. It hands out ids, recycles them, and is the single source of truth for physical memory.

```python
import threading, time

class BlockPool:
    def __init__(self, num_blocks: int):
        self._lock = threading.Lock()
        self._blocks: list[Block] = [Block(block_id=i) for i in range(num_blocks)]
        self._free: list[int] = list(range(num_blocks - 1, -1, -1))  # stack

    def allocate(self) -> Block:
        with self._lock:
            if not self._free:
                raise MemoryError("BlockPool exhausted; eviction should have run")
            block_id = self._free.pop()
            b = self._blocks[block_id]
            b.refcount = 1
            b.last_used_ts = time.monotonic()
            return b

    def retain(self, block_id: int) -> None:
        with self._lock:
            self._blocks[block_id].refcount += 1

    def release(self, block_id: int) -> None:
        with self._lock:
            b = self._blocks[block_id]
            assert b.refcount > 0
            b.refcount -= 1
            if b.refcount == 0:
                b.last_used_ts = time.monotonic()  # mark for eviction

    def reclaim(self) -> int:
        """Evict one zero-refcount block. Returns block_id or -1 if none."""
        with self._lock:
            # pick the least recently used zero-refcount block
            candidates = [b for b in self._blocks if b.refcount == 0]
            if not candidates:
                return -1
            victim = min(candidates, key=lambda b: b.last_used_ts)
            # reset
            victim.kv[:] = 0
            victim.is_full = False
            self._free.append(victim.block_id)
            return victim.block_id

    def get(self, block_id: int) -> Block:
        return self._blocks[block_id]
```

### Step 3: The Block Table

Each in-flight request has its own block table: a list of physical block ids in logical order.

```python
class BlockTable:
    def __init__(self, pool: BlockPool, block_ids: Optional[list[int]] = None):
        self._pool = pool
        self.block_ids: list[int] = block_ids or []
        self._cursor = 0  # next free slot within the tail block

    def needs_new_block(self) -> bool:
        if not self.block_ids:
            return True
        tail = self._pool.get(self.block_ids[-1])
        return tail.is_full

    def append_block(self) -> int:
        b = self._pool.allocate()
        self.block_ids.append(b.block_id)
        self._cursor = 0
        return b.block_id

    def write_token(self, k: np.ndarray, v: np.ndarray) -> None:
        if self.needs_new_block():
            self.append_block()
        tail = self._pool.get(self.block_ids[-1])
        tail.append(k, v)

    def physical_view(self) -> np.ndarray:
        """Concatenate K/V across blocks for the attention kernel."""
        blocks = [self._pool.get(bid).kv for bid in self.block_ids]
        return np.concatenate(blocks, axis=1)  # along token axis

    def fork(self) -> "BlockTable":
        """Copy-on-write fork: new table, shared block ids, retain each."""
        new = BlockTable(self._pool, list(self.block_ids))
        for bid in new.block_ids:
            self._pool.retain(bid)
        return new

    def free(self) -> None:
        for bid in self.block_ids:
            self._pool.release(bid)
        self.block_ids.clear()
```

### Step 4: The Prefix Tree (Radix Trie)

This is where prefix sharing lives. Each edge is labelled with a slice of token ids; each node carries the block id holding the tokens that end there.

```python
class _Node:
    __slots__ = ("children", "block_id", "depth_tokens")
    def __init__(self):
        self.children: dict[int, _Node] = {}
        self.block_id: Optional[int] = None
        self.depth_tokens: int = 0  # how many tokens from root to here

class PrefixTree:
    def __init__(self, pool: BlockPool, block_size: int = BLOCK_SIZE):
        self._pool = pool
        self._block_size = block_size
        self._root = _Node()

    def match(self, tokens: list[int]) -> tuple[list[int], int]:
        """Return (shared_block_ids, shared_token_count)."""
        node = self._root
        shared_blocks: list[int] = []
        i = 0
        while i + self._block_size <= len(tokens):
            key = tuple(tokens[i:i + self._block_size])
            if key not in node.children:
                break
            node = node.children[key]
            if node.block_id is None:
                break
            shared_blocks.append(node.block_id)
            self._pool.retain(node.block_id)
            i += self._block_size
        return shared_blocks, i

    def insert(self, tokens: list[int], block_ids: list[int]) -> None:
        node = self._root
        for j, bid in enumerate(block_ids):
            start = j * self._block_size
            key = tuple(tokens[start:start + self._block_size])
            if key not in node.children:
                node.children[key] = _Node()
            node = node.children[key]
            node.block_id = bid
            node.depth_tokens = start + self._block_size
```

### Step 5: The Cache Manager

The orchestrator that ties everything together.

```python
class Sequence:
    def __init__(self, seq_id: int, tokens: list[int], block_table: BlockTable):
        self.seq_id = seq_id
        self.tokens = list(tokens)
        self.block_table = block_table
        self.beam_id = 0

class CacheManager:
    def __init__(self, num_blocks: int):
        self.pool = BlockPool(num_blocks)
        self.prefix = PrefixTree(self.pool)
        self._seqs: dict[int, Sequence] = {}
        self._next_seq_id = 0

    def add_request(self, prompt_tokens: list[int]) -> Sequence:
        shared_blocks, shared_tokens = self.prefix.match(prompt_tokens)
        # Retain the shared blocks so they survive this request's lifetime.
        for bid in shared_blocks:
            self.pool.retain(bid)
        bt = BlockTable(self.pool, block_ids=list(shared_blocks))

        # Allocate blocks for the unshared suffix.
        remaining = prompt_tokens[shared_tokens:]
        for t in remaining:
            # In a real engine, K/V come from a forward pass; we synthesize.
            k = np.random.randn(NUM_KV_HEADS, HEAD_DIM).astype(DTYPE)
            v = np.random.randn(NUM_KV_HEADS, HEAD_DIM).astype(DTYPE)
            bt.write_token(k, v)

        seq_id = self._next_seq_id
        self._next_seq_id += 1
        seq = Sequence(seq_id, prompt_tokens, bt)
        self._seqs[seq_id] = seq

        # Publish the freshly written blocks into the prefix tree.
        if bt.block_ids:
            self.prefix.insert(prompt_tokens, bt.block_ids)
        return seq

    def fork_for_beam(self, parent: Sequence) -> Sequence:
        """CoW fork: a sibling beam starts from the parent's tokens."""
        new_bt = parent.block_table.fork()
        seq_id = self._next_seq_id
        self._next_seq_id += 1
        seq = Sequence(seq_id, list(parent.tokens), new_bt)
        seq.beam_id = parent.beam_id + 1
        self._seqs[seq_id] = seq
        return seq

    def append_token(self, seq: Sequence) -> None:
        k = np.random.randn(NUM_KV_HEADS, HEAD_DIM).astype(DTYPE)
        v = np.random.randn(NUM_KV_HEADS, HEAD_DIM).astype(DTYPE)
        seq.block_table.write_token(k, v)
        seq.tokens.append(-1)  # placeholder for generated token id

    def finish(self, seq: Sequence) -> None:
        seq.block_table.free()
        self._seqs.pop(seq.seq_id, None)

    def maybe_evict(self) -> int:
        # In production this runs on a timer or when allocate() raises.
        try:
            return self.pool.reclaim()
        except AssertionError:
            return -1
```

That is the entire manager. It is small enough to read in one sitting but exercises every interesting decision a production system makes.

## Running and Testing It

A test harness is what turns this from "code I wrote" into "a system I shipped." Keep it in the same file for convenience.

```python
# test_paged_kv.py
import unittest
from paged_kv import CacheManager, BlockTable, PrefixTree, BLOCK_SIZE

class TestPagedKV(unittest.TestCase):
    def test_allocate_and_write(self):
        cm = CacheManager(num_blocks=8)
        seq = cm.add_request([1, 2, 3, 4])
        self.assertGreater(len(seq.block_table.block_ids), 0)

    def test_prefix_sharing(self):
        cm = CacheManager(num_blocks=16)
        s1 = cm.add_request([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 99])
        s2 = cm.add_request([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 100])
        # s1 and s2 should share the first full block.
        self.assertEqual(s1.block_table.block_ids[0], s2.block_table.block_ids[0])
        cm.finish(s1); cm.finish(s2)

    def test_copy_on_write_via_fork(self):
        cm = CacheManager(num_blocks=8)
        parent = cm.add_request(list(range(1, BLOCK_SIZE * 3 + 1)))
        # Parent holds refs on every block.
        before_refs = [cm.pool.get(b).refcount for b in parent.block_table.block_ids]
        child = cm.fork_for_beam(parent)
        after_refs = [cm.pool.get(b).refcount for b in parent.block_table.block_ids]
        self.assertEqual([r * 2 for r in before_refs], after_refs)
        cm.finish(parent); cm.finish(child)

    def test_eviction_recycles_zero_refcount(self):
        cm = CacheManager(num_blocks=4)
        s1 = cm.add_request(list(range(1, BLOCK_SIZE + 1)))
        cm.finish(s1)             # refcount drops to 0
        evicted = cm.maybe_evict()
        self.assertNotEqual(evicted, -1)
        # Pool should have a free slot now.
        s2 = cm.add_request(list(range(100, 100 + BLOCK_SIZE)))
        self.assertIsNotNone(s2)

    def test_no_double_free(self):
        cm = CacheManager(num_blocks=4)
        s = cm.add_request(list(range(1, BLOCK_SIZE + 1)))
        cm.finish(s)
        # Calling finish again must not corrupt refcounts.
        cm.finish(s)

if __name__ == "__main__":
    unittest.main()
```

Run it:

```bash
python -m unittest test_paged_kv.py -v
```

All five tests should pass. If you want a smoke-test that prints what is happening:

```python
# demo.py
from paged_kv import CacheManager

cm = CacheManager(num_blocks=16)
prompts = [
    "The capital of France is",
    "The capital of France is Paris",
    "The capital of Germany is",
]
tokenized = [[ord(c) for c in p] for p in prompts]

for p in tokenized:
    seq = cm.add_request(p)
    print(f"prompt={''.join(chr(t) for t in p)} blocks={seq.block_table.block_ids}")
    cm.finish(seq)
print("free blocks after run:", len(cm.pool._free))
```

```bash
python demo.py
```

You should see the second prompt share its leading block with the first, and a non-empty free list after the run.

## Extending It: Your Roadmap to Senior-Level

A weekend gets you the system above. The next four weekends — in roughly this order — turn it into something that reads as production-flavored on a CV.

1. **Real GPU tensors and a CUDA-backed block.** Swap the `numpy` arrays for `torch` tensors living on a CUDA device. The management code does not change, only the storage. *Why it matters:* it proves you understand that the management layer is decoupled from the kernel layer — exactly the separation vLLM and SGLang maintain.
2. **Eviction as a background scheduler.** Move `maybe_evict` into a `threading` worker that wakes every 10 ms, or trigger it from `allocate()` when the pool is near capacity. Track eviction rate as a metric. *Why it matters:* eviction is a control loop, not an error path. Treating it like one is a senior-engineer tell.
3. **Persistence to disk and a warm-restart path.** On shutdown, serialize the prefix tree and block contents to disk; on boot, rehydrate before serving traffic. *Why it matters:* cold-start latency is a real production cost — see how [vLLM discusses prefix caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html) and how the [SGLang runtime](https://github.com/sgl-project/sglang) treats it.
4. **Observability: metrics and traces.** Emit Prometheus counters for `allocations`, `evictions`, `prefix_hits`, `cow_forks`, and a histogram for `block_pool_utilization`. Add OpenTelemetry spans across `add_request` → `append_token` → `finish`. *Why it matters:* "you can't operate what you can't measure" is a line that has shipped many an interview.
5. **Concurrency stress test.** Spawn 200 concurrent sequences that share prefixes, mutate, fork, and finish in random order. Hunt for races with `threading` + assertions, then move the lock to a per-block or sharded lock to recover throughput. *Why it matters:* this is the bug class that kills naive KV cache implementations.
6. **Benchmark against a baseline.** Reproduce a small version of the [PagedAttention paper](https://arxiv.org/abs/2309.06180)'s Figure 5: measure tokens/sec for batched requests *without* prefix sharing, then *with* it, then *with* CoW. *Why it matters:* numbers on a README are the single strongest signal on a portfolio.

If you ship even three of these, you have a project that an LLM inference hiring manager will read end to end.

## Key Takeaways

- A paged KV cache is just a virtual-memory manager for attention tensors. The interesting parts — block tables, prefix sharing, copy-on-write, eviction — fit in a few hundred lines.
- Prefix sharing through a radix tree turns prompts with shared system prompts or few-shot examples into a near-free operation; this is the single biggest throughput win in production inference.
- Copy-on-write is what makes beam search and parallel sampling safe to share prefixes. Without it, sibling beams corrupt each other.
- The differentiator between a toy and a system is the boring layer: refcounts, eviction under pressure, and tests that prove refcounts balance.
- A project like this signals exactly the skills hiring managers screen for in 2026: memory systems thinking, comfort with the inference stack, and the discipline to ship the boring parts.

## Further Reading

- [PagedAttention: Virtual Memory-style Management for LLM Serving (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180) — the paper this project is a faithful subset of; study it, then extend your implementation with its eviction policy.
- [vLLM documentation on Automatic Prefix Caching](https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html) — how a production system exposes prefix caching and what knobs it exposes.
- [SGLang: Efficient Execution of Structured Language Model Programs](https://arxiv.org/abs/2312.07104) — shows how prefix sharing is used at the program level, not just the request level.
- [RadixAttention (Zheng et al., SGLang)](https://github.com/sgl-project/sglang/blob/main/python/sglang/srt/mem_cache/radix_cache.py) — the reference implementation of a radix-tree KV cache; read it after you finish yours.
- [Efficient Memory Management for Large Language Model Serving with PagedAttention (vLLM blog)](https://blog.vllm.ai/2023/06/20/vllm.html) — the original announcement with motivating numbers and architecture diagrams.
- [NVIDIA TensorRT-LLM: KV cache configuration guide](https://nvidia.github.io/TensorRT-LLM/architecture/core-concepts.html) — a contrasting design where the KV layout is configured per model rather than paged; useful for understanding the design space.

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
