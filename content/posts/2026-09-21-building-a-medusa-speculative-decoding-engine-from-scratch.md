---
title: "Building a Medusa Speculative Decoding Engine from Scratch"
date: "2026-09-21T04:01:45.465"
draft: false
tags: ["machine-learning", "systems-engineering", "llm-optimization", "medusa", "speculative-decoding"]
description: "A hands-on guide to building a Medusa speculative decoding engine with auxiliary heads, token-tree verification, and KV-cache rollback to accelerate LLM inference."
summary: "Learn how to build a high-performance speculative decoding engine from scratch, mastering KV-cache management and token-tree verification to optimize LLM inference."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-building-a-medusa-speculative-decoding-engine-from-scratch.svg"
  alt: "A visual representation of a speculative decoding engine processing tokens across multiple parallel heads."
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding is the secret weapon for accelerating LLM inference without sacrificing accuracy. By building a Medusa speculative decoding engine from scratch, you will implement auxiliary heads, token-tree verification, and KV-cache rollback. This project demonstrates deep systems and ML engineering skills, proving you can optimize the bottlenecks that matter in production.

Large Language Models (LLMs) are notoriously slow during inference. While batching and flash attention help, the autoregressive nature of token generation remains a fundamental bottleneck. Speculative decoding solves this by using a smaller, faster "draft" model to propose several tokens at once, which a larger "target" model then verifies in a single forward pass. 

The Medusa framework takes this a step further by using multiple auxiliary heads to predict the next token in parallel, forming a verification tree. Building this from scratch is an exceptional portfolio project. It forces you to navigate the intersection of PyTorch internals, memory management, and graph theory. Here is how to build it.

## Why This Project Stands Out on a CV

Hiring managers for ML Infrastructure and Systems Engineering roles are constantly searching for candidates who understand the gap between model training and production serving. This project signals three highly specific competencies:

*   **Memory Architecture Mastery:** Managing a Key-Value (KV) cache is one of the hardest problems in LLM serving. Implementing rollback mechanisms proves you understand GPU memory allocation and state management.
*   **Parallelism and Concurrency:** Medusa's auxiliary heads require parallel computation. Building this demonstrates you can architect systems that maximize hardware utilization rather than just running sequential loops.
*   **Algorithmic Optimization:** Token-tree verification is essentially a graph traversal problem applied to LLM outputs. It shows you can translate theoretical computer science into performant engineering.

This project signals that you are not just a Python script runner; you are an engineer capable of optimizing the foundational layers of AI infrastructure.

## Architecture Overview

A Medusa speculative decoding engine consists of four primary components working in tandem. The system must balance compute latency against memory bandwidth to achieve a net speedup.

```text
+-----------------+       +-----------------+       +-----------------+       +-----------------+
|   Draft Model   |       |  Auxiliary Heads|       |  Token Tree     |       |  Target Model   |
|  (Base LLM)     |------>|  (Parallel Predictors)|-->|  (Verification DAG)|-->|  (Verifier)     |
+-----------------+       +-----------------+       +-----------------+       +-----------------+
        |                                               |                       |
        v                                               v                       v
+-----------------------------------------------------------------------------------------------------------+
|                                           KV-Cache Manager                                                |
|  - Caches Key/Value pairs for the draft tokens                                                          |
|   - Handles State Rollback if verification fails                                                        |
+-----------------------------------------------------------------------------------------------------------+
```

*   **Draft Model & Auxiliary Heads:** The base model generates an initial token, while the auxiliary heads predict subsequent tokens in parallel. 
*   **Token Tree:** A directed acyclic graph (DAG) that structures the draft tokens. If the target model accepts the root token, the tree expands; if it rejects, the tree prunes.
*   **KV-Cache Manager:** Stores the historical key-value pairs to avoid recomputation. Crucially, it must support atomic rollbacks to discard the state of rejected speculative tokens.
*   **Target Model:** The larger, authoritative model that verifies the draft tokens in a single forward pass, ensuring output parity with standard greedy decoding.

## Building It Step by Step

We will implement this using PyTorch and the HuggingFace `transformers` library. The code below represents the core logic required to make the engine function.

### Step 1: Initialize the Draft Model and Auxiliary Heads

Medusa requires a base model and multiple auxiliary heads attached to specific transformer layers. These heads predict the next token independently.

