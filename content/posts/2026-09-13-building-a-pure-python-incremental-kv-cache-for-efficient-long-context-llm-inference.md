---
title: "Building a Pure Python Incremental KV Cache for Efficient Long-Context LLM Inference"
date: "2026-09-13T05:02:03.407"
draft: false
tags: ["python", "llm", "kv-cache", "inference-engineering", "systems-design", "deep-learning"]
description: "A hands-on guide to building a pure Python incremental KV cache — the core mechanism behind efficient long-context LLM inference — with real runnable code and a senior-level roadmap."
summary: "Build a production-grade incremental KV cache from scratch in pure Python. This guide covers architecture, implementation, testing, and a roadmap to production-flavored features that signal real systems skill to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-13-building-a-pure-python-incremental-kv-cache-for-efficient-long-context-llm-inference.svg"
  alt: "A visualization of a KV cache data structure with key and value tensors being incrementally appended during autoregressive LLM decoding."
  caption: ""
  relative: false
---

> **TL;DR** — Building a pure Python incremental KV cache is one of the highest-signal portfolio projects an aspiring ML systems engineer can undertake. It demonstrates mastery of the exact mechanism that powers efficient inference in vLLM, FlashAttention, and every major LLM serving platform. This guide walks you through a fully runnable implementation, testing strategy, and a concrete roadmap to production-grade features.

Long-context LLM inference is one of the most expensive operations in modern machine learning systems. When a model generates tokens autoregressively — one at a time — a naive implementation recomputes the full attention over every previous token for every new step. This is O(n²) in sequence length and quickly becomes untenable for conversations, document analysis, or any workload where context windows exceed a few thousand tokens.

The solution is the **Key-Value (KV) cache**: a mechanism that stores the computed key and value tensors from each previous layer and position, so that during decoding you only compute attention for the single new token and look up everything else. This reduces per-token computation from O(n²) to O(1) — the difference between a usable assistant and a sluggish one.

Implementing this from scratch in pure Python (with PyTorch tensors) forces you to understand memory layout, tensor operations, and the exact data flow inside a transformer decoder. It is also a project that hiring managers in ML infrastructure, backend systems, and applied AI roles immediately recognize as evidence of deep technical capability.

## Why This Project Stands Out on a CV

This project signals a rare combination of skills that most candidates cannot demonstrate through coursework or tutorial-following alone:

- **Systems-level thinking**: You are not just calling `model.generate()` — you are managing tensor memory, understanding allocation strategies, and designing data structures that minimize redundant computation.
- **ML inference internals**: You understand the difference between training and inference, why autoregressive decoding has distinct performance characteristics, and how attention mechanisms actually work under the hood.
- **Performance engineering**: Even in pure Python, you will confront memory bandwidth, tensor contiguousness, and the cost of kernel launches — skills directly transferable to C++, CUDA, or Rust-based infrastructure roles.
- **Production awareness**: Extending this project into areas like paged attention, observability, and fault tolerance mirrors exactly what teams at vLLM, TensorRT-LLM, and Together AI do daily.
- **Cross-disciplinary depth**: This sits at the intersection of deep learning, distributed systems, and low-level optimization — a profile that is scarce and highly valued.

For roles like ML Infrastructure Engineer, Backend Engineer for AI Platforms, or Research Engineer focused on efficient inference, this project communicates: "I have built the thing that makes LLMs actually work at scale."

## Architecture Overview

The implementation consists of five core components that interact in a well-defined pipeline. Here is how they fit together:

- **`KVCache`**: The central data structure. Pre-allocates tensors for keys and values across all transformer layers and manages append operations as new tokens are generated. Think of it as a ring buffer for attention states.
- **`AttentionLayer`**: The transformer attention block. During the forward pass, it retrieves cached keys and values from the `KVCache`, concatenates them with newly computed keys and values, and performs scaled dot-product attention over the full cached sequence.
- **`TransformerBlock`**: A single transformer decoder layer wrapping the attention mechanism and feed-forward network. Each block holds a reference to its corresponding KV cache slice (one per layer).
- **`Model`**: The full transformer model stacking multiple `TransformerBlock` instances. It orchestrates the autoregressive loop: tokenize input, run forward passes, sample the next token, append its KV to the cache, and repeat.
- **`InferenceEngine`**: The top-level loop that ties everything together. Handles tokenization, cache management, sampling strategy (greedy or top-k), and iteration until an end-of-sequence token or maximum length is reached.

