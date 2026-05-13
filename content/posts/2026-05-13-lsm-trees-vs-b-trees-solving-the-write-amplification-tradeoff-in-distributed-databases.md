---
title: "LSM Trees vs B-Trees: Solving the Write Amplification Tradeoff in Distributed Databases"
date: "2026-05-13T10:00:51.579"
draft: false
tags: ["LSM", "B-Tree", "Write Amplification", "Distributed Databases", "Storage Engines"]
description: "Explore how LSM trees and B‑trees differ in handling write amplification, and why distributed databases favor one over the other for performance and durability."
summary: "A deep dive into LSM trees versus B‑trees, focusing on write amplification, read/write trade‑offs, and their impact on modern distributed database design."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-lsm-trees-vs-b-trees-solving-the-write-amplification-tradeoff-in-distributed-databases.svg"
  alt: "Diagram comparing LSM tree and B‑tree structures."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees dramatically reduce write amplification by batching writes and deferring compaction, making them ideal for write‑heavy distributed workloads. B‑trees offer lower read latency and simpler range queries, so the choice hinges on the workload’s read‑write balance and the system’s consistency requirements.

Modern distributed databases must juggle high throughput, low latency, and strong durability. Two storage‑engine families dominate the design space: the classic B‑tree and the log‑structured merge (LSM) tree. While B‑trees excel at point reads and ordered scans, LSM trees shine when writes dominate and hardware favors sequential I/O. Understanding how each structure creates—or mitigates—*write amplification* is essential for architects who need to tune performance, control storage costs, and guarantee data safety.

## Fundamentals of B‑Trees

B‑trees are balanced search trees where each node can hold multiple keys and child pointers. Their design guarantees O(log N) depth, ensuring predictable lookup times even as datasets grow.

### Structure and Operations

A typical B‑tree node contains:

```text
[key₁, key₂, …, keyₖ]   // sorted keys
[ptr₀, ptr₁, …, ptrₖ]   // child pointers (k+1)
```

*Insertion* proceeds by descending the tree to the appropriate leaf, inserting the key, and splitting the node if it overflows. Splits propagate upward, potentially reaching the root and increasing tree height.

```python
def btree_insert(root, key):
    leaf = descend_to_leaf(root, key)
    leaf.keys.append(key)
    leaf.keys.sort()
    if len(leaf.keys) > MAX_KEYS:
        split_node(leaf)
```

### Write Amplification in B‑Trees

Write amplification occurs when a single logical write triggers multiple physical writes. In a B‑tree, each insert may cause:

1. **Leaf write** – the modified leaf page.
2. **Node splits** – each split rewrites the parent node.
3. **Propagation** – up‑the‑tree splits can cascade to the root.

If a leaf split triggers a parent split, the original write results in three or more disk pages being flushed. On storage media with high write latency (e.g., HDDs) or limited write endurance (e.g., SSDs), this overhead can degrade throughput and shorten device lifespan.

## Fundamentals of LSM Trees

LSM trees invert the write path: instead of writing in place, they append to sequential logs and later merge sorted runs. This design trades immediate read simplicity for write efficiency.

### Log‑Structured Design

An LSM tree consists of multiple *levels* (L0, L1, …). New writes land in an in‑memory *memtable* (often a skip list). When the memtable fills, it is frozen, serialized to an immutable *sstable* on disk, and added to level 0.

```bash
# Flush memtable to disk as an sstable
$ echo "flush memtable" > /dev/null
```

Because flushing writes a single contiguous file, the physical write cost equals the logical write size—*write amplification* is close to 1.

### Compaction and Write Amplification

Compaction merges overlapping sstables into larger, sorted runs at higher levels, discarding obsolete keys (tombstones). While compaction re‑writes data, it is performed *asynchronously* and can be throttled. The overall write amplification factor (WAF) for an LSM tree is roughly:

```
WAF ≈ 1 + (size of compaction work) / (size of incoming writes)
```

With tiered or leveled compaction strategies, WAF can be kept between 2× and 10×, far lower than the worst‑case cascade in B‑trees for heavy write workloads.

## Comparing Performance in Distributed Environments

Distributed databases replicate data across nodes, introduce network latency, and must handle concurrent writes. The storage engine’s behavior directly influences cluster-wide metrics.

### Write Path Latency

| Engine | Write Path Steps | Typical Latency (SSD) |
|--------|------------------|-----------------------|
| B‑Tree | Log → Page Cache → Page Write → Possible Split → Flush | 0.5 ms – 1 ms |
| LSM    | Log → Memtable Append → Flush (async) → Background Compaction | 0.1 ms – 0.3 ms |

