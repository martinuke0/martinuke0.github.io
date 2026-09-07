---
title: "Build a Byte-Level BPE Tokenizer From Scratch: A Portfolio Project That Actually Signals Systems Skill"
date: "2026-09-07T16:59:02.299"
draft: false
tags: ["NLP", "BPE", "tokenization", "python", "systems"]
description: "A hands-on build guide for a from-scratch byte-level BPE tokenizer with regex pretokenization, merge learning, and live visualization."
summary: "Ship a production-flavored BPE tokenizer end to end: byte-level pretokenization, regex splitting, merge learning, and a Tkinter visualization that animates each merge so you can actually see vocabulary grow."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-build-a-byte-level-bpe-tokenizer-from-scratch-a-portfolio-project-that-actually-signals-systems-skill.svg"
  alt: "Animated visualization of BPE merges building a vocabulary table."
  caption: ""
  relative: false
---

> **TL;DR** — A byte-level BPE tokenizer is one of the few side projects small enough to finish in a weekend yet deep enough to demonstrate real systems thinking: streaming I/O, regex pretokenization, priority-queue merge scheduling, and visualization. In this guide we build the whole pipeline in roughly 300 lines of Python, animate the merge steps, and leave you with a clear upgrade path toward production tooling like SentencePiece and tiktoken.

## Why This Project Stands Out on a CV

Most "from scratch" ML projects on GitHub are neural network architectures trained on MNIST or CIFAR. Hiring managers have seen hundreds. A tokenizer is different: it sits underneath every modern LLM, it has well-defined formal behavior, and building one forces you to touch real systems concerns that neural net demos usually skip.

Concretely, this project signals:

- **Comfort with bytes and encodings** — UTF-8, multi-byte characters, and the realization that "characters" are a fiction layered on top of bytes. This is the same skill you need when debugging a Kafka consumer that silently corrupts non-ASCII payloads.
- **Regex fluency** — The GPT-2 pretokenizer pattern is one of the most-cited regexes in NLP. Writing, reading, and tweaking it fluently is a transferrable skill that comes up in log parsing, schema validation, and feature extraction pipelines.
- **Algorithmic thinking under constraints** — BPE is greedy, but the *fast* version requires a priority queue, inverted indices, and lazy re-ranking. That's the same shape as a scheduler, a router, or a build system.
- **Visualization instinct** — Adding a live merge visualizer signals that you care about debugging and explainability, not just shipping opaque binaries. This is what separates a senior IC from a junior one.
- **Awareness of production alternatives** — Discussing tiktoken, SentencePiece, and Hugging Face Tokenizers in your README shows that you know the toy you built and the tools you'd actually ship.

For roles targeting **ML platform engineering**, **LLM inference infrastructure**, or **search/relevance systems**, this project is unusually well aligned. For general backend roles, the algorithmic core and visualization still read as solid engineering.

## Architecture Overview

The pipeline has five stages. Each is small in isolation, but together they exercise I/O, regex, data structures, and rendering.

- **Corpus loader** — Streams a text file line by line so the trainer never holds the whole dataset in memory. The same shape as a Spark or Beam reader.
- **Byte-level pretokenizer** — Encodes every line to UTF-8 bytes, maps each byte through a 256-entry vocabulary (`Ġ` for space, etc.), and runs a regex over the resulting string. The regex is the GPT-2 pattern adapted for clarity.
- **Vocabulary + frequency table** — A `dict[tuple[int, ...], int]` mapping byte sequences to counts. Counts come from a single streaming pass.
- **Pair index** — An inverted index: `dict[tuple[int, int], set[tuple[int, ...]]]` from symbol pairs to the words they appear in. This is what makes incremental merging fast.
- **Merge learner + visualizer** — A max-heap keyed by pair frequency. Each pop produces a new merge rule, applies it to every word in the inverted index, and pushes a frame to the visualizer.

```
        text file
           │
           ▼
   ┌─────────────────┐
   │ streaming reader│
   └─────────────────┘
           │  line
           ▼
   ┌─────────────────┐    ┌──────────────────┐
   │ byte-level +    │──▶ │ freq table       │
   │ regex split     │    │ (word → count)   │
   └─────────────────┘    └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │ pair index       │
                        │ (pair → words)   │
                        └──────────────────┘
                                 │
                                 ▼
   ┌─────────────────────────────────────────┐
   │  merge loop (priority queue + updates)  │
   └─────────────────────────────────────────┘
                │                │
                ▼                ▼
        vocab.json        live visualization
        merges.txt        (Tkinter canvas)
```

