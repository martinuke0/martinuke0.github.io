---
title: "Mastering Cgroups v2 Resource Isolation: A Deep Dive into Unified Hierarchy and Control Controllers"
date: "2026-05-27T11:00:45.870"
draft: false
tags: ["cgroups","linux","resource-management","devops","containers"]
description: "Explore how cgroups v2’s unified hierarchy and control controllers deliver fine-grained resource isolation in Linux production, with patterns, configs, and real‑world examples."
summary: "A practical guide for engineers to harness cgroups v2 for CPU, memory, I/O, and device isolation, featuring architecture diagrams and production‑ready configs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-27-mastering-cgroups-v2-resource-isolation-a-deep-dive-into-unified-hierarchy-and-control-controllers.svg"
  alt: "Diagram of a Linux process tree with cgroup v2 hierarchy overlay."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 replaces the fragmented v1 tree with a single, unified hierarchy and a set of modular controllers. By mastering its mount options, controller activation, and per‑cgroup configuration files, you can achieve deterministic CPU, memory, I/O, and device isolation for containers, VMs, or any Linux workload.

Resource isolation has become a non‑negotiable requirement for modern cloud‑native workloads. While cgroups v1 served us well for a decade, its scattered hierarchy and controller‑specific quirks made large‑scale tuning a nightmare. This post unpacks the **unified hierarchy**, walks through each **control controller**, and shows how production teams at Netflix, Shopify, and Red Hat have baked cgroups v2 into their deployment pipelines.

## Unified Hierarchy Overview

cgroups v2 collapses the eight (or more) separate v1 hierarchies into a **single virtual filesystem** mounted at `/sys/fs/cgroup`. All enabled controllers operate **side‑by‑side** on the same tree, which eliminates cross‑hierarchy race conditions and simplifies bookkeeping.

### What Changed from v1

| Aspect | cgroups v1 | cgroups v2 |
|--------|------------|------------|
| Hierarchy | One mount per controller (e.g., `cpu`, `memory`) | Single mount, all enabled controllers share it |
| Controller activation | Implicit when a controller is mounted | Explicit via `cgroup.subtree_control` file |
| Resource distribution | `cpu.shares`, `memory.limit_in_bytes` per hierarchy | Unified `cpu.max`, `memory.max` per cgroup |
| Process placement | `cgroup.procs` file per hierarchy | Single `cgroup.procs` file per node in the unified tree |

The **single mount** means you can now reason about a workload’s resource envelope in one place, and you no longer need to remember which hierarchy a given controller lives under.

### Mounting the Unified Hierarchy

On a modern distro with kernel ≥ 5.4, the unified hierarchy is usually enabled by default. If you need to enforce it manually:

```bash
# Bash – mount cgroup2 as the only cgroup filesystem
sudo mount -t cgroup2 none /sys/fs/cgroup
```

To make the mount persistent across reboots, add the following line to `/etc/fstab`:

```fstab
none    /sys/fs/cgroup    cgroup2    defaults    0   0
```

> **Note** – The kernel parameter `systemd.unified_cgroup_hierarchy=1` forces systemd to bootstrap the unified hierarchy early in the boot process. See the systemd docs for details.

## Control Controllers Deep Dive

cgroups v2 ships with a **core set of controllers** that can be turned on or off per subtree. The most common ones for production workloads are `cpu`, `memory`, `io`, `pids`, and `cpuset`. Below we explore each controller’s syntax, typical usage patterns, and pitfalls.

### CPU Controller

The CPU controller in v2 uses **bandwidth‑based throttling** rather than the share‑based model of v1. Two files are relevant:

* `cpu.max` – defines the **hard quota** and **period**.
* `cpu.weight` – a relative priority used when the quota is not set.

#### Setting a hard quota

```bash
# Bash – limit a cgroup to 200 ms of CPU every 1 s (20% of a single core)
echo "200000 1000000" > /sys/fs/cgroup/myservice/cpu.max
```

The values are in **microseconds**. If you need a fractional number of cores, multiply the desired share by the period (default 100 ms) and write that as the quota.

#### Using weight for best‑effort scheduling

```bash
# Bash – give this cgroup a weight of 200 (default is 100)
echo 200 > /sys/fs/cgroup/myservice/cpu.weight
```

Higher weight translates to more CPU time when the system is under contention, but it does **not** enforce a hard limit.

### Memory Controller

Memory isolation is expressed with two files:

* `memory.max` – the absolute limit in bytes.
* `memory.high` – a *soft* threshold that triggers reclamation but does not kill the cgroup.

#### Hard limit example

```bash
# Bash – cap the cgroup at 2 GiB
echo $((2 * 1024 * 1024 * 1024)) > /sys/fs/cgroup/myservice/memory.max
```

#### Soft limit and OOM handling

```bash
# Bash – set a high watermark at 1.5 GiB
echo $((1536 * 1024 * 1024)) > /sys/fs/cgroup/myservice/memory.high
```

When usage exceeds `memory.high`, the kernel starts reclaiming pages from the cgroup before hitting `memory.max`. If `memory.max` is breached, the cgroup receives an OOM kill, just like a process‑level OOM.

