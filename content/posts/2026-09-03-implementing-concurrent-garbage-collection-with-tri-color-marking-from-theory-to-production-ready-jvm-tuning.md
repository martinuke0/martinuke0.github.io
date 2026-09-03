---
title: "Implementing Concurrent Garbage Collection with Tri-Color Marking: From Theory to Production-Ready JVM Tuning"
date: "2026-09-03T08:00:34.910"
draft: false
tags: ["jvm", "garbage-collection", "tri-color-marking", "performance-tuning", "java", "low-latency"]
description: "A deep dive into tri-color marking, how G1 and ZGC use it concurrently, and production-ready JVM tuning knobs for predictable low-latency."
summary: "How modern concurrent collectors like G1 and ZGC use the tri-color invariant to do most of their work without stopping your threads, and the JVM flags you actually need in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-implementing-concurrent-garbage-collection-with-tri-color-marking-from-theory-to-production-ready-jvm-tuning.svg"
  alt: "Abstract visualization of tri-color object graph with moving collector threads."
  caption: ""
  relative: false
---

> **TL;DR** — Tri-color marking is the algorithm G1, ZGC, and Shenandoah all use to reclaim heap space while your application threads keep running. The hard part isn't the colors themselves — it's the SATB and incremental-update write barriers that keep the invariant intact. Get those wrong and you get silent memory leaks; get the JVM flags right and you can run p99 pauses in the sub-millisecond range.

## Why Stop-The-World Pauses Are a Tax You Can No Longer Afford

If you're running a service on the JVM, every garbage collection cycle is, at some level, a tax on your response times. The original mark-and-sweep collectors of the 1990s were stop-the-world by design: the runtime would freeze every application thread, walk the object graph, and only then resume. For a 100 MB heap that was fine. For a 100 GB heap serving 50k requests per second, it's not.

Concurrent collectors — G1, ZGC, and Shenandoah — exist because the heap got too big and the latency budget got too small. All three are built on the same conceptual foundation: **tri-color marking**, an algorithm first formalized by Dijkstra in a 1978 paper on graph marking. Understanding that algorithm is the difference between treating the JVM like a black box and being able to reason about why a particular `-XX` flag actually matters.

The goal of this post is to walk you from the abstract invariant to the JVM flags you'd put in a Dockerfile in production. If you've ever wondered why ZGC can hit single-millisecond p99 pauses on a 100 GB heap while your service still stutters every few minutes, the answer lives in the write barriers and the snapshotting model — and we'll get there.

## The Tri-Color Invariant: A Graph Coloring Problem

Imagine your heap as a directed graph. The GC roots (thread stacks, JNI references, static fields) are the entry points, and every object points to other objects through fields. To know what's still live, the collector starts at the roots and walks the graph, marking everything reachable.

Tri-color marking assigns one of three states to every object:

- **White** — not yet discovered. The candidate set for "garbage."
- **Gray** — discovered, but its references haven't been scanned yet.
- **Black** — fully scanned; all of its outgoing references have been processed.

The worklist algorithm looks like this:

```java
// Conceptual pseudocode — not the real JVM implementation
void mark(Reference root) {
    worklist.push(root);
    while (!worklist.isEmpty()) {
        Object ref = worklist.pop();
        if (colorOf(ref) == BLACK) continue;
        setColor(ref, BLACK);
        for (Object child : childrenOf(ref)) {
            if (colorOf(child) != BLACK) {
                setColor(child, GRAY);
                worklist.push(child);
            }
        }
    }
}
```

The **tri-color invariant** is what keeps this safe when multiple threads are running:

> No black object may point directly to a white object.

If this invariant holds, the algorithm cannot miss a live object: every white object that survives is provably unreachable. If it breaks, you lose objects — which, from the user's perspective, looks like a silent memory leak followed by mysterious `NullPointerException`s.

There are two ways to break it, and they're the reason concurrent marking is hard. If a gray object removes its reference to a white child, that white child becomes unreachable from the worklist — **a lost object**. If a black object picks up a new reference to a white child, the marking pass won't revisit it — **the same lost object, different cause**.

## How a Concurrent Collector Actually Runs

In a stop-the-world mark-sweep, the invariant is trivially preserved because the application isn't running. In a concurrent collector, application threads (the **mutators** in GC literature) are reading and writing references the entire time. The collector has to insert tiny snippets of code into every reference write — **write barriers** — to keep the invariant from collapsing.

The collector and the mutator are running in the same graph at the same time, on different threads. The barriers are the contract between them.

G1, ZGC, and Shenandoah all use tri-color marking, but they differ in *how* they defend the invariant:

- **G1 (Garbage-First)** — uses a **Snapshot-At-The-Beginning (SATB)** barrier. When a write barrier fires, it pushes the old reference value into a per-thread remembered set buffer, as if the snapshot at the start of the marking cycle is what we want to preserve.
- **ZGC** — uses **load barriers** instead of (well, in addition to) write barriers. Every time a thread reads a reference, the load barrier checks the pointer's metadata bits and remaps it if the GC has moved the object. ZGC is a **concurrent *compacting*** collector, not just a concurrent marker.
- **Shenandoah** — uses an **update-reference** barrier that's a hybrid: it remembers the old value (SATB-like) but also queues the new value for the concurrent updater phase.

