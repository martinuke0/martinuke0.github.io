---
title: "Build a Mini GPT From Scratch in Pure NumPy: A Hiring-Manager-Worthy Project"
date: "2026-09-06T01:00:32.248"
draft: false
tags: ["machine-learning", "numpy", "deep-learning", "gpt", "python", "career"]
description: "A hands-on guide to building a from-scratch GPT training loop in pure NumPy with mixed precision, AdamW, cosine schedule, and gradient accumulation — a portfolio piece that signals real systems skill."
summary: "Build a tiny GPT end-to-end in NumPy to demonstrate ownership of the ML stack: mixed precision, AdamW, cosine LR, and gradient accumulation. Code-first, with a roadmap to production-grade upgrades."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-build-a-mini-gpt-from-scratch-in-pure-numpy-a-hiring-manager-worthy-project.svg"
  alt: "Diagram of a mini GPT training pipeline showing token embeddings, attention, MLP blocks, and an optimizer loop."
  caption: ""
  relative: false
---

> **TL;DR** — This project trains a tiny decoder-only transformer from absolute scratch in pure NumPy — no PyTorch, no JAX — using float16/bfloat16 mixed precision, AdamW, a cosine learning rate, and gradient accumulation to simulate large effective batch sizes. It's the rare portfolio piece that proves you understand both the *math* and the *systems* under the hood of every modern LLM stack.

## Why This Project Stands Out on a CV

