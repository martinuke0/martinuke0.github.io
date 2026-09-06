---
title: "Building a Mixed-Precision GPT Trainer From Scratch: A CV-Grade ML Systems Project"
date: "2026-09-06T02:00:41.243"
draft: false
tags: ["pytorch", "cuda", "mixed-precision", "ml-systems", "portfolio-project"]
description: "A hands-on build guide for a from-scratch mixed-precision training loop with gradient scaling, dynamic loss scaling, and a custom bf16 tensor kernel for a mini GPT."
summary: "A working engineer's guide to building a from-scratch mixed-precision training loop — gradient scaling, dynamic loss scaling, and a custom bf16 tensor kernel — applied to a mini GPT. Includes architecture, runnable code, and a roadmap for turning the toy into a portfolio-grade ML systems project."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-building-a-mixed-precision-gpt-trainer-from-scratch-a-cv-grade-ml-systems-project.svg"
  alt: "Diagram of a mixed-precision training loop showing forward, autocast, loss scaling, and a custom CUDA bf16 kernel."
  caption: ""
  relative: false
---

> **TL;DR** — Mixed-precision training is the bread-and-butter of every modern LLM stack, and a from-scratch implementation — including gradient scaling, dynamic loss scaling, and a hand-written bf16 CUDA kernel — is a small, sharp project that signals real ML systems skill. This guide walks through the architecture, the runnable code for a mini GPT, and a roadmap of upgrades that take the project from a weekend build to something a hiring manager pauses on.

If you've ever stared at a job description asking for "experience training and optimizing large models" and felt your production experience didn't quite match, you're not alone. Most engineers have trained a model with `model.fit` or a Hugging Face `Trainer` — few have built the loop underneath. A small, focused project that exposes the moving parts of mixed-precision training is one of the most efficient ways to close that gap. It fits on a single GPU, runs in a weekend, and demonstrates the kind of low-level intuition that distinguishes "uses PyTorch" from "understands PyTorch."

This is a build guide, not a survey. We'll write the training loop ourselves, implement gradient scaling by hand, add dynamic loss scaling, and replace one of the hot kernels with a custom CUDA implementation in bf16. The end result is a mini GPT that trains stably in mixed precision, with a codebase small enough to fully explain in a code review.

## Why This Project Stands Out on a CV

Hiring managers scanning a portfolio for ML systems chops look for a few specific signals. This project hits several of them at once.