Each design is a different answer to the same question: *how aggressively do we trade mutator throughput for shorter, more predictable pauses?*

## Patterns in Production: G1, ZGC, and Shenandoah Side by Side

Here's the practical layout of the three collectors, anchored in real numbers and shipped versions.

### G1 — The Pragmatic Default

G1 has been the default collector since JDK 9 and is what most production services are running. It partitions the heap into ~2,048 equal-sized **regions** (1–32 MB each, default ~4 MB). It runs mostly concurrently but still has a small stop-the-world final-mark and a parallel compaction phase.

The key knob is the pause-time goal:

```bash
-XX:+UseG1GC
-XX:MaxGCPauseMillis=200
-XX:G1NewSizePercent=30
-XX:G1MaxNewSizePercent=40
-XX:InitiatingHeapOccupancyPercent=45
-XX:ConcGCThreads=4
```

`InitiatingHeapOccupancyPercent` (IHOP) is the most misunderstood of these. It tells G1: "Start a concurrent marking cycle once the heap is this percent full." Set it too high and you'll get a stop-the-world Full GC; set it too low and you'll trigger marking cycles that don't accomplish much. The default of 45% is conservative — well-tuned services often run with 30–35% if they have a tight pause budget.

### ZGC — The Sub-Millisecond Option

ZGC is what you reach for when G1's p99 spikes are still too high. Since JDK 15 (and default-tiered since JDK 21 in some configurations), ZGC offers pause times that don't scale with heap size. On a 100 GB heap, a ZGC pause is in the same ballpark as on a 1 GB heap: usually 100–500 microseconds.

The flag set is small:

```bash
-XX:+UseZGC
-XX:+ZGenerational    # JDK 21+ multi-generational ZGC, strongly recommended
-XX:ConcGCThreads=4
-XX:SoftMaxHeapSize=8G
```

`SoftMaxHeapSize` is the lever people miss. It tells ZGC: "Treat this as the practical ceiling; try not to grow past it." If your container has a memory limit of 8 GB but the JVM was launched with `-Xmx16g`, ZGC will try to keep the working set at 8 GB and aggressively return memory to the OS, which matters enormously in Kubernetes.

### Shenandoah — The Middle Ground

Shenandoah ships in most JDK distributions (it was upstreamed in JDK 13). It targets a similar profile to ZGC but has historically been more aggressive about compaction. It's particularly popular in OpenJDK-based distributions like Azul Zulu and Eclipse Temurin for specific workloads.

```bash
-XX:+UseShenandoahGC
-XX:ShenandoahGCHeuristics=adaptive
-XX:ShenandoahUncommitDelay=300000
```

The `adaptive` heuristic is the one you want unless you have a very specific reason to choose otherwise. It watches your allocation rate and pause distribution and tunes itself.

## Write Barriers: The Actual Engineering

Let's look at the SATB barrier in G1, because it's the most common in production. When mutator thread T writes a new reference to a field:

```
old = obj.field
obj.field = newRef
barrier(old)  // <- this runs on every reference write
```

The barrier pushes `old` into a per-thread **SATB buffer**. If `old` was a white object, the marking cycle will still see it because the SATB buffer is drained at the start of the next concurrent marking phase. The conceptual contract: *the snapshot is "everything that was reachable at the moment marking started."* Any reference that existed at T0 is protected.

