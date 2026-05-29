---
title: "Mastering cgroups v2 Resource Isolation: Implementation, Unified Hierarchy, and Production-Ready Control Groups"
date: "2026-05-29T18:00:47.702"
draft: false
tags: ["cgroups","linux","resource-management","kubernetes","devops"]
description: "Explore cgroups v2 in depth—how to implement resource isolation, leverage the unified hierarchy, and build production‑ready control groups for modern workloads."
summary: "A hands‑on guide that walks engineers through cgroups v2 setup, unified hierarchy design, and proven patterns for reliable resource isolation in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-29-mastering-cgroups-v2-resource-isolation-implementation-unified-hierarchy-and-production-ready-control-groups.svg"
  alt: "Diagram of Linux cgroups v2 hierarchy with containers and services."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 replaces the fragmented v1 tree with a single, unified hierarchy that lets you enforce CPU, memory, I/O, and pressure limits per workload. By enabling the kernel flag, configuring systemd slices, and applying the “resource‑control” attributes, you can build production‑grade isolation that scales from a single VM to a multi‑tenant Kubernetes cluster.

Resource isolation is no longer a nice‑to‑have feature; it’s a hard requirement for any service that must meet SLAs under noisy‑neighbor conditions. While most engineers are familiar with the legacy cgroups v1 interface, the Linux kernel has shipped cgroups v2 as the default since 5.4, and most modern distributions expose it through systemd. This post shows you how to move from “cgroups are on” to “cgroups are a first‑class production primitive”, with concrete commands, configuration snippets, and architectural patterns that you can copy into your own environments.

## Why cgroups v2 Matters

1. **Unified hierarchy** – Unlike v1, where each controller (cpu, memory, blkio, etc.) built its own tree, v2 presents a single tree. This eliminates the “controller mismatch” problem that caused processes to be placed in different sub‑trees for CPU vs. memory, leading to unintuitive resource accounting.  
2. **Improved accounting** – The `memory.pressure` and `cpu.pressure` metrics give you a direct view of how close a workload is to hitting its limits, enabling proactive throttling.  
3. **Better integration with systemd** – Systemd’s slice/unit model maps one‑to‑one onto cgroups v2, so you can declare limits in unit files without worrying about mounting separate controller filesystems.  
4. **Future‑proof** – The kernel development roadmap treats v2 as the only supported interface; new controllers (e.g., `io_uring`) will only appear under the unified tree.

> “cgroups v2 is to Linux resource control what HTTP/2 is to the web: a clean, single‑stream protocol that removes legacy baggage.” – [Linux Kernel Documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)

## Implementing cgroups v2: From Kernel to User Space

### 1. Verify Kernel Support

```bash
$ uname -r
5.15.0-78-generic
$ grep cgroup /proc/filesystems
cgroup
cgroup2
```

If `cgroup2` appears, the kernel already knows the new filesystem. On older kernels, enable it by adding `cgroup2` to the initramfs modules list and rebuilding.

### 2. Boot with the Unified Hierarchy

Add the following kernel parameter (or edit `/etc/default/grub` and run `update-grub`):

```text
systemd.unified_cgroup_hierarchy=1
```

After reboot, confirm the mount point:

```bash
$ mount | grep cgroup2
cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime)
```

### 3. Enable Controllers

cgroups v2 starts with **no controllers enabled**. Enable the ones you need through the `cgroup.subtree_control` file at the root of the hierarchy.

```bash
# Enable CPU, memory, and I/O controllers
$ echo "+cpu +memory +io" > /sys/fs/cgroup/cgroup.subtree_control
```

> The plus sign (`+`) adds a controller; a minus (`-`) removes it. This command must be run as root, and it propagates to all child cgroups automatically.

### 4. Create a Test Slice with systemd

Systemd abstracts cgroup creation via *slices* and *scopes*. The following unit creates a slice named `demo.slice` with explicit limits:

```ini
# /etc/systemd/system/demo.slice
[Slice]
# CPU: 20% of a single core (20000 µseconds per 100 ms period)
CPUQuota=20%
# Memory: 512 MiB soft limit, 1 GiB hard limit
MemoryLimit=1G
MemoryLow=512M
# I/O: limit to 10 MiB/s read on /dev/sda
IOReadBandwidthMax=/dev/sda 10M
```

Reload systemd and start the slice:

```bash
$ sudo systemctl daemon-reload
$ sudo systemctl start demo.slice
```

All processes launched under this slice (e.g., via `systemd-run -p Slice=demo.slice`) will inherit the limits.

### 5. Direct cgroup Manipulation (Optional)

For environments that bypass systemd (e.g., custom container runtimes), you can write to the cgroup files directly:

