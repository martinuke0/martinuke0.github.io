---
title: "Quantization in Production: Trading Precision for Scale"
date: "2026-09-04T12:39:56.068"
draft: false
tags: ["machine-learning", "quantization", "inference", "performance", "production-engineering"]
description: "A production engineer's guide to quantization: how 4-bit and 8-bit models cut cost and latency without breaking accuracy, with patterns from real deployments."
summary: "Quantization is the single highest-leverage optimization for LLM and vision inference at scale. This post covers the math, the formats, the failure modes, and the patterns shipping teams use to roll out quantized models safely."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-quantization-in-production-trading-precision-for-scale.svg"
  alt: "Binary digits flowing into a neural network diagram representing reduced precision inference."
  caption: ""
  relative: false
---

> **TL;DR** — Quantization maps a model's weights and activations from FP16/FP32 to lower-precision integer or sub-byte formats, typically cutting memory 2–4× and latency 1.5–3× with under 1% accuracy loss on most workloads. The real engineering work is choosing a scheme (PTQ vs QAT, INT8 vs INT4 vs FP8), validating it against your eval set, and rolling it out behind feature flags so you can detect regressions before they hit the P99 bill.

If you've shipped an LLM, a vision model, or even a moderately sized embedding service in the last two years, you've almost certainly looked at quantization. It is the rare ML optimization that delivers a double-digit percentage cost reduction on the same hardware, often without a single line of architecture change. The story sounds too good to be true, and in some edge cases it is — but for the overwhelming majority of inference workloads, quantization is the first thing you should try, not the last.

This post is the writeup I wish I had when I was rolling out INT8 BERT and then INT4 LLMs at scale. I'll cover what quantization actually does at the bit level, the formats you'll encounter, the two main techniques (post-training and quantization-aware training), and the production patterns that separate a smooth rollout from a 3 a.m. incident.

## What Quantization Actually Does

At its core, quantization replaces high-precision floating-point numbers with lower-precision representations. Concretely, you take a tensor of FP32 weights and map each value to one of a much smaller set of representable values — for INT8, that's 256 discrete points; for INT4, just 16.

The mapping is defined by a **scale** (s) and a **zero point** (z), following the affine formula:

`x_q = round(clamp(x / s + z, q_min, q_max))`

To dequantize: `x ≈ s * (x_q - z)`

The scale is typically a per-tensor or per-channel floating-point value, while the zero point is the integer that maps back to 0.0 in the original space. Symmetric quantization drops the zero point by assuming the range is centered on zero, which is faster on hardware but slightly less accurate when weight distributions are skewed — which, as it turns out, they almost always are in transformers.

The reason this works at all is that neural networks are remarkably tolerant of noise. A weight that "should" be 0.1373 can be stored as INT8 bucket 18 representing 0.1406, and the network's output barely moves. This property has been known since the early 1990s and is the foundation of every modern quantization scheme. The [Google quantization whitepaper](https://arxiv.org/abs/1806.08342) is still the cleanest theoretical treatment.

## The Format Zoo: INT8, INT4, FP8, and NF4

Choosing a precision is not just a question of "fewer bits equals more savings." Each format has different hardware support, different accuracy characteristics, and different tooling maturity.

