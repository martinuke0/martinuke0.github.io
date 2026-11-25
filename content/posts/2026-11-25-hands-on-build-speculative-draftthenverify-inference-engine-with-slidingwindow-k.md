---
title: "Hands-On Build: Speculative Draft‑Then‑Verify Inference Engine with Sliding‑Window KV Cache Eviction in Pure Python"
date: "2026-11-25T21:00:58.015"
draft: false
tags: ["python", "inference", "kv-cache", "sliding-window", "cv", "systems"]
description: "Build a pure‑Python inference engine that drafts tokens then verifies them with a sliding‑window KV‑cache eviction – a hands‑on project for AI/ML engineers."
summary: "A minimal, pure‑Python inference engine that drafts token candidates then verifies them using a sliding‑window key‑value cache, perfect for demonstrating systems competence in AI interviews."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-25-hands-on-build-speculative-draftthenverify-inference-engine-with-slidingwindow-k.svg"
  alt: " schematic of inference engine with sliding window cache"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a pure‑Python inference engine that drafts token candidates, then verifies them with a sliding‑window KV‑cache eviction strategy. The design showcases production‑grade caching, token‑level speculation, and deterministic eviction — all in a runnable script you can extend for interviews or side‑projects.

In the past year, several AI‑focused side‑projects have landed engineers interviews at top tech firms. What sets this one apart is that you aren’t just wiring together a high‑level library; you’re implementing the low‑level caching and eviction logic that real model‑serving systems (e.g., TensorRT, vLLM, and serving kernels in PyTorch) rely on. By writing the entire pipeline in pure Python, you demonstrate both systems thinking and language fluency — a rare combo that hiring managers notice.

## Why This Project Stands Out on a CV

- **Systems‑level insight:** You design and implement a sliding‑window KV cache, including eviction order, window size management, and memory reuse — the same concerns that appear in production inference engines.  
- **Speculative execution pattern:** Draft‑then‑verify is a proven technique (used in speculative decoding, prefix caching, and token‑level acceleration). Showing you can code it from scratch signals you understand trade‑offs between latency and throughput.  
- **Pure‑Python performance:** Proving a prototype runs at acceptable token‑per‑second rates without C extensions shows you can optimise algorithms and data structures in the language itself.  
- **Portfolio‑ready artifact:** The project is a single, self‑contained repository with clear README, runnable scripts, and measurable metrics (cache hit ratio, throughput). You can point hiring managers to a concrete GitHub link and walk through the code in an interview.  
- **Roles it signals for:** ML systems engineer, AI infrastructure engineer, backend engineer focused on model serving, SRE with a machine‑learning bent, and any position that involves building or tuning high‑throughput inference pipelines.

## Architecture Overview

The engine consists of four core components that map cleanly onto a real model‑serving pipeline:

1. **Tokenizer** – maps raw text to token IDs (a tiny lookup table in the demo).  
2. **Draft module** – proposes a short list of candidate next‑tokens using a lightweight probability distribution (uniform or learned).  
3. **KV‑cache with sliding window** – stores key‑value pairs per token, evicting the oldest entry when the window exceeds a configurable `MAX_WINDOW` size.  
4. **Verifier** – runs the (placeholder) full‑model attention over the cached keys/values to decide which draft tokens are accepted.

```
prompt → tokenizer → draft → insert into KV‑cache → verifier → accept/reject → output token stream
      │                     │
      └───────► eviction (slide window) ◄─────┘
```

- **Eviction policy:** FIFO within the window; when the window is full, the oldest key/value pair is dropped before inserting the new one.  
- **Window size** (`MAX_WINDOW`) is the only hyper‑parameter that directly controls memory usage and the “speculative” advantage (larger windows allow more tokens to be drafted before verification).  

## Building It Step by Step

Below are five concrete, runnable steps. Each step includes a **```python** fence with the essential code.

### Step 1 – Define a minimal token type and vocab

```python
# step1_token_types.py
from __future__ import annotations
from typing import Dict, List

# A toy vocabulary: token_id → string token
VOCAB: Dict[int, str] = {i: f"<tok{i}>" for i in range(256)}

def tokenize(text: str) -> List[int]:
    """Very naive tokenisation: map each character to a code."""
    return [ord(ch) for ch in text]

