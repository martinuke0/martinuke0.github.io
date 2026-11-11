---
title: "Mastering eBPF: Implementing Kernel Probes for High-Throughput Packet Filtering"
date: "2026-11-11T01:00:39.505"
draft: false
tags: ["eBPF", "kernel", "packet-filtering", "performance", "observability", "Linux"]
description: "Learn how to write eBPF programs with kernel probes to filter packets at line rate, optimizing network throughput and reducing CPU overhead."
summary: "A practical guide to using eBPF kernel probes for high‑throughput packet filtering, with code examples and performance tips."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-11-mastering-ebpf-implementing-kernel-probes-for-high-throughput-packet-filtering.svg"
  alt: "Abstract illustration of network packets flowing through a kernel"
  caption: ""
  relative: false
---

> **TL;DR** — Attaching eBPF programs to kernel probe points lets you filter packets at line rate with sub‑microsecond latency. This guide walks through building a high‑throughput XDP filter, attaching it to a network interface, and profiling its performance in a real production environment.

In modern data‑center networks, the gap between line speed and CPU capacity is widening. A single 100 GbE interface can generate millions of packets per second, and traditional user‑space filtering (e.g., `libpcap` or `AF_PACKET`) introduces tens of microseconds of latency per packet. Kernel‑level probes built on **extended Berkeley Packet Filter (eBPF)** let you inspect and drop packets before they reach the network stack, achieving near‑wire‑rate throughput with minimal CPU overhead.

## Why Kernel Probes for Packet Filtering?

### The Cost of Traditional Filtering

When a packet arrives, the kernel first copies it into a shared ring buffer (e.g., `AF_PACKET`), then wakes up a user‑space process. Each copy and context switch consumes hundreds of nanoseconds, and the per‑packet overhead grows with traffic volume. In high‑throughput scenarios, this quickly saturates a core.

### Introducing eBPF and XDP

eBPF is a sandboxed virtual machine that runs inside the Linux kernel. It can attach to various hook points, including **XDP (eXpress Data Path)**, which is invoked on the receive path of a network interface card (NIC) before any allocation of `sk_buff` structures. By returning an action such as `XDP_PASS`, `XDP_DROP`, or `XDP_TX`, you can decide the fate of a packet with a single bytecode instruction.

The XDP program type (`BPF_PROG_TYPE_XDP`) is the cornerstone of high‑throughput packet filtering. It executes in the context of the NIC driver, often in hard‑IRQ mode, providing the lowest possible latency.

## Architecture: From NIC to XDP

### Packet Path in the Kernel

1. **Driver Receive** – The NIC DMA engine writes the packet into a pre‑allocated ring buffer.
2. **XDP Hook** – The driver calls the attached XDP program, passing a pointer to the `xdp_buff` structure.
3. **Decision** – The program inspects headers and returns an action.
4. **Action Handling** – Depending on the action, the packet is forwarded, dropped, or passed to the network stack.

### Where to Hook: XDP vs. TC

- **XDP** runs before any memory allocation, making it ideal for DDoS mitigation, load balancing, and early drop.
- **Traffic Control (TC)** operates after the packet has been converted to an `sk_buff`, allowing more complex processing but with higher overhead.

For line‑rate filtering, XDP is the preferred hook.

## Building an XDP Filter

### Setting Up the Development Environment

You need the following tools:

- Linux kernel ≥ 5.4 (XDP support is stable)
- `clang` and `llc` (LLVM) for compiling eBPF bytecode
- `bpftool` for loading and inspecting programs
- `libbpf` (or `libbpf`‑based `libbpf` C library)

Install them on Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y clang llvm libbpf-dev bpftool linux-headers-$(uname -r)
```

### Writing the eBPF Program

Below is a minimal XDP program that drops all TCP SYN packets, a common building block for rate limiting.

```c
// syn_drop.c
#define KBUILD_MODNAME "syn_drop"
#include <linux/version.h>
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/tcp.h>