**INT8** is the workhorse. It is supported natively on every modern CPU (via AVX-512 VNNI and ARM dotprod), every NVIDIA GPU since Turing, and every Google TPU. The accuracy hit is almost always negligible — typically under 0.5% on standard benchmarks. If you are starting out, this is where you should start. [ONNX Runtime's quantization guide](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html) is the most pragmatic reference for getting INT8 working on a CPU-serving model.

**INT4** (and sub-4-bit formats) is where the real cost wins live for LLMs. A 70B parameter model at FP16 is ~140 GB; at INT4 it fits in ~40 GB, which means it can sit on a single H100 or two L40S instead of a multi-node tensor-parallel deployment. The catch is that naive INT4 destroys accuracy. You almost always need GPTQ, AWQ, or SmoothQuant-style preprocessing to get acceptable results. The [GPTQ paper](https://arxiv.org/abs/2210.17323) introduced the now-standard approach of using second-order information from the Hessian to compensate for quantization error, and it remains the foundation of most production 4-bit LLM serving stacks.

**FP8** (E4M3 and E5M2) is the newest entrant, formalized in [NVIDIA's H100 architecture](https://www.nvidia.com/en-us/data-center/h100/) and supported natively in the Transformer Engine. FP8 keeps an 8-bit footprint but uses a floating-point rather than integer representation, which preserves dynamic range much better. For training, this is transformative; for inference, it is mostly a transitional format on the way to INT4, with one important exception: the FP8 attention paths in TensorRT-LLM often beat INT8 for very long contexts because they handle outliers in the attention scores more gracefully.

**NF4** (4-bit NormalFloat) is the format [bitsandbytes](https://github.com/TimDettmers/bitsandbytes) introduced for QLoRA-style fine-tuning. It is information-theoretically optimal for normally distributed weights — which transformer weights approximately are — and it has become the de facto format for adapter-based fine-tuning of large models on a single GPU.

The practical takeaway: for **inference**, prefer INT8 if you can, INT4 (via GPTQ or AWQ) if you must, and FP8 if you are on Hopper-class hardware and the workload justifies it. For **fine-tuning**, use NF4 with QLoRA unless you have a good reason not to.

## Post-Training Quantization vs. Quantization-Aware Training

The two high-level techniques differ in *when* you simulate low precision.

**Post-Training Quantization (PTQ)** takes a fully trained model and quantizes it after the fact. The simplest variant, dynamic PTQ, computes scales and zero points on the fly from activation statistics during a calibration pass on a representative dataset. Static PTQ does the same for activations using a small calibration set, then freezes the scales. PTQ is fast — you can quantize a 7B model in minutes — and works well for INT8 on most architectures. It is what you should try first.

PTQ starts to break down at INT4, especially for models that have not been trained with quantization in mind. Outlier features — a handful of activation channels with magnitudes 10–100× larger than the rest — dominate the quantization range and force everything else into a tiny slice of the representable buckets. This is the [SmoothQuant](https://arxiv.org/abs/2211.10438) problem, and the solution is to mathematically migrate that outlier mass from activations to weights (where it can be absorbed into the per-channel scale) before quantizing.

**Quantization-Aware Training (QAT)** simulates quantization noise during training by inserting fake-quantization ops in the forward pass. The model learns to be robust to the rounding error it will see at inference time. QAT is more expensive — you have to fine-tune the model, sometimes for billions of tokens — but it is the only reliable path to INT3 and INT2, and it is increasingly the path to robust INT4 on hard tasks. The [LLM-QAT paper](https://arxiv.org/abs/2305.17888) demonstrated that QAT on a self-generated dataset can recover most of the accuracy loss from aggressive quantization.

A useful mental model: PTQ is to QAT as a recompile is to writing a new algorithm. PTQ is fast and almost free; QAT is a project.

## Patterns in Production: How Teams Actually Roll Out Quantized Models

The interesting engineering work is not the quantization itself — it is the rollout. Here are the patterns I have seen work consistently across teams running quantized LLMs, vision models, and embedding services in production.

### Pattern 1: Quantize the Model Card, Not the Weights

Before you quantize anything, you need an **eval-driven quantization card**: a structured record of which format (INT8, INT4, FP8), which calibration dataset, which evaluation suite, and what accuracy regression you are willing to accept on which tasks. Without this, every rollback conversation will be a rehash of "well, how much accuracy did we actually lose?" The [Hugging Face Optimum documentation](https://huggingface.co/docs/optimum/concept_guides/quantization) walks through how to build one.

A good card specifies, for each task in your eval suite, a regression budget. For a customer support chatbot, a 1% drop in exact-match accuracy on a held-out FAQ set might be unacceptable; a 2% drop in BLEU on a translation task might be fine. The thresholds should be set by the product owner, not the ML engineer, because the engineer is the wrong person to decide what "good enough" means.

### Pattern 2: Shadow Mode Before Switchover

Never roll a quantized model directly to live traffic. The standard pattern is to run the quantized and full-precision models in parallel, send the same inputs to both, log both outputs, and compare — but only *show* the full-precision output to users. After a few million requests, you can analyze the divergence rate, the per-task accuracy, and the latency distribution before cutting over.

This is especially important for INT4 LLMs, where the failure modes are subtle. A model can pass every standard benchmark (MMLU, HumanEval, HellaSwag) and still produce subtly worse outputs on your specific traffic distribution. Shadow mode catches this. The [PyTorch quantization best practices guide](https://pytorch.org/blog/quantization-aware-training/) has good examples of how to instrument this kind of dual-serve comparison.

### Pattern 3: Feature-Flag the Quantized Path

Even after shadow mode, you want a way to route a percentage of traffic to the quantized model. A simple approach is to set a feature flag on a per-user or per-tenant basis, ramp from 1% to 10% to 50% to 100% over days, and watch the P99 latency, error rate, and any task-specific quality metrics at each step.

This is also where you discover the **distribution shift** problem. Your calibration set was probably a sample of traffic from last month; traffic this month might be different. Quantized models are more sensitive to distribution shift than full-precision ones because their decision boundaries are coarser. A 1% regression in eval might be a 5% regression on traffic you did not see during calibration.

### Pattern 4: Watch the Long Tail of the Latency Distribution

Mean latency improvements from quantization are real, but the more interesting number is **P99 and P999**. Quantization reduces the variance of compute time (fewer FLOPs, more predictable memory access patterns) and usually tightens the tail substantially — but only if the kernel implementation is well-tuned. A naive INT8 implementation can actually *worsen* P99 because of dequantization overhead in the wrong place.

The kernel matters as much as the format. [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM) and [vLLM](https://github.com/vllm-project/vllm) have invested heavily in fused INT4 and FP8 kernels, and the difference between their optimized paths and a from-scratch implementation can be 3–5×. If you are quantizing a model for production, you almost certainly want to use one of these serving stacks rather than rolling your own kernel.

## Common Failure Modes

Quantization breaks in predictable ways. Knowing the failure modes in advance saves a lot of debugging time.

**Outlier activations.** The single most common cause of INT4 accuracy collapse. Activations with a few extreme values (often in the attention softmax or early layer norm outputs) force the quantizer to use a coarse scale for the entire tensor. Solutions: SmoothQuant, per-token activation quantization, or QAT.

**Layer sensitivity.** Not all layers quantize equally. In transformers, the softmax and layer-norm layers are notoriously quantization-sensitive, while the FFN gate projections are usually robust. Per-layer mixed precision — quantize the easy layers to INT4 and keep the sensitive ones at INT8 — is one of the highest-leverage techniques. The [LLaMA INT4 study from IST-DASLab](https://arxiv.org/abs/2306.00978) provides a clean methodology for identifying which layers to keep at higher precision.

**Calibration set mismatch.** Your calibration data must be representative of inference traffic. If you calibrate on Wikipedia but serve Reddit, you will be off. This sounds obvious, but I have seen it bite teams multiple times. The fix is to use a sample of real production prompts, properly anonymized, as the calibration set.

**Tokenizer and embedding drift.** Quantizing the LM head and embeddings to very low precision can shift the output distribution of the model in ways that do not show up on perplexity but do show up on downstream tasks. A common pattern is to keep the embedding and unembedding layers at INT8 even when everything else is INT4. This costs a few percent of memory but buys back a lot of accuracy.

**Numerical issues with KV cache.** For long-context LLM inference, the KV cache often dominates memory, and quantizing it can yield large savings. But quantized KV caches are extremely sensitive to attention score scale. The [KV cache quantization work from MIT](https://arxiv.org/abs/2401.18079) showed that naive INT4 KV cache can degrade accuracy by 5–10% on long-context tasks; more careful schemes (per-head, per-token dynamic quantization) can hold the loss under 1%.

## Quantization Is Not Free, But It Is Almost Always Worth It

A realistic bottom line for a 7B–13B parameter LLM deployment:

- **INT8**: 2× memory reduction, 1.5–2× throughput improvement, <0.5% accuracy loss. Almost no downside.
- **INT4 (GPTQ/AWQ)**: 4× memory reduction, 2–3× throughput improvement, 0.5–2% accuracy loss depending on the task. Worth the work for most serving scenarios.
- **FP8**: 2× memory reduction, similar throughput to INT8 on H100, accuracy loss usually negligible. Transitional — not the long-term destination.
- **INT4 + QAT**: Similar memory and throughput to vanilla INT4, but accuracy loss can drop to <0.5% even on hard reasoning tasks. The most expensive option, justified only when vanilla INT4 is not quite there.

The honest version: quantization is one of the few ML optimizations where the engineering effort is small relative to the operational benefit. If you are serving a model at any meaningful scale and you have not yet quantized it, you are leaving a 2–3× cost improvement on the table. The first time you watch a P99 latency histogram tighten and your GPU utilization chart go up after an INT8 rollout, you will understand why this is the first lever every serious inference team pulls.

## Key Takeaways

- **Quantization maps FP16/FP32 tensors to lower-precision representations** via per-tensor or per-channel scale and zero point, exploiting neural networks' tolerance to noise.
- **INT8 is the safe default.** Start there. It is supported on essentially all modern hardware and accuracy loss is usually negligible.
- **INT4 (via GPTQ or AWQ) is the cost-scaling lever** for LLM inference, with accuracy loss bounded by careful preprocessing and per-layer mixed precision.
- **PTQ before QAT.** Post-training quantization is fast and works for INT8; quantization-aware training is a real project and only needed for aggressive sub-INT8 precision or accuracy-sensitive workloads.
- **Shadow mode, feature flags, and eval cards are non-negotiable.** The format is not the hard part; the rollout is.
- **Watch for outlier activations, layer sensitivity, and calibration set mismatch.** These are the three failure modes that account for 90% of quantization regressions.
- **Use a tuned serving stack (TensorRT-LLM, vLLM, ONNX Runtime) rather than rolling your own kernels.** The difference between optimized and unoptimized quantization paths is 3–5× in latency.

## Further Reading

- [A Survey of Quantization Methods for Efficient Neural Network Inference](https://arxiv.org/abs/2103.13630)
- [GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers](https://arxiv.org/abs/2210.17323)
- [SmoothQuant: Accurate and Efficient Post-Training Quantization for Large Language Models](https://arxiv.org/abs/2211.10438)
- [AWQ: Activation-aware Weight Quantization for LLM Compression and Acceleration](https://arxiv.org/abs/2306.00978)
- [TensorRT-LLM GitHub Repository](https://github.com/NVIDIA/TensorRT-LLM)
- [ONNX Runtime Quantization Documentation](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html)
- [bitsandbytes: 4-bit and 8-bit Quantization for Hugging Face Transformers](https://github.com/TimDettmers/bitsandbytes)