---
title: "The Thread Safety Tradeoffs of Epoch Based Reclamation"
date: "2026-05-17T23:01:00.304"
draft: false
tags: ["concurrency","memory-management","epoch-reclamation","thread-safety","systems-programming"]
description: "Explore how epoch based reclamation balances lock‑free performance with thread safety, comparing its guarantees, costs, and practical pitfalls."
summary: "A deep dive into epoch based reclamation, its thread‑safety model, performance trade‑offs, and how it stacks up against alternative reclamation schemes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-the-thread-safety-tradeoffs-of-epoch-based-reclamation.svg"
  alt: "Illustration of overlapping threads and memory epochs."
  caption: ""
  relative: false
---

> **TL;DR** — Epoch based reclamation (EBR) offers lock‑free memory safety with low overhead, but it relies on cooperative threads to advance epochs. If a thread stalls, memory can be retained indefinitely, and certain data‑race scenarios still require careful design.

In modern lock‑free data structures, reclaiming retired nodes without introducing blocking operations is a perennial challenge. Epoch based reclamation (EBR) emerged as a pragmatic answer: threads announce the “epoch” they are operating in, and memory is reclaimed only after all threads have moved past the epoch in which the node was retired. This article unpacks the mechanics of EBR, examines the thread‑safety guarantees it provides, and weighs its trade‑offs against hazard pointers, RCU, and other reclamation schemes. By the end you’ll understand when EBR is a good fit, what hidden costs to expect, and how to avoid the most common pitfalls.

## Overview of Epoch Based Reclamation

EBR was popularized by Michael and Scott’s lock‑free queue and later formalized in the Linux kernel’s RCU (Read‑Copy‑Update) subsystem. The core idea is simple:

1. **Global epoch counter** – a monotonically increasing integer, usually advanced by a dedicated thread or by any thread that notices sufficient inactivity.
2. **Thread‑local epoch** – each thread stores the current global epoch when it begins an operation that may access shared nodes.
3. **Retirement list** – when a thread removes a node, it places the node into a per‑thread list tagged with the current epoch.
4. **Reclamation** – once the global epoch has advanced twice beyond the epoch stored with a retired node, the node is guaranteed to be unreachable by any active thread and can be freed.

Because the algorithm only requires each thread to read a single atomic counter and write its own epoch, the per‑operation overhead is minimal. However, the safety model hinges on the assumption that **all threads eventually make progress** and periodically publish their epoch.

### A Minimal Implementation (C++)

```cpp
// Minimal EBR sketch in C++20
#include <atomic>
#include <vector>
#include <thread>

static std::atomic<std::size_t> global_epoch{0};

struct ThreadInfo {
    std::atomic<std::size_t> local_epoch{0};
    std::vector<std::pair<void*, std::size_t>> retired;
};

thread_local ThreadInfo ti;

void enter_critical() {
    ti.local_epoch.store(global_epoch.load(std::memory_order_acquire),
                         std::memory_order_release);
}

void exit_critical() {
    ti.local_epoch.store(0, std::memory_order_release);
}

void retire(void* ptr) {
    ti.retired.emplace_back(ptr, global_epoch.load(std::memory_order_relaxed));
    if (ti.retired.size() >= 64) // arbitrary threshold
        try_reclaim();
}

void try_reclaim() {
    std::size_t cur = global_epoch.load(std::memory_order_acquire);
    // Scan all thread locals (pseudo‑code)
    for (ThreadInfo* other : all_thread_infos) {
        if (other->local_epoch.load(std::memory_order_acquire) != 0 &&
            other->local_epoch.load(std::memory_order_acquire) < cur) {
            return; // some thread still in older epoch
        }
    }
    // Safe to reclaim
    for (auto it = ti.retired.begin(); it != ti.retired.end(); ) {
        if (it->second + 2 <= cur) {
            delete static_cast<Node*>(it->first);
            it = ti.retired.erase(it);
        } else ++it;
    }
    global_epoch.fetch_add(1, std::memory_order_acq_rel);
}
```

The snippet omits many engineering details (memory fences, thread registration, etc.) but captures the essential flow. Notice how the only *synchronization point* that touches other threads is the `global_epoch` load in `try_reclaim`; all other operations are thread‑local.

## How EBR Works Under the Hood

### Epoch Advancement Strategies

There are three common ways to advance the global epoch:

1. **Periodic timer thread** – a background thread wakes every few milliseconds, checks that each thread’s local epoch is non‑zero, and increments the epoch if safe. This mirrors the Linux kernel’s `rcu_cpu_stall_check`.
2. **Operation‑driven** – any thread that observes its retirement list exceeding a threshold attempts to advance the epoch, as shown in the code above.
3. **Hybrid** – combine a timer for low‑latency reclamation with opportunistic advancement during heavy workloads.

Choosing a strategy influences both latency (how quickly memory is reclaimed) and safety (how likely a stalled thread blocks reclamation). A timer thread can guarantee eventual progress even if all worker threads are idle, but it adds a dedicated OS thread and a wake‑up cost.

### Memory Visibility Guarantees

EBR relies on *release‑acquire* ordering between the write of a node’s pointer and the retirement epoch. When a thread **enters** a critical section, it performs an *acquire* load of `global_epoch`; when it **exits**, it performs a *release* store of zero. This ordering ensures that any write to a node that happens before retirement is visible to any thread that later observes the node’s pointer while holding a matching epoch.

From a formal perspective, EBR provides **sequential consistency for data‑race‑free programs** as long as every thread respects the enter/exit protocol. If a thread skips `enter_critical`, it may observe a node after it has been reclaimed, leading to undefined behavior.

## Thread Safety Guarantees

### What EBR Guarantees

- **No use‑after‑free** for nodes that were retired while all participating threads were in a known epoch.
- **Lock‑free progress** for the *data structure* itself; the reclamation step may block if a thread stalls, but the data structure can still be accessed (albeit with potentially higher memory pressure).
- **Bounded memory usage** *provided* that every thread eventually exits its critical sections. In practice, the bound is proportional to the number of threads × the maximum retirement list size.

### What EBR Does *Not* Guarantee

- **Protection against stuck threads** – a thread that crashes or is pre‑empted indefinitely prevents epoch advancement, causing memory to leak until the process terminates.
- **Deterministic reclamation latency** – reclamation may be delayed by several epochs, typically on the order of milliseconds, which may be unacceptable for real‑time systems.
- **Safety for non‑cooperative code** – if a thread accesses shared memory without announcing its epoch (e.g., via a raw pointer passed from another module), EBR cannot protect it.

These gaps explain why many high‑performance libraries still expose hazard pointers as an alternative: hazard pointers give per‑node safety without requiring global coordination, at the cost of higher per‑operation overhead.

## Trade‑offs Compared to Hazard Pointers

| Aspect | Epoch Based Reclamation | Hazard Pointers |
|--------|------------------------|-----------------|
| **Per‑operation overhead** | O(1) reads/writes of atomic counters; cheap. | O(N) hazard‑pointer stores per access (N = number of protected pointers). |
| **Reclamation latency** | Bounded by epoch period (often a few ms). | Immediate once all hazard pointers are cleared. |
| **Memory overhead** | One retirement list per thread; size grows with workload. | One hazard‑pointer slot per thread per protected pointer; can be larger for complex traversals. |
| **Complexity** | Simpler to integrate into existing lock‑free code; requires only enter/exit calls. | Requires explicit protection/unprotection around every pointer dereference. |
| **Stalled‑thread impact** | Can block reclamation entirely. | Only affects the specific nodes protected by the stalled thread, not global reclamation. |

In practice, the choice often hinges on the *expected contention* and *real‑time requirements*. If you have many short‑lived traversals and a modest thread count, EBR’s low overhead shines. If you need deterministic reclamation (e.g., in a kernel module where memory cannot grow arbitrarily), hazard pointers or RCU’s grace‑period mechanisms may be preferable.

## Performance Considerations

### Cache‑Friendliness

EBR’s per‑thread data structures (epoch variable, retirement list) stay in the thread’s local cache, minimizing false sharing. The global epoch counter is read often but written rarely, reducing coherence traffic. By contrast, hazard pointers involve multiple writes to a shared array of hazard slots, which can generate more cache line bouncing.

### Scalability with Thread Count

The reclamation step must scan *all* thread locals to verify that no thread is still in an older epoch. This scan is O(T) where T is the number of threads. In systems with hundreds of threads, the scan can become a bottleneck. Several mitigation strategies exist:

- **Sharding** – partition threads into groups; each group advances its own epoch, at the cost of weaker guarantees.
- **Lazy scanning** – only scan a subset of threads each time, deferring full verification until later.
- **Epoch‑bitmaps** – maintain a bitmap of active epochs; updating the bitmap can be done with atomic fetch‑or operations, allowing a single check of `bitmap == 0b111` to confirm all epochs have progressed.

These techniques are described in depth in the *Crossbeam* crate documentation for Rust’s epoch implementation, which uses a combination of per‑CPU data and a global epoch counter to scale to thousands of threads.

### Real‑World Benchmarks

A 2023 benchmark suite by Facebook’s Folly library compared EBR, hazard pointers, and a custom lock‑free reference counting scheme across a concurrent hash map workload. The results (summarized in the paper) showed:

- **EBR** achieved ~15% higher throughput than hazard pointers at 64 threads, with average memory usage 2× lower.
- **Hazard pointers** exhibited more stable latency under thread‑stall simulations, where a single thread was paused for 500 ms.
- **Reference counting** lagged behind both in throughput due to atomic increment/decrement overhead on every access.

The full dataset can be inspected in the repository: <https://github.com/facebook/folly/blob/main/benchmark/ebr_vs_hazard.cc>.

## Common Pitfalls and Best Practices

### Pitfall 1: Forgetting to Call `exit_critical`

If a thread returns from a function without resetting its local epoch, the global reclamation algorithm will treat the thread as permanently active in an older epoch. This leads to memory leaks that may only surface under heavy allocation pressure.

**Fix:** Use RAII wrappers (C++), `defer` (Go), or `using` statements (C#) to guarantee `exit_critical` runs even on early returns or exceptions.

```cpp
struct CriticalSection {
    CriticalSection() { enter_critical(); }
    ~CriticalSection() { exit_critical(); }
};
```

### Pitfall 2: Mixing EBR with Non‑Cooperative Code

Passing raw pointers to external libraries that do not participate in epoch announcements can break safety guarantees. For example, handing a node pointer to a logging library that stores it for later printing may cause a use‑after‑free.

**Fix:** Either wrap such interactions in a *protected* region where the caller holds a hazard pointer, or avoid exposing raw pointers altogether.

### Pitfall 3: Over‑tuning the Retirement Threshold

Setting the retirement list size too low forces frequent reclamation attempts, increasing the cost of scanning all thread locals. Conversely, a very high threshold delays reclamation and inflates memory usage.

**Best practice:** Empirically tune the threshold based on workload characteristics; many production systems start with 64–128 entries per thread and adjust after profiling.

### Pitfall 4: Ignoring CPU Affinity

On NUMA systems, threads may migrate between sockets, causing their local epoch data to bounce across memory nodes. This can degrade performance and increase latency of epoch checks.

**Fix:** Pin threads to specific cores or sockets when possible, and store `ThreadInfo` in per‑socket memory pools. The Linux kernel’s RCU implementation uses per‑CPU structures precisely for this reason.

### Pitfall 5: Assuming Epoch Advancement Is Free

Even though `global_epoch` is updated rarely, each advancement requires a *full scan* of all participants. In workloads with frequent retirements, this can dominate CPU time.

**Mitigation:** Batch retirements and only attempt epoch advancement when the retirement list exceeds a sizable threshold (e.g., 1024 nodes). This amortizes the scan cost.

## Key Takeaways

- **EBR provides low‑overhead, lock‑free reclamation** as long as every thread cooperatively announces its epoch.
- **Stalled or crashed threads can halt reclamation**, leading to unbounded memory growth; hazard pointers isolate this risk.
- **Performance scales well up to dozens of threads**, but the O(T) scan for epoch advancement can become a bottleneck at large thread counts.
- **Proper use requires disciplined enter/exit calls**, RAII wrappers, and careful handling of any code that bypasses the epoch protocol.
- **Hybrid approaches** (timer‑driven epoch advancement plus opportunistic reclamation) often deliver the best trade‑off between latency and throughput.

## Further Reading

- [Crossbeam Epoch (Rust)](https://docs.rs/crossbeam-epoch) – detailed design and implementation notes for a production‑grade EBR library.
- [Linux Kernel RCU Documentation](https://www.kernel.org/doc/html/latest/rcu/) – the original inspiration for epoch‑based reclamation in operating systems.
- [Facebook Folly Benchmark Suite](https://github.com/facebook/folly/blob/main/benchmark/ebr_vs_hazard.cc) – source code and results comparing EBR, hazard pointers, and other schemes.