SEC("xdp")
int syn_drop(struct xdp_md *ctx) {
    void *data_end = (void *)(long)ctx->data_end;
    void *data     = (void *)(long)ctx->data;

    // Ethernet header
    struct ethhdr *eth = data;
    if (data + sizeof(*eth) > data_end) return XDP_DROP;
    if (eth->h_proto != __constant_htons(ETH_P_IP)) return XDP_PASS;

    // IP header
    struct iphdr *ip = data + sizeof(*eth);
    if ((void *)(ip + 1) > data_end) return XDP_DROP;
    if (ip->protocol != IPPROTO_TCP) return XDP_PASS;

    // TCP header
    struct tcphdr *tcp = (void *)ip + (ip->ihl * 4);
    if ((void *)(tcp + 1) > data_end) return XDP_DROP;

    // Drop SYN packets
    if (tcp->syn) return XDP_DROP;

    return XDP_PASS;
}
```

Compile to eBPF bytecode:

```bash
clang -O2 -target bpf -c syn_drop.c -o syn_drop.o
```

### Loading and Attaching the Program

Use `bpftool` to load the program and attach it to an interface (e.g., `eth0`):

```bash
# Load the program
sudo bpftool prog load syn_drop.o /sys/fs/bpf/syn_drop \
    pin_maps /sys/fs/bpf/maps

# Attach to interface
sudo bpftool net attach xdp pinned /sys/fs/bpf/syn_drop dev eth0
```

Verify the attachment:

```bash
bpftool net show
```

You should see the program listed under `xdp` for `eth0`.

## Performance Tuning

### BPF Map Design

Maps are the primary way to share state between eBPF and user space. For high‑throughput scenarios, prefer:

- **Per‑CPU arrays** (`BPF_MAP_TYPE_PERCPU_ARRAY`) to avoid lock contention.
- **Hash maps** with a small number of entries to keep lookup latency low.

Example: a per‑CPU counter for dropped packets.

```c
struct bpf_map_def SEC("maps") drop_counter = {
    .type       = BPF_MAP_TYPE_PERCPU_ARRAY,
    .key_size   = sizeof(u32),
    .value_size = sizeof(u64),
    .max_entries = 1,
};
```

### Avoiding Per‑Packet Overhead

- **Minimize branching**: Use constant‑folded checks where possible.
- **Pre‑compute offsets**: Store header offsets in a map to avoid repeated arithmetic.
- **Use `static` inline helpers**: The compiler can inline them, reducing call overhead.

### Using JIT Compilation

The kernel JIT‑compiles eBPF programs to native x86‑64 instructions. Ensure JIT is enabled:

```bash
sysctl net.core.bpf_jit_enable=1
```

JIT compilation typically reduces latency by 30‑50 % compared to the interpreter.

## Production Patterns

### Rate Limiting with XDP

Combine XDP with a **token bucket** map to enforce per‑source IP rate limits. The program increments a per‑IP counter and drops packets when the threshold is exceeded.

```c
SEC("xdp")
int rate_limit(struct xdp_md *ctx) {
    // ... extract src IP ...
    u64 now = bpf_ktime_get_ns();
    u64 *last = bpf_map_lookup_elem(&last_seen, &src_ip);
    if (last && (now - *last) < INTERVAL) return XDP_DROP;
    bpf_map_update_elem(&last_seen, &src_ip, &now, BPF_ANY);
    return XDP_PASS;
}
```

### Load Balancing with BPF

For L4 load balancing, XDP can rewrite destination IP/port and forward packets to a backend pool. The **XDP_TX** action transmits the packet back onto the same or another interface, enabling inline forwarding without involving the network stack.

## Key Takeaways

- XDP provides the lowest latency hook for packet filtering, operating before `sk_buff` allocation.
- Use per‑CPU maps and minimal branching to sustain line‑rate performance.
- JIT compilation and pinned programs simplify deployment and reduce overhead.
- Real‑world patterns include SYN flood mitigation, rate limiting, and L4 load balancing.
- Always verify attachment with `bpftool net show` and monitor drop counters via `bpf_trace`.

## Further Reading

- [eBPF Official Documentation](https://ebpf.io/)
- [XDP – Express Data Path](https://www.iovisor.org/technology/xdp)
- [Linux Kernel XDP Documentation](https://www.kernel.org/doc/html/latest/af_xdp.html)
- [Cloudflare’s XDP Blog Series](https://blog.cloudflare.com/tag/xdp/)
- [BPF Program Types – Linux Man Pages](https://man7.org/linux/man-pages/man7/bpf-helpers.7.html)