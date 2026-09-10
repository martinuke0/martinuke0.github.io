

---
title: "Switch Transformer-Style Sparse MoE Layer from Scratch in PyTorch"
date: "2026-09-10T07:01:49.612"
draft: false
tags: ["pytorch", "mixture-of-experts", "deep-learning", "systems", "switch-transformer"]
description: "Build a Switch Transformer sparse MoE layer in PyTorch with differentiable routing, capacity limits, and load-balancing loss for a portfolio project."
summary: "Implement a Switch Transformer‑style sparse mixture‑of‑experts layer in PyTorch, complete with differentiable routing, capacity limits, and load‑balancing loss."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-10-switch-transformer-style-sparse-moe-layer-from-scratch-in-pytorch.svg"
  alt: "Abstract illustration of a neural network with routing switches."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a Switch Transformer‑style sparse mixture‑of‑experts layer in PyTorch, including differentiable routing, expert capacity limits, and a load‑balancing loss. You’ll end up with a runnable, testable module that demonstrates real systems skills and can be extended for production use.

In the race to scale transformer models, sparse mixture‑of‑experts (MoE) has emerged as a way to increase capacity without linearly increasing compute. The Switch Transformer simplifies MoE by routing each token to a single expert, which makes training and inference faster but introduces load‑balancing challenges. In this guide you will implement a minimal yet functional MoE layer from scratch, focusing on the three pillars that make it production‑ready: differentiable routing, explicit capacity constraints, and a differentiable load‑balancing loss.

## Why This Project Stands Out on a CV

- **Advanced architecture implementation** – You’ll build a Switch Transformer‑style MoE layer, a topic that appears in research papers and high‑scale production systems but is rarely taught in standard courses.
- **From‑scratch coding** – The implementation uses only core PyTorch primitives, demonstrating the ability to create custom layers rather than relying on high‑level libraries.
- **Systems thinking** – By enforcing expert capacity limits and adding a load‑balancing loss, you showcase an understanding of resource management and distributed training concerns.
- **Differentiable routing** – Using Gumbel‑Softmax or straight‑through estimators shows familiarity with advanced gradient techniques needed for discrete decisions.
- **Portfolio signal** – A complete, tested module with clear documentation signals readiness for roles in ML infrastructure, research engineering, or high‑scale model serving.

## Architecture Overview

The MoE layer consists of four cooperating components:

1. **Router** – A small linear projection followed by a softmax (or Gumbel‑Softmax) that produces a probability distribution over experts for each token.
2. **Experts** – A collection of independent feed‑forward networks (one per expert) that process the tokens assigned to them.
3. **Capacity Limiter** – A mechanism that caps the number of tokens any single expert can handle, preventing overload and ensuring balanced computation.
4. **Load‑Balancing Loss** – An auxiliary loss that encourages uniform token distribution across experts, computed from the routing probabilities.

These pieces fit together in a forward pass:

```
Input → Router → (routing probs, one‑hot) → Capacity Mask → Expert Dispatch → Expert Compute → Combine → Output
```

The router outputs both a soft probability vector (for gradient flow) and a hard assignment (for dispatch). The capacity limiter uses the hard assignments to enforce per‑expert limits, masking out excess tokens. The load‑balancing loss is derived from the soft probabilities and added to the task loss.

## Building It Step by Step

### Step 1: Install dependencies

```bash
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
```

### Step 2: Define the Expert module

```python
import torch
import torch.nn as nn
import torch.nn.functional as F

class Expert(nn.Module):
    """A single feed‑forward expert."""
    def __init__(self, d_model: int, d_ff: int):
        super().__init__()
        self.fc1 = nn.Linear(d_model, d_ff)
        self.fc2 = nn.Linear(d_ff, d_model)
        self.act = nn.GELU()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (num_tokens, d_model)
        return self.fc2(self.act(self.fc1(x)))
```

### Step 3: Implement differentiable routing with Gumbel‑Softmax

