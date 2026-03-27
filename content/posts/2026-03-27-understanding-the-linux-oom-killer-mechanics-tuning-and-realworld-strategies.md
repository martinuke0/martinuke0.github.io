---
title: "Understanding the Linux OOM Killer: Mechanics, Tuning, and Real‑World Strategies"
date: "2026-03-27T10:06:18.841"
draft: false
tags: ["Linux", "OOM Killer", "Performance", "System Administration", "Containers"]
---

## Introduction

When a Linux system runs out of memory, the kernel must decide which processes to terminate to reclaim RAM and keep the machine alive. That decisive, sometimes brutal, component is the **Out‑Of‑Memory (OOM) Killer**. While most users never see it in action, administrators, developers, and anyone who runs workloads on servers, virtual machines, or containers will eventually encounter it—especially under heavy load, memory leaks, or mis‑configured resource limits.

This article provides an in‑depth, practical guide to the OOM Killer:

1. **What the OOM Killer is and why it exists**  
2. **The kernel’s decision‑making algorithm** (OOM scores, adjustments, and cgroup integration)  
3. **How to observe and diagnose OOM events** (logs, `/proc` entries, `dmesg`)  
4. **Tuning strategies** (sysctl, `oom_score_adj`, cgroup v1/v2, systemd‑oomd, earlyoom)  
5. **Real‑world case studies** (bare‑metal services, Docker, Kubernetes)  
6. **Best‑practice checklist** for preventing unwanted terminations  

By the end of this guide, you’ll be able to **interpret OOM killer messages**, **adjust scores to protect critical services**, and **design systems that gracefully handle memory pressure**.

---

## 1. The Rationale Behind the OOM Killer

### 1.1 Memory Exhaustion in Linux

Linux manages memory through a combination of **physical RAM**, **swap space**, and a **page cache**. When all of these resources are consumed, the kernel cannot allocate a new page for any process. Unlike some operating systems that simply refuse the allocation, Linux’s memory management strives to keep the system responsive. If a user-space allocation fails, the kernel may try to free memory by:

- Dropping clean page cache pages
- Swapping out anonymous pages
- Reclaiming memory from inactive file mappings

If all reclamation attempts fail, the system is in an **out‑of‑memory (OOM) state**. At this point, the kernel must **kill one or more processes** to free memory and avoid a total freeze.

### 1.2 Historical Perspective

The OOM Killer was introduced in Linux 2.6.11 (2005) as a **last‑ditch** mechanism. Early implementations were blunt: the kernel would select the “most memory‑hungry” process based on a simple heuristic. Over time, it evolved to include:

- **OOM scores** that weigh both memory usage and process importance.
- **`oom_adj` / `oom_score_adj`** fields allowing administrators to influence the decision.
- **cgroup awareness** (first in v1, then fully integrated in v2) to respect resource limits.
- **User‑space helpers** (`systemd-oomd`, `earlyoom`) that can intervene before the kernel’s hard kill.

Understanding this evolution is essential because modern distributions often combine the kernel OOM killer with user‑space daemons to provide a more graceful experience.

---

## 2. How the Kernel Chooses a Victim

### 2.1 The OOM Score

Every task (`struct task_struct`) has an **OOM score** (`oom_score`) that reflects how “expensive” it would be to kill that task. The score is a **percentage of the total memory** the system could reclaim by terminating the task, scaled to the range **0‑1000**. A higher score means a higher likelihood of being selected.

The score is calculated from several factors:

| Factor | Description | Impact |
|--------|-------------|--------|
| **RSS (Resident Set Size)** | Physical pages currently in RAM. | Directly proportional. |
| **Swap usage** | Pages swapped out. | Increases score (more memory already off‑loaded). |
| **`oom_score_adj`** | Administrator‑set bias (`-1000` to `+1000`). | Large negative values protect, large positives penalize. |
| **Root privileges** | Processes owned by `root` get a **-100** bias by default. | Makes system services less likely to be killed. |
| **Process age** | Older processes receive a slight penalty. | Encourages killing newer, potentially misbehaving tasks. |
| **Number of threads** | Multi‑threaded processes have higher scores (more memory consumption). | Increases chance of killing large services. |

The kernel computes a **raw score** based on memory usage, then applies the `oom_score_adj` bias:

