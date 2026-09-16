---
title: "Building a Mini LLM Inference Engine in Pure Python"
date: "2026-09-16T11:02:24.910"
draft: false
tags: ["LLM Inference", "PagedAttention", "Python", "Systems Engineering", "Side Project"]
description: "Build a mini LLM inference engine from scratch in Python using PagedAttention, prefix-aware block refcounting, and token-budget LRU KV eviction to signal deep systems engineering skills."
summary: "A hands-on guide to building a mini LLM inference engine featuring PagedAttention and advanced KV cache management, designed to demonstrate production-grade systems architecture on your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-16-building-a-mini-llm-inference-engine-in-pure-python.svg"
  alt: "A visualization of memory blocks and tokens in a neural network inference engine"
  caption: ""
  relative: false
---

> **TL;DR** — Build a mini LLM inference engine in pure Python to demonstrate deep systems engineering skills. By implementing PagedAttention, prefix-aware block refcounting, and token-budget LRU KV eviction, you signal to hiring managers that you understand memory management, distributed systems, and production-grade architecture, not just model architectures.

Most engineers building portfolio projects focus on fine-tuning models or building chat interfaces with APIs. While understandable, these projects rarely demonstrate the systems-level thinking that hiring managers covet for infrastructure and backend roles. To truly stand out, you need a project that proves you understand the plumbing beneath the model: memory management, caching strategies, and computational scheduling.

A mini LLM inference engine built from scratch is the ultimate systems project. It forces you to confront the reality of the Key-Value (KV) cache—the primary bottleneck in LLM serving—and how to manage it efficiently. By implementing PagedAttention, prefix-aware block refcounting, and token-budget LRU KV eviction in pure Python, you bridge the gap between academic ML knowledge and production systems engineering.

## Why This Project Stands Out on a CV

This project signals a rare blend of skills that separates junior developers from senior systems engineers. Here is exactly what it demonstrates to hiring managers:

*   **Memory Management & Allocation:** Implementing PagedAttention shows you understand how operating systems manage virtual memory and how to apply paging concepts to GPU/CPU memory to eliminate fragmentation.
*   **Concurrency & Scheduling:** Managing a queue of incoming requests and allocating resources to them mirrors the work of a production scheduler like Kubernetes or an OS process scheduler.
*   **Cache Invalidation & Eviction:** The token-budget LRU eviction logic proves you understand how to design systems that gracefully degrade under memory pressure, a critical skill for any backend engineer working with caches (Redis, Memcached).
*   **Algorithmic Optimization:** Prefix-aware block refcounting requires you to think about data sharing and reference counting, concepts central to copy-on-write systems and database management.

For roles like ML Infrastructure Engineer, Backend Systems Engineer, or Performance Engineer, this project is a direct signal that you can architect systems that are both compute-efficient and memory-safe.

## Architecture Overview

The engine is composed of several distinct, decoupled components that communicate through well-defined interfaces. Understanding how these pieces fit together is crucial before writing a single line of code.

```text
+----------------+       +-------------------+       +----------------------+
|  Input Prompt  | ----> |   Tokenizer       | ----> |   Scheduler          |
+----------------+       +-------------------+       +----------+-----------+
                                                                |
                                                                v
                                          +-------------------+-------------------+
                                          |   PagedAttention Manager            |
                                          |   +-------------------------------+ |
                                          |   | Block Table (Page Mapping)    | |
                                          |   +-------------------------------+ |
                                          |   | Free List (Available Blocks)  | |
                                          |   +-------------------------------+ |
                                          +-------------------+---------------+
                                                                |
                                                                v
                                          +-------------------+-------------------+
                                          |   KV Cache Manager                  |
                                          |   +-------------------------------+ |
                                          |   | Prefix-Aware Refcounter       | |
                                          |   +-------------------------------+ |
                                          |   | Token-Budget LRU Evictor      | |
                                          |   +-------------------------------+ |
                                          +-------------------+---------------+
                                                                |
                                                                v
                                          +-------------------+-------------------+
                                          |   Model Core (Linear + Softmax)     |
                                          +-------------------------------------+
```

*   **Tokenizer:** Converts raw text into token IDs. It is the entry point for all requests.
*   **Scheduler:** Manages the lifecycle of a request, feeding tokens to the model and collecting generated outputs.
*   **PagedAttention Manager:** The core memory allocator. It maintains a `Block Table` mapping logical token positions to physical memory blocks, and a `Free List` of unused blocks.
*   **KV Cache Manager:** Handles the actual storage of keys and values. It uses a `Prefix-Aware Refcounter` to track how many requests are sharing a specific block of the cache, and a `Token-Budget LRU Evictor` to remove the least recently used blocks when memory limits are reached.
*   **Model Core:** The mathematical engine that takes token IDs and KV states to produce the next token probabilities.

