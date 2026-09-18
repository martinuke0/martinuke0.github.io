---
title: "Optimizing CUDA Kernels for Sparse Matrix Multiplication: A Performance Guide"
date: "2026-09-18T21:01:25.930"
draft: false
tags: ["cuda", "sparse-matrices", "gpu-computing", "performance-engineering", "linear-algebra", "deep-learning"]
description: "A practical guide to optimizing CUDA kernels for sparse matrix multiplication, covering storage formats, kernel design patterns, and real-world profiling strategies."
summary: "Sparse matrix multiplication is a bottleneck in many GPU workloads. This guide covers storage formats, kernel-level optimization strategies, and profiling techniques to extract maximum performance from your CUDA kernels."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-optimizing-cuda-kernels-for-sparse-matrix-multiplication-a-performance-guide.svg"
  alt: "GPU computing visualization with sparse matrix data flow"
  caption: ""
  relative: false
---

> **TL;DR** — Sparse matrix multiplication on GPUs demands careful attention to memory access patterns, storage formats, and thread scheduling. Choosing the right format (CSR, ELL, HYB), maximizing coalesced global memory reads, and leveraging shared memory for intermediate accumulation can yield 3–10× speedups over naive implementations. This guide walks through the full optimization pipeline from format selection to kernel tuning.

## The Sparse Matrix Multiplication Problem

Sparse matrices arise everywhere in high-performance computing — from graph neural networks and recommendation systems to finite element solvers and circuit simulation. Unlike their dense counterparts, where GPUs excel through massive parallelism and high arithmetic intensity, sparse matrices introduce irregular memory access patterns that can cripple GPU throughput if handled naively.

Consider a typical scenario: you need to compute $C = A \times B$, where $A$ is an $m \times k$ sparse matrix with $\text{nnz}_A$ non-zero elements and $B$ is a $k \times n$ sparse matrix with $\text{nnz}_B$ non-zero elements. A naive approach that iterates over every possible $(i, j, p)$ triple — even where $A_{ip} = 0$ and $B_{pj} = 0$ — wastes orders of magnitude more computation than is actually needed.

The core challenge is not arithmetic — it is memory. On modern NVIDIA GPUs (Ampere, Hopper, Blackwell), the arithmetic-to-memory ratio is enormous: an H100 can deliver up to 1979 TFLOPS of FP8 throughput but is limited by memory bandwidth to roughly 3.35 TB/s. For sparse operations, the effective arithmetic intensity is often so low that the kernel becomes entirely memory-bound. Every optimization decision must therefore be evaluated through the lens of: *how many bytes does each non-zero element traverse from global memory to the compute units?*

## Storage Format Selection

The choice of sparse storage format fundamentally constrains what your kernel can do. Each format represents a different trade-off between random access patterns, storage overhead, and kernel complexity.

### Compressed Sparse Row (CSR)

CSR is the most widely used format and the one supported by cuSPARSE. It stores three arrays:

- `values`: the non-zero elements, read left-to-right per row.
- `column_indices`: the column index for each non-zero value.
- `row_ptr`: an array of length $m+1$ where `row_ptr[i]` gives the starting index in `values` for row $i$.

```python
# Conceptual CSR representation for a 4x4 matrix
# Matrix:
# [1.0, 0.0, 2.0, 0.0]
# [0.0, 0.0, 0.0, 3.0]
# [4.0, 0.0, 5.0, 0.0]
# [0.0, 6.0, 0.0, 0.0]

values    = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
col_index = [0,  2,  3,  0,  2,  1]
row_ptr   = [0,  2,  3,  5,  6]
```

CSR excels at row-wise traversal — each row's non-zero elements are contiguous in memory. This makes it ideal for SpMV (sparse matrix-vector multiply), where one thread can process an entire row. However, for sparse matrix-matrix multiplication (SpGEMM), CSR introduces a problem: the columns of $B$ are not stored contuously, leading to gather-style reads that are inefficient on GPUs.

### Ellpack (ELL)

ELL stores each row in a fixed-width array of length $\text{max\_nnz\_per\_row}$. This eliminates the need for indirect indexing within a row and enables fully coalesced memory reads when threads in a warp access the same column position across different rows.