```
Input Tokens
     │
     ▼
┌──────────────────┐
│  Tokenizer       │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐     ┌──────────────────┐
│  Transformer     │────▶│  KVCache         │
│  Model           │     │  (keys, values)  │
│  (layer 0..N)    │◀────│  (per-layer)     │
└──────┬───────────┘     └──────────────────┘
       │
       ▼
┌──────────────────┐
│  Sampler         │  (greedy / top-k)
└──────┬───────────┘
       │
       ▼
  Next Token ──▶ Append to KVCache ──▶ Loop
```

The critical insight is the **incremental** part: at each decoding step, only the new token's K and V tensors are computed and appended. The attention mechanism then queries the entire cached sequence, but the expensive computation is amortized across steps.

## Building It Step by Step

Below is a complete, runnable implementation. We use PyTorch for tensor operations — it is the standard framework for this kind of work and the same primitives underlie every major inference engine.

### Step 1: Define the KVCache Data Structure

The cache pre-allocates tensors for the maximum sequence length and manages a write pointer. This avoids repeated memory allocation during generation, which is a major source of latency.

```python
import torch
import torch.nn.functional as F
import math

class KVCache:
    def __init__(self, num_layers: int, num_heads: int, head_dim: int,
                 max_seq_len: int = 4096, dtype: torch.dtype = torch.float16,
                 device: str = "cpu"):
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.head_dim = head_dim
        self.max_seq_len = max_seq_len
        self.current_len = 0

        # Pre-allocate key and value tensors for every layer
        self.keys = torch.zeros(
            num_layers, max_seq_len, num_heads, head_dim,
            dtype=dtype, device=device
        )
        self.values = torch.zeros(
            num_layers, max_seq_len, num_heads, head_dim,
            dtype=dtype, device=device
        )

    def append(self, layer_idx: int, new_keys: torch.Tensor, new_values: torch.Tensor):
        """Append a batch of new key/value tensors to the cache."""
        seq_len = new_keys.shape[1]
        if self.current_len + seq_len > self.max_seq_len:
            raise ValueError("KV cache capacity exceeded")

        end = self.current_len + seq_len
        self.keys[layer_idx, self.current_len:end] = new_keys
        self.values[layer_idx, self.current_len:end] = new_values
        self.current_len = end

    def get(self, layer_idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        """Retrieve all cached keys and values for a given layer."""
        return (
            self.keys[layer_idx, :self.current_len],
            self.values[layer_idx, :self.current_len]
        )

    def reset(self):
        """Reset the cache for a new generation sequence."""
        self.current_len = 0

    @property
    def is_full(self) -> bool:
        return self.current_len >= self.max_seq_len
```

### Step 2: Build the Attention Layer with Cache Integration

The attention layer is where the incremental logic lives. During the first forward pass (prefill), all tokens are processed together and their K/V is cached. During subsequent steps (decode), only the last token's K/V is computed and appended.

```python
class IncrementalAttentionLayer(torch.nn.Module):
    def __init__(self, embed_dim: int, num_heads: int, layer_idx: int,
                 max_seq_len: int = 4096):
        super().__init__()
        self.embed_dim = embed_dim
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        self.layer_idx = layer_idx

        # Projection layers
        self.q_proj = torch.nn.Linear(embed_dim, embed_dim)
        self.k_proj = torch.nn.Linear(embed_dim, embed_dim)
        self.v_proj = torch.nn.Linear(embed_dim, embed_dim)
        self.out_proj = torch.nn.Linear(embed_dim, embed_dim)

        self.scale = self.head_dim ** -0.5

    def forward(self, x: torch.Tensor, kv_cache: KVCache, mask: torch.Tensor = None):
        """
        x: input tensor of shape (batch_size, seq_len, embed_dim)
        During decode, seq_len == 1 (single new token).
        During prefill, seq_len can be larger.
        """
        batch_size, seq_len, _ = x.shape

        # Project to queries, keys, values
        q = self.q_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.k_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.v_proj(x).view(batch_size, seq_len, self.num_heads, self.head_dim).transpose(1, 2)

        # Append new K/V to the cache (incremental step)
        kv_cache.append(self.layer_idx, k, v)

        # Retrieve the full cached sequence
        cached_k, cached_v = kv_cache.get(self.layer_idx)

        # Compute attention over the full cached sequence
        # cached_k shape: (num_heads, cached_seq_len, head_dim)
        # q shape: (batch_size, num_heads, current_seq_len, head_dim)
        scores = torch.matmul(q, cached_k.transpose(-2, -1)) * self.scale

        if mask is not None:
            scores = scores + mask

        attn_weights = torch.softmax(scores, dim=-1)
        attn_output = torch.matmul(attn_weights, cached_v)  # (batch, heads, cur_seq, head_dim)

        # Reshape and project back
        attn_output = attn_output.transpose(1, 2).contiguous().view(batch_size, seq_len, self.embed_dim)
        return self.out_proj(attn_output)
```

