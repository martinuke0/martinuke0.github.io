---
title: "Solving Data Races with Lock‑Free Atomic Compare‑and‑Swap"
date: "2026-05-14T12:00:36.280"
draft: false
tags: ["concurrency","lock-free","atomic","compare-and-swap","rust"]
description: "Learn how lock‑free atomic compare‑and‑swap eliminates data races, with practical C++ and Rust examples, memory‑ordering nuances, and performance tips."
summary: "A deep dive into lock‑free programming using atomic compare‑and‑swap, covering theory, implementation patterns, and real‑world best practices."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-solving-data-races-with-lockfree-atomic-compareandswap.png"
  alt: "Illustration of two threads exchanging data atomically."
  caption: ""
  relative: false
---

> **TL;DR** — Atomic compare‑and‑swap (CAS) lets you build lock‑free data structures that avoid classic data races. By mastering memory‑ordering flags, handling the ABA problem, and profiling contention, you can write high‑performance concurrent code in C++ or Rust without the overhead of mutexes.

Multithreaded programs are plagued by data races, subtle bugs that appear only under specific interleavings. Traditional lock‑based synchronization removes the race but often introduces contention, priority inversion, and cache‑line bouncing. Modern CPUs expose low‑level atomic primitives that, when used correctly, let you design lock‑free algorithms that scale better and stay responsive even under heavy load. This article walks through the theory behind CAS, shows concrete implementations of a lock‑free stack in both C++ and Rust, and highlights the practical considerations—memory ordering, the ABA problem, and performance profiling—that turn a textbook example into production‑ready code.

## The Problem: Data Races in Multithreaded Code

### What a data race looks like
A data race occurs when two threads access the same memory location concurrently, at least one access is a write, and there is no synchronization ordering them. Consider a naïve counter:

```cpp
int counter = 0;

void increment() {
    counter++;   // read-modify-write without protection
}
```

If two threads call `increment()` simultaneously, the final value may be one instead of two because each thread reads the old value, increments it locally, and writes back, overwriting the other's update. The C++ memory model defines this as undefined behavior, and the bug can manifest sporadically, making it hard to reproduce.

### Why traditional locks can be overkill
Mutexes serialize access, guaranteeing correctness:

```cpp
std::mutex m;

void increment_locked() {
    std::lock_guard<std::mutex> lock(m);
    ++counter;
}
```

While safe, locks introduce latency (the thread may block) and cache‑coherency traffic (the lock’s cache line bounces between cores). In high‑frequency paths—e.g., per‑packet processing in a network stack—this overhead can dominate latency budgets. Moreover, lock contention can cause convoy effects, where many threads line up behind a single holder, reducing throughput dramatically.

## Atomic Operations: The Building Blocks

### Memory model basics
Modern CPUs implement a relaxed memory model: operations may be reordered unless explicit barriers are used. C++20 and Rust expose this via `std::atomic` and `core::sync::atomic`, respectively. Each atomic operation can be annotated with a memory order:

- `memory_order_relaxed` – no ordering constraints.
- `memory_order_acquire` – prevents later reads/writes from moving before the operation.
- `memory_order_release` – prevents earlier reads/writes from moving after the operation.
- `memory_order_acq_rel` – combines acquire and release.
- `memory_order_seq_cst` – strongest, global total order.

Choosing the weakest ordering that still provides correctness yields better performance because it reduces the amount of fence instructions the compiler emits.

### Compare‑and‑Swap (CAS) explained
CAS is an atomic read‑modify‑write primitive. It reads a memory location, compares it to an expected value, and, only if they match, writes a new value. The operation returns whether the swap succeeded, allowing the caller to retry if another thread intervened.

In C++:

```cpp
std::atomic<int*> head{nullptr};

bool try_push(int* node) {
    int* old_head = head.load(std::memory_order_relaxed);
    node->next = old_head;
    // Attempt to replace head with node
    return head.compare_exchange_weak(old_head, node,
                                      std::memory_order_release,
                                      std::memory_order_relaxed);
}
```

`compare_exchange_weak` may fail spuriously even when `old_head` matches, which is acceptable for loops that retry. The strong variant (`compare_exchange_strong`) only fails on true mismatches but can be slower on some architectures.

## Implementing Lock‑Free Structures with CAS

### A simple lock‑free stack in C++
A classic example is a singly‑linked stack where `head` is an atomic pointer. Push and pop are built around CAS loops.

