---
title: "Architecting NVIDIA MIG: Virtualizing GPU Resources in Containerized Environments"
date: "2026-10-14T10:01:19.217"
draft: false
tags: ["NVIDIA", "MIG", "GPU", "Kubernetes", "Containers", "Virtualization"]
description: "Learn how NVIDIA MIG partitions GPUs into isolated instances for containerized workloads, with architecture patterns and production best practices."
summary: "NVIDIA MIG lets you slice a single GPU into multiple isolated instances, each with dedicated memory and compute. This post covers the architecture, Kubernetes integration, and production patterns for deploying MIG in containerized environments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-14-architecting-nvidia-mig-virtualizing-gpu-resources-in-containerized-environments.svg"
  alt: "NVIDIA GPU architecture diagram showing MIG partitions"
  caption: ""
  relative: false
---

> **TL;DR** — NVIDIA MIG partitions a single GPU into multiple isolated instances, each with dedicated memory and compute units, enabling fine-grained resource sharing in Kubernetes. By combining MIG with device plugins and scheduling policies, you can run mixed workloads (training, inference, data science) on the same GPU without interference. Production success depends on right-sizing MIG profiles, handling topology constraints, and monitoring instance-level utilization.

NVIDIA's GPUs have become the de facto standard for AI workloads, but as models grow and teams multiply, the old approach of dedicating an entire GPU to a single tenant or job leaves hardware underutilized. Multi-Instance GPU (MIG) changes that calculus by slicing a physical GPU into several independent, isolated instances. Each instance behaves like a small, discrete GPU with its own memory bandwidth, L2 cache, and compute engines. When you pair MIG with Kubernetes, you can pack multiple containers onto the same physical GPU, enforce strict resource boundaries, and still give each workload the performance guarantees it expects. In this post, we'll walk through the architecture of MIG, show how to wire it into a Kubernetes cluster, and explore the patterns that production teams use to get the most out of their GPU estate.

## Understanding MIG: How It Works

### What Is MIG?

MIG is a firmware-level feature available on NVIDIA A100, H100, and later data-center GPUs. It partitions the GPU's streaming multiprocessors (SMs), L2 cache, and DRAM into up to seven simultaneous instances. Each instance is fully isolated: a crash or memory overflow in one instance cannot affect another. From the driver's perspective, each MIG instance appears as a separate PCIe device, which means the Linux kernel and container runtimes see it as a normal GPU.

### MIG Profiles and Partitioning

NVIDIA ships a set of predefined profiles that determine how many instances you can create and how much memory each gets. The profiles are named like `1g.5gb`, `2g.10gb`, `3g.20gb`, and `4g.40gb` for the A100 40 GB and 80 GB variants. The first number is the number of GPC (Graphics Processing Cluster) partitions, and the second number is the frame buffer memory per instance. For example, a single A100 80 GB can run seven `1g.5gb` instances or three `2g.10gb` instances plus one `1g.10gb` instance, depending on the workload's memory and compute needs.

You create instances with the `nvidia-smi` command or, more commonly in Kubernetes, via the device plugin. Here's a quick example of creating a `2g.10gb` instance on an A100:

```bash
nvidia-smi -mig 1
nvidia-smi -i 0 -mig 2g.10gb
```

After creation, `nvidia-smi -L` lists the instances as separate GPUs, each with a UUID and a name like `GPU-<uuid>-MIG-<instance-id>`.

### Hardware Support and Requirements

MIG requires both hardware and software support. On the hardware side, you need an Ampere-or-later GPU (A100, H100, H200, etc.) and a motherboard that supports SR-IOV if you want to virtualize further. On the software side, the host must run NVIDIA's Linux driver version 470.56 or later, and the container runtime (Docker or containerd) must use the NVIDIA Container Toolkit. The MIG feature is not available on consumer-grade GPUs like the RTX 3090 or 4090.

## Integrating MIG with Kubernetes

### NVIDIA Device Plugin for MIG

