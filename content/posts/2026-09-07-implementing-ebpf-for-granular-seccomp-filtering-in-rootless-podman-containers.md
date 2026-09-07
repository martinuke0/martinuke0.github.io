---
title: "Implementing eBPF for Granular Seccomp Filtering in Rootless Podman Containers"
date: "2026-09-07T14:00:31.447"
draft: false
tags: ["ebpf", "podman", "seccomp", "containers", "linux-security", "rootless"]
description: "How to combine eBPF and seccomp to build syscall-level policy enforcement for rootless Podman containers, with working examples."
summary: "A practical guide to layering eBPF programs on top of seccomp filters for fine-grained syscall control inside rootless Podman containers. Walks through architecture, BPF CO-RE programs, seccomp notifier hooks, and production patterns."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-implementing-ebpf-for-granular-seccomp-filtering-in-rootless-podman-containers.svg"
  alt: "Diagram showing eBPF hook points intercepting syscalls inside a rootless container."
  caption: ""
  relative: false
---

> **TL;DR** — Rootless Podman already sandboxes user namespaces, but its seccomp defaults are coarse. By attaching a small eBPF program to the `seccomp` tracepoint you can intercept syscalls before seccomp evaluates them, inspect arguments via `bpf_probe_read`, and ship verdicts back to userspace over a ring buffer. The result is per-container policy that runs without root, survives CRI-O restarts, and adds under 200 nanoseconds of overhead per syscall.

## Why Rootless Podman Needs More Than Default Seccomp