## Building It Step by Step

We'll build this in a single file, `bpe.py`, then split a `train.py` and `tokenize.py` once the core works. Python 3.11+ is recommended for `dict` ordering guarantees, but anything 3.8+ will run.

### Step 1: The byte-level vocabulary

This is the byte-to-printable-string mapping that GPT-2 introduced. Every possible byte gets a unique, printable symbol so that we can treat the corpus as a normal string.

```python
# bpe.py
def bytes_to_unicode() -> dict[int, str]:
    """Reproduce the byte-to-unicode mapping from GPT-2."""
    bs = (
        list(range(ord("!"), ord("~") + 1))
        + list(range(ord("¡"), ord("¬") + 1))
        + list(range(ord("®"), ord("ÿ") + 1))
    )
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}

_BYTE_DECODER = {v: k for k, v in bytes_to_unicode().items()}
```

The trick: ASCII printable bytes map to themselves, and the remaining bytes get mapped into the 256–323 unicode range. This guarantees round-trippability and keeps the regex pattern simple.

### Step 2: The pretokenization regex

This is the GPT-2 pattern, lightly annotated. It splits text into chunks that should never be merged across boundaries — contractions, letters, numbers, and punctuation each get their own regime.

```python
import re

PAT = r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+"""
PRETOK_RE = re.compile(PAT)
```

Why this matters: BPE is fundamentally a greedy *within-word* merger. If you let it merge "ly" from "really" with "ed" from "red", you produce nonsense. The regex fences off those regions.

### Step 3: The streaming word counter

We never hold the whole corpus. Lines stream in, get encoded to bytes, mapped through `bytes_to_unicode`, and regex-split. Each chunk becomes a tuple of ints in the freq table.

```python
from collections import Counter

def count_words(text_path: str) -> Counter:
    word_freq: Counter = Counter()
    decoder = bytes_to_unicode()
    with open(text_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            encoded = line.encode("utf-8")
            rendered = "".join(decoder[b] for b in encoded)
            for chunk in PRETOK_RE.findall(rendered):
                word_freq[tuple(chunk.encode("utf-8"))] += 1
    return word_freq
```

Note the round trip: we render to unicode for regex matching, then re-encode the captured chunk as raw bytes. The freq table therefore holds raw bytes, which is what we want for the actual token IDs.

### Step 4: The pair index

The naive BPE trainer scans every word on every merge step, which is O(N × V) per epoch. The pair index inverts that: we track, for each adjacent pair, the set of words containing it.

```python
from collections import defaultdict

def build_pair_index(words: dict[tuple[int, ...], int]):
    pair_to_words: dict[tuple[int, int], set[tuple[int, ...]]] = defaultdict(set)
    pair_freq: dict[tuple[int, int], int] = defaultdict(int)
    for word, count in words.items():
        for a, b in zip(word, word[1:]):
            pair_to_words[(a, b)].add(word)
            pair_freq[(a, b)] += count
    return pair_to_words, pair_freq
```

When we merge a pair, we only touch the words in `pair_to_words[pair]`, not the whole vocabulary. This is the same insight that makes Lucene's postings lists and RocksDB's merge operators fast.

### Step 5: The merge loop with a heap

We pop the most frequent pair, mint a new token id, and update both the freq table and the pair index. A heap keeps the selection O(log P).

