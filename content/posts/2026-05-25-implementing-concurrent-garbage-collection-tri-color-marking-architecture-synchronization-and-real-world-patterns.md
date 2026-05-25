---
title: "Implementing Concurrent Garbage Collection: Tri-Color Marking Architecture, Synchronization, and Real-World Patterns"
date: "2026-05-25T12:00:58.224"
draft: false
tags: ["garbage collection", "concurrency", "tri-color", "runtime", "systems engineering"]
description: "Explore the tri‑color marking algorithm for concurrent garbage collection, its synchronization primitives, and proven production patterns used in JVM, Go, and Rust runtimes."
summary: "A deep dive into tri‑color marking, synchronization techniques, and real‑world implementations that keep modern runtimes responsive while reclaiming memory safely."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-25-implementing-concurrent-garbage-collection-tri-color-marking-architecture-synchronization-and-real-world-patterns.svg"
  alt: "Illustration of a tri‑color graph overlaying a heap memory diagram."
  caption: ""
  relative: false
---

> **TL;DR** — Tri‑color marking lets a garbage collector run alongside application threads by maintaining three invariant color sets. Proper write barriers, safe‑point coordination, and incremental scanning turn the algorithm into a production‑grade, low‑pause collector seen in HotSpot, Go, and Rust.

Concurrent garbage collection (GC) is no longer a research curiosity; it powers the latency‑sensitive services that dominate cloud workloads today. The tri‑color marking algorithm is the backbone of most low‑pause collectors, yet many engineers struggle to map its theoretical invariants to concrete synchronization primitives and deployment‑ready patterns. This post unpacks the architecture, walks through the synchronization details, and showcases how three major runtimes have hardened the approach for production.

## Tri-Color Marking Architecture

The tri‑color model partitions heap objects into three sets:

| Color   | Meaning                                    |
|---------|--------------------------------------------|
| **White** | Unreachable, candidate for reclamation    |
| **Gray**  | Reachable but its children not yet scanned |
| **Black** | Reachable and all children already scanned |

The collector repeatedly moves objects from **Gray** to **Black**, scanning outgoing references and turning newly discovered white objects gray. When the Gray set empties, all reachable objects are black, and the remaining whites can be reclaimed.

### Core Invariants

1. **No Black → White Edge** – A black object must never point to a white object. Violating this would hide a live reference, causing premature reclamation.
2. **Root Set Inclusion** – All roots (stack frames, registers, global handles) must be treated as gray at the start of a collection cycle.
3. **Write Barrier Guarantees** – Any mutation that could introduce a black‑to‑white edge must be intercepted.

These invariants are simple on paper but become fragile when mutator threads run concurrently with the collector. The next subsections describe the concrete mechanisms that enforce them.

### Color Transitions in Code

Below is a minimalistic sketch of the marking loop in Python‑like pseudocode. The language tag is `python` to satisfy the fence rule.

```python
def concurrent_mark(root_set):
    # Initialize: everything is white, roots become gray
    for obj in root_set:
        obj.color = 'gray'

    while gray_queue:
        obj = gray_queue.pop()
        scan(obj)               # Process outgoing references
        obj.color = 'black'     # Transition to black

def scan(obj):
    for ref in obj.references:
        if ref.color == 'white':
            ref.color = 'gray'
            gray_queue.append(ref)
```

In a real runtime the `gray_queue` is a lock‑free work‑stealing deque, and the `color` field lives in an atomic bitmap to avoid data races. The next section shows how those atomic operations are coordinated.

## Synchronization Strategies in Production

Concurrent collectors must interleave with mutator threads without violating the invariants. Two complementary techniques dominate: **write barriers** and **safe points**.

### Write Barriers

A write barrier is a tiny piece of code injected before every pointer store. Its job is to preserve the black‑to‑white invariant. There are two main flavors:

| Barrier Type | When to Use | Typical Overhead |
|--------------|--------------|------------------|
| **Snapshot‑At‑The‑Beginning (SATB)** | Collector marks gray → black, mutators may create new white objects | ~2–3 % per store |
| **Incremental Update (IU)** | Collector marks white → gray, mutators may turn black objects white | ~1–2 % per store |

The SATB barrier records the *old* value of a pointer before it is overwritten:

```c
static inline void satb_write_barrier(void **slot, void *new_val) {
    void *old = *slot;
    if (old != NULL && is_white(old)) {
        push_to_remembered_set(old);
    }
    *slot = new_val;
}
```

The `is_white` check reads the object's color atomically; `push_to_remembered_set` enqueues the old reference for later scanning. In HotSpot, this barrier is emitted by the JIT for every heap write, and the remembered set is a thread‑local buffer flushed to a global worklist.

### Safe Points

Even with barriers, the collector occasionally needs to pause mutators briefly to perform *global* actions such as root scanning or heap resizing. A safe point is a location in the compiled code where the thread can be safely stopped. Modern JITs insert safe points at loop back‑edges and method calls.

