---
title: "Build a WordPiece Tokenizer From Scratch: A CV-Worthy NLP Project"
date: "2026-09-06T09:00:30.379"
draft: false
tags: ["nlp", "python", "tokenization", "bert", "side-projects"]
description: "A hands-on guide to building a WordPiece tokenizer from scratch, with subword merging, BERT special tokens, and greedy decode-to-words, designed as a portfolio project."
summary: "Build a production-shaped WordPiece tokenizer in Python with subword merging, BERT special tokens, and a greedy decode path. Includes runnable code, tests, and a roadmap to senior-level extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-build-a-wordpiece-tokenizer-from-scratch-a-cv-worthy-nlp-project.svg"
  alt: "Code editor showing a Python tokenizer implementation with token merges and a vocabulary table."
  caption: ""
  relative: false
---

> **TL;DR** — A from-scratch WordPiece tokenizer is a small, runnable system that proves you understand subword segmentation, the greedy longest-match algorithm, and BERT's special-token contract end-to-end. It fits on a single weekend but signals NLP depth, careful testing habits, and the kind of systems thinking hiring managers look for in ML and platform roles.

## Why This Project Stands Out on a CV

Hiring teams in 2026 are drowning in portfolio projects that wrap an LLM API. The projects that cut through are ones where the candidate shows they understand what sits underneath the API surface. A tokenizer is one of those layers. Almost every modern NLP system — BERT, DistilBERT, RoBERTa, ALBERT, the encoder half of T5 — uses WordPiece as its subword algorithm, and the people who can reason about it confidently are the ones who can debug tokenization drift, vocabulary mismatches, and "why does this one input blow up my model" bugs in production.

Concretely, this project demonstrates:

- **Algorithm literacy.** You can explain and implement the longest-match-first scoring rule, the `##` continuation convention, and the difference between BPE merge-order learning and WordPiece likelihood scoring. That vocabulary is what shows up in system design interviews for ML platform roles.
- **BERT-protocol fluency.** Hand-rolled `[CLS]`/`[SEP]`/`[PAD]` handling with attention masks and token-type ids is the same contract Hugging Face's `BertTokenizerFast` implements. If you can write it from scratch, you understand what the library hides from you.
- **Test-driven engineering.** A tokenizer has crisp, falsifiable behavior. Writing a real `pytest` suite with edge inputs (empty strings, punctuation, out-of-vocab words, long-tail Unicode) signals that you treat correctness as non-negotiable, which is the single strongest predictor of senior-level hire signals.
- **Systems thinking.** Once you have the core loop, persistence to a `tokenizer.json` artifact, deterministic vocab hashing, and a small CLI are one evening away — and that evening is the difference between a "tutorial clone" and a project that looks like it shipped.

Roles this signals for: ML engineer, applied scientist, NLP engineer, ML platform engineer, and even backend engineers who work on inference infrastructure. It is the rare side project that is technical enough to impress a research team and pragmatic enough to impress a platform team.

## Architecture Overview

The system has five cleanly separable components. Keeping them split is what makes the project easy to extend later.

- **Corpus loader.** A tiny iterator over plain text files. Yields one normalized line at a time. Keeps memory flat regardless of corpus size.
- **Vocabulary builder.** Counts word frequencies on the pre-tokenized corpus, then greedily grows the vocab by selecting the candidate subword pair that maximizes the WordPiece likelihood score (the log-probability ratio of the pair vs. the independent subwords). Emits `vocab.txt` in BERT's sorted order so downstream tooling stays compatible.
- **Encoder.** Takes a string, applies basic normalization, inserts `[CLS]` and `[SEP]`, runs longest-match-first against the vocab, and emits `input_ids`, `token_type_ids`, and `attention_mask`.
- **Decoder (greedy decode-to-words).** Walks the `input_ids`, drops special tokens, joins `##` continuations to the previous token, and surfaces a list of words plus the original text.
- **Persistence + CLI.** Writes the vocab and config to disk in a layout that mirrors `tokenizers.json`, and exposes a `python -m wordpiece` command for encode/decode.

