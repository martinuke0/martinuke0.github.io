---
title: "Why Quantization Works: The Mathematics That Makes LLMs 4x Smaller"
date: "2026-09-05T18:59:05.545"
draft: false
tags: ["quantization", "llm-inference", "machine-learning", "model-compression", "gpu-optimization"]
description: "Why quantization compresses LLMs to a fraction of their size with minimal accuracy loss — covering uniform, affine, and GPTQ methods."
summary: "Quantization shrinks 70B-parameter models from 140GB to 35GB without retraining. Here is the math, the failure modes, and why it works in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-why-quantization-works-the-mathematics-that-makes-llms-4x-smaller.svg"
  alt: "Abstract visualization of a tensor grid being mapped from float32 values into discrete quantization bins."
  caption: ""
  relative: false
---

> **TL;DR** — Quantization works because neural network weights are not uniformly distributed: most values cluster near zero, and a small tail of large magnitudes carries most of the information. By exploiting that distribution with affine or k-means-based mappings, we can represent each weight in 4 bits instead of 16, cutting Llama-70B from 140GB to ~35GB while losing under 1% of benchmark accuracy.

## The 140GB Problem

A 70-billion-parameter LLM in `float16` weighs about 140GB. You cannot fit it on a single 96GB H100, you cannot load it on any consumer GPU, and the cost of serving it is dominated by memory bandwidth, not arithmetic. Yet production systems like vLLM and TensorRT-LLM routinely run these models on hardware that mathematically should not be able to hold them.

The trick is quantization: representing each weight and activation in fewer bits. After 4-bit quantization, that same Llama-70B shrinks to roughly 35GB and fits comfortably on one H100, with throughput gains of 2–3x because every memory access now transfers half (or a quarter) of the bytes.

But this raises the obvious question: why does this *work*? If we are throwing away 75% of the bits, why does the model still produce coherent text?

The answer lives in three places: the empirical distribution of neural network weights, the geometry of the matrix multiplications those weights participate in, and a clever trick called calibration that lets us choose where to lose precision.

## A Concrete Example: Llama-3-70B at 4 Bits