```python
def gumbel_softmax(logits: torch.Tensor, tau: float = 1.0, hard: bool = False) -> torch.Tensor:
    """Gumbel‑Softmax for differentiable discrete routing."""
    gumbel = -torch.log(-torch.log(torch.rand_like(logits)))
    y = logits + gumbel
    y = F.softmax(y / tau, dim=-1)
    if hard:
        # Straight‑through: forward is discrete, backward uses soft probs
        y_hard = torch.zeros_like(y).scatter_(-1, y.argmax(dim=-1, keepdim=True), 1.0)
        return y_hard - y.detach() + y
    return y

class Router(nn.Module):
    def __init__(self, d_model: int, num_experts: int):
        super().__init__()
        self.num_experts = num_experts
        self.gate = nn.Linear(d_model, num_experts, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, d_model)
        logits = self.gate(x)  # (batch, seq_len, num_experts)
        # Differentiable top‑1 routing
        routing_probs = gumbel_softmax(logits, tau=1.0, hard=True)
        return routing_probs  # (batch, seq_len, num_experts)
```

### Step 4: Enforce expert capacity limits

```python
def apply_capacity(routing_probs: torch.Tensor, capacity: int) -> torch.Tensor:
    """
    Zero out routing probabilities beyond the per‑expert capacity.
    routing_probs: (batch, seq_len, num_experts) – hard assignments (one‑hot).
    capacity: maximum tokens per expert.
    Returns a mask of shape (batch, seq_len, num_experts) where 1 = allowed.
    """
    batch, seq_len, num_experts = routing_probs.shape
    # Count tokens per expert
    token_counts = routing_probs.sum(dim=(0, 1))  # (num_experts,)
    # For each expert, keep only the first `capacity` tokens (by position)
    # We'll create a cumulative mask along the sequence dimension.
    # First, compute per‑expert cumulative sum of assignments.
    cumsum = torch.cumsum(routing_probs, dim=1)  # (batch, seq_len, num_experts)
    # A token is allowed if its cumulative count <= capacity
    allowed = cumsum <= capacity  # (batch, seq_len, num_experts)
    # Convert to float mask
    return allowed.float()
```

### Step 5: Load‑balancing loss

```python
def load_balancing_loss(routing_probs: torch.Tensor) -> torch.Tensor:
    """
    Switch Transformer auxiliary loss: encourages uniform expert usage.
    routing_probs: (batch, seq_len, num_experts) – soft probabilities.
    """
    # Fraction of tokens assigned to each expert
    f = routing_probs.mean(dim=(0, 1))  # (num_experts,)
    # Mean probability per expert
    p = routing_probs.mean(dim=(0, 1))  # same as f for hard routing, but kept separate for clarity
    # Loss = num_experts * sum(f * p)
    num_experts = routing_probs.shape[-1]
    return num_experts * torch.sum(f * p)
```

### Step 6: Assemble the MoE layer

```python
class SparseMoE(nn.Module):
    """Switch Transformer‑style sparse MoE layer."""
    def __init__(self, d_model: int, d_ff: int, num_experts: int, capacity: int):
        super().__init__()
        self.num_experts = num_experts
        self.capacity = capacity
        self.router = Router(d_model, num_experts)
        self.experts = nn.ModuleList([Expert(d_model, d_ff) for _ in range(num_experts)])

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, d_model)
        batch, seq_len, d_model = x.shape
        # 1️⃣ Routing
        routing_probs = self.router(x)  # (batch, seq_len, num_experts) – hard one‑hot
        # 2️⃣ Capacity mask
        capacity_mask = apply_capacity(routing_probs, self.capacity)  # (batch, seq_len, num_experts)
        # 3️⃣ Dispatch tokens to experts
        # Flatten batch and seq_len for easier indexing
        flat_x = x.view(-1, d_model)  # (batch*seq_len, d_model)
        flat_routing = routing_probs.view(-1, self.num_experts)  # (batch*seq_len, num_experts)
        flat_mask = capacity_mask.view(-1, self.num_experts)  # (batch*seq_len, num_experts)

        # For each expert, gather tokens where mask == 1
        expert_outputs = []
        for e in range(self.num_experts):
            mask_e = flat_mask[:, e]  # (batch*seq_len,)
            # Select tokens for this expert
            tokens_e = flat_x[mask_e.bool()]  # (num_selected, d_model)
            if tokens_e.num

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
