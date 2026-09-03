---
title: "Implementing Concurrent Garbage Collection: A Deep Dive into Tri-Color Marking for Low-Latency Runtimes"
date: "2026-09-03T06:00:20.167"
draft: false
tags: ["garbage-collection", "gc", "runtime", "tri-color", "low-latency", "go"]
description: "How tri-color marking underpins concurrent garbage collectors in Go, Java, and the JVM, and what it takes to build one without stopping the world."
summary: "A working-engineer's tour of tri-color invariant, write barriers, and the SATB vs. incremental-update trade-offs that make modern concurrent GCs possible."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-implementing-concurrent-garbage-collection-a-deep-dive-into-tri-color-marking-for-low-latency-runtimes.svg"
  alt: "Abstract diagram showing white, grey, and black object nodes connected by pointers representing tri-color marking."
  caption: ""
  relative: false
---

> **TL;DR** — Tri-color marking turns the classical mark-and-sweep algorithm into something that can safely run alongside application mutators, provided the runtime enforces an invariant with write barriers. Modern runtimes like Go, HotSpot, and V8 each pick a slightly different flavor (SATB, incremental update, deletion, hybrid) and pay for it in different ways — the cost is always in the barrier, not the collector.

If you've ever shipped a service that briefly froze for 200 milliseconds during peak traffic, only to find the cause was a "GC pause," you've already felt why concurrent garbage collection matters. Stop-the-world collection is the easy path: you halt the program, walk the heap, and resume. For a 100 MB heap that pause might be a few milliseconds. For a 100 GB heap, it's the difference between a service that's usable and one that times out every few minutes.

The industry has converged on a remarkably elegant technique to make collection incremental: **tri-color marking**. It's the foundation of the Go runtime's concurrent collector, HotSpot's CMS and G1, and the V8 garbage collector. This post walks through how it works, why the invariant matters, what the write barriers are doing, and what the trade-offs look like in production.

## The Core Idea: Three Colors, One Invariant

Mark-and-sweep has two phases. The mark phase walks every object reachable from a set of roots (stack, globals, registers) and tags it as live. The sweep phase reclaims anything not tagged. In a single-threaded world, this is trivial. In a concurrent world, the mutator is modifying the heap while the collector walks it — and the naive algorithm breaks in subtle ways.

Edsger Dijkstra and his colleagues formalized the solution in the 1970s, and it remains the basis for nearly every concurrent collector shipped today. The idea: paint every object one of three colors, and keep an invariant that holds the algorithm together.

| Color  | Meaning                                                                       |
| ------ | ----------------------------------------------------------------------------- |
| White  | Candidate for garbage. Not yet reached by the collector.                      |
| Grey   | Reached, but its outgoing references have not yet been scanned.               |
| Black  | Reached, and all of its outgoing references have been scanned.              |

The collector starts with roots grey and everything else white. It repeatedly pops a grey object, scans its references, and paints them grey while painting the source black. When no grey objects remain, anything still white is unreachable and can be reclaimed.

The invariant that keeps this correct under mutation is:

> **No black object may point directly to a white object.**

If that condition holds, the white set is provably either unreachable or only reachable through a chain of grey/black objects that the collector will eventually visit. The challenge is that mutators constantly break the invariant by writing new pointers. Fixing it is what write barriers are for.

## Why the Invariant Breaks: The Two Classic Problems

Consider the collector has scanned object A (now black) and is about to look at object B (still white). Two concurrent mutations can each violate the invariant in their own way.

### Problem 1: The Lost Object

The mutator nulls a reference held by black object A and stores it only in a local root or a stack frame. If the collector has already finished scanning the root set, this newly-reachable object never gets visited. The white object ends up reclaimed even though the program still uses it. This is the classic *missing re-roots* problem.

### Problem 2: The Premature Reclamation

The mutator stores a reference to a not-yet-scanned object C inside an already-black object D. The collector never revisits D, so C is never turned grey. When the collector terminates, C is still white and gets swept. This is the *wrongly coloured target* problem — the one Dijkstra originally described.

Both problems are prevented by write barriers. The choice of barrier determines which problem is solved and at what cost.

## Write Barrier Flavors: SATB, Incremental Update, and Deletion

The three barrier families correspond to three different ways of preserving the invariant. They differ in *when* they fire and *what* they do.

### SATB: Snapshot-at-the-Beginning

The SATB barrier, used by the HotSpot G1 collector and originally by CMS, fires on every reference **store** (i.e., when overwriting a field). When the mutator writes a new reference into a black object, the barrier records the *old* value (the reference being overwritten) as a grey object, or pushes it to a SATB buffer. The semantic guarantee: at the moment the collector started, the heap looked a certain way, and we'll keep everything reachable *at that moment* alive, even if the mutator later deletes the path.

