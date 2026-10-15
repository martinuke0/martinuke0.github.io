---
title: "Implementing Work-Stealing Runtimes: Building a Lock-Free Scheduler from Scratch"
date: "2026-10-15T14:00:45.758"
draft: false
tags: ["concurrency", "rust", "systems-programming", "scheduler", "work-stealing", "lock-free"]
description: "Learn how to build a lock-free work-stealing scheduler from scratch, exploring the algorithms and data structures that power modern runtimes like Go and Tokio."
summary: "A deep dive into lock-free work-stealing schedulers, covering the theory, architecture, and a minimal implementation in Rust."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-15-implementing-work-stealing-runtimes-building-a-lock-free-scheduler-from-scratch.svg"
  alt: "Abstract illustration of concurrent threads and data flow"
  caption: ""
  relative: false
---

> **TL;DR** — Work-stealing schedulers enable efficient parallel execution by allowing idle threads to steal tasks from busy threads' queues. This post explores the lock-free algorithms behind systems like Go's goroutine scheduler and Tokio, and walks through building a minimal implementation from scratch using atomic operations and a concurrent deque.

In the world of concurrent programming, the scheduler is the unsung hero. It decides which thread runs which task, and its efficiency can make or break an application's throughput. Traditional centralized schedulers, with a single queue and locks, quickly become bottlenecks as core counts scale. Work-stealing, popularized by systems like Cilk and now embedded in languages like Go and Rust's async runtimes, distributes work across per-thread deques, allowing idle threads to "steal" tasks from overloaded peers. This article dives into the lock-free algorithms that make this possible, and guides you through building a minimal scheduler from scratch.

## The Problem: Why Traditional Schedulers Fall Short

Before diving into work-stealing, it's worth understanding why simpler approaches fail under load. A naive scheduler might use a single shared queue protected by a mutex. Every time a thread needs work, it locks the mutex, dequeues a task, and unlocks. This works fine for low contention, but as the number of threads grows, the mutex becomes a hotspot. Threads spend more time waiting for the lock than doing useful work. Even with atomic operations, a single queue still suffers from cache-line contention: all threads ping-ong on the same memory location, causing cache-coherence traffic that can dominate execution time.

Another approach is to give each thread its own queue, but then how do you balance load? Without a mechanism for idle threads to find work elsewhere, some threads may starve while others are overloaded. Work-stealing solves both problems: it eliminates the central bottleneck by using per-thread deques, and it provides a decentralized load-balancing mechanism through stealing.

## Architecture of a Lock-Free Work-Stealing Scheduler

A lock-free work-stealing scheduler rests on three pillars: a concurrent deque (double-ended queue), a set of worker threads that push and pop from their own deque, and a protocol for thieves to steal from the deque's opposite end. The key insight is that pushing and popping from the bottom of the deque can be done without locks if only the owning thread performs those operations, while stealing from the top requires careful atomic coordination.

### Core Data Structures

The central data structure is the work-stealing deque. In its simplest form, it's a ring buffer with a top and bottom index. The owner thread increments the bottom index when pushing a task and decrements it when popping. Thieves operate on the top index, incrementing it when they successfully steal a task. The challenge is to avoid the ABA problem and ensure that push, pop, and steal operations are linearizable without locks.

In Rust, a common implementation uses `AtomicUsize` for the indices and a `Vec` or fixed-size array for the actual task storage. The deque must handle the case where the buffer is full or empty, and it must ensure that a thief doesn't steal a task that the owner is concurrently popping.

### The Stealing Algorithm

When a worker thread finds its own deque empty, it becomes a thief. It selects a victim—typically another thread's deque at random or in a round-robin fashion—and attempts to steal. The steal operation reads the top index and the bottom index, then tries to pop the task at the top. If the deque appears empty (top >= bottom), the thief moves on. Otherwise, it uses a compare-and-swap (CAS) loop to atomically increment the top index, claiming the task. If the CAS fails, it means another thief or the owner intervened, so the thief retries or moves to a different victim.

The owner's pop operation is simpler: it decrements the bottom index and reads the task. However, it must be careful if a thief is concurrently stealing. If the bottom index is about to be decremented past the top index, the owner might need to reset the indices or coordinate with thieves. The exact protocol varies, but the goal is to ensure that every task is executed exactly once.

### Work Distribution and Load Balancing

Work-stealing naturally balances load because tasks migrate from overloaded threads to idle ones. The frequency of stealing is controlled by a backoff strategy: if a thief repeatedly fails to steal, it might spin for a while, then yield the CPU, or eventually go to sleep. In production runtimes, this is integrated with the OS scheduler—for example, Go's runtime uses a hybrid approach where goroutines that are idle may be parked on a global run queue or stolen by other threads.

