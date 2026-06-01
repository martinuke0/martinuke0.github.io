---
title: "Mastering Cgroups v2 Resource Isolation: A Deep Dive into Effective Linux Control Groups"
date: "2026-06-01T18:00:43.971"
draft: false
tags: ["cgroups","linux","resource-isolation","performance","devops"]
description: "Explore how cgroups v2 isolates CPU, memory, and I/O in Linux, with real‑world patterns, config snippets, and troubleshooting tips for production engineers."
summary: "A practical guide that walks you through cgroups v2 hierarchy, CPU, memory, and I/O controllers, and production‑ready patterns for resource isolation."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-06-01-mastering-cgroups-v2-resource-isolation-a-deep-dive-into-effective-linux-control-groups.png"
  alt: "Diagram of Linux cgroups v2 hierarchy with resource controllers."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 gives you a single, unified hierarchy to limit CPU, memory, and I/O per workload. By wiring the controllers into systemd units or container runtimes, you can enforce strict isolation, observe real‑time metrics, and recover from quota violations without rebooting the host.

Resource isolation is no longer a “nice‑to‑have” feature; it’s a prerequisite for running latency‑sensitive services alongside batch jobs on the same Linux host. While the original cgroups (v1) required juggling multiple hierarchies, cgroups v2 consolidates everything under one tree, simplifying both configuration and observability. This post walks you through the internal architecture, shows production‑grade patterns, and gives you ready‑to‑paste snippets for common tooling such as systemd, Kubernetes, and Docker.

## Why cgroups v2 Matters

* **Single hierarchy** – No more “CPU‑only” vs “memory‑only” mounts; everything lives under `/sys/fs/cgroup`.  
* **Unified control interface** – The `cgroup.procs` file is the single source of truth for task placement.  
* **Thread‑aware accounting** – Kernel threads are accounted for the same way as user threads, eliminating hidden CPU consumption.  
* **Improved I/O throttling** – The `io.max` file replaces the fragmented `blkio.throttle.*` files of v1, supporting per‑device, per‑cgroup limits in a single line.

These benefits translate into concrete operational gains:

| Scenario | v1 Pain Point | v2 Resolution |
|----------|---------------|----------------|
| Adding a new memory limit to a running service | Must unmount and remount a separate memory hierarchy | Write a single value to `memory.max` in the same cgroup |
| Enforcing I/O latency SLAs for a database | Multiple `blkio.throttle.read_bps_device` files, easy to mis‑configure | One `io.max` line that can set both read/write Bps and IOPS per device |
| Auditing resource usage across dozens of services | Scattered files, inconsistent naming | All metrics under `cpu.stat`, `memory.stat`, `io.stat` – parsable by a single Prometheus exporter |

## Core Controllers Overview

cgroups v2 ships with a set of **controllers** that you enable per‑cgroup. The most common ones are:

| Controller | What it controls | Typical file(s) |
|------------|------------------|-----------------|
| `cpu` | CPU time, bandwidth, and realtime priority | `cpu.max`, `cpu.stat` |
| `memory` | Anonymous and file‑backed memory, swap, OOM killer behavior | `memory.max`, `memory.swap.max`, `memory.stat` |
| `io` | Block I/O bytes and IOPS throttling | `io.max`, `io.stat` |
| `pids` | Maximum number of processes/threads | `pids.max`, `pids.current` |
| `cpuset` | CPU core and NUMA node affinity | `cpuset.cpus`, `cpuset.mems` |

You enable a controller by mounting the cgroup filesystem with the `-o` option, or by letting **systemd** handle it automatically (recommended for production).

### Enabling Controllers System‑wide

```bash
# Create the unified hierarchy with the controllers we need
mount -t cgroup2 -o rw,nosuid,nodev,noexec,relatime,cpu,memory,io,pids,cpuset cgroup2 /sys/fs/cgroup

# Verify the active controllers
cat /sys/fs/cgroup/cgroup.controllers
# Output: cpu memory io pids cpuset
```

If you are on a distro that already ships with a unified mount (most modern Ubuntu, Fedora, and RHEL), you can simply check:

```bash
grep cgroup2 /proc/mounts
```

## Architecture Patterns in Production

### 1. Systemd‑Managed Service Isolation

Systemd creates a slice for each service (`myapp.service`) and automatically attaches the requested controllers. The declarative syntax lives in the unit file.

```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My high‑performance API
After=network.target

[Service]
ExecStart=/usr/local/bin/myapp
# CPU: 20% of a single core (200ms of 1s period)
CPUQuota=20%
# Memory: hard limit of 1 GiB
MemoryMax=1G
# I/O: 10 MiB/s read, 5 MiB/s write on /dev/sda
IOReadBandwidthMax=/dev/sda 10M
IOWriteBandwidthMax=/dev/sda 5M
# Max 200 processes (including threads)
TasksMax=200

[Install]
WantedBy=multi-user.target
```

After reloading systemd (`systemctl daemon-reload`) and restarting the service, you can inspect the cgroup:

```bash
# Show the full hierarchy
systemd-cgls

# Drill into the service’s cgroup
systemd-cgtop -u myapp.service
```

### 2. Container Runtime Integration (Docker)

Docker 20.10+ defaults to the unified hierarchy when the host kernel supports cgroups v2. You can enforce limits directly via the `docker run` CLI:

```bash
docker run -d \
  --name=web \
  --cpus="0.5" \          # 50 % of a core (maps to cpu.max)
  --memory="512m" \      # hard limit (memory.max)
  --pids-limit=100 \     # pids.max
  --device-read-bps=/dev/sda:10M \
  --device-write-bps=/dev/sda:5M \
  myorg/webapp:latest
```

Docker translates these flags into the appropriate `cpu.max`, `memory.max`, and `io.max` entries under the container’s cgroup. For deeper control, you can drop a custom `daemon.json` snippet:

```json
{
  "default-runtime": "runc",
  "runtimes": {
    "runc": {
      "path": "runc",
      "runtimeArgs": [
        "--systemd-cgroup"
      ]
    }
  }
}
```

The `--systemd-cgroup` flag tells Docker to hand off cgroup management to systemd, which then applies the same unit‑file semantics as native services.

### 3. Kubernetes with the `cgroupv2` Feature Gate

Kubernetes 1.26+ supports cgroups v2 natively. Enable the feature gate in the kubelet config:

```yaml
# /var/lib/kubelet/config.yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd
cgroupRoot: ""
featureGates:
  NodeSwap: true
```

Pod specifications can now use the familiar resource fields:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: analytics
spec:
  containers:
  - name: worker
    image: analytics:stable
    resources:
      limits:
        cpu: "1"
        memory: "2Gi"
        ephemeral-storage: "5Gi"
```

Kubernetes writes the limits into the cgroup’s `cpu.max`, `memory.max`, and `io.max` files automatically. The unified hierarchy also means you can query a pod’s cgroup directly from the node for debugging:

```bash
# Assuming the pod’s UID is abc123
cat /sys/fs/cgroup/kubepods.slice/kubepods-burstable.slice/kubepods-burstable-podabc123.slice/containerd-*.scope/cpu.stat
```

## Configuration Walkthrough

### Step‑by‑Step: Adding a New Service with Precise I/O Throttling

1. **Create a dedicated slice** – This isolates the service from unrelated workloads.

   ```bash
   cat <<EOF > /etc/systemd/system/critical.slice
   [Slice]
   CPUQuota=30%
   MemoryMax=2G
   IOReadBandwidthMax=/dev/nvme0n1 50M
   IOWriteBandwidthMax=/dev/nvme0n1 20M
   EOF
   ```

2. **Place the service unit inside the slice**.

   ```ini
   # /etc/systemd/system/critical-db.service
   [Unit]
   Description=Critical PostgreSQL instance
   After=network.target
   PartOf=critical.slice

   [Service]
   ExecStart=/usr/lib/postgresql/15/bin/postgres -D /var/lib/pgsql/data
   ```

3. **Reload and start**.

   ```bash
   systemctl daemon-reload
   systemctl start critical-db.service
   ```

4. **Validate** – The service’s cgroup should now inherit the slice’s limits.

   ```bash
   cat /sys/fs/cgroup/system.slice/critical.slice/critical-db.service/cpu.max
   # Expected: 30000 100000 (30% of 100ms period)
   cat /sys/fs/cgroup/system.slice/critical.slice/critical-db.service/memory.max
   # Expected: 2147483648 (2 GiB)
   ```

### Using `cgroupfs` Directly (Advanced)

Sometimes you need to tweak limits for a *process* that is not managed by systemd. The unified hierarchy lets you write directly to the cgroup files.

```bash
# Create a temporary cgroup
mkdir -p /sys/fs/cgroup/mytemp