The data flow looks like this:

```
raw text
   │
   ▼
[Normalizer]  lowercase, strip accents, whitespace collapse
   │
   ▼
[Pre-tokenizer]  split on whitespace + punctuation, keep offsets
   │
   ▼
[WordPiece Model]  longest-match-first lookup in vocab
   │
   ▼
[Post-processor]  prepend [CLS], append [SEP], build type ids + mask
   │
   ▼
Encoding { input_ids, token_type_ids, attention_mask }
```

The decode path runs the inverse: drop specials, expand `##` prefixes, concatenate, and return words. Each box is small enough to swap independently — which is exactly what the senior-level extensions below exploit.

## Building It Step by Step

Let's build the thing. The full code lives in a single package called `wordpiece`, with one module per component. I'll show the parts that matter; the rest is mechanical glue.

### Step 1 — Project layout

```
wordpiece/
  __init__.py
  __main__.py          # CLI entry point
  normalizer.py
  pre_tokenizer.py
  vocab.py
  model.py              # the WordPiece algorithm itself
  post_processor.py
  tokenizer.py          # the public Encoder/Decoder
  persistence.py
tests/
  test_tokenizer.py
data/
  corpus.txt            # ~5 MB of public-domain text
```

Add a `pyproject.toml` so the package is installable, and pin `pytest` for the test runner. Nothing exotic.

### Step 2 — The normalizer

The job here is to produce the canonical string form the vocab was built against. For BERT-style English, the rules are: NFD Unicode, strip combining marks, lowercase, collapse whitespace.

```python
# wordpiece/normalizer.py
import re, unicodedata

_WS = re.compile(r"\s+")

def normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower()
    text = _WS.sub(" ", text).strip()
    return text
```

This is the same chain Hugging Face's `BertNormalizer` performs under the hood. Keeping it explicit means you can swap in a multilingual rule set later without touching the encoder.

### Step 3 — The pre-tokenizer

Pre-tokenization splits on whitespace and punctuation, but **keeps the offsets** so the decoder can recover the original whitespace. This is the part people skip and then can't reverse.

```python
# wordpiece/pre_tokenizer.py
import re

# punctuation that always splits; ASCII letters/digits/apostrophe are word chars
_SPLIT = re.compile(r"([\u0021-\u002F\u003a-\u0040\u005b-\u0060\u007b-\u007e])")

def pre_tokenize(text: str):
    tokens, offsets = [], []
    cursor = 0
    for match in _SPLIT.finditer(text):
        start, end = match.span()
        if cursor < start:
            chunk = text[cursor:start]
            tokens.append(chunk)
            offsets.append((cursor, start))
        tokens.append(match.group())
        offsets.append((start, end))
        cursor = end
    if cursor < len(text):
        tokens.append(text[cursor:])
        offsets.append((cursor, len(text)))
    return tokens, offsets
```

For a "Don't panic!" input you get `["Don", "'", "t", "panic", "!"]` with offsets. The decoder uses those offsets to glue the original whitespace back together.

### Step 4 — The vocab builder

This is the part most blog posts skip because the scoring rule looks intimidating. It is not. WordPiece picks the subword pair with the highest score `(freq(pair) / freq(first)) / (freq(second))`, restricted to pairs where the first piece appears at the start of some word. We then add the best pair to the vocab and repeat.