```python
import torch
import torch.nn as nn
from transformers import AutoModelForCausalLM, AutoTokenizer

class MedusaDraftModel:
    def __init__(self, base_model_name: str, num_heads: int = 4):
        self.base_model = AutoModelForCausalLM.from_pretrained(base_model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(base_model_name)
        self.num_heads = num_heads
        
        # Initialize auxiliary heads as lightweight linear layers
        self.auxiliary_heads = nn.ModuleList([
            nn.Linear(self.base_model.config.n_embd, self.base_model.config.vocab_size)
            for _ in range(num_heads)
        ])
        
    def forward_draft(self, input_ids: torch.Tensor):
        # Pass input through the base model to get hidden states
        outputs = self.base_model(input_ids=input_ids, output_hidden_states=True)
        hidden_states = outputs.hidden_states[-1]
        
        # Generate speculative tokens from each auxiliary head
        draft_tokens = []
        for head in self.auxiliary_heads:
            logits = head(hidden_states[:, -1, :])
            next_token = torch.argmax(logits, dim=-1)
            draft_tokens.append(next_token.unsqueeze(0))
            
        return torch.cat(draft_tokens, dim=0)
```

### Step 2: Build the Token Tree Verification Logic

The token tree verifies the draft tokens against the target model. If the target model accepts the first draft token, we proceed down that branch of the tree.

```python
class TokenTreeVerifier:
    def __init__(self, target_model: AutoModelForCausalLM):
        self.target_model = target_model
        
    def verify_tree(self, input_ids: torch.Tensor, draft_tokens: torch.Tensor):
        # Combine input and draft tokens for target verification
        candidate_ids = torch.cat([input_ids, draft_tokens], dim=1)
        
        # Target model verifies all draft tokens in a single forward pass
        with torch.no_grad():
            outputs = self.target_model(input_ids=candidate_ids)
            logits = outputs.logits
            
        # Check acceptance: does the target model agree with the draft?
        target_logits = logits[0, -len(draft_tokens):, :]
        target_next = torch.argmax(target_logits, dim=-1)
        
        # If target matches the first draft token, we have an acceptance
        accepted_tokens = []
        for i, token in enumerate(draft_tokens[0]):
            if token == target_next[i]:
                accepted_tokens.append(token.item())
            else:
                break
                
        return accepted_tokens
```

### Step 3: Implement the KV-Cache Rollback Mechanism

This is the most critical systems component. If the target model rejects a speculative token, we must roll back the KV-cache to the state before the draft tokens were generated, preventing memory corruption.

```python
class KVCacheManager:
    def __init__(self, model: AutoModelForCausalLM, cache_len: int = 1024):
        self.model = model
        self.cache_len = cache_len
        self.key_cache = []
        self.value_cache = []
        self.current_len = 0
        
    def save_state(self):
        # Snapshot the current KV cache state before speculative generation
        self.snapshot_keys = [k.clone() for k in self.key_cache]
        self.snapshot_values = [v.clone() for v in self.value_cache]
        self.snapshot_len = self.current_len
        
    def rollback(self):
        # Restore the KV cache to the saved snapshot state
        self.key_cache = [k for k in self.snapshot_keys]
        self.value_cache = [v for v in self.snapshot_values]
        self.current_len = self.snapshot_len
        
    def append_to_cache(self, keys: torch.Tensor, values: torch.Tensor):
        # Append new key-value pairs to the cache
        self.key_cache.append(keys)
        self.value_cache.append(values)
        self.current_len += keys.shape[1]
```

### Step 4: Orchestrate the Speculative Decoding Loop

Finally, we combine the draft model, verifier, and cache manager into a single inference loop.

```python
def speculative_decode(prompt: str, draft_model: MedusaDraftModel, verifier: TokenTreeVerifier, cache_mgr: KVCacheManager):
    input_ids = draft_model.tokenizer.encode(prompt, return_tensors="pt")
    
    # Save KV cache state before speculation
    cache_mgr.save_state()
    
    # Step 1: Draft tokens using auxiliary heads
    draft_tokens = draft_model.forward_draft(input_ids)
    
    # Step 2: Verify tokens against the target model
    accepted_tokens = verifier.verify_tree(input_ids, draft_tokens)
    
    if len(accepted_tokens) == 0:
        # Rollback if no tokens were accepted
        cache_mgr.rollback()
        return input_ids
    
    # Step 3: Append accepted tokens to the cache
    new_tokens = torch.tensor([accepted_tokens])
    # ... (logic to compute and append KV cache for new_tokens)
    cache_mgr.append_to_cache(new_keys, new_values)
    
    return torch.cat([input_ids, new_tokens], dim=1)
```

