---
title: "Deep Dive into Linux I/O Evolution: From epoll Mastery to io_uring Architecture and Performance"
date: "2026-05-26T04:00:41.895"
draft: false
tags: ["linux", "io", "epoll", "io_uring", "performance"]
description: "Explore how Linux I/O has evolved from epoll to io_uring, covering architecture, real‑world patterns, and performance numbers for production engineers."
summary: "A practical walkthrough of epoll’s design, its limits, and how io_uring reshapes asynchronous I/O for modern cloud workloads."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-26-deep-dive-into-linux-io-evolution-from-epoll-mastery-to-io_uring-architecture-and-performance.svg"
  alt: "Diagram of epoll vs io_uring architecture."
  caption: ""
  relative: false
---

> **TL;DR** — epoll remains a solid edge‑triggered poller for simple event loops, but its kernel‑user handshakes limit scalability. io_uring swaps the poller for a submission‑completion queue pair, slashing syscalls and latency, and is now the recommended path for high‑throughput services.

Linux networking and storage workloads have outgrown the original asynchronous APIs that were baked into the kernel a decade ago. While epoll has powered everything from Nginx to Redis, the rising demand for sub‑microsecond latency and millions of concurrent connections pushes engineers toward the newer io_uring interface. This article dissects both APIs, compares their internals, and shows how production teams can migrate safely while extracting measurable performance gains.

## The I/O Challenge in Modern Services

### Why Asynchronous I/O Matters

* **Connection explosion** – Cloud‑native microservices routinely handle 100 k+ concurrent sockets per node.
* **Latency budgets** – Front‑end latency budgets of <5 ms leave little room for kernel‑user round‑trips.
* **CPU efficiency** – Busy‑wait loops waste cores; efficient event delivery lets the scheduler keep cores busy with useful work.

In a typical high‑traffic service, each request triggers a read from the network stack, a lookup in a cache, maybe a DB query, and a write back to the client. If each of those steps incurs even one extra syscall, the CPU overhead balloons. The kernel’s role is to surface readiness events with as few transitions as possible—this is where epoll and io_uring diverge.

## epoll: The Classic Edge‑Triggered API

### Architecture of epoll

epoll is built around a **file descriptor** that represents an interest set. Applications register interest (`EPOLLIN`, `EPOLLOUT`, etc.) on sockets or file descriptors, then block on `epoll_wait`. Internally, the kernel maintains two main structures:

1. **Red‑Black Tree** – Stores the user‑registered interest set for O(log n) lookups.
2. **Ready List** – Populated by the networking stack when an event becomes ready.

When `epoll_wait` returns, the kernel copies the ready list into user‑space, and the process iterates over the events. The flow looks like this:

```c
int efd = epoll_create1(0);
struct epoll_event ev = {.events = EPOLLIN, .data.fd = listen_fd};
epoll_ctl(efd, EPOLL_CTL_ADD, listen_fd, &ev);

while (1) {
    struct epoll_event events[64];
    int n = epoll_wait(efd, events, 64, -1);
    for (int i = 0; i < n; ++i) {
        handle_event(events[i].data.fd);
    }
}
```

### Strengths

| Feature | What it Gives You |
|---------|-------------------|
| Edge‑triggered mode (`EPOLLET`) | Reduces duplicate notifications |
| Level‑triggered mode (`EPOLLIN`) | Simpler logic for most apps |
| Scales to ~10⁵ fds | Red‑Black tree lookup stays O(log n) |
| Well‑documented (`man7.org/linux/man-pages/man7/epoll.7.html`) | Mature ecosystem, libraries like libevent, libuv |

### Limitations and Pain Points

* **Syscall overhead** – Every `epoll_wait` and every `epoll_ctl` is a full syscall.
* **Copy‑out cost** – The kernel copies up to 64 `epoll_event` structs into user memory each wake‑up.
* **No batch I/O** – Reads/writes still require separate syscalls (`read`, `write`, `sendmsg`).
* **Complex edge‑triggered state** – Missed events can silently stall an application if not handled correctly.

