---
title: "Implementing Concurrent Garbage Collection: A Deep Dive into Tri-Color Marking and Barrier Techniques"
date: "2026-05-20T02:00:12.763"
draft: false
tags: ["garbage-collection", "concurrency", "tri-color", "write-barrier", "systems-engineering"]
description: "Explore how to build a concurrent garbage collector using tri‑color marking and write barriers, with real‑world patterns, code snippets, and production considerations."
summary: "A practical guide to implementing concurrent garbage collection, covering tri‑color algorithms, barrier designs, and deployment tips for production systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-20-implementing-concurrent-garbage-collection-a-deep-dive-into-tri-color-marking-and-barrier-techniques.svg"
  alt: "Illustration of a tri‑color graph overlaying a heap memory diagram."
  caption: ""
  relative: false
---

> **TL;DR** — Tri‑color marking combined with carefully designed write barriers lets you collect garbage without stopping the world; this post shows the algorithm, barrier implementations, and how large‑scale services like Kafka Streams or GCP’s Go runtime make it work in production.

Concurrent garbage collection (GC) is no longer a luxury for experimental languages; it is a production requirement for services that must stay online while reclaiming memory. Engineers building high‑throughput back‑ends—think Kafka, Aerospike, or the Go runtime on GCP—need a collector that can run alongside mutating application threads. The classic “stop‑the‑world” mark‑and‑sweep approach guarantees correctness but incurs latency spikes that break SLAs. Tri‑color marking, paired with write barriers, provides a lock‑step mechanism that lets the collector progress while the program continues to allocate and mutate objects.

## Foundations of Concurrent Garbage Collection

### Why Classic Mark‑and‑Sweep Falls Short

Traditional mark‑and‑sweep works in two phases:

1. **Mark** – pause all mutators, walk the object graph from roots, and set a mark bit on every reachable object.
2. **Sweep** – scan the heap, reclaim unmarked memory.