```cpp
#include <atomic>
#include <memory>

struct Node {
    int value;
    Node* next;
};

class LockFreeStack {
    std::atomic<Node*> head{nullptr};

public:
    void push(int v) {
        Node* n = new Node{v, nullptr};
        while (true) {
            Node* cur = head.load(std::memory_order_acquire);
            n->next = cur;
            if (head.compare_exchange_weak(cur, n,
                                           std::memory_order_release,
                                           std::memory_order_acquire))
                break;               // success
            // on failure, cur now holds the observed head; loop retries
        }
    }

    std::unique_ptr<Node> pop() {
        while (true) {
            Node* cur = head.load(std::memory_order_acquire);
            if (!cur) return nullptr; // empty
            Node* nxt = cur->next;
            if (head.compare_exchange_weak(cur, nxt,
                                           std::memory_order_acquire,
                                           std::memory_order_relaxed))
                return std::unique_ptr<Node>(cur);
            // otherwise another thread interfered; retry
        }
    }
};
```

Key points:

- The `head` load uses `memory_order_acquire` to ensure that once a thread sees a node, it also sees the node’s fields (`value`, `next`) correctly.
- The successful CAS uses `memory_order_release` on push, guaranteeing that the store of `n->next` happens before the head update becomes visible.
- The loop retries on failure, which can be caused by contention or spurious failure.

### Porting the pattern to Rust
Rust’s `std::sync::atomic::AtomicPtr` mirrors the C++ API, but ownership rules require careful handling. Below is a minimal lock‑free stack using `Arc` for safe memory reclamation (the example skips hazard pointers for brevity).

```rust
use std::sync::atomic::{AtomicPtr, Ordering};
use std::ptr;
use std::sync::Arc;

struct Node<T> {
    value: T,
    next: *mut Node<T>,
}

pub struct LockFreeStack<T> {
    head: AtomicPtr<Node<T>>,
}

impl<T> LockFreeStack<T> {
    pub fn new() -> Self {
        Self {
            head: AtomicPtr::new(ptr::null_mut()),
        }
    }

    pub fn push(&self, value: T) {
        let new = Box::into_raw(Box::new(Node {
            value,
            next: ptr::null_mut(),
        }));

        loop {
            let cur = self.head.load(Ordering::Acquire);
            unsafe { (*new).next = cur; }
            if self.head
                .compare_exchange_weak(
                    cur,
                    new,
                    Ordering::Release,
                    Ordering::Acquire,
                )
                .is_ok()
            {
                break;
            }
            // CAS failed – retry
        }
    }

    pub fn pop(&self) -> Option<T> {
        loop {
            let cur = self.head.load(Ordering::Acquire);
            if cur.is_null() {
                return None;
            }
            let nxt = unsafe { (*cur).next };
            if self.head
                .compare_exchange_weak(
                    cur,
                    nxt,
                    Ordering::Acquire,
                    Ordering::Relaxed,
                )
                .is_ok()
            {
                // SAFETY: we own `cur` now; convert back to Box and extract value
                let boxed = unsafe { Box::from_raw(cur) };
                return Some(boxed.value);
            }
            // otherwise retry
        }
    }
}
```

Rust’s strict lifetimes prevent dangling pointers, but manual reclamation (e.g., epoch‑based reclamation) is still required for long‑running systems. The code above works for short‑lived examples or when the stack is cleared before shutdown.

### Handling the ABA problem
CAS can be fooled by the ABA scenario: a thread reads `A`, another thread changes the value to `B` and back to `A`, and the first thread’s CAS succeeds even though the state changed in between. In lock‑free stacks, this manifests when a node is popped, reused, and pushed again.

A common mitigation is to augment the pointer with a version counter, forming a *tagged pointer* (also called a *double‑width CAS*). In C++20 you can use `std::atomic<std::uintptr_t>` and pack the counter into the low bits, assuming alignment leaves those bits free.

```cpp
struct TaggedPtr {
    Node* ptr;
    std::uint16_t tag;
};

std::atomic<std::uint64_t> head_tagged{0};

bool push(Node* n) {
    while (true) {
        std::uint64_t cur = head_tagged.load(std::memory_order_acquire);
        TaggedPtr cur_tp{ reinterpret_cast<Node*>(cur & ~0xFFFFULL),
                          static_cast<std::uint16_t>(cur & 0xFFFFULL) };
        n->next = cur_tp.ptr;
        std::uint64_t new_val = (reinterpret_cast<std::uint64_t>(n) & ~0xFFFFULL)
                               | ((cur_tp.tag + 1) & 0xFFFF);
        if (head_tagged.compare_exchange_weak(cur, new_val,
                                               std::memory_order_release,
                                               std::memory_order_relaxed))
            return true;
    }
}
```

