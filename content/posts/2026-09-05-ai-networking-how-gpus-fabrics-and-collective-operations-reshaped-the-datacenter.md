---
title: "AI Networking: How GPUs, Fabrics, and Collective Operations Reshaped the Datacenter"
date: "2026-09-05T18:56:44.257"
draft: false
tags: ["ai-infrastructure", "networking", "gpu", "rdma", "datacenter"]
description: "How AI workloads changed datacenter networking — RDMA, RoCE, fat-tree fabrics, and the patterns that keep multi-thousand-GPU clusters running."
summary: "AI workloads pushed the network to its limits. This post walks through the protocols, topologies, and failure modes that define modern AI networking — from RoCE and collective operations to fat-tree fabrics and packet-level telemetry."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-ai-networking-how-gpus-fabrics-and-collective-operations-reshaped-the-datacenter.svg"
  alt: "A datacenter fabric diagram showing GPU racks connected via spine-leaf switches."
  caption: ""
  relative: false
---

> **TL;DR** — AI training is a bandwidth problem disguised as a compute problem. Every GPU-to-GPU gradient exchange is a tightly-scheduled, latency-sensitive network transaction, which is why modern AI fabrics rely on RDMA, lossless Ethernet (PFC + ECN), and topologies like fat-tree and rail-optimized designs. If you operate these clusters, your network is the cluster.

## Why AI Networking Is Different From "Regular" Datacenter Networking

Traditional web and microservice traffic is bursty, latency-tolerant, and dominated by request-response patterns. AI training traffic is the opposite: long-running collectives where thousands of GPUs exchange partial gradients in lockstep, often for hours at a time. The network is not a side effect of the workload — it is the medium through which the workload is performed.

Concretely, distributed training does three things to the network that nothing else really does:

- **Sustained all-to-all pressure.** A single AllReduce over 1,024 H100s can push terabits per second across the fabric for the entire duration of the step. There is no idle time.
- **Tail-latency sensitivity.** The slowest rank in a synchronous step determines the throughput of every other rank. A handful of stragglers can cost millions of dollars in wasted GPU-hours, as detailed in [NVIDIA's DGX SuperPOD reference architecture](https://docs.nvidia.com/dgx-superpod/index.html).
- **Loss intolerance.** TCP retransmits under a tight collective deadline look identical to a 10x slowdown. Lossless transport is mandatory, not optional.

That combination — sustained bandwidth, tight tail-latency budgets, and zero tolerance for packet loss — is the entire design brief behind modern AI fabrics.

## The Building Block: RDMA Over Converged Ethernet (RoCE)

Remote Direct Memory Access lets a NIC write directly into another host's memory without involving the CPU or the kernel's TCP stack. For AI collectives, RDMA is the difference between training a 70B-parameter model and never finishing.

RoCEv2 — the version everyone actually deploys — runs RDMA's verbs over UDP on top of standard Ethernet/IP. That choice keeps it routable, lets it ride on merchant silicon, and means your switch vendors (Arista, Cisco, Broadcom, Mellanox-NVIDIA) all speak the same wire protocol. The tradeoff is that you now need Ethernet itself to behave like a lossless fabric, which is where **Priority Flow Control (PFC)** and **Explicit Congestion Notification (ECN)** enter.

A minimal RoCEv2 deployment looks like this:

```text
GPU 0 (rank 0)  ──┐
GPU 1 (rank 1)  ──┤── host NIC ── ToR ── Spine ── ToR ── host NIC ──┤── GPU 1023
GPU 2 (rank 2)  ──┘                                                     │
                                                                       NCCL/Gloo
                                                                       AllReduce
```

Where:

- **PFC** pauses traffic on a congested queue instead of dropping it. Eight priorities × per-port pause frames is what makes "lossless Ethernet" not a contradiction.
- **ECN** marks packets that cross a queue threshold so the sender can reduce its rate before PFC ever fires. ECN is the early-warning system; PFC is the emergency brake.
- **DSCP-aware QoS** keeps RDMA traffic in a strict-priority queue above anything else, because the moment a backup flow grabs buffer headroom, your collective stalls.

If you only remember one thing: **ECN + PFC + a well-sized buffer is the lossless-Ethernet triangle.** Skip any side and you will be debugging tail-latency spikes for quarters.

## Collective Operations and Why Topology Matters

The heavy hitters in distributed training are NCCL primitives — `AllReduce`, `AllGather`, `ReduceScatter`, and `All-to-All` — each of which has a network-shape that suits it best. The library behind most of this, [NCCL](https://github.com/NVIDIA/ncccl) (and its OSS sibling [Gloo](https://github.com/facebookincubator/gloo)), is topology-aware: it inspects NVLink islands, PCIe lanes, NUMA distances, and NIC-to-switch mappings before picking a routing plan.

Two patterns dominate:

- **Ring AllReduce** — bandwidth-optimal, latency-linear in N. Great on a single NVLink island, painful across thousands of GPUs.
- **Tree AllReduce** — bandwidth-optimal, latency-log in N. How most multi-rack collectives are actually run.

The hidden third pattern is **rail-optimized collectives**, where each "rail" is a dedicated network plane that handles one dimension of the reduction. NVIDIA's DGX H100/H200 SuperPOD design, summarized in the [DGX SuperPOD networking whitepaper](https://docs.nvidia.com/dgx-superpod/), uses rails so that one switch plane carries the in-rack reduction, another carries inter-rack, and they are stitched together so that no single switch oversubscribes the GPU bandwidth it advertises.

### Patterns in Production: The Rail-Optimized Fabric

Most production AI fabrics today look less like a generic fat-tree and more like a **dual-plane, rail-aligned design**:

```text
       ┌─────────── Spine Plane A ───────────┐
       │         (e.g. 400 GbE/800 GbE)      │
GPU rack 0 ── ToR-A ──┐                ┌── ToR-A ── GPU rack 7
GPU rack 1 ── ToR-A ──┤                ├── ToR-A ── GPU rack 8
       │               │                │               │
       └───────────────┼────────────────┼───────────────┘
                       │                │
       ┌───────────────┼────────────────┼───────────────┐
       │               │                │               │
GPU rack 0 ── ToR-B ──┘                └── ToR-B ── GPU rack 7
GPU rack 1 ── ToR-B ──                 ── ToR-B ── GPU rack 8
       └─────────── Spine Plane B ───────────┘
```

Two independent switch planes, one per rail. The reduction is split across planes and merged only at the endpoints. Two practical consequences:

1. **Failover is mostly free.** Lose a spine switch? You still have a working plane at half the ideal bandwidth. Lose a ToR? Only one plane drops; the other keeps the cluster training, just slower.
2. **Capacity planning is deterministic.** You can compute the maximum bisection bandwidth you will ever need and dimension spines for it on day one, instead of reacting to growth.

This is also why vendors sell "AI fabrics" as bundles — the switches, optics, NICs, and even the rack PDUs are all picked to make one of these planes fit cleanly into a row.

## Topology Choices: Fat-Tree vs. Dragonfly vs. Torus

There's no single best topology. There are only topologies that match your scale, your workload mix, and your tolerance for cabling complexity.

| Topology | Where it shines | Where it hurts |
|---|---|---|
| **Fat-tree (Clos)** | Predictable latency, easy capacity planning, works on merchant silicon | More switches and more cables per GPU than the alternatives |
| **Dragonfly+** | Massive scale (10k+ endpoints) with fewer global links | Intolerant of link failures; rerouting can spike latency |
| **Rail-optimized (above)** | Map directly onto NCCL's collective strategy; ideal for LLM training | Adds complexity around planning which rack sits on which rail |
| **3D/4D Torus** | HPC codes with nearest-neighbor communication | Worse for AllReduce; rarely seen in pure AI shops |

The hyperscalers running the largest training clusters in the world — Meta, Google, Microsoft, AWS — almost universally converge on **fat-tree or rail-optimized fat-tree**, partly because the failure modes are well understood and partly because it works on Ethernet. IBM and a handful of HPC shops still run [dragonfly topologies for Frontier-class systems](https://www.olcf.ornl.gov/frontier/), but for AI workloads specifically, fat-tree has effectively won.

## Congestion Control: The Part That Quietly Eats Your Throughput

Most AI clusters have bandwidth on paper and not in practice because their **congestion control is wrong**. The mistakes are almost always the same:

1. **PFC storms.** A single misbehaving sender pauses an entire priority class across a whole fabric. The fix is careful headroom allocation and per-port PFC watchdog timers.
2. **Slow ECN reaction.** ECN thresholds are set too high, so congestion is detected only after PFC fires. The fix is lowering the threshold and using DCTCP-style alpha tracking.
3. **Hotspots from unbalanced collectives.** A rank-straggler ends up relaying traffic for many others. NCCL's topology detection plus host-level QoS helps.
4. **Background traffic mixing with RDMA.** A backup job pushing data over the same ToR as training traffic. The fix is hard segmentation: RDMA on its own VLAN/VRF, no exceptions.

The right tool to verify all of this is **in-band network telemetry (INT)** or streaming telemetry from the switches. Arista's EOS, Cisco's NX-OS, and NVIDIA's Cumulus-derived NetQ all expose queue-depth histograms and PFC pause counters in near real time. If your NOC can't tell you how many microseconds a given flow spent paused yesterday, you're flying blind.

## Storage Networking: The Network Nobody Ponders Until It Breaks

Training a frontier model reads checkpoints at terabyte scale and writes them again. Your storage fabric is, for the duration of a checkpoint, just as contended as your compute fabric — and almost always lower priority in the design.

Three rules learned the hard way:

- **Checkpoints are bursty.** A 1 TB checkpoint across 1,024 ranks is, by definition, 1 GB of coordinated writes per rank at the same instant. Storage needs to absorb that.
- **Object stores with parallel data paths (S3A over parallel HTTP, pNFS, custom multi-channel) handle this.** Single-connection storage will fall over.
- **Replay from staging, not from primary.** The checkpoint itself shouldn't ride the same fabric as the live training step. Mirror it to a different ToR plane before acknowledging.

Practically, this is why you see AI labs deploying **parallel filesystems (Lustre, GPFS, WekaFS) for hot data and object stores for cold**, with the tier transition automated and the network paths explicitly partitioned. The [Lustre architecture overview](https://www.lustre.org/) and [WekaFS architecture guide](https://www.weka.io/tech-topics/) are both worth a read if you're sizing this for the first time.

## Observability and Failure Modes You Should Expect

AI networking failures don't look like "the link went down." They look like "the training run suddenly takes 12% longer and we don't know why." Your telemetry stack has to catch the subtle forms:

- **PFCRD (PFC Rx Delay) increasing on a port** — first sign that someone upstream is congested.
- **ECN-marked bytes creeping up** — collective is competing with something it shouldn't be.
- **Out-of-order RoCE packets** — usually a NIC firmware bug or a misconfigured hash on an ECMP bundle.
- **NVLink island asymmetry** — one rank ends up on a different NVLink domain than its peers and now every AllReduce pays an inter-island hop.

The tools that ship with serious AI fabrics — [NVIDIA NetQ](https://developer.nvidia.com/networking/netq), [Arista DANZ Monitoring Fabric](https://www.arista.com/en/products/dmf), and [Cisco Nexus Dashboard](https://www.cisco.com/c/en/us/products/cloud-systems-management/nexus-dashboard/index.html) — all try to surface these signals before they become dollar-costing stragglers. Open-source stacks like [TimescaleDB](https://www.timescale.com/) + Grafana + switch telemetry exporters get you 80% of the way there for almost no spend.

## A Practical Checklist for Operating an AI Fabric

If you're standing one up, this is roughly the order of operations:

1. **Pick the topology that matches your scale.** Fat-tree rail-optimized for ≤8k GPUs; fat-tree full bisection beyond.
2. **Dimension buffers for PFC headroom, not just bandwidth.** A 400 GbE port with 50 MB of buffer behaves very differently under bursty collectives than one with 16 MB.
3. **Tune ECN aggressively.** Lower thresholds than the vendor default. Test with [the NCCL tests](https://github.com/NVIDIA/nccl-tests) `all_reduce_perf`.
4. **Partition storage from compute traffic.** Different ToRs or at minimum different VLANs and DSCP classes.
5. **Stream telemetry to a time-series store before you go live.** You will want to look back at this data within a week.
6. **Automate PFC storm detection.** A simple alert on "PFC frames sent > N for > M seconds" catches most regressions.
7. **Plan for firmware.** A switch firmware update once broke ECN thresholds across an entire fleet. Stage, canary, verify.

## Key Takeaways

- AI networking is a **bandwidth + tail-latency + loss-intolerance** problem; treat it as such from day one.
- The transport stack is **RDMA (RoCEv2) over lossless Ethernet**, which means **PFC + ECN + DSCP-aware QoS** are not optional.
- **Topology is mostly fat-tree or rail-optimized fat-tree** in production, sized to the workload's largest collective.
- **Congestion control** — not link capacity — is the most common cause of "we have 800 GbE and we're not getting 800 GbE."
- **Storage and checkpoint traffic must be partitioned** from compute traffic or they will quietly eat into your training budget.
- **Telemetry must be streaming, per-queue, and historical**, or you will spend weeks chasing phantom stragglers.

## Further Reading

- [NVIDIA NCCL documentation — collective communication patterns](https://docs.nvidia.com/deeplearning/nccl/)
- [Arista Networks — AI/ML networking reference designs](https://www.arista.com/en/solutions/ai-data-center-networking)
- [Ultra Ethernet Consortium — the emerging AI-focused Ethernet spec](https://ultraethernet.org/)
- [RDMAmojo — RoCEv2 congestion control deep dives](https://www.rdma-mojo.com/)
- [Google SRE — capacity planning for AI workloads](https://sre.google/sre-book/managing-load/)
- [Linux Foundation — DPDK and kernel-bypass networking primer](https://www.dpdk.org/)