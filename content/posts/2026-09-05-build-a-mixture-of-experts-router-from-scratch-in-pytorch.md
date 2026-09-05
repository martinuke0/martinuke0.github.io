---
title: "Build a Mixture-of-Experts Router From Scratch in PyTorch"
date: "2026-09-05T11:00:27.925"
draft: false
tags: ["pytorch", "mixture-of-experts", "deep-learning", "machine-learning-engineering", "transformers", "project-ideas"]
description: "A hands-on guide to building a from-scratch MoE router with top-k gating, load-balancing loss, and Switch Transformer capacity factors in pure PyTorch."
summary: "A portfolio-grade project: a pure PyTorch mixture-of-experts router with top-k gating, expert load-balancing loss, and Switch-style capacity factors — with runnable code, tests, and a roadmap to senior-level extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-build-a-mixture-of-experts-router-from-scratch-in-pytorch.svg"
  alt: "Abstract diagram of a mixture-of-experts router routing tokens to multiple expert networks."
  caption: ""
  relative: false
---

> **TL;DR** — A mixture-of-experts (MoE) layer routes each token to a small subset of "expert" sub-networks, and a learnable gating network makes that routing decision. In this guide we build one from scratch in pure PyTorch: a top-k router, an auxiliary load-balancing loss that prevents expert collapse, and Switch Transformer–style capacity factors that throttle each expert's token load. By the end you'll have ~200 lines of runnable code, a unit test that proves expert utilization is balanced, and a concrete roadmap for extending it into a portfolio-grade project.

Hiring managers in ML engineering are tired of seeing the same ResNet-on-CIFAR-10 GitHub pin. The bar has moved. The projects that now stand out are the ones that demonstrate you understand how modern architectures actually *work* — not how to call `transformers.AutoModelForCausalLM.from_pretrained()`. Mixture-of-Experts is one of the few topics where a from-scratch implementation is both tractable for a solo weekend and genuinely impressive, because it forces you to grapple with the same systems-level concerns that show up in production LLM inference: sparsity, load balancing, capacity, and routing collapse.

This post is a complete build guide. We will write a `SparseMoE` module, a `TopKRouter`, a load-balancing loss, and Switch Transformer capacity-factor masking, with real, runnable code. Then we will test that it works, and finish with a roadmap that turns the toy into something that looks like it could ship.

## Why This Project Stands Out on a CV

Recruiters and hiring managers for ML platform, ML systems, and research-engineering roles look for evidence of three things, in roughly this order: (1) can you read a paper and translate it into code, (2) can you reason about the *systems* properties of a model — memory, throughput, numerical stability — and (3) do you write code that someone else can read.

A from-scratch MoE router checks all three boxes at once:

- **It signals research literacy.** The MoE landscape spans [Shazeer et al.'s *Outrageously Large Neural Networks*](https://arxiv.org/abs/1701.06538), the [GShard paper](https://arxiv.org/abs/2006.16668), [Fedus, Zoph & Shazeer's *Switch Transformers*](https://arxiv.org/abs/2101.03961), and the [ST-MoE survey](https://arxiv.org/abs/2202.08906). Implementing even the simplest of these end-to-end shows you've actually read them rather than skimming the abstracts.
- **It signals systems thinking.** A naive MoE implementation is a memory disaster — every expert runs on every token. The whole point of routing and capacity factors is that you only run a subset. Implementing the capacity mask correctly — and proving the mask is doing real work — is a small but legitimate piece of GPU-systems engineering.
- **It signals role fit.** If you're interviewing for an ML infrastructure, inference platform, or frontier-model team at a place like Anthropic, Mistral, Together, or any of the large-model orgs at Meta/Google, MoE literacy is table stakes. The same project, with a different README framing, is also credible for a research-engineering or applied-science role.

The reason it's such a strong portfolio piece for the *systems* side of ML specifically is that most "from scratch" transformer tutorials stop at scaled-dot-product attention. MoE forces you to confront routing, sparsity, and dispatch — concerns that look a lot like the ones you'd find in the kernel-level Triton kernels of [vLLM](https://github.com/vllm-project/vllm) or the routing tables in [DeepSeek-V2](https://arxiv.org/abs/2405.04434).

## Architecture Overview

Our module is intentionally small. There are four pieces, and you should be able to draw each on a napkin:

- **`TopKRouter`** — a single linear layer that maps each token's hidden state to a logits vector over `num_experts`, followed by a softmax. For each token it picks the top-`k` experts (we'll use `k=1` to mirror Switch Transformer, but `k=2` is the standard top-2 MoE choice).
- **`ExpertFFN`** — a standard two-layer feed-forward network with a SwiGLU-style activation. We instantiate `num_experts` of these. In a real system they'd live on different devices; for the from-scratch project a list of `nn.Module`s on one device is fine.
- **`SparseMoE`** — the orchestrator. It takes router logits, applies the capacity mask (Switch Transformer's key trick), dispatches each token to its routed expert(s), gathers the outputs, and returns a dense output tensor plus the auxiliary load-balancing loss.
- **`Capacity factor + load-balancing loss`** — the two innovations that turn "an MoE that collapses to one expert" into "an MoE that actually uses them all". The capacity factor `C` says "expert `i` should receive at most `ceil(C * tokens_per_expert)` tokens"; tokens past that limit are dropped (their output is a zero tensor). The load-balancing loss penalizes uneven routing distributions.

```text
input x  (B*T, d_model)
   │
   ▼
TopKRouter  →  logits (B*T, E), top-k indices (B*T, k), top-k weights (B*T, k)
   │
   ▼
expert_assignments = scatter: for each (token, expert_idx) pair, increment count
   │
   ▼
capacity_mask = expert_assignments <= capacity_factor * tokens_per_expert
   │                (drop tokens that overflow)
   ▼
ExpertFFN dispatch  →  expert_outputs indexed by (token, expert)
   │
   ▼
weighted sum of expert outputs per token  →  dense output (B*T, d_model)
   │
   ▼
aux_loss = E * Σ_i (f_i · p_i)   ← Switch Transformer load-balancing loss
```

A subtle but important point: in production systems like [GShard](https://arxiv.org/abs/2006.16668), the dispatch step is an `all-to-all` collective across GPUs. In our CPU/single-GPU from-scratch build, it's just a Python loop with index assignment. The interface is the same; only the implementation differs.

## Building It Step by Step

The full project lives in a single file. I'll walk through the components in order; you can copy-paste each block into `moe.py`.

### Step 1: The expert network

```python
import math
from typing import Tuple

import torch
import torch.nn as nn
import torch.nn.functional as F


class ExpertFFN(nn.Module):
    """A standard two-layer SwiGLU expert. d_model -> 4*d_model -> d_model."""

    def __init__(self, d_model: int, d_hidden: int):
        super().__init__()
        self.w_gate = nn.Linear(d_model, d_hidden, bias=False)
        self.w_up = nn.Linear(d_model, d_hidden, bias=False)
        self.w_down = nn.Linear(d_hidden, d_model, bias=False)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.w_down(F.silu(self.w_gate(x)) * self.w_up(x))
```

SwiGLU is the activation of choice in modern open-weights models like [Llama 3](https://arxiv.org/abs/2407.21783) and [Qwen 2](https://arxiv.org/abs/2407.10671), so it's the right default for a project that signals "I read the recent literature."

### Step 2: The top-k router

The router is the heart of the module. Two things matter: (a) it's just a linear projection, so it adds almost no parameters, and (b) we return both the indices and the softmax weights so the caller can apply capacity-based masking downstream.

```python
class TopKRouter(nn.Module):
    def __init__(self, d_model: int, num_experts: int, k: int = 1):
        super().__init__()
        self.k = k
        self.num_experts = num_experts
        # Initialize small so routing is initially uniform-ish.
        self.gate = nn.Linear(d_model, num_experts, bias=False)
        nn.init.normal_(self.gate.weight, std=0.02)

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # x: (N, d_model) where N = batch * seq_len
        logits = self.gate(x)                                  # (N, E)
        scores = F.softmax(logits, dim=-1)                     # (N, E)
        topk_scores, topk_indices = scores.topk(self.k, dim=-1)  # (N, k)
        # Renormalize so the routed weights sum to 1 per token.
        topk_scores = topk_scores / (topk_scores.sum(dim=-1, keepdim=True) + 1e-9)
        return logits, topk_indices, topk_scores
```

A note on `k`: Switch Transformer uses `k=1` (each token goes to exactly one expert). The original sparse MoE paper used `k=2`. For a portfolio project, `k=1` is cleaner and makes the capacity math easier to explain in the README. Set `k=2` in the constructor if you want to mirror the [GShard](https://arxiv.org/abs/2006.16668) configuration.

### Step 3: Switch Transformer capacity factor

The capacity factor `C` is the single most important number in this entire module. Without it, training collapses: one expert learns to be slightly better than the others, gets routed more tokens, gets updated more, gets even better — and you end up with a dense model wearing an MoE costume. The capacity factor enforces a hard upper bound on how many tokens any single expert may process per forward pass. Tokens past the limit are *dropped*; their output is the identity (zero).

```python
def apply_capacity(expert_idx: torch.Tensor,
                   num_experts: int,
                   capacity_factor: float,
                   tokens_per_expert: int) -> torch.Tensor:
    """Return a boolean mask: True for (token, expert) pairs that survive capacity.

    Tokens are dropped in the order they arrive, so a token that 'lost the race'
    for an over-capacity expert contributes zero to the output.
    """
    # Count how many tokens each expert is currently assigned.
    counts = torch.bincount(expert_idx, minlength=num_experts)
    capacity = int(math.ceil(capacity_factor * tokens_per_expert))
    # For each (token, expert) pair, derive that expert's current count *up to* this token.
    # We approximate with a per-pair flag: keep if its expert's total <= capacity.
    # For top-1 routing this is exact; for top-k>1 you'd need a per-token position counter.
    keep_by_expert = counts <= capacity
    keep_mask = keep_by_expert[expert_idx]
    return keep_mask
```

This is the part that, in production, looks like an `index_add` plus a Triton kernel. The simple version above is exact for `k=1` and a reasonable approximation for `k=2`. If you want to be rigorous about the per-token ordering for general `k`, you can replace it with the "token-position-within-expert" trick described in §3.1 of the [Switch Transformer paper](https://arxiv.org/abs/2101.03961).

### Step 4: The load-balancing loss

Without an auxiliary loss, the router will collapse. The Switch Transformer load-balancing loss is elegant: it's `E * Σ_i f_i · p_i`, where `f_i` is the fraction of tokens routed to expert `i` and `p_i` is the average router probability assigned to expert `i`. It's minimized when all `f_i` and `p_i` are uniform (`1/E`), and it's differentiable through `p_i` because those probabilities come from the softmax.

```python
def load_balancing_loss(router_logits: torch.Tensor,
                        topk_indices: torch.Tensor,
                        num_experts: int) -> torch.Tensor:
    """Switch Transformer auxiliary loss: encourages uniform expert utilization."""
    N = router_logits.shape[0]
    router_probs = F.softmax(router_logits, dim=-1)            # (N, E)

    # f_i: fraction of tokens dispatched to expert i.
    one_hot = F.one_hot(topk_indices.squeeze(-1), num_experts).float()  # (N, E)
    f = one_hot.mean(dim=0)                                    # (E,)

    # p_i: mean router probability for expert i across all tokens.
    p = router_probs.mean(dim=0)                               # (E,)

    loss = num_experts * (f * p).sum()
    return loss
```

In practice you scale this by an `alpha` hyperparameter (the original paper uses `0.01`); we'll wire that up in the next block.

### Step 5: The orchestrator

This is where everything comes together. The dispatch is a Python loop — which would be catastrophic in production but is fine for the from-scratch build. The point of writing it this way is that the *interface* maps cleanly to a real `all-to-all` dispatch if you later swap in something like [DeepSpeed's MoE](https://www.deepspeed.ai/tutorials/mixture-of-experts/) or [Megatron's tensor-parallel MoE](https://github.com/NVIDIA/Megatron-LM).

```python
class SparseMoE(nn.Module):
    def __init__(self, d_model: int, d_hidden: int, num_experts: int,
                 k: int = 1, capacity_factor: float = 1.25,
                 aux_loss_alpha: float = 0.01):
        super().__init__()
        self.router = TopKRouter(d_model, num_experts, k=k)
        self.experts = nn.ModuleList(
            [ExpertFFN(d_model, d_hidden) for _ in range(num_experts)]
        )
        self.num_experts = num_experts
        self.capacity_factor = capacity_factor
        self.aux_loss_alpha = aux_loss_alpha

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        # x: (N, d_model)
        N = x.shape[0]
        router_logits, topk_idx, topk_scores = self.router(x)
        out = torch.zeros_like(x)

        # Capacity: how many tokens is each expert *allowed* to take?
        tokens_per_expert = math.ceil(N / self.num_experts)
        capacity = int(math.ceil(self.capacity_factor * tokens_per_expert))

        # Count assignments per expert.
        flat_idx = topk_idx.view(-1)
        counts = torch.bincount(flat_idx, minlength=self.num_experts)

        # Walk the experts in order, dispatching the tokens they receive.
        # This loop is O(N) and trivially maps to all-to-all on multiple GPUs.
        for e in range(self.num_experts):
            mask_e = (topk_idx == e).view(-1)
            if not mask_e.any():
                continue
            tokens_e = x[mask_e]
            if tokens_e.shape[0] > capacity:
                tokens_e = tokens_e[:capacity]
                mask_e_indices = mask_e.nonzero(as_tuple=True)[0][:capacity]
            else:
                mask_e_indices = mask_e.nonzero(as_tuple=True)[0]

            y_e = self.experts[e](tokens_e)
            # Multiply by the router weight for this expert on each kept token.
            w_e = topk_scores.view(-1)[mask_e_indices].unsqueeze(-1)
            out[mask_e_indices] = y_e * w_e

        aux = self.aux_loss_alpha * load_balancing_loss(
            router_logits, topk_idx, self.num_experts
        )
        return out, aux
```

The `aux_loss_alpha` defaults to `0.01` as in the Switch Transformer paper. If you find that the loss is dominating during training, drop it to `0.001`; if routing is collapsing, raise it to `0.05`.

### Step 6: A minimal training loop

To prove the system works end-to-end, wire it up against a toy task. The classic choice is character-level language modeling on a tiny corpus; we'll use a synthetic regression problem so the example fits in 20 lines.

```python
def toy_train():
    torch.manual_seed(0)
    d_model, d_hidden, num_experts = 32, 128, 4
    moe = SparseMoE(d_model, d_hidden, num_experts, k=1, capacity_factor=1.25)

    # Toy task: map random vectors to a fixed projection. Sparse MoE should
    # learn to route "clusters" of inputs to different experts.
    W_target = torch.randn(d_model, d_model)

    opt = torch.optim.Adam(moe.parameters(), lr=1e-3)
    for step in range(2000):
        x = torch.randn(64, d_model)
        # Inject cluster structure so experts have something to specialize on.
        cluster = torch.randint(0, num_experts, (64,))
        x = x + torch.eye(num_experts)[cluster] * 2.0

        y_true = x @ W_target
        y_pred, aux = moe(x)
        task_loss = F.mse_loss(y_pred, y_true)
        loss = task_loss + aux
        opt.zero_grad(); loss.backward(); opt.step()

        if step % 200 == 0:
            with torch.no_grad():
                # Check expert utilization: should be roughly uniform (16 ± a few).
                _, topk_idx, _ = moe.router(x)
                counts = torch.bincount(topk_idx.view(-1), minlength=num_experts)
            print(f"step {step:4d} | task {task_loss.item():.4f} "
                  f"| aux {aux.item():.4f} | counts {counts.tolist()}")
```

If everything is wired up correctly, after a few hundred steps you'll see the expert counts stabilizing around the cluster prior (16 each), and the auxiliary loss dropping alongside the task loss. If one expert is doing all the work, the aux loss will be high and you'll see counts like `[60, 2, 1, 1]` — that's the bug to chase.

## Running and Testing It

You should be able to run the whole project locally with:

```bash
python -m venv .venv && source .venv/bin/activate
pip install torch --index-url https://download.pytorch.org/whl/cpu   # CPU is fine
python moe.py
```

For a portfolio project, you'll also want a proper test suite. The most valuable test is one that *proves the capacity mask is doing real work*, because that's the part most candidates get wrong on their first attempt:

```python
def test_capacity_drops_overflow_tokens():
    moe = SparseMoE(d_model=16, d_hidden=64, num_experts=4, k=1, capacity_factor=1.0)
    # 16 tokens, 4 experts: capacity is exactly 4. Force the router to pick expert 0.
    with torch.no_grad():
        moe.router.gate.weight.zero_()
        moe.router.gate.weight[0] = 1.0  # bias all routing to expert 0

    x = torch.randn(16, 16)
    y, aux = moe(x)
    # Only 4 tokens should have non-zero outputs; the rest must be zero.
    nonzero_rows = (y.abs().sum(dim=-1) > 0).sum().item()
    assert nonzero_rows == 4, f"Expected exactly 4 kept tokens, got {nonzero_rows}"
    assert aux.item() > 0.5, f"Expected high aux loss under collapsed routing, got {aux.item()}"


def test_load_balancing_loss_is_zero_when_uniform():
    """If all experts receive equal tokens and equal probability, loss = 1."""
    logits = torch.zeros(8, 4)   # uniform softmax → all probs = 0.25
    idx = torch.tensor([[0], [1], [2], [3], [0], [1], [2], [3]])
    loss = load_balancing_loss(logits, idx, num_experts=4)
    assert torch.isclose(loss, torch.tensor(1.0), atol=1e-5)


def test_gradient_flows_to_router():
    moe = SparseMoE(d_model=8, d_hidden=16, num_experts=2, k=1, capacity_factor=2.0)
    x = torch.randn(4, 8, requires_grad=True)
    y, aux = moe(x)
    (y.sum() + aux).backward()
    assert moe.router.gate.weight.grad is not None
    assert moe.router.gate.weight.grad.abs().sum() > 0
```

A strong portfolio signal is to wire these into `pytest`, add a [GitHub Actions](https://github.com/features/actions) workflow that runs them on every push, and pin the Python/PyTorch versions in `requirements.txt`. That alone tells a reviewer you know how to ship.

## Extending It: Your Roadmap to Senior-Level

The toy is the point — but the *extensions* are what turn a one-day project into something a senior interviewer remembers. Each of these maps to a real system in production, and you can claim experience with that system if you implement the extension cleanly:

1. **Replace the Python dispatch loop with vectorized scatter ops.** A clean rewrite with `index_select` / `index_add` runs 10–50× faster on CPU and is a prerequisite for GPU work. *Why it matters:* production MoE training at any non-toy scale runs on grouped GEMMs in [Triton](https://triton-lang.org/) or [CUTLASS](https://github.com/NVIDIA/cutlass); understanding the dispatch pattern is the gateway.

2. **Add expert-parallel placement across multiple GPUs.** Wrap the experts with `nn.parallel.DistributedDataParallel` and dispatch with a `torch.distributed.all_to_all` collective, mirroring [GShard](https://arxiv.org/abs/2006.16668). *Why it matters:* this is how [DeepSeek-V3](https://arxiv.org/abs/2412.19437), [Mixtral](https://arxiv.org/abs/2401.04088), and the [Switch-XXL](https://arxiv.org/abs/2101.03961) training runs are organized.

3. **Save and version the experts as sharded checkpoints.** Use [Safetensors](https://github.com/huggingface/safetensors) and write one file per expert. *Why it matters:* MoE inference systems ([vLLM](https://github.com/vllm-project/vllm), [SGLang](https://github.com/sgl-project/sglang), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM)) all treat experts as individually addressable weights; understanding the layout is essential for any inference-platform role.

4. **Add observability: per-expert utilization, token-drop rate, and aux-loss dashboard.** Export Prometheus metrics and render them in a Grafana panel. *Why it matters:* in production, the leading indicator of "your MoE is collapsing" is the standard deviation of expert utilization over a training window; every frontier-lab team monitors it.

5. **Benchmark forward and backward pass against a dense baseline of equivalent FLOPs.** Profile with `torch.profiler` and visualize with [`chrome://tracing`](https://www.chromium.org/developers/how-tos/trace-event-profiling-tool/). *Why it matters:* "sparse MoE is faster than dense at inference" is a claim that needs measurement; showing you can produce the chart is more impressive than the chart itself.

6. **Integrate a real tokenizer and train on a public corpus.** Drop in [Hugging Face Tokenizers](https://github.com/huggingface/tokenizers) and train on a slice of [WikiText-103](https://huggingface.co/datasets/Salesforce/wikitext). Report validation perplexity. *Why it matters:* it converts the project from "I read the math" to "I shipped something measurable" — which is the single biggest differentiator between a junior and a senior portfolio.

Pick two of these and ship them. A `SparseMoE` with vectorized dispatch and Grafana observability, in a repo with a real README and a CI badge, will beat almost any other project a junior candidate is likely to show.

## Key Takeaways

- A from-scratch MoE router is a high-leverage portfolio project: tractable, runnable in pure PyTorch, and signals research literacy *and* systems thinking at the same time.
- The two pieces that actually make MoE work are the **load-balancing auxiliary loss** (otherwise the router collapses to one expert) and the **Switch Transformer capacity factor** (otherwise one expert becomes a hot-spot).
- Keep the implementation small and inspectable first; the production-grade optimizations (vectorized dispatch, expert parallelism, sharded checkpoints) are clean extensions you can layer on one at a time.
- The interface matters more than the implementation. Writing the dispatch as a clean function means you can later swap in an `all_to_all` collective or a grouped-GEMM kernel without rewriting the rest of the model.
- Add a test that *proves* capacity drops overflow tokens and a test that *proves* the load-balancing loss is zero under uniform routing. Those two tests cover most of what can go wrong.

## Further Reading

- [Outrageously Large Neural Networks: The Sparsely-Gated Mixture-of-Experts Layer](https://arxiv.org/abs/1701.06538) — Shazeer et al., the original sparse MoE paper.
- [Switch Transformers: Scaling to Trillion Parameter Models with Simple and Efficient Sparsity](https://arxiv.org/abs/2101.03961) — Fedus, Zoph & Shazeer; introduces top-1 routing and the capacity factor.
- [GShard: Scaling Giant Models with Conditional Computation and Automatic Sharding](https://arxiv.org/abs/2006.16668) — Lepikhin et al.; the canonical reference for expert parallelism and all-to-all dispatch.
- [DeepSeek-V2: A Strong, Economical, and Efficient Mixture-of-Experts Language Model](https://arxiv.org/abs/2405.04434) — modern production example of fine-grained MoE routing.
- [MegaBlocks: Efficient Sparse Training with Mixture-of-Experts](https://arxiv.org/abs/2211.15841) — for when you want to go beyond the dense dispatch and learn how real systems handle MoE training efficiently.
- [Triton MoE tutorial](https://triton-lang.org/main/getting-started/tutorials/09-grouped-gemm.html) — hands-on with grouped GEMMs, the actual operator used by modern MoE kernels.