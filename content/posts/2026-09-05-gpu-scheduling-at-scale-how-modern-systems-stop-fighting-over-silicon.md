---
title: "GPU Scheduling at Scale: How Modern Systems Stop Fighting Over Silicon"
date: "2026-09-05T18:54:32.916"
draft: false
tags: ["gpu-scheduling", "kubernetes", "ml-infrastructure", "cuda", "distributed-systems"]
description: "A working engineer's guide to GPU scheduling: time-slicing, MIG, multi-instance GPUs, and the schedulers that orchestrate accelerators in production."
summary: "GPUs are no longer exotic, but scheduling them well is still hard. This post walks through the policies, primitives, and production patterns that decide who gets the silicon."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-gpu-scheduling-at-scale-how-modern-systems-stop-fighting-over-silicon.svg"
  alt: "Abstract diagram of GPU scheduling queues feeding a rack of accelerators."
  caption: ""
  relative: false
---

> **TL;DR** — GPUs are the scarcest resource in modern AI infrastructure, and naive scheduling wastes 30–60% of their capacity. Production systems use a layered toolkit: hardware partitioning (MIG, MPS), kernel-level time-slicing, gang scheduling across nodes, and topology-aware placement. Choosing the right combination is the difference between a cluster that hums and one that melts down at peak load.

## Why GPU Scheduling Is Its Own Discipline

CPUs have been "shared" since the 1960s. GPUs, by contrast, were sold as discrete accelerators for decades — one job, one device, one user. That assumption broke the moment teams started running inference alongside training, serving multiple tenants on shared hardware, and stitching hundreds of accelerators into a single training job.

