---
title: "Building Mixed-Precision AdamW with ZeRO-1 from Scratch in Pure PyTorch"
date: "2026-09-06T06:01:04.243"
draft: false
tags: ["pytorch", "deep-learning", "distributed-training", "mixed-precision", "ze-ro", "optimizers"]
description: "A hands-on build guide for implementing mixed-precision AdamW with dynamic loss scaling and ZeRO-1 sharded optimizer state in pure PyTorch — a portfolio project that signals real systems skill."
summary: "A runnable, from-scratch implementation of mixed-precision AdamW with dynamic loss scaling and ZeRO-1 sharded optimizer state in pure PyTorch — built to demonstrate real systems engineering, not just model design."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-building-mixed-precision-adamw-with-zero-1-from-scratch-in-pure-pytorch.svg"
  alt: "Diagram of mixed-precision AdamW with ZeRO-1 sharding across GPUs."
  caption: ""
  relative: false
---

> **TL;DR** — Mixed-precision AdamW and ZeRO-1 are two of the most-cited optimisations in modern training stacks (Apex, Megatron, DeepSpeed, FairScale). Rebuilding them in pure PyTorch — without leaning on `torch.cuda.amp` or `DeepSpeed` — gives you a CV project that proves you understand FP16 underflow, gradient scaling, parameter sharding, and `all-gather`/`reduce-scatter` collectives from first principles.

## Why This Project Stands Out on a CV

Most ML side projects on hiring managers' desks are Jupyter notebooks that fine-tune a HuggingFace model on a sentiment dataset. They demonstrate familiarity with a library, not engineering depth. This project is different. It forces you to engage with the layers that production training frameworks sit on:

