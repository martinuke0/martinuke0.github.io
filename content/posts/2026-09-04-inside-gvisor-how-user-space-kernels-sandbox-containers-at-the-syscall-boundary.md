---
title: "Inside gVisor: How User-Space Kernels Sandbox Containers at the Syscall Boundary"
date: "2026-09-04T04:00:43.512"
draft: false
tags: ["gVisor", "containers", "sandboxing", "syscalls", "security", "kubernetes"]
description: "A deep dive into gVisor's user-space kernel architecture, how it intercepts syscalls, and why it changes the container security model."
summary: "gVisor moves the Linux kernel into userspace to sandbox containers at the syscall boundary, trading raw throughput for a dramatically smaller attack surface."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-gvisor-how-user-space-kernels-sandbox-containers-at-the-syscall-boundary.svg"
  alt: "Diagram of gVisor Sentry intercepting syscalls between application and host kernel."
  caption: ""
  relative: false
---

> **TL;DR** — gVisor re-implements enough of the Linux kernel in user space to intercept every syscall a container makes, so untrusted application code never talks to the host kernel directly. It costs you CPU, but it shrinks the kernel attack surface by roughly 80% and is the same approach Google uses to run multi-tenant workloads on Cloud Run and App Engine.

When a container "runs" on Linux, the kernel does most of the heavy lifting: the `open`, `read`, `write`, `clone`, and `mmap` syscalls all execute in ring 0, inside the same monolithic kernel that hosts every other tenant on the machine. The isolation story is namespaces, cgroups, and seccomp — strong, but the kernel itself is the trust boundary. A bug in any of those tens of millions of lines of code is a bug in your container's wall.

