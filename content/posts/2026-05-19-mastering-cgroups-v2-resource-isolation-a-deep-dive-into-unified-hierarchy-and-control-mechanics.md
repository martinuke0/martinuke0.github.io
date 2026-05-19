---
title: "Mastering cgroups v2 Resource Isolation: A Deep Dive into Unified Hierarchy and Control Mechanics"
date: "2026-05-19T13:00:13.193"
draft: false
tags: ["cgroups","linux","resource-management","systemd","performance"]
description: "Explore cgroups v2’s unified hierarchy, control files, and production patterns for precise CPU, memory, and I/O isolation on Linux enterprise systems."
summary: "A practical guide to cgroups v2’s unified hierarchy, showing how to configure CPU, memory, and I/O limits with systemd and raw cgroup files."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-mastering-cgroups-v2-resource-isolation-a-deep-dive-into-unified-hierarchy-and-control-mechanics.svg"
  alt: "Diagram of a Linux cgroup v2 hierarchy with resource controllers."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 collapses all controllers into a single, unified hierarchy, letting you enforce CPU, memory, and I/O limits with a handful of control files. By delegating slices to systemd or managing raw files directly, you gain production‑grade isolation without the fragmentation of cgroups v1.

Resource isolation is the backbone of modern cloud‑native workloads. While many engineers still configure limits with the legacy cgroups v1 interface, Linux’s cgroups v2 offers a cleaner, more predictable model that integrates tightly with systemd. This post unpacks the unified hierarchy, walks through the most useful control files, and shows proven patterns for deploying cgroups v2 at scale.

## Why cgroups v2 Matters

cgroups (control groups) were introduced in 2007 to partition kernel resources among processes. The original design grew a patchwork of independent hierarchies—one per controller—leading to:

* **Fragmented accounting** – a process could appear in multiple hierarchies with contradictory limits.
* **Complex delegation** – moving a process between groups required coordination across controllers.
* **Inconsistent tooling** – some utilities only understood v1, forcing hybrid setups.

cgroups v2, merged into the mainline kernel in 2015, solves these pain points by enforcing a **single unified hierarchy**. All enabled controllers (cpu, memory, io, pids, etc.) coexist under one tree, guaranteeing that a process’s resource view is coherent across the board.

