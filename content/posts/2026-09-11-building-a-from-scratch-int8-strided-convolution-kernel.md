---
title: "Building a From-Scratch INT8 Strided Convolution Kernel"
date: "2026-09-11T04:02:31.436"
draft: false
tags: ["systems", "quantization", "c++", "simd", "high-performance-computing"]
description: "A hands-on guide to building a from-scratch INT8 strided convolution kernel in C++ to signal deep systems engineering skills."
summary: "Learn how to build a high-performance INT8 convolution kernel from scratch using strided memory access and SIMD instructions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-building-a-from-scratch-int8-strided-convolution-kernel.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — Building a from-scratch INT8 strided convolution kernel demonstrates mastery of memory hierarchy, SIMD vectorization, and low-level ML systems. Unlike generic model quantization tutorials, this project proves you can engineer the actual compute primitives that make AI fast on real hardware.

The gap between high-level machine learning frameworks and the silicon that executes them is where the most valuable engineering happens. When hiring managers look at a portfolio, they see thousands of resumes claiming proficiency in PyTorch or TensorFlow. What they rarely see is a candidate who understands how a convolution actually traverses memory, how INT8 arithmetic prevents overflow, and how to vectorize a loop to squeeze out every last cycle of a CPU. 

A from-scratch INT8 strided convolution kernel is the perfect antidote to generic tutorial fatigue. It sits at the intersection of computer architecture and ML systems, requiring you to manipulate memory layouts, leverage SIMD instructions, and optimize for cache locality. This guide will walk you through building a production-grade primitive that signals exactly the kind of deep systems thinking that top tech companies covet.

## Why This Project Stands Out on a CV

Most ML engineers know how to call `torch.quantize` or `tf.quantization.quantize_and_dequantize`. But knowing *how* to use a tool is fundamentally different from understanding the machine it runs on. This project signals three critical competencies to hiring managers:

1. **Memory Hierarchy Mastery:** Strided convolutions require accessing overlapping regions of an input tensor. Naive implementations thrash the CPU cache. By optimizing the memory access pattern, you demonstrate an understanding of cache lines, spatial locality, and the cost of DRAM round-trips.
2. **SIMD Vectorization:** INT8 operations are heavily reliant on Single Instruction, Multiple Data (SIMD) units (like AVX2 on x86 or NEON on ARM). Writing these kernels from scratch proves you can bridge the gap between algorithmic logic and hardware capabilities.
3. **ML Systems Engineering:** This is not a data science project; it is an infrastructure project. It signals that you can build the plumbing that makes AI models viable in production, a skillset heavily requested for ML Platforms, Infra, and HPC roles.

## Architecture Overview

To build this kernel effectively, you need a clear separation between the high-level logic and the low-level hardware manipulation. The architecture consists of four primary components:

*   **The Memory Manager:** Handles the allocation and layout of input, kernel, and output tensors. It explicitly manages the stride—the number of elements to skip in memory to move to the next row or column—which is critical for avoiding cache misses.
*   **The Kernel Core:** The C++ function that performs the actual Multiply-Accumulate (MAC) operations. It iterates over the output spatial dimensions, applying the strided window to the input.
*   **The SIMD Abstraction:** A wrapper around hardware intrinsics (e.g., AVX2) that processes multiple INT8 values in parallel, widening them to INT16 or INT32 to prevent overflow during accumulation.
*   **The Python Binding:** A `pybind11` interface that allows you to call your C++ kernel from Python, enabling easy integration with standard ML workflows and testing frameworks.

```text
[Python Test Suite] 
       |
       v
[pybind11 Binding] 
       |
       v
[C++ Strided Conv Kernel] 
       |
       +---> [Memory Layout / Stride Calculator]
       |
       v
[AVX2 SIMD Intrinsics (INT8 -> INT16 MAC)]
       |
       v
[Hardware Execution]
```

## Building It Step by Step

We will use C++ for the core logic to ensure maximum performance and direct hardware access. The project will use `pybind11` to expose the kernel to Python.

### Step 1: Define the Strided Tensor Layout

