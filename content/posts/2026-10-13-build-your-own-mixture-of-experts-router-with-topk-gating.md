---
title: "Build Your Own Mixture-of-Experts Router with Top‑k Gating"
date: "2026-10-13T05:00:48.893"
draft: false
tags: ["mixture-of-experts", "deep-learning", "pytorch", "systems", "portfolio-project"]
description: "Learn to implement a sparse mixture-of-experts router using top‑k gating in PyTorch, with runnable code and production‑grade extensions for your CV."
summary: "This tutorial walks you through building a top‑k gated mixture-of-experts router in PyTorch, giving you a concrete portfolio piece that demonstrates model architecture, sparse routing, and system‑level scaling."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-13-build-your-own-mixture-of-experts-router-with-topk-gating.svg"
  alt: "A diagram of a mixture-of-experts router"
  caption: ""
  relative: false
---

> **TL;DR** — You will implement a sparse mixture-of-experts router with top‑k gating in under 200 lines of PyTorch, run it on synthetic data, and see how to extend it to a production‑grade service. The project showcases model architecture, efficient routing, and system design skills that hiring managers look for.

In the race to scale language models, mixture-of-experts (MoE) has emerged as a way to increase capacity without linearly increasing compute. This post guides you through building a minimal but functional MoE router from scratch, focusing on top‑k gating and sparse routing. By the end you will have a runnable script, a clear architecture diagram, and a roadmap to turn this prototype into a production system.

## Why This Project Stands Out on a CV

- **Deep Learning Architecture** – You will implement a custom layer (the router) that combines gating logic with expert selection, demonstrating understanding of conditional computation.
- **Sparse Computation** – By routing only a subset of tokens to each expert, you showcase knowledge of efficiency techniques used in models like GShard and Switch Transformer.
- **System‑Oriented Design** – The code is structured as a reusable PyTorch module, ready to be wrapped in a service (FastAPI, TorchServe) and scaled horizontally.
- **Production Readiness** – The extension roadmap covers persistence, observability, fault tolerance, and benchmarking—skills that map directly to senior ML engineer or MLOps roles.
- **Portfolio Signal** – A working MoE router is a concrete artifact that can be demoed in interviews, illustrating both algorithmic and engineering competence.

## Architecture Overview

The system consists of four logical components:

1. **Expert Pool** – A list of feed‑forward networks (e.g., simple MLPs) that process tokens. Each expert is independent and can be sharded across devices.
2. **Gating Network** – A small linear layer that produces a logits vector for each token; from these logits we derive routing probabilities.
3. **Top‑k Selector** – For each token, we keep the *k* highest gating scores and zero out the rest, creating a sparse routing mask.
4. **Router & Combiner** – The router dispatches each token to its selected experts, collects the expert outputs, and combines them via a weighted sum (weights are the normalized gating scores).

A textual diagram:

```
Input Tokens ──► Gating Net ──► Top‑k Mask ──► Expert Dispatch
                     ▲                     │
                     │                     ▼
                 Expert Pool ◄───────────────┘
                     │
                     ▼
               Weighted Sum ──► Output
```

This separation mirrors the design used in large‑scale MoE systems and makes it easy to swap in different expert architectures or scaling strategies.

## Building It Step by Step

Below is a complete, runnable PyTorch implementation. The code is intentionally compact but includes all essential logic.

### Step 1 – Set up the environment

```bash
# Create a virtual environment and install dependencies
python -m venv moe-env
source moe-env/bin/activate
pip install torch torchvision numpy
```

### Step 2 – Define the Expert Pool

```python
import torch
import torch.nn as nn
from typing import List

class Expert(nn.Module):
    def __init__(self, input_dim: int, hidden_dim: int, output_dim: int):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)

def build_expert_pool(num_experts: int, input_dim: int, hidden_dim: int, output_dim: int) -> List[Expert]:
    return [Expert(input_dim, hidden_dim, output_dim) for _ in range(num_experts)]
```

### Step 3 – Implement the Gating Network

```python
class GatingNet(nn.Module):
    def __init__(self, input_dim: int, num_experts: int):
        super().__init__()
        self.linear = nn.Linear(input_dim, num_experts)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x shape: (batch, seq_len, input_dim)
        logits = self.linear(x)          # (batch, seq_len, num_experts)
        probs = torch.softmax(logits, dim=-1)
        return probs
```

### Step 4 – Top‑k Selection and Sparse Routing

```python
def top_k_gating(probs: torch.Tensor, k: int):
    """
    Returns:
        topk_probs: (batch, seq_len, k) – normalized probabilities for selected experts
        topk_indices: (batch, seq_len, k) – expert indices
        mask: (batch, seq_len, num_experts) – binary mask, 1 for selected experts
    """
    topk_probs, topk_indices = torch.topk(probs, k, dim=-1)
    # Normalize the selected probabilities
    topk_probs = topk_probs / topk_probs.sum(dim=-1, keepdim=True)
    # Create a mask of shape (batch, seq_len, num_experts)
    mask = torch.zeros_like(probs).scatter_(-1, topk_indices, 1.0)
    return topk_probs, topk_indices, mask
```

### Step 5 – The Full Mixture‑of‑Experts Router

