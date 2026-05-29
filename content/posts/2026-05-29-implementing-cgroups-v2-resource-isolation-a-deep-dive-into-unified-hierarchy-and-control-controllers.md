---
title: "Implementing Cgroups v2 Resource Isolation: A Deep Dive into Unified Hierarchy and Control Controllers"
date: "2026-05-29T13:00:10.556"
draft: false
tags: ["cgroups","linux","resource-isolation","kubernetes","devops"]
description: "Explore how to configure cgroups v2 unified hierarchy and control controllers for reliable CPU, memory, and IO isolation in production Linux workloads."
summary: "A practical guide that walks you through setting up cgroups v2, mapping controllers, and applying patterns that scale from a single VM to a Kubernetes node."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-29-implementing-cgroups-v2-resource-isolation-a-deep-dive-into-unified-hierarchy-and-control-controllers.svg"
  alt: "Diagram of Linux cgroups v2 hierarchy with resource controllers."
  caption: ""
  relative: false
---

> **TL;DR** — cgroups v2 replaces the fragmented v1 trees with a single unified hierarchy, letting you bind controllers (cpu, memory, io, etc.) to a predictable subtree. By enabling the hierarchy early, mapping the right controllers, and applying proven production patterns, you can achieve deterministic resource isolation for containers, VMs, or any Linux process.

Resource isolation is a non‑negotiable requirement for modern cloud workloads. While cgroups v1 gave us a foothold, its scattered trees made cross‑controller policies brittle and hard to audit. cgroups v2, introduced in Linux 4.5 and now the default in most distributions, consolidates everything under one “unified hierarchy” and exposes a richer set of control files. This post walks you through the *why*, *what*, and *how* of implementing cgroups v2 in a production environment, with concrete examples on a bare‑metal host and a Kubernetes node.

---

## Understanding the Unified Hierarchy

### What changed from v1 to v2?

| Aspect | cgroups v1 | cgroups v2 |
|--------|------------|------------|
| **Hierarchy** | Separate trees per controller (e.g., `cpu`, `memory`) | Single tree shared by all enabled controllers |
| **Thread granularity** | Optional per‑controller | Implicit – threads inherit the same cgroup as their parent process |
| **API surface** | Hundreds of files, many deprecated | Streamlined set of files per controller, all under `/sys/fs/cgroup/` |
| **Migration** | Mixed mode possible but confusing | Pure mode (v2 only) or hybrid (both) – most distros ship pure mode now |

The unified hierarchy eliminates the “orphaned controller” problem where a process could be limited by memory but not by CPU because it lived in a different subtree. With v2, every subtree can be *simultaneously* bound to **all** enabled controllers, guaranteeing consistent isolation.

### The root of the hierarchy

When the kernel boots, it decides whether to mount a v1 or v2 hierarchy based on the `cgroup_no_v1` kernel command line or the presence of `cgroup2` in `/proc/filesystems`. On a fresh Ubuntu 22.04 server you’ll see:

```bash
$ mount | grep cgroup
cgroup2 on /sys/fs/cgroup type cgroup2 (rw,nosuid,nodev,noexec,relatime,seclabel)
```

If you still have a v1 mount, you can force v2 by adding `systemd.unified_cgroup_hierarchy=1` to the kernel command line and rebuilding the initramfs.

### Why “unified” matters for production

1. **Predictable accounting** – CPU, memory, and I/O counters are attached to the same cgroup path, making per‑service dashboards trivial.
2. **Simpler automation** – A single `mkdir` creates a subtree that can be handed to systemd, Docker, or a custom launcher without worrying about missing controllers.
3. **Future‑proof** – New controllers (e.g., `pids.max` for process limiting) plug into the same tree automatically.

---

## Mapping Controllers to Resources

cgroups v2 does not automatically enable every controller; the kernel must be told which ones to expose. The list lives in `/sys/fs/cgroup/cgroup.controllers`. Example on a recent Fedora box:

```bash
$ cat /sys/fs/cgroup/cgroup.controllers
cpu io memory pids rdma
```

### Enabling a controller for a subtree

To bind a controller, write its name into the `cgroup.subtree_control` file of the parent cgroup. The root (`/`) is the natural place to enable the set you need for the entire host:

```bash
# Enable cpu, memory, and io for the whole system
sudo bash -c 'echo "+cpu +memory +io" > /sys/fs/cgroup/cgroup.subtree_control'
```

> **Note** – The leading `+` adds the controller; a `-` would remove it. Only the *parent* can enable a controller for its children.

### Verifying enabled controllers

```bash
$ cat /sys/fs/cgroup/cpu.max
max 100000
$ cat /sys/fs/cgroup/memory.max
9223372036854771712
```

If you get “No such file or directory”, the controller is not active for that subtree.

### Common controller semantics

