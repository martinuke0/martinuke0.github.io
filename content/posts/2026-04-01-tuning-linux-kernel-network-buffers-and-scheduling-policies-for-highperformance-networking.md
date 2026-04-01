---
title: "Tuning Linux Kernel Network Buffers and Scheduling Policies for High‑Performance Networking"
date: "2026-04-01T07:42:33.900"
draft: false
tags: ["linux", "networking", "kernel", "performance", "scheduling"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Kernel‑Level Tuning Matters](#why-kernel-level-tuning-matters)  
3. [Anatomy of the Linux Network Stack](#anatomy-of-the-linux-network-stack)  
   - 3.1 [Socket Buffers (sk_buff)](#socket-buffers-sk_buff)  
   - 3.2 [Ring Buffers & NIC Queues](#ring-buffers--nic-queues)  
4. [Core Network Buffer Parameters](#core-network-buffer-parameters)  
   - 4.1 [`/proc/sys/net/core/*`](#proc-sysnetcore)  
   - 4.2 [`/proc/sys/net/ipv4/*`](#proc-sysnetipv4)  
5. [Practical Buffer Tuning Walk‑through](#practical-buffer-tuning-walk-through)  
   - 5.1 [Baseline Measurement](#baseline-measurement)  
   - 5.2 [Increasing Socket Memory Limits](#increasing-socket-memory-limits)  
   - 5.3 [Adjusting NIC Ring Sizes](#adjusting-nic-ring-sizes)  
   - 5.4 [Enabling Zero‑Copy and GRO/LRO](#enabling-zero-copy-and-grolro)  
6. [Scheduling Policies in the Kernel](#scheduling-policies-in-the-kernel)  
   - 6.1 [Completely Fair Scheduler (CFS)](#completely-fair-scheduler-cfs)  
   - 6.2 [Real‑Time Policies (SCHED_FIFO, SCHED_RR, SCHED_DEADLINE)](#real-time-policies)  
   - 6.3 [Network‑Specific Scheduling (qdisc, tc)](#network-specific-scheduling)  
7. [CPU Affinity, IRQ Balancing, and NUMA Considerations](#cpu-affinity-irq-balancing-and-numa-considerations)  
8. [Putting It All Together: A Real‑World Example](#putting-it-all-together-a-real-world-example)  
9. [Monitoring, Validation, and Troubleshooting](#monitoring-validation-and-troubleshooting)  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)  

---

## Introduction

Modern data‑center workloads, high‑frequency trading platforms, and large‑scale content delivery networks demand **sub‑microsecond latency** and **multi‑gigabit throughput**. While application‑level optimizations (e.g., async I/O, connection pooling) are essential, the **Linux kernel** remains the decisive factor that ultimately caps performance.

Two levers that often go unnoticed are:

1. **Network buffers** – the memory regions that hold packets while they travel between NIC hardware, the kernel’s networking stack, and user‑space sockets.
2. **Scheduling policies** – the kernel’s decision‑making engine for CPU time, which decides *when* and *where* network processing occurs.

Tweaking these knobs can unlock tens of gigabits per second of additional bandwidth, shave off microseconds of latency, and make a system more deterministic under load.

In this article we’ll:

* Dive deep into the kernel’s networking data structures.
* Explain every relevant sysctl and driver‑level parameter.
* Show concrete, reproducible examples of how to tune buffers.
* Explore the scheduler families (CFS, real‑time, deadline) and traffic‑shaping subsystems (qdisc, tc).
* Provide a full end‑to‑end case study that integrates buffer‑size changes, CPU‑affinity, IRQ‑threading, and real‑time scheduling.

By the end, you’ll have a **playbook** you can adapt to any Linux server—whether it runs a web server, a database, a packet‑capture appliance, or a latency‑critical trading engine.

---

## Why Kernel‑Level Tuning Matters

> **Note:** Application‑level changes (e.g., larger `SO_RCVBUF`) can only succeed if the kernel’s *global* limits allow the requested size.

When a packet arrives at a Network Interface Card (NIC), the NIC places it into a **receive ring buffer** (a circular DMA queue). The kernel then copies or maps that packet into a **socket buffer (`sk_buff`)** before delivering it to the appropriate socket. On the transmit side, data flows in the opposite direction.

If any of these queues are undersized, the NIC will start **dropping packets** (RX overrun) or the kernel will **stall** waiting for buffer space (TX underrun). This manifests as:

* **Packet loss** → retransmissions, reduced throughput.
* **Increased latency** → packets wait in queues.
* **CPU spikes** → polling loops spin while buffers fill.

Similarly, the **scheduler** decides which CPU runs the network interrupt handler, the soft‑IRQ processing, and the user‑space process that consumes the data. A poorly chosen policy can cause **priority inversion**, where a latency‑sensitive thread is pre‑empted by a CPU‑hungry background job, or **CPU starvation**, where the network stack never receives enough cycles to drain its queues.

Thus, **buffer sizing and scheduling are tightly coupled**. A well‑tuned system must balance memory, CPU, and NIC resources in harmony.

---

## Anatomy of the Linux Network Stack

### Socket Buffers (`sk_buff`)

The `sk_buff` (or *skb*) is the fundamental data structure that represents a packet inside the kernel. It contains:

| Field | Purpose |
|-------|---------|
| `data` / `len` | Pointer to packet payload and its length |
| `head` / `tail` | Boundaries of the allocated buffer |
| `cb` (control buffer) | Private per‑protocol data (e.g., TCP state) |
| `dev` | Pointer to the originating/receiving `net_device` |
| `priority` | QoS class used by traffic‑shapers |
| `skb->tstamp` | Timestamp for latency measurements |

Each `sk_buff` lives in kernel memory, typically allocated from the **SLAB** or **SLUB** allocator. The number of simultaneous skbs is limited by the **socket memory** limits (`net.core.rmem_max`, `net.core.wmem_max`).

### Ring Buffers & NIC Queues

Modern NICs expose **multiple hardware queues** (e.g., RSS – Receive Side Scaling) to spread traffic across CPUs. Each queue is backed by a **descriptor ring**:

```text
+-----------------+   DMA   +-------------------+   CPU   +-----------------+
| NIC Rx Queue 0  | <----> | Rx Ring Buffer 0  | <----> | SoftIRQ (net_rx)|
+-----------------+        +-------------------+        +-----------------+
| NIC Tx Queue 0  | ---->  | Tx Ring Buffer 0  | ---->  | SoftIRQ (net_tx)|
+-----------------+        +-------------------+        +-----------------+
```

The size of these rings is configurable via **ethtool** (`-G`) or driver‑specific sysfs entries (`/sys/class/net/<iface>/queues/...`). Larger rings reduce the probability of drops under bursty traffic but consume more DMA memory.

---

## Core Network Buffer Parameters

Linux exposes most buffer limits through **sysctl** entries under `/proc/sys/net`. While defaults are safe for generic workloads, high‑performance scenarios often require raising them.

### `/proc/sys/net/core/*`

| Parameter | Default (Ubuntu 22.04) | Meaning | Typical High‑Perf Value |
|-----------|-----------------------|---------|------------------------|
| `net.core.rmem_default` | 212992 | Default **receive** socket buffer size (bytes) | 4 MiB |
| `net.core.rmem_max` | 212992 | Upper limit for **receive** socket buffer (`SO_RCVBUF`) | 64 MiB or higher |
| `net.core.wmem_default` | 212992 | Default **send** socket buffer size (bytes) | 4 MiB |
| `net.core.wmem_max` | 212992 | Upper limit for **send** socket buffer (`SO_SNDBUF`) | 64 MiB or higher |
| `net.core.optmem_max` | 20480 | Max ancillary memory per socket (e.g., control messages) | 2 MiB |
| `net.core.somaxconn` | 128 | Max pending connections for `listen()` | 65535 (for large web servers) |
| `net.core.netdev_max_backlog` | 1000 | Max packets queued on the *netdev* backlog before dropping | 5000–20000 for high‑throughput NICs |
| `net.core.rmem_default` & `wmem_default` are **per‑socket**; `net.core.rmem_max`/`wmem_max` are **global caps**.

### `/proc/sys/net/ipv4/*`

| Parameter | Default | Meaning | Example Tuning |
|-----------|---------|---------|----------------|
| `net.ipv4.tcp_rmem` | `4096 87380 6291456` | Min‑default‑max **TCP receive** memory (bytes) | `4096 16777216 67108864` |
| `net.ipv4.tcp_wmem` | `4096 65536 6291456` | Min‑default‑max **TCP send** memory (bytes) | `4096 16777216 67108864` |
| `net.ipv4.tcp_mem` | `786432 1048576 1572864` | Global TCP memory pressure thresholds (pages) | `2097152 4194304 8388608` |
| `net.ipv4.tcp_window_scaling` | `1` | Enables TCP window scaling (must be on for >64 KB) | Keep enabled |
| `net.ipv4.tcp_congestion_control` | `cubic` | Default congestion algorithm | `bbr` for low‑latency workloads |
| `net.ipv4.tcp_fastopen` | `0` | Enables TCP Fast Open (optional) | `1` for client‑heavy workloads |

> **Tip:** For UDP‑only services, `net.ipv4.udp_mem` and `net.ipv4.udp_rmem_min` are the equivalents.

---

## Practical Buffer Tuning Walk‑through

Below is a step‑by‑step guide you can follow on any recent Linux distribution (kernel ≥ 5.10). We’ll use a **10 Gbps NIC** (`eth0`) as the target.

### 5.1 Baseline Measurement

1. **Capture current settings**:

   ```bash
   # Sysctl snapshot
   sysctl -a | grep -E 'net.core|net.ipv4.tcp' > baseline.sysctl

   # NIC ring sizes
   ethtool -g eth0
   ```

2. **Run a benchmark** (e.g., `iperf3 -c <server> -P 8 -t 30` for TCP, or `-u` for UDP). Record:

   * Throughput (Mbps)
   * Packet loss (%)
   * RTT latency (use `ping` or `ss -i`)

3. **Collect kernel metrics** while the test runs:

   ```bash
   sudo perf top -e net:netif_receive_skb,net:net_dev_queue
   watch -n1 "cat /proc/net/dev | grep eth0"
   ```

### 5.2 Increasing Socket Memory Limits

Edit `/etc/sysctl.d/99‑network‑tuning.conf` (or create a new file) with:

```ini
# Increase global socket buffer caps
net.core.rmem_max = 67108864   # 64 MiB
net.core.wmem_max = 67108864   # 64 MiB
net.core.rmem_default = 4194304   # 4 MiB
net.core.wmem_default = 4194304   # 4 MiB

# Expand TCP auto‑tuning windows
net.ipv4.tcp_rmem = 4096 16777216 67108864
net.ipv4.tcp_wmem = 4096 16777216 67108864

# Raise backlog for listening sockets
net.core.somaxconn = 65535
net.core.netdev_max_backlog = 20000
```

Apply immediately:

```bash
sudo sysctl --system
```

**Verification**:

```bash
sysctl net.core.rmem_max net.core.wmem_max
```

### 5.3 Adjusting NIC Ring Sizes

Use `ethtool` to enlarge both RX and TX rings. Most modern drivers accept up to 4096 descriptors. Example for a 10 Gbps Intel X710:

```bash
# Query current limits
ethtool -g eth0

# Set RX/TX rings to 4096 (must be a power of two for many drivers)
sudo ethtool -G eth0 rx 4096 tx 4096

# Verify
ethtool -g eth0
```

If the NIC supports **multiple queues**, repeat for each queue:

```bash
for q in /sys/class/net/eth0/queues/rx-*; do
    echo 4096 | sudo tee $q/rx_ring
done

for q in /sys/class/net/eth0/queues/tx-*; do
    echo 4096 | sudo tee $q/tx_ring
done
```

**Important:** Large rings consume DMA memory; ensure the system has enough **hugepages** if you plan on using **XDP** or **AF\_XDP** sockets.

### 5.4 Enabling Zero‑Copy and GRO/LRO

* **GRO (Generic Receive Offload)** aggregates incoming packets before delivering them to the stack, reducing per‑packet processing overhead.
* **LRO (Large Receive Offload)** is driver‑specific and works only on the receive path.

Enable GRO globally (usually on by default):

```bash
sudo ethtool -K eth0 gro on
```

If your NIC supports LRO:

```bash
sudo ethtool -K eth0 lro on
```

**Zero‑Copy** for user‑space (e.g., `AF_PACKET` with `PACKET_TX_RING` or `AF_XDP`) requires:

```bash
# Reserve 2 GiB of hugepages for XDP
echo 2048 | sudo tee /proc/sys/vm/nr_hugepages
```

Then use libraries such as **DPDK** or **libbpf** to bind the NIC to XDP.

---

## Scheduling Policies in the Kernel

Linux offers several families of schedulers, each with distinct goals. Choosing the right one for network‑intensive workloads can dramatically affect latency and jitter.

### 6.1 Completely Fair Scheduler (CFS)

CFS is the default **time‑sharing** scheduler. It aims to give each runnable task an equal share of CPU *in proportion to its weight*. Key knobs:

| Parameter | Description | Typical Adjustment |
|-----------|-------------|--------------------|
| `sched_latency_ns` | Targeted latency for a runnable task set | Reduce to `4ms` for low‑latency workloads |
| `sched_min_granularity_ns` | Minimum time slice | Reduce to `500µs` |
| `sched_wakeup_granularity_ns` | Wake‑up pre‑empt granularity | Reduce for more aggressive pre‑empt |

These can be tuned via `/proc/sys/kernel/sched_*`:

```bash
# Example: Aggressive CFS for a 10 Gbps server
sudo sysctl -w kernel.sched_latency_ns=4000000
sudo sysctl -w kernel.sched_min_granularity_ns=500000
sudo sysctl -w kernel.sched_wakeup_granularity_ns=200000
```

However, **CFS is not deterministic**; for latency‑critical paths you’ll likely need a real‑time policy.

### 6.2 Real‑Time Policies (SCHED_FIFO, SCHED_RR, SCHED_DEADLINE)

* **SCHED_FIFO** – First‑In‑First‑Out, static priority (1‑99). No time slice; a higher‑priority task runs until it blocks or yields.
* **SCHED_RR** – Round‑Robin with a fixed quantum (default 100 ms) among tasks of equal priority.
* **SCHED_DEADLINE** – Provides explicit runtime, deadline, and period guarantees (available since kernel 3.14).

#### Setting Real‑Time Priority

```bash
# Give the network‑processing thread higher priority (e.g., 80)
sudo chrt -f 80 /usr/local/bin/net_worker
```

If you run a **DPDK** or **XDP** application, you can pin it to a dedicated CPU and give it a real‑time policy:

```bash
# Bind to CPU 2,3 and set SCHED_FIFO 90
sudo taskset -c 2,3 chrt -f 90 /opt/dpdk/app/xdp_demo
```

#### Using SCHED_DEADLINE

Create a cgroup with deadline parameters:

```bash
# Create a cgroup
sudo mkdir /sys/fs/cgroup/deadline/netapp
echo $$ > /sys/fs/cgroup/deadline/netapp/tasks

# Set runtime 5ms, deadline 20ms, period 20ms
echo 5000 > /sys/fs/cgroup/deadline/netapp/runtime_us
echo 20000 > /sys/fs/cgroup/deadline/netapp/deadline_us
echo 20000 > /sys/fs/cgroup/deadline/netapp/period_us
```

Now any process placed in that cgroup receives **5 ms of CPU every 20 ms**, guaranteeing a deterministic share.

### 6.3 Network‑Specific Scheduling (qdisc, tc)

The **traffic control (tc)** subsystem provides queueing disciplines (qdisc) that shape outbound traffic and prioritize inbound handling via **Classful qdiscs** (e.g., `htb`, `fq_codel`, `fq`).  

#### Example: FQ\_Codel + Priority Classes

```bash
# Clear existing qdisc
sudo tc qdisc del dev eth0 root

# Add root fq_codel (good for bulk traffic)
sudo tc qdisc add dev eth0 root fq_codel limit 1000 target 5ms interval 100ms

# Add a high‑priority class for latency‑sensitive traffic
sudo tc class add dev eth0 parent 1: classid 1:10 htb rate 9gbit ceil 10gbit prio 0

# Filter traffic (e.g., port 443) into the high‑priority class
sudo tc filter add dev eth0 protocol ip parent 1:0 prio 1 u32 \
    match ip dport 443 0xffff flowid 1:10
```

**Key takeaways**:

* `fq_codel` reduces bufferbloat by actively managing queue depth.
* Classful qdiscs let you carve out a *guaranteed* bandwidth slice for latency‑critical flows.

---

## CPU Affinity, IRQ Balancing, and NUMA Considerations

### IRQ Affinity

The kernel distributes hardware interrupts across CPUs using **`/proc/irq/*/smp_affinity`**. For a multi‑queue NIC, each queue has its own IRQ (`eth0‑tx-0`, `eth0‑rx-0`, …). Pinning these IRQs to the same cores that will process the packets reduces cache migration.

```bash
# Example: Pin RX queue 0 IRQ to CPU 2
echo 4 > /proc/irq/45/smp_affinity   # 4 = 1<<2

# Pin TX queue 0 IRQ to CPU 3
echo 8 > /proc/irq/46/smp_affinity   # 8 = 1<<3
```

Use `cat /proc/interrupts` to see the IRQ numbers.

### irqbalance vs Manual Pinning

The `irqbalance` daemon automatically spreads interrupts. For ultra‑low latency, **disable it** and manually assign affinities:

```bash
sudo systemctl stop irqbalance
sudo systemctl disable irqbalance
```

### CPUSet and Cgroup Isolation

Create a **cpuset** cgroup for your network stack:

```bash
sudo mkdir /sys/fs/cgroup/cpuset/net
echo 2-5 > /sys/fs/cgroup/cpuset/net/cpuset.cpus
echo 0 > /sys/fs/cgroup/cpuset/net/cpuset.mems
echo $$ > /sys/fs/cgroup/cpuset/net/tasks   # Add current shell
```

All processes launched from this shell will inherit the cpuset, ensuring they stay on CPUs 2‑5 (which also host the NIC IRQs).

### NUMA Awareness

On multi‑socket servers, the NIC is attached to a specific NUMA node. Allocate memory from the same node to avoid cross‑node latency:

```bash
# Use numactl to bind memory and CPUs
numactl --cpunodebind=1 --membind=1 /opt/dpdk/app/xdp_demo
```

Check NIC NUMA node:

```bash
cat /sys/class/net/eth0/device/numa_node
```

---

## Putting It All Together: A Real‑World Example

**Scenario:** A financial firm runs a low‑latency market‑data feed handler on a 2‑socket, 64‑core server equipped with an Intel 100 GbE NIC (X722). Requirements:

* **< 5 µs** end‑to‑end latency for UDP market data.
* **Zero packet loss** at 20 Mpps (≈ 15 Gbps).
* **Deterministic CPU usage** (no jitter > 2 µs).

### Step‑by‑Step Configuration

1. **Kernel Parameters** (`/etc/sysctl.d/99‑fd‑tuning.conf`):

   ```ini
   # Increase socket buffers
   net.core.rmem_max = 134217728      # 128 MiB
   net.core.wmem_max = 134217728
   net.core.rmem_default = 16777216   # 16 MiB
   net.core.wmem_default = 16777216
   net.core.netdev_max_backlog = 50000

   # UDP specific
   net.ipv4.udp_mem = 65536 131072 262144
   net.ipv4.udp_rmem_min = 65536

   # Scheduler tweaks for CFS (fallback)
   kernel.sched_latency_ns = 3000000
   kernel.sched_min_granularity_ns = 250000
   kernel.sched_wakeup_granularity_ns = 50000
   ```

   Apply: `sudo sysctl --system`.

2. **NIC Ring Buffers**:

   ```bash
   # Query max supported sizes
   ethtool -g eth0

   # Set each queue to 8192 descriptors (max for X722)
   for q in $(seq 0 7); do
       sudo ethtool -G eth0 rx $q 8192 tx $q 8192
   done
   ```

3. **IRQ Pinning** (assuming IRQs 120‑135 for the 8 queues):

   ```bash
   # Pin each RX queue IRQ to a dedicated core on socket 0
   for i in {120..127}; do
       echo $((1 << (i-120))) > /proc/irq/$i/smp_affinity
   done

   # Pin each TX queue IRQ to cores on socket 1
   for i in {128..135}; do
       echo $((1 << (i-124))) > /proc/irq/$i/smp_affinity
   done
   ```

4. **CPUSet & NUMA**:

   ```bash
   sudo mkdir -p /sys/fs/cgroup/cpuset/mdfeed
   echo 0-7 > /sys/fs/cgroup/cpuset/mdfeed/cpuset.cpus   # socket 0
   echo 0 > /sys/fs/cgroup/cpuset/mdfeed/cpuset.mems
   echo $$ > /sys/fs/cgroup/cpuset/mdfeed/tasks
   ```

5. **Real‑Time Scheduling** (for the user‑space market‑data receiver):

   ```bash
   # Build the binary with POSIX real‑time extensions
   gcc -O3 -pthread -lrt -o md_recv md_recv.c

   # Run with SCHED_FIFO priority 90, bound to cpuset
   sudo chrt -f 90 taskset -c 0-7 ./md_recv -i eth0
   ```

6. **Traffic Control (Optional)** – Ensure inbound UDP traffic bypasses qdisc (most NICs do, but for egress monitoring we add a low‑latency class):

   ```bash
   sudo tc qdisc add dev eth0 root handle 1: prio bands 3
   sudo tc filter add dev eth0 protocol ip parent 1:0 prio 1 u32 \
       match ip protocol 17 0xff flowid 1:1   # UDP traffic to high‑prio band
   ```

7. **Zero‑Copy Capture** – Use **AF_XDP** with **XDP\_SKB** mode for simplicity, or **XDP\_DRV** for best performance:

   ```c
   struct xdp_umem_reg mr = {
       .addr   = (uint64_t)umem_buf,
       .len    = UMEM_SIZE,
       .chunk_size = 2048,
       .headroom   = 0,
   };
   if (setsockopt(fd, SOL_XDP, XDP_UMEM_REG, &mr, sizeof(mr)) < 0)
       perror("setsockopt XDP_UMEM_REG");
   ```

   Compile with `-l:libbpf.a` and launch with `numactl --cpunodebind=0 --membind=0`.

### Results (Sample Run)

| Metric | Before Tuning | After Tuning |
|--------|---------------|--------------|
| **Throughput** | 12 Gbps (≈ 12 Mpps) | 20 Mpps (≈ 16 Gbps) |
| **Packet loss** | 0.12 % (burst) | 0 % (steady) |
| **Average latency** | 12 µs | **4.3 µs** |
| **Latency jitter (99‑th percentile)** | 30 µs | **6 µs** |
| **CPU utilization (core 0‑7)** | 80 % (spikes to 100 %) | 48 % (stable) |

The deterministic real‑time priority, along with larger ring buffers and NUMA‑aware memory allocation, eliminated drops and reduced jitter, meeting the sub‑5 µs latency target.

---

## Monitoring, Validation, and Troubleshooting

1. **Queue Depth** – `ethtool -S eth0` shows per‑queue packet counts (`rx_queue_0_packets`). Use `watch` to spot growing queues.
2. **SoftIRQ Statistics** – `cat /proc/softirqs | grep NET_RX` gives per‑CPU softIRQ counts. An imbalance suggests affinity issues.
3. **Latency Histograms** – Tools like `perf record -e skb:kfree_skb` or `bcc` scripts (`trace`/`profile`) can produce latency distributions.
4. **Packet Drops** – `dmesg | grep -i dropped` often logs kernel‑level overrun warnings.
5. **Real‑Time Violations** – `rt-tests` (`cyclictest`) can confirm the system stays within the real‑time budget.

If you observe **increased CPU usage** after raising buffers, consider:

* Enabling **GRO/LRO** to reduce per‑packet processing.
* Offloading checksum calculation (`ethtool -K eth0 rx off tx off` may be needed for certain NICs).
* Switching to **XDP** with a zero‑copy path to bypass the regular stack.

---

## Conclusion

Network performance on Linux is not a black box; it is a **tunable ecosystem** where memory, CPU, and NIC hardware interact through well‑defined kernel interfaces. By systematically:

1. **Raising socket memory caps** (`rmem_max`, `wmem_max`),
2. **Expanding NIC ring buffers** (`ethtool -G`),
3. **Enabling offloads** (GRO/LRO, zero‑copy),
4. **Applying the right scheduler** (real‑time `SCHED_FIFO` or `SCHED_DEADLINE`),
5. **Pinning IRQs and tasks** to the same NUMA node,
6. **Using traffic control** to prioritize latency‑sensitive flows,

you can achieve **sub‑5 µs latency**, **zero packet loss**, and **predictable CPU usage** even at multi‑gigabit line rates.

The key is **measurement first, then iteration**. Capture baseline metrics, apply one change at a time, re‑measure, and keep a log of sysctl values and hardware counters. Over time, you’ll develop a performance profile that can be reproduced across servers, ensuring that your networking stack remains a competitive advantage rather than a bottleneck.

Happy tuning!

---

## Resources

- **Linux Kernel Documentation – Network Buffering**  
  <https://www.kernel.org/doc/html/latest/networking/buffer.html>

- **Red Hat Performance Tuning Guide – Network**  
  <https://access.redhat.com/documentation/en-us/red_hat_enterprise_linux/8/html/performance_tuning_guide/networking>

- **DPDK – Getting Started Guide (Zero‑Copy and Hugepages)**  
  <https://doc.dpdk.org/guides/prog_guide/zero_copy.html>

- **Linux Foundation – Real‑Time Linux Overview**  
  <https://www.linuxfoundation.org/realtime/>

- **RFC 8290 – TCP Congestion Control with BBR** (useful for high‑throughput tuning)  
  <https://datatracker.ietf.org/doc/html/rfc8290>

- **Brendan Gregg – Systems Performance (Chapter on Network Stack)**  
  <http://www.brendangregg.com/SystemsPerformance.html>

- **Linux Traffic Control (tc) Primer**  
  <https://man7.org/linux/man-pages/man8/tc.8.html