

---
title: "Build a Minimal Transformer Inference Engine for Your Portfolio"
date: "2026-09-18T00:02:08.865"
draft: false
tags: ["transformer", "kv-cache", "tokenizer", "attention", "sampler"]
description: "Build a minimal transformer engine with KV cache, custom tokenizer, attention block, and sampler to showcase real systems skill."
summary: "A practical guide to building a minimal transformer inference engine with KV cache, tokenizer, attention, and sampler. It demonstrates systems skills that hiring managers look for."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-build-a-minimal-transformer-inference-engine-for-your-portfolio.svg"
  alt: "Minimal transformer engine illustration"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a minimal transformer inference engine from scratch, including a custom tokenizer, KV cache, attention block, and sampling logic. By the end you'll have a runnable Python project that demonstrates real systems skills to hiring managers.

In the current job market, simply listing “transformer experience” on a résumé is no longer enough. Hiring managers want evidence that you understand the underlying systems, not just how to call an API. This project gives you that evidence by implementing the core components of a transformer decoder—tokenization, attention with a KV cache, and token sampling—from scratch in Python.

## Why This Project Stands Out on a CV

- **From‑scratch implementation** – You’ll write a tokenizer, attention block, KV cache, and sampler yourself, proving you can build the pieces that most engineers only use as a black box.
- **Systems‑level thinking** – The KV cache forces you to manage memory, handle incremental updates, and reason about cache hits/misses—skills directly transferable to database and caching systems.
- **Performance awareness** – By profiling the attention computation and comparing naive vs. cached inference, you demonstrate the ability to measure and optimize critical paths.
- **End‑to‑end ownership** – Taking raw text through tokenization, model inference, and decoding mirrors the full pipeline of production LLM services, showcasing your ability to ship a complete feature.

These competencies map to roles such as **Machine Learning Engineer**, **Systems Engineer**, **Infrastructure Engineer**, or **Research Engineer** at companies that build or operate large‑scale AI services.

## Architecture Overview

The project is organized into five logical components:

1. **Tokenizer** – Converts raw text into integer token IDs using a learned vocabulary (word‑level or BPE).
2. **Embedding** – Looks up token embeddings and adds positional encodings.
3. **Transformer Block** – Contains a multi‑head self‑attention layer followed by a feed‑forward network (FFN).
4. **KV Cache** – Stores past key/value vectors so that each new token only attends to itself, enabling O(1) per‑step inference.
5. **Sampler** – Selects the next token given the model logits, supporting temperature, top‑k, and top‑p strategies.

Data flows as follows:

```
Text → Tokenizer → IDs → Embedding → [Transformer Block] × N → Logits → Sampler → Next Token
                              ↑_____________________↓
                                    KV Cache
```

The KV cache is updated after each forward pass, allowing subsequent tokens to reuse previously computed keys and values.

## Building It Step by Step

### Step 1: Tokenizer

We start with a simple word‑level tokenizer. The vocabulary is built from a small corpus, and each unique word maps to an integer.

```python
class WordTokenizer:
    def __init__(self):
        self.word2id = {}
        self.id2word = {}
        self.pad_token = "<pad>"
        self.unk_token = "<unk>"
        # Reserve IDs for special tokens
        self.word2id[self.pad_token] = 0
        self.word2id[self.unk_token] = 1
        self.next_id = 2

    def build_vocab(self, texts):
        for text in texts:
            for word in text.split():
                if word not in self.word2id:
                    self.word2id[word] = self.next_id
                    self.id2word[self.next_id] = word
                    self.next_id += 1

    def encode(self, text):
        ids = []
        for word in text.split():
            ids.append(self.word2id.get(word, self.word2id[self.unk_token]))
        return ids

    def decode(self, ids):
        return " ".join(self.id2word.get(id, self.unk_token) for id in ids)
```

### Step 2: Embedding

We use a simple lookup table with learned positional embeddings.

