

---
title: "Build a Fused Causal Self-Attention Block with RoPE and Sliding-Window KV Cache in Pure Python"
date: "2026-09-11T06:01:09.057"
draft: false
tags: ["transformers", "attention", "rope", "kv-cache", "python"]
description: "Build a fused causal self-attention block with RoPE and sliding-window KV cache in pure Python, demonstrating practical systems skills for your CV."
summary: "This guide walks through implementing a fused causal self-attention block with RoPE and a sliding-window KV cache in pure Python, giving you a concrete portfolio piece that highlights systems engineering expertise."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-build-a-fused-causal-self-attention-block-with-rope-and-sliding-window-kv-cache-in-pure-python.svg"
  alt: "A diagram of a transformer attention block with sliding window"
  caption: ""
  relative: false
---

> **TL;DR** — This guide shows you how to build a fused causal self-attention block with rotary position embeddings (RoPE) and a sliding‑window KV cache entirely in pure Python. The implementation is runnable, produces numerically correct outputs, and demonstrates the systems‑level skills that hiring managers value for senior ML infrastructure roles.

In the current landscape of large language models, the ability to implement and optimize core transformer components is a differentiator for engineers seeking roles in ML infrastructure. This post provides a hands‑on walkthrough of a fused causal self‑attention block augmented with RoPE and a sliding‑window KV cache. By the end you will have a self‑contained, runnable script that you can showcase on your portfolio or discuss in technical interviews.

## Why This Project Stands Out on a CV

- **Core Transformer Expertise** – You will implement multi‑head attention, causal masking, and position encoding from scratch, proving you understand the mathematical and algorithmic foundations of modern LLMs.
- **Systems‑Oriented Optimizations** – The sliding‑window KV cache and fused Q/K/V projection demonstrate memory‑efficient inference patterns used in production serving systems such as vLLM and TensorRT‑LLM.
- **Performance Awareness** – Writing the attention kernel in pure NumPy (or optionally JAX) forces you to think about vectorization, cache locality, and numerical stability—skills that translate directly to optimizing GPU kernels.
- **Portfolio‑Ready Artifact** – A single, well‑documented Python file that can be run locally and visualized provides concrete evidence of your ability to ship production‑quality ML infrastructure.
- **Signals for Senior Roles** – The extension roadmap (persistence, horizontal scaling, observability) shows you can think beyond a toy model to the challenges of real‑world deployment, which is often the threshold for senior or staff engineer positions.

## Architecture Overview

The project is composed of the following logical components:

- **Input Embedding & Projection** – A linear layer maps token embeddings to query, key, and value vectors for each head.
- **Rotary Position Embedding (RoPE)** – Applies a rotation matrix to the query and key vectors, encoding positional information in a way that preserves relative distances.
- **Causal Mask** – Ensures each token only attends to previous tokens, preserving the autoregressive property.
- **Sliding‑Window KV Cache** – Stores a limited history of key‑value pairs (the window size) to reduce memory consumption during inference.
- **Fused Attention Computation** – Combines the projection, RoPE application, masked dot‑product attention, and output projection into a single forward pass.
- **Output Projection** – Projects the concatenated attention outputs back to the model’s hidden dimension.

A high‑level data flow is:

```
Token Embeddings → Q/K/V Projection → RoPE → Causal Mask → Sliding‑Window KV Cache → Softmax → Weighted Sum → Output Projection
```

## Building It Step by Step

### Step 1: Set Up the Environment

```bash
pip install numpy
```

### Step 2: Implement Rotary Position Embedding (RoPE)

RoPE rotates the query and key vectors by an angle that depends on their position. The following function computes the rotation matrix for a given dimension and sequence length.

```python
import numpy as np

def rotary_embedding(dim: int, seq_len: int, theta: float = 10000.0) -> np.ndarray:
    """
    Compute the RoPE rotation matrix of shape (seq_len, dim, dim).
    """
    # Compute the angles for each position and dimension pair
    pos = np.arange(seq_len)[:, None]          # (seq_len, 1)
    dim_idx = np.arange(dim // 2)              # (dim/2,)
    freqs = 1.0 / (theta ** (2 * dim_idx / dim))  # (dim/2,)
    angles = pos * freqs                        # (seq_len, dim/2)

    # Build the block‑diagonal rotation matrix
    cos = np.cos(angles)
    sin = np.sin(angles)

    # Interleave to create full rotation matrix
    rot = np.zeros((seq_len, dim, dim))
    for i in range(dim // 2):
        rot[:, 2*i, 2*i] = cos[:, i]
        rot[:, 2*i, 2*i+1] = -sin[:, i]
        rot[:, 2*i+1, 2*i] = sin[:, i]
        rot[:, 2*i+1, 2*i+1] = cos[:, i]
    return rot
```

### Step 3: Create a Causal Mask

A causal mask prevents a token from attending to future positions. We can generate it as a boolean array.

```python
def causal_mask(seq_len: int) -> np.ndarray:
    """
    Returns a boolean mask of shape (seq_len, seq_len) where True indicates
    that the position is allowed to attend.
    """
    mask = np.tril(np.ones((seq_len, seq_len), dtype=bool))
    return mask
```

### Step 4: Sliding‑Window KV Cache

The KV cache stores the last `window_size` key‑value pairs. When a new token arrives, the oldest entry is evicted.

```python
class SlidingWindowKVCache:
    def __init__(self, window_size: int, head_dim: int, num_heads: int):
        self.window_size = window_size
        self.head_dim = head_dim
        self.num_heads = num_heads
        # Initialize empty cache
        self.keys = np.zeros((0, num_heads, head_dim))
        self.values = np.zeros((0, num_heads, head_dim))

    def update(self, new_keys: np.ndarray, new_values: np.ndarray):
        """
        Append new key/value vectors and evict oldest if exceeding window size.
        """
        # Concatenate along sequence axis
        self.keys = np.concatenate([self.keys, new_keys], axis=0)
        self.values = np.concatenate([self.values, new_values], axis=0)
        # Trim to window size
        if self.keys.shape[0] > self.window_size:
            self.keys = self.keys[-self.window_size:]
            self.values = self.values[-self.window_size:]

    def get(self):
        return self.keys, self.values
```

### Step 5: Fused Causal Self‑Attention Forward

We now combine projection, RoPE, masking, and the KV cache into a single forward function.

```python
def fused_causal_attention(
    x: np.ndarray,
    W_q: np.ndarray,
    W_k: np.ndarray,
    W_v: np.ndarray,
    W_o: np.ndarray,
    num_heads: int,
    head_dim: int,
    window_size: int,
) -> np.ndarray:
    """
    x: input embeddings of shape (batch, seq_len, d_model)
    W_q,