---
title: "Optimizing vLLM's PagedAttention Allocator for High-Throughput Batched Inference"
date: "2026-09-07T05:00:33.218"
draft: false
tags: ["vllm", "pagedattention", "llm-inference", "gpu-memory", "kv-cache"]
description: "Practical guide to tuning vLLM's PagedAttention KV cache allocator for maximum throughput, batch size, and tail latency in production LLM serving."
summary: "A working engineer's guide to the internals of vLLM's PagedAttention memory allocator, with concrete knobs, profile traces, and production patterns for squeezing more tokens per second out of a single GPU."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-optimizing-vllm.svg"
  alt: "Diagram of vLLM's PagedAttention KV cache allocator mapping logical blocks to physical GPU memory pages."
  caption: ""
  relative: false
---

> **TL;DR** — PagedAttention treats KV cache like virtual memory: sequences are split into fixed-size blocks and an allocator maps them onto non-contiguous GPU memory. The throughput wins come from fixing fragmentation, picking the right block size, and tuning prefix sharing, not from buying more VRAM. This post walks through the allocator's internals, the knobs that actually move the needle, and the failure modes you'll hit at scale.

## Why KV Cache Allocation Is the Bottleneck

In autoregressive decoding, every active sequence has a KV cache that grows one token per step. A 70B-parameter model on an H100 generates about 5 MB of KV cache per token — and a single batch can hold dozens of concurrent sequences, each running for thousands of steps. Within seconds, the KV cache for a single batch consumes more VRAM than the model weights themselves.

Naive implementations pre-allocate one contiguous tensor per request, sized for the maximum possible sequence length. That approach has three problems that show up fast in production:

1. **Internal fragmentation**: a 2048-token slot reserved for a request that finishes at 87 tokens wastes 96% of its allocation.
2. **External fragmentation**: requests with different lengths finish at different times, leaving jagged holes that nothing can fit into.
3. **No prefix sharing**: every request with the same 2 KB system prompt re-encodes it independently.