Real‑world engineers often report that beyond ~200 k concurrent connections, CPU spent in `epoll_wait` and the accompanying `read`/`write` syscalls dominates the profile. The next generation of Linux I/O was designed to address exactly these bottlenecks.

## io_uring: The New Paradigm

### Origins and Design Goals

io_uring debuted in Linux 5.1 (released in 2019) as a collaborative effort between Jens Axboe and the Facebook infrastructure team. The design goal was simple: **eliminate the per‑operation syscall** while still exposing a flexible, asynchronous API that works for networking, files, and even custom kernel extensions.

The core idea is a pair of **ring buffers** mapped into user space:

* **Submission Queue (SQ)** – User writes I/O requests directly into the kernel‑visible memory.
* **Completion Queue (CQ)** – Kernel writes completion entries back to the same memory region.

Both queues are protected by a single `io_uring` file descriptor, and the kernel only needs to be entered when the application *submits* or *waits* for completions. The typical loop looks like this:

```c
#include <liburing.h>

int main() {
    struct io_uring ring;
    io_uring_queue_init(4096, &ring, 0);

    /* Prepare a read */
    struct iovec iov = {.iov_base = malloc(4096), .iov_len = 4096};
    io_uring_prep_readv(&ring.sqe[0], fd, &iov, 1, 0);
    io_uring_submit(&ring);

    /* Wait for completion */
    struct io_uring_cqe *cqe;
    io_uring_wait_cqe(&ring, &cqe);
    if (cqe->res >= 0) {
        process(iov.iov_base, cqe->res);
    }
    io_uring_cqe_seen(&ring, cqe);
    io_uring_queue_exit(&ring);
}
```

### Architecture Details

| Component | Role |
|-----------|------|
| **SQE (Submission Queue Entry)** | Describes one operation (read, write, poll, sendmsg, etc.) |
| **CQE (Completion Queue Entry)** | Returns result, flags, and user data for the operation |
| **IORING_SETUP_SQPOLL** | Optional kernel thread that polls SQ, eliminating the need for `io_uring_enter` on every submit |
| **IORING_REGISTER_BUFFERS** | Allows zero‑copy I/O by registering user buffers once |
| **IORING_OP_POLL_ADD / POLL_REMOVE** | Native async poll support, replacing epoll entirely |

The kernel processes SQEs in batches, often completing dozens of operations before returning to user space. Because the buffers are already mapped, there is **no data copy** between kernel and user for the request metadata itself.

### Performance Numbers (2023‑2024 Benchmarks)

| Workload | epoll latency (p99) | io_uring latency (p99) | Throughput increase |
|----------|---------------------|------------------------|----------------------|
| 10 k concurrent TCP echo | 150 µs | 65 µs | +130 % |
| 1 M small file reads (4 KB) | 2.1 ms | 0.9 ms | +133 % |
| 200 k HTTP/2 streams (nghttp2) | 210 µs | 80 µs | +162 % |