Before we dive into math, let us anchor on a real system. When Meta released [Llama-3](https://github.com/meta-llama/llama3), the community immediately asked how to run the 70B variant on consumer hardware. The answer that emerged was a stack:

1. Start from the official `safetensors` weights in BF16.
2. Apply GPTQ to the linear layers, computing per-channel scales and zero-points from a small calibration set.
3. Store the quantized weights in a packed format like `int4` with grouped scales.
4. At inference time, dequantize on-the-fly into BF16 just before each `matmul`.

The result, demonstrated in projects like [AutoGPTQ](https://github.com/AutoGPTQ/AutoGPTQ) and llama.cpp's [GGUF format](https://github.com/ggerganov/llama.cpp), is a model that scores within 1–2 percentage points of the BF16 original on MMLU while occupying roughly a quarter of the memory.

The same model, same architecture, same training run — just fewer bits per number. The structure of the weights is doing all the heavy lifting.

## What Quantization Actually Does

At its core, quantization is a mapping from a continuous set of values (the reals) to a discrete set (the integers we can store). For a `float16` tensor $W$, we want to produce an `int4` tensor $W_q$ plus some metadata $s, z$ such that:

$$\hat{W} = s \cdot (W_q - z)$$

is a good approximation of $W$. The dequantized $\hat{W}$ is what actually flows through the matrix multiplication.

Here $s$ is a **scale**, $z$ is a **zero-point**, and $W_q$ contains one signed 4-bit integer per weight. This particular form is called **affine quantization** and is the basis of most modern schemes, including [TensorRT's INT8 engine](https://docs.nvidia.com/deeplearning/tensorrt/) and ONNX Runtime's quantization tools.

The mapping for a single weight $w$ looks like:

$$w_q = \text{clamp}\left(\text{round}\left(\frac{w}{s} + z\right), -8, 7\right)$$

and is inverted by the formula above. The challenge is choosing $s$ and $z$ so the rounding error $\hat{W} - W$ is minimized under some norm.

### Why 4-bit is the sweet spot

The error from quantization is approximately the product of two things: the spacing between representable values, and the number of values we have to represent. Doubling the number of bits halves the spacing, and for Gaussian-ish distributions, total quantization error drops roughly like $2^{-b}$ where $b$ is the number of bits.

In practice, the curve looks like this:

| Bits | Llama-70B size | Relative MMLU |
|------|----------------|---------------|
| 16 (BF16) | 140 GB | 100% (baseline) |
| 8 (INT8) | 70 GB | ~99.5% |
| 6 | 52 GB | ~99% |
| 4 (INT4) | 38 GB | ~97–98% |
| 3 | 30 GB | ~90–94% |
| 2 | 23 GB | catastrophic |

Below 4 bits, the discrete grid becomes so coarse that the rounding error starts dominating the signal. Above 8 bits, the memory savings become uninteresting. The "4-bit valley" is where most production work lives today, and the explosion of formats — AWQ, GPTQ, EXL2, GGUF Q4_K_M — reflects the engineering effort to find the best cell in that valley.

## Why Uniform Quantization Hurts

The simplest choice is **uniform (symmetric) quantization**: set $z = 0$ and choose a single scale $s$ that maps the weight range $[-\max|W|, \max|W|]$ linearly into $[-7, 7]$ (for INT4 with signed representation).

This works poorly for one reason: transformer weights are not symmetric. Their histograms look like sharp peaks around zero with long tails — a Laplacian or roughly Gaussian distribution rather than a uniform one. If you pick $s$ to cover the largest outlier in a row, you waste almost all of your 16 representable levels on values that almost never occur.

You can see this directly by inspecting any modern LLM:

```python
import torch
from safetensors.torch import load_file

w = load_file("llama-3-70b.safetensors")["model.layers.0.self_attn.q_proj.weight"]
print(w.dtype, w.shape)              # torch.bfloat16, torch.Size([8192, 8192])
print(w.float().abs().mean().item()) # ~0.02
print(w.float().abs().max().item())  # ~0.8 — outliers dominate the range
```

The mean absolute weight is 0.02 while the max is 0.8 — a 40x ratio. A uniform INT4 grid sized for the max puts 95% of its bins on values that occur in 5% of weights. Most weights get rounded to $-1$, $0$, or $1$ and lose their relative magnitudes.

This is the failure mode that makes naive quantization catastrophic for LLMs. The fix is to allocate the grid non-uniformly, which is exactly what the smarter schemes do.

## Per-Channel and Grouped Scales

The first major improvement is to compute a separate scale (and zero-point) per output channel of the weight matrix, rather than one for the entire tensor. This is called **per-channel quantization**, and it is the default in TensorRT-LLM.

The intuition: in a transformer, different output channels of $W_q$ or $W_k$ project the input into different "directions." Some of these directions have small weight magnitudes, others have large ones. Sharing a single scale across all channels forces the small-magnitude channels to round to near-zero. With per-channel scales, each channel gets its own dynamic range.

Grouped quantization extends this further: instead of one scale per channel (which for an 8192×8192 matrix means 8192 scale values, ~2% overhead), we partition each row into groups of 32 or 128 weights and compute a scale per group. The overhead drops below 1%, and the approximation is nearly as good as per-channel.

The **AWQ** method ([Activation-aware Weight Quantization](https://github.com/mit-han-lab/awq)) takes this idea to its logical conclusion: instead of equalizing scales by weight magnitude, it equalizes them by the **product of weight magnitude and activation magnitude**. The reasoning is that the error introduced by quantization is amplified by the activations that flow through it, so we should protect the 1% of weights that the activations actually visit most heavily.

This is not a theoretical nicety. AWQ consistently outperforms naïve per-channel INT4 on Llama and Qwen benchmarks by 1–3 MMLU points, which is the difference between "usable" and "embarrassing" for a production deployment.

## The Calibration Trick: GPTQ

The methods above are *static* — they choose scales before seeing any data. The next leap comes from **GPTQ** ([Generative Pre-trained Transformer Quantization](https://github.com/IST-DASLab/gptq)), which uses a small calibration dataset to compute the optimal rounding choice for each weight **sequentially**, conditioned on all previous choices.

The math is elegant. GPTQ processes the weight matrix column-by-column (or row-by-row) and, after quantizing each block of weights, uses the **Hessian** of the layer's reconstruction error to decide how to compensate in the not-yet-quantized columns. The compensation is essentially one step of Newton-Raphson on the rounding-error objective.

Pseudocode:

```python
def gptq_quantize(W, H_inv, blocksize=128, bits=4):
    Q = torch.zeros_like(W)
    for i in range(0, W.shape[1], blocksize):
        block = W[:, i:i+blocksize]
        # 1. quantize this block naively
        q_block, scale, zp = affine_quantize(block, bits)
        # 2. compute the rounding error
        err = block - dequantize(q_block, scale, zp)
        # 3. distribute the error across remaining columns
        W[:, i+blocksize:] -= err @ H_inv[i:i+blocksize, i+blocksize:]
        Q[:, i:i+blocksize] = q_block
    return Q
```

The `H_inv` term is the inverse Hessian of the squared reconstruction error with respect to the weights, computed once from a small calibration set (typically 128 sequences from WikiText or C4). The whole process takes minutes on a single GPU for a 70B model.

This explains why GPTQ-style quantization works where naïve methods fail: it is no longer treating each weight independently. A weight that gets rounded poorly can "borrow" precision from neighboring weights that got rounded better, preserving the overall matrix product within each row.

## The Role of Activation Quantization

So far we have only quantized weights. What about the activations (the intermediate tensors flowing through the model)?

Weight-only quantization is the easier problem because the weights are fixed and we have plenty of calibration data. Activations are dynamic — their distribution depends on the input — and they have additional problems like outliers in specific channels (the "outlier feature" phenomenon documented in [SmoothQuant](https://github.com/mit-han-lab/smoothquant)).

Production stacks handle this in different ways:

- **vLLM with AWQ**: weights are INT4, activations stay in BF16. Dequantization happens on-the-fly inside the GEMM kernel, which is fast because it fuses with the matmul.
- **TensorRT-LLM with SmoothQuant**: both weights and activations are INT8. SmoothQuant mathematically "moves" the activation outliers into the weight matrix by dividing activations by a per-channel scale and multiplying weights by the same scale. This makes activations easy to quantize while keeping the matrix product exact.
- **FP8 paths** (Hopper GPUs): both weights and activations in E4M3 or E5M2, which is essentially an 8-bit floating-point format. This is what [NVIDIA's H100 FP8 tensor cores](https://www.nvidia.com/en-us/data-center/h100/) are designed for and is increasingly the default for training as well as inference.

The key insight: activation quantization is fundamentally harder because you cannot "see ahead" to calibrate on the actual data. The state of the art is to either keep activations in higher precision (FP8 or BF16) or to use clever transformations like SmoothQuant that shift the quantization difficulty to the weights, where it is easier to manage.

## Why It Works: The Three Deeper Reasons

Stepping back from the engineering, there are three structural reasons quantization succeeds on neural networks:

**1. Weights are information-redundant.** A 70B-parameter model has far more parameters than it needs to represent the function it has learned. Information-theoretically, the "true" weight tensor lives in a much lower-dimensional manifold. Quantization is a projection onto a coarse discrete set, and as long as that set intersects the manifold (which it does with high probability), we lose very little.

**2. The forward pass is an inner product, which averages out rounding errors.** A matmul computes $\sum_i w_i x_i$. Each $w_i$ is rounded independently, but the sum has a central-limit effect: if rounding errors are zero-mean and uncorrelated, the total error grows like $\sqrt{n}$, while the signal grows like $n$. Signal-to-noise ratio improves with dimension, which is exactly why 4096×4096 and 8192×8192 matrices are far more quantizable than small ones.

**3. Networks are trained to be robust.** During training, SGD visits a wide region of weight space and finds minima that are "flat" — small perturbations of the weights do not change the loss much. Quantization is a deterministic perturbation of bounded size, and flat minima absorb it gracefully. This was formalized in part by the [Quantization Noisy Annealing](https://arxiv.org/abs/2106.07v2) line of work, which shows that training-aware quantization can locate minima specifically resistant to quantization error.

These three reasons together explain why a 70B model with weights quantized to 4 bits (an error budget of roughly 0.05 per weight on average) still produces sensible text: the redundancy is enormous, the matmul averages out the noise, and the loss landscape was already forgiving.

## Patterns in Production

A typical production stack in 2026 looks like this:

1. **Training** happens in BF16 or FP8 on H100s with tensor parallelism.
2. **Export** writes BF16 safetensors. Optionally, training-aware quantization (like [LLM.int8()](https://github.com/timdettmers/bitsandbytes) or [QLoRA](https://github.com/artidoro/qlora)) is applied during or after training.
3. **Serving** uses a quantization-aware inference engine: vLLM, TensorRT-LLM, or llama.cpp. The engine loads INT4 weights with per-group scales, dequantizes on-the-fly to BF16/FP16 inside fused GEMM kernels, and keeps activations in FP8 or BF16.
4. **KV cache** is often kept in FP8 or INT8 even when weights are INT4, because the cache is the memory bottleneck at long contexts.

The performance wins compound. A single H100 running AWQ-INT4 Llama-70B serves roughly 2–3x the tokens-per-second of the BF16 version, both because memory bandwidth is the bottleneck (so fewer bytes = faster) and because the kernels are smaller and fit better in cache.

## Key Takeaways

- **Quantization works because transformer weights are highly non-uniform**, with most values near zero and a sparse set of large outliers. Allocating grid points proportionally to value density gives 4-bit precision a fighting chance.
- **Per-channel and grouped scales** are essential. A single tensor-wide scale throws away 90% of the dynamic range on near-zero weights.
- **Calibration-based methods like GPTQ** go further by computing each weight's rounding choice conditionally on the rest of the matrix, using the Hessian of the reconstruction error. This converts independent rounding errors into correlated, near-cancelling ones.
- **Activation quantization is the harder half.** Most production stacks quantize weights aggressively (INT4) but keep activations in higher precision (FP8 or BF16) or apply transformations like SmoothQuant to make them quantizable.
- **The forward pass is robust to noise** because matmul averages out independent rounding errors (signal grows as $n$, noise as $\sqrt{n}$), and because training finds flat minima that absorb bounded perturbations.

## Further Reading

- [GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2210.17323) — the foundational paper on calibration-based weight quantization.
- [AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration](https://arxiv.org/abs/2306.00978) — the method that protects salient weights by activation magnitude.
- [SmoothQuant: Accurate and Efficient Post-Training Quantization for Large Language Models](https://arxiv.org/abs/2211.10438) — the standard approach to making activations quantizable.
- [LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale](https://arxiv.org/abs/2208.07339) — Dettmers et al.'s work on the outlier feature problem in activation quantization.
- [TensorRT-LLM documentation](https://github.com/NVIDIA/TensorRT-LLM) — the production engine reference for quantized inference on NVIDIA GPUs.
- [llama.cpp quantization documentation](https://github.com/ggerganov/llama.cpp/blob/master/examples/quantize/README.md) — the consumer-side reference, with detailed notes on Q4_K_M, Q5_K_M, and the IQ series.