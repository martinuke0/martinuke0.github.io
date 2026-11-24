---

---
title: "Inside Tokio's Work-Stealing Scheduler: Task Sharding, Core Affinity, and Fairness"
date: "2026-11-24T07:00:40.933"
draft: false
tags: ["tokio", "rust", "concurrency", "work-stealing", "scheduler"]
description: "Tokio's work-stealing scheduler under the hood: how task sharding, core affinity, and fairness guarantees shape performance in production Rust async applications."
summary: "A deep dive into Tokio's scheduler mechanics, from double-ended deques to NUMA-aware core binding, with practical patterns for high-throughput async services."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-24-inside-tokio.svg"
  alt: "Illustration of a work-stealing scheduler with worker threads and task deques"
  caption: ""
  relative: false
---

> **TL;DR** — Tokio’s scheduler distributes tasks across worker-thread double-ended deques using work-stealing, respects core affinity via thread-local task allocation, and maintains fairness through configurable steal orders. Understanding the interplay between task sharding, NUMA topology, and runtime configuration lets you tune latency and throughput for production async services.

## Tokio's Execution Model: Green Threads and Worker Threads

Tokio’s runtime is built around a compact but powerful execution model. At the foundation are *futures*—zero-cost abstractions that represent asynchronous computations. The runtime schedules these futures onto a pool of OS threads, each backed by a *local* task queue. This design avoids the global lock contention that plagued early async runtimes, while still providing the ability to parallelize work across multiple cores.

A Tokio `Runtime` (or `Tokio`) creates a set of *worker threads* at startup. The default number of workers equals the number of logical CPUs on the machine, though this is configurable via `runtime.builder().worker_threads(n)`. Each worker thread owns a local deque of `Task` objects. When a future is spawned onto the runtime, it’s placed onto the local deque of the calling worker. If the calling thread is itself a worker, the task stays local; if it’s a *runtime thread* invoked via `spawn` from a non-worker context, Tokio may still attempt to place the task on the nearest worker’s deque.

The key insight is that Tokio treats *tasks* as units of work that can be moved between deques without allocating on the hot path. Tasks are simple heap-allocated structures containing a `Waker` and the future’s state. This design enables the work-stealing algorithm to operate in amortized O(1) time, which is critical for high-frequency async workloads.

Importantly, Tokio distinguishes between *local* and *remote* task operations. A worker can pop the front of its own deque (FIFO order) or pop from the back (LIFO order, useful for recursion or continuation-passing style). When stealing, a worker pops from the *back* of the victim’s deque. This asymmetry—FIFO for local, LIFO for remote—shapes both fairness and cache locality across the system.

## Work-Sharding and the Double-Ended Deque

The heart of Tokio’s scheduler is the *double-ended deque* (deque). Each worker’s deque holds tasks as a contiguous array, with indices for the “front” and “back.” This layout gives O(1) push/pop at both ends and allows efficient stealing without complex synchronization.

### Local Operation: Push and Pop

When a task is spawned on a worker’s thread, it’s pushed to the back of that worker’s deque. Popping from the front retrieves the oldest task, preserving FIFO ordering. This is the primary path for task execution and ensures that work submitted to a given worker is processed in the order it arrived, which is essential for predictable behavior in many applications.

Pushing and popping are lock-free. The deque uses atomic compare-and-swap operations at the indices, and because each worker exclusively owns its deque, there’s no cross-thread contention for the common case. If a deque becomes full, Tokio may allocate additional space, but in practice, the initial capacity (typically a few hundred tasks) suffices for most request-driven workloads.

### Stealing: Victim Selection and Order

When a worker runs out of local work, it *steals* from another worker’s deque. The stealer chooses a victim randomly or via a deterministic round-robin pattern, then attempts to pop from the *back* of the victim’s deque. The LIFO steal is deliberate: it preserves recently pushed tasks for the victim, reducing the chance that the victim’s own cache hotset is disrupted. Meanwhile, the stealer gains a task that’s likely to be independent of its current workload.

If the victim’s deque is empty, the stealer may try another victim or block on a condvar until new work arrives. The stealing loop continues until the stealer has a task to execute or all workers are quiescent. This design ensures that no worker sits idle for long, as long as at least one worker has pending tasks.

