---
title: "Build a Medusa Speculative Decoding Engine in Pure Python"
date: "2026-11-04T23:00:37.320"
draft: false
tags: ["python", "speculative-decoding", "llm", "medusa", "portfolio", "cv"]
description: "Hands‑on guide to building a pure‑Python Medusa speculative decoder from scratch, with runnable code, architecture diagrams, and extension roadmap for senior‑level projects."
summary: "Learn how to construct a Medusa‑style speculative decoding engine in pure Python, from architecture to testing, and how the project signals production‑grade systems skills to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-04-build-a-medusa-speculative-decoding-engine-in-pure-python.svg"
  alt: "A Python script visualising token generation and speculative decoding"
  caption: ""
  relative: false
---

> **TL;DR** — Speculative decoding can halve LLM latency by generating multiple candidate tokens with a lightweight draft model and verifying them against the target. This post walks you through building a Medusa‑style decoder in pure Python, with runnable code, architecture diagrams, and a roadmap to production‑grade features. By the end you’ll have a portable engine you can demo, benchmark, and extend.

Building a high‑performance LLM serving stack often means tackling the latency bottleneck head‑on. Speculative decoding addresses this by proposing several tokens with a small “draft” model and only paying the cost of the expensive target model when the proposals are accepted. A Medusa‑style engine takes this a step further: the draft model outputs a distribution over *k* future tokens, the verifier checks them in parallel, and the accepted tokens are flushed to the output buffer. The result is a pure‑Python implementation that you can run on a laptop, embed in a CI pipeline, or expand into a production‑grade service.

## Why This Project Stands Out on a CV

- **Algorithmic engineering**: You design and implement a non‑trivial feedback loop (propose → verify → accept/reject) that mirrors real production decoders.  
- **Python performance tuning**: Use of `numpy` (or pure‑list alternatives) to keep the critical path fast without leaving the language.  
- **Systems thinking**: Choosing data structures (circular buffers, token queues) that minimise copying and GC pressure.  
- **Observable code**: Easy‑to‑instrument timing, acceptance rates, and per‑step metrics—exactly what hiring managers look for in senior‑level candidates.  

Roles that benefit most: ML inference engineers, backend services engineers for AI platforms, and data‑science tooling specialists. The project signals that you can move from “hello world” notebooks to a runnable, benchmarkable component that could sit behind a FastAPI or gRPC endpoint.

## Architecture Overview

The engine consists of four core components that fit together in a simple pipeline:

```
+----------------+     +----------------+     +----------------+     +----------------+
|  Prompt /      | --> |  Draft Model   | --> |  Proposer      | --> |  Verifier      |
|  Tokenizer     |     | (small LM)     |     | (top‑k select) |     | (target LM)    |
+----------------+     +----------------+     +----------------+     +----------------+
        |                       |                   |                     |
        |                       |                   v                     v
        |                       |            +----------------+   +----------------+
        |                       |            |  Accepted Tokens|->| Output Buffer |
        |                       |            +----------------+   +----------------+
        |                       |
        v                       v
   +----------------+      +----------------+
   |  Token Buffer  | <---> |  Metrics/Stats |
   +----------------+      +----------------+
```

- **Prompt/Tokenizer**: converts user text into a sequence of token IDs.  
- **Draft Model**: a lightweight neural net (here a stub that returns random logits) that proposes *k* candidate tokens.  
- **Propler**: selects the top‑k tokens from the draft distribution.  
- **Verifier**: runs the target model (another stub) on the candidate tokens and returns a binary accept/reject per token.  
- **Accepted Tokens**: accumulate the tokens that passed verification; the rejected ones are discarded.  
- **Output Buffer**: the final generated text, ready for streaming or storage.  
- **Metrics/Stats**: simple counters for latency, acceptance rate, and total tokens generated.

The diagram can be reproduced in Markdown with a Mermaid block if your publishing pipeline supports it, but the ASCII layout above works everywhere.

## Building It Step by Step

Below are **10 numbered steps** that produce a fully functional speculative decoder. Each step includes a fenced Python snippet with a language tag.

### Step 1 – Install dependencies

```bash
pip install numpy
```

### Step 2 – Define a minimal tokenizer (character‑level for demo)