| Controller | Primary file(s) | Typical use |
|------------|----------------|-------------|
| `cpu` | `cpu.max`, `cpu.weight` | Hard caps (`cpu.max`) and proportional shares (`cpu.weight`) |
| `memory` | `memory.max`, `memory.swap.max`, `memory.low` | Hard caps, swap limits, and “best‑effort” memory |
| `io` | `io.max`, `io.bfq.weight` | Per‑device bandwidth throttling |
| `pids` | `pids.max` | Prevent fork bombs |
| `rdma` | `rdma.max` | Limit RDMA queue pairs (rare) |

These files are *plain text* and can be manipulated with `echo` or via higher‑level tools like `systemd-run` or the Docker `--cgroup-parent` flag.

---

## Architecture Patterns for Production Isolation

### 1. Service‑per‑cgroup pattern

Every long‑running service (e.g., `nginx`, `postgres`) gets its own dedicated subtree under `/sys/fs/cgroup/services/<name>`. Systemd already does this when `systemd.unified_cgroup_hierarchy=1` is set:

```bash
$ systemctl show -p ControlGroup nginx
ControlGroup=/system.slice/nginx.service
```

Because the slice sits under the unified hierarchy, all enabled controllers apply automatically.

**Benefits**

- One‑line audit: `systemd-cgls` shows the full tree.
- Automatic cleanup on service stop.
- Consistent metrics across CPU, memory, and I/O.

### 2. Tenant‑isolated subtree for multi‑tenant platforms

In a SaaS platform you may host dozens of customer workloads on a single VM. Create a top‑level tenant cgroup and delegate sub‑cgroups to each tenant’s scheduler:

```
/sys/fs/cgroup/
 └─ tenants/
     ├─ tenantA/
     │   ├─ web/
     │   └─ db/
     └─ tenantB/
         ├─ web/
         └─ db/
```

Enable controllers at the `tenants` level, then fine‑tune per‑tenant quotas:

```bash
# Give tenantA 2 CPUs and 4 GiB RAM
sudo bash -c 'echo "200000 100000" > /sys/fs/cgroup/tenants/tenantA/cpu.max'
sudo bash -c 'echo $((4*1024*1024*1024)) > /sys/fs/cgroup/tenants/tenantA/memory.max'
```

### 3. “Burst‑able” workloads with `memory.low`

`memory.low` defines a *soft* guarantee; the kernel will protect that amount unless the system is under memory pressure. This is perfect for batch jobs that should not starve foreground services.

```bash
# Reserve 512 MiB as low memory for a nightly ETL job
echo $((512*1024*1024)) > /sys/fs/cgroup/etl_job/memory.low
```

When the system is idle, the job can use more RAM; when other services need memory, the kernel reclaims from the job first.

### 4. I/O throttling with per‑device `io.max`

The `io.max` file accepts a space‑separated list of `<dev>:<read>/<write>` limits in bytes per second. Example for a PostgreSQL data directory on `/dev/sdb`:

```bash
# Limit reads to 50 MiB/s, writes to 20 MiB/s
echo "8:0 rbps=52428800 wbps=20971520" > /sys/fs/cgroup/postgres/io.max
```

You can discover the major:minor numbers with `lsblk -dno MAJ:MIN /dev/sdb`.

---

## Configuring Cgroups v2 on a Host

### Step‑by‑step bootstrap script

Below is a minimal Bash script you can drop into `/usr/local/sbin/bootstrap-cgroup2.sh`. It:

1. Ensures the v2 hierarchy is mounted.
2. Enables the core controllers.
3. Creates a `services` slice with sane defaults.
4. Persists the configuration via a systemd unit.

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1. Verify v2 mount
if ! mountpoint -q /sys/fs/cgroup; then
  echo "Mounting cgroup2..."
  mount -t cgroup2 none /sys/fs/cgroup
fi

# 2. Enable core controllers at the root
ROOT="/sys/fs/cgroup"
CONTROLLERS="+cpu +memory +io +pids"
echo "$CONTROLLERS" > "$ROOT/cgroup.subtree_control"

# 3. Create a top‑level services slice
mkdir -p "$ROOT/services"
echo "$CONTROLLERS" > "$ROOT/services/cgroup.subtree_control"

# 4. Set default limits (example: 80% of CPU, 8 GiB RAM)
echo "80000 100000" > "$ROOT/services/cpu.max"   # 80% of a single CPU
echo $((8*1024*1024*1024)) > "$ROOT/services/memory.max"

echo "Cgroup v2 bootstrap complete."
```

Make it executable and run once during provisioning:

```bash
sudo chmod +x /usr/local/sbin/bootstrap-cgroup2.sh
sudo /usr/local/sbin/bootstrap-cgroup2.sh
```

### Persisting with systemd

Create `/etc/systemd/system/cgroup2-bootstrap.service`:

```ini
[Unit]
Description=Bootstrap cgroups v2 hierarchy
DefaultDependencies=no
After=local-fs.target
Before=systemd-remount-fs.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/bootstrap-cgroup2.sh
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Enable it:

```bash
sudo systemctl enable --now cgroup2-bootstrap.service
```

Now the hierarchy survives reboots, and any new service launched by systemd will inherit the configured defaults.

---

## Integrating with Kubernetes

