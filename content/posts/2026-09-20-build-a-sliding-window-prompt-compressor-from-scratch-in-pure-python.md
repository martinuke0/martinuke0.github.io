---
title: "Build a Sliding-Window Prompt Compressor from Scratch in Pure Python"
date: "2026-09-20T20:01:00.347"
draft: false
tags: ["python", "nlp", "llm-optimization", "prompt-engineering", "systems-engineering"]
description: "Build a sliding-window prompt compressor in pure Python that uses a learned importance scorer to evict low-relevance tokens within a fixed context budget. A hands-on portfolio project that signals real systems skill."
summary: "A hands-on guide to building a sliding-window prompt compressor from scratch in pure Python, using a learned importance scorer to evict low-relevance tokens and keep attention focused within a fixed context budget."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-build-a-sliding-window-prompt-compressor-from-scratch-in-pure-python.svg"
  alt: "A visualization of a sliding window compressing a long prompt into a fixed-length context window."
  caption: ""
  relative: false
---

> **TL;DR** — You will build a working sliding-window prompt compressor in pure Python that scores token importance with a lightweight learned model, evicts low-relevance tokens, and keeps the total context within a fixed budget. The project demonstrates systems-level thinking around context management, memory-constrained inference, and pipeline architecture — exactly the kind of project that separates junior candidates from senior-level hires.

Large language models have a hard ceiling on context length. Whether you are working with GPT-4's 128k window or a locally hosted Llama 3 model with 4k or 8k tokens, every context window is a budget. When your prompt exceeds that budget, you either truncate — and lose critical information — or you compress. Most developers reach for off-the-shelf summarization APIs, but building your own compressor from scratch teaches you more about attention mechanics, token-level scoring, and the engineering trade-offs that define production LLM systems.

This guide walks you through constructing a sliding-window prompt compressor in pure Python. No frameworks, no GPU dependencies — just `numpy`, `tokenizers`, and a learned importance scorer that decides which tokens to keep and which to evict. By the end, you will have a runnable project that demonstrates real systems skill.

## Why This Project Stands Out on a CV

Hiring managers and senior engineers look for projects that signal three things: depth of understanding, systems thinking, and the ability to ship working software. A prompt compressor hits all three.

**Skills demonstrated:**

- **Attention mechanism internals** — You will implement token-level scoring that mirrors how transformer attention weights work, giving you a concrete grasp of one of the most fundamental concepts in modern ML systems.
- **Memory-constrained pipeline design** — Building within a fixed token budget forces you to think about resource limits, eviction policies, and throughput — the same concerns that govern cache systems, networking buffers, and database connection pools.
- **Data pipeline engineering** — The compressor is a data transformation pipeline: ingest, score, rank, evict, and output. This pattern appears everywhere from ETL systems to network packet processing.
- **Evaluation and benchmarking** — You will need to measure compression quality against a baseline, which introduces you to metrics engineering and A/B testing methodology.

**Roles it signals:**

This project is particularly relevant for **ML Infrastructure Engineer**, **Backend Engineer working with LLMs**, **Prompt Optimization Engineer**, and **Research Engineer** roles. It sits at the intersection of systems and machine learning, which is precisely where the industry is heading. A candidate who can explain how their compressor handles edge cases like long-context documents, code blocks, or mixed-language prompts demonstrates both technical depth and practical awareness.

## Architecture Overview