Before computing anything, you must define how data is laid out in memory. A strided convolution means the kernel slides across the input with a step size greater than 1. We need a struct to track the dimensions and the strides.

```cpp
#include <vector>
#include <cstdint>

struct StridedTensor {
    std::vector<int8_t> data;
    size_t batches;
    size_t channels;
    size_t height;
    size_t width;
    // Strides in elements, not bytes
    size_t stride_batch;
    size_t stride_channel;
    size_t stride_height;
    size_t stride_width;
};
```

### Step 2: Implement the Naive Strided Loop

The baseline implementation iterates over the output spatial dimensions, applies the stride to find the corresponding input region, and computes the dot product. This is unoptimized but establishes the mathematical correctness.

```cpp
void naive_strided_conv(
    const StridedTensor& input, 
    const StridedTensor& kernel, 
    StridedTensor& output, 
    int stride_h, 
    int stride_w
) {
    for (size_t b = 0; b < output.batches; ++b) {
        for (size_t c = 0; c < output.channels; ++c) {
            for (size_t oh = 0; oh < output.height; ++oh) {
                for (size_t ow = 0; ow < output.width; ++ow) {
                    int32_t sum = 0;
                    // Map output position to input position via stride
                    size_t ih = oh * stride_h;
                    size_t iw = ow * stride_w;
                    
                    // Compute dot product over kernel and input channels
                    for (size_t kh = 0; kh < kernel.height; ++kh) {
                        for (size_t kw = 0; kw < kernel.width; ++kw) {
                            for (size_t ic = 0; ic < input.channels; ++ic) {
                                int8_t inp_val = input.data[
                                    (b * input.stride_batch) + 
                                    (ic * input.stride_channel) + 
                                    ((ih + kh) * input.stride_height) + 
                                    ((iw + kw) * input.stride_width)
                                ];
                                int8_t kern_val = kernel.data[
                                    (c * kernel.stride_channel) + 
                                    (ic * kernel.stride_channel) + 
                                    (kh * kernel.stride_height) + 
                                    (kw * kernel.stride_width)
                                ];
                                sum += static_cast<int32_t>(inp_val) * static_cast<int32_t>(kern_val);
                            }
                        }
                    }
                    // Clamp and store as INT8
                    output.data[b * output.stride_batch + c * output.stride_channel + oh * output.stride_height + ow * output.stride_width] = 
                        static_cast<int8_t>(std::max(-128, std::min(127, sum)));
                }
            }
        }
    }
}
```

### Step 3: Vectorize with AVX2 Intrinsics

The naive loop is bound by memory bandwidth and integer throughput. To unlock performance, we use AVX2 intrinsics to process 32 INT8 values simultaneously. We widen the INT8 values to INT16 using `_mm256_cvtepu8_epi16`, multiply, and accumulate.

```cpp
#include <immintrin.h>

void avx2_strided_mac(
    const int8_t* input_ptr, 
    const int8_t* kernel_ptr, 
    int32_t& sum
) {
    // Load 32 bytes of input and kernel
    __m256i inp_vec = _mm256_cvtepu8_epi16(_mm_loadu_si128(reinterpret_cast<const __m128i*>(input_ptr)));
    __m256i kern_vec = _mm256_cvtepu8_epi16(_mm_loadu_si128(reinterpret_cast<const __m128i*>(kernel_ptr)));
    
    // Multiply and accumulate
    __m256i prod = _mm256_mullo_epi16(inp_vec, kern_vec);
    __m256i sum_vec = _mm256_set1_epi32(sum);
    
    // Horizontal add to accumulate the 16-bit products into a 32-bit sum
    __m256i prod_lo = _mm256_unpacklo_epi16(prod, _mm256_setzero_si256());
    __m256i prod_hi = _mm256_unpackhi_epi16(prod, _mm256_setzero_si256());
    sum_vec = _mm256_add_epi32(sum_vec, prod_lo);
    sum_vec = _mm256_add_epi32(sum_vec, prod_hi);
    
    // Extract the sum
    alignas(32) int32_t temp[8];
    _mm256_store_si256(reinterpret_cast<__m256i*>(temp), sum_vec);
    sum = temp[0] + temp[1] + temp[2] + temp[3] + temp[4] + temp[5] + temp[6] + temp[7];
}
```

