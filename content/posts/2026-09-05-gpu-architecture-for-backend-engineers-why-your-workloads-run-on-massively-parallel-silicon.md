---
title: "GPU Architecture for Backend Engineers: Why Your Workloads Run on Massively Parallel Silicon"
date: "2026-09-05T18:58:08.534"
draft: false
tags: ["gpu", "gpu-architecture", "parallel-computing", "cuda", "simt"]
description: "GPU architecture explained for backend and systems engineers: SMs, warps, memory hierarchy, SIMT, and why these design choices make GPUs ideal for AI, analytics, and HPC."
summary: "A practical tour of GPU architecture for engineers who don't write shaders: how streaming multiprocessors, warps, and the memory hierarchy actually work, and why that matters for inference, analytics, and simulation workloads."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-gpu-architecture-for-backend-engineers-why-your-workloads-run-on-massively-parallel-silicon.svg"
  alt: "Diagram of streaming multiprocessors, warp schedulers, and HBM stacks inside a modern GPU package."
  caption: ""
  relative: false
---

> **TL;DR** — A modern GPU is an array of hundreds to thousands of small execution cores organized into Streaming Multiprocessors (SMs), each running groups of 32 threads ("warps") in lockstep on dedicated ALUs. That SIMT design trades single-thread speed for massive throughput, and a deep, programmer-controlled memory hierarchy hides the cost of doing so — which is exactly why GPUs dominate AI training, inference, analytics, and simulation.

## Why Backend Engineers Should Care About GPU Internals

