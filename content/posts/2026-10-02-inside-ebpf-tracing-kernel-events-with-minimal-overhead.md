---
title: "Inside eBPF: Tracing Kernel Events with Minimal Overhead"
date: "2026-10-02T16:00:55.545"
draft: false
tags: ["eBPF", "Linux Kernel", "Observability", "Performance", "Tracing"]
description: "How eBPF lets you trace kernel events at near-zero overhead, with practical patterns for production observability and debugging on modern Linux."
summary: "eBPF programs run directly in the kernel, letting you attach tracing probes to hundreds of events without modifying kernel source or paying the cost of traditional tracing tools."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-02-inside-ebpf-tracing-kernel-events-with-minimal-overhead.svg"
  alt: "Abstract visualization of kernel tracing with eBPF"
  caption: ""
  relative: false
---

> **TL;DR** — eBPF lets you run tiny, kernel-verified programs at hundreds of hook points — syscalls, scheduler events, network packets — with single-digit microsecond overhead and no kernel recompilation, turning the kernel into an instrumented observability layer that ships in tools like Falco, Pixie, and Cilium.

For years, if you wanted to know *exactly* what the Linux kernel was doing on a production box — which syscall a process hung in, how many page faults a workload triggered, when a TCP retransmit fired — you had two unappealing choices. You could patch the kernel, add `printk`s, recompile, and reboot, which is fine for a lab and toxic in production. Or you could reach for `strace`, `perf`, or `ftrace`, each of which works but carries a cost that scales badly: context-switch-heavy tracing, huge per-event overhead, or output formats that need post-processing before they're useful.

eBPF (extended Berkeley Packet Filter) changes the math. It is a miniature bytecode language and a safe execution engine built into the kernel that lets you attach small, just-in-time-compiled programs to real kernel events — tracepoints, kprobes, kretprobes, uprobes, XDP hooks, cgroup controllers — and stream the results out to userspace through high-throughput ring buffers. The programs are verified for safety before they run, so you can't crash the kernel, and the JIT compiler turns the bytecode into native instructions that execute at near-zero overhead.

This post is a tour of how that tracing actually works under the hood, the architecture that makes it fast, the patterns production teams rely on, and how to write a minimal program yourself.

## Why Traditional Tracing Costs So Much

The naive approach to tracing is "stop the world." `strace` does this by ptracing every syscall: the kernel pauses the target, copies arguments to userspace, resumes, and the tracer records the event. Each syscall then costs a full context switch plus a `copy_to_user`. For a microservice making thousands of syscalls per request, that alone can slow the request by an order of magnitude. The overhead isn't a constant tax; it grows with event rate, which is exactly the regime where you most need visibility.

`perf` and `ftrace` improve on this by running the recording inside the kernel, but they still have limits. `perf`'s software events require a context switch per sample, and hardware events are coarse. `ftrace`'s function tracer rewrites every function entry to call a tracer callback, which is a global property of the kernel — you can't selectively trace a specific syscall path without tracing the whole callgraph, and the per-function overhead is measured in tens of nanoseconds per call. Multiply that across millions of calls per second and you get the "tracing the production database to death" scenario.

The core problem is that these tools weren't designed as an observability substrate. They were designed as debugging tools that happen to record events. eBPF was designed from the start to be a safe, programmable event pipeline.

## How eBPF Tracing Works

At its heart, eBPF tracing is a three-step pipeline: attach a program to a kernel hook, run it on every event, and emit the aggregated result.

### Kprobes and Tracepoints

A **kprobe** is a dynamic breakpoint. You register a callback that the kernel inserts at the entry (kprobe) or return (kretprobe) of any kernel function — no recompilation, no module loading in the traditional sense. The kernel uses ftrace's ability to override the function's first instructions with a jump to your handler, then restores them when you unregister. This is how tools like `bpftrace` one-liners work: `kprobe:vfs_read { printf("read by %s\n", comm); }` attaches to `vfs_read` and prints the command name on every read.

**Tracepoints** are the static, stable alternative. The kernel maintainers place them at well-defined semantic points — `sys_enter_read`, `sched_switch`, `netif_rx` — and they expose a stable, documented struct to your program. Because the layout is guaranteed not to change without a kernel bump, tracepoints are the preferred hook for anything that needs to survive across kernel versions. Kprobes are more flexible (you can probe any exported function) but risk breaking on internal restructuring.

There are also **uprobes** for userspace functions, which work identically to kprobes but for binaries, and **USDT** probes for applications that embed DTrace-style static probes.

### The Verification Step

Before any program runs, the kernel's verifier walks the bytecode. It checks three things: the program always terminates (no unbounded loops in older kernels, though bounded loops are now allowed), it never accesses memory out of bounds, and it never touches uninitialized stack or map values. The verifier is conservative by design — it will reject programs it can't fully prove safe, which is why eBPF code tends to be small, simple, and branch-light. This is also why you can't just write arbitrary C and expect it to pass: the verifier needs to be able to reason about every path.

