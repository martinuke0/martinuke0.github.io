---
title: "Building a Multi-Head Self-Attention Block with RoPE and ALiBi from Scratch"
date: "2026-09-10T17:00:47.734"
draft: false
tags: ["deep-learning", "pytorch", "transformers", "systems-engineering", "ai-architecture"]
description: "Build a production-grade multi-head self-attention block with rotary embeddings and ALiBi from scratch to demonstrate deep systems and ML engineering skills."
summary: "A hands-on guide to building a multi-head self-attention block with RoPE and ALiBi from scratch, signaling advanced ML and systems engineering skills to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-10-building-a-multi-head-self-attention-block-with-rope-and-alibi-from-scratch.svg"
  alt: "PyTorch code and neural network architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Building a multi-head self-attention block with Rotary Positional Embeddings (RoPE) and ALiBi from scratch proves you understand the core mechanics of modern LLMs and how to optimize them for performance. This project bridges the gap between theoretical machine learning and production-grade systems engineering, signaling to hiring managers that you can architect and debug foundational AI components.

The transition from using high-level APIs like HuggingFace `transformers` to implementing the core mechanics of a Large Language Model (LLM) from scratch is a defining moment for any aspiring ML engineer. While leveraging pre-built modules accelerates prototyping, it obscures the intricate tensor operations, memory constraints, and numerical stability challenges that define production systems. 

Building a multi-head self-attention block with Rotary Positional Embeddings (RoPE) and Attention with Linear Biases (ALiBi) from scratch forces you to confront the exact linear algebra and systems optimizations that power today's most advanced models. It is a project that demonstrates you don't just call `model.fit()`, but you understand the mathematical primitives and hardware constraints underneath.

## Why This Project Stands Out on a CV

Hiring managers and technical interviewers are inundated with candidates who can fine-tune a pre-trained BERT model on a single GPU. Implementing the attention mechanism from scratch separates you from the pack by signaling three critical skill sets:

1. **Deep Mathematical Proficiency:** You aren't just stacking layers; you are deriving and implementing the rotational matrices for RoPE and the additive biases for ALiBi. This proves you understand *why* positional encoding matters and how to encode relative distances without training an additional parameter set.
2. **Systems and Memory Optimization:** Attention mechanisms are notoriously memory-bound. By building this from scratch, you must manage tensor shapes, data types (e.g., `float16` vs. `float32`), and memory layout to avoid out-of-memory (OOM) errors on limited hardware.
3. **Debugging and Numerical Stability:** Implementing softmax, scaling factors, and additive biases introduces subtle numerical pitfalls. A candidate who has debugged a vanishing gradient caused by an improperly scaled attention matrix is far more valuable than one who hasn't.

This project signals readiness for roles like Core Model Engineer, ML Systems Architect, or Research Engineer, where the ability to modify the foundational building blocks of a model is a daily requirement.

## Architecture Overview

The architecture of our self-attention block is a streamlined pipeline designed to process token embeddings, apply positional context, and compute contextualized representations. Understanding how these components fit together is crucial for debugging and scaling.

The data flows through the following stages:

* **Input Embedding Layer:** Converts token IDs into dense vectors of dimension $d_{model}$.
* **Rotary Positional Embeddings (RoPE):** Applies a rotation matrix to the Query ($Q$) and Key ($K$) vectors based on their absolute positions. Unlike sinusoidal encodings, RoPE encodes relative position without adding explicit parameters, leveraging the properties of complex rotations.
* **Linear Projections:** The embedded tokens are projected into $Q$, $K$, and $V$ matrices using learned weight matrices ($W_Q, W_K, W_V$).
* **Scaled Dot-Product Attention with ALiBi:** Computes the attention scores as $softmax(\frac{QK^T}{\sqrt{d_k}} + M)$, where $M$ is the ALiBi bias matrix. ALiBi adds a negative, linearly increasing penalty to attention scores based on the distance between tokens, effectively enforcing a locality bias without requiring a learned positional matrix.
* **Multi-Head Splitting:** The $Q$, $K$, and $V$ matrices are split into multiple heads, allowing the model to attend to different representation subspaces simultaneously.
* **Output Projection:** The concatenated head outputs are projected back to the $d_{model}$ dimension via $W_O$.
* **Residual Connection and Layer Normalization:** Adds the input tensor to the output and normalizes the activations to stabilize training.

```text
[Token IDs] 
    ↓ 
[Embedding] → [RoPE Rotation on Q & K] 
    ↓ 
[Linear Projections: Q, K, V] → [Multi-Head Splitting] 
    ↓ 
[Scaled Dot-Product] + [ALiBi Bias Matrix] → [Softmax] 
    ↓ 
[Attention Output] × [V] → [Concatenate Heads] 
    ↓ 
[Output Projection] + [Residual] → [Layer Norm] 
    ↓ 
[Contextualized Output]
```

## Building It Step by Step

We will implement this architecture using PyTorch, leveraging its autograd system for gradient computation and `nn.Module` for parameter management. The following steps provide the core logic required to build a functional, runnable attention block.