```python
# wordpiece/vocab.py
from collections import Counter

def word_freqs(corpus_iter):
    freq = Counter()
    for line in corpus_iter:
        for word in normalize(line).split():
            freq[word] += 1
    return freq

def initial_alphabet(freqs):
    alpha = set()
    for word in freqs:
        if word:
            alpha.add(word[0])
            for ch in word[1:]:
                alpha.add(f"##{ch}")
    return alpha

def compute_pair_scores(freqs, vocab):
    subword_freq = Counter()
    pairs = Counter()
    for word, f in freqs.items():
        pieces = [word[0]] + [f"##{c}" for c in word[1:]]
        for p in pieces:
            subword_freq[p] += f
        for a, b in zip(pieces[:-1], pieces[1:]):
            pairs[(a, b)] += f
    scores = {}
    for (a, b), p in pairs.items():
        denom = subword_freq[a] * subword_freq[b]
        scores[(a, b)] = p / denom if denom else 0.0
    return scores, subword_freq

def grow_vocab(freqs, target_size, specials):
    vocab = set(specials) | initial_alphabet(freqs)
    while len(vocab) < target_size:
        scores, subword_freq = compute_pair_scores(freqs, vocab)
        # only pairs whose first piece appears at word start are eligible
        eligible = {p: s for p, s in scores.items() if p[0] in subword_freq}
        if not eligible:
            break
        best = max(eligible, key=eligible.get)
        vocab.add(best[0] + best[1][2:])  # drop the "##" from the second piece
    return vocab
```

Run it on `data/corpus.txt` and write the vocab out sorted, BERT-style:

```python
# wordpiece/vocab.py (continued)
def save_vocab(vocab, path):
    with open(path, "w", encoding="utf-8") as f:
        for token in sorted(vocab):
            f.write(token + "\n")
```

### Step 5 — The WordPiece model (longest-match-first)

This is the hot loop. Given a word, find the longest prefix that is in the vocab. If it is not a `##` piece, recurse on the rest. If nothing matches, the project policy is: emit `[UNK]`. Production vocabularies typically include `[UNK]` from the start.

```python
# wordpiece/model.py
UNK = "[UNK]"

def wordpiece_tokenize(word, vocab, max_input_chars=100):
    if len(word) > max_input_chars:
        return [UNK]
    out = []
    start = 0
    while start < len(word):
        end = len(word)
        cur = None
        while start < end:
            sub = word[start:end]
            if start > 0:
                sub = "##" + sub
            if sub in vocab:
                cur = sub
                break
            end -= 1
        if cur is None:
            return [UNK]
        out.append(cur)
        start = end
    return out
```

That is the whole algorithm. Everything else is plumbing.

### Step 6 — The post-processor

BERT expects `[CLS]` at position 0, `[SEP]` at the end of each segment, an `attention_mask` of `1`s over real tokens and `0`s over padding, and `token_type_ids` of `0` for segment A and `1` for segment B.

```python
# wordpiece/post_processor.py
CLS, SEP, PAD = "[CLS]", "[SEP]", "[PAD]"

def post_process(ids_a, ids_b=None):
    cls_id = vocab_id(CLS)
    sep_id = vocab_id(SEP)
    pad_id = vocab_id(PAD)
    tokens = [cls_id] + ids_a + [sep_id]
    type_ids = [0] * len(tokens)
    if ids_b is not None:
        tokens += ids_b + [sep_id]
        type_ids += [1] * (len(ids_b) + 1)
    mask = [1] * len(tokens)
    return {"input_ids": tokens, "token_type_ids": type_ids, "attention_mask": mask}
```

### Step 7 — The public `Tokenizer` and the decoder

The decoder is the part the title calls out specifically. Walk the ids, drop specials, and fold `##` continuations back into the previous word.

```python
# wordpiece/tokenizer.py
class Tokenizer:
    def __init__(self, vocab):
        self.vocab = vocab
        self.tok2id = {t: i for i, t in enumerate(vocab)}
        self.id2tok = {i: t for t, i in self.tok2id.items()}

    def encode(self, text_a, text_b=None):
        ids_a = self._encode_text(text_a)
        ids_b = self._encode_text(text_b) if text_b else None
        return post_process(ids_a, ids_b, self.id2tok)  # wired up via persistence

    def _encode_text(self, text):
        ids = []
        for word, (s, e) in zip(*pre_tokenize(normalize(text))):
            for piece in wordpiece_tokenize(word, self.vocab):
                ids.append(self.tok2id[piece])
        return ids

    def decode(self, ids, skip_specials=True):
        tokens = [self.id2tok[i] for i in ids]
        if skip_specials:
            tokens = [t for t in tokens if t not in (CLS, SEP, PAD, UNK)]
        words = []
        for tok in tokens:
            if tok.startswith("##") and words:
                words[-1] = words[-1] + tok[2:]
            else:
                words.append(tok)
        return words
```

