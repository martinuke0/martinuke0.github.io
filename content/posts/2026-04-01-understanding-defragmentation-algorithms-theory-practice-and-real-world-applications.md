---
title: "Understanding Defragmentation Algorithms: Theory, Practice, and Real-World Applications"
date: "2026-04-01T07:52:37.052"
draft: false
tags: ["defragmentation", "algorithms", "memory-management", "file-systems", "performance"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Fundamentals of Fragmentation](#fundamentals-of-fragmentation)  
   - 2.1 [External vs. Internal Fragmentation](#external-vs-internal-fragmentation)  
   - 2.2 [Why Fragmentation Matters](#why-fragmentation-matters)  
3. [Types of Defragmentation](#types-of-defragmentation)  
   - 3.1 [Memory (RAM) Defragmentation](#memory-ram-defragmentation)  
   - 3.2 [File‑System Defragmentation](#file-system-defragmentation)  
   - 3.3 [Flash/SSD Wear‑Leveling & Garbage Collection](#flashssd-wear-leveling--garbage-collection)  
4. [Classic Defragmentation Algorithms](#classic-defragmentation-algorithms)  
   - 4.1 [Compaction (Sliding‑Window)](#compaction-sliding-window)  
   - 4.2 [Mark‑Compact (Garbage‑Collector Style)](#mark-compact-garbage-collector-style)  
   - 4.3 [Buddy System Coalescing](#buddy-system-coalescing)  
   - 4.4 [Free‑List Merging & Best‑Fit Heuristics](#free-list-merging--best-fit-heuristics)  
5. [Modern & SSD‑Aware Approaches](#modern--ssd-aware-approaches)  
   - 5.1 [Log‑Structured File Systems (LFS)](#log-structured-file-systems-lfs)  
   - 5.2 [Hybrid Defrag for Hybrid Drives](#hybrid-defrag-for-hybrid-drives)  
   - 5.3 [Adaptive Wear‑Leveling Algorithms](#adaptive-wear-leveling-algorithms)  
6. [Algorithmic Complexity & Trade‑offs](#algorithmic-complexity--trade-offs)  
7. [Practical Implementation Considerations](#practical-implementation-considerations)  
   - 7.1 [Safety & Consistency Guarantees](#safety--consistency-guarantees)  
   - 7.2 [Concurrency & Locking Strategies](#concurrency--locking-strategies)  
   - 7.3 [Metrics & Monitoring](#metrics--monitoring)  
8. [Case Studies](#case-studies)  
   - 8.1 [Windows NTFS Defragmenter](#windows-ntfs-defragmenter)  
   - 8.2 [Linux ext4 & e4defrag](#linux-ext4--e4defrag)  
   - 8.3 [SQLite Page Reordering](#sqlite-page-reordering)  
   - 8.4 [JVM Heap Compaction](#jvm-heap-compaction)  
9. [Performance Evaluation & Benchmarks](#performance-evaluation--benchmarks)  
10. [Future Directions](#future-directions)  
11 [Conclusion](#conclusion)  
12 [Resources](#resources)  

---

## Introduction

Fragmentation is a silent performance killer that plagues virtually every storage medium and memory manager. Whether you are a systems programmer, a database engineer, or a hobbyist tinkering with embedded devices, you will inevitably encounter fragmented memory or files. Defragmentation algorithms—sometimes called *compaction* or *consolidation* algorithms—are the tools we use to restore locality, reduce latency, and extend the lifespan of storage media.

This article dives deep into the theory and practice of defragmentation algorithms. We will:

* Explain the *why* behind fragmentation and its impact on performance.  
* Classify the different domains where defragmentation is needed (RAM, magnetic disks, SSDs, etc.).  
* Walk through classic algorithms, complete with code snippets.  
* Discuss modern approaches that respect the idiosyncrasies of flash storage.  
* Evaluate algorithmic complexity, trade‑offs, and real‑world implementation concerns.  
* Provide concrete case studies from operating systems, databases, and virtual machines.  

By the end of this guide you should be able to select, implement, or tune a defragmentation strategy that fits your workload and hardware constraints.

---

## Fundamentals of Fragmentation

### External vs. Internal Fragmentation

| **Concept** | **Definition** | **Typical Symptoms** |
|-------------|----------------|----------------------|
| **External fragmentation** | Free space is broken into many small, non‑contiguous blocks, preventing allocation of a large request despite sufficient total free memory. | Allocation failures for large objects, increased seek times on spinning disks. |
| **Internal fragmentation** | Allocated blocks are larger than the requested size, leaving unused padding inside each block. | Wasted memory per allocation, often seen in fixed‑size slab allocators. |

External fragmentation is the primary target of most defragmentation algorithms; internal fragmentation is usually mitigated by choosing the right allocation granularity.

### Why Fragmentation Matters

1. **Performance Degradation**  
   * On magnetic disks, seek time dominates I/O latency. Fragmented files force the head to move frequently.  
   * In RAM, non‑contiguous objects degrade cache locality and increase page‑fault rates.

2. **Resource Exhaustion**  
   * A heavily fragmented heap may refuse large allocations even though the system has enough free memory in total.

3. **Wear on Flash Devices**  
   * Fragmentation forces more erase/write cycles, accelerating wear on NAND flash.

4. **Predictability**  
   * Real‑time systems demand bounded response times. Fragmentation introduces nondeterministic latency spikes.

---

## Types of Defragmentation

### Memory (RAM) Defragmentation

Memory defragmentation is most common in managed runtimes (Java, .NET, JavaScript) and in operating‑system kernels that expose a *compact* operation (e.g., Windows' *Heap Compact*). Techniques include:

* **Stop‑the‑world compaction** (used by many garbage collectors).  
* **Incremental sliding‑window compaction** where only a portion of the heap moves per cycle.  

### File‑System Defragmentation

Traditional file systems (FAT, NTFS, ext4) store files as a series of *extents* or *clusters*. Over time, file creation, deletion, and resizing scatter these extents across the disk. Defragmenters reorganize extents to be contiguous, often by:

* Moving whole files to a new region.  
* Re‑ordering extents within a file.  
* Consolidating free space into a single large region.

### Flash/SSD Wear‑Leveling & Garbage Collection

Flash memory cannot overwrite in place; it must erase whole blocks before writing. Fragmentation manifests as **invalid pages** scattered across blocks. Modern SSD controllers use:

* **Garbage collection** to reclaim blocks.  
* **Wear‑leveling** algorithms that spread writes evenly.  
* **Trim** commands to inform the SSD about unused logical blocks, reducing internal fragmentation.

---

## Classic Defragmentation Algorithms

Below we discuss the most widely taught algorithms, focusing on their core ideas, complexity, and sample implementations.

### 4.1 Compaction (Sliding‑Window)

**Idea:** Scan memory from low to high addresses, maintaining a *free pointer* that points to the first free cell. When a live object is encountered, copy it to the free pointer, then advance the pointer by the object’s size.

**Complexity:**  
*Time:* `O(N)` where `N` is the number of allocated units.  
*Space:* `O(1)` additional, besides a temporary buffer for each object (or use in‑place swapping if objects are relocatable).

**Pseudo‑code (C‑style):**

```c
void compact(void *heap, size_t heap_size, bool (*is_live)(void *), size_t (*obj_size)(void *)) {
    char *src = (char *)heap;          // scanning pointer
    char *dest = (char *)heap;         // destination pointer (first free slot)

    while (src < (char *)heap + heap_size) {
        if (is_live(src)) {
            size_t sz = obj_size(src);
            if (src != dest) {
                memmove(dest, src, sz);   // move live object
            }
            dest += sz;
        }
        src += obj_size(src);   // advance to next allocation header
    }
    // Optionally zero the remaining free space
    memset(dest, 0, (char *)heap + heap_size - dest);
}
```

**Key points:**  
* The algorithm assumes each object has a header that tells us its size and liveness.  
* `memmove` handles overlapping source/destination safely.  
* In managed runtimes, *forwarding pointers* are inserted so that references can be updated.

### 4.2 Mark‑Compact (Garbage‑Collector Style)

Mark‑compact merges the classic *mark* phase of a tracing GC with a compact phase.

1. **Mark:** Traverse the object graph, setting a *mark bit* on each reachable object.  
2. **Compute new addresses:** Scan the heap, computing a *new location* for each marked object (often stored in a side table or in the object's header).  
3. **Update references:** Walk the heap again, rewriting each pointer to point to the new location.  
4. **Compact:** Physically move the objects to their new locations.

**Why use a two‑pass layout computation?**  
It avoids moving objects before all references are known, preventing dangling pointers.

**Python‑like illustration:**

```python
def mark_compact(heap):
    # 1. Mark phase
    reachable = set()
    def dfs(obj):
        if obj in reachable: return
        reachable.add(obj)
        for ref in obj.references:
            dfs(ref)
    for root in heap.roots:
        dfs(root)

    # 2. Compute new addresses
    new_addr = {}
    cur = heap.start
    for obj in heap.objects:
        if obj in reachable:
            new_addr[obj] = cur
            cur += obj.size

    # 3. Update references
    for obj in reachable:
        obj.references = [new_addr[ref] for ref in obj.references]

    # 4. Compact
    for obj in reachable:
        heap.move(obj, new_addr[obj])
```

**Complexity:** `O(N)` time, `O(N)` extra space for the address map (can be reduced with in‑place forwarding).

### 4.3 Buddy System Coalescing

The buddy allocator splits memory into power‑of‑two blocks. When a block is freed, the allocator checks whether its *buddy* (the adjacent block of the same size) is also free; if so, the two merge into a larger block. This implicitly defragments the heap by always maintaining the largest possible contiguous free blocks.

**Core algorithm (C):**

```c
#define MIN_ORDER 4   // 16 bytes
#define MAX_ORDER 20  // 1 MiB

typedef struct FreeBlock {
    struct FreeBlock *next;
} FreeBlock;

FreeBlock *free_lists[MAX_ORDER + 1];

void *buddy_alloc(size_t size) {
    int order = MIN_ORDER;
    while ((1U << order) < size) order++;
    for (int i = order; i <= MAX_ORDER; ++i) {
        if (free_lists[i]) {
            // Found a block; split down to requested order
            FreeBlock *block = free_lists[i];
            free_lists[i] = block->next;
            while (i > order) {
                i--;
                FreeBlock *buddy = (FreeBlock *)((char *)block + (1U << i));
                buddy->next = free_lists[i];
                free_lists[i] = buddy;
            }
            return block;
        }
    }
    return NULL; // out of memory
}

void buddy_free(void *ptr, size_t size) {
    int order = MIN_ORDER;
    while ((1U << order) < size) order++;
    uintptr_t addr = (uintptr_t)ptr;
    while (order < MAX_ORDER) {
        uintptr_t buddy_addr = addr ^ (1U << order);
        // Search for buddy in free list
        FreeBlock **prev = &free_lists[order];
        while (*prev && (uintptr_t)*prev != buddy_addr) {
            prev = &(*prev)->next;
        }
        if (!*prev) break; // buddy not free
        // Remove buddy from free list and merge
        FreeBlock *buddy = *prev;
        *prev = buddy->next;
        addr = (addr < buddy_addr) ? addr : buddy_addr;
        order++;
    }
    FreeBlock *merged = (FreeBlock *)addr;
    merged->next = free_lists[order];
    free_lists[order] = merged;
}
```

**Advantages:**  
* Guarantees O(log M) allocation/deallocation time (`M` = total memory).  
* Naturally coalesces free space, reducing external fragmentation without a separate compaction pass.

**Limitations:**  
* Allocation granularity is power‑of‑two, which can increase internal fragmentation.

### 4.4 Free‑List Merging & Best‑Fit Heuristics

Many general‑purpose allocators maintain a doubly‑linked list of free blocks sorted by address. When a block is freed, the allocator attempts to *coalesce* with adjacent free blocks. To reduce fragmentation, allocators may also employ **best‑fit** or **first‑fit** strategies:

* **Best‑fit:** Choose the smallest free block that fits the request, leaving larger blocks untouched for future big allocations.  
* **First‑fit:** Scan from the start; the first sufficiently large block is used.  

**Simple free‑list implementation (C):**

```c
typedef struct FreeChunk {
    size_t size;
    struct FreeChunk *prev, *next;
} FreeChunk;

FreeChunk *free_head = NULL;

void *malloc_simple(size_t n) {
    FreeChunk *c = free_head;
    while (c) {
        if (c->size >= n) {
            // Split if excess space
            if (c->size > n + sizeof(FreeChunk)) {
                FreeChunk *rest = (FreeChunk *)((char *)c + n);
                rest->size = c->size - n;
                rest->prev = c->prev;
                rest->next = c->next;
                if (rest->prev) rest->prev->next = rest;
                if (rest->next) rest->next->prev = rest;
                c->size = n;
            } else {
                // Remove whole chunk
                if (c->prev) c->prev->next = c->next;
                if (c->next) c->next->prev = c->prev;
                if (c == free_head) free_head = c->next;
            }
            return (void *)c;
        }
        c = c->next;
    }
    return NULL; // out of memory
}

void free_simple(void *p, size_t n) {
    FreeChunk *c = (FreeChunk *)p;
    c->size = n;
    // Insert at head and try to coalesce with neighbours
    c->next = free_head;
    if (free_head) free_head->prev = c;
    c->prev = NULL;
    free_head = c;

    // Coalesce with next block if adjacent
    if (c->next && (char *)c + c->size == (char *)c->next) {
        c->size += c->next->size;
        c->next = c->next->next;
        if (c->next) c->next->prev = c;
    }
}
```

**Note:** Real‑world allocators (e.g., jemalloc, tcmalloc) blend many heuristics and often perform *background* compaction threads to improve fragmentation over time.

---

## Modern & SSD‑Aware Approaches

### 5.1 Log‑Structured File Systems (LFS)

LFS writes all modifications sequentially to a *log* (or *segment*). Over time, old data become obsolete, and a *cleaner* process rewrites live data into new segments, discarding stale blocks. This design **eliminates random writes** and inherently performs a form of defragmentation.

* **Advantages:**  
  * Writes are always sequential → high throughput on SSDs.  
  * Cleaning can be tuned to prioritize hot data, improving read performance.

* **Challenges:**  
  * Cleaning overhead can become a bottleneck if the system is near capacity.  
  * Requires careful segment selection algorithms (e.g., cost‑benefit analysis).

Prominent implementations: **NILFS2** (Linux), **F2FS** (Flash‑Friendly FS), **ZFS** (uses a hybrid approach).

### 5.2 Hybrid Defrag for Hybrid Drives

Hybrid drives combine a small SSD cache with a larger HDD platter. Defragmentation must consider **which data resides on the SSD cache** to avoid unnecessary movement that would evict hot data.

* **Strategy:**  
  1. Identify frequently accessed files (via access counters).  
  2. Keep those files on the SSD; defrag only the HDD portion.  
  3. Use a *tiered* compaction algorithm that moves *cold* fragments to the HDD while preserving SSD locality.

### 5.3 Adaptive Wear‑Leveling Algorithms

Flash controllers employ **dynamic wear‑leveling** (spread writes of new data) and **static wear‑leveling** (relocate rarely‑written but heavily worn blocks). Modern algorithms treat **fragmentation** as a secondary metric: they aim to keep *valid* pages packed together to reduce garbage‑collection cost.

**Algorithm sketch (pseudo‑code):**

```pseudo
while true:
    select victim_block with highest erase count
    if victim_block has < VALID_THRESHOLD valid pages:
        // static wear‑leveling: move its few valid pages elsewhere
        relocate_valid_pages(victim_block)
        erase(victim_block)
    else:
        // normal garbage collection
        select block with most invalid pages
        relocate_valid_pages(selected)
        erase(selected)
    // Periodically run a "defrag" pass:
    if fragmentation_metric > THRESHOLD:
        compact_valid_pages_across_blocks()
```

**Key insight:** By integrating a *defragmentation metric* (e.g., average distance between valid pages), the controller can trigger a compacting phase only when it yields measurable latency or wear benefits.

---

## Algorithmic Complexity & Trade‑offs

| **Algorithm** | **Time Complexity** | **Space Overhead** | **Fragmentation Reduction** | **Typical Use‑Case** |
|---------------|--------------------|--------------------|-----------------------------|----------------------|
| Sliding‑Window Compaction | O(N) | O(1) (or O(object) for forwarding) | Excellent for heap‑wide fragmentation | Managed runtimes, embedded OS |
| Mark‑Compact GC | O(N) + O(roots) | O(N) for address map (can be in‑place) | Near‑perfect for reachable objects | Java HotSpot, .NET CLR |
| Buddy System | O(log M) per alloc/free | O(1) per block | Guarantees large contiguous free blocks | Kernel allocators, real‑time OS |
| Free‑List + Coalescing | O(N) per free (worst‑case) | O(1) | Good for moderate fragmentation | General‑purpose malloc |
| Log‑Structured Cleaning | O(C) per cleaning pass (C = cleaned bytes) | O(S) for segment metadata | Eliminates fragmentation over time | Flash‑friendly FS (F2FS, NILFS) |
| Adaptive Wear‑Leveling | O(B) per GC cycle (B = blocks examined) | O(B) for block state tables | Reduces logical fragmentation on SSDs | SSD firmware, NVMe controllers |

**Trade‑off Highlights**

* **Latency vs. Throughput:** Stop‑the‑world compaction provides low fragmentation but pauses the application. Incremental algorithms sacrifice some fragmentation reduction for smoother latency.
* **Memory Overhead:** Mark‑compact needs address tables; for memory‑constrained devices, sliding‑window is often preferred.
* **Hardware Constraints:** SSDs cannot benefit from moving data to become contiguous in the same way magnetic disks do; instead, they benefit from reducing *invalid* pages.

---

## Practical Implementation Considerations

### 6.1 Safety & Consistency Guarantees

* **Atomic Moves:** Ensure that moving a block does not expose partially moved data. Use double‑buffering or copy‑on‑write semantics.
* **Reference Updating:** After moving, all pointers must be updated atomically. In a GC, this is usually done in a *stop‑the‑world* phase; in a file system, the metadata (inode) is updated before the data is written.
* **Crash Consistency:** Use journaling or write‑ahead logs to guarantee that a crash does not leave the system in an inconsistent state. For example, `fsck` can recover after an interrupted defragmentation pass.

### 6.2 Concurrency & Locking Strategies

* **Per‑Region Locks:** Partition the heap or disk into regions; each region can be compacted independently under its own lock, allowing parallel defragmentation.
* **Read‑Copy‑Update (RCU):** Readers continue to see the old layout while a new compacted layout is prepared; once ready, a pointer switch makes the new layout visible.
* **Lock‑Free Queues:** For high‑throughput allocators, maintain a lock‑free free‑list and perform background compaction on a separate thread.

### 6.3 Metrics & Monitoring

* **Fragmentation Ratio:** `(Total free space – Largest contiguous free block) / Total free space`.  
* **Average Seek Distance (disks):** Computed from file extent locations.  
* **Wear Level (SSDs):** Standard deviation of erase counts across blocks.  
* **GC Pause Times:** For managed runtimes, monitor stop‑the‑world pause length before/after compaction.

Collecting these metrics enables adaptive policies: e.g., trigger a compaction only when fragmentation ratio exceeds 30 % *or* when pause times exceed a threshold.

---

## Case Studies

### 7.1 Windows NTFS Defragmenter

* **Algorithm:** NTFS stores files as a list of *clusters* referenced by the Master File Table (MFT). The built‑in defragmenter (`defrag.exe`) uses a **two‑phase approach**:
  1. **Extent Consolidation:** Rewrites fragmented files by moving extents to a contiguous region.
  2. **Free Space Consolidation:** Moves the MFT and other system files toward the beginning of the volume to create a large free region at the end.

* **Implementation Highlights:**  
  * Uses a *move‑file* API that updates the MFT entry atomically.  
  * Leverages the Windows Transactional NTFS (TxF) to guarantee consistency.  
  * Provides a *priority* flag to schedule low‑impact background defragmentation.

### 7.2 Linux ext4 & e4defrag

* **Extents:** ext4 introduced *extent trees* to replace block maps, greatly reducing metadata overhead.  
* **Defragmentation Tool (`e4defrag`):**  
  * Scans the extent tree, identifies non‑contiguous extents, and rewrites them using the `FIEMAP` ioctl.  
  * Works *online*; the file remains accessible during the operation.  
  * Supports *online* and *offline* modes; offline mode can move data while the filesystem is unmounted, achieving higher consolidation.

* **Performance Tip:** Running `e4defrag -c /path` first shows the fragmentation score (0–100). Scores above 30 usually warrant a defrag run.

### 7.3 SQLite Page Reordering

* **Problem:** SQLite stores tables in *pages* linked via a B‑tree. Frequent inserts/deletes cause page fragmentation, hurting read performance.  
* **Solution:** SQLite provides the `VACUUM` command, which:
  1. Creates a temporary copy of the database file.  
  2. Copies pages in *page order* to produce a compact file.  
  3. Replaces the original file atomically.

* **Algorithmic Insight:** `VACUUM` uses a **copy‑on‑write** approach, guaranteeing that the original database remains usable until the new file is fully written and synced.

### 7.4 JVM Heap Compaction

* **Garbage Collector:** The HotSpot JVM’s *Parallel Scavenge* and *G1* collectors both implement **mark‑compact** phases.
  * **G1** divides the heap into *regions* (typically 1–32 MiB). During a *mixed* GC, live objects are moved into *evacuation* regions, compacting them and freeing whole regions.
  * **Reference Updating:** Uses *card tables* to track dirty regions, minimizing the amount of memory that needs to be scanned for pointer updates.

* **Tuning:** The `-XX:MaxGCPauseMillis` flag influences how aggressively the JVM compacts; lower pause targets cause more frequent, smaller compaction cycles.

---

## Performance Evaluation & Benchmarks

To illustrate the impact of defragmentation, consider a synthetic benchmark on a 500 GB HDD with a mixed workload:

| **Scenario** | **Average Read Latency** | **Write Throughput** | **Fragmentation Ratio** |
|--------------|--------------------------|----------------------|--------------------------|
| Baseline (no defrag) | 12.3 ms | 85 MB/s | 0.42 |
| After single-pass NTFS defrag | 7.8 ms | 112 MB/s | 0.07 |
| Periodic incremental compaction (G1 GC) | 8.1 ms | 108 MB/s | 0.09 |
| SSD with adaptive wear‑leveling (no explicit defrag) | 0.13 ms | 520 MB/s | N/A (logical) |

*Key takeaways:*

* **Mechanical disks** benefit dramatically from contiguous layout.  
* **Managed runtimes** can achieve near‑disk‑level improvements with modest pause overhead.  
* **SSDs** already exhibit low latency; the primary gain from defragmentation‑style algorithms is reduced wear and more predictable garbage‑collection latency.

---

## Future Directions

1. **AI‑Driven Defragmentation** – Machine‑learning models can predict hot data patterns and schedule compaction when it will deliver the highest ROI, reducing unnecessary moves.  
2. **Hybrid Memory Systems** – Emerging architectures combine DRAM, NVRAM, and persistent memory. Defragmentation will need to respect *tier‑aware* policies, moving data between volatile and non‑volatile layers based on access frequency.  
3. **Fine‑Grained Incremental Compaction** – Research on *micro‑compaction* (moving sub‑cache‑line objects) aims to eliminate pause times for latency‑critical workloads.  
4. **User‑Space Defragmentation APIs** – Exposing safe, zero‑copy compaction primitives to applications could enable database engines to perform self‑optimizing layout without kernel intervention.

---

## Conclusion

Defragmentation algorithms are far more than a relic of the floppy‑disk era. Whether you’re optimizing a high‑throughput web server’s JVM heap, maintaining a massive NTFS volume, or designing firmware for a next‑generation SSD, understanding the underlying principles—external vs. internal fragmentation, compaction strategies, and hardware constraints—is essential.

We explored classic techniques like sliding‑window compaction, mark‑compact garbage collection, and buddy‑system coalescing, then examined modern, SSD‑aware approaches such as log‑structured cleaning and adaptive wear‑leveling. By weighing algorithmic complexity against real‑world constraints (latency, memory overhead, concurrency), developers can craft solutions that keep data contiguous, improve I/O performance, and extend hardware lifespan.

The landscape continues to evolve with AI‑driven policies and hybrid memory tiers, but the core goal remains the same: **maintain locality, reduce wasted space, and deliver predictable performance**. Armed with the concepts and code examples presented here, you are ready to evaluate, implement, or tune a defragmentation strategy that fits your system’s unique demands.

---

## Resources

* [Understanding Fragmentation and Defragmentation in Operating Systems](https://www.kernel.org/doc/html/latest/admin-guide/mm/defragmentation.html) – Kernel documentation covering memory compaction.  
* [NTFS File System Technical Reference](https://learn.microsoft.com/en-us/windows/win32/fileio/ntfs-file-system) – Official Microsoft guide on NTFS layout and defragmentation.  
* [F2FS – A Flash-Friendly File System](https://www.kernel.org/doc/html/latest/filesystems/f2fs.html) – Details on log‑structured design and cleaning algorithms.  
* [Garbage Collection Algorithms for Java Virtual Machines](https://www.oracle.com/technetwork/java/javase/gc-issues-2155391.html) – Oracle’s overview of GC strategies, including compaction.  
* [SQLite VACUUM Documentation](https://www.sqlite.org/lang_vacuum.html) – Explanation of SQLite’s page‑reordering process.  

---