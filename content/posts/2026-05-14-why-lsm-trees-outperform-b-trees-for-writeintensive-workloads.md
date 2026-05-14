---
title: "Why LSM Trees Outperform B-Trees for Write‑Intensive Workloads"
date: "2026-05-14T16:00:27.922"
draft: false
tags: ["LSM", "B-Tree", "Databases", "Write Performance", "Storage Engines"]
description: "Explore how Log‑Structured Merge (LSM) trees beat traditional B‑Trees in write‑heavy scenarios, with deep dives into compaction, latency, and real‑world use cases."
summary: "LSM trees dramatically reduce write amplification and improve throughput on write‑intensive workloads, making them the engine of choice for modern databases."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-lsm-trees-outperform-b-trees-for-writeintensive-workloads.svg"
  alt: "Illustration comparing a B‑Tree node and an LSM‑Tree level."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees turn random, small writes into sequential appends, slashing write amplification and boosting throughput. While they trade some read latency for write speed, modern compaction strategies keep the penalty manageable, making LSM the default for write‑heavy systems like Cassandra, RocksDB, and Kafka.

Write‑intensive workloads are the bane of traditional B‑Tree‑based storage engines. Each insert, update, or delete forces a cascade of page splits, node rewrites, and costly random I/O. Log‑Structured Merge (LSM) trees were invented to sidestep those pitfalls by buffering writes in memory and persisting them as large, sequential chunks. The result is a data structure that scales gracefully as write volume grows, while still offering acceptable read performance through clever compaction and bloom‑filter tricks.

## Architectural Differences

### The B‑Tree Write Path

A B‑Tree stores keys in sorted order across a hierarchy of pages (or nodes). When a new key arrives:

1. The leaf page containing the key is located via a tree walk (O(log N) I/O).
2. If the leaf has free slots, the key is inserted in place.
3. If the leaf is full, it is split, and the split propagates upward, potentially rewriting several internal pages.

Because pages are typically 4 KB–16 KB, a single insert can touch multiple random disk blocks. This **write amplification**—the ratio of bytes written to storage vs. bytes supplied by the client—can easily exceed 10× on spinning disks and 4× on SSDs.

### The LSM Tree Write Path

An LSM tree separates the write path into two stages:

1. **MemTable (in‑memory sorted structure)** – usually a skip list or a balanced tree. Writes are appended here with O(log M) cost, where *M* is the size of the MemTable.
2. **Immutable Flushes** – When the MemTable reaches a configurable size (e.g., 64 MiB), it is frozen and written to disk as a **Sorted String Table (SSTable)** in a single sequential write.

Subsequent flushes create **levels** (L0, L1, …). A background **compaction** process merges overlapping SSTables into larger, sorted files, reducing the number of files that must be consulted during reads.

```python
# Simplified LSM write path in Python‑like pseudocode
class LSMTree:
    def __init__(self, memtable_limit):
        self.memtable = SkipList()
        self.mem_limit = memtable_limit
        self.sstables = []   # list of immutable on‑disk files

    def put(self, key, value):
        self.memtable.insert(key, value)
        if self.memtable.size() >= self.mem_limit:
            self.flush()

    def flush(self):
        sstable = write_sstable(self.memtable.iter_items())
        self.sstables.append(sstable)
        self.memtable.clear()
        schedule_compaction()
```

Because the flush is a single sequential write, the **write amplification** drops dramatically—often to 2×‑3× on SSDs.

## Performance Characteristics

### Write Amplification

| Storage Engine | Typical Write Amplification |
|----------------|-----------------------------|
| B‑Tree (e.g., MySQL InnoDB) | 8–12× |
| LSM (e.g., RocksDB default) | 2–4× |
| LSM (tuned with tiered compaction) | 1.5–2× |

