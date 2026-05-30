---
title: "Implementing Concurrent Garbage Collection: Tri-Color Marking Architecture and Production Heap Management Strategies"
date: "2026-05-30T11:00:44.572"
draft: false
tags: ["garbage-collection","concurrency","runtime","systems-engineering","java"]
description: "A deep dive into tri‑color marking for concurrent GC, covering architecture, write barriers, heap layout, and real‑world tuning strategies used in production Java and Go services."
summary: "Explore how tri‑color marking powers low‑pause concurrent collectors, see concrete architecture diagrams, and learn production‑grade heap management tricks."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-30-implementing-concurrent-garbage-collection-tri-color-marking-architecture-and-production-heap-management-strategies.svg"
  alt: "Illustration of a heap with colored nodes representing tri‑color marking."
  caption: ""
  relative: false
---

> **TL;DR** — Tri‑color marking lets a collector run alongside mutators with only micro‑second pauses. By combining a precise write barrier, incremental mark phases, and a generational heap layout, you can keep pause times below 10 ms even on multi‑core workloads.

Concurrent garbage collection (GC) used to be a research curiosity; today it powers billions of requests per day in services built on OpenJDK, Go, and .NET. The secret sauce is the tri‑color marking algorithm, a disciplined way to traverse object graphs while the application keeps allocating and mutating. This post unpacks the algorithm, shows how production runtimes wire it together, and shares pragmatic heap‑management patterns that keep latency predictable.

## Tri‑Color Marking in Theory

The tri‑color abstraction divides every object in the heap into three sets:

| Color | Meaning | Transition |
|-------|---------|------------|
| **White** | Not yet discovered; will be reclaimed if it stays white at the end of the mark phase. | White → Gray when a mutator or the collector discovers the object. |
| **Gray** | Discovered but its outgoing references have not been scanned. | Gray → Black after scanning all its fields. |
| **Black** | All outgoing references have been scanned; the object is known to be live. | No further transition. |

The invariant that guarantees correctness is **“no black object points to a white object.”** If this holds when the mark phase ends, any remaining white objects are unreachable and safe to collect.

In a *stop‑the‑world* collector the algorithm is trivial: pause mutators, walk the graph, then reclaim. In a concurrent collector the mutators keep running, so we need a **write barrier** that preserves the invariant despite concurrent modifications.

## Architecture of a Concurrent Collector

A production‑grade concurrent collector typically consists of four pipelines that run on dedicated threads:

1. **Marking Thread(s)** – perform incremental gray → black transitions.
2. **Root Scanning Thread** – periodically rescans roots (stack, registers, global handles) to catch newly reachable objects.
3. **Sweeping Thread** – reclaims white objects after the mark phase stabilizes.
4. **Allocation Thread** – services mutator allocation requests; it also maintains per‑thread allocation buffers (TLABs).

Below is a simplified diagram (pseudo‑code only, not a full implementation):

```text
+-------------------+      +-------------------+
| Mutator (Thread)  |      | Collector Thread  |
+-------------------+      +-------------------+
| allocate()        | ---> | mark_gray(obj)    |
| write_field(o,f,v)| ---> | barrier(o,f,v)    |
| ...               |      | ...               |
+-------------------+      +-------------------+
```

### Write Barriers

The barrier is the heart of the tri‑color approach. Two common flavors exist:

* **Snapshot‑At‑The‑Beginning (SATB)** – treats the heap as if a snapshot was taken at the start of the mark. The barrier records *any* object that *loses* a reference to a white object. Implemented in OpenJDK as `SATBBarrier::write`. Example in C++‑like pseudocode:

```cpp
void satb_write_barrier(Object* src, Object* field, Object* new_val) {
    if (new_val->color == WHITE) {
        mark_gray(new_val);          // ensure it will be scanned
    }
    // store the new reference
    src->field = new_val;
}
```

* **Incremental Update (IU)** – assumes the heap starts with all objects black and records *any* object that *gains* a reference to a white object. Used by Go's runtime. Pseudocode:

```go
func iuWriteBarrier(dst *Object, field *Object, newVal *Object) {
    if newVal.color == white {
        markGray(newVal) // promote to gray immediately
    }
    *field = newVal
}
```

Both barriers are *tiny* (a handful of CPU cycles) and are inlined into every field store. The choice depends on the language's memory model and the collector's pause‑time goals.

### Incremental Mark Phase

Instead of walking the entire graph in one go, the collector processes a *work queue* of gray objects in small batches. A typical loop looks like this:

```python
while not work_queue.empty():
    # Pull a batch to keep pause short
    batch = work_queue.pop_batch(max_batch_size=256)
    for obj in batch:
        for ref in obj.references():
            if ref.color == WHITE:
                ref.color = GRAY
                work_queue.push(ref)
        obj.color = BLACK
```

The `max_batch_size` can be tuned dynamically based on observed pause times. OpenJDK’s G1 GC, for instance, adjusts the batch size to keep each *GC worker* pause under 5 ms.

### Root Rescanning

Mutators can create new roots (e.g., store a reference in a thread‑local variable) after the initial root scan. A lightweight *root rescanner* runs every few milliseconds, walking the stack frames of each mutator thread. The cost is bounded because only a small fraction of frames change between rescans.

