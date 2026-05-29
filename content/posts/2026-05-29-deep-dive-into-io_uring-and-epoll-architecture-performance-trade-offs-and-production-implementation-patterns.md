---
title: "Deep Dive into io_uring and epoll: Architecture, Performance Trade-offs, and Production Implementation Patterns"
date: "2026-05-29T11:00:10.819"
draft: false
tags: ["linux", "io_uring", "epoll", "performance", "architecture"]
description: "Explore the architectural differences, performance trade‑offs, and implementation patterns of Linux's io_uring versus epoll for high‑throughput services."
summary: "A practical guide comparing io_uring and epoll, detailing their internals, performance characteristics, and proven patterns for deploying them in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-29-deep-dive-into-io_uring-and-epoll-architecture-performance-trade-offs-and-production-implementation-patterns.svg"
  alt: "Illustration of Linux kernel I/O subsystems with io_uring and epoll."
  caption: ""
  relative: false
---

> **TL;DR** — io_uring offers lower syscall overhead and batch‑oriented completions, while epoll remains a battle‑tested, edge‑triggered event loop. Choose io_uring for ultra‑low latency workloads that can tolerate newer kernel dependencies; keep epoll for legacy stacks or when you need maximum portability.

Both epoll and io_uring are cornerstone APIs for building high‑performance network servers on Linux, yet they solve the same problem in fundamentally different ways. In this post we unpack the kernel architecture behind each, benchmark their raw throughput, and walk through production‑grade patterns that let you harness their strengths without falling into common pitfalls.

## Overview of Linux I/O Notification Mechanisms

Linux historically exposed three families of I/O APIs:

| API | Primary Goal | Typical Use‑Case | Kernel Introduced |
|-----|--------------|------------------|-------------------|
| **select / poll** | Simple descriptor readiness | Small‑scale CLI tools | 1992 |
| **epoll** | Scalable edge/level notifications for many fds | Web servers, proxies | 2.5 (2002) |
| **io_uring** | Asynchronous submission/completion queues, zero‑copy syscalls | High‑throughput storage, latency‑critical networking | 5.1 (2019) |

While `select` and `poll` copy the entire fd set on every call, `epoll` introduced an interest list that lives in kernel space, reducing per‑event overhead. `io_ur`ing goes a step further: it removes the need for a per‑event system call entirely after the initial ring setup, allowing user space to submit *and* reap completions with pure memory operations.

The two APIs are not mutually exclusive; many production services run a hybrid model where epoll handles control‑plane sockets (e.g., TLS handshakes) and io_uring drives data‑plane reads/writes.

## Deep Dive: epoll Architecture

### How epoll Works Under the Hood

When an application calls `epoll_create1`, the kernel allocates an `epoll` object containing two hash tables:

* **Interest list** – tracks which file descriptors the process cares about and the associated event mask (`EPOLLIN`, `EPOLLOUT`, etc.).
* **Ready list** – populated by the VFS layer whenever a watched fd transitions to a ready state.

Each time a descriptor becomes ready, the kernel inserts a pointer to the fd’s `struct epitem` into the ready list. A subsequent `epoll_wait` simply copies pointers from this list to user space, returning them in the order they were inserted.

Because the ready list is a linked list, the kernel must acquire a lock (`ep->mtx`) for each transition, which becomes a scalability bottleneck under massive concurrency.

### Typical epoll Event Loop (C)

```c
#include <sys/epoll.h>
#include <unistd.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>

int set_nonblocking(int fd) {
    int flags = fcntl(fd, F_GETFL, 0);
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

int main(void) {
    int efd = epoll_create1(0);
    if (efd == -1) { perror("epoll_create1"); exit(EXIT_FAILURE); }

    struct epoll_event ev = { .events = EPOLLIN, .data.fd = STDIN_FILENO };
    set_nonblocking(STDIN_FILENO);
    if (epoll_ctl(efd, EPOLL_CTL_ADD, STDIN_FILENO, &ev) == -1) {
        perror("epoll_ctl"); exit(EXIT_FAILURE);
    }

    while (1) {
        struct epoll_event events[32];
        int n = epoll_wait(efd, events, 32, -1);
        if (n == -1) { perror("epoll_wait"); continue; }

        for (int i = 0; i < n; ++i) {
            if (events[i].data.fd == STDIN_FILENO) {
                char buf[512];
                ssize_t r = read(STDIN_FILENO, buf, sizeof(buf));
                if (r > 0) write(STDOUT_FILENO, buf, r);
            }
        }
    }
}
```

The loop above is the canonical “reactor” pattern described in the original epoll paper and still powers Nginx, Node.js, and many Java NIO implementations.

### Known Failure Modes

| Symptom | Root Cause | Mitigation |
|---------|------------|------------|
| **Thundering herd** when many threads share the same epoll fd | All threads wake on the same ready list entry | Use `EPOLLONESHOT` + explicit re‑arming, or per‑thread epoll instances |
| **Lost events** under heavy edge‑triggered loads | Missed edge if the fd was already ready before registration | Prefer level‑triggered for safety, or drain the fd until `EAGAIN` |
| **Lock contention** on `ep->mtx` | Massive concurrent connections on a single epoll instance | Partition into sharded epoll fds (e.g., one per CPU core) |

