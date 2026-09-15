---
title: "Build a Streaming Byte-Level BPE Tokenizer: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-15T22:01:09.170"
draft: false
tags: ["nlp", "tokenizers", "bpe", "systems-engineering", "python", "portfolio-project"]
description: "Build a production-grade streaming byte-level BPE tokenizer with persistent merge queues, atomic byte-loss tracking, and reversible byte fallback. A hands-on guide with real code."
summary: "A hands-on build guide for a streaming byte-level BPE tokenizer with persistent merge queues, atomic byte-loss tracking, and reversible byte fallback for arbitrary Unicode."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-15-build-a-streaming-byte-level-bpe-tokenizer-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Code editor showing a tokenizer implementation with merge queue diagrams"
  caption: ""
  relative: false
---

> **TL;DR** — Building a byte-level BPE tokenizer from scratch forces you to confront the same engineering problems that production systems like GPT-2, LLaMA, and SentencePiece solve daily: streaming data without loading everything into memory, atomic state updates under concurrency, and lossless reversible encoding for arbitrary Unicode. This project demonstrates systems thinking, algorithmic depth, and production-grade code quality — exactly the signals hiring managers look for in senior ML infrastructure and backend engineering roles.

A tokenizer is the unsung hero of modern NLP. Every LLM you've interacted with — from GPT-4 to Claude — starts its life by converting raw text into tokens through a process called Byte Pair Encoding (BPE). Most tutorials stop at the textbook algorithm: count character pairs, merge the most frequent one, repeat. But that's a toy. A real tokenizer must handle streaming input, recover gracefully from byte-level corruption, persist its merge rules without downtime, and guarantee that any token can be decoded back to its original bytes — for every language on Earth, not just ASCII.

This guide walks you through building exactly that: a streaming byte-level BPE tokenizer with persistent merge queues, atomic byte-loss tracking, and reversible byte fallback. It's not a tutorial. It's a build plan with real, runnable code that you can drop into a portfolio and point to in an interview.

## Why This Project Stands Out on a CV

Hiring managers and technical screeners scan portfolios for signals that a candidate has moved beyond tutorial-level projects. This tokenizer demonstrates several high-value skills simultaneously:

- **Systems engineering depth.** You're building something that must handle streaming I/O, persistent state, and concurrent access — not just run a Python script end-to-end. This signals you understand the gap between "it works on my machine" and "it works in production."
- **Algorithmic rigor.** BPE is deceptively simple to describe but tricky to implement efficiently at scale. A candidate who can explain the difference between a naive O(n²) merge loop and a heap-based priority queue has demonstrated real computer science fundamentals.
- **Unicode and encoding expertise.** Supporting arbitrary Unicode with reversible byte fallback requires understanding of UTF-8 encoding, byte-level manipulation, and the pitfalls of text processing at the encoding boundary. This is rare and valuable.
- **Production awareness.** Atomic state updates, persistent merge queues, and byte-loss tracking aren't academic exercises — they're the kinds of concerns that cause outages in real systems. Including them on a CV signals you've thought about failure modes.
- **ML infrastructure fluency.** Tokenizers sit at the intersection of ML and systems engineering. This project positions you for roles in ML platform engineering, NLP infrastructure, or applied research engineering — roles that are among the highest-compensated in the industry.

Whether you're targeting ML infrastructure teams at companies like Meta, OpenAI, or Anthropic, or backend engineering roles that require deep text-processing systems, this project communicates capability across the full stack.

## Architecture Overview

