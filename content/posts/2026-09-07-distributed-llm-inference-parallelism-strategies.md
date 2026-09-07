---
title: "Distributed LLM Inference: Parallelism Strategies"
date: "2026-09-07T20:48:57.578"
draft: false
tags: ["distributed systems", "LLM inference", "tensor parallelism", "pipeline parallelism", "vLLM", "deep learning infrastructure"]
description: "A deep dive into the parallelism strategies powering distributed LLM inference at scale — from tensor and pipeline parallelism to expert parallelism and practical deployment patterns."
summary: "Exploring the core parallelism strategies behind distributed LLM inference — tensor, pipeline, data, and expert parallelism — with real-world architecture patterns and practical deployment insights."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-distributed-llm-inference-parallelism-strategies.svg"
  alt: "Abstract visualization of distributed GPU clusters processing large language model inference requests"
  caption: ""
  relative: false
---

> **TL;DR** — Serving large language models at scale demands a careful interplay of tensor, pipeline, data, and expert parallelism. Each strategy attacks a different bottleneck — memory bandwidth, compute saturation, or throughput — and modern serving engines like vLLM and Megatron-LM compose them into hybrid schemes that push billions of parameters through GPUs with sub-second latency.

## Introduction

A 70-billion-parameter model doesn't fit on a single GPU. Even a 7-billion-parameter model strains the memory of an A100 with 80 GB of VRAM once you account for the KV cache, activation buffers, and the overhead of a serving framework. The question isn't whether to distribute inference across devices — it's how.

Distributed LLM inference sits at the intersection of hardware constraints, model architecture, and latency requirements. The parallelism strategy you choose determines whether your serving stack delivers 10 ms tokens per user or 2 seconds of buffering. It dictates how many GPUs you need, how much networking bandwidth you burn, and how gracefully the system degrades under load.

This post breaks down the principal parallelism strategies used in production today, explains the architectural trade-offs behind each one, and shows how modern serving engines compose them into hybrid configurations.

## The Memory Wall: Why Distribution Is Non-Negotiable

Before discussing strategies, it helps to understand what makes distribution necessary. A transformer model's weights, activations, and KV cache all compete for the same finite GPU memory pool.

For a model with `P` parameters stored in FP16, the weight footprint alone is `2P` bytes. A 70B-parameter model occupies roughly 140 GB — far beyond a single accelerator. During inference, the KV cache adds another dimension: for each layer, each head, and each token position, you store key and value tensors. For a sequence of length `L`, `H` heads, and hidden dimension `d`, the per-token KV cache per layer is `2 · L · H · d · 2` bytes in FP16.

This is where parallelism strategies enter. They partition the model state, the computation, or the data stream across multiple devices so that no single GPU bears the full burden.

## Tensor Parallelism

Tensor parallelism (TP) splits individual layers of the transformer across GPUs. Within a single layer, different weight matrices or activations are partitioned, and each GPU computes a slice of the forward pass. The GPUs must synchronize after each split operation, typically using all-reduce communications.

### How It Works

Consider a linear layer `Y = X · W^T`, where `W` is partitioned column-wise across two GPUs. GPU 0 computes `X · W_0^T` and GPU 1 computes `X · W_1^T`. The results are concatenated via an all-reduce to produce `Y`. For row-wise partitioning, the input `X` is split instead, and the output is reduced.

```python
# Conceptual illustration of column-wise tensor parallelism
# Each GPU holds a shard of the weight matrix
class LinearTP(nn.Module):
    def __init__(self, in_features, out_features, num_gpus):
        self.shard_size = out_features // num_gpus
        self.gpu_rank = get_rank()
        self.weight_shard = load_weight_shard(
            full_weight, self.gpu_rank, self.shard_size
        )

    def forward(self, x):
        # Each GPU computes its slice of the output
        partial_out = F.linear(x, self.weight_shard)
        # Synchronize across GPUs
        full_out = all_reduce(partial_out)
        return full_out
```

### Strengths and Limitations