```python
class MoERouter(nn.Module):
    def __init__(self, num_experts: int, input_dim: int, hidden_dim: int, output_dim: int, k: int):
        super().__init__()
        self.experts = nn.ModuleList(build_expert_pool(num_experts, input_dim, hidden_dim, output_dim))
        self.gate = GatingNet(input_dim, num_experts)
        self.k = k

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_dim)
        batch, seq_len, _ = x.shape
        probs = self.gate(x)                     # (batch, seq_len, num_experts)
        topk_probs, topk_indices, mask = top_k_gating(probs, self.k)

        # Flatten batch and sequence dimensions for easier dispatch
        x_flat = x.view(-1, x.size(-1))          # (B*S, input_dim)
        topk_probs_flat = topk_probs.view(-1, self.k)   # (B*S, k)
        topk_indices_flat = topk_indices.view(-1, self.k) # (B*S, k)

        # Allocate output tensor
        output_flat = torch.zeros(x_flat.size(0), self.experts[0].net[-1].out_features, device=x.device)

        # For each expert, gather the tokens routed to it
        for expert_idx, expert in enumerate(self.experts):
            # Find positions where this expert is selected
            sel = (topk_indices_flat == expert_idx).any(dim=-1)  # (B*S,)
            if not sel.any():
                continue
            # Indices of tokens that chose this expert
            token_idx = torch.nonzero(sel, as_tuple=False).squeeze(-1)
            # For each such token, we need the weight (probability) assigned to this expert
            # Locate the weight in topk_probs_flat
            # topk_indices_flat[token_idx] contains k indices; find the slot matching expert_idx
            slots = (topk_indices_flat[token_idx] == expert_idx).int().argmax(dim=-1)
            weights = topk_probs_flat[token_idx].gather(1, slots.unsqueeze(-1)).squeeze(-1)

            # Run expert on the selected tokens
            expert_input = x_flat[token_idx]               # (N, input_dim)
            expert_output = expert(expert_input)           # (N, output_dim)
            # Weighted contribution
            output_flat[token_idx] += expert_output * weights.unsqueeze(-1)

        # Reshape back to original dimensions
        output = output_flat.view(batch, seq_len, -1)
        return output
```

### Step 6 – Quick Sanity Check

```python
# Example usage
num_experts = 4
input_dim = 16
hidden_dim = 32
output_dim = 16
k = 2

model = MoERouter(num_experts, input_dim, hidden_dim, output_dim, k)
dummy_input = torch.randn(8, 5, input_dim)  # batch=8, seq_len=5
out = model(dummy_input)
print("Output shape:", out.shape)  # should be (8, 5, 16)
```

Running the script above prints `Output shape: torch.Size([8, 5, 16])`, confirming the router works end‑to‑end.

## Running and Testing It

1. **Save the code** in a file named `moe_router.py`.
2. **Execute**:

```bash
python moe_router.py
```

You should see the output shape printed without errors.

3. **Write a unit test** (using `pytest`) to verify that:
   - The gating probabilities sum to 1 for each token.
   - Exactly `k` experts are active per token.
   - The output shape matches the input shape.

```python
# test_moe.py
import torch
from moe_router import MoERouter

def test_router_shape():
    model = MoERouter(4, 16, 32, 16, 2)
    x = torch.randn(8, 5, 16)
    assert model(x).shape == x.shape

def test_topk_mask():
    from moe_router import top_k_gating
    probs = torch.tensor([[0.1, 0.2, 0.3, 0.4]])
    _, _, mask = top_k_gating(probs, k=2)
    assert mask.sum().item() == 2
```

Run with `pytest -q` to see all tests pass.

## Extending It: Your Roadmap to Senior-Level

1. **Persistence & Model Export** – Save the router using `torch.jit.script` and load it in a production environment; this demonstrates model versioning and deployment readiness.
2. **Horizontal Scaling** – Shard experts across multiple GPUs or machines using `torch.distributed` and a parameter server; essential for handling large expert pools.
3. **Observability** – Integrate with Prometheus to expose routing statistics (expert utilization, top‑k entropy) and latency metrics; shows you care about system health.
4. **Fault Tolerance** – Implement fallback logic when an expert fails (e.g., route to a default expert) and use `torch.distributed.rpc` for heartbeat checks.
5. **Benchmarking Suite** – Create a script that measures throughput and memory usage across different `k` values and expert counts; useful for capacity planning.
6. **Dynamic Expert Addition** – Allow adding new experts at runtime without retraining, using a hash‑based routing table; signals adaptability in production.

Each upgrade directly maps to a real‑world concern, turning a toy into a resilient, observable service.

## Key Takeaways

- You have built a functional mixture‑of‑experts router with top‑k gating and sparse routing.
- The implementation is modular, making it easy to swap experts or integrate into larger models.
- The extension roadmap provides a clear path to a production‑grade system.
- This project highlights architecture design, efficient computation, and system engineering—key skills for senior roles.

## Further Reading

- [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538) – foundational paper on sparse MoE.
- [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668) – practical scaling insights.
- [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961) – modern sparse architecture.
- [PyTorch Distributed RPC Documentation](https://pytorch.org/docs/stable/rpc/index.html) – for building fault‑tolerant services.
- [Prometheus Client for Python](https://github.com/prometheus/client_python) – add observability to your router.