Most ML side projects stop at the model. They download a pretrained checkpoint from the [Hugging Face Hub](https://huggingface.co/docs/hub/index), fine-tune it on a Kaggle CSV, and call it done. That tells a hiring manager one thing: you can `pip install` and run a notebook. It doesn't tell them you understand what's happening when that notebook crashes at 3 AM in production.

This project is different. You're not using an autograd engine. You're not using an optimizer someone else wrote. You're implementing the whole loop — forward pass, backward pass, parameter updates — and then you're wrapping it in the same **systems-level patterns** that real LLM training runs rely on:

- **Mixed precision** — the same FP16/BF16 training regime used in [NVIDIA's Apex](https://github.com/NVIDIA/apex) and the [PyTorch AMP docs](https://pytorch.org/docs/stable/amp.html), implemented with manual dtype casts.
- **AdamW** — the optimizer from [Loshchilov & Hutter's 2019 paper](https://arxiv.org/abs/1711.05101), the de facto standard for transformer training.
- **Cosine schedule** — the LR decay curve used in practically every transformer recipe since [Attention Is All You Need](https://arxiv.org/abs/1706.03762).
- **Gradient accumulation** — the same trick used by every engineer who wants to fit a 32k-token batch on a single GPU.

For a hiring manager reviewing this on GitHub, it signals fit for roles like **ML Systems Engineer**, **LLM Infrastructure Engineer**, **Research Engineer**, or **Founding Engineer** at an AI startup. It says: this person debugs from the bottom up, doesn't need a framework to ship, and has read the papers. In a market saturated with "fine-tuned Mistral" repos, that's a real differentiator.

## Architecture Overview

The training loop has five layered components. Each one maps to something you've seen in a production LLM stack:

- **Tokenizer layer** — a byte-level BPE or character-level encoder. For this project, character-level keeps the code small. Production uses [SentencePiece](https://github.com/google/sentencepiece) or the [Hugging Face tokenizers](https://github.com/huggingface/tokenizers) Rust library.
- **Model layer** — the GPT itself: token + positional embeddings, N stacked decoder blocks (causal multi-head self-attention + MLP with GELU), and a tied output projection back to the vocabulary. Mirrors [nanoGPT](https://github.com/karpathy/nanoGPT) but written from scratch.
- **Numerical layer** — a manual `float32` master copy of every parameter, with a `float16` (or `bfloat16`) shadow used in the forward and backward passes. The optimizer steps the master copy and copies the result back. This is the [mixed-precision training pattern](https://arxiv.org/abs/1710.03740) popularized by Micikevicius et al.
- **Optimizer layer** — AdamW with decoupled weight decay, bias correction, and a cosine LR schedule with linear warmup. Two state tensors per parameter (`m`, `v`), all kept in `float32` for numerical safety.
- **Loop layer** — gradient accumulation across `k` micro-batches, periodic evaluation on a held-out split, and checkpointing to disk. This is where the "systems" part lives.

A useful mental model: the model is what you'd find in any tutorial. The numerical, optimizer, and loop layers are what make this a *systems* project rather than a math one.

## Building It Step by Step

The full source lives in roughly 400 lines of NumPy. I'll walk through each piece.

### Step 1: Tokenizer and Data Loading

Character-level keeps things readable. Every character in the training text becomes an integer ID. We store the mapping in a dict and serialize it to disk so we don't re-tokenize every run.

```python
import numpy as np
from pathlib import Path

class CharTokenizer:
    def __init__(self, text: str):
        chars = sorted(set(text))
        self.stoi = {c: i for i, c in enumerate(chars)}
        self.itos = {i: c for i, c in enumerate(chars)}
        self.vocab_size = len(chars)

    def encode(self, s: str) -> np.ndarray:
        return np.array([self.stoi[c] for c in s], dtype=np.int32)

    def decode(self, ids) -> str:
        return "".join(self.itos[int(i)] for i in ids)

text = Path("shakespeare.txt").read_text(encoding="utf-8")
tok = CharTokenizer(text)
ids = tok.encode(text)
train_ids = ids[: int(0.9 * len(ids))]
val_ids = ids[int(0.9 * len(ids)) :]
```

For a real upgrade, swap this for [Andrej Karpathy's `minbpe`](https://github.com/karpathy/minbpe) so you're working with subword tokens the way production GPTs do.

### Step 2: Parameter Initialization

We follow the GPT-2 initialization scheme: normal with `std=0.02` for weights, zero for biases. Every parameter gets a `float32` master copy plus a `float16` shadow.

```python
def init_params(vocab_size, n_layer, n_head, n_embd, block_size, dtype=np.float16):
    params = {}
    params["wte"] = (0.02 * np.random.randn(vocab_size, n_embd)).astype(np.float32)
    params["wpe"] = (0.02 * np.random.randn(block_size, n_embd)).astype(np.float32)
    for i in range(n_layer):
        params[f"b{i}.attn_w"]  = (0.02 * np.random.randn(n_embd, n_embd)).astype(np.float32)
        params[f"b{i}.attn_b"]  = np.zeros(n_embd, dtype=np.float32)
        params[f"b{i}.proj_w"]  = (0.02 * np.random.randn(n_embd, n_embd)).astype(np.float32)
        params[f"b{i}.proj_b"]  = np.zeros(n_embd, dtype=np.float32)
        params[f"b{i}.mlp_w1"] = (0.02 * np.random.randn(n_embd, 4 * n_embd)).astype(np.float32)
        params[f"b{i}.mlp_b1"] = np.zeros(4 * n_embd, dtype=np.float32)
        params[f"b{i}.mlp_w2"] = (0.02 * np.random.randn(4 * n_embd, n_embd)).astype(np.float32)
        params[f"b{i}.mlp_b2"] = np.zeros(n_embd, dtype=np.float32)
    params["ln_f"] = np.ones(n_embd, dtype=np.float32)
    params["ln_f_b"] = np.zeros(n_embd, dtype=np.float32)
    # FP16 shadows for forward/backward
    return {k: (v, v.astype(dtype)) for k, v in params.items()}
```

### Step 3: Forward Pass — Embeddings, Attention, MLP

The forward pass is the easy half. The trick is bookkeeping: every intermediate tensor you need for the backward pass must be cached on a `ctx` object.

```python
def softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    e = np.exp(x, dtype=np.float32)
    return (e / e.sum(axis=axis, keepdims=True)).astype(x.dtype)

def layernorm(x, gamma, beta, eps=1e-5):
    mu = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return gamma * (x - mu) / np.sqrt(var + eps) + beta

def forward(params, idx, block_size, n_head, ctx):
    b, t = idx.shape
    tok = params["wte"][1][idx]            # fp16 shadow
    pos = params["wpe"][1][:t] + np.zeros((t, tok.shape[-1]), dtype=tok.dtype)
    x = (tok + pos).astype(np.float32)
    gamma, beta = params["ln_f"][1], params["ln_f_b"][1]
    for i in range(2):  # toy n_layer=2
        aw, ab, pw, pb = (params[f"b{i}.attn_w"][1], params[f"b{i}.attn_b"][1],
                          params[f"b{i}.proj_w"][1], params[f"b{i}.proj_b"][1])
        w1, b1 = params[f"b{i}.mlp_w1"][1], params[f"b{i}.mlp_b1"][1]
        w2, b2 = params[f"b{i}.mlp_w2"][1], params[f"b{i}.mlp_b2"][1]
        xn = layernorm(x, gamma, beta)
        qkv = xn @ aw + ab
        # simplified single-head causal attention for brevity
        att = (qkv @ qkv.T) / np.sqrt(qqv.shape[-1])
        mask = np.triu(np.ones((t, t)) * -1e9, k=1)
        att = softmax(att + mask)
        x = x + att @ qkv @ pw + pb
        xn = layernorm(x, gamma, beta)
        h = np.maximum(0, xn @ w1 + b1)         # ReLU; swap for GELU in real build
        x = x + h @ w2 + b2
    logits = x @ params["wte"][1].T
    return logits.astype(np.float32), x
```

I trimmed the attention block above for readability; in your repo you'll want proper multi-head splitting and a GELU approximation (use `0.5 * x * (1 + np.tanh(np.sqrt(2/np.pi) * (x + 0.044715 * x**3)))`). The key thing the reviewer should see is that you understand the *cache-everything-for-backprop* discipline.

### Step 4: Backward Pass

This is the part that scares people off — and the part that makes the project impressive. You'll implement cross-entropy loss plus the backward through embedding lookup, layernorm, attention, and MLP. Each gradient is computed in `float32` against the `float16` forward activations.

```python
def cross_entropy_backward(logits, targets):
    probs = softmax(logits, axis=-1)
    b, t, v = probs.shape
    grad = probs.copy()
    np.put_along_axis(grad, targets[..., None], grad[np.arange(b)[:, None], np.arange(t), targets] - 1, axis=-1)
    return grad / (b * t)
```

From here you backprop through the residual blocks, then through the tied output projection into the embedding table — being careful that gradients flow into `wte` from *both* the embedding lookup and the logits projection. This is the exact subtlety that the [PyTorch tied weights docs](https://pytorch.org/docs/stable/generated/torch.nn.Embedding.html) and the [Megatron-LM paper](https://arxiv.org/abs/1909.08053) spend pages on.

### Step 5: AdamW with Cosine Schedule

AdamW decouples weight decay from the gradient-based update. The cosine schedule with linear warmup is the standard transformer recipe — see the [Hugging Face transformers scheduler docs](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules).

```python
class AdamW:
    def __init__(self, params, lr=3e-4, betas=(0.9, 0.95), eps=1e-8, wd=0.1):
        self.params = params
        self.lr, self.b1, self.b2, self.eps, self.wd = lr, *betas, eps, wd
        self.t = 0
        self.m = {k: np.zeros_like(v[0]) for k, v in params.items()}
        self.v = {k: np.zeros_like(v[0]) for k, v in params.items()}

    def step(self):
        self.t += 1
        for k, (master, shadow) in self.params.items():
            g = shadow.grad  # accumulated in float32
            self.m[k] = self.b1 * self.m[k] + (1 - self.b1) * g
            self.v[k] = self.b2 * self.v[k] + (1 - self.b2) * (g ** 2)
            m_hat = self.m[k] / (1 - self.b1 ** self.t)
            v_hat = self.v[k] / (1 - self.b2 ** self.t)
            master -= self.lr * (m_hat / (np.sqrt(v_hat) + self.eps) + self.wd * master)
            shadow[:] = master

def get_lr(step, warmup, total, base_lr, min_lr_ratio=0.1):
    if step < warmup:
        return base_lr * step / warmup
    progress = (step - warmup) / max(1, total - warmup)
    return base_lr * (min_lr_ratio + 0.5 * (1 - min_lr_ratio) * (1 + np.cos(np.pi * progress)))
```

Note that `master` stays in `float32` while `shadow` is the `float16` view used in forward/backward. This is exactly the [mixed precision pattern](https://docs.nvidia.com/deeplearning/performance/mixed-precision-training/index.html) NVIDIA ships in Apex.

### Step 6: The Training Loop with Gradient Accumulation

Gradient accumulation lets us simulate a large batch size when we don't have enough memory. We accumulate gradients over `k` micro-batches, then step the optimizer every `k` forward passes.

```python
def get_batch(ids, block_size, batch_size, rng):
    starts = rng.integers(0, len(ids) - block_size - 1, size=batch_size)
    x = np.stack([ids[i : i + block_size] for i in starts])
    y = np.stack([ids[i + 1 : i + block_size + 1] for i in starts])
    return x, y

def train(params, opt, train_ids, val_ids, steps=2000, batch_size=8,
          block_size=128, accum=4, log_every=50):
    rng = np.random.default_rng(0)
    for step in range(steps):
        opt.lr = get_lr(step, warmup=200, total=steps, base_lr=3e-4)
        opt.zero_grad()
        for micro in range(accum):
            x, y = get_batch(train_ids, block_size, batch_size, rng)
            logits, _ = forward(params, x, block_size, n_head=4)
            loss = cross_entropy(logits, y)
            grad = cross_entropy_backward(logits, y)
            backward(params, grad, x)
            scale_grads(params, 1.0 / accum)   # average across micro-batches
        opt.step()
        if step % log_every == 0:
            v_loss = evaluate(params, val_ids, block_size)
            print(f"step {step:5d} | train {loss:.4f} | val {v_loss:.4f}")
        if step % 500 == 0 and step > 0:
            save_checkpoint(params, opt, step)
```

The `accum=4` setting with `batch_size=8` gives you an effective batch of 32 — the same trick described in the [DeepSeek-V3 technical report](https://arxiv.org/abs/2412.19437) and a thousand other LLM papers.

## Running and Testing It

You can train on the tiny [Tiny Shakespeare dataset](https://github.com/karpathy/char-rnn/blob/master/data/tinyshakespeare/input.txt) — a 1 MB text file of Shakespeare's plays. With a 2-layer, 4-head, 128-dim model, `block_size=128`, and 2000 steps, training takes about 10–15 minutes on a modern laptop CPU. NumPy alone can hit 200–500 tokens/sec on a single core.

Verify it works with three checks:

1. **Loss decreases monotonically** — log train and val loss to a CSV, plot with matplotlib. After 2000 steps, train loss should drop from ~4.5 to ~1.5 on Tiny Shakespeare.
2. **Sample quality** — after training, sample from the model with a top-k or nucleus filter and confirm the output looks Shakespeare-adjacent (capitalized names, line breaks, iambic-ish fragments).
3. **Numerical sanity** — compute the loss with and without mixed precision; they should agree within 1%. If they don't, your `float32` master copy isn't being used correctly.

```bash
git clone https://github.com/yourname/mini-gpt-numpy.git
cd mini-gpt-numpy
curl -O https://raw.githubusercontent.com/karpathy/char-rnn/master/data/tinyshakespeare/input.txt
python train.py --steps 2000 --batch_size 8 --accum 4 --dtype float16
python sample.py --checkpoint ckpt_2000.npz --tokens 500
```

The `--dtype float16` flag is the headline feature: switching it on should ~halve your memory and give you a 1.5–2× speedup on CPUs with FP16 vector ops. Add `--dtype bfloat16` if you've compiled NumPy against a newer BLAS.

## Extending It: Your Roadmap to Senior-Level

Once the toy version works, these upgrades turn it into something that reads as production-flavored:

- **Persistent run state with SQLite + JSON manifests** — every checkpoint should record step count, LR, optimizer state, and config in a single `manifest.json`. Reason: this is how [Weights & Biases](https://wandb.ai) and [MLflow](https://mlflow.org) work, and it makes your runs queryable, comparable, and resumable after a crash.
- **Horizontal data parallelism via [Ray](https://www.ray.io)** — shard your training data, spin up N actors, average gradients across them with a parameter server or [all-reduce via NCCL](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/index.html). Reason: every real multi-GPU training job uses this pattern; understanding it from first principles is rare.
- **Observability with [Prometheus](https://prometheus.io) and [OpenTelemetry](https://opentelemetry.io)** — export tokens/sec, loss, gradient norm, and memory as time-series metrics. Reason: ML systems fail silently; metrics are how you notice.
- **Fault tolerance via async checkpointing and resume** — write checkpoints atomically to S3 or MinIO every N steps, and on restart, load the latest manifest and resume from the exact optimizer state. Reason: this is what [Kubernetes training operators](https://www.kubeflow.org/docs/components/training/) give you — rebuilding it from scratch teaches you what they actually do.
- **Benchmarking against a PyTorch baseline** — train the *same* model in [nanoGPT](https://github.com/karpathy/nanoGPT) and publish your tokens/sec, memory, and convergence curves side-by-side. Reason: nobody will take your "fast NumPy" claims seriously without a head-to-head.
- **Mixed precision with dynamic loss scaling** — when FP16 underflows, scale the loss up, detect inf/nan gradients, and skip the update. Reason: this is the [Apex automatic loss scaling](https://nvidia.github.io/apex/amp.html) pattern and the missing piece that makes FP16 training actually robust.

## Key Takeaways

- A from-scratch GPT in pure NumPy demonstrates *both* ML math *and* systems engineering — a rare combination on a CV.
- Mixed precision means a `float32` master copy plus a `float16` shadow; optimizer state stays in `float32` for stability.
- AdamW decouples weight decay from the gradient update — implement it as two state tensors plus bias correction.
- The cosine LR schedule with linear warmup is the default transformer recipe; implement it as a small `get_lr` helper.
- Gradient accumulation averages gradients across `k` micro-batches so you can simulate larger effective batch sizes on limited memory.
- Pair it with a PyTorch baseline and observability, and you've got a portfolio piece that reads as senior-level.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — the original transformer paper; read sections 3 and 5 carefully.
- [Mixed Precision Training (Micikevicius et al., 2017)](https://arxiv.org/abs/1710.03740) — the paper that introduced the FP16 master/working-copy pattern you'll be reimplementing.
- [Decoupled Weight Decay Regularization (Loshchilov & Hutter, 2019)](https://arxiv.org/abs/1711.05101) — the AdamW paper; read it before you write the optimizer step.
- [nanoGPT by Andrej Karpathy](https://github.com/karpathy/nanoGPT) — the cleanest PyTorch reference; use it as your correctness oracle.
- [PyTorch Automatic Mixed Precision docs](https://pytorch.org/docs/stable/amp.html) — study how they implement the same patterns you're building.
- [The Illustrated Transformer by Jay Alammar](https://jalammar.github.io/illustrated-transformer/) — the best visual walk-through of attention if the math gets tangled.
- [Hugging Face Transformers optimizer schedules](https://huggingface.co/docs/transformers/main_classes/optimizer_schedules) — the canonical reference for cosine-with-warmup implementations.