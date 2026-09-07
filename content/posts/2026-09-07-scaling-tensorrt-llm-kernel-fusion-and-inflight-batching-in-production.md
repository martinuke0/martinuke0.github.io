---
title: "Scaling TensorRT-LLM: Kernel Fusion and Inflight Batching in Production"
date: "2026-09-07T10:00:29.787"
draft: false
tags: ["tensorrt-llm", "inference", "kernel-fusion", "inflight-batching", "llmops"]
description: "A practitioner's deep dive into how TensorRT-LLM uses kernel fusion and inflight batching to push GPU utilization past 80% in production LLM serving."
summary: "How NVIDIA's TensorRT-LLM squeezes maximum throughput from a single GPU — and across a fleet — by fusing kernels, paged KV-cache, and continuously batching requests."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-scaling-tensorrt-llm-kernel-fusion-and-inflight-batching-in-production.svg"
  alt: "A heatmap-style illustration of GPU SM utilization across batched transformer layers."
  caption: ""
  relative: false
---

> **TL;DR** — TensorRT-LLM ships two compounding wins for production LLM serving: aggressive *kernel fusion* that turns a multi-op graph into a single launchable CUDA kernel, and *inflight batching* (a.k.a. continuous batching) that interleaves decode steps from requests at different lengths so no SM sits idle. Together, they routinely push effective GPU utilization from the 20–30% you get with naive serving to 70–80%+.

If you have ever looked at `nvidia-smi` while serving an LLM and wondered why the GPU is at 22% utilization while your latency SLO is on fire, you have met the two problems TensorRT-LLM was built to solve. The first is *kernel-launch overhead* — every matmul, softmax, and rope rotation is a separate launch, and launches are not free. The second is *request heterogeneity* — one prompt with 512 tokens, three with 64, one with 2048 — and static batching forces the slowest request to dictate throughput for the whole batch.

This post walks through both halves of the engine: the graph-level optimizations that make each forward pass cheaper, and the scheduler-level optimizations that make every millisecond of GPU time earn its keep.

## The Starting Point: Why Naive LLM Serving Leaves Performance on the Floor

A typical transformer block does more than `Q @ K^T`. It does RMSNorm, a QKV projection, rotary position embedding, attention, a residual add, an MLP up-projection, a SiLU/GELU, an MLP down-projection, and another residual add. In PyTorch eager mode that is **roughly 15–20 discrete CUDA kernel launches per layer**. At batch size 1, a 70B-parameter model on H100 spends more time *scheduling* kernels than *executing* them on small layers, which is why single-request latency on naive stacks can be 30–40% worse than the theoretical FLOPs would predict.