```
final_score = raw_score + (oom_score_adj * 10)   // because adj is -1000..+1000
final_score = clamp(final_score, 0, 1000)
```

> **Note:** The scaling factor (`*10`) is an implementation detail that may change across kernel versions.

### 2.2 The Selection Algorithm (Simplified)

1. **Iterate over all processes** in the `tasklist`.  
2. **Skip processes** that are in `TASK_UNINTERRUPTIBLE` state (e.g., kernel threads).  
3. **Calculate the OOM score** for each candidate.  
4. **Select the process with the highest final score**.  
5. **Send `SIGKILL`** to the selected process (or `SIGTERM` first if `oom_kill_disable` is set).  

If the selected process cannot be killed (e.g., it is a kernel thread with `PF_KTHREAD`), the kernel proceeds to the next highest score.

### 2.3 Interaction with cgroups

#### cgroup v1

- **`memory.oom_control`**: When a cgroup’s memory limit is exceeded, the kernel triggers an OOM event *inside* that cgroup. The OOM killer will preferentially kill processes belonging to the offending cgroup.
- **`memory.memsw.limit_in_bytes`**: If both memory and swap limits are breached, the OOM killer may act even though the system still has free RAM elsewhere.

#### cgroup v2

- **`memory.max`** and **`memory.swap.max`** define hard limits.  
- **`memory.low`** (a “soft” limit) tells the kernel to protect memory usage up to that threshold. When memory pressure exceeds `memory.low`, the kernel may start reclaiming from the cgroup before invoking the OOM killer.  
- **`memory.oom.group`**: If set, the kernel kills the *entire cgroup* (all its processes) instead of a single task, which is useful for containers.

cgroup‑aware OOM handling is the foundation of modern container runtimes (Docker, Podman, Kubernetes).

---

## 3. Observing OOM Killer Activity

### 3.1 Kernel Logs (`dmesg`)

When the OOM killer fires, the kernel logs a detailed message:

```text
[  842.123456] Out of memory: Kill process 12345 (my-app) score 987 or sacrifice child
[  842.123460] Killed process 12345 (my-app) total-vm:204800kB, anon-rss:102400kB, file-rss:0kB, shmem-rss:0kB
```

Key fields:

- **PID** and **process name**  
- **Score** (0‑1000)  
- **Memory statistics** (`total-vm`, `anon-rss`, `file-rss`, `shmem-rss`)  

You can filter with:

```bash
dmesg | grep -i "out of memory"
```

### 3.2 `/proc` Interfaces

- **`/proc/<pid>/oom_score`** – Current OOM score (0‑1000).  
- **`/proc/<pid>/oom_score_adj`** – Adjusted bias (`-1000`…`+1000`).  
- **`/proc/<pid>/status`** – Contains `VmRSS`, `VmSwap`, and `OOMScoreAdj` fields.  

Example script to list top OOM candidates:

```bash
#!/usr/bin/env bash
printf "%-8s %-20s %-6s %-6s\n" "PID" "COMM" "RSS(KB)" "Score"
for pid in $(ls /proc | grep -E '^[0-9]+$'); do
    if [[ -r /proc/$pid/status ]]; then
        comm=$(awk '/^Name:/ {print $2}' /proc/$pid/status)
        rss=$(awk '/^VmRSS:/ {print $2}' /proc/$pid/status)
        score=$(cat /proc/$pid/oom_score)
        printf "%-8s %-20s %-6s %-6s\n" "$pid" "$comm" "$rss" "$score"
    fi
done | sort -k4 -nr | head -n 10
```

### 3.3 Systemd Journal

On systemd‑based distributions, OOM events are also captured in the journal:

```bash
journalctl -k | grep -i "out of memory"
```

You can add a filter for a specific service:

```bash
journalctl -u nginx.service | grep -i "killed process"
```

### 3.4 User‑Space Daemons

- **`systemd-oomd`** – Monitors memory pressure and kills low‑priority processes *before* the kernel OOM killer is invoked.  
- **`earlyoom`** – A lightweight daemon that reacts to low memory thresholds (e.g., < 5% RAM) and kills the largest consumer.

Both daemons write to the journal, making it easy to differentiate kernel‑initiated kills from user‑space interventions.

---

## 4. Tuning the OOM Killer