## Production Heap Management Strategies

### Generational Layout

Most production workloads exhibit *generational* allocation patterns: most objects die young, a few survive for a long time. A typical heap is split into:

* **Young Generation** – a contiguous region (often a *nursery* of 1–2 MiB per thread) collected with a fast *copying* collector.
* **Old Generation** – a larger region (several GiB) where the concurrent tri‑color collector runs.
* **Humongous/Metaspace** – special handling for very large objects or class metadata.

The interaction looks like this:

1. Objects start in the nursery (young gen). When the nursery fills, a *minor* stop‑the‑world pause copies live objects to the *old* gen.
2. The concurrent collector later marks those survivors and may promote them further if they survive several minor collections.

The generational barrier is cheap because most writes stay within the young gen, which does not need a full tri‑color barrier.

### Adaptive Tuning

Production runtimes expose knobs that adapt to workload pressure:

| Parameter | Effect | Typical Range |
|-----------|--------|---------------|
| `MarkingWorkUnit` | Number of objects processed per GC slice | 128–1024 |
| `PauseTarget` | Desired maximum pause (ms) | 5–20 |
| `HeapOccupancyTarget` | Trigger for concurrent cycle start (percentage) | 60‑80 % |
| `ConcurrentRefinement` | Enable background reference processing (e.g., `java.lang.ref`) | true/false |

A practical tuning loop in Bash:

```bash
#!/usr/bin/env bash
# Adjust G1GC pause target based on observed latency
while true; do
    latency=$(curl -s http://metrics.local/latency_ms | jq .p99)
    if (( latency > 15 )); then
        jcmd $(pgrep java) GC.set_pause_target_ms 10
    elif (( latency < 5 )); then
        jcmd $(pgrep java) GC.set_pause_target_ms 20
    fi
    sleep 30
done
```

The script watches the 99th‑percentile latency and nudges the GC pause target accordingly. In large‑scale microservice fleets, a similar controller runs as a sidecar, feeding metrics into a central autoscaling service.

## Patterns in Production

### Failure Modes and Mitigations

| Failure Mode | Symptom | Mitigation |
|--------------|---------|------------|
| **Barrier Overhead** | CPU spikes in write‑intensive services | Switch to *SATB* if using *IU*, or batch writes in hot loops. |
| **White‑to‑Black Regression** | Objects reclaimed prematurely, leading to segfaults | Verify the invariant with `-XX:+PrintGCDetails` and enable `-XX:+PrintReferenceGC`. |
| **Heap Fragmentation** | Increased allocation latency, OOM despite free memory | Trigger a *compaction* pause (`-XX:+UseG1GC -XX:+ExplicitGCInvokesConcurrent`). |
| **Long Mark Phase** | GC threads saturate CPU, causing request latencies | Reduce `MarkingWorkUnit` or add more GC worker threads (`-XX:ParallelGCThreads`). |

OpenJDK’s G1 GC includes a *concurrent refinement* phase that processes `java.lang.ref` objects while the main mark runs, preventing a sudden burst of reference processing at the end of the cycle.

### Coordination with Observability

Logging GC events directly into a distributed tracing system (e.g., OpenTelemetry) makes it possible to correlate pause spikes with request latency. Example snippet in Java:

```java
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.Tracer;

public class GcObserver {
    private static final Tracer tracer = GlobalOpenTelemetry.getTracer("gc");

    public static void onPauseStart(String phase) {
        Span.current().addEvent("GC Pause Start", Attributes.of(
            AttributeKey.stringKey("gc.phase"), phase));
    }

    public static void onPauseEnd(String phase, long durationMs) {
        Span.current().addEvent("GC Pause End", Attributes.of(
            AttributeKey.stringKey("gc.phase"), phase,
            AttributeKey.longKey("gc.duration_ms"), durationMs));
    }
}
```

When a pause exceeds the SLA, the trace shows the exact request path, enabling rapid root‑cause analysis.

## Key Takeaways

- Tri‑color marking guarantees correctness with the invariant *no black → white*; a precise write barrier enforces it during concurrent execution.
- Incremental marking with a bounded work queue keeps individual GC slices under a configurable pause budget.
- Generational heap layout isolates most allocation traffic, allowing the concurrent collector to focus on long‑lived objects.
- Adaptive tuning (pause target, marking work unit, heap occupancy) is essential to meet latency SLAs across heterogeneous workloads.
- Observability integration turns GC pauses from opaque events into actionable telemetry.

## Further Reading

- [OpenJDK G1 Garbage Collector Overview](https://openjdk.org/projects/g1)
- [Go Runtime Garbage Collector Design](https://golang.org/doc/gc)
- [Microsoft .NET GC Architecture](https://learn.microsoft.com/en-us/dotnet/standard/garbage-collection/)
- [The Java Memory Model (JMM) Specification](https://docs.oracle.com/javase/specs/jls/se21/html/jls-17.html)
- [A Survey of Concurrent Garbage Collection Techniques](https://dl.acm.org/doi/10.1145/3386328)