```python
import numpy as np

class Embedding:
    def __init__(self, vocab_size, embed_dim, max_len=512):
        self.token_emb = np.random.randn(vocab_size, embed_dim) * 0.02
        self.pos_emb = np.random.randn(max_len, embed_dim) * 0.02

    def forward(self, token_ids):
        # token_ids: (batch, seq_len)
        batch, seq_len = token_ids.shape
        x = self.token_emb[token_ids]               # (batch, seq_len, embed_dim)
        positions = np.arange(seq_len)[None, :]     # (1, seq_len)
        x += self.pos_emb[positions]                # broadcast add
        return x
```

### Step 3: Multi‑Head Attention

A scaled dot‑product attention with multiple heads.

```python
def softmax(x, axis=-1):
    e_x = np.exp(x - np.max(x, axis=axis, keepdims=True))
    return e_x / np.sum(e_x, axis=axis, keepdims=True)

class MultiHeadAttention:
    def __init__(self, embed_dim, num_heads):
        assert embed_dim % num_heads == 0
        self.num_heads = num_heads
        self.head_dim = embed_dim // num_heads
        # Linear projections for Q, K, V
        self.W_q = np.random.randn(embed_dim, embed_dim) * 0.02
        self.W_k = np.random.randn(embed_dim, embed_dim) * 0.02
        self.W_v = np.random.randn(embed_dim, embed_dim) * 0.02
        self.W_o = np.random.randn(embed_dim, embed_dim) * 0.02

    def forward(self, x, mask=None):
        batch, seq_len, _ = x.shape
        # Linear projections and reshape for multi‑head
        Q = x @ self.W_q  # (batch, seq_len, embed_dim)
        K = x @ self.W_k
        V = x @ self.W_v
        Q = Q.reshape(batch, seq_len, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)
        K = K.reshape(batch, seq_len, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)
        V = V.reshape(batch, seq_len, self.num_heads, self.head_dim).transpose(0, 2, 1, 3)

        # Scaled dot‑product attention
        scores = (Q @ K.transpose(0, 1, 3, 2)) / np.sqrt(self.head_dim)  # (batch, heads, seq, seq)
        if mask is not None:
            scores = scores + mask
        attn_weights = softmax(scores, axis=-1)
        out = attn_weights @ V  # (batch, heads, seq, head_dim)

        # Concatenate heads and project
        out = out.transpose(0, 2, 1, 3).reshape(batch, seq_len, -1)
        out = out @ self.W_o
        return out
```

### Step 4: KV Cache

The cache stores key/value vectors from previous steps, allowing us to avoid recomputing them.

```python
class KVCache:
    def __init__(self, max_len=512):
        self.max_len = max_len
        self.K = None  # (batch, num_heads, max_len, head_dim)
        self.V = None
        self.cur_len = 0

    def update(self, K_new, V_new):
        # K_new, V_new shape: (batch, num_heads, seq_len, head_dim)
        if self.K is None:
            self.K = np.zeros_like(K_new, shape=(K_new.shape[0], K_new.shape[1], self.max_len, K_new.shape[3]))
            self.V = np.zeros_like(V_new, shape=(V_new.shape[0], V_new.shape[1], self.max_len, V_new.shape[3]))
        seq_len = K_new.shape[2]
        self.K[:, :, self.cur_len:self.cur_len+seq_len, :] = K_new
        self.V[:, :, self.cur_len:self.cur_len+seq_len, :] = V_new
        self.cur_len += seq_len

    def get(self):
        return self.K[:, :, :self.cur_len, :], self.V[:, :, :self.cur_len, :]
```

In the forward pass, we compute Q for the current token, but K and V for all previous tokens are fetched from the cache.

### Step 5: Feed‑Forward Network

A simple two‑layer MLP with a non‑linearity.

```python
class FeedForward:
    def __init__(self, embed_dim, hidden_dim):
        self.W1 = np.random.randn(embed_dim, hidden_dim) * 0.02
        self.b1 = np.zeros(hidden_dim)
        self.W2 = np.random.randn(hidden_dim, embed_dim) * 0.02
        self.b2 = np.zeros(embed_dim)

    def forward(self, x):
        h = np.maximum(0, x @ self.W1 + self.b1)  # ReLU
        out = h @ self.W2 + self.b2
        return out
```