- **Demonstrates torch internals literacy.** Writing the forward/backward loop, the loss-scaling state machine, and a custom CUDA kernel shows you understand what's behind `torch.cuda.amp.autocast`, not just how to call it. That maps directly to roles tagged "ML Engineer," "Training Infrastructure," and "Performance Engineer."
- **Proves CUDA fluency without requiring a PhD.** You don't need to derive FlashAttention. Implementing a fused bf16 GEMV for the projection layers is enough to demonstrate you can ship a `.cu` file, integrate it via `torch.utils.cpp_extension`, and reason about memory coalescing and shared-memory tiling.
- **Shows production-minded thinking.** Dynamic loss scaling is exactly the kind of stability machinery that breaks in the field and gets debugged at 3 a.m. Including it in a side project — with logs, decay, and skip-step recovery — telegraphs that you've seen real training runs, not just notebooks.
- **Compresses multiple skills into one repo.** Autograd, kernel launches, profiling with `torch.profiler`, mixed-precision numerics, and tokenizer wiring all live in one ~500-line codebase. That's a higher information density than a generic "trained ResNet on CIFAR" repo.
- **Maps to named platforms.** The patterns you'll implement are the same ones in [NVIDIA Apex](https://github.com/NVIDIA/apex), [DeepSpeed's](https://www.deepspeed.ai/tutorials/amp/) mixed-precision engine, and [Megatron-LM](https://github.com/NVIDIA/Megatron-LM). A reviewer who has shipped one of those will immediately recognize the architecture.

In short: it's the rare side project that looks small and reads big. Five hundred lines, but every line is something a staff engineer has had to debug for real.

## Architecture Overview

The system is deliberately small. Five components, each with a single responsibility.

- **Model (`model/minigpt.py`).** A decoder-only transformer with pre-norm, GELU, learned positional embeddings, and tied input/output embeddings. Parameters kept in fp32 master weights; activations and compute in bf16.
- **Custom CUDA kernel (`csrc/bf16_gemv.cu`).** A tiled matrix-vector product that reads fp32 weights, casts to bf16 on the fly, and accumulates in fp32. This replaces one `nn.Linear` in the forward pass and demonstrates kernel-level mixed precision.
- **AMP state (`amp/scaler.py`).** A `DynamicLossScaler` class holding the current scale factor, a growth/decay interval counter, and the skip-step recovery flag. Mirrors the public API of `torch.cuda.amp.GradScaler` but is ~80 lines you can read.
- **Training loop (`train.py`).** Iterates batches, runs forward under autocast, applies loss scaling, calls backward, unscales gradients, clips, and steps the optimizer. Logs scale factor and any skipped steps.
- **Data pipeline (`data/tinyshakespeare.py`).** Character-level tokenizer over the Tiny Shakespeare corpus, packed into fixed-length sequences. Small enough to overfit visibly, large enough to produce non-trivial loss curves.

The data flow looks like this:

```
tokens (int64)
   -> Embedding (fp32) + pos embed
   -> N x [bf16 Attention -> bf16 Custom Linear -> bf16 FFN]
   -> bf16 logits
   -> fp32 cross-entropy
   -> DynamicLossScaler.scale(loss)
   -> backward()  (gradients in bf16 on params, fp32 on master)
   -> scaler.unscale_(optimizer)
   -> torch.nn.utils.clip_grad_norm_
   -> scaler.step(optimizer)   # skip if inf/nan
   -> scaler.update()
```

Two design decisions worth flagging up front. First, we keep **fp32 master weights** and cast on the fly — this is the [Micikevicius et al. approach](https://arxiv.org/abs/1710.03740) and matches how Apex and DeepSpeed do it. Second, we choose **bf16 over fp16** for the cast because bf16 has the same exponent range as fp32, which means we don't *technically* need loss scaling for bf16 — but we implement it anyway, because fp16 with dynamic loss scaling is still the standard on most accelerators, and the scaler is the most educational piece of the whole project.

## Building It Step by Step

### Step 1 — Repository scaffold

```
minigpt-mixed-precision/
├── csrc/
│   └── bf16_gemv.cu
├── amp/
│   ├── __init__.py
│   └── scaler.py
├── model/
│   ├── __init__.py
│   └── minigpt.py
├── data/
│   ├── __init__.py
│   └── tinyshakespeare.py
├── train.py
├── benchmark.py
├── requirements.txt
└── README.md
```

`requirements.txt` is short and intentional:

```text
torch>=2.1
numpy
tiktoken
pybind11
```

### Step 2 — The mini GPT

A decoder-only transformer, ~50M parameters at the default config. Pre-norm, GELU, learned positional embeddings, weight tying between the token embedding and the LM head.

```python
# model/minigpt.py
import torch
import torch.nn as nn
import torch.nn.functional as F


class Block(nn.Module):
    def __init__(self, d_model, n_head, dropout):
        super().__init__()
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)
        self.attn = nn.MultiheadAttention(d_model, n_head, batch_first=True)
        self.mlp = nn.Sequential(
            nn.Linear(d_model, 4 * d_model),
            nn.GELU(),
            nn.Linear(4 * d_model, d_model),
            nn.Dropout(dropout),
        )
        self.drop = nn.Dropout(dropout)

    def forward(self, x, mask):
        h = self.ln1(x)
        a, _ = self.attn(h, h, h, attn_mask=mask, need_weights=False)
        x = x + self.drop(a)
        x = x + self.drop(self.mlp(self.ln2(x)))
        return x


class MiniGPT(nn.Module):
    def __init__(self, vocab, d_model=384, n_head=6, n_layer=6, block_size=256, dropout=0.1):
        super().__init__()
        self.tok = nn.Embedding(vocab, d_model)
        self.pos = nn.Embedding(block_size, d_model)
        self.blocks = nn.ModuleList(
            [Block(d_model, n_head, dropout) for _ in range(n_layer)]
        )
        self.ln_f = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab, bias=False)
        self.head.weight = self.tok.weight  # weight tying
        self.block_size = block_size

    def forward(self, idx):
        B, T = idx.shape
        pos = torch.arange(T, device=idx.device)
        x = self.tok(idx) + self.pos(pos)
        mask = torch.triu(
            torch.full((T, T), float("-inf"), device=idx.device), diagonal=1
        )
        for blk in self.blocks:
            x = blk(x, mask)
        x = self.ln_f(x[:, -1] if self.training else idx.shape[1]:)
        # training path uses all positions; the slice above is for sampling only
        return self.head(x)
```

> A note on the head: for loss computation we want logits at every position. In practice the trainer slices off the last token for the target. Keep this clean in your repo — a reviewer reading the loss line should not have to decode a slice.

### Step 3 — The custom bf16 GEMV kernel

This is the showcase piece. We replace the second `nn.Linear` in the MLP with a custom CUDA kernel that reads fp32 weights, casts to `__nv_bfloat16` per element, and accumulates in fp32. A matrix-vector product is the right shape here because the inference-style pass over a single token at a time is `W @ x`, and it's also the easiest kernel to verify against `torch.matmul`.

```cpp
// csrc/bf16_gemv.cu
#include <torch/extension.h>
#include <cuda_bf16.h>

// y[m] = sum_k W[m,k] * x[k],   W: [M,K] fp32, x: [K] fp32, y: [M] fp32
// W is stored row-major. Threads cooperate on output rows.
template <int BM, int BN, int BK>
__global__ void bf16_gemv_kernel(
    const float* __restrict__ W,
    const float* __restrict__ x,
    float* __restrict__ y,
    int M, int K) {
  __shared__ float xs[BN];
  int row = blockIdx.x * BM + threadIdx.y;
  int tx = threadIdx.x;
  float acc = 0.f;
  for (int tile = 0; tile < K; tile += BN) {
    if (tx < BN && (tile + tx) < K) xs[tx] = x[tile + tx];
    __syncthreads();
    if (row < M) {
      #pragma unroll
      for (int k = 0; k < BN; ++k) {
        int col = tile + k;
        if (col < K) {
          float w = W[row * K + col];
          __nv_bfloat16 wb = __float2bfloat16(w);
          acc += __bfloat162float(wb) * xs[k];
        }
      }
    }
    __syncthreads();
  }
  if (row < M) y[row] = acc;
}


torch::Tensor bf16_gemv(torch::Tensor W, torch::Tensor x) {
  TORCH_CHECK(W.is_cuda() && x.is_cuda(), "tensors must be CUDA");
  TORCH_CHECK(W.dtype() == torch::kFloat32, "W must be fp32");
  TORCH_CHECK(x.dtype() == torch::kFloat32, "x must be fp32");
  TORCH_CHECK(W.dim() == 2, "W must be 2D");
  int M = W.size(0), K = W.size(1);
  TORCH_CHECK(x.numel() == K, "shape mismatch");
  auto y = torch::empty({M}, W.options());
  constexpr int BM = 32, BN = 32;
  dim3 block(BN, BM);
  dim3 grid((M + BM - 1) / BM);
  bf16_gemv_kernel<BM, BN, BN><<<grid, block>>>(
      W.data_ptr<float>(), x.data_ptr<float>(), y.data_ptr<float>(), M, K);
  return y;
}


PYBIND11_MODULE(TORCH_EXTENSION_NAME, m) {
  m.def("bf16_gemv", &bf16_gemv, "bf16 cast + GEMV (fp32 accum)");
}
```

The kernel is intentionally simple — no tensor cores, no shared-memory tiling of `W`. Its job is not to be the fastest GEMV in the world; its job is to demonstrate that you understand cast-on-load, fp32 accumulation, and a `cpp_extension` build. In a code review, "this could be `cublasGemmEx`" is a fair comment, and your answer is "yes, and the production version uses cuBLAS, see `benchmark.py`." That's the right conversation to have.

Compile and test it:

```python
# quick check
import torch
from torch.utils.cpp_extension import load
ext = load(name="bf16_gemv", sources=["csrc/bf16_gemv.cu"], verbose=True)

W = torch.randn(512, 384, device="cuda")
x = torch.randn(384, device="cuda")
y_ref = W @ x
y_mine = ext.bf16_gemv(W, x)
assert torch.allclose(y_ref, y_mine, atol=1e-2), "kernel mismatch"
print("kernel OK, max abs diff:", (y_ref - y_mine).abs().max().item())
```

The 1e-2 tolerance is real — bf16 has 8 mantissa bits, so per-element rounding error compounds. Anything tighter is a bug in your test, not the kernel.

### Step 4 — Dynamic loss scaler

This is where the project earns its keep on a CV. The scaler implements the state machine from the [AMP paper](https://arxiv.org/abs/1710.03740) without leaning on `torch.cuda.amp`.

```python
# amp/scaler.py
class DynamicLossScaler:
    def __init__(self, init_scale=2 ** 15, growth_factor=2.0,
                 backoff_factor=0.5, growth_interval=2000, enabled=True):
        self.scale = init_scale
        self.growth_factor = growth_factor
        self.backoff_factor = backoff_factor
        self.growth_interval = growth_interval
        self.enabled = enabled
        self._growth_step = 0
        self._found_inf = False

    def scale_loss(self, loss):
        return loss * self.scale if self.enabled else loss

    def unscale_grads(self, optimizer):
        if not self.enabled:
            return
        inv = 1.0 / self.scale
        for group in optimizer.param_groups:
            for p in group["params"]:
                if p.grad is not None:
                    p.grad.mul_(inv)

    def _check_inf(self, optimizer):
        for group in optimizer.param_groups:
            for p in group["params"]:
                if p.grad is not None and not torch.isfinite(p.grad).all():
                    return True
        return False

    def step(self, optimizer):
        if not self.enabled:
            optimizer.step()
            return True
        if self._found_inf:
            self._found_inf = False
            self._shrink()
            return False
        optimizer.step()
        return True

    def update(self):
        if not self.enabled:
            return
        if not self._found_inf:
            self._growth_step += 1
            if self._growth_step >= self.growth_interval:
                self.scale *= self.growth_factor
                self._growth_step = 0
        else:
            self._found_inf = False

    def _shrink(self):
        self.scale *= self.backoff_factor
        self.scale = max(self.scale, 1.0)
        self._growth_step = 0

    def check_and_mark_inf(self, optimizer):
        if not self.enabled:
            return
        if self._check_inf(optimizer):
            self._found_inf = True
```

The contract is: scale the loss before backward, unscale after, check for inf/nan, skip the step if found, otherwise grow the scale every `growth_interval` clean steps. This is exactly the loop described in the [PyTorch AMP docs](https://pytorch.org/docs/stable/amp.html), but written by hand.

### Step 5 — The training loop

Pulling it together. The loop runs forward under `torch.autocast`, scales the loss, calls backward, unscales, checks inf, and steps.

```python
# train.py
import torch, time, math, argparse
from torch.utils.cpp_extension import load
from amp.scaler import DynamicLossScaler
from model.minigpt import MiniGPT
from data.tinyshakespeare import get_batch

ext = load(name="bf16_gemv", sources=["csrc/bf16_gemv.cu"], verbose=False)


def main():
    device = "cuda"
    model = MiniGPT(vocab=256).to(device)  # char-level
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4, weight_decay=0.1)
    scaler = DynamicLossScaler(init_scale=2 ** 15, growth_interval=500)

    torch.manual_seed(0)
    losses = []
    for step in range(2000):
        x, y = get_batch(device, block_size=256, batch_size=32)
        opt.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            logits = model(x)
            loss = torch.nn.functional.cross_entropy(
                logits.view(-1, logits.size(-1)), y.view(-1)
            )
        scaled = scaler.scale_loss(loss)
        scaled.backward()
        scaler.unscale_grads(opt)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.check_and_mark_inf(opt)
        stepped = scaler.step(opt)
        scaler.update()
        losses.append(loss.item())
        if step % 50 == 0:
            print(f"step {step:4d} | loss {loss.item():.4f} "
                  f"| scale {scaler.scale:.0f} | inf {not stepped}")


if __name__ == "__main__":
    main()
```

Three things to point out for a reviewer. (1) The `scaler.unscale_grads` call happens *after* backward and *before* `clip_grad_norm_` — if you clip before unscaling, your clip threshold is wrong by the scale factor and you'll clip real gradients. (2) `check_and_mark_inf` must happen between unscale and step. (3) `opt.zero_grad(set_to_none=True)` is the modern idiom — it frees memory rather than writing zeros. Mentioning these unprompted in your README is the difference between "uses PyTorch" and "understands PyTorch."

### Step 6 — Wire the custom kernel into the model

In the `Block.mlp` forward, swap the second `Linear` for our kernel:

```python
# in model/minigpt.py, inside Block.forward
def mlp_forward(self, x):
    h = self.fc1(x)              # standard bf16 matmul via autocast
    h = torch.nn.functional.gelu(h)
    # custom path: cast h to fp32 view, call kernel, cast back
    h_fp32 = h.float()
    w_fp32 = self.fc2.weight.float()
    out = ext.bf16_gemv(w_fp32, h_fp32.reshape(-1, h_fp32.size(-1)).t().contiguous().t())
    return out.view(*h.shape[:-1], -1)
```

Yes, this is slower than `torch.matmul`. That's the point — `benchmark.py` proves it. The story you tell in the README is: "here's where I'd swap in cuBLAS or cuBLASLt for production; here's the kernel boundary; here's the dispatch."

## Running and Testing It

Three commands cover everything you need to demonstrate the project works.

```bash
# 1. Train the mini GPT
python train.py

# 2. Profile with torch.profiler to show the custom kernel lands on GPU
python -c "
import torch
from torch.utils.cpp_extension import load
ext = load(name='bf16_gemv', sources=['csrc/bf16_gemv.cu'])
W = torch.randn(1024, 1024, device='cuda')
x = torch.randn(1024, device='cuda')
with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CUDA]) as p:
    for _ in range(100):
        ext.bf16_gemv(W, x)
print(p.key_averages().table(sort_by='cuda_time_total', row_limit=5))
"

# 3. Verify numerical equivalence against a fp32 reference
python -m pytest tests/test_kernel.py -v
```

A clean run on an RTX 4090 should produce a loss curve that drops from ~5.5 to ~1.8 over 2000 steps. The scale factor should grow from 32768 upward, never shrink — if it shrinks, your kernel or your unscale order has a bug. The README should include a screenshot of the loss curve from a real run; reviewers love seeing actual numbers.

## Extending It: Your Roadmap to Senior-Level

The toy is the start. Each of these upgrades maps to a real production concern, and each is small enough to be a meaningful PR.

- **Persistent checkpointing with `safetensors` and atomic writes.** Add a `save_pretrained` and `from_pretrained` pair that writes to a temp file and `os.replace`s into place. *Why it matters:* training jobs fail at exactly the wrong time; atomic checkpoint writes are the difference between "lost 6 hours" and "lost 2 minutes." This is the same pattern [Hugging Face's `safetensors` library](https://huggingface.co/docs/safetensors/index) uses.
- **Multi-GPU data parallelism with `torch.distributed` (DDP).** Wrap the model in `DistributedDataParallel`, launch with `torchrun`, add an `all-reduce` of the loss for honest logging. *Why it matters:* every production trainer — DeepSpeed, Megatron, [PyTorch FSDP](https://pytorch.org/docs/stable/fsdp.html) — is fundamentally DDP under the hood. Showing you can launch a 2-GPU job and explain `NCCL` is a strong signal.
- **Integration with `torch.profiler` and TensorBoard for observability.** Emit `trace.json` per run, log scale factor, inf-step count, tokens/sec, MFU. *Why it matters:* "it trains" is table stakes; "I can see what it's doing while it trains" is the staff-engineer skill. The [PyTorch profiler docs](https://pytorch.org/docs/stable/profiler.html) walk through the API.
- **Fault tolerance with elastic restarts and a `last_step.txt` marker.** On launch, check for the marker; resume from the matching checkpoint; rewrite the marker atomically every N steps. *Why it matters:* this is how SLURM-managed and [Kubernetes-managed](https://kubernetes.io/docs/concepts/workloads/controllers/job/) training jobs survive preemption. A reviewer who has run on a spot fleet will recognize it instantly.
- **A benchmark harness comparing bf16 vs fp16 vs fp32 vs the custom kernel.** Use `triton.testing.do_bench`, report median + std, plot on a single chart. *Why it matters:* a side-by-step throughput chart is a beautiful interview artifact, and writing the harness teaches you how [A100 vs H100](https://www.nvidia.com/en-us/data-center/h100/) numbers are actually produced.
- **Activation checkpointing and ZeRO-1 sharding.** Add `torch.utils.checkpoint` for memory, and a manual parameter-shard that splits optimizer state across ranks. *Why it matters:* this is the seed of [DeepSpeed ZeRO](https://www.deepspeed.ai/tutorials/zero/) and [FSDP](https://pytorch.org/docs/stable/fsdp.html). Having implemented the prefix of one of those in a side project is a quietly devastating interview move.

Each of these is a half-day to a day of work. Together they take the project from "toy that runs" to "system an SRE would trust on a Friday afternoon."

## Key Takeaways

- **A small, kernel-level project reads bigger than a big one.** 500 lines that touch autocast, loss scaling, custom CUDA, and a real training loop signal more than a 5,000-line fork of someone else's repo.
- **Dynamic loss scaling is the highest-leverage piece to implement by hand.** It's small, it's well-documented, and it forces you to reason about gradient scale, inf/nan propagation, and skip-step recovery — the exact failure modes that bite production runs.
- **The custom kernel doesn't have to be fast.** It has to be correct, profilable, and honestly benchmarked against a reference. The conversation "here's why cuBLAS wins" is the right one to have.
- **Document the order of operations in the training loop.** Reviewers will check for unscale-before-clip, zero-grad-with-set-none, and the right place to check inf. Get these wrong and the whole project reads as cargo-culted.
- **Anchor your README in named systems.** When you say "this is the same pattern as Apex's `LossScaler`" or "this is the seed of FSDP," a reviewer instantly knows where the project sits in the ecosystem.
- **End with a roadmap, not a victory lap.** The six extensions above turn a weekend build into a months-long deepening. That's the arc a hiring manager wants to see in a candidate.

## Further Reading

The references below are the ones that will actually deepen *this* project. Read them in roughly this order.

- [Mixed Precision Training (Micikevicius et al., 2017)](https://arxiv.org/abs/1710.03740) — the original paper. Read sections 3 and 4; they justify every choice in `DynamicLossScaler`.
- [PyTorch Automatic Mixed Precision docs](https://pytorch.org/docs/stable/amp.html) — the public API your scaler mirrors. Worth comparing line-for-line.
- [CUDA C++ Programming Guide — bfloat16](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#bfloat16) — the cast intrinsics used in the kernel.
- [PyTorch C++/CUDA extensions tutorial](https://pytorch.org/tutorials/advanced/cpp_extension.html) — how `torch.utils.cpp_extension.load` actually builds, and how to ship a JIT-compiled kernel.
- [FlashAttention paper (Dao et al., 2022)](https://arxiv.org/abs/2205.14135) — the next thing you'd write after the bf16 GEMV. Same mixed-precision ideas, much harder kernel.
- [DeepSpeed AMP tutorial](https://www.deepspeed.ai/tutorials/amp/) — what production-grade mixed precision looks like at scale; useful as a contrast point.
- [Megatron-LM paper (Shoeybi et al., 2019)](https://arxiv.org/abs/1909.08053) — for when you outgrow DDP and start thinking about tensor and pipeline parallelism.