---
title: "The Mechanical Reality of Cheney Semispace Copying"
date: "2026-05-17T12:00:53.369"
draft: false
tags: ["garbage-collection","cheney-algorithm","memory-management","runtime","systems"]
description: "An in‑depth exploration of Cheney's semispace copying collector, covering its mechanical steps, performance trade‑offs, and practical implementation tips."
summary: "Discover how Cheney's semispace copying algorithm works under the hood, why it matters for modern runtimes, and what pitfalls to avoid when implementing it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-the-mechanical-reality-of-cheney-semispace-copying.png"
  alt: "Illustration of two memory semispaces with arrows indicating copying."
  caption: ""
  relative: false
---

> **TL;DR** — Cheney's semispace copying collector divides the heap into two equal regions, continuously copying live objects from the from‑space to the to‑space during collection. The algorithm offers simple pause‑time guarantees but demands careful handling of pointer updates, object forwarding, and memory fragmentation.

Garbage collection is often presented as a black‑box service that magically reclaims memory, yet the underlying mechanics of a collector can dramatically affect a language’s performance characteristics. Among the classic algorithms, Cheney’s semispace copying collector stands out for its elegance and deterministic pause behaviour. This article pulls back the curtain, describing each mechanical step, analysing the runtime costs, and offering concrete guidance for engineers who need to implement or tune a Cheney‑style collector in a production runtime.

## How Cheney’s Algorithm Works

At its core, Cheney’s algorithm is a breadth‑first copying collector that operates on a **semispace** model: the heap is split into two equal halves, called *from‑space* and *to‑space*. Only one semispace is active for allocation; the other is reserved for the next collection cycle.

### The Semispace Model

1. **Allocation Region** – All new objects are allocated linearly in the active semispace (the *from‑space*) using a simple bump pointer.  
2. **Collection Trigger** – When the bump pointer reaches the end of from‑space, a collection is started.  
3. **Swap** – After the collection finishes, the roles of the two semispaces are swapped: the former *to‑space* becomes the new *from‑space* and vice‑versa.

This model eliminates fragmentation within a semispace because objects are always packed tightly during copying. The trade‑off is that the usable heap size is effectively halved.

### The Copy Phase

The copy phase proceeds in three tightly coupled steps:

1. **Root Scanning** – All root references (stack slots, registers, global variables) are examined. Each root pointing into from‑space is *forwarded* to a newly allocated copy in to‑space. The root is then updated to point at the new location.  
2. **Worklist Traversal** – Cheney uses a single worklist pointer, often called `scan`. It starts at the beginning of to‑space and walks forward. For each object it encounters, it scans the object’s fields; any field that references from‑space is copied to the end of to‑space (the *free* pointer) and the field is updated to the new address.  
3. **Termination** – When `scan` catches up to `free`, every reachable object has been copied and the algorithm terminates.

The following pseudo‑code illustrates the core loop in Python‑like syntax:

```python
def cheney_collect(root_set):
    # 1. Prepare to‑space
    to_space = allocate_semispace()
    free = to_space.start
    scan = free

    # 2. Forward roots
    for root in root_set:
        if in_from_space(root):
            new_addr = copy_object(root, to_space, free)
            free += object_size(root)
            root = new_addr   # update the root reference

    # 3. Breadth‑first scan
    while scan < free:
        obj = read_object_at(scan)
        for field in obj.fields:
            if in_from_space(field):
                new_addr = copy_object(field, to_space, free)
                free += object_size(field)
                field = new_addr   # update the field in the copied object
        scan += object_size(obj)

    # 4. Swap spaces
    swap_semispaces()
```

**Key mechanical details**:

- **Forwarding Pointer** – When an object is first copied, a small *forwarding pointer* is left in the original location (often stored in the object header). Subsequent encounters with the same original object read this pointer instead of copying again.  
- **Object Size Calculation** – Accurate size computation is essential for advancing `scan` and `free`. Most runtimes store the size in the object header.  
- **Alignment** – Objects must respect alignment constraints (e.g., 8‑byte alignment on 64‑bit machines). The allocator pads `free` accordingly.

### Example Walkthrough

Consider a tiny program with three objects: `A` (root) points to `B`, and `B` points to `C`. All reside in from‑space.

1. **Root Scan** – `A` is copied to to‑space at address `0x1000`. Its forwarding pointer is stored at the old location (`0x2000`). `free` now points to `0x1000 + size(A)`.  
2. **Scan = 0x1000** – The collector reads the copied `A`. It discovers the field referencing `B`. Since `B` is still in from‑space, it is copied to `free` (say `0x1010`). The field inside the copied `A` is updated to `0x1010`. `free` advances.  
3. **Scan = 0x1010** – The copied `B` is examined, finds a reference to `C`, copies `C` to `free` (`0x1020`), updates the field, and advances `free`.  
4. **Scan = 0x1020** – The copied `C` has no outgoing references, so the loop ends when `scan == free`.

All three objects now live contiguously in to‑space, and the old from‑space can be reclaimed wholesale.

## Performance Characteristics

Understanding the mechanical cost of each phase helps developers predict pause times and throughput.

### Time Complexity

- **Linear in Live Data** – The algorithm touches each live object exactly once (plus its header for the forwarding pointer). Therefore, the collection time is `O(L)`, where `L` is the total size of live objects.  
- **Root Set Cost** – Scanning roots is `O(R)`, with `R` being the number of roots, typically negligible compared to `L`.  
- **No Mark Phase** – Because copying implicitly marks live objects, there is no separate mark pass, reducing overall overhead.

