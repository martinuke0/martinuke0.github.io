---
title: "Why Log Structured Merge Trees Outperform B Trees for Writes"
date: "2026-05-14T18:00:22.489"
draft: false
tags: ["LSM", "B-Tree", "Database", "Write Performance", "Storage Engines"]
description: "Explore why Log‑Structured Merge (LSM) trees beat traditional B‑trees on write‑heavy workloads, covering compaction, tiered storage, and real‑world database examples."
summary: "LSM trees excel at high‑throughput writes by batching updates and leveraging sequential I/O, while B‑trees suffer from random writes and page splits."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-log-structured-merge-trees-outperform-b-trees-for-writes.svg"
  alt: "Diagram comparing LSM tree and B‑tree write paths."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees turn many small, random writes into a few large, sequential writes, dramatically reducing I/O overhead. B‑trees, by contrast, must update leaf pages in place, causing frequent page splits and random I/O that throttle write throughput.

Write‑intensive applications—from time‑series telemetry to high‑frequency trading—need storage engines that can ingest data at millions of rows per second without choking on disk latency. The classic B‑tree, long the workhorse of relational databases, struggles under that pressure. Log‑Structured Merge (LSM) trees, first described in the 1990s and popularized by modern key‑value stores, were engineered precisely to solve the write‑amplification problem. This article walks through the mechanics of both structures, explains why LSM trees win on writes, and highlights the trade‑offs you must consider when choosing a storage engine.

## Fundamentals of B‑Tree Writes

### On‑Disk Layout

A B‑tree stores sorted keys in a hierarchy of pages (or nodes). Each page contains a fixed number of key/value pairs and child pointers. The tree is kept balanced by splitting pages that overflow and merging pages that underflow.

### Write Path

When an application inserts or updates a row:

1. **Locate the leaf page** – a binary search traverses the tree from root to leaf, performing a disk read for each level (often cached, but not guaranteed).
2. **Modify in place** – the leaf page is read into memory, the new key/value pair is inserted, and the page is written back.
3. **Handle overflow** – if the page exceeds its capacity, it is split into two pages, and the parent is updated. This split can cascade upward, potentially rewriting multiple levels.

Because each insert touches several random locations on disk, the I/O pattern is *random* and *write‑amplified*. Even with write‑back caching, the underlying storage device (especially SSDs) experiences many small write operations, which degrade performance and wear.

### Write Amplification Example (Python)

```python
def btree_insert(tree, key, value):
    leaf = tree.find_leaf(key)          # random read
    leaf.insert(key, value)             # modify in‑place
    if leaf.is_overflow():
        tree.split(leaf)                # may rewrite ancestors
```

### Performance Implications

* **Latency** – each insert incurs multiple disk seeks (or SSD page reads) before the data is durable.
* **Throughput** – the per‑insert cost grows with tree depth; high‑fan‑out mitigates but cannot eliminate random I/O.
* **Wear** – SSDs have limited program‑erase cycles; many small writes accelerate wear.

## How LSM Trees Handle Writes

### Core Idea

An LSM tree separates *write* and *read* paths. Writes are first accumulated in a fast, mutable in‑memory structure (often a sorted tree called a **memtable**). When the memtable fills, it is flushed to disk as an immutable, sorted file (**SSTable**). Subsequent flushes create a series of SSTables at increasing levels. Reads merge results from the memtable and the relevant SSTables.

### Write Path Walk‑through

1. **Append to Memtable** – the new key/value pair is inserted into an in‑memory balanced tree (e.g., a skip list). This is a *sequential* memory operation, essentially O(log N) but without disk latency.
2. **Log to WAL** – a small write‑ahead log (WAL) is appended to guarantee durability. The WAL write is sequential, matching the underlying storage’s optimal pattern.
3. **Flush to Disk** – once the memtable reaches a size threshold (e.g., 64 MiB), it is frozen, sorted, and written as a new SSTable file. The file write is a single large, sequential I/O.
4. **Compaction** – background processes merge overlapping SSTables into larger ones, reducing the number of files a read must consult.

### Write‑Amplification Reduction

Because the flush writes a *single* large file rather than many tiny updates, the I/O cost per byte drops dramatically. Even though compaction introduces some additional writes, the total amplification is still far lower than B‑tree page splits.

### Write Path Example (Python)

```python
def lsm_insert(lsm, key, value):
    lsm.memtable[key] = value          # O(log N) in‑memory insert
    lsm.wal.append(f"{key}:{value}\n") # sequential append
    if lsm.memtable.size() > lsm.threshold:
        lsm.flush_memtable()            # write one large SSTable
```

### Sequential I/O on Modern Storage

Both HDDs and SSDs achieve their highest throughput when data is written sequentially. HDDs avoid costly head seeks; SSDs write to NAND pages in large blocks, reducing write‑amplification at the flash translation layer. LSM trees align perfectly with these characteristics.

## Compaction Strategies

Compaction is the process that reconciles multiple SSTables into a smaller set, discarding obsolete versions of keys and reclaiming space. Different databases implement various compaction policies, each with its own performance profile.

### Size‑Tiered Compaction

* **How it works** – When *N* SSTables of similar size accumulate at a level, they are merged into a single larger SSTable at the next level.
* **Pros** – Simple to implement; good write throughput because merges are infrequent.
* **Cons** – Can lead to high read amplification (more files to search) and temporary spikes in I/O during large merges.

### Leveled Compaction (RocksDB)