The scheduler must also handle the case where all threads are idle. In that case, the runtime should park threads or enter a low-power state until new work arrives. This is often done with futex or similar OS primitives, but the lock-free protocol ensures that the transition to and from the parked state is safe.

## Patterns in Production: Real-World Implementations

Work-stealing isn't a theoretical concept; it's the backbone of several high-performance runtimes. Looking at how production systems implement it provides valuable lessons.

### Go's Goroutine Scheduler

Go's runtime uses a two-level scheduler: each OS thread (M) has a local run queue (P), and goroutines (G) are scheduled from these queues. When a thread's local queue is empty, it attempts to steal from other threads' queues. If stealing fails, it takes goroutines from a global run queue. The stealing algorithm is optimized to reduce contention: thieves use a random selection and back off exponentially on failure. Go also uses a technique called "handoff" where a thread can directly transfer a goroutine to another thread, avoiding the global queue entirely. The source code for Go's scheduler is available in the runtime package, and it's a masterclass in lock-free programming.

### Rust's Tokio

Tokio, the dominant async runtime for Rust, also employs work-stealing. Its scheduler consists of a set of worker threads, each with a local injection queue and a shared injection queue for tasks that arrive from other threads. When a worker is idle, it first checks its local queue, then the shared injection queue, and finally attempts to steal from other workers. Tokio's implementation uses `crossbeam-deque` for the concurrent deques, which provides a proven lock-free algorithm. The stealing protocol in Tokio is designed to minimize false sharing by padding the deques to separate cache lines.

### Cilk and TBB

The Cilk programming language, developed at MIT, pioneered work-stealing in the 1990s. Its runtime uses a stack-based deque where the owner pushes and pops from the bottom, and thieves steal from the top. Cilk's algorithm is notable for its simplicity and its proof of optimal speedup under certain assumptions. Intel's Threading Building Blocks (TBB) adapted these ideas for C++ with its `task_arena` and `task_scheduler` components. TBB's implementation is more complex, supporting nested parallelism and priority tasks, but the core stealing mechanism is similar.

## Building from Scratch: A Minimal Implementation

Now, let's build a minimal lock-free work-stealing scheduler in Rust. We'll focus on the core deque and the worker/stealer protocol. This implementation is simplified for educational purposes—production runtimes add features like task priorities, work stealing from global queues, and thread parking.

### Step 1: The Deque

We'll use a fixed-size ring buffer with `AtomicUsize` indices. The deque stores `usize` tasks for simplicity, but in a real system, these would be function pointers or async tasks.

```rust
use std::sync::atomic::{AtomicUsize, Ordering};
use std::cell::UnsafeCell;

const DEQUE_SIZE: usize = 256; // Must be a power of two for masking

struct Deque {
    bottom: AtomicUsize,
    top: AtomicUsize,
    tasks: UnsafeCell<[usize; DEQUE_SIZE]>,
}

unsafe impl Send for Deque {}
unsafe impl Sync for Deque {}

impl Deque {
    fn new() -> Self {
        Deque {
            bottom: AtomicUsize::new(0),
            top: AtomicUsize::new(0),
            tasks: UnsafeCell::new([0; DEQUE_SIZE]),
        }
    }

    // Owner pushes a task at the bottom.
    fn push(&self, task: usize) {
        let bottom = self.bottom.load(Ordering::Relaxed);
        let top = self.top.load(Ordering::Acquire);
        if bottom - top >= DEQUE_SIZE - 1 {
            panic!("Deque overflow"); // In production, grow or handle gracefully
        }
        unsafe {
            (*self.tasks.get())[bottom & (DEQUE_SIZE - 1)] = task;
        }
        self.bottom.store(bottom + 1, Ordering::Release);
    }

    // Owner pops a task from the bottom.
    fn pop(&self) -> Option<usize> {
        let bottom = self.bottom.load(Ordering::Relaxed);
        if bottom == 0 {
            return None;
        }
        let new_bottom = bottom - 1;
        self.bottom.store(new_bottom, Ordering::Relaxed);
        let task = unsafe { (*self.tasks.get())[new_bottom & (DEQUE_SIZE - 1)] };
        let top = self.top.load(Ordering::Acquire);
        if new_bottom > top {
            return Some(task);
        }
        // If new_bottom == top, the deque might be empty or a thief is stealing.
        self.bottom.store(bottom, Ordering::Relaxed); // Restore on race
        if new_bottom == top {
            // Deque is empty; reset indices to avoid overflow.
            self.bottom.store(0, Ordering::Relaxed);
            self.top.store(0, Ordering::Relaxed);
            return None;
        }
        Some(task)
    }

    // Thief steals a task from the top.
    fn steal(&self) -> Option<usize> {
        let top = self.top.load(Ordering::Relaxed);
        let bottom = self.bottom.load(Ordering::Acquire);
        if top >= bottom {
            return None; // Empty
        }
        let task = unsafe { (*self.tasks.get())[top & (DEQUE_SIZE - 1)] };
        // Attempt to claim the task by incrementing top.
        if self.top.compare_exchange(top, top + 1, Ordering::AcqRel, Ordering::Relaxed).is_ok() {
            Some(task)
        } else {
            None // Another thief or owner intervened; retry elsewhere.
        }
    }
}
```