### Space Overhead

- **Semispace Duplication** – The heap must be twice as large as the maximum live data set, which can be a limiting factor on memory‑constrained devices.  
- **Forwarding Pointers** – Each object temporarily occupies two locations (original + copy) plus a forwarding entry, but this overhead disappears after the collection.

### Pause Time Predictability

Since the collector runs to completion before the program resumes, the pause duration is directly proportional to the amount of live data. This deterministic behaviour is valuable for real‑time systems where worst‑case latency matters.

### Cache Behaviour

- **Sequential Access** – The bump‑pointer allocation and breadth‑first scan produce largely sequential memory accesses, which are cache‑friendly.  
- **Write‑Barrier Cost** – Some runtimes employ a write barrier to maintain invariants during incremental or generational extensions; in a pure Cheney collector, this is unnecessary, further improving locality.

## Implementation Pitfalls

Even with a conceptually simple algorithm, real‑world implementations encounter subtle challenges.

### 1. Forwarding Pointer Placement

If the object header is not large enough to hold a forwarding address, a common workaround is to store the pointer in the first word of the object's body. However, this collides with languages that use the first field for user data. The safe approach is:

- Reserve a *tagged* header field that can hold either a type tag or a forwarding address.  
- Use a distinguished bit pattern (e.g., the least‑significant bit set) to indicate a forwarding pointer, as described in the *Baker* algorithm.

```c
// C example: store forwarding pointer in header
typedef struct {
    uintptr_t header; // high bits: type tag, low bit: forward flag
    // object fields follow
} ObjHeader;

static inline bool is_forwarded(ObjHeader *obj) {
    return (obj->header & 1) != 0;
}
static inline ObjHeader* forwarding_addr(ObjHeader *obj) {
    return (ObjHeader*)(obj->header & ~((uintptr_t)1));
}
```

### 2. Handling Weak References

Weak references must not keep an object alive, yet they need to be updated if the referent moves. A typical solution is to maintain a separate *weak reference table* that is scanned after the main copy phase:

- For each weak entry, check whether the target has been forwarded.  
- If forwarded, update the weak entry; otherwise, clear it.

The table is usually small, so the extra scan does not dominate performance.

### 3. Dealing with Finalizers

Objects with finalizers (destructors) require special handling because they may need to be resurrected after collection. The common strategy is:

1. After copying, place objects with finalizers on a *finalizer queue*.  
2. Run finalizers; if a finalizer re‑references an object, that object must be treated as live and copied again.  
3. Repeat until the queue stabilises.

This introduces a second, potentially non‑deterministic pause, but is necessary for correct semantics.

### 4. Multi‑Threaded Mutators

In a concurrent environment, mutator threads may write to objects while the collector is scanning. Without a write barrier, the collector could miss newly created references. Options include:

- **Stop‑the‑World** – Pause all mutators during the entire collection (simplest, but increases pause time).  
- **Snapshot‑At‑The‑Beginning (SATB)** – Use a write barrier that records any pointer writes made after the collection starts, ensuring the collector eventually sees them. This hybrid approach retains most of Cheney’s simplicity while supporting concurrency.

### 5. Alignment and Padding Bugs

Incorrect alignment can cause subtle crashes on architectures that require word‑aligned accesses. Always round `free` up to the required alignment after each allocation:

```python
def align_up(addr, align):
    return (addr + (align - 1)) & ~(align - 1)

free = align_up(free, OBJECT_ALIGNMENT)
```

Neglecting this step may lead to hard‑to‑diagnose segmentation faults.

## Real‑World Uses

While Cheney’s algorithm originated in the early Lisp implementations of the 1970s, its principles survive in modern runtimes:

- **Java HotSpot** – The *Serial* GC is a stop‑the‑world copying collector that uses a semispace model for small heaps.  
- **OCaml** – The default garbage collector employs a generational copying scheme where the young generation is a classic semispace collector.  
- **Go** – The *tiny* allocator for very small objects resembles a bump‑pointer allocator, and the *concurrent* collector incorporates copying phases inspired by Cheney’s breadth‑first scan.

These systems adapt the basic algorithm to their specific performance goals, adding generational layers, concurrent marking, or incremental sweeping.

## Key Takeaways

- Cheney’s semispace copying collector divides memory into two equal halves, copying live objects from *from‑space* to *to‑space* in a breadth‑first manner.  
- The algorithm’s pause time is linear in the amount of live data, providing predictable latency for real‑time workloads.  
- Implementation challenges include forwarding pointer storage, weak reference handling, finalizer support, and multi‑threaded safety.  
- Modern runtimes (HotSpot, OCaml, Go) still rely on the core ideas of Cheney’s algorithm, often layering generational or concurrent techniques on top.  
- Proper alignment, careful management of object headers, and an explicit post‑copy weak‑reference scan are essential for a robust implementation.

## Further Reading

- [The Garbage Collection Handbook – Richard Jones, Antony Hosking, and Eliot Moss](https://www.cs.cmu.edu/~rwh/papers/GCbook.pdf)  
- [Wikipedia: Cheney's algorithm](https://en.wikipedia.org/wiki/Cheney%27s_algorithm)  
- [Java HotSpot VM Garbage Collection Tuning Guide](https://www.oracle.com/java/technologies/javase/gc-tuning.html)  
- [OCaml Manual – Memory Management](https://ocaml.org/manual/memory.html)  
- [Go Memory Management](https://golang.org/doc/gc)