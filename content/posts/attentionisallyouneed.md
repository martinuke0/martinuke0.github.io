---
title: "Attention Is All You Need: Zero-to-Hero"
date: "2025-12-28T01:56:00+02:00"
draft: false
tags: ["transformers", "attention", "deep learning", "nlp", "llm", "paper-walkthrough"]
---

In 2017, a team at Google published a paper that would fundamentally reshape the landscape of machine learning. "[Attention Is All You Need](https://arxiv.org/abs/1706.03762)" by Vaswani et al. introduced the Transformer architecture—a bold departure from the recurrent and convolutional approaches that had dominated sequence modeling for years.

The paper's central thesis was radical: **you don't need recurrence or convolution at all**. Just attention mechanisms and feed-forward networks are sufficient to achieve state-of-the-art results in sequence-to-sequence tasks.

Today, every major language model you interact with—GPT, Claude, BERT, LLaMA, and countless others—is built on the foundation laid by this paper. Understanding the Transformer isn't just academic curiosity; it's essential knowledge for anyone working in modern AI.

This guide will take you from zero to hero, breaking down every component of the Transformer architecture with intuition, mathematics, and practical insights.

---

## 0. Why This Paper Exists (The Big Picture)

### The problem (pre-2017)
Sequence modeling (translation, text, speech) relied on:
- RNNs / LSTMs
- GRUs
- CNNs

These had major limitations:
- Sequential computation (slow training)
- Long-range dependency problems
- Hard to parallelize

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

These come from learned linear projections:
```
Q = X × W_Q
K = X × W_K
V = X × W_V
```

Where `X` is your input embeddings and `W_Q`, `W_K`, `W_V` are learned weight matrices.

**Concrete Example:**
Imagine the sentence: "The cat sat on the mat"

When processing the word "sat":
- Its **Query** asks: "What's doing the sitting? What's being sat on?"
- The word "cat" has a **Key** that says: "I'm an animal/actor"
- The word "mat" has a **Key** that says: "I'm a location/object"
- When the Query matches these Keys, we retrieve their **Values** (rich semantic representations)

The model learns what to look for (Q), what to advertise (K), and what information to pass along (V) through training.

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
One attention mechanism can focus on only one type of relationship. Language is complex—we need to capture multiple types of dependencies simultaneously:
- Syntactic relationships (subject-verb agreement)
- Semantic relationships (what modifies what)
- Long-range dependencies (pronouns to antecedents)
- Positional relationships (next word, previous clause)

A single attention head can't capture all of these at once.

### Solution: Multiple heads
Instead of one attention, use **h parallel attention heads** (typically h=8 or h=16).

The key insight: **Each head can learn to focus on different aspects of the relationships between tokens.**

**Concrete example (h=8 heads):**
- Head 1 → syntactic dependencies (verb finds subject)
- Head 2 → coreference resolution (pronouns find nouns)
- Head 3 → semantic similarity (related concepts)
- Head 4 → positional relationships (adjacent words)
- Head 5 → long-range dependencies
- Head 6-8 → other learned patterns

### The mathematics

```
MultiHead(Q, K, V) = Concat(head₁, head₂, ..., head_h) × W_O

where head_i = Attention(Q×W_Qⁱ, K×W_Kⁱ, V×W_Vⁱ)
```

### Process
1. **Linear projections** → Project Q, K, V into h different subspaces (each of dimension d_k = d_model/h)
2. **Apply attention independently** → Each head computes its own attention
3. **Concatenate outputs** → Combine all head outputs
4. **Final linear projection** → Mix information from all heads with W_O

**Why split into smaller dimensions?**
- With d_model = 512 and h = 8 heads, each head works with d_k = 64 dimensions
- This keeps computational cost similar to single-head attention
- But gives us 8 different "views" of the data

This gives **rich, diverse representations** that capture multiple types of relationships simultaneously.

## 4. Positional Encoding (Where Is Order?)

### The problem
Transformers process all tokens **in parallel**. Unlike RNNs which process sequentially, the Transformer has:
- No built-in notion of order
- No way to distinguish position 1 from position 100

Consider: "The dog bit the man" vs "The man bit the dog"
- Same words, completely different meaning
- Order matters!

### The solution
**Add positional encodings** to the token embeddings before feeding them into the model.

```
Input = Token_Embedding + Positional_Encoding
```