Kubernetes 1.26+ defaults to the *cgroupfs* driver on most distros, but you can switch to the *systemd* driver to fully leverage the unified hierarchy. The key steps are:

1. **Configure the kubelet** to use `cgroupDriver=systemd`.
2. **Enable the desired controllers** at the node level (usually via the same bootstrap script).
3. **Annotate Pods** with `io.kubernetes.cri-o.CgroupParent` or `systemd.io` to place them in custom slices.

### Sample kubelet config snippet (`/var/lib/kubelet/config.yaml`)

```yaml
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: "systemd"
cgroupRoot: "/system.slice/kubelet.service"
cgroupSubsystems:
  - "cpu"
  - "memory"
  - "io"
  - "pids"
```

### Creating a per‑namespace cgroup hierarchy

You can use a MutatingAdmissionWebhook to inject a `cgroupParent` annotation based on the namespace label:

```yaml
apiVersion: admissionregistration.k8s.io/v1
kind: MutatingWebhookConfiguration
metadata:
  name: cgroup-parent-injector
webhooks:
  - name: inject.cgroup.parent.example.com
    admissionReviewVersions: ["v1"]
    clientConfig:
      service:
        name: cgroup-webhook
        namespace: kube-system
        path: "/inject"
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
```

The webhook logic (Python example) could be:

```python
import json

def mutate(pod):
    ns = pod["metadata"]["namespace"]
    parent = f"/system.slice/k8s-{ns}.slice"
    patch = [{
        "op": "add",
        "path": "/metadata/annotations/io.kubernetes.cri-o.CgroupParent",
        "value": parent
    }]
    return {"response": {"patchType": "JSONPatch", "patch": json.dumps(patch)}}
```

When a pod lands in namespace `prod`, it ends up under `/system.slice/k8s-prod.slice`, inheriting the node‑level limits you set there.

### Monitoring from inside the cluster

Prometheus node‑exporter already scrapes cgroup v2 metrics when the `--collector.cgroups` flag is enabled. You can visualize per‑slice CPU and memory usage with a Grafana dashboard that queries:

```promql
rate(container_cpu_user_seconds_total{slice=~"k8s-.*"}[1m])
```

and

```promql
container_memory_working_set_bytes{slice=~"k8s-.*"}
```

---

## Debugging and Monitoring

### Inspecting a cgroup

```bash
# Show the full tree with enabled controllers
sudo systemd-cgls --tree --all

# Dump the configuration of a specific slice
cat /sys/fs/cgroup/services/nginx/cpu.max
cat /sys/fs/cgroup/services/nginx/memory.max
```

### Common failure modes

| Symptom | Likely cause | Diagnostic command |
|---------|--------------|---------------------|
| Process can’t allocate memory despite `memory.max` being high | `memory.low` is set too low, causing aggressive reclamation under pressure | `cat /sys/fs/cgroup/<cgroup>/memory.low` |
| CPU throttling appears random | `cpu.max` set as a *period*/**quota** pair that doesn’t align with real CPU count | `cat /sys/fs/cgroup/<cgroup>/cpu.max` |
| I/O limits not applied | `io.max` syntax error or missing major:minor numbers | `cat /sys/fs/cgroup/<cgroup>/io.max` |
| New containers fall back to v1 hierarchy | Kernel boot parameter `cgroup_no_v1` missing, or systemd version < 244 | `systemctl cat systemd | grep Unified` |

### Live tracing with `perf` and `cgroup2`

`perf` can be scoped to a cgroup, enabling per‑slice performance analysis:

```bash
sudo perf top -G $(cat /sys/fs/cgroup/services/postgres/cgroup.procs | head -n1)
```

The `-G` flag tells `perf` to filter events by the cgroup of the given PID, giving you a view of the hottest functions *inside* that slice.

---

## Key Takeaways

- cgroups v2’s unified hierarchy removes the fragmentation of v1, providing a single source of truth for CPU, memory, I/O, and other resources.  
- Enable the required controllers **once** at the root (or a designated parent) via `cgroup.subtree_control`; children inherit without extra work.  
- Production‑grade patterns—service‑per‑cgroup, tenant slices, burstable `memory.low`, and per‑device `io.max`—turn abstract limits into concrete, auditable policies.  
- A short bootstrap script plus a systemd unit makes the hierarchy reproducible across VM images and bare‑metal servers.  
- When running Kubernetes, switch the kubelet to the `systemd` driver, annotate Pods with a custom `cgroupParent`, and you gain the same isolation guarantees at scale.  
- Use `systemd-cgls`, `cat` of the control files, and `perf -G` for day‑to‑day debugging; Prometheus node‑exporter can surface the metrics to your observability stack.

---

## Further Reading

- [Linux kernel documentation – Control Groups v2](https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html)  
- [systemd.resource-control – Managing resources with systemd](https://www.freedesktop.org/software/systemd/man/systemd.resource-control.html)  
- [Kubernetes documentation – Using cgroup v2 with the kubelet](https://kubernetes.io/docs/tasks/administer-cluster/cgroup-v2/)