The *sharding* aspect emerges naturally: tasks are initially sharded across workers based on the spawning thread. Over time, stealing redistributes tasks, but the initial sharding determines the *steady-state distribution*. If your application spawns the majority of tasks on a single thread (e.g., a main thread handling HTTP requests), that worker’s deque will be overfull while others starve. Conscious task distribution—using `spawn_many` across contexts, or explicitly partitioning work—is therefore a key lever for achieving balanced sharding.

## Core Affinity and NUMA Awareness

In production systems, *where* a task runs matters as much as *how* it’s scheduled. Modern CPUs have deep memory hierarchies: each core has private L1/L2 cache, shared L3 cache per socket, and non-uniform memory access (NUMA) regions spanning sockets. A scheduler that ignores these nuances can incur significant cache misses and remote memory latency.

### Affinity via Thread Local Storage

Tokio’s scheduler exposes *core affinity* through the runtime builder. By default, each worker thread is free to run on any core, and the OS scheduler handles placement. However, developers can bind workers to specific cores using `runtime.builder().affinity(...)` or by setting the `TOKIO_WORKER_THREADS` environment variable in combination with CPU pinning tools like `taskset` or `cgroups`.

When affinity is set, Tokio ensures that a given worker’s deque stays on its assigned core. This has two immediate effects:
1. **Cache locality:** The worker’s deque and its associated Waker table remain hot in the core’s L1/L3 cache, reducing latency for task pops and steals.
2. **NUMA alignment:** If the affinity mask respects NUMA boundaries, the worker’s memory allocations (e.g., for boxed futures, buffers) happen from the local NUMA node, avoiding remote memory access.

### Explicit Affinity and `park`/`unpark`

Tokio’s thread pool uses a *park*/`unpark` model for wakeups. When a future is woken up, it posts a notification to the owning worker via `unpark`. If the worker is parked (idling), it wakes up and retrieves the task. With affinity, the unparked worker’s thread is already (or quickly becomes) running on its assigned core, so the wakeup latency is minimal.

Developers can also use `tokio::task::set_local` to associate a task with the current worker’s local storage, and `tokio::task::LocalSet` to create nested async contexts that run on the same worker. This is useful for patterns like per-connection state that should never migrate across workers, preserving affinity and avoiding cross-worker synchronization.

### NUMA-Aware Configuration

For multi-socket servers, the best practice is to:
1. Discover the NUMA topology (e.g., via `numactl --hardware`).
2. Assign workers to cores within the same NUMA node as the I/O devices they interact with (network cards, disks).
3. Use `runtime_builder.worker_threads(n)` where `n` matches the number of cores per NUMA node, and pin the runtime process to a specific socket.

Tools like `numactl` can be used at process start to mask CPUs and memory nodes. When combined with Tokio’s affinity, this yields predictable latency profiles, especially for latency-sensitive services like API gateways or real-time data pipelines.

## Fairness in the Scheduler

Fairness is the trickiest part of work-stealing schedulers. The goal is to ensure that no task or worker is permanently starved, while still maintaining high throughput. Tokio’s fairness guarantees stem from the interplay of steal order, deque saturation, and runtime configuration.

### Steal Strategies: FIFO vs LIFO

As noted, local pops are FIFO, while remote steals are LIFO. This asymmetry has direct fairness implications:
- **FIFO local pops** ensure that tasks submitted to a worker are processed in order. This is crucial for request-response patterns where ordering matters (e.g., processing incoming HTTP requests per connection).
- **LIFO steals** favor the victim, keeping recent tasks local. However, a malicious or pathological workload—such as a tight loop that continuously pushes and steals tasks—could cause a worker to repeatedly steal from the same victim, effectively starving other workers.

To mitigate this, Tokio employs *victim randomization* and *steal quotas*. A worker won’t blindly steal from the same victim indefinitely; after a few successful steals, it rotates to a different victim. Additionally, if a deque becomes empty after a steal, the stealer may block or yield, preventing a tight loop of steals that wastes CPU cycles.

### Starvation Prevention

Fairness also depends on the *rate* at which tasks are generated. In a balanced workload, where tasks are evenly distributed across workers, work-stealing naturally achieves fairness: idle workers steal from busy ones, evening out the load. In skewed workloads, however, fairness can degrade.

Tokio provides a few mechanisms to counteract imbalance:
- **Minimum worker count:** Setting at least as many workers as CPU cores ensures that there’s always work to steal if any worker becomes overloaded.
- **Task prioritization:** While Tokio’s scheduler is inherently fair (FIFO per worker), developers can implement priority queues by pushing high-priority tasks to the *front* of a deque (via `push_front` if available) or by using separate channels for urgent work.
- **Work stealing with backoff:** If a worker repeatedly finds its deque empty after stealing, it can back off and park, allowing the OS to schedule other processes. This prevents CPU spinning and improves overall system fairness.