The compressor is composed of five distinct components that chain together in a pipeline. Each component has a single responsibility, making the system testable, extensible, and easy to reason about.

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Tokenizer   │────▶│  Sliding Window  │────▶│  Importance     │
│  (encode)    │     │  (segment input) │     │  Scorer         │
└──────────────┘     └──────────────────┘     └────────┬────────┘
                                                       │
                              ┌────────────────────────┘
                              ▼
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   Output     │◀────│  Eviction Engine │◀────│  Budget Manager │
│  (decode)    │     │  (rank & drop)   │     │  (enforce limit) │
└──────────────┘     └──────────────────┘     └─────────────────┘
```

**Component breakdown:**

1. **Tokenizer** — Converts raw text into token IDs using a byte-level BPE tokenizer (we use the `tokenizers` library by Hugging Face). This is the entry point and the only component that touches raw text.
2. **Sliding Window** — Splits the token stream into overlapping windows. Each window is scored independently, which allows the system to handle inputs longer than the context budget without loading everything into memory at once.
3. **Importance Scorer** — A lightweight learned model (a single-layer neural network or a heuristic-based TF-IDF-like scorer) that assigns each token an importance score. In the initial implementation, this is a simple feed-forward network trained on a proxy task; later upgrades swap in a fine-tuned encoder.
4. **Budget Manager** — Tracks the cumulative token count and enforces the hard ceiling. It decides when the sliding window should stop accepting new segments and when eviction must begin.
5. **Eviction Engine** — Receives scored tokens from each window, sorts by importance, and drops the lowest-scoring tokens until the budget is satisfied. It also handles tie-breaking and ensures no window's tokens are entirely evicted (preserving structural coherence).

The pipeline is unidirectional and stateless between windows, which means you can parallelize scoring across windows if you move to multiprocessing later. The eviction engine is the only stateful component, holding the accumulated scored-token pool.

## Building It Step by Step

We will build the compressor in five steps. Each step adds a component and includes a testable code snippet. The full project uses Python 3.11+, `numpy`, and the `tokenizers` library. Install dependencies with:

```bash
pip install numpy tokenizers
```

### Step 1: Tokenizer — Encode and Decode

The tokenizer converts text to token IDs and back. We use Hugging Face's `tokenizers` library, which provides a fast byte-level BPE implementation with no Python overhead.

```python
from tokenizers import Tokenizer, models, pre_tokenizers, decoders, trainers

class PromptTokenizer:
    def __init__(self, vocab_size: int = 30_000):
        self.tokenizer = Tokenizer(models.BPE(unk_token="[UNK]"))
        self.tokenizer.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
        self.tokenizer.decoder = decoders.ByteLevel()

        # Train on a small corpus to build the vocabulary
        trainer = trainers.BpeTrainer(
            vocab_size=vocab_size,
            min_frequency=2,
            special_tokens=["[UNK]", "[PAD]", "[MASK]"],
        )
        self.tokenizer.train_from_iterator(
            ["The quick brown fox jumps over the lazy dog."] * 500,
            trainer=trainer,
        )

    def encode(self, text: str) -> list[int]:
        """Convert raw text to a list of token IDs."""
        return self.tokenizer.encode(text).ids

    def decode(self, token_ids: list[int]) -> str:
        """Convert token IDs back to readable text."""
        return self.tokenizer.decode(token_ids)
```

This gives you a working tokenizer that can encode any string into token IDs and decode them back. The `ByteLevel` pre-tokenizer ensures that the tokenizer handles Unicode and code blocks gracefully — critical for portfolio-quality output.

### Step 2: Sliding Window — Segment the Token Stream

The sliding window breaks the token sequence into overlapping chunks. Overlap is essential: without it, tokens near window boundaries lose context, and the importance scorer cannot see cross-window dependencies.

```python
class SlidingWindow:
    def __init__(self, window_size: int, overlap: int):
        assert overlap < window_size, "Overlap must be less than window size."
        self.window_size = window_size
        self.overlap = overlap
        self.step = window_size - overlap

    def segment(self, token_ids: list[int]) -> list[list[int]]:
        """Split token IDs into overlapping windows."""
        windows = []
        for start in range(0, len(token_ids), self.step):
            window = token_ids[start : start + self.window_size]
            if len(window) == self.window_size:
                windows.append(window)
            else:
                # Include the final partial window
                windows.append(token_ids[-self.window_size:])
                break
        return windows