Tensor parallelism excels at reducing per-GPU memory for model weights. Since each GPU holds only a fraction of the parameters, even very large models can be served on a single node with NVLink-bound communication. The downside is that every forward pass requires synchronization — all-reduce operations that introduce latency proportional to the number of GPUs and the interconnect bandwidth.

In practice, tensor parallelism is most effective within a single server where NVLink or NVSwitch provides high-bandwidth, low-latency communication between GPUs. Stretching tensor parallelism across racks introduces network bottlenecks that quickly erode its benefits.

## Pipeline Parallelism

Pipeline parallelism (PP) takes a coarser approach: it partitions the model's layers across GPUs, so each GPU owns a contiguous block of layers. The model becomes a pipeline, and micro-batches flow through stages sequentially.

### How It Works

A 32-layer transformer might be split across four GPUs, with each GPU holding eight layers. GPU 0 processes the first eight layers and passes the activation to GPU 1, which processes the next eight, and so on. The key innovation is **micro-batching**: instead of sending one batch through the entire pipeline, the scheduler breaks the batch into smaller micro-batches and overlaps computation with communication.

```python
# Pipeline parallelism schedule illustration (GPipe-style)
# Four stages, four micro-batches
schedule = [
    # Time step 0
    {"stage_0": "forward_m0", "stage_1": "idle", "stage_2": "idle", "stage_3": "idle"},
    # Time step 1
    {"stage_0": "forward_m1", "stage_1": "forward_m0", "stage_2": "idle", "stage_3": "idle"},
    # Time step 2
    {"stage_0": "forward_m2", "stage_1": "forward_m1", "stage_2": "forward_m0", "stage_3": "idle"},
    # Time step 3
    {"stage_0": "forward_m3", "stage_1": "forward_m2", "stage_2": "forward_m1", "stage_3": "forward_m0"},
]
```

### Strengths and Limitations

Pipeline parallelism scales to very large model sizes because each GPU only needs to hold a fraction of the layers. It also reduces communication overhead compared to tensor parallelism, since inter-stage communication happens only at layer boundaries rather than at every operation.

The primary cost is **pipeline bubble** — idle time when GPUs wait for the pipeline to fill and drain. With `N` stages and `B` micro-batches, the bubble overhead is roughly `N/B` of total execution time. Techniques like 1F1B (one forward, one backward) scheduling and interleaved pipeline parallelism reduce this bubble but add scheduling complexity.

## Data Parallelism

Data parallelism (DP) replicates the entire model on each GPU and splits the input batch across devices. Each GPU performs a full forward and backward pass independently, then synchronizes gradients or, in the inference case, merges results.

### How It Works in Inference

During inference, data parallelism is conceptually straightforward: each GPU holds a complete copy of the model and processes a subset of incoming requests. A load balancer routes requests to available GPUs, and each GPU produces outputs independently.

```python
# Data parallelism for inference — simple request routing
class DataParallelInference:
    def __init__(self, model, num_gpus):
        self.models = [load_model_copy(model) for _ in range(num_gpus)]
        self.request_queue = RingBuffer(num_gpus)

    def route_request(self, request):
        gpu_id = self.request_queue.next_slot()
        return self.models[gpu_id].generate(request)
```

### Strengths and Limitations

Data parallelism is the simplest strategy to implement and provides near-linear throughput scaling: double the GPUs, roughly double the requests per second. The cost is memory — each GPU must hold the full model, so the total memory footprint is `num_gpus × model_size`. For a 70B model in FP16, that means 140 GB per GPU, which is infeasible without extreme hardware.

In practice, data parallelism is often combined with other strategies. A common pattern is to use tensor parallelism within a node to fit the model, and data parallelism across nodes to scale throughput.

## Expert Parallelism

Expert parallelism (EP) emerges from the Mixture-of-Experts (MoE) architecture, where each transformer layer contains multiple "expert" sub-networks, and a router selects a subset of experts per token. Since different tokens activate different experts, the experts can be distributed across GPUs.

### How It Works

In an MoE layer with `E` experts and `N` GPUs, each GPU might host `E/N` experts. When a token's router selects experts, the system must route the token's activation to the GPU holding the selected expert, perform the computation there, and return the result. This introduces all-to-all communication patterns that are more complex than the collective operations used in tensor or pipeline parallelism.

