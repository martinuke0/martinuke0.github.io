---
title: "Building an eBPF-Powered Packet Classifier in C: A CV-Worthy Systems Project"
date: "2026-09-03T16:00:47.488"
draft: false
tags: ["ebpf", "xdp", "networking", "systems", "portfolio"]
description: "A hands-on guide to building a userspace eBPF packet classifier in C with a custom XDP loader — a project that signals real Linux systems skill to hiring managers."
summary: "Build a production-shaped eBPF/XDP packet classifier from scratch in C. Real code, real architecture, and a clear roadmap to extend it into a senior-level systems project."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-building-an-ebpf-powered-packet-classifier-in-c-a-cv-worthy-systems-project.svg"
  alt: "Network packets flowing through an eBPF/XDP datapath diagram."
  caption: ""
  relative: false
---

> **TL;DR** — This project wires a kernel-side eBPF/XDP program to a userspace C loader that classifies packets by L4 protocol and per-CPU counters, then prints live stats. It demonstrates real systems fluency: kernel/userspace boundaries, BPF CO-RE, ring buffers, and XDP attach modes — the exact stack used by Cilium, Katran, and Cloudflare's Magic Transit.

Most "packet classifier" tutorials stop at `iptables -L`. This one goes the other way — into the kernel datapath, where XDP lets you drop, redirect, or count packets *before* the networking stack even allocates a `sk_buff`. If you've been looking for a side project that proves you can write C, read kernel headers without flinching, and reason about per-CPU data structures, this is it.

## Why This Project Stands Out on a CV

Hiring managers at companies running serious infrastructure — Cloudflare, Datadog, Meta, Isovalent (Cilium), AWS — screen for specific signals. This project sends several at once:

- **Kernel fluency, not just userspace C.** Touching `vmlinux.h`, understanding `BPF_MAP_TYPE_PERCPU_ARRAY`, and reasoning about which fields are safe to access at XDP time signals you've actually shipped code in the Linux networking path.
- **BPF CO-RE / BTF literacy.** BTF (BPF Type Format) and CO-RE (Compile Once – Run Everywhere) are how Cilium and Katran stay portable across kernel versions. Mentioning them shows you know the modern toolchain, not just the legacy `bpf_probe_read` style.
- **Knowledge of attach points.** Understanding the difference between `XDP_FLAGS_SKB_MODE`, `XDP_FLAGS_HW_MODE`, and `XDP_FLAGS_DRV_MODE` — and when each is appropriate — is exactly the kind of detail that separates a hobbyist from a kernel-networking candidate.
- **Production-shaped loader design.** A clean userspace loader with signal handling, atomic map access via `bpf_map_lookup_elem`, and graceful detach is closer to what `bpftool` itself does than to a textbook demo.