## Running and Testing It

To run this locally, you need a Python environment with PyTorch and HuggingFace Transformers installed. The following commands set up the environment and execute the engine.

```bash
# Clone the project repository and navigate into it
git clone https://github.com/your-repo/medusa-engine.git
cd medusa-engine

# Install the required dependencies
pip install torch transformers accelerate

# Run the speculative decoding engine with a baseline model
python main.py --model_name meta-llama/Llama-2-7b-hf --num_aux_heads 4
```

To prove the engine works, you must benchmark it against standard greedy decoding. The primary metric is **tokens per second (TPS)**. Because speculative decoding only provides a speedup when the target model accepts the draft tokens, you should observe a TPS increase proportional to the acceptance rate. If your implementation is correct, running the script will output the TPS for both the speculative engine and the baseline, demonstrating a measurable acceleration without any degradation in output quality.

## Extending It: Your Roadmap to Senior-Level

Turning this toy project into a production-grade system requires addressing the realities of distributed computing and observability. Here are five concrete upgrades that will elevate your portfolio:

1.  **Persistent KV-Cache Pool with Redis:** Implement a Redis-backed cache to store KV states across inference requests. *Why it matters:* It eliminates the need to recompute context for long conversations, drastically reducing latency in stateful chat applications.
2.  **Horizontal Scaling via Ray Serve:** Distribute the target verifier across multiple GPUs using Ray Serve. *Why it matters:* It allows the system to handle high-throughput traffic by parallelizing the verification step, which is the primary bottleneck in speculative decoding.
3.  **Prometheus and Grafana Observability:** Instrument the codebase to emit metrics like draft acceptance rate, KV-cache hit ratio, and speculative latency percentiles. *Why it matters:* Without observability, you cannot detect when the draft model is generating low-quality tokens that waste compute, masking the speedup benefits.
4.  **Dynamic Speculative Depth:** Adjust the number of auxiliary heads and draft tokens based on the prompt's perplexity. *Why it matters:* Simple prompts have high acceptance rates, while complex prompts often result in zero accepted tokens; dynamic depth maximizes the compute-to-speedup ratio.
5.  **Quantized Draft Models with GGUF:** Load the draft model using llama.cpp's GGUF format to reduce its memory footprint. *Why it matters:* It allows the draft model to run on CPU or smaller edge GPUs, freeing up precious VRAM on the target model's GPU for larger batch sizes.

## Key Takeaways

*   Speculative decoding accelerates LLM inference by using a fast draft model to propose tokens, which a larger target model verifies in a single pass.
*   The Medusa framework improves upon basic speculative decoding by using auxiliary heads to form a token-tree verification DAG.
*   Implementing a KV-cache rollback mechanism is the most critical systems engineering challenge, ensuring memory integrity when speculative tokens are rejected.
*   Building this project demonstrates rare hybrid skills in PyTorch internals, memory management, and algorithmic optimization.
*   Productionizing this engine requires addressing observability, dynamic resource allocation, and distributed scaling.

## Further Reading

To deepen your understanding and evolve this project further, study the primary sources and canonical documentation that define the field:

*   [Medusa: Simple Baselines for Accelerated LLM Inference](https://arxiv.org/abs/2302.01318) — The foundational paper introducing the auxiliary head architecture and token-tree verification.
*   [Accelerating Large Language Model Decoding with Speculative Sampling](https://arxiv.org/abs/2211.17192) — The original DeepMind paper on speculative decoding, which outlines the theoretical acceptance rates you are optimizing.
*   [HuggingFace Transformers Documentation](https://huggingface.co/docs/transformers/main/en/main_classes/model) — The canonical guide to implementing custom forward passes and managing model outputs in PyTorch.
*   [FlashAttention: Fast and Memory-Efficient Exact Attention](https://arxiv.org/abs/2205.14135) — The underlying attention mechanism that makes KV-cache management feasible on modern GPU hardware.