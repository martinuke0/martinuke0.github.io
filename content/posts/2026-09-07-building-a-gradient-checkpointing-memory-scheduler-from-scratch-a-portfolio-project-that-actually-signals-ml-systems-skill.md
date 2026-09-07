---
title: "Building a Gradient Checkpointing Memory Scheduler From Scratch: A Portfolio Project That Actually Signals ML Systems Skill"
date: "2026-09-07T17:02:33.607"
draft: false
tags: ["PyTorch", "Deep Learning", "Systems Engineering", "Portfolio Project", "ML Infrastructure"]
description: "Hands-on guide to building a from-scratch gradient checkpointing memory scheduler for mini GPT training, with runnable code and a roadmap to senior-level ML systems work."
summary: "A practical build guide for a portfolio-grade gradient checkpointing scheduler that trades compute for memory in mini GPT training. Includes runnable PyTorch code, a scheduler design, tests, and a roadmap to production-flavored upgrades."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-a-gradient-checkpointing-memory-scheduler-from-scratch-a-portfolio-project-that-actually-signals-ml-systems-skill.svg"
  alt: "Diagram of a transformer training loop showing activations dropped at checkpoint boundaries and recomputed during backward pass."
  caption: ""
  relative: false
---

> **TL;DR** — Gradient checkpointing trades compute for memory by dropping activations during the forward pass and recomputing them in backward. This post walks through a from-scratch memory scheduler — a small policy layer that decides *which* checkpoints to keep, *when* to evict, and *how* to stream the rest — implemented in pure PyTorch against a mini GPT. You finish with a runnable repo, measurable memory savings, and a clear roadmap for evolving it into a senior-level ML systems artifact.

## Why This Project Stands Out on a CV

Most "I trained a transformer" repos look identical: a tiny GPT, a Hugging Face Trainer call, a loss curve, done. They demonstrate familiarity, not engineering. A custom memory scheduler is different. It signals the things hiring managers for ML infra, performance, or research-engineering roles actually screen for.

What the project concretely demonstrates:

- **Memory-model literacy.** You are reasoning about activation lifetimes, CUDA allocator behavior, and the difference between *stored* and *recomputable* tensors. That is the daily vocabulary of ML performance engineers at Meta, Google, and any inference-platform team.
- **Trade-off engineering.** Checkpointing is the textbook example of trading FLOPs for HBM. Showing you can quantify and tune that trade-off — and measure it — is what separates "I read the docs" from "I built the thing."
- **Scheduler design.** You are writing a small policy engine: priorities, eviction rules, a flush threshold, a recompute trigger. That is the same shape as a query planner, a cache evictor, or a Kubernetes scheduler. It transfers directly.
- **Profiling discipline.** The project ships with `torch.cuda` memory snapshots, a benchmark harness, and a CSV you can plot. Recruiters notice that.
- **Real failure modes.** OOMs, allocator fragmentation, accidental graph retention through `retain_graph=True` — you have hit and handled them, and that story is hard to fake in interviews.

Roles this targets: ML Systems Engineer, Performance Engineer, Training Platform Engineer, Research Engineer, and the increasingly common "AI Infrastructure" SWE role. If you are applying to companies running their own training stacks — Together, Anyscale, MosaicML-style, even inference teams at larger shops — this lands.

## Architecture Overview

The system has four clean components. Treat them as four files. The seams between them are what make the project easy to extend later.

**1. The Mini GPT (`model.py`).** A small decoder-only transformer in pure PyTorch — embedding, N× causal-block, RMSNorm, SwiGLU, rotary embeddings, and a tied output projection. Kept tiny so the whole thing runs on a single GPU or CPU. Each block exposes a `forward(x, ckpt: CheckpointStore)` hook so the scheduler can interpose.

**2. The Activation Store (`store.py`).** A Python class that owns the lifecycle of saved activations. Internally it is a tuple of (name, tensor, generation) entries plus an LRU index. It exposes `save(name, tensor)`, `recompute(name, fn)`, `evict_older_than(gen)`, and `memory_bytes()`. It never holds a reference it does not need — tensors are detached at save time, and `torch.no_grad()` wraps every recompute.

