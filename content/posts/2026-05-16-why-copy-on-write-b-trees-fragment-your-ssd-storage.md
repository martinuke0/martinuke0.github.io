---
title: "Why Copy-on-Write B-Trees Fragment Your SSD Storage"
date: "2026-05-16T09:01:05.088"
draft: false
tags: ["databases", "b-trees", "copy-on-write", "ssd", "storage"]
description: "Copy-on-Write B‑Trees boost concurrency but can cause SSD fragmentation, leading to slower writes and reduced lifespan; learn why and how to mitigate."
summary: "Copy‑on‑Write B‑Trees improve database performance but introduce write‑amplification that fragments SSDs; this post explains the mechanics and mitigation strategies."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-why-copy-on-write-b-trees-fragment-your-ssd-storage.svg"
  alt: "Illustration of a B‑Tree node being duplicated on an SSD."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑Write (CoW) B‑Trees write new versions of pages instead of overwriting, which creates many small, scattered writes on SSDs. Over time those writes fragment the flash, increase garbage‑collection overhead, and degrade both performance and drive endurance.

Modern key‑value stores and relational engines often tout **Copy‑on‑Write B‑Trees** as the secret sauce behind low‑latency reads and lock‑free writes. The trade‑off, however, is hidden deep inside the storage layer: every logical update becomes a physical write to a new location, and SSDs are notoriously sensitive to that pattern. In this article we unpack the data‑structure internals, the physics of NAND flash, and the cascade of effects that turn a perfectly balanced tree into a fragmented storage device. Finally we explore concrete mitigation techniques that let you keep the concurrency benefits without sacrificing SSD health.

## How Copy-on-Write B-Trees Work

### Basic B‑Tree Structure

A classic B‑Tree stores sorted keys in a hierarchy of nodes, each node holding multiple key/value pairs and pointers to child nodes. The node size (often 4 KB or 8 KB) is chosen to match the underlying storage block size, minimizing the number of I/O operations required for a search. Because nodes are immutable in a CoW variant, **any modification creates a fresh copy of the affected node** while the rest of the tree remains untouched.