> **Caution** – Do not set `memory.max` to “max” (the string) if you plan to later enforce a limit; the kernel will treat it as *unlimited* and you’ll lose the ability to enforce a hard cap without remounting.

### I/O Controller (`io`)

The I/O controller works on a **per‑device** basis, using the `io.max` file. It accepts **weighted I/O** (`rbps`, `wbps`) and **IOPS** limits.

#### Limiting a block device

```bash
# Bash – limit /dev/sda to 10 MiB/s reads and 5 MiB/s writes
echo "8:0 rbps=10485760 wbps=5242880" > /sys/fs/cgroup/myservice/io.max
```

`8:0` is the major:minor number for `/dev/sda`. You can discover it with `lsblk -dno MAJ:MIN /dev/sda`.

#### Combining IOPS and bandwidth

```bash
# Bash – 1000 read IOPS and 500 write IOPS on /dev/nvme0n1
echo "259:0 riops=1000 wiops=500" > /sys/fs/cgroup/myservice/io.max
```

### PIDs Controller

The `pids` controller caps the **number of processes** (including threads) that can be spawned in a cgroup. This is a safety net against fork bombs.

```bash
# Bash – allow at most 200 processes
echo 200 > /sys/fs/cgroup/myservice/pids.max
```

When the limit is reached, `fork()` returns `EAGAIN`, and the offending workload typically logs an error. This is especially useful for untrusted code execution environments.

### Cpuset Controller

`cpuset` pins a cgroup to a specific set of CPUs and memory nodes. It requires **two files**:

* `cpuset.cpus` – list of logical CPUs (e.g., `0-3,8-11`).
* `cpuset.mems` – list of NUMA memory nodes.

#### Example: isolate a service to a dedicated CPU socket

```bash
# Bash – bind to CPUs 0‑7 (first socket) and NUMA node 0
echo "0-7" > /sys/fs/cgroup/myservice/cpuset.cpus
echo "0"   > /sys/fs/cgroup/myservice/cpuset.mems
```

When you enable `cpuset`, you must also enable it on the **parent** cgroup, otherwise the kernel will reject the write with `EINVAL`.

## Architecture Patterns in Production

cgroups v2 is not a standalone toy; it is the backbone of **container runtimes**, **systemd slices**, and **Kubernetes pod isolation**. Below we outline three proven patterns.

### 1. Systemd Slice per Service

Systemd automatically creates a **slice** (`myservice.slice`) that maps to a dedicated cgroup subtree. By adding `CPUQuota=20%` and `MemoryMax=2G` to the unit file, you let systemd translate those directives into the appropriate `cpu.max` and `memory.max` files.

```ini
# /etc/systemd/system/myservice.service
[Unit]
Description=My high‑throughput API

[Service]
ExecStart=/usr/local/bin/myservice
Slice=myservice.slice
Restart=on-failure

[Slice]
CPUQuota=20%
MemoryMax=2G
IOWeight=500
```

When the unit starts, systemd writes the values into the unified hierarchy, ensuring **consistent enforcement** across reboots.

### 2. Kubernetes Pod Cgroup Integration

Kubernetes 1.27+ enables the **cgroup v2 driver** (`systemd`) by default. The kubelet creates a pod‑level cgroup under `/sys/fs/cgroup/kubepods.slice/kubepods-besteffort.slice`. Resource requests/limits in the pod spec become `cpu.max` and `memory.max` entries.

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: data‑worker
spec:
  containers:
  - name: worker
    image: myorg/worker:latest
    resources:
      requests:
        cpu: "500m"
        memory: "1Gi"
      limits:
        cpu: "1"
        memory: "2Gi"
```

The kubelet also configures **IO throttling** via the `io.max` controller if the `DeviceResources` feature gate is enabled.

### 3. Edge‑Node Isolation with Podman

Podman (v4+) ships with native cgroup v2 support. When you run `podman run --cgroup-manager=cgroupfs`, Podman creates a dedicated subtree under `/sys/fs/cgroup/podman`. You can pass fine‑grained limits directly:

```bash
podman run -d \
  --name analytics \
  --cpu-quota=200000 --cpu-period=1000000 \
  --memory=2g \
  --pids-limit=150 \
  myorg/analytics:latest