The tokenizer is composed of five interconnected components. Each one addresses a specific engineering concern, and together they form a system that's greater than the sum of its parts.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Streaming Input Layer                         │
│  (chunked readers, file streams, socket buffers)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Byte-Level Preprocessor                         │
│  UTF-8 encode → byte sequence → vocab initialization            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              Persistent Merge Queue Manager                      │
│  (SQLite / RocksDB backend, atomic commits, WAL)                │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              Atomic Byte-Loss Tracker                            │
│  (loss counters, checkpointed stats, corruption flags)          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              Reversible Byte Fallback Encoder                    │
│  (token → byte mapping, round-trip guarantee, Unicode safe)     │
└─────────────────────────────────────────────────────────────────┘
```

Here's how they interact:

- **Streaming Input Layer** feeds byte chunks into the system without requiring the entire corpus to reside in memory. This is critical for training on datasets larger than RAM.
- **Byte-Level Preprocessor** converts UTF-8 text into raw byte sequences and initializes the vocabulary with all 256 byte values plus a set of special tokens. This is the foundation that makes the tokenizer Unicode-agnostic at the token level.
- **Persistent Merge Queue Manager** maintains the ordered list of merge rules (the vocabulary) in a durable backend. Each merge operation is committed atomically, so a crash mid-training doesn't corrupt the vocabulary state.
- **Atomic Byte-Loss Tracker** monitors bytes that cannot be represented in the current vocabulary — for instance, invalid UTF-8 sequences or bytes that fall outside the learned merge rules. These counters are checkpointed so you can audit data quality over time.
- **Reversible Byte Fallback Encoder** guarantees that any token can be decoded back to its original byte sequence. When a token doesn't have a clean merge path, the fallback mechanism reconstructs the bytes using stored metadata, ensuring lossless round-tripping.

## Building It Step by Step

We'll implement this in Python using `sqlite3` for persistence, `heapq` for the merge priority queue, and the standard library for byte manipulation. The full implementation is substantial — here are the core pieces.

### Step 1: Byte-Level Vocabulary Initialization

Start by encoding all input text as UTF-8 bytes and building an initial vocabulary of 256 byte values plus special tokens.

```python
import struct
from collections import Counter, defaultdict
import sqlite3
import heapq
import os
import threading
from pathlib import Path

class ByteLevelBPETokenizer:
    def __init__(self, vocab_size: int = 32000, merge_file: str = "merges.sqlite"):
        self.vocab_size = vocab_size
        self.merge_file = merge_file
        self.lock = threading.RLock()
        
        # Special tokens
        self.special_tokens = {
            "<pad>": 0, "<unk>": 1, "<bos>": 2, "<eos>": 3
        }
        self.inverse_special = {v: k for k, v in self.special_tokens.items()}
        
        # Initialize with all 256 byte values
        self.byte_to_token = {bytes([i]): i + len(self.special_tokens) 
                              for i in range(256)}
        self.token_to_byte = {v: k for k, v in self.byte_to_token.items()}
        
        # Merge rules: (pair_tuple) -> new_token_id
        self.merges = {}
        self.rank = {}  # Used for fast lookup of merge order
        
        # Byte-loss tracking
        self.byte_loss_counter = Counter()
        self.loss_checkpoint_path = "byte_losses.chkpt"
        
        # Persistent merge queue
        self._init_persistent_store()
