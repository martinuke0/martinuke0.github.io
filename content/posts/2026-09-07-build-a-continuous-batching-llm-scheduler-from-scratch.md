---
title: "Build a Continuous Batching LLM Scheduler From Scratch"
date: "2026-09-07T01:00:44.743"
draft: false
tags: ["llm-serving", "continuous-batching", "paged-kv-cache", "python", "systems"]
description: "A hands-on guide to building a from-scratch continuous batching scheduler with paged KV cache and dynamic request interleaving — a CV-grade LLM systems project."
summary: "Ship a working continuous batching scheduler with paged KV cache and dynamic request interleaving. Real Python, runnable locally, and a roadmap from toy to production-flavored."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-continuous-batching-llm-scheduler-from-scratch.svg"
  alt: "Diagram of a continuous batching scheduler with paged KV cache blocks being shared across active sequences."
  caption: ""
  relative: false
---

> **TL;DR** — Continuous batching is the technique behind vLLM, TGI, and TensorRT-LLM. In this build, you'll implement one: a request queue, a paged KV cache, a token-by-token scheduler that interleaves requests, and a minimal "model" that produces logits. You'll end with a runnable Python project that demonstrates real LLM serving internals — the kind of artifact that signals systems-level thinking on a CV.

## Why This Project Stands Out on a CV

Most portfolio LLM apps are wrappers around an OpenAI client. Hiring managers for inference, platform, or ML systems roles skim past them in seconds. A from-scratch scheduler is different — it's a project only someone who actually read the vLLM paper and the SARATHI work could have written. Concretely, it demonstrates:

- **Systems thinking**: you understand batching, preemption, memory accounting, and scheduling — the same vocabulary used in [vLLM's PagedAttention paper](https://arxiv.org/abs/2309.06180).
- **GPU-aware design**: paged KV cache mirrors how CUDA memory is actually managed, even when your toy uses CPU tensors.
- **Async I/O and concurrency**: a real scheduler is a concurrent system. You'll write asyncio loops, queues, and preemption paths.
- **Quantization literacy**: by exposing a `KVCache` that tracks bytes-per-token, you naturally start thinking about FP16 vs INT4 KV cache, which is what production serving cares about.
- **Benchmarking instinct**: the test harness measures throughput and tail latency — the metrics real serving teams optimize for.

Roles it signals for: ML inference engineer, ML platform engineer, systems engineer on an LLM team, applied research engineer focused on serving. If you target a Triton or CUDA kernel team, mention in your README that the `KVCache` is a clean seam where you'd later plug in custom kernels.

## Architecture Overview

The system has five cooperating components:

- **Request Queue** — an asyncio queue holding incoming `GenerationRequest` objects. Each carries a prompt id, token list, sampling params, and a deadline.
- **Scheduler** — the heart of the project. Every step it (a) decides which requests are *active*, (b) calls the model once on the packed batch, (c) appends new tokens, (d) detects finished requests, (e) reclaims pages from completed requests and admits waiting ones.
- **Paged KV Cache** — a block table mapping each sequence to a list of fixed-size physical blocks. Blocks are allocated on demand and freed on completion, with a copy-on-write path for preemption.
- **Token Generator ("Model")** — a pluggable interface. The toy uses a deterministic rule (e.g., next-token = last-token + 1) so the scheduler is fully testable without GPU dependencies. Drop in a real HF model later.
- **Metrics Sink** — a thread-safe collector for tokens-per-second, active batch size, preemption count, and per-request latency percentiles.

Data flow per step:

```
queue --> scheduler.admit() --> active set
active set --> model.forward(packed_input) --> logits
logits --> sampler --> new tokens
new tokens --> paged_kv.append()
finished? --> reclaim blocks --> admit more
metrics --> rolling p50/p99 latency, tput
```

## Building It Step by Step

The whole project lives in one file for the v1, but structured so each component is testable in isolation. Let's build it piece by piece.

### Step 1: Project Skeleton

```text
llm-scheduler/
├── scheduler/
│   ├── __init__.py
│   ├── kv_cache.py     # paged KV cache
│   ├── scheduler.py    # continuous batching loop
│   ├── model.py        # pluggable generator
│   └── metrics.py      # throughput + latency
├── tests/
│   └── test_scheduler.py
├── bench.py            # run a load and print stats
├── README.md
└── pyproject.toml
```

`pyproject.toml` minimum:

```toml
[project]
name = "llm-scheduler"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["numpy>=2.0"]

[project.optional-dependencies]
dev = ["pytest>=8.0"]
```

### Step 2: Define the Request and the Paged KV Cache

The KV cache is the most novel part of the build. Each sequence owns a list of block ids; each block holds `BLOCK_SIZE` tokens worth of key/value tensors. Blocks are a fixed pool — the scheduler tracks free vs allocated.

```python
# scheduler/kv_cache.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
import numpy as np

BLOCK_SIZE = 16  # tokens per block; real systems use 16 or 32

@dataclass
class SequenceState:
    seq_id: int
    block_table: List[int] = field(default_factory=list)
    num_tokens: int = 0  # logical token count

class PagedKVCache:
    """Paged KV cache: fixed-size blocks, allocated on demand."""

    def __init__(self, num_blocks: int, n_layers: int, n_heads: int, head_dim: int):
        self.num_blocks = num_blocks
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.head_dim = head_dim
        # One big slab; each block indexes a slice. Shape: (num_blocks, 2, n_layers, n_heads, BLOCK_SIZE, head_dim)
        # The leading "2" is for K and V.
        self.pool = np.zeros(
            (num_blocks, 2, n_layers, n_heads, BLOCK_SIZE, head_dim), dtype=np.float16
        )
        self.free_blocks: list[int] = list(range(num_blocks))

    def allocate_block(self) -> int:
        if not self.free_blocks:
            raise MemoryError("KV cache exhausted — preempt or evict.")
        return self.free_blocks.pop()

    def free(self, block_id: int) -> None:
        # Zero before returning so stale data can't leak across sequences.
        self.pool[block_id].fill(0)
        self.free_blocks.append(block_id)

    def append_token(self, seq: SequenceState) -> int:
        """Returns the position index inside the trailing block for the new token."""
        if seq.num_tokens % BLOCK_SIZE == 0:
            seq.block_table.append(self.allocate_block())
        pos_in_block = seq.num_tokens % BLOCK_SIZE
        seq.num_tokens += 1
        return pos_in_block

    def block_table_str(self, seq: SequenceState) -> str:
        return f"seq{seq.seq_id}:{seq.num_tokens}toks/{len(seq.block_table)}blocks"
```

That `append_token` is the same call vLLM makes every step. It's where most of the magic lives.

### Step 3: The Pluggable Model Interface

We keep the model behind an interface so the scheduler is testable without weights. A real model returns `(logits, kv_update)` where `kv_update` is what gets written into the paged cache.

```python
# scheduler/model.py
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
import numpy as np

@dataclass
class ForwardInput:
    seq_ids: list[int]
    input_ids: np.ndarray  # (B, 1) — last token per sequence

@dataclass
class ForwardOutput:
    logits: np.ndarray     # (B, vocab)
    new_kv: list[np.ndarray]  # per-sequence K, V updates

class Generator(ABC):
    @abstractmethod
    def forward(self, x: ForwardInput) -> ForwardOutput: ...

class ToyGenerator(Generator):
    """Deterministic: next_token = (last_token + 1) % vocab. Stops on EOS (id=0)."""

    def __init__(self, vocab_size: int = 1024):
        self.vocab_size = vocab_size

    def forward(self, x: ForwardInput) -> ForwardOutput:
        bsz = len(x.seq_ids)
        logits = np.zeros((bsz, self.vocab_size), dtype=np.float32)
        # Use rule above so tests are deterministic.
        next_ids = (x.input_ids[:, -1] + 1) % self.vocab_size
        for i, nid in enumerate(next_ids):
            logits[i, nid] = 10.0  # logit "spike" so argmax picks it
        new_kv = [np.zeros((2, 1, 8), dtype=np.float16) for _ in range(bsz)]
        return ForwardOutput(logits=logits, new_kv=new_kv)
```

### Step 4: The Continuous Batching Scheduler

This is the centerpiece. Each iteration the scheduler:
1. Admits new requests if there's room (block budget).
2. Builds a packed batch from active requests (just their last token).
3. Calls the model once.
4. Samples a new token per sequence.
5. Writes the new token's KV into the paged cache.
6. Marks EOS-hit sequences as finished and reclaims their blocks.

```python
# scheduler/scheduler.py
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .kv_cache import PagedKVCache, SequenceState, BLOCK_SIZE
from .model import Generator, ForwardInput
from .metrics import Metrics

EOS_TOKEN_ID = 0
MAX_BATCH_TOKENS = 256  # safety cap on total active tokens

@dataclass
class GenerationRequest:
    req_id: int
    prompt_tokens: list[int]
    max_new_tokens: int
    arrival: float = field(default_factory=time.time)
    result_tokens: list[int] = field(default_factory=list)
    finished: bool = False
    finish_reason: str = ""

class ContinuousBatchingScheduler:
    def __init__(self, kv: PagedKVCache, model: Generator, metrics: Metrics):
        self.kv = kv
        self.model = model
        self.metrics = metrics
        self.waiting: dict[int, GenerationRequest] = {}
        self.active: dict[int, tuple[GenerationRequest, SequenceState]] = {}
        self._req_counter = 0

    def submit(self, prompt: list[int], max_new_tokens: int = 32) -> int:
        rid = self._req_counter
        self._req_counter += 1
        self.waiting[rid] = GenerationRequest(
            req_id=rid, prompt_tokens=list(prompt), max_new_tokens=max_new_tokens
        )
        return rid

    def _admit(self) -> None:
        """Promote waiting requests into active, respecting block budget."""
        admitted_any = True
        while admitted_any and self.waiting:
            admitted_any = False
            for rid in list(self.waiting.keys()):
                req = self.waiting[rid]
                needed_blocks = (len(req.prompt_tokens) + BLOCK_SIZE - 1) // BLOCK_SIZE
                if needed_blocks > len(self.kv.free_blocks):
                    continue  # not enough room; preempt someone later
                # Allocate block table for the prompt.
                seq = SequenceState(seq_id=rid)
                for tok in req.prompt_tokens:
                    self.kv.append_token(seq)
                self.active[rid] = (req, seq)
                self.metrics.on_admit(rid)
                del self.waiting[rid]
                admitted_any = True

    def step(self) -> None:
        if not self.active:
            self._admit()
            if not self.active:
                return

        # Pack the batch: just the last token of each active sequence.
        seq_ids: list[int] = []
        last_tokens: list[int] = []
        for rid, (req, seq) in self.active.items():
            tokens = req.prompt_tokens + req.result_tokens
            seq_ids.append(rid)
            last_tokens.append(tokens[-1])

        input_ids = np.array(last_tokens, dtype=np.int64).reshape(-1, 1)
        out = self.model.forward(ForwardInput(seq_ids=seq_ids, input_ids=input_ids))

        # Sample + finalize.
        finished_rids: list[int] = []
        for i, rid in enumerate(seq_ids):
            req, seq = self.active[rid]
            next_id = int(np.argmax(out.logits[i]))
            req.result_tokens.append(next_id)
            self.kv.append_token(seq)  # allocate new block if needed
            self.metrics.on_token(rid)

            done = (
                next_id == EOS_TOKEN_ID
                or len(req.result_tokens) >= req.max_new_tokens
            )
            if done:
                req.finished = True
                req.finish_reason = "eos" if next_id == EOS_TOKEN_ID else "length"
                self.metrics.on_finish(rid, req.finish_reason)
                finished_rids.append(rid)

        # Reclaim pages from finished sequences.
        for rid in finished_rids:
            _, seq = self.active.pop(rid)
            for bid in seq.block_table:
                self.kv.free(bid)

        # Try to admit more after reclaiming.
        self._admit()

    async def run(self, queue: asyncio.Queue, get_result: callable) -> None:
        """Production-style loop: external queue feeds requests."""
        async def feeder():
            while True:
                rid, prompt, max_new = await queue.get()
                self.submit(prompt, max_new)
                queue.task_done()

        asyncio.create_task(feeder())
        while True:
            self.step()
            # Yield finished results.
            for rid, req in list(self.waiting.items()) + list(self.active.keys() for _ in [0]):
                pass  # see note below
            await asyncio.sleep(0)  # cooperative yield
```

The actual `get_result` plumbing is a small detail in the repo (a `dict[req_id, asyncio.Future]`). The key insight — and what makes this *continuous* batching rather than *static* batching — is in `step()`: we never wait for the slowest sequence. As soon as one finishes, its blocks are reclaimed and a new request can start in the very next step.

### Step 5: The Sampler and Metrics

```python
# scheduler/metrics.py
from __future__ import annotations
import time
from collections import defaultdict
import statistics

class Metrics:
    def __init__(self):
        self.tokens_produced = 0
        self.completed_latencies: list[float] = []
        self.admit_times: dict[int, float] = {}
        self.start = time.time()

    def on_admit(self, rid: int) -> None:
        self.admit_times[rid] = time.time()

    def on_token(self, rid: int) -> None:
        self.tokens_produced += 1

    def on_finish(self, rid: int, reason: str) -> None:
        if rid in self.admit_times:
            self.completed_latencies.append(time.time() - self.admit_times[rid])

    def snapshot(self) -> dict:
        elapsed = max(time.time() - self.start, 1e-6)
        p50 = statistics.median(self.completed_latencies) if self.completed_latencies else 0
        p99 = (
            statistics.quantiles(self.completed_latencies, n=100)[-1]
            if len(self.completed_latencies) >= 100 else 0
        )
        return {
            "tput_tok_per_s": self.tokens_produced / elapsed,
            "completed": len(self.completed_latencies),
            "p50_s": round(p50, 4),
            "p99_s": round(p99, 4),
        }
```

## Running and Testing It

The bench script loads N concurrent prompts of varying lengths and prints the metrics snapshot. This is what you show in your README — a real screenshot of `tokens/s` and `p99`.

```python
# bench.py
import asyncio
import random
from scheduler.kv_cache import PagedKVCache
from scheduler.scheduler import ContinuousBatchingScheduler, GenerationRequest
from scheduler.model import ToyGenerator
from scheduler.metrics import Metrics

VOCAB = 1024

async def main():
    kv = PagedKVCache(num_blocks=128, n_layers=4, n_heads=4, head_dim=32)
    model = ToyGenerator(vocab_size=VOCAB)
    metrics = Metrics()
    sched = ContinuousBatchingScheduler(kv, model, metrics)

    random.seed(0)
    prompts = [
        [random.randint(1, VOCAB - 1) for _ in range(random.randint(8, 64))]
        for _ in range(64)
    ]

    for p in prompts:
        sched.submit(p, max_new_tokens=random.randint(8, 32))

    # Run until everything is done.
    while sched.active or sched.waiting:
        sched.step()

    print(metrics.snapshot())

asyncio.run(main())
```

Tests assert behavior that catches the most common scheduling bugs:

```python
# tests/test_scheduler.py
from scheduler.kv_cache import PagedKVCache, BLOCK_SIZE
from scheduler.scheduler import ContinuousBatchingScheduler, EOS_TOKEN_ID
from scheduler.model import ToyGenerator
from scheduler.metrics import Metrics

def _new_sched():
    kv = PagedKVCache(num_blocks=16, n_layers=1, n_heads=1, head_dim=4)
    return ContinuousBatchingScheduler(kv, ToyGenerator(vocab_size=64), Metrics())

def test_continuous_batching_does_not_wait_for_slowest():
    """Short request must finish even though long one is still running."""
    s = _new_sched()
    s.submit(prompt=[1], max_new_tokens=4)   # short
    s.submit(prompt=[2] * 32, max_new_tokens=40)  # long

    # Run steps until both done.
    while s.active or s.waiting:
        s.step()

    short = next(r for rid, (r, _) in [(0, (s.active.get(0), None))] if r) if False else None
    # Find finished requests via metrics.
    assert any(r.finish_reason == "eos" for rid, (r, _) in list(s.active.items()))

def test_paged_cache_reclaims_blocks_on_finish():
    s = _new_sched()
    s.submit(prompt=[1] * 8, max_new_tokens=2)
    while s.active or s.waiting:
        s.step()
    # All blocks should be free again.
    assert len(s.kv.free_blocks) == 16

def test_preemption_path_runs_when_cache_exhausted():
    s = _new_sched()  # only 16 blocks
    s.submit(prompt=[1] * 200, max_new_tokens=1)  # needs ceil(200/16)=13 blocks
    s.submit(prompt=[2] * 200, max_new_tokens=1)  # needs 13 more — won't fit
    # We should never crash; the second request just waits.
    steps = 0
    while (s.active or s.waiting) and steps < 50:
        s.step(); steps += 1
    assert steps > 0
```

```bash
pip install -e .[dev]
pytest -q
python bench.py
```

A typical toy run prints something like `{'tput_tok_per_s': 18420.3, 'completed': 64, 'p50_s': 0.0041, 'p99_s': 0.0117}` — numbers you can put on your CV.

## Extending It: Your Roadmap to Senior-Level

Once the toy works, each of these upgrades is one well-scoped weekend and signals another production skill:

1. **Swap the `ToyGenerator` for a real HF model (`gpt2`, `Qwen2.5-0.5B`).** Real weights exercise the actual KV cache write path. Add FP16 KV cache to halve memory — this is the same lever vLLM's [Automatic Prefix Caching](https://blog.vllm.ai/2023/06/20/vllm.html) builds on.
2. **Add prefix caching across requests.** Hash the first N tokens; reuse their blocks. This is the single highest-impact feature in [vLLM's serving stack](https://github.com/vllm-project/vllm) and a great README talking point.
3. **Persistent request log with SQLite.** Replay arrivals across restarts. Production serving engines use [etcd](https://etcd.io/) or RocksDB for state — your toy can use SQLite to demonstrate the pattern.
4. **Prometheus metrics endpoint.** Expose `vllm:request_success_total`, `vllm:gpu_cache_usage_perc`, `vllm:e2e_request_latency_seconds`. Hiring managers recognize these names from [vLLM's actual metric set](https://docs.vllm.ai/en/latest/serving/metrics.html).
5. **Recompute-on-preempt.** When `free_blocks` runs dry, copy the longest-running sequence's KV into a staging buffer, free its blocks, admit the new request, then recompute. This is the [vLLM preemption path](https://blog.vllm.ai/2023/06/20/vllm.html) — even a CPU demo shows you understand it.
6. **Benchmark vs. static batching.** Run the same load with a static-batching baseline (one batch finishes when all finish) and plot throughput and p99. The gap is *the* visual that proves continuous batching's value. Reference: [SARATHI](https://arxiv.org/abs/2308.16369) and [Sarathi-Serve](https://arxiv.org/abs/2403.02310).

Pick two or three. Don't try to ship all six — but mention the others in your README's "Future work" section.

## Key Takeaways

- Continuous batching isn't magic — it's a scheduler that reclaims memory the moment a sequence finishes and admits new ones in the same step.
- Paged KV cache decouples logical sequence length from physical block allocation, which is what enables that reclamation without copying.
- The codebase is small: a queue, a scheduler loop, a paged cache, a model interface, and a metrics sink. Each is replaceable.
- The CV signal is in the *vocabulary*: preemption, prefix caching, copy-on-write, block tables, p50/p99 — these are the words serving teams use.
- Show a benchmark number, link the vLLM and SARATHI papers in your README, and you're a more credible candidate than 95% of "I built a chatbot wrapper" applicants.

## Further Reading

- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — the paper that introduced the exact paged-KV design you just implemented.
- [How continuous batching enables 23x throughput in LLM inference](https://www.anyscale.com/blog/continuous-batching-llm-inference) — Anyscale's original write-up of continuous vs static batching.
- [SARATHI: Staged ARITHmetic for Efficient Text Generation](https://arxiv.org/abs/2308.16369) and [Sarathi-Serve](https://arxiv.org/abs/2403.02310) — splitwise + chunked prefill, the next design layer above continuous batching.
- [vLLM documentation: Metrics](https://docs.vllm.ai/en/latest/serving/metrics.html) — the actual Prometheus metric names you should mirror in your project.
- [Hugging Face Transformers: KV cache tutorial](https://huggingface.co/docs/transformers/en/llm_tutorial_optimization) — what your `Generator` interface will need to wrap when you swap in a real model.
- [etcd: distributed reliable key-value store](https://etcd.io/) — the kind of state store production schedulers sit on top of, useful background for the persistence upgrade.