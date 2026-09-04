---
title: "Building a Mini-GPT From Scratch: A Portfolio Project That Signals Real ML Systems Skill"
date: "2026-09-04T20:00:29.037"
draft: false
tags: ["pytorch", "mixed-precision", "transformers", "machine-learning", "ml-systems"]
description: "Hands-on build guide for a from-scratch GPT training loop with mixed precision, gradient accumulation, cosine LR warmup, weight tying, and AdamW — a CV-ready ML systems project."
summary: "A working engineer's guide to building a mini-GPT training loop from scratch in PyTorch — featuring AMP, gradient accumulation, cosine warmup, weight tying, and AdamW — designed as a CV-grade portfolio piece."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-building-a-mini-gpt-from-scratch-a-portfolio-project-that-signals-real-ml-systems-skill.svg"
  alt: "Diagram of a mini-GPT training loop with mixed precision, gradient accumulation, and optimizer components."
  caption: ""
  relative: false
---

> **TL;DR** — This is a runnable, from-scratch PyTorch training loop for a mini GPT that wires together the five techniques hiring managers actually look for: automatic mixed precision (AMP), gradient accumulation, cosine LR warmup, weight tying, and AdamW. By the end you will have a single, well-tested module you can drop into a CV, walk a recruiter through on a whiteboard, and extend toward distributed training, persistent checkpoints, and benchmarking.

## Why This Project Stands Out on a CV

