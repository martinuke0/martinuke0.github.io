---
title: "How Epoch-Based Reclamation Avoids the Stalled Pointer Problem"
date: "2026-05-17T01:00:49.643"
draft: false
tags: ["concurrency", "memory-management", "epoch-reclamation", "lock-free", "systems-programming"]
description: "Explore how epoch‑based reclamation (EBR) eliminates the stalled pointer problem in lock‑free data structures, with concrete examples, performance analysis, and best‑practice guidance."
summary: "A deep dive into epoch‑based reclamation, showing why it solves the stalled pointer issue and how to apply it safely in high‑performance concurrent code."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-how-epoch-based-reclamation-avoids-the-stalled-pointer-problem.png"
  alt: "Illustration of overlapping epochs in concurrent memory reclamation."
  caption: ""
  relative: false
---

> **TL;DR** — Epoch‑based reclamation (EBR) sidesteps the stalled pointer problem by tying object lifetimes to globally visible epochs. When all threads have moved past an epoch, memory from that epoch can be reclaimed safely, eliminating the need for per‑pointer hazard tracking and enabling deterministic, low‑overhead reclamation in lock‑free structures.

Concurrent programs that manipulate shared data without locks must solve a subtle but critical issue: how to free memory that might still be accessed by another thread. The *stalled pointer problem* arises when a thread lingers on an old pointer while other threads have already retired the underlying object. Traditional solutions such as hazard pointers require per‑pointer bookkeeping, which can be costly and error‑prone. Epoch‑based reclamation (EBR) offers a different approach: it groups reclamation decisions into *epochs* that advance only when every thread has indicated it is no longer using the previous epoch. This article explains the stalled pointer problem in detail, walks through the mechanics of EBR, and shows why the epoch model guarantees safe reclamation while keeping overhead low.

## The Stalled Pointer Problem

### What it is

In lock‑free data structures, threads typically read a pointer to a node, perform some work, and then possibly remove the node from the structure. The removal step often includes *retiring* the node—marking it for later reclamation—but the retiring thread cannot free the memory immediately because another thread might still hold a reference.

A *stalled pointer* occurs when a thread reads a pointer, then gets descheduled (or simply takes a long time) before it can finish using the object. Meanwhile, other threads may have completed the removal and reclaimed the memory. When the stalled thread finally resumes and dereferences the stale pointer, it accesses freed memory, leading to undefined behavior, crashes, or subtle data corruption.

### Why it matters

The problem is not just theoretical; real‑world systems have observed crashes due to stalled pointers in production lock‑free queues, stacks, and hash tables. The difficulty lies in the fact that lock‑free algorithms deliberately avoid global synchronization, so there is no natural point at which all threads can be guaranteed to have finished using a retired object.

If a reclamation scheme fails to account for stalled pointers, developers must resort to heavyweight techniques such as global quiescent points, thread pauses, or garbage collection, all of which erode the performance benefits of lock‑free designs.

## Epoch-Based Reclamation (EBR) Fundamentals

### Epoch concept

An *epoch* is a logical time interval shared by all threads. Think of it as a generation counter that advances monotonically. When a thread begins an operation that might touch shared nodes, it announces the current global epoch as the *active epoch* for that operation. The thread records this epoch in a thread‑local slot that is visible to other threads.

When a thread removes a node, it does not free the memory immediately. Instead, it **retires** the node by placing it into a per‑thread *retire list* together with the current global epoch. The node is therefore associated with the epoch in which it was retired.

### Global epoch advancement

A dedicated *epoch manager* (often the same thread that performs reclamation) periodically attempts to advance the global epoch. Advancement is allowed only when **every** thread’s announced active epoch is at least the current epoch. In other words, no thread is still operating in the old epoch. This condition guarantees that all pointers that could have been observed in the old epoch are no longer reachable.

The algorithm for advancing the epoch typically looks like this (C++‑style pseudocode):

```cpp
void try_advance_epoch() {
    uint64_t cur = global_epoch.load(std::memory_order_acquire);
    for (auto &slot : thread_epochs) {
        uint64_t announced = slot.load(std::memory_order_acquire);
        if (announced < cur) {
            // At least one thread is still in the old epoch.
            return;
        }
    }
    // All threads have moved on; safe to advance.
    global_epoch.store(cur + 1, std::memory_order_release);
}
```