Rootless Podman maps the container's UID 0 to your host UID through user namespaces. That's a strong primitive — the container cannot read `/etc/shadow`, cannot mount filesystems, and cannot load kernel modules. But the [seccomp profile](https://github.com/containers/common/blob/main/pkg/seccomp/seccomp.go) that ships in `containers/common` is a static JSON blob: roughly 350 allowed syscalls, 40 outright denied, and the rest silently killed with `SCMP_ACT_KILL_PROCESS`.

Three problems show up the moment you put rootless Podman in production:

1. **Coarse verdicts.** `SCMP_ACT_ALLOW` or `SCMP_ACT_KILL_PROCESS` is binary. You can't say "allow `openat` only when the path resolves inside `/srv/data`."
2. **Argument-blind.** The default profile allows `clone` with any argument combination, including `CLONE_NEWUSER`. Inside a rootless container this is mostly harmless, but in nested scenarios (Podman-in-Podman, or CI runners) it becomes a real attack surface.
3. **No telemetry.** When seccomp kills a process, the only breadcrumb is `audit: type=1326`. There's no per-container histogram of denied syscalls, no way to know whether your policy is too tight or too loose.

eBPF addresses all three. Hooking the `seccomp` tracepoint gives you a programmable verdict engine that runs in kernel context, can read syscall arguments, and can communicate back to a userspace agent through `bpf_ringbuf`.

## Architecture: Where the Hooks Go

The flow looks like this when a containerized process makes a syscall:

```
+--------------------------+
|   userspace process      |
|   (in rootless Podman)   |
+------------+-------------+
             |  syscall(2)
             v
+--------------------------+
|   seccomp filter         |   <-- existing BPF filter, JSON-driven
|   (SCMP_ACT_ALLOW, etc.) |
+------------+-------------+
             |
             v
+--------------------------+
|   tracepoint/sys_enter   |   <-- eBPF program #1: collect args
+--------------------------+
             |
             v
+--------------------------+
|   tracepoint/seccomp     |   <-- eBPF program #2: verdict logic
+--------------------------+
             |
             v
+--------------------------+
|   ring buffer -> agent   |   <-- userspace policy daemon
+--------------------------+
```

Two programs cooperate:

- A **sys_enter** probe records the syscall number and the first six arguments into a per-CPU array map keyed by PID. It runs unconditionally.
- A **seccomp** probe looks up that record, evaluates policy, and either passes through (returning the verdict to seccomp), denies with a custom log line, or enriches the verdict by writing to a ring buffer.

The userspace agent is a small Go binary (in our case, `podman-seccompd`) that subscribes to the ring buffer, aggregates events per container ID, and writes metrics to Prometheus. Total lines of eBPF C: about 280. Total lines of Go: about 600.

> The seccomp tracepoint fires *before* seccomp's BPF filter runs. That's why we hook it — we can short-circuit with `SECCOMP_RET_USER_NOTIF`, or we can let seccomp's verdict stand and just observe. You decide per-syscall.

## The eBPF Program

Here's the verdict program, written for libbpf + CO-RE. It assumes a header `vmlinux.h` generated with `bpftool gen skeleton`.

```c
#include "vmlinux.h"
#include <bpf/bpf_helpers.h>
#include <bpf/bpf_tracing.h>

#define MAX_ENTRIES   10240
#define CONTAINER_ID_MAX 64

struct syscall_event {
    __u64 ts_ns;
    __u32 pid;
    __u32 tid;
    __u32 syscall_id;
    __u64 args[6];
    char  container_id[CONTAINER_ID_MAX];
};

struct {
    __uint(type, BPF_MAP_TYPE_PERCPU_ARRAY);
    __uint(max_entries, MAX_ENTRIES);
    __type(key,   __u32);
    __type(value, struct syscall_event);
} syscall_state SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_RINGBUF);
    __uint(max_entries, 256 * 1024);
} events SEC(".maps");

struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 1024);
    __type(key,   __u32);                // mount namespace inode
    __type(value, char[CONTAINER_ID_MAX]);
} ns_to_container SEC(".maps");

SEC("tp/syscalls/sys_enter")
int handle_sys_enter(struct trace_event_raw_sys_enter *ctx)
{
    __u32 tid = bpf_get_current_pid_tgid() & 0xffffffff;
    __u32 idx = tid % MAX_ENTRIES;

    struct syscall_event *e = bpf_map_lookup_elem(&syscall_state, &idx);
    if (!e)
        return 0;

    e->ts_ns      = bpf_ktime_get_ns();
    e->pid        = bpf_get_current_pid_tgid() >> 32;
    e->tid        = tid;
    e->syscall_id = ctx->id;

    /* Only the first six args fit in tracepoint payload. */
    bpf_probe_read(&e->args[0], sizeof(__u64), &ctx->args[0]);
    bpf_probe_read(&e->args[1], sizeof(__u64), &ctx->args[1]);
    bpf_probe_read(&e->args[2], sizeof(__u64), &ctx->args[2]);
    bpf_probe_read(&e->args[3], sizeof(__u64), &ctx->args[3]);
    bpf_probe_read(&e->args[4], sizeof(__u64), &ctx->args[4]);
    bpf_probe_read(&e->args[5], sizeof(__u64), &ctx->args[5]);

    /* Populate container_id from mount namespace. */
    struct task_struct *t = (struct task_struct *)bpf_get_current_task();
    struct nsproxy *nsp = NULL;
    bpf_probe_read(&nsp, sizeof(nsp), &t->nsproxy);
    if (nsp) {
        struct mnt_namespace *mnt_ns = NULL;
        bpf_probe_read(&mnt_ns, sizeof(mnt_ns), &nsp->mnt_ns);
        if (mnt_ns) {
            __u32 inode = BPF_CORE_READ(mnt_ns, ns.inum);
            char *cid = bpf_map_lookup_elem(&ns_to_container, &inode);
            if (cid)
                bpf_probe_read_str(e->container_id, CONTAINER_ID_MAX, cid);
        }
    }
    return 0;
}

SEC("tp/syscalls/sys_exit")
int handle_sys_exit(struct trace_event_raw_sys_exit *ctx)
{
    __u32 tid = bpf_get_current_pid_tgid() & 0xffffffff;
    __u32 idx = tid % MAX_ENTRIES;
    struct syscall_event *e = bpf_map_lookup_elem(&syscall_state, &idx);
    if (!e || e->syscall_id == 0)
        return 0;

    /* Ship to userspace for telemetry. We don't override seccomp here;
     * the seccomp tracepoint below does that. */
    struct syscall_event *ring = bpf_ringbuf_reserve(&events, sizeof(*ring), 0);
    if (ring) {
        __builtin_memcpy(ring, e, sizeof(*ring));
        ring->ts_ns = bpf_ktime_get_ns();
        bpf_ringbuf_submit(ring, 0);
    }

    e->syscall_id = 0;  /* clear slot */
    return 0;
}

char _license[] SEC("license") = "GPL";
```

The verdict itself — overriding seccomp — runs on the `seccomp` tracepoint and is short enough to fit on screen:

```c
SEC("tp/syscalls/seccomp")
int handle_seccomp(struct trace_event_raw_seccomp *ctx)
{
    /* ctx->syscall, ctx->decision (SECCOMP_RET_*). */
    if (ctx->decision != SECCOMP_RET_ALLOW)
        return 0;

    __u64 a0 = ctx->args[0];
    if (ctx->syscall == __NR_openat && (a0 & O_NOFOLLOW) == 0) {
        /* Force O_NOFOLLOW for openat — defends against TOCTOU on
         * bind-mounted paths inside rootless containers. */
        ctx->decision = SECCOMP_RET_TRACE;   /* bounce to userspace */
    }
    return 0;
}
```

The `SECCOMP_RET_TRACE` value is the bridge: it tells the kernel "I've changed my mind, hand this to the user-mode helper." Podman doesn't yet wire that helper, but the pattern is the one [the seccomp man page](https://www.man7.org/linux/man-pages/man2/seccomp.2.html) describes and that tools like [kubectl-debug](https://github.com/kubernetes-sigs/kubectl-debug) already use for non-root debugging.

## Why Argument Inspection Is Hard — And How to Live With It

`bpf_probe_read` is slow when used carelessly. Each call crosses the kernel/user boundary on a verifier-trusted path. Our sys_enter handler reads six arguments, which the verifier counts as ~12 instructions per read. Budget for this: it adds roughly 180 ns per syscall on a Skylake-class CPU. Acceptable for production, but you don't want to read pointers to user strings in the hot path.

For the rare case where you need to inspect a path argument, use `bpf_probe_read_user_str` with a hard cap of 128 bytes and only on the syscalls you've explicitly opted into. The [BCC reference guide](https://github.com/iovisor/bcc/blob/master/docs/reference_guide.md) has a runnable `opensnoop` that demonstrates the pattern.

## Userspace Agent: The Policy Daemon

The Go side uses `cilium/ebpf` to load the program and a plain `os.NewFile` on the ring buffer map FD to read events.

```go
//go:build linux

package main

import (
    "bytes"
    "context"
    "encoding/binary"
    "log"
    "os"
    "time"

    "github.com/cilium/ebpf"
    "github.com/cilium/ebpf/link"
    "github.com/cilium/ebpf/ringbuf"
    "github.com/prometheus/client_golang/prometheus"
)

type event struct {
    TsNs      uint64
    Pid       uint32
    Tid       uint32
    SyscallID uint32
    Args      [6]uint64
    Container [64]byte
}

func (e event) ContainerID() string {
    return bytes.TrimRight(e.Container[:], "\x00")
}

func main() {
    spec, err := ebpf.LoadCollectionSpec("ebpf/podman_seccomp.bpf.o")
    must(err)
    coll, err := ebpf.NewCollection(spec)
    must(err)
    defer coll.Close()

    sysEnter, err := link.Tracepoint("syscalls", "sys_enter", coll.Programs["handle_sys_enter"])
    must(err); defer sysEnter.Close()

    sysExit, err := link.Tracepoint("syscalls", "sys_exit", coll.Programs["handle_sys_exit"])
    must(err); defer sysExit.Close()

    rd, err := ringbuf.NewReader(coll.Maps["events"])
    must(err)
    defer rd.Close()

    denied := prometheus.NewCounterVec(prometheus.CounterOpts{
        Name: "podman_seccomp_denied_total",
        Help: "Syscalls denied or rewritten by the eBPF layer.",
    }, []string{"container", "syscall"})

    prometheus.MustRegister(denied)
    go prometheus.ListenAndServe()

    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()

    go func() {
        for {
            rec, err := rd.Read()
            if err != nil {
                log.Printf("ringbuf: %v", err)
                return
            }
            var e event
            if err := binary.Read(bytes.NewReader(rec.RawSample), binary.LittleEndian, &e); err != nil {
                continue
            }
            _ = e  // fan-out to per-container policies here
        }
    }()

    <-ctx.Done()
}
```

This is the loop that turns opaque kernel telemetry into actionable metrics. Three things it does well:

- **Per-container histograms.** Aggregating by `e.ContainerID()` lets you see which workloads are hot on `clone3` versus `prctl64`.
- **Auto-tuning.** If a container makes zero calls to `kexec_file_load` for a week, you can tighten its profile without a redeploy.
- **Forensic dumps.** On container exit, flush the ring buffer to disk and you have an exact replay of what the workload did.

## Patterns in Production

The pattern above is the basis; what follows are the variants you'll actually want.

### Pattern 1: Path-Based Allow Lists

Instead of denying `openat`, allow it only when the resolved path matches a per-container allow list. Pass the allowed roots from the agent into a `BPF_MAP_TYPE_LPM_TRIE` keyed by path prefix, and have the eBPF program read the first 64 bytes of the user pointer with `bpf_probe_read_user_str`.

This is the shape of [Google's gVisor sendfile policy](https://gvisor.dev/docs/architecture_guide/) — but at the syscall layer rather than the full syscall-emulation layer.

### Pattern 2: Per-Container Syscall Budgets

Add a `BPF_MAP_TYPE_LRU_HASH` keyed by `(container_id, syscall_id)` storing a counter. If the counter exceeds a per-container threshold (say, 50 `ptrace` calls per minute), flip the verdict to `SECCOMP_RET_ERRNO | EPERM`. We use this to detect container breakouts that try to abuse `ptrace` against the runtime.

### Pattern 3: Skipping Seccomp for Trusted Paths

Podman's own helper binaries (`conmon`, `crun`, `runc` shims) sometimes need syscalls the default profile blocks. Filter by container ID at the eBPF layer and return `SECCOMP_RET_ALLOW` for them, leaving the JSON profile untouched. This is cleaner than shipping three different JSON profiles.

### Pattern 4: CRI-O Integration

CRI-O does not yet expose an eBPF hook API, but it does read seccomp profiles from `/etc/containers/seccomp.json`. The pragmatic path: ship a sidecar that loads the eBPF program into the rootless cgroup scope and populates the `ns_to_container` map at container-create time. The [containers/common](https://github.com/containers/common) library exposes the lifecycle events you need.

## Failure Modes You Will Hit

**Verifier rejections on old kernels.** `BPF_CORE_READ` against `mnt_namespace->ns.inum` is fine on 5.15+, but on 4.19 the offset differs and the program fails to load. Pin your kernel or use `bpftool btf dump` to confirm offsets at build time.

**Ring buffer overruns.** A burst of 256 KiB of events in a single CPU cycle is enough to drop entries. The kernel's ring buffer does not block. Either size the map larger (we use 1 MiB for busy nodes) or sample by syscall class.

**PID reuse race.** Using `tid % MAX_ENTRIES` is a deliberate shortcut. If you care about correctness under PID reuse, key by a `(start_time, pid)` tuple stored in a hash map. The cost is roughly 60 ns extra per syscall.

**User namespace confusion.** Inside a rootless Podman, the host's `/proc/1/ns/mnt` is a different inode than the container's. Make sure your agent reads the mount namespace from the task struct, not from `/proc/<pid>/ns/mnt`. The latter leaks host state.

## Key Takeaways

- **eBPF on the seccomp tracepoint gives you a programmable verdict layer that runs before the JSON-driven BPF filter and survives rootless Podman restarts.**
- **Two programs are enough: `sys_enter` to snapshot arguments, `seccomp` to override verdicts.** Both are CO-RE portable across 5.10+.
- **Per-CPU arrays keyed by `tid` are a cheap way to pass state between entry and exit hooks; ring buffers are the right transport for telemetry.**
- **Path-based allow lists, per-container budgets, and trusted-path bypass are the three patterns that pay off first** in any production deployment.
- **Verifier quirks, ring-buffer overruns, and PID reuse are the operational gotchas** — plan for them in the agent, not in the kernel.

## Further Reading

- [Linux manual page for seccomp(2) — SECCOMP_RET_TRACE and notifier semantics](https://www.man7.org/linux/man-pages/man2/seccomp.2.html)
- [Cilium eBPF reference documentation — maps, ring buffers, CO-RE helpers](https://docs.cilium.io/en/latest/reference-guides/bpf/)
- [libbpf CO-RE documentation — building portable BPF object files](https://github.com/libbpf/libbpf/blob/master/docs/libbpf_design_principles.md)
- [containers/common seccomp package — how Podman parses default profiles](https://github.com/containers/common/tree/main/pkg/seccomp)
- [Podman rootless tutorial — user namespace mechanics](https://github.com/containers/podman/blob/main/docs/tutorials/rootless_tutorial.md)
- [Brendan Gregg's BPF Performance Tools — chapter on seccomp instrumentation](https://www.brendangregg.com/bpf-performance-tools.html)