This means SATB tends to be conservative: it may keep objects alive a little longer than strictly necessary, but it never prematurely reclaims. The cost is that every reference store incurs a barrier, and the SATB buffer must be drained regularly. The [G1 garbage collector documentation](https://docs.oracle.com/en/java/javase/17/gctuning/garbage-first-garbage-collector.html) describes how this buffer draining fits into the concurrent mark cycle.

### Incremental Update

The incremental update barrier, associated with Dijkstra's original paper, fires on stores that put a reference into an already-black object. The barrier re-colors that target grey (or, in some implementations, re-colors the *source* back to grey). This is the approach the Go runtime uses.

Incremental update tracks liveness more tightly than SATB, which means less floating garbage — objects kept alive past their actual reachability. The cost is that you can re-mark objects the collector has already finished with, and you have to be careful about how write ordering interacts with the mark termination phase.

### Deletion Barrier

The deletion barrier, less common but used in some research collectors, treats an *unstore* specially: when the mutator removes a reference, the old target is greyed. This is symmetric to SATB but at the *write* of the deletion rather than the write of the new value. It's the variant that some JVMs experimented with, though it's mostly of historical and academic interest now.

In practice, almost every shipping runtime uses either SATB or incremental update. HotSpot's CMS originally used incremental update; G1 switched to SATB. Go uses a variant of incremental update. The difference shows up in two measurable places: floating garbage volume and barrier cost under write-heavy workloads.

## How Go Implements This in Practice

The Go runtime is one of the most accessible production implementations to study because the source is public and the algorithm is documented. The [Go runtime source on GitHub](https://github.com/golang/go/blob/master/src/runtime/mgc.go) shows the moving parts directly.

Go's collector uses a **deletion-style hybrid** that combines aspects of both. The barrier — `writePointer` in `mgcmark.go` — runs on every pointer write. When the program overwrites a pointer in a heap object, the runtime checks whether the source is black and the destination is white; if so, the destination is repainted grey. This preserves the invariant without having to instrument reads, which is important because instrumenting reads would be catastrophically expensive on modern CPUs.

The mark phase in Go is organized around a **mark assist** mechanism. If the application allocates faster than the collector can mark, the mutator is required to do some marking itself before it can allocate. This is why you'll sometimes see `GC assist` lines in `GODEBUG=gctrace=1` output — the program is paying down its marking debt.

The cycle is:

1. **Mark setup (STW).** A short stop-the-world pause enables write barriers and prepares root scanning. This is the *first* of two small pauses.
2. **Concurrent mark.** Background workers (one per P, in the current model) traverse the heap while the program runs. Write barriers keep the invariant intact.
3. **Mark termination (STW).** A second short pause drains outstanding mark work, re-scans dirty stacks, and disables barriers.
4. **Concurrent sweep.** Memory is returned to the allocator in the background.

The two STW pauses are bounded and small — typically sub-millisecond on modern hardware for Go programs with modest heap sizes. The concurrent phase is where the heavy lifting happens, and it's where the cost of the write barrier shows up.

## A Concrete Walk-Through

Let's trace what happens with a tiny heap. Imagine three objects: A holds a pointer to B; B holds a pointer to C. Roots point at A. White-grey-black colors assigned to heap objects.

Initial state after mark setup:
- Roots grey
- A, B, C white

Step 1 — scan roots. Pop A. A becomes black. Push B as grey. (Invariant holds: A→B, black→grey is allowed.)

Step 2 — pop B. B becomes black. Push C as grey. (B→C, black→grey is allowed.)

Step 3 — pop C. C becomes black. Nothing to push.

No grey left. A, B, C are all black and live. White objects are unreachable; they get swept.

Now introduce a concurrent mutator. The program, running on another goroutine, does `A.field = &D`, where D is a brand new white object.

Without a barrier: A is black, D is white, A now points to D. **Invariant violated.** The collector will not re-scan A, so D will be reclaimed even though the program uses it.

With Go's barrier: the write barrier observes that A is black and D is white, and repaints D grey. The mark worker will pick D up, scan it (nothing inside), and paint it black. D survives.

Now consider the symmetric case: the program nulls `B.field`, removing the path B→C. C is still white at this point. The barrier — being a *write* barrier, not a *read* barrier — doesn't fire on the deletion in a way that re-greys C. But the path from A→B→C is no longer load-bearing. As long as A→B→C was never the *only* path to C, C gets reclaimed at sweep. If it was the only path, then C is genuinely unreachable and reclamation is correct. Either way, the invariant guarantees we never reclaim an object the program can still reach.

This is the elegance of the design: the barrier doesn't need to know whether the deletion was correct. The invariant is sufficient.

## The Pattern in Production: Stop-the-World Is the Easy Part

The reason concurrent collection is hard isn't the algorithm — it's the bookkeeping. There are four recurring patterns you'll see in any concurrent GC implementation:

**Root scanning with concurrent mutators.** Stacks change every instruction. The Go runtime scans goroutine stacks at mark termination precisely because they were being modified the whole time the concurrent phase was running. Some runtimes (HotSpot) treat the thread stack as a snapshot taken at the start of the cycle; others re-scan at termination.

**Termination detection.** The collector needs a correct, cheap way to decide when to stop. Using "no grey objects left" is correct in isolation, but mutators may be in the middle of a barrier that will produce more grey work. Most collectors drain all SATB buffers or mark queues before terminating.

**Overflow handling.** When the per-thread buffer (or mark queue) fills up, the mutator has to take a slow path: either flush the buffer or, in the worst case, do some of the collector's work itself. Go's mark assist is one form of this. HotSpot's G1 has the *concurrent refinement threads* that drain SATB buffers in the background.

**Floating garbage.** Whichever barrier you pick, some objects will be marked live that are actually unreachable by the time sweep runs. SATB produces more of this than incremental update. This is a non-correctness issue, just a space overhead. The next collection will reclaim it.

You can see the same patterns echoed in completely different runtimes because they solve the same problems. A good place to read about the Java side is Aleksey Shipilëv's blog ([shipilev.net](https://shipilev.net/jvm-anatomy-park/)) and the [OpenJDK HotSpot GC source](https://github.com/openjdk/jdk/tree/master/src/hotspot/share/gc).

## Patterns in Production: What Real Systems Choose

Different languages have made different choices, and those choices reflect their workloads.

Go picked incremental update because it produces less floating garbage for the long-lived, write-heavy services Go is typically deployed for. The two STW pauses are tightly bounded, and the concurrent phase is bounded by GOMAXPROCS, the available parallelism. The cost is that some short allocations can cause mark assist and slow the mutator.

HotSpot G1 picked SATB because it composes better with region-based heap layout. G1 divides the heap into regions, evacuates live data during mixed collections, and uses SATB to keep the snapshot consistent. The cost is more floating garbage between concurrent and evacuation phases, but G1 can fall back to a stop-the-world full GC if the concurrent cycle doesn't keep up.

V8 uses a combination: a tri-color concurrent mark phase, with write barriers implemented in the C++ embedding layer rather than the JIT. The trade-off is similar to Go's. The [V8 blog post on Orinoco](https://v8.dev/blog/orinoco) is a great high-level walk-through if you want the JavaScript take.

Across all of them, the *barrier cost* is the limiting factor. The work the collector does in the background is essentially free; the work the application does because of the barrier is the budget. Optimizing that barrier is where the engineering hours go.

## Key Takeaways

- **Tri-color marking reduces a hard problem (concurrent reachability) to a local one (an invariant enforced at every write).** The collector doesn't have to be globally consistent; the barrier keeps the invariant one write at a time.
- **The invariant is "no black-to-white pointers."** Every barrier style is a different way of preventing this after a mutator write.
- **SATB vs. incremental update is a trade-off, not a one-is-better choice.** SATB has higher floating garbage and more buffer overhead; incremental update can cause more re-scanning and a more complex termination protocol.
- **Stop-the-world pauses are still required, but they're small and bounded.** Modern collectors spend most of their time in concurrent phases; the STW work is setup and termination only.
- **Barrier cost dominates the mutator overhead.** The collector itself is essentially free compared to the per-write instrumentation. This is why every implementation spends enormous effort keeping the barrier fast — inline checks, fast paths, and on-stack buffering to avoid atomic operations.
- **The same patterns recur across runtimes.** If you understand Go's concurrent GC, you're most of the way to understanding G1, CMS, ZGC, and V8's Orinoco. The names change; the structure doesn't.

## Further Reading

- [Dijkstra et al., "On-the-fly Garbage Collection: An Exercise in Cooperation" (1978)](https://www.cs.utexas.edu/~dwyer/cs378/papers/Dijkstra_etal_1978.pdf) — the original tri-color paper, still the cleanest exposition of the invariant.
- [Go runtime: `src/runtime/mgc.go`](https://github.com/golang/go/tree/master/src/runtime/mgc.go) — the actual production implementation, with extensive inline comments.
- [OpenJDK G1 Garbage Collector Documentation](https://docs.oracle.com/en/java/javase/17/gctuning/garbage-first-garbage-collector.html) — Oracle's reference for how G1 applies SATB to a region-based heap.
- [V8 Orinoco: Minor GC and Concurrent Marking](https://v8.dev/blog/orinoco) — a high-level tour of V8's concurrent collector, with diagrams of the mark phases.
- [Shipilëv, "JVM Anatomy Park" series](https://shipilev.net/jvm-anatomy-park/) — a deep, opinionated dive into the internals of HotSpot's GC, with measurements.
- ["The Garbage Collection Handbook" (Jones, Hosking, Moss)](https://www.wiley.com/en-us/The+Garbage+Collection+Handbook%3A+The+Art+of+Automatic+Memory+Management-p-9780884155901) — the comprehensive reference if you want to go from "deep dive" to "everything there is to know."