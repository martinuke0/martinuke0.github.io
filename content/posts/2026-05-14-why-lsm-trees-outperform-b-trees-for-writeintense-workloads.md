---
title: "Why LSM Trees Outperform B-Trees for Write‑Intense Workloads"
date: "2026-05-14T08:00:30.683"
draft: false
tags: ["LSM", "B-Tree", "databases", "write performance", "storage engines"]
description: "Learn how Log‑Structured Merge (LSM) trees achieve superior write throughput compared to B‑trees, the trade‑offs involved, and when to pick each for modern storage workloads."
summary: "An in‑depth comparison of LSM trees and B‑trees that explains why LSM excels on write‑heavy workloads, backed by real‑world examples and practical takeaways."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-lsm-trees-outperform-b-trees-for-writeintense-workloads.svg"
  alt: "Diagram comparing LSM and B‑Tree write paths"
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees batch writes into sequential files, turning random‑write hotspots into cheap sequential I/O. This design yields dramatically higher write throughput than B‑trees, especially on SSDs and spinning disks, at the cost of more complex reads and background compaction.

Modern storage engines constantly juggle two conflicting goals: *fast writes* and *efficient reads*. For many applications—log aggregation, time‑series data, and high‑frequency trading—writes dominate the workload. In those scenarios, Log‑Structured Merge (LSM) trees consistently beat the classic B‑tree. This article unpacks why, diving into the data structures, the I/O patterns they generate, and the engineering trade‑offs that shape real‑world systems.

## Understanding B‑Trees

### The Classic Design

A B‑tree is a balanced multi‑way search tree where each node holds a sorted array of keys and child pointers. The tree maintains a height of *O(logₙ N)* (where *n* is the branching factor) so lookups, inserts, and deletes all cost *O(logₙ N)* disk I/O in the worst case.

When a new key arrives, the algorithm walks down the tree, finds the leaf node, inserts the key in sorted order, and may split the node if it overflows. Splits propagate upward, occasionally causing a cascade of page splits up to the root.

### Write Amplification in B‑Trees

Because B‑trees modify data *in place*, each insert can trigger multiple random writes:

1. **Leaf write** – the leaf page must be read, modified, and written back.
2. **Node splits** – a split creates a new page, writes the new page, updates the parent, and possibly rewrites the parent page.
3. **Propagation** – if the parent overflows, the process repeats up the tree.

On spinning disks, random writes are expensive due to seek time. Even on SSDs, each write incurs *write amplification*: the SSD’s internal wear‑leveling writes more data than the host asked for. Consequently, a B‑tree’s write path can be a performance bottleneck under heavy insert loads.

## The Log‑Structured Merge Tree Architecture

### Core Idea

An LSM tree replaces in‑place updates with *append‑only* writes. New records are first placed in an in‑memory structure (often a sorted string table, or **memtable**, implemented as a skip list or red‑black tree). When the memtable fills, it is frozen and flushed to disk as a **sorted string table (SSTable)**—a contiguous, immutable file.

Subsequent writes keep appending to the current memtable. Over time, the disk accumulates multiple SSTable generations (Level‑0, Level‑1, …). A background *compaction* process merges overlapping SSTables into larger, sorted files, discarding obsolete versions of keys.

### Write Path in Detail

```python
def lsm_insert(key, value):
    # 1️⃣ Write to WAL for durability
    wal.append(f"{key}:{value}\n")
    # 2️⃣ Insert into in‑memory memtable (sorted structure)
    memtable[key] = value
    # 3️⃣ If memtable exceeds size threshold, flush to disk
    if memtable.size() > MEMTABLE_LIMIT:
        sstable = memtable.freeze()
        disk.write(sstable)          # sequential write
        memtable.clear()
```

Key points:

* **Sequential Disk I/O** – Flushing creates a single, large, sequential write, which SSDs and HDDs handle efficiently.
* **Write Batching** – Thousands of inserts are coalesced into one flush, reducing per‑record overhead.
* **Log‑Structured** – No in‑place overwrites; old data becomes obsolete and is reclaimed later by compaction.