```bash
# Create a new cgroup under the unified hierarchy
$ mkdir /sys/fs/cgroup/myapp
$ echo 500000 > /sys/fs/cgroup/myapp/cpu.max   # 0.5 CPU (500 ms per 1 s)
$ echo 1G > /sys/fs/cgroup/myapp/memory.max
# Add a process
$ echo 12345 > /sys/fs/cgroup/myapp/cgroup.procs
```

The `cpu.max` file uses the `max period` syntax (`max period` = `<quota> <period>`). Setting `max` to `max` disables throttling.

## The Unified Hierarchy Explained

### 2.1 Tree Layout

```
/sys/fs/cgroup
├─ .scope            (systemd’s internal scope)
├─ user.slice
│  ├─ user-1000.slice
│  │  ├─ session-2.scope
│  │  └─ myapp.slice
│  │     └─ myapp.service
│  └─ user-1001.slice
└─ demo.slice
```

Every node in this tree can have its own set of *resource controls*. Because the hierarchy is unified, a child automatically inherits the controller set of its parent, preventing the “partial‑controller” problem that plagued v1.

### 2.2 Pressure Stall Information (PSI)

cgroups v2 introduces PSI files that expose *resource pressure*:

- `cpu.pressure`
- `memory.pressure`
- `io.pressure`

These files contain three fields: `some avg10 avg60 avg300 total`. For example:

```bash
$ cat /sys/fs/cgroup/demo.slice/cpu.pressure
some 0.00/0.00/0.00 avg10=0.01 avg60=0.03 avg300=0.05 total=12345
```

A rising `avg60` indicates sustained CPU contention, prompting you to either increase the quota or shed load.

### 2.3 Delegation Model

When you expose a subtree to an untrusted tenant (e.g., a multi‑tenant SaaS platform), you can **delegate** controllers:

```bash
# In the parent cgroup
$ echo "+cpu +memory" > child.cgroup.subtree_control
# In the child (tenant) cgroup
$ echo 500M > memory.max          # Tenant can only set limits within parent bounds
```

The kernel enforces that a child cannot enable a controller that the parent has not exposed, providing a clean security boundary.

## Production‑Ready Control Group Patterns

### 3.1 Slice‑Per‑Service Pattern (systemd)

Most production services run as systemd units. By creating a dedicated slice per microservice, you gain:

- **Isolation** – Each slice gets its own CPU, memory, and I/O caps.
- **Observability** – PSI metrics are scoped to the slice, simplifying alerting.
- **Graceful degradation** – When a slice hits its `memory.max`, the kernel OOM‑kills only processes inside that slice, preserving the rest of the host.

**Implementation checklist**

| Step | Action |
|------|--------|
| 1 | Define a `.slice` file with `CPUQuota`, `MemoryMax`, `IOReadBandwidthMax`, etc. |
| 2 | Set `Delegate=yes` if you need child cgroups (e.g., containers) to adjust limits. |
| 3 | Add `Restart=on-failure` to the service unit to avoid silent death. |
| 4 | Export PSI metrics to Prometheus via `node_exporter`'s `cgroup` collector. |
| 5 | Create alerts on `cpu.pressure` > 0.2 (60‑second avg) and `memory.pressure` > 0.15. |

### 3.2 Container Runtime Integration

Both **Docker** (v20+) and **containerd** expose cgroups v2 when the daemon is started with `--cgroupns=private` and the host is running the unified hierarchy. Example for containerd:

```bash
$ cat /etc/containerd/config.toml
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true   # Use systemd for cgroup management
```

When systemd is the cgroup driver, each container becomes a *systemd scope* under the slice you assign via the `--slice` flag:

```bash
$ sudo ctr run --rm --gpus 0 --slice demo.slice docker.io/library/nginx:latest mynginx
```

The container now inherits the `demo.slice` limits, and you can further fine‑tune per‑container resources by setting `resources.limits` in the pod spec (Kubernetes) or using `docker run --cpu-quota` (Docker) – both translate to `cpu.max` under the hood.

### 3.3 Multi‑Tenant Kubernetes with cgroups v2

Kubernetes 1.27+ ships with the `systemd` cgroup driver by default on most distros. To enforce per‑namespace isolation:

1. **Create a RuntimeClass** that specifies a custom `podAnnotations` mapping to a systemd slice:

   ```yaml
   apiVersion: node.k8s.io/v1
   kind: RuntimeClass
   metadata:
     name: demo-slice
   handler: runc
   overhead:
     pod: {"cpu": "100m", "memory": "256Mi"}
   ```

2. **Annotation on the pod**:

   ```yaml
   apiVersion: v1
   kind: Pod
   metadata:
     name: tenant-a
     annotations:
       io.kubernetes.cri-o.SandboxCgroup: "demo.slice"
   spec:
     runtimeClassName: demo-slice
     containers:
     - name: app
       image: myorg/app:latest
       resources:
         limits:
           cpu: "500m"
           memory: "1Gi"
   ```

