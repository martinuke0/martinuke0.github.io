---
title: "Designing eBPF-Based Telemetry Pipelines for Constrained Embedded Linux Devices"
date: "2026-09-04T03:00:46.061"
draft: false
tags: ["ebpf", "embedded-linux", "telemetry", "observability", "linux-kernel", "iot"]
description: "Practical guide to building eBPF telemetry pipelines on resource-limited hardware, covering CO-RE, ring buffers, and production patterns."
summary: "How to design and ship eBPF-based telemetry pipelines on constrained embedded Linux devices — covering CO-RE, ring buffers, perf events, and the patterns that survive contact with 32 MB RAM and flaky flash."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-designing-ebpf-based-telemetry-pipelines-for-constrained-embedded-linux-devices.svg"
  alt: "Diagram of an eBPF program attached to kernel hooks feeding a userspace collector on an embedded board."
  caption: ""
  relative: false
---

> **TL;DR** — eBPF lets you observe kernel and application behavior on embedded devices with near-zero overhead, but the same constraints that make it attractive (small RAM, slow flash, no FPU, locked kernels) demand a different design than a cloud VM. The winning pattern is a small, CO-RE-portable BPF core, a bounded ring buffer, and a userspace collector that batches, compresses, and ships only the deltas that matter.

## Why eBPF on Tiny Boxes?

Embedded Linux is having a strange moment. A modern IoT gateway — an NXP i.MX 8M, a Raspberry Pi Compute Module 4, a TI Sitara AM62x — boots a full Linux kernel, runs systemd, talks TLS over Wi-Fi, and yet ships with 64–256 MB of RAM and 256 MB–2 GB of NAND. Traditional observability agents (statsd, node_exporter, Telegraf, OpenTelemetry SDKs) were written for servers with gigabytes of memory, multiple vCPUs, and writable filesystems. Drop one of those onto a 64 MB device and you get OOM kills, journald thrashing, and brownouts.

