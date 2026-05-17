---
title: "Why Cheney Semispace Copying Prevents Heap Fragmentation"
date: "2026-05-17T13:00:51.238"
draft: false
tags: ["garbage-collection", "memory-management", "cheney-algorithm", "heap-fragmentation", "runtime"]
description: "An in‑depth look at how Cheney's semispace copying collector eliminates heap fragmentation, with concrete examples, performance analysis, and practical implications."
summary: "Explore why Cheney's semispace copying algorithm inherently prevents heap fragmentation, how it works under the hood, and what trade‑offs developers should consider."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-why-cheney-semispace-copying-prevents-heap-fragmentation.svg"
  alt: "Illustration of two memory semispaces with objects being copied."
  caption: ""
  relative: false
---

> **TL;DR** — Cheney's semispace copying collector moves all live objects into a contiguous region each GC cycle, erasing any gaps left by dead objects. This simple move‑only strategy guarantees a defragmented heap at the cost of using twice the memory and performing extra copy work.

Modern managed runtimes—Java, Go, Ruby, and many functional languages—rely on garbage collection (GC) to reclaim memory without explicit `free` calls. Among the myriad GC strategies, **Cheney's semispace copying collector** stands out for its elegance and its built‑in defense against heap fragmentation. In this article we unpack why the algorithm prevents fragmentation, walk through its mechanics, and discuss the practical implications for language designers and performance‑critical applications.

## The Problem: Heap Fragmentation

### What is fragmentation?

Heap fragmentation occurs when a program’s allocation and deallocation patterns leave the heap peppered with small, unusable gaps. There are two primary flavors:

* **External fragmentation** – free memory is split into many non‑contiguous blocks, preventing large allocations even though the total free space is sufficient.
* **Internal fragmentation** – allocated blocks are larger than needed, wasting space inside each block.

Both forms increase the memory footprint and can trigger premature out‑of‑memory (OOM) errors.

### Why traditional mark‑and‑sweep suffers

Classic **mark‑and‑sweep** collectors traverse the object graph, mark live objects, then sweep the heap, reclaiming unmarked regions. The sweep phase simply marks reclaimed slots as free; it does **not** move live objects. Consequently:

* Surviving objects retain their original addresses, preserving the “holes” left by dead objects.
* Over time, the heap can become a mosaic of live objects and free fragments, leading to external fragmentation.

To mitigate this, many runtimes add a **compaction** phase that slides live objects together, but compaction incurs extra bookkeeping, pointer updating, and often pauses the world for longer periods.

## How Cheney's Semispace Copying Works

### The two‑space model

Cheney’s algorithm divides the heap into two equal‑sized regions, called **from‑space** and **to‑space** (often visualized as `A` and `B`). At any moment, allocation happens only in the active **from‑space**. When the from‑space fills, a GC cycle begins:

1. **Swap roles** – `from‑space` becomes `to‑space` and vice‑versa.
2. **Copy live objects** – Starting from the roots, the collector copies each reachable object into the fresh to‑space, preserving the order of discovery (breadth‑first).
3. ** duplicate copies.
4. **Resume allocation** – After copying, the former from‑space (nowUpdate references** – As objects are copied, a forwarding pointer is left in the original location to avoid empty) becomes the new allocation region.

Because the to‑space starts empty, **every live object ends up packed tightly at the beginning of the region**, leaving a single contiguous free area at the end.

### Pseudocode illustration

```python
# Simplified Cheney copying collector (Python‑like pseudocode)
def cheney_collect(root_set, from_space, to_space):
    # Initialize the_space.start

    # Copy roots into to_space
    for root in root_set:
        new_addr = copy_object(root, from_space, to_space, free)
        root = new_addr          # Update root reference
        free = free + new_addr.size

    # Process objects breadth‑first
    while scan < free:
        obj = scan.dereference()
        for field in obj.references:
            if field.is_in(from_space):
                # Copy if not already moved
                if not field.has_forwarding():
                    new_addr = copy_object(field, from_space, to_space, free)
                    field.set_forwarding(new_addr)
                    free = free + new_addr.size
                # Update reference to point to the copy
                obj.update_field(field, field.forwarding_addr)
        scan = scan + obj.size
```

*`copy_object`* copies the raw bytes from `from_space` to `to_space` and returns the new address. The algorithm never frees individual objects; it simply discards the entire old space after the copy completes.

### Real‑world implementations

* **Java HotSpot’s Serial GC** uses a similar copying scheme for its young generation, known as **PSYoungGen**.
* **Go’s garbage collector** employs a tri‑color marking algorithm but also uses a copying phase for small objects in the “small object heap” (see the Go runtime source: `runtime/mgc.go`).
* **OCaml’s minor heap** is a classic Cheney collector, moving all live objects from the minor to the major heap each minor collection.

## Why It Eliminates Fragmentation

### Live objects become contiguous

Because the collector writes each live object **sequentially** into the empty to‑space, there is no opportunity for gaps to form. The algorithm’s invariant is simple:

> *After a collection, the to‑space contains exactly the set of reachable objects, packed with no intervening free space.*