The trade-off is padding. If your matrix has highly variable row lengths, ELL wastes significant memory on zeros. For matrices with a Poisson-distributed non-zero pattern (common in finite difference stencils), ELL overhead is typically 10–30%. For power-law graphs, it can exceed 300%.

### Hybrid (HYB) and Blocked Formats

The hybrid format splits the matrix into an ELL portion for rows with regular structure and a COO (coordinate) portion for the irregular remainder. NVIDIA's cuSPARSE historically used this approach. More recently, blocked formats like BSR (Blocked Sparse Row) have gained traction because they increase arithmetic intensity by operating on small dense sub-blocks rather than individual scalars.

For SpGEMM specifically, the **row-column** format (where $A$ is in CSR and $B$ is in column-major CSR, sometimes called CSC) allows each thread to compute one output element $C_{ij}$ by taking the dot product of row $i$ of $A$ and column $j$ of $B$. This is elegant but suffers from poor parallelism when output rows have highly variable lengths.

## Kernel Architecture and Thread Mapping

### The Row-at-a-Time Pattern

The most straightforward SpGEMM kernel assigns one thread block per output row of $C$. Within each block, threads cooperatively compute the dot products for that row.

```
Block for row i:
  for each non-zero A[i, p]:
    for each non-zero B[p, j]:
      atomicAdd(C[i, j], A[i, p] * B[p, j])
```

The problem is the inner loop: for each $p$, we must locate the non-zero entries in row $p$ of $B$, which requires a binary search or hash lookup into $B$'s row pointer array. This is a random access pattern that destroys cache locality.

A better approach is to precompute a "sparse accumulator" (SPA) data structure. The algorithm proceeds in two phases:

1. **Symbolic phase**: determine the sparsity pattern of $C$ (which entries are non-zero) without computing values.
2. **Numeric phase**: fill in the computed values.

cuSPARSE's `cusparseSpGEMM` performs exactly this two-phase approach, and it is the recommended path for production workloads unless you have a specific reason to write custom kernels.

### Shared Memory Tiling

For kernels where you can tile the computation, shared memory acts as a software-managed cache. The idea is to load a tile of $A$ and a tile of $B$ into shared memory, compute partial results, and then load the next tile.

```cuda
__global__ void spmm_tile_kernel(
    const float* __restrict__ A_val,
    const int* __restrict__ A_col,
    const int* __restrict__ A_row_ptr,
    const float* __restrict__ B_val,
    const int* __restrict__ B_col,
    const int* __restrict__ B_row_ptr,
    float* __restrict__ C,
    int m, int k, int n) {

    extern __shared__ float smem[];
    float* sA = smem;
    float* sB = &smem[TILE_K * TILE_N];

    int row = blockIdx.x * blockDim.x + threadIdx.x;
    if (row >= m) return;

    float accum[N] = {0.0f};

    for (int idx = A_row_ptr[row]; idx < A_row_ptr[row + 1]; idx++) {
        int p = A_col[idx];
        float a_val = A_val[idx];

        // Load tile of B row p into shared memory
        int b_start = B_row_ptr[p];
        int b_end = B_row_ptr[p + 1];
        // ... cooperative loading of B tile ...

        // Compute partial dot products
        for (int j = 0; j < n; j++) {
            // Accumulate using shared memory B values
        }
    }

    // Write results
    if (threadIdx.x == 0) {
        for (int j = 0; j < n; j++) C[row * n + j] = accum[j];
    }
}
```

The key insight is that shared memory has ~100× the bandwidth of global memory on NVIDIA GPUs. By ensuring that each non-zero element of $B$ is loaded from global memory exactly once and then reused by multiple threads in the tile, you dramatically reduce global memory traffic.

### Warp-Level Primitives

Modern CUDA architectures (Volta and later) support warp-level primitives that enable efficient reduction and scatter operations without shared memory. For SpGEMM, warp-level matrix multiply-accumulate (`wmma::mma_sync`) can be used to fuse the dot-product computation directly into tensor cores.

The `nvcuda::wmma` API allows a warp to collaboratively compute a $16 \times 16 \times 16$ matrix multiply in a single instruction. When combined with sparse input formats, this can push utilization above 80% on Ampere and Hopper GPUs — but only if the data layout matches what the WMMA instructions expect (typically dense fragments with specific memory alignment).

## Memory Access Optimization

### Coalescing Global Memory Reads