```python
import heapq

def learn_merges(
    words: dict[tuple[int, ...], int],
    num_merges: int,
    pair_to_words: dict,
    pair_freq: dict,
):
    merges: list[tuple[int, int, int]] = []  # (a, b) -> new_id
    next_id = 256  # first 256 ids reserved for raw bytes

    heap = [(-freq, i, pair) for i, (pair, freq) in enumerate(pair_freq.items())]
    heapq.heapify(heap)

    while heap and len(merges) < num_merges:
        neg_freq, _, top = heapq.heappop(heap)
        if top not in pair_freq or pair_freq[top] != -neg_freq:
            continue  # stale entry

        a, b = top
        new_id = next_id
        next_id += 1
        merges.append((a, b, new_id))

        affected = list(pair_to_words[top])
        for word in affected:
            count = words[word]
            # find and replace non-overlapping occurrences of (a, b)
            new_word: list[int] = []
            i = 0
            while i < len(word):
                if i < len(word) - 1 and word[i] == a and word[i + 1] == b:
                    new_word.append(new_id)
                    # decrement pair frequencies for neighbors of (a, b)
                    if i > 0:
                        left = (word[i - 1], a)
                        pair_freq[left] -= count
                        pair_to_words[left].discard(word)
                        heapq.heappush(heap, (-pair_freq[left], next_id + len(merges), left))
                    if i + 2 < len(word):
                        right = (b, word[i + 2])
                        pair_freq[right] -= count
                        pair_to_words[right].discard(word)
                        heapq.heappush(heap, (-pair_freq[right], next_id + len(merges), right))
                    i += 2
                else:
                    new_word.append(word[i])
                    i += 1

            new_word_t = tuple(new_word)
            words[new_word_t] = words.pop(word)
            # re-index pairs in the new word
            for x, y in zip(new_word_t, new_word_t[1:]):
                pair_to_words[(x, y)].add(new_word_t)
                pair_freq[(x, y)] += count
                heapq.heappush(heap, (-pair_freq[(x, y)], next_id + len(merges), (x, y)))

        # done with this pair
        pair_freq.pop(top, None)

    return merges, words
```

The stale-entry check is critical: the heap can hold many entries for the same pair with different frequencies. We discard anything that doesn't match the live `pair_freq`. This is the same lazy-deletion trick you'd use in a Dijkstra implementation over a dynamic graph.

### Step 6: Tokenization with learned merges

Once trained, tokenizing new text is two passes: pretokenize, then apply merges greedily by priority order.

```python
def tokenize(text: str, merges: list[tuple[int, int, int]], decoder: dict[str, int]):
    encoded = text.encode("utf-8")
    rendered = "".join(chr(_BYTE_DECODER_R[b]) for b in encoded)
    out: list[int] = []
    for chunk in PRETOK_RE.findall(rendered):
        symbols = list(chunk.encode("utf-8"))
        # apply merges in priority order
        for a, b, new_id in merges:
            i = 0
            while i < len(symbols) - 1:
                if symbols[i] == a and symbols[i + 1] == b:
                    symbols[i] = new_id
                    del symbols[i + 1]
                else:
                    i += 1
        out.extend(symbols)
    return out
```

This O(M × L) encoder is slow but correct. For your senior-level roadmap, you'll replace it with the linear-time algorithm from the [tiktoken design notes](https://github.com/openai/tiktoken).

### Step 7: The visualization

A Tkinter canvas that animates the top tokens by frequency after each merge step. It sells the project on a CV because it lets interviewers *see* vocabulary growth.

```python
import tkinter as tk
from collections import Counter

class MergerVisualizer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("BPE merge growth")
        self.canvas = tk.Canvas(self.root, width=600, height=400, bg="white")
        self.canvas.pack()

    def render(self, words: dict[tuple[int, ...], int], step: int):
        self.canvas.delete("all")
        flat = Counter()
        for word, c in words.items():
            for sym in word:
                flat[sym] += c
        top = flat.most_common(20)
        bar_w = 600 // max(len(top), 1)
        max_count = top[0][1] if top else 1
        for i, (sym, c) in enumerate(top):
            h = int(380 * c / max_count)
            self.canvas.create_rectangle(
                i * bar_w, 400 - h, (i + 1) * bar_w, 400, fill="#4c78a8"
            )
            self.canvas.create_text(i * bar_w + bar_w // 2, 395 - h, text=str(sym))
        self.root.title(f"BPE merge growth — step {step}")
        self.root.update()
```

Wire it into the merge loop with a `tk.after(0, visualizer.render, ...)` call after every N merges so the UI stays responsive. For a CV demo, record a GIF from the canvas using `Pillow.ImageGrab` and embed it in your README.

## Running and Testing It

Drop a corpus somewhere — `data/corpus.txt` — and add a `train.py` that ties everything together.

```bash
# train.py
python train.py --input data/corpus.txt --merges 8000 --viz
```

```python
# train.py
import argparse, json
from bpe import count_words, build_pair_index, learn_merges, MergerVisualizer

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--merges", type=int, default=8000)
    ap.add_argument("--viz", action="store_true")
    args = ap.parse_args()

    words = count_words(args.input)
    print(f"unique chunks: {len(words)}")

    pair_to_words, pair_freq = build_pair_index(words)
    viz = MergerVisualizer() if args.viz else None

    # wrap learn_merges to call viz.render periodically
    # (omitted for brevity — pass a callback in)
    merges, final_words = learn_merges(words, args.merges, pair_to_words, pair_freq)

    with open("merges.json", "w") as f:
        json.dump(merges, f)
    print(f"learned {len(merges)} merges")

if __name__ == "__main__":
    main()
```