Kubernetes will instruct the container runtime to place the pod’s sandbox in `demo.slice`. The slice’s limits become the hard ceiling for every container in the pod, while the pod’s `resources.limits` become *soft* caps that the kube‑let can enforce via cgroup `cpu.max` and `memory.max`.

### 3.4 Monitoring & Alerting Blueprint

A production‑ready setup should surface cgroup metrics to a central observability stack:

- **node_exporter** (Prometheus) – enable `--collector.cgroup` to scrape `cpu.max`, `memory.current`, and PSI files.
- **Grafana dashboards** – use the community “cgroup v2” dashboard as a base, add panels for `memory.pressure` and `io.pressure`.
- **Alert rules** (Prometheus):

```yaml
- alert: HighCpuPressure
  expr: avg_over_time(node_cgroup_cpu_pressure_seconds_total{slice="demo.slice"}[5m]) > 0.2
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "CPU pressure high on demo.slice"
    description: "Average CPU pressure over the last 5 minutes is {{ $value }}, indicating possible throttling."

- alert: OOMKilledInSlice
  expr: increase(node_cgroup_oom_kill_total{slice="demo.slice"}[1h]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "OOM kills detected in demo.slice"
    description: "One or more processes were killed by the OOM killer in the last hour."
```

## Architecture Blueprint for Isolated Services

Below is a simplified diagram of a production host running three independent services, each confined to its own cgroup slice:

```
+---------------------------------------------------+
| Host (Linux + systemd)                            |
|                                                   |
|  /sys/fs/cgroup                                    |
|   ├─ web.slice   (CPU 30%, Mem 2Gi, IO 20Mi/s)   |
|   │   └─ web.service  <-- Nginx, PHP-FPM         |
|   ├─ worker.slice (CPU 20%, Mem 1Gi, IO 10Mi/s) |
|   │   └─ worker.service <-- Celery workers       |
|   └─ db.slice    (CPU 40%, Mem 4Gi, IO 50Mi/s)   |
|       └─ postgres.service <-- PostgreSQL         |
+---------------------------------------------------+
```

**Key architectural benefits**

1. **Predictable performance** – Each slice’s `CPUQuota` guarantees a share of the CPU, preventing a spike in the worker tier from starving the web tier.
2. **Fault containment** – If PostgreSQL exceeds its memory limit, only the `db.slice` processes are OOM‑killed; the web front‑end remains available.
3. **Observability isolation** – PSI metrics per slice allow you to set tier‑specific alerts (e.g., tighter I/O pressure thresholds for the database).

### Deploying the Blueprint with Ansible

A quick Ansible role can enforce the slice files across a fleet:

```yaml
- name: Deploy cgroup slices
  become: true
  copy:
    dest: "/etc/systemd/system/{{ item.name }}.slice"
    content: |
      [Slice]
      CPUQuota={{ item.cpu_quota }}
      MemoryMax={{ item.mem_max }}
      IOReadBandwidthMax={{ item.io_dev }} {{ item.io_limit }}
  loop:
    - { name: web, cpu_quota: "30%", mem_max: "2G", io_dev: "/dev/sda", io_limit: "20M" }
    - { name: worker, cpu_quota: "20%", mem_max: "1G", io_dev: "/dev/sda", io_limit: "10M" }
    - { name: db, cpu_quota: "40%", mem_max: "4G", io_dev: "/dev/sda", io_limit: "50M" }
  notify: Reload systemd

- name: Reload systemd
  become: true
  systemd:
    daemon_reload: yes
```

Run the playbook, and every host instantly gains the same isolation guarantees without manual edits.

## Key Takeaways

- **Unified hierarchy** eliminates controller fragmentation; enable the needed controllers once at the root and they cascade.
- **Systemd slices** are the idiomatic production interface—declare limits in unit files, let systemd manage the underlying cgroup files.
- **Pressure Stall Information (PSI)** provides actionable metrics for CPU, memory, and I/O contention; integrate them into Prometheus alerts.
- **Delegation** lets you safely expose sub‑cgroups to untrusted tenants while preserving strict upper bounds.
- **Kubernetes integration** works out‑of‑the‑box with the `systemd` cgroup driver; map pods to slices for per‑namespace hard caps.
- **Monitoring + automation** (node_exporter + Grafana + Ansible) turns raw cgroup knobs into a reproducible, observable platform.

## Further Reading

- [Linux kernel cgroups v2 documentation](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd.resource-control man page](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)  
- [Kubernetes documentation on cgroup drivers](https://kubernetes.io/docs/tasks/administer-cluster/cgroup-driver/)  