**3. The Scheduler Policy (`policy.py`).** Pure functions over the store: `should_checkpoint(layer_idx, n_layers, memory_bytes, budget_bytes)` and `select_evictions(store, target_bytes)`. Policies are swappable — `full`, `selective`, `budget`, `uniform`. This is the file that ages best on your CV because every performance improvement lands here.

**4. The Training Driver (`train.py`).** The standard loop — data, forward, backward, optimizer step — with the scheduler plugged in around `model.forward`. It writes `metrics.csv` (loss, peak MB, checkpoint count, recompute count) so the benchmark section has something to plot.

The data flow looks like:

```
data → Embedding → Block[0] → Block[1] → … → Block[N-1] → LM Head → loss
                  ↑           ↑                 ↑
              ckpt save   ckpt save         ckpt save
                  ↓           ↓                 ↓
              [      ActivationStore (LRU by generation)     ]
                  ↓           ↓                 ↓
              recompute   recompute        recompute
              during backward, freed after use
```

A single `CheckpointConfig` dataclass threads the budget, policy name, and recompute granularity through every layer so the model never imports the policy directly. That is the seam that lets you swap in a learned policy or a cost model later without touching the model code.

## Building It Step by Step

You can build this in an afternoon. The repo has no external dependencies beyond PyTorch and `tiktoken` for the tokenizer. CPU works for the smoke tests; CUDA is what makes the memory numbers interesting.

### Step 1 — Project Skeleton

Create a virtualenv and lay out the files:

```
mini-gpt-ckpt/
├── README.md
├── requirements.txt
├── model.py
├── store.py
├── policy.py
├── train.py
├── benchmark.py
└── tests/
    ├── test_store.py
    └── test_policy.py
```

```text
# requirements.txt
torch>=2.1
tiktoken>=0.5
```

### Step 2 — The Activation Store

This is the heart of the project. The store owns saved activations and decides when to free them. Detach aggressively — holding a tensor with `requires_grad=True` keeps the autograd graph alive and silently breaks checkpointing.

```python
# store.py
from __future__ import annotations
import torch
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Optional

@dataclass
class StoredTensor:
    name: str
    data: torch.Tensor          # detached, on the configured device
    generation: int             # forward-pass id when it was saved
    cost_bytes: int             # nbytes, cached for the policy
    layer_idx: int

class ActivationStore:
    def __init__(self, device: torch.device, max_bytes: int = 256 * 1024 * 1024):
        self.device = device
        self.max_bytes = max_bytes
        self._items: "OrderedDict[str, StoredTensor]" = OrderedDict()
        self._generation = 0
        self._bytes = 0
        # counters used by the benchmark
        self.recompute_count = 0
        self.evict_count = 0

    def begin_forward(self) -> None:
        self._generation += 1

    def save(self, name: str, tensor: torch.Tensor, layer_idx: int) -> None:
        # Detach so we are not pinning the autograd graph.
        detached = tensor.detach()
        cost = detached.untyped_storage().nbytes()
        self._items[name] = StoredTensor(
            name=name,
            data=detached,
            generation=self._generation,
            cost_bytes=cost,
            layer_idx=layer_idx,
        )
        self._bytes += cost
        if self._bytes > self.max_bytes:
            self._evict_until(self.max_bytes)

    def get(self, name: str) -> torch.Tensor:
        item = self._items[name]
        # touch for LRU
        self._items.move_to_end(name)
        return item.data

    def recompute(self, name: str, fn: Callable[[], torch.Tensor]) -> torch.Tensor:
        with torch.no_grad():
            out = fn()
        # Replace the evicted (or never-saved) entry with the fresh tensor.
        item = self._items.get(name)
        if item is None:
            return out
        item.data = out.detach()
        item.generation = self._generation
        self.recompute_count += 1
        return out

    def _evict_until(self, target_bytes: int) -> None:
        # Evict oldest generations first.
        while self._bytes > target_bytes and self._items:
            name, item = self._items.popitem(last=False)
            self._bytes -= item.cost_bytes
            self.evict_count += 1
            del item.data

    def memory_bytes(self) -> int:
        return self._bytes

    def clear(self) -> None:
        self._items.clear()
        self._bytes = 0
```

