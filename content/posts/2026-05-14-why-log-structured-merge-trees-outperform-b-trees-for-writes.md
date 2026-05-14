---
title: "Why Log Structured Merge Trees Outperform B Trees for Writes"
date: "2026-05-14T21:00:10.568"
draft: false
tags: ["databases", "LSM", "B-Tree", "write performance", "storage engines"]
description: "Log Structured Merge (LSM) trees provide superior write throughput compared to B‑trees by batching, sequential I/O, and compaction, making them ideal for modern write‑heavy workloads."
summary: "An in‑depth look at why LSM trees beat B‑trees on writes, covering architecture, trade‑offs, and practical implications."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-log-structured-merge-trees-outperform-b-trees-for-writes.svg"
  alt: "Diagram comparing LSM and B‑Tree write paths."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees achieve higher write throughput than B‑trees by turning many random writes into sequential appends, buffering in memory, and using background compaction. The trade‑off is higher read amplification and more storage overhead, so choose based on workload characteristics.

Modern data platforms—from time‑series databases to key‑value stores—must ingest millions of records per second while keeping latency low. Two data structures dominate the storage engine landscape: the classic B‑Tree and the newer Log Structured Merge (LSM) tree. Although B‑trees excel at point reads, LSM trees consistently outperform them on write‑heavy workloads. This article unpacks why, diving into the internals of each structure, the physics of storage media, and the practical implications for system designers.

## The Fundamentals of B‑Trees

### Structure and Write Path

A B‑Tree is a balanced multi‑way search tree where each node stores a sorted array of keys and child pointers. The tree height is kept low (typically 3–5 levels for terabyte‑scale datasets) by using a high branching factor, which reduces the number of I/O hops for reads.

When a write arrives:

1. **Search** – Locate the leaf node that should contain the key (O(log N) I/O).
2. **Modify** – Insert or update the key in the leaf’s in‑memory copy.
3. **Flush** – If the leaf is full, split it and propagate the split up the tree, potentially rewriting several parent nodes.
4. **Write‑Ahead Log (WAL)** – The change is first recorded in a sequential log for durability.

Because each write may touch multiple nodes, B‑Tree writes involve *random* I/O on both the leaf and internal levels. On SSDs, random writes are still more expensive than sequential appends due to write amplification and internal page management.

### Strengths and Limitations

* **Strong point queries** – B‑Trees provide O(log N) lookup with minimal read amplification.
* **Range scans** – Nodes are stored contiguously on disk, enabling efficient range queries.
* **Predictable latency** – Each operation touches a bounded number of pages.

However, the write path suffers from:

* **Write amplification** – Splits cause multiple pages to be rewritten.
* **Garbage collection overhead** – SSDs must erase and rewrite blocks, increasing wear.
* **Limited write batching** – Each transaction forces an immediate WAL sync, limiting throughput.

## How Log Structured Merge Trees Work

### MemTable and Immutable Segments

An LSM tree separates writes from the on‑disk structure:

1. **MemTable (in‑memory)** – Incoming writes are appended to an in‑memory sorted data structure (often a skip list). This operation is *purely sequential* in memory, O(1) latency.
2. **Immutable Flush** – When the MemTable reaches a size threshold (e.g., 64 MiB), it is frozen and written as an immutable sorted file called an **SSTable** (Sorted String Table) on disk.
3. **WAL** – A small sequential log ensures durability of the MemTable before the flush.

Because the flush writes a *single* contiguous file, the I/O pattern is completely sequential, matching the strengths of modern SSDs and NVMe drives.

### Levels, Compaction, and Write Amplification

SSTables are organized into *levels* (L0, L1, …). New files land in L0 and are later merged into higher levels through **compaction**:

* **Size‑tiered compaction** – Merges a handful of similarly sized files.
* **Leveled compaction** – Maintains a strict size ratio between levels (e.g., each level ten times larger than the previous) and merges overlapping key ranges.

Compaction is a background process that rewrites data to eliminate duplicate keys and reclaim deleted entries. While compaction introduces *write amplification*—each record may be rewritten multiple times—the cost is amortized and performed asynchronously, keeping the *foreground* write latency low.

