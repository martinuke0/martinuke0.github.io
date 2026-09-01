---
title: "Architecting Async I/O with io_uring vs. epoll: A Deep Dive into Linux Performance Models"
date: "2026-09-01T21:00:33.953"
draft: false
tags: ["io_uring", "epoll", "linux-kernel", "async-io", "systems-performance"]
description: "A deep dive into io_uring vs epoll for Linux async I/O: submission queues, kernel bypasses, syscalls, and which model fits your workload."
summary: "Compare io_uring and epoll as Linux async I/O architectures, covering kernel internals, syscall costs, and the production patterns where each one wins."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-architecting-async-io-with-io_uring-vs-epoll-a-deep-dive-into-linux-performance-models.svg"
  alt: "Layered diagram contrasting epoll's readiness-based loop with io_uring's submission and completion queues."
  caption: ""
  relative: false
---

> **TL;DR** — `epoll` is a *readiness notification* model: the kernel tells you a fd is ready, then you issue syscalls. `io_uring` is a *completion-based* model: you describe the entire I/O operation in shared ring buffers and reap results asynchronously. Both are async, but they sit at very different points on the syscall, latency, and complexity curve — and the right choice depends on whether your bottleneck is connection count, per-op overhead, or storage latency.

## Why Async I/O Architecture Matters

Modern servers spend most of their CPU time waiting, not computing. A web proxy holding 100k idle keep-alive connections, a database answering point queries on NVMe, a log shipper tailing journals — each has a different I/O profile, and each pays a different tax for the wrong abstraction. The choice between `epoll` and `io_uring` is not a religious war; it is an architecture decision with measurable consequences in CPU per request, tail latency, and code complexity.