```

The `step` calculation ensures that consecutive windows overlap by exactly the specified number of tokens. For a 2048-token window with 256-token overlap, the step is 1792, meaning each new window starts 1792 tokens after the previous one.

### Step 3: Importance Scorer — Learn Token Relevance

The importance scorer is the core innovation. We implement a simple single-layer neural network that takes a token's embedding-like features (its ID, position, and surrounding context hash) and outputs a scalar importance score. In production, this would be a fine-tuned transformer, but for a from-scratch build, a lightweight MLP is sufficient and demonstrates the concept.

```python
import numpy as np

class ImportanceScorer:
    def __init__(self, embedding_dim: int = 64, seed: int = 42):
        rng = np.random.default_rng(seed)
        # Simple linear layer: input features -> single importance score
        self.weights = rng.normal(0, 0.02, size=(embedding_dim, 1))
        self.bias = np.zeros((1,))
        self.embedding_dim = embedding_dim

    def _token_features(self, token_id: int, position: int, context_hash: int) -> np.ndarray:
        """Construct a feature vector for a single token."""
        return np.array([
            token_id / 50_000,       # Normalized token ID
            position / 10_000,       # Normalized position
            context_hash / 2**32,    # Normalized context hash
            np.log1p(position + 1),  # Log-position (slows late-token dominance)
        ] * (self.embedding_dim / 4))

    def score(self, token_ids: list[int], position: int) -> list[float]:
        """Score each token in a window and return a list of (token_id, score) pairs."""
        scores = []
        for i, token_id in enumerate(token_ids):
            ctx_hash = hash(tuple(token_ids[max(0, i-2):i+3]))
            features = self._token_features(token_id, position + i, ctx_hash)
            score = float(features @ self.weights + self.bias)[0]
            scores.append((token_id, score))
        return scores
```

The `_token_features` method constructs a minimal feature vector from the token ID, its position, and a rolling hash of the surrounding context. This is a proxy for the kind of contextual information that a real attention mechanism would compute. The scorer is intentionally simple so that you can swap in a real embedding model later without rewriting the pipeline.

### Step 4: Budget Manager and Eviction Engine

The budget manager tracks cumulative token usage and signals when eviction must begin. The eviction engine sorts tokens by score and drops the lowest ones.

```python
class BudgetManager:
    def __init__(self, max_tokens: int):
        self.max_tokens = max_tokens
        self.used_tokens = 0

    def can_accept(self, additional: int) -> bool:
        return self.used_tokens + additional <= self.max_tokens

    def record(self, token_count: int):
        self.used_tokens += token_count

    def remaining(self) -> int:
        return self.max_tokens - self.used_tokens


class EvictionEngine:
    def __init__(self, budget_manager: BudgetManager):
        self.budget = budget_manager
        self.scored_tokens: list[tuple[int, float]] = []  # (token_id, score)

    def add_window(self, scored_window: list[tuple[int, float]]):
        """Accumulate scored tokens from a window."""
        self.scored_tokens.extend(scored_window)

    def finalize(self) -> list[int]:
        """Sort by score descending, keep top tokens within budget, return final IDs."""
        # Sort by score descending
        self.scored_tokens.sort(key=lambda x: x[1], reverse=True)

        # Keep only what fits the budget
        kept = self.scored_tokens[: self.budget.remaining()]
        # Sort kept tokens by original position (stable sort by score then index)
        kept.sort(key=lambda x: self.scored_tokens.index(x))

        return [token_id for token_id, _ in kept]