### Measuring Fairness

In practice, fairness can be observed via metrics like *average wait time* and *load imbalance*. A simple benchmark might spawn 10,000 tasks across 4 workers and measure the variance in completion times. With good affinity and balanced sharding, the variance should be low. With poor sharding (e.g., all tasks on one worker), variance spikes as three workers steal furiously while the original worker drowns in work.

## Patterns in Production: Tuning Tokio for High-Throughput Workloads

Understanding the scheduler’s internals translates directly into concrete tuning patterns for production Rust services.

### 1. Size Deques Appropriately

Tokio’s default deque capacity is ~64 tasks. For high-throughput workloads (e.g., thousands of concurrent connections), increasing the capacity reduces the frequency of steals and the associated overhead. The runtime builder exposes `runtime_builder.max_blocking_threads(n)` and other knobs, but deque sizing is often done via the `task_capacity` feature or by pre-populating channels that feed tasks into the runtime.

### 2. Minimize Cross-Worker Dependencies

Tasks that frequently await on each other or share mutable state should ideally stay on the same worker. Use `tokio::task::LocalSet` for per-connection state, and avoid `spawn` from a global context when the task has affinity to a specific thread. If cross-worker communication is necessary, prefer async channels (`mpsc`, `oneshot`) that are designed for concurrent access, rather than sharing raw data structures.

### 3. Align Worker Count with Work Type

- **CPU-bound work:** Match worker threads to logical CPUs, and ensure each worker’s deque holds enough tasks to keep the core busy between steals.
- **I/O-bound work:** More workers than cores can improve utilization, as I/O waits free up threads to process other tasks. However, excessive workers increase context-switch overhead. A common starting point is `num_cpus * 2` for pure I/O workloads.
- **Mixed workloads:** Profile. The optimal count often lies between the CPU and I/O extremes.

### 4. Use `#[tokio::main]` and Runtime Builder Wisely

The macro `#[tokio::main]` creates a single-threaded runtime by default, which is great for scripts and CLIs but unsuitable for servers. Always use the builder pattern for services:
```rust
#[tokio::main]
async fn main() {
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(num_cpus::get())
        .thread_name("tokio-worker")
        .enable_all()
        .build()
        .expect("failed to build runtime");
    runtime.block_on(async {
        // app logic
    });
}
```
This gives full control over affinity, panic handling, and thread naming—all of which aid debugging and monitoring in production.

### 5. Observe and Iterate

Use Tokio’s introspection features (e.g., `runtime.metrics()`) to observe queue lengths, idle worker counts, and steal rates. Pair this with OS-level tools like `perf`, `top`, or `bpftrace` to correlate scheduler behavior with cache misses and context switches. Iterate on worker count, deque size, and affinity until the metrics align with your SLOs.

## Key Takeaways

- Tokio’s scheduler relies on per-worker double-ended deques, enabling O(1) local task operations and efficient work-stealing when workers exhaust their local queue.
- Work sharding is determined at task spawn time; conscious distribution is required to prevent hotspot workers and achieve balanced load across cores.
- Core affinity, when aligned with NUMA topology, dramatically improves cache locality and reduces remote memory latency, yielding lower and more predictable request latency.
- Fairness is achieved through FIFO local pops, LIFO steals, victim rotation, and steal quotas; pathological workloads can still starve other workers without randomization and backoff.
- Production tuning hinges on matching worker count to workload type, sizing deques for expected concurrency, and minimizing cross-worker state sharing.
- Observe scheduler metrics (queue lengths, steal rates) alongside OS performance counters to iteratively refine configuration for your specific traffic patterns.

## Further Reading

- [Tokio documentation – Runtime](https://docs.rs/tokio/latest/tokio/runtime/index.html)
- [Tokio scheduler source repository](https://github.com/tokio-rs/tokio/tree/main/tokio/src/scheduler)
- [The Rust Async Book – Foundations](https://rust-lang.github.io/async-book/basics/await.html)
- [Understanding NUMA and Affinity in Rust](https://blog.rust-lang.org/2021/06/15/numa.html)
- [High-Performance Async I/O with Tokio](https://tokio.rs/tokio/topics/async-basics)