```

Behind the scenes, Podman writes the same values we demonstrated earlier, giving you **CLI‑level parity** with systemd slices.

## Configuring cgroups v2 in Real Deployments

Below is a step‑by‑step checklist that production teams can embed into their CI/CD pipelines.

1. **Detect unified hierarchy**  
   ```bash
   if mountpoint -q /sys/fs/cgroup && grep -q cgroup2 /proc/mounts; then
       echo "Unified hierarchy present"
   else
       echo "Fallback to v1 – abort"
       exit 1
   fi
   ```

2. **Enable required controllers** on the root cgroup (only once).  
   ```bash
   echo "+cpu +memory +io +pids +cpuset" > /sys/fs/cgroup/cgroup.subtree_control
   ```

3. **Create a dedicated subtree** for the service.  
   ```bash
   mkdir /sys/fs/cgroup/myservice
   ```

4. **Assign processes** – echo the PID(s) into `cgroup.procs`.  
   ```bash
   echo $$ > /sys/fs/cgroup/myservice/cgroup.procs   # current shell
   ```

5. **Apply limits** – write to the appropriate controller files (see sections above).  
   ```bash
   echo "200000 1000000" > /sys/fs/cgroup/myservice/cpu.max
   echo $((2*1024*1024*1024)) > /sys/fs/cgroup/myservice/memory.max
   echo "8:0 rbps=10485760 wbps=5242880" > /sys/fs/cgroup/myservice/io.max
   echo 200 > /sys/fs/cgroup/myservice/pids.max
   echo "0-3" > /sys/fs/cgroup/myservice/cpuset.cpus
   echo "0"   > /sys/fs/cgroup/myservice/cpuset.mems
   ```

6. **Validate** – read back the files and compare with expectations.  
   ```bash
   cat /sys/fs/cgroup/myservice/cpu.max
   cat /sys/fs/cgroup/myservice/memory.max
   ```

7. **Monitor** – use `systemd-cgtop` or `cgroupfs`‑compatible tools like `cgroup2-tools` to watch live usage.  
   ```bash
   systemd-cgtop -n 5
   ```

### Automating with Ansible

A minimal Ansible role can enforce the same configuration across a fleet:

```yaml
# tasks/main.yml
- name: Ensure unified hierarchy is mounted
  mount:
    path: /sys/fs/cgroup
    src: none
    fstype: cgroup2
    state: mounted

- name: Enable controllers on root
  copy:
    dest: /sys/fs/cgroup/cgroup.subtree_control
    content: "+cpu +memory +io +pids +cpuset"
    mode: '0644'

- name: Create service cgroup
  file:
    path: /sys/fs/cgroup/{{ service_name }}
    state: directory
    mode: '0755'

- name: Apply resource limits
  block:
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/cpu.max
        content: "{{ cpu_quota }} {{ cpu_period }}"
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/memory.max
        content: "{{ memory_limit }}"
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/io.max
        content: "{{ io_limits }}"
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/pids.max
        content: "{{ pids_limit }}"
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/cpuset.cpus
        content: "{{ cpus }}"
    - copy:
        dest: /sys/fs/cgroup/{{ service_name }}/cpuset.mems
        content: "{{ mems }}"
```

Deploying this role ensures **idempotent** enforcement of cgroup limits, a pattern widely adopted at companies with thousands of nodes.

## Common Pitfalls and Debugging

Even seasoned engineers stumble over a few recurring issues.

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `write error: Invalid argument` when echoing to `cpuset.cpus` | Parent cgroup does not have `cpuset` enabled | Enable `+cpuset` on the parent’s `cgroup.subtree_control` first |
| Process escapes the limit after a reboot | Limits were set on a **temporary** cgroup that disappears on restart | Persist configuration via systemd slice, kubelet, or a startup script |
| OOM kills despite `memory.high` being set | `memory.max` is still **unlimited** (`max`) | Set a finite `memory.max` value; `memory.high` alone cannot prevent hard OOM |
| `io.max` has no effect on SSDs | Underlying block device does not support throttling (e.g., NVMe with kernel < 5.12) | Upgrade kernel or use a different device that implements the `blk-mq` throttling path |
| `systemd-cgtop` shows 0% CPU for a throttled container | CPU quota is too low relative to the period; kernel rounds down to 0 | Increase the period (second column) or raise the quota proportionally |

When in doubt, consult the **kernel documentation** for the controller you’re tweaking. The official cgroup v2 reference is an excellent source: <https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html>.

## Key Takeaways

- cgroups v2’s **unified hierarchy** eliminates the fragmentation of v1, letting you manage all resources from a single tree.
- Controllers (`cpu`, `memory`, `io`, `pids`, `cpuset`) use **simple flat files** (`*.max`, `*.weight`, etc.) that can be scripted or managed by systemd/Kubernetes.
- Production‑grade isolation patterns include **systemd slices**, **Kubernetes pod cgroups**, and **Podman subtrees**.
- Always enable controllers on the **parent** before writing to child cgroups; otherwise you’ll hit `EINVAL`.
- Persist limits via declarative mechanisms (systemd unit files, kubelet specs, Ansible roles) to survive reboots and node churn.
- Monitor with `systemd-cgtop` or specialized tools; validate limits after each deployment to catch regression early.

## Further Reading

- [Linux kernel documentation – Control Groups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd.resource-control – Managing resources with systemd slices](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)  
- [Kubernetes resource management documentation](https://kubernetes.io/docs/concepts/scheduling-eviction/resource-management/)  
- [Docker run reference – cgroup v2 support](https://docs.docker.com/engine/reference/commandline/run/#control-groups)  
- [Red Hat Enterprise Linux – Using cgroups v2 for resource management](https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/9/html/using_the_linux_kernel/using-cgroups-v2_resource-management)