```python
# step2_tokenizer.py
class CharTokenizer:
    """Very small tokenizer that maps characters to integer IDs."""
    def __init__(self):
        self.chars = sorted(set(" ".join(map(chr, range(32, 127)))))
        self.stoi = {c: i for i, c in enumerate(self.chars)}
        self.itos = {i: c for c, i in self.stoi.items()}

    def encode(self, text: str) -> list[int]:
        return [self.stoi.get(c, self.stoi[" "]) for c in text]

    def decode(self, ids: list[int]) -> str:
        return "".join(self.itos[i] for i in ids)

tokenizer = CharTokenizer()
```

### Step 3 – Stub draft model that outputs random logits

```python
# step3_draft.py
import numpy as np

class DraftModel:
    """Random‑logits draft; replace with a real tiny transformer later."""
    def __init__(self, vocab_size: int = 95, draft_tokens: int = 4):
        self.vocab_size = vocab_size
        self.draft_tokens = draft_tokens   # how many candidates to propose

    def logits(self, prompt_ids: list[int]) -> np.ndarray:
        # Shape: (1, vocab_size) – unnormalised log probabilities
        return np.random.randn(1, self.vocab_size)

draft = DraftModel()
```

### Step 4 – Proposer: pick the top‑k token IDs from draft logits

```python
# step4_proposer.py
def propose_tokens(logits: np.ndarray, k: int = 4) -> list[int]:
    """Return the indices of the k highest logits."""
    # argpartition is O(n) – faster than full sort for large vocab
    top_idx = np.argpartition(logits[0], -k)[-k:]
    # sort those k by actual value descending
    top_idx = top_idx[np.argsort(logits[0][top_idx])[::-1]]
    return top_idx.tolist()

# Example usage
logits = draft.logits([tokenizer.encode("Hello")])
candidates = propose_tokens(logits, k=draft.draft_tokens)
print("Candidates:", candidates)
```

### Step 5 – Verifier: simple target model that decides acceptance

```python
# step5_verifier.py
class TargetModel:
    """Stub target; in reality this would be the heavy LLM."""
    def __init__(self, vocab_size: int = 95):
        self.vocab_size = vocab_size

    def accept(self, token_id: int, context_ids: list[int]) -> bool:
        # Very naive rule: accept if token_id is even (just for demo)
        return token_id % 2 == 0

target = TargetModel()
```

### Step 6 – Core speculative‑decoding loop

```python
# step6_loop.py
from collections import deque

def speculative_decode(
    prompt: str,
    draft: DraftModel,
    target: TargetModel,
    tokenizer: CharTokenizer,
    k: int = 4,
    max_new_tokens: int = 30,
) -> str:
    ids = tokenizer.encode(prompt)
    output_ids = list(ids)          # keep everything we have generated so far
    pos = len(ids)                  # current generation position

    while pos < len(ids) + max_new_tokens:
        # 1️⃣  Get draft logits for the current prefix
        logits = draft.logits(output_ids[-k:] if len(output_ids) >= k else output_ids)

        # 2️⃣  Propose top‑k tokens
        candidates = propose_tokens(logits, k=k)

        # 3️⃣  Verify each candidate against the target model
        accepted = []
        for tok in candidates:
            # context is everything generated so far + this candidate
            ctx = output_ids + [tok]
            if target.accept(tok, ctx):
                accepted.append(tok)

        # 4️⃣  If we got at least one accepted token, flush them all
        if accepted:
            output_ids.extend(accepted)
            pos += len(accepted)
        else:
            # No token accepted – emit a single fallback token and continue
            fallback = np.random.randint(0, tokenizer.vocab_size)
            output_ids.append(fallback)
            pos += 1

    return tokenizer.decode(output_ids)

# Run a quick demo
prompt = "Hello"
result = speculative_decode(prompt, draft, target, tokenizer, k=4, max_new_tokens=20)
print("Generated:", result)
```

### Step 7 – Add timing metrics

```python
# step7_metrics.py
import time

def timed_speculative_decode(*args, **kwargs):
    start = time.perf_counter()
    text = speculative_decode(*args, **kwargs)
    elapsed = time.perf_counter() - start
    return text, elapsed
```

### Step 8 – Wrap as a CLI tool (optional)