[gVisor](https://gvisor.dev/docs/) takes a different bet: what if the application never actually calls into the host kernel at all? Instead, the application calls into a userspace re-implementation of Linux that itself decides what is safe to forward to the real kernel. That intermediate layer — the *Sentry* — becomes the trust boundary, and the host kernel becomes an unwitting I/O multiplexer.

## Why a User-Space Kernel at All

The original Google paper and the [open-source release](https://github.com/google/gvisor) frame gVisor as a defense-in-depth layer for multi-tenant environments. Traditional container runtimes rely on:

- **Linux namespaces** for filesystem, PID, network, and IPC isolation.
- **cgroups** for resource limits.
- **seccomp** to blacklist dangerous syscalls.
- **capabilities** to drop privileges.

Each of these is enforced *by the host kernel*. If the kernel has a bug — and Linux historically has many in its filesystem, network, and ioctl paths — a container can sometimes exploit it to escape. gVisor's pitch is simple: don't trust the host kernel with your syscalls at all. Let a small, audited userspace program handle them.

The cost is performance. The benefit is a much smaller TCB (trusted computing base) in the syscall hot path.

## The Two-Process Architecture

gVisor runs every sandboxed application as two cooperating processes:

1. **The Sentry** — written in Go, this process loads the application binary and emulates the Linux kernel for it. It implements file systems (Gofer, procfs, sysfs, tmpfs, overlay), networking (an AF\_INET/AF\_PACKET stack called `netstack`), process management, signal delivery, and the syscall ABI.
2. **The Gofer** — a small, thin process that brokers host filesystem access for the Sentry. The Sentry never opens files on the host directly; it always goes through the Gofer, which is a much smaller surface than a fully featured kernel.

Communication between the application and the Sentry happens over a custom ptrace-based or KVM-based mechanism called the **platform**. Yes, you read that right — ptrace. A modern sandboxing primitive built on a 1990s debugging interface.

The application process is the one that owns the address space, file descriptor table, and signal state. The Sentry is a separate process that holds the *shadow* versions of all of those, then performs real syscalls on the application's behalf using a tiny set of carefully selected host syscalls.

## How a Syscall Actually Flows

Let's trace a `write(2)` call from a Go binary running inside a gVisor sandbox.

```text
application:  mov rax, 1        ; SYS_write
              mov rdi, fd
              mov rsi, buf
              mov rdx, count
              syscall
                          │
                          ▼
       Sentry (via ptrace stop or KVM exit)
                          │
                          ▼
       1. Validate fd against the shadow fd table
       2. Resolve the file's vfs entry (procfs, tmpfs, host FD via gofer)
       3. Decide: is this write allowed by seccomp, capabilities, no_new_privs?
       4. If yes, perform a SINGLE host syscall — write() — using
          a pre-mapped buffer in the sentry's own address space
       5. Inject the return value back into the application
```

So one application-level `write` becomes one host-level `write`. The interception overhead is the cost of the trap plus the cost of the Sentry's own kernel logic.

> The Sentry only ever uses around 60–70 distinct host syscalls, no matter what the application does. You can see the full list in the [gVisor security model docs](https://gvisor.dev/docs/architecture_guide/security/).

That tiny syscall whitelist is the single most important security property of gVisor. It means an application can call `io_uring_setup`, `bpf`, `perf_event_open`, or any other famously-buggy syscall and the host kernel will never see it.

## Platform: ptrace vs. KVM

gVisor ships two platform backends and choosing between them is one of the first decisions you make when deploying it.

### ptrace (the default)

The application is traced by the Sentry. Every syscall entry and exit generates a `SIGTRAP`, which the Sentry catches, interprets, and either emulates or forwards. This works anywhere Linux works — no virtualization required — but it's slow because every syscall pays a context-switch cost.

### KVM

The Sentry opens `/dev/kvm` and runs the application inside a lightweight virtual CPU. Syscalls are intercepted via KVM exit reasons rather than signals. This is closer to native performance, sometimes within 10–20% of bare metal for I/O-bound workloads, but it requires KVM access and `CAP_SYS_ADMIN`-ish privileges.

In production on Kubernetes, the KVM platform is preferred when available. The [runsc (runtime) configuration docs](https://gvisor.dev/docs/user_guide/quick_start/) show how to switch with a single flag in the OCI config:

```json
{
  "ociVersion": "1.0.2",
  "platform": {
    "sandboxer": "kvm"
  }
}
```

If you're running gVisor in a nested-virt environment where KVM isn't reliably available — say, a CI runner on a shared VM — ptrace is the fallback that still gives you the same security guarantees.

## The Sentry: A Kernel in Go

The Sentry is, in functional terms, a small monolithic kernel. It has:

- A virtual file system layer with support for overlay mounts, bind mounts, tmpfs, procfs, and a remote FUSE-like filesystem called the **Gofer** that brokers accesses to the host filesystem.
- A socket stack (`netstack`) that implements TCP, UDP, ICMP, raw sockets, and a substantial subset of `ioctl(SIOCGIFNAME)`-style queries. The application sees a normal Linux network namespace; the Sentry handles TCP state machines entirely in user space.
- Process and thread emulation with `clone`, `set_tid_address`, `futex`, and friends.
- A ptrace re-implementation so that debuggers like `strace` and `gdb` continue to work *inside* the sandbox.
- Signal delivery that respects `sigaltstack`, `SA_RESTORER`, and the rest of the gnarly POSIX signal contract.

The reason this fits in a tractable amount of code is that Go's memory model and concurrency primitives make the kernel-style "many goroutines, shared address space, careful locking" pattern expressible without manual memory management. The Sentry is one of the largest real-world demonstrations that Go can host systems code.

## Patterns in Production

### Multi-tenant serverless

This is the [original Google use case](https://cloud.google.com/blog/products/containers-kubernetes/open-sourcing-gvisor-a-sandboxed-container-runtime) and remains the most important one. Cloud Run and App Engine standard environment run user code that Google does not control. The host kernel sees only gVisor's sentry process; even if a customer's code triggers a kernel vulnerability in `fs/pipe.c`, the kernel code path isn't reached.

### High-density Kubernetes nodes

In a default Kubernetes setup, every pod is a process tree on the host, sharing the host kernel. If a node runs 200 pods, the host kernel has 200 unconfined attack surfaces. With a gVisor RuntimeClass, each pod is a sentry+application pair and the host kernel sees ~200 sentries — each calling only the ~60 allowlisted syscalls.

```yaml
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted
spec:
  runtimeClassName: gvisor
  containers:
  - name: app
    image: myservice:latest
```

### Defense in depth with seccomp

Even with gVisor, you should still ship a [seccomp profile](https://kubernetes.io/docs/tutorials/security/seccomp/). The Sentry is small but not bug-free; seccomp is your belt to gVisor's suspenders. A common pattern is to start from `RuntimeDefault`, then add the small set of additional syscalls the Sentry itself needs (e.g., `prctl`, `seccomp`, `setsid`).

## The Honest Performance Picture

GVisor is slower. Let's not pretend otherwise.

- **CPU-bound workloads**: usually within 5–15% of native. The Sentry doesn't intercept every instruction, only syscalls.
- **Syscall-heavy workloads**: 1.5x–2x slower on ptrace, 1.1x–1.3x slower on KVM. The classic offender is a tight `epoll` loop in a network server.
- **Filesystem-heavy workloads**: 2x–4x slower because the Gofer adds a hop for every file operation. The overlayfs support helps, but it is not as mature as the host's overlayfs.
- **Network-heavy workloads**: surprisingly competitive when using netstack's TPROXY/AF_PACKET, but raw `sendto` throughput can suffer because netstack goes user-space for the full TCP stack.

The performance team has steadily closed the gap. The KVM platform, the [netstack optimizations](https://gvisor.dev/blog/2019/11/12/gVisor-netstack-perf/), and the recent addition of a `directfs` mode that lets the Sentry read certain files without going through the Gofer have all made a measurable difference.

> If you're benchmark-gaming, the workload you care about most is syscalls per second. gVisor is at its best when the application is I/O bound and at its worst when it's a syscall blaster like a busy database or a fast-path network proxy.

## Where gVisor Doesn't Fit

It's worth being explicit about the rough edges:

- **Anything needing a real kernel module**: NFS client, certain accelerators, `iptables` inside the container.
- **Workloads that need raw socket performance**: gRPC servers pushing hundreds of thousands of QPS per core. You'll be tempted to bypass gVisor for these — and probably should.
- **Anything that depends on `/proc` or `/sys` quirks the Sentry doesn't emulate**: there are gaps, and the [gVisor compatibility docs](https://gvisor.dev/docs/user_guide/compatibility/) are the source of truth.
- **High-density nodes where you already trust your workloads**: the security benefit is real but the CPU cost is real too. Don't add it because it's fashionable.

## Key Takeaways

- gVisor re-implements the Linux kernel ABI in a userspace Sentry process so that untrusted application code never makes host syscalls directly.
- The host kernel sees only ~60–70 distinct syscalls issued by the Sentry, shrinking the syscall attack surface dramatically compared to a direct container runtime.
- The two platform backends are ptrace (universal, slower) and KVM (faster, requires hardware virt); choose KVM when you can.
- The Sentry is a real, if small, kernel: it has a VFS, a socket stack (netstack), process management, signal handling, and a ptrace implementation.
- Performance is the trade. CPU-bound code is fine; syscall-heavy and filesystem-heavy code can be 2x–4x slower on ptrace, much less on KVM.
- Deploy it on Kubernetes via a RuntimeClass; pair it with seccomp for defense in depth; keep it for the workloads that actually need untrusted-code isolation.

## Further Reading

- [gVisor Architecture Guide](https://gvisor.dev/docs/architecture_guide/) — the canonical walkthrough of Sentry, Gofer, and platform layers.
- [gVisor open-source announcement on Google Cloud Blog](https://cloud.google.com/blog/products/containers-kubernetes/open-sourcing-gvisor-a-sandboxed-container-runtime) — original motivation and threat model.
- [gVisor Security Model](https://gvisor.dev/docs/architecture_guide/security/) — the exact list of host syscalls the Sentry is allowed to use.
- [runsc Quick Start](https://gvisor.dev/docs/user_guide/quick_start/) — how to run your first sandboxed container.
- [Kubernetes RuntimeClass documentation](https://kubernetes.io/docs/concepts/containers/runtime-class/) — wiring gVisor into a cluster.
- [gVisor netstack performance post](https://gvisor.dev/blog/2019/11/12/gVisor-netstack-perf/) — a deep dive into the networking stack and how it was tuned.