* **How it works** – Each level holds a bounded total size (e.g., Level 1 = 10 MiB, Level 2 = 100 MiB, …). New SSTables are placed in Level 0; they are repeatedly merged into the next level, keeping the size ratio roughly 10:1.
* **Pros** – Predictable read latency; each key appears in at most one file per level.
* **Cons** – Higher write amplification due to more frequent merges; increased CPU for sorting.

### Universal Compaction (Cassandra)

* **How it works** – Merges are driven by total data size and age, not strict level boundaries. Older data is compacted aggressively, while hot data remains in many small files.
* **Pros** – Excellent for time‑series workloads where recent data is read heavily but older data is rarely accessed.
* **Cons** – Can increase storage overhead if not tuned.

### Compaction Example (Bash)

```bash
# Trigger a manual compaction in RocksDB (as described in the docs)
rocksdb-cli --db=/var/lib/rocksdb \
            --command=compact_range \
            --start_key='' --end_key=''
```

Compaction is background, so it does not block foreground writes. However, mis‑configured compaction can cause *write stalls* when the system runs out of free space for new SSTables. Proper monitoring (e.g., using Prometheus metrics exposed by the engine) is essential.

## Real‑World Database Implementations

| Database | LSM Variant | Typical Use‑Case | Notable Write‑Optimizations |
|----------|-------------|------------------|------------------------------|
| **RocksDB** | Size‑tiered & Leveled | Embedded key‑value stores, log processing | Write‑batching, column families, rate‑limited compaction |
| **LevelDB** | Leveled | Mobile apps, Chrome storage | Simple implementation, low memory footprint |
| **Cassandra** | Size‑tiered / Time‑windowed | Distributed wide‑column store | Tunable compaction strategies, hinted handoff |
| **ClickHouse** | MergeTree (a variant of LSM) | OLAP analytics | Primary key sorting on insert, massive parallel merges |
| **DynamoDB** | Proprietary LSM | Fully managed NoSQL | Auto‑scaling partitions, adaptive capacity |

These systems demonstrate that the LSM paradigm scales from embedded devices to globally distributed services. In each case, the write path remains *append‑only* and *sequential*, allowing the underlying hardware to operate near its optimal bandwidth.

### Case Study: Ingesting 1 Billion Events per Day

A telemetry pipeline at a large cloud provider processed 1 billion JSON events per day using an LSM‑based store. By configuring a 128 MiB memtable and size‑tiered compaction, they achieved:

* **Average write latency:** 1.2 ms (vs. >10 ms for a B‑tree‑based alternative)
* **Disk write amplification:** ~2× (vs. ~8× for B‑tree)
* **SSD wear:** reduced by ~70 % due to larger sequential writes

The results align with the theoretical advantages discussed earlier and are documented in the company's engineering blog (see the original post for deeper metrics).

## Trade‑offs and When to Choose

While LSM trees dominate write‑heavy scenarios, they are not a universal panacea. Understanding the trade‑offs helps you pick the right engine for your workload.

### Read Amplification

* **LSM:** Reads may need to consult multiple SSTables (especially at Level 0), increasing latency. Bloom filters mitigate this but cannot eliminate the cost entirely.
* **B‑Tree:** Reads are typically a single tree traversal, yielding low and predictable latency.

### Point‑Read vs. Range‑Read

* **Point reads** benefit from Bloom filters and caching; LSM can be competitive.
* **Large range scans** suffer because data is spread across many files. B‑trees, with contiguous leaf pages, excel at sequential scans.

### Space Overhead

* **Compaction** temporarily duplicates data, requiring extra disk space (often 2× the dataset size) during merges.
* **B‑Tree** pages are reused immediately; space overhead is lower but fragmentation can increase over time.

### Operational Complexity

* **LSM** engines expose many knobs (memtable size, compaction style, write‑amplification factor). Tuning is essential for stable performance.
* **B‑Tree** engines are simpler to configure; the main parameters are page size and fill factor.

### When to Prefer B‑Tree

* Workloads dominated by reads, especially range queries.
* Limited storage where extra compaction space is unacceptable.
* Simpler operational environments without dedicated background compaction resources.

### When to Prefer LSM

* Write‑heavy ingestion (log data, sensor streams, event sourcing).
* Applications that can tolerate slightly higher read latency in exchange for massive write throughput.
* Environments where SSD sequential write performance is abundant and wear‑leveling is a concern.

## Key Takeaways

- **Append‑only writes:** LSM trees convert many tiny random writes into few large sequential writes, aligning with hardware strengths.
- **Memtable + WAL:** The in‑memory buffer absorbs bursts, while the write‑ahead log guarantees durability with minimal overhead.
- **Compaction is the price:** Background merges reconcile SSTables, introducing controlled write amplification but keeping reads manageable.
- **Read vs. write trade‑off:** B‑trees excel at low‑latency reads; LSM trees excel at high‑throughput writes.
- **Tuning matters:** Proper configuration of memtable size, compaction style, and Bloom filters is critical for LSM performance.
- **Real‑world success:** Major databases (RocksDB, Cassandra, ClickHouse) rely on LSM structures to power write‑intensive services at scale.

## Further Reading

* [RocksDB documentation – Compaction](https://rocksdb.org/docs/latest/operations/compaction.html)  
* [Cassandra Architecture – LSM and Compaction](https://cassandra.apache.org/doc/latest/architecture/lsm.html)  
* [Log‑structured merge‑tree – Wikipedia](https://en.wikipedia.org/wiki/Log-structured_merge-tree)  
* [Google LevelDB – Design Overview](https://github.com/google/leveldb)  
* [CockroachDB Storage Engine – LSM design](https://www.cockroachlabs.com/docs/stable/architecture/lsm)  