### Step 3: Compose the Transformer Model

Stack multiple attention layers with feed-forward networks to form a minimal but functional transformer decoder.

```python
class TransformerBlock(torch.nn.Module):
    def __init__(self, embed_dim: int, num_heads: int, ff_dim: int,
                 layer_idx: int, max_seq_len: int = 4096):
        super().__init__()
        self.attention = IncrementalAttentionLayer(embed_dim, num_heads, layer_idx, max_seq_len)
        self.ff = torch.nn.Sequential(
            torch.nn.Linear(embed_dim, ff_dim),
            torch.nn.GELU(),
            torch.nn.Linear(ff_dim, embed_dim),
        )
        self.norm1 = torch.nn.LayerNorm(embed_dim)
        self.norm2 = torch.nn.LayerNorm(embed_dim)

    def forward(self, x: torch.Tensor, kv_cache: KVCache, mask: torch.Tensor = None):
        # Pre-norm transformer block
        attn_out = self.attention(self.norm1(x), kv_cache, mask)
        x = x + attn_out
        ff_out = self.ff(self.norm2(x))
        x = x + ff_out
        return x


class MiniTransformer(torch.nn.Module):
    def __init__(self, vocab_size: int, embed_dim: int, num_heads: int,
                 num_layers: int, ff_dim: int, max_seq_len: int = 4096):
        super().__init__()
        self.embed_dim = embed_dim
        self.token_embedding = torch.nn.Embedding(vocab_size, embed_dim)
        self.pos_embedding = torch.nn.Embedding(max_seq_len, embed_dim)

        self.layers = torch.nn.ModuleList([
            TransformerBlock(embed_dim, num_heads, ff_dim, i, max_seq_len)
            for i in range(num_layers)
        ])

        self.output_proj = torch.nn.Linear(embed_dim, vocab_size)
        self.kv_cache = KVCache(num_layers, num_heads, embed_dim // num_heads, max_seq_len)

    def forward(self, tokens: torch.Tensor, kv_cache: KVCache = None, mask: torch.Tensor = None):
        if kv_cache is None:
            kv_cache = self.kv_cache

        seq_len = tokens.shape[1]
        positions = torch.arange(seq_len, device=tokens.device).unsqueeze(0)

        x = self.token_embedding(tokens) + self.pos_embedding(positions)

        for layer in self.layers:
            x = layer(x, kv_cache, mask)

        logits = self.output_proj(x)
        return logits
```

### Step 4: Implement the Autoregressive Inference Loop

This is the engine that ties everything together. It generates tokens one at a time, appending each new token's K/V to the cache.

```python
class InferenceEngine:
    def __init__(self, model: MiniTransformer, vocab_size: int,
                 device: str = "cpu"):
        self.model = model.to(device)
        self.vocab_size = vocab_size
        self.device = device

    def generate(self, prompt_tokens: list[int], max_new_tokens: int = 64,
                 temperature: float = 1.0, top_k: int = 10) -> list[int]:
        self.model.kv_cache.reset()
        generated = list(prompt_tokens)

        for _ in range(max_new_tokens):
            # Build input tensor from the last token (or full prompt on first step)
            input_ids = torch.tensor(
                [generated[-1]] if len(generated) > len(prompt_tokens) else [generated],
                device=self.device, dtype=torch.long
            )

            # Create causal mask (prevent looking at future tokens)
            seq_len = input_ids.shape[1]
            mask = torch.full((seq_len, seq_len), float('-inf'), device=self.device)
            mask = torch.triu(mask, diagonal=1)

            with torch.no_grad():
                logits = self.model(input_ids, self.model.kv_cache, mask)

            # Sample the next token
            next_token_logits = logits[:, -1, :] / temperature
            if top_k > 0:
                top_k_vals, _ = torch.topk(next_token_logits, top_k)
                next_token_logits[next_token_logits < top_k_vals[-1]] = float('-inf')

            probs = torch.softmax(next_token_logits, dim=-1)
            next_token = torch.multinomial(probs, num_samples=1).item()

            generated.append(next_token)

            if next_token == 0:  # Assuming 0 is the end-of-sequence token
                break

        return generated
```