This way, the model gets both:
1. **What** the token is (from embedding)
2. **Where** it is in the sequence (from positional encoding)

### Sinusoidal encodings (the paper's approach)

The paper uses **deterministic sinusoidal functions:**

```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

Where:
- `pos` = position in the sequence (0, 1, 2, ...)
- `i` = dimension index (0 to d_model/2)
- Even dimensions use sine, odd dimensions use cosine

### Why sinusoidal?

**1. Continuous and smooth**
- No discrete jumps between positions
- Smooth gradients for learning

**2. Generalizes to any sequence length**
- Not limited by training sequence lengths
- Can extrapolate to longer sequences

**3. Relative positions can be expressed linearly**
- `PE(pos + k)` can be written as a linear function of `PE(pos)`
- Allows the model to learn relative positions easily
- Mathematical property: sin(a + b) can be decomposed using sin(a) and cos(a)

**4. Different frequencies for different dimensions**
- Low dimensions → high frequency (capture fine-grained position info)
- High dimensions → low frequency (capture coarse-grained position info)
- Creates a unique "fingerprint" for each position

### Visualization intuition
Think of it like a binary counter, but with smooth sine/cosine waves instead of discrete bits. Each dimension oscillates at a different frequency, creating a unique pattern for each position.

### Modern alternatives
While the paper used sinusoidal encodings, modern models often use:
- **Learned positional embeddings** (BERT, GPT-2) → treat positions as learnable parameters
- **Rotary Position Embeddings (RoPE)** (LLaMA, GPT-NeoX) → rotate Q and K by position
- **ALiBi** (BLOOM) → add bias to attention scores based on distance

But sinusoidal encodings remain elegant and effective for many applications.

## 5. The Transformer Encoder (Stacked Intelligence)

### Encoder responsibilities
The encoder's job is to:
1. **Read the input sequence** (e.g., "The cat sat on the mat")
2. **Produce rich contextual representations** for each token
3. **Pass these representations** to the decoder (in encoder-decoder models)

In the original paper, encoders had **N = 6 identical layers** stacked on top of each other.

### Encoder layer structure
Each of the 6 layers contains two sub-layers:

#### Sub-layer 1: Multi-Head Self-Attention
Allows each token to attend to all other tokens in the input sequence.
- "Self" means attending to the same sequence (not decoder or external)
- Captures relationships between words

#### Sub-layer 2: Feed-Forward Network (FFN)
Applies the same feed-forward network to each token independently:

```
FFN(x) = max(0, xW₁ + b₁)W₂ + b₂
```

Where:
- `W₁`: Projects from d_model (512) to d_ff (2048) — expansion
- `ReLU`: Adds non-linearity
- `W₂`: Projects back from d_ff (2048) to d_model (512) — compression

Think of it as:
> "Token-wise non-linear reasoning and feature transformation"

**Why expand to 2048 then compress back to 512?**
- The expansion creates a higher-dimensional space for learning complex patterns
- The compression forces the model to extract the most important features
- Similar to a bottleneck architecture

### Critical architecture details

#### Residual connections (skip connections)
```
output = LayerNorm(x + Sublayer(x))
```

Instead of just `Sublayer(x)`, we add the input `x` back.

**Why?**
- **Gradient flow:** Allows gradients to flow directly backward through the network
- **Identity mapping:** The network can learn to do nothing if that's optimal
- **Prevents degradation:** Deep networks can train without losing performance

#### Layer normalization
Normalizes the features across the embedding dimension for each token:

```
LayerNorm(x) = γ × (x - μ) / σ + β
```

**Why?**
- **Stabilizes training:** Prevents activations from growing too large or small
- **Accelerates convergence:** More consistent gradient magnitudes
- **Enables deeper models:** Critical for stacking many layers

### The full encoder layer formula
```
# Sub-layer 1: Self-Attention
x' = LayerNorm(x + MultiHeadAttention(x, x, x))