> “Copy‑on‑Write B‑Trees maintain logical consistency by never overwriting existing pages; they instead allocate new pages for each mutation.” — as described in the [SQLite documentation](https://www.sqlite.org/wal.html).

### Copy-on-Write Mechanics

When a transaction updates a key, the engine performs the following steps:

1. **Locate the leaf node** containing the key (read‑only).
2. **Create a new leaf page** with the updated key/value pair.
3. **Propagate the change upward**: each parent node that references the modified child is also copied with the new child pointer.
4. **Write the new pages** to storage and finally update the root pointer atomically.

Because each write generates a brand‑new page, the tree grows in physical size even though its logical size may stay constant. A simplified Python illustration shows the core idea:

```python
def cow_update(tree, key, value):
    # Locate leaf (read‑only)
    leaf = tree.find_leaf(key)
    # Create a new leaf with the modification
    new_leaf = leaf.clone()
    new_leaf.update(key, value)
    # Walk back up, cloning each parent
    parent = leaf.parent
    while parent:
        new_parent = parent.clone()
        new_parent.replace_child(leaf, new_leaf)
        leaf, new_parent = new_parent, parent
        parent = parent.parent
    # Commit new root
    tree.root = new_parent
```

The algorithm guarantees **atomicity without locks**: readers continue to see the old pages while the writer builds a new version in the background.

## Why SSDs Care About Write Patterns

### NAND Flash Organization

An SSD is a collection of NAND flash chips, each divided into **blocks** (typically 256 KB–4 MB) composed of many **pages** (4 KB–16 KB). Pages are the smallest unit that can be written, but they can only be **erased** at the block level. When a page is rewritten, the controller must write the new data to a fresh page and later reclaim the old page during **garbage collection**.

### Garbage Collection and Wear Leveling

Because each block has a finite number of erase cycles (≈ 3,000–10,000), the SSD controller spreads writes evenly (wear leveling) and consolidates valid pages into new blocks when old ones become partially filled. This process, known as **write amplification**, multiplies the amount of data physically written compared to the logical data issued by the host.

A CoW B‑Tree amplifies this effect dramatically: each logical update may generate 3–4 new pages (leaf + parents) scattered across the drive. The controller cannot simply overwrite the old pages; it must allocate fresh locations, leading to a high proportion of **invalid (stale) pages** that later trigger garbage collection.

## The Fragmentation Process

### Page Allocation and Tree Updates

Consider a workload that performs many small updates to random keys. Each update:

- Allocates a new leaf page (≈ 4 KB).
- Allocates a new parent page for each level (often 2–3 levels deep).
- Writes these pages to whatever free space the SSD’s write pointer currently points to.

Since the SSD’s internal write pointer moves linearly across the flash, the new pages become **interleaved with older, still‑valid pages**. Over time the logical order of the B‑Tree (which is highly localized) diverges from the physical order on the NAND cells.

### Write Amplification and Space Fragmentation

The SSD’s garbage collector must now:

1. Scan blocks to find pages that are still valid.
2. Copy those pages to a new block.
3. Erase the old block.

If a block contains a mix of a few fresh CoW pages and many stale pages from previous updates, the **copy‑move cost** for that block is high relative to the amount of new data it holds. This inefficiency is quantified as **write amplification factor (WAF)**, often rising from the typical 1.2–1.5 for sequential workloads to 2.0–3.5 for aggressive CoW patterns.

The net result is **SSD fragmentation**: free space becomes scattered in small pockets, the controller's write pointer must frequently jump to locate these pockets, and overall throughput drops because each write now triggers additional internal moves.

## Real‑World Impact

### Benchmarks and Latency Spikes

Empirical studies on databases like **MongoDB** (which uses a B‑Tree variant) and **PostgreSQL** with the **ZHeap** extension show latency spikes after a few hundred thousand random updates. The spikes correlate with increased garbage‑collection cycles reported by the SSD’s SMART statistics.

> “Under a write‑heavy, random‑key workload, the average write latency grew from 0.2 ms to 1.5 ms after 500 k updates, primarily due to SSD internal compaction.” — data from the [Samsung SSD whitepaper](https://www.samsung.com/semiconductor/minisite/ssd).

### Device Lifespan Considerations

Because each erase cycle consumes part of the NAND’s endurance budget, the extra write amplification from CoW B‑Trees can **shorten the drive’s rated TBW (Terabytes Written)** by 30 %–50 % in worst‑case scenarios. For consumer‑grade SSDs rated at 150 TBW, a high‑throughput logging service could exhaust the warranty in just a few years.

## Mitigation Strategies

### Log‑Structured Merge Trees (LSM)

LSM trees batch writes into large, sequential segments, dramatically reducing random page writes. While they sacrifice some read latency, the **write amplification drops** because most updates are absorbed into in‑memory memtables before being flushed as contiguous runs.

```bash
# Example: RocksDB compaction command
rocksdb-cli --db=/data/db --compact
```

### B‑Tree Tuning (Node Size, Clustering)

Increasing the node size (e.g., from 4 KB to 16 KB) reduces the number of pages touched per update, thereby lowering the total number of writes. Additionally, **clustered indexes** that keep related keys physically adjacent can improve locality, making the SSD’s internal garbage collector more efficient.

### SSD‑Aware Filesystem Settings

Filesystems like **F2FS** and **XFS** expose mount options to control **allocation unit size** and **writeback thresholds**. Enabling `discard=async` and `noatime` reduces unnecessary metadata writes, while `logbufs=8` can coalesce small writes into larger batches.

```yaml
# /etc/fstab entry for an SSD‑optimized mount
/dev/nvme0n1p1 /mnt/data xfs noatime,discard=async,logbufs=8 0 2
```

### Periodic Compaction

Some databases expose a **vacuum** or **compact** operation that rewrites the entire B‑Tree in a sequential pass, reclaiming fragmented space. Scheduling this during low‑traffic windows can keep the SSD’s free space contiguous.

```sql
-- PostgreSQL VACUUM FULL on a table using a CoW index
VACUUM FULL my_table;
```

### Hybrid Approaches

Combining a CoW B‑Tree for hot data with an LSM for cold data can strike a balance: recent writes enjoy low‑latency updates, while older rows are migrated to a write‑friendly structure. Frameworks like **Apache Arrow** and **Delta Lake** implement such tiered storage models.

## Key Takeaways

- **Copy‑on‑Write B‑Trees never overwrite pages**, causing many small, random writes that fragment SSDs.
- **NAND flash’s block‑erase constraint** forces the SSD controller to perform garbage collection, which amplifies writes and reduces performance.
- **Write amplification** from CoW can increase the SSD’s WAF to 2–3×, shortening its endurance and raising latency.
- **Mitigation options** include larger node sizes, SSD‑aware filesystem tuning, periodic compaction, or switching to LSM‑based storage for write‑heavy workloads.
- **Hybrid designs** let you keep the concurrency benefits of CoW for hot data while offloading cold data to a more SSD‑friendly structure.

## Further Reading

- [Copy‑on‑Write overview (Wikipedia)](https://en.wikipedia.org/wiki/Copy-on-write)  
- [B‑Tree fundamentals (Wikipedia)](https://en.wikipedia.org/wiki/B-tree)  
- [SSD architecture and wear leveling (Intel)](https://www.intel.com/content/www/us/en/architecture-and-technology/ssd.html)  
- [RocksDB documentation – Compaction](https://rocksdb.org/blog/2020-09-16-compaction.html)  
- [PostgreSQL VACUUM documentation](https://www.postgresql.org/docs/current/sql-vacuum.html)