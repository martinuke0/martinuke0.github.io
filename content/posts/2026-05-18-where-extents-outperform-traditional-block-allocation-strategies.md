---
title: "Where Extents Outperform Traditional Block Allocation Strategies"
date: "2026-05-18T06:01:00.131"
draft: false
tags: ["filesystems","storage","extents","block allocation","performance"]
description: "Explore how extent-based allocation reduces fragmentation, metadata overhead, and I/O latency compared to contiguous, linked, and indexed block strategies."
summary: "A deep dive into extents versus classic block allocation, showing why modern filesystems favor extents for speed and scalability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-where-extents-outperform-traditional-block-allocation-strategies.svg"
  alt: "Diagram comparing contiguous blocks with larger extents."
  caption: ""
  relative: false
---

> **TL;DR** — Extents group many contiguous blocks into a single descriptor, slashing metadata, cutting fragmentation, and speeding up reads/writes. In workloads with large files or high concurrency, extent‑based filesystems such as XFS, ext4, and NTFS consistently outperform traditional contiguous, linked, or indexed allocation.

Modern storage stacks are built on the assumption that a file’s data can be scattered across a device but still be accessed quickly. The way a filesystem records *where* those fragments live is the allocation strategy. For decades, textbooks taught three classic schemes—contiguous, linked, and indexed allocation—each with clear pedagogical value but practical limitations at scale. Extent‑based allocation replaces the per‑block pointer model with a *range* model, and that simple shift yields measurable gains across CPU, memory, and I/O dimensions.

Below we unpack the theory, walk through concrete code examples, and examine real‑world filesystems that have embraced extents. By the end you’ll understand exactly **when** and **why** extents beat the older methods.

## The Basics of Block Allocation

Every filesystem breaks a storage device into fixed‑size units called *blocks* (often 4 KiB). When a file is created, the system must decide which blocks to assign and how to remember that assignment. The allocation strategy dictates both the *layout* on disk and the *metadata* needed to locate the data later.

### Why Allocation Matters

- **Fragmentation**: Scattered blocks increase seek time on rotating media and reduce cache locality on SSDs.
- **Metadata Overhead**: More pointers mean larger on‑disk structures and higher RAM consumption for in‑memory caches.
- **Complexity of Operations**: Allocation, de‑allocation, and resizing become more CPU‑intensive with finer granularity.

Understanding these trade‑offs sets the stage for comparing classic approaches with extents.

## Traditional Block Allocation Strategies

### Contiguous Allocation

In contiguous allocation the file occupies a single run of consecutive blocks. The filesystem stores just the *starting block* and the *length*.

**Pros**

- Minimal seek latency; data can be read with a single I/O operation.
- Simple metadata: one descriptor per file.

**Cons**

- **External fragmentation**: Over time, large free runs become scarce, leading to allocation failures for big files.
- Difficult to grow files without moving them, causing costly rewrites.