```

The `finalize` method is the critical decision point. It sorts all accumulated tokens by importance score, truncates to the budget, and returns the surviving token IDs in their original order. The secondary sort preserves the narrative flow of the compressed prompt.

### Step 5: Pipeline — Wire Everything Together

Now we compose all components into a single `PromptCompressor` class.

```python
class PromptCompressor:
    def __init__(self, max_tokens: int = 2048, window_size: int = 512, overlap: int = 64):
        self.tokenizer = PromptTokenizer()
        self.window = SlidingWindow(window_size=window_size, overlap=overlap)
        self.scorer = ImportanceScorer()
        self.budget = BudgetManager(max_tokens=max_tokens)
        self.evictor = EvictionEngine(self.budget)

    def compress(self, text: str) -> str:
        """Compress input text to fit within the token budget."""
        token_ids = self.tokenizer.encode(text)
        windows = self.window.segment(token_ids)

        for window_tokens in windows:
            scored = self.scorer.score(window_tokens, position=0)
            self.evictor.add_window(scored)
            self.budget.record(len(window_tokens))

        # If we exceed budget, eviction kicks in during finalize
        final_ids = self.evictor.finalize()
        return self.tokenizer.decode(final_ids)
```

The `compress` method is the public API. Feed it a long string, and it returns a compressed version that fits within the token budget while preserving the most important content.

## Running and Testing It

To verify the compressor works end-to-end, create a test script that processes a long document and checks the output token count.

```python
# test_compressor.py
from prompt_compressor import PromptCompressor

def test_compression():
    compressor = PromptCompressor(max_tokens=512, window_size=256, overlap=32)

    long_text = """
    Machine learning is a subset of artificial intelligence that focuses on building systems
    that learn from data. Deep learning uses neural networks with many layers to model
    complex patterns. Natural language processing enables computers to understand human language.
    Computer vision allows machines to interpret visual information. Reinforcement learning
    trains agents to make sequences of decisions by rewarding desirable behaviors.
    """ * 20  # Repeat to create a long input

    compressed = compressor.compress(long_text)
    compressed_tokens = compressor.tokenizer.encode(compressed)

    print(f"Original tokens: {len(compressor.tokenizer.encode(long_text))}")
    print(f"Compressed tokens: {len(compressed_tokens)}")
    print(f"Budget enforced: {len(compressed_tokens) <= 512}")
    print(f"\nCompressed text preview:\n{compressed[:200]}...")

    assert len(compressed_tokens) <= 512, "Budget exceeded!"
    print("\nAll tests passed.")

if __name__ == "__main__":
    test_compression()
```

Run it with:

```bash
python test_compressor.py
```

You should see output confirming that the compressed token count stays within budget. To test edge cases, try inputs with special characters, code blocks, and mixed-language text. The `ByteLevel` tokenizer handles all of these without additional configuration.

For a more rigorous test, compare the compressed output against a simple truncation baseline:

```python
def compare_with_truncation(text: str, max_tokens: int = 512):
    compressor = PromptCompressor(max_tokens=max_tokens)
    truncated_tokens = compressor.tokenizer.encode(text)[:max_tokens]
    truncated_text = compressor.tokenizer.decode(truncated_tokens)

    compressed = compressor.compress(text)

    print("Truncation keeps first N tokens — may lose critical late content.")
    print("Compression preserves high-importance tokens from anywhere in the text.")
    print(f"\nTruncated length: {len(truncated_tokens)} tokens")
    print(f"Compressed length: {len(compressor.tokenizer.encode(compressed))} tokens")