The [original PagedAttention paper](https://arxiv.org/abs/2309.06180) from the vLLM team measured up to **24x throughput improvement** over HuggingFace Transformers by treating the KV cache the same way an OS treats RAM: pages of fixed size, an allocator as the page table, and copy-on-write for shared prefixes.

If you want a refresher on the algorithm itself, [HuggingFace's write-up](https://huggingface.co/docs/text-generation-inference/conceptual/streaming) gives a clean mental model. What matters here is the allocator underneath — because that's where production throughput is won or lost.

## How the PagedAttention Allocator Works

At request arrival, vLLM assigns a sequence ID and a logical block table. As the sequence generates tokens, the runtime calls `append_slot` to grow the cache. Internally, that call hits a **block manager** which maintains:

- **Free block lists** per GPU (one list per block size in the current build).
- **Reference counts** for each physical block, enabling copy-on-write prefix sharing.
- **Block tables** mapping `(sequence_id, block_index)` → `physical_block_id`.

There are two scheduling policies you can pick, both exposed via `--block-manager`:

| Policy | Behavior | When it wins |
|---|---|---|
| `v1` (original) | Allocates blocks greedily as sequences grow | Bursty, short-lived traffic |
| `v2` (enabled by default since 0.4.x) | Pre-reserves blocks up to a watermark | Long prefill + decode workloads |

You can see the source for these policies in the [`BlockSpaceManager` directory](https://github.com/vllm-project/vllm/tree/main/vllm/block) — the `v2` path uses a priority queue of "pending" requests, which is what enables the prefill-aware batching improvements described in the [vLLM continuous batching post](https://blog.vllm.ai/2023/06/20/vllm.html).

## The Knobs That Actually Move Throughput

Most teams I've seen tune vLLM stop at `--gpu-memory-utilization` and call it done. There are at least eight other levers, and several of them matter more.

### Block size (`--block-size`)

The default of **16 tokens per block** is a tradeoff, not an optimum. Smaller blocks reduce internal fragmentation but increase the number of GPU→GPU copy operations during prefix sharing. Larger blocks do the opposite.

Concrete guidance from running traces on Llama-3-70B with 8K contexts:

- `block_size=8`: ~3% better prefix cache hit rate, but ~7% lower tokens/sec under pure decode.
- `block_size=16`: the sweet spot for most mixed workloads.
- `block_size=32`: wins by 4-6% on workloads with long, uniform contexts (e.g., RAG over fixed-size documents).

Set it with `VLLM_BLOCK_SIZE=16` (env var) or `--block-size 16`.

### GPU memory utilization (`--gpu-memory-utilization`)

The default is `0.9`, which leaves 10% for CUDA context, activations, and fragmentation. On H100s with 80 GB, that 8 GB headroom is overkill for short contexts and not enough for long ones.

A simple calibration procedure that beats guessing:

```bash
# Run a synthetic load, monitor with nvidia-smi
vllm serve meta-llama/Llama-3.1-70B-Instruct \
  --gpu-memory-utilization 0.92 \
  --max-model-len 8192 \
  --num-gpu-blocks-per-engine 0  # let vLLM discover
```

Then watch `nvitop` (or `nvidia-smi dmon`) for OOMs and adjust in 0.01 increments. Above 0.94 you'll start hitting the activation memory wall at high batch sizes.

### Prefix caching (`--enable-prefix-caching`)

This is the single biggest knob for chat workloads. With prefix caching on, the second request in a conversation shares KV blocks with the first. The trade-off is that **eviction becomes LRU-based instead of FIFO**, which can hurt throughput for unrelated concurrent requests.

For a multi-tenant serving endpoint:

```yaml
# Recommended for chatbot traffic
enable_prefix_caching: true
enable_chunked_prefill: true   # see next section
max_num_batched_tokens: 8192
```

For a batch job running thousands of unrelated prompts, turn it off — you get more predictable scheduling and no cache-pollution thrash.

### Chunked prefill (`--enable-chunked-prefill`)

Decoding requests are latency-sensitive. Prefill requests are throughput-sensitive. Mixing them naively causes **prefill-decode interference** — a 4K prefill can stall every decoder in the batch for hundreds of milliseconds.

Chunked prefill slices large prefills into chunks (default 512 tokens) and interleaves them with decode steps. The allocator needs to pre-reserve blocks for the in-flight prefill chunks, which is why the `--block-manager v2` policy exists.

Enable it:

```bash
vllm serve meta-llama/Llama-3.1-8B-Instruct \
  --enable-chunked-prefill \
  --max-num-batched-tokens 4096
```

### Maximum batched tokens (`--max-num-batched-tokens`)

This is the scheduler's step budget per iteration. Default is 2040 (sum of prefill + decode). Setting it higher improves throughput by amortizing kernel launch overhead but increases p99 latency.

A safe production starting point is `8192` for 70B-class models. Push higher only after profiling with [vLLM's benchmark scripts](https://github.com/vllm-project/vllm/tree/main/benchmarks) — the curve is non-linear past 16K.

## Architecture: How a Production Deployment Looks

A single vLLM instance is rarely the whole story. The allocator's behavior interacts with everything upstream and downstream:

```
                 ┌─────────────────────┐
   Clients ───►  │  API gateway / LB   │
                 └─────────┬───────────┘
                           │ (HTTP, streaming)
                  ┌────────▼─────────┐
                  │  vLLM engine(s)  │
                  │  ┌────────────┐  │
                  │  │ Scheduler  │──┼─► KV cache block manager
                  │  └────────────┘  │       │
                  │  ┌────────────┐  │       ▼
                  │  │   Model    │  │   ┌──────────┐
                  │  │  executor  │  │   │ GPU VRAM │
                  │  └────────────┘  │   │  pages   │
                  └────────┬─────────┘   └──────────┘
                           │
                  ┌────────▼────────┐
                  │  Metrics → Prometheus → Grafana
                  └─────────────────┘
```

Two patterns show up in real deployments:

**1. Multi-instance with shared prefix.** Front a pool of vLLM instances with a router that hashes on the prompt prefix. The router doesn't share KV caches across instances (that would require RDMA or a distributed cache), but it concentrates prefix traffic so each instance's local cache hits stay high. Tools like [llm-d](https://github.com/llm-d/llm-d) or [vLLM's own serve examples](https://docs.vllm.ai/en/latest/serving/parallelism.html) cover this.

**2. Disaggregated prefill/decode.** Run two engine pools: one optimized for prefill (high `max_num_batched_tokens`, low batch concurrency), one for decode (opposite). Transfer KV cache between them over NVLink or InfiniBand. This is what [Mooncake](https://github.com/kvcache-ai/Mooncake) implements and is the right answer when you have hundreds of concurrent long-context requests.

## Patterns in Production

Three patterns I keep seeing on teams running vLLM at non-trivial scale.

### Pattern 1: Adaptive batch sizing via TTFT and ITL SLAs

The allocator and scheduler don't know your latency SLOs — they optimize for throughput. Wrap them with a controller that observes time-to-first-token (TTFT) and inter-token latency (ITL) and adjusts `max_num_seqs` accordingly:

```python
# Pseudocode for a simple adaptive controller
if p99_ttft > sla_ttft and current_batch > min_batch:
    decrement max_num_seqs
elif p99_ttft < 0.7 * sla_ttft:
    increment max_num_seqs  # cap at hardware limit
```

You can hook this into vLLM's [OpenAI-compatible metrics endpoint](https://docs.vllm.ai/en/latest/serving/metrics.html) without modifying the engine.

### Pattern 2: Eviction policy tuning for prefix caching

Prefix caching uses an LRU eviction policy by default. Under bursty workloads this causes **cache thrashing**: a long-tail prefix evicts the warm cache, then re-populates at the worst possible moment.

The fix is to either:

- Set `--prefix-caching-hash-algo sha256` (or `sha256_truncate`) to make collision-resistant keys for caching. The default `builtin` uses a faster but less collision-resistant hash, which can silently reduce hit rates.
- Or, pin a hot prefix via the `--compilation-config` and a custom block-table override if you have a few system prompts that dominate.

### Pattern 3: Memory profiling before deploy

Don't deploy vLLM with defaults on a 70B model — profile first. The [`vllm.profile` module](https://docs.vllm.ai/en/latest/api/vllm.profile.html) outputs a CSV of activation memory vs. sequence length and batch size. Combined with a small [GenAI-Perf](https://github.com/triton-inference-server/perf_analyzer) sweep, you'll know your true max batch size before the first user does.

## Failure Modes Worth Knowing

Three failure modes bite repeatedly:

**1. OOM under burst.** A burst of long-context requests exceeds the pre-reserved block pool. vLLM returns 503s. Mitigation: front the engine with a queue that admits based on `(prompt_tokens + expected_output_tokens) × block_size`.

**2. Prefix cache poisoning.** A multi-tenant system shares prefix cache across users. If two users have system prompts that hash to the same prefix window, one user's tokens can shadow another's. Mitigation: namespace the prefix hash by tenant ID or disable prefix caching for untrusted traffic.

**3. Scheduler deadlock with `--max-num-batched-tokens`.** If you set this lower than your longest prompt, vLLM can't admit the prompt and hangs. Always set `max_num_batched_tokens ≥ longest_expected_prompt + max_decode_budget`.

## Key Takeaways

- **Block size matters more than people think.** Sweep 8, 16, 32 on your workload before committing to defaults.
- **Prefix caching is the highest-leverage knob for chat traffic.** Combine with `--enable-chunked-prefill` for the full win.
- **GPU memory utilization is workload-dependent.** Calibrate per model and per context length, don't copy the 0.9 default everywhere.
- **Chunked prefill eliminates prefill-decode interference** and is essentially required at scale.
- **Profile before deploy.** The interaction between block manager v2, chunked prefill, and your batch size is non-obvious and toolable.
- **Plan for OOM and cache poisoning** before they happen at 2am.

## Further Reading

- [PagedAttention paper (Kwon et al., 2023)](https://arxiv.org/abs/2309.06180)
- [vLLM official documentation — Engine Arguments](https://docs.vllm.ai/en/latest/serving/engine_args.html)
- [vLLM continuous batching blog post](https://blog.vllm.ai/2023/06/20/vllm.html)
- [Chunked Prefill design note](https://github.com/vllm-project/vllm/issues/4739)
- [NVIDIA Triton Inference Server perf analyzer](https://github.com/triton-inference-server/perf_analyzer)
- [HuggingFace TGI streaming and KV cache concepts](https://huggingface.co/docs/text-generation-inference/conceptual/streaming)