```python
# Expert parallelism concept — router dispatches tokens to expert shards
class MoELayerTP:
    def __init__(self, num_experts, experts_per_gpu):
        self.local_experts = load_expert_shards(num_experts, experts_per_gpu)
        self.router = TopKGate(num_experts, top_k=2)

    def forward(self, x):
        scores, indices = self.router(x)
        # Dispatch tokens to GPUs holding selected experts
        dispatched = all_to_all(x, indices)
        # Compute on each GPU with its local experts
        output = compute_local_experts(dispatched, self.local_experts)
        # Combine results
        return all_gather(output)
```

### Strengths and Limitations

Expert parallelism allows models with trillions of parameters to be served with manageable per-GPU memory, because only the active experts consume compute and memory for any given token. The trade-off is communication complexity: the all-to-all routing pattern can become a bottleneck, especially when the number of experts per GPU is small and the inter-GPU network is constrained.

Systems like DeepSeek-MoE and Mixtral have demonstrated that MoE architectures can achieve quality comparable to dense models while dramatically reducing active parameter count per token, making EP a compelling strategy for frontier-scale inference.

## Hybrid Strategies in Production

No single parallelism strategy is sufficient for modern LLM serving. Production systems compose multiple strategies to balance memory, compute, and communication.

### The 3D Parallelism Pattern

The canonical hybrid approach combines tensor, pipeline, and data parallelism into a three-dimensional grid:

- **Tensor parallelism** fits the model within a node (NVLink-connected GPUs).
- **Pipeline parallelism** spreads the model across nodes.
- **Data parallelism** replicates the pipeline across additional nodes for throughput.

```
Total GPUs = TP × PP × DP
Example: TP=8, PP=4, DP=2 → 64 GPUs for a single model replica
```

This pattern is the backbone of Megatron-LM and is widely adopted in cloud-based LLM serving deployments. The key engineering challenge is scheduling: the system must manage micro-batch flow through the pipeline while keeping all tensor-parallel groups synchronized and load-balancing data-parallel replicas.

### vLLM and PagedAttention

Modern serving engines like vLLM have introduced optimizations that reshape how parallelism interacts with memory management. vLLM's PagedAttention borrows the concept of virtual memory paging from operating systems, allowing the KV cache to be allocated and deallocated in variable-sized blocks rather than pre-allocated contiguous regions.

This doesn't replace parallelism strategies — it makes them more efficient. By reducing KV cache fragmentation, PagedAttention allows higher GPU utilization under dynamic request patterns, which means the data-parallel replicas can serve more requests per unit of time.

```python
# vLLM's PagedAttention conceptually manages KV cache blocks
class PagedKVCache:
    def __init__(self, block_size, num_blocks):
        self.block_size = block_size
        self.free_blocks = Pool(num_blocks)
        self.block_tables = {}  # maps request_id → list of block addresses

    def allocate(self, request_id, num_tokens):
        blocks_needed = ceil(num_tokens / self.block_size)
        blocks = self.free_blocks.allocate(blocks_needed)
        self.block_tables[request_id] = blocks

    def deallocate(self, request_id):
        blocks = self.block_tables.pop(request_id)
        self.free_blocks.release(blocks)
```

### Offloading and Hybrid Parallelism

When GPU memory is the binding constraint, some systems offload portions of the model to CPU memory or NVMe storage. Offloading strategies include:

- **Weight offloading**: Keep activations on GPU, swap weights in and out.
- **KV cache offloading**: Move older KV cache blocks to CPU RAM.
- **Layer offloading**: Place entire transformer layers on CPU, with GPU performing the compute.

Offloading trades latency for capacity. The memory bandwidth of PCIe or NVLink becomes the critical path, and careful overlap of computation with data transfer is essential to avoid catastrophic slowdowns.

## Architecture Patterns in Production

### Pattern 1: The Node-Local Tensor Parallel Group

This is the most common production pattern. Within each server, 8 GPUs are connected via NVLink and form a single tensor-parallel group. Pipeline parallelism spans servers, and data parallelism replicates the pipeline. The advantage is that all intra-node communication stays on the ultra-fast NVLink fabric, while only inter-node communication traverses the slower network.