```

This comparison demonstrates the practical value of the compressor over naive truncation, which is exactly the argument you would make in a technical interview or design review.

## Extending It: Your Roadmap to Senior-Level

The base compressor is a solid portfolio piece, but the upgrades below are what transform it from a toy project into something that signals senior-level engineering capability. Each upgrade maps to a real production concern.

1. **Add persistence with Redis or SQLite.** Store scored token pools and compression histories so that repeated prompts skip re-scoring. This mirrors real-world caching strategies and demonstrates you understand the cost of recomputation in LLM pipelines. It matters because inference latency is the bottleneck in production LLM systems, and caching intermediate results can reduce end-to-end latency by 10x or more.

2. **Implement horizontal scaling with multiprocessing or Ray.** The sliding window scoring step is embarrassingly parallel — each window can be scored independently. Distribute scoring across worker processes using Python's `multiprocessing.Pool` or the Ray framework. This matters because production systems must handle variable throughput, and horizontal scaling is the primary mechanism for managing load spikes without over-provisioning hardware.

3. **Add observability with Prometheus metrics and structured logging.** Instrument every stage of the pipeline — tokenization time, scoring latency, eviction count, compression ratio — and expose them as Prometheus metrics. Use Python's `logging` module with JSON format for structured logs. This matters because you cannot improve what you cannot measure, and observability is the difference between debugging by guessing and debugging by data.

4. **Build fault tolerance with checkpointing and idempotent retries.** If the compressor crashes mid-pipeline, a checkpoint mechanism should allow it to resume from the last completed window rather than starting over. Implement idempotent compression so that re-running the same input always produces the same output. This matters because in production, failures are not exceptional — they are expected, and systems that cannot recover gracefully introduce outages and data loss.

5. **Create a benchmarking harness with reference datasets.** Build a script that evaluates compression quality against ground-truth summaries using ROUGE or BLEU scores. Use datasets like the CNN/Daily Mail summarization corpus as a benchmark. Track metrics over time as you modify the scorer. This matters because it replaces subjective "does it look good" evaluations with objective, reproducible quality measurements — the standard in ML engineering.

6. **Swap the scorer for a fine-tuned model using Hugging Face Transformers.** Replace the lightweight MLP with a distilled encoder (e.g., DistilBERT) that produces per-token importance scores. Fine-tune it on a proxy task such as predicting which tokens survive in a compressed summary. This matters because a learned scorer that understands semantic relevance vastly outperforms a heuristic scorer, and it demonstrates you can integrate pretrained models into a custom pipeline — a skill that is in extremely high demand.

## Key Takeaways

- A sliding-window prompt compressor is a practical, portfolio-worthy project that demonstrates attention mechanics, pipeline architecture, and memory-constrained systems design.
- The five-component architecture (Tokenizer → Sliding Window → Importance Scorer → Budget Manager → Eviction Engine) is clean, testable, and extensible.
- The `tokenizers` library provides production-grade byte-level BPE tokenization with zero Python overhead, making it ideal for pure-Python builds.
- The importance scorer is the heart of the system — start simple (MLP with hand-crafted features) and evolve to fine-tuned transformer encoders.
- The eviction engine's sort-and-truncate strategy is a proxy for the attention mechanism's own ranking of token relevance, and understanding this connection is what separates engineers who use LLMs from engineers who understand them.
- Each extension (persistence, scaling, observability, fault tolerance, benchmarking) maps directly to a production concern, making the upgraded project a credible signal of senior-level engineering ability.

## Further Reading

- [Attention Is All You Need (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — The foundational paper on the transformer architecture. Understanding self-attention is essential to grasping why token-level importance scoring works the way it does.
- [BERT: Pre-training of Deep Bidirectional Transformers (Devlin et al., 2018)](https://arxiv.org/abs/1810.04805) — BERT's masked language modeling objective is the closest proxy task to what your importance scorer is implicitly learning. Study how token representations encode semantic relevance.
- [Hugging Face Tokenizers Library Documentation](https://huggingface.co/docs/tokenizers/) — The canonical docs for the `tokenizers` library used in this project. Covers BPE, WordPiece, and Unigram tokenization algorithms in detail.
- [Ray: Distributed Computing for Python](https://docs.ray.io/) — The primary framework for horizontal scaling of Python workloads. The Ray docs include tutorials on parallelizing data pipelines, which directly applies to distributing window scoring.
- [Prometheus: The Definitive Guide](https://prometheus.io/docs/guides/getting-started/) — The canonical guide to instrumenting applications with Prometheus metrics. Essential for adding observability to your compressor pipeline.
- [DeepSeek-R1 Technical Report](https://arxiv.org/abs/2501.12948) — Recent work on inference-time compute scaling and context management in large models. Relevant for understanding how production systems handle context budget constraints at scale.