LSM’s append‑only memtable allows the client request to return after a tiny in‑memory operation, while B‑tree writes may stall on disk I/O during node splits.

### Read Path Complexity

* Point reads in B‑trees require a single tree traversal (≈ log N page reads).  
* LSM reads must probe multiple levels: a Bloom filter checks each level, then the engine may perform up to *L* disk reads (one per level) before finding the latest version.

```python
def lsm_point_read(key):
    for level in levels:
        if level.bloom.might_contain(key):
            record = level.search_sstable(key)
            if record:
                return record
    return None
```

Thus, LSM trees pay a read penalty, especially for random point lookups, unless Bloom filters and caching are well‑tuned.

### Consistency and Recovery

Both engines support write‑ahead logging (WAL) for durability. However, LSM’s immutable sstables simplify crash recovery: after a crash, the system replays the WAL to rebuild the memtable and discards any partially written sstables. B‑trees must reconcile partially applied page splits, which can be more error‑prone.

## Architectural Choices in Popular Systems

### Apache Cassandra

Cassandra uses a *partition‑key*‑based LSM implementation (the **SSTable** format). It relies on *size‑tiered compaction* by default, offering low write amplification at the cost of occasional read spikes during compaction.

*Reference*: [Cassandra Architecture Guide](https://cassandra.apache.org/doc/latest/architecture.html)

### RocksDB & TiDB

RocksDB, the storage engine behind TiDB, provides configurable compaction strategies (leveled, tiered, FIFO). TiDB exposes these knobs via SQL hints, allowing workloads to balance write amplification against read latency dynamically.

*Reference*: [RocksDB Compaction Overview](https://rocksdb.org/blog/2020-03-23-compaction.html)

### PostgreSQL's B‑Tree Indexes

PostgreSQL ships with classic B‑tree indexes for most workloads. Extensions like *pg\_lsm* experiment with LSM‑style indexes, but the core engine remains B‑tree‑centric, reflecting its emphasis on strong point‑query performance.

*Reference*: [PostgreSQL Index Types](https://www.postgresql.org/docs/current/indexes-types.html)

## Mitigating Write Amplification

Even within each engine, administrators can tune parameters to reduce the effective WAF.

### Tiered Compaction

Leveled compaction keeps each level size bounded, limiting the amount of data rewritten during merges. This approach caps WAF around 2–4× for typical workloads.

```yaml
# Example RocksDB options for leveled compaction
compaction_style: leveled
level0_file_num_compaction_trigger: 4
max_bytes_for_level_base: 256MB
```

### Write Buffering Strategies

Increasing the memtable size reduces flush frequency, lowering the number of small sstables that must be merged later.

```bash
# Increase memtable size in Cassandra
cassandra.yaml:
  memtable_total_space_in_mb: 2048
```

### Hybrid Approaches

Some systems combine B‑tree and LSM concepts. For example, *HBase* stores write‑ahead logs (WAL) like an LSM, but uses B‑tree‑based block caches for hot reads.

## Key Takeaways

- **Write amplification** is intrinsic to both structures, but LSM trees achieve far lower amplification for write‑heavy workloads by batching writes and deferring merges.  
- **Read latency** favors B‑trees; LSM reads may involve multiple level scans unless Bloom filters and caching are aggressively tuned.  
- **Compaction strategy** is the primary lever for controlling LSM write amplification; tiered or leveled compaction can keep WAF under 5×.  
- **System design** matters: distributed databases that prioritize linear scalability and high ingest rates (Cassandra, TiDB) usually adopt LSM, while OLTP‑focused systems (PostgreSQL, MySQL InnoDB) stick with B‑trees.  
- **Hybrid models** exist and can offer a middle ground, but they add operational complexity.

## Further Reading

- [Log-Structured Merge Trees (LSM) – Wikipedia](https://en.wikipedia.org/wiki/Log-structured_merge-tree)  
- [B‑Tree – Wikipedia](https://en.wikipedia.org/wiki/B-tree)  
- [Apache Cassandra Architecture Overview](https://cassandra.apache.org/doc/latest/architecture.html)  
- [RocksDB Documentation – Compaction](https://rocksdb.org/blog/2020-03-23-compaction.html)  
- [PostgreSQL Index Types](https://www.postgresql.org/docs/current/indexes-types.html)