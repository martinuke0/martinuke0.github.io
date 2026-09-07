---
title: "Building LLMs from Scratch: A Working Engineer's Guide"
date: "2026-09-07T11:07:39.244"
draft: false
tags: ["llm", "transformers", "pytorch", "machine-learning", "from-scratch"]
description: "An engineer-focused walkthrough of building a small GPT-style LLM from scratch, covering tokenization, attention, training, and scaling pitfalls."
summary: "A working engineer's end-to-end guide to assembling a transformer language model in PyTorch: from BPE tokenization to multi-head attention, rotary embeddings, and a real training loop on a single GPU."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-llms-from-scratch-a-working-engineer.svg"
  alt: "Neural network diagram with attention heads visualized as colored connections between token nodes."
  caption: ""
  relative: false
---

> **TL;DR** — A GPT-style LLM is a surprisingly small amount of code once you strip the abstractions: a tokenizer, an embedding, a stack of attention-plus-MLP blocks, a causal mask, and a cross-entropy loss. This post walks through each piece in PyTorch, then zooms out to the systems problems — memory, sharding, throughput — that decide whether your model can actually train.

Most engineers I've talked to treat large language models as something that lives behind an API. That's fair — production LLMs are enormous, and the people training them at frontier scale have PhDs and eight-figure compute budgets. But there's a strange second-order effect: the engineers who *understand* how the model works under the hood write better prompts, debug better integrations, and make smarter calls about cost, latency, and failure modes. The fastest way to get that understanding is to build one.

So we're going to build a GPT-style model from scratch. Not a toy one with stubbed layers — a working model that you can train on a single GPU, generate text from, and reason about end-to-end. Then we'll talk about what breaks when you try to scale that same code to something resembling a real production model.

## Why Build One From Scratch?

There are excellent libraries that hide the transformer behind a one-liner — [Hugging Face Transformers](https://huggingface.co/docs/transformers/index), [nanoGPT](https://github.com/karpathy/nanoGPT), [LitGPT](https://github.com/Lightning-AI/litgpt). You should use them. But using them is not the same as understanding them. When something goes wrong — gradient explosion, attention sink, position-embedding overflow — you need a mental model of the internals.

The goal of building one from scratch is not to compete with these libraries. It's to develop an intuition you can't get any other way. The transformer is roughly 800 lines of actual logic. That's a weekend.

## The Architecture in One Picture

A decoder-only transformer (the family GPT belongs to) is conceptually simple:

1. **Tokenize** the input text into integer IDs.
2. **Embed** each ID into a dense vector.
3. **Add positional information** so the model knows token order.
4. **Stack N transformer blocks**, each doing attention and a feed-forward network with residuals.
5. **Project** the final hidden states back to vocabulary logits.
6. **Sample** the next token from those logits.

That's the whole thing. The complexity lives inside the block. Let's build it piece by piece.

## Tokenization: BPE in 100 Lines

The model never sees characters — it sees integers. The tokenizer is the bridge. Byte-Pair Encoding (BPE) is the workhorse used by GPT-2, GPT-4's cl100k_base, LLaMA, and most others. The intuition: start with 256 byte tokens, repeatedly merge the most frequent adjacent pair into a new token, and end up with a vocabulary of 50k–100k subword pieces.

For a from-scratch build, [tiktoken](https://github.com/openai/tiktoken) (OpenAI's Rust-backed tokenizer) or [sentencepiece](https://github.com/google/sentencepiece) is fine for the *runtime* — we still need to understand what it does. Here's the contract:

```python
import tiktoken

enc = tiktoken.get_encoding("gpt2")
ids = enc.encode("Large language models are transformers all the way down.")
print(ids)
# [3237, 1243, 3611, 389, 3061, 22205, 467, 2757, 2417, 13]
```

Each ID maps to a subword. The vocabulary has 50,257 entries in GPT-2. Two important properties follow from BPE:

- **No out-of-vocabulary tokens.** Every byte sequence is representable.
- **Token count ≠ word count.** Common words are single tokens; rare ones are pieces.

This matters for cost. A 1,000-token request to an API is not 1,000 words — it's closer to 750 words of English, per OpenAI's general guidance in their [tokenizer help article](https://help.openai.com/en/articles/4936856-what-are-tokens-and-how-to-count-them).

## Embeddings and Positional Information

Two embedding tables: one for tokens, one for positions. In a modern build you'll often skip the positional table and use rotary positional embeddings inside attention instead — more on that below. For a first pass, learned absolute positions are clearer:

```python
import torch
import torch.nn as nn

class Embeddings(nn.Module):
    def __init__(self, vocab_size, d_model, max_seq_len):
        super().__init__()
        self.token = nn.Embedding(vocab_size, d_model)
        self.pos   = nn.Embedding(max_seq_len, d_model)

    def forward(self, ids):
        # ids: (batch, seq_len)
        b, t = ids.shape
        positions = torch.arange(t, device=ids.device)
        return self.token(ids) + self.pos(positions)[None, :, :]
```

`d_model` is the hidden dimension — 768 in GPT-2 small, 4096 in LLaMA-7B. The position embedding table is `max_seq_len × d_model`. For a 2048 context, that's only ~1.5M parameters — small. For 100k context, it's 400M+ parameters just for positions, which is one reason [RoPE](https://arxiv.org/abs/2104.09864) and other relative-position schemes took over.

## Multi-Head Causal Self-Attention

This is the part everyone gets stuck on. It's not actually hard — it's three matrix multiplies and a softmax. Let's write it.

```python
class CausalSelfAttention(nn.Module):
    def __init__(self, d_model, n_heads, max_seq_len, dropout=0.1):
        super().__init__()
        assert d_model % n_heads == 0
        self.n_heads = n_heads
        self.d_head  = d_model // n_heads
        self.qkv = nn.Linear(d_model, 3 * d_model, bias=False)
        self.out = nn.Linear(d_model, d_model, bias=False)
        self.dropout = nn.Dropout(dropout)
        # Causal mask: upper triangle is -inf
        mask = torch.triu(torch.full((max_seq_len, max_seq_len), float("-inf")), 1)
        self.register_buffer("mask", mask)

    def forward(self, x):
        # x: (batch, seq, d_model)
        b, t, d = x.shape
        qkv = self.qkv(x)                          # (b, t, 3d)
        q, k, v = qkv.chunk(3, dim=-1)
        # Split into heads: (b, n_heads, t, d_head)
        q = q.view(b, t, self.n_heads, self.d_head).transpose(1, 2)
        k = k.view(b, t, self.n_heads, self.d_head).transpose(1, 2)
        v = v.view(b, t, self.n_heads, self.d_head).transpose(1, 2)
        # Attention scores
        scores = (q @ k.transpose(-2, -1)) / (self.d_head ** 0.5)   # (b, h, t, t)
        scores = scores + self.mask[:t, :t]
        weights = scores.softmax(-1)
        weights = self.dropout(weights)
        out = weights @ v                                            # (b, h, t, d_head)
        out = out.transpose(1, 2).contiguous().view(b, t, d)
        return self.out(out)
```

Three things to internalize:

1. **Causal masking.** The `triu(-inf, 1)` line ensures token *t* cannot attend to tokens after it. Without this, the model trivially learns to copy the answer.
2. **Scaling by `sqrt(d_head)`.** Prevents the softmax from saturating when dot products grow with dimension. Without this, gradients vanish.
3. **Multi-head is just a reshape.** There's no magic — heads run in parallel along the head dimension.

For production-scale models, three optimizations change the math: [FlashAttention](https://arxiv.org/abs/2205.14135) fuses the softmax and matmuls to avoid materializing the full attention matrix in HBM; grouped-query attention shares K/V heads across query heads (used in [LLaMA 2](https://arxiv.org/abs/2307.09288)); and RoPE replaces learned positional embeddings. The LLaMA architecture diagram in the original paper is still the cleanest reference.

## The MLP Block

Between attention blocks sits a two-layer feed-forward network with a nonlinear activation. In modern transformers this is typically a SwiGLU or gated linear unit variant — LLaMA uses it. For a first build, a plain GeLU MLP is fine:

```python
class MLP(nn.Module):
    def __init__(self, d_model, mult=4, dropout=0.1):
        super().__init__()
        self.fc1 = nn.Linear(d_model, mult * d_model)
        self.fc2 = nn.Linear(mult * d_model, d_model)
        self.drop = nn.Dropout(dropout)

    def forward(self, x):
        return self.drop(self.fc2(torch.nn.functional.gelu(self.fc1(x))))
```

The expansion factor (`mult=4`) is conventional but worth questioning — gated variants like SwiGLU often use `mult=8/3` to keep parameter count comparable. See the [PaLM paper](https://arxiv.org/abs/2204.02311) for the parameter-matching discussion.

## Putting the Block Together

```python
class Block(nn.Module):
    def __init__(self, d_model, n_heads, max_seq_len, dropout=0.1):
        super().__init__()
        self.ln1  = nn.LayerNorm(d_model)
        self.attn = CausalSelfAttention(d_model, n_heads, max_seq_len, dropout)
        self.ln2  = nn.LayerNorm(d_model)
        self.mlp  = MLP(d_model, dropout=dropout)

    def forward(self, x):
        x = x + self.attn(self.ln1(x))   # Pre-norm
        x = x + self.mlp(self.ln2(x))
        return x
```

Note the `LayerNorm` placement. Modern transformers use **pre-norm** (norm before the sublayer), which trains more stably than the original post-norm. GPT-2 used post-norm; LLaMA, GPT-3, and basically everything since 2020 uses pre-norm. Use pre-norm unless you have a specific reason not to.

## The Full Model

```python
class GPT(nn.Module):
    def __init__(self, vocab_size, d_model=384, n_layers=6, n_heads=6,
                 max_seq_len=1024, dropout=0.1):
        super().__init__()
        self.embed = Embeddings(vocab_size, d_model, max_seq_len)
        self.blocks = nn.ModuleList([
            Block(d_model, n_heads, max_seq_len, dropout) for _ in range(n_layers)
        ])
        self.ln_f = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size, bias=False)
        # Weight tying: share embedding weights with output projection
        self.head.weight = self.embed.token.weight

    def forward(self, ids, targets=None):
        x = self.embed(ids)
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        logits = self.head(x)             # (b, t, vocab_size)
        loss = None
        if targets is not None:
            loss = torch.nn.functional.cross_entropy(
                logits.view(-1, logits.size(-1)), targets.view(-1)
            )
        return logits, loss
```

That's a working GPT. The config above (`d_model=384, n_layers=6, n_heads=6`) gives roughly 45M parameters — small enough to train on a single 12GB GPU.

## A Real Training Loop

The training loop is the same one Andrej Karpathy popularized with [nanoGPT](https://github.com/karpathy/nanoGPT): a simple AdamW step with cosine learning rate decay. The full loop is too long to inline, but the skeleton is:

```python
import torch
from torch.optim import AdamW

model = GPT(vocab_size=50257).cuda()
opt = AdamW(model.parameters(), lr=3e-4, weight_decay=0.1)

# Cosine LR schedule
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=max_steps)

for step in range(max_steps):
    x, y = next(train_loader)             # (b, t) of token ids
    _, loss = model(x.cuda(), y.cuda())
    opt.zero_grad(set_to_none=True)
    loss.backward()
    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
    opt.step()
    sched.step()
```

Three non-obvious details:

- **`set_to_none=True`** in `zero_grad` is meaningfully faster than the default — it skips writing zeros to memory and lets the next backward pass allocate fresh grads.
- **Gradient clipping at 1.0** is the single most impactful stability trick. Without it, an occasional large batch can send gradients to infinity and unwrap training.
- **Weight decay only on 2D parameters** (matrices, not biases or norms) is what the original GPT-2 paper does and what nanoGPT inherits. Worth replicating.

## Sampling Text

Once you have a trained model, generation is straightforward greedy or top-p sampling:

```python
@torch.no_grad()
def generate(model, ids, max_new_tokens=50, temperature=1.0, top_p=0.9):
    for _ in range(max_new_tokens):
        ids_cond = ids[:, -model.embed.pos.num_embeddings:]
        logits, _ = model(ids_cond)
        logits = logits[:, -1, :] / temperature
        # Top-p (nucleus) sampling
        sorted_logits, sorted_idx = logits.sort(dim=-1, descending=True)
        probs = sorted_logits.softmax(-1)
        cum = probs.cumsum(-1)
        mask = cum > top_p
        mask[..., 1:] = mask[..., :-1].clone()
        mask[..., 0] = False
        sorted_logits[mask] = -float("inf")
        next_id = sorted_idx.gather(-1, sorted_logits.argmax(-1, keepdim=True))
        ids = torch.cat([ids, next_id], dim=1)
    return ids
```

`top_p` sampling typically gives more coherent output than greedy decoding and is what most chat-tuned models default to. Temperature below 1.0 sharpens the distribution; above 1.0 flattens it. The [Hugging Face generation guide](https://huggingface.co/docs/transformers/generation_strategies) has a good visual explanation of the tradeoffs.

## Patterns in Production

A model you can train on a laptop and a model that serves at scale are the same code, modulo engineering. Five things change:

### 1. Mixed Precision Training

Run matmuls in bfloat16, accumulate in float32. PyTorch makes this a one-liner with [`torch.autocast`](https://pytorch.org/docs/stable/amp.html) and gives you 2–3x throughput on modern GPUs with negligible quality loss.

### 2. Sharding Across GPUs

Three strategies, increasingly complex:

- **DDP** — replicate the model on each GPU, shard the batch. Easy. Use until your model stops fitting on one GPU.
- **FSDP** — shard parameters, gradients, *and* optimizer state across GPUs. PyTorch's [FSDP2](https://pytorch.org/docs/stable/fsdp.html) implementation is mature.
- **Tensor parallelism** — split individual layers across GPUs. Required for the largest models. Megatron-style implementations are the reference; libraries like [axolotl](https://github.com/OpenAccess-AI-Collective/axolotl) wrap this.

### 3. KV-Cache for Inference

The naive generate loop above recomputes attention for every previously-seen token on every step. At 100k context that's wasteful. Production servers cache the K and V projections from previous tokens and only compute attention for the new one. [vLLM](https://github.com/vllm-project/vllm), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM), and [SGLang](https://github.com/sgl-project/sglang) all build on this. Paged attention in vLLM is the current state of the art for high-throughput serving.

### 4. Quantization

Post-training quantization to INT8 or INT4 gives 2–4x memory reduction with small quality loss. [bitsandbytes](https://github.com/TimDettmers/bitsandbytes) does INT8/INT4 loading in Hugging Face; GPTQ and AWQ are common quantization formats. Worth understanding because it determines what hardware tier can serve your model.

### 5. The Data Problem

Almost every failure mode in real training is a data problem. [DataComp-LM](https://arxiv.org/abs/2406.04194) and the [FineWeb](https://huggingface.co/datasets/HuggingFaceFW/fineweb) paper both show that *better data beats bigger models* at fixed compute budgets. A solid baseline pipeline:

- Deduplicate with a hash or [MinHash](https://github.com/chrisjmccormick/MinHash)
- Filter quality with a fast classifier ([FastText](https://fasttext.cc/) is the workhorse)
- Decontaminate against eval benchmarks — accidentally training on your test set is a real failure mode and ruins numbers

## Common Pitfalls

A few things that bit me when I first built one:

- **Forgetting the causal mask.** Your model will train, the loss will go down, and your generations will be nonsense because every position can see every other position.
- **Off-by-one in position embeddings.** Index `t` requires positions `0..t-1`, not `1..t`. Easy to flip.
- **Not detaching the input when computing logits for loss.** Causes memory blow-up because PyTorch keeps the entire graph for the full sequence.
- **Evaluating on training data.** I've seen this in production code. Don't.
- **Learning rate too high.** 3e-4 works for ~50M models. 1.5e-4 or lower for ~1B. Going higher usually diverges within a few hundred steps.

## Key Takeaways

- A decoder-only LLM is roughly: tokenizer → embedding → N×(attention + MLP) blocks with residuals and LayerNorm → output projection. That's the entire architecture.
- The hard parts are not the math — they are the systems pieces: mixed precision, sharding, KV-cache, quantization, and data curation.
- Multi-head attention is just three matmuls and a softmax. Causal masking and `sqrt(d_head)` scaling are the two tricks that make it work.
- Pre-norm, weight tying between the input embedding and output projection, and gradient clipping at 1.0 are the defaults you want unless you have a reason to deviate.
- Once you can train a 50M model, the path to 7B is engineering — FlashAttention, FSDP, better data — not novel research.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — the original transformer paper. Still worth reading.
- [The Illustrated Transformer (Jay Alammar)](https://jalammar.github.io/illustrated-transformer/) — the clearest visual explanation I've seen.
- [Andrej Karpathy's nanoGPT](https://github.com/karpathy/nanoGPT) — a ~300-line GPT you can read in an evening.
- [Hugging Face NLP Course, Chapter 1](https://huggingface.co/learn/nlp-course/chapter1/1) — solid production-oriented grounding.
- [The Transformer Family (Lil'Log)](https://lilianweng.github.io/posts/2023-01-27-the-transformer-family-v2/) — an excellent survey of the variants that have appeared since 2017.
- [PyTorch distributed training docs](https://pytorch.org/docs/stable/distributed.html) — the reference for DDP and FSDP.