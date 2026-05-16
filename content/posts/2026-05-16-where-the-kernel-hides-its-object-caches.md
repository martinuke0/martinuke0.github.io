---
title: "Where the Kernel Hides Its Object Caches"
date: "2026-05-16T23:00:47.971"
draft: false
tags: ["linux", "kernel", "memory-management", "slab", "performance"]
description: "Explore how Linux stores its object caches, the slab/slub mechanisms, where they reside in memory, and how to inspect and tune them for performance."
summary: "A deep dive into Linux kernel object caches, their implementation, location, inspection tools, and tuning tips."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-where-the-kernel-hides-its-object-caches.svg"
  alt: "Illustration of kernel memory zones and object caches."
  caption: ""
  relative: false
---

> **TL;DR** — Linux keeps its frequently allocated objects in per‑CPU slab caches, which are backed by the page allocator and exposed through `/proc/slabinfo` and debugfs. Understanding the slab, slub, and slob allocators lets you locate, monitor, and tune these caches for lower latency and better memory utilization.

The kernel’s object caches are the invisible workhorses that make everyday operations—from file descriptors to network sockets—fast and deterministic. While the high‑level idea of a “cache” is familiar, the Linux kernel hides the concrete data structures deep inside its memory‑management subsystem. In this article we will unpack the slab family of allocators, explain where the caches live in physical memory, show you how to inspect them with the tools the kernel already ships, and provide practical tuning advice for production workloads.

## The Purpose of Object Caches

Every time the kernel needs a small data structure (e.g., a `task_struct`, an inode, a `socket`), it could request a fresh page from the buddy allocator, carve out the needed bytes, and then free the remainder. That would be wasteful for two reasons:

1. **Fragmentation** – Repeatedly allocating and freeing objects of similar size creates internal fragmentation within pages, reducing overall memory efficiency.
2. **Latency** – The buddy system works on a page granularity; pulling a page from the free‑list can take dozens of microseconds, which is far too slow for high‑frequency kernel paths.

Object caches solve both problems by pre‑allocating **slabs**—contiguous groups of pages—filled with objects of a single size class. When a kernel component asks for an object, the allocator hands out a pre‑initialized slot from the appropriate cache; when the object is released, it is returned to the same cache, ready for reuse. This reduces allocation overhead to a simple pointer manipulation and keeps memory fragmentation under control.

## SLAB vs. SLUB vs. SLOB: A Quick Comparison

Historically the kernel shipped three allocators that implement the same high‑level API:

| Feature | SLAB | SLUB | SLOB |
|---------|------|------|------|
| **Design** | Explicit slab management with per‑CPU caches, kmem\_cache\_node structures | Simplified slab management, no per‑CPU freelists, uses a single `kmem_cache` per size | Tiny allocator for embedded systems, linear search in a single page |
| **Performance** | Good for large, heavily used caches; higher memory overhead | Generally faster for most workloads, lower overhead | Minimal code size, not suitable for high‑throughput servers |
| **Memory Overhead** | Higher (metadata per slab) | Lower (metadata stored in slab itself) | Minimal |
| **Configuration** | `CONFIG_SLUB=y` disables it; `CONFIG_SLUB=y` is default since 2.6.23 | Default in mainstream kernels | Only enabled on very constrained platforms |

Since kernel 2.6.23, **SLUB** has been the default allocator because it offers a simpler implementation and comparable performance. Nevertheless, the underlying concepts—slabs, caches, per‑CPU pages—are identical across the three, so the “where” part of our investigation applies to all of them.

## Where the Caches Live in Memory

### 1. The Buddy Allocator’s Role

All slabs ultimately come from the **buddy allocator**, the low‑level page allocator that manages physical memory in power‑of‑two sized blocks. When a cache needs more storage, SLUB calls `alloc_pages_node()` to obtain one or more contiguous pages. Those pages become a **slab** and are linked into the cache’s internal list.

Because the buddy allocator works on a per‑node basis (NUMA node), each cache maintains a **kmem\_cache\_node** structure that tracks how many slabs reside on each node. This is why you often see output such as:

```text
kmem_cache_node: 0 objects, 0 active slabs, 0 total slabs, 0 pages per slab
```

The actual objects are stored inside the pages themselves, starting after the slab’s metadata header (in SLUB the header is embedded at the beginning of the first object).