## Running and Testing It

To ensure your kernel is both correct and performant, you need a rigorous testing and benchmarking pipeline.

### Correctness Testing
You must verify that your optimized kernel produces the exact same results as the naive implementation. A robust approach is to generate random tensors, run both implementations, and assert a zero-difference output.

```bash
# CMake setup to compile the tests
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build
./build/conv_validation_test
```

```cpp
#include <cassert>
#include <random>

void test_correctness() {
    StridedTensor input = generate_random_tensor(1, 3, 32, 32);
    StridedTensor kernel = generate_random_tensor(64, 3, 3, 3);
    StridedTensor output_naive = create_empty_output(1, 64, 30, 30);
    StridedTensor output_avx = create_empty_output(1, 64, 30, 30);

    naive_strided_conv(input, kernel, output_naive, 1, 1);
    avx2_strided_conv(input, kernel, output_avx, 1, 1);

    for (size_t i = 0; i < output_naive.data.size(); ++i) {
        assert(output_naive.data[i] == output_avx.data[i]);
    }
}
```

### Benchmarking
Use `std::chrono` or a dedicated library like Google Benchmark to measure the throughput in GOPS (Giga Operations Per Second). A successful implementation should show a 4x to 8x speedup over the naive loop, directly attributable to the SIMD vectorization.

## Extending It: Your Roadmap to Senior-Level

A working kernel is a toy; a production-grade kernel is a system. To elevate this project to senior-level signaling, implement the following upgrades:

1. **Kernel Fusion:** Fuse the convolution with a subsequent ReLU and quantization step. *Reason: Minimizes DRAM round-trips, which is the primary bottleneck in inference.*
2. **Horizontal Scaling via gRPC:** Wrap the kernel in a gRPC service that splits large tensors across multiple worker nodes. *Reason: Proves you can scale compute beyond a single machine, a core requirement for production ML infra.*
3. **Hardware Observability:** Integrate `perf` or `PAPI` to monitor cache miss rates and Instructions Per Cycle (IPC) during execution. *Reason: Enables data-driven optimization and demonstrates production-grade debugging skills.*
4. **Fault Tolerance:** Add atomic operations and checkpointing for asynchronous kernel execution on shared memory. *Reason: Ensures system reliability under concurrent workloads, preventing silent data corruption.*
5. **Cross-Architecture CI:** Build a GitHub Actions pipeline that compiles and benchmarks the kernel on both x86 (AVX2) and ARM (NEON) architectures. *Reason: Guarantees performance regressions are caught early across diverse hardware, a hallmark of senior engineering.*

## Key Takeaways

*   **Memory layout dictates performance:** Optimizing how you traverse a tensor is often more impactful than optimizing the math itself.
*   **SIMD is non-negotiable for modern ML systems:** Writing scalar loops for AI inference is a relic of the past; vectorization is the baseline.
*   **Systems engineering bridges algorithms and silicon:** The ability to translate a high-level math operation into efficient hardware instructions is a rare and highly valued skill.
*   **Correctness must precede optimization:** An optimized bug is infinitely worse than a slow correct implementation; rigorous validation is mandatory.

## Further Reading

To deepen your understanding of the primitives and systems concepts explored in this guide, study the following canonical resources:

1. [Intel Intrinsics Guide](https://www.intel.com/content/www/us/en/docs/intrinsics-guide/) — The definitive reference for x86 SIMD instructions, essential for understanding the vectorization capabilities of modern CPUs.
2. [High Performance Convolutions for Deep Learning (Chellapilla et al.)](https://arxiv.org/abs/1606.05336) — A foundational paper that explores the algorithmic and memory-access optimizations required for fast convolutions.
3. [pybind11 Documentation](https://pybind11.readthedocs.io/en/stable/) — The canonical guide for creating Python bindings for C++ code, allowing you to integrate your high-performance kernels with the broader ML ecosystem.