> “The unified hierarchy eliminates the ‘controller‑scattered‑tree’ problem that plagued v1, making policy enforcement deterministic.” – [Kernel documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

## Unified Hierarchy Architecture

### The Tree Model

At boot, the kernel mounts a single filesystem:

```bash
mount -t cgroup2 none /sys/fs/cgroup
```

The mount point becomes the **root cgroup** (`/`). Every subsequent cgroup is a subdirectory, and each directory inherits the same set of enabled controllers. For example:

```
/sys/fs/cgroup
├─ user.slice
│  ├─ user-1000.slice
│  │  └─ session-2.scope
│  └─ user-1001.slice
└─ system.slice
   ├─ nginx.service
   └─ docker.service
```

* **Slices** (`*.slice`) are systemd’s abstraction for grouping related services.
* **Scopes** (`*.scope`) represent transient units attached to an existing process tree.
* **Units** (`*.service`) are the leaf nodes where the actual workload runs.

Because the hierarchy is unified, any controller enabled at the root automatically applies to every descendant unless a child explicitly disables it (rare in production).

### Enabling Controllers

Not all controllers are active by default. The kernel exposes the list under `cgroup.controllers`:

```bash
cat /sys/fs/cgroup/cgroup.controllers
# cpu memory io pids
```

Systemd decides which controllers to enable at boot via the `systemd.unified_cgroup_hierarchy` kernel command line flag (default = 1 on most modern distros). You can verify the active set with:

```bash
systemctl show -p DefaultControllers
```

If you need to add a controller after boot (e.g., `rdma`), you can write to `cgroup.subtree_control` on the appropriate node:

```bash
echo "+rdma" > /sys/fs/cgroup/system.slice/cgroup.subtree_control
```

> Note: Only privileged users (or processes with the `CAP_SYS_ADMIN` capability) can modify `cgroup.subtree_control`.

## Control Files and Mechanics

Each controller offers a set of **control files** that read or write resource limits, statistics, and event notifications. Below we focus on the three most common controllers: **cpu**, **memory**, and **io**.

### CPU Controller (`cpu.max` and `cpu.weight`)

* `cpu.max` – Sets a hard limit in the format `<max_usec> <period_usec>`. A value of `max 100000` disables throttling.
* `cpu.weight` – Relative share (1‑10 000) used by the scheduler when contention occurs.

Example: Limit a container to 20 % of a single CPU core (using the default period of 100 ms):

```bash
# Inside the cgroup directory for the container
echo "20000 100000" > cpu.max
```

Or give it a higher priority in a crowded node:

```bash
echo "8000" > cpu.weight   # ~80 % of the default weight
```

Systemd translates these files from the unit’s `CPUQuota=` and `CPUWeight=` directives. For instance:

```ini
# /etc/systemd/system/myapp.service
[Service]
CPUQuota=30%
CPUWeight=9000
```

When the unit starts, systemd writes the appropriate values into the underlying cgroup files.

### Memory Controller (`memory.max`, `memory.high`, `memory.swap.max`)

* `memory.max` – Hard limit in bytes. OOM killer is invoked once the limit is breached.
* `memory.high` – Soft limit that triggers reclamation but does not kill the process.
* `memory.swap.max` – Controls swap usage per cgroup (default = unlimited).

Setting a 2 GiB hard cap with a 1 GiB soft threshold:

```bash
echo $((2*1024*1024*1024)) > memory.max
echo $((1*1024*1024*1024)) > memory.high
```

Systemd equivalents:

```ini
# /etc/systemd/system/db.service
[Service]
MemoryMax=2G
MemoryHigh=1G
```

### I/O Controller (`io.max`)

The I/O controller uses the **blkio** syntax, but v2 consolidates it under `io.max`. You specify a device major:minor pair followed by a throttling rule:

```
<major>:<minor> <rbps>|<riops> <wbps>|<wiops>
```

Example: Limit a database to 50 MiB/s reads and 30 MiB/s writes on `/dev/sda` (major 8, minor 0):

```bash
echo "8:0 rbps=52428800 wbps=31457280" > io.max
```

Systemd syntax (in a unit file) mirrors this:

```ini
[Service]
IOReadBandwidthMax=/dev/sda 50M
IOWriteBandwidthMax=/dev/sda 30M
```

### Event Notification (`cgroup.events`)

All controllers expose a unified `cgroup.events` file that reports state changes such as OOM, memory pressure, or I/O throttling. Polling this file is a lightweight way to integrate with health‑check agents.

```bash
while read -r line; do
    echo "Event: $line"
done < /sys/fs/cgroup/myapp.slice/cgroup.events
```

## Patterns in Production

### Delegating to systemd vs. Direct Management

| Aspect                | systemd delegation                              | Direct cgroup file manipulation |
|-----------------------|--------------------------------------------------|-----------------------------------|
| **Ease of use**       | High – unit files express limits declaratively | Medium – requires manual writes   |
| **Dynamic scaling**  | Supports `systemctl set-property` at runtime    | Must echo into files yourself     |
| **Security**          | Leverages `Delegate=` and `ProtectSystem=`      | Must manage capabilities manually|
| **Portability**       | Works across most modern distros                | May differ on older kernels      |

**Best practice**: Use systemd for long‑running services (web servers, databases) and fall back to raw cgroup files for short‑lived containers launched by custom orchestrators.

### Container Orchestration with `crun`

`crun` is a lightweight OCI runtime that natively uses cgroups v2. When you launch a pod with `crun`, it creates a dedicated subtree under `/sys/fs/cgroup` and populates all control files based on the OCI spec.

```bash
crun create mypod /path/to/config.json
crun start mypod
```

Because `crun` talks directly to the kernel, you can avoid the systemd‑to‑cgroup translation layer and achieve lower latency in limit enforcement—critical for high‑frequency trading workloads.

### Multi‑Tenant SaaS: Isolation Blueprint

1. **Root slice per tenant** – Create a `tenant-<id>.slice` via `systemd-run`:

    ```bash
    systemd-run --slice=tenant-42.slice --property=CPUQuota=40% --property=MemoryMax=8G \
                --unit=tenant-42-manager.service /usr/bin/tenant-manager
    ```

2. **Per‑service sub‑slices** – Inside the tenant slice, launch each microservice as a separate unit (`svc-frontend.service`, `svc-backend.service`). Inherit tenant‑wide limits automatically.

3. **Dynamic scaling** – Adjust limits on the fly with `systemctl set-property` without redeploying containers:

    ```bash
    systemctl set-property svc-backend.service CPUQuota=60%
    ```

4. **Telemetry** – Export `cgroup.events` and `memory.stat` via Prometheus node‑exporter’s `cgroup` collector. This gives you per‑tenant OOM alerts and I/O throttling metrics.

### Handling OOM in Production

When `memory.max` is reached, the kernel kills the *most* memory‑intensive task in the cgroup. To avoid silent service restarts:

* Enable `OOMScoreAdjust=` in the unit file to bias the OOM killer toward less critical processes.
* Use `systemd-cgtop` to monitor memory pressure in real time.
* Hook into `cgroup.events` and trigger a custom alert:

    ```bash
    if grep -q "memory.oom" /sys/fs/cgroup/myapp.slice/cgroup.events; then
        curl -XPOST -d '{"text":"⚠️ OOM in myapp"}' https://hooks.slack.com/services/XXX/YYY/ZZZ
    fi
    ```

## Performance Implications

### Latency of Limit Enforcement

Because cgroups v2 consolidates controllers, the kernel can evaluate resource usage in a single pass, reducing the per‑syscall overhead. Benchmarks from the Red Hat performance team show:

| Workload          | v1 (separate hierarchies) | v2 (unified) |
|-------------------|---------------------------|--------------|
| CPU‑bound loop   | 1.42 µs per iteration     | 1.08 µs      |
| Memory churn      | 2.31 µs per allocation    | 1.95 µs      |
| Disk I/O throttling | 3.12 µs per request    | 2.68 µs      |

The gains are modest per operation but compound dramatically in high‑QPS services.

### Scheduler Interactions

The `cpu.weight` value maps to the **CFS** (Completely Fair Scheduler) bandwidth allocation. In a mixed‑tenant environment, allocating weights proportional to Service Level Objectives (SLOs) yields deterministic latency slices. For example, a latency‑critical API with `CPUWeight=9000` will receive roughly 9 × the CPU time of a background batch job with `CPUWeight=1000`.

### Memory Pressure and Reclaim

`memory.high` triggers **soft reclamation** before hitting the hard limit. The kernel’s **reclaim daemon** works more aggressively when a cgroup’s `memory.high` is crossed, freeing page cache and inactive anon pages. Production teams often set `memory.high` at 80 % of `memory.max` to keep a safety margin while still allowing bursty workloads.

## Common Pitfalls and How to Avoid Them

1. **Forgot to enable a controller** – The kernel silently ignores writes to a disabled controller’s files. Always check `cgroup.controllers` before configuring.
2. **Mixing v1 and v2 hierarchies** – Some legacy tools (e.g., `cgcreate`) still mount a v1 hierarchy under `/sys/fs/cgroup`. Running both on the same host can cause duplicate resource accounting. Use `systemd`’s `Delegate=` flag to isolate legacy workloads.
3. **Improper subtree control** – Writing `+cpu` to `cgroup.subtree_control` on a parent without also enabling the controller on the parent itself results in “Operation not permitted”. The correct sequence:
    ```bash
    echo "+cpu" > /sys/fs/cgroup/cgroup.subtree_control
    echo "+cpu" > /sys/fs/cgroup/user.slice/cgroup.subtree_control
    ```
4. **Ignoring `cgroup.procs`** – Adding a PID to `cgroup.procs` moves the process *and all its children* into the target cgroup. Forgetting this can leave orphaned processes running with default limits.

## Key Takeaways

- cgroups v2 replaces fragmented hierarchies with a **single unified tree**, simplifying policy enforcement.
- Controllers are enabled via `cgroup.controllers`; limits are set through concise control files such as `cpu.max`, `memory.max`, and `io.max`.
- Systemd provides a declarative front‑end (`CPUQuota=`, `MemoryMax=`, `IOReadBandwidthMax=`) that writes directly to the underlying cgroup files.
- For container runtimes that need low‑latency isolation, tools like **crun** interact directly with the v2 API.
- Production patterns—tenant slices, dynamic `systemctl set-property`, and event‑driven alerts—leverage the unified model to achieve deterministic resource guarantees.
- Monitoring `cgroup.events` and the various `*.stat` files gives you early visibility into pressure, OOM, and throttling before they impact SLAs.

## Further Reading

- [Linux kernel – Control Groups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd – Managing control groups](https://systemd.io/CGROUP_DELEGATION/)  
- [Red Hat – Using cgroups v2 to control system resources](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/monitoring_and_managing_systems_using_systemd/using-cgroups-v2_to_control-system-resources_monitoring-and-managing-system)  
- [crun – OCI runtime with native cgroup v2 support](https://github.com/containers/crun)  
- [Prometheus – node_exporter cgroup collector](https://github.com/prometheus/node_exporter#cgroup-metrics)