### 2. Per‑CPU Caches

To avoid lock contention, SLUB creates a **per‑CPU partial list** for each cache. When a CPU needs an object, it first checks its own partial list; if empty, it grabs a slab from the global list, splits it into objects, and populates its per‑CPU cache. When objects are freed, they are returned to the same CPU’s partial list, not to the global pool.

These per‑CPU structures live in **kernel memory that is mapped into each CPU’s local data area** (`percpu`). You can see their size with:

```bash
grep ^cpu /proc/meminfo
```

The per‑CPU caches are therefore scattered across the physical memory that backs each node, but they are logically tied to the CPU that owns them. This design explains why cache‑miss patterns can be NUMA‑aware: an allocation on CPU 0 will preferentially reuse pages that are already local to node 0.

### 3. The `slabinfo` Interface

The kernel exports a snapshot of all active caches via `/proc/slabinfo`. Each line contains:

```
name <active_objs> <num_objs> <objsize> <objs_per_slab> <pages_per_slab> <flags> <active_slabs> <num_slabs>
```

For example:

```text
kmalloc-64  1024 2048 64 8 1 0x0 128 256
```

This tells us that the `kmalloc-64` cache currently has 1024 active objects out of a total capacity of 2048, each object is 64 bytes, each slab holds 8 objects, and each slab occupies a single page. By parsing this file you can infer **where** the objects reside (how many pages, how many slabs) and **how full** each cache is.

### 4. Debugfs: `kmem/slab` and `kmem/slub`

When the kernel is compiled with `CONFIG_DEBUG_KMEMLEAK=y` and `CONFIG_DEBUG_SLUB=y`, a rich debugfs hierarchy appears under `/sys/kernel/debug/kmem/`. For SLUB you’ll find:

```
/sys/kernel/debug/kmem/slub
├── cache
│   ├── kmalloc-64
│   │   ├── active_objs
│   │   ├── num_objs
│   │   ├── objs_per_slab
│   │   └── pages_per_slab
│   └── ...
└── stats
    ├── total_objects
    └── total_slabs
```

Reading these files gives you the same data as `/proc/slabinfo` but in a more structured way, and you can also write to certain entries to trigger cache flushing or reclamation.

## Inspecting Caches with `/proc` and Debugfs

Below is a step‑by‑step guide to locate a cache, understand its memory footprint, and diagnose a potential issue.

### Step 1: Identify the Cache of Interest

Suppose you suspect the `sock` cache (used for `struct socket`) is growing unexpectedly. First, search for it:

```bash
grep ^sock /proc/slabinfo
```

Typical output:

```text
sock  5120 8192 128 8 1 0x0 640 1024
```

Interpretation:

- **Active objects**: 5120 (currently in use)
- **Total objects**: 8192 (capacity)
- **Object size**: 128 bytes
- **Objects per slab**: 8
- **Pages per slab**: 1 (each slab = 1 page)

### Step 2: Find the Physical Pages

The kernel does not expose the exact physical addresses of each slab directly, but you can approximate the total memory used:

```
memory_used = pages_per_slab * num_slabs * PAGE_SIZE
```

For `sock`:

```bash
pages_per_slab=$(awk '/^sock / {print $6}' /proc/slabinfo)
num_slabs=$(awk '/^sock / {print $9}' /proc/slabinfo)
echo $((pages_per_slab * num_slabs * 4096))   # assuming 4 KiB pages
```

If the result is, say, 4 MiB, you now know that the `sock` cache consumes roughly that amount of RAM.

### Step 3: Drill Down with Debugfs

Enable debugfs if not already mounted:

```bash
mount -t debugfs none /sys/kernel/debug
```

Read per‑CPU stats:

```bash
cat /sys/kernel/debug/kmem/slub/cache/sock/active_objs
cat /sys/kernel/debug/kmem/slub/cache/sock/num_objs
```

You can also trigger a **reclaim** of unused slabs:

```bash
echo 1 > /sys/kernel/debug/kmem/slub/cache/sock/reclaim
```

Afterwards, re‑run the `grep` command to see if the numbers dropped.

### Step 4: Correlate with System Metrics

Combine the cache data with system‑wide memory stats:

```bash
free -h
cat /proc/meminfo | grep -E 'Slab|SReclaimable|SUnreclaim'
```