These results are taken from the official io_uring benchmark suite and reproduced by the LWN article on io_uring’s impact ([LWN.io_uring](https://lwn.net/Articles/859332/)). The reduction in syscalls and the ability to batch completions are the primary drivers.

## Architecture of io_uring in Production

### Integration with Existing Event Loops

Many production services already run an epoll‑based event loop (e.g., Nginx, Envoy). Migrating to io_uring can be done incrementally:

1. **Hybrid mode** – Keep the epoll loop for control plane events, use io_uring for data‑plane reads/writes.
2. **Full replace** – Switch to `IORING_OP_POLL_ADD` to let io_uring handle socket readiness, removing epoll entirely.
3. **Zero‑copy file serving** – Register file buffers with `IORING_REGISTER_FILES` and serve static assets without extra copies.

A practical pattern used by Facebook’s “Proxygen” stack is to allocate a dedicated **IO thread** per NUMA node that runs an io_uring loop, while the main worker threads communicate via lock‑free queues. This isolates kernel‑user transitions to a single core per socket, preserving cache locality.

### Failure Modes and Mitigations

| Failure | Symptom | Mitigation |
|---------|---------|------------|
| **SQ overflow** | `-EBUSY` on `io_uring_submit` | Pre‑allocate a larger ring or enable `IORING_SETUP_SQPOLL` |
| **CQ lag** | Unprocessed completions, growing latency | Periodically call `io_uring_peek_cqe` in a background task |
| **Kernel version mismatch** | Missing opcodes (e.g., `IORING_OP_CONNECT`) | Detect at runtime with `io_uring_probe` and fallback to epoll |
| **Resource exhaustion** | `-ENOBUFS` when registering buffers | Use `IORING_REGISTER_BUFFERS` with per‑CPU pools, release unused buffers promptly |

Understanding these patterns is essential before a full production rollout.

## Patterns in Production

### 1. Batch Submission for High‑Throughput Services

A typical microservice that processes protobuf messages from a TCP stream can batch 32 reads into a single SQ submission:

```c
for (int i = 0; i < BATCH; ++i) {
    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
    io_uring_prep_recv(sqe, sockfd, bufs[i], BUF_SIZE, 0);
    io_uring_sqe_set_data(sqe, bufs[i]);
}
io_uring_submit(&ring);
```

The kernel then processes all reads back‑to‑back, dramatically reducing per‑message overhead.

### 2. Zero‑Copy File Transmission

Static‑file servers can register file descriptors once and reuse them across many completions:

```c
int fds[NUM_FILES];
for (int i = 0; i < NUM_FILES; ++i) fds[i] = open(file_paths[i], O_RDONLY);
io_uring_register_files(&ring, fds, NUM_FILES);

/* Later, send a file */
struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
io_uring_prep_sendfile(sqe, client_fd, fds[idx], 0, file_size);
io_uring_submit(&ring);
```

No extra `read` syscalls are needed; the kernel streams directly from the page cache to the socket.

### 3. Hybrid Polling for Legacy Codebases

When a codebase already relies on epoll for control messages (e.g., configuration reload), you can keep a tiny epoll set and offload data I/O to io_uring:

```c
// epoll for control
int epfd = epoll_create1(0);
epoll_ctl(epfd, EPOLL_CTL_ADD, ctrl_fd, &ev);

// io_uring for data
struct io_uring ring;
io_uring_queue_init(4096, &ring, 0);
```

This approach avoids a massive rewrite while still harvesting most latency benefits.

## Key Takeaways

- **epoll** is reliable for modest concurrency but suffers from per‑operation syscall overhead and copy‑out costs.
- **io_uring** replaces the poller with a shared ring buffer, cutting syscalls and enabling batch processing.
- Real‑world benchmarks show **2‑3× latency reductions** and **>100 % throughput gains** for typical cloud workloads.
- Production migration strategies include **hybrid loops**, **batch submissions**, and **zero‑copy file serving**.
- Guard against common pitfalls: ring overflow, CQ lag, and kernel version incompatibilities by probing capabilities at startup.

## Further Reading

- [epoll man page](https://man7.org/linux/man-pages/man7/epoll.7.html) – Official documentation of the classic API.  
- [io_uring kernel documentation](https://kernel.org/doc/html/latest/io_uring/index.html) – Deep dive into the kernel’s design and syscalls.  
- [LWN article on io_uring performance](https://lwn.net/Articles/859332/) – Benchmark data and architectural analysis.  
- [Facebook’s io_uring blog post](https://engineering.fb.com/2020/02/05/open-source/io_uring/) – Real‑world use cases from a large-scale service.  
- [liburing GitHub repository](https://github.com/axboe/liburing) – Reference implementation and examples.  