## Why LSM Trees Shine for Writes

### Batched Sequential Writes

The core advantage is that the write path reduces *random* I/O to *sequential* I/O:

```bash
# Example: flushing a MemTable to an SSTable with RocksDB
rocksdb-cli --db=/data/mydb --flush
```

Sequential writes exploit the high throughput of SSD/NVMe controllers, achieving near‑line‑rate performance. In contrast, a B‑Tree must seek for each leaf split, incurring latency penalties.

### Write Amplification Trade‑offs

While LSM trees do rewrite data during compaction, the **effective write amplification** can be lower than a B‑Tree for write‑heavy workloads because:

* **Batching** – Hundreds of thousands of updates are merged into a single large write, reducing per‑record overhead.
* **Background processing** – Compaction runs on idle I/O bandwidth, smoothing out spikes.

Empirical studies (e.g., the RocksDB performance guide) show LSM write amplification values of 2–5×, whereas B‑Tree engines like InnoDB can reach 10–20× under the same write intensity.

### Impact of Modern Storage Media

NVMe SSDs have *high sequential bandwidth* (>3 GB/s) but still incur a penalty for random writes due to the Flash Translation Layer (FTL). LSM trees align perfectly with this asymmetry:

* **Sequential appends** → low latency, low wear.
* **Random reads** → mitigated by Bloom filters and block caches that locate the correct SSTable without scanning all levels.

As storage hardware continues to favor sequential throughput, the performance gap widens.

## Trade‑offs and When B‑Trees Still Matter

### Read Latency

LSM reads may need to probe multiple levels (L0‑Ln) before finding the latest version of a key. Bloom filters reduce unnecessary disk accesses, but the worst‑case read path can involve **N** disk reads, where **N** is the number of levels. B‑Trees typically require a single leaf fetch, giving them an edge for latency‑sensitive point reads.

### Space Overhead

Compaction creates temporary duplicate data, temporarily inflating disk usage. Additionally, each SSTable carries metadata (index blocks, filter blocks). B‑Trees store a single copy of each key/value pair, yielding better space efficiency for static datasets.

### Use‑Case Decision Matrix

| Workload                     | Preferred Structure | Reasoning                                      |
|------------------------------|---------------------|-------------------------------------------------|
| High write throughput (≥ 1 M ops/s) | LSM                 | Batched sequential writes, low foreground latency |
| Point‑lookup heavy (≤ 10 µs) | B‑Tree              | Single‑page reads, minimal read amplification   |
| Mixed read/write with moderate write rate | LSM (leveled)      | Balanced compaction, good read latency with Bloom filters |
| Log‑structured or time‑series data | LSM (size‑tiered)   | Append‑only pattern matches LSM flush model      |
| Small embedded devices (limited RAM) | B‑Tree              | Simpler implementation, fewer background tasks  |

## Key Takeaways

- **Sequential writes**: LSM trees convert many random writes into large sequential appends, leveraging SSD/NVMe performance.
- **Memory buffering**: The MemTable absorbs writes in RAM, eliminating per‑record disk latency.
- **Background compaction**: Write amplification is amortized and does not affect foreground latency, unlike B‑Tree split‑and‑rewrite.
- **Read trade‑offs**: LSM reads can be slower due to multi‑level lookups; Bloom filters and caching mitigate but do not eliminate this cost.
- **Hardware alignment**: Modern storage devices favor the write patterns of LSM trees, making them the default for write‑intensive databases such as RocksDB, LevelDB, Cassandra, and InfluxDB.

## Further Reading

- [RocksDB Architecture Overview](https://github.com/facebook/rocksdb/wiki/Architecture)  
- [LevelDB: A Fast Persistent Key‑Value Store](https://github.com/google/leveldb)  
- [The Log‑Structured Merge‑Tree (LSM‑Tree)](https://www.cs.umb.edu/~poneil/lsmtree.pdf)  
- [InnoDB B‑Tree Internals](https://dev.mysql.com/doc/refman/8.0/en/innodb-storage-engine.html)  
- [Understanding Write Amplification in SSDs](https://www.tldp.org/HOWTO/SSD-Write-Amplification.html)