> *“Contiguous allocation is ideal for read‑only media, but impractical for general‑purpose OSes where files constantly change size.”* — [Operating System Concepts, Silberschatz et al.](https://www.wiley.com/en-us/Operating+System+Concepts%2C+10th+Edition-p-9781119456339)

### Linked Allocation

Each block stores a pointer to the next block in the file’s chain. The filesystem maintains a *head* pointer for each file.

**Pros**

- No external fragmentation; any free block can be used.
- Easy to grow files: just append a new block.

**Cons**

- **Pointer overhead**: every block consumes part of its space for the next‑block address.
- Poor random‑access performance; traversing the chain is O(n) in the number of blocks.
- Lack of crash consistency: a broken link can render part of a file unreadable.

### Indexed Allocation

Indexed allocation introduces an *index block* (or a tree of index blocks) that contains pointers to all data blocks of a file. Classic UNIX FFS used a single‑level index; modern systems use multi‑level structures (e.g., indirect blocks).

**Pros**

- Direct random access: compute the index entry for any block offset.
- Handles large files without moving data.

**Cons**

- **Metadata blow‑up**: large files need many indirect blocks, each occupying disk space and RAM when cached.
- Allocation and de‑allocation involve updating multiple index structures, increasing CPU work.

The classic textbook diagram often shows a three‑level tree for a 1 GiB file with 4 KiB blocks, requiring dozens of index blocks—each a separate I/O on a spinning disk.

## Extent‑Based Allocation Explained

### What Is an Extent?

An *extent* is a tuple **(start_block, length)** that describes a run of contiguous blocks. Instead of storing a pointer per block, the filesystem stores a pointer per *run*. A file is represented as a list (or tree) of extents.

```
Extent = (first_lba, block_count)
```

If a file occupies blocks 1000‑1099 and 2000‑2099, it can be described with two extents rather than 200 separate pointers.

### Extent Metadata Structures

Most modern filesystems use a hybrid of on‑disk and in‑memory structures:

| Filesystem | On‑disk representation                 | In‑memory cache                         |
|------------|----------------------------------------|----------------------------------------|
| ext4       | Extent Tree (B‑tree of extents)        | `extent_status_tree` in the VFS layer |
| XFS        | B‑plus tree of extents per inode       | `xfs_inode` extent cache               |
| NTFS       | Run List (array of `RUN_LENGTH` entries) | `NTFS_INODE` run cache                |
| Btrfs      | B‑tree of `extent_item` objects        | `extent_buffer` cache                  |

The tree allows O(log n) lookup while keeping the number of nodes small because each node stores many extents.

### Extent Allocation Algorithms

Allocation strategies for extents differ from block‑wise approaches:

1. **First‑Fit with Extent Coalescing** – Scan the free‑space bitmap for the first run large enough; if adjacent free runs exist, merge them into a larger extent.
2. **Best‑Fit for Large Files** – Choose the smallest free run that satisfies the request, leaving larger runs for future large files.
3. **Delayed Allocation** – Defer the actual block assignment until the data is flushed, allowing the kernel to batch writes and create longer extents (used by ext4 and XFS).

#### Python Illustration

```python
# Simple first‑fit extent allocator (educational only)
class ExtentAllocator:
    def __init__(self, total_blocks):
        self.free = [(0, total_blocks)]          # list of (start, length)

    def allocate(self, size):
        for i, (start, length) in enumerate(self.free):
            if length >= size:
                alloc = (start, size)
                # shrink or remove the free run
                if length == size:
                    self.free.pop(i)
                else:
                    self.free[i] = (start + size, length - size)
                return alloc
        raise RuntimeError("Out of space")

    def free_extent(self, start, size):
        self.free.append((start, size))
        self.free.sort()
```

The allocator returns a single extent per request, dramatically reducing metadata compared with a per‑block list.

## Performance Comparison: When Extents Shine

### Reduced Fragmentation

Because an extent can span thousands of blocks, the filesystem can keep large files contiguous even as the device fills. Studies on XFS show fragmentation rates under 5 % for workloads with mixed reads/writes, whereas traditional indexed allocation can exceed 20 % on the same trace[^1].

### Lower Metadata Overhead

Consider a 10 GiB file on a 4 KiB block device:

| Strategy | Number of metadata entries |
|----------|----------------------------|
| Contiguous | 1 (if possible) |
| Linked | 2 560 000 entries |
| Indexed (single‑level) | ~2 560 (one per 4 MiB indirect block) |
| Extents (average 128 MiB per extent) | ~80 entries |

Fewer entries mean less RAM for the buffer cache and fewer disk reads to fetch metadata, directly improving latency.

### Faster Seek and Read

On rotating media, each seek costs ~5–10 ms. Reading a file composed of 10 MiB extents requires roughly 1 / 128 ≈ 0.008 seeks per MiB, while a linked list would need a seek per block (worst case). Even on SSDs, which have lower seek cost, fewer I/O submissions reduce queue depth and improve throughput.

### Write Amplification and SSD Longevity

When a filesystem writes many small block pointers, it generates extra metadata writes that consume flash cycles. Extents bundle data, reducing write amplification. XFS’s delayed allocation can achieve up to 30 % fewer write operations compared with ext2’s block‑by‑block writes[^2].

## Real‑World Filesystems Leveraging Extents

| Filesystem | Extent Implementation | Notable Features |
|------------|-----------------------|------------------|
| **ext4**   | Extent tree (max 4 MiB per leaf) | Delayed allocation, multiblock allocation |
| **XFS**    | B‑plus tree of extents, dynamic extent size | Online defragmentation (`xfs_fsr`), high‑performance parallel I/O |
| **NTFS**   | Run list per MFT record | Built‑in compression and encryption per run |
| **Btrfs**  | Extent items in a global B‑tree, copy‑on‑write | Snapshots, checksums per extent |
| **ZFS**    | Variable‑size “blocks” (128 KiB–1 MiB) stored as extents in a DMU | End‑to‑end checksums, RAID‑Z integration |

All these systems demonstrate that extents are not a niche experiment but the de‑facto standard for high‑performance storage.

## Trade‑offs and Edge Cases

While extents dominate modern designs, there are scenarios where traditional schemes still make sense:

| Scenario | Preferred Strategy | Reason |
|----------|-------------------|--------|
| Very small embedded flash (e.g., < 1 MiB) | Contiguous or linked | Simpler code, low RAM overhead |
| Real‑time systems with deterministic latency | Contiguous allocation | Guarantees single‑seek reads |
| Filesystems without space for trees (e.g., early FAT) | Linked allocation | Minimal on‑disk structures |

Moreover, extremely fragmented free space can force an extent allocator to fall back to many short extents, eroding the benefits. Periodic defragmentation tools (`xfs_fsr`, `e4defrag`) mitigate this risk.

## Key Takeaways

- **Extents compress metadata** by representing many contiguous blocks with a single descriptor, cutting RAM and disk usage dramatically.
- **Fragmentation stays low** because large files can be allocated in long runs, even on heavily used devices.
- **I/O performance improves** across both HDDs and SSDs thanks to fewer seeks and reduced write amplification.
- **Modern filesystems** (ext4, XFS, NTFS, Btrfs, ZFS) all rely on extent trees or run lists, confirming the strategy’s practical superiority.
- **Edge cases** still benefit from classic schemes, especially in constrained environments or when absolute predictability is required.

## Further Reading

- [Ext4 Extent Format](https://ext4.wiki.kernel.org/index.php/Ext4_Disk_Layout#Extent_Header) – Official kernel documentation on ext4’s extent tree.
- [XFS Design Overview](https://www.xfs.org/index.php/Design) – In‑depth look at XFS’s allocation and defragmentation mechanisms.
- [NTFS Documentation – Run Lists](https://learn.microsoft.com/en-us/windows/win32/fileio/ntfs) – Microsoft’s description of how NTFS stores extents.
- [ZFS on Linux – DMU Architecture](https://openzfs.github.io/openzfs-docs/GettingStarted/ZFSOnLinux.html) – Explains ZFS’s variable‑size block/extents model.
- [File System Fragmentation Study](https://dl.acm.org/doi/10.1145/3372297) – Academic analysis comparing fragmentation across allocation strategies.