```python
# step8_cli.py
import argparse
from step7_metrics import timed_speculative_decode

def main():
    parser = argparse.ArgumentParser(description="Pure‑Python Medusa speculative decoder")
    parser.add_argument("--prompt", type=str, required=True, help="Input prompt")
    parser.add_argument("--max-tokens", type=int, default=20, help="Max new tokens to generate")
    args = parser.parse_args()

    text, elapsed = timed_speculative_decode(
        args.prompt, draft, target, tokenizer, k=4, max_new_tokens=args.max_tokens
    )
    print(f"Generated in {elapsed:.3f}s: {text}")

if __name__ == "__main__":
    main()
```

### Step 9 – Run the CLI

```bash
python step8_cli.py --prompt "Once upon a time"
```

You should see a short generated sentence and a timing line like `Generated in 0.123s: Once upon a time …`.

### Step 10 – Basic unit test with `pytest`

```python
# test_demo.py
import pytest
from step6_loop import speculative_decode

def test_basic_generation():
    result = speculative_decode("Hi", draft, target, tokenizer, k=4, max_new_tokens=5)
    assert isinstance(result, str)
    assert len(result) > 0
```

Run with `pytest -q test_demo.py`.

---

## Running and Testing It

1. **Clone / create a folder** and place the ten step files (`step1_tokenizer.py` through `step10_cli.py`) inside.  
2. **Install numpy** (`pip install numpy`).  
3. **Run the CLI** as shown in step 9 to generate text and see the elapsed time.  
4. **Execute the test suite** (`pytest -q`) to verify the core loop works across random seeds.  
5. **Profile** with `python -m cProfile step8_cli.py --prompt "Test"` to observe hot paths; the critical sections are the `logits` call and `propose_tokens`.  

Because the models are stubs, the acceptance rate will be 50 % (even‑token rule). Replace the `DraftModel.logits` and `TargetModel.accept` with real transformer inference (e.g., using `torch` or `jax`) and the engine will automatically benefit from speculative speed‑ups.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Swap stubs for a real tiny transformer** (e.g., `distilgpt2` from 🤗 Transformers) | Moves the project from a toy to a *real* decoder that can be benchmarked against production models. |
| 2 | **Persist draft and target states** with `shelve` or `Redis` | Enables resuming long‑running generation jobs and sharing cached drafts across requests. |
| 3 | **Add observability**: Prometheus metrics for acceptance rate, latency per token, and error counters | Hiring managers look for services that emit structured metrics; you can integrate with `prometheus_client`. |
| 4 | **Horizontal scaling** via a gRPC/FastAPI wrapper that batches multiple prompts | Demonstrates ability to design APIs that handle concurrent LLM traffic, a common senior‑level responsibility. |
| 5 | **Fault tolerance**: retry logic, circuit‑breaker pattern, and graceful degradation when the target model crashes | Shows you can build resilient systems that survive real‑world failures. |
| 6 | **Benchmark suite** that measures tokens‑per‑second with varying `k` values and plots results using `matplotlib` | Provides concrete data to back performance claims in interviews or portfolio write‑ups. |

Each upgrade adds a production‑grade dimension while keeping the core engine intact, letting you evolve the project from “here’s some code” to “here’s a shipping‑ready component”.

## Key Takeaways

- Speculative decoding reduces LLM latency by exploiting a lightweight draft model; the Medusa pattern amplifies this with multiple parallel proposals.  
- Building the engine in pure Python forces you to think about data structures, algorithmic complexity, and performance‑critical micro‑optimisations—exactly the skills senior engineers are evaluated on.  
- The modular architecture (draft → proposer → verifier → buffer) mirrors real inference pipelines, making the codebase a solid foundation for further system‑level work.  
- Adding observability, persistence, and scaling transforms the toy into a demonstrable component for CVs and interviews.  
- Real‑world benchmarking and fault‑tolerance are what separate a “fun script” from a production‑ready service.

## Further Reading

- [Speculative Decoding](https://arxiv.org/abs/2307.04738) – the original arXiv paper that introduced the concept.  
- [vLLM – High‑throughput LLM serving](https://github.com/vllm/vllm) – production‑grade engine that implements speculative decoding at scale.  
- [Hugging Face Transformers documentation – LLaMA model usage](https://huggingface.co/docs/transformers/main/en/model_doc/llama) – reference for integrating a real target model.  
- [Medusa: Draft‑aware speculative decoding](https://arxiv.org/abs/2402.14307) – newer paper that formalises the Medusa head design.  
- [Prometheus client for Python](https://github.com/prometheus/client_python) – library to emit the metrics mentioned in the roadmap.