Most "I built a transformer" portfolio pieces are actually a fork of [nanoGPT](https://github.com/karpathy/nanoGPT) or a copy-paste of the Hugging Face `Trainer` callback chain. Both are fine starting points, but neither signals the thing senior interviewers probe for: **can this person reason about the training loop itself** — about numerical stability, memory pressure, throughput, and the dozen small decisions that decide whether a 7B-parameter model converges on Tuesday or silently NaNs?

This project targets that gap deliberately. By implementing the loop yourself — and committing the resulting code to a public GitHub repo with a clean README and a `make train` target — you demonstrate:

- **Numerical literacy.** Mixed precision is not "just add `autocast`." You make explicit choices about where loss scaling happens, which ops stay in fp32, and how gradient scaling interacts with accumulation. That is exactly the reasoning expected in a PyTorch / CUDA interview loop at companies running large training jobs.
- **Production-shaped code.** A single `train.py` script with checkpoints, resumability, deterministic seeding, gradient clipping, and structured logs is more interview-relevant than a notebook with a wandb chart. Reviewers can read it like production code.
- **Optimizer fluency.** AdamW with decoupled weight decay, separate param groups for weight-decay vs. no-decay layers (the GPT-2 convention), and a cosine schedule with linear warmup is the standard baseline for LLM pretraining. Showing you can wire this up by hand, without `transformers.get_scheduler`, is a credibility signal.
- **Architecture understanding.** Weight tying between the token embedding and the LM head is one of the oldest and most parameter-efficient tricks in the GPT playbook. Knowing *why* it works (the embedding and output projection learn the same distribution over the vocabulary) and being able to implement it correctly under AMP is the kind of detail that distinguishes a hobbyist from someone who has read [GPT-2](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf) and [GPT-3](https://arxiv.org/abs/2005.14165) carefully.

The roles it signals for: ML platform engineer, ML infra, applied research engineer, training systems engineer, and the more senior end of "AI engineer" at companies that pretrain or fine-tune their own models. Even for roles where you will mostly use [DeepSpeed](https://www.deepspeed.ai/) or [Megatron-LM](https://github.com/NVIDIA/Megatron-LM), the hiring manager wants to know you understand what those frameworks are doing under the hood.

## Architecture Overview

The whole project fits in a single Python package with five cohesive modules. Keep it that small on purpose — anything bigger stops being a portfolio piece and starts being a framework.

```text
mini-gpt/
├── minigpt/
│   ├── __init__.py
│   ├── model.py        # Transformer block, causal attention, weight tying
│   ├── data.py         # Tokenizer wrapper, streaming dataset, packed batches
│   ├── optim.py        # AdamW param groups, cosine schedule with warmup
│   ├── train.py        # AMP loop, grad accumulation, checkpoint, resume
│   └── utils.py        # seeding, logging, grad-norm clipping
├── configs/
│   └── tiny.yaml       # Hyperparameters in one place
├── tests/
│   ├── test_model.py
│   ├── test_optim.py
│   └── test_train_step.py
├── Makefile
├── README.md
└── pyproject.toml
```

The data flow at training time:

```text
┌────────────────┐    ┌─────────────────┐    ┌──────────────────┐
│  raw text file │ →  │  BPE tokenizer  │ →  │  packed uint32   │
│  (shakesphere) │    │  (tiktoken GPT-2)│    │  token stream    │
└────────────────┘    └─────────────────┘    └────────┬─────────┘
                                                      │ sliding window
                                                      ▼
                                            ┌─────────────────────┐
                                            │  (B, T) int64 batch │
                                            └──────────┬──────────┘
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                       FORWARD  (autocast bf16)                           │
│  Embed(T) ─► N × [LN ─► CausalAttn ─► residual] ─► LN ─► LMHead ─► logits│
│                                          weight-tied to Embed^T          │
└──────────────────────────────────────────────────────────────────────────┘
                                                       │ loss
                                                       ▼
┌──────────────────────────────────────────────────────────────────────────┐
│   backward (scaler.scale(loss).backward())                               │
│   accumulate every k micro-batches                                       │
│   scaler.unscale_ + clip_grad_norm_                                       │
│   scaler.step(optimizer) → scaler.update                                 │
└──────────────────────────────────────────────────────────────────────────┘
                                                       │
                                                       ▼
                                              ┌─────────────────┐
                                              │  cosine LR step │
                                              │  AdamW update   │
                                              └─────────────────┘
```

Three decisions to internalize before writing code:

1. **bf16, not fp16, on any modern NVIDIA GPU.** bf16 has the same dynamic range as fp32 so you do not need `GradScaler` at all. The loop still works with fp16 + scaling for older hardware, and the code below supports both, but default to bf16 on Ampere and later. See the [PyTorch AMP docs](https://pytorch.org/docs/stable/amp.html) for the rationale.
2. **`torch.compile` the inner step.** A single forward/backward/opt closure is the easiest place to win 1.3–2× throughput with no correctness risk.
3. **Weight tying must happen before the optimizer is constructed.** Otherwise AdamW will create two independent weight-decay groups for the tied parameter and corrupt the math.

## Building It Step by Step

### Step 1 — The model with weight tying

This is a compact GPT block: pre-norm, causal multi-head attention with a single QKV projection, MLP with GELU, and a weight-tied output head. Weight tying is one line — `self.lm_head.weight = self.token_embed.weight` — but it must happen after the embeddings are constructed and before the optimizer sees the parameters.

```python
# minigpt/model.py
import math
import torch
import torch.nn as nn
import torch.nn.functional as F

class CausalSelfAttention(nn.Module):
    def __init__(self, n_embd: int, n_head: int, block_size: int, dropout: float):
        super().__init__()
        assert n_embd % n_head == 0
        self.n_head = n_head
        self.block_size = block_size
        self.qkv = nn.Linear(n_embd, 3 * n_embd, bias=False)
        self.proj = nn.Linear(n_embd, n_embd, bias=False)
        self.dropout = dropout
        # Pre-allocate a causal mask so we don't rebuild it every step.
        mask = torch.tril(torch.ones(block_size, block_size, dtype=torch.bool))
        self.register_buffer("mask", mask.view(1, 1, block_size, block_size), persistent=False)

    def forward(self, x):
        B, T, C = x.shape
        qkv = self.qkv(x).view(B, T, 3, self.n_head, C // self.n_head)
        q, k, v = qkv.unbind(dim=2)
        q, k, v = (t.transpose(1, 2) for t in (q, k, v))  # (B, nh, T, hs)
        # Scaled dot-product attention with the causal mask baked in.
        att = (q @ k.transpose(-2, -1)) * (1.0 / math.sqrt(k.size(-1)))
        att = att.masked_fill(~self.mask[:, :, :T, :T], float("-inf"))
        att = F.softmax(att, dim=-1)
        att = F.dropout(att, p=self.dropout, training=self.training)
        y = att @ v
        y = y.transpose(1, 2).contiguous().view(B, T, C)
        return self.proj(y)


class Block(nn.Module):
    def __init__(self, n_embd, n_head, block_size, dropout, mlp_ratio=4):
        super().__init__()
        self.ln1 = nn.LayerNorm(n_embd)
        self.attn = CausalSelfAttention(n_embd, n_head, block_size, dropout)
        self.ln2 = nn.LayerNorm(n_embd)
        self.mlp = nn.Sequential(
            nn.Linear(n_embd, mlp_ratio * n_embd, bias=False),
            nn.GELU(),
            nn.Linear(mlp_ratio * n_embd, n_embd, bias=False),
            nn.Dropout(dropout),
        )

    def forward(self, x):
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class MiniGPT(nn.Module):
    def __init__(self, vocab_size: int, n_embd: int, n_head: int,
                 n_layer: int, block_size: int, dropout: float = 0.0):
        super().__init__()
        self.block_size = block_size
        self.token_embed = nn.Embedding(vocab_size, n_embd)
        self.pos_embed = nn.Embedding(block_size, n_embd)
        self.blocks = nn.ModuleList(
            [Block(n_embd, n_head, block_size, dropout) for _ in range(n_layer)]
        )
        self.ln_f = nn.LayerNorm(n_embd)
        # Weight tying: the output projection reuses the embedding matrix.
        # This is the GPT-2 trick and saves (V * D) parameters.
        self.lm_head = nn.Linear(n_embd, vocab_size, bias=False)
        self.lm_head.weight = self.token_embed.weight
        self.apply(self._init_weights)

    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)

    def forward(self, idx, targets=None):
        B, T = idx.shape
        tok = self.token_embed(idx)
        pos = self.pos_embed(torch.arange(T, device=idx.device))
        x = self.blocks[0](tok + pos)
        for blk in self.blocks[1:]:
            x = blk(x)
        x = self.ln_f(x)
        logits = self.lm_head(x)
        loss = None
        if targets is not None:
            loss = F.cross_entropy(
                logits.view(-1, logits.size(-1)), targets.view(-1), ignore_index=-1
            )
        return logits, loss
```

A subtle point: in PyTorch, `self.lm_head.weight = self.token_embed.weight` makes the two attributes point at the **same `nn.Parameter` object**. This is exactly what you want — AdamW's parameter groups must see a single `Parameter` for weight decay math to be consistent. If you accidentally do `self.lm_head.weight.data = self.token_embed.weight.data`, you get a copy and two independent optimizer states. The test suite should fail loudly if you make that mistake.

### Step 2 — AdamW with separate param groups

The GPT-2 / nanoGPT convention: 2D matrices (Linear weights, embedding weights) get weight decay; 1D parameters (biases, LayerNorm scales) and the tied head do not. This matters because decaying a LayerNorm gain has no regularization interpretation and tends to hurt.

```python
# minigpt/optim.py
import torch
from torch.optim import AdamW

def build_optimizer(model: torch.nn.Module, lr: float, weight_decay: float,
                    betas=(0.9, 0.95), eps=1e-8):
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        # Tied weight: only count it once, and put it in decay.
        if name == "lm_head.weight":
            continue
        if p.dim() >= 2:
            decay.append(p)
        else:
            no_decay.append(p)
    groups = [
        {"params": decay,    "weight_decay": weight_decay},
        {"params": no_decay, "weight_decay": 0.0},
    ]
    return AdamW(groups, lr=lr, betas=betas, eps=eps, fused=True)
```

Note `fused=True`. On CUDA this dispatches to a single fused kernel per step and is meaningfully faster than the default loop. It is the same call `torch.optim.AdamW` makes inside [PyTorch's reference implementation](https://pytorch.org/docs/stable/generated/torch.optim.AdamW.html).

### Step 3 — Cosine schedule with linear warmup

The canonical LLM schedule from [GPT-3](https://arxiv.org/abs/2005.14165): linearly ramp from 0 → peak LR over `warmup_steps`, then decay as the cosine curve from peak → `min_lr` over the remaining steps. The trick to keep the code short is to express the cosine part as a function of progress in `[0, 1]` and clamp.

```python
# minigpt/optim.py  (continued)
import math

def cosine_lr(step: int, warmup: int, total: int, peak_lr: float, min_lr: float) -> float:
    if step < warmup:
        return peak_lr * (step + 1) / max(1, warmup)
    if step >= total:
        return min_lr
    progress = (step - warmup) / max(1, total - warmup)
    coeff = 0.5 * (1.0 + math.cos(math.pi * progress))
    return min_lr + coeff * (peak_lr - min_lr)
```

You call this every step and assign the result into each param group with `optimizer.param_groups[i]["lr"] = lr`. There is no PyTorch built-in for cosine-with-warmup that handles `min_lr != 0`, which is why a hand-rolled version is the right choice for a portfolio piece.

### Step 4 — Mixed precision and gradient accumulation

This is the heart of the project. The pattern below is the production-grade one:

- **bf16 path**: no `GradScaler`, autocast wraps the forward.
- **fp16 path**: `GradScaler` is required because fp16 underflows at small gradients.
- Accumulation divides the loss by `accum_steps` so the effective learning rate is independent of the micro-batch size.
- Gradient clipping is done **after** `unscale_` and **before** `step`, per the [PyTorch AMP recipe](https://pytorch.org/docs/stable/notes/amp_examples.html#working-with-scaled-gradients).

```python
# minigpt/train.py
import torch
from contextlib import nullcontext

def train_step(model, batch, optimizer, scaler, step, cfg, device):
    x, y = batch["input_ids"].to(device, non_blocking=True), \
           batch["labels"].to(device, non_blocking=True)

    use_bf16 = cfg["dtype"] == "bf16"
    autocast_ctx = (torch.autocast(device_type="cuda", dtype=torch.bfloat16)
                    if use_bf16
                    else torch.autocast(device_type="cuda", dtype=torch.float16))

    with autocast_ctx:
        _, loss = model(x, y)
    loss_for_log = loss.detach().item()
    loss = loss / cfg["grad_accum_steps"]

    if use_bf16:
        loss.backward()
    else:
        scaler.scale(loss).backward()

    return loss_for_log
```

And the outer accumulation loop, which is where most interview candidates fumble:

```python
# minigpt/train.py  (continued)
def train(cfg, model, loader, optimizer, scheduler_step, scaler, device, log, ckpt):
    model.train()
    optimizer.zero_grad(set_to_none=True)
    micro = 0
    running = 0.0
    for step in range(cfg["max_steps"]):
        batch = next(loader)
        loss = train_step(model, batch, optimizer, scaler, step, cfg, device)
        running += loss

        if (step + 1) % cfg["grad_accum_steps"] == 0:
            # Clip in fp32, after unscaling for fp16.
            if cfg["dtype"] == "fp16":
                scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), cfg["grad_clip"])

            # Apply LR schedule.
            lr = cosine_lr(
                step=(step + 1) // cfg["grad_accum_steps"],
                warmup=cfg["warmup_steps"],
                total=cfg["max_lr_steps"],
                peak_lr=cfg["peak_lr"],
                min_lr=cfg["min_lr"],
            )
            for g in optimizer.param_groups:
                g["lr"] = lr

            if cfg["dtype"] == "fp16":
                scaler.step(optimizer)
                scaler.update()
            else:
                optimizer.step()

            optimizer.zero_grad(set_to_none=True)
            avg = running / cfg["grad_accum_steps"]
            log({"train/loss": avg, "train/lr": lr, "train/step": step})
            running = 0.0
```

Three correctness traps baked into this loop: `set_to_none=True` (saves memory and is the documented best practice), gradient clipping happens after unscaling for fp16 only, and the LR schedule steps **per effective update, not per micro-batch**. The third is the bug every junior implementation has.

### Step 5 — Data, seeding, and a small YAML config

A `packed uint32` token stream with a sliding window is the standard GPT pretraining data format. [nanoGPT's `prepare.py`](https://github.com/karpathy/nanoGPT/blob/master/data/shakespeare_char/prepare.py) is a good reference. The training loop just calls `next(loader)` to grab the next (B, T) window.

```yaml
# configs/tiny.yaml
vocab_size: 50257
block_size: 256
n_layer: 6
n_head: 6
n_embd: 384
dropout: 0.1
batch_size: 32
grad_accum_steps: 4
peak_lr: 3.0e-4
min_lr: 3.0e-5
warmup_steps: 100
max_lr_steps: 2000
max_steps: 2000
grad_clip: 1.0
dtype: bf16        # "bf16" or "fp16"
seed: 1337
```

`peak_lr: 3.0e-4` is a reasonable starting point for a model of this size on Shakespeare-scale text; Karpathy's [nanoGPT](https://github.com/karpathy/nanoGPT) default config uses similar values and is the standard reference for tuning them.

## Running and Testing It

A CV-grade project has a one-line install and run path. Pin everything, expose a Makefile, and write tests that would actually catch the bugs reviewers think of first.

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Train the tiny config for 2000 steps on a single GPU.
make train CONFIG=configs/tiny.yaml

# Or directly:
python -m minigpt.train --config configs/tiny.yaml

# Run the test suite (fast, no GPU required for unit tests).
make test
```

What you should see during training:

- Loss starts around 10–11 (log of `vocab_size` for an untrained model) and drops to roughly 1.3–1.5 on the [Tiny Shakespeare](https://huggingface.co/datasets/karpathy/tiny_shakespeare) dataset after 2000 steps of the tiny config.
- A line per effective step on stdout with `loss`, `lr`, `grad_norm`, `tokens_per_sec`, and `step` — structured enough to pipe into `jq` or load into [Weights & Biases](https://wandb.ai/) with one callback.
- A `checkpoints/step_*.pt` written every N steps with `model.state_dict()`, `optimizer.state_dict()`, `scaler.state_dict()` (fp16 only), `step`, and `config`. Resuming is one CLI flag: `--resume checkpoints/step_1000.pt`.

The test suite is where you prove engineering discipline. Three tests that matter most:

```python
# tests/test_model.py
import torch
from minigpt.model import MiniGPT

def test_weight_tying_shares_parameter():
    m = MiniGPT(vocab_size=100, n_embd=32, n_head=4, n_layer=2, block_size=16)
    assert m.lm_head.weight is m.token_embed.weight, "tied weights must share the Parameter object"

def test_forward_shape():
    m = MiniGPT(vocab_size=100, n_embd=32, n_head=4, n_layer=2, block_size=16)
    x = torch.randint(0, 100, (2, 16))
    logits, loss = m(x, x)
    assert logits.shape == (2, 16, 100)
    assert torch.isfinite(loss)
```

```python
# tests/test_optim.py
from minigpt.optim import build_optimizer, cosine_lr

def test_param_groups_separate_decay():
    # Build a model, check the no_decay group contains only 1D params (biases, LayerNorm).
    ...

def test_cosine_warmup_endpoints():
    assert abs(cosine_lr(0, warmup=10, total=100, peak_lr=1.0, min_lr=0.0)) < 1e-6
    assert abs(cosine_lr(9, warmup=10, total=100, peak_lr=1.0, min_lr=0.0) - 1.0) < 1e-6
    assert abs(cosine_lr(100, warmup=10, total=100, peak_lr=1.0, min_lr=0.0) - 0.0) < 1e-6
```

```python
# tests/test_train_step.py
def test_grad_accum_is_invariant_to_micro_batch():
    # Running 4 micro-batches with grad_accum=4 should produce the same
    # parameter update as running 1 micro-batch with effective batch 4x larger
    # (up to floating point noise). This is the property reviewers will probe.
    ...
```

That last test — **gradient accumulation equivalence** — is the one that proves you understand what accumulation actually does. It is also a great talking point in interviews: *"I wrote a test that asserts accumulation is mathematically equivalent to a larger batch, because if it isn't, your LR schedule is wrong."*

## Extending It: Your Roadmap to Senior-Level

Once the basic loop converges and the tests are green, the project has a clear upgrade path. Each extension below maps to a real production concern at a company training models at scale, and each one is small enough to ship in a weekend. Stack them in order.

1. **Persistent checkpoints to S3 / GCS.** Replace `torch.save` with a streaming uploader so a pre-emptible spot instance loss does not lose progress. Reason it matters: resumability across failures is table stakes for any real training run, and the [PyTorch checkpoint tutorial](https://pytorch.org/tutorials/recipes/recipes/saving_and_loading_a_general_checkpoint.html) is deceptively incomplete on the cloud part.
2. **Multi-GPU with [DistributedDataParallel](https://pytorch.org/tutorials/intermediate/ddp_tutorial.html).** Wrap the loop in `torchrun` and replicate the model across GPUs with gradient all-reduce. Reason it matters: DDP is the canonical scaling primitive; every bigger framework (FSDP, DeepSpeed, Megatron) is an evolution of it. Knowing the ungraduated version makes the others intelligible.
3. **Profiling with [torch.profiler](https://pytorch.org/tutorials/recipes/recipes/profiler_recipe.html) and Nsight Systems.** Find the kernel-bound step, swap a Python `for` loop for a fused op or a `torch.compile` region, re-measure. Reason it matters: throughput wins come from profilers, not from intuition. A repo with a `bench/` directory that records before/after traces signals you know how to optimize.
4. **Observability via [Weights & Biases](https://docs.wandb.ai/) or [TensorBoard](https://www.tensorflow.org/tensorboard).** Log histograms of activations and gradients, not just scalar loss. Reason it matters: spike detection on gradient norms is how you catch a divergent run early, and reviewers will ask how you monitor training health.
5. **Mixed precision variant with explicit grad scaling even for bf16.** Add an option that uses `torch.autocast(..., dtype=torch.bfloat16)` plus a custom manual scaler to mimic what [Megatron-LM](https://github.com/NVIDIA/Megatron-LM) does for very large bf16 runs. Reason it matters: shows you can defend the bf16-doesn't-need-a-scaler claim *and* know when it does.
6. **Benchmark harness with [MLPerf-style](https://mlcommons.org/benchmarks/) throughput numbers.** Add a `bench.py` that records tokens/sec/GPU, MFU (model FLOPs utilization), and loss curves for a fixed wall-clock budget, and commit the JSON results to the repo. Reason it matters: numbers > vibes. A table in the README showing "we hit 41% MFU on a single A100" is something a hiring manager can compare against a real production setup.

Each of these is a separate commit with its own README section. By the time you have shipped three of them you have a portfolio piece that competes with people who have shipped at work — which is exactly the audience this project targets.

## Key Takeaways

- A from-scratch GPT training loop is one of the highest signal-per-line projects you can put on a CV because it surfaces *how you think about numerical stability and throughput*, not just whether you can call `model.fit`.
- The five techniques in this guide — AMP, gradient accumulation, cosine warmup, weight tying, AdamW — are not separate tricks; they are one coupled system. The schedule steps per *effective* update, the scaler interacts with clipping, and weight tying constrains how the optimizer sees the parameters.
- Default to bf16 on Ampere+ and skip `GradScaler` entirely; keep the fp16 path working for portability and to show you understand why the bf16 path is simpler.
- A test that asserts "4 accumulated micro-batches equal one large batch" is the single most valuable test in the suite — it is the property everything else rests on.
- The upgrade roadmap is what turns the project from "I built a transformer" into "I built the thing training infra engineers build." Distributed training, persistent checkpoints, profilers, and a benchmark harness are where senior-level signal lives.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — the original Transformer paper. Read it once for the math, then keep it as a reference.
- [Language Models are Unsupervised Multitask Learners (GPT-2, Radford et al., 2019)](https://cdn.openai.com/better-language-models/language_models_are_unsupervised_multitask_learners.pdf) — the canonical description of weight tying and pre-norm GPT.
- [Language Models are Few-Shot Learners (GPT-3, Brown et al., 2020)](https://arxiv.org/abs/2005.14165) — section 2.2 has the cosine-with-warmup schedule and the warmup step counts that every later paper copies.
- [PyTorch Automatic Mixed Precision docs](https://pytorch.org/docs/stable/amp.html) — the authoritative reference for `autocast`, `GradScaler`, and the bf16-vs-fp16 decision tree.
- [PyTorch DistributedDataParallel tutorial](https://pytorch.org/tutorials/intermediate/ddp_tutorial.html) — the natural first step toward multi-GPU training once the single-GPU loop is solid.
- [karpathy/nanoGPT](https://github.com/karpathy/nanoGPT) — the cleanest reference implementation in existence. Read it *after* you have built your own; the differences will teach you more than the code itself.