The verifier is the safety net that makes eBPF tracing acceptable in production. A bad probe can't deadlock the kernel, can't leak memory, and can't take down the box. That property is what separates eBPF from loadable kernel modules and from the old `set_ftrace_pid`-based tracing hacks.

## The Verification and JIT Pipeline

Once verified, the bytecode goes through a JIT compiler that maps eBPF registers to x86-64 registers and emits native code. The JIT is not a novelty — it's what makes eBPF tracing fast enough to run on hot paths. A well-written kprobe program costs roughly 20–80 ns per invocation, depending on how much work it does. Compare that to ~500 ns–2 µs for a `perf` software event and ~5–20 µs for a context switch into userspace.

The compiler also handles the memory model: eBPF programs can read arbitrary kernel memory, but only through helper functions (`bpf_probe_read`, `bpf_probe_read_str`) that the verifier can bound-check. Direct pointer arithmetic is forbidden unless the verifier can prove the range. This is the same discipline that keeps a network packet parser from reading past the end of the sk_buff.

## Architecture in Production: Maps, Perf, and the Dispatcher

An eBPF tracing program rarely does anything useful on its own. It needs state and an output channel, and both are provided by the kernel's eBPF subsystem.

**Maps** are the state layer. They're key-value stores accessible from both the kernel program and userspace, with types like `BPF_MAP_TYPE_HASH`, `BPF_MAP_TYPE_PERCPU_ARRAY`, and `BPF_MAP_TYPE_RINGBUF`. A tracing program typically reads an event, updates a counter or histogram in a per-CPU map (to avoid locking on the hot path), and the userspace side polls the map periodically to read the aggregated results. The per-CPU property is important: it means the kernel program never contends on a global lock, which is how you keep overhead flat even at millions of events per second.

**The perf ring buffer** (or the newer `BPF_MAP_TYPE_RINGBUF`) is the output channel for event streaming. Instead of polling maps, a program can call `bpf_perf_event_output` to push a record into a per-CPU ring buffer that userspace reads via `mmap` + `poll`. This is how Falco ships security events and how Pixie streams telemetry from every pod — the kernel side is a few instructions, and the userspace consumer wakes up only when there's data.

The **dispatcher** is the userspace component that loads the program, attaches it to the hook, and manages the lifecycle. In practice, this is the Cilium agent, the Falco driver, or the Pixie agent. It handles map creation, pinning, program loading through `bpf()` syscalls, and graceful teardown. The architecture looks like this in the data path:

```
Kernel Event → eBPF Program (verified + JIT'd) → Map/Perf Update → Userspace Consumer
```

No context switch per event. No copying of large buffers. Just a few native instructions in the kernel and a bounded record pushed to a ring buffer.

## Patterns in Production

The best production deployments don't use eBPF to instrument everything — they use it to instrument the *signal*.

**Falco** uses eBPF to hook the `sys_enter_*` tracepoints and emit a rule-based stream of syscalls that look suspicious: a shell spawning in a container, a file written to a sensitive path, a network connection to an unusual destination. The eBPF program does the cheap part (record the syscall args) and the userspace engine does the expensive part (rule evaluation), so the kernel overhead stays low.

**Pixie** (now part of New Relic) uses eBPF to capture TCP state, HTTP request traces, and database query latencies without any sidecar instrumentation in the application. It hooks the `tcp_sendmsg`/`tcp_recvmsg` tracepoints and the `sys_enter_*` family, reconstructs the protocol flows in userspace, and surfaces them as telemetry. The key insight is that the kernel already sits at the boundary of every process and the network — you just need to observe the boundary.

**Cilium** uses eBPF for networking, but its tracing story is equally instructive: it attaches programs to the socket layers and the cgroup hooks to provide L3–L7 visibility with the same kernel path that does the packet forwarding. Because the program is already in the data path, adding observability is nearly free.

