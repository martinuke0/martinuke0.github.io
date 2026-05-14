---
title: "Why Log-Structured Merge Trees Outperform B-Trees for Write Throughput"
date: "2026-05-14T10:00:32.367"
draft: false
tags: ["databases", "lsm-tree", "b-tree", "write-performance", "storage-engine"]
description: "Log-Structured Merge (LSM) trees achieve higher write throughput than B‑trees by batching writes, minimizing random I/O, and leveraging sequential disk access, making them ideal for modern SSD‑backed workloads."
summary: "Explore how LSM trees boost write performance compared to B‑trees, the mechanics behind their design, and the trade‑offs involved."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-log-structured-merge-trees-outperform-b-trees-for-write-throughput.svg"
  alt: "Diagram comparing LSM tree layers with B‑tree nodes."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees turn many small, random writes into a few large, sequential operations, dramatically increasing write throughput on modern storage. B‑trees still excel at point reads, but their write path forces costly random I/O that LSM designs avoid.

Write‑intensive workloads have become the norm for many modern applications—time‑series telemetry, log aggregation, and key‑value caching all demand millions of inserts per second. Historically, the B‑tree family dominated on‑disk indexing because of its balanced search properties, but the Log‑Structured Merge (LSM) tree, first described by O'Neil et al. in 1996, has since eclipsed B‑trees in raw write throughput. This article dissects why, by examining the underlying algorithms, hardware interactions, and real‑world implementations.

## The Traditional B‑Tree Write Path

### Structure and Guarantees

A B‑tree is a height‑balanced, multi‑way search tree where each node contains a sorted array of keys and child pointers. The tree maintains two invariants:

1. All leaf nodes reside at the same depth.
2. Every internal node (except possibly the root) holds between ⌈m/2⌉ and m keys, where *m* is the branching factor.

These invariants guarantee *O(log N)* search, insert, and delete complexity while keeping the tree height low, which is essential for minimizing disk seeks.

### Insert Mechanics

When inserting a new key‑value pair:

1. **Locate the leaf** – a series of *log N* node reads (often random I/O).
2. **Insert into the leaf’s in‑memory buffer** – if the leaf has space, the operation finishes.
3. **Split on overflow** – if the leaf is full, it splits, propagating a *push‑up* of the middle key to the parent. This can cascade up to the root, causing a *tree re‑balance*.

Because each split writes a new node to disk, a single insert may trigger **multiple random writes**. Even with write‑back caches, the underlying storage device still sees many small, scattered writes, which is especially painful on HDDs and, to a lesser extent, SSDs.

### Write Amplification

Write amplification is the ratio of physical bytes written to logical bytes supplied by the application. In a B‑tree, each split writes an entire node (often 4–16 KB) for a single key, yielding an amplification factor of 4–8× or higher under heavy insert workloads. This overhead directly throttles throughput.

## The LSM Tree Write Path

### Core Idea

An LSM tree decouples *write ordering* from *read ordering*. Writes first land in an in‑memory structure (commonly a sorted string table, or **memtable**) and are later flushed to disk as **immutable sorted files** (SSTables). The on‑disk layout consists of multiple *levels* (L0, L1, …), each holding a set of SSTables with increasing size constraints.

### Step‑by‑Step Insert Flow

```text
┌─────────────────────┐
│   Application Write │
└─────────┬───────────┘
          ▼
   ┌─────────────┐
   │  Memtable   │  (e.g., a red‑black tree)
   └─────┬───────┘
         │
   (Memtable fills)
         ▼
   ┌─────────────────────┐
   │   Flush to Disk     │   →  Write a new SSTable (sequential)
   └─────────────────────┘
         │
   ┌─────▼─────┐
   │ Compaction│ (merge overlapping SSTables)
   └───────────┘
```

1. **Memtable insert** – O(log M) in‑memory operation (M = memtable size), no disk I/O.
2. **Immutable memtable** – once full, it is frozen and scheduled for a *flush*.
3. **Flush** – the frozen memtable is written to a new SSTable file using a single sequential write. This eliminates random I/O for the original insert.
4. **Compaction** – background process merges overlapping SSTables to maintain read efficiency and enforce size limits per level.

Because the flush is sequential and the compaction runs asynchronously, the *critical path* for an insert is essentially a cheap in‑memory update, giving LSM trees a **dramatically lower write amplification** (often 1.5–2×).

### Write Batching and Sequentiality

A typical LSM implementation (e.g., RocksDB) batches millions of key‑value pairs into a single 64 MB SSTable. The OS and storage controller can coalesce these into large, contiguous writes, fully exploiting the bandwidth of modern NVMe SSDs. In contrast, a B‑tree would interleave many 4 KB random writes throughout the same period.

## Compaction Strategies: The Hidden Cost

### Why Compaction Matters

Compaction reconciles the *write‑optimized* layout (many small SSTables) with the *read‑optimized* layout (few, larger, non‑overlapping files). There are three primary compaction styles:

| Style          | Typical Use‑Case | Trade‑offs |
|----------------|------------------|------------|
| **Levelled**   | RocksDB, LevelDB | Low read latency, higher write amplification |
| **Tiered**     | Cassandra, ScyllaDB | Higher write throughput, larger read amplification |
| **Universal**  | Apache Druid     | Good for time‑series, balances both |

Each style schedules background merges that read overlapping SSTables and rewrite them into a new level. The cost is *read‑modify‑write* traffic, but because it occurs off the critical path, the *perceived* write latency remains low.

### Example Compaction Script (bash)

```bash
#!/usr/bin/env bash
# Simple demonstration of invoking RocksDB's manual compaction
DB_PATH="/var/lib/rocksdb"
LEVEL=0

echo "Starting manual compaction of level $LEVEL..."
rocksdb-cli --db=$DB_PATH compact --start_level=$LEVEL --end_level=$LEVEL
echo "Compaction completed."
```