### Step 6: Transformer Layer

Combine attention and FFN with residual connections and layer normalization.

```python
class TransformerLayer:
    def __init__(self, embed_dim, num_heads, hidden_dim):
        self.attn = MultiHeadAttention(embed_dim, num_heads)
        self.ffn = FeedForward(embed_dim, hidden_dim)
        self.ln1 = LayerNorm(embed_dim)
        self.ln2 = LayerNorm(embed_dim)

    def forward(self, x, cache=None, mask=None):
        # Pre‑norm architecture
        attn_input = self.ln1(x)
        if cache is not None:
            # Compute Q only for the last token
            q = self.attn.forward(attn_input[:, -1:, :])
            # Use cache for K, V
            K, V = cache.get()
            # Expand q to match heads
            batch, seq_len, _ = q.shape
            q = q.reshape(batch, seq_len, self.attn.num_heads, self.attn.head_dim).transpose(0, 2, 1, 3)
            scores = (q @ K.transpose(0, 1, 3, 2)) / np.sqrt(self.attn.head_dim)
            if mask is not None:
                scores = scores + mask[:, :, -1:, :]
            attn_weights = softmax(scores, axis=-1)
            out = attn_weights @ V
            out = out.transpose(0, 2, 1, 3).reshape(batch, seq_len, -1)
            out = out @ self.attn.W_o
        else:
            out = self.attn.forward(attn_input, mask=mask)
        x = x + out
        ffn_input = self.ln2(x)
        x = x + self.ffn.forward(ffn_input)
        return x
```

### Step 7: Sampler

Generate the next token using temperature, top‑k, and top‑p (nucleus) sampling.

```python
def sample(logits, temperature=1.0, top_k=None, top_p=None):
    # logits shape: (vocab_size,)
    logits = logits / temperature
    if top_k is not None:
        top_k = min(top_k, logits.shape[0])
        indices = np.argpartition(-logits, top_k)[:top_k]
        mask = np.ones_like(logits, dtype=bool)
        mask[indices] = False
        logits = np.where(mask, -np.inf, logits)
    if top_p is not None:
        sorted_logits = np.sort(logits)[::-1]
        cumulative_probs = np.cumsum(softmax(sorted_logits))
        cutoff = np.searchsorted(cumulative_probs, top_p)
        cutoff = max(cutoff, 1)
        mask = np.ones_like(logits, dtype=bool)
        mask[:cutoff] = False
        logits = np.where(mask, -np.inf, logits)
    probs = softmax(logits)
    return np.random.choice(len(probs), p=probs)
```

### Step 8: Inference Loop

Tie everything together for autoregressive generation.

```python
def generate(model, tokenizer, prompt, max_new_tokens=20, temperature=1.0, top_k=None, top_p=None):
    ids = tokenizer.encode(prompt)
    input_ids = np.array([ids])
    cache = KVCache(max_len=512)
    for _ in range(max_new_tokens):
        # Embedding
        x = embedding.forward(input_ids)
        # Pass through transformer layers
        for layer in model:
            x = layer.forward(x, cache=cache)
        # Project to vocab logits (assume a linear head)
        logits = x[:, -1, :] @ W_head  # W_head is a learned matrix
        next_id = sample(logits[0], temperature, top_k, top_p)
        input_ids = np.array([[next_id]])
        cache.update(...)  # Update with new token's K, V
        print(tokenizer.decode([next_id]), end="", flush=True)
```

*Note:* The above snippets are simplified for clarity. A full implementation would include proper initialization, batch handling, and a learned output projection `W_head`.

## Running and Testing It

1. **Set up a virtual environment**  
   ```bash
   python -m venv env
   source env/bin/activate
   pip install numpy
   ```

2. **Save the code** in a file `transformer_engine.py`.

3. **Create a small corpus** (e.g., `corpus.txt`) with a few sentences.

4.