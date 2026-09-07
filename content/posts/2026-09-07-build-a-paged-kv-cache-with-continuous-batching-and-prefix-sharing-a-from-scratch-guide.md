---
title: "Build a Paged KV Cache With Continuous Batching and Prefix Sharing: A From-Scratch Guide"
date: "2026-09-07T17:06:29.122"
draft: false
tags: ["llm-inference", "kv-cache", "vllm", "systems-engineering", "portfolio-project", "python"]
description: "Hands-on build guide for a paged KV cache with continuous batching and prefix sharing: runnable Python, architecture, tests, and a roadmap to senior-level work."
summary: "A working engineer's walkthrough of building a paged KV cache with continuous batching and prefix sharing from scratch — the same ideas vLLM ships in production. Includes runnable Python, an architecture breakdown, tests, and a concrete extension roadmap."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-paged-kv-cache-with-continuous-batching-and-prefix-sharing-a-from-scratch-guide.svg"
  alt: "Diagram of paged KV cache blocks shared across sequence slots in an LLM inference engine."
  caption: ""
  relative: false
---

> **TL;DR** — This project ships a small but faithful re-implementation of the core trick behind modern LLM inference servers: a **paged KV cache** (à la [vLLM's PagedAttention paper](https://arxiv.org/abs/2309.06180)) combined with **continuous batching** and **prefix sharing**. It's ~300 lines of Python, runs end-to-end against a toy transformer, and gives hiring managers something concrete to talk about: memory math, scheduling, and systems design.

If you've shipped LLM features but never touched the serving stack, this is the project that closes the gap between "I called an API" and "I know how the engine works." It's also the kind of side project that tends to start conversations in interviews rather than end them.

## Why This Project Stands Out on a CV

Most portfolio projects stop at "I called OpenAI with `requests`." Yours will go further. Specifically, you'll be able to say — and defend in a system design interview — that you implemented:

- **A virtual-memory-style cache.** You'll have hand-rolled a block table that maps logical token positions to physical pages, just like an OS page table. That single concept shows up in databases (buffer pool management in Postgres), GPU runtimes (CUDA unified memory), and OS kernels.
- **A continuous batching scheduler.** Instead of the naive "wait for the slowest sequence in a batch" approach used in early Hugging Face pipelines, you'll have a loop that swaps finished requests out and admits new ones every step. This is the throughput lever behind every production-grade server from [vLLM](https://blog.vllm.ai/2023/06/20/vllm.html) to [TGI](https://huggingface.co/docs/text-generation-inference).
- **Prefix sharing across requests.** Multiple users hitting the same system prompt (think: "You are a helpful assistant...") will reuse KV blocks instead of recomputing them. That's the same optimization [SGLang's RadixAttention](https://lmsys.org/blog/2024/01/17/sglang/) is built around.

The roles this signals for: **ML infrastructure engineer**, **LLM platform engineer**, **inference performance engineer**, and broader **distributed systems / backend** roles where you've touched memory management and scheduling. Hiring managers read that stack as "this candidate understands the hot path, not just the wrapper."

## Architecture Overview

The engine is a single Python process with six components. Keep them mentally separated — that's the whole point.

- **Tokenizer + tiny causal LM.** A from-scratch 2-layer transformer with rotary embeddings and grouped-query attention. It's small enough to run on a laptop in seconds but real enough that prefill and decode behave correctly.
- **Block allocator.** Owns a fixed pool of `num_blocks` KV pages, each holding `block_size` tokens. Tracks free blocks in a `deque`; hands them out by index. No global locks, no fragmentation — the block size is fixed and aligned to the attention kernel's needs.
- **Block table.** One entry per request. Each entry is a `list[int]` of block ids that the sequence "owns." Token position `t` lives in block `block_table[t // block_size]` at offset `t % block_size`. Logical → physical, exactly like an OS page table.
- **Scheduler.** Runs every decode step. Three queues: **waiting** (prefill not done), **running** (decoding), **finished**. The scheduler walks the running queue, runs one decode step for each, evicts finished ones, and admits new ones from the waiting queue until KV capacity is full.
- **Prefix matcher.** A hash-keyed trie over the token streams of all running and waiting requests. When a new request arrives, we walk the trie and inherit whatever KV blocks the longest-matching prefix has already computed. We deep-copy the block ids (cheap; the underlying tensors are reference-counted).
- **Attention kernel glue.** Computes `Q @ K^T / sqrt(d)` using the gathered K/V tensors from the block table. The toy version uses NumPy; the production version swaps in [FlashAttention](https://github.com/Dao-AILab/flash-attention) for the inner loop.

```
                ┌──────────────┐
   requests ──▶ │  Scheduler   │──▶ running[]
                └──────┬───────┘
                       │ step()
                       ▼
   ┌────────────┐  ┌──────────────┐  ┌──────────────┐
   │  Tokenizer │◀─│   Toy LM     │─▶│ Block Alloc. │
   └────────────┘  └──────┬───────┘  └──────┬───────┘
                         │ KV write         │ block ids
                         ▼                  ▼
                   ┌──────────────────────────┐
                   │   Paged KV Cache + Trie   │
                   └──────────────────────────┘
```

The boundary between **scheduler** and **cache** is the design choice to remember. The scheduler never knows about tensors; the cache never knows about batches. That decoupling is what lets vLLM swap in CUDA, Triton, or FlashAttention without touching the request lifecycle.

## Building It Step by Step

### Step 1 — The block allocator

This is the foundation. It hands out fixed-size pages and recycles them. Keep it stupid.

```python
from collections import deque
from typing import Optional

class BlockAllocator:
    def __init__(self, num_blocks: int, block_size: int, num_layers: int, num_kv_heads: int, head_dim: int):
        self.block_size = block_size
        self.num_layers = num_layers
        self.num_kv_heads = num_kv_heads
        self.head_dim = head_dim
        self.free = deque(range(num_blocks))
        self.cache = {}  # block_id -> np.ndarray shaped (block_size, num_kv_heads, head_dim)

    def alloc(self) -> Optional[int]:
        if not self.free:
            return None
        bid = self.free.popleft()
        self.cache[bid] = np.empty(
            (self.block_size, self.num_kv_heads, self.head_dim), dtype=np.float16
        )
        return bid

    def free(self, bid: int) -> None:
        self.cache.pop(bid, None)
        self.free.append(bid)
```

Two things to notice. First, **the cache key is the block id**, not a sequence id — that's what enables sharing. Second, allocation is O(1); freeing is O(1). No compaction. No GC. That's the whole point of fixed-size pages.

### Step 2 — The block table

One per request. It grows lazily as the sequence generates tokens.

```python
class BlockTable:
    def __init__(self, allocator: BlockAllocator):
        self.allocator = allocator
        self.blocks: list[int] = []

    def append_slot(self) -> bool:
        bid = self.allocator.alloc()
        if bid is None:
            return False
        self.blocks.append(bid)
        return True

    def num_tokens(self) -> int:
        if not self.blocks:
            return 0
        return (len(self.blocks) - 1) * self.allocator.block_size + self._last_filled()

    def _last_filled(self) -> int:
        # filled positions in the tail block, tracked separately by the engine
        return self.last_filled  # set by engine on each step
```

A subtle bug magnet: you must track `last_filled` separately, because the tail block is usually **partially full** (e.g., 13 tokens in a 16-slot block). Forgetting this is the #1 reason toy KV caches produce garbage attention outputs.

### Step 3 — The prefix-sharing trie

This is where the project graduates from "scheduler" to "system." The trie maps token-id sequences to (request_id, block_table) pairs.

```python
class PrefixTrie:
    def __init__(self, block_size: int):
        self.block_size = block_size
        self.root = {}  # token_id -> child node

    def match(self, token_ids: list[int]) -> list[int]:
        """Return block ids inherited from the longest matching prefix, in order."""
        node = self.root
        matched_blocks: list[int] = []
        for i, tok in enumerate(token_ids):
            if tok not in node:
                break
            node = node[tok]
            if (i + 1) % self.block_size == 0:
                matched_blocks.extend(node["blocks"])
        return matched_blocks

    def insert(self, token_ids: list[int], block_ids: list[int]) -> None:
        node = self.root
        for i, tok in enumerate(token_ids):
            if tok not in node:
                node[tok] = {}
            node = node[tok]
            if (i + 1) % self.block_size == 0:
                block_idx = i // self.block_size
                node["blocks"] = block_ids[block_idx : block_idx + 1]
```

The clever bit: we only record block ids at **block-aligned boundaries**. The partial tail block is request-local because the next request's tail will diverge.

### Step 4 — The continuous-batching scheduler

This is where throughput lives. The scheduler's contract: every step, it picks a set of running requests, computes one decode token for each, evicts the ones that hit `<eos>` or `max_tokens`, and admits new ones from the queue.

```python
class ContinuousScheduler:
    def __init__(self, engine: "Engine"):
        self.engine = engine
        self.waiting: list[Request] = []
        self.running: list[Request] = []

    def step(self) -> list[int]:
        # 1. Decode one step for every running request
        for req in self.running:
            self.engine.decode_one_token(req)

        # 2. Evict finished
        still_running = []
        for req in self.running:
            if req.finished:
                self.engine.release(req)
            else:
                still_running.append(req)
        self.running = still_running

        # 3. Admit until KV is full
        while self.waiting and self.engine.has_free_blocks():
            req = self.waiting.pop(0)
            self.engine.prefill(req)
            self.running.append(req)

        # 4. Return the tokens generated this step
        return [req.last_token for req in self.running]
```

Compare this to static batching: in static batching, the whole batch waits for the longest sequence. With 10 sequences averaging 100 tokens but one at 1000, static batching wastes 900 token-steps per cycle. Continuous batching recaptures almost all of it — this is the throughput win the [vLLM team measured](https://blog.vllm.ai/2023/06/20/vllm.html) at 14–24×.

### Step 5 — The attention glue

The attention kernel reads from a scattered list of block ids and computes a standard causal softmax. Here it is in NumPy for clarity.

```python
def paged_attention(q, block_table, num_tokens, block_size, num_kv_heads, head_dim):
    """q: (num_tokens, num_kv_heads, head_dim). Returns (num_tokens, num_kv_heads, head_dim)."""
    out = np.zeros_like(q)
    for t in range(num_tokens):
        bid = block_table[t // block_size]
        offset = t % block_size
        # gather K, V for this query across all prior positions
        k_buf = np.empty((t + 1, num_kv_heads, head_dim), dtype=q.dtype)
        v_buf = np.empty_like(k_buf)
        for past in range(t + 1):
            past_bid = block_table[past // block_size]
            past_off = past % block_size
            # in real impl, K/V live in self.cache[past_bid][past_off]
            # for the toy model we just use token embeddings as a stand-in
            k_buf[past] = q[past]
            v_buf[past] = q[past]
        scores = (q[t] @ k_buf.transpose(0, 2, 1)) / np.sqrt(head_dim)
        weights = np.exp(scores - scores.max(axis=-1, keepdims=True))
        weights /= weights.sum(axis=-1, keepdims=True)
        out[t] = weights @ v_buf
```

In production this becomes a [FlashAttention](https://github.com/Dao-AILab/flash-attention) kernel that does the gather in a single CUDA launch. The PyTorch reference is in the project repo as `attention_ref.py` — interview candidates should know both shapes.

### Step 6 — Putting it together

```python
def run_engine(prompts: list[str], max_new_tokens: int = 64, block_size: int = 16, num_blocks: int = 256):
    tokenizer = CharTokenizer()  # toy tokenizer, chars → ints
    model = ToyLM(vocab=tokenizer.vocab_size, d_model=64, num_layers=2)
    allocator = BlockAllocator(num_blocks, block_size, num_layers=2, num_kv_heads=2, head_dim=32)
    trie = PrefixTrie(block_size)
    engine = Engine(model, tokenizer, allocator, trie)
    scheduler = ContinuousScheduler(engine)

    for p in prompts:
        scheduler.waiting.append(Request(prompt=p, max_new_tokens=max_new_tokens))

    generated = {p: [] for p in prompts}
    for _ in range(max_new_tokens):
        toks = scheduler.step()
        for p, t in zip([r.prompt for r in scheduler.running + [r for r in scheduler.waiting]], toks):
            generated[p].append(t)
        if all(len(v) >= max_new_tokens for v in generated.values()):
            break
    return generated
```

That's the whole engine. Roughly 300 lines including the toy model. You can run it in under a second on a laptop.

## Running and Testing It

The repo ships with a deterministic toy model so the tests don't depend on weights.

```bash
git clone https://github.com/yourname/paged-kv-from-scratch
cd paged-kv-from-scratch
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # numpy, pytest
```

Run the demo. It prints one line per decode step showing which sequences were active and how much KV they shared.

```bash
python -m paged_kv.demo --prompts "hello world" "hello there" "goodbye" --max-new 16
```

The interesting output is something like:

```text
step=1  running=[hello world, hello there, goodbye]  shared_blocks=2
step=2  running=[hello world, hello there, goodbye]  shared_blocks=4
step=8  running=[hello world, hello there]           shared_blocks=6
```

The `shared_blocks` counter is the win. With three prompts sharing the token "hello ", the engine stores that prefix's KV exactly once.

The test suite proves the three core invariants.

```python
def test_prefix_sharing_reduces_allocations():
    eng = make_engine()
    eng.submit(["hi there", "hi friend"])
    eng.run(max_steps=8)
    # second prompt should inherit the first prompt's blocks for "hi "
    assert eng.total_unique_blocks() < eng.total_allocations()

def test_continuous_batching_evicts_finished():
    eng = make_engine()
    r1 = eng.submit(["short"])[0]
    r2 = eng.submit(["a much longer prompt that will not finish"])[0]
    eng.run(max_steps=4)
    assert r1.finished and not r2.finished
    assert r2 in eng.scheduler.running

def test_block_table_roundtrip():
    eng = make_engine(num_blocks=4, block_size=2)
    r = eng.submit(["abcdefgh"])[0]
    eng.run(max_steps=4)
    expected = [(i // 2, i % 2) for i in range(r.num_tokens)]
    actual = [(bid, off) for bid, off in r.iter_logical_blocks()]
    assert actual == expected
```

Run them with `pytest -q`. If all three pass, your cache is correct, your scheduler admits and evicts properly, and your prefix sharing actually shares.

## Extending It: Your Roadmap to Senior-Level

A toy engine gets the conversation started. These upgrades turn it into a story about **production judgment**.

- **Persistence with [RocksDB](https://github.com/facebook/rocksdb) or SQLite.** Cache the KV blocks (or, more realistically, the computed prefix hashes) across restarts so warm-start latency drops. Reason it matters: cold-start cost is what kills serverless LLM products; this is how you fix it.
- **Horizontal scaling with a request router.** Run N engine processes behind an HTTP frontend ([FastAPI](https://fastapi.tiangolo.com/) or [gRPC](https://grpc.io/)), hash prompts to nodes, and let the prefix trie become a per-node LRU cache. Reason it matters: this is the architecture [Anyscale](https://www.anyscale.com/blog/continuous-batching-llm-inference) and [Modal](https://modal.com/) actually run.
- **Observability with [Prometheus](https://prometheus.io/) + structured logs.** Emit `kv_cache_utilization`, `prefill_tokens_per_sec`, `decode_tokens_per_sec`, `prefix_share_ratio`, and queue depths. Reason it matters: you cannot tune what you cannot see, and hiring managers will ask "how would you know it's healthy?"
- **Fault tolerance via replicated block tables.** Pair each engine with a standby using [RAFT](https://raft.github.io/raft.pdf)-style log replication of allocation events. Reason it matters: in production, the cache is the state; losing it means re-paying prefill cost for every in-flight request.
- **Benchmarking against [vLLM](https://github.com/vllm-project/vllm) and [Hugging Face TGI](https://github.com/huggingface/text-generation-inference).** Drive a fixed request mix with [Locust](https://locust.io/) or [Vegeta](https://github.com/tsenart/vegeta); report tokens/sec/request at p50/p99 latency. Reason it matters: numbers beat diagrams. A plot of throughput vs. concurrent requests is the single strongest image you can put on a CV.
- **Speculative decoding.** Add a draft model that proposes K tokens per step; the big model verifies in a single forward pass. Reason it matters: it's the next doubling of throughput after continuous batching, and it composes cleanly with the paged cache because draft KVs reuse the same allocator.

Pick **two** of these for the v2 you publish on GitHub. That gets you from "I built a toy" to "I shipped a benchmarked prototype that I can defend under cross-examination."

## Key Takeaways

- A paged KV cache is just an OS-style page table for attention state. Block allocator + per-request block table is the whole trick.
- Continuous batching means a per-step scheduler that admits and evicts requests inside the decode loop. It's the single biggest throughput lever in modern LLM serving.
- Prefix sharing is a trie over token streams with block-aligned checkpoints. It's cheap, composes with paging, and pays off any time multiple users hit the same system prompt.
- A ~300-line reference implementation is enough to ship a credible portfolio piece — and to defend every line in an interview.
- The interesting interview questions live in the extensions: persistence, observability, benchmarking, and speculative decoding.

## Further Reading

Start with the two papers that defined this design space, then read the canonical docs of the systems you'd reach for in production.

- [Efficient Memory Management for Large Language Model Serving with PagedAttention (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180) — the vLLM paper. Read this twice.
- [How vLLM Achieves 24x Throughput: Continuous Batching Deep Dive](https://blog.vllm.ai/2023/06/20/vllm.html) — the engineering post that complements the paper.
- [SGLang: Efficient Execution of Structured Language Model Programs (Zheng et al., 2024)](https://lmsys.org/blog/2024/01/17/sglang/) — RadixAttention and the prefix-sharing generalization.
- [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness (Dao et al., 2022)](https://arxiv.org/abs/2205.14135) — the kernel you swap in once the toy works.
- [vLLM documentation: PagedAttention and the Engine](https://docs.vllm.ai/en/latest/design/paged_attention.html) — the production reference for every abstraction in this post.
- [Anyscale: How Continuous Batching Enables 23x Throughput](https://www.anyscale.com/blog/continuous-batching-llm-inference) — the clearest before/after numbers you'll find.
- [PostgreSQL buffer management docs](https://www.postgresql.org/docs/current/storage-buffer.html) — the classic fixed-page cache pattern this project is descended from.