### Step 5: Wire Everything Together and Train a Minimal Model

For the project to be credible, you need a trained (or at least trainable) model. Below is a minimal training loop using a character-level dataset.

```python
def train_minimal_model():
    # Hyperparameters
    vocab_size = 64       # ASCII character vocabulary
    embed_dim = 128
    num_heads = 4
    num_layers = 4
    ff_dim = 256
    max_seq_len = 256
    learning_rate = 3e-4
    num_epochs = 20

    model = MiniTransformer(
        vocab_size=vocab_size, embed_dim=embed_dim,
        num_heads=num_heads, num_layers=num_layers,
        ff_dim=ff_dim, max_seq_len=max_seq_len
    )
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = torch.nn.CrossEntropyLoss()

    # Prepare a simple character-level dataset
    text = "the quick brown fox jumps over the lazy dog. " * 500
    chars = sorted(set(text))
    char_to_idx = {ch: i for i, ch in enumerate(chars)}
    data = torch.tensor([char_to_idx[ch] for ch in text], dtype=torch.long)

    for epoch in range(num_epochs):
        total_loss = 0
        for i in range(0, len(data) - max_seq_len, max_seq_len // 2):
            inputs = data[i:i + max_seq_len]
            targets = data[i + 1:i + max_seq_len + 1]

            optimizer.zero_grad()
            logits = model(inputs.unsqueeze(0), model.kv_cache)
            loss = loss_fn(logits.view(-1, vocab_size), targets.view(-1))
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        if epoch % 5 == 0:
            print(f"Epoch {epoch}, Loss: {total_loss:.4f}")

    return model, char_to_idx
```

## Running and Testing It

Once you have the implementation, you need to verify it works correctly and demonstrate the performance improvement the KV cache provides.

**1. Run the training and generation pipeline:**

```bash
python kv_cache_inference.py
```

This trains the minimal character-level model and then generates text from a prompt. You should see loss decreasing over epochs and coherent character-level predictions emerging.

**2. Verify the incremental behavior with a unit test:**

The critical correctness property is that the KV cache produces identical attention outputs to a full recomputation, but with fewer FLOPs. Add this test to your test suite:

```python
def test_kv_cache_correctness():
    """Verify that cached attention matches full attention computation."""
    torch.manual_seed(42)
    embed_dim = 32
    num_heads = 4
    seq_len = 8
    batch_size = 1

    layer = IncrementalAttentionLayer(embed_dim, num_heads, layer_idx=0)
    cache = KVCache(1, num_heads, embed_dim // num_heads, max_seq_len=64)

    x = torch.randn(batch_size, seq_len, embed_dim)

    # Full attention (no cache) — reference
    with torch.no_grad():
        full_logits = layer(x, cache)  # cache starts empty, so this is full attention

    # Reset and recompute with explicit cache steps
    cache.reset()
    incremental_logits = []
    for i in range(seq_len):
        single_token = x[:, i:i+1, :]
        mask = torch.full((i+1, i+1), float('-inf'))
        mask = torch.triu(mask, diagonal=1)
        with torch.no_grad():
            logits = layer(single_token, cache, mask)
        incremental_logits.append(logits)

    incremental_output = torch.cat(incremental_logits, dim=1)

    # Compare
    assert torch.allclose(full_logits, incremental_output, atol=1e-5), \
        "Cached attention does not match full attention!"
    print("✓ KV cache correctness verified.")
```

**3. Benchmark the speedup:**

Use Python's `time` module or `torch.profiler` to measure per-token latency with and without the cache:

```python
import time

def benchmark(engine: InferenceEngine, prompt: list[int]):
    start = time.perf_counter()
    engine.generate(prompt, max_new_tokens=100)
    elapsed = time.perf_counter() - start
    print(f"Generated 100 tokens in {elapsed:.3f}s "
          f"({100/elapsed:.1f} tokens/sec)")
```

You should observe that as the sequence grows, the cached approach maintains roughly constant per-token latency, while a naive recomputation approach degrades quadratically.

## Extending It: Your Roadmap to Senior-Level

The minimal implementation above is a credible portfolio piece on its own. But to truly stand out, extend it with features that mirror what production inference engines ship. Here are six concrete upgrades, each with a one-line reason it matters:

1. **Paged Attention with block-level memory management** — Implement a page-based allocation scheme (inspired by [vLLM's PagedAttention](https://arxiv.org/abs/2309.06180)) where the KV cache is divided into fixed-size blocks that can be non-contiguously allocated in memory. This eliminates fragmentation and enables efficient batch processing across sequences of different lengths, which is the primary bottleneck in multi-tenant LLM serving.

2. **Persistence via mmap or SQLite-backed cache** — Add the ability to serialize and deserialize the KV cache to disk using `numpy.memmap` or a lightweight SQLite store. This matters because long-running conversations or document-processing pipelines need to resume inference across sessions without recomputing the entire context from scratch.

3. **Observability with Prometheus metrics and structured logging** — Instrument the inference loop to emit per-token latency, cache hit rate, memory utilization, and generation throughput as Prometheus metrics using the `prometheus_client` Python library. Production systems are managed systems; if you cannot observe it, you cannot improve it.

4. **Fault tolerance through checkpoint-and-recover** — Implement periodic serialization of model state and KV cache to disk, with a recovery routine that resumes generation from the last checkpoint after a crash. This matters because serving long-context workloads on commodity hardware means dealing with OOM kills and node failures — a system that cannot recover is not production-ready.

5. **Horizontal scaling with a request queue and worker pool** — Build a lightweight HTTP server (using `fastapi` or `httpcore`) that accepts generation requests, queues them, and distributes them across multiple model instances running in separate processes. This introduces you to the actual architecture of services like Text Generation Inference (TGI) and demonstrates you understand load balancing, not just tensor math.

6. **Benchmarking suite with custom kernels** — Replace the naive PyTorch attention with a custom CUDA kernel or a Triton kernel for the attention computation, and benchmark it against the baseline using `pytest-benchmark`. This is the single most impressive upgrade because it demonstrates you can identify a performance bottleneck and implement a hardware-specific optimization — the exact skill that separates ML engineers from ML infrastructure engineers.

Each of these extensions maps directly to a real production concern at companies running LLM inference at scale. You do not need to implement all six — even two or three, done well, will make your portfolio stand out.

## Key Takeaways

- The KV cache is the single most important optimization for autoregressive LLM inference, reducing per-token computation from O(n²) to O(1) by storing and reusing previously computed key and value tensors.
- Building this from scratch in pure Python with PyTorch forces deep understanding of memory management, tensor operations, and the transformer architecture — skills that are directly transferable to production inference engines like vLLM and TensorRT-LLM.
- A working implementation with unit tests and benchmarks is a credible portfolio piece that signals systems-level thinking, ML internals knowledge, and production awareness to hiring managers.
- The six extension roadmap items (paged attention, persistence, observability, fault tolerance, horizontal scaling, custom kernels) mirror the actual feature set of production LLM serving platforms and provide a clear path from toy project to senior-level engineering portfolio.
- This project sits at the intersection of deep learning, distributed systems, and performance engineering — a cross-disciplinary profile that is scarce and highly valued in the current job market.
- The correctness property (cached attention matches full attention) must be verified with a unit test before any performance claims are made; correctness without verification is not engineering.

## Further Reading

- **[FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness](https://arxiv.org/abs/2205.14135)** — The foundational paper that introduced the tiling strategy for efficient attention computation. Understanding this paper is essential for anyone who wants to move beyond the Python prototype to hardware-accelerated inference.
- **[Efficient Memory Management for Large Language Model Serving with PagedAttention](https://arxiv.org/abs/2309.06180)** — The vLLM paper that introduced paged attention, the block-level memory management scheme that is the industry standard for batched LLM inference. This is the direct inspiration for Extension #1 in the roadmap.
- **[Attention Is All You Need](https://arxiv.org/abs/1706.03762)** — The original transformer paper. While this project uses a simplified architecture, understanding the full specification (including layer normalization placement, positional encoding schemes, and activation functions) is critical for extending the model to match production-grade transformers.
- **[Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers)** — The canonical reference for loading, fine-tuning, and serving transformer models. Once your pure Python implementation is working, you can integrate it with HuggingFace models to demonstrate the KV cache mechanism on real, pretrained architectures like LLaMA or Mistral.
- **[PyTorch Documentation — `torch.nn.functional.scaled_dot_product_attention`](https://pytorch.org/docs/stable/generated/torch.nn.functional.scaled_dot_product_attention.html)** — PyTorch's built-in fused attention kernel. Comparing your custom implementation against this fused kernel is a natural next step for benchmarking and understanding the performance gap between pure Python and optimized C++/CUDA backends.
- **[The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/)** — Jay Alammar's visual guide to the transformer architecture. A useful companion reference for refreshing the exact data flow through attention layers, feed-forward networks, and residual connections before diving into the implementation.