The pause in the mark phase can last milliseconds to seconds on large heaps, which is unacceptable for latency‑sensitive services. As described in the [Wikipedia overview of mark‑and‑sweep](https://en.wikipedia.org/wiki/Mark-and-sweep), the root cause is the lack of coordination between mutators and the collector.

### The Tri‑Color Invariant

The tri‑color algorithm splits objects into three sets:

| Color | Meaning | Invariant |
|-------|---------|-----------|
| **White** | Not yet discovered; may be reclaimed | Must never become reachable after the collector starts. |
| **Gray** | Discovered but whose outgoing references haven’t been scanned | All references from gray objects must point only to gray or black objects. |
| **Black** | Fully scanned; all outgoing references are known to be reachable | No reference from a black object may point to a white object. |

The invariant guarantees that once an object turns black, any object it points to is already known to be live, preventing the collector from missing newly reachable objects that the mutator creates after the mark phase began.

## Tri‑Color Marking in Practice

### High‑Level Algorithm

```python
def concurrent_mark(heap, roots):
    # 1. Initialize
    for obj in heap:
        obj.color = 'white'
    worklist = []
    for root in roots:
        root.color = 'gray'
        worklist.append(root)

    # 2. Process gray objects
    while worklist:
        obj = worklist.pop()
        for ref in obj.references:
            if ref.color == 'white':
                ref.color = 'gray'
                worklist.append(ref)
        obj.color = 'black'
```

In a real system the collector runs this loop on a dedicated thread while mutator threads continue allocating and updating references. The crucial missing piece is *how to keep the tri‑color invariant true when mutators modify the graph*.

### Write Barriers: The Glue That Holds the Invariant

A write barrier is a tiny piece of code executed every time a mutator writes a reference into an object. The barrier records enough information for the collector to maintain the invariant without halting the world.

Two common barrier styles:

| Style | When to use | Typical overhead |
|-------|-------------|-------------------|
| **Snapshot‑At‑The‑Begin (SATB)** | Generational collectors, low‑write workloads | One extra read per write |
| **Incremental Update (IU)** | High‑write workloads, low latency | One extra write per write |

Both are described in detail in the [Oracle GC tuning guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/).

#### Incremental Update Barrier Example (C++)

```cpp
inline void write_barrier(Object* host, Object* new_ref) {
    // If host is black and new_ref is white, we must turn new_ref gray.
    if (host->color == Color::Black && new_ref->color == Color::White) {
        new_ref->color = Color::Gray;
        collector->enqueue_gray(new_ref);
    }
    host->field = new_ref; // Perform the actual write
}
```

The barrier checks the colors at runtime; if a black object points to a white one, the white object is promoted to gray, ensuring it will be scanned later.

#### Snapshot‑At‑The‑Begin Barrier Example (Java)

```java
// Executed before the write
void satbBarrier(Object host, Object newRef) {
    if (host.isBlack()) {
        // Record the old reference so the collector can later scan it
        collector.recordEdge(host, host.field);
    }
    host.field = newRef;
}
```

In SATB the collector takes a snapshot of all references *before* the mutator changes them. Any object that was reachable at the start of the cycle is treated as gray, even if later overwritten.

## Architecture in Production

### Integration with a Real Service: Kafka Streams

Kafka Streams runs on the JVM and historically relied on the default parallel GC. When the team switched to a low‑latency workload, they adopted the *ZGC* collector, which implements a tri‑color algorithm with a *load‑barrier* (a variant of IU). The architecture looks like this:

1. **Collector Thread** – Runs the tri‑color scan, maintaining a concurrent work queue.
2. **Mutator Threads** – Execute user code; every field write passes through the load‑barrier generated by the JIT.
3. **Safepoint Coordination** – Only at the start of a new GC cycle does the runtime pause mutators briefly to publish the root set.

The result: sub‑millisecond pause times even with heap sizes of 64 GiB, as reported in the [Kafka Streams performance whitepaper](https://kafka.apache.org/documentation/streams).

### GCP’s Go Runtime

Go’s concurrent collector, introduced in Go 1.5, uses a tri‑color mark phase combined with a *write barrier* that is inlined by the compiler. The collector’s architecture is:

- **Mark Workers** – Multiple goroutines walk gray objects in parallel.
- **Write Barrier** – A tiny `runtime.writeBarrier` function injected at each pointer store.
- **Assist Model** – Mutators help the collector when they allocate, ensuring forward progress.

The design is detailed in the Go blog post “[Concurrent Garbage Collection in Go](https://go.dev/blog/gc)”.

## Patterns in Production

### 1. Split Heap Into Generations

Most production systems combine tri‑color marking with generational segregation: young objects are collected frequently with a stop‑the‑world minor GC, while the concurrent collector focuses on the old generation. This hybrid approach reduces overall pause time and limits the amount of data the concurrent collector must scan.

### 2. Deferred Finalization

Finalizers (destructors) can re‑introduce references that break the tri‑color invariant. Production collectors therefore *defer* finalizer execution until after the sweep phase, or run them on a dedicated thread that respects the current color set. The Java HotSpot VM follows this pattern.

### 3. Adaptive Barrier Selection

Workloads with high write rates (e.g., in‑memory caches) benefit from IU barriers, while workloads with large allocation bursts (e.g., batch processing) may switch to SATB. Some runtimes expose a tuning knob to flip between the two at runtime, as seen in the [Eclipse OpenJ9 GC options](https://www.eclipse.org/openj9/docs/garbage-collection/).

### 4. Incremental Sweep

Even after marking, sweeping a massive heap can cause latency spikes. An *incremental sweep* spreads the reclamation work over many mutator cycles, often using a bitmap to track freed pages. This pattern appears in the .NET Core GC and the Azul C4 collector.

## Key Takeaways

- **Tri‑color marking** provides a rigorous invariant that lets a collector run concurrently with mutators, eliminating long stop‑the‑world pauses.
- **Write barriers** (IU or SATB) are the minimal runtime instrumentation required to preserve the invariant; they add only a few nanoseconds per write in production systems.
- **Hybrid architectures** (generational + concurrent) combine the best of both worlds: fast minor collections and low‑latency major collections.
- **Real‑world runtimes** (Go, HotSpot, ZGC) demonstrate that the theory scales to multi‑terabyte heaps with sub‑millisecond pause budgets.
- **Pattern libraries** such as deferred finalization, adaptive barrier selection, and incremental sweep turn the algorithm into a production‑ready service.

## Further Reading

- [Mark‑and‑sweep garbage collection (Wikipedia)](https://en.wikipedia.org/wiki/Mark-and-sweep)
- [Java HotSpot VM Garbage Collection Tuning Guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/)
- [Go Blog: Concurrent Garbage Collection in Go](https://go.dev/blog/gc)
- [Apache Kafka Streams Documentation](https://kafka.apache.org/documentation/streams)
- [Eclipse OpenJ9 Garbage Collection Options](https://www.eclipse.org/openj9/docs/garbage-collection/)