This deque uses a simplified protocol. The `pop` method can race with `steal`, and the restoration logic is a basic attempt to handle the race. In a production system, you'd use a more robust protocol, such as the one described in the Cilk literature, which involves a more careful CAS loop and index management.

### Step 2: The Worker Threads

Each worker thread owns a `Deque` and repeatedly tries to pop from it. If it fails, it becomes a thief and attempts to steal from other deques.

```rust
use std::thread;
use std::sync::Arc;
use std::time::Duration;

struct Scheduler {
    deques: Arc<Vec<Deque>>,
}

impl Scheduler {
    fn new(num_workers: usize) -> Self {
        let mut deques = Vec::with_capacity(num_workers);
        for _ in 0..num_workers {
            deques.push(Deque::new());
        }
        Scheduler {
            deques: Arc::new(deques),
        }
    }

    fn run(&self) {
        let mut handles = Vec::new();
        for worker_id in 0..self.deques.len() {
            let deques = Arc::clone(&self.deques);
            handles.push(thread::spawn(move || {
                let my_deque = &deques[worker_id];
                loop {
                    // Try to pop from own deque.
                    if let Some(task) = my_deque.pop() {
                        // Execute the task (for this example, just print).
                        println!("Worker {} executing task {}", worker_id, task);
                        continue;
                    }
                    // Attempt to steal from others.
                    let mut stole = false;
                    for i in 0..deques.len() {
                        let victim = &deques[(worker_id + i) % deques.len()];
                        if let Some(task) = victim.steal() {
                            println!("Worker {} stole task {} from worker {}", worker_id, task, (worker_id + i) % deques.len());
                            stole = true;
                            break;
                        }
                    }
                    if !stole {
                        // No work found; back off or sleep.
                        thread::sleep(Duration::from_millis(1));
                    }
                }
            }));
        }
        for h in handles {
            h.join().unwrap();
        }
    }
}
```

In a real runtime, the loop would be integrated with the event loop or async runtime, and the sleep would be replaced with a parking mechanism. The key is the pattern: pop, steal, back off.

### Step 3: The Stealing Protocol

The stealing protocol in the code above is straightforward: iterate over all deques and attempt to steal. In production, you'd use a random start index to reduce contention, and you'd implement exponential backoff. For example, after a failed steal, you might spin for a few iterations, then yield the CPU, and eventually park the thread if no work is found for an extended period.

The protocol must also handle the case where a thief steals a task that the owner is about to pop. The `compare_exchange` in `steal` ensures that only one thread claims the task. However, the owner's `pop` might decrement the bottom index and then find that a thief has already taken the task at that index. The restoration logic in `pop` is a simplified way to handle this; a more robust approach uses a CAS loop to reset the bottom index only if it hasn't changed.

## Key Takeaways

- Work-stealing eliminates the central bottleneck of traditional schedulers by distributing work across per-thread deques.
- Lock-free deques rely on atomic operations and careful index management to allow concurrent push, pop, and steal without locks.
- Production runtimes like Go and Tokio have refined stealing protocols with backoff, random victim selection, and integration with OS parking.
- Building a minimal scheduler from scratch is feasible with a few hundred lines of Rust, but production systems add complexity for performance and correctness.
- The stealing algorithm must handle races between owners and thieves; the core invariant is that each task is executed exactly once.

## Further Reading

- [Go Runtime Scheduler Source](https://golang.org/src/runtime/proc.go) — The implementation of work-stealing in Go's scheduler, with detailed comments on the stealing protocol.
- [Tokio Runtime Design](https://tokio.rs/tokio/runtime/scheduler) — An overview of Tokio's work-stealing scheduler and its integration with async tasks.
- [Cilk: A Language for Multithreaded Programming](https://www.cilk.com/) — The original paper and resources on Cilk, which pioneered work-stealing in the 1990s.