### Step 1: Initialize Parameters and RoPE Constants

First, we initialize the weight matrices for $Q$, $K$, $V$, and the output projection. We also pre-compute the rotation angles for RoPE, which depend on the embedding dimension and the head size.

```python
import torch
import torch.nn as nn
import torch.nn.functional as F
import math

class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, num_heads: int):
        super().__init__()
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        
        # Ensure d_model is divisible by num_heads
        assert self.head_dim * num_heads == d_model, "d_model must be divisible by num_heads"
        
        # Learnable weight matrices
        self.w_q = nn.Linear(d_model, d_model, bias=False)
        self.w_k = nn.Linear(d_model, d_model, bias=False)
        self.w_v = nn.Linear(d_model, d_model, bias=False)
        self.w_o = nn.Linear(d_model, d_model, bias=False)
        
        # ALiBi slopes (pre-computed based on the paper's heuristic)
        self.register_buffer('alibi_slopes', self._get_alibi_slopes(num_heads))
        
        # Pre-compute RoPE frequencies
        self.register_buffer('freqs_cis', self._get_freqs_cis(self.head_dim))

    def _get_alibi_slopes(self, num_heads: int) -> torch.Tensor:
        slopes = []
        for i in range(1, num_heads + 1):
            slopes.append(1.0 / (2 ** ((2 * i) / num_heads)))
        return torch.tensor(slopes, dtype=torch.float32)

    def _get_freqs_cis(self, head_dim: int) -> torch.Tensor:
        theta = 10000.0
        freqs = 1.0 / (theta ** (torch.arange(0, head_dim, 2)[:head_dim] / head_dim))
        return torch.polar(torch.ones_like(freqs), freqs)
```

### Step 2: Implement Rotary Positional Embeddings (RoPE)

RoPE rotates the Query and Key vectors by an angle dependent on their position. This is implemented by multiplying the complex representation of the vectors by a rotation matrix derived from the position index.

```python
    def apply_rope(self, x: torch.Tensor, position: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, num_heads, seq_len, head_dim)
        # Convert to complex numbers for rotation
        x_complex = torch.view_as_complex(x.float().reshape(*x.shape[:-1], -1, 2))
        
        # Compute the rotation angles based on position
        freqs = position.unsqueeze(-1) * self.freqs_cis.unsqueeze(0)
        rot_mat = torch.polar(torch.ones_like(freqs), freqs)
        
        # Apply rotation
        x_rotated = x_complex * rot_mat
        return torch.view_as_real(x_rotated).flatten(-2).type_as(x)
```

### Step 3: Implement ALiBi Bias

ALiBi bypasses learned positional embeddings by adding a simple, fixed bias to the attention scores. The bias is a negative slope multiplied by the distance between the query and key positions.

```python
    def get_alibi_bias(self, seq_len: int, batch_size: int) -> torch.Tensor:
        # Create a matrix of distances: (seq_len, seq_len)
        positions = torch.arange(seq_len, dtype=torch.float32)
        distances = positions.unsqueeze(0) - positions.unsqueeze(1)
        
        # Apply slopes: (num_heads, 1) * (1, seq_len) -> (num_heads, seq_len, seq_len)
        bias = -torch.abs(distances.unsqueeze(0) * self.alibi_slopes.unsqueeze(-1).unsqueeze(-1))
        return bias.unsqueeze(0).expand(batch_size, -1, -1, -1)
```

### Step 4: Multi-Head Attention Logic

Now we combine the projections, RoPE, ALiBi, and scaled dot-product attention into the forward pass. We must carefully manage tensor shapes to split and concatenate the attention heads.

```python
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        
        # Project and split into heads: (B, T, C) -> (B, num_heads, T, head_dim)
        q = self.w_q(x).view(B, T, self.num_heads, self.head_dim).transpose(1, 2)
        k = self.w_k(x).view(B, T, self.num_heads, self.head_dim).transpose(1, 2)
        v = self.w_v(x).view(B, T, self.num_heads, self.head_dim).transpose(1, 2)
        
        # Apply RoPE to Q and K
        positions = torch.arange(T, device=x.device).unsqueeze(0)
        q = self.apply_rope(q, positions)
        k = self.apply_rope(k, positions)
        
        # Scaled Dot-Product Attention
        scores = torch.matmul(q, k.transpose(-2, -1)) / math.sqrt(self.head_dim)
        
        # Add ALiBi bias
        alibi_bias = self.get_alibi_bias(T, B)
        scores = scores + alibi_bias
        
        # Softmax and apply to V
        attn_weights = F.softmax(scores, dim=-1)
        context = torch.matmul(attn_weights, v)
        
        # Concatenate heads and project output
        context = context.transpose(1, 2).contiguous().view(B, T, C)
        return self.w_o(context)
```

## Running and Testing It

To ensure your implementation is mathematically correct and numerically stable, you must rigorously test it before integrating it into a larger model. The best approach is to compare your custom block against a known reference implementation and verify gradient flow.