The `Slab` line in `/proc/meminfo` aggregates *all* caches, so a sudden jump usually points to one or more hot caches you can pinpoint with the steps above.

## Tuning Cache Behaviour

While the kernel automatically adjusts slab sizes, many knobs exist for administrators who need tighter control.

| Parameter | Path | Effect |
|-----------|------|--------|
| `slub_debug` | `/sys/module/slub/parameters/debug` | Enables sanity checks (e.g., red‑zone, poisoning). Helpful for debugging but adds overhead. |
| `slub_min_objects` | `/sys/module/slub/parameters/min_objects_per_slub` | Minimum objects per slab; raising it reduces slab fragmentation at the cost of larger pages per cache. |
| `kmem_cache_alloc` flags | API level | Callers can request `SLAB_RECLAIM_ACCOUNT` or `SLAB_NOLEAKTRACE` to influence reclamation. |
| `vm.min_free_kbytes` | `/proc/sys/vm/min_free_kbytes` | Guarantees a reserve of free memory; indirectly limits how aggressively caches can grow. |

### Example: Reducing Slab Bloat in a High‑Connection Server

A web server handling tens of thousands of concurrent connections may see the `tcp_sock` cache swell. You can limit its growth by adjusting the per‑CPU partial list size:

```bash
echo 64 > /sys/module/slub/parameters/numa_zone
```

(Replace `numa_zone` with the appropriate sysfs knob for your kernel version; the exact name varies.)

Alternatively, you can **shrink** the cache at runtime:

```bash
echo 1 > /sys/kernel/debug/kmem/slub/cache/tcp_sock/shrink
```

The shrink operation forces the allocator to walk through empty slabs and release them back to the buddy system, freeing physical pages.

## Common Pitfalls and How to Avoid Them

1. **Assuming `/proc/slabinfo` is up‑to‑date** – The file is a snapshot taken at read time. Rapid allocation bursts can make the numbers stale within milliseconds. Use `watch -n 1 cat /proc/slabinfo` for a live view, but remember that the act of reading can slightly perturb the statistics.

2. **Over‑tuning per‑CPU caches** – Setting `percpu` cache limits too low forces frequent global slab grabs, increasing lock contention. The default values are tuned for typical workloads; only modify them after benchmarking.

3. **Neglecting NUMA effects** – On multi‑node systems, allocating memory on the wrong node can inflate latency. Use `numactl --membind=0` for processes that should stay local, and verify cache distribution with `numastat`.

4. **Disabling SLUB debugging in production** – While turning off `slub_debug` improves performance, it also removes valuable safety nets. Keep it enabled in staging environments where you can catch use‑after‑free bugs early.

5. **Forgetting to free caches created with `kmem_cache_create`** – Kernel modules that allocate their own caches must destroy them on unload (`kmem_cache_destroy`). Leaked caches remain forever in `slabinfo`, consuming memory and polluting metrics.

## Key Takeaways

- Linux object caches are built on top of the buddy allocator; each cache consists of slabs (contiguous pages) that store objects of a single size.
- Per‑CPU partial lists minimize lock contention, but they scatter cache pages across NUMA nodes, making locality an important performance factor.
- `/proc/slabinfo` and debugfs under `/sys/kernel/debug/kmem/` provide the primary visibility into cache occupancy, slab counts, and per‑CPU statistics.
- Tuning knobs such as `slub_debug`, `slub_min_objects`, and `vm.min_free_kbytes` let you balance memory overhead against allocation latency.
- Always correlate cache data with system‑wide memory metrics and be cautious when modifying defaults; premature tuning can degrade performance more than it helps.

## Further Reading

- [Linux Kernel Documentation – Memory Management](https://www.kernel.org/doc/html/latest/vm/index.html)  
- [LWN.net article “The SLUB Allocator”](https://lwn.net/Articles/593896/)  
- [Wikipedia: Slab allocation](https://en.wikipedia.org/wiki/Slab_allocation)  
- [Kernel.org – kmem_cache API](https://www.kernel.org/doc/html/latest/core-api/kmem_cache.html)  
- [Red Hat Developer Blog – Understanding kernel slab caches](https://developers.redhat.com/articles/2020/04/14/understanding-linux-kernel-slab-caches)