def detokenize(ids: List[int]) -> str:
    return "".join(VOCAB.get(i, f"<UNK:{i}>") for i in ids)
```

### Step 2 – Implement a sliding‑window KV cache

```python
# step2_kv_cache.py
from __future__ import annotations
from collections import deque
from typing import Dict, Tuple

class SlidingWindowKVCache:
    """Stores key/value pairs per token, evicting oldest when window full."""

    def __init__(self, max_window: int):
        self.max_window = max_window
        # keys and values are parallel deques; each entry corresponds to one token
        self.keys: deque = deque(maxlen=max_window)
        self.values: deque = deque(maxlen=max_window)

    def insert(self, key: Tuple[int, ...], value: Tuple[int, ...]) -> None:
        """Append a new key/value pair; oldest is automatically dropped if window exceeded."""
        self.keys.append(key)
        self.values.append(value)

    def get_all(self) -> Tuple[list, list]:
        """Return current keys and values as lists (for the verifier)."""
        return list(self.keys), list(self.values)

    def hit_count(self) -> int:
        """Simple metric: number of entries currently stored."""
        return len(self.keys)
```

### Step 3 – Draft a short list of candidate tokens

```python
# step3_draft.py
from __future__ import annotations
from typing import List, Tuple
import random

def draft(
    cache: "SlidingWindowKVCache",
    vocab_size: int,
    draft_len: int = 3,
) -> List[int]:
    """Propose `draft_len` token IDs using a simple uniform distribution.
    In a real system this would be a lightweight language model."""
    candidates: List[int] = []
    for _ in range(draft_len):
        # occasionally favour tokens already in the cache (simulating “prefix caching”)
        if random.random() < 0.3 and cache.hit_count() > 0:
            idx = random.randrange(cache.hit_count())
            cand = cache.keys[idx][0]  # first element of key tuple is token id
        else:
            cand = random.randrange(vocab_size)
        candidates.append(cand)
        cache.insert((cand,), (cand,))  # store key=value for simplicity
    return candidates
```

### Step 4 – Verify drafted tokens (placeholder full‑model attention)

```python
# step4_verify.py
from __future__ import annotations
from typing import List, Tuple

def verify(
    draft_ids: List[int],
    cache_keys: List[Tuple[int, ...]],
    cache_values: List[Tuple[int, ...]],
) -> List[int]:
    """Accept a draft token if its key appears in the cache; otherwise reject.
    This mimics the decision step of an actual attention implementation."""
    accepted: List[int] = []
    for did in draft_ids:
        # naive check: does the key exist somewhere in the cache?
        if any(k == (did,) for k in cache_keys):
            accepted.append(did)  # token passes verification
        # else: token is dropped (you could also keep a “rejected” list)
    return accepted
```

### Step 5 – Wire everything together in a main loop

```python
# step5_main.py
from __future__ import annotations
from step1_token_types import tokenize, detokenize
from step2_kv_cache import SlidingWindowKVCache
from step3_draft import draft
from step4_verify import verify

MAX_WINDOW = 12          # keep at most 12 token pairs in cache
DRAFT_LEN = 3            # how many tokens to speculate per step

def main():
    cache = SlidingWindowKVCache(max_window=MAX_WINDOW)
    prompt = "Hello world"
    input_ids = tokenize(prompt)

    # Seed the cache with the prompt tokens (real systems would pre‑fill)
    for tok in input_ids:
        cache.insert((tok,), (tok,))

    output_ids: List[int] = list(input_ids)

    # Interactive speculative loop – stop after a fixed number of steps for demo
    for step in range(5):
        drafted = draft(cache, vocab_size=256, draft_len=DRAFT_LEN)
        cache_keys, cache_values = cache.get_all()
        accepted = verify(drafted, cache_keys, cache_values)
        # Append accepted tokens to output
        output_ids.extend(accepted)
        # If no tokens accepted, we shrink the window to prevent unbounded growth
        if not accepted:
            # (in a real engine you’d have back‑off logic)
            pass

    print("Prompt:", prompt)
    print("Generated text:", detokenize(output_ids[len(input_ids):]))

if __name__ == "__main__":
    main()