The standard way to expose MIG instances to pods is through the [NVIDIA device plugin](https://github.com/NVIDIA/k8s-device-plugin). The plugin runs as a DaemonSet on each GPU node, discovers MIG instances, and advertises them as extended Kubernetes resources. You configure the plugin with a YAML file that tells it which MIG profiles to create and how to label them.

Here's a minimal device plugin configuration that creates `1g.5gb` instances on all A100 GPUs:

```yaml
version: v1
devicePlugin:
  config:
    - name: mig
      devicePluginStrategy: mig
      mig:
        deviceSlices:
          - deviceIDs: ["GPU-*"]
            migProfile: "1g.5gb"
```

After applying this config and restarting the device plugin DaemonSet, your nodes will advertise `nvidia.com/gpu` resources equal to the number of MIG instances. Pods can request these resources just like any other Kubernetes resource:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: inference-pod
spec:
  containers:
  - name: inference
    image: nvidia/cuda:12.0-base
    resources:
      limits:
        nvidia.com/gpu: 1
```

### Scheduling and Resource Quotas

Kubernetes' default scheduler treats each MIG instance as a separate GPU. This means you can use node affinity, taints, and tolerations to steer specific workloads to specific instances. For example, you might label a node with `gpu-type=mig-1g.5gb` and then use a node selector in your inference deployment to ensure it lands on the right slice.

If you need to prevent a single tenant from consuming all instances on a node, combine resource quotas with limit ranges. Set a per-namespace quota that caps the total `nvidia.com/gpu` requests, and enforce a limit range that requires each pod to specify a limit equal to its request. This prevents overcommit and guarantees that a misbehaving container cannot starve its neighbors.

### Labeling Nodes and Pods

A common production pattern is to add well-known labels to nodes based on the MIG profile they expose. For instance, a node with three `2g.10gb` instances could be labeled `mig-profile=2g.10gb` and `mig-count=3`. Your deployment YAML can then use `nodeSelector` to target those nodes. On the pod side, you can add annotations like `nvidia.com/mig.profile` to document which profile the pod expects, which helps with debugging and cost allocation.

## Architecture Patterns in Production

### Pattern 1: Multi-Tenant GPU Sharing

In a shared ML platform, data scientists, ML engineers, and QA teams often compete for GPU time. With MIG, you can partition a single A100 into, say, four `1g.5gb` instances for small inference jobs and one `3g.20gb` instance for a large training job. Each tenant gets a dedicated slice, and because MIG enforces memory and compute isolation, a runaway training job cannot consume the entire GPU's memory and crash the inference pods.

### Pattern 2: Mixed Workload Co-location

Consider a recommendation system that runs both a daily model retraining batch job and a real-time inference service. Instead of buying two separate GPUs, you can allocate a `4g.40gb` instance for the training job and three `1g.5gb` instances for the inference service on the same physical GPU. The training job runs overnight, and the inference service runs 24/7, but because MIG guarantees dedicated resources, latency spikes in the inference service are minimal even when the training job is active.

### Pattern 3: Dynamic Instance Allocation

Some workloads have bursty resource demands. A natural language processing team might need a full GPU for a few hours to fine-tune a model, then release it. With MIG, you can dynamically create and destroy instances using a custom controller that watches a job queue. When a job arrives, the controller creates the appropriate MIG profile, labels the instance, and schedules the pod. When the job finishes, the controller deletes the instance, returning the hardware to a pool of available slices. This pattern is especially powerful when combined with Kubernetes Jobs and TTL controllers.

### Pattern 4: Cost-Optimized Instance Sizing

Not every workload needs a full GPU. A simple embedding lookup or a small transformer inference can run comfortably on a `1g.5gb` instance, which costs a fraction of a full GPU on cloud platforms. By matching the MIG profile to the actual memory and compute requirements, you can reduce your GPU spend by 30–50% compared to over-provisioned full-GPU allocations. Always profile your workload first: measure peak memory usage and SM utilization, then choose the smallest MIG profile that leaves a 20% safety margin.

### Handling Topology and NUMA Constraints

MIG instances on the same physical GPU share the same PCIe switch and memory controller, which can lead to contention if you place latency-sensitive workloads on instances that share the same GPC partition. To avoid this, use the `nvidia-smi topo` command to inspect the topology and then assign instances to pods based on their NUMA node and PCIe topology. For example, if you have a two-GPU server with a NVLink bridge, you might want to place a distributed training job on instances that are on different GPUs but connected via NVLink, rather than on two instances of the same GPU.

## Operational Considerations

### Monitoring and Observability

MIG instances expose metrics through the NVIDIA DCGM (Data Center GPU Manager) exporter, which you can scrape with Prometheus. Key metrics include `DCGM_FI_GPU_MIG_*` for instance-level utilization, memory usage, and temperature. You can also use `nvidia-smi` to query instance health from inside the container. To visualize per-tenant usage, build Grafana dashboards that group metrics by namespace, pod name, and MIG profile. Set up alerts for instance memory pressure, high temperature, and unexpected instance count changes.

### Failure Modes and Recovery

The most common failure mode is a pod that exceeds its MIG memory limit, which causes the NVIDIA driver to kill the container. Kubernetes will restart the pod, but if the failure is systematic (e.g., a model that requires more memory than the instance provides), you need to right-size the MIG profile. Another failure mode is a buggy driver that corrupts the MIG configuration; in that case, you must disable MIG with `nvidia-smi -mig 0` and re-enable it after a driver update. Always test driver upgrades in a staging environment before rolling them out to production.

### Security and Isolation

MIG provides hardware-level isolation, but it is not a replacement for container-level security. You should still run your containers with non-root users, read-only root filesystems, and seccomp profiles. Additionally, because MIG instances are visible as separate devices, you can use Linux device cgroup controls to restrict which users can access which instances, adding another layer of defense.

## Key Takeaways

- MIG partitions a single GPU into up to seven isolated instances, each with dedicated memory and compute, enabling fine-grained resource sharing.
- Integrate MIG with Kubernetes via the NVIDIA device plugin, which advertises each instance as a `nvidia.com/gpu` resource.
- Use MIG profiles like `1g.5gb` or `2g.10gb` to match workload memory and compute requirements, and right-size them to avoid overcommit.
- Production patterns include multi-tenant sharing, mixed workload co-location, and dynamic instance allocation driven by job queues.
- Monitor instance-level metrics with DCGM, handle topology and NUMA constraints, and enforce container security best practices.

## Further Reading

- [NVIDIA MIG User Guide](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/) — official documentation on MIG profiles, configuration, and troubleshooting.
- [NVIDIA Kubernetes Device Plugin](https://github.com/NVIDIA/k8s-device-plugin) — source code and usage examples for exposing MIG instances to Kubernetes.
- [Kubernetes GPU Device Plugin Architecture](https://kubernetes.io/docs/concepts/extend/devices/) — deep dive into how device plugins integrate with the kubelet.
- [DCGM Exporter for Prometheus](https://github.com/NVIDIA/dcgm-exporter) — metrics exporter for GPU and MIG instance monitoring.