### Pattern 2: The Disaggregated Serving Pipeline

Some architectures split prefill and decode phases across different GPU clusters. Prefill (processing the input prompt) is compute-intensive and benefits from large batch sizes, while decode (generating tokens) is memory-bandwidth-bound. By running prefill on one set of GPUs and decode on another, each cluster can be optimized for its workload. This pattern is used in systems like DistServe and SplitWise.

### Pattern 3: The Speculative Decoding Pipeline

Speculative decoding uses a small "draft" model to generate candidate tokens in parallel, then a large "target" model verifies them in a single forward pass. This pattern introduces a novel parallelism dimension: the draft model runs on cheaper GPUs while the target model runs on expensive GPUs, and the two pipelines must synchronize at each verification step.

## Practical Considerations

### Choosing the Right Strategy

The right parallelism configuration depends on three factors:

1. **Model size**: If the model doesn't fit in a single GPU's memory, tensor parallelism is mandatory. If it doesn't fit across a node, pipeline parallelism becomes necessary.
2. **Throughput requirements**: Data parallelism scales throughput linearly but requires full model replication.
3. **Latency budget**: Tensor parallelism adds synchronization latency per layer; pipeline parallelism adds bubble overhead. For low-latency serving, minimizing the number of communication rounds is paramount.

### Failure Modes

Distributed inference introduces failure modes that don't exist in single-GPU serving:

- **Stragglers**: A slow GPU in a tensor-parallel group stalls the entire forward pass.
- **Network partitions**: If inter-node links fail, pipeline stages become unreachable.
- **Memory fragmentation**: Poor KV cache management leads to out-of-memory errors under load, even when aggregate memory appears sufficient.

Monitoring and observability must account for these distributed failure modes. Per-GPU metrics, per-stage latency histograms, and communication-time profiling are essential debugging tools.

## Key Takeaways

- **Tensor parallelism** splits layers across GPUs and is essential for fitting large models, but requires high-bandwidth interconnects like NVLink to avoid communication bottlenecks.
- **Pipeline parallelism** partitions layers across nodes and scales model size, but introduces pipeline bubble overhead that must be mitigated through micro-batch scheduling.
- **Data parallelism** is the simplest throughput-scaling strategy but requires each GPU to hold a full model copy, making it impractical as a standalone solution for frontier-scale models.
- **Expert parallelism** unlocks trillion-parameter MoE models by distributing experts across GPUs, with the cost of complex all-to-all communication patterns.
- **Hybrid configurations** combining TP, PP, and DP are the production norm, and the optimal ratio depends on model size, hardware topology, and latency requirements.
- **Modern serving engines** like vLLM add critical memory-management optimizations (PagedAttention, speculative decoding) that improve the efficiency of any parallelism strategy.

## Further Reading

- [Megatron-LM: Training Multi-Billion Parameter Language Models Using Model Parallelism](https://github.com/NVIDIA/Megatron-LM) — NVIDIA's seminal framework for tensor and pipeline parallelism in transformer training and inference.
- [vLLM: Easy, Fast, and Cheap LLM Serving with PagedAttention](https://vllm.readthedocs.io/en/stable/) — The official documentation for vLLM, covering PagedAttention architecture and serving configurations.
- [DeepSpeed: System Optimizations for Scaling Transformer Training and Inference](https://www.deepspeed.ai/) — Microsoft's framework for distributed training and inference, including ZeRO optimizations and pipeline parallelism.
- [DeepSeek-MoE: Mixture-of-Experts Language Models](https://arxiv.org/abs/2201.05596) — The paper introducing the Mixtral-style MoE architecture and expert parallelism strategies.
- [SplitWise: Efficient Creative Large Language Model Serving Using Disaggregated Prefill and Decoding](https://arxiv.org/abs/2307.03172) — Research on disaggregating prefill and decode phases across separate GPU clusters.
- [The Illustrated Transformer](https://jalammar.github.io/illustrated-transformer/) — Jay Alammar's visual guide to transformer architecture, useful for understanding the layer structure that parallelism strategies partition.