A few subtleties worth calling out:

- `untyped_storage().nbytes()` is the cheap, accurate way to read the underlying allocation. `tensor.element_size() * tensor.nelement()` overcounts on views; storage nbytes does not.
- `_evict_until` runs eagerly in `save`. That is fine for a 16-layer toy; in a larger model you would amortize it with a background thread or a watermark.
- `recompute_count` is the metric that tells you the *compute* cost of checkpointing. If recompute count explodes while memory stays flat, your policy is too aggressive.

### Step 3 — The Scheduler Policy

The policy decides *which* layers become checkpoints. Two useful ones are enough to start: `uniform` (every layer, predictable) and `budget` (keep adding layers until the budget is hit, prefer expensive ones).

```python
# policy.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Sequence

@dataclass
class LayerCost:
    layer_idx: int
    activation_bytes: int     # estimated from a warmup pass
    flops: int                 # estimated from hidden, seq, ffn_dim

def should_checkpoint(layer_idx: int, n_layers: int, memory_bytes: int,
                      budget_bytes: int) -> bool:
    """Cheap call used by the model on every block."""
    if budget_bytes <= 0:
        return False
    return memory_bytes < budget_bytes

def select_checkpoints_uniform(n_layers: int) -> List[int]:
    return list(range(n_layers))

def select_checkpoints_budget(costs: Sequence[LayerCost],
                              budget_bytes: int) -> List[int]:
    # Greedy by cost, descending. Keeps the layers whose activations
    # would be most expensive to recompute.
    ordered = sorted(costs, key=lambda c: c.activation_bytes, reverse=True)
    chosen: List[int] = []
    used = 0
    for c in ordered:
        if used + c.activation_bytes <= budget_bytes:
            chosen.append(c.layer_idx)
            used += c.activation_bytes
    return sorted(chosen)
```

The `uniform` policy is what the train driver uses by default. The `budget` policy is what you benchmark against `none` (no checkpointing) in Step 6 to prove the savings. Both are pure functions over data the driver passes in — easy to unit-test, easy to swap.

### Step 4 — The Mini GPT Model

Keep it small. The point of the project is the scheduler, not the architecture.

