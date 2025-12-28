---
title: "Attention Is All You Need: Zero-to-Hero"
date: "2025-12-28T01:56:00+02:00"
draft: false
tags: ["transformers", "attention", "deep learning", "nlp", "llm", "paper-walkthrough"]
---

# Attention Is All You Need — Zero to Hero

**Paper:** Vaswani et al., 2017
**Core idea:** You can replace recurrence and convolution entirely with attention

## 0. Why This Paper Exists (The Big Picture)

### The problem (pre-2017)
Sequence modeling (translation, text, speech) relied on:
- RNNs / LSTMs
- GRUs
- CNNs

These had major limitations:
- ❌ Sequential computation (slow training)
- ❌ Long-range dependency problems
- ❌ Hard to parallelize

### The radical claim
**"Attention alone is sufficient for sequence modeling."**

- No recurrence
- No convolution
- Just attention + feed-forward layers

This paper introduced the **Transformer**, which now powers:
- GPT
- BERT
- Claude
- LLaMA
- Basically everything modern

## 1. What Is "Attention"? (Intuition First)

### Human analogy
When reading a sentence, you don't read word-by-word blindly. You look back and forth to relevant words.

**Example:**

> "The animal didn't cross the street because it was too tired."

What does "it" refer to? You attend to **animal**, not street.

### Formal idea
Attention answers: **"How much should token A care about token B?"**

Mathematically:
1. Compare a query to keys
2. Use similarity scores
3. Apply weighted sum over values

## 2. Scaled Dot-Product Attention (Core Mechanism)

### The formula (don't panic yet)

```
Attention(Q, K, V) = softmax(QK^T / √d_k) × V
```

Let's unpack slowly.

### Step 1: Queries, Keys, Values
Each token becomes three vectors:
- **Query (Q)** → what am I looking for?
- **Key (K)** → what do I contain?
- **Value (V)** → what do I provide if selected?

These come from learned linear projections.

### Step 2: Similarity scores
Compute:
```
score = Q · K
```
This tells us how relevant another token is.

### Step 3: Scaling
Why divide by √d_k?
- Large dot products → extreme softmax values
- Causes unstable gradients
- Scaling keeps training stable

### Step 4: Softmax → weights
Convert scores into probabilities:
- All weights sum to 1
- Represents attention distribution

### Step 5: Weighted sum of values
Each token becomes:
> "A blend of other tokens, weighted by relevance"

This is **contextualization**.

## 3. Multi-Head Attention (Why One Attention Isn't Enough)

### Problem with single attention
One attention mechanism can focus on only one type of relationship.

### Solution: Multiple heads
Instead of one attention:
1. Split vectors into `h` heads
2. Each head attends differently

**Examples:**
- Head 1 → syntax
- Head 2 → coreference
- Head 3 → long-range meaning

### Process
1. Linear projections → multiple subspaces
2. Apply attention independently
3. Concatenate outputs
4. Final linear projection

This gives **rich, diverse representations**.

## 4. Positional Encoding (Where Is Order?)

### The problem
Transformers:
- Process tokens in parallel
- Have no built-in notion of order

### The solution
Add positional encodings to embeddings.

The paper uses **sinusoidal encodings:**

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d))
```

### Why sinusoidal?
- Continuous
- Generalizes to longer sequences
- Relative positions can be inferred linearly

Modern models often use **learned** or **rotary** variants.

## 5. The Transformer Encoder (Stacked Intelligence)

### Encoder responsibilities
1. Read the input sequence
2. Produce contextual representations

### Encoder layer structure
Each layer has:
1. **Multi-Head Self-Attention**
2. **Feed-Forward Network**
3. **Residual connections**
4. **Layer normalization**

### Feed-Forward Network (FFN)
Same FFN applied to each token:

```
FFN(x) = max(0, xW₁ + b₁)W₂ + b₂
```

Think of it as:
> "Token-wise non-linear reasoning"

### Residuals + LayerNorm
They:
- Stabilize gradients
- Enable deep stacking
- Preserve information

## 6. The Transformer Decoder (Controlled Generation)

### Decoder's job
Generate output one token at a time, while:
1. Attending to previous outputs
2. Attending to encoder outputs

### Decoder layer structure
Each layer has three sub-layers:
1. **Masked Self-Attention**
2. **Encoder–Decoder Attention**
3. **Feed-Forward Network**

### Masked attention (crucial)
Prevents cheating:
- Token `t` cannot see tokens `t+1...n`
- This enforces **autoregressive generation**

## 7. Encoder–Decoder Attention (Translation Bridge)

This allows:
- **Decoder queries**
- **Encoder keys/values**

Effect:
> "While generating word i, look at relevant input words."

This is how **translation alignment** emerges.

## 8. Training Objective

### Task
Machine translation.

### Loss
Standard cross-entropy loss over next-token prediction.

### Teacher forcing
- Decoder sees ground-truth previous tokens
- Speeds up training

## 9. Optimization Tricks (Why It Actually Works)

### Adam optimizer
With custom learning rate schedule:

```
lr = d^(-0.5) × min(step^(-0.5), step × warmup^(-1.5))
```

**Why?**
- Large models need warmup
- Prevents early divergence

### Label smoothing
Prevents overconfidence:
- Improves generalization
- Stabilizes training

## 10. Results & Why They Mattered

### Key achievements
- 🔥 Better BLEU scores
- ⚡ Faster training
- 📈 Better scaling

### Historical impact
This paper:
- Replaced RNNs
- Enabled LLMs
- Changed deep learning architecture design

## Final Chapter — How to Truly Master This Paper

### Step-by-Step Learning Path

#### Step 1 — Intuition
- Understand why attention replaces recurrence
- Visualize attention matrices

#### Step 2 — Math
- Re-derive attention formula by hand
- Understand matrix shapes

#### Step 3 — Code
Implement:
1. Scaled dot-product attention
2. Multi-head attention
3. Full Transformer block

#### Step 4 — Variants
- **BERT** (encoder-only)
- **GPT** (decoder-only)
- **T5** (encoder-decoder)

### Essential Resources (High Quality)

#### Paper & Visuals
- **Original paper (Annotated):**
  https://nlp.seas.harvard.edu/annotated-transformer/

- **Jay Alammar (visual gold):**
  https://jalammar.github.io/illustrated-transformer/

#### Video
- **Yannic Kilcher (deep dive):**
  https://www.youtube.com/watch?v=iDulhoQ2pro

- **Andrej Karpathy (from scratch):**
  https://www.youtube.com/watch?v=kCc8FmEb1nY

#### Code
- **Harvard NLP implementation:**
  https://github.com/harvardnlp/annotated-transformer

- **PyTorch official tutorial:**
  https://pytorch.org/tutorials/beginner/transformer_tutorial.html

#### Advanced Topics
- Attention complexity & FlashAttention
- Rotary Position Embeddings (RoPE)
- KV-caching for inference