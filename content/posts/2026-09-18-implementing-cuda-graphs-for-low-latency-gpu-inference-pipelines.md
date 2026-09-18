

---
title: "Implementing CUDA Graphs for Low-Latency GPU Inference Pipelines"
date: "2026-09-18T09:00:54.413"
draft: false
tags: ["CUDA", "GPU", "Inference", "Low-Latency", "Deep Learning", "Performance"]
description: "Learn how to use CUDA Graphs to reduce latency and boost throughput in GPU inference pipelines with practical examples and performance tips."
summary: "CUDA Graphs capture and replay GPU workloads, reducing kernel launch overhead and cutting inference latency by up to 40% in production systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-implementing-cuda-graphs-for-low-latency-gpu-inference-pipelines.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — CUDA Graphs let you record a sequence of GPU operations once and replay them with minimal overhead, dramatically lowering latency for inference pipelines. By capturing the entire forward pass, you eliminate per‑kernel launch costs and can launch the whole model in a single API call. This technique is especially effective for small batch sizes and latency‑sensitive serving scenarios.

GPU inference has become the backbone of modern machine‑learning services, but as models grow, the overhead of launching individual kernels can dominate latency, especially when serving many small requests. In production environments, every microsecond matters: users expect sub‑millisecond responses, and hardware must be pushed to its limits without wasting cycles on driver calls. CUDA Graphs provide a way to turn a series of kernel launches into a single, replayable unit, slashing the CPU‑to‑GPU synchronization cost and freeing up host resources for other tasks.

## The Latency Bottleneck in GPU Inference

When a request arrives, the typical flow is:

1. **Host‑side preprocessing** – tokenization, padding, feature extraction.  
2. **Data transfer** – copy input tensors from host to device memory.  
3. **Kernel execution** – a sequence of CUDA kernels (e.g., matrix multiplies, activations, attention).  
4. **Result retrieval** – copy output back to host.

Each kernel launch involves a syscall, driver overhead, and a round‑trip to the GPU. For a model with hundreds of kernels, this overhead can exceed the actual compute time, especially for small batch sizes. The problem is amplified in multi‑tenant serving systems where the CPU must orchestrate many concurrent requests.

## CUDA Graphs: A Primer

CUDA Graphs address this by **capturing** a stream of CUDA operations into a graph object and then **replaying** it with a single launch. The graph records memory allocations, kernel launches, and memory copies, but defers their execution until the replay call.

### How CUDA Graphs Work

- **Capture phase** – you begin a graph capture on a CUDA stream; all subsequent CUDA API calls (kernels, memcpy, etc.) are recorded as nodes.  
- **Construction** – the captured nodes form a directed acyclic graph (DAG) that preserves dependencies.  
- **Replay** – invoking `cudaGraphLaunch` (or the equivalent PyTorch API) executes the entire DAG with minimal driver involvement.

Because the driver only sees one launch, the per‑kernel overhead is eliminated. The graph can be reused across many inference requests, making it ideal for repetitive workloads.

### Capturing a Graph

Below is a minimal C++ example that captures a simple two‑kernel pipeline:

```cpp
// Capture a CUDA Graph
cudaGraph_t graph;
cudaGraphExec_t exec;
cudaStream_t stream;

cudaStreamCreate(&stream);
cudaGraphCreate(&graph, 0);

// Begin capture
cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal);

// Record kernels (placeholder calls)
someKernel<<<...>>>(...);
anotherKernel<<<...>>>(...);

// End capture
cudaStreamEndCapture(stream, &graph);

// Instantiate the graph for later launch
cudaGraphInstantiate(&exec, graph, nullptr, nullptr, 0);
```

In Python with PyTorch, the same idea is exposed via `torch.cuda.CUDAGraph`:

```python
import torch

# Define model
model = MyModel().cuda()
example_input = torch.randn(1, 3, 224, 224).cuda()

# Capture the forward pass
with torch.cuda.CUDAGraph() as g:
    output = model(example_input)

# Later, replay the graph for new inputs
new_input = torch.randn(1, 3, 224, 224).cuda()
# (Assuming the model's parameters are unchanged)
g.replay()
```

The key is that the graph is created **once** during warm‑up, then replayed for each request, avoiding repeated kernel launch overhead.

### Replaying a Graph

Replay is a single API call. In C++ you would use:

```cpp
cudaGraphLaunch(exec, stream);
```

In PyTorch, `g.replay()` triggers the same mechanism. The GPU executes the entire DAG, and the host can continue processing other work while the GPU runs.

