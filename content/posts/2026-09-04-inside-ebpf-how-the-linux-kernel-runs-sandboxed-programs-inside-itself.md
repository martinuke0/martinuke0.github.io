---
title: "Inside eBPF: How the Linux Kernel Runs Sandboxed Programs Inside Itself"
date: "2026-09-04T01:00:47.330"
draft: false
tags: ["ebpf", "linux-kernel", "observability", "networking", "performance"]
description: "A working engineer's guide to eBPF: how the Linux kernel safely runs sandboxed programs, with hooks, verifiers, and production use cases like Cilium and Pixie."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-ebpf-how-the-linux-kernel-runs-sandboxed-programs-inside-itself.svg"
  alt: "Diagram of the eBPF verifier, JIT, and hook points inside the Linux kernel."
  caption: ""
  relative: false
---

> **TL;DR** — eBPF lets you load and run sandboxed bytecode inside the Linux kernel at near-native speed, attached to hooks like network events, syscalls, and tracepoints. A static verifier guarantees the program terminates and stays safe before a JIT compiler turns it into machine code, which is why tools like Cilium, Pixie, and bpftrace have reshaped observability and networking in production.

If you've shipped a service on Linux in the last five years, you've almost certainly been touched by eBPF — even if you never wrote a program yourself. Cilium powers the networking and service mesh layer for hyperscalers like AWS and Shopify. Datadog and New Relic ship kernel probes for zero-instrumentation tracing. Cloudflare uses eBPF to do connection tracking and DDoS mitigation at line rate. The reason this is possible is a piece of kernel machinery that turns "the kernel is a closed black box" into "the kernel is a programmable, observable, auditable system," without compromising its stability.

This post walks through how that machinery actually works — the verifier, the JIT, the hook points, the maps — and how it shows up in the systems you already run.

## What eBPF Actually Is

eBPF (extended Berkeley Packet Filter) started life as a small in-kernel interpreter for packet filtering, the kind of thing you'd express with `tcpdump` filters. In 2014, Alexei Starovoitov's rewrite added a register-based virtual machine, maps for persistent state, and a verifier that could prove program safety. That rewrite turned BPF from a packet filter into a general-purpose in-kernel execution substrate.

The basic promise is simple but unusual: user space loads a program, the kernel checks it, and if the check passes, the program runs *inside kernel context* — in the middle of a network receive path, on every scheduler tick, on every syscall — with strict limits on what it can do.

A complete eBPF program has three moving parts:

1. **The bytecode** — instructions for a register VM, similar in spirit to a RISC ISA.
2. **The program type and hook point** — *where* in the kernel this thing is allowed to run (a network device, a tracepoint, a kprobe, etc.).
3. **Maps** — kernel-resident key/value data structures the program reads and writes, and that user space can also read and write. Maps are how state crosses the kernel/user boundary.

```c
#include <linux/bpf.h>
#include <bpf/bpf_helpers.h>

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10240);
    __type(key, __u32);    /* key: pid */
    __type(value, __u64);  /* value: bytes read */
} read_bytes SEC(".maps");

SEC("tracepoint/syscalls/sys_enter_read")
int trace_read(struct trace_event_raw_sys_enter_read *ctx)
{
    __u32 pid = bpf_get_current_pid_tgid() >> 32;
    __u64 *cnt, zero = 0;

    cnt = bpf_lookup_elem(&read_bytes, &pid, &zero);
    if (cnt)
        (*cnt) += ctx->args[2];  /* args[2] is the count argument */

    return 0;
}

char _license[] SEC("license") = "GPL";
```

That little program attaches to the `sys_enter_read` tracepoint and tallies bytes read per PID into kernel memory. User space then reads that map, no kernel module needed.

## The Hook System: Where Programs Attach

You can't run eBPF "anywhere." The kernel exposes a finite set of hook points, and your program type determines which subset you can attach to. The big families:

- **Network driver hooks** (`XDP`, `tc`) — run as a packet arrives, on the earliest possible path. XDP can even run before `sk_buff` allocation.
- **Socket hooks** (`sock_ops`, `sk_msg`) — run in the kernel's TCP path. Used for things like socket-level load balancing and encryption policy.
- **Kernel tracing hooks** — `tracepoint` (static, stable), `kprobe` / `uretprobe` (dynamic, may break across kernels), `perf_event`, `USDT` for statically-marked user programs.
- **Security and LSM hooks** — used by tools like Tetragon and Falco to enforce or audit security policy.
- **cgroup, scheduling, and device hooks** — for resource control, the kind of thing [Cilium's socket-level load balancer](https://docs.cilium.io/en/latest/reference-guides/scalability/load-balancer/) builds on.

The hook system matters for two practical reasons. First, it bounds blast radius: an eBPF program can only ever run where the kernel has agreed there's a hook, so it can't be pointed at arbitrary kernel code. Second, it determines the helper functions you can call. `XDP` programs can call `bpf_redirect`, but a `tracepoint` program cannot. This is the first layer of the safety story.

## The Verifier: The Reason This Doesn't Crash Your Production Box

The single most important part of eBPF is also the part least visible from user space: the verifier. Before any program runs, the kernel walks every reachable instruction and proves four things:

1. **Termination.** The program has no infinite loops. The verifier does this by exhausting all execution paths within a configurable instruction budget (defaulted to 1 million verified instructions in recent kernels), which forces every loop to be provably bounded.
2. **Memory safety.** Every load and store is checked against its actual type. Stack accesses are bounds-checked. Map lookups return null-checked pointers.
3. **Type safety.** A pointer to a `struct __sk_buff` cannot be dereferenced as a `struct task_struct`. Context types are matched to program type.
5. **Helper and map correctness.** You can only call helpers the program type allows, and map operations use compatible key/value sizes.

This is a whole-program abstract interpretation pass over a register machine. If anything doesn't prove out — a path that could be unbounded, a pointer that could be null, a helper called from the wrong context — the program is rejected with `EPERM` and a verifier log. You have to fix it.

```bash
# typical dev loop
$ clang -O2 -g -target bpf -c trace_read.c -o trace_read.o
$ bpftool prog load trace_read.o /sys/fs/bpf/trace_read
# any verifier rejection lands here
$ dmesg | tail -20
```

The verifier is what lets eBPF programs run *as root* in production. Even if a developer makes a mistake — even a malicious one — the kernel will refuse to load the program if it could damage the host. This is also why some legitimately useful programs get rejected. The verifier is famously picky about loops, signed integer overflow, and pointer arithmetic. There are workarounds (`bpf_loop()`, `bpf_for_each()`, range tracking improvements in newer kernels), but the principle holds: the kernel has the final word.

Once verified, the program is handed to the JIT, which translates BPF bytecode into native machine code for the host CPU. The result runs at near-native speed, often with a single-digit-percent performance delta versus hand-written kernel C — a fact confirmed repeatedly in the [Cilium team's XDP benchmarks](https://docs.cilium.io/en/latest/overview/intro/#why-cilium).

## Maps: How eBPF Talks to the World

If the verifier is eBPF's safety net, maps are its memory model. A map is a kernel-allocated, refcounted data structure with a fixed type, fixed key and value sizes, and a fixed maximum number of entries. Both the BPF program and user-space code can read and write it. Common map types:
- `BPF_MAP_TYPE_HASH` and `ARRAY` — generic key/value.
- `BPF_MAP_TYPE_LRU_HASH` and `LRU_PERCPU_HASH` — for memory-bounded caches.
- `BPF_MAP_TYPE_RINGBUF` — high-throughput event streaming from kernel to user.
- `BPF_MAP_TYPE_LPM_TRIE` — longest-prefix-match, used for IP lookup tables.
- `BPF_MAP_TYPE_DEVMAP` and `CPUMAP` — redirect packets to a network device or CPU.
- `BPF_MAP_TYPE_STRUCT_OPS` — install custom implementations of kernel struct ops, like `tcp_congestion_ops`. This is how [Katran](https://github.com/facebookincubator/katran), Facebook's XDP-based load balancer, plugs in custom forwarding logic.

Per-CPU variants exist for the hot-path cases: when you're updating a counter on every packet, you want each CPU updating its own slot to avoid cacheline bouncing. Modern eBPF programs in network data planes rely heavily on this.

## Architecture: How Cilium Uses This in the Real World

The cleanest production example of eBPF is [Cilium](https://cilium.io/). Cilium replaces the Linux networking stack's traditional iptables-based service routing with eBPF programs attached at `tc` ingress/egress and at the socket level.

In the iptables model, every new pod on a node adds hundreds of iptables rules, and every packet entering or leaving a pod walks the entire chain. With ~5,000 services, you're easily at 50,000+ rules, and a single packet pays O(n) cost in rule evaluation. Kubernetes nodes routinely see this become the bottleneck.

Cilium's `tc` programs do something fundamentally smarter: it uses an `BPF_MAP_TYPE_HASH` to map a service virtual IP plus port to a real backend. On the first packet to a given tuple, the BPF program does a map query, gets a backend, and rewrites the destination MAC and IP. From then on, conntrack and a smaller fast-path map skip the lookup entirely. For service traffic, you go from O(n) iptables rule walks to a constant-time BPF program with a couple of map lookups. In [published benchmarks](https://docs.cilium.io/en/latest/overview/intro/#why-cilium), this has shown 5–10x improvements in service-to-service throughput and dramatic tail-latency reductions for the kind of east-west traffic a service mesh produces.

The same kernel primitives power socket-level acceleration: when an in-pod process talks to another in-pod process on the same node, Cilium can short-circuit via `connect()` time BPF and skip a full TCP/IP path. That's `sockmap`/`sk_msg` programs.

## Observability: Pixie, bpftrace, and Zero-Instrumentation Tracing

The other production story is observability. [Pixie](https://px.dev/) (from New Relic) and tools like [bpftrace](https://github.com/iovisor/bpftrace) use eBPF to get visibility without touching application code.

A typical flow: a user-space daemon attaches `kprobe` or `tracepoint` programs to instrument HTTP request latency, DNS resolution, and database query time. Those programs write per-request records into a `BPF_MAP_TYPE_RINGBUF`. The user-space daemon tail-reads the ring buffer, aggregates the events, and ships them onward — or, in Pixie's case, runs a full in-cluster analytics engine on them.

The wins over traditional approaches are real:
- **No sidecars, no SDKs.** The application code doesn't change. There's no Python agent to update, no Java agent pinned to a JVM version.
- **No code change for new languages.** You can trace a Go binary the same way you trace a Rust binary.
- **Whole-system.**: The kernel sees every process, every syscall, every connection. You can write a 50-line bpftrace script to count `read()`s by PID grouped by container ID, then aggregate over time.

```c
/* bpftrace: count process execs by binary name */
tracepoint:syscalls:sys_enter_execve
{
    @[comm] = count();
}
```

This is also where Tetragon, Falco, and Tracee operate — they use eBPF not just to observe but to enforce policy. A Tetragon `TracingPolicy` can detect and block a process attempting to read `/etc/shadow` in real time, because the kernel's `security_file_open` LSM hook fires, the BPF program inspects the path, and the kernel blocks the syscall with `-EPERM` before the read happens.

## Performance: The Numbers That Matter

eBPF programs run with the cost of a single kernel function call plus the verified program body. In practice, that means:
- **XDP** can saturate a 100 Gbps NIC with simple drop/redirect programs. This is the basis for [their DDoS mitigation pipeline](https://blog.cloudflare.com/l4drop-xdp-ebpf-based-ddos-mitigation/).
- **`tc`** programs typically run at single-digit-percent cost relative to the kernel's regular stack, including for production service routing (Cilium's measurements).
- **Tracing** overhead depends on what's instrumented. A `tracepoint` fires in well-defined places and is cheap. `kprobe` adds a trap on every entry to the probed function, which can be measurably expensive if you hit a hot path — say, every `tcp_sendmsg`.

A practical optimization in tracing code: prefer `tracepoint` over `kprobe` when one exists, prefer per-CPU maps when you're aggregating counters, and batch events into the ring buffer rather than emitting one per call.

## Patterns in Production

A few patterns show up repeatedly in shipping eBPF systems:

- **Sidecar-less service mesh.** Cilium's `sockmap`-based acceleration removes the sidecar from the request path. This is the architecture behind a lot of the [production-grade service meshes](https://istio.io/latest/docs/ops/deployment/architecture/) in 2026 — the sidecar still exists for control plane reasons, but the data path is BPF-native.

- **Custom load balancing in the kernel.** Katran at Facebook, [Cilium's DSR mode](https://docs.cilium.io/en/latest/network/kubernetes/kube-proxy-free/), and Maglev-style consistent hashing all run inside the kernel as BPF programs to keep traffic decisions off the user-space network stack.

- **Auto-instrumentation for APM.** Zero-instrumentation tracing that ships as a DaemonSet. Pixie is the canonical example, and most major APM vendors now have an eBPF-based mode.

- **Policy enforcement at the syscall boundary.** [Tetragon](https://github.com/cilium/tetragon) attaches to LSM hooks and enforces security policy directly in the kernel, with no in-process agent required.

- **Hot-path debugging for the kernel itself.** Engineers investigating scheduler behavior or page reclaim bugs routinely use bpftrace to correlate events that were unobservable a decade ago.

## The Honest Tradeoffs

eBPF is not free. The verifier can be brutal — it's a static analyzer, not a probabilistic safety net, so it sometimes rejects programs that would have worked. The 1-million-instruction verified instruction limit and the inability to do unbounded loops shaped BPF program style for years. Recent kernel work (5.13+) introduced `bpf_loop()` and bounded loops, but the practical advice still holds: keep programs simple, prefer helpers over open-coded logic, and don't try to write a state machine.

The hook model is also a constraint. You can only attach to what the kernel exposes. If you want to inspect a code path that has no `tracepoint`, you're stuck either adding one upstream or using a `kprobe` and accepting the instability risk.

Finally, eBPF is Linux-specific. The exact tooling won't run on Windows or macOS hosts. For most server-side workloads that's fine. For client-side or edge devices, it's a real constraint.

## Key Takeaways

- eBPF is a register-based VM that runs sandboxed programs inside the Linux kernel, attached to a fixed set of hook points (XDP, `tc`, tracepoints, kprobes, LSM hooks, and more).
- The verifier is what makes it safe. It performs whole-program abstract interpretation before any program runs and rejects anything that could loop forever, dereference an invalid pointer, or violate type rules.
- After verification, a JIT compiles BPF bytecode to native code, so the program runs at near-native speed.
- Maps are the kernel/user boundary: typed, refcounted data structures that both BPF programs and user-space code can read and write. Per-CPU variants are essential for hot-path aggregation.
- In production, eBPF powers Cilium's service routing, Cloudflare's DDoS mitigation, Facebook's Katran, Pixie's APM, and Tetragon's security enforcement. The pattern is consistent — replace expensive or impossible-to-instrument user-space paths with verified kernel-side programs.
- The main tradeoffs are the verifier's strictness, the constraint to existing hook points, and Linux-only availability.

## Further Reading

- [eBPF documentation](https://ebpf.io/) — the canonical landing page with links to specs, docs, and community resources.
- [Cilium architecture overview](https://docs.cilium.io/en/latest/overview/intro/) — the most thorough production-grade writeup of BPF in networking.
- [BPF and XDP reference guide](https://docs.kernel.org/networking/filter.html) — the Linux kernel's own documentation of BPF internals.
- [bpftrace reference](https://github.com/iovisor/bpftrace) — the high-level tracing language built on eBPF.
- [Cloudflare's L4Drop writeup](https://blog.cloudflare.com/l4drop-xdp-ebpf-based-ddos-mitigation/) — a real-world XDP DDoS pipeline in production.
- [Tetragon documentation](https://github.com/cilium/tetragon) — security observability and enforcement using eBPF and LSM hooks.