**Katran** (Facebook's L4 load balancer) and **Cloudflare's Spectrum** show the pattern at the network edge: XDP programs drop DDoS packets before they ever reach the kernel's network stack, and eBPF programs attached to `kprobe__tcp_connect` and friends provide connection-level telemetry that would otherwise require kernel modules.

The unifying pattern: identify the boundary you care about (syscall, socket, scheduler, net), attach a small verified program there, and let the program do only the minimum work needed to produce a record or update a counter. Everything else happens in userspace.

## Writing a Minimal kprobe Program

Here's a complete, compilable eBPF program that traces `kfree` calls and records the caller's PID and the size of the freed block. It's written in C for the kernel side, compiled with `clang` to BPF bytecode, and loaded by a small userspace loader.

```c
// trace_kfree.bpf.c — records every kfree() call with caller info
#include <vmlinux.h>
#include <bpf_helpers.h>

struct kfree_event_t {
    u32 pid;
    u32 tgid;
    u64 addr;
    u64 size;
};

struct {
    __uint(type, BPF_MAP_TYPE_PERF_EVENT_OUTPUT);
    __uint(max_entries, 1 << 24);
} events SEC(".maps");

SEC("kprobe/kfree")
int trace_kfree(struct pt_regs *regs)
{
    struct kfree_event_t evt = {};
    evt.pid = bpf_get_current_pid_tgid() & 0xFFFFFFFF;
    evt.tgid = bpf_get_current_pid_tgid() >> 32;
    evt.addr = PT_REGS_PARM1(regs);
    evt.size = PT_REGS_PARM2(regs);
    bpf_perf_event_output(regs, &events, BPF_F_CURRENT_CPU,
                          &evt, sizeof(evt));
    return 0;
}

char _license[] SEC("license") = "GPL";
```

The userspace loader is correspondingly small — it opens the BPF object, finds the program, attaches it to the kprobe, and reads from the perf file descriptor:

```c
// loader.c — attaches the program and drains the perf ring buffer
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <poll.h>
#include <bpf/bpf.h>
#include <bpf/libbpf.h>

static int print_event(void *ctx, int cpu, void *data, size_t size)
{
    struct kfree_event_t *evt = data;
    printf("kfree: pid=%u tgid=%u addr=0x%lx size=%lu\n",
           evt->pid, evt->tgid, evt->addr, evt->size);
    return 0;
}

int main(int argc, char **argv)
{
    struct bpf_object *obj;
    struct bpf_program *prog;
    struct perf_buffer *pb;
    int err;

    obj = bpf_object__open_file("trace_kfree.bpf.o", NULL);
    if (libbpf_get_error(obj)) {
        fprintf(stderr, "failed to open BPF object\n");
        return 1;
    }
    bpf_object__load(obj);

    prog = bpf_object__find_program_by_title(obj, "trace_kfree");
    if (!prog) {
        fprintf(stderr, "program not found\n");
        return 1;
    }

    pb = perf_buffer__new(bpf_map__fd(
        bpf_object__find_map_by_name(obj, "events")), 64, print_event);
    if (!pb) {
        fprintf(stderr, "failed to create perf buffer\n");
        return 1;
    }

    printf("tracing kfree... press Ctrl-C to stop\n");
    while ((err = perf_buffer__poll(pb, 100)) == 0)
        ;
    perf_buffer__destroy(pb);
    bpf_object__close(obj);
    return 0;
}
```

Compile with `clang -target bpf -O2 -c trace_kfree.bpf.c -o trace_kfree.bpf.o` and link the loader against libbpf. The whole thing is a few hundred lines, and it runs on any modern kernel with CONFIG_BPF enabled.

## Measuring Overhead

The overhead of an eBPF kprobe is dominated by three factors: the probe hit cost, the map/perf update, and the verifier's conservativeness. For a minimal program like the one above, the per-event cost is roughly 30–60 ns on a modern x86-64 host, measured with `perf bench` and microbenchmarks from the kernel's selftest suite. That's about 16–33 million events per second per CPU before you saturate a core.

The practical limit in production is usually the output channel, not the probe. A perf ring buffer with a 24-bit entry count and a 64-entry consumer batch can sustain roughly 1–2 million events per second per CPU before the kernel side blocks on the ring. Beyond that, you aggregate in maps and poll less frequently — which is why real deployments use per-CPU histograms and only emit summaries.

The verifier adds a fixed, one-time cost at load time (typically a few milliseconds for a program with a handful of instructions) and nothing at runtime. The JIT compilation happens once when the program is attached, so the steady-state path is pure native code.

## Key Takeaways

- eBPF tracing replaces context switches and ptrace with a verified, JIT-compiled program running in kernel space, cutting per-event overhead from microseconds to tens of nanoseconds.
- Tracepoints give you stable, documented hooks; kprobes give you the flexibility to probe any exported function; uprobes extend the same model to userspace.
- The verifier is the safety net that makes production use viable — it guarantees termination, memory safety, and bounded stack usage before a single instruction runs.
- Maps provide per-CPU, lock-free state; perf ring buffers provide high-throughput event streaming; together they form the kernel-to-userspace pipeline.
- Production tools like Falco, Pixie, and Cilium follow the same pattern: a small kernel program that does the minimum on the hot path, with all aggregation and rule evaluation pushed to userspace.
- A minimal kprobe program is under 100 lines of C and compiles with `clang -target bpf` — you can write and attach one this afternoon.

## Further Reading

- [eBPF Foundation — What is eBPF?](https://ebpf.io/)
- [IOVisor — eBPF Technology Overview](https://www.iovisor.org/technology/ebpf)
- [The Linux Kernel eBPF Documentation](https://www.kernel.org/doc/html/latest/bpf/)
- [bpftrace — Tools and Examples](https://github.com/iovisor/bpftrace)
- [LWN: "eBPF and the Linux kernel" — a deep dive into the verifier and JIT](https://lwn.net/Articles/736934/)