Coalescing is the single most impactful optimization for memory-bound sparse kernels. On NVIDIA GPUs, threads in a warp (32 threads) that access consecutive addresses in global memory can combine their requests into a single memory transaction. For a warp-wide read of 128 bytes (32 FP32 values), the transaction is a single 128-byte segment.

In CSR format, if a warp processes rows $i$ through $i+31$ of matrix $A$, the `values` and `column_indices` arrays will have non-contiguous access patterns because each row has a different number of non-zeros. This results in uncoalesced reads and can cut effective bandwidth by 50–80%.

The solution is to reorder rows by non-zero count — a process called **row sorting** or **queue sorting**. By sorting rows in descending order of non-zero count, threads in a warp process rows of similar length, improving the likelihood of coalesced access. cuSPARSE provides `cusparseXcsrsort` for this purpose.

### L2 Cache and Persistent Threads

On Ampere and Hopper GPUs, the L2 cache is significantly larger (up to 50 MB on H100) and can be configured for persistent caching. For sparse kernels where the same column indices are accessed repeatedly (as in the inner loop of SpGEMM), enabling persistent L2 caching via `cudaDeviceSetCacheConfig(cudaFuncCachePreferL1)` can reduce global memory re-fetches.

Persistent threads — threads that remain resident on a Streaming Multiprocessor (SM) for the duration of the kernel rather than being periodically evicted — improve occupancy and cache reuse. This is configured through the CUDA occupancy API and requires careful tuning of block size and shared memory usage.

## Profiling and Performance Analysis

### Key Metrics to Monitor

When profiling a sparse matrix multiplication kernel, the following metrics from `nsys` (NVIDIA Nsight Systems) and `ncu` (NVIDIA Nsight Compute) are essential:

- **Achieved Occupancy**: The ratio of active warps to the maximum supported on each SM. Below 50% indicates a resource bottleneck (registers, shared memory, or blocks per SM).
- **Memory Throughput**: Global load and store throughput relative to the theoretical peak. If you are achieving less than 60% of peak bandwidth, your access pattern is the bottleneck.
- **L2 Cache Hit Rate**: For sparse kernels, an L2 hit rate below 40% suggests that the working set exceeds cache capacity and you need better data reuse or a different tiling strategy.
- **Divergent Branches**: Warp divergence in the row-length loop causes serialization. A divergence rate above 20% warrants restructuring.

```bash
# Profile a SpGEMM kernel with Nsight Compute
ncu --metrics sm__sass_thread_inst_executed_op_dfma_pred_on_avg
     --metrics l1tex__t_sectors_pipe_lsu_mem_global_op_ld.sum
     --metrics smsp__sass_thread_inst_executed_op_ffma_pred_on_avg
     --kernel-name spmm_kernel ./spmm_app
```

### The Roofline Model

The roofline model is indispensable for understanding where your sparse kernel sits on the performance spectrum. Plot the arithmetic intensity (FLOPs per byte) against achieved FLOPS:

- If your kernel falls on the **memory-bound** roofline, optimizing arithmetic won't help — you need to reduce bytes transferred or increase data reuse.
- If your kernel falls on the **compute-bound** roofline, you need more instructions per byte — consider larger tile sizes or blocked formats that increase arithmetic intensity.

For a typical CSR-based SpGEMM with double-precision floats, arithmetic intensity is often 0.1–0.5 FLOPs/byte, placing it far below the memory bandwidth ceiling. This means the kernel is almost entirely memory-bound, and the optimization strategy must focus on reducing memory traffic rather than increasing compute.

## Production Patterns and Libraries

### When to Use cuSPARSE

For most production workloads, the recommended path is to use NVIDIA's cuSPARSE library rather than writing custom kernels. The `cusparseSpGEMM` function handles the symbolic and numeric phases automatically and is optimized across all supported GPU architectures.

```cuda
cusparseSpGEMM(handle, CUSPARSE_OPERATION_NON_TRANSPOSE,
               CUSPARSE_OPERATION_NON_TRANSPOSE,
               &alpha, matA, matB, &beta, matC,
               CUDA_R_32F, CUSPARSE_SPGEMM_DEFAULT,
               &matC_desc);
```

cuSPARSE internally selects the best algorithm based on matrix dimensions, sparsity, and GPU architecture. It also handles the SPA data structure construction and memory management transparently.