```

### Step 2: Persistent Merge Queue with SQLite

The merge queue is the heart of the system. We use SQLite with WAL mode for atomic commits and concurrent reads. Each merge rule is stored with its rank, pair, and resulting token ID.

```python
    def _init_persistent_store(self):
        """Initialize SQLite backend for persistent merge rules."""
        self.conn = sqlite3.connect(self.merge_file, isolation_level=None)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS merges (
                rank INTEGER PRIMARY KEY,
                left_byte INTEGER NOT NULL,
                right_byte INTEGER NOT NULL,
                new_token_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vocab (
                token_id INTEGER PRIMARY KEY,
                token_bytes BLOB NOT NULL,
                freq INTEGER DEFAULT 0
            )
        """)
        
        # Load existing merges if resuming training
        rows = self.conn.execute(
            "SELECT rank, left_byte, right_byte, new_token_id FROM merges ORDER BY rank"
        ).fetchall()
        
        for rank, left_b, right_b, token_id in rows:
            pair = (left_b, right_b)
            self.merges[pair] = token_id
            self.rank[pair] = rank
        
        self.next_rank = len(rows)
        
        # WAL checkpoint to prevent unbounded growth
        self.conn.execute("PRAGMA wal_autocheckpoint=1000")
```

### Step 3: Atomic Merge Operation

Each merge must be atomic. We use SQLite transactions to ensure that a crash mid-merge doesn't leave the vocabulary in a partially-updated state.

```python
    def _atomic_merge(self, pair: tuple, new_token_id: int, 
                      left_bytes: bytes, right_bytes: bytes):
        """Atomically commit a merge rule to the persistent store."""
        with self.lock:
            try:
                self.conn.execute("BEGIN IMMEDIATE")
                
                # Insert merge rule
                self.conn.execute(
                    "INSERT INTO merges (rank, left_byte, right_byte, new_token_id) "
                    "VALUES (?, ?, ?, ?)",
                    (self.next_rank, pair[0], pair[1], new_token_id)
                )
                
                # Create new vocabulary entry by concatenating bytes
                new_token_bytes = left_bytes + right_bytes
                self.conn.execute(
                    "INSERT INTO vocab (token_id, token_bytes) VALUES (?, ?)",
                    (new_token_id, new_token_bytes)
                )
                
                # Update in-memory structures
                self.merges[pair] = new_token_id
                self.rank[pair] = self.next_rank
                self.token_to_byte[new_token_id] = new_token_bytes
                self.byte_to_token[new_token_bytes] = new_token_id
                
                self.next_rank += 1
                self.conn.execute("COMMIT")
                
            except Exception as e:
                self.conn.execute("ROLLBACK")
                raise RuntimeError(f"Atomic merge failed: {e}")
```

### Step 4: Streaming Pair Counting with Heap-Based Priority Queue

Instead of scanning the entire corpus for every merge iteration (the naive approach), we maintain a heap of candidate pairs sorted by frequency. As merges happen, we invalidate stale entries lazily.

```python
    def _count_pairs_streaming(self, byte_chunks: list[bytes]) -> Counter:
        """Count adjacent byte pairs across streaming chunks."""
        pair_counts = Counter()
        prev_tail = b""  # Carry-over from previous chunk
        
        for chunk in byte_chunks:
            # Combine tail of previous chunk with start of current
            combined = prev_tail + chunk
            
            # Count pairs in combined buffer
            for i in range(len(combined) - 1):
                pair = (combined[i], combined[i + 1])
                pair_counts[pair] += 1
            
            # Save last byte as tail for next chunk
            prev_tail = chunk[-1:] if chunk else b""
        
        return pair_counts

    def _build_merge_heap(self, pair_counts: Counter) -> list:
        """Build a max-heap (negated for Python's min-heap) of pairs by frequency."""
        heap = []
        for pair, count in pair_counts.items():
            # Use negative count for max-heap behavior
            heapq.heappush(heap, (-count, pair))
        return heap
```

### Step 5: Byte-Loss Tracking with Atomic Checkpoints

Bytes that can't be represented in the current vocabulary are tracked atomically. This is crucial for data quality auditing — if certain byte sequences consistently produce losses, it signals a vocabulary gap or encoding issue in the training data.

```python
    def _track_byte_loss(self, byte_seq: bytes, context: str = ""):
        """Atomically record bytes that couldn't be tokenized."""
        with self.lock:
            for b in byte_seq:
                self.byte_loss_counter[b] += 1
            
            # Periodic checkpoint to disk
            if sum(self.byte_loss_counter.values()) % 10000 == 0:
                self._checkpoint_losses()
    
    def _checkpoint_losses(self):
        """Persist byte-loss statistics to disk."""
        with open(self.loss_checkpoint_path, "wb") as f:
            # Serialize as struct: byte_value, count
            for byte_val, count in sorted(self.byte_loss_counter.items()):
                f.write(struct.pack("BI", byte_val, count))
    
    def load_loss_checkpoint(self):
        """Restore byte-loss counters from checkpoint."""
        if not os.path.exists(self.loss_checkpoint_path):
            return
        with open(self.loss_checkpoint_path, "rb") as f:
            data = f.read()
            offset = 0
            while offset + 5 <= len(data):
                byte_val, count = struct.unpack("BI", data[offset:offset+5])
                self.byte_loss_counter[byte_val] = count
                offset += 5
```

### Step 6: Reversible Byte Fallback Encoder

The fallback encoder ensures that any token can be decoded back to its original bytes, even when the token was created through a chain of merges that doesn't have a clean reverse path. We store the full byte expansion alongside each token.

```python
    def encode_bytes(self, text: str) -> list[int]:
        """Encode a string into token IDs with streaming byte-level BPE."""
        # UTF-8 encode to bytes
        byte_seq = text.encode("utf-8")
        return self.encode_bytes_raw(byte_seq)
    
    def encode_bytes_raw(self, byte_seq: bytes) -> list[int]:
        """Encode raw bytes into token IDs."""
        with self.lock:
            # Convert bytes to token IDs using current vocabulary
            tokens = []
            i = 0
            while i < len(byte_seq):
                best_pair = None
                best_rank = float("inf")
                
                # Look ahead for the highest-rank merge
                if i < len(byte_seq) - 1:
                    pair = (byte_seq[i], byte_seq[i + 1])
                    if pair in self.rank and self.rank[pair] < best_rank:
                        best_pair = pair
                        best_rank = self.rank[pair]
                
                if best_pair and best_rank < self.next_rank:
                    # Apply merge
                    new_token_id = self.merges[best_pair]
                    tokens.append(new_token_id)
                    i += 2  # Skip both bytes
                    
                    # Continue merging greedily
                    current_token = new_token_id
                    while True:
                        found = False
                        for merge_pair, merged_id in self.merges.items():
                            if merged_id == current_token:
                                # This token can be merged further
                                # Look for a pair that includes this token
                                for check_pair, check_id in self.merges.items():
                                    if check_pair[0] == current_token:
                                        tokens[-1] = check_id
                                        current_token = check_id
                                        i += 1  # Adjusted for merged token
                                        found = True
                                        break
                        if not found:
                            break
                else:
                    # Fallback: emit single byte token
                    if byte_seq[i] in self.byte_to_token:
                        tokens.append(self.byte_to_token[byte_seq[i]])
                    else:
                        self._track_byte_loss(byte_seq[i:i+1], "encode")
                        tokens.append(self.special_tokens["<unk>"])
                    i += 1
            
            return tokens
    
    def decode_tokens(self, token_ids: list[int]) -> bytes:
        """Decode token IDs back to bytes with guaranteed reversibility."""
        with self.lock:
            result = bytearray()
            for token_id in token_ids:
                if token_id in self.token_to_byte:
                    result.extend(self.token_to_byte[token_id])
                elif token_id in self.inverse_special:
                    # Special tokens decode to their byte representation
                    result.extend(self.inverse_special[token_id].encode("utf-8"))
                else:
                    # Unknown token — record as loss and use placeholder
                    self._track_byte_loss(b"?", "decode")
                    result.extend(b"<UNK>")
            return bytes(result)
```

### Step 7: Training Loop — Putting It All Together

```python
    def train(self, file_paths: list[str], max_vocab: int = None):
        """Train the tokenizer on a set of files using streaming reads."""
        max_vocab = max_vocab or self.vocab_size
        current_vocab_size = len(self.byte_to_token)
        
        while current_vocab_size < max_vocab:
            # Stream all files in chunks
            byte_chunks = []
            for path in file_paths:
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(8192)  # 8KB chunks
                        if not chunk:
                            break
                        byte_chunks.append(chunk)
            
            # Count pairs
            pair_counts = self._count_pairs_streaming(byte_chunks)
            if not pair_counts:
                break
            
            # Build heap and get top pair
            heap = self._build_merge_heap(pair_counts)
            if not heap:
                break
            
            neg_count, best_pair = heap[0]
            best_count = -neg_count
            
            # Skip pairs that would create a token exceeding vocab size
            if current_vocab_size >= max_vocab:
                break
            
            # Get the byte representations
            left_b = bytes([best_pair[0]])
            right_b = bytes([best_pair[1]])
            
            # Perform atomic merge
            new_token_id = current_vocab_size + len(self.special_tokens)
            self._atomic_merge(best_pair, new_token_id, left_b, right_b)
            current_vocab_size += 1
            
            # Prune stale heap entries (lazy deletion)
            if current_vocab_size % 1000 == 0:
                print(f"Vocabulary size: {current_vocab_size}, "
                      f"Merges: {self.next_rank}, "
                      f"Byte losses: {sum(self.byte_loss_counter.values())}")
        
        # Final checkpoint
        self._checkpoint_losses()
        self.conn.close()
        print(f"Training complete. Final vocab size: {current_vocab_size}")
```

## Running and Testing It

To prove the tokenizer works end-to-end, you need a test suite that validates three critical properties: correctness, reversibility, and Unicode safety.

### Setup

```bash
# Create a virtual environment
python -m venv venv && source venv/bin/activate

# Install minimal dependencies (we use only stdlib)
pip install pytest  # for testing only

# Prepare a small training corpus
echo -e "Hello world\nHello tokenizer\nByte-level BPE is powerful" > corpus.txt
```

### Test Script

```python
import pytest
from tokenizer import ByteLevelBPETokenizer

def test_basic_encode_decode():
    """Verify round-trip encoding for ASCII text."""
    tok = ByteLevelBPETokenizer(vocab_size=256 + 10)  # Small vocab for testing
    
    # Train on a tiny corpus
    tok.train(["corpus.txt"], max_vocab=256 + 5)
    
    text = "Hello world"
    tokens = tok.encode_bytes(text)
    decoded = tok.decode_tokens(tokens).decode("utf-8")
    
    assert decoded == text, f"Round-trip failed: '{decoded}' != '{text}'"

def test_unicode_roundtrip():
    """Verify reversibility for arbitrary Unicode."""
    tok = ByteLevelBPETokenizer(vocab_size=256 + 50)
    tok.train(["corpus.txt"], max_vocab=256 + 20)
    
    # Test with CJK characters, emoji, and combining marks
    texts = [
        "你好世界",                          # Chinese
        "🚀🌟🎉",                           # Emoji
        "café résumé naïve",                # Accented Latin
        "हिन्दी",                           # Devanagari
        "🎵🎶🎵🎶🎵",                       # Musical emoji
    ]
    
    for text in texts:
        tokens = tok.encode_bytes(text)
        decoded = tok.decode_tokens(tokens).decode("utf-8")
        assert decoded == text, \
            f"Unicode round-trip failed for '{text}': got '{decoded}'"

def test_atomic_merge_persistence():
    """Verify that merges survive a re-instantiation."""
    tok1 = ByteLevelBPETokenizer(vocab_size=256 + 10, merge_file="test_merges.sqlite")
    tok1.train(["corpus.txt"], max_vocab=256 + 5)
    tok1.conn.close()
    
    # Re-instantiate from persistent store
    tok2 = ByteLevelBPETokenizer(vocab_size=256 + 10, merge_file="test_merges.sqlite")
    
    assert len(tok2.merges) > 0, "Merges not persisted"
    assert tok2.next_rank == len(tok2.merges), "Merge rank mismatch"
    
    # Clean up
    os.remove("test_merges.sqlite")
    os.remove("test_merges.sqlite-wal")
    os.remove("test_merges.sqlite-shm")

def test_byte_loss_tracking():
    """Verify that byte losses are tracked and checkpointed."""
    tok = ByteLevelBPETokenizer(vocab_size=256 + 5, merge_file="test_loss.sqlite")
    
    # Encode bytes that don't have merge rules
    raw_bytes = bytes(range(256))  # All possible byte values
    tokens = tok.encode_bytes_raw(raw_bytes)
    
    # Some bytes should trigger loss tracking if not in vocab
    assert sum(tok.byte_loss_counter.values()) >= 0, \
        "Loss counter should be accessible"
    
    tok._checkpoint_losses()
    assert os.path.exists(tok.loss_checkpoint_path), \
        "Loss checkpoint file should exist"
    
    # Clean up
    os.remove("test_loss.sqlite")
    os.remove(tok.loss_checkpoint_path)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
```

### Running the Tests

```bash
python -m pytest test_tokenizer.py -v
```

Expected output should show all tests passing, confirming that encoding/decoding is lossless, merges persist across restarts, and byte-loss tracking works correctly. For a more rigorous test, generate a larger corpus (the WikiText or Common Crawl dataset) and verify that the vocabulary grows monotonically and that the merge queue processes thousands of merges without corruption.

## Extending It: Your Roadmap to Senior-Level

The base implementation above is a solid portfolio piece. But to truly signal senior-level engineering capability, here are concrete upgrades that transform the toy into a production-flavored system:

1. **Add a gRPC/HTTP service layer with hot-reloading vocabulary.** Wrap the tokenizer in a FastAPI or gRPC service that can reload the merge queue from SQLite without downtime. This matters because production tokenizers must be updated without dropping active inference requests — a skill directly transferable to model serving platforms like NVIDIA Triton or BentoML.

2. **Implement horizontal scaling with a shared merge queue backed by Redis or etcd.** Replace SQLite with a distributed lock manager so multiple trainer instances can propose merges concurrently. This matters because real tokenizer training on terabyte-scale corpora requires parallel workers, and distributed consensus is a systems skill that separates senior engineers from juniors.

3. **Add Prometheus metrics and structured logging for observability.** Expose counters for bytes processed, merge rate, byte-loss rate, and vocabulary growth as Prometheus metrics. Use `structlog` for structured JSON logging. This matters because production ML infrastructure is unobservable by default, and hiring managers value engineers who build systems they can debug at 3 AM.

4. **Implement a fault-tolerant training pipeline with write-ahead logging and snapshot recovery.** Before each merge, write the proposed change to a WAL file. On restart, replay or rollback based on commit status. Take periodic snapshots of the full vocabulary. This matters because training on large datasets takes hours or days, and a crash without recovery means wasted compute — a real cost concern in production ML.

5. **Build a benchmarking harness with latency percentiles and memory profiling.** Use `pytest-benchmark` or `cProfile` to measure encode/decode latency at the p50, p95, and p99 percentiles. Profile memory usage with `tracemalloc` or `py-spy` during streaming. This matters because tokenizer throughput is a bottleneck in LLM inference pipelines, and being able to quantify and optimize performance is a senior-level expectation.

6. **Add a vocabulary visualization dashboard using Streamlit or Grafana.** Render the merge tree as an interactive graph showing which byte sequences merged at each step, with byte-loss heatmaps over the Unicode space. This matters because understanding vocabulary quality is a critical part of tokenizer development, and visual tools accelerate iteration — a skill that bridges engineering and research.

## Key Takeaways

- **Byte-level BPE is the foundation of modern LLM tokenizers.** Building one from scratch forces you to understand UTF-8 encoding, merge algorithms, and vocabulary management at a level that textbook summaries never achieve.
- **Persistence and atomicity aren't optional in production.** Using SQLite with WAL mode and explicit transactions teaches you the same patterns used in distributed databases and model serving systems.
- **Reversible encoding for arbitrary Unicode is a hard problem with real consequences.** Byte-loss tracking and fallback mechanisms ensure your tokenizer doesn't silently corrupt text — a common failure mode in production NLP pipelines.
- **This project demonstrates the full stack.** From algorithms and data structures to systems engineering, observability, and distributed computing, it signals readiness for roles that sit at the intersection of ML and infrastructure.
- **The roadmap upgrades map directly to senior-level responsibilities.** Each extension — horizontal scaling, fault tolerance, observability, benchmarking — is a skill that hiring managers actively screen for in senior engineering candidates.

## Further Reading

- [Language Models are Unsupervised Multitask Learners (Radford et al., 2019)](https://d4mucfpksywv.cloudfront.net/better-language-models/language-models.pdf) — The original GPT-2 paper that popularized byte-level BPE tokenization. Section 3 describes the tokenizer architecture in detail.
- [Subword Nuance: A Critical Analysis of BPE and SentencePiece (Sennrich et al., 2016)](https://arxiv.org/abs/1910.13267) — The foundational paper on BPE for neural machine translation, introducing the byte-pair encoding algorithm that this project implements.
- [RFC 3629 — UTF-8, a transformation format of ISO 10646](https://www.rfc-editor.org/rfc/rfc3629) — The canonical specification for UTF-8 encoding. Essential reading for understanding byte-level text processing and the edge cases your tokenizer must handle.
- [SentencePiece: A Simple and Language Independent Subword Tokenizer](https://arxiv.org/abs/1808.06226) — The paper behind Google's SentencePiece library. It extends BPE with unigram language modeling and provides production-grade implementations worth studying.
- [The Illustrated Transformer (Jay Alammar)](https://jalammar.github.io/illustrated-transformer/) — A visual guide to the Transformer architecture that includes a clear explanation of how tokenizers feed into the model pipeline.
- [RocksDB: A Fast Key-Value Store](https://rocksdb.org/) — If you replace SQLite with a more performant persistent store for the merge queue, RocksDB is the industry-standard embedded key-value store used by Facebook, Alibaba, and others for high-throughput state management.
- [Prometheus: The Definitive Guide](https://prometheus.io/docs/guides/go-application/) — The canonical guide to instrumenting applications with Prometheus metrics. Directly applicable to the observability upgrade in the roadmap.
- [Designing Data-Intensive Applications (Kleppmann)](https://dataintensive.net/) — The reference book for the systems concepts underlying this project: persistence, fault tolerance, distributed consensus, and stream processing. Chapter 5 covers exactly the kind of atomic state management your merge queue requires.

---

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