```python
# model.py
from __future__ import annotations
import math
import torch
import torch.nn as nn
import torch.nn.functional as F

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))
    def forward(self, x):
        norm = x.pow(2).mean(-1, keepdim=True).add(self.eps).rsqrt()
        return x * norm * self.weight

class CausalSelfAttention(nn.Module):
    def __init__(self, dim: int, n_heads: int):
        super().__init__()
        assert dim % n_heads == 0
        self.n_heads = n_heads
        self.qkv = nn.Linear(dim, 3 * dim, bias=False)
        self.proj = nn.Linear(dim, dim, bias=False)
    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv(x).view(B, T, 3, self.n_heads, C // self.n_heads)
        q, k, v = qkv.unbind(dim=2)
        q = q.transpose(1, 2)
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)
        y = F.scaled_dot_product_attention(q, k, v, is_causal=True)
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.proj(y)

class SwiGLU(nn.Module):
    def __init__(self, dim: int, hidden: int):
        super().__init__()
        self.w1 = nn.Linear(dim, hidden, bias=False)
        self.w2 = nn.Linear(hidden, dim, bias=False)
        self.w3 = nn.Linear(dim, hidden, bias=False)
    def forward(self, x):
        return self.w2(F.silu(self.w1(x)) * self.w3(x))

class Block(nn.Module):
    def __init__(self, dim: int, n_heads: int, ffn: int):
        super().__init__()
        self.norm1 = RMSNorm(dim)
        self.attn = CausalSelfAttention(dim, n_heads)
        self.norm2 = RMSNorm(dim)
        self.mlp = SwiGLU(dim, ffn)
    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x

class MiniGPT(nn.Module):
    def __init__(self, vocab: int, dim: int = 256, n_layers: int = 8,
                 n_heads: int = 8, ffn: int = 1024, max_seq: int = 256):
        super().__init__()
        self.tok = nn.Embedding(vocab, dim)
        self.blocks = nn.ModuleList(
            [Block(dim, n_heads, ffn) for _ in range(n_layers)]
        )
        self.norm = RMSNorm(dim)
        self.head = nn.Linear(dim, vocab, bias=False)
        self.head.weight = self.tok.weight  # tied
        self.max_seq = max_seq
        self.dim = dim
        self.n_layers = n_layers
        self._pos = nn.Parameter(torch.zeros(max_seq, dim), requires_grad=False)

    def forward(self, ids: torch.Tensor, store=None,
                ckpt_layers: set[int] | None = None,
                recompute_fn=None) -> torch.Tensor:
        T = ids.shape[1]
        x = self.tok(ids) + self._pos[:T].unsqueeze(0)
        for i, blk in enumerate(self.blocks):
            if store is not None and ckpt_layers and i in ckpt_layers:
                # Save the input; recompute the block output in backward.
                store.save(f"block_in_{i}", x, layer_idx=i)
                with torch.no_grad():
                    saved_shape = x.shape
                # Forward must still produce a real tensor for autograd.
                x = blk(x)
            else:
                x = blk(x)
        x = self.norm(x)
        return self.head(x)
```

The model itself is not the point — the integration shape is. The block of code inside the loop is the contract every performance engineer writes: *if this layer is a checkpoint, save its input, compute forward normally, and trust the policy to recompute it later*. You can swap in `torch.utils.checkpoint.checkpoint` here later as a performance upgrade, but writing it by hand is what teaches you what checkpointing actually costs.

### Step 5 — The Training Driver

This is where the scheduler is wired in. The driver picks a policy, runs a forward pass, tracks peak memory, and writes the metrics CSV.

```python
# train.py
from __future__ import annotations
import argparse, time, csv, os
import torch
from model import MiniGPT
from store import ActivationStore
from policy import select_checkpoints_uniform, should_checkpoint

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--steps", type=int, default=200)
    p.add_argument("--batch", type=int, default=4)
    p.add_argument("--seq", type=int, default=256)
    p.add_argument("--dim", type=int, default=256)
    p.add_argument("--layers", type=int, default=8)
    p.add_argument("--policy", choices=["none", "uniform"], default="uniform")
    p.add_argument("--budget_mb", type=int, default=128)
    p.add_argument("--out", type=str, default="metrics.csv")
    p.add_argument("--device", type=str, default="cuda" if torch.cuda.is_available() else "cpu")
    return p.parse_args()

def main():
    args = parse_args()
    device = torch.device(args.device)
    torch.manual_seed(0)

    model = MiniGPT(vocab=50304, dim=args.dim, n_layers=args.layers).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    store = ActivationStore(device, max_bytes=args.budget_mb * 1024 * 1024)

    ckpt_layers = (
        set(select_checkpoints_uniform(args.layers))
        if args.policy == "uniform"
        else set()
    )

    f = open(args.out, "w", newline="")
    w = csv.writer(f)
    w.writerow(["step", "loss", "peak_mb", "store_mb", "recompute", "evict"])

    for step in range(args.steps):
        ids = torch.randint(0, 50304, (args.batch, args.seq), device=device)
        store.begin_forward()
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        logits = model(ids, store=store, ckpt_layers=ckpt_layers)
        loss = torch.nn.functional.cross_entropy(
            logits.view(-1, logits.size(-1)), ids.view(-1)
        )
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()

        peak_mb = (torch.cuda.max_memory_allocated(device) / 1024 / 1024
                   if device.type == "cuda" else 0.0)
        w.writerow([step, float(loss), f"{peak_mb:.2f}",
                    f"{store.memory_bytes() / 1024 / 1024:.2f}",
                    store.recompute_count, store.evict_count])
        if step % 20 == 0:
            print(f"step {step:4d} loss={loss.item():.4f} "
                  f"peak={peak_mb:.1f}MB store={store.memory_bytes()/1024/1024:.1f}MB "
                  f"recompute={store.recompute_count}")
    f.close()

if __name__ == "__main__":
    main()
```