# Move the current shell into it
echo $$ > /sys/fs/cgroup/mytemp/cgroup.procs

# Apply a 100 MiB memory cap
echo $((100*1024*1024)) > /sys/fs/cgroup/mytemp/memory.max

# Verify
cat /sys/fs/cgroup/mytemp/memory.current
```

Be careful: writing an invalid value will cause the kernel to reject the change and return `EINVAL`. Always test in a non‑production shell first.

## Monitoring and Troubleshooting

### Real‑Time Metrics with Prometheus Node Exporter

The node exporter has built‑in support for cgroups v2 as of version 1.5. Enable the collector:

```bash
# /etc/systemd/system/node-exporter.service.d/override.conf
[Service]
Environment="NODE_EXPORTER_COLLECTORS_ENABLED=cgroup"
```

Metrics you’ll see:

* `node_cgroup_cpu_seconds_total` – Cumulative CPU time per cgroup.
* `node_cgroup_memory_usage_bytes` – Current memory usage.
* `node_cgroup_io_service_bytes_total` – Bytes read/written per device.

Grafana dashboards can be built on top of these series to alert when a service exceeds its quota.

### OOM and Memory Pressure

When a cgroup hits `memory.max`, the kernel may kill the offending process. The OOM killer writes to `memory.events`.

```bash
cat /sys/fs/cgroup/myapp/memory.events
# Example output:
# low 0
# high 0
# oom 1
# oom_kill 1
```

If you see `oom_kill` > 0, you have a hard limit breach. Mitigation strategies:

* Increase `memory.max` and add `memory.swap.max=0` to disallow swapping.
* Enable `memory.high` (soft limit) to trigger proactive reclamation before hitting the hard cap:

  ```bash
  echo $((800*1024*1024)) > /sys/fs/cgroup/myapp/memory.high   # 800 MiB soft limit
  ```

The kernel will start reclaiming pages once usage exceeds `memory.high`, reducing the chance of an OOM event.

### I/O Throttling Misbehaviour

If `io.max` appears to have no effect, verify:

1. **Device identification** – Use the major:minor format (`8:0` for `/dev/sda`).  
2. **Kernel support** – The `blkio` subsystem must be compiled with `CONFIG_BLK_DEV_THROTTLING`.  
3. **cgroup inheritance** – Child cgroups can only tighten limits, not loosen them.

```bash
# Example: limit a child cgroup to 5 MiB/s read on the same device
echo "8:0 rbps=5M" > /sys/fs/cgroup/parent/child/io.max
```

If the parent already set a tighter limit, the child’s setting will be ignored.

## Key Takeaways

- cgroups v2 consolidates all resource controllers under a single hierarchy, simplifying both configuration and observability.
- Use **systemd slices** for service‑level isolation; they automatically propagate CPU, memory, and I/O limits.
- Container runtimes (Docker, Kubernetes) now map their resource flags directly to the unified cgroup files, so you can treat containers as first‑class citizens in your isolation strategy.
- Real‑time metrics are readily exposed via the Prometheus node exporter; set alerts on `cpu.max`, `memory.events`, and `io.stat` to catch violations early.
- When troubleshooting, start with the `*.stat` and `*.events` files in the cgroup directory; they give you a precise view of what the kernel is accounting.

## Further Reading

- [Linux kernel documentation – Control Groups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd.resource-control – Managing resources with systemd](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)  
- [Kubernetes – Using cgroups v2 on nodes](https://kubernetes.io/docs/tasks/administer-cluster/cgroup-v2/)  