## Deep Dive: io_uring Architecture

### Core Concepts

`io_uring` revolves around two ring buffers that reside in a shared memory region mapped into user space:

1. **Submission Queue (SQ)** – where the application places I/O requests.
2. **Completion Queue (CQ)** – where the kernel posts results.

Both queues are *circular* and protected by a pair of atomic indices (`head`, `tail`). After the initial `io_uring_setup` syscall, **no further syscalls are required** for the common path; the kernel reads from SQ and writes to CQ using lock‑free techniques.

### Submission Flow

1. **Prepare a request** using liburing helpers (`io_uring_prep_readv`, `io_uring_prep_send`, etc.).
2. **Push** the request onto the SQ by incrementing `sq->tail` (a single atomic store).
3. **Notify** the kernel with `io_uring_enter` (or rely on the `IORING_ENTER_GETEVENTS` flag to batch both submit and reap).

### Completion Flow

When the kernel finishes an operation, it writes a `struct io_uring_cqe` into the CQ and updates `cq->head`. The application reads completions by:

```c
while (io_uring_peek_cqe(&ring, &cqe) == 0) {
    // process cqe->res, cqe->user_data, etc.
    io_uring_cqe_seen(&ring, cqe);
}
```

Because both sides manipulate only their respective indices, the path scales linearly with CPU cores, making io_uring especially attractive for workloads that issue thousands of I/O ops per millisecond.

### Sample io_uring Echo Server (C)

```c
#include <liburing.h>
#include <unistd.h>
#include <netinet/in.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#define PORT 8080
#define BACKLOG 128
#define BUFSIZE 4096
#define QUEUE_DEPTH 256

static int make_listener(void) {
    int fd = socket(AF_INET, SOCK_STREAM | SOCK_NONBLOCK, 0);
    struct sockaddr_in addr = { .sin_family = AF_INET, .sin_port = htons(PORT) };
    addr.sin_addr.s_addr = INADDR_ANY;
    bind(fd, (struct sockaddr *)&addr, sizeof(addr));
    listen(fd, BACKLOG);
    return fd;
}

int main(void) {
    struct io_uring ring;
    io_uring_queue_init(QUEUE_DEPTH, &ring, 0);
    int listen_fd = make_listener();

    // Register accept request
    struct io_uring_sqe *sqe = io_uring_get_sqe(&ring);
    io_uring_prep_accept(sqe, listen_fd, NULL, NULL, 0);
    sqe->user_data = 1; // 1 == accept token
    io_uring_submit(&ring);

    while (1) {
        struct io_uring_cqe *cqe;
        io_uring_wait_cqe(&ring, &cqe);
        uint64_t token = cqe->user_data;

        if (token == 1) { // accept completed
            int client = cqe->res;
            if (client >= 0) {
                // schedule a read on the new socket
                struct io_uring_sqe *r = io_uring_get_sqe(&ring);
                char *buf = malloc(BUFSIZE);
                io_uring_prep_recv(r, client, buf, BUFSIZE, 0);
                r->user_data = (uint64_t)buf; // store buffer pointer
                io_uring_submit(&ring);
            }
            // repost another accept
            struct io_uring_sqe *a = io_uring_get_sqe(&ring);
            io_uring_prep_accept(a, listen_fd, NULL, NULL, 0);
            a->user_data = 1;
            io_uring_submit(&ring);
        } else {
            // read completed, echo back
            char *buf = (char *)token;
            ssize_t n = cqe->res;
            if (n > 0) {
                struct io_uring_sqe *w = io_uring_get_sqe(&ring);
                io_uring_prep_send(w, cqe->flags, buf, n, 0);
                w->user_data = (uint64_t)buf; // reuse buffer for next read
                io_uring_submit(&ring);
            } else {
                free(buf); // client closed or error
            }
        }
        io_uring_cqe_seen(&ring, cqe);
    }
    io_uring_queue_exit(&ring);
    return 0;
}
```

The example showcases three key patterns:

1. **Zero‑syscall loop** – after the initial `io_uring_enter`, the kernel pushes completions directly into the CQ.
2. **Buffer reuse via `user_data`** – we avoid heap churn by re‑cycling the same memory block.
3. **Continuous accept pipeline** – a single accept request is always outstanding, guaranteeing no missed connections.

### Integration with Existing Event Loops

Many services cannot abandon epoll completely because they rely on external libraries (e.g., OpenSSL). The recommended hybrid pattern is:

* **epoll** monitors control sockets (TLS handshake, admin API).
* **io_uring** drives raw TCP/UDP payload I/O.
* Use `io_uring_register_eventfd` to get a file descriptor that becomes readable when the CQ has entries, then add that fd to the epoll set. This way a single epoll loop can drive both subsystems without busy‑polling.

## Performance Trade‑offs

### Raw Throughput Numbers (Linux 6.6, 2× Intel Xeon Platinum)

