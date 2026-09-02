---
title: "Mastering io_uring vs epoll: A Deep Dive into Linux Async I/O Architectures"
date: "2026-09-02T06:00:57.121"
draft: false
tags: ["linux", "io_uring", "epoll", "async-io", "systems-programming", "performance"]
description: "A working engineer's deep dive into io_uring and epoll: how they differ under the hood, when to pick which, and what production systems reveal about each."
summary: "Compare Linux's two dominant async I/O architectures, io_uring and epoll, with kernel internals, real benchmarks, and patterns drawn from production systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-mastering-io_uring-vs-epoll-a-deep-dive-into-linux-async-io-architectures.svg"
  alt: "Layered diagram of kernel submission and completion rings for async I/O."
  caption: ""
  relative: false
---

> **TL;DR** — epoll is a readiness-notification API that scales to millions of file descriptors but still requires one syscall per I/O operation, while io_uring is a true asynchronous submission/completion model that batches work and eliminates most syscalls. The right choice depends on your workload: epoll wins for connection-heavy servers with light per-connection I/O, io_uring wins for I/O-heavy paths where syscall overhead dominates.

## Why Linux Async I/O Still Matters in 2026

After two decades of evolution, Linux still offers two fundamentally different mental models for handling I/O without blocking a thread. The first, `epoll`, treats the kernel as a notification service: "tell me when this socket is readable, and I'll come back to read it." The second, `io_uring`, treats the kernel as a work queue: "here are 10,000 operations, do them, and ring the doorbell when you're done." They aren't just different APIs — they encode different assumptions about the cost of a syscall, the role of userspace, and what a "thread" is for.

This matters because the bottlenecks have moved. In 2003 when `epoll` arrived, the cost was waking waiters and walking descriptor lists. Today, on a 128-core server with DPDK, SPDK, and NVMe, the cost is often the syscall itself, the cache line crossing between ring buffers, and the lock contention on shared submission queues. `io_uring` was designed explicitly to attack these new bottlenecks — and as a result, the choice between the two has become a real architectural decision rather than a stylistic one.

## A Quick Refresher on epoll

`epoll` is the scalable variant of the older `select`/`poll` interfaces. The model is straightforward: you register file descriptors with an `epoll` instance, then ask the kernel, "which of these descriptors are ready for I/O right now?" The kernel maintains a red-black tree of watched fds and a ready list. After `epoll_wait` returns, you perform the actual `read`/`write`/`accept` calls yourself.

The advantage is that `epoll_wait` only reports descriptors that are actually ready. Even with 100,000 sockets in the watch set, the cost of a single round trip is proportional to the number of *ready* descriptors, not the size of the set. This is why every high-performance TCP server on Linux — NGINX, Envoy, HAProxy, Redis — uses `epoll` (or `io_uring` now) as its multiplexer.

The disadvantage is structural: each I/O operation is still a separate syscall. On a fast NVMe device doing 32 KB reads, you can issue 5 million I/Os per second, which is roughly 1.6 billion syscalls per minute. At that rate, the cost of transitioning to kernel mode — even at ~200 ns per syscall — starts to dominate the actual work being done.

## How io_uring Changes the Model

`io_uring`, merged in Linux 5.1 (2019) and substantially expanded since, decouples submission from completion using two shared ring buffers between userspace and kernel:

- **Submission Queue (SQ)**: userspace writes Submission Queue Entries (SQEs) describing an operation (read, write, accept, openat, splice, etc.) and updates a tail pointer.
- **Completion Queue (CQ)**: the kernel writes Completion Queue Entries (CQEs) when operations finish, and userspace updates a head pointer.

When userspace wants to submit work, it does so by writing to the SQ and then either (a) executing a single `io_uring_enter` syscall to give the kernel a kick, or (b) using **SQ polling (SQPOLL)**, where a kernel thread polls the SQ without any syscall at all. When using `IO_URING_SETUP_SQPOLL` with the `IORING_SETUP_SQ_AFFINITY` flag, the kernel can pin a polling thread to a specific CPU and even batch completions back to userspace through shared memory.

This gives you three operating modes with different tradeoffs:

| Mode | Syscall cost | Latency | CPU overhead |
|------|--------------|---------|--------------|
| Standard (kernel-driven) | 1 syscall per batch | Lowest predictability | Lowest kernel footprint |
| SQPOLL | 0 syscalls for submission | Slightly higher minimum latency | Always-on polling thread |
| IOPOLL | 0 syscalls, polls device | Best for fast storage | Burns CPU on idle devices |

The third mode — `IOPOLL` — is what makes `io_uring` interesting for storage stacks: it lets a userspace thread poll a completion ring without ever notifying the kernel, similar to how SPDK and DPDK work for network and storage.

### The Building Blocks: Submission and Completion

A typical `io_uring` read flow looks like this in C:

```c
struct io_uring ring;
io_uring_queue_init(32, &ring, 0);

struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_read(sqe, fd, buf, len, offset);
sqe->user_data = request_id;

io_uring_submit(&ring);

struct io_uring_cqe *cqe;
io_uring_wait_cqe(&ring, &cqe);
process_completion(cqe->res, cqe->user_data);
io_uring_cqe_seen(&ring, cqe);
```

There is no `epoll_wait`, no separate `read` syscall — the kernel performs the I/O based on the SQE and posts a CQE. The `user_data` field is your private tag that comes back in the completion, so you can correlate completions with the requests you issued.

## Performance: What the Numbers Actually Show

Benchmarks in this space are notoriously easy to fudge, but several large-scale studies have held up under scrutiny:

- **Jens Axboe (the original author of `io_uring`)** has published repeatable results showing [8x throughput improvement over `libaio` for direct I/O](https://github.com/axboe/liburing/wiki/Benchmarks) on NVMe devices, with the gap widening as queue depth increases.
- **Facebook/Meta's katran load balancer**, when ported from `epoll` to `io_uring`, saw a measurable reduction in P99 latency under load — published in [their engineering blog on kernel-bypass work](https://engineering.fb.com/2022/08/22/building-metas-infrastructure-for-llama/).
- **Ceph's bluestore** added `io_uring` support as an alternative to `libaio` and reported improvements in tail latency for small random writes, as documented in the [Ceph Quincy release notes](https://docs.ceph.com/en/quincy/releases/quincy/).

The key insight is not raw throughput — both APIs can saturate modern devices. It's the *shape* of the latency distribution. `io_uring` tends to produce tighter, more predictable P99/P999 latencies under high concurrency because the work is batched and the kernel can re-order operations for better device utilization.

That said, the syscall overhead story isn't always as dramatic as it sounds. Modern Linux (5.15+) has vDSO-based optimizations and a fast path for common syscalls, so a single `read()` is closer to 100–200 ns than the 1+ μs that older literature suggests. The 8x improvements show up when the syscall rate is the actual bottleneck — think 10+ million ops/sec — not for typical web request/response patterns.

## Patterns in Production

Three production patterns are worth knowing in detail.

### 1. Connection-Multiplexed Servers (epoll's Home Turf)

For a server like NGINX, Envoy, or a custom TCP proxy handling 100k+ connections where most of the time is spent waiting for network data, `epoll` is still the right call. The work per event is large (parsing, business logic, response generation), and the cost of one syscall per ready fd is negligible compared to the application code that runs afterward. `io_uring` can also handle this — newer versions of NGINX support it for accept and read — but the gains are modest, in the single-digit percent range.

### 2. Storage Engines and Database Backends (io_uring's Sweet Spot)

Postgres, RocksDB, and ClickHouse are exactly the workloads `io_uring` was designed for: many small I/Os, syscall overhead visible in profiles, and reordering opportunities the kernel can exploit. The pattern is to use a single submission thread feeding a ring that multiple worker threads consume completions from. This is also where `IOPOLL` and registered buffers (`io_uring_register_buffers`) shine — registered buffers avoid the page pinning/unpinning that happens on every `read`/`write` syscall.

### 3. Hybrid Designs

Some systems use both. A typical pattern: `epoll` for accepting connections and reading requests (low rate, latency-sensitive), then `io_uring` for the actual database or storage I/O (high rate, throughput-sensitive). This is what [ScyllaDB's Seastar framework](https://www.scylladb.com/2018/02/13/seastar-the-future-of-database-infrastructure/) does in spirit — a shared-nothing reactor model where each shard handles its own I/O using whatever API fits best. Rust async runtimes like Tokio and Monoio are converging on this model too, with Monoio being the most aggressive `io_uring`-first design I've seen.

## Architectural Tradeoffs: When to Pick Which

The decision tree I've settled on after watching several large systems migrate (and a few migrate back) looks like this:

**Choose `epoll` when:**
- Your connection count is high (10k+) but per-connection I/O is light.
- Your application code is more expensive than the syscall overhead.
- You need to support older kernels or want maximum portability across BSDs.
- You need well-understood kernel behavior — `epoll` has been stable for 20 years.

**Choose `io_uring` when:**
- You issue more than ~500k I/O operations per second and profiling shows syscalls in the hot path.
- You have a tight latency budget (microseconds matter) and need P99 predictability.
- Your I/O pattern is amenable to reordering (random reads, async writes).
- You can target Linux 5.10+ (released late 2020) and don't need BSD/macOS support.

**Avoid `io_uring` for:**
- New code that you can't test on multiple kernel versions. The API has changed significantly between 5.1, 5.6, 5.11, and 5.19, and old code that uses deprecated opcodes (like `IORING_OP_READ` without `IOSQE_FIXED_FILE`) will silently break or have security implications.
- Anything in a multi-tenant container environment without recent enough kernel support. There were several CVEs (including [CVE-2022-1043](https://nvd.nist.gov/vuln/detail/CVE-2022-1043)) related to `io_uring` permission issues in unprivileged containers, and some distros still disable unprivileged `io_uring` by default.

## Kernel Internals: What Makes io_uring Fast

The performance story is more nuanced than "fewer syscalls." The kernel-side implementation is designed around three principles:

1. **Lock-free fast paths where possible.** The SQ and CQ use single-producer/single-consumer rings by default, so submission and completion can run on different cores without lock contention.

2. **Task work and inline completion.** When you submit a request, the kernel can either complete it inline (if the data is already in the page cache) or queue it for asynchronous execution. Inline completion means the CQE can appear in the same ring cycle as the SQE, with no context switch at all.

3. **Registered resources.** By calling `io_uring_register_files` and `io_uring_register_buffers`, you can pre-pin file descriptors and memory regions. The kernel keeps references to them in a structure it can access without going through the file descriptor table or the MMU's permission checks. For long-running processes, this is a meaningful win.

The completion ring is the part most newcomers misunderstand. It's not a notification — it's a *queue*. If you submit 10,000 reads and only consume completions, those completions sit in the CQ until you reap them. This means you can decouple submission rate from consumption rate, which is exactly what you want when one thread produces and many threads consume.

## The Security Reality Check

It's tempting to write only about performance, but `io_uring` has had a rough security history. Between 2022 and 2024, [Google's Project Zero](https://googleprojectzero.blogspot.com/) and various kernel developers disclosed multiple privilege escalation vulnerabilities through the `io_uring` syscall. In response, several distributions now restrict or disable unprivileged `io_uring`:

- Ubuntu 22.04+ requires the `kernel.unprivileged_userns_clone` and `io_uring_disabled` sysctls to be explicitly enabled for non-root users.
- ChromeOS and Android disable `io_uring` entirely.
- Some Kubernetes distributions run with seccomp filters that block the `io_uring_setup` and `io_uring_enter` syscalls.

This isn't a reason to avoid `io_uring` for server-side code that runs as root, but it is a reason to be explicit about which kernel version you're targeting and to test your code on the kernels your fleet actually runs.

## A Pragmatic Adoption Path

If you're evaluating `io_uring` for an existing `epoll`-based system, the migration I'd recommend:

1. **Start with `liburing` from Jens Axboe.** It wraps the raw syscall and gives you portable behavior across kernel versions. The [liburing repository](https://github.com/axboe/liburing) has examples for every operation type.

2. **Replace your hottest single-operation type first.** If you're doing 10 million small reads per second, replace just those reads with `io_uring` and leave the rest on `epoll`. Measure end-to-end latency and throughput.

3. **Use registered buffers and files from day one.** Unregistered `io_uring` doesn't show much benefit over `epoll` for short-lived operations.

4. **Plan for kernel-version-aware code paths.** Use `uname()` at startup to detect your minimum kernel version and fall back to `epoll` if it's too old. Treat the `io_uring` path as a feature flag, not a hard dependency.

5. **Benchmark at production scale, not in your laptop.** The `io_uring` advantage grows with concurrency. A benchmark on a 4-core dev box often shows `epoll` winning because the contention and queue depth simply aren't there.

## Key Takeaways

- `epoll` is a notification API: you ask which fds are ready, then perform the I/O. It scales to millions of fds and is the right choice for connection-heavy servers with light per-connection work.
- `io_uring` is a work-queue API: you submit operations to a ring buffer and reap completions later. It eliminates most syscalls and is the right choice for I/O-heavy paths where syscall overhead is visible in profiles.
- The performance gap between them is workload-dependent. For web-style request/response, the gap is small. For storage engines and high-QPS proxies, `io_uring` can deliver 2–8x throughput improvements and tighter tail latencies.
- `io_uring` has had real security issues; pin to a current LTS kernel and restrict unprivileged access where multi-tenant isolation matters.
- Migration is best done incrementally — replace the hottest operation type first, benchmark at production scale, and keep `epoll` as a fallback for older kernels.

## Further Reading

- [The io_uring man page (latest)](https://man.archlinux.org/man/io_uring.7) — the canonical reference for opcodes, flags, and ring management.
- [Efficient IO with io_uring (kernel docs)](https://kernel.dk/io_uring.pdf) — Jens Axboe's design document covering the original motivation and architecture.
- [liburing examples repository](https://github.com/axboe/liburing/tree/master/examples) — working C code for every operation type, kept in sync with the latest kernel features.
- [Lord of the io_uring (LWN series)](https://lwn.net/Articles/810414/) — Jonathan Corbet's multi-part deep dive into `io_uring` internals and evolution.
- [Linux Kernel epoll(7) man page](https://man7.org/linux/man-pages/man7/epoll.7.html) — the authoritative reference for `epoll` semantics, edge-triggered vs level-triggered, and event semantics.