Running compactions during low‑traffic windows can further reduce their impact on foreground writes.

## Hardware Interaction: HDD vs SSD vs NVMe

### Random vs Sequential I/O

| Device | Random Write Cost | Sequential Write Cost |
|--------|-------------------|-----------------------|
| HDD    | ~10 ms per 4 KB   | ~0.1 ms per MB        |
| SATA SSD | ~0.1 ms per 4 KB | ~0.02 ms per MB       |
| NVMe SSD | ~0.02 ms per 4 KB | ~0.005 ms per MB      |

The B‑tree’s random writes become a bottleneck on HDDs and remain non‑trivial on SSDs due to write amplification and wear leveling. LSM trees, by converting most writes to sequential patterns, align perfectly with the strengths of SSDs and especially NVMe drives, where throughput scales linearly with write size.

### Write Amplification on Flash

Flash memory has a *program‑erase* cycle constraint. Random small writes cause the flash controller to perform **read‑modify‑write** cycles internally, inflating wear. Sequential large writes allow the controller to write whole blocks, reducing internal amplification. LSM trees, therefore, extend SSD lifespan compared to B‑trees under identical logical write loads.

## Real‑World Deployments

| System | Engine | Choice of Tree | Reason |
|--------|--------|----------------|--------|
| **Cassandra** | LSM (via Apache Cassandra's own storage engine) | LSM | High write throughput for time‑series and logging data |
| **RocksDB** | LSM (Levelled) | LSM | Embedded key‑value store for write‑heavy workloads |
| **MongoDB** (WiredTiger) | LSM (Hybrid) | LSM | Balances write speed with read latency |
| **MySQL InnoDB** | B‑tree | B‑tree | Transactional workloads with strong point‑read requirements |
| **PostgreSQL** | B‑tree (default) | B‑tree | General‑purpose OLTP with balanced read/write |

These examples illustrate that the industry often defaults to LSM for write‑dominant scenarios, while B‑trees remain the go‑to for mixed or read‑heavy workloads.

## Benchmark Snapshot

A recent YCSB benchmark (source: [RocksDB vs InnoDB performance study](https://rocksdb.org/blog/2023/09/benchmark.html)) measured **500 k inserts/second** for RocksDB (LSM) against **120 k inserts/second** for InnoDB (B‑tree) on identical NVMe hardware. The LSM configuration used a 64 MB memtable, levelled compaction, and a 4‑hour warm‑up period. Read latency for point lookups was higher for RocksDB (≈2 ms) than InnoDB (≈0.5 ms), confirming the classic trade‑off.

## Trade‑offs Beyond Write Throughput

### Read Amplification

Because multiple SSTables may need to be consulted for a single key, LSM trees can suffer from **read amplification**. Bloom filters, fence pointers, and partitioned indexes mitigate this, but they add memory overhead.

### Space Amplification

Compaction temporarily stores both old and new versions of data, leading to **space amplification** up to 2× during heavy write bursts. B‑trees have lower space overhead but higher write costs.

### Consistency and Durability

Both structures can provide ACID guarantees, but the LSM’s asynchronous compaction introduces a window where recently flushed data exists in multiple places. Proper write‑ahead logging (WAL) and checkpointing are essential; see the **RocksDB WAL** documentation for details.

## Design Guidelines for Practitioners

1. **Assess Write vs Read Ratio** – If writes exceed ~70 % of total operations, LSM is usually the better choice.
2. **Size Your Memtable** – Larger memtables increase flush size, improving sequentiality, but also increase latency for the first write after a flush.
3. **Tune Compaction** – Choose levelled compaction for read‑heavy workloads, tiered for write‑heavy, and adjust the number of background threads to match I/O capacity.
4. **Enable Bloom Filters** – A 10 % false‑positive rate can cut read I/O by 30–50 % without significant memory cost.
5. **Monitor Write Amplification** – Tools like `rocksdb-stats` expose `total_write_amp` metrics; keep this below 2× for SSD longevity.

## Key Takeaways

- **Write Path Simplicity** – LSM trees batch inserts in memory and flush them as large, sequential files, eliminating the random writes that dominate B‑tree insert costs.
- **Lower Write Amplification** – Typical LSM implementations achieve 1.5–2× amplification versus 4–8× for B‑trees, directly translating to higher throughput.
- **Hardware Alignment** – Modern NVMe SSDs are optimized for sequential I/O; LSM trees exploit this, while B‑trees remain bound by random‑seek penalties.
- **Compaction Is the Trade‑off** – Background merges restore read efficiency but consume CPU, I/O, and temporary extra space; proper tuning mitigates impact.
- **Read vs Write Balance** – Choose LSM for write‑heavy, B‑tree for read‑heavy or mixed workloads; hybrid approaches (e.g., WiredTiger) can offer a middle ground.
- **Operational Monitoring** – Track memtable size, flush frequency, and write amplification to keep performance predictable and hardware wear low.

## Further Reading

- [The original LSM paper by O'Neil et al. (1996)](https://www.cs.umb.edu/~poneil/papers/lsm.pdf)  
- [RocksDB documentation – Compaction and Write Amplification](https://rocksdb.org/docs/latest/operations/compaction.html)  
- [Cassandra architecture guide – Storage Engine](https://cassandra.apache.org/doc/latest/architecture/architecture.html)  
- [Understanding B‑Tree write amplification](https://www.sqlite.org/btree.html)  
- [NVMe performance characteristics – Intel SSD whitepaper](https://www.intel.com/content/www/us/en/architecture-and-technology/solid-state-drive-performance.html)  