## Architecture: Integrating CUDA Graphs into an Inference Pipeline

A production inference service typically consists of:

- **Request router** – dispatches incoming queries to GPU workers.  
- **Pre‑processing service** – tokenizes, pads, and prepares tensors.  
- **GPU worker** – runs the model and returns logits or embeddings.  
- **Post‑processing service** – decodes outputs, applies NMS, etc.

To leverage CUDA Graphs, the GPU worker should:

1. **Capture the model graph** at startup (or after the first request).  
2. **Replace per‑request kernel launches** with a single graph replay.  
3. **Handle dynamic shapes** by either capturing multiple graphs (one per shape) or using graph‑capture with conditional nodes (CUDA 11.2+).  

The following diagram (conceptual) shows the flow:

```
[Request Router] → [Pre‑process] → [GPU Worker] → [Post‑process]
                                 │
                          ┌──────┴──────┐
                          │  CUDA Graph  │
                          │  (capture)   │
                          └──────┬──────┘
                                 │
                          ┌──────┴──────┐
                          │  Replay     │
                          └──────┬──────┘
```

Because the graph is immutable, any change to the model (e.g., different weights) requires a new capture. In practice, you capture a graph for each distinct input shape and switch between them at runtime.

## Patterns in Production

### 1. Warm‑up and Graph Caching

Most frameworks (TensorRT, PyTorch, TensorFlow) provide hooks to capture a graph during a warm‑up pass. The captured graph is stored in a thread‑safe cache keyed by input shape and batch size.

```python
graph_cache = {}

def get_graph(model, input_shape):
    if input_shape not in graph_cache:
        # Create dummy input
        dummy = torch.empty(input_shape, device='cuda')
        with torch.cuda.CUDAGraph() as g:
            model(dummy)
        graph_cache[input_shape] = g
    return graph_cache[input_shape]
```

### 2. Dynamic Batching vs. Static Graphs

Dynamic batching aggregates multiple requests into a larger batch to improve GPU utilization. However, varying batch sizes break graph immutability. Solutions include:

- **Multiple graphs** – pre‑capture graphs for common batch sizes (1, 2, 4, 8, …).  
- **Graph with conditional nodes** – use CUDA 11.2’s `cudaGraphAddConditionalNode` to branch inside the graph, but this adds complexity.  
- **Fallback to regular launches** for rare shapes, keeping the common path on graphs.

### 3. Multi‑GPU Deployment

In a multi‑GPU setup, each device needs its own set of graphs. The capture must be performed on the target stream, and replay should use the same stream. NVLink or PCIe topology can affect graph launch latency; profiling with `ncu` is recommended.

## Performance Considerations

- **Memory overhead** – a captured graph stores kernel parameters and memory addresses, typically adding a few hundred kilobytes per graph. This is negligible compared to model weights.  
- **Capture time** – the first capture incurs a one‑time cost (usually < 100 ms for a medium‑size model). Subsequent replays are near‑zero.  
- **Speedup** – benchmarks on an A100 GPU show a **30–45 % reduction** in end‑to‑end latency for batch size 1 inference when using CUDA Graphs versus regular kernel launches. For batch size 8, the improvement drops to ~10 % because kernel launch overhead is amortized over more work.  
- **Limitations** – graphs cannot be modified after instantiation; any change in control flow (e.g., early exit) requires a new capture. Also, graphs are not compatible with asynchronous memory operations that are not part of the capture.

## Key Takeaways

- CUDA Graphs transform a sequence of kernel launches into a single replayable unit, eliminating per‑kernel driver overhead.  
- Capture the graph once during warm‑up, then reuse it for every request to achieve the lowest latency.  
- For variable input shapes, maintain a cache of graphs or use conditional nodes to stay on the graph path.  
- In production, combine graph replay with dynamic batching and multi‑GPU orchestration for maximum throughput.  
- Measure with profiling tools (Nsight Compute, `ncu`) to confirm the expected latency reduction for your specific model.

## Further Reading

- [NVIDIA CUDA Graphs Guide](https://developer.nvidia.com/blog/cuda-graphs/) – official overview and best practices.  
- [CUDA Programming Guide: CUDA Graphs](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#cuda-graphs) – deep dive into the API.  
- [CUDA Graphs Sample Code](https://github.com/NVIDIA/cuda-samples/tree/master/Samples/cudaGraphs) – runnable examples in C++ and Python.  
- [TensorRT: High‑Performance Deep Learning Inference](https://developer.nvidia.com/tensorrt/) – how TensorRT leverages CUDA Graphs for optimized serving.