The extra tag guarantees that even if the pointer value cycles back to `A`, the tag will differ, causing the CAS to fail and forcing a retry. Languages like Rust provide the `crossbeam::epoch` crate, which supplies safe memory reclamation and automatically embeds epoch counters to avoid ABA without manual tagging.

## Performance Considerations

### Memory ordering flags
Choosing the right ordering is a performance knob. `memory_order_seq_cst` enforces a global total order, which can serialize unrelated operations on different variables. In most lock‑free data structures, a combination of `acquire` on loads and `release` on successful stores is sufficient. Profiling with `perf record -e cycles,instructions` on Linux often shows a measurable reduction in retired cycles when switching from `seq_cst` to `acquire/release`.

### Contention and back‑off strategies
When many threads contend for the same CAS target, the hardware may experience cache‑line ping‑pong, inflating latency. Exponential back‑off mitigates this:

```cpp
int backoff = 1;
while (!head.compare_exchange_weak(cur, new, ...)) {
    std::this_thread::yield();            // give scheduler a chance
    std::this_thread::sleep_for(std::chrono::nanoseconds(backoff));
    backoff = std::min(backoff * 2, 1024);
}
```

The back‑off window grows until a ceiling, reducing bus traffic during hot periods. Empirical studies (e.g., in the paper “Scalable Synchronization on Multiprocessors” by Herlihy & Shavit) confirm that modest back‑off yields the best throughput for lock‑free queues.

### Benchmarks and profiling tips
A realistic benchmark should simulate contention, e.g., by spawning `N = std::thread::hardware_concurrency()` threads each performing millions of push/pop operations on a shared stack. Measure:

- **Throughput** (`ops/s`).
- **Latency** (median time per operation via `std::chrono::steady_clock`).
- **Cache‑miss rate** (`perf stat -e cache-misses`).

When comparing a lock‑free stack to a mutex‑protected one, expect the lock‑free version to scale linearly up to the number of physical cores, while the mutex version plateaus early due to lock contention.

## Common Pitfalls and Debugging Techniques

### Mis‑aligned atomics
Atomic operations require the underlying object to be naturally aligned for the target width (e.g., 8‑byte alignment for 64‑bit atomics). Declaring an atomic inside a packed struct can trigger undefined behavior. Use `alignas(8)` or place atomics at the top level.

```cpp
struct alignas(8) Packed {
    char c;
    std::atomic<std::uint64_t> counter; // safe
};
```

### Spurious failures
`compare_exchange_weak` may fail even when the expected value matches. This is not an error; loops must be prepared to retry. Using `compare_exchange_strong` eliminates spurious failures but can be slower on architectures like ARM where the weak version maps directly to the hardware instruction.

### Tools (ThreadSanitizer, perf)
- **ThreadSanitizer (TSan)**: Run `clang++ -fsanitize=thread -g` to detect data races that you may have missed. It instruments atomic operations and can flag misuse of memory orderings.
- **perf**: Use `perf record -g` to capture call stacks of heavy CAS loops, then `perf report` to see where most cycles are spent.
- **Valgrind’s DRD**: Another race detector focusing on lock‑based code, useful when mixing lock‑free and lock‑based parts.

## Key Takeaways
- **CAS is the cornerstone of lock‑free programming**; it atomically validates and updates a location, enabling safe concurrent mutation without mutexes.
- **Memory ordering matters**: Use the weakest ordering (`acquire`/`release`) that still guarantees correctness to avoid unnecessary fences.
- **ABA must be addressed** with tagged pointers, epoch‑based reclamation, or hazard pointers; otherwise, subtle bugs can slip through under high contention.
- **Back‑off and contention management** keep the system scalable; exponential back‑off reduces cache‑line thrashing.
- **Profiling is essential**; measure throughput, latency, and cache behavior to verify that the lock‑free design actually outperforms a lock‑based alternative in your workload.
- **Debugging tools** like ThreadSanitizer and `perf` help surface hidden races and performance hot spots early in development.

## Further Reading
- [C++ Atomic Operations and Memory Model (cppreference)](https://en.cppreference.com/w/cpp/atomic)  
- [Rust’s Atomic Types (Rustonomicon)](https://doc.rust-lang.org/nomicon/atomics.html)  
- [Herlihy & Shavit – The Art of Multiprocessor Programming (book)](https://www.cs.tau.ac.il/~shanir/CS/212/notes/ArtOfMultiprocessorProgramming.pdf)  
- [Linux `perf` Tool Documentation](https://perf.wiki.kernel.org/index.php/Main_Page)  
- [ThreadSanitizer Introduction (Clang Docs)](https://clang.llvm.org/docs/ThreadSanitizer.html)