[eBPF](https://ebpf.io) changes the economics. Because programs run in-kernel in a verified sandbox, there is no context-switch cost to count events, no userspace buffering for sampling decisions, and no interpreter. You attach a single program to a tracepoint, kprobe, or hook, and it counts, timestamps, and aggregates as close to the event as the kernel allows. The same mechanism that powers [Pixie](https://pixielabs.ai) and [Parca](https://www.parca.dev) on a beefy Kubernetes node can run on a router — provided you design for it.

The catch: the BPF subsystem itself, while lighter than userspace agents, still consumes memory for maps, ring buffers, and program state. A naive implementation that `bpf_ringbuf_output()` every event with a 256-byte payload will exhaust 64 MB faster than you'd expect. So designing for constrained devices is really about three tradeoffs: **where to observe**, **how much to buffer**, and **what to leave on the floor**.

## The Architecture: Three Pieces That Have to Talk

A production-grade eBPF telemetry pipeline on an embedded device looks like this:

```
+-------------------+   syscall / tracepoint / kprobe   +-----------+
|   Kernel space    | --------------------------------> |  BPF prog |
|  (events fire)   |                                     +-----+-----+
+-------------------+                                           |
                                                                  | map ops
                                                                  v
                                                          +---------------+
                                                          |  BPF maps /  |
                                                          | ring buffer  |
                                                          +-------+-------+
                                                                  |
                                                                  | perf / ringbuf
                                                                  v
                                                          +---------------+
                                                          |  Userspace   |
                                                          |  collector   |
                                                          | (single bin)  |
                                                          +-------+-------+
                                                                  |
                                                                  | batch + compress
                                                                  v
                                                            network / MQTT / HTTP
```

Three pieces have to be designed together, and the design choices in each constrain the others:

1. **The BPF program core** — what you attach to, what you read, what you emit.
2. **The kernel-side buffer** — per-CPU arrays vs. ring buffers vs. perf events.
3. **The userspace collector** — how you drain the buffer, what you keep, what you discard.

The rest of this article walks through each, with the production decisions that matter.

### Patterns in Production: Pixie, Cilium, and Tetragon as Anchors

Before going deeper, it's worth looking at how the big boys do it. [Cilium](https://cilium.io) uses BPF to make networking decisions at the XDP layer, with per-CPU hash maps and a ring buffer for telemetry. [Tetragon](https://github.com/cilium/tetragon) ships a security event stream that ends up in JSON over a Unix socket. [Pixie](https://docs.pixielabs.ai) collects full request traces from Go programs using uprobes and BPF ring buffers.

None of these target a 64 MB embedded board out of the box, but their architecture is portable. The pattern — small, verified BPF core + bounded ring buffer + userspace aggregator that decides what's worth sending — is exactly the pattern you need. What changes for embedded devices is the budget on each step.

## Designing the BPF Core: CO-RE, BTF, and What You Can Drop

The first design decision is whether your BPF programs will be **CO-RE** (Compile Once – Run Everywhere) or whether you'll ship a per-kernel binary. The answer is almost always CO-RE, and [libbpf](https://github.com/libbpf/libbpf) is the de-facto standard for it. CO-RE means you compile your BPF object against `vmlinux.h` (a giant header generated from BTF) and ship a single `.o` file. At load time, libbpf relocates accesses to kernel structs based on the running kernel's BTF. This matters enormously for fleets: one binary per architecture, not one per kernel version.

The practical implication for embedded is **BTF has to be present**. The standard kernel config option is `CONFIG_DEBUG_INFO_BTF=y`. Many older vendor kernels (4.19 LTS, 5.4 LTS) ship without it. If your device fleet is locked to a vendor kernel and you can't enable BTF, you have two choices: upgrade the kernel (sometimes impossible) or build a non-CO-RE variant with hardcoded struct offsets that you verify at load time. The latter is fragile but workable.

Once you've committed to CO-RE, your BPF program structure should follow the conventions libbpf expects. A minimal skeleton looks like:

```c
// SPDX-License-Identifier: GPL-2.0
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>
#include <bpf/bpf_core_read.h>

struct event {
    __u64 ts_ns;
    __u32 pid;
    __u32 syscall_id;
    __u64 latency_ns;
};

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 64 * 1024);  // 64 KB ring buffer
} events SEC(".maps");

SEC("tp_btf/sys_enter_read")
int handle_read_enter(struct trace_event_raw_sys_enter *ctx)
{
    __u64 ts = bpf_ktime_get_ns();
    __u64 pid_tgid = bpf_get_current_pid_tgid();

    struct event *e = bpf_ringbuf_reserve(&events, sizeof(*e), 0);
    if (!e)
        return 0;

    e->ts_ns = ts;
    e->pid = pid_tgid >> 32;
    e->syscall_id = ctx->id;
    bpf_ringbuf_submit(e, 0);
    return 0;
}

char LICENSE[] SEC("license") = "GPL";
```

Three things to note:

- `vmlinux.h` is required. Generate it with `bpftool btf dump file /sys/kernel/btf/vmlinux format c > vmlinux.h`.
- `SEC("tp_btf/sys_enter_read")` uses BTF-aware tracepoints, which are stable across kernel versions when BTF is present. They also run faster than classic tracepoints.
- `bpf_ringbuf_reserve` + `bpf_ringbuf_submit` is the modern pattern. It's lock-free for single-producer and uses an efficient `mmap`'d region. The verifier accepts it more readily than older `bpf_perf_event_output` paths.

For embedded specifically, the size of `vmlinux.h` matters. A typical `vmlinux.h` for a 5.15 kernel is 25–30 MB of C. Compile time is dominated by this. Most CI pipelines pre-generate it once per kernel and check the artifact in. On the device, the BPF object itself is small — typically 5–50 KB.

## Choosing the Right Map Type

Map choice is where most embedded telemetry designs go wrong. The temptation is to use `BPF_MAP_TYPE_HASH` for everything. Resist it.

| Map type | Use case | Embedded suitability |
|---|---|---|
| `BPF_MAP_TYPE_HASH` | Per-key state, lookup tables | OK in small counts. Avoid if cardinality is unbounded. |
| `BPF_MAP_TYPE_ARRAY` | Fixed-size configuration, per-CPU state | Excellent. Bounded, fast. |
| `BPF_MAP_TYPE_PERCPU_ARRAY` | Per-CPU counters | Excellent. No locking, no cross-CPU cache traffic. |
| `BPF_MAP_TYPE_LRU_HASH` | Bounded caches | Acceptable. Set a tight max_entries. |
| `BPF_MAP_TYPE_RINGBUF` | Event streaming | The default for telemetry. |
| `BPF_MAP_TYPE_PERF_EVENT_ARRAY` | Legacy event streaming | Avoid on new code. Ring buffer is better. |

The cardinal sin is putting **per-event** data into a hash map keyed by pid or connection tuple. On a server that's fine — pid space is huge. On an embedded device running a handful of processes, you might think it's safe, but consider a reconnect storm in MQTT or a runaway loop spawning short-lived threads. Cardinality explosions will OOM your kernel.

The right pattern: **aggregate in the kernel, stream only summaries**. If you want syscall latency percentiles, maintain a small fixed-size histogram per syscall in a `PERCPU_ARRAY`. Don't emit one event per syscall.

## The Kernel-Side Buffer: Sizing the Ring

`BPF_MAP_TYPE_RINGBUF` is the workhorse. It's a single mmap'd region shared between kernel and userspace, with a producer-consumer model that the BPF verifier handles well. The default size you'll see in tutorials — 256 KB or 1 MB — is wrong for embedded.

Sizing rules of thumb that hold up in production:

- **Latency budget × event rate × event payload size**. If your collector wakes every 1 s, you generate 10k events/s, and each event is 64 bytes, you need at minimum 640 KB of ring buffer (with a 2× safety factor: 1.28 MB). But that's a lot on a device with 64 MB total RAM.
- **Right-size to your slowest consumer**. If your collector batches to disk or network, the ring buffer must absorb the worst-case delay between polls. Add jitter. Multiply by 2.
- **Pre-reserve a watermark**. Use the `BPF_RB_AVAIL_DATA` and `BPF_RB_NO_WAKEUP` flags to drain in batches.

In practice on embedded, a 64 KB ring buffer drained every 250 ms with a watermark of 32 KB is a sensible starting point. You can adjust it at load time without recompiling by setting `max_entries` based on device class:

```c
// In your loader, not in the BPF object:
size_t ringbuf_size = is_high_end() ? 256 * 1024 : 64 * 1024;
```

Don't forget the **instruction limit**. The BPF verifier caps in-kernel program complexity. As of Linux 5.x, the default is 1 million verified instructions per program. Complex programs can hit this. Use `BPF_COMPLEXITY_LIMIT_INSNS` (typically 65,536 for unprivileged, 1,048,576 for privileged) and design your programs to be small. Split a complex flow into a kprobe + a tail call to a subprogram.

## The Userspace Collector: One Binary, One Job

The userspace collector is the longest-lived process on the device. It needs to be small, robust, and well-behaved under memory pressure. Don't write it as a Python or Node script. Don't link it against a 30 MB OpenTelemetry SDK. Use a small statically-linked C or Rust binary.

The classic skeleton uses libbpf's ring buffer consumer API:

```c
struct ring_buffer *rb = ring_buffer__new(
    bpf_map__fd(skel->maps.events),
    handle_event,
    NULL,
    NULL
);

while (!exiting) {
    int err = ring_buffer__poll(rb, 250 /* timeout ms */);
    if (err == -EINTR) continue;
    if (err < 0) break;
}
```

Three responsibilities the collector owns:

1. **Drain, don't block**. The BPF program must never spin waiting for the collector. Use `BPF_RB_NO_WAKEUP` to control when events are released. Configure the ring buffer's `watermark` bytes so the producer side only wakes the consumer when there's a real batch.
2. **Batch and compress**. Don't send one event per packet. Batch to a length-prefixed protobuf or CBOR message, optionally compress with zstd, then write to a Unix socket, MQTT topic, or HTTP endpoint.
3. **Apply backpressure and shedding**. If the network is down, what happens? If you buffer forever in userspace, you'll OOM. If you drop, you lose. Use a bounded userspace queue (say, 4 MB) and a drop policy — newest-first or oldest-first, with a metric tracking the drop count.

A minimal drop-and-count approach:

```c
struct queue {
    struct event *buf;
    size_t cap;
    size_t head, tail;
    atomic_uint drops;
};

// In the ring buffer consumer:
if (q_full(q)) {
    atomic_fetch_add(&q->drops, 1);
    return;  // drop oldest already there
}
q_push(q, ev);
```

Emit the drop count itself as a metric. Silence is the worst failure mode.

### Patterns in Production: Tetragon's Export Pipeline

[Tetragon's](https://github.com/cilium/tetragon) userspace agent is a useful reference. It consumes BPF ring buffer events, decodes them with a generated Go struct, and exports to a configurable sink — JSON over a Unix socket, gRPC to a server, or a k8s CRD. The agent is a single binary, statically linked where licensing permits. The same shape works on embedded: a single binary, a Unix socket to a local aggregator, and a forwarder that batches to the cloud.

## What About Memory Limits? The Hard Numbers

A common question: "will the BPF subsystem itself OOM my 64 MB device?" The honest answer: **probably not, but it can**.

Hard limits to enforce:

- Total BPF map memory is bounded by `RLIMIT_MEMLOCK` per process (default 64 KB on most distros) and the system-wide `vm.unprivileged_bpf_disable` / `kernel.unprivileged_bpf_restrict` knobs. Privileged processes (or anything running as root, which on an embedded device is everything) can request more via `CAP_BPF` + `CAP_PERFMON`. The kernel enforces a soft system cap; on modern kernels it's effectively unlimited for privileged processes but should still be capped in your loader.
- **Per-device memory budget**: design your loader to fail fast if `bpf_object__open_skeleton()` reports a map that exceeds, say, 4 MB total. Print a clear error.
- **Pin maps in `/sys/fs/bpf/`** if they need to survive across processes. Use `BPF_F_PIN_GLOBAL` or explicit `bpf_obj_pin()`. Be aware that `/sys/fs/bpf/` is usually a tmpfs; on devices with limited RAM this matters.

The single biggest memory hog in BPF telemetry is the ring buffer. Cap it explicitly:

```c
struct bpf_map_create_opts opts = {
    .sz = sizeof(opts),
    .map_flags = 0,
};
// At load time:
bpf_map__set_max_entries(skel->maps.events, 64 * 1024);  // 64 KB
```

Don't leave `max_entries` at the default. The verifier and libbpf will pick a "sensible" value (often 256 KB or more), which is wrong for constrained devices.

## Logging, Sampling, and What to Skip

A naïve design emits every event. A production design samples, hashes, or skips. Some rules:

- **Hash PIDs, don't store names**. Resolving PID → comm is expensive and races. Either cache the lookup in a small LRU (max 64 entries, max 4 KB) or skip names entirely. Send `pid` and let the backend resolve.
- **Sample high-frequency syscalls**. `sys_enter_read` on a busy process can fire millions of times per second. Decide whether you need 1-in-100 or 1-in-1000 sampling at the kernel side using a simple counter map:

  ```c
  struct {
      __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
      __uint(max_entries, 1);
  } sample SEC(".maps");

  SEC("tp_btf/sys_enter_read")
  int handle_read(struct trace_event_raw_sys_enter *ctx)
  {
      __u32 key = 0;
      __u32 *cnt = bpf_map_lookup_elem(&sample, &key);
      if (!cnt) return 0;
      if ((*cnt++ % 1000) != 0) return 0;  // 1-in-1000 sample
      // ... emit event
  }
  ```

  Be aware that this is per-CPU, so the actual sample rate is `N × 1000` where `N` is the number of CPUs. For a 4-core device sampling at 1-in-1000, you're effectively sampling at 1-in-250.

- **Batch by time, not count**. A 100 ms time-based window with up to 256 events per window is more predictable than "send every 1000 events." Count-based batching interacts badly with bursty workloads.

- **Drop on the producer side when you can**. If your collector hasn't drained in 5 seconds, the ring buffer is full, and you're already losing events. Make the BPF program itself detect overload using `bpf_ringbuf_query()`:

  ```c
  if (bpf_ringbuf_query(&events, BPF_RB_AVAIL_DATA) > 60 * 1024) {
      // Buffer nearly full; skip this one
      return 0;
  }
  ```

  This is the BPF-side equivalent of an in-app circuit breaker.

## Patterns That Bite You in Production

A few patterns that look fine in a tutorial and fail on real fleets:

**1. Relying on `/sys/kernel/debug`**. Many production kernels mount `debugfs` read-only or not at all. If your BPF program reads from debugfs, it won't work. Use tracepoints and kprobes instead. Tracepoints in `/sys/kernel/debug/tracing/` are similarly fragile — prefer `tp_btf` (BTF-based tracepoints) which use BTF in `/sys/kernel/btf/` and don't depend on debugfs.

**2. Hardcoded kprobe offsets**. Without BTF, you can't do CO-RE and you're stuck with `kprobe.attach("do_sys_open+0x42")` style offsets. One kernel rebuild and your probe misses. Avoid this unless you control the kernel.

**3. Stack-walking in BPF**. `bpf_get_stack()` is expensive — it walks the kernel stack and copies it into your event. On a server, fine. On a 600 MHz ARM core, it can be 1–5 µs per call. Sample, don't always capture.

**4. Tail calls as a debugging tool**. Tail calls are great for factoring complex programs. But each tail call adds verifier overhead and a small constant runtime cost. Reserve them for code paths that fire rarely.

**5. Writing the BPF object from scratch every boot**. If you generate the BPF program from templated C in your build system, you'll regenerate it on every kernel upgrade and break CO-RE compatibility. Pin the BPF objects in the firmware image.

**6. Letting the collector log to journald**. Journald on a small device will eat flash and CPU. Have the collector write to a structured log file (rotated by `logrotate` or equivalent) or to a ring buffer in shared memory that an external watchdog drains.

## Where to Anchor for Production

The names to know, with their canonical docs:

- **libbpf** — [https://github.com/libbpf/libbpf](https://github.com/libbpf/libbpf) — the C library for loading BPF objects. Read the [libbpf-bootstrap](https://github.com/libbpf/libbpf-bootstrap) examples before writing anything.
- **bpftool** — included with the kernel under `tools/bpf/bpftool`. Use `bpftool prog list` and `bpftool map list` to debug what's loaded.
- **Cilium's BPF docs** — [https://docs.cilium.io/en/stable/bpf/](https://docs.cilium.io/en/stable/bpf/) — the most complete public reference on BPF maps, helpers, and program types.
- **The kernel's own BPF samples** — `samples/bpf/` in the kernel tree, especially `trace_output` and `ringbuf` examples.
- **Pixie's eBPF docs** — [https://docs.pixielabs.ai/reference/about-pixie/ebpf-pixie](https://docs.pixielabs.ai/reference/about-pixie/ebpf-pixie) — a real production deployment of uprobes + ring buffers at scale.

A practical end-to-end starter for embedded looks like this:

1. Use the [libbpf-bootstrap](https://github.com/libbpf/libbpf-bootstrap) `minimal` template as your starting skeleton.
2. Add a `SEC("tp_btf/...")` program for the tracepoint you care about.
4. Replace `perf_buffer` with `ring_buffer` in the consumer.
5. Add a watermark and a max-entries clamp in the loader.
6. Add a userspace-side bounded queue and a drop counter.
7. Batch, compress, and forward.

That's it. Everything else is tuning.

## Key Takeaways

- **Use CO-RE and BTF-based tracepoints** whenever you can. One `.o` per architecture beats one per kernel version, especially on long-lived embedded fleets.
- **Aggregate in the kernel; stream summaries.** Don't emit raw per-event data for high-frequency events. Histograms and counters are far cheaper than events.
- **Right-size the ring buffer** for your slowest consumer, with a 2× safety factor. Default to 64 KB on constrained devices and adjust by device class.
- **Cap BPF map memory at load time.** Fail fast if a map exceeds your device budget. Don't trust defaults.
- **The userspace collector must be tiny, statically linked, and self-contained.** No Python, no Node, no 30 MB OpenTelemetry SDK. One C or Rust binary.
- **Sample and shed deliberately.** Drop policy is a feature, not a failure. Track drops; emit them as a metric.
- **Avoid `/sys/kernel/debug` and debugfs.** Use BTF-based tracepoints in `/sys/kernel/btf/`.
- **Test on the actual target kernel, not your laptop.** The verifier, instruction limits, and helper availability differ across kernel versions.

## Further Reading

- [libbpf GitHub repository and documentation](https://github.com/libbpf/libbpf)
- [Cilium BPF reference docs](https://docs.cilium.io/en/stable/bpf/)
- [BPF ring buffer kernel docs](https://docs.kernel.org/next/userspace-api/ring_buffer.html)
- [Pixie's architecture overview — eBPF-based observability](https://docs.pixielabs.ai/reference/about-pixie/ebpf-pixie)
- [Tetragon — eBPF-based security observability](https://github.com/cilium/tetragon)
- [bpftool man page — debugging BPF programs and maps](https://manpages.debian.org/testing/bpftool/bpftool.8)