### Thread‑local epochs

Each thread maintains a small, lock‑free data structure (often a single `std::atomic<uint64_t>`) that holds its currently announced epoch. When a thread starts a *critical section*—the period during which it may dereference shared pointers—it writes the current global epoch into this slot. When it exits the critical section, it writes a sentinel value (e.g., `UINT64_MAX`) to indicate it is quiescent.

Because the slot is read by the epoch manager without any lock, the overhead per entry/exit is just a couple of atomic stores, typically a few nanoseconds on modern CPUs.

## How EBR Solves the Stalled Pointer Problem

### Deferred reclamation using epochs

When a node is retired, it is placed into the retire list together with the epoch number `e_retire`. The node cannot be reclaimed until the global epoch has advanced **twice** beyond `e_retire`. The reason for two epochs is simple:

1. **First advancement** ensures that every thread that *might* have observed the node in epoch `e_retire` has moved to a later epoch.
2. **Second advancement** guarantees that any thread that was still in the *previous* epoch when the node was retired has also progressed past the epoch in which it could have observed the node.

This two‑epoch grace period is sufficient to cover any stalled pointer. Even if a thread was descheduled right after reading the pointer, it will be forced to announce the epoch before it can resume dereferencing, and the reclamation will wait until that epoch has passed.

### Safe memory reuse guarantees

The safety argument can be expressed formally:

*Lemma*: If a node `N` is retired in epoch `e`, and the global epoch has advanced to `e + 2`, then no thread holds a pointer to `N`.

*Proof Sketch*:  
- Any thread that could have observed `N` must have been in epoch `e` or earlier when it read the pointer.  
- Advancement to `e + 1` requires all threads to have announced an epoch ≥ `e + 1`, meaning none are still in epoch `e`.  
- Advancement to `e + 2` further requires all threads to have announced ≥ `e + 2`, so no thread is still in epoch `e + 1`.  
- Therefore, no thread can be holding a pointer that was acquired in epoch `e` or `e + 1`. ∎

Because reclamation only occurs after two epoch increments, the algorithm eliminates the stalled pointer problem without needing per‑pointer hazard tracking.

### Example: lock‑free stack

Consider a simple lock‑free stack implemented with a singly linked list. The push operation performs an atomic `compare_exchange_strong` on the head pointer, while pop removes the head and returns the value.

```cpp
struct Node {
    int value;
    Node* next;
};

std::atomic<Node*> head{nullptr};
thread_local std::vector<std::pair<Node*, uint64_t>> retire_list;
thread_local std::atomic<uint64_t> my_epoch{UINT64_MAX};

void enter_critical() {
    my_epoch.store(global_epoch.load(std::memory_order_acquire),
                   std::memory_order_release);
}

void exit_critical() {
    my_epoch.store(UINT64_MAX, std::memory_order_release);
}

void push(int v) {
    Node* n = new Node{v, nullptr};
    enter_critical();
    Node* old = head.load(std::memory_order_relaxed);
    do {
        n->next = old;
    } while (!head.compare_exchange_weak(old, n));
    exit_critical();
}

std::optional<int> pop() {
    enter_critical();
    Node* old = head.load(std::memory_order_relaxed);
    while (old && !head.compare_exchange_weak(old, old->next));
    exit_critical();
    if (!old) return std::nullopt;

    // Retire the removed node.
    retire_list.emplace_back(old, global_epoch.load(std::memory_order_acquire));
    reclaim();   // May free nodes whose epoch is safe.
    return old->value;
}
```

The `reclaim()` function scans `retire_list` and frees any node whose stored epoch is ≤ `global_epoch - 2`. Because every thread announces its epoch on entry and clears it on exit, any stalled thread that was paused after reading `old` will still have its `my_epoch` set to the epoch in which it observed `old`. The reclamation will wait until that epoch has passed twice, guaranteeing safety.

## Performance Considerations

### Overhead analysis

EBR’s runtime cost consists of three main components:

1. **Critical‑section entry/exit** – two atomic stores per operation (≈ 5‑10 ns on x86_64).  
2. **Retire list management** – appending a pointer and epoch to a thread‑local vector (amortized O(1)).  
3. **Epoch advancement** – a periodic scan of all thread slots; the scan cost is O(N_threads) but is performed infrequently (e.g., every 1000 operations).

Empirical studies (see the benchmarks in the original paper by Michael and Scott) show that EBR adds less than 2 % latency to typical lock‑free push/pop workloads, far lower than the per‑pointer overhead of hazard pointers (≈ 10‑15 %).

### Comparison with Hazard Pointers

| Aspect                | Epoch‑Based Reclamation                         | Hazard Pointers                                 |
|-----------------------|-------------------------------------------------|-------------------------------------------------|
| Memory safety         | Guarantees after two epoch advances            | Guarantees per‑pointer after explicit hazard set |
| Per‑operation cost    | 2 atomic stores + vector push                  | 1–2 hazard slot writes + scan of hazard list    |
| Scalability           | O(N_threads) epoch scan, cheap per thread       | O(N_hazards) per reclamation, can grow large   |
| Stalled pointer safety| Built‑in via two‑epoch grace period             | Requires each thread to publish hazards timely |
| Complexity            | Simple global epoch counter + thread slots      | Requires careful hazard management per object  |

In practice, EBR shines for workloads where the number of retired objects far exceeds the number of concurrent threads, such as high‑throughput queues or stacks. Hazard pointers are still useful when reclamation must be *immediate* after a specific pointer is no longer needed, but they incur higher bookkeeping costs.

## Common Pitfalls and Correct Usage

### Forgetting to quiesce

A thread must set its epoch slot to the sentinel value (`UINT64_MAX` or similar) whenever it is *not* inside a critical section. Failure to do so makes the epoch manager believe the thread is still active in an old epoch, preventing global advancement and causing memory leaks. A common pattern is to wrap critical sections in a RAII guard:

```cpp
class EpochGuard {
public:
    EpochGuard() {
        my_epoch.store(global_epoch.load(std::memory_order_acquire),
                       std::memory_order_release);
    }
    ~EpochGuard() {
        my_epoch.store(UINT64_MAX, std::memory_order_release);
    }
};
```

Then use `EpochGuard guard;` at the start of any operation that accesses shared nodes.

### Over‑advancing epochs

If the epoch manager advances the global epoch too aggressively—e.g., without confirming that *all* threads have announced the current epoch—reclamation may occur while a thread still holds a pointer from the previous epoch, re‑introducing the stalled pointer bug. The check must be *strict*: every thread’s announced epoch must be **greater than or equal to** the current epoch before increment.

### Unbounded retire lists

Although EBR delays reclamation only for two epochs, a thread that generates many retired objects without invoking `reclaim()` can cause its retire list to grow unboundedly. A practical implementation periodically calls `reclaim()` after a fixed number of retirements (e.g., every 64 nodes) or when the list size exceeds a threshold. This keeps memory usage predictable.

## Key Takeaways

- **Epoch‑based reclamation ties object lifetimes to globally visible epochs**, eliminating the need for per‑pointer hazard tracking.
- **Two‑epoch grace periods** guarantee that any stalled pointer will be detected before memory is reclaimed, solving the stalled pointer problem.
- **Critical‑section entry/exit costs are minimal** (two atomic stores), making EBR suitable for high‑throughput lock‑free data structures.
- **Proper quiescence handling** (clearing the thread’s epoch slot) is essential; forgetting it stalls epoch advancement and leads to memory leaks.
- **EBR scales better than hazard pointers** when the number of threads is modest and the volume of retired objects is large, but it requires periodic global scans.

## Further Reading

- [Epoch‑based reclamation (Wikipedia)](https://en.wikipedia.org/wiki/Epoch-based_reclamation) – Overview of the algorithm and its variants.  
- [Boost Smart Pointers – Epoch Reclamation](https://www.boost.org/doc/libs/1_81_0/doc/html/boost/smart_ptr/epoch_reclamation.html) – Reference implementation details in the Boost library.  
- [The Art of Multiprocessor Programming – Chapter on Memory Reclamation](https://mitpress.mit.edu/9780262033848) – Classic textbook treatment of EBR, hazard pointers, and related techniques.  

---