# Sub-layer 2: Feed-Forward
output = LayerNorm(x' + FFN(x'))
```

### Why stack 6 layers?
Each layer adds another level of abstraction:
- **Layer 1:** Basic token relationships
- **Layer 2-3:** Syntactic patterns emerge
- **Layer 4-5:** Semantic understanding
- **Layer 6:** High-level abstract representations

The stacking allows the model to build increasingly sophisticated representations.

## 6. The Transformer Decoder (Controlled Generation)

### Decoder's job
The decoder generates the output sequence **one token at a time** (autoregressively), while:
1. **Attending to previously generated tokens** (via masked self-attention)
2. **Attending to the encoder output** (via encoder-decoder attention)
3. **Predicting the next token** at each step

Like the encoder, the decoder has **N = 6 identical layers** stacked on top of each other.

### Decoder layer structure
Each decoder layer has **three sub-layers** (vs. two in the encoder):

#### Sub-layer 1: Masked Self-Attention
Allows each position to attend to all **previous positions** in the output sequence.

**The mask is crucial:** During generation, we can only use tokens that have already been generated.

```
When generating position 3:
Can attend to positions 0, 1, 2
Cannot attend to positions 3, 4, 5, ...
```

#### Sub-layer 2: Encoder-Decoder Attention (Cross-Attention)
Allows decoder to attend to **encoder outputs**.
- **Q** comes from the decoder (current state)
- **K, V** come from the encoder output (source sentence)

This is how the model "looks at" the input while generating output.

#### Sub-layer 3: Feed-Forward Network
Same as in the encoder—token-wise transformation.

### Masked attention (crucial detail)

The mask prevents the model from "cheating" by looking at future tokens during training.

**Implementation:**
```
# In attention scores before softmax
scores[i, j] = -inf if j > i else QK^T / √d_k

# After softmax
attention_weights[i, j] = 0 if j > i
```

**Why is this necessary?**

During **training:**
- We have the full target sequence available
- Without masking, the model would just copy from the target
- The mask simulates the real generation scenario

During **inference:**
- We generate one token at a time anyway
- The mask isn't needed but doesn't hurt

**Example:**
```
Target: "Le chat est noir"
Position 2 ("est"):
  Can see: "Le", "chat"
  Cannot see: "noir"
```

This enforces **autoregressive generation**: each token depends only on previous tokens.

### The full decoder layer formula
```
# Sub-layer 1: Masked Self-Attention
x' = LayerNorm(x + MaskedMultiHeadAttention(x, x, x))

# Sub-layer 2: Encoder-Decoder Attention
x'' = LayerNorm(x' + MultiHeadAttention(x', encoder_output, encoder_output))

# Sub-layer 3: Feed-Forward
output = LayerNorm(x'' + FFN(x''))
```

Note: All three sub-layers have residual connections and layer normalization.

## 7. Encoder–Decoder Attention (Translation Bridge)

Encoder-decoder attention (also called **cross-attention**) is the mechanism that connects the encoder and decoder, allowing the decoder to access information from the input sequence while generating output.

### How it works

**Key asymmetry:**
- **Q (Query):** Comes from the decoder's current state
- **K (Key), V (Value):** Come from the encoder's output

```
CrossAttention(decoder_state, encoder_output):
  Q = decoder_state × W_Q
  K = encoder_output × W_K
  V = encoder_output × W_V

  return Attention(Q, K, V)
```

### Concrete example: Machine Translation

**Task:** Translate "The cat sat" → "Le chat s'est assis"

When generating the French word "chat":
1. **Decoder state** (generating position 1) creates a **Query**: "What should I generate now?"
2. This Query attends to **encoder outputs** (all English words)
3. The attention mechanism finds that "cat" is most relevant
4. The Value from "cat" flows into the decoder
5. Decoder generates "chat"

**Attention weights might look like:**
```
Generating "Le"   → Attends to: "The" (0.9), "cat" (0.1)
Generating "chat" → Attends to: "cat" (0.95), "The" (0.05)
Generating "assis"→ Attends to: "sat" (0.9), "cat" (0.1)
```

### Why this matters

This mechanism allows the model to:
1. **Align source and target:** Learn which input words correspond to which output words
2. **Dynamic attention:** Different output positions attend to different input positions
3. **Soft alignment:** Unlike hard alignment, uses weighted combinations

> "While generating word i, look at relevant input words."

This is how **translation alignment** emerges naturally without explicit supervision.

### The magic
The model **learns alignment automatically** through backpropagation. No need to manually specify that "chat" should align with "cat"—the attention mechanism discovers this during training.

## 8. Training Objective

### Task
The original paper focused on **machine translation** tasks:
- English-to-German (WMT 2014)
- English-to-French (WMT 2014)

But the Transformer architecture generalizes to any sequence-to-sequence task.

### Loss function
**Cross-entropy loss** over next-token prediction:

```
Loss = -Σ log P(y_t | y_<t, x)
```

Where:
- `y_t` = target token at position t
- `y_<t` = all previous target tokens
- `x` = source sequence
- `P(y_t | ...)` = predicted probability from the model

The model outputs a probability distribution over the vocabulary for each position, and we maximize the probability of the correct token.

### Teacher forcing (during training)

**Key training technique:**
- Decoder receives **ground-truth previous tokens** as input
- NOT the model's own predictions

**Example:**
```
Target: "Le chat est noir"

