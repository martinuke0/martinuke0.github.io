---
title: "Mastering Linux cgroups v2 Resource Isolation: Implementation, Control Groups, and Production Performance Tuning"
date: "2026-06-01T17:00:43.801"
draft: false
tags: ["cgroups","linux","performance","kubernetes","devops"]
description: "Implement and tune Linux cgroups v2 for precise CPU, memory, and I/O isolation, using production‑tested patterns that boost Kubernetes and bare‑metal workloads."
summary: "A deep dive into cgroups v2 architecture, practical commands, and performance‑tuning tricks you can apply today to keep containers and services well‑behaved in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-06-01-mastering-linux-cgroups-v2-resource-isolation-implementation-control-groups-and-production-performance-tuning.svg"
  alt: "Diagram of Linux cgroups hierarchy with CPU, memory, and I/O controllers."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 gives you a single‑unified hierarchy for fine‑grained CPU, memory, and I/O limits. By creating slices or manual control groups, you can enforce hard caps, prioritize workloads, and diagnose contention without touching application code.

Linux engineers have relied on cgroups since the early 2000s, but the migration to version 2 (v2) unlocks a cleaner API, better accounting, and tighter integration with systemd and Kubernetes. This post walks through the underlying architecture, shows concrete `bash` commands for creating and managing groups, and presents production‑ready patterns that keep your services fast, predictable, and safe from noisy neighbors.

## Understanding cgroups v2 Architecture

cgroups v2 replaces the multiple‑hierarchy model of v1 with a **single unified hierarchy**. All controllers (cpu, memory, io, pids, etc.) are attached to the same tree, eliminating the “controller mismatch” problems that plagued mixed‑v1 setups.

### Unified Tree Explained

```
/sys/fs/cgroup
└─ <root>
   ├─ cpu.max          # max CPU time (quota/period)
   ├─ memory.max       # hard memory limit
   ├─ io.max           # I/O bandwidth per device
   └─ user.slice/
       └─ myservice.slice/
           └─ myservice.service
```

* The root node represents the whole system.  
* Each **slice** (a systemd concept) or manually created directory becomes a **control group** that inherits limits from its parent.  
* Controllers expose plain‑text files; writing a value instantly changes the limit.

The design is deliberately simple: **one file per resource per group**. This uniformity lets you script policies without juggling disparate mount points.

### Key Differences from v1

| Feature | cgroups v1 | cgroups v2 |
|---------|------------|------------|
| Hierarchy | Multiple independent trees (one per controller) | Single unified tree |
| Thread granularity | Optional per‑controller | Always per‑thread (no separate `tasks` vs `cgroup.procs`) |
| Delegation | Manual mount‑point tricks | Native systemd slice delegation |
| Memory pressure notifications | `memory.pressure_level` (v1) | `memory.low` and `memory.high` with unified pressure interface |

For a detailed spec, see the [kernel documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html).

## Implementation Basics: Creating and Managing Control Groups

You can interact with cgroups directly via the filesystem or through systemd. Below we cover both approaches.

### Manual Creation with Bash

```bash
#!/usr/bin/env bash
# Create a new control group called "batch"
CGROUP_ROOT="/sys/fs/cgroup"
CGROUP_NAME="batch"

mkdir -p "${CGROUP_ROOT}/${CGROUP_NAME}"
# Set a CPU limit of 20% (200ms of 1s period)
echo "20000 100000" > "${CGROUP_ROOT}/${CGROUP_NAME}/cpu.max"
# Restrict memory to 2 GiB
echo "$((2 * 1024 * 1024 * 1024))" > "${CGROUP_ROOT}/${CGROUP_NAME}/memory.max"
# Limit I/O to 10 MiB/s on /dev/sda
echo "8:0 wbps=10485760" > "${CGROUP_ROOT}/${CGROUP_NAME}/io.max"
```

* `cpu.max` takes `quota period` in microseconds.  
* `memory.max` expects bytes.  
* `io.max` uses the format `major:minor <op>=<bytes>`; `wbps` is write bandwidth.

To attach a process:

```bash
PID=12345
echo "$PID" > "${CGROUP_ROOT}/${CGROUP_NAME}/cgroup.procs"
```

### Systemd Slice Delegation

Systemd abstracts the same files behind **slices** and **services**, which is the preferred method for most production environments.

```ini
# /etc/systemd/system/batch.slice
[Slice]
# 20% of one CPU
CPUQuota=20%
# 2 GiB RAM
MemoryMax=2G
# 10 MiB/s write on /dev/sda
IOWriteBandwidthMax=/dev/sda 10M
```