The cost? Every reference write in your application goes through this barrier. The JIT compiler inlines it via the [G1 post-barrier](https://openjdk.org/jeps/307) — but you're still paying for a conditional branch and, on the slow path, a buffer write. The reason naive G1 benchmarks sometimes *lose* to Parallel GC is the barrier overhead.

ZGC trades this differently. Because ZGC is also concurrent-compacting, it can move objects while your application is running. It can't put a write barrier on every write (too expensive at that volume), so it puts a **load barrier** on every *read*. Every time the application dereferences a reference, ZGC checks the pointer's "marked" bits and remaps if needed.

This is why ZGC's throughput overhead is roughly 5–15% on allocation-heavy workloads, but its pauses are tiny. It's a different point in the design space.

## The Tuning Workflow That Actually Works

Theory is great. Here's the workflow I use when tuning a service that's hitting GC issues.

### Step 1: Enable GC Logging

First, set up logs you can actually analyze. In JDK 11+:

```bash
-Xlog:gc*,gc+heap=info,gc+ergo=debug:file=/var/log/app/gc.log:time,uptime,level,tags:filecount=10,filesize=50M
```

JDK 9+ unified logging has many knobs. The format string above gives you everything you need without flooding the log. Forward these to your metrics pipeline and parse them; don't try to read them by hand.

### Step 2: Measure Before Tuning

Capture these baseline metrics over at least 24 hours of representative traffic:

- Allocation rate (bytes/sec)
- GC frequency (cycles/min)
- p50, p99, p999 pause duration
- Heap occupancy at the start of each cycle

If you don't know your numbers, you're not tuning — you're guessing. Tools like [async-profiler](https://github.com/async-profiler/async-profiler) can also dump allocation sites, which is often where the real wins are.

### Step 3: Identify Your Failure Mode

There are three common failure modes, and they need different fixes:

1. **Pause spikes from Full GC** — heap is too small, or IHOP is too aggressive. Increase heap, lower IHOP, or move to a generational collector (ZGC Generational in JDK 21+).
2. **Allocation pressure** — your service is generating too much garbage. No collector will save you. Fix the code or cache the allocations.
3. **Pause spikes from concurrent-marking handoff** — G1's final-mark and cleanup phases are still stop-the-world. If your heap is mostly garbage and your mutator is generating a lot of it, the marking work inflates. Lower the allocation rate, or move to ZGC.

### Step 4: Apply the Minimum Set of Flags

For a typical Spring Boot microservice in Kubernetes on JDK 21, this is the baseline I'd start with:

```bash
-XX:+UseG1GC
-XX:MaxGCPauseMillis=100
-XX:+UseStringDeduplication
-XX:+ExitOnOutOfMemoryError
-XX:+HeapDumpOnOutOfMemoryError
-XX:HeapDumpPath=/var/log/app/
-Xlog:gc*:file=/var/log/app/gc.log:time,uptime:filecount=5,filesize=50M
-XX:+UseContainerSupport
-XX:MaxRAMPercentage=75.0
```

`MaxRAMPercentage=75.0` is critical in containerized environments. Without it, the JVM thinks it has access to the host's full memory and will happily try to allocate a 32 GB heap in a 4 GB container, then get its head handed to it by the kernel OOM killer. See the [Eclipse Adoptium container guide](https://blog.adoptium.net/2021/08/using-jlink-to-reduce-java-container-size/) for more on JVM-in-container behavior.

### Step 5: Verify, Don't Trust

After applying changes, run a load test that matches production traffic. Watch the GC log tail with:

```bash
jcmd <pid> GC.heap_info
jcmd <pid> VM.flags
```

If you have a way to trigger a representative spike in traffic, do it. A tuning that works on Tuesday's traffic might be wrong for Friday's.

## Where Tri-Color Goes Next

The frontier is **generational ZGC**, which made it production-ready in JDK 21 and reached full feature parity in later versions. The premise is that most objects die young — the **weak generational hypothesis** — and a generational collector can reclaim that nursery much faster than scanning the whole heap. The trick is that the generational boundaries add more write barriers, and the engineers had to design them so the per-write overhead stays tiny.

Another active area is **region pinning** for ZGC and **load barrier elision** for Shenandoah, both aimed at reducing throughput cost. The OpenJDK project has [active discussions](https://openjdk.org/projects/) on these topics — if you care about low-latency JVM, the [jdk-dev](https://mail.openjdk.org/mailman/listinfo/jdk-dev) mailing list is where the design conversations happen.

## Key Takeaways

- **Tri-color marking is the foundation** — G1, ZGC, and Shenandoah are all variations on Dijkstra's 1978 algorithm, distinguished by how they defend the invariant against concurrent mutation.
- **Write barriers are the cost** — every reference write pays a small tax to keep the marking snapshot consistent. The throughput hit is the price of concurrent collection.
- **Pick the collector for your failure mode** — G1 for the 95% case, ZGC for hard p99 SLAs, Shenandoah if you're on a distribution that ships it well.
- **Tune with data, not folklore** — enable unified logging, parse the output, and look at p99 over 24 hours, not the average pause over 5 minutes.
- **Container-aware flags are not optional** — `MaxRAMPercentage` and `UseContainerSupport` are the difference between a JVM that runs in Kubernetes and one that mysteriously dies.
- **The algorithm isn't the bottleneck** — at 100 GB heap sizes, ZGC pauses are measured in microseconds. The bottleneck is almost always allocation rate in the application.

## Further Reading

- [JEP 333: ZGC — A Scalable Low-Latency Garbage Collector](https://openjdk.org/jeps/333)
- [JEP 377: ZGC — Remove Experimental Flag](https://openjdk.org/jeps/377)
- [JEP 404: Generational ZGC](https://openjdk.org/jeps/404)
- [G1 Garbage Collector Tuning Guide (Oracle)](https://docs.oracle.com/en/java/javase/21/gctuning/garbage-first-garbage-collector.html)
- [Shenandoah GC — Red Hat build of OpenJDK documentation](https://developers.redhat.com/articles/2021/11/02/shenandoah-garbage-collector)
- [JEP 307: Parallel Full GC for G1](https://openjdk.org/jeps/307)
- [Aleksey Shipilëv — Everything I Ever Learned About JVM Performance Tuning (twitter.com)](https://shipilev.net/talks/javazone-JVM-Performance-Tutorial.pdf)