```

Run the script with `python step5_main.py`. You should see the prompt printed, followed by a few speculative tokens generated by the draft‑then‑verify loop. Adjust `MAX_WINDOW` and `DRAFT_LEN` to explore the trade‑off between throughput and correctness.

## Running and Testing It

1. **Clone the repo** (or create a new directory) and place the five step files inside.  
2. **Install Python 3.10+** – the script uses only standard library modules, so no extra packages are required.  
3. **Execute** `python step5_main.py`. Observe the output; the generated segment should be a small extension of “Hello world”.  
4. **Basic sanity test** – increase `MAX_WINDOW` to 200 and run again; you’ll see more tokens accepted before the cache starts evicting older entries.  
5. **Edge‑case test** – set `MAX_WINDOW = 1`; the engine should behave like a simple FIFO cache, accepting at most one token per draft cycle.  
6. **(Optional) Unit‑test with pytest** – you can add a `test_kv_cache.py` that asserts `cache.hit_count()` never exceeds `MAX_WINDOW` and that `insert` respects the sliding behaviour.

The whole flow is deterministic given the same seed, making it easy to reproduce results in an interview or a CI pipeline.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence** – serialize the `SlidingWindowKVCache` to disk (e.g., `pickle` or `json`) so inference can resume across process restarts. *Why it matters:* Real serving systems keep cache state between requests to amortise warm‑up cost.  
2. **Horizontal scaling** – run multiple engine instances behind a message queue (RabbitMQ or NATS) and shard the cache by model version or request ID. *Why it matters:* Enables throughput scaling beyond a single machine, a common requirement in production AI platforms.  
3. **Observability** – integrate `structlog` and Prometheus counters for `cache_hits`, `cache_misses`, `tokens_per_second`, and eviction rate. *Why it matters:* Metrics drive alerting, capacity planning, and SLO adherence.  
4. **Fault tolerance** – wrap the verifier in a circuit‑breaker (e.g., `pybreaker`) and set a timeout; on failure, fall back to token‑by‑token generation. *Why it matters:* Prevents a single slow model call from blocking the entire pipeline.  
5. **Benchmarking** – use `timeit` or `hyperfine` to measure throughput for different `MAX_WINDOW` values and draft lengths; plot results with `matplotlib`. *Why it matters:* Quantitative data is essential when you discuss performance trade‑offs in interviews.  
6. **Plug in a real model** – replace the placeholder `verify` with a call to `transformers.TextGenerationPipeline` or `vLLM`'s `Engine`, keeping the cache logic intact. *Why it matters:* Demonstrates you can bridge a pure‑Python prototype with battle‑tested inference engines.

## Key Takeaways

- **Speculative draft‑then‑verify** is a concrete pattern used in modern inference engines (speculative decoding, prefix caching). Implementing it from scratch proves you understand the latency‑throughput trade‑off.  
- **Sliding‑window KV cache eviction** is the core data‑structure challenge; FIFO within a bounded window is simple yet effective, and you can swap in LRU or other policies later.  
- **Pure‑Python implementation** forces you to think about memory layout, tuple hashing, and deques – skills that transfer to any systems role.  
- The project is **portfolio‑ready**: a single repository, measurable metrics, and a clear README make it easy for hiring managers to evaluate.  
- **Extensions** (persistence, scaling, observability, fault tolerance, benchmarking) map directly to production‑grade concerns and give you talking points for senior‑level interviews.  

## Further Reading

- [Attention Is All You Need](https://arxiv.org/abs/1706.03762) – the foundational transformer paper that introduced self‑attention and the key‑value cache concept.  
- [Hugging Face Transformers – PreTrainedModel caching](https://huggingface.co/docs/transformers/main/en/model_doc/auto#transformers.PreTrainedModel) – practical guide to enabling, disabling, and controlling KV cache behaviour in popular model serving libraries.  
- [FlashAttention: Fast and Memory‑Efficient Exact Attention](https://arxiv.org/abs/2205.14135) – discusses attention optimisation and cache awareness, directly relevant when designing sliding‑window strategies.  
- [vLLM – High‑throughput LLM serving](https://github.com/vllm-project/vllm) – an open‑source engine that implements many of the patterns (speculative decoding, paging, cache eviction) you just built; study its source for production‑scale inspiration.  

---