### 4.1 Adjusting Process Bias with `oom_score_adj`

The most direct way to protect a critical service is to set a **negative adjustment**:

```bash
# Example: protect a database process with PID 2345
echo -1000 > /proc/2345/oom_score_adj   # Minimum possible value
```

For a less aggressive protection:

```bash
# Reduce likelihood but still allow kill if absolutely necessary
echo -500 > /proc/2345/oom_score_adj
```

**Persisting the change** across restarts:

- Add a systemd drop‑in file:

```ini
# /etc/systemd/system/postgresql.service.d/oom.conf
[Service]
OOMScoreAdjust=-500
```

- Or use an init script that writes to `/proc` after the daemon starts.

### 4.2 Global Kernel Parameters (`/proc/sys/vm`)

| Parameter | Description | Typical Values |
|-----------|-------------|----------------|
| `vm.overcommit_memory` | Controls memory overcommit handling. `0` = heuristic, `1` = always allow, `2` = never overcommit. | `2` for strict environments (requires explicit `oom_score_adj`). |
| `vm.overcommit_ratio` | When `overcommit_memory=2`, defines the percentage of RAM + swap allowed for allocation. | `50` (default) |
| `vm.panic_on_oom` | If set to `1`, the kernel panics instead of killing processes. Useful for testing. | `0` |
| `vm.oom_kill_allocating_task` | When `1`, the task that triggered OOM is killed directly (Linux 5.4+). | `0` (default) |

Example to enable strict overcommit:

```bash
sysctl -w vm.overcommit_memory=2
sysctl -w vm.overcommit_ratio=70
```

Persist in `/etc/sysctl.d/99-oom.conf`:

```ini
vm.overcommit_memory = 2
vm.overcommit_ratio = 70
```

### 4.3 cgroup Memory Limits

#### Docker Example

```bash
docker run -d --name heavy-app \
  --memory=2g --memory-swap=2g \
  myimage
```

- `--memory` sets the hard limit (cgroup v1 `memory.limit_in_bytes`).  
- `--memory-swap` disables swap for the container (`2g` = same as memory limit).  

If the container exceeds 2 GiB, the kernel OOM killer will target processes inside that cgroup first.

#### Kubernetes Example

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: memory‑stress
spec:
  containers:
  - name: stress
    image: progrium/stress
    resources:
      limits:
        memory: "1Gi"
      requests:
        memory: "512Mi"
```

Kubernetes uses **cgroup v2** on modern clusters, so the `memory.max` limit is enforced. When the container hits the limit, the **kubelet** may also pre‑emptively delete the pod (via `eviction`) before the kernel kills it, depending on the `evictionHard` thresholds.

### 4.4 Using `systemd-oomd`

`systemd-oomd` leverages **`/proc/pressure/memory`** to monitor *memory pressure*. It can be configured with a JSON file (`/etc/systemd/oomd.conf`).

Example configuration:

```json
{
  "DefaultMemoryPressureLimit": "80%",
  "DefaultSwapPressureLimit": "60%",
  "DefaultMemorySwapFactor": 0.5,
  "DefaultKillUserProcesses": false,
  "DefaultKillUserProcessesIntervalSec": 300
}
```

- **Pressure** is measured as the percentage of time in the last 5 seconds that the system was under memory pressure.  
- When the limit is exceeded, `systemd-oomd` selects a *low‑priority* process (based on `Nice` value) and kills it, avoiding a kernel panic.

### 4.5 Earlyoom – A Minimalist Alternative

Install via package manager:

```bash
# Debian/Ubuntu
apt-get install earlyoom