First, set up a local testing environment using `pytest`. Install the necessary dependencies:

```bash
pip install torch pytest
```

Next, create a test script to validate the output shapes, gradient computation, and numerical equivalence to a baseline. We can use HuggingFace's `BertAttention` as a sanity check for the attention mechanism itself, ignoring the positional encoding differences.

```python
import torch
import torch.nn as nn
from torch.testing import assert_close

def test_attention_block():
    d_model = 128
    num_heads = 4
    batch_size = 2
    seq_len = 16
    
    # Initialize custom block
    custom_attn = MultiHeadAttention(d_model, num_heads)
    
    # Generate random input
    x = torch.randn(batch_size, seq_len, d_model)
    
    # Forward pass
    output = custom_attn(x)
    
    # Test shape
    assert output.shape == (batch_size, seq_len, d_model), f"Expected shape {(batch_size, seq_len, d_model)}, got {output.shape}"
    
    # Test gradient flow
    loss = output.sum()
    loss.backward()
    
    # Verify gradients exist and are not NaN
    for name, param in custom_attn.named_parameters():
        assert param.grad is not None, f"Gradient missing for {name}"
        assert not torch.isnan(param.grad).any(), f"NaN gradient in {name}"
        
    print("All tests passed successfully!")

if __name__ == "__main__":
    test_attention_block()
```

Running `pytest test_attention.py` will execute the validation suite. If the gradients flow without `NaN` values and the output shapes match, your block is mathematically sound and ready for integration.

## Extending It: Your Roadmap to Senior-Level

A basic attention block is a strong portfolio piece, but transforming it into a production-flavored system is what separates senior engineers from junior ones. Here are five concrete upgrades to evolve your project:

1. **Integrate FlashAttention for Kernel Optimization:** Replace the standard PyTorch matmul operations with the FlashAttention kernel. *Why it matters:* It reduces memory complexity from $O(n^2)$ to $O(n)$ and significantly speeds up training on long sequences by optimizing GPU memory bandwidth.
2. **Implement Distributed Data Parallel (DDP) Training:** Wrap your model with PyTorch's `DistributedDataParallel` to train across multiple GPUs. *Why it matters:* It demonstrates you can scale model training horizontally, handling gradient synchronization and device placement seamlessly.
3. **Add Checkpointing and Persistence:** Implement `torch.utils.checkpoint` to trade compute for memory, and add robust serialization logic to save and load model states. *Why it matters:* Production systems must recover from crashes and manage massive memory footprints without failing.
4. **Integrate Weights & Biases for Observability:** Hook up the training loop to Weights & Biases (W&B) to log gradients, weight histograms, and loss curves. *Why it matters:* Observability is critical for debugging training instability and ensuring reproducibility across different runs and environments.
5. **Implement TorchScript for Inference Optimization:** Convert your `nn.Module` into a TorchScript model using `torch.jit.script`. *Why it matters:* It removes Python overhead during inference, allowing the model to run in a high-performance C++ runtime environment for low-latency production serving.

## Key Takeaways

* Implementing attention from scratch forces you to manage the exact tensor operations and memory constraints that high-level APIs abstract away, proving deep systems proficiency.
* Rotary Positional Embeddings (RoPE) and ALiBi are superior to traditional learned positional encodings because they encode relative positions efficiently without adding trainable parameters.
* Rigorous testing using `torch.testing` and gradient checks is non-negotiable to ensure numerical stability and correct backpropagation in custom neural network components.
* Upgrading a toy model with production features like FlashAttention, DDP, and checkpointing is the fastest way to signal senior-level engineering capability to hiring managers.
* A portfolio project that demonstrates you can build, debug, and scale foundational AI components is infinitely more valuable than one that simply fine-tunes existing APIs.

## Further Reading

To deepen your understanding of the specific algorithms and systems concepts used in this project, study the primary sources and canonical documentation below:

1. **RoFormer: Enhanced Transformer with Rotary Position Embedding** — The original paper introducing RoPE, detailing the mathematical derivation of the rotation matrices and their superior performance in handling long sequences. [https://arxiv.org/abs/2104.09864](https://arxiv.org/abs/2104.09864)
2. **Train Short, Memory Long: Attention with Linear Biases** — The seminal paper by Google Research introducing ALiBi, explaining how linear biases can replace learned positional embeddings and improve generalization. [https://arxiv.org/abs/2108.12409](https://arxiv.org/abs/2108.12409)
3. **FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness** — The foundational paper for the FlashAttention kernel, which is essential for any production-grade transformer implementation dealing with long context windows. [https://arxiv.org/abs/2205.14135](https://arxiv.org/abs/2205.14135)
4. **PyTorch Distributed Data Parallel Documentation** — The official canonical documentation for implementing DDP, which you will need to scale your attention block across multiple GPUs. [https://pytorch.org/docs/stable/distributed.html](https://pytorch.org/docs/stable/distributed.html)