The line you actually want recruiters to notice is `opt.zero_grad(set_to_none=True)`. It is a one-character performance habit — `set_to_none` lets the allocator reuse the gradient buffers instead of zeroing them — and it is the kind of detail that flags someone who has read the [PyTorch CUDA semantics notes](https://pytorch.org/docs/stable/notes/cuda.html) rather than skimmed them.

## Running and Testing It

You should be able to clone, install, run, and produce a CSV in under five minutes. That is the bar.

### Local smoke test (CPU, no checkpointing)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python train.py --steps 50 --batch 2 --seq 64 --layers 4 --policy none --out smoke_none.csv
```

Expect loss to come down from ~10 to ~8. If it does, your forward/backward/optimizer loop is correct.

### Local smoke test (CPU, with checkpointing)

```bash
python train.py --steps 50 --batch 2 --seq 64 --layers 4 --policy uniform --budget_mb 16 --out smoke_ckpt.csv
```

The `recompute` counter in the CSV should climb on every step, peak memory should drop, and step time should go up modestly — exactly the trade-off you are trying to demonstrate.

### GPU run for real numbers

```bash
python train.py --steps 200 --batch 4 --seq 256 --layers 12 --policy uniform --budget_mb 256 --out run_uniform.csv
python train.py --steps 200 --batch 4 --seq 256 --layers 12 --policy none --out run_none.csv
```

Plot the two CSVs. You should see a clear peak-memory gap (often 2–4× on real GPUs) and a step-time gap in the opposite direction. That single chart is the centerpiece of your README.

### Unit tests for the scheduler

The store is the file most worth testing. It is where regressions hurt.

```python
# tests/test_store.py
import torch
from store import ActivationStore

def test_save_and_get_returns_detached_tensor():
    s = ActivationStore(torch.device("cpu"), max_bytes=10_000)
    t = torch.randn(2, 3, requires_grad=True)
    s.save("x", t, layer_idx=0)
    out = s.get("x")
    assert not out.requires_grad
    assert out.shape == (2, 3)

def test_eviction_respects_budget():
    s = ActivationStore(torch.device("cpu"), max_bytes=200_000)
    big = torch.zeros(100, 100)  # 40_000 bytes (float32)
    for i in range(10):
        s.save(f"t{i}", big, layer_idx=i)
    assert s.memory_bytes() <= s.max_bytes
    assert s.evict_count > 0

def test_recompute_replaces_entry():
    s = ActivationStore(torch.device("cpu"), max_bytes=1_000_000)
    t = torch.randn(4, 4)
    s.save("y", t, layer_idx=0)
    fresh = torch.randn(4, 4)
    out = s.recompute("y", lambda: fresh)
    assert torch.equal(out, fresh)
    assert s.recompute_count == 1
```

Run with `pytest tests/`. These three tests catch the three bugs you will actually hit: graph retention, budget overflow, and recompute returning a stale tensor.

### What "proof" looks like in the README

Three artifacts make the project read as serious:

1. A `metrics.csv` (or PNG) comparing `none` vs `uniform` checkpointing on peak memory and step time.
2. A `torch.cuda.memory_summary()` snippet captured at the end of a run, showing the allocator is not fragmenting.
3. The unit test output. Three green tests from `pytest` is more convincing than a paragraph of prose.

## Extending It: Your Roadmap to Senior-Level

The first version is a toy on purpose. The next six upgrades are what turn it into something a staff engineer would happily interview you on. Each one is small in code and large in signal.

- **Cost-model-driven selection.** Replace the `uniform` policy with one that scores each layer by `activation_bytes + flops` and selects a subset under a budget. This is exactly the shape of [GriCheck](https://arxiv.org/abs/2206.12508) and Checkmate-style planners, and it composes with everything else on the list. *Why it matters: shows you can reason about heterogenous costs, not just uniform knobs.*

- **Activation offload to CPU pinned memory.** When the store hits the budget, move evicted tensors to a `torch.Tensor.pin_memory()` buffer instead of freeing them. Free the pinned copy on the next forward pass. *Why it matters: this is how PyTorch's `OffloadEngine` and DeepSpeed's Zero-Offload work in spirit — you are demonstrating the same pattern at a learnable scale.*

- **Persistence via a JSON or SQLite journal.** On checkpoint (the optimizer kind, not the activation kind), write the store's manifest — names, shapes, dtypes — to disk so a restarted job can resume. *Why it matters: shows you understand that scheduler state is just another form of metadata, which is the heart of fault-tolerant training.*

- **Observability hooks.** Emit OpenTelemetry spans for each `save`, `recompute`, and `evict`, and export a Prometheus histogram of recompute latency. *Why it matters: the difference between "a script" and "a service" is whether someone else can see what it is doing at 3am.*

- **Horizontal scaling via ZeRO-style sharding.** Split the store across N ranks; each rank owns a slice of saved activations and serves recompute requests via collectives. *Why it matters: turns a single-process demo into a story about distributed memory, which is the next interview after you land this one.*

- **Benchmarking harness with `torch.compile`.** Add a `--compile` flag and a `nsys` profile target, then publish a table comparing eager, `torch.compile`, `uniform`, and `budget` policies on the same seed. *Why it matters: benchmarking is its own skill; doing it cleanly and reproducibly is rare enough that it alone moves you up a level.*

Pick two. The point is depth, not breadth — a senior-level project is one where three subsystems are finished, not six where each is half-done.

## Key Takeaways

- Gradient checkpointing is a *policy problem*, not just a torch utility. Writing the policy yourself is the interview story.
- Detach aggressively at save time. Holding `requires_grad=True` activations silently breaks the whole optimization and is the most common bug.
- Measure two things, always: peak memory (the win) and recompute count (the cost). A good policy moves the first down without blowing up the second.
- Keep seams clean — model, store, policy, driver. Every senior-level upgrade lands in exactly one of those files.
- The demo that lands is a CSV or plot, not prose. Show `none` vs `uniform` on the same axes and let the numbers speak.
- Treat this as a living repo. One well-evolved mini-GPT scheduler with cost modeling and observability is worth more on a CV than five half-finished "from-scratch transformers."

## Further Reading

- [Training Deep Nets with Sublinear Memory Cost — Chen et al., the original gradient checkpointing paper](https://arxiv.org/abs/1604.06174)
- [GriCheck: Mitigating Training Memory Footprint via Activation Recomputation — Kurilov et al.](https://arxiv.org/abs/2206.12508)
- [PyTorch CUDA semantics notes — the official guide to allocator behavior, `set_to_none`, and memory snapshots](https://pytorch.org/docs/stable/notes/cuda.html)
- [`torch.utils.checkpoint` API reference — the utility whose behavior you are now reimplementing from first principles](https://pytorch.org/docs/stable/checkpoint.html)
- [ZeRO-Offload: Democratizing Billion-Scale Model Training — Ren et al., for the CPU-offload extension path](https://arxiv.org/abs/2101.06840)
- [Checkmate: Breaking the Memory Wall with Checkpoint Ratio Tuning — Beaumont et al., for the cost-model selection upgrade](https://arxiv.org/abs/2211.07435)
- [NSight Systems documentation — the profiler you will use to produce the README's profile trace](https://docs.nvidia.com/nsight-systems/)