## Why Writes Are Faster in LSM Trees

### 1. Sequential I/O vs. Random I/O

The primary performance win comes from turning many tiny random writes into a few large sequential writes. Modern storage devices have dramatically higher throughput for sequential streams (often 5‑10× on SSDs, 10‑20× on HDDs). By writing SSTables in one pass, LSM trees exploit this hardware characteristic.

### 2. Write Amplification Reduction

While compaction does add background writes, the *average* write amplification can still be lower than a B‑tree’s per‑insert cost, especially when the write workload is bursty. Techniques such as *tiered* or *leveled* compaction (used by RocksDB and LevelDB) let engineers tune the trade‑off between write amplification and read latency.

### 3. Write‑Ahead Log (WAL) Guarantees Durability

The WAL is a small, append‑only file that protects against crashes. Because it is written sequentially, its overhead is minimal. In a B‑tree, durability often requires a separate journal plus the in‑place page writes, doubling the random I/O.

### 4. Memory‑Centric Front‑End

Most inserts never touch the disk until the memtable flush. If the workload fits within the allocated memory, the effective write latency drops to pure RAM speed, which can be orders of magnitude faster than any storage device.

### 5. Parallelizable Compaction

Compaction runs in the background and can be parallelized across CPU cores and disks. This means the foreground write path stays lightweight, whereas B‑tree writes must wait for page splits that are inherently serialized.

## Trade‑offs and When to Choose Each

| Aspect               | B‑Tree                                         | LSM Tree                                          |
|----------------------|-----------------------------------------------|---------------------------------------------------|
| **Write Latency**    | Higher due to random page writes and splits   | Low foreground latency; background compaction adds eventual cost |
| **Read Latency**     | Predictable single‑level lookup (often 1‑2 I/O) | May need to search multiple SSTables; bloom filters mitigate |
| **Space Overhead**   | Moderate (metadata + leaf pages)              | Higher due to duplicated keys in older SSTables and compaction waste |
| **Complexity**       | Simpler implementation, mature codebases     | More moving parts (WAL, memtable, compaction scheduler) |
| **Best Fit**         | OLTP workloads with balanced reads/writes, small to medium data size | Write‑heavy workloads, time‑series, log aggregation, large data sets |

### Real‑World Examples

* **RocksDB** – A high‑performance LSM‑based key‑value store used by Facebook for its messaging platform. RocksDB’s *leveled compaction* keeps write amplification around 10×, far better than a comparable B‑tree under the same load.
* **MySQL InnoDB** – Still relies on a B‑tree for its clustered index. It excels at mixed read/write OLTP but can saturate I/O under pure insert streams.
* **Apache Cassandra** – Built on an LSM design; its ability to ingest millions of rows per second on commodity hardware is a testament to the model’s scalability.

## Key Takeaways

- **Sequential flushing** turns many random writes into a few fast sequential writes, which is the core reason LSM trees outshine B‑trees on write‑intense workloads.
- **Background compaction** decouples write latency from storage reclamation, allowing the foreground path to stay lightweight.
- **Write‑ahead logging** provides durability with minimal overhead, whereas B‑trees must juggle both a journal and in‑place page updates.
- **Read performance** can suffer due to multiple SSTable lookups, but bloom filters, caching, and tiered compaction mitigate the impact.
- **Choosing a data structure** depends on workload profile: pick LSM for write‑heavy, append‑only, or time‑series data; pick B‑tree for balanced read/write or latency‑critical point queries.

## Further Reading

- [Log‑Structured Merge‑Tree (Wikipedia)](https://en.wikipedia.org/wiki/Log-structured_merge-tree) – A concise overview of the LSM concept and its variants.  
- [RocksDB Documentation – Compaction](https://github.com/facebook/rocksdb/wiki/Compaction) – Deep dive into compaction strategies and performance tuning.  
- [Apache Cassandra Architecture Guide](https://cassandra.apache.org/doc/latest/architecture.html) – Explains how Cassandra leverages LSM trees for massive write scalability.