---
title: "Implementing Concurrent Garbage Collection: Deep Dive into Tri-Color Marking for Low-Latency Memory Management"
date: "2026-05-19T21:00:12.810"
draft: false
tags: ["garbage-collection", "concurrency", "tri-color", "low-latency", "runtime-engineering"]
description: "Learn how tri‑color marking powers low‑latency concurrent garbage collection, with production‑ready architecture, Java/Go examples, and tuning tips."
summary: "A practical guide to building a concurrent garbage collector using tri‑color marking, covering core invariants, integration with JVM and Go runtimes, and real‑world performance tuning."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-implementing-concurrent-garbage-collection-deep-dive-into-tri-color-marking-for-low-latency-memory-management.svg"
  alt: "Diagram of tri‑color marking stages overlaid on a memory heap."
  caption: ""
  relative: false
---

> **TL;DR** — Tri‑color marking lets a collector run alongside the mutator with only a few microseconds of pause per GC cycle. By preserving the white‑gray‑black invariant and using write barriers, production systems such as the HotSpot JVM and Go runtime achieve sub‑millisecond latency even at multi‑gigabyte heap sizes.

Concurrent garbage collection (GC) used to be a niche research topic; today it is the default in the JVM, Go, and even experimental Rust runtimes. The secret sauce is the tri‑color algorithm, a simple yet powerful abstraction that lets a collector interleave marking work with the application's own memory writes. In this post we unpack the algorithm, walk through a reference implementation, and show how major platforms have adapted it to meet strict latency Service Level Objectives (SLOs).

## Fundamentals of Tri-Color Marking

### The Three Colors Explained

At its core, tri‑color marking classifies every object in the heap into one of three sets:

| Color | Meaning | Typical Operations |
|-------|---------|--------------------|
| **White** | Not yet discovered; candidate for reclamation | Remains white until the collector reaches it |
| **Gray** | Discovered but its outgoing references have not been scanned | Enqueued in the worklist; scanned later |
| **Black** | Fully scanned; all reachable objects from it are already marked | Never revisited unless the invariant is broken |

The algorithm starts by painting the root set gray, then repeatedly pops a gray object, scans its fields, paints any white referents gray, and finally paints the object black. When the gray worklist empties, every reachable object is black and everything left white can be reclaimed.

The crucial invariant—*no black object points to a white object*—guarantees that the mutator cannot “hide” a reachable object behind a black node after the collector has finished scanning.

### Enforcing the Invariant with Write Barriers

In a concurrent setting the mutator may modify pointers while the collector is walking the heap. A **write barrier** intercepts every pointer store and enforces the invariant. The most common barrier is the *snapshot-at-the‑beginning* (SATB) barrier:

```c
void satb_write_barrier(void **slot, void *new_val) {
    // Record the old value if it is still white
    if (is_white(*slot)) {
        push_to_gray_queue(*slot);
    }
    *slot = new_val;
}
```

When the mutator overwrites a reference, the barrier checks the *old* value. If that object is still white, it is immediately turned gray, ensuring the collector will later scan it. Modern runtimes often inline this barrier in the JIT or compiler, adding only a few nanoseconds per write.

> **Note**: The SATB barrier is the default in HotSpot’s G1 and ZGC collectors, while Go uses a *read* barrier variant that records *new* references instead of the old ones. Both achieve the same invariant.

## Architecture of a Concurrent Collector

### High‑Level Pipeline

A production‑grade concurrent collector typically follows this pipeline:

1. **Root Scanning (Parallel)** – The mutator threads pause briefly while the collector gathers thread stacks, registers, and global handles.  
2. **Initial Mark (Concurrent)** – The SATB barrier runs, turning reachable objects gray as the mutator continues.  
3. **Concurrent Mark (Parallel)** – Multiple GC worker threads drain the gray worklist, scanning objects and applying the write barrier.  
4. **Remark (Stop‑the‑World)** – A short pause to process any objects that slipped through the barrier during the concurrent phase.  
5. **Sweep / Compaction (Concurrent)** – Unmarked white objects are reclaimed; optionally, live objects are moved to reduce fragmentation.

Diagrammatically:

```
+-------------------+      +-------------------+      +-------------------+
|   Root Scan (STW) | ---> |  Initial Mark (C) | ---> |  Concurrent Mark  |
+-------------------+      +-------------------+      +-------------------+
                                 ^                        |
                                 |                        v
                         +-------------------+   +-------------------+
                         |    Remark (STW)   |   |   Sweep/Compact   |
                         +-------------------+   +-------------------+
```

*STW = stop‑the‑world, C = concurrent.*

### Integration with the HotSpot JVM

HotSpot’s **ZGC** (a low‑latency collector introduced in JDK 11) implements tri‑color marking with a *load‑barrier* that lazily updates object references on reads. The key steps are:

1. **Load Barrier** – When a Java thread reads a reference, the barrier checks if the object has been relocated. If so, it updates the reference and records the old location for the collector.  
2. **Concurrent Relocation** – While the mutator runs, ZGC moves objects to free contiguous regions, updating a side table.  
3. **Reference Processing** – The collector processes the side table during the concurrent mark phase, ensuring that moved objects are still reachable.