### When to Write Custom Kernels

Custom kernels become worthwhile when:

- The matrix structure is known and regular (e.g., block-banded, power-law with a known degree distribution).
- You need to fuse the sparse multiplication with a downstream operation (e.g., activation function, normalization) to avoid writing intermediate results to global memory.
- You are targeting a specific GPU architecture and can exploit hardware features (e.g., tensor cores, asynchronous copy instructions) that generic libraries do not expose.

A notable example is DeepSeek's approach to sparse attention, where custom kernels were written to exploit the structured sparsity pattern of sliding-window attention, achieving significant throughput improvements over cuSPARSE.

## Common Pitfalls

1. **Ignoring structural sparsity**: Many ML workloads have structured sparsity (entire rows or columns are zero). Unstructured formats like CSR waste bandwidth loading the row pointer and column index arrays for zero rows. Use structured sparse formats when possible.

2. **Over-optimizing for a single matrix**: A kernel tuned for a 10,000×10,000 matrix with 0.1% density will perform poorly on a 1,000×1,000 matrix with 1% density. Always benchmark across the full range of production inputs.

3. **Neglecting host-side overhead**: The symbolic phase of SpGEMM can dominate runtime for small matrices. If your application performs many small sparse multiplications, consider batching them into a single cuSPARSE call or using a different algorithm entirely.

4. **Assuming uniform row lengths**: Real-world sparse matrices are rarely uniform. Kernels designed for uniform lengths (like ELL-based) will have severe padding penalties on irregular matrices.

## Key Takeaways

- **Storage format dictates performance ceiling.** CSR is versatile but memory-bound; ELL maximizes coalescing at the cost of padding; HYB and blocked formats offer the best compromise for production workloads.
- **Memory access patterns matter more than arithmetic.** Sparse kernels are almost always memory-bound. Focus optimization effort on coalescing global memory reads, maximizing L2 cache hit rates, and reducing bytes per non-zero element.
- **Two-phase SpGEMM (symbolic + numeric) is the standard approach.** The symbolic phase determines the output sparsity pattern, enabling efficient memory allocation and coalesced writes in the numeric phase.
- **Shared memory tiling can improve data reuse by 2–5×** but requires careful tuning of tile dimensions to balance occupancy against shared memory usage.
- **Always profile before optimizing.** Use `nsys` and `ncu` to identify whether your bottleneck is memory bandwidth, compute throughput, or occupancy. The roofline model provides an intuitive framework for this analysis.
- **Start with cuSPARSE.** Custom kernels are justified only when you have a specific structural advantage or a fused operation that the library cannot express.

## Further Reading

- [NVIDIA cuSPARSE Documentation](https://docs.nvidia.com/cuda/cusparse/index.html) — The official reference for sparse matrix operations on NVIDIA GPUs, including the SpGEMM API and format descriptions.
- [Sparse Matrix Format Comparison (CSF)](https://github.com/sparse-template-library/stl/blob/master/doc/CSR.md) — A detailed comparison of CSR, ELL, HYB, and blocked formats with performance benchmarks across GPU architectures.
- [NVIDIA Nsight Compute User Guide](https://docs.nvidia.com/nsight-compute/index.html) — Comprehensive profiling documentation with metric descriptions and optimization case studies for CUDA kernels.
- [An Overview of Adaptive Precision and Sparse Matrix Algorithms on GPUs](https://ieeexplore.ieee.org/document/8923944) — Academic survey covering sparse matrix formats, GPU memory hierarchies, and optimization strategies with empirical results.
- [CUDA Programming Guide: Shared Memory and Memory Hierarchy](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#shared-memory) — The definitive reference for CUDA memory architecture, including shared memory bank conflicts, L1/L2 caching, and coalescing rules.
- [cuSPARSELt: A Library for Sparse Matrix Operations on NVIDIA GPUs](https://developer.nvidia.com/blog/cusparselt-library/) — NVIDIA's blog on cuSPARSELt, the next-generation sparse library leveraging structured sparsity and tensor cores.
- [The Roofline Model Explained](https://developer.nvidia.com/blog/analysis-of-gpu-optimization-case-study-roofline-model/) — NVIDIA's guide to applying the roofline model for practical GPU performance analysis.