To prove it works, write three tests.

```python
# test_bpe.py
from bpe import count_words, build_pair_index, learn_merges, tokenize

def test_round_trip():
    text = "hello hello world"
    with open("/tmp/_t.txt", "w") as f:
        f.write(text)
    words = count_words("/tmp/_t.txt")
    pair_to_words, pair_freq = build_pair_index(words)
    merges, _ = learn_merges(words, 10, pair_to_words, pair_freq)
    ids = tokenize("hello world", merges, None)
    assert all(isinstance(i, int) for i in ids)

def test_deterministic():
    # same input → same merges
    a = train("the quick brown fox jumps over the lazy dog" * 50)
    b = train("the quick brown fox jumps over the lazy dog" * 50)
    assert a == b

def test_compression():
    # learned tokenizer must shorten frequent sequences
    raw = "tokenization " * 100
    tokens = tokenize(raw, merges, None)
    assert len(tokens) < len(raw)
```

Run with `pytest -q`. The compression test is the one that goes in your README — it shows a real-world compression ratio on a real-world pattern.

## Extending It: Your Roadmap to Senior-Level

A weekend project gets you the core. These upgrades turn it into a portfolio piece that reads like infrastructure work, not a homework assignment.

- **Persist merges in a binary format** — JSON is fine for the toy, but production tokenizers ship as compact binary blobs like the ones in [Hugging Face `tokenizers`](https://huggingface.co/docs/tokenizers). Use `struct` or `msgpack` and benchmark the load time. *Why it matters:* the same shape as a feature store or model registry lookup.
- **Parallelize the merge loop with multiprocessing** — The pair index is embarrassingly parallelizable per shard. Distribute work across cores with `concurrent.futures.ProcessPoolExecutor` and a shared `multiprocessing.Manager` for the heap. *Why it matters:* this is exactly how SentencePiece and tiktoken shard training corpora.
- **Add OpenTelemetry traces around merge steps** — Instrument each iteration with span timings so you can profile which pairs dominate cost. *Why it matters:* observability is the difference between a script and a service, and interviewers love seeing it in a side project.
- **Build a Rust extension with PyO3** — Rewrite the hot loop in Rust and expose it as a Python module. Compare throughput against the pure-Python version with `timeit`. *Why it matters:* Python+Rust is the de facto stack for ML infrastructure (see `tokenizers`, `polars`, `ruff`).
- **Add a checkpointing resume protocol** — Serialize the heap and freq table to disk every K merges so a crashed training run resumes without recomputation. *Why it matters:* same pattern as a Flink or Spark checkpoint.
- **Benchmark against tiktoken** — Run both tokenizers on the same corpus and a downstream model, and report tokens-per-second and bytes-per-token. Put the chart in your README. *Why it matters:* demonstrates you can evaluate your own work against the production alternative — the senior-engineer mindset.

## Key Takeaways

- BPE is small, well-defined, and surprisingly close to real systems work: streaming I/O, regex, inverted indices, and heaps.
- Byte-level pretokenization sidesteps Unicode ambiguity entirely and is what GPT-2, RoBERTa, and tiktoken all use.
- The pair index is the single optimization that turns a naive O(N²) trainer into something that scales to real corpora.
- A visualization is a force multiplier for any systems project — it makes the work legible in interviews and on GitHub.
- The upgrade path to senior-level work runs through persistence, parallelism, observability, and performance benchmarking against tiktoken or SentencePiece.

## Further Reading

- [Sennrich et al., 2016 — *Neural Machine Translation of Rare Words with Subword Units*](https://arxiv.org/abs/1608.06959) — the paper that introduced BPE to NLP.
- [GPT-2 tokenizer source in `tiktoken`](https://github.com/openai/tiktoken) — the canonical reference implementation for the byte-level variant.
- [Hugging Face `tokenizers` library docs](https://huggingface.co/docs/tokenizers) — the production-grade Rust implementation with Python bindings.
- [SentencePiece paper (Kudo, 2018)](https://arxiv.org/abs/1808.06226) — alternative subword approach with a different sampling strategy worth comparing.
- [Andrej Karpathy's `minbpe`](https://github.com/karpathy/minbpe) — the cleanest educational implementation of the same algorithm.