## Building It Step by Step

We will build the core logic in pure Python, utilizing `dataclasses` for structure and `collections.OrderedDict` for our LRU cache. This implementation will be functional and demonstrate the exact mechanics used in systems like vLLM.

### Step 1: Define the Paged Block Structure

First, we define the physical memory blocks and the logical page table. In PagedAttention, the KV cache is divided into fixed-size blocks. We map logical tokens to these physical blocks.

```python
from dataclasses import dataclass, field
from typing import List, Optional

@dataclass
class KVBlock:
    block_id: int
    keys: List[float] = field(default_factory=list)
    values: List[float] = field(default_factory=list)
    refcount: int = 0

class PagedAttentionManager:
    def __init__(self, total_blocks: int, block_size: int):
        self.total_blocks = total_blocks
        self.block_size = block_size
        self.free_list: List[int] = list(range(total_blocks))
        self.block_table: dict[int, KVBlock] = {}
        
    def allocate_block(self) -> Optional[int]:
        if not self.free_list:
            return None
        block_id = self.free_list.pop(0)
        self.block_table[block_id] = KVBlock(block_id=block_id)
        return block_id

    def free_block(self, block_id: int):
        if block_id in self.block_table:
            self.block_table[block_id].refcount -= 1
            if self.block_table[block_id].refcount <= 0:
                self.free_list.append(block_id)
                del self.block_table[block_id]
```

### Step 2: Implement Prefix-Aware Block Refcounting

When multiple prompts share a common prefix (e.g., a system prompt), they should share the same physical KV blocks. We use a reference counter to ensure a block is only freed when no request is using it.

```python
class PrefixAwareRefcounter:
    def __init__(self, paged_manager: PagedAttentionManager):
        self.paged_manager = paged_manager
        self.prefix_map: dict[str, int] = {} # Maps prefix hash to block_id

    def get_or_create_prefix_block(self, prefix_hash: str) -> int:
        if prefix_hash in self.prefix_map:
            block_id = self.prefix_map[prefix_hash]
            self.paged_manager.block_table[block_id].refcount += 1
            return block_id
        
        block_id = self.paged_manager.allocate_block()
        if block_id is not None:
            self.prefix_map[prefix_hash] = block_id
            self.paged_manager.block_table[block_id].refcount = 1
        return block_id
```

### Step 3: Build the Token-Budget LRU Evictor

To prevent out-of-memory errors, we must evict blocks when the budget is exceeded. We use an `OrderedDict` to track the least recently used blocks. When a block is accessed, it moves to the end; when evicting, we pop the first item.

```python
from collections import OrderedDict

class TokenBudgetLRUEvictor:
    def __init__(self, paged_manager: PagedAttentionManager, max_tokens: int):
        self.paged_manager = paged_manager
        self.max_tokens = max_tokens
        self.current_tokens = 0
        self.lru_cache: OrderedDict[int, int] = OrderedDict() # block_id -> token_count

    def access_block(self, block_id: int, token_count: int):
        if block_id in self.lru_cache:
            self.lru_cache.move_to_end(block_id)
        else:
            self.lru_cache[block_id] = token_count
            self.current_tokens += token_count
            self._evict_if_needed()

    def _evict_if_needed(self):
        while self.current_tokens > self.max_tokens and self.lru_cache:
            oldest_block_id, tokens = self.lru_cache.popitem(last=False)
            self.current_tokens -= tokens
            self.paged_manager.free_block(oldest_block_id)
```

### Step 4: Assemble the Inference Loop

Finally, we tie the components together. The engine tokenizes the input, allocates blocks, runs the model step-by-step, and manages the KV cache lifecycle.