Generating "est":
  Without teacher forcing: Use model's prediction for "chat" (might be wrong)
  With teacher forcing: Use ground-truth "chat" (always correct)
```

**Why teacher forcing?**
1. **Faster training:** Provides correct context at each step
2. **Stable learning:** Prevents compounding errors
3. **Parallel training:** Can compute all positions simultaneously

**The tradeoff:**
- **Training:** Use ground-truth tokens (fast, stable)
- **Inference:** Use model's own predictions (slower, but necessary)

This gap between training and inference is called **exposure bias**, but it works well in practice.

## 9. Optimization Tricks (Why It Actually Works)

The Transformer wouldn't work without these crucial training techniques:

### 1. Adam optimizer with warmup schedule

The paper uses **Adam optimizer** with a custom learning rate schedule:

```
lr = d_model^(-0.5) × min(step^(-0.5), step × warmup_steps^(-1.5))
```

This creates a schedule with two phases:

**Phase 1: Warmup (first 4000 steps)**
- Learning rate **increases linearly** from 0
- Formula: `lr ∝ step`

**Phase 2: Decay (after 4000 steps)**
- Learning rate **decreases** as inverse square root of steps
- Formula: `lr ∝ step^(-0.5)`

**Why this schedule?**
1. **Warmup prevents early divergence:**
   - Large models with random initialization are unstable
   - Starting with low LR allows the model to "settle in"
   - Gradients early in training can be very large

2. **Decay enables convergence:**
   - As training progresses, smaller updates are needed
   - Helps find better local minima
   - Reduces oscillation around the optimum

**Typical parameters:**
- `d_model = 512` (base model) or `1024` (big model)
- `warmup_steps = 4000`
- `β₁ = 0.9, β₂ = 0.98, ε = 10^(-9)` (Adam parameters)

### 2. Label smoothing (ε = 0.1)

Instead of hard targets `[0, 0, 1, 0]`, use soft targets `[0.025, 0.025, 0.925, 0.025]`.

**Formula:**
```
y_smooth = (1 - ε) × y_true + ε / vocab_size
```

**Why label smoothing?**
1. **Prevents overconfidence:** Model can't predict 100% probability for any token
2. **Better calibration:** Predicted probabilities better match true likelihoods
3. **Improves generalization:** Reduces overfitting to training data
4. **Hurts perplexity but helps BLEU:** Slightly worse train metrics but better actual translations

**Example (vocab_size = 4, ε = 0.1):**
```
Hard target:  [0.0,  0.0,  1.0,  0.0]
Soft target:  [0.025, 0.025, 0.925, 0.025]
```

### 3. Dropout (rate = 0.1)

Applied to:
- Attention weights
- Output of each sub-layer (before residual addition)
- Positional encodings + embeddings

**Why dropout?**
- Prevents overfitting
- Forces redundancy in representations
- Acts as ensemble of many models

### 4. Gradient clipping (not in paper but common)

Many implementations add gradient clipping to prevent exploding gradients during training spikes.

## 10. Results & Why They Mattered

### Benchmark results (WMT 2014)

**English-to-German translation:**
- **Transformer (big):** 28.4 BLEU
- Previous best (ensemble): 28.4 BLEU
- **Transformer (base):** 27.3 BLEU
- Training cost: **1/4 of previous models**

**English-to-French translation:**
- **Transformer (big):** 41.8 BLEU (new state-of-the-art)
- Previous best: 41.0 BLEU
- Training time: **3.5 days on 8 GPUs** (vs. weeks for RNN models)

### Why these results were revolutionary

#### 1. Quality: State-of-the-art performance
The Transformer matched or exceeded the best RNN/CNN models on established benchmarks.

#### 2. Speed: Parallelization wins
**RNN problem:**
```
Token 1 → Token 2 → Token 3 → Token 4
(sequential, can't parallelize)
```

**Transformer solution:**
```
Token 1
Token 2  → All computed in parallel!
Token 3
Token 4
```

**Training time comparison:**
- LSTM: ~12 days on 96 GPUs
- Transformer base: ~12 hours on 8 P100 GPUs
- Transformer big: ~3.5 days on 8 P100 GPUs

This was a **100x+ speedup** in wall-clock time.

#### 3. Scaling: Bigger models → Better results
Unlike RNNs which struggled to scale, Transformers showed clear improvements with size:

**Base model:**
- N = 6 layers
- d_model = 512
- h = 8 heads
- Parameters: ~65M
- BLEU: 27.3 (EN-DE)

**Big model:**
- N = 6 layers
- d_model = 1024
- h = 16 heads
- Parameters: ~213M
- BLEU: 28.4 (EN-DE)

This scaling property would later enable GPT-3 (175B), GPT-4, and beyond.

### Historical impact

This paper didn't just improve translation—it **changed the entire field of deep learning**.

#### Immediate impact (2017-2018)
- **BERT (2018):** Transformer encoder for language understanding
- **GPT (2018):** Transformer decoder for language generation
- Transformers replaced RNNs/LSTMs in most NLP tasks

#### Medium-term impact (2019-2021)
- **GPT-2, GPT-3:** Showed massive scaling potential
- **T5, BART:** Unified text-to-text frameworks
- **Vision Transformers (ViT):** Extended beyond NLP to computer vision
- **AlphaFold2:** Applied attention to protein folding

#### Long-term impact (2022-present)
- **ChatGPT, Claude, LLaMA:** Modern LLMs all use Transformers
- **Multimodal models:** CLIP, DALL-E, GPT-4
- **Code generation:** Codex, GitHub Copilot
- **Basically everything:** If it's doing AI in 2024, it's probably using Transformers

### Why it worked when RNNs failed

| Aspect | RNNs/LSTMs | Transformers |
|--------|-----------|--------------|
| **Parallelization** | Sequential | Fully parallel |
| **Long-range dependencies** | Vanishing gradients | Direct connections |
| **Training speed** | Slow (weeks) | Fast (hours/days) |
| **Scaling** | Diminishing returns | Clear improvements |
| **Architecture complexity** | Many variants | Simple, universal |

The key insight: **Attention is all you need.** No recurrence, no convolution, just attention mechanisms.

---

## Summary: The Big Picture

Let's recap the entire Transformer architecture:

### The complete flow (Encoder-Decoder)

**Input Processing:**
1. Tokenize input text
2. Convert to embeddings
3. Add positional encodings
4. Apply dropout

**Encoder (6 layers):**
```
For each layer:
  1. Multi-head self-attention
     → Tokens attend to each other
  2. Add & Normalize (residual + LayerNorm)
  3. Feed-forward network
     → Token-wise transformation
  4. Add & Normalize
```

**Decoder (6 layers):**
```
For each layer:
  1. Masked multi-head self-attention
     → Tokens attend to previous tokens only
  2. Add & Normalize
  3. Cross-attention to encoder output
     → Attend to input sequence
  4. Add & Normalize
  5. Feed-forward network
  6. Add & Normalize
```

**Output:**
1. Linear projection to vocabulary size
2. Softmax to get probabilities
3. Sample or take argmax

### Key innovations

1. **Self-Attention:** Tokens directly attend to each other (no recurrence)
2. **Multi-Head Attention:** Learn multiple types of relationships simultaneously
3. **Positional Encoding:** Inject order information without recurrence
4. **Residual + LayerNorm:** Enable deep networks to train stably
5. **Parallelization:** Process entire sequences at once

### Why it matters

The Transformer proved that:
- Attention alone is sufficient for sequence modeling
- Parallelization enables massive scaling
- Simple, universal architecture works across domains
- Bigger models consistently improve performance

This foundation enabled the AI revolution we're experiencing today.

---

## Final Chapter — How to Truly Master This Paper

### Step-by-Step Learning Path

#### Step 1 — Build intuition (1-2 days)
- Read this guide completely
- Watch Jay Alammar's illustrated guide
- Visualize attention matrices with small examples
- Understand **why** attention works better than RNNs

**Key question to answer:** Why does self-attention solve the long-range dependency problem?

#### Step 2 — Master the mathematics (2-3 days)
- Re-derive the attention formula by hand
- Understand all matrix dimensions (Q, K, V shapes)
- Work through a concrete example with real numbers
- Calculate attention weights manually for a 3-token sentence

**Exercise:** Compute attention weights for "The cat sat" by hand.

#### Step 3 — Code from scratch (1-2 weeks)
Don't just copy code—implement each component yourself:

**Week 1: Core components**
1. Scaled dot-product attention
2. Multi-head attention
3. Position-wise feed-forward network
4. Positional encoding
5. Layer normalization
6. Residual connections

**Week 2: Full Transformer**
7. Encoder layer
8. Decoder layer
9. Full Transformer (encoder + decoder)
10. Training loop with teacher forcing

**Use PyTorch or JAX.** Start simple, add complexity gradually.

**Debugging tip:** Print shapes at every step. Most bugs are shape mismatches.

#### Step 4 — Study variants and extensions (ongoing)
Once you understand the base architecture:

**Encoder-only models:**
- **BERT** (masked language modeling)
- **RoBERTa** (improved BERT)
- Use case: Classification, embeddings, understanding

**Decoder-only models:**
- **GPT** (autoregressive language modeling)
- **GPT-2, GPT-3, GPT-4** (scaled versions)
- **LLaMA, Mistral** (open alternatives)
- Use case: Generation, chat, completion

**Encoder-decoder models:**
- **T5** (text-to-text framework)
- **BART** (denoising autoencoder)
- Use case: Translation, summarization, question-answering

**Beyond NLP:**
- **Vision Transformer (ViT):** Images as sequences of patches
- **CLIP:** Joint vision-language models
- **Whisper:** Speech recognition

#### Step 5 — Dive deeper into optimizations (advanced)
- **Efficient attention:** Linear attention, FlashAttention, sparse attention
- **Position embeddings:** RoPE, ALiBi, learned embeddings
- **Scaling laws:** How performance scales with model size, data, compute
- **Training stability:** Mixed precision, gradient checkpointing
- **Inference optimization:** KV-caching, quantization, distillation

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

---

## Quick Reference: Key Concepts

### Architecture parameters (base model)
- **d_model** = 512 (embedding dimension)
- **d_ff** = 2048 (feed-forward inner dimension)
- **h** = 8 (number of attention heads)
- **d_k** = d_v = 64 (dimension per head = 512/8)
- **N** = 6 (number of encoder/decoder layers)
- **Vocabulary size** = ~37K (BPE tokens)

### Key formulas

**Attention:**
```
Attention(Q, K, V) = softmax(QK^T / √d_k) × V
```

**Multi-Head Attention:**
```
MultiHead(Q, K, V) = Concat(head₁, ..., head_h) × W_O
where head_i = Attention(QW_Qⁱ, KW_Kⁱ, VW_Vⁱ)
```

**Positional Encoding:**
```
PE(pos, 2i)   = sin(pos / 10000^(2i/d_model))
PE(pos, 2i+1) = cos(pos / 10000^(2i/d_model))
```

**Feed-Forward:**
```
FFN(x) = max(0, xW₁ + b₁)W₂ + b₂
```

**Layer with Residual:**
```
output = LayerNorm(x + Sublayer(x))
```

### Glossary

- **Self-Attention:** Attention where Q, K, V all come from the same sequence
- **Cross-Attention:** Attention where Q comes from decoder, K/V from encoder
- **Masked Attention:** Attention that prevents looking at future tokens
- **Teacher Forcing:** Using ground-truth tokens during training instead of predictions
- **Autoregressive:** Generating one token at a time, each conditioned on previous tokens
- **BLEU Score:** Metric for translation quality (higher is better)
- **Warmup Steps:** Initial training period with increasing learning rate
- **Label Smoothing:** Softening hard target labels to improve generalization
- **Residual Connection:** Adding input directly to output (x + f(x))
- **Layer Normalization:** Normalizing activations across features

### Common dimensions

For a batch of sequences with `batch_size = B`, `sequence_length = L`:

```
Input embeddings:         [B, L, d_model]
Queries/Keys/Values:      [B, L, d_model]
After split to heads:     [B, h, L, d_k]
Attention scores:         [B, h, L, L]
Attention output:         [B, h, L, d_k]
After concat:             [B, L, d_model]
FFN intermediate:         [B, L, d_ff]
FFN output:               [B, L, d_model]
```

Understanding these shapes is crucial for implementation!