Therefore, **external fragmentation is impossible**—the only free memory resides in a single contiguous tail.

### No need for a separate compaction pass

Traditional mark‑and‑sweep must add a compaction step to achieve the same effect, which involves:

* Scanning the heap a second time.
* Updating every pointer to the new location.
* Potentially moving objects multiple times if they belong to different generations.

Cheney’s collector **combines marking, copying, and compaction into a single pass**. The “copy” operation inherently compacts, and the “forwarding pointer” technique ensures each object is moved at most once per cycle.

### Predictable allocation pattern

Allocation in the active from‑space proceeds via a bump pointer (also called a **allocation cursor**). This pattern has two benefits:

1. **Constant‑time allocation** – just add the object size to the cursor.
2. **Deterministic fragmentation behavior** – because the entire from‑space is reclaimed at the next collection, the allocator never sees fragmented free blocks.

### Formal reasoning (optional)

Consider the heap as an ordered list of bytes `H = [b₁, b₂, …, b_N]`. Let `L ⊆ H` be the set of live objects after a GC cycle. Cheney’s algorithm constructs a bijection `f: L → [0, Σ size bump pointer at the start of to_space
    scan = to_space.start
    free = to(l_i))` where `Σ size(l_i)` is the total size of live objects. ` complement `H \ f(L)` is a single interval `[Σ size(l_i), N]`.f` maps each live object to a unique offset in to‑space without gaps, guaranteeing that the No external fragmentation can exist because `H \ f(L)` is contiguous.

## Trade‑offs and at least reserving two semispaces). If the application’s memory budget is tight, this can Performance

### Memory overhead

The most obvious cost is **doubling the heap size** (or be prohibitive.

*Mitigation*: Many runtimes allocate the semispaces only for the **young generation**, where most objects die quickly, keeping the overall memory footprint reasonable.

### Copying cost

Each live object is copied each collection, which adds a **write‑heavy** phase. The cost is proportional to the amount of live data, not the total heap size. For workloads with high live‑data ratios, the copying overhead can dominate.

*Mitigation*: Generational heuristics keep most objects in a non‑copying, mark‑sweep “old generation,” limiting copying to, pause times grow with live data size. However, the **breadth‑first** nature of short‑lived objects.

### Pause times

Because the collector must traverse the entire reachable object graph Cheney’s algorithm yields good cache locality, often resulting in shorter pauses than a comparable mark‑sweep1**, **ZGC**, **Shenandoah**) blend copying with concurrent marking to reduce pause + compaction cycle.

### Interaction with other GC strategies

Hybrid collectors (e.g., **G times while still benefiting from fragmentation‑free regions. Understanding Cheney’s core principle helps explain why these modern collectors allocate “regions” that can be reclaimed without moving live objects.

## Real‑World Impact: Case Studies

| Runtime | Semispace Use | Observed Benefits | Notable Trade‑offs |
|---------|---------------|-------------------|--------------------|
| **HotSpot Serial GC** | Young generation only | Predictable pause times, no fragmentation in young gen | Requires larger heap for young gen; copying overhead on each minor GC |
| **Go (1.22)** | Small object heap (≤ 8 KB) | Low latency, simple allocation, no fragmentation for small objects | Larger objects use mark‑sweep, so fragmentation can appear there |
| **OCaml** | Minor heap (default 1 MB) | Extremely fast minor collections, zero fragmentation | Minor heap size limits; long‑lived objects promoted to major heap can fragment |

These examples illustrate that **the fragmentation‑free guarantee is most valuable where allocation rates are high and object lifetimes are shortCopy‑once, compact‑once**: Cheney’s semispace copying moves every live object into**—exactly the scenario Cheney’s algorithm was designed for.

## Key Takeaways

- ** a fresh region, guaranteeing a contiguous layout and eliminating external fragmentation.
- **Memory trade‑off**: The algorithm requires two equally sized semispaces, effectively doubling the heap for the region it manages pause times are predictable but grow with the amount of live data.
- **Generational synergy**:.
- **Performance profile**: Copying cost scales with live data, not total heap size; Most modern runtimes use Cheney’s copying collector for the young generation, where it offers the best ROI.
- **Design insight**: Understanding the copy‑and‑compact nature of Cheney’s algorithm helps (low latency, no fragmentation) while relegating older objects to mark‑sweep or concurrent collectors explain the architecture of hybrid collectors like G1, ZGC, and Shenandoah, which aim to retain fragmentation‑free regions without full‑heap copying.

## Further Reading

- [The original paper by C.J. Cheney (1970)](https://doi.org/10.1145/800119.803464) – The classic description of the copying collector.
- [Java HotSpot VM GC Overview](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/) – Details on Serial, Parallel, and G1 collectors.
- [Go runtime garbage collector design](https://golang.org/doc/articles/gc_design) – Explains Go’s hybrid approach and small‑object copying.
- [OCaml manual: Garbage Collection](https://ocaml.org/manual/garbage-collection.html) – Describes the minor heap copying collector.
- [Understanding G1 GC](https://www.oracle.com/technical-resources/articles/java/g1.html) – Shows how region‑based copying builds on Cheney’s ideas.