The mismatch is fundamental. A CPU is a latency-optimized, preemptible unit that the Linux scheduler has spent thirty years learning to share fairly. A modern GPU like an [NVIDIA H100](https://www.nvidia.com/en-us/data-center/h100/) is a throughput-optimized monster with 80 GB of HBM3, 3 TB/s of memory bandwidth, and a CUDA context that costs hundreds of milliseconds to set up and several gigabytes of VRAM to keep alive. Treating it like "a fast CPU" produces queues that starve, jobs that OOM each other, and clusters where everyone complains that "the GPUs are busy but nothing is running."

This post walks through the layers a working engineer needs to understand: the hardware primitives, the kernel mechanisms, the cluster schedulers, and the patterns that actually hold up in production.

## The Anatomy of a GPU "Job"

Before talking about scheduling, it's worth being precise about what we're scheduling. A typical GPU workload has three properties that matter to a scheduler:

1. **VRAM footprint.** A 70B-parameter model in fp16 weights is ~140 GB. It cannot share a device with anything else. A 7B fine-tune might fit alongside a small inference server.
2. **Kernel sensitivity.** Some kernels are latency-critical (interactive inference, online features). Others are throughput-critical (training). Co-locating them can hurt both.
3. **Multi-GPU coupling.** A tensor-parallel training job needs its GPUs to talk over NVLink at microsecond latencies. A data-parallel job tolerates slower PCIe or even cross-node links.

A scheduler that ignores any of these will make bad decisions. The rest of this post is about how production systems handle them.

## Hardware Primitives: Partitioning the Device

The first lever is the silicon itself. Modern accelerators expose hardware-level partitioning that lets multiple tenants share one physical device safely.

### Multi-Instance GPU (MIG)

MIG is NVIDIA's answer to "what if a GPU were actually several GPUs." On an H100, you can carve a single 80 GB device into up to seven isolated instances, each with its own memory, cache, and compute pipelines. From CUDA's perspective, an MIG instance is just a GPU — the same `cudaMalloc`, the same kernel launch, the same NCCL primitives.

This is the gold standard for hard isolation. Two tenants cannot OOM each other, cannot interfere through cache contention, and cannot crash each other's contexts. The cost is flexibility: an instance is statically sized, and changing the partition requires a reset of the device.

In practice, MIG is used for production inference fleets where predictable tail latency matters more than peak throughput. Google documents their MIG strategy in the [GPU sharing guide for GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/timesharing-gpus), where MIG slices are mapped to Kubernetes device plugins.

### Multi-Process Service (MPS)

MPS predates MIG and is more permissive. Where MIG carves the hardware, MPS merges multiple CUDA contexts into a single hypervisor process, allowing kernels from different processes to coexist on the streaming multiprocessors with hardware-level prioritization.

The upside is flexibility: you can oversubscribe a GPU by 2x or 3x and let the hardware arbitrate. The downside is that MPS is *not* a memory isolator — one process can still OOM the device and take down everyone. As the [CUDA MPS docs](https://docs.nvidia.com/deploy/mps/) put it, MPS is about compute concurrency, not fault isolation.

MPS shines for throughput workloads where jobs are well-behaved and want to share SM cycles — for example, multiple small inference replicas on one H100.

### Time-Slicing

Time-slicing is the simplest model: multiple processes hold CUDA contexts to the same GPU, and the kernel scheduler round-robins between them. Each process thinks it owns the device.

The catch is VRAM. All contexts are resident simultaneously, so memory is the binding constraint, not compute. Time-slicing is great for development environments (the canonical use case in the [NVIDIA GPU Operator docs](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)) and disastrous for production inference where latency tails blow out under context-switch pressure.

## Kernel-Level Mechanisms

Even with hardware partitioning, the GPU kernel scheduler is doing real work. Understanding it explains many "why is my job slow?" tickets.

Modern CUDA dispatches kernels through a hardware work queue. The GPU's schedulers pick up work from this queue with priorities and preemption rules that depend on the device. On Volta and later, kernels are preemptible at the instruction boundary — but preemption still costs a context save/restore measured in microseconds to milliseconds, depending on state.

Two mechanisms matter operationally:

- **Stream priorities.** CUDA streams carry a priority hint that the hardware scheduler honors. Inference frameworks like [vLLM](https://docs.vllm.ai/) and TensorRT-LLM use this to keep prefill kernels from starving decode kernels on the same device.
- **Kernel preemption modes.** The driver can be configured to either drain the running kernel before switching or to preempt mid-kernel. Mid-kernel preemption is faster to respond but can cause numerical drift in long-running reductions; draining is safer but slower.

These are knobs that production schedulers expose as quality-of-service hints.

## Cluster Schedulers: The Orchestration Layer

Hardware primitives get you shared silicon. They do not get you fair allocation across a 1,000-node cluster. That is the job of a cluster scheduler.

### Kubernetes with the GPU Operator

The de facto stack is [Kubernetes](https://kubernetes.io/) plus the [NVIDIA GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html). The Operator deploys the drivers, the device plugin, and the monitoring stack. Workloads request GPUs through extended resources:

```yaml
apiVersion: v1
kind: Pod
spec:
  containers:
  - name: trainer
    resources:
      limits:
        nvidia.com/gpu: 8
        nvidia.com/mig-1g.10gb: 1   # alternative: request a MIG slice
```

The default Kubernetes scheduler is a bin-packing, gang-ignorant scheduler that fills nodes one at a time. That is fine for CPU workloads but disastrous for distributed training, where partial allocation wastes every allocated GPU. A 16-GPU job that only got 8 GPUs sits there forever, blocking 8 GPUs that no other job can use.

### Gang Schedulers

A gang scheduler is one that allocates atomically — either all the resources a job needs, or none. This is non-negotiable for distributed training.

The two open-source options that dominate production:

- **[Volcano](https://volcano.sh/).** A CNCF incubating project, originally built at Huawei. Adds gang scheduling, queue management, fair-share, and topology plugins to Kubernetes. Most teams running training on EKS or self-hosted K8s use Volcano.
- **[Kueue](https://kueue.sigs.k8s.io/).** A newer, simpler job-queueing layer from SIG Scalability. Kueue does not replace the scheduler; it gates admission and leaves gang semantics to Volcano or other plugins. This separation of concerns is increasingly popular.

For very large fleets, some teams build on top of [Slurm](https://slurm.schedmd.com/documentation.html), which has been scheduling HPC and ML workloads for years and has first-class support for GPU topology, GRES, and exclusive node allocation.

### Topology-Aware Placement

On a DGX H100 node, eight GPUs are connected by NVLink in a specific topology. Not every pair has the same bandwidth. On an H100 SuperPod, multiple nodes are connected by NVLink over InfiniBand in a rail-optimized fabric. Where you place a process determines how fast it can talk to its peers.

A topology-aware scheduler labels nodes with their GPU-to-GPU bandwidth matrix and packs communication-heavy jobs onto high-bandwidth pairs. Volcano's [topology plugin](https://volcano.sh/en/docs/plugins/#topology) does this; so does the [GKE TPU/GPU topology-aware scheduling feature](https://cloud.google.com/kubernetes-engine/docs/how-to/topology-aware-scheduling).

The failure mode without this is brutal: a job that places ranks across NVLink boundaries where it expected NVLink can spend more time in collectives than in compute.

## Patterns in Production

Theory aside, here is what working deployments actually look like.

### Inference Fleets on Shared Hardware

A typical inference platform runs tens to hundreds of models behind a router. Models range from 1B to 70B parameters; traffic is bursty and latency-sensitive. The pattern:

1. Bin models by VRAM footprint.
2. Pack small models onto MIG slices or MPS-served GPUs.
3. Reserve full GPUs for the few large models that need them.
4. Use a queueing layer (Kueue) so that oversubscribed models queue rather than OOM.

The result is 2–4x higher GPU utilization than naive one-model-per-GPU placement, with predictable p99 latencies as long as the bin-packing respects MIG boundaries.

### Training Fleets with Preemption

Training jobs run for hours to weeks. Cluster operators want to pack them tightly; users want their job to never be preempted. The standard compromise is priority queues with preemption thresholds:

- High-priority queue: short, debug, and interactive jobs. Can preempt anything below.
- Medium-priority queue: standard training. Can preempt low.
- Low-priority queue: research, sweeps, hyperparameter searches. Anything can preempt these.

This is exactly the model Volcano implements with its [preemption and reclaim](https://volcano.sh/en/docs/preemption/) features, and it is how most large research labs run.

### Hybrid Training-and-Serving Clusters

Some teams — notably smaller ones — run training and inference on the same cluster. This is the hardest case because the workloads have opposite profiles: training wants all GPUs for hours; serving wants partial GPUs forever.

The production answer is **separate node pools with oversubscription tiers**:

- A "training" pool of bare-metal GPU nodes, fully allocated.
- A "serving" pool of MIG-partitioned nodes, oversubscribed 3x via time-slicing.
- A small "spot" pool that hosts hyperparameter sweeps and preempts on demand.

A scheduler like Volcano with multi-cluster queueing (or a two-cluster deployment) keeps them separated while letting operators rebalance capacity nightly.

## Observability: Knowing When It Is Broken

You cannot schedule what you cannot measure. The minimum observability stack for a GPU fleet:

- **DCGM exporter** for per-GPU telemetry: utilization, memory, temperature, ECC errors, MIG slice usage.
- **Prometheus** for time-series storage; **Grafana** dashboards built from the [NVIDIA DCGM dashboards](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/getting-started.html#monitoring).
- **Per-job attribution.** The hard part. DCGM tells you the device is busy; it does not tell you which of the seven MIG tenants is hot. The answer is process-level telemetry via [pyNVML](https://pypi.org/project/pynvml/) or the `nvidia-smi` CSV output piped into your metrics pipeline.

A useful derived metric is **VRAM wasted**, computed as `1 - allocated_vram / total_vram` averaged across the fleet. Anything above 30% is a sign that bin-packing or MIG sizing is off.

## Common Failure Modes

A non-exhaustive list of things that bite teams in production:

- **Context-spam OOM.** Time-slicing many small jobs onto a GPU until the resident contexts exceed VRAM, at which point the next `cudaMalloc` fails and a random job crashes.
- **NVLink hotspotting.** Allocating a job that wants all-to-all communication without checking the topology, causing 10x slowdown in collectives.
- **MIG reset storms.** Re-partitioning a GPU is not free; doing it on every autoscaling event burns minutes per device.
- **Gang-scheduler starvation.** Without backfill, small jobs wait behind a large job that needs almost all the cluster.
- **Preemption without checkpointing.** Killing a training job that has not checkpointed in 6 hours is a 6-hour loss. Schedulers should respect checkpoint cadence.

## Key Takeaways

- GPUs are *not* fast CPUs. Treat them as throughput-optimized, VRAM-bound, kernel-sensitive accelerators with non-trivial context costs.
- Partition at the hardware level whenever you can. MIG gives true isolation; MPS gives compute concurrency; time-slicing gives flexibility with the least guarantees.
- Use gang scheduling for distributed training. Default Kubernetes bin-packing will burn your cluster.
- Respect topology. NVLink bandwidth between GPUs is not uniform, and collectives will show you that quickly.
- Observe per-job, not per-device. Aggregate GPU utilization hides the real story.
- Match the scheduler to the workload class. Inference, training, and research each want different queues, priorities, and preemption policies.

## Further Reading

- [NVIDIA Multi-Instance GPU User Guide](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/index.html)
- [Volcano Scheduler Documentation](https://volcano.sh/en/docs/)
- [Kueue: Kubernetes-native Job Queueing](https://kueue.sigs.k8s.io/docs/concepts/)
- [Google Cloud: Time-Sharing and MIG on GKE](https://cloud.google.com/kubernetes-engine/docs/concepts/timesharing-gpus)
- [Slurm Quick Start for GPU Scheduling](https://slurm.schedmd.com/quickstart.html)
- [DCGM-Exporter GitHub Repository](https://github.com/NVIDIA/dcgm-exporter)