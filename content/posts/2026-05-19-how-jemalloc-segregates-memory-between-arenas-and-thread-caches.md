---
title: "How jemalloc Segregates Memory Between Arenas and Thread Caches"
date: "2026-05-19T08:00:07.497"
draft: false
tags: ["jemalloc","memory management","arenas","thread cache","performance"]
description: "Explore how jemalloc divides memory across arenas and per‑thread caches, improving allocation speed and reducing contention in multithreaded programs."
summary: "A deep dive into jemalloc's arena and thread‑cache design, showing how they work together to deliver low‑latency memory allocation."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-how-jemalloc-segregates-memory-between-arenas-and-thread-caches.svg"
  alt: "Diagram of jemalloc's arena and thread cache hierarchy."
  caption: ""
  relative: false
---

> **TL;DR** — jemalloc isolates allocation work by assigning each thread a private cache that draws from a set of arenas.  
> This separation eliminates lock contention, improves locality, and lets developers tune both arenas and caches for predictable performance.

jemalloc has become the de‑facto allocator for many high‑performance services because it carefully balances scalability and latency. The secret lies in splitting the heap into **arenas**—coarse‑grained memory pools protected by a small number of mutexes—and **thread caches**, which are per‑thread, lock‑free buffers that satisfy most small allocation requests. Understanding how these two layers interact lets you diagnose fragmentation, tune throughput, and avoid surprising latency spikes.

## jemalloc Architecture at a Glance

Before diving into arenas and thread caches, it helps to see the whole picture.

| Layer                | Responsibility                               | Contention handling |
|----------------------|----------------------------------------------|---------------------|
| **Thread Cache**     | Fast, lock‑free allocation of small objects   | No locks – per‑thread |
| **Arena**            | Bulk memory management, large allocations    | Few mutexes (one per arena) |
| **Extent Hooks**     | Interaction with the OS (mmap/munmap)        | Serialized per extent |
| **Background Thread**| Periodic purging of unused pages              | Runs independently |

When a thread asks for memory, jemalloc first looks in its **thread cache**. If the cache can satisfy the request, the allocation is a simple pointer bump. If not, the request is forwarded to an **arena**. The arena obtains fresh pages from the OS (or from a central *extent* pool) and refills the thread cache. This two‑step path keeps the hot path lock‑free while still allowing global reclamation.