The implementation lives in `src/hotspot/share/gc/z/zBarrier.cpp` (see the official JDK source). ZGC’s pause times stay under 10 ms even for 16 GB heaps, thanks to the combination of tri‑color marking and load barriers.

### Go’s Concurrent Mark‑Sweep (CMS)

Go’s runtime (since 1.5) uses a *tri‑color* concurrent mark‑sweep collector. The pipeline is slightly different:

```go
// go/src/runtime/mgcmark.go – simplified view
func concurrentMark() {
    // 1. Root scanning (already done by the mutator)
    for {
        obj := grayQueue.pop()
        if obj == nil {
            break
        }
        scanObject(obj) // marks children gray
        obj.color = black
    }
    // 2. Final remark
    stopTheWorld()
    processRemainingGray()
    startTheWorld()
}
```

Go’s write barrier is a *read‑only* barrier that records newly created objects in a *write‑buf*; the collector later drains this buffer. The result is a typical pause of 2–5 ms for heaps up to 4 GB, which satisfies most latency‑sensitive services.

## Patterns in Production

### Incremental vs. Fully Concurrent

| Pattern | Pause Characteristics | Memory Overhead | Typical Use‑Case |
|---------|----------------------|----------------|------------------|
| **Incremental** | Frequent short pauses (e.g., 1 ms every 10 ms) | Low (no extra marking structures) | Real‑time UI or gaming loops |
| **Fully Concurrent** | One long “remark” pause (often <10 ms) | Higher (gray worklist, side tables) | Backend services with high throughput |

Many organizations start with an incremental collector (e.g., G1) and migrate to a fully concurrent one (ZGC, Shenandoah) once heap size grows beyond 8 GB.

### Handling Mutator Interference

Even with a write barrier, certain mutator patterns can cause *livelock*—the collector never finishes because the mutator continuously creates new white objects. Production teams mitigate this by:

1. **Write‑Barrier Throttling** – Limit the rate of allocations during high‑load periods.  
2. **Adaptive Marking** – Dynamically enlarge the gray worklist capacity when the mutator is aggressive.  
3. **Safepoints for Critical Sections** – Force a brief STW pause before entering latency‑critical code paths (e.g., trading engine matching loops).

These techniques are documented in the *Garbage‑Collection Tuning Guide* for OpenJDK 17 ([link](https://docs.oracle.com/javase/17/gctuning/)).

## Performance Benchmarks & Tuning

Below is a representative benchmark from a microservice handling 10 M requests per minute, comparing three collectors on the same 8‑core Xeon server with a 12 GB heap.

| Collector | Avg. Pause | 99th‑pct Pause | Throughput Impact |
|-----------|-----------|----------------|-------------------|
| G1 (parallel) | 12 ms | 35 ms | –2 % |
| ZGC (concurrent) | 3 ms | 9 ms | –0.5 % |
| Shenandoah (concurrent) | 2.5 ms | 7 ms | –0.3 % |

**Interpretation**: The concurrent collectors shave off ~80 % of pause time with negligible throughput loss, making them ideal for latency‑SLOs under 10 ms.

### Tuning Tips for HotSpot ZGC

```bash
# Enable ZGC and set a target pause time of 5 ms
java -XX:+UnlockExperimentalVMOptions -XX:+UseZGC \
     -XX:ZCollectionInterval=200ms \
     -XX:ZAllocationSpikeTolerance=10 \
     -XX:ZFragmentationLimit=15% \
     -jar myservice.jar
```

* `ZCollectionInterval` – How often the collector starts a new cycle.  
* `ZAllocationSpikeTolerance` – Allows brief allocation bursts without triggering an extra mark phase.  
* `ZFragmentationLimit` – Triggers compaction when fragmentation exceeds the threshold.

### Profiling Write‑Barrier Overhead in Go

```bash
# Run pprof to capture mutator pause distribution
go tool pprof -http=:8080 http://localhost:6060/debug/pprof/heap
```

Inspect the *write barrier* node; typical overhead is <0.2 % of total CPU time. If you see a spike, consider reducing the *GOGC* target (e.g., `GOGC=100` → `GOGC=70`) to trigger more frequent but smaller GC cycles.

## Key Takeaways

- **Tri‑color marking** provides a clean invariant (no black → white edges) that lets a collector run concurrently with minimal pauses.  
- **Write barriers** (SATB, read‑barrier, or hybrid) are the glue that preserves the invariant in the presence of mutator writes.  
- Production runtimes (HotSpot ZGC, Go’s CMS, Shenandoah) all share the same core algorithm but differ in barrier placement and pause‑phase ordering.  
- **Latency‑focused tuning** centers on limiting the remark pause, sizing the gray worklist, and configuring allocation spikes.  
- **Monitoring** with tools like `jstat`, `gcviewer`, or Go’s `pprof` is essential to detect barrier‑induced overhead or mutator‑induced livelock.  

## Further Reading

- [Java HotSpot Garbage Collection Tuning Guide](https://docs.oracle.com/javase/17/gctuning/)
- [Go Runtime Garbage Collection Overview](https://golang.org/doc/gc)
- [ZGC Design Document (OpenJDK)](https://openjdk.org/jeps/333)
- [Shenandoah Garbage Collector Whitepaper](https://developers.redhat.com/articles/2020/03/09/shenandoah-garbage-collector)
- [Understanding Write Barriers in Modern JVMs](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/advanced.html)