```python
class InferenceEngine:
    def __init__(self, model_weights, max_memory_tokens: int = 1000):
        self.tokenizer = SimpleTokenizer()
        self.paged_manager = PagedAttentionManager(total_blocks=500, block_size=16)
        self.refcounter = PrefixAwareRefcounter(self.paged_manager)
        self.evictor = TokenBudgetLRUEvictor(self.paged_manager, max_memory_tokens)
        self.model = model_weights

    def generate(self, prompt: str) -> str:
        tokens = self.tokenizer.encode(prompt)
        prefix_hash = self._get_prefix_hash(tokens)
        
        # Allocate or reuse block based on prefix
        block_id = self.refcounter.get_or_create_prefix_block(prefix_hash)
        if block_id is not None:
            self.evictor.access_block(block_id, len(tokens))
            
        generated_tokens = []
        for token in tokens:
            # Simulate model step using the KV block
            output_token = self.model.step(token, self.paged_manager.block_table[block_id])
            generated_tokens.append(output_token)
            
        return self.tokenizer.decode(generated_tokens)
```

## Running and Testing It

To run the engine locally, you simply instantiate the `InferenceEngine` with a dummy set of weights and call the `generate` method. 

```bash
python main.py "Explain the concept of PagedAttention"
```

To prove the system works, you should write rigorous unit tests focusing on the memory management components. Using `pytest`, you can assert that blocks are correctly shared and evicted.

```python
def test_prefix_refcounting():
    manager = PagedAttentionManager(10, 16)
    refcounter = PrefixAwareRefcounter(manager)
    
    block1 = refcounter.get_or_create_prefix_block("hello")
    assert manager.block_table[block1].refcount == 1
    
    block2 = refcounter.get_or_create_prefix_block("hello")
    assert manager.block_table[block1].refcount == 2
    assert block1 == block2

def test_lru_eviction():
    manager = PagedAttentionManager(10, 16)
    evictor = TokenBudgetLRUEvictor(manager, max_tokens=32)
    
    block1 = manager.allocate_block()
    evictor.access_block(block1, 16)
    
    block2 = manager.allocate_block()
    evictor.access_block(block2, 16)
    
    # Adding a third block should trigger eviction of the first
    block3 = manager.allocate_block()
    evictor.access_block(block3, 16)
    
    assert block1 not in manager.block_table
```

Running `pytest` will confirm that your prefix sharing works and your memory budget strictly enforces the LRU eviction policy.

## Extending It: Your Roadmap to Senior-Level

To transform this toy project into a production-flavored system that truly impresses senior engineers, consider implementing the following upgrades:

1.  **Persistent KV Cache via Redis:** Integrate Redis to persist the KV cache to disk. This ensures that long-running sessions survive engine restarts, drastically improving fault tolerance and user experience.
2.  **Continuous Batching Scheduler:** Replace the sequential processing with a continuous batching mechanism that dynamically adds new requests to the batch while computing existing ones. This maximizes hardware utilization and reduces latency.
3.  **gRPC API Layer:** Wrap the engine in a gRPC service. This enables efficient, language-agnostic horizontal scaling, allowing you to deploy multiple engine instances behind a load balancer.
4.  **Prometheus Metrics Integration:** Expose Prometheus metrics for cache hit rates, eviction counts, and request latency. Observability is non-negotiable in production systems, allowing you to proactively manage resource bottlenecks.
5.  **PagedAttention v2 (Blocksize Tuning):** Implement dynamic blocksize allocation based on the sequence length. Smaller blocks reduce memory waste for short sequences, while larger blocks minimize overhead for long sequences, optimizing memory bandwidth.
6.  **Speculative Decoding:** Add a smaller "draft" model that generates tokens faster, which the main model then verifies in parallel. This pattern significantly increases throughput without sacrificing output quality.

## Key Takeaways

*   Implementing PagedAttention in a side project demonstrates a deep understanding of memory management and external fragmentation, bridging OS concepts with ML infrastructure.
*   Prefix-aware block refcounting is a practical application of copy-on-write and reference counting, proving you can optimize memory usage for shared data.
*   Token-budget LRU eviction shows you can design systems that gracefully handle resource constraints, a critical skill for any backend or infrastructure role.
*   Building this in pure Python forces you to understand the underlying mechanics without hiding behind optimized C++ or CUDA libraries, making your systems knowledge explicit.
*   A project like this signals to hiring managers that you are capable of architecting the full stack, from the mathematical model to the memory allocator.

## Further Reading

To deepen your understanding and evolve this project further, study the primary sources that inspired these architectural patterns:

*   [Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — The foundational paper by the vLLM team that introduced the PagedAttention concept.
*   [FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135) — A critical paper on optimizing the attention mechanism itself, which complements the memory management focus of this project.
*   [Redis Persistence Documentation](https://redis.io/docs/management/persistence/) — The canonical documentation for implementing the persistent KV cache upgrade mentioned in the roadmap.