---
title: "How Tokenizers in Large Language Models Work: A Deep Dive"
date: "2026-01-06T08:24:25.543"
draft: false
tags: ["Tokenization", "LLMs", "Byte Pair Encoding", "BPE", "Natural Language Processing", "AI Tokenizers"]
---

## Introduction

Tokenizers are the unsung heroes of large language models (LLMs), converting raw text into numerical sequences that models can process. Without tokenization, LLMs couldn't interpret human language, as they operate solely on numbers.[1][4][5] This comprehensive guide explores how tokenizers work, focusing on **Byte Pair Encoding (BPE)**—the dominant method in modern LLMs like GPT series—while covering fundamentals, algorithms, challenges, and practical implications.[3][5]

## Why Tokenization Matters in LLMs

Tokens are the **fundamental units**—"atoms"—of LLMs. Everything from input processing to output generation happens in tokens.[3][5] Tokenization breaks text into discrete components, assigns each a unique **ID**, and maps it to an **embedding** vector for the model.[1][2][4]

Key reasons tokenization is essential:
- **Numerical conversion**: LLMs process numbers, not strings. Tokens become IDs, then embeddings capturing meaning.[4]
- **Efficiency**: Subword units balance vocabulary size and coverage, handling rare words and out-of-vocabulary (OOV) issues.[1][5]
- **Context limits**: Models have fixed **context windows** (e.g., max tokens per input), directly impacting usable text length.[4]
- **Autoregressive generation**: LLMs predict the next token based on prior ones, repeating until a stop condition.[2]

For example, "BentoML supports custom LLM inference." tokenizes (using GPT-4o) as: **"B", "ento", "ML", " supports", " custom", " L", "LM", " inference", "."** with IDs like [33, 13969, 4123...].[2]

## Types of Tokenizers

Tokenizers evolved from simple to sophisticated methods:

- **Character-based**: Treats each character as a token. Vocabulary ~256 (bytes) or Unicode size. Pros: No OOV. Cons: Long sequences, poor efficiency (e.g., "dog" = 3 tokens).[1][5]
- **Word-based**: Splits on spaces/punctuation. Vocabulary explodes with rare words (e.g., "unread" as one token fails on "theemailisunread").[4]
- **Subword-based**: Hybrids like **BPE**, WordPiece, or SentencePiece. Most common in LLMs; vocabulary 30k-100k tokens.[1][3][5]

**BPE** dominates (used in GPT, Llama), starting from bytes for universality across languages.[3][5]

## Byte Pair Encoding (BPE): The Core Algorithm

BPE builds a vocabulary by iteratively merging frequent byte pairs, compressing text efficiently.[1][3][5]

### Step-by-Step BPE Training

1. **Start with bytes**: Convert text to UTF-8 bytes (vocab size: 256). Tokenize into single-byte tokens.[3]
2. **Count pairs**: Find most frequent adjacent pairs (e.g., 'a' + 'a').[3]
3. **Merge**: Replace pair with new token (ID 256+), add to vocab. Repeat on updated text.[1][3]
4. **Iterate**: Continue until vocab reaches target (e.g., 50k).[1]
5. **Encode new text**: Apply merges in order to split into vocab tokens; fallback to bytes.[3]

**Example** from a simple text (inspired by Karpathy's implementation):[3]

Original: "aaabdaabac" → Bytes: [97,97,97,98,100,97,97,98,97,99] (a=97, b=98, etc.)

- Merge most frequent 'a'+'a' → new token 256 ("aa")
- Updated: [256,97,98,100,256,98,97,99]
- Next: 'a'+'b' → 257 ("ab")
- Continue until compressed.

Python snippet for BPE basics (from fast.ai guide):[3]

```python
def get_most_frequent_pair(current_tokens):
    pairs = {}
    for i in range(len(current_tokens) - 1):
        pair = (current_tokens[i], current_tokens[i+1])
        pairs[pair] = pairs.get(pair, 0) + 1
    return max(pairs, key=pairs.get)

# Training loop
vocab_size = 256
merges = {}
while vocab_size < target_vocab_size:
    pair = get_most_frequent_pair(current_tokens)
    merges[pair] = vocab_size
    # Replace pair with new token
    vocab_size += 1
```

This yields merges like: Token 260: (105,110) → 'i'+'n' = "in".[3]

> **Key Insight**: BPE learns common substrings (e.g., "ing", "tion"), handling morphology without explicit rules.[1]

### Encoding and Decoding

- **Encoding**: Greedily apply merges from first to last. Unknown sequences fall to bytes.[5]
- **Decoding**: Reverse: Split tokens back to bytes/strings.[3]
- Tools: OpenAI's **tiktoken** (open-source BPE impl.).[5]

## Tokenizers in the LLM Pipeline

Tokenizers integrate into **inference** (prefill + decode):[2]

1. **Prefill**: Prompt → Tokens → IDs → Embeddings → Transformer layers (self-attention via QKV).[2]
2. **Decode**: Autoregressively generate next token (prob dist. over vocab), append, repeat until EOS.[2]
3. **Output**: Detokenize IDs to text.[2][4]

Embeddings differ from tokens: Tokens → IDs → **Embeddings** (learned vectors linking similar meanings, e.g., "email"/"emails").[4][5]

## Challenges and Advanced Topics

- **Variability**: Inconsistent tokenization (e.g., "dog" as "d"+"o"+"g" or "dog") aids robustness, like noise in speech models.[1]
- **Multilingual**: Byte-level BPE handles any UTF-8 without OOV.[3]
- **Context Window**: Longer tokens = less content (e.g., code > English).[4]
- **Custom Vocabs**: Fine-tune for domains (e.g., enterprise jargon).[4]
- **Alternatives**: Unigram (SentencePiece), used in T5/BERT.[5]

| Tokenizer Type | Vocab Size | Strengths | Weaknesses |
|---------------|------------|-----------|------------|
| **Character** | ~256 | No OOV | Long seqs |
| **Word** | Millions | Readable | OOV explodes |
| **BPE/Subword** | 30k-100k | Efficient, robust | Learned, opaque [1][3][5] |

## Practical Tips and Experiments

- Test tokenizers: Use tiktoken to count tokens in your prompts.
- Variability experiment: Models generalize better with split roots (e.g., "run"/"r"+"un").[1]
- Compression: BPE shrinks datasets (11→5 tokens in example).[3]

## Conclusion

Tokenizers like **BPE** enable LLMs to handle diverse text efficiently, bridging human language and machine computation. Mastering them unlocks better prompting, cost optimization (tokens = billing units), and custom models. As LLMs evolve, expect smarter tokenizers tackling efficiency and multimodality.

## Resources

- [Tokenization in LLMs Explained](https://seantrott.substack.com/p/tokenization-in-large-language-models)[1]
- [Karpathy: Build GPT Tokenizer](https://www.fast.ai/posts/2025-10-16-karpathy-tokenizers.html)[3] (incl. code)
- [OpenAI tiktoken](https://github.com/openai/tiktoken) – Hands-on BPE[5]
- [LLM Inference Basics](https://bentoml.com/llm/llm-inference-basics/how-does-llm-inference-work)[2]
- [AI21 Tokenization Guide](https://www.ai21.com/knowledge/tokenization/)[4]
- [ChristopherGS: Technical Intro](https://christophergs.com/blog/understanding-llm-tokenization)[5]

Experiment with these to tokenize your own text—understanding tokens demystifies LLMs!