TensorRT-LLM attacks this from three angles simultaneously:
- **Graph-level fusion** at the kernel level (custom CUDA / CUTLASS kernels).
- **Graph-level fusion** at the engine level (TensorRT's layer fusion and `INetwork` builder).
- **Scheduler-level batching** that adapts to per-request decode progress.

Each one matters. Skipping any one of them caps the others.

## Kernel Fusion: Fewer Launches, Bigger Payloads

Kernel fusion combines multiple operations into a single CUDA kernel. The wins are not just "fewer launches" — they include *eliminated round-trips through HBM*, *better register reuse*, and *higher arithmetic intensity per SM*.

### What Gets Fused

TensorRT-LLM ships fused kernels for nearly every hot block in a transformer. The pattern looks like this in the generated engine:

- **RMSNorm + residual**: a single pass over the activations writes the normalized output *and* the residual sum in one read-write cycle.
- **QKV projection**: three GEMMs collapsed into one `[B, H] @ [H, 3H]` matmul so the input activations are read once from HBM.
- **RoPE**: rotary embedding applied *inside* the attention projection kernel rather than as a follow-up pass.
- **Attention**: the big one — fused multi-head attention (FMHA) and, on newer GPUs, FlashAttention-2/3 paths via [CUTLASS](https://github.com/NVIDIA/cutlass). KV reads, softmax, and output projection happen in SRAM/registers.
- **MLP gate+up+activation**: SiLU/gated activation fused into the up-projection epilogue so the intermediate tensor never spills to HBM.
- **AllReduce + residual**: in tensor-parallel setups, the all-reduce is fused with the next residual add to hide NCCL latency behind compute.

### How It Actually Looks in the Engine

When you build a TensorRT-LLM engine, the Python API hands a graph definition to TensorRT, which then runs its [layer fusion optimization pass](https://docs.nvidia.com/deeplearning/tensorrt/developer-guide/index.html). Vertical fusion collapses `Conv → Bias → ReLU` style chains; horizontal fusion duplicates a kernel across heads and runs them as a single 3D launch. Below the engine layer, TensorRT-LLM's own [kernel library](https://github.com/NVIDIA/TensorRT-LLM) supplies the custom CUDA kernels that TensorRT cannot synthesize on its own.

A useful mental model: TensorRT's optimizer is the compiler; TensorRT-LLM's kernel library is the hand-rolled intrinsic set for transformer ops the compiler cannot infer.

### Quantization Tightens the Loop

Fusion matters more, not less, when models are quantized. INT8 / FP8 GEMMs already cut HBM bandwidth pressure; fusing the surrounding ops means the now-cheaper matmul is the *only* place you touch global memory. This is why TensorRT-LLM's [FP8 path](https://nvidia.github.io/TensorRT-LLM/performance/perf-best-practices.html) reports such large wins — it is not just "8-bit instead of 16-bit," it is "8-bit in a graph where the surrounding ops are free." On H100, FP8 + fused attention is the default sweet spot; on A100, INT8 weight-only is more typical.

## Inflight Batching: Stop Wasting the Fast Requests

Fusion gets you cheaper *per-token* cost. Inflight batching gets you more *tokens per second per GPU*.

### Static vs. Dynamic vs. Inflight

Three serving regimes, in increasing order of efficiency:

1. **Static batching** (the naive baseline): pack requests into a batch of size N, run them as a group, return when *all* are done. A 2000-token completion next to a 50-token completion wastes 1950 tokens of GPU time.
2. **Dynamic batching** (what vLLM popularized under the name *continuous batching*): form batches at each decode step from the request queue, so a finished request is replaced immediately. Tokens-per-second roughly doubles for chatty workloads.
3. **Inflight batching** (TensorRT-LLM's term, sometimes called *iteration-level scheduling*): the same as dynamic batching, but extended to handle *prefix sharing*, *beam search*, *paged KV-cache*, and *LoRA adapter swapping* within the same iteration.

The crucial difference is iteration-level rather than request-level scheduling: at step *t*, the scheduler looks at every in-flight request, decides which ones get to decode at step *t+1*, and reissues a batch that may include some requests still in their prefill phase and others already mid-decode. Prefill and decode *coexist* in the same iteration, which is where the real wins come from.

### The Paged KV-Cache: vLLM Borrowed by TensorRT-LLM

The reason continuous batching was hard to build before paged attention was memory fragmentation. A naive KV-cache reserves `max_seq_len` slots per request, which means a 512-token-cap request wastes 80% of its reserved memory when it only uses 64 tokens. Paged attention (introduced in the [vLLM paper](https://arxiv.org/abs/2309.06180) and adopted by TensorRT-LLM) allocates the cache in fixed-size *blocks* (typically 16 or 32 tokens) and tracks per-request block tables.

This changes the batching math. With paged KV, you can pack requests into the available KV-cache budget instead of into pre-allocated worst-case slots, which means you can keep 4–8x more concurrent requests in flight at the same GPU memory cost. The scheduler — Triton-style in vLLM, custom-CUDA in TensorRT-LLM — handles the block-table lookup inside the attention kernel so the indirection is free.

### Beam Search and LoRA on the Same Iteration

Two cases that *break* naive batching but are first-class in TensorRT-LLM:

- **Beam search**: each request may have K beams, each with its own KV-cache. Inflight batching treats each beam as an independent sequence, so a finished beam does not stall the others. The scheduler also handles beam pruning mid-decode.
- **LoRA / PEFT**: serving 50 adapter variants on a single base model is a common production pattern. TensorRT-LLM's [LoRA support](https://nvidia.github.io/TensorRT-LLM/lora.html) keeps adapter weights in host memory and pages the active ones into GPU memory per iteration. A fused GEMM picks the right adapter weights at launch time, so swapping adapters is a metadata operation, not a reload.

### What the Scheduler Actually Does

At each iteration the scheduler runs a small decision loop:

1. **Admit** new requests from the queue if KV-cache budget allows.
2. **Match** in-flight requests to available GPU memory; preempt the lowest-priority ones if needed (with configurable recompute vs. swap policy).
3. **Build** the per-iteration batch — a list of (request_id, seq_id, token_ids_to_decode) tuples.
4. **Launch** a single fused forward pass across the batch.
5. **Sample** outputs per sequence (top-k, top-p, etc.) and update KV-cache block tables.

Step 4 is the magic. Because every operation in the transformer block is fused, the iteration is effectively one or two CUDA kernel launches per layer, regardless of batch size. The scheduler overhead is dominated by Python/C++ dispatch, which TensorRT-LLM keeps in a C++ executor to avoid GIL contention.

## Patterns in Production

Three concrete patterns from teams running TensorRT-LLM at scale:

### 1. The Two-Engine Trick for Chat Workloads

A chat workload is bimodal: short prompts (1–200 tokens) with short completions, vs. long-context prompts (4k–32k tokens) with moderate completions. A single engine optimized for the median is suboptimal for both tails.

The pattern: build two engines — one with max_seq_len=512, FP8 weights, and aggressive in-flight batching; one with max_seq_len=8192, FP8 KV-cache, and conservative batch size for prefill throughput. Route requests at admission time based on `prompt_tokens + expected_completion_tokens`. The result is typically a 1.5–2x throughput improvement over a single-engine deployment at the same latency budget.

### 2. Disaggregated Prefill/Decode

When you have a fleet, you can go further. Run *prefill engines* on a subset of nodes (high FLOPS, low concurrency) and *decode engines* on the rest (lower FLOPS per request, very high concurrency). Transfer KV-cache between them over NVLink/InfiniBand using TensorRT-LLM's [disaggregated serving](https://nvidia.github.io/TensorRT-LLM/reference/disaggregated-serving.html) support. The prefill node finishes a request's prompt processing and hands the KV-cache to a decode node that streams the rest of the response.

This pattern is the one most often credited with pushing large-model serving past the 70B-on-8xH100 mark at acceptable cost. It also lets you scale the two phases independently — prefill is memory-bandwidth-bound on long prompts, decode is compute-bound on short steps.

### 3. Speculative Decoding for Tail Latency

For interactive workloads (chat, code completion), pair TensorRT-LLM's executor with a draft model — e.g. a 1B draft + 70B target using [Medusa heads](https://arxiv.org/abs/2401.10774) or EAGLE. The fused-target forward path stays the same; you just feed multiple candidate tokens per iteration. End-to-end latency drops 2–3x while throughput on the target model actually *increases* because you amortize each forward pass across more accepted tokens.

## What You Measure vs. What You Configure

A short list of knobs that matter, in order of leverage:

| Lever | Where | Typical impact |
|---|---|---|
| `max_num_tokens` (iteration budget) | Executor config | 1.5–3x throughput vs. naive batching |
| KV-cache block size | Engine build | Memory efficiency, fragmentation |
| Quantization (FP8/INT8) | Engine build | 1.5–2x throughput, 2x HBM savings |
| `enable_chunked_context` | Engine build | Prefill latency on long prompts |
| Tensor parallel degree | Executor config | Scales throughput, not latency |
| `max_batch_size` | Engine build | Caps concurrent requests per step |

The single most-levered knob is `max_num_tokens`. It defines how many tokens (prefill + decode) can be processed in a single iteration. Set it too low and the GPU starves; too high and tail latency blows up because the scheduler waits for a full token budget before launching. The right value depends on your SLO — start at `max_batch_size * avg_decode_len` and tune from there with `nsys` profiles.

## Key Takeaways

- **Kernel fusion is not optional.** The difference between a fused transformer block and a per-op PyTorch eager block is often 1.5–2x in tokens/second before you even consider batching.
- **Inflight batching is the dominant throughput lever.** Going from static to inflight batching typically 2–4x's tokens/second on chat workloads, regardless of which engine you use.
- **Paged KV-cache is what makes inflight batching feasible at high concurrency.** Without it, KV-cache fragmentation caps you at a handful of concurrent long-tail requests.
- **Quantization amplifies fusion.** FP8 + fused attention on H100 is the current sweet spot; the 8-bit math is only worth it because the surrounding ops are free.
- **Production deployments are disaggregated.** Prefill and decode have different resource profiles; serving them on separate pools (or even separate engines) is the pattern that scales.
- **Profile before you tune.** `nsys` and `ncu` are not optional — the bottleneck moves between matmul, attention, and AllReduce as batch size and sequence length change, and there is no single config that wins everywhere.

## Further Reading

- [TensorRT-LLM GitHub repository](https://github.com/NVIDIA/TensorRT-LLM) — engine builder, kernel library, and the disaggregated-serving examples referenced above.
- [vLLM paper: Efficient Memory Management for LLM Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — the origin of paged KV-cache and continuous batching.
- [FlashAttention-2 paper](https://arxiv.org/abs/2307.08691) — the fused-attention algorithm TensorRT-LLM's FMHA kernels implement.
- [NVIDIA TensorRT Developer Guide](https://docs.nvidia.com/deeplearning/tensorrt/developer-guide/index.html) — the layer-fusion and optimization passes underneath TensorRT-LLM.
- [CUTLASS library](https://github.com/NVIDIA/cutlass) — the template library used to build TensorRT-LLM's custom GEMM and attention kernels.
- [Medusa: Simple LLM Inference Acceleration Framework with Multiple Decoding Heads](https://arxiv.org/abs/2401.10774) — speculative-decoding companion for tail-latency reduction.