The roles this signals for: **Linux kernel engineer**, **networking/SRE** at a CDN, **platform/SRE** at a cloud provider, **security engineering** (DDoS, IDS), and **observability** (think Datadog's [eBPF-based USM](https://www.datadoghq.com/blog/engineering/universal-service-monitoring-datadog/) or Pixie's [edge networking work](https://github.com/pixie-io/pixie)).

If you write the loader correctly, you can talk about it in interviews as "the same architectural pattern Cilium uses for kube-proxy replacement" — which is true. Cilium's [kube-proxy-free datapath](https://docs.cilium.io/en/stable/overview/intro/#kube-proxy-replacement) is fundamentally an XDP + TC classifier on every node.

## Architecture Overview

The system has three components wired together by a single shared BPF object:

- **The BPF program (`classifier.bpf.c`).** Compiled with `clang -target bpf`. Runs in kernel context at the NIC driver hook (XDP). Decides — per packet — which L4 protocol class it belongs to, then atomically bumps a per-CPU counter. No allocations, no `sk_buff`, no sleeping. It's a hot path; the rule is "do less."
- **The BPF object file (`classifier.bpf.o`).** Produced by clang, contains BTF type info (CO-RE). This is what you actually `bpf_object__open()` against.
- **The userspace loader (`loader.c`).** A normal C binary that links `libbpf`. Opens the object, pins maps, loads the program, attaches it to a chosen interface via `bpf_xdp_attach`, then sits in a loop printing counters from each CPU. Handles `SIGINT` by detaching XDP and unpinning so the interface comes back clean.

The data flow is straightforward:

```text
NIC driver (XDP hook)
    └── classifier.bpf.c   — parse eth/ip/tcp/udp headers
          └── PERCPU_ARRAY map keyed by protocol_id (TCP=1, UDP=2, ICMP=3, OTHER=0)
                └── userspace: poll loop reads each CPU's slot, aggregates, prints
```

Why a `PERCPU_ARRAY` instead of a regular hash? Because XDP runs on the softirq path on every CPU, and a shared map would be a contention disaster at line rate. Per-CPU storage sidesteps locking entirely; aggregation happens lazily in userspace when we sum CPU slots. This is exactly the design [Cloudflare's blog](https://blog.cloudflare.com/announcing-xdp/) describes for early XDP work, and what Katran still uses for its LB4 hash counters.

## Building It Step by Step

You need: Linux 5.10+ (for CO-RE maturity), `clang >= 12`, `llvm`, `libbpf-dev`, `bpftool`, and a kernel built with `CONFIG_BPF`, `CONFIG_BPF_SYSCALL`, `CONFIG_BPF_JIT`, and `CONFIG_XDP_SOCKETS` enabled (Ubuntu 22.04+ has all of these out of the box).

### Step 1: The BPF program

Save this as `classifier.bpf.c`. It parses Ethernet → IPv4 → L4 in one pass, identifies TCP/UDP/ICMP, and bumps a per-CPU counter. No helper calls beyond the map lookup — XDP is hot, so we want it lean.

```c
#include <linux/bpf.h>
#include <linux/if_ether.h>
#include <linux/ip.h>
#include <linux/ipv6.h>
#include <linux/tcp.h>
#include <linux/udp.h>
#include <linux/icmp.h>
#include <bpf/bpf_helpers.h>

#define PROTO_TCP   1
#define PROTO_UDP   2
#define PROTO_ICMP  3
#define PROTO_OTHER 0

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, 4);
    __type(key,   __u32);
    __type(value, __u64);
} pkt_counters SEC(".maps");

SEC("xdp")
int xdp_classify(struct xdp_md *ctx)
{
    void *data     = (void *)(long)ctx->data;
    void *data_end = (void *)(long)ctx->data_end;

    struct ethhdr *eth = data;
    if ((void *)(eth + 1) > data_end)
        return XDP_PASS;

    __u16 h_proto = eth->h_proto;

    if (h_proto == bpf_htons(ETH_P_IP)) {
        struct iphdr *iph = (void *)(eth + 1);
        if ((void *)(iph + 1) > data_end)
            return XDP_PASS;

        __u32 key;
        switch (iph->protocol) {
            case IPPROTO_TCP:  key = PROTO_TCP;  break;
            case IPPROTO_UDP:  key = PROTO_UDP;  break;
            case IPPROTO_ICMP: key = PROTO_ICMP; break;
            default:           key = PROTO_OTHER; return XDP_PASS;
        }
        __u64 *cnt = bpf_map_lookup_elem(&pkt_counters, &key);
        if (cnt)
            __sync_fetch_and_add(cnt, 1);
    }
    return XDP_PASS;
}

char _license[] SEC("license") = "GPL";
```

The boundary checks `(void *)(eth + 1) > data_end` are non-negotiable — the BPF verifier will reject any code path that could read past the packet. This is the most common reason beginner programs fail to load. The [libbpf documentation](https://docs.kernel.org/bpf/libbpf/index.html) has a whole section on the contract.

### Step 2: The Makefile

This compiles the BPF object with BTF and links the loader against `libbpf`.

```makefile
CLANG      ?= clang
CC         ?= gcc
BPFTOOL    ?= bpftool
CFLAGS     ?= -O2 -g -Wall -I/usr/include
LIBBPF_INC ?= -I/usr/include
LIBBPF_LD  ?= -lbpf -lelf -lz

all: classifier.bpf.o loader

classifier.bpf.o: classifier.bpf.c
	$(CLANG) -target bpf \
		-D__TARGET_ARCH_x86 \
		-mcpu=v3 \
		-O2 -g -Wall \
		-c $< -o $@

loader: loader.c
	$(CC) $(CFLAGS) $(LIBBPF_INC) $< -o $@ $(LIBBPF_LD)

clean:
	rm -f classifier.bpf.o loader

.PHONY: all clean
```

`-mcpu=v3` is the default target for most modern kernels; bump to `v4` if you've confirmed your kernel supports it ([BPF instruction set encoding](https://www.kernel.org/doc/html/latest/networking/XDP/index.html)).

### Step 3: The userspace loader

The loader does four jobs: open the BPF object, find the program by name, look up the map by name, attach XDP to the interface, then poll and print.

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>
#include <net/if.h>
#include <bpf/bpf.h>
#include <bpf/libbpf.h>

static volatile int running = 1;

static void on_sigint(int sig) { (void)sig; running = 0; }

static int attach_xdp(const char *ifname, int prog_fd)
{
    int ifindex = if_nametoindex(ifname);
    if (!ifindex) {
        fprintf(stderr, "if_nametoindex(%s): %s\n", ifname, strerror(errno));
        return -1;
    }
    /* Use generic/driver mode based on driver support; SKB_MODE always works. */
    return bpf_xdp_attach(ifindex, prog_fd, 0, NULL);
}

static int detach_xdp(const char *ifname)
{
    int ifindex = if_nametoindex(ifname);
    if (!ifindex) return -1;
    return bpf_xdp_detach(ifindex, 0, NULL);
}

int main(int argc, char **argv)
{
    if (argc < 3) {
        fprintf(stderr, "usage: %s <ifname> <bpf_obj.o>\n", argv[0]);
        return 1;
    }
    const char *ifname = argv[1];
    const char *obj_path = argv[2];

    signal(SIGINT, on_sigint);

    struct bpf_object *obj = bpf_object__open_file(obj_path, NULL);
    if (libbpf_get_error(obj)) {
        fprintf(stderr, "open object failed: %s\n", strerror(-libbpf_get_error(obj)));
        return 1;
    }

    if (bpf_object__load(obj)) {
        fprintf(stderr, "load failed\n");
        bpf_object__close(obj);
        return 1;
    }

    struct bpf_program *prog = bpf_object__find_program_by_name(obj, "xdp_classify");
    if (!prog) { fprintf(stderr, "program not found\n"); return 1; }

    int prog_fd = bpf_program__fd(prog);
    struct bpf_map *map = bpf_object__find_map_by_name(obj, "pkt_counters");
    int map_fd = bpf_map__fd(map);

    if (attach_xdp(ifname, prog_fd) < 0) {
        fprintf(stderr, "attach failed: %s\n", strerror(errno));
        bpf_object__close(obj);
        return 1;
    }
    printf("XDP attached to %s. Press Ctrl-C to stop.\n", ifname);

    __u32 keys[4] = {0, 1, 2, 3};
    const char *labels[4] = {"OTHER", "TCP", "UDP", "ICMP"};
    __u64 values[4];
    __u64 totals[4] = {0};

    while (running) {
        sleep(1);
        for (int i = 0; i < 4; i++) {
            values[i] = 0;
            bpf_map_lookup_elem(map_fd, &keys[i], &values[i]);
            totals[i] += values[i];
        }
        printf("\rTCP=%llu UDP=%llu ICMP=%llu OTHER=%llu (since start)",
               (unsigned long long)values[1],
               (unsigned long long)values[2],
               (unsigned long long)values[3],
               (unsigned long long)values[0]);
        fflush(stdout);
    }

    puts("\nDetaching XDP...");
    detach_xdp(ifname);
    bpf_object__close(obj);
    return 0;
}
```

Two design choices worth calling out: (1) we poll on `sleep(1)` because a regular `PERCPU_ARRAY` doesn't support ring-buffer events — that's a deliberate trade for throughput, and (2) we always detach on exit, even on error, because leaving XDP attached after a crash is a real ops headache. The Cilium team's [XDP datapath blog](https://docs.cilium.io/en/latest/concepts/datapath/xdp-acceleration/) discusses similar lifecycle concerns at scale.

### Step 4: Compile

```bash
make
```

You should see `classifier.bpf.o` and `loader` produced with no warnings.

## Running and Testing It

Pick an interface — ideally a loopback or a dummy interface for testing, never your primary uplink during development. You will need `CAP_NET_ADMIN` (i.e., run as root, or grant via a systemd unit with `AmbientCapabilities=CAP_NET_ADMIN`).

```bash
sudo ip link add dev pktest type dummy
sudo ip link set pktest up
sudo ./loader pktest classifier.bpf.o
```

In another terminal, generate traffic:

```bash
ping -c 5 127.0.0.1    # ICMP — should bump the ICMP counter
curl -s https://example.com > /dev/null  # TCP — bumps TCP
nc -u -w 1 127.0.0.1 9 < /dev/null      # UDP — bumps UDP
```

You should see the counters incrementing once per second. Verify XDP is actually attached with:

```bash
bpftool net show
ip link show pktest
```

`ip link show` will print `prog/xdp id <N>` if your program is attached.

To validate the program independently of the loader:

```bash
sudo bpftool prog dump xlated pinned /sys/fs/bpf/myprog
sudo bpftool map dump id <MAP_ID>
```

The `xlated` view shows the BPF instructions the verifier actually accepted — useful evidence for a CV write-up or interview ("here is the verifier-approved bytecode my program emits").

Common failures and what they mean:

- **`failed to load: Permission denied`** — you don't have `CAP_BPF` / `CAP_NET_ADMIN`. Run with `sudo`.
- **`verifier rejected`** — a bounds check is missing. Add more `if (ptr + 1 > data_end)` guards. The [BPF verifier reference](https://docs.kernel.org/bpf/verifier.html) is worth reading once.
- **`attach failed: Device or resource busy`** — another XDP program is already attached. Detach it first with `sudo ip link set dev <ifname> xdp off`.

## Extending It: Your Roadmap to Senior-Level

A toy counter is a great demo; a *senior-level* project is what happens when you make the toy survive production-shaped concerns. Pick two or three of these — each is a meaningful branch in the repo with its own commit, README, and tests.

- **Add a userspace ring buffer for sample packets.** Wire `BPF_MAP_TYPE_RINGBUF` and `bpf_ringbuf_output()` from XDP for, say, 1-in-10000 SYN packets. Replace the polling loop with a ringbuf consumer. *Why it matters:* ringbufs are how [Pixie](https://pixielabs.ai/) and Datadog stream events out of the kernel at line rate without blocking.
- **Persist counters across restarts.** On `SIGINT`, walk the per-CPU map, write aggregated counts to a JSON or SQLite file. On startup, restore them. *Why it matters:* this is the difference between a demo and a metric — engineers who care about continuity are the ones you want on-call.
- **Expose counters as Prometheus metrics.** Embed an HTTP server (or a small custom one using a BPF map as the backing store) and serve `/metrics`. *Why it matters:* every production observability stack is Prometheus-shaped; this single feature makes your project feel "datacenter."
- **Add a simple ACL: drop traffic from a configurable CIDR.** Promote the static map to a `LRU_HASH` keyed by source IP, populated at runtime from the loader via a netlink-style control channel. *Why it matters:* you've now built a microscopic version of what [Katran](https://github.com/facebookincubator/katran) does for L4 load balancing.
- **Multi-attach / fan-out via TCX.** Add a TC ingress hook alongside XDP so packets on veth pairs (containers) are also classified. *Why it matters:* this is exactly the pattern Cilium uses for kube-proxy replacement — same kernel hook, different code path.
- **Benchmark against `iptables`.** Use `wrk`, `iperf`, or a simple packet generator, measure pps and CPU before/after. Write the numbers into a `BENCH.md`. *Why it matters:* quantifying the win is the single most persuasive thing in a CV project. "XDP did 26 Mpps single core vs. iptables' 1.2 Mpps" is a sentence interviewers remember.

Each of these is roughly a weekend of work, but together they turn a 200-line toy into something that demonstrates the same architectural instincts as a real eBPF deployment at scale.

## Key Takeaways

- The kernel/userspace split is the heart of any BPF project — get the verifier boundary checks right and everything else follows.
- `BPF_MAP_TYPE_PERCPU_ARRAY` is the right default for counters on the XDP hot path; aggregate lazily in userspace.
- A custom loader beats shelling out to `bpftool` for any real workflow — lifecycle control (detach on signal, error paths) is half the value.
- XDP attach mode matters: `DRV_MODE` is fastest but driver-dependent; `SKB_MODE` is universally compatible; `HW_MODE` is offloaded to the NIC.
- Treat the loader as production code from day one — signal handlers, clean detach, readable stats — because that's what differentiates a CV project from a tutorial.
- The roadmap above is how you go from "I built a toy" to "I built a system." Pick the extensions that interest you and write good READMEs for them; hiring managers read those.

## Further Reading

- [Linux Kernel BPF Documentation — the canonical reference](https://docs.kernel.org/bpf/index.html)
- [BPF and XDP Reference Guide — Cilium's eBPF primer](https://docs.cilium.io/en/latest/bpf/)
- [Cloudflare's "XDP for the impatient" — production XDP lessons](https://blog.cloudflare.com/announcing-xdp/)
- [Kernel XDP subsystem docs](https://docs.kernel.org/networking/XDP/index.html)
- [RFC 9293 — Transmission Control Protocol (for understanding the headers you'll be parsing)](https://www.rfc-editor.org/rfc/rfc9293.html)
- [libbpf API reference](https://docs.kernel.org/bpf/libbpf/index.html)
- [Katran — Facebook's XDP-based L4 load balancer (production code to read)](https://github.com/facebookincubator/katran)