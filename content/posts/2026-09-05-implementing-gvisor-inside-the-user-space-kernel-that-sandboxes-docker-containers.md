---
title: "Implementing gVisor: Inside the User-Space Kernel That Sandboxes Docker Containers"
date: "2026-09-05T19:00:27.770"
draft: false
tags: ["gVisor", "Docker", "containers", "security", "linux", "sandboxing"]
description: "A deep dive into gVisor's architecture: how a user-space kernel intercepts syscalls, runs sandboxed Docker containers, and what to expect in production."
summary: "How gVisor reimplements the Linux kernel in user space to safely sandbox containers, and what the trade-offs look like in real deployments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-implementing-gvisor-inside-the-user-space-kernel-that-sandboxes-docker-containers.svg"
  alt: "Diagram of gVisor's sentry and gofer architecture"
  caption: ""
  relative: false
---

> **TL;DR** — gVisor sandboxes containers by inserting a user-space kernel (the *sentry*) between the application and the host kernel. Every syscall is intercepted in Go, then handed to a re-implementation of Linux subsystems, dramatically shrinking the host attack surface at the price of some throughput and memory overhead.

## Why a User-Space Kernel?

Containers promise isolation, but at the OS level they are still processes making real syscalls on the host kernel. A single vulnerability in the kernel — or in the syscall surface a container can reach — and the "isolation" disappears. This is the problem gVisor was built to solve.