# Fedora
dnf install earlyoom
```

Configure thresholds in `/etc/earlyoom.conf`:

```
# Kill when free RAM < 5% or free swap < 10%
EARLYOOM_DISABLE=0
EARLYOOM_TIMEOUT=0
EARLYOOM_THRESHOLD=5
EARLYOOM_SWAP_THRESHOLD=10
```

`earlyoom` runs in user space with a small memory footprint and can be a safety net for desktop systems where the kernel OOM killer might otherwise kill the X server or a window manager.

---

## 5. Real‑World Scenarios

### 5.1 Bare‑Metal Service Crash

**Situation:** A high‑traffic web server (`nginx`) runs on a 8 GiB VM. A memory leak in a PHP-FPM pool gradually consumes memory until the kernel OOM killer terminates `nginx`, causing a total outage.

**Root cause analysis:**

```bash
# Find the process that was killed
journalctl -k | grep -i "killed process"
# Example output
[  3542.123456] Killed process 3321 (php-fpm) total-vm:512000kB, anon-rss:300000kB, file-rss:0kB, shmem-rss:0kB
```

**Mitigation steps:**

1. **Add `OOMScoreAdjust` to protect `nginx`:**

   ```ini
   # /etc/systemd/system/nginx.service.d/oom.conf
   [Service]
   OOMScoreAdjust=-800
   ```

2. **Enable `systemd-oomd` with a low memory‑pressure threshold** to kill the PHP-FPM workers before `nginx` is affected.

3. **Set a cgroup memory limit** for the PHP-FPM pool using a separate systemd slice:

   ```ini
   # /etc/systemd/system/php-fpm.service.d/memory.conf
   [Service]
   Slice=php-fpm.slice
   ```

   And then configure the slice:

   ```ini
   # /etc/systemd/system/php-fpm.slice
   [Slice]
   MemoryMax=2G
   ```

### 5.2 Docker Container OOM

**Problem:** A container running a Java microservice crashes with “java.lang.OutOfMemoryError”. The container logs show the JVM exiting, and `docker logs` reveal an OOM kill:

```bash
docker ps -a | grep "Exited (137)"
```

**Explanation:** Exit code **137** (`128 + 9`) indicates the process received `SIGKILL`, typically from the OOM killer.

**Solution workflow:**

1. **Inspect container memory stats:**

   ```bash
   docker stats <container-id> --no-stream
   ```

2. **Adjust JVM heap size** to stay within the container limit:

   ```bash
   # Assuming container limit is 2GiB
   java -Xmx1500m -Xms1500m -jar app.jar
   ```

3. **Set `--oom-score-adj` for the container** (Docker 1.13+):

   ```bash
   docker run -d --oom-score-adj=-500 myimage
   ```

4. **Add a soft limit** with `--memory-reservation` to give the kernel early warning:

   ```bash
   docker run -d --memory=2g --memory-reservation=1.5g myimage
   ```

### 5.3 Kubernetes Eviction vs Kernel OOM

**Scenario:** A pod running a Redis server is evicted by the kubelet due to memory pressure, even though the node still has free RAM. The pod’s `oomKilled` flag in its status is **false**, but the pod disappears.

**Why it happens:** Kubernetes uses *node‑level eviction thresholds* (e.g., `memory.available < 100Mi`). When the threshold is crossed, the kubelet kills pods based on QoS class:

| QoS Class | Ranking |
|-----------|---------|
| Guaranteed | 1 (most protected) |
| Burstable | 2 |
| Best‑Effort | 3 (first to be evicted) |

If the Redis pod is **Burstable**, it can be evicted before the kernel OOM kill.

**Best practice:**

- **Set resource requests and limits** so that critical services become **Guaranteed**:

  ```yaml
  resources:
    requests:
      memory: "2Gi"
    limits:
      memory: "2Gi"
  ```

- **Tune `evictionHard`** in the kubelet config to give more breathing room:

  ```yaml
  evictionHard:
    memory.available: "200Mi"
    nodefs.available: "10%"
  ```

- **Enable `systemd-oomd` on the node** to handle pressure earlier, reducing the chance of pod eviction.

### 5.4 High‑Performance Computing (HPC) Cluster

In an HPC environment, **batch jobs** often request large memory allocations. A mis‑behaving job can cause the entire compute node to OOM, which then kills the **scheduler daemon** (`slurmctld`), bringing the whole node offline.

**Mitigation strategy:**

1. **Set `OOMScoreAdjust` for the scheduler:**

   ```bash
   echo -1000 > /proc/$(pidof slurmctld)/oom_score_adj
   ```

2. **Configure cgroup memory limits per job** via the scheduler’s plugin (e.g., Slurm’s `cgroup.conf`):

   ```ini
   ConstrainRAMSpace=yes
   TaskMemoryLimit=500M
   ```

3. **Deploy `earlyoom` on each node** with a low threshold (e.g., 2 % free RAM) to kill the offending job before the scheduler is affected.

---

## 6. Common Pitfalls and How to Avoid Them

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Neglecting swap** | System OOMs despite “plenty” of RAM because swap is disabled. | Enable a modest swap file (e.g., 2 GiB) or set `vm.swappiness` to a value like `60`. |
| **Setting `oom_score_adj` to `+1000`** | Critical service gets killed instantly under any pressure. | Use values in the range `-500` to `+500` and test on a staging node. |
| **Over‑committing memory (`overcommit_memory=0`)** | Kernel may reject large allocations, causing abrupt failures. | For production servers, consider `overcommit_memory=2` with a calibrated `overcommit_ratio`. |
| **Relying solely on `SIGKILL`** | No chance for graceful shutdown, possible data loss. | Set `vm.oom_kill_allocating_task=1` (Linux 5.4+) to kill the allocating task directly, allowing others to survive. |
| **Ignoring cgroup OOM notifications** | Container orchestration systems cannot react to OOM events. | Use `cgroup.events` (cgroup v2) or `memory.oom_control` (cgroup v1) to monitor OOM events from user space. |
| **Not logging OOM events** | Post‑mortem debugging becomes impossible. | Ensure `kernel.printk` level includes `KERN_WARNING` (default) and forward kernel logs to a centralized system (e.g., ELK). |

---

## 7. Checklist for Production‑Ready OOM Management

1. **Set realistic memory requests/limits** for every service (systemd slices, Docker `--memory`, Kubernetes resources).  
2. **Protect critical daemons** with `OOMScoreAdjust` (systemd drop‑ins or direct `/proc` writes).  
3. **Enable cgroup‑aware limits** and verify they are enforced (`cat /sys/fs/cgroup/.../memory.max`).  
4. **Deploy a user‑space OOM daemon** (`systemd-oomd` or `earlyoom`) with appropriate thresholds.  
5. **Configure kernel overcommit** (`/etc/sysctl.d/99-oom.conf`) to match workload characteristics.  
6. **Monitor pressure metrics** (`/proc/pressure/memory`, `cgroup.events`) and set alerts in your observability stack.  
7. **Test OOM scenarios** in a staging environment:  
   - Use `stress-ng --vm 2 --vm-bytes 90%` to generate pressure.  
   - Verify that protected services survive and logs contain expected entries.  
8. **Document OOM response procedures** for on‑call engineers (e.g., “Check `journalctl -k`, look for `Killed process`, then restart service if needed”).  

Following this checklist reduces the likelihood of an unexpected OOM kill taking down a production system.

---

## Conclusion

The Linux OOM Killer is a sophisticated safety valve that balances the need to keep a system alive against the desire to preserve critical workloads. By understanding how the kernel computes OOM scores, how cgroups influence victim selection, and how to observe and tune the behavior, administrators can **turn a potentially catastrophic event into a manageable one**.

Key takeaways:

- **Protect essential services** with negative `oom_score_adj` or systemd’s `OOMScoreAdjust`.  
- **Leverage cgroup limits** to confine memory usage per container or job, ensuring the OOM killer works *inside* the offending group first.  
- **Deploy user‑space helpers** (`systemd-oomd`, `earlyoom`) to intervene before the kernel’s hard kill.  
- **Monitor pressure metrics** and integrate OOM events into your logging/alerting pipeline.  

When you combine kernel‑level safeguards with orchestration‑aware policies and proactive monitoring, you gain both **predictability** and **resilience**—the hallmarks of a production‑grade Linux environment.

---

## Resources

- **Kernel Documentation – OOM Killer**: <https://www.kernel.org/doc/html/latest/admin-guide/mm/oom-killer.html>
- **Systemd OOMD Documentation**: <https://www.freedesktop.org/software/systemd/man/systemd-oomd.service.html>
- **Red Hat Enterprise Linux – Managing OOM**: <https://access.redhat.com/articles/3078>
- **Docker Runtime Memory Management**: <https://docs.docker.com/config/containers/resource_constraints/#limit-a-containers-access-to-memory>
- **Kubernetes Memory Management and Eviction**: <https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/>
- **EarlyOOM GitHub Repository**: <https://github.com/rfjakob/earlyoom>

*Happy tuning, and may your servers stay memory‑healthy!*