Greedy decode-to-words gives you exactly what `decode()` returns: a list of word-level strings with the `##` glue removed. If you also want the original text back with whitespace, keep the offsets from pre-tokenization and use them to splice pieces into the source string.

## Running and Testing It

Now wire the CLI. A thin `__main__.py` is enough:

```python
# wordpiece/__main__.py
import argparse, sys
from .vocab import word_freqs, grow_vocab, save_vocab
from .tokenizer import Tokenizer

def main():
    p = argparse.ArgumentParser(prog="wordpiece")
    sub = p.add_subparsers(dest="cmd", required=True)

    train = sub.add_parser("train")
    train.add_argument("corpus")
    train.add_argument("--out", default="vocab.txt")
    train.add_argument("--size", type=int, default=30000)

    enc = sub.add_parser("encode")
    enc.add_argument("--vocab", required=True)
    enc.add_argument("--text", required=True)

    args = p.parse_args()

    if args.cmd == "train":
        with open(args.corpus, encoding="utf-8") as f:
            freqs = word_freqs(f)
        specials = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]
        vocab = sorted(grow_vocab(freqs, args.size, specials) | set(specials))
        save_vocab(vocab, args.out)
        print(f"wrote {args.out} with {len(vocab)} tokens")
    elif args.cmd == "encode":
        with open(args.vocab, encoding="utf-8") as f:
            vocab = [line.rstrip("\n") for line in f]
        tk = Tokenizer(vocab)
        out = tk.encode(args.text)
        print(out)

if __name__ == "__main__":
    sys.exit(main())
```

Train on a small public-domain corpus:

```bash
python -m wordpiece train data/corpus.txt --out vocab.txt --size 30000
python -m wordpiece encode --vocab vocab.txt --text "Don't panic."
```

Then prove it with tests. This is the part that separates a tutorial from a portfolio piece:

```python
# tests/test_tokenizer.py
import pytest
from wordpiece.normalizer import normalize
from wordpiece.pre_tokenizer import pre_tokenize
from wordpiece.tokenizer import Tokenizer
from wordpiece.model import wordpiece_tokenize

VOCAB = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]",
         "don", "##'", "##t", "panic", "!", "lower"]

def test_normalizer_lowercases_and_strips_accents():
    assert normalize("  Café  Déjà ") == "cafe deja"

def test_pre_tokenizer_keeps_punctuation_and_offsets():
    toks, offs = pre_tokenize("Don't panic!")
    assert toks == ["Don", "'", "t", "panic", "!"]
    assert offs == [(0, 3), (3, 4), (4, 5), (6, 11), (11, 12)]

def test_wordpiece_longest_prefix_match():
    pieces = wordpiece_tokenize("dont", VOCAB)
    assert pieces == ["don", "##t"]

def test_encoder_inserts_specials_and_mask():
    tk = Tokenizer(VOCAB)
    out = tk.encode("Don't panic!")
    assert out["input_ids"][0] == VOCAB.index("[CLS]")
    assert out["input_ids"][-1] == VOCAB.index("[SEP]")
    assert out["attention_mask"] == [1] * len(out["input_ids"])
    assert all(t == 0 for t in out["token_type_ids"])

def test_decode_to_words_strips_hashmark_glue():
    tk = Tokenizer(VOCAB)
    ids = [VOCAB.index("[CLS]"), VOCAB.index("don"),
           VOCAB.index("##t"), VOCAB.index("[SEP]")]
    assert tk.decode(ids) == ["dont"]

def test_unk_fallback_for_oov_word():
    pieces = wordpiece_tokenize("banana", VOCAB)
    assert pieces == ["[UNK]"]
```

Run it:

```bash
pytest -q
python -m wordpiece train data/corpus.txt --out vocab.txt --size 30000
python -m wordpiece encode --vocab vocab.txt --text "Don't panic, Mr. President."
```

If the encoder produces something like `[CLS] don ' ##t panic , mr . president . [SEP]`, you have a working tokenizer that round-trips through a vocab, special tokens, and greedy decode. That alone is a project; everything below is polish.

## Extending It: Your Roadmap to Senior-Level

The core is small on purpose. The value of the project to a hiring manager scales with how much of the following you ship. Each bullet is one focused PR.

- **Persistence to a `tokenizer.json` artifact.** Serialize vocab, normalizer rules, pre-tokenizer regex, and post-processor config into a single JSON that mirrors Hugging Face's format. Reason it matters: a tokenizer is only useful if it is reproducible six months later on someone else's laptop.
- **Multiprocess vocab training with `multiprocessing.Pool`.** Shard the corpus by hash bucket, compute pair scores per shard, then merge with a reduction pass. Reason it matters: training on a real corpus (a few GB of Common Crawl) is single-threaded-impossible, and recruiters notice when you actually scaled something.
- **Structured observability.** Emit OpenTelemetry spans for `normalize`, `pre_tokenize`, `wordpiece_tokenize`, and `post_process` with token counts as attributes. Reason it matters: tokenization is a hidden SLO; you cannot debug latency regressions in a 100k-RPS inference path without spans.
- **Fault tolerance via checkpointing.** Snapshot `subword_freq` and `pairs` to LMDB after every 1k iterations so a crash mid-training loses at most one minute of work. Reason it matters: the difference between a hobby script and production tooling is whether it survives a power loss.
- **Benchmark harness.** Wrap `tokenize` in a `timeit`-driven benchmark that reports tokens/sec, peak RSS via `tracemalloc`, and the 99p latency from `perf_counter`. Compare your tokenizer against `bert-base-uncased` from Hugging Face. Reason it matters: performance claims without numbers are vibes; numbers are senior-level signal.
- **Server mode with `FastAPI` and `uvicorn`.** Expose `POST /encode` and `POST /decode` with Pydantic models, behind a single uvicorn worker. Reason it matters: it turns a library into a deployable service, which is the kind of "I shipped it" line a CV actually wants.

Pick two. Ship them. The project stops being "I built a tokenizer" and starts being "I built and operated a tokenizer service" — and that phrasing is what gets interviews.

## Key Takeaways

- A WordPiece tokenizer is small enough to fit on a weekend but dense enough to demonstrate NLP depth, BERT-protocol fluency, and test discipline in one artifact.
- The two non-obvious parts are the **vocab scoring rule** (`freq(pair) / (freq(a) * freq(b))`) and the **longest-match-first** encoder loop; both are short once you write them down.
- Keep the five components — normalizer, pre-tokenizer, vocab builder, encoder/decoder, persistence — cleanly separated so each one can be swapped or scaled independently.
- Decode-to-words is just "drop specials, fold `##` continuations into the previous token" — trivial to implement and easy to test.
- The CV value compounds when you add persistence, parallelism, observability, and a benchmark harness; those are the moves that turn a tutorial into a portfolio piece.

## Further Reading

- [Wu et al., "Google's Neural Machine Translation System" (the original WordPiece paper)](https://arxiv.org/abs/1609.08144)
- [Schuster & Nakajima, "Japanese and Korean Voice Search" (the canonical BPE-for-NLP formulation)](https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/37842.pdf)
- [Hugging Face Tokenizers documentation — components and pipeline](https://huggingface.co/docs/transformers/tokenizer_summary)
- [BERT repo — `tokenization.py` reference implementation](https://github.com/google-research/bert/blob/master/tokenization.py)
- [Sennrich et al., "Neural Machine Translation of Rare Words with Subword Units" (BPE primer)](https://arxiv.org/abs/1508.07909)
- [Kudo, "Subword Regularization" (a useful contrast to WordPiece's greedy scoring)](https://arxiv.org/abs/1804.10959)