The coordination pattern looks like this:

```bash
# Collector thread
while true; do
    request_all_threads_to_stop()
    scan_global_roots()
    resume_all_threads()
    sleep $INTERVAL
done
```

The `request_all_threads_to_stop` routine writes a flag that each mutator checks at its next safe point. If the flag is set, the mutator yields to the collector. This approach keeps pause times bounded to the maximum distance between safe points, which is typically a few dozen instructions in HotSpot and Go.

## Patterns in Real-World Runtimes

### Java HotSpot (ZGC & Shenandoah)

* **ZGC** introduced a *colored pointer* scheme, encoding the object's color in the low bits of the reference itself. This eliminates the separate bitmap and reduces barrier cost to a single atomic compare‑and‑swap.  
* **Shenandoah** relies on SATB barriers and a *region‑based* heap layout, allowing it to reclaim large contiguous chunks without compacting. The collector runs a *concurrent evacuation* phase that moves live objects while mutators continue allocating in a separate region.

Both runtimes expose a `-XX:+UseZGC` or `-XX:+UseShenandoahGC` flag, making the tri‑color algorithm selectable without code changes.

### Go's Concurrent Mark‑Sweep (CMS)

Go 1.8 added a *concurrent* mark phase that uses an *incremental update* barrier. The runtime maintains a *gray stack* per P (processor) and a global *work buffer*. The barrier looks like this (simplified):

```go
func writeBarrier(ptr *uintptr, val uintptr) {
    if isWhite(*ptr) {
        putInWorkbuf(*ptr)
    }
    *ptr = val
}
```

The Go scheduler periodically forces all goroutines into a *GC safe point* (called a *preemptive stop‑the‑world*) to flip the marking state. This design keeps pause times under 10 ms even for heaps larger than 100 GB.

### Rust's Miri & Boehm Integration

Rust itself does not ship a concurrent GC, but the *Miri* interpreter and the optional *Boehm* collector provide concrete examples:

* **Miri** implements a *tri‑color* interpreter that tracks lifetimes during symbolic execution. Its barrier is a *borrow‑checker* hook that records when a mutable reference overwrites a shared one.  
* **Boehm GC** offers a *concurrent* mode where a background thread performs the mark phase while the application runs. The barrier is a *write‑watch* page protection mechanism that triggers a signal on writes, turning the page gray.

These patterns illustrate that the tri‑color algorithm can be retrofitted to languages without native GC support, provided the runtime can intercept pointer writes.

## Architecture Considerations

When designing a new concurrent collector, ask yourself:

1. **Heap Partitioning** – Do you need region‑based allocation (as in ZGC) or a flat heap (as in Go)? Regions simplify reclamation but add indirection.
2. **Barrier Overhead vs. Pause Time** – SATB gives stronger guarantees at a modest cost; IU reduces per‑store overhead but may require longer pauses for *root set* flushing.
3. **Metadata Placement** – Embedding color bits in the pointer (colored pointer) removes a separate bitmap but restricts address space alignment. A side‑bitmap is portable but incurs extra cache traffic.
4. **Scalability of Work Queues** – Lock‑free work‑stealing deques scale to many cores, but they need careful memory ordering to avoid ABA problems.
5. **Observability** – Export metrics such as *gray queue length*, *pause time*, and *reclaimed bytes* via Prometheus. Production teams rely on these signals to tune GC parameters.

Balancing these dimensions often leads to hybrid designs: a colored‑pointer fast path for the hot write path, falling back to a side‑bitmap for objects that cannot encode color bits.

## Key Takeaways

- The tri‑color marking algorithm enforces three invariants that guarantee safety while mutators run concurrently.  
- Write barriers (SATB or IU) are the primary mechanism to preserve the **no black‑to‑white edge** rule; they must be ultra‑low‑latency.  
- Safe points let the collector perform global actions without violating invariants, and their frequency directly impacts pause latency.  
- Production runtimes (HotSpot, Go, Rust tooling) demonstrate concrete patterns: colored pointers, region‑based heaps, lock‑free work queues, and scheduler‑driven safe points.  
- Architectural decisions—heap layout, metadata encoding, barrier choice—are trade‑offs between throughput, pause time, and implementation complexity.  
- Expose runtime metrics and make GC behavior configurable; real‑world tuning is an iterative process.

## Further Reading

- [HotSpot Garbage Collection Tuning Guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning.html)  
- [Go Runtime: Garbage Collector Overview](https://golang.org/doc/gc)  
- [Boehm-Demers-Weiser Garbage Collector Documentation](https://www.hboehm.info/gc/)  
- [The Java Memory Model and Write Barriers](https://openjdk.org/jeps/376)  
- [Rust Reference: Unsafe Code Guidelines (GC considerations)](https://doc.rust-lang.org/reference/unsafe.html)