Enable the slice and start a service inside it:

```bash
systemctl daemon-reload
systemctl start batch.slice
systemctl start mybatch.service  # Service file should have `Slice=batch.slice`
```

Systemd automatically writes the appropriate values to the unified cgroup files, and it also handles **delegation**—allowing the service to create its own sub‑cgroups without root privileges. See the official guide on [cgroup delegation](https://systemd.io/CGROUP_DELEGATION/).

## Patterns in Production: CPU, Memory, and I/O Isolation

Real‑world workloads rarely need a single static limit. Instead, engineers apply a mix of **hard caps**, **soft guarantees**, and **burst policies**.

### CPU: Quotas, Shares, and Idle Balancing

* **Hard quota** (`cpu.max`) caps the absolute CPU time. Ideal for batch jobs that must not exceed a budget.  
* **Shares** (`cpu.weight`) provide proportional scheduling when the system is oversubscribed. A service with weight 1000 gets roughly twice the CPU time of one with weight 500.  
* **Idle balancing** (`cpu.idle`) lets the kernel reclaim CPU from idle groups, preventing them from hogging cores.

```bash
# Give interactive service higher priority
echo 2000 > /sys/fs/cgroup/interactive.slice/cpu.weight
# Batch jobs get lower weight
echo 500 > /sys/fs/cgroup/batch.slice/cpu.weight
```

### Memory: Hard Limits, Low/High Watermarks, and OOM Scoring

* `memory.max` is a hard cap; the kernel kills processes that exceed it.  
* `memory.low` sets a **soft guarantee**—the kernel tries to keep the group above this level during contention.  
* `memory.high` triggers reclamation before hitting the hard limit.

```bash
# Reserve 1 GiB for a latency‑critical service
echo "$((1 * 1024 * 1024 * 1024))" > /sys/fs/cgroup/latency.slice/memory.low
# Allow up to 4 GiB total, but start reclaiming at 3 GiB
echo "$((4 * 1024 * 1024 * 1024))" > /sys/fs/cgroup/latency.slice/memory.max
echo "$((3 * 1024 * 1024 * 1024))" > /sys/fs/cgroup/latency.slice/memory.high
```

When a group is OOM‑killed, the kernel writes the PID to `memory.events`. Monitoring this file gives early warning before the service crashes.

### I/O: Bandwidth Throttling and Priority

* `io.max` controls per‑device bandwidth.  
* `io.bfq.weight` (if the BFQ scheduler is enabled) gives weighted I/O priority.  
* Use `blkio.weight` for legacy kernels; cgroups v2 maps it to `io.bfq.weight`.

```bash
# Limit a backup job to 50 MiB/s reads on /dev/nvme0n1
echo "259:0 rbps=52428800" > /sys/fs/cgroup/backup.slice/io.max
# Give it lower priority than the database
echo 200 > /sys/fs/cgroup/backup.slice/io.bfq.weight
echo 800 > /sys/fs/cgroup/database.slice/io.bfq.weight
```

### Real‑World Example: Kubernetes Pods

Kubernetes 1.25+ uses the **cgroupfs** driver by default, but the **systemd** driver is recommended for v2. In a pod spec:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: analytics
spec:
  containers:
  - name: worker
    image: myorg/worker:latest
    resources:
      limits:
        cpu: "500m"          # 50% of a core
        memory: "2Gi"
      requests:
        cpu: "250m"
        memory: "1Gi"
    # Enable explicit cgroup v2 delegation
    securityContext:
      privileged: false
      allowPrivilegeEscalation: false
```

Kubernetes translates these `limits` into `cpu.max`, `memory.max`, and `io.max` under the pod’s cgroup, respecting the unified hierarchy automatically. For a deeper dive, see the Kubernetes docs on [cgroup version 2 support](https://kubernetes.io/docs/concepts/scheduling-eviction/cgroup/).

## Performance Tuning Strategies

Even with limits in place, you need observability and feedback loops to avoid over‑provisioning.

### 1. Real‑Time Metrics from `/proc` and cgroup files

```bash
#!/usr/bin/env bash
CGROUP="/sys/fs/cgroup/latency.slice"

while true; do
  cpu_usec=$(cat "${CGROUP}/cpu.stat" | grep usage_usec | awk '{print $2}')
  mem_used=$(cat "${CGROUP}/memory.current")
  io_read=$(cat "${CGROUP}/io.stat" | grep rbytes | awk '{print $2}')
  printf "CPU µs: %s | Mem: %s MiB | I/O read: %s KiB\n" \
    "$cpu_usec" "$((mem_used/1024/1024))" "$((io_read/1024))"
  sleep 5
done
```

Collecting these metrics with Prometheus node‑exporter or a custom sidecar gives you per‑group visibility. Alert on thresholds such as `memory.current > memory.max * 0.9`.

### 2. Adaptive Limits with `systemd-run --property`

For workloads with variable demand (e.g., nightly data pipelines), you can **adjust limits on the fly**:

```bash
systemd-run --scope \
  --property=CPUQuota=30% \
  --property=MemoryMax=4G \
  /usr/bin/python3 batch_job.py
```

The `--scope` flag creates a transient slice that inherits from the caller’s slice, making it easy to experiment without permanent config changes.

### 3. Avoiding “Throttling” Pitfalls

* **CPU throttling** does not guarantee latency; a process may be starved for long periods. Pair `cpu.max` with `cpu.idle=0` to let the kernel reclaim unused time quickly.  
* **Memory overcommit**: Setting `memory.max` too low can trigger OOM kills under bursty traffic. Use `memory.high` to start reclaim before hitting the hard limit.  
* **I/O starvation**: When many groups contend for the same SSD, the kernel may serialize writes, inflating latency. Distribute critical I/O across multiple devices or use `io.max` with separate device IDs.

### 4. Profiling with `perf` Inside a Cgroup

Running `perf` inside a cgroup respects the same limits, which helps you understand the cost of throttling:

```bash
perf stat -e cycles,instructions,cache-misses -a -G latency.slice -- sleep 30
```

The `-G` flag attaches the measurement to the specified cgroup, giving you per‑group performance counters directly from the kernel.

## Architecture Considerations for Kubernetes and Systemd

When you blend containers, systemd services, and bare‑metal processes, the **delegation boundary** becomes critical.

### Delegating from the Host to Pods

1. **Mount the unified hierarchy** at `/sys/fs/cgroup` on each node.  
2. Enable the `systemd` driver in the kubelet (`--cgroup-driver=systemd`).  
3. Create a **parent slice** for all pods, e.g., `kubepods.slice`.  
4. Allow the kubelet to `Delegate=yes` on that slice so pods can create their own sub‑cgroups without root.

```ini
# /etc/systemd/system/kubepods.slice
[Slice]
Delegate=yes
```

Now each pod appears as `kubepods.slice/kubepods-burstable.slice/kubepods-burstable-pod<uid>.slice`.

### Mixing Bare‑Metal Services

If you run a legacy daemon outside Kubernetes, give it its own slice (e.g., `legacy.slice`) and set `CPUQuota`, `MemoryMax`, etc. The slice can be **nested** under `system.slice` to keep it separate from container workloads.

```ini
# /etc/systemd/system/legacy.slice
[Slice]
CPUQuota=10%
MemoryMax=1G
IOWriteBandwidthMax=/dev/sda 5M
```

### Failure Isolation

cgroups provide **failure domains**:

| Failure Mode | Mitigation via cgroups |
|--------------|------------------------|
| Noisy neighbor consumes CPU | Set a low `cpu.max` or use `cpu.weight` to limit share |
| Memory leak crashes host | Apply per‑group `memory.max`; OOM events are isolated |
| Disk I/O saturation | Throttle with `io.max`; use separate devices for critical services |
| Process fork bomb | Limit `pids.max` (`pids.max` controller) per group |

These patterns let you enforce Service Level Objectives (SLOs) without modifying application code.

## Key Takeaways

- cgroups v2 unifies all resource controllers under a single hierarchy, simplifying policy enforcement.  
- Use **systemd slices** for most production workloads; they handle delegation, persistence, and integration with `journald`.  
- Combine **hard caps** (`cpu.max`, `memory.max`, `io.max`) with **soft guarantees** (`cpu.weight`, `memory.low`, `memory.high`) to balance fairness and performance.  
- Continuous observability through `/sys/fs/cgroup/*` files (or Prometheus exporters) is essential to avoid silent throttling or OOM events.  
- When running Kubernetes on the same host, enable the `systemd` cgroup driver and delegate from a parent slice (`kubepods.slice`) to keep container and host services isolated.

## Further Reading

- [Linux kernel documentation – Control Groups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd – Cgroup Delegation](https://systemd.io/CGROUP_DELEGATION/)  
- [Kubernetes – Managing Resources with cgroups](https://kubernetes.io/docs/concepts/scheduling-eviction/cgroup/)