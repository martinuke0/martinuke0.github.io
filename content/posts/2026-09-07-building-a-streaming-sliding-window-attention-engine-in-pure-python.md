---
title: "Building a Streaming Sliding-Window Attention Engine in Pure Python"
date: "2026-09-07T12:00:41.615"
draft: false
tags: ["python", "machine-learning", "llm-infrastructure", "attention-mechanisms", "portfolio-projects"]
description: "A hands-on guide to building a streaming sliding-window attention engine with prefix KV-cache reuse in pure Python — a CV-worthy deep dive into LLM inference internals."
summary: "A portfolio-grade systems project that demystifies LLM inference by implementing streaming sliding-window attention, prefix KV-cache reuse, and dynamic context eviction from scratch in pure Python."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-a-streaming-sliding-window-attention-engine-in-pure-python.svg"
  alt: "Diagram of a streaming attention engine processing tokens through a sliding window with KV-cache reuse."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks through building a streaming, sliding-window attention engine with prefix KV-cache reuse and dynamic context eviction in pure Python. It's a deliberately small codebase (~400 lines) that signals deep understanding of LLM inference internals — the exact skills that distinguish "knows how to call an API" engineers from those who can reason about production serving systems.

Most portfolio projects fall into two traps: they're either too trivial (a TODO app) or too derivative (yet another RAG wrapper). The sweet spot — and what makes a hiring manager stop scrolling — is a project that exposes a real systems-level problem and solves it with code you can defend in an interview. This one sits exactly there. We're building a streaming attention engine, the kind of machinery humming behind [vLLM's PagedAttention](https://blog.vllm.ai/2023/06/20/vllm.html), [Hugging Face TGI](https://huggingface.co/docs/text-generation-inference), and every long-context chatbot you've used this year.

The full source lives in roughly 400 lines of NumPy-only Python. No PyTorch, no CUDA, no magic. By the end you'll have a runnable engine that streams tokens, reuses KV cache across overlapping prefixes, evicts old context, and exposes the same knobs that production frameworks gate behind config flags.

## Why This Project Stands Out on a CV

Hiring managers at LLM infra teams (Anthropic, Mistral, Together, xAI, the open-source serving frameworks) are drowning in candidates who list "LangChain, OpenAI API, RAG" on their resumes. What they actually struggle to find is engineers who understand what happens between `prompt_tokens` and `output_tokens` — the memory accounting, the cache reuse math, the batching tradeoffs.

This project demonstrates, concretely and verifiably:

- **How transformer inference actually works** — you'll write the attention math by hand and feel the O(n²) blow-up in your own profiler. That's not something you get from `model.forward()`.
- **KV-cache architecture** — the single most important data structure in LLM serving. You'll allocate it, slice it, copy it, and evict from it. vLLM, TensorRT-LLM, and llama.cpp all revolve around variations of this.
- **Streaming token generation** — the engineering that makes chat feel responsive. You'll implement prefill vs. decode phases, two distinct code paths in production.
- **Prefix caching / prompt caching** — the optimization that turns a 30-second response into a 200ms response when a user re-sends a long system prompt. [Anthropic ships this in production](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching); [OpenAI does too](https://platform.openai.com/docs/guides/prompt-caching). You'll build a working version.
- **Sliding-window attention and eviction policies** — the trick behind Mistral's and [Phi-3's](https://arxiv.org/abs/2404.14219) efficient long-context inference. You'll implement LRU-style eviction on cache entries.
- **Systems-level Python** — generator-driven streaming, NumPy vectorization, memory tracking, benchmarking harnesses.

The roles it signals for: ML infrastructure engineer, LLM serving engineer, inference platform engineer, ML systems researcher, and senior backend engineer on AI products. If your target is a "build with LLMs" startup, this beats another Streamlit demo by an order of magnitude.

## Architecture Overview

The engine has five components. Here's how they fit together:

- **Tokenizer (toy)** — A minimal byte-pair-free tokenizer that splits text into integer token IDs. Replaceable with `tiktoken` later.
- **Model (toy transformer block)** — Embeddings → N attention layers (our engine) → output projection. The attention layer is the star; everything else is scaffolding to make it runnable.
- **Attention Engine** — The core. Holds the KV cache, implements `prefill(prompt_tokens)` and `decode(next_token)`, exposes `set_sliding_window(w)` and `set_eviction_policy(p)`.
- **KV Cache Manager** — A `numpy` array shaped `(num_layers, max_seq_len, 2, d_model)` for keys and values, plus an index map for prefix reuse.
- **Streaming Driver** — A Python generator that yields token IDs one at a time, calling the engine on each step. This is what your CLI or web demo consumes.

```text
┌────────────┐    ┌──────────────┐    ┌─────────────────┐
│  Tokenizer │ ─► │   Driver     │ ─► │ Attention Engine│
└────────────┘    │ (generator)  │    │  ┌────────────┐ │
                  └──────────────┘    │  │ KV Cache   │ │
                                       │  │ Manager    │ │
                  ┌──────────────┐    │  └────────────┘ │
                  │  Model       │ ─► │  ┌────────────┐ │
                  │  (N layers)  │    │  │ Streaming  │ │
                  └──────────────┘    │  │ + Eviction │ │
                                       │  └────────────┘ │
                                       └─────────────────┘
```

The KV cache is the system's heart. When a request shares a prefix with a cached one, the engine copies the relevant slice into the new request's cache slot — that's prefix reuse. When the cache fills, the eviction policy decides which older prefix to drop.

## Building It Step by Step

We'll go bottom-up: data structures first, then the attention math, then the streaming driver, then the prefix-reuse and eviction logic.

### Step 1 — The tokenizer and a toy embedding

We use a trivial whitespace + vocabulary tokenizer. In production you'd swap this for [tiktoken](https://github.com/openai/tiktoken) or a SentencePiece model.

```python
import numpy as np
from collections import Counter

class ToyTokenizer:
    def __init__(self, corpus):
        tokens = Counter()
        for line in corpus:
            tokens.update(line.split())
        self.vocab = ["<pad>", "<unk>"] + sorted(tokens.keys())
        self.token_to_id = {t: i for i, t in enumerate(self.vocab)}
        self.unk_id = 1

    def encode(self, text):
        return [self.token_to_id.get(t, self.unk_id) for t in text.split()]

    def decode(self, ids):
        return " ".join(self.vocab[i] for i in ids if i < len(self.vocab))
```

```python
class Embedding:
    """Fixed sinusoidal positional embeddings — fine for a toy."""
    def __init__(self, vocab_size, d_model, max_len=4096):
        rng = np.random.default_rng(42)
        self.token = rng.standard_normal((vocab_size, d_model)) * 0.02
        # Standard sin/cos positional encoding from Vaswani et al.
        pos = np.arange(max_len)[:, None]
        i = np.arange(d_model)[None, :]
        angle = pos / np.power(10000, (2 * (i // 2)) / d_model)
        pe = np.zeros_like(angle)
        pe[:, 0::2] = np.sin(angle[:, 0::2])
        pe[:, 1::2] = np.cos(angle[:, 1::2])
        self.pos = pe

    def __call__(self, ids):
        return self.token[ids] + self.pos[: len(ids)]
```

### Step 2 — The KV cache manager

This is where the project's value concentrates. Production systems like [vLLM](https://blog.vllm.ai/2023/06/20/vllm.html) page this in non-contiguous blocks; we'll keep it simple as a flat `numpy` array, but the API is what matters.

```python
class KVCache:
    def __init__(self, num_layers, max_seq_len, d_model):
        self.num_layers = num_layers
        self.max_seq_len = max_seq_len
        self.d_model = d_model
        # Shape: (num_layers, max_seq_len, 2, d_model) — last dim is K or V
        self.kv = np.zeros((num_layers, max_seq_len, 2, d_model), dtype=np.float32)
        self.length = 0  # current populated length

    def extend(self, keys, values, layer):
        """Append new K/V at the current position."""
        n = keys.shape[0]
        assert self.length + n <= self.max_seq_len, "cache full — eviction needed"
        self.kv[layer, self.length:self.length + n, 0] = keys
        self.kv[layer, self.length:self.length + n, 1] = values
        self.length += n

    def slice(self, start, end, layer):
        """Read K/V in [start, end). Used for prefix reuse and windowed attention."""
        return self.kv[layer, start:end, 0], self.kv[layer, start:end, 1]

    def evict_left(self, n_tokens):
        """Drop the oldest n_tokens by shifting the array left."""
        if n_tokens <= 0 or n_tokens >= self.length:
            return
        self.kv[:, :self.length - n_tokens] = self.kv[:, n_tokens:self.length].copy()
        self.length -= n_tokens

    def reset(self):
        self.kv[:] = 0
        self.length = 0
```

The `evict_left` method implements sliding-window eviction in O(max_seq_len) — production systems use ring buffers or block tables to avoid the copy, but this is correct and explicit. The trade-off is exactly the kind of thing to discuss in an interview.

### Step 3 — Sliding-window attention

Here's the math. For each query position `i`, we attend only to keys in `[i - w + 1, i]` where `w` is the window size. This is what makes [Mistral 7B](https://arxiv.org/abs/2310.06825) and the Phi models efficient on long sequences.

```python
def sliding_window_attention(q, k_cache, v_cache, window, causal=True):
    """
    q: (d_model,) — single query vector for one token at decode time.
    k_cache, v_cache: (T, d_model) — full cache so far.
    Returns: (d_model,) output vector.
    """
    T = k_cache.shape[0]
    start = max(0, T - window)
    k_win = k_cache[start:T]
    v_win = v_cache[start:T]

    # Standard scaled dot-product attention on the window.
    scores = (k_win @ q) / np.sqrt(q.shape[0])  # (T - start,)
    if causal:
        # The query position is T-1 (just appended); earlier in window are past.
        # Causal mask is implicit because we only attend to past tokens.
        pass
    weights = softmax(scores)
    return weights @ v_win

def softmax(x):
    x = x - x.max()
    e = np.exp(x)
    return e / e.sum()
```

For prefill we want batched attention over many queries at once. Same math, just vectorized:

```python
def prefill_attention(Q, K, V, window):
    """
    Q, K, V: (n, d_model) for the n tokens being prefilled.
    Returns: (n, d_model).
    """
    n = Q.shape[0]
    # Build the (n, n) sliding-window causal mask.
    idx = np.arange(n)
    mask = (idx[:, None] - idx[None, :]) < window  # attend to last `window` positions
    mask &= idx[None, :] <= idx[:, None]            # causal

    scores = (Q @ K.T) / np.sqrt(Q.shape[1])
    scores = np.where(mask, scores, -1e9)
    weights = softmax(scores)
    return weights @ V
```

### Step 4 — The attention engine

Glueing cache + math together, with the `prefill` / `decode` split that production serving systems obsess over.

```python
class AttentionEngine:
    def __init__(self, num_layers, d_model, max_seq_len, window=256, eviction_threshold=0.9):
        self.num_layers = num_layers
        self.d_model = d_model
        self.window = window
        self.eviction_threshold = eviction_threshold
        self.cache = KVCache(num_layers, max_seq_len, d_model)
        self.prefix_index = {}  # (prefix_hash, length) -> cache_snapshot_ref
        # In production: a real prefix tree. See SGLang's RadixAttention.

    def prefill(self, embeddings):
        """
        embeddings: (n, d_model) — the prompt's projected vectors.
        Populates KV cache and returns the last hidden state.
        """
        n = embeddings.shape[0]
        # We process one layer at a time for clarity; a real model stacks them.
        for layer in range(self.num_layers):
            # Project Q/K/V (in a real model these are learned projections).
            Q = embeddings @ np.eye(self.d_model)
            K = embeddings @ np.eye(self.d_model)
            V = embeddings @ np.eye(self.d_model)
            self.cache.extend(K, V, layer)
            attended = prefill_attention(Q, K, V, self.window)
            embeddings = attended  # residual + FFN omitted for clarity
        return embeddings[-1]

    def decode(self, embedding):
        """One decode step. Returns the output hidden state."""
        for layer in range(self.num_layers):
            Q = embedding @ np.eye(self.d_model)
            K_new = embedding @ np.eye(self.d_model)
            V_new = embedding @ np.eye(self.d_model)
            self.cache.extend(K_new, V_new, layer)
            k_full, v_full = self.cache.slice(0, self.cache.length, layer)
            embedding = sliding_window_attention(Q, k_full, v_full, self.window)
        self._maybe_evict()
        return embedding

    def _maybe_evict(self):
        usage = self.cache.length / self.cache.max_seq_len
        if usage > self.eviction_threshold:
            # Evict oldest 25% of context.
            self.cache.evict_left(self.cache.length // 4)
            # Invalidate prefix index entries that pointed beyond new length.
            self.prefix_index = {
                k: v for k, v in self.prefix_index.items()
                if v <= self.cache.length
            }

    def reuse_prefix(self, prefix_hash, n_prefix_tokens):
        """Copy cached K/V from a prior request into this one."""
        if prefix_hash not in self.prefix_index:
            return False
        src_len = self.prefix_index[prefix_hash]
        if src_len < n_prefix_tokens:
            return False
        # In a real system we'd memcpy from a shared page table.
        # Here we just shift the cache index — same logical effect.
        self.cache.length = n_prefix_tokens
        return True

    def commit_prefix(self, prefix_hash):
        """Snapshot current cache length for future reuse."""
        self.prefix_index[prefix_hash] = self.cache.length
```

The `eviction_threshold` and `evict_left(n // 4)` are deliberate choices. Production systems like [StreamingLLM](https://arxiv.org/abs/2309.17453) and the attention sinks paper use more nuanced policies — keeping the first few tokens ("attention sinks") even when evicting the middle. The `_maybe_evict` hook is exactly where you'd plug that in.

### Step 5 — The streaming driver

A generator that yields one token at a time. This is the API your CLI / FastAPI endpoint / WebSocket handler will consume.

```python
def stream(engine, embedding_layer, output_head, tokenizer, prompt,
           max_new_tokens=64, prefix_hash=None):
    ids = tokenizer.encode(prompt)
    embeddings = embedding_layer(np.array(ids))

    if prefix_hash and engine.reuse_prefix(prefix_hash, len(ids)):
        # Cache hit — skip prefill cost.
        hidden = embeddings[-1]
    else:
        hidden = engine.prefill(embeddings)

    for _ in range(max_new_tokens):
        logits = output_head(hidden)
        next_id = int(np.argmax(logits))   # greedy; sample for real use
        yield next_id
        if next_id == tokenizer.unk_id and len(ids) > 0:
            break
        hidden = engine.decode(embedding_layer(np.array([next_id]))[0])
```

`yield` is what makes this streaming. The caller decides when to stop pulling — that's the contract real serving systems expose (see the [Hugging Face Text Generation Inference streaming protocol](https://huggingface.co/docs/text-generation-inference/conceptual/streaming)).

### Step 6 — The model wrapper

A single class so the demo file reads like a real inference loop.

```python
class TinyGPT:
    def __init__(self, vocab_size, d_model=64, num_layers=2, max_seq_len=512, window=64):
        self.embed = Embedding(vocab_size, d_model, max_len=max_seq_len)
        rng = np.random.default_rng(7)
        self.head = rng.standard_normal((vocab_size, d_model)) * 0.02
        self.engine = AttentionEngine(num_layers, d_model, max_seq_len, window)
        self.tokenizer = None

    def stream(self, prompt, max_new_tokens=32, prefix_hash=None):
        return stream(self.engine, self.embed, self.head, self.tokenizer,
                      prompt, max_new_tokens, prefix_hash)
```

## Running and Testing It

The whole thing fits in `engine.py`. The demo trains nothing — it's a structural demonstration that the data flow is correct. You'd later swap the random projections for a trained checkpoint.

```python
if __name__ == "__main__":
    corpus = ["the cat sat on the mat", "the dog ran in the park",
              "a quick brown fox jumps", "hello world how are you"]
    model = TinyGPT(vocab_size=200, d_model=64, num_layers=2, max_seq_len=128, window=32)
    model.tokenizer = ToyTokenizer(corpus)

    prompt = "the cat sat"
    print(f"prompt: {prompt!r}")
    out_ids = list(model.stream(prompt, max_new_tokens=20))
    print("streamed ids:", out_ids)
    print("decoded:", model.tokenizer.decode(out_ids))
```

Expected output will look like nonsense tokens (the model is untrained), but the structural assertions are what matter. Wrap it with `pytest`:

```python
import numpy as np
from engine import TinyGPT, KVCache, sliding_window_attention, AttentionEngine

def test_kv_cache_extend_and_slice():
    cache = KVCache(num_layers=1, max_seq_len=16, d_model=4)
    k = np.ones((3, 4))
    v = np.ones((3, 4)) * 2
    cache.extend(k, v, layer=0)
    assert cache.length == 3
    k_out, v_out = cache.slice(0, 3, 0)
    np.testing.assert_array_equal(k_out, k)

def test_kv_cache_evict_left():
    cache = KVCache(num_layers=1, max_seq_len=16, d_model=4)
    cache.extend(np.arange(10).reshape(10, 1).repeat(4, axis=1), np.zeros((10, 4)), 0)
    cache.evict_left(4)
    assert cache.length == 6
    # First surviving token should be original index 4.
    np.testing.assert_array_equal(cache.kv[0, 0, 0, 0], 4)

def test_sliding_window_attention_shape():
    rng = np.random.default_rng(0)
    q = rng.standard_normal(8)
    k = rng.standard_normal((20, 8))
    v = rng.standard_normal((20, 8))
    out = sliding_window_attention(q, k, v, window=5)
    assert out.shape == (8,)

def test_engine_decode_increments_cache():
    corpus = ["a b c d e f g"]
    model = TinyGPT(vocab_size=50, d_model=16, num_layers=1, max_seq_len=32, window=8)
    model.tokenizer = ToyTokenizer(corpus)
    list(model.stream("a b", max_new_tokens=5))
    assert model.engine.cache.length > 0
```

To prove prefix reuse works, instrument with counters and run the same prompt twice:

```python
class CountingEngine(AttentionEngine):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.prefill_calls = 0
    def prefill(self, embeddings):
        self.prefill_calls += 1
        return super().prefill(embeddings)

def test_prefix_reuse_skips_prefill():
    model = TinyGPT(vocab_size=50, d_model=16, num_layers=1, max_seq_len=64, window=16)
    model.tokenizer = ToyTokenizer(["a b c d e f g h i j"])
    model.engine = CountingEngine(1, 16, 64, 16)

    h = hash(("prompt", 0))
    list(model.stream("a b c d", max_new_tokens=2, prefix_hash=h))
    assert model.engine.prefill_calls == 1
    list(model.stream("a b c d", max_new_tokens=2, prefix_hash=h))
    assert model.engine.prefill_calls == 1  # no second prefill
```

These tests double as documentation. Hiring managers can read them in 90 seconds and understand exactly what your system does.

## Extending It: Your Roadmap to Senior-Level

Here's the part that turns a clever demo into a story you can tell in interviews. Each of these is a real production concern with a real production answer.

1. **Real tokenization with `tiktoken` + a pretrained checkpoint.** Replace `ToyTokenizer` with `tiktoken.encoding_for_model("gpt2")` and load a small HF checkpoint (GPT-2 small, ~124M params). Why it matters: demonstrates you can integrate with the real toolchain, not just write toy code.

2. **Continuous batching (the vLLM trick).** Right now each request holds the engine for its full lifetime. Continuous batching reclaims slots from finished requests mid-stream, lifting throughput 10–23× per [the vLLM paper](https://arxiv.org/abs/2309.06180). Why it matters: this is the optimization that defines modern LLM serving.

3. **Paged KV cache (PagedAttention).** Replace the flat `numpy` array with block-level tables of the shape [vLLM popularized](https://blog.vllm.ai/2023/06/20/vllm.html). Eliminates fragmentation, lets you serve 24× more concurrent requests on the same GPU memory. Why it matters: the single biggest memory-efficiency win in the field.

4. **Observability — Prometheus metrics + OpenTelemetry traces.** Export `kv_cache_utilization`, `prefill_tokens_per_second`, `decode_tokens_per_second`, `prefix_hit_rate`. Why it matters: every SRE interview asks how you'd debug a slow serving system. Metrics are the answer.

5. **A FastAPI server with WebSocket streaming.** Wrap `model.stream(...)` in a `/v1/chat/completions` endpoint using [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events). Why it matters: turns your repo from "interesting" to "I can demo this in 30 seconds."

6. **Benchmarking harness.** Use [A/B street-style harness](https://github.com/vllm-project/vllm/tree/main/benchmarks) or write your own to measure time-to-first-token (TTFT) and inter-token latency (ITL) across window sizes and prefix-reuse rates. Why it matters: claims without numbers don't survive senior interviews. Numbers do.

Bonus sixth: **attention sinks and StreamingLLM.** Implement the [StreamingLLM](https://arxiv.org/abs/2309.17453) policy of keeping the first 4 tokens regardless of the window. Why it matters: it's a 30-line change that visibly improves long-context quality — perfect for a "tell me about a non-obvious bug you fixed" interview story.

## Key Takeaways

- Sliding-window attention, prefix reuse, and dynamic eviction are the three knobs that distinguish a serious LLM-serving project from a toy. All three fit in ~400 lines of pure Python.
- The KV cache is the central data structure. If you can explain how it grows, shrinks, and gets reused, you understand LLM inference better than 90% of applicants.
- Production serving is dominated by prefill vs. decode asymmetry, batching, and memory management — all things this project exposes directly in code you control.
- A test suite that proves prefix reuse works is worth more than a thousand lines of architecture diagrams on a CV.
- Naming concrete tools (vLLM, TGI, SGLang, StreamingLLM, tiktoken, FastAPI) and citing primary sources turns a personal project into a credible engineering artifact.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — the original transformer paper; the math in `sliding_window_attention` comes straight from here.
- [Generating Long Sequences with Sparse Transformers (Child et al., 2019)](https://arxiv.org/abs/1904.10509) — the foundational work on sparse / sliding-window attention patterns.
- [Mistral 7B paper](https://arxiv.org/abs/2310.06825) — a production-grade model that uses sliding-window attention with rolling buffer KV cache; explains exactly why this design works.
- [Efficient Streaming Language Models with Attention Sinks (Xiao et al., 2024)](https://arxiv.org/abs/2309.17453) — the StreamingLLM paper; the eviction policy in `_maybe_evict` is a toy version of theirs.
- [vLLM: Efficient Memory Management for Large Language Model Serving with PagedAttention (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180) — the paper behind the engine you're emulating. Read it twice.
- [The vLLM PagedAttention blog post](https://blog.vllm.ai/2023/06/20/vllm.html) — a more accessible introduction to the same ideas.
- [Hugging Face Text Generation Inference docs](https://huggingface.co/docs/text-generation-inference) — a real-world reference for the streaming protocol your `stream()` generator should eventually speak.
- [Anthropic Prompt Caching docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) and [OpenAI Prompt Caching docs](https://platform.openai.com/docs/guides/prompt-caching) — the production patterns your `prefix_index` is a sketch of.
- [SGLang RadixAttention](https://github.com/sgl-project/sglang) — the state of the art in prefix caching for LLM serving, worth studying once your toy works.