The official design is documented in the [jemalloc wiki](https://github.com/jemalloc/jemalloc/wiki) and the man page [jemalloc(3)](https://manpages.debian.org/unstable/jemalloc/jemalloc.3.en.html).

## Arenas: The Scalable Backbone

### What Is an Arena?

An **arena** is a logical heap that owns a collection of *extents*—contiguous memory regions obtained from the kernel via `mmap`. Each arena has its own set of data structures (bins, runs, and the free list) and a **mutex** protecting them. By default, jemalloc creates a number of arenas equal to `2 * ncpus + 1`, but this can be overridden with the `narenas` option.

```bash
# Show the default number of arenas for the current process
$ numactl --hardware | grep "available:" | wc -l   # just an example
```

The choice of a relatively small arena count (compared to the number of threads) is intentional: it reduces memory overhead while still providing enough parallelism to avoid lock contention on most workloads.

### Bins and Runs

Inside an arena, memory is divided into **bins** based on size classes (e.g., 16 B, 32 B, … up to 64 KB). Each bin manages **runs**, which are pages that hold many objects of the same size. When a thread cache needs to replenish, the arena allocates a run from the appropriate bin and slices it into objects.

```c
/* Simplified pseudo‑code for allocating a run */
run_t *run_alloc(arena_t *arena, size_t size_class) {
    lock(arena->mtx);
    run_t *run = arena->bins[size_class].free_runs;
    if (!run) run = get_new_run_from_extent(arena, size_class);
    unlock(arena->mtx);
    return run;
}
```

Because the arena lock is held only while a run is taken or returned, the critical section is short and rarely a bottleneck.

### Large Allocations

Requests larger than `large_threshold` (by default 64 KB) bypass the bin system entirely. The arena directly maps a new extent sized to the request, avoiding fragmentation in the bin structure. Large allocations are still protected by the arena lock, but they are infrequent enough that the impact is negligible.

## Thread Caches: The Lock‑Free Frontline

### Per‑Thread Cache Layout

Each thread that uses jemalloc owns a **thread cache** (`tcache`). The cache contains a small, fixed‑size buffer for each size class. When a thread frees an object, it usually returns it to its own cache instead of directly to the arena, enabling fast reuse.

```c
/* Pseudo‑code for freeing into the thread cache */
void tcache_free(tcache_t *tc, void *ptr, size_t sz) {
    unsigned idx = size_to_bin_index(sz);
    if (tc->bins[idx].count < TCACHE_MAX_BINS) {
        tc->bins[idx].ptrs[tc->bins[idx].count++] = ptr;
    } else {
        arena_free(tc->arena, ptr, sz);  // cache full, flush to arena
    }
}
```

The constants (`TCACHE_MAX_BINS`) are configurable via `tcache_max` (default 64). When a cache becomes full for a particular size class, excess objects are **evicted** back to the arena, which may later recycle them.

### Allocation Path

1. **Lookup** in the thread cache for the requested size class.  
2. If a cached object exists, pop it and return immediately (no lock).  
3. If the cache is empty, request a **refill** from the arena. The arena provides a run, slices it, and populates the cache. The thread then consumes one object.

```python
# Python‑like illustration of the allocation flow
def allocate(size):
    idx = size_to_bin(size)
    if tcache.bins[idx]:
        return tcache.bins[idx].pop()
    else:
        run = arena.refill(idx)
        tcache.bins[idx].extend(run.objects[1:])  # keep one for the caller
        return run.objects[0]
```

Because the fast path never acquires a lock, the per‑allocation overhead drops to a few nanoseconds on modern CPUs.

### Interaction with NUMA

On NUMA systems, jemalloc can bind arenas to specific nodes (`arena.<id>.nthreads` and `arena.<id>.page` settings). Thread caches automatically draw from the arena that is *closest* in terms of node affinity, improving memory locality.

```bash
# Example: Pin arena 0 to node 0, arena 1 to node 1
export MALLOC_CONF="arena.0.nthreads:4,arena.0.page:0,arena.1.nthreads:4,arena.1.page:1"
```

## The Arena ↔ Thread‑Cache Dialogue

### Refill Mechanics

When a thread cache needs more objects, it sends a **request** to its associated arena. The arena chooses a run that matches the size class, splits it, and transfers a batch (default 64 objects for small sizes) to the cache. This batch size is controlled by `lg_tcache_max` and `lg_tcache_gc_sweep` parameters.

```bash
# Show current tcache parameters
$ jemalloc-config --stats | grep tcache
```

The batch transfer amortizes the cost of acquiring the arena lock across many allocations, preserving the low‑latency promise.

### Eviction and Purging

If a thread frees objects faster than it allocates, its cache may become **oversaturated**. jemalloc then evicts a proportion of cached objects back to the arena. The arena may later **purge** unused pages back to the OS, a process triggered by the background thread or explicit calls like `malloc_trim(0)`.

```c
/* Trigger a purge of completely free runs */
arena_purge(arena);
```

Purging is essential for long‑running services that experience fluctuating memory pressure, preventing the allocator from hoarding memory indefinitely.

### Cross‑Thread Allocation

When a thread allocates memory that was previously freed by another thread, the object will likely be in the **arena’s free list** rather than the target thread’s cache. The allocating thread will fetch it from the arena, incurring a lock acquisition. This scenario is rare in well‑designed workloads where each thread owns its data structures, but it explains occasional latency spikes in contention‑heavy programs.

## Configuration & Tuning for Production

jemalloc is highly tunable via the `MALLOC_CONF` environment variable or the `mallctl` API. Below are common knobs that influence arena‑cache behavior.

| Variable | Default | Typical adjustment | Effect |
|----------|---------|--------------------|--------|
| `narenas` | `2 * ncpus + 1` | `narenas:8` for low‑core containers | Controls total arena count |
| `tcache_max` | `64` | `tcache_max:128` for high allocation rates | Max objects per cache bin |
| `lg_dirty_mult` | `0` | `lg_dirty_mult:2` to keep more dirty pages | Reduces OS calls |
| `background_thread` | `true` | `background_thread:false` on latency‑critical paths | Enables asynchronous purging |
| `retain` | `true` | `retain:false` to release memory on exit | Controls process‑wide retention |

Example: a latency‑sensitive microservice on a 4‑core machine might use:

```bash
export MALLOC_CONF="narenas:4,tcache_max:96,lg_dirty_mult:2,background_thread:true"
```

The `mallctl` interface lets you query and adjust settings at runtime:

```c
size_t narenas;
size_t sz = sizeof(narenas);
mallctl("opt.narenas", &narenas, &sz, NULL, 0);
printf("Current arena count: %zu\n", narenas);
```

### Monitoring Statistics

jemalloc provides rich statistics via `mallctl("stats.print")` or the `jemalloc-config` utility. A typical snapshot looks like:

```text
=== Begin jemalloc statistics ===
thread.allocated: 12345678
thread.deallocated: 12200000
epoch: 1
arenas.narenas: 9
arenas.0.pdirty: 256
arenas.0.purged: 128
tcache.0.nrequests: 987654
tcache.0.nfrees: 985432
=== End jemalloc statistics ===
```

These numbers help you spot whether caches are under‑utilized (`tcache.*.nrequests` much larger than `tcache.*.nfrees`) or if arenas are holding many dirty pages (`pdirty`).

## Debugging Common Issues

### Symptom: Unexpected Latency Spikes

*Root cause*: Cross‑thread allocations forcing arena lock acquisition.  
*Fix*: Increase `narenas` to reduce the chance that two hot threads share the same arena, or pin threads to specific arenas using `arena.<id>.tcache` and `thread.tcache.flush` settings.

### Symptom: Memory Bloat After Heavy Load

*Root cause*: Thread caches retain many objects after the load subsides.  
*Fix*: Call `mallctl("thread.tcache.flush")` at graceful shutdown points, or enable the background thread to periodically purge caches.

```bash
# Flush all thread caches from a shell script
jemalloc-config --mallctl "thread.tcache.flush"
```

### Symptom: High RSS on a NUMA Machine

*Root cause*: Arenas not bound to NUMA nodes, causing remote memory allocation.  
*Fix*: Use `arena.<id>.page` to bind arenas, and set `numa:true` if the kernel supports it.

## Key Takeaways

- **Arenas** are coarse‑grained, mutex‑protected pools that own extents and manage bins; they provide scalability without excessive lock contention.  
- **Thread caches** are per‑thread, lock‑free buffers that satisfy the vast majority of small allocations, keeping the hot path ultra‑fast.  
- The **refill/eviction** handshake between caches and arenas amortizes lock costs and maintains memory locality.  
- jemalloc’s configurability (`MALLOC_CONF`, `mallctl`) lets you match arena counts, cache sizes, and NUMA placement to your workload’s characteristics.  
- Monitoring statistics and flushing caches at appropriate times prevent memory bloat and latency spikes in production services.

## Further Reading

- [jemalloc Official Site](https://jemalloc.net/)
- jemalloc GitHub repository and wiki: <https://github.com/jemalloc/jemalloc/wiki>
- Linux man page for jemalloc: <https://manpages.debian.org/unstable/jemalloc/jemalloc.3.en.html>