For a long time, "GPU programming" meant graphics: renderers, shaders, vertex transforms. Then CUDA arrived in 2007, frameworks like [PyTorch](https://pytorch.org/) and [TensorFlow](https://www.tensorflow.org/) rode the wave, and suddenly a CPU-side backend engineer is asked to optimize a vector search, fine-tune a 7B-parameter model, or ship a real-time fraud-scoring service that runs entirely on GPU. At that point, knowing the difference between a Streaming Multiprocessor and a CPU core isn't trivia — it's the difference between a service that costs $0.0002 per request and one that costs $0.02.

This post is a ground-up tour of GPU architecture aimed at engineers who already understand CPUs, virtual memory, and cache hierarchies. We'll focus on the design decisions that matter for production workloads: why GPUs are throughput machines, how the SM / warp / thread model works, where the memory bottlenecks actually live, and how all of this shapes the way you should write code.

## The Throughput Machine Mental Model

A modern server CPU has somewhere between 8 and 128 physical cores, each with deep out-of-order pipelines, branch prediction, speculative execution, and multiple megabytes of fast cache. Each core is optimized to minimize the latency of *one* thread. A high-end GPU, by contrast, has thousands of small execution units and is optimized to maximize the throughput of *many* threads. The two are complementary designs with different cost functions.

| Attribute | Server CPU (e.g. Xeon / EPYC) | Data-center GPU (e.g. H100, MI300X) |
|---|---|---|
| Cores / execution units | 8–128 | 10,000–20,000 FP32 ALUs |
| Cache per core | 1–4 MB L2 private | ~256 KB combined L1/SMEM per SM, shared across threads |
| Memory bandwidth | ~100 GB/s (DDR5) | 800–3,000 GB/s (HBM3) |
| Thread model | MIMD, heavy per-thread state | SIMT, 32 threads per warp |
| Best for | Branchy, latency-sensitive code | Data-parallel, throughput-bound code |

That last row is the whole story. A CPU is a scalpel; a GPU is a combine harvester. Knowing which one your workload actually needs — and why — is the first architectural lesson.

## The Core Building Block: Streaming Multiprocessors (SMs)

If the GPU is a throughput machine, the Streaming Multiprocessor is its factory floor. A modern GPU die is essentially an array of SMs replicated across the chip. An NVIDIA H100 SXM5 has 132 SMs; an AMD MI300X has 304. Each SM is a largely independent execution unit that contains:

- A pool of integer and floating-point ALUs (the "CUDA cores" or "stream processors").
- Special-function units (SFUs) for transcendentals like `sin`, `cos`, `exp`, `sqrt`.
- Tensor cores for matrix-multiply-accumulate (the workhorse of deep learning).
- A register file shared by every thread running on the SM.
- A small, low-latency **shared memory** region (also called "SMEM" on NVIDIA, "LDS" on AMD) that threads in the same block can use as a user-managed scratchpad.
- An L1 cache that fronts global memory accesses.
- Warp schedulers and dispatch units that decide which warp of threads runs next.

You can think of an SM as a CPU with hundreds of hardware threads in flight, no branch prediction, and a register file sized for the world. It's deliberately under-engineered per-thread to make room for parallelism.

### What's in a warp?

A **warp** (NVIDIA terminology) or **wavefront** (AMD) is a group of 32 (NVIDIA) or 64 (AMD) threads that execute in lockstep on the SM. When the SM issues an instruction, every thread in the warp executes that instruction on its own data — the SIMT model (Single Instruction, Multiple Threads). If the threads in a warp disagree on a branch, the hardware **serializes** both paths and masks off the lanes that didn't take the branch. This is called *branch divergence* and is one of the most common performance pitfalls in naive GPU code.

> **Aside — "SIMT" vs "SIMD":** SIMD (SSE, AVX, NEON) executes one instruction on multiple data elements packed into wide registers. SIMT looks identical from the outside but exposes scalar threads to the programmer. The hardware still does SIMD under the hood; SIMT is just a friendlier programming model.

### Why so many warps?

Latency hiding. An SM can hold many warps in flight at once — H100 SMs can hold up to 64 resident warps, totaling 2048 threads. When one warp stalls on a memory load, the warp scheduler instantly switches to another warp whose data is ready. This is the same trick as hyperthreading on CPUs, but cranked to the maximum. The arithmetic intensity of your kernel (FLOPs per byte fetched from global memory) determines whether you have enough work to keep those warps fed.

## The Memory Hierarchy: Where GPU Performance Is Won or Lost

GPUs have a memory hierarchy that looks superficially like a CPU's but behaves very differently, because the programmer is expected to manage it more explicitly.

```
+-----------------------------+
|           DRAM              |   <- HBM, 80+ GB, ~3 TB/s on H100
+-----------------------------+
            |  L2 cache (~50 MB on H100, shared across all SMs)
            v
+-----------------------------+
|  L1 cache + Shared Memory   |   <- ~128 KB per SM, user-managed
+-----------------------------+
            |
            v
+-----------------------------+
|        Register File        |   <- 256 KB per SM, ~256 32-bit regs/thread
+-----------------------------+
```

The numbers matter. An H100 has roughly 3 TB/s of HBM bandwidth — that's about 30x what a dual-socket server CPU can pull from DDR5. That bandwidth is the entire reason GPUs exist for AI and analytics: moving tensors through a network is a bandwidth problem, and HBM solves it.

### Registers and occupancy

Every thread in a warp gets its own set of registers. The more registers a thread uses, the fewer warps the SM can hold resident. If your kernel uses 64 registers per thread, you can fit ~32 warps per SM; if it uses 128, only ~16. Lower occupancy means fewer warps to hide stalls, which means lower throughput even if your arithmetic is perfect. Tuning register usage is one of the dark arts of GPU performance engineering.

### Shared memory: the programmer's cache

Unlike CPU L1 caches, shared memory is a user-managed scratchpad. Threads in the same CUDA block can stage data into shared memory, do fast on-chip reductions, and avoid round trips to global memory entirely. This is how classic GPU algorithms like [scan, reduction, and matrix multiply](https://docs.nvidia.com/cuda/cuda-c-programming-guide/) get their speedups — they treat shared memory as a programmable cache and explicitly orchestrate data movement.

### Global memory: coalescing or die

When threads in a warp access global memory, the hardware tries to *coalesce* those accesses into a single wide transaction. If the 32 threads each read one float from 32 contiguous addresses, that's one 128-byte transaction. If the addresses are scattered, you get 32 separate transactions and your kernel grinds to a halt. Coalesced access patterns are non-negotiable for serious GPU performance.

## SIMT, Branching, and Divergence

The SIMT execution model gives GPUs their efficiency but also creates their most famous footgun: branch divergence. Consider:

```cuda
__global__ void classify(int* data, int* out, int n) {
    int i = threadIdx.x + blockIdx.x * blockDim.x;
    if (i >= n) return;
    if (data[i] > 0) {
        out[i] = do_expensive_positive_path(data[i]);
    } else {
        out[i] = do_expensive_negative_path(data[i]);
    }
}
```

If `data[i] > 0` evaluates differently across threads in the same warp, the warp executes both branches serially, with half the lanes idle in each half. Throughput drops by up to 2x for that warp. The fix is usually to restructure the data so that threads in a warp tend to take the same branch — sorting, partitioning, or simply batching inputs by branch condition.

This is why GPU code often has a "struct-of-arrays" flavor, even when an "array-of-structs" would be more natural on the CPU side. You want adjacent threads to read adjacent memory and take adjacent branches.

## Tensor Cores: The Real Reason AI Runs on GPUs

By the time the Volta generation (V100, 2017) shipped, NVIDIA had added dedicated matrix-multiply-accumulate units called **tensor cores**. A single tensor core instruction performs a small matrix multiply (e.g. 16x16x16 FP16) in one cycle, something that would take dozens of cycles on regular ALUs.

The H100's tensor cores go further: they handle FP8, FP16, BF16, TF32, FP64, and various sparsity-accelerated formats. An H100 can deliver nearly 1 PFLOP of FP8 compute and ~990 TFLOPs of BF16 — versus about 60 TFLOPs of plain FP32. That's why every modern LLM serving stack ([vLLM](https://github.com/vllm-project/vllm), [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM), [SGLang](https://github.com/sgl-project/sglang)) spends most of its time orchestrating tensor-core-friendly GEMMs.

Architecturally, tensor cores live inside the SM and consume data from the register file and shared memory. They are the main reason why "GPU utilization" for AI workloads is usually reported as *tensor-core utilization* rather than *SM utilization*.

## Patterns in Production: GPUs in Real Systems

Theory is nice; here are three concrete patterns where GPU architecture shapes production systems.

### 1. LLM inference serving (vLLM, TensorRT-LLM)

Modern LLM serving engines treat the GPU as a memory-and-bandwidth-bound system. The dominant cost is loading the model's weights from HBM into the tensor cores for each generated token. Techniques like **PagedAttention** (introduced in the [vLLM paper](https://arxiv.org/abs/2309.06180)) and continuous batching exist to keep those tensor cores fed by packing multiple user requests into the same forward pass. The hardware's huge memory bandwidth is what makes this work.

### 2. Vector search at scale (FAISS, Milvus, Qdrant)

Approximate nearest neighbor search on billion-vector datasets lives or dies by memory bandwidth. Indexes like IVF-PQ and HNSW are designed so that the dominant operations — distance calculations — can be expressed as huge batched matrix multiplies on the GPU. The architecture's 3 TB/s of HBM bandwidth is what lets a single H100 serve tens of thousands of vector queries per second. The same workload on a CPU cluster would need dozens of machines.

### 3. Real-time analytics on GPUs (BlazingSQL, RAPIDS, GPU databases)

Engines like the [RAPIDS](https://rapids.ai/) suite and GPU-accelerated databases (e.g. Brytlyt, OmniSciDB, HeavyDB) push entire SQL pipelines onto the GPU. Joins, group-bys, and window functions are reformulated as joins on sorted keys, reductions across warps, and shared-memory hash tables. The win comes from collapsing what would be many round trips to CPU RAM into a single sweep through HBM.

### 4. Simulation and HPC

Physics simulators (climate models, CFD, molecular dynamics) are the original "embarrassingly parallel" GPU workload. They typically have a regular grid, lots of floating-point work per cell, and predictable memory access. They're a near-perfect fit for SIMT execution and tensor-core acceleration, and they routinely achieve 70–90% of peak FLOPS on production hardware.

## Common Pitfalls When Moving from CPU to GPU Code

A few things that consistently bite engineers porting code to GPUs for the first time:

- **Launch overhead.** Each kernel launch costs roughly 5–20 µs. Launching a kernel in a tight loop on small inputs is slower than just running on the CPU. Batch small operations, or use CUDA Graphs to capture and replay launch sequences.
- **Synchronization costs.** `cudaDeviceSynchronize` forces the host to wait for the GPU, draining the pipeline. Overuse is a classic performance bug.
- **PCIe transfers.** Moving data between host RAM and GPU HBM costs ~25–32 GB/s on PCIe Gen5. Always overlap transfers with compute using separate streams.
- **Host-side allocations.** Allocating GPU memory inside a hot loop is a hidden killer. Pre-allocate buffers.
- **Assuming "free" parallelism.** Just because you have 16,384 threads doesn't mean your problem is 16,384 times faster. The memory subsystem is the actual bottleneck.

## A Concrete Performance Sketch

To make the bandwidth story concrete, consider a simple operation: element-wise vector add.

```cuda
__global__ void add(const float* a, const float* b, float* c, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) c[i] = a[i] + b[i];
}
```

Each thread reads 8 bytes (two floats) and writes 4 bytes (one float). For N = 100 million elements, that's 1.2 GB of traffic. On an H100 with ~3 TB/s of HBM bandwidth, this kernel completes in roughly 0.4 ms — bandwidth-bound, as expected. The arithmetic is essentially free; the entire kernel is just moving bytes.

This is the *right* shape for a GPU kernel: lots of independent work per memory access, minimal branching, simple inner loop. Most GPU performance work is about reshaping algorithms until they look like this.

## Where GPU Architecture Is Going

A few trends worth knowing about, since they show up in vendor roadmaps and conference talks:

- **Larger and faster HBM.** HBM3e and the upcoming HBM4 push per-package bandwidth past 5 TB/s.
- **Tighter CPU-GPU integration.** NVIDIA Grace Hopper and AMD MI300A use coherent NVLink / Infinity Fabric to put the CPU and GPU on the same memory fabric, eliminating the PCIe bottleneck for memory-bound workloads.
- **Lower-precision numerics.** FP8 and FP4 are now first-class citizens for inference; training is following.
- **Transformer-specific silicon.** Both NVIDIA and AMD are adding hardware blocks optimized for attention's specific memory access patterns.
- **Multi-GPU fabrics.** NVLink, NVSwitch, and Infinity Fabric scale to dozens of GPUs sharing a coherent memory space, which is increasingly important as models exceed a single GPU's HBM capacity.

## Key Takeaways

- A modern GPU is an array of Streaming Multiprocessors, each running many small threads grouped into warps of 32, executing in lockstep under the SIMT model.
- The defining trade-off is single-thread latency for massively parallel throughput, enabled by a deep memory hierarchy and very high HBM bandwidth.
- Most GPU performance problems are actually memory problems — coalescing, occupancy, shared memory use, and arithmetic intensity dominate over raw compute speed.
- Tensor cores are the reason AI workloads run on GPUs at all; everything else (warp scheduling, shared memory, HBM) exists to feed them.
- When porting code, the wins come from reshaping algorithms to match SIMT-friendly access patterns, batching launches, and overlapping transfers with compute.

## Further Reading

- [NVIDIA CUDA C++ Programming Guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/) — the canonical reference for SMs, warps, shared memory, and the memory hierarchy.
- [NVIDIA H100 Tensor Core GPU Architecture Whitepaper](https://resources.nvidia.com/en-us-tensor-core) — the closest thing to a public architectural deep-dive on Hopper.
- [AMD CDNA 3 / MI300X Architecture Overview](https://www.amd.com/en/technologies/cdna.html) — the data-center counterpart from AMD, useful for cross-vendor comparison.
- [PyTorch CUDA semantics documentation](https://pytorch.org/docs/stable/notes/cuda.html) — practical notes on how frameworks actually use the GPU.
- [vLLM: Efficient Memory Management for LLM Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — a great example of GPU architecture shaping a production system design.