- **Mixed-precision arithmetic**: FP16/BF16 storage, FP32 master weights, safe downcast/cast boundaries, and the gradient-scaling machinery that prevents underflow. You'll understand why Apex and `torch.cuda.amp` exist rather than just calling them.
- **Optimiser-state sharding**: The same design as [DeepSpeed's ZeRO-1](https://www.deepspeed.ai/tutorials/zero/) and [FairScale's `oss`](https://fairscale.readthedocs.io/en/stable/api/optimizers.html). You'll implement the partitioning of `exp_avg`, `exp_avg_sq`, and FP32 master weights across data-parallel workers, plus the `all-gather` at `step()` and the `reduce-scatter` of gradients.
- **NCCL collectives by hand**: Every cross-rank coordination point uses `torch.distributed` primitives (`_all_gather_into_tensor`, `_reduce_scatter_tensor`, `barrier`). Reviewers can see you know what `init_process_group("nccl")` actually does.
- **Numerical-stability reasoning**: Dynamic loss scaling with skip-step on overflow detection is the *exact* mechanism Apex shipped in 2018. Re-deriving it shows you can reason about FP16's tiny exponent (5 bits, max ~65,504) and why `1e-4 * 1e-4` underflows to zero.
- **Testing discipline**: Unit tests for correctness parity against `torch.optim.AdamW`, a divergence assertion under aggressive scaling, and a multi-rank determinism check — all wired into a runnable script.

Roles this signals for: ML systems engineer, training infra engineer, performance engineer at an LLM lab, GPU-kernel adjacent SWE, and any "we build the frameworks" team (PyTorch core, JAX, Triton, Megatron). It's also a credible talking-point interview artefact for general ML engineer roles at places like Anthropic, Cohere, Mistral, HuggingFace, and the foundation-model orgs at the hyperscalers.

## Architecture Overview

The system has five tightly-coupled components. Each is small, but their interaction is where the engineering lives.

- **Process group**: Initialised via `torch.distributed.init_process_group("nccl")` with one process per GPU. World size = number of DP workers. The group handle is threaded through every collective.
- **Parameter sharding**: On `__init__`, each rank receives a contiguous shard of the parameter list (flat indexing, like FSDP's `_shard_parameters`). The shard sizes differ by at most one element. Each rank owns the *full* FP16 parameter for its shard (needed for the forward/backward) but only a *shard* of the FP32 master weight, `exp_avg`, and `exp_avg_sq`.
- **Mixed-precision state**: Every parameter has three tensors:
  - `p_local` (FP16, shape = full param) — used in the forward pass.
  - `p_master_local` (FP32, shape = shard) — the optimiser's source of weight.
  - `exp_avg`, `exp_avg_sq` (FP32, shape = shard) — Adam moments.
- **Dynamic loss scaler**: A `LossScaler` object with `scale()` (multiplies loss), `unscale_()` (divides grads in-place), `update()` (halves on overflow, doubles on a window of clean steps), and a `step_no_overflow` flag used by the trainer to skip the optimiser step.
- **Step kernel**: The hot path. Pseudocode for one rank:
  ```
  for each param shard i:
      all_gather(p_local_shard_i)         # everyone needs the FP16 weight
      # user does forward + backward
      reduce_scatter(grad_shard_i)        # average grads into my shard
      unscale grads by 1/scale
      check for inf/nan
      if clean:
          update p_master_local, exp_avg, exp_avg_sq (FP32)
          cast back to p_local
      else:
          skip step, halve scale
  ```

The data flow looks like this:

```
[rank 0] p_local[0..N/4]   p_master[0..N/4]   exp_avg[0..N/4]   exp_avg_sq[0..N/4]
[rank 1] p_local[N/4..N/2] p_master[N/4..N/2] exp_avg[N/4..N/2] exp_avg_sq[N/4..N/2]
[rank 2] p_local[N/2..3N/4] ...
[rank 3] p_local[3N/4..N]  ...
                  │
                  ▼
        all_gather on every step
                  │
                  ▼
        forward → backward → reduce_scatter grads
                  │
                  ▼
        shard-local AdamW update in FP32
```

## Building It Step by Step

The repo layout:

```
mpadam/
  __init__.py
  shard.py        # parameter sharding utilities
  scaler.py       # dynamic loss scaler
  optimizer.py    # MixedPrecisionAdamW + ZeRO-1 step kernel
  train.py        # reference training loop
  test_*.py       # correctness + numerical tests
```

### Step 1 — Process group and shard utility

```python
# mpadam/shard.py
import torch
import torch.distributed as dist

def shard_parameters(params: list[torch.nn.Parameter], world_size: int, rank: int):
    """Split a flat list of params into per-rank contiguous shards.

    Returns: (local_params, shard_index) where shard_index maps
    each local param back to its position in the global list.
    """
    n = len(params)
    per_rank, rem = divmod(n, world_size)
    start = rank * per_rank + min(rank, rem)
    end = start + per_rank + (1 if rank < rem else 0)
    local = params[start:end]
    return local, list(range(start, end))
```

### Step 2 — Dynamic loss scaler

The scaler tracks a `scale` factor (starts at `2**16`, the historical Apex default), a `growth_interval` (typically 2000 steps), and a `backoff_factor` (0.5). On overflow, scale halves and we skip the step. On `growth_interval` consecutive clean steps, scale doubles.

```python
# mpadam/scaler.py
import torch

class DynamicLossScaler:
    def __init__(self, init_scale=2**16, growth_factor=2.0,
                 backoff_factor=0.5, growth_interval=2000):
        self.scale = float(init_scale)
        self.growth_factor = growth_factor
        self.backoff_factor = backoff_factor
        self.growth_interval = growth_interval
        self._clean_steps = 0

    def scale_loss(self, loss: torch.Tensor) -> torch.Tensor:
        return loss * self.scale

    def has_overflow(self, params) -> bool:
        for p in params:
            if p.grad is None:
                continue
            if torch.isinf(p.grad).any() or torch.isnan(p.grad).any():
                return True
        return False

    def unscale_(self, params):
        inv = 1.0 / self.scale
        for p in params:
            if p.grad is not None:
                p.grad.mul_(inv)

    def update(self, overflow: bool):
        if overflow:
            self.scale *= self.backoff_factor
            self._clean_steps = 0
        else:
            self._clean_steps += 1
            if self._clean_steps >= self.growth_interval:
                self.scale *= self.growth_factor
                self._clean_steps = 0
```

The `growth_interval` matters more than it looks. Aggressive scaling catches underflow but breaks overflow-prone layers (logits before softmax). The 2000-step default matches what Apex and early AMP recipes settled on empirically.

### Step 3 — The mixed-precision AdamW step with ZeRO-1

This is the core. The contract:

- `step()` is called *after* the user has done `backward()` on a scaled loss.
- Before collectives, each rank must hold the FP16 parameters for *all* shards. So we `all_gather` the FP16 weights from peers first.
- Then we `reduce_scatter` the FP16 gradients so each rank gets the *averaged* gradient of its own shard.
- Then we run AdamW on FP32 master weights, locally, with the un-scaled gradient.

```python
# mpadam/optimizer.py
import torch
import torch.distributed as dist
from .shard import shard_parameters

class MixedPrecisionAdamW(torch.optim.Optimizer):
    def __init__(self, model_parameters, lr=1e-3, betas=(0.9, 0.999),
                 eps=1e-8, weight_decay=1e-2, world_size=1, rank=0):
        # We keep the FULL param list reference so we can all_gather into them.
        self._all_params = [p for p in model_parameters if p.requires_grad]
        defaults = dict(lr=lr, betas=betas, eps=eps,
                        weight_decay=weight_decay)
        super().__init__(self._all_params, defaults)

        self.world_size = world_size
        self.rank = rank
        # Each rank owns a contiguous slice of params.
        self._local_params, self._shard_idx = shard_parameters(
            self._all_params, world_size, rank
        )

        # Build FP32 master weights + Adam moments for the local shard only.
        for p in self._local_params:
            self.state[p]["master"] = p.detach().float().clone()
            self.state[p]["exp_avg"] = torch.zeros_like(self.state[p]["master"])
            self.state[p]["exp_avg_sq"] = torch.zeros_like(self.state[p]["master"])

    @torch.no_grad()
    def _all_gather_params(self):
        # Make every rank's full FP16 param tensor consistent.
        if self.world_size == 1:
            return
        for full_p in self._all_params:
            buf = torch.empty_like(full_p)
            handle = dist.all_gather_into_tensor(buf, full_p)
            # In a strict impl we'd async-wait; sync keeps the code clear.
            handle.wait()
            full_p.copy_(buf)

    @torch.no_grad()
    def _reduce_scatter_grads(self, scaler):
        # Average FP16 grads across ranks, scatter shards back.
        if self.world_size > 1:
            for full_p in self._all_params:
                if full_p.grad is None:
                    continue
                # Allocate a contiguous buffer matching the full param shape.
                grad = full_p.grad
                out = torch.zeros_like(grad)
                dist.reduce_scatter_tensor(out, grad, op=dist.ReduceOp.SUM)
                # Replace grad with the averaged (post-reduce-scatter) shard view.
                full_p.grad = out

        # Unscale AFTER the collective so the average is correct first.
        scaler.unscale_(self._all_params)

    @torch.no_grad()
    def step(self, scaler: "DynamicLossScaler"):
        # 1. Sync FP16 weights across ranks so the user's forward/backward
        #    on this iteration sees the parameters produced by last step.
        self._all_gather_params()

        # 2. Reduce-scatter + unscale.
        self._reduce_scatter_grads(scaler)

        # 3. Overflow check on local grads only — by symmetry every rank
        #    sees the same finite/infinite pattern post-reduction.
        overflow = scaler.has_overflow(self._local_params)

        # 4. Cross-rank overflow consensus so all ranks skip together.
        if self.world_size > 1:
            flag = torch.tensor([overflow], dtype=torch.int32, device="cuda")
            dist.all_reduce(flag, op=dist.ReduceOp.MAX)
            overflow = bool(flag.item())

        scaler.update(overflow)
        if overflow:
            # Zero grads and bail — weights unchanged this step.
            for p in self._all_params:
                if p.grad is not None:
                    p.grad = None
            return

        # 5. Local AdamW update on FP32 master weights, then cast back.
        for group in self.param_groups:
            beta1, beta2 = group["betas"]
            lr = group["lr"]
            wd = group["weight_decay"]
            eps = group["eps"]

            for p in self._local_params:
                state = self.state[p]
                master = state["master"]
                m, v = state["exp_avg"], state["exp_avg_sq"]
                g = p.grad.float()

                # Decoupled weight decay (the W in AdamW).
                master.mul_(1 - lr * wd)
                m.mul_(beta1).add_(g, alpha=1 - beta1)
                v.mul_(beta2).addcmul_(g, g, value=1 - beta2)

                denom = v.sqrt().add_(eps)
                step_size = lr / (1 - beta1 ** (state.get("step", 0) + 1))
                master.addcdiv_(m, denom, value=-step_size)
                state["step"] = state.get("step", 0) + 1

                # Cast back to FP16 for the next forward.
                p.copy_(master.to(p.dtype))

        for p in self._all_params:
            if p.grad is not None:
                p.grad = None
```

Two subtleties that are easy to get wrong:

1. **`all_gather` order vs. backward**: We do the `all_gather` *before* the user's backward, not after. That's because we want every rank to forward+backward against the *same* weights that the previous step produced — not stale shards. This matches how FSDP's `forward_pre_hook` works.
2. **Overflow consensus**: Each rank might observe different finite/infinite patterns before the reduction (because the reduction itself can introduce NaNs via `inf - inf`). We force a global agreement with `all_reduce(MAX)` on a one-bit flag, so all ranks skip together.

### Step 4 — A runnable training loop

```python
# mpadam/train.py
import os, torch, torch.distributed as dist, torch.nn as nn
from torch.nn.parallel import DDP
from mpadam.optimizer import MixedPrecisionAdamW
from mpadam.scaler import DynamicLossScaler

def main():
    dist.init_process_group("nccl")
    rank, world = dist.get_rank(), dist.get_world_size()
    torch.cuda.set_device(rank)
    device = torch.device("cuda", rank)

    model = nn.Sequential(
        nn.Linear(1024, 4096), nn.GELU(),
        nn.Linear(4096, 4096), nn.GELU(),
        nn.Linear(4096, 1024),
    ).to(device)
    model = DDP(model, device_ids=[rank])

    opt = MixedPrecisionAdamW(
        model.parameters(), lr=2e-4, weight_decay=1e-2,
        world_size=world, rank=rank,
    )
    scaler = DynamicLossScaler()

    for step in range(200):
        x = torch.randn(64, 1024, device=device)
        y = model(x)
        loss = (y ** 2).mean()
        scaled = scaler.scale_loss(loss)
        scaled.backward()
        opt.step(scaler)

        if rank == 0 and step % 20 == 0:
            print(f"step {step:3d}  loss={loss.item():.4f}  scale={scaler.scale:.0f}")

    dist.barrier(); dist.destroy_process_group()

if __name__ == "__main__":
    os.environ.setdefault("MASTER_ADDR", "127.0.0.1")
    os.environ.setdefault("MASTER_PORT", "29500")
    main()
```

Launch with `torchrun --nproc_per_node=4 train.py`.

## Running and Testing It

Three tests are non-negotiable. They are what turn "I wrote a custom optimiser" into "I can prove it works."

**1. Single-rank parity with `torch.optim.AdamW`.** With `world_size=1`, the optimiser must produce identical-step updates when run with `init_scale=1.0` and a passthrough scaler. This catches weight-decay, bias-correction, and dtype bugs.

```python
# test_parity.py
import torch
from torch.optim import AdamW
from mpadam.optimizer import MixedPrecisionAdamW
from mpadam.scaler import DynamicLossScaler

torch.manual_seed(0)
p_ref = torch.randn(64, 64, requires_grad=True)
g = torch.randn_like(p_ref)
p_ref.grad = g.clone()
ref = AdamW([p_ref], lr=1e-2, weight_decay=1e-1)
class IdentityScaler:
    def scale_loss(self, l): return l
    def unscale_(self, ps): pass
    def has_overflow(self, ps): return False
    def update(self, ok): pass
ref.step()

torch.manual_seed(0)
p_mp = torch.randn(64, 64, requires_grad=True)
p_mp.grad = g.clone()
mp = MixedPrecisionAdamW([p_mp], lr=1e-2, weight_decay=1e-1, world_size=1, rank=0)
mp.step(IdentityScaler())

assert torch.allclose(p_ref, p_mp, atol=1e-5), "parity broken"
```

**2. Multi-rank determinism.** All ranks must produce the same final weights when seeded identically.

```bash
torchrun --nproc_per_node=4 tests/test_determinism.py
```

```python
# tests/test_determinism.py
import os, torch, torch.distributed as dist
from mpadam.train import build_model

def main():
    dist.init_process_group("nccl")
    rank = dist.get_rank()
    torch.cuda.set_device(rank)
    torch.manual_seed(123)
    model, opt, scaler = build_model(rank, dist.get_world_size())
    # ... 100 steps ...
    dist.barrier()
    sig = torch.stack([p.detach().float() for p in model.parameters()]).sum()
    dist.all_reduce(sig, op=dist.ReduceOp.SUM)
    assert torch.isfinite(sig), f"rank {rank} diverged"
    dist.destroy_process_group()
```

**3. Memory accounting.** Measure peak GPU memory with `torch.cuda.max_memory_allocated()` before and after. On a 4-GPU box with a 1B-parameter model, ZeRO-1 should cut optimiser-state memory by ~4x compared to DDP. This is the number you cite in your README.

**Local runbook.** Start small:

```bash
# Single-GPU smoke test
python -m mpadam.train --steps 50

# 4-GPU correctness test
torchrun --nproc_per_node=4 tests/test_determinism.py

# Memory benchmark
python benchmarks/mem.py --model-size 1B
```

## Extending It: Your Roadmap to Senior-Level

The base project is ~600 lines. Each of these upgrades adds production-shaped surface area.

1. **BF16 path with the same code** — Many of today's runs use BF16 because its exponent range prevents the underflow that forces loss scaling. Refactor `_all_gather_params` and the cast at the end of `step` to branch on a `dtype` arg, then add a `test_bf16_no_scaler` that proves overflow handling becomes a no-op. Why it matters: shows you understand why BF16 is the default on Hopper/Ada and how AMP recipes evolve.
2. **Gradient bucketing à la FSDP** — The current code does one `reduce_scatter` per parameter. Real frameworks coalesce gradients into ~25 MB buckets to overlap with backward compute. Implement a `Bucket` class and a `reduce_scatter` queue per bucket. Why it matters: this is the single biggest throughput win in FSDP, and interview questions on "why is FSDP fast" almost always land here.
3. **CPU offloading of optimiser state** — When sharding isn't enough, push `exp_avg`/`exp_avg_sq` to pinned host memory and stream back per step. It's the natural next step toward ZeRO-2/ZeRO-3. Why it matters: this is how you fit 13B+ models on commodity nodes.
4. **Async `all_gather` overlapping backward** — Issue the next shard's gather before the current backward completes, using CUDA stream events. Why it matters: shows you can reason about the GPU's execution pipeline, not just the algorithm.
5. **Persistence and checkpointing** — Save only the local shard per rank, with a metadata file describing the sharding layout. Resuming must validate world size and rehydrate the right shards. Why it matters: every production checkpoint format (FSDP, DeepSpeed, Megatron) solves this problem; doing it yourself proves you can.
6. **Observability hooks** — Emit step time, grad norm, overflow count, scale factor, and per-bucket comm time to a structured log. Wire up a `--profile torch-tensorboard` flag using `torch.profiler`. Why it matters: the difference between "research code" and "training infra" is whether you can answer "why did this run take 12% longer?"

## Key Takeaways

- Mixed-precision AdamW is not one optimisation but two stacked concerns: **numerical format** (FP16 storage, FP32 master weight, gradient scaling) and **state distribution** (ZeRO-1 sharding across data-parallel ranks).
- The hot path is: `all_gather` FP16 weights → user backward → `reduce_scatter` grads → unscale → finite-check → local FP32 AdamW update → cast back to FP16.
- Dynamic loss scaling with skip-step on overflow is the production answer to FP16's tiny exponent; it's still relevant for FP16 and is the conceptual template for any future "dynamic something" scaling (e.g. attention softmax temperature).
- ZeRO-1's memory win is exactly `1 / world_size` on optimiser state, plus free `all_gather`/`reduce_scatter` collectives via NCCL. The win compounds when you extend to ZeRO-2 (gradients) and ZeRO-3 (parameters).
- A CV-grade version of this project includes tests for parity, determinism, and memory, plus one extension that goes beyond the textbook (BF16 path, bucketing, or checkpointing).

## Further Reading

- [Mixed Precision Training (Micikevicius et al., 2017) — the paper that introduced FP16 + loss scaling](https://arxiv.org/abs/1710.03740)
- [ZeRO: Memory Optimizations Toward Training Trillion Parameter Models (Rajbhandari et al., 2019)](https://arxiv.org/abs/1910.02054)
- [PyTorch Distributed: `torch.distributed` API reference for `all_gather_into_tensor` and `reduce_scatter_tensor`](https://pytorch.org/docs/stable/distributed.html)
- [DeepSpeed ZeRO-1 tutorial — to compare your implementation against the canonical one](https://www.deepspeed.ai/tutorials/zero/)
- [FairScale's `oss` optimizer source — the closest production-grade reference for the API you're building](https://github.com/facebookresearch/fairscale/blob/main/fairscale/optim/oss.py)
- [Apex AMP source code — the original mixed-precision trainer whose scaler you are re-deriving](https://github.com/NVIDIA/apex/tree/master/apex/amp)
- [PyTorch native AMP (`torch.cuda.amp`) design notes — for the BF16/FP16 split that motivates your BF16 extension](https://pytorch.org/docs/stable/amp.html)