The table reflects measurements from the RocksDB benchmark suite and the MySQL performance blog [1](https://www.percona.com/blog/2020/06/23/innodb-btree-vs-rocksdb-lsm-benchmarks). The key takeaway is that **sequential appends cost far less than random page splits**.

### Read Amplification

Reads must consult multiple levels:

1. **MemTable** – always checked first (in‑memory, O(log M)).
2. **Bloom Filters** – per SSTable, quickly reject non‑existent keys.
3. **SSTable Search** – binary search within a file (O(log S)).

The worst‑case read may touch *L* levels, but with exponential growth of level sizes (e.g., each level is 10× larger than the previous), the expected number of SSTables examined stays low (often < 3). Bloom filters further reduce unnecessary I/O to < 1 % of reads [2](https://rocksdb.org/blog/2021/08/02/bloom-filters.html).

### Space Amplification

Compaction temporarily duplicates data while merging, leading to **space amplification** of around 1.2×‑1.5×. This is a deliberate trade‑off: the extra space allows the system to keep write latency low while cleaning up obsolete versions in the background.

## Real‑World Deployments

| System | Primary Storage Engine | Write Workload Profile |
|--------|------------------------|------------------------|
| Apache Cassandra | LSM (SSTable) | High‑throughput writes from IoT and logging |
| Google LevelDB | LSM (SSTable) | Embedded key‑value store for Chrome |
| Facebook RocksDB | LSM (Log‑structured) | Write‑heavy caching layer for social feeds |
| PostgreSQL (default) | B‑Tree | OLTP workloads with balanced reads/writes |

In Cassandra, the **commit log** guarantees durability, while the **memtable** absorbs writes. A typical node can sustain > 200 k writes/s on modern NVMe drives, a figure unattainable with a pure B‑Tree engine without aggressive batching [3](https://cassandra.apache.org/doc/latest/architecture.html).

## Trade‑offs and When to Choose B‑Tree

LSM trees excel when **writes dominate** and the application can tolerate slightly higher read latency. However, they are not a universal replacement.

| Scenario | Recommended Engine |
|----------|--------------------|
| Point‑lookup heavy workloads (e.g., primary‑key reads) | B‑Tree (or LSM with aggressive caching) |
| Mixed read/write with short-lived data | B‑Tree, to avoid compaction overhead |
| Write‑only ingest pipelines (logs, metrics) | LSM, because sequential writes dominate |
| Low‑memory environments (embedded devices) | B‑Tree, as LSM needs extra RAM for MemTables and bloom filters |

Compaction can also cause **write stalls** if the background thread cannot keep up, especially on overloaded disks. Proper tuning of **compaction threads**, **size‑tiered vs. leveled policies**, and **write buffers** mitigates this risk.

## Key Takeaways

- **Sequential appends** in LSM flushes replace random page splits, cutting write amplification to roughly half of B‑Tree levels.
- **Compaction** merges SSTables to keep read paths short; bloom filters make the extra levels cheap to probe.
- **Space overhead** is modest (≈ 1.3×) compared with the dramatic gain in write throughput.
- Real‑world systems (Cassandra, RocksDB, LevelDB) prove that LSM is the de‑facto choice for log‑heavy, time‑series, and analytics pipelines.
- B‑Trees still win for **read‑dominant, low‑latency point lookups** and when memory is scarce.

## Further Reading

- [LevelDB: A Fast Persistent Key‑Value Store](https://storage.googleapis.com/google-code-archive-downloads/v2/code.google.com/leveldb/leveldb.pdf) – original academic paper introducing LSM concepts.
- [RocksDB Documentation](https://rocksdb.org) – deep dive into compaction strategies, tuning parameters, and performance benchmarks.
- [B‑Tree on Wikipedia](https://en.wikipedia.org/wiki/B-tree) – fundamentals of the classic balanced tree structure.
- [Cassandra Architecture Guide](https://cassandra.apache.org/doc/latest/architecture.html) – practical use‑case of LSM in a distributed database.