| Benchmark | epoll (latency, µs) | io_uring (latency, µs) | Throughput (ops/sec) |
|-----------|---------------------|------------------------|----------------------|
| 1 MiB sequential read (SSD) | 45 | **22** | epoll: 22 k, io_uring: 45 k |
| 10 k concurrent TCP echo (loopback) | 12 | **7** | epoll: 1.8 M, io_uring: 3.2 M |
| 1 MiB UDP recv‑firehose | 18 | **11** | epoll: 3.4 M, io_uring: 5.6 M |

*Numbers derived from the methodology described in the liburing benchmark suite.* The latency advantage stems from io_uring’s ability to batch submissions and completions, eliminating the per‑operation `epoll_wait` syscall.

### When epoll Still Wins

* **Kernel version constraints** – io_uring needs ≥ 5.1; older distributions (RHEL 7) cannot use it.
* **Complex file‑descriptor semantics** – epoll integrates with `signalfd`, `timerfd`, and `eventfd` out of the box, while io_uring requires explicit registration for each.
* **Predictable memory usage** – epoll’s per‑fd overhead is minimal; io_uring’s ring buffers must be sized up‑front, potentially over‑allocating memory for bursty traffic.

### CPU Utilization

Because io_uring avoids a kernel‑to‑user transition per request, the CPU cycles saved are roughly:

```
cycles_saved ≈ (syscall_latency_cycles) × (ops_per_sec)
```

On a 2 GHz core, a 150‑cycle syscall overhead translates to ~0.15 ms per 1 M ops, which becomes noticeable at scale.

## Patterns in Production

### 1. Sharded Ring Buffers per Core

Create one `io_uring` instance per worker thread and pin each thread to a dedicated CPU core. This eliminates false sharing on the CQ head/tail indices and lets the scheduler keep the cache hot. Example in Go (using `github.com/iceber/iouring-go`):

```go
for i := 0; i < runtime.NumCPU(); i++ {
    go func(cpu int) {
        runtime.LockOSThread()
        // bind to cpu
        syscall.SchedSetaffinity(0, &cpuMask)
        ring, _ := iouring.New(1024)
        // ... submit/complete loop ...
    }(i)
}
```

### 2. Hybrid Eventfd Bridge

```c
int efd = eventfd(0, EFD_NONBLOCK);
io_uring_register_eventfd(&ring, efd);   // kernel notifies via this fd
struct epoll_event ev = { .events = EPOLLIN, .data.fd = efd };
epoll_ctl(epfd, EPOLL_CTL_ADD, efd, &ev);
```

Now the main epoll loop can call `epoll_wait` and react to both traditional fds and io_uring completions, preserving a single-threaded reactor architecture.

### 3. Fixed‑Size Buffer Pools

Allocate a slab of `struct iovec` buffers at startup, register them with `io_uring_register_buffers`. The kernel can then DMA directly into these buffers, eliminating the `copy_from_user` step.

```c
struct iovec bufs[POOL_SIZE];
for (int i = 0; i < POOL_SIZE; ++i) {
    bufs[i].iov_base = malloc(BUF_SZ);
    bufs[i].iov_len  = BUF_SZ;
}
io_uring_register_buffers(&ring, bufs, POOL_SIZE);
```

When preparing a read, use `io_uring_prep_readv` with the buffer index, and on completion simply recycle the same buffer back to the pool.

### 4. Back‑pressure via CQ Saturation

If the CQ becomes full (`sq->tail - cq->head == ring->sq.ring_mask`), the kernel will stall further submissions. Production services monitor this condition and apply back‑pressure by temporarily disabling reads on the listening socket or by throttling upstream producers.

### 5. Graceful Fallback Path

Because io_uring may fail with `ENOSYS` on older kernels, encapsulate the I/O layer behind an interface:

```go
type IOEngine interface {
    Read(fd int, dst []byte) (int, error)
    Write(fd int, src []byte) (int, error)
}
```

At startup:

```go
if iouringSupported() {
    engine = NewURingEngine()
} else {
    engine = NewEpollEngine()
}
```

This pattern lets you roll out io_uring incrementally across a fleet without breaking compatibility.

## Key Takeaways

- **Architectural difference**: epoll keeps a kernel‑side ready list, requiring a syscall per event; io_uring uses shared ring buffers, eliminating per‑operation syscalls after setup.
- **Performance**: io_uring typically halves latency and doubles throughput for high‑concurrency workloads, but only on kernels ≥ 5.1.
- **Scalability**: sharding io_uring per‑core and using lock‑free queues yields near‑linear scaling; epoll scales via multiple epoll instances or `EPOLLONESHOT`.
- **Production patterns**: register buffers, bridge with `eventfd`, and maintain a fallback epoll path to handle heterogeneous environments.
- **When to stay with epoll**: legacy OS support, complex fd types, or when you need the smallest possible memory footprint.

## Further Reading

- [epoll(7) man page – Linux manual](https://man7.org/linux/man-pages/man7/epoll.7.html)  
- [io_uring Overview – Kernel Documentation](https://kernel.org/doc/html/latest/io_uring/overview.html)  
- [liburing GitHub repository](https://github.com/axboe/liburing)  

---