The original [gVisor announcement from Google Cloud](https://cloudplatform.googleblog.com/2018/05/open-sourcing-gvisor-sandbox-container-tools.html) frames it bluntly: the goal is to reduce the amount of host kernel code that an untrusted application can touch. Instead of letting containerized code call `open`, `read`, `write`, and `mount` directly on the host, gVisor intercepts those calls in user space and re-implements the relevant kernel semantics on behalf of the application.

This approach sits between two familiar extremes:

- **Hardware VMs** (KVM, Firecracker): strong isolation through virtualization, but heavy in memory and slow to boot.
- **Namespaces + cgroups** (plain Docker): cheap and fast, but the container shares the host kernel surface.

gVisor occupies a middle ground: same container ergonomics, but most syscalls never reach the host kernel.

## Two Architectures: ptrace and KVM

gVisor ships two backends, and choosing between them is one of the first operational decisions you'll make.

### The ptrace Backend

In `ptrace` mode, the container process is a normal Linux process. The sentry attaches to it via the [ptrace(2) interface](https://man7.org/linux/man-pages/man2/ptrace.2) and traps on every syscall. Inside the trapped handler, the sentry interprets the call against its in-memory model of Linux.

- **Pros**: no privileges beyond `CAP_SYS_PTRACE`; works in any container runtime; easy to deploy.
- **Cons**: every syscall crosses the kernel/user boundary twice, which makes `ptrace` mode roughly 2–3× slower than the host kernel on syscall-heavy workloads.

### The KVM Backend

In KVM mode, gVisor runs the application as a hardware-virtualized guest with a custom BIOS and a single vCPU. The sentry still services the syscalls, but it gets them via [KVM](https://www.linux-kvm.org/page/Main_Page) instead of ptrace. This means syscalls exit through `hypercall` instructions and stay inside the same address space, dramatically reducing overhead.

- **Pros**: 1–2× of host throughput in many benchmarks; supports multi-threading; lower syscall latency.
- **Cons**: requires `/dev/kvm`; needs kernel headers at build time; slightly more complex setup.

The architectural diagram from the [gVisor design docs](https://gvisor.dev/docs/architecture_guide/) shows this clearly: in both modes, the *Sentry* is the boundary. Nothing inside the sandbox touches the host kernel except through a tiny allowlist of safe operations.

## Inside the Sentry

The sentry is the heart of gVisor. It is written primarily in Go — a deliberate choice because memory-safe languages matter when you are deliberately accepting untrusted code paths. The sentry is organized into packages that mirror real kernel subsystems.

### The Syscall Layer

When the trapped application issues `read(fd, buf, n)`, the sentry:

1. Validates the arguments against the application's seccomp policy.
2. Resolves the file descriptor through the sentry's file-description table.
3. Calls into the appropriate Go package (`fs`, `net`, `mem`, etc.) to actually satisfy the request.

The implementation lives in [`pkg/sentry/syscalls`](https://github.com/google/gvisor/tree/master/pkg/sentry/syscalls) and is genuinely readable — it looks like a small kernel source tree, but in Go.

### The File System Layer

Filesystem operations are handled by `pkg/sentry/fs`, which implements `inode`, `dentry`, and `mount` semantics from scratch. Importantly, the sentry does not just proxy `openat` to the host; it implements a virtual filesystem (VFS) tree where each path is resolved against its own dentry cache.

When the sentry needs real data, it asks the **gofer**. The gofer is a small host-side process whose only job is to perform the actual `open()`, `read()`, and `stat()` against the host filesystem and reply to the sentry over a socket (in ptrace mode) or shared memory (in KVM mode). This split keeps the sentry itself from needing host privileges for filesystem I/O.

```text
+-------------------+        +-------------------+        +-------------------+
|  Application      |  -->   |     Sentry        |  -->   |      Gofer        |
|  (sandboxed)      |  <--   |  (user-space      |  <--   |  (host fs proxy)  |
|                   |        |   kernel in Go)   |        |                   |
+-------------------+        +-------------------+        +-------------------+
```

### Networking

Networking follows the same pattern. The sentry implements an `AF_INET`, `AF_UNIX`, and `AF_PACKET` stack in `pkg/sentry/network`, including TCP state machine handling. Outbound packets are forwarded to a netstack that ultimately translates them into real socket operations performed by the gofer over a `TAP` device or a proxy socket.

This is why gVisor can be paired with [`runsc` and Docker's `--security-opt seccomp=unconfined`](https://gvisor.dev/docs/user_guide/quick_start/docker/) — the seccomp profile can be relatively permissive because the application is not actually executing raw syscalls against the host kernel.

### Memory Management

Memory in the sentry is interesting. The application believes it has a flat virtual address space backed by Go-managed memory. The sentry maps the application's stack, heap, and threads into a `kernel.Thread` abstraction, with the sentry acting as the page fault handler in KVM mode. This is described in detail in [The gVisor Architecture Guide](https://gvisor.dev/docs/architecture_guide/).

## Patterns in Production

### Docker Integration

The simplest deployment is `runsc` registered as a Docker runtime. After following the [Docker install steps](https://gvisor.dev/docs/user_guide/quick_start/docker/), you launch a sandboxed container with:

```bash
docker run --runtime=runsc -d nginx:alpine
```

You can confirm you're running under gVisor by exec'ing in and looking for the truncated `/proc`:

```bash
docker exec $(docker ps -q --filter ancestor=nginx:alpine) cat /proc/version
# Will report something like "4.4.0.x-gvisor"
```

### Kubernetes Pod Sandboxing

For multi-tenant clusters, gVisor's real value is in pod-level sandboxing. A common pattern is to run untrusted or third-party workloads under `runsc` while keeping trusted services on the default `runc`:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: tenant-workload
spec:
  runtimeClassName: gvisor
  containers:
  - name: app
    image: registry.example.com/tenant/image:1.2.3
    resources:
      requests:
        memory: "512Mi"
        cpu: "500m"
```

The `RuntimeClass` is defined once on the cluster, and node-level configuration chooses the `runsc` binary plus the KVM or ptrace configuration. The [gVisor Kubernetes guide](https://gvisor.dev/docs/user_guide/quick_start/kubernetes/) walks through the `RuntimeClass` manifest.

### Failure Modes Worth Knowing

In production, the failure modes people hit most often are:

- **Syscall-heavy workloads** slow down noticeably under ptrace. Switching to KVM often recovers most of the throughput.
- **Inotify and fanotify are partially supported**, so tools that rely on filesystem watchers (some build systems, some config reloaders) need careful testing.
- **Kernel features like io_uring, BPF, and certain ioctl families are restricted.** The compatibility matrix lives in [gvisor.dev/docs](https://gvisor.dev/docs/user_guide/compatibility/).
- **Memory overhead** is real: the sentry and gofer each have a Go runtime footprint, so a 64 MB container will typically need 120–180 MB of overhead in practice.

## Benchmarks: What to Expect

Numbers vary by workload, but a few patterns are consistent across the [gVisor benchmarks](https://gvisor.dev/docs/architecture_guide/performance/) and community reports:

- **CPU-bound workloads** run within roughly 10–20% of host performance under KVM.
- **Syscall-bound workloads** (e.g., high-frequency database calls) can be 1.5–3× slower than `runc` under ptrace.
- **Cold start** is slower than `runc` (hundreds of milliseconds) but much faster than full VMs.
- **Memory overhead** per container is typically 50–100 MB for the sentry plus gofer.

For workloads that are network- or disk-bound at the container boundary, gVisor overhead is often negligible. For workloads that pound on the syscall interface — high-QPS services, certain database engines — the overhead is real and measurable.

## Security Model: What Actually Gets Hardened

The value proposition of gVisor is the security boundary, so it's worth being precise about what is and isn't hardened:

- **Application → host kernel**: most syscalls are intercepted; the application sees a re-implemented kernel.
- **Application → other containers**: standard Linux namespaces still apply.
- **Sentry → host kernel**: the sentry only uses a small, audited set of syscalls, enforced by a strict seccomp profile generated at build time. See [pkg/sentry/syscalls/linux64.go](https://github.com/google/gvisor/blob/master/pkg/sentry/syscalls/linux64.go) for the full set.
- **Gofer → host kernel**: the gofer is narrowly privileged to perform only the file and network operations the sentry requests.

The [gVisor security model document](https://gvisor.dev/docs/architecture_guide/security/) explains that the goal is *defense in depth*: even if a vulnerability exists in the sentry, the host kernel exposure is minimized because the sentry itself runs under a tight seccomp filter.

## Key Takeaways

- gVisor runs a Go-based reimplementation of the Linux kernel (the *sentry*) between containerized applications and the host kernel.
- Two backends exist: `ptrace` for portability and `KVM` for performance; most production users should prefer KVM.
- Filesystem and network I/O are split out to a small *gofer* process, keeping the sentry's host privileges minimal.
- Expect real but manageable overhead: 10–20% for CPU-bound work in KVM mode, more for syscall-heavy workloads in ptrace mode.
- It's a strong fit for multi-tenant Kubernetes clusters and untrusted workloads; it's less of a fit for applications that rely on io_uring, BPF, or kernel-bypass networking.

## Further Reading

- [gVisor Architecture Guide](https://gvisor.dev/docs/architecture_guide/)
- [Open-sourcing gVisor — Google Cloud Blog](https://cloudplatform.googleblog.com/2018/05/open-sourcing-gvisor-sandbox-container-tools.html)
- [gVisor on GitHub](https://github.com/google/gvisor)
- [Quick start with Docker](https://gvisor.dev/docs/user_guide/quick_start/docker/)
- [gVisor performance benchmarks](https://gvisor.dev/docs/architecture_guide/performance/)
- [ptrace(2) — Linux man pages](https://man7.org/linux/man-pages/man2/ptrace.2)