Linux has spent fifteen years evolving its async I/O story. `epoll` arrived in 2.6, scaled past `select` and `poll`, and became the default event loop for [NGINX, Redis, and Envoy](https://www.nginx.com/blog/thread-pools-boost-performance-9x/). `io_uring` shipped in 5.1 (2019), matured through 5.11+, and now powers [Caddy, ScyllaDB, and the Rust Tokio runtime](https://github.com/tokio-rs/tokio/discussions/5432). Understanding both is non-optional for anyone building high-throughput services on Linux.

## epoll: The Readiness Model

### How the Kernel Thinks About epoll

`epoll` is built around three syscalls: [`epoll_create1`](https://man7.org/linux/man-pages/man2/epoll_create.2.html), `epoll_ctl`, and `epoll_wait`. You register file descriptors of interest, then block until one or more become "ready." Readiness has a precise meaning per fd type:

- A TCP socket is ready when the kernel has data in the receive buffer (read-ready) or free space in the send buffer (write-ready).
- An eventfd is ready when its counter is non-zero.
- A timerfd is ready when its expiration fires.

Crucially, `epoll_wait` does **not** perform I/O. It returns, you loop over the ready fds, and you issue `read`, `write`, `accept`, etc. yourself.

```c
int epfd = epoll_create1(EPOLL_CLOEXEC);
struct epoll_event ev = {.events = EPOLLIN, .data.fd = listen_fd};
epoll_ctl(epfd, EPOLL_CTL_ADD, listen_fd, &ev);

struct epoll_event events[MAX_EVENTS];
for (;;) {
    int n = epoll_wait(epfd, events, MAX_EVENTS, -1);
    for (int i = 0; i < n; i++) {
        if (events[i].data.fd == listen_fd) {
            int cfd = accept4(listen_fd, NULL, NULL, SOCK_NONBLOCK);
            epoll_ctl(epfd, EPOLL_CTL_ADD, cfd, &(struct epoll_event){.events = EPOLLIN, .data.fd = cfd});
        } else {
            handle_client(events[i].data.fd);
        }
    }
}
```

### Strengths in Production

The model is conceptually clean and battle-tested. It scales to hundreds of thousands of fds on a single thread because the kernel uses a red-black tree for the interest set and a linked list for ready events. There is no shared memory with userspace, no ring buffer to mmap, no synchronization primitives beyond what your event loop already uses.

Where `epoll` shines:

- **Proxy and gateway workloads** dominated by many short-lived sockets (NGINX, HAProxy, Envoy).
- **Latency-sensitive request/response** servers where the round-trip is dominated by network RTT, not syscall overhead.
- **Heterogeneous fd types** — mixing sockets, timers, signals, and eventfd is straightforward.

### Where It Hurts

Every `read` or `write` is a syscall. On a quiescent connection you might do `epoll_wait → read → epoll_wait → read` in a tight loop, paying two syscalls per event. Each syscall crosses the kernel/userspace boundary (typically 100–300 ns on modern hardware), causes a TLB flush, and serializes through the vDSO entry path. Multiply by 1M ops/sec and you are spending milliseconds per second of CPU in transitions alone.

For disk I/O specifically, `epoll` only covers the network side cleanly. You can wire regular file descriptors into `epoll` for readiness, but the semantics are [incomplete and historically unreliable](https://lwn.net/Articles/520198/). Real async disk I/O under `epoll` historically required `O_DIRECT` + `libaio`, which is a separate stack with its own quirks.

## io_uring: The Completion Model

### Submission and Completion Queues

`io_uring` flips the model. Instead of asking "is this fd ready?" you submit a fully-formed operation description — a [`struct io_uring_sqe`](https://man7.org/linux/man-pages/man3/io_uring_get_sqe.3.html) — and reap the result later from a completion queue entry ([`struct io_uring_cqe`](https://man7.org/linux/man-pages/man3/io_uring_peek_cqe.3.html)). Both queues are shared ring buffers mmap'd between kernel and userspace. The producer and consumer sides are lock-free for a single submitter.

```c
struct io_uring ring;
io_uring_queue_init(256, &ring, 0);

struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_read(sqe, fd, buf, len, 0);
sqe->user_data = 42;
io_uring_submit(&ring);

struct io_uring_cqe *cqe;
io_uring_wait_cqe(&ring, &cqe);
// ... use result ...
io_uring_cqe_seen(&ring, cqe);
```

This is a **completion-based** model: the kernel writes a result entry telling you "read of 1024 bytes from fd 7 returned 1024," or "write failed with -EAGAIN." You never ask "is it ready?" You assume the operation has consequences and react to outcomes.

### Why This Is Faster

Three architectural wins:

1. **Zero syscall fast path.** With `SQPOLL`, the kernel spins a thread polling the submission queue. Userspace writes entries and the kernel picks them up without any syscall at all. Even without `SQPOLL`, batching 64 operations into a single `io_uring_submit()` is one syscall per batch, not per op.
2. **Registered resources.** Files, buffers, and even personality contexts can be registered once and referenced by index in subsequent SQEs. `io_uring_register_files()` skips the fd lookup; `io_uring_register_buffers()` skips `get_user_pages()`.
3. **True async disk I/O.** Read, write, fsync, accept, connect, send, recv, openat, close, timeout, cancel — all are first-class async ops. There is no `O_DIRECT` or `libaio` needed.

Benchmarks by the kernel developers and independent testers consistently show [2–10× throughput improvements on disk-heavy workloads](https://github.com/axboe/liburing/wiki/Benchmarks) compared to sync I/O or `libaio`, and substantial wins over `epoll` + `read()` for high-frequency ops.

### The Cost of Power

`io_uring` is more complex on every axis:

- **Memory ordering.** SQE/CQE rings use explicit memory barriers ([`io_uring_sqe_set_flags()`](https://man7.org/linux/man-pages/man3/io_uring_sqe_set_flags.3.html), `smp_wmb/smp_rmb` internally). Single-submitter single-receiver is lock-free; multiple threads need careful coordination.
- **Resource registration lifetime.** Registered files and buffers stay pinned in kernel memory. Registering millions of buffers is not free; the [upstream limit is 1M by default](https://github.com/tokio-rs/io-uring/issues/187).
- **Security surface.** Early versions exposed privilege escalation vectors, prompting [kernel lockdown patches](https://lwn.net/Articles/820555/). Many distros now restrict `io_uring` for unprivileged users (e.g., Ubuntu's `kernel.io_uring_disabled` sysctl).
- **Error handling is richer.** A single `read` SQE can complete with `EAGAIN`, `EBADF`, short read, EOF, or success-with-different-bytes-transferred. Your code must handle all of these distinctly.

## Architecture Patterns in Production

### Pattern 1: epoll + thread pool for mixed I/O

A common production pattern in legacy C++ servers is to use `epoll` for network sockets and offload disk I/O to a thread pool using `libaio` or synchronous `preadv`. The event loop thread stays free to multiplex millions of sockets; worker threads block on disk. This is how [Linkerd 1.x and older NGINX worked](https://www.nginx.com/blog/thread-pools-boost-performance-9x/), and it remains a sensible choice when disk I/O is a small fraction of total work.

### Pattern 2: io_uring for storage-centric services

Database engines, log shippers, and object stores are dominated by disk latency. [ScyllaDB rewrote its storage layer on io_uring](https://www.scylladb.com/2022/01/12/io_uring-in-scylladb/) and reported measurable tail-latency reductions. RocksDB has an [experimental IO_URING env](https://github.com/facebook/rocksdb/wiki/IO-uring-Env). QEMU added io_uring support for [virtio-blk in 7.1](https://www.qemu.org/2022/08/whats-new-qemu-7-1/). The pattern: one submission queue, dedicated worker thread, registered buffers for hot pages.

### Pattern 3: io_uring with SQPOLL for ultra-low latency

With `IORING_SETUP_SQPOLL`, a kernel thread spins polling your SQ. The cost is one extra kernel thread per ring and slightly higher idle CPU. The benefit is no `io_uring_enter()` syscall even for the submit barrier — useful in HFT, ad bidding, and any workload where 1–2 µs matters. This is also where the security tightening bites: [SQPOLL requires `CAP_SYS_ADMIN` or the `kernel.unprivileged_io_uring_sqpoll` sysctl](https://docs.kernel.io/admin-guide/sysctl/kernel.html#unprivileged-io-uring-sqpoll) on most distros.

### Pattern 4: epoll with io_uring as the disk backend

You can run `epoll` for the network side and use `io_uring` purely for disk operations on the same threads. Tokio's [tokio-uring crate](https://github.com/tokio-rs/tokio-uring) supports this hybrid: the runtime handles sockets via `epoll`, but `read`, `write`, and `fsync` on file descriptors go through `io_uring`. You get the maturity of `epoll` for sockets and the kernel-bypass benefits of `io_uring` for storage without rewriting your reactor.

## Decision Framework

### Choose epoll when:

- Your workload is **socket-dominated**: web servers, proxies, RPC frameworks, message brokers with persistent connections.
- You need **broad compatibility**: every Linux from 3.10 onward, every language runtime, no security restrictions.
- Your team values **code simplicity** over peak throughput.
- I/O is **RTT-bound** (sub-millisecond network latency to remote services) — syscall cost is noise relative to network round-trip.

### Choose io_uring when:

- Disk I/O is on the **critical path**: databases, log indexes, object stores, anything touching NVMe or high-latency storage.
- You operate at **>100k ops/sec** where syscall overhead starts to dominate CPU.
- You can target **Linux 5.11+ or 5.15+** and accept the version floor.
- You have the **engineering capacity** to handle the complexity: registered buffers, SQE lifetime, CQE error paths.

### Hybrid when:

- Mixed workload with a non-trivial fraction of both. Tokio's hybrid or libuv + liburing give you both without forcing a choice.

## Benchmarks That Matter

Vendor benchmarks are notoriously self-serving. The independent benchmarks that have aged well:

- [Shuveb Cao's 2021 comparison](https://github.com/shuveb/cio-the-era-of-reusing-virtual-memory) showed io_uring handles ~1.2M small IOs/sec vs epoll's ~700k on a tuned setup.
- [Jens Axboe's fio benchmarks](https://github.com/axboe/fio/blob/master/engines/io_uring.c) consistently show io_uring matching or exceeding libaio for NVMe random read workloads, with lower CPU utilization.
- [Cloudflare's HTTP/3 work](https://blog.cloudflare.com/) discusses how their QUIC stack uses epoll-driven sockets but offloads to thread pools for disk-backed caching.

The honest summary: for **socket-heavy workloads**, the gap between `epoll` and `io_uring` is usually within 20%. For **disk-heavy workloads**, `io_uring` routinely wins by 2–4× and occasionally by 10×.

## Operational Gotchas

Both APIs have sharp edges that only show up in production:

- **epoll level-triggered vs edge-triggered.** EPOLLT (level-triggered) requires you to drain the fd fully; EPOLLET (edge-triggered) requires non-blocking I/O. Mixing the two semantics in one loop is a classic source of stuck connections.
- **io_uring CQE ordering.** Completions are not strictly ordered with submissions in the general case. If you submit reads A then B, you might reap B first. Code that assumes ordering will have race conditions.
- **io_uring cancellation.** `IORING_OP_ASYNC_CANCEL` exists but is subtle: cancel-by-sqe-index, cancel-by-user-data, and cancel-by-fd all behave differently. Mid-operation cancellation can leak resources if not handled carefully.
- **Resource registration limits.** Pinning millions of user pages via `io_uring_register_buffers` can fragment memory and cause reclaim pressure. Track registration count and unregister idle buffers.
- **Security policy.** Some hardened distros disable `io_uring` entirely (e.g., [ChromeOS and certain Android builds](https://security.googleblog.com/2023/06/disabling-io_uring-in-android-and-chromeos.html)). Have a fallback path if your service might run in such environments.

## Key Takeaways

- **`epoll` is a readiness notification system; `io_uring` is a completion-based I/O submission system.** They answer different questions.
- **Per-syscall overhead is the core tradeoff.** `epoll` issues 1 syscall per I/O op; `io_uring` can issue 1 syscall per batch or zero with `SQPOLL`.
- **Disk I/O favors `io_uring`; socket I/O is closer to a wash.** Pick based on your dominant I/O type, not on hype.
- **Both APIs have sharp edges.** ET vs LT semantics for epoll; CQE ordering, registration lifetime, and security policy for io_uring.
- **Hybrid architectures are a legitimate production choice.** Tokio's hybrid reactor proves you don't have to pick one.
- **Benchmark in your own workload.** The 2–10× wins in the literature assume disk-bound conditions that may not match your service.

## Further Reading

- [io_uring official documentation and man pages](https://man7.org/linux/man-pages/man7/io_uring.7.html)
- [Effective IO_uring on Large-Scale Network Workloads](https://www.scylladb.com/2022/01/12/io_uring-in-scylladb/) — ScyllaDB's production deployment notes
- [Lord of the io_uring — Linux Foundation event recording](https://www.youtube.com/watch?v=f-PnCsEkL4E) — Jens Axboe (kernel maintainer) walkthrough
- [The epoll man page](https://man7.org/linux/man-pages/man2/epoll_wait.2.html) — canonical reference for the readiness model
- [LWN: The rapid growth of io_uring](https://lwn.net/Articles/810414/) — historical and architectural deep dive
- [Tokio: io_uring support proposal](https://github.com/tokio-rs/tokio/discussions/5432) — design rationale for the hybrid reactor