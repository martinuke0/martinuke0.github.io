---
title: "From Neural Networks to LLMs: A Very Detailed, Practical Tutorial"
date: "2026-01-04T08:54:59.617"
draft: false
tags: ["machine learning", "deep learning", "neural networks", "large language models", "tutorial"]
---

Modern large language models (LLMs) like GPT-4, Llama, and Claude look magical—but they are built on concepts that have matured over decades: neural networks, gradient descent, and clever architectural choices.

This tutorial walks you step by step from classic neural networks all the way to LLMs. You’ll see how each idea builds on the previous one, and you’ll get practical code examples along the way.

---

## Table of Contents

1. [Foundations: What Is a Neural Network?](#foundations-what-is-a-neural-network)  
   1.1 [The Perceptron](#the-perceptron)  
   1.2 [From Perceptron to Multi-Layer Networks](#from-perceptron-to-multi-layer-networks)  
   1.3 [Activation Functions](#activation-functions)  

2. [Training Neural Networks: Gradient Descent & Backprop](#training-neural-networks-gradient-descent--backprop)  
   2.1 [Loss Functions](#loss-functions)  
   2.2 [Gradient Descent and SGD](#gradient-descent-and-sgd)  
   2.3 [Backpropagation in Practice](#backpropagation-in-practice)  

3. [From Vectors to Sequences: Working with Text](#from-vectors-to-sequences-working-with-text)  
   3.1 [Tokenization](#tokenization)  
   3.2 [Word Embeddings](#word-embeddings)  
   3.3 [Sequence Models: RNNs and Their Limits](#sequence-models-rnns-and-their-limits)  

4. [The Transformer: The Architecture Behind LLMs](#the-transformer-the-architecture-behind-llms)  
   4.1 [Attention: The Core Idea](#attention-the-core-idea)  
   4.2 [Self-Attention and Multi-Head Attention](#self-attention-and-multi-head-attention)  
   4.3 [Position Encodings](#position-encodings)  
   4.4 [The Transformer Block](#the-transformer-block)  

5. [From Transformers to Language Models](#from-transformers-to-language-models)  
   5.1 [What Is a Language Model?](#what-is-a-language-model)  
   5.2 [Decoder-Only Transformers for LLMs](#decoder-only-transformers-for-llms)  
   5.3 [Training Objective: Next-Token Prediction](#training-objective-next-token-prediction)  

6. [Scaling Up: From Toy Models to LLMs](#scaling-up-from-toy-models-to-llms)  
   6.1 [Model Size, Data, and Compute](#model-size-data-and-compute)  
   6.2 [Training Pipeline Overview](#training-pipeline-overview)  
   6.3 [Fine-Tuning and Instruction Tuning](#fine-tuning-and-instruction-tuning)  

7. [Hands-On Code: Tiny Neural Net to Tiny Transformer](#hands-on-code-tiny-neural-net-to-tiny-transformer)  
   7.1 [A Minimal Feedforward Neural Network (PyTorch)](#a-minimal-feedforward-neural-network-pytorch)  
   7.2 [A Tiny Transformer Block](#a-tiny-transformer-block)  

8. [Where to Go Next: Resources and Links](#where-to-go-next-resources-and-links)  

9. [Conclusion](#conclusion)  

---

## 1. Foundations: What Is a Neural Network?

At its core, a neural network is a function approximator. It takes inputs (numbers), passes them through a series of linear transformations and non-linearities (layers), and outputs predictions (numbers again).

Mathematically, the simplest neural network layer is:

\[
\mathbf{y} = f(W\mathbf{x} + \mathbf{b})
\]

- \( \mathbf{x} \): input vector  
- \( W \): weight matrix  
- \( \mathbf{b} \): bias vector  
- \( f \): non-linear activation function  

You stack layers like this to build deeper networks.

### 1.1 The Perceptron

The perceptron is one of the earliest models of a neuron (1950s–1960s). It models a binary decision:

\[
\hat{y} = \begin{cases}
1 & \text{if } \mathbf{w}^\top \mathbf{x} + b > 0\\
0 & \text{otherwise}
\end{cases}
\]

Where:

- \( \mathbf{x} \) is your feature vector (e.g., pixel values)
- \( \mathbf{w} \) are the learned weights
- \( b \) is a learned bias

> **Limitation:** A single perceptron can only learn linearly separable functions. It cannot represent something as simple as XOR. This limitation motivated multi-layer networks.

### 1.2 From Perceptron to Multi-Layer Networks

The idea is simple: stack neurons into layers.

- **Input layer**: your raw data  
- **Hidden layers**: intermediate transformations  
- **Output layer**: final predictions  

For a network with one hidden layer:

\[
\begin{align}
\mathbf{h} &= f(W_1 \mathbf{x} + \mathbf{b}_1) \\
\hat{\mathbf{y}} &= g(W_2 \mathbf{h} + \mathbf{b}_2)
\end{align}
\]

- \( f \) and \( g \) are activation functions  
- With enough hidden units, this network can approximate any continuous function on a compact domain (Universal Approximation Theorem)

### 1.3 Activation Functions

Without activation functions, stacking linear layers is equivalent to a single linear layer. Non-linear activations give neural networks their expressive power.

Common activations:

- **Sigmoid**:  
  \[
  \sigma(x) = \frac{1}{1 + e^{-x}}
  \]  
  Outputs in (0, 1). Used historically; now mostly for binary outputs.

- **Tanh**:  
  \[
  \tanh(x) = \frac{e^{x} - e^{-x}}{e^{x} + e^{-x}}
  \]  
  Outputs in (-1, 1). Still used sometimes.

- **ReLU (Rectified Linear Unit)**:  
  \[
  \text{ReLU}(x) = \max(0, x)
  \]  
  Simple, effective, and widely used.

- **GELU (Gaussian Error Linear Unit)**: popular in Transformers and LLMs:  
  \[
  \text{GELU}(x) \approx 0.5x\left(1 + \tanh\left(\sqrt{\frac{2}{\pi}}(x + 0.044715x^3)\right)\right)
  \]

---

## 2. Training Neural Networks: Gradient Descent & Backprop

Once you define a neural network architecture, you need to **train** it: adjust its weights such that predictions match desired outputs.

This is done by:

1. Defining a **loss function**  
2. Using **gradient descent** to minimize the loss  
3. Computing gradients via **backpropagation**

### 2.1 Loss Functions

A loss function measures how bad the model’s predictions are.

- **Mean Squared Error (MSE)** (regression):

  \[
  \mathcal{L} = \frac{1}{N}\sum_{i=1}^N (y_i - \hat{y}_i)^2
  \]

- **Cross-Entropy Loss** (classification):

  For a single example with true class distribution \( \mathbf{y} \) (one-hot) and predicted probabilities \( \hat{\mathbf{y}} \):

  \[
  \mathcal{L} = -\sum_{c} y_c \log(\hat{y}_c)
  \]

LLMs use cross-entropy over tokens: how well does the model predict the next token?

### 2.2 Gradient Descent and SGD

Given parameters \( \theta \) (all weights and biases) and loss \( \mathcal{L}(\theta) \), gradient descent updates:

\[
\theta \leftarrow \theta - \eta \nabla_\theta \mathcal{L}(\theta)
\]

- \( \eta \): learning rate  
- \( \nabla_\theta \mathcal{L} \): gradient of the loss wrt parameters  

**Stochastic Gradient Descent (SGD)** approximates the gradient using mini-batches instead of all data, making training scalable.

Modern optimizers (e.g., Adam) build on this with adaptive learning rates.

### 2.3 Backpropagation in Practice

Backpropagation is an algorithm to compute gradients efficiently using the chain rule.

The idea:

1. **Forward pass**: compute outputs and loss from inputs  
2. **Backward pass**: propagate gradients from the loss back through each layer  

Frameworks like PyTorch or TensorFlow perform backprop automatically via **autograd**.

---

## 3. From Vectors to Sequences: Working with Text

Neural networks operate on **vectors of numbers**, but text is discrete. We need a way to convert text to numbers and capture structure (sentences, order, meaning).

### 3.1 Tokenization

Tokenization splits text into units (tokens) and maps them to integer IDs.

Common schemes:

- **Word-level**: each word is a token  
  - Simple but leads to huge vocabularies and issues with rare words  

- **Subword-level** (BPE, WordPiece, Unigram):  
  - Tokens are frequently used sequences of characters  
  - Efficient, handles rare words by splitting them  
  - Used by most modern LLMs  

- **Character-level**: each character is a token  
  - Smaller vocab, longer sequences, slower to train  

Example (BPE-like):

- Text: `"transformers"`  
- Possible tokens: `"trans"`, `"form"`, `"ers"`  

### 3.2 Word Embeddings

Once tokens are mapped to IDs, we use an **embedding matrix** to map each ID to a **dense vector**.

\[
\text{embedding}: \{0, 1, \dots, V-1\} \to \mathbb{R}^d
\]

- \( V \): vocabulary size  
- \( d \): embedding dimension  

In code (PyTorch):

```python
import torch
import torch.nn as nn

vocab_size = 10000
embed_dim = 256

embedding = nn.Embedding(vocab_size, embed_dim)

token_ids = torch.tensor([1, 5, 20, 42])  # example token IDs
vectors = embedding(token_ids)            # shape: (4, 256)
```

These embeddings are learned during training and capture semantic relationships (e.g., similar words have similar vectors).

### 3.3 Sequence Models: RNNs and Their Limits

Before Transformers, **Recurrent Neural Networks (RNNs)** and variants like **LSTMs** and **GRUs** were the standard for sequences.

RNN recurrence:

\[
\mathbf{h}_t = f(W_x \mathbf{x}_t + W_h \mathbf{h}_{t-1} + \mathbf{b})
\]

- \( \mathbf{x}_t \): input embedding at time step \( t \)  
- \( \mathbf{h}_t \): hidden state at time step \( t \)  

**Issues with RNNs:**

- Hard to parallelize across sequence positions  
- Struggle with very long dependencies (vanishing/exploding gradients)  
- Training is slower compared to fully parallelizable architectures  

These limitations motivated the search for alternative architectures—leading to the **Transformer**.

---

## 4. The Transformer: The Architecture Behind LLMs

Introduced in the 2017 paper **“Attention Is All You Need”**, the Transformer discarded recurrence and convolutions in favor of **self-attention**.

Key advantages:

- Parallelizable across sequence positions  
- Better modeling of long-range dependencies  
- Scales well with data and compute  

### 4.1 Attention: The Core Idea

Attention mechanisms allow a model to focus on different parts of the input when computing a representation.

For input vectors \( \mathbf{x}_1, ..., \mathbf{x}_n \), attention computes a weighted sum of values based on learned similarity scores between queries and keys.

We typically compute:

- Queries \( Q \)
- Keys \( K \)
- Values \( V \)

Each is a linear projection of the inputs:

\[
Q = XW_Q,\quad K = XW_K,\quad V = XW_V
\]

The **scaled dot-product attention**:

\[
\text{Attention}(Q, K, V) = \text{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right) V
\]

Where \( d_k \) is the dimensionality of keys.

Interpretation:

- Each position’s query compares to all positions’ keys  
- The softmax gives attention weights  
- Weighted sum of values produces a contextual representation

### 4.2 Self-Attention and Multi-Head Attention

**Self-attention** is attention where \( Q, K, V \) all come from the same sequence (e.g., the tokens of a sentence).

**Multi-head attention** uses multiple attention “heads” in parallel:

\[
\text{MultiHead}(Q, K, V) = \text{Concat}(\text{head}_1, \dots, \text{head}_h) W^O
\]

Each head learns different subspaces and relationships (e.g., syntax vs. semantics).

### 4.3 Position Encodings

Transformers process tokens in parallel, so they lack inherent information about order. **Position encodings** inject order information.

Two common kinds:

- **Sinusoidal position encodings** (original Transformer):

  For position \( pos \) and dimension \( i \):

  \[
  \text{PE}_{pos,2i} = \sin\left(\frac{pos}{10000^{2i/d}}\right), \quad
  \text{PE}_{pos,2i+1} = \cos\left(\frac{pos}{10000^{2i/d}}\right)
  \]

- **Learned positional embeddings**: a trainable embedding for each position. Many LLMs use variants like RoPE, ALiBi, etc.

### 4.4 The Transformer Block

A standard Transformer block consists of:

1. **Multi-head self-attention**  
2. **Add & LayerNorm** (residual connection + normalization)  
3. **Feedforward network (MLP)**  
4. **Add & LayerNorm** again  

Diagrammatically:

```text
Input
  │
  ├─► [Multi-Head Self-Attention]
  │         │
  └─(Add)◄─┘
  │
 [LayerNorm]
  │
  ├─► [Feedforward (MLP)]
  │         │
  └─(Add)◄─┘
  │
 [LayerNorm]
  │
 Output
```

This block is repeated many times (e.g., 12, 24, 96 layers) to build deep Transformer models.

---

## 5. From Transformers to Language Models

With an understanding of Transformers, we can now see how they form the backbone of LLMs.

### 5.1 What Is a Language Model?

A **language model** assigns probabilities to sequences of tokens.

Formally, for a token sequence \( x_1, x_2, ..., x_T \):

\[
P(x_1, ..., x_T) = \prod_{t=1}^T P(x_t \mid x_{<t})
\]

LLMs are **autoregressive** language models: they predict the next token given the previous ones.

### 5.2 Decoder-Only Transformers for LLMs

Early Transformers used an encoder-decoder structure for tasks like translation. Many LLMs use a **decoder-only** architecture:

- Input: a sequence of tokens (prompt)  
- Processed through stacked Transformer decoder blocks  
- Output: a probability distribution over the next token at each position  

Key features:

- **Causal (masked) self-attention**: each position can only attend to previous positions (no “peeking into the future”)  
- Large depth (many layers) and width (large embedding dimension)  

### 5.3 Training Objective: Next-Token Prediction

The training objective is typically **cross-entropy loss over the next token**.

Given input sequence tokens \( x_1, ..., x_T \), model outputs a distribution \( p_\theta(x_t \mid x_{<t}) \). The loss is:

\[
\mathcal{L}(\theta) = -\sum_{t=1}^T \log p_\theta(x_t \mid x_{<t})
\]

During training:

1. Take a batch of sequences  
2. Feed them to the model  
3. Predict logits for each token position  
4. Compute cross-entropy loss vs. the shifted sequence (next token)  
5. Backpropagate and update parameters  

At inference time, you **sample tokens sequentially**, feeding previous outputs back into the model.

---

## 6. Scaling Up: From Toy Models to LLMs

The leap from a small Transformer to an LLM is primarily about **scale** and **engineering**, not fundamentally different math.

### 6.1 Model Size, Data, and Compute

Key levers:

- **Model size**: number of parameters (e.g., millions to hundreds of billions)  
- **Data size**: number of tokens (e.g., billions to trillions)  
- **Compute**: GPU/TPU hours used for training  

Empirical work (e.g., OpenAI’s scaling laws) shows that performance improves smoothly as you scale model size, data, and compute in the right proportions.

Trade-offs:

- Bigger models need more data to avoid overfitting  
- More data with too small a model underutilizes data  

### 6.2 Training Pipeline Overview

A large-scale LLM training pipeline typically includes:

1. **Data collection**  
   - Web crawl, books, code, scientific papers, etc.  
   - Deduplication and filtering for quality and safety  

2. **Preprocessing & tokenization**  
   - Clean text (HTML stripping, Unicode normalization)  
   - Train or adopt a tokenizer (e.g., BPE, SentencePiece)  
   - Convert text to token IDs  

3. **Sharding & batching**  
   - Split dataset into chunks for distributed training  
   - Construct batches to maximize hardware utilization  

4. **Model initialization**  
   - Configure architecture (layers, heads, embedding dim, etc.)  
   - Initialize weights (e.g., Xavier, Kaiming, or custom schemes)  

5. **Distributed training**  
   - Data parallelism (different GPUs see different batches)  
   - Model / tensor parallelism (split the model across GPUs)  
   - Pipeline parallelism (split layers across machines)  

6. **Monitoring & evaluation**  
   - Track loss, perplexity, learning rate  
   - Evaluate on benchmarks (e.g., MMLU, code tasks, etc.)  

### 6.3 Fine-Tuning and Instruction Tuning

Once you have a base LLM, you can adapt it:

- **Supervised fine-tuning (SFT)**  
  - Train on curated input-output pairs (e.g., Q&A, instructions, code tasks)  
  - Objective: imitate provided responses  

- **Instruction tuning**  
  - Fine-tune on many examples of “instruction → helpful answer”  
  - Makes models better at following natural-language instructions  

- **Reinforcement Learning from Human Feedback (RLHF)**  
  - Collect human preferences over model outputs  
  - Train a reward model  
  - Use RL (e.g., PPO) to optimize for outputs that humans prefer  

These steps transform a raw LLM into a more **aligned**, **useful**, and **safe** assistant.

---

## 7. Hands-On Code: Tiny Neural Net to Tiny Transformer

This section provides minimal PyTorch examples to connect the concepts with real code. These are educational, not production-ready.

> **Note:** You need Python 3.x and PyTorch installed. See [https://pytorch.org](https://pytorch.org) for installation instructions.

### 7.1 A Minimal Feedforward Neural Network (PyTorch)

We’ll build a tiny MLP to classify 2D points into two classes.

```python
import torch
import torch.nn as nn
import torch.optim as optim

# Generate some toy data: points in 2D, labels 0 or 1
N = 1000
X = torch.randn(N, 2)
y = (X[:, 0] * X[:, 1] > 0).long()  # label 1 if product > 0 else 0

class SimpleMLP(nn.Module):
    def __init__(self, input_dim=2, hidden_dim=16, output_dim=2):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, output_dim)
        )
    
    def forward(self, x):
        return self.net(x)

model = SimpleMLP()
criterion = nn.CrossEntropyLoss()
optimizer = optim.Adam(model.parameters(), lr=1e-2)

for epoch in range(100):
    logits = model(X)            # forward pass
    loss = criterion(logits, y)  # compute loss

    optimizer.zero_grad()
    loss.backward()              # backprop
    optimizer.step()             # update weights

    if (epoch + 1) % 20 == 0:
        pred = logits.argmax(dim=1)
        acc = (pred == y).float().mean().item()
        print(f"Epoch {epoch+1}, Loss: {loss.item():.4f}, Acc: {acc:.3f}")
```

This demonstrates:

- Defining a network as a composition of layers  
- Forward pass, loss computation, backward pass  
- Optimizer step (gradient descent/Adam)

### 7.2 A Tiny Transformer Block

Now we implement a basic Transformer-style block for short token sequences.

```python
import torch
import torch.nn as nn
import math

class TinyTransformerBlock(nn.Module):
    def __init__(self, d_model=128, n_heads=4, d_ff=512):
        super().__init__()
        self.attn = nn.MultiheadAttention(embed_dim=d_model, num_heads=n_heads, batch_first=True)
        self.ln1 = nn.LayerNorm(d_model)
        
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Linear(d_ff, d_model)
        )
        self.ln2 = nn.LayerNorm(d_model)

    def forward(self, x, attn_mask=None):
        # x: (batch, seq_len, d_model)
        attn_output, _ = self.attn(x, x, x, attn_mask=attn_mask)
        x = self.ln1(x + attn_output)   # residual + norm
        ff_output = self.ff(x)
        x = self.ln2(x + ff_output)     # residual + norm
        return x

class TinyLM(nn.Module):
    def __init__(self, vocab_size, d_model=128, n_heads=4, d_ff=512, n_layers=2, max_len=64):
        super().__init__()
        self.token_emb = nn.Embedding(vocab_size, d_model)
        self.pos_emb = nn.Embedding(max_len, d_model)
        
        self.layers = nn.ModuleList([
            TinyTransformerBlock(d_model, n_heads, d_ff)
            for _ in range(n_layers)
        ])
        self.ln_f = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab_size)  # projection to vocab

    def forward(self, input_ids):
        # input_ids: (batch, seq_len)
        batch_size, seq_len = input_ids.size()
        positions = torch.arange(seq_len, device=input_ids.device).unsqueeze(0)
        
        x = self.token_emb(input_ids) + self.pos_emb(positions)
        
        # Causal mask: prevent attending to future tokens
        # Shape: (batch * num_heads, seq_len, seq_len) or (seq_len, seq_len) depending on PyTorch version
        mask = torch.triu(torch.ones(seq_len, seq_len, device=input_ids.device), diagonal=1).bool()
        
        for layer in self.layers:
            x = layer(x, attn_mask=mask)
        
        x = self.ln_f(x)
        logits = self.head(x)  # (batch, seq_len, vocab_size)
        return logits

# Example usage:
vocab_size = 1000
model = TinyLM(vocab_size=vocab_size)

batch_size, seq_len = 2, 10
dummy_input = torch.randint(0, vocab_size, (batch_size, seq_len))
logits = model(dummy_input)
print("Logits shape:", logits.shape)  # (2, 10, 1000)
```

This tiny model:

- Uses embeddings for tokens and positions  
- Applies multiple Transformer blocks  
- Produces logits over the vocabulary for each position (for next-token prediction)  

With more layers, larger dimensions, and much more data, this architecture becomes the backbone of LLMs.

---

## 8. Where to Go Next: Resources and Links

This final chapter provides curated resources to deepen your understanding, from fundamentals to advanced LLM engineering.

### 8.1 Foundational Deep Learning

- **Books & Guides**  
  - *Deep Learning* (Goodfellow, Bengio, Courville) – full free PDF:  
    https://www.deeplearningbook.org/  
  - *Dive into Deep Learning* – interactive book with code (PyTorch/MXNet):  
    https://d2l.ai/  

- **Courses**  
  - Andrew Ng’s *Deep Learning Specialization*:  
    https://www.coursera.org/specializations/deep-learning  
  - MIT 6.S191: *Introduction to Deep Learning* (lectures & materials):  
    http://introtodeeplearning.com/  

### 8.2 Neural Networks & Backpropagation

- Michael Nielsen – *Neural Networks and Deep Learning* (excellent visual + math explanations):  
  http://neuralnetworksanddeeplearning.com/  

- Stanford CS231n (especially the lecture notes on backprop and optimization):  
  http://cs231n.stanford.edu/  

### 8.3 NLP & Sequence Modeling

- *Speech and Language Processing* (Jurafsky & Martin) – draft 3rd edition online:  
  https://web.stanford.edu/~jurafsky/slp3/  

- Stanford CS224n: *Natural Language Processing with Deep Learning*:  
  http://web.stanford.edu/class/cs224n/  

### 8.4 Transformers and Attention

- Original Transformer paper: *Attention Is All You Need* (Vaswani et al., 2017):  
  https://arxiv.org/abs/1706.03762  

- Illustrated Transformer (Jay Alammar):  
  http://jalammar.github.io/illustrated-transformer/  

- Annotated Transformer (Harvard NLP, PyTorch):  
  http://nlp.seas.harvard.edu/2018/04/03/attention.html  

### 8.5 Large Language Models

- *Scaling Laws for Neural Language Models* (Kaplan et al., 2020):  
  https://arxiv.org/abs/2001.08361  

- *Language Models are Few-Shot Learners* (GPT-3 paper):  
  https://arxiv.org/abs/2005.14165  

- LLaMA & LLaMA 2 papers (Meta):  
  - LLaMA: https://arxiv.org/abs/2302.13971  
  - LLaMA 2: https://arxiv.org/abs/2307.09288  

- OpenAI Cookbook – practical examples for using and integrating LLMs:  
  https://github.com/openai/openai-cookbook  

### 8.6 Practical Implementation and Libraries

- **PyTorch Documentation**:  
  https://pytorch.org/docs/stable/index.html  

- **Hugging Face Transformers** – ready-to-use LLMs, tokenizers, training utilities:  
  https://github.com/huggingface/transformers  

- **Hugging Face Course** – free, very practical:  
  https://huggingface.co/learn  

- **minGPT** (Andrej Karpathy) – minimal GPT implementation:  
  https://github.com/karpathy/minGPT  

- **nanoGPT** – training and finetuning small GPT models from scratch:  
  https://github.com/karpathy/nanoGPT  

---

## 9. Conclusion

Neural networks and LLMs are not separate worlds; they are points on the same continuum.

You began with:

- The perceptron as a simple linear classifier  
- Multi-layer networks with non-linear activations  
- Gradient descent and backprop as the optimization backbone  

You then moved into:

- How to represent text as sequences of tokens and embeddings  
- RNNs and their limitations for long sequences  
- Transformers and self-attention as a scalable, parallel alternative  

Finally, you connected these concepts to:

- Autoregressive language modeling (next-token prediction)  
- Decoder-only Transformers as the foundation of modern LLMs  
- Scaling laws, training pipelines, and fine-tuning strategies that turn architectures into powerful general-purpose models  

If you work through the linked resources, experiment with tiny models (like the ones in this post), and then explore open-source LLM implementations, you’ll develop a strong, end-to-end understanding of how systems like GPT and Llama are built.

From here, natural next steps include:

- Implementing your own small Transformer from scratch  
- Fine-tuning a pretrained model on a custom dataset using Hugging Face  
- Exploring alignment techniques like RLHF and preference optimization  

With a solid grasp of the fundamentals, you’re well positioned to both **use** and **build** the next generation of language models.