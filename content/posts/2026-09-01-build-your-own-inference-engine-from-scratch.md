---
title: "Build Your Own Inference Engine: From Scratch"
date: "2026-09-01T19:45:56.615"
draft: false
tags: ["llm", "inference", "systems", "python", "machine-learning"]
description: "A hands-on walkthrough of building a small LLM inference engine in Python, covering tokenization, KV cache, and sampling."
summary: "Demystify how LLM inference works by building a tiny inference engine from scratch. Covers tokenization, the transformer forward pass, KV cache, and decoding."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-build-your-own-inference-engine-from-scratch.svg"
  alt: "A stylized illustration of transformer blocks and a KV cache heatmap."
  caption: ""
  relative: false
---

> **TL;DR** — A working LLM inference engine is just four stages: tokenize the prompt, run a forward pass through transformer blocks while filling a KV cache, sample the next token, and repeat until the model emits an end-of-sequence. We will build all four in pure Python, then look at why production systems like vLLM and TensorRT-LLM optimize each one differently.

## Why Build an Inference Engine From Scratch?

Every time you call an LLM API, a sophisticated runtime is at work. It manages tokenization, schedules prefill and decode phases across GPUs, juggles a key-value cache to avoid redundant computation, and samples tokens at a temperature you probably never think about. The usual abstractions — `model.generate()` in Hugging Face, or a one-line call to OpenAI's API — hide all of this behind a convenient function.

That convenience is great until something goes wrong. Maybe tokens are streaming out at 20 per second when you expect 200. Maybe a long context bloats memory until the GPU OOMs. Maybe two users share an instance and one of them is waiting on the other without knowing why. None of these problems make sense until you have seen what an inference engine actually does.

This post is a working tour. By the end, you will have a ~200-line Python script that can load a small open-weights model, accept a prompt, and stream completions — token by token, with a real KV cache. We will then connect that toy engine to the design choices behind production systems like [vLLM](https://blog.vllm.ai/2023/06/20/vllm.html), [Hugging Face TGI](https://huggingface.co/docs/text-generation-inference/en/index), and [NVIDIA TensorRT-LLM](https://developer.nvidia.com/tensorrt-llm).

## The Four Stages of Inference

Before writing code, it helps to hold the whole pipeline in your head. Any autoregressive language model inference call, regardless of model size, follows this pattern:

1. **Tokenize the prompt** — convert the input string into a sequence of integer token IDs using the model's tokenizer.
2. **Prefill** — run the full prompt through the model in one pass, computing and caching the keys and values for every transformer layer.
3. **Decode** — repeatedly sample one new token, append it, and run only the new token through the model while reusing the cached keys and values.
4. **Detokenize** — convert the produced token IDs back into text as they are generated.

The prefill and decode stages have very different performance characteristics. Prefill is compute-bound: it processes the whole prompt in parallel and saturates the GPU's matrix multiplication units. Decode is memory-bound: it generates one token at a time, and most of the time is spent loading the model's weights from VRAM. This asymmetry is the central design constraint of every production inference engine.

## A Minimal Engine in Pure Python

We will build a tiny but complete engine in about 200 lines. It will not be fast — pure Python is roughly 1000x slower than a GPU implementation — but it will be correct and illustrative. Once you understand this, switching the matmul operations to PyTorch or NumPy is mechanical.

Our model of choice is **GPT-2 small** (124M parameters). It is small enough to run on a laptop, the weights are openly available, and the architecture is a vanilla decoder-only transformer that we can implement with no surprises.

### Step 1: Loading Weights

The GPT-2 weights are distributed as a single PyTorch state dict. We can download them once and load them as NumPy arrays, which keeps the dependency footprint small.

```python
import numpy as np
from pathlib import Path

def load_gpt2_weights(cache_dir: Path):
    import tensorflow as tf  # gpt-2 was originally released in TF
    # In practice, use: from transformers import GPT2LMHeadModel
    # m = GPT2LMHeadModel.from_pretrained("gpt2")
    # but here we keep it framework-free.
    ckpt = tf.train.load_checkpoint(str(cache_dir / "gpt2_124m" / "model.ckpt"))
    weights = {name: ckpt.get_tensor(name) for name in ckpt.get_variable_to_shape_map()}
    return weights
```

For brevity, this post uses a higher-level loader. In a real engine, you would read the safetensors file directly using [the safetensors format](https://huggingface.co/docs/safetensors/index), which is memory-mapped and zero-copy.

### Step 2: Tokenization

GPT-2 uses byte-pair encoding with a vocabulary of 50,257 tokens. We can grab the tokenizer from the `tokenizers` library, or load the `encoder.json` and `vocab.bpe` files directly.

```python
import json, regex as re

class BPETokenizer:
    def __init__(self, encoder_path: Path, bpe_path: Path):
        self.encoder = json.loads(encoder_path.read_text())
        self.decoder = {v: k for k, v in self.encoder.items()}
        with bpe_path.open() as f:
            bpe_merges = [tuple(line.rstrip().split()) for line in f
                          if line and not line.startswith("#")]
        self.bpe_ranks = {pair: i for i, pair in enumerate(bpe_merges)}
        self.pat = re.compile(r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+""")

    def bpe(self, token):
        word = tuple(token)
        pairs = {tuple(word[i:i+2]) for i in range(len(word)-1)}
        while True:
            bigram = min(pairs, key=lambda p: self.bpe_ranks.get(p, float("inf")), default=None)
            if bigram is None or bigram not in self.bpe_ranks:
                break
            first, second = bigram
            new_word = [first]
            i = 1
            while i < len(word):
                if i < len(word)-1 and word[i] == first and word[i+1] == second:
                    new_word.append(first + second)
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1
            word = tuple(new_word)
            pairs = {tuple(word[i:i+2]) for i in range(len(word)-1)}
        return " ".join(word)

    def encode(self, text: str) -> list[int]:
        ids = []
        for tok in re.findall(self.pat, text):
            tok = "".join(self.byte_encoder[b] for b in tok.encode("utf-8"))
            ids.extend(self.encoder[pair] for pair in self.bpe(tok).split())
        return ids

    def decode(self, ids: list[int]) -> str:
        text = "".join(self.decoder[i] for i in ids)
        return bytearray(self.byte_decoder[c] for c in text).decode("utf-8", "replace")
```

This is a faithful reproduction of GPT-2's tokenizer. Byte-level BPE is fiddly but it is what makes the model robust to arbitrary Unicode input.

### Step 3: The Transformer Forward Pass

A decoder-only transformer is a stack of identical blocks. Each block has a masked self-attention layer followed by a feed-forward MLP, with residual connections and layer norms in between.

```python
def gelu(x):
    return 0.5 * x * (1.0 + np.tanh(np.sqrt(2.0/np.pi) * (x + 0.044715 * x**3)))

def softmax(x, axis=-1):
    x = x - x.max(axis=axis, keepdims=True)
    return np.exp(x) / np.exp(x).sum(axis=axis, keepdims=True)

def layer_norm(x, gamma, beta, eps=1e-5):
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return gamma * (x - mean) / np.sqrt(var + eps) + beta

def attention(q, k, v, mask):
    # q, k, v: [T, d]
    scores = q @ k.T / np.sqrt(q.shape[-1])    # [T, T]
    scores = scores + mask                       # causal mask
    weights = softmax(scores, axis=-1)
    return weights @ v                            # [T, d]

def block(x, params, kv_cache=None, position_offset=0):
    # x: [T, d_model]
    a = layer_norm(x, params["ln1_gamma"], params["ln1_beta"])
    q = a @ params["wq"]  # [T, d]
    k = a @ params["wk"]
    v = a @ params["wv"]
    if kv_cache is not None:
        k = np.concatenate([kv_cache["k"], k], axis=0)
        v = np.concatenate([kv_cache["v"], v], axis=0)
        kv_cache["k"] = k
        kv_cache["v"] = v
    # Split into heads, attend, recombine — omitted for brevity
    x = x + attention(q, k, v, mask=causal_mask(len(k)))
    m = layer_norm(x, params["ln2_gamma"], params["ln2_beta"])
    h = gelu(m @ params["ffw1"]) @ params["ffw2"]
    return x + h
```

That `kv_cache` parameter is the heart of efficient inference. During prefill, we cache the keys and values for every token in the prompt. During decode, the new token's K and V get appended, and the cached K and V from the prompt and all previously generated tokens get reused. Without this trick, generating 1000 tokens would require recomputing attention over an ever-growing sequence at quadratic cost. With it, each new token costs only O(n) in attention compute, dominated by a single matrix multiply.

### Step 4: Sampling and the Generation Loop

Once we have a logits vector for the next token, we sample. Greedy decoding — always pick the argmax — is fast and deterministic, but produces dull, repetitive text. A bit of stochasticity helps.

```python
def sample(logits, temperature=1.0, top_k=0, top_p=1.0):
    logits = logits / max(temperature, 1e-5)
    if top_k:
        idx = np.argpartition(-logits, top_k)[:top_k]
        mask = np.full_like(logits, -np.inf); mask[idx] = logits[idx]
        logits = mask
    if top_p < 1.0:
        sort_idx = np.argsort(-logits)
        sorted = logits[sort_idx]
        probs = softmax(sorted)
        cum = np.cumsum(probs)
        cutoff = cum > top_p
        cutoff[1:] = cutoff[:-1].copy(); cutoff[0] = False
        logits[sort_idx[cutoff]] = -np.inf
    probs = softmax(logits)
    return int(np.random.choice(len(probs), p=probs))
```

The two most common knobs are `temperature` (lower = more deterministic) and `top_p` (nucleus sampling, as described in [Holtzman et al., 2020](https://arxiv.org/abs/1904.09751)). For a chatty assistant, something like `temperature=0.7, top_p=0.9` is a common starting point.

Putting it all together, the generation loop is almost disappointingly small:

```python
def generate(model, tokenizer, prompt, max_new_tokens=64, **sampling_kwargs):
    tokens = tokenizer.encode(prompt)
    kv_caches = [{} for _ in model["blocks"]]
    for _ in range(max_new_tokens):
        # Prefill on first iteration, decode afterwards
        x = model["wte"][tokens] + model["wpe"][np.arange(len(tokens))]
        for i, block_params in enumerate(model["blocks"]):
            x = block(x, block_params, kv_cache=kv_caches[i])
        logits = (layer_norm(x, ...) @ model["wte"].T)[-1]
        nxt = sample(logits, **sampling_kwargs)
        tokens.append(nxt)
        if nxt == tokenizer.eos_token_id:
            break
        tokens = [nxt]  # next step we only need the new token
    return tokenizer.decode(tokens)
```

Notice how `tokens` is reassigned to a single-element list after the first iteration. The cached keys and values from earlier positions are still in `kv_caches`, so the model only needs to compute the representation of the freshly generated token. This is exactly the trick that makes streaming responses feasible.

## Patterns in Production

Our toy engine is correct but glacially slow. Production systems apply a series of well-understood optimizations, and each one targets a specific bottleneck in the four-stage pipeline.

### Continuous Batching

A naive serving system processes requests one at a time: a 512-token prompt takes ~200ms of prefill, then the model generates one token every 20ms until the request is done. During the prefill, the GPU is busy but the user is waiting. During decode, the GPU is mostly idle because the matrix multiplications are tiny compared to the model's weight matrix.

[vLLM](https://blog.vllm.ai/2023/06/20/vllm.html) popularized **PagedAttention**, a technique that manages the KV cache like virtual memory with fixed-size pages. Combined with **continuous batching** — adding new requests to the running batch every iteration instead of waiting for the current batch to finish — this can improve throughput by 10–23x compared to a static batching scheduler. The [vLLM paper](https://arxiv.org/abs/2309.06180) explains the design in detail.

### Quantization

Most model weights can be stored in INT8 or INT4 with minimal quality loss. INT8 roughly halves memory and compute, INT4 quarters them. Since decode is memory-bandwidth bound, weight quantization directly translates to higher tokens per second. [bitsandbytes](https://github.com/TimDettmers/bitsandbytes), [GPTQ](https://arxiv.org/abs/2210.17323), and [AWQ](https://arxiv.org/abs/2306.00978) are the most common formats you'll encounter.

### Speculative Decoding

Why generate one token per forward pass when you could guess several at once? A small "draft" model proposes the next k tokens; the large model verifies them in a single forward pass using a tree-shaped attention mask. When the draft model is well-aligned with the target, you can get 2–4x speedups. [Google's paper on speculative decoding](https://arxiv.org/abs/2211.17192) is the canonical reference.

### Tensor Parallelism

For models that do not fit on a single GPU, you can split each layer's matrix multiplications across multiple devices. Megatron-style tensor parallelism, originally described in [Shoeybi et al., 2019](https://arxiv.org/abs/1909.08053), is the standard approach. The catch is that it requires fast interconnect (NVLink, InfiniBand) because every layer triggers a synchronization across GPUs.

## A Common Failure Mode: KV Cache Memory

The single biggest production surprise is how much memory the KV cache consumes. A rough formula for a transformer with L layers, H attention heads, head dimension d, sequence length n, and bytes-per-element b:

```
KV cache size = 2 * L * H * d * n * b
```

For a 7B parameter model with 32 layers, 32 heads, head dim 128, sequence length 4096, and fp16 weights, that is roughly 1 GB per request. Serve 50 concurrent users and you have burned 50 GB of VRAM just for caches. This is why paged attention, prefix sharing across requests, and quantization of the cache itself ([KIVI](https://arxiv.org/abs/2402.02750) and similar) are such hot research topics.

If you ever debug an OOM that "should not happen" given the model size, the KV cache is the first place to look.

## Key Takeaways

- Inference has four stages: tokenize, prefill, decode, detokenize. Production systems optimize each one differently.
- The KV cache is what makes streaming generation cheap. Without it, generating n tokens is O(n²) instead of O(n).
- Prefill is compute-bound, decode is memory-bound. Many production optimizations (quantization, speculative decoding, continuous batching) target the decode phase specifically.
- Tokenization matters. GPT-2's byte-level BPE looks strange but is robust to arbitrary input — and a buggy tokenizer will silently corrupt your outputs.
- A 200-line Python engine is enough to demystify the whole stack. The leap from this to vLLM is engineering, not magic.

## Further Reading

- [The Illustrated Transformer — Jay Alammar](https://jamasth.github.io/illustrated-transformer/) — the clearest visual walkthrough of the attention mechanism.
- [Attention Is All You Need — Vaswani et al., 2017](https://arxiv.org/abs/1706.03762) — the original transformer paper, still the best reference for the architecture.
- [vLLM: Efficient Memory Management for LLM Serving with PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html) — the blog post that introduced PagedAttention.
- [Hugging Face Text Generation Inference documentation](https://huggingface.co/docs/text-generation-inference/en/index) — a production-grade Rust + Python serving stack worth studying.
- [Andrej Karpathy's "Let's build GPT: from scratch, in code"](https://www.youtube.com/watch?v=kCc8FmEb1nY) — the video that inspired the hands-on style of this post, with a full GPT training walkthrough in pure Python.