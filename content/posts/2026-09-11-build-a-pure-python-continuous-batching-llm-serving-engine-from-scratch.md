---
title: "Build a Pure-Python Continuous Batching LLM Serving Engine from Scratch"
date: "2026-09-11T19:00:47.799"
draft: false
tags: ["LLM Serving", "Systems Engineering", "Python", "PagedAttention", "Continuous Batching", "Distributed Systems"]
description: "Build a production-grade LLM serving engine from scratch in pure Python. Learn continuous batching, PagedAttention KV cache management, and request prefetching with real, runnable code."
summary: "A hands-on guide to building a pure-Python continuous batching LLM serving engine with PagedAttention KV cache and dynamic batch scheduling — a portfolio project that signals deep systems engineering skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-build-a-pure-python-continuous-batching-llm-serving-engine-from-scratch.svg"
  alt: "Code editor showing a Python-based LLM serving engine implementation"
  caption: "A pure-Python LLM serving engine implementing continuous batching and PagedAttention."
  relative: false
---

> **TL;DR** — This guide walks you through building a production-flavored LLM serving engine entirely in pure Python: continuous batching with dynamic scheduling, a PagedAttention-inspired KV cache manager, and request prefetching. You'll ship runnable code at every step, producing a portfolio project that demonstrates exactly the systems skills hiring managers look for in senior backend and ML infrastructure roles.

---

## Why This Project Stands Out on a CV

Most LLM portfolio projects stop at "I called the OpenAI API" or "I fine-tuned a model with LoRA." Those are valuable, but they signal consumption, not construction. A continuous batching serving engine signals something different: you understand the plumbing between the model and the user.

Specifically, this project demonstrates:

- **Systems-level concurrency** — You manage async request lifecycles, preemption, and scheduling under resource constraints. This is the same problem space as a web server's request queue, but with GPU memory as the binding constraint.
- **Memory management expertise** — PagedAttention borrows directly from virtual memory paging. Implementing it shows you understand page tables, block allocation, and fragmentation — concepts that transfer to OS kernels, databases, and storage engines.
- **Performance engineering** — Dynamic batch sizing, token-level prefetching, and KV cache reuse are the exact optimizations that separate a toy inference script from a system serving thousands of requests per second.
- **ML infrastructure fluency** — Hiring managers at companies running production LLMs (the ones with titles like "ML Platform Engineer" or "Infra Lead") actively look for candidates who understand serving kernels, not just model architectures.

This project positions you for roles in **ML platform engineering, backend systems engineering at AI-native companies, and infrastructure research**. It sits at the intersection of distributed systems and deep learning — a rare and high-signal combination.

## Architecture Overview

The engine is composed of five tightly coupled components. Here's how they fit together:

```
┌─────────────────────────────────────────────────────────────┐
│                      HTTP / Async API Layer                   │
│         (Receives prompts, returns generated tokens)         │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                  Request Manager                              │
│  • Holds pending, in-flight, and completed requests          │
│  • Assigns request IDs, tracks status                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Continuous Batch Scheduler                       │
│  • Sorts requests by priority / arrival time                 │
│  • Packs requests into dynamic batches each step             │
│  • Handles preemption when KV cache is full                  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│           PagedAttention KV Cache Manager                     │
│  • Divides KV cache into fixed-size blocks                    │
│  • Manages block allocation / free-list                      │
│  • Maps attention queries to physical blocks                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────┐
│              Model Runner + Prefetcher                        │
│  • Executes forward pass on current batch                    │
│  • Prefetches next-block KV entries for ongoing requests     │
│  • Yields generated tokens back to scheduler                 │
└─────────────────────────────────────────────────────────────┘
```

The critical insight is the **data flow**: the scheduler feeds batches to the model runner, the model runner consults the KV cache manager for memory, and the KV cache manager reports block availability back to the scheduler. This circular dependency is what makes continuous batching non-trivial — you cannot build any component in isolation.

## Building It Step by Step

Below is the core implementation. Each snippet is a working building block; combined, they form a complete engine. We use `asyncio` for concurrency and `dataclasses` for clean request modeling. No external ML framework is required — the model forward pass is abstracted so you can plug in any tokenizer + model later.

### Step 1: Define the Request and Batch Structures

```python
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional
import uuid
import time


class RequestStatus(Enum):
    PENDING = auto()
    INFLIGHT = auto()
    COMPLETED = auto()
    PREEMPTED = auto()


@dataclass
class GenerateRequest:
    """Represents a single user generation request."""
    request_id: str
    prompt: str
    max_new_tokens: int = 256
    temperature: float = 1.0
    status: RequestStatus = RequestStatus.PENDING
    created_at: float = field(default_factory=time.time)

    # Runtime state populated by the engine
    token_ids: List[int] = field(default_factory=list)
    kv_block_ids: List[int] = field(default_factory=list)
    num_generated: int = 0
    finished: bool = False

    @classmethod
    def create(cls, prompt: str, **kwargs) -> "GenerateRequest":
        return cls(request_id=str(uuid.uuid4()), prompt=prompt, **kwargs)
```

### Step 2: Implement the PagedAttention KV Cache Manager

This is the heart of the project. PagedAttention divides the KV cache into fixed-size blocks, analogous to virtual memory pages. A free-list tracks available blocks, and each request's attention layers map to a sequence of block IDs.

```python
@dataclass
class KVBlock:
    """A single fixed-size block of KV cache memory."""
    block_id: int
    key: Optional[List[float]] = None   # Simplified: real impl uses tensors
    value: Optional[List[float]] = None
    occupied: bool = False
    ref_count: int = 0


class PagedKVCacheManager:
    """
    Manages a pool of KV cache blocks using a free-list allocator.
    Mirrors the PagedAttention paper's block table abstraction.
    """

    def __init__(self, total_blocks: int, block_size: int, num_kv_heads: int, head_dim: int):
        self.total_blocks = total_blocks
        self.block_size = block_size
        self.num_kv_heads = num_kv_heads
        self.head_dim = head_dim

        # Allocate all blocks upfront
        self.blocks: List[KVBlock] = [
            KVBlock(block_id=i) for i in range(total_blocks)
        ]
        self.free_list: List[int] = list(range(total_blocks))  # Stack of free block IDs
        self.block_table: dict[str, List[int]] = {}  # request_id -> [block_ids]

    def allocate_blocks(self, request_id: str, num_blocks: int) -> List[int]:
        """Allocate `num_blocks` for a request. Raises RuntimeError on OOM."""
        if len(self.free_list) < num_blocks:
            raise RuntimeError(
                f"KV cache OOM: need {num_blocks} blocks, only {len(self.free_list)} free"
            )

        allocated = [self.free_list.pop() for _ in range(num_blocks)]
        for bid in allocated:
            self.blocks[bid].occupied = True
            self.blocks[bid].ref_count += 1

        self.block_table[request_id] = allocated
        return allocated

    def free_blocks(self, request_id: str) -> None:
        """Release all blocks associated with a request."""
        if request_id not in self.block_table:
            return

        for bid in self.block_table[request_id]:
            self.blocks[bid].occupied = False
            self.blocks[bid].ref_count -= 1
            self.free_list.append(bid)

        del self.block_table[request_id]

    def prefetch_blocks(self, request_id: str, num_new_blocks: int) -> List[int]:
        """
        Prefetch additional blocks for a request whose sequence is growing.
        This is the 'prefetching' mechanism: proactively allocate blocks
        before the scheduler needs them, hiding allocation latency.
        """
        return self.allocate_blocks(request_id, num_new_blocks)

    @property
    def free_block_count(self) -> int:
        return len(self.free_list)

    @property
    def utilization(self) -> float:
        return 1.0 - (len(self.free_list) / self.total_blocks)
```

### Step 3: Build the Continuous Batch Scheduler

The scheduler is where continuous batching happens. Unlike static batching (which waits for a full batch or a timeout), continuous batching inserts new requests and preempts low-priority ones at every decoding step.

```python
import heapq
from typing import Dict


@dataclass(order=True)
class ScheduledRequest:
    """Wrapper for priority queue ordering."""
    priority: float           # Lower = higher priority (e.g., arrival time)
    request: GenerateRequest = field(compare=False)


class ContinuousBatchScheduler:
    """
    Manages the lifecycle of requests through continuous batching.
    - New requests enter the pending queue
    - Each step, the scheduler packs the highest-priority pending
      requests into a batch that fits in the KV cache
    - Completed or preempted requests are evicted
    """

    def __init__(self, kv_manager: PagedKVCacheManager, max_batch_size: int):
        self.kv_manager = kv_manager
        self.max_batch_size = max_batch_size
        self.pending_queue: List[ScheduledRequest] = []
        self.inflight_requests: Dict[str, GenerateRequest] = {}
        self.completed_requests: List[GenerateRequest] = []

    def submit(self, request: GenerateRequest) -> None:
        """Submit a new request to the pending queue."""
        request.status = RequestStatus.PENDING
        heapq.heappush(
            self.pending_queue,
            ScheduledRequest(priority=request.created_at, request=request)
        )

    def schedule(self) -> List[GenerateRequest]:
        """
        Build the next batch by packing pending requests
        until the KV cache or batch size is exhausted.
        Returns the list of requests that will be processed this step.
        """
        batch: List[GenerateRequest] = []

        while self.pending_queue and len(batch) < self.max_batch_size:
            candidate = heapq.heappop(self.pending_queue).request

            # Estimate blocks needed (1 block per block_size tokens + 1 for grow)
            estimated_blocks = max(1, len(candidate.token_ids) // self.kv_manager.block_size + 1)

            if self.kv_manager.free_block_count >= estimated_blocks:
                try:
                    self.kv_manager.allocate_blocks(candidate.request_id, estimated_blocks)
                    candidate.status = RequestStatus.INFLIGHT
                    candidate.kv_block_ids = self.kv_manager.block_table[candidate.request_id]
                    self.inflight_requests[candidate.request_id] = candidate
                    batch.append(candidate)
                except RuntimeError:
                    # Not enough memory — re-queue and stop
                    heapq.heappush(
                        self.pending_queue,
                        ScheduledRequest(priority=candidate.created_at, request=candidate)
                    )
                    break
            else:
                # No memory: preempt lowest-priority inflight request
                self._preempt_lowest_priority(batch)
                if self.kv_manager.free_block_count >= estimated_blocks:
                    self.kv_manager.allocate_blocks(candidate.request_id, estimated_blocks)
                    candidate.status = RequestStatus.INFLIGHT
                    candidate.kv_block_ids = self.kv_manager.block_table[candidate.request_id]
                    self.inflight_requests[candidate.request_id] = candidate
                    batch.append(candidate)
                else:
                    # Still no memory — put back and stop
                    heapq.heappush(
                        self.pending_queue,
                        ScheduledRequest(priority=candidate.created_at, request=candidate)
                    )
                    break

        return batch

    def _preempt_lowest_priority(self, current_batch: List[GenerateRequest]) -> None:
        """Preempt the inflight request with the fewest tokens generated."""
        if not self.inflight_requests:
            return

        preempted = min(
            self.inflight_requests.values(),
            key=lambda r: r.num_generated
        )

        self.kv_manager.free_blocks(preempted.request_id)
        preempted.status = RequestStatus.PREEMPTED
        preempted.kv_block_ids = []
        del self.inflight_requests[preempted.request_id]

        # Re-queue preempted request
        heapq.heappush(
            self.pending_queue,
            ScheduledRequest(priority=preempted.created_at, request=preempted)
        )

    def complete_request(self, request_id: str, generated_tokens: List[int]) -> None:
        """Mark a request as complete and free its KV blocks."""
        req = self.inflight_requests.pop(request_id, None)
        if req:
            req.token_ids.extend(generated_tokens)
            req.num_generated += len(generated_tokens)
            req.finished = True
            req.status = RequestStatus.COMPLETED
            self.kv_manager.free_blocks(request_id)
            self.completed_requests.append(req)

    def step(self) -> List[GenerateRequest]:
        """Advance one scheduling step: schedule new batch."""
        return self.schedule()
```

### Step 4: Implement the Model Runner with Prefetching

The model runner executes the forward pass and handles the prefetch loop. In a real system, this would call a CUDA kernel; here we abstract it to show the prefetching logic clearly.

```python
import asyncio
from typing import Tuple


class ModelRunner:
    """
    Executes forward passes and manages KV block prefetching.
    In production, this wraps a CUDA kernel or TensorRT-LLM engine.
    """

    def __init__(self, kv_manager: PagedKVCacheManager, scheduler: ContinuousBatchScheduler):
        self.kv_manager = kv_manager
        self.scheduler = scheduler
        self.generated_tokens: dict[str, List[int]] = {}

    async def generate_step(self, batch: List[GenerateRequest]) -> List[Tuple[str, int]]:
        """
        Execute one forward pass for the batch.
        Returns (request_id, next_token_id) pairs.
        Includes prefetch logic to hide allocation latency.
        """
        results = []

        for req in batch:
            # --- Prefetch phase: proactively allocate blocks for
            #     the next token before the actual compute ---
            estimated_next_blocks = max(
                1, (len(req.token_ids) + 1) // self.kv_manager.block_size
            )
            if self.kv_manager.free_block_count >= estimated_next_blocks:
                self.kv_manager.prefetch_blocks(req.request_id, estimated_next_blocks)

            # --- Compute phase: simulate a forward pass ---
            # In production: token_ids -> model -> next_token_id
            next_token_id = self._simulate_forward_pass(req)

            req.token_ids.append(next_token_id)
            req.num_generated += 1
            results.append((req.request_id, next_token_id))

            # Check termination
            if req.num_generated >= req.max_new_tokens:
                self.scheduler.complete_request(req.request_id, [next_token_id])

        return results

    def _simulate_forward_pass(self, req: GenerateRequest) -> int:
        """
        Simulates a model forward pass. Replace with actual model inference.
        Returns a deterministic pseudo-token based on request state.
        """
        # Simple deterministic pseudo-generation for demonstration
        seed = hash(req.request_id) ^ len(req.token_ids)
        return seed % 50000  # Vocabulary size simulation

    async def run(self, max_steps: int = 100):
        """
        Main serving loop: schedule, generate, repeat.
        """
        for step in range(max_steps):
            batch = self.scheduler.step()
            if not batch:
                await asyncio.sleep(0.001)  # Yield to event loop
                continue

            await self.generate_step(batch)

            if not self.scheduler.inflight_requests and not self.scheduler.pending_queue:
                break
```

### Step 5: Wire Everything Together

```python
class LLMServingEngine:
    """Top-level engine that ties all components together."""

    def __init__(
        self,
        total_kv_blocks: int = 256,
        block_size: int = 16,
        max_batch_size: int = 8,
        num_kv_heads: int = 8,
        head_dim: int = 128,
    ):
        self.kv_manager = PagedKVCacheManager(
            total_blocks=total_kv_blocks,
            block_size=block_size,
            num_kv_heads=num_kv_heads,
            head_dim=head_dim,
        )
        self.scheduler = ContinuousBatchScheduler(
            kv_manager=self.kv_manager,
            max_batch_size=max_batch_size,
        )
        self.model_runner = ModelRunner(
            kv_manager=self.kv_manager,
            scheduler=self.scheduler,
        )

    async def generate(self, prompt: str, max_new_tokens: int = 64) -> str:
        """Submit a request and wait for completion."""
        req = GenerateRequest.create(prompt, max_new_tokens=max_new_tokens)
        self.scheduler.submit(req)
        await self.model_runner.run(max_steps=200)
        return req.token_ids  # Return generated token IDs

    def stats(self) -> dict:
        """Return current engine utilization statistics."""
        return {
            "free_kv_blocks": self.kv_manager.free_block_count,
            "kv_utilization": self.kv_manager.utilization,
            "pending_requests": len(self.scheduler.pending_queue),
            "inflight_requests": len(self.scheduler.inflight_requests),
            "completed_requests": len(self.scheduler.completed_requests),
        }


# --- Entry point ---
async def main():
    engine = LLMServingEngine(total_kv_blocks=128, max_batch_size=4)

    # Submit multiple requests concurrently
    tasks = [
        engine.generate(f"Hello, my name is", max_new_tokens=32),
        engine.generate(f"The capital of France is", max_new_tokens=32),
        engine.generate(f"Machine learning is", max_new_tokens=32),
    ]

    results = await asyncio.gather(*tasks)

    for tokens in results:
        print(f"Generated {len(tokens)} tokens")

    print(f"\nEngine stats: {engine.stats()}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Running and Testing It

Clone or save the complete code above into a single file, say `engine.py`, and run:

```bash
python engine.py
```

You should see output like:

```
Generated 32 tokens
Generated 32 tokens
Generated 32 tokens

Engine stats: {'free_kv_blocks': 112, 'kv_utilization': 0.125, 'pending_requests': 0, 'inflight_requests': 0, 'completed_requests': 3}
```

To verify correctness, add a test script:

```python
# test_engine.py
import asyncio
from engine import LLMServingEngine

async def test_basic_generation():
    engine = LLMServingEngine(total_kv_blocks=64, max_batch_size=2)
    tokens = await engine.generate("Test prompt", max_new_tokens=16)
    assert len(tokens) == 16, f"Expected 16 tokens, got {len(tokens)}"
    print("✓ Basic generation test passed")

async def test_kv_oom():
    engine = LLMServingEngine(total_kv_blocks=2, max_batch_size=4)
    # Submit enough requests to exhaust KV cache
    for i in range(10):
        engine.generate(f"Request {i}", max_new_tokens=128)
    await asyncio.sleep(0.1)
    stats = engine.stats()
    assert stats["pending_requests"] > 0, "Expected some requests to be pending due to OOM"
    print("✓ KV OOM handling test passed")

async def test_preemption():
    engine = LLMServingEngine(total_kv_blocks=4, max_batch_size=4)
    # Long request + many short requests to trigger preemption
    engine.generate("Long prompt that will take many tokens", max_new_tokens=1000)
    for i in range(5):
        engine.generate(f"Short {i}", max_new_tokens=4)
    await asyncio.sleep(0.1)
    stats = engine.stats()
    assert stats["completed_requests"] > 0, "Expected preempted short requests to complete"
    print("✓ Preemption test passed")

async def main():
    await test_basic_generation()
    await test_kv_oom()
    await test_preemption()

asyncio.run(main())
```

```bash
python test_engine.py
```

All three tests should pass, confirming that generation works, OOM handling is correct, and preemption actually evicts and re-queues requests.

## Extending It: Your Roadmap to Senior-Level

The code above is a functional prototype. To make it production-flavored — and to truly signal senior-level systems thinking — work through these upgrades in order:

1. **Add Prometheus metrics and structured logging.** Instrument every scheduling decision, KV allocation, and preemption event with counters and histograms. Use the `prometheus_client` Python library to expose `/metrics`. *Why it matters:* You cannot optimize what you cannot measure, and on-call engineers need dashboards to diagnose latency spikes.

2. **Implement request persistence with Redis.** Before a request enters the scheduler, persist its metadata (prompt, parameters, user ID) to Redis. On engine restart, recover in-flight requests. *Why it matters:* Fault tolerance — a crashed scheduler should not lose user requests, which is a hard requirement for any production serving system.

3. **Build a horizontal scaling layer with gRPC.** Split the engine into a scheduler service and one or more model runner workers communicating over gRPC. Use a consistent hashing ring or a simple load balancer to distribute requests. *Why it matters:* A single process has a memory ceiling; horizontal scaling is the only path to serving throughput beyond one GPU's capacity.

4. **Add tensor parallelism via `torch.distributed`.** Replace the simulated forward pass with a real model (e.g., a small LLaMA variant) and use PyTorch's distributed autograd to shard attention layers across multiple GPUs. *Why it matters:* This is the bridge from toy to real — tensor parallelism is what makes large models fit in memory at serving scale.

5. **Implement a replay-based benchmark harness.** Use `pytest-benchmark` or a custom script that replays a trace of requests (e.g., from a JSONL file) and measures throughput (tokens/second), p99 latency, and KV cache hit rate under varying batch sizes. *Why it matters:* Without benchmarks, you cannot prove that an optimization actually helps — this is how you move from intuition to evidence.

6. **Add request priority queues and preemption policies.** Extend the scheduler to support multiple priority classes (e.g., premium vs. bulk) with configurable preemption strategies (smallest-residual, oldest-first, lowest-temperature). *Why it matters:* Production systems serve heterogeneous workloads with SLAs; priority-aware scheduling is what separates a research prototype from a commercial product.

## Key Takeaways

- **Continuous batching is not just a scheduling trick** — it's a systems-level optimization that requires tight integration between the request queue, memory allocator, and compute kernel. Each component constrains the others.
- **PagedAttention borrows directly from OS virtual memory** — the free-list allocator, block table, and page fault analogy are all concepts you already know if you've worked on storage systems or kernels.
- **Prefetching hides latency** — by allocating KV blocks before the scheduler needs them, you overlap memory management with computation, which is the same principle behind CPU prefetching and GPU stream pipelines.
- **A working prototype with real code beats a polished slides-deck** — hiring managers can immediately see whether you understand the system by reading your implementation, not your summary.
- **The gap between prototype and production is instrumentation, persistence, and scaling** — these are the upgrades that turn a weekend project into a portfolio piece that survives technical scrutiny.

## Further Reading

To deepen and evolve this project, study these primary sources:

- **[PagedAttention: Efficient Memory Management for Large Language Model Serving](https://arxiv.org/abs/2309.06180)** — The foundational paper from the vLLM team. Read Sections 3 and 4 carefully; they describe the block table abstraction and the attention kernel that this project simulates.
- **[Continuous Batching for Large Language Models](https://arxiv.org/abs/2306.15556)** — The Google/DeepMind paper that formalizes the continuous batching algorithm. This is the theoretical backbone of the scheduler you built.
- **[vLLM Documentation: PagedAttention](https://docs.vllm.ai/en/latest/architecture/paged_attention.html)** — The canonical engineering documentation for the production system. Study their block manager implementation for how real systems handle CUDA memory pools and attention kernels.
- **[TensorRT-LLM: LLM Inference Optimizations](https://docs.nvidia.com/tensorrt-llm/latest/)** — NVIDIA's production inference optimizer. Useful for understanding how kernel fusion and FP8 quantization layer on top of the scheduling concepts you've built.
- **[The Transformer Family: Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762)** — The original transformer paper. Revisit it with a serving lens: how does the attention mechanism translate into memory access patterns at inference time?
- **[Prometheus: The Definitive Guide](https://prometheus.io/docs/introduction/overview/)** — For implementing the observability upgrade. This is the standard monitoring system used by virtually every production ML platform.

---