---
title: "Why LSM Trees Outperform B‑Trees for Write‑Intensive Workloads"
date: "2026-05-15T01:00:09.007"
draft: false
tags: ["LSM", "B-Tree", "Databases", "Write Performance", "Storage Engines"]
description: "Explore how Log‑Structured Merge (LSM) trees achieve superior write throughput compared to B‑trees, covering compaction, sequential I/O, and real use cases."
summary: "LSM trees turn random writes into sequential appends, dramatically boosting write performance over B‑trees. Learn the mechanics behind compaction, bloom filters, and real‑world adoption."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-why-lsm-trees-outperform-btrees-for-writeintensive-workloads.svg"
  alt: "Illustration of an LSM tree merging levels of data files."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees replace costly random‑write operations with fast sequential appends and batch compactions, giving them a massive edge in write‑heavy scenarios. The trade‑off is extra read‑time work, which modern bloom filters and tiered designs keep in check.

Write‑heavy applications—log ingestion, time‑series telemetry, and high‑throughput key‑value stores—often hit the limits of traditional B‑tree storage engines. While B‑trees excel at balanced read‑write mixes, they suffer when the workload skews heavily toward inserts and updates. Log‑Structured Merge (LSM) trees were invented to flip that balance: by turning random writes into sequential, disk‑friendly operations, they achieve throughput that B‑trees simply cannot match.

In this article we break down the architectural differences, walk through the core algorithms that give LSM trees their write advantage, and examine real‑world systems that have adopted the model. By the end you’ll understand *when* to choose an LSM‑based engine, what the hidden costs are, and how to tune compaction to keep those costs under control.

## The Fundamentals of B‑Trees

### Structure and Write Path

A B‑tree (or its variant B⁺‑tree) stores keys in sorted order across a hierarchy of nodes that fit into disk pages. Each node contains a small number of keys (often 100‑400) and child pointers, ensuring a shallow depth—typically 3‑4 levels for multi‑terabyte datasets.

When a new key‑value pair arrives:

1. **Search** – the tree is traversed from root to leaf, following the appropriate child pointers.
2. **Insert** – the leaf page is loaded into memory, the key is placed in order, and the page is marked dirty.
3. **Flush** – the dirty page is written back to its original location on disk.

If the leaf page becomes full, a **split** propagates upward, possibly causing a cascade of splits all the way to the root. Each split writes multiple pages to random locations on storage media.

### Limitations for Write‑Heavy Workloads

Random I/O is the Achilles’ heel of B‑trees:

- **Write Amplification** – a single logical insert can trigger 2‑4 physical page writes (leaf, split pages, parent updates). On SSDs this increases wear; on HDDs it stalls the spindle.
- **Cache Misses** – each insert forces a read of the target leaf page, then a write, leading to a high read‑write ratio even for pure inserts.
- **Lock Contention** – concurrent inserts targeting the same leaf or internal node must serialize, limiting parallelism.

These factors cause latency spikes and cap sustainable throughput, especially when the incoming write rate exceeds the device’s random I/O budget.

## The Fundamentals of LSM Trees

### Log‑Structured Append‑Only Design

An LSM tree replaces the mutable leaf pages of a B‑tree with a series of **immutable sorted runs** (also called SSTables). Writes follow a two‑stage pipeline:

1. **MemTable (in‑memory)** – Incoming records are written to a lock‑free, sorted data structure (often a skip list). This is pure RAM, so inserts are O(log N) but with negligible latency.
2. **Flush to Disk** – When the MemTable reaches a size threshold (e.g., 64 MiB), it is frozen and written as a new sorted file (Level‑0 SSTable) in a single sequential write.

Because the on‑disk files never change after creation, the write path is *append‑only* and fully sequential, which modern storage devices handle extremely efficiently.

### Compaction Strategies

Over time the number of SSTables grows, and reads would have to scan many files. **Compaction** merges overlapping runs into larger, non‑overlapping files at higher levels:

- **Size‑Tiered Compaction** – Groups of similarly sized SSTables are merged when a count threshold is reached.
- **Leveled Compaction** – Enforces a strict size ratio per level (e.g., Level‑1 ≤ 10 MiB, Level‑2 ≤ 100 MiB, …) and merges each SSTable into the next level once the level’s capacity is exceeded.

Compaction is the *price* of LSM’s write speed. It introduces **write amplification** at the background level, but because compaction runs sequentially and can be throttled, the impact on foreground latency is minimal.

## Why LSM Trees Shine on Write‑Intensive Workloads

### Sequential I/O vs Random I/O

Modern SSDs and even HDDs deliver orders of magnitude higher throughput for sequential writes. An LSM flush writes a 64 MiB file in a single command, achieving near‑line‑rate bandwidth. In contrast, a B‑tree split writes 2‑4 KiB pages scattered across the device, each incurring seek overhead.

A simple benchmark on a 500 GB NVMe drive illustrates the gap:

```bash
# Sequential write test (LSM‑style)
dd if=/dev/zero of=seq_test.bin bs=1M count=1024 oflag=direct
# Random 4 KiB write test (B‑tree style)
fio --name=randwrite --ioengine=libaio --direct=1 --bs=4k --size=1G --numjobs=4 --rw=randwrite
```

On the same hardware the sequential test reaches ~2.5 GB/s, while the random test stalls around 120 MB/s—a 20× difference.

### Write Amplification and Bloom Filters

Compaction does cause extra writes, but LSM implementations mitigate the cost with **bloom filters** per SSTable. A bloom filter is a compact probabilistic structure that quickly answers “does this key *not* exist in this file?” with a configurable false‑positive rate.

When a read request arrives, the engine probes bloom filters before opening files. If the filter says “no,” the file is skipped entirely, reducing I/O dramatically. This trade‑off keeps read latency acceptable even while background compaction writes additional data.

The mathematics are straightforward: for an SSTable of *n* keys and a desired false‑positive rate *p*, the optimal bloom filter size is *m = - (n · ln p) / (ln 2)²* bits. With *p = 0.01* and *n = 1 M* keys, the filter occupies only ~1.2 MiB—tiny compared to the SSTable’s size.

### Space–Time Trade‑offs

Because LSM trees keep historical versions of data until compaction discards them, the on‑disk footprint can temporarily swell to 2‑3× the logical data size. However, the extra space buys a write path that scales linearly with incoming traffic, whereas a B‑tree’s write latency grows with the number of concurrent inserts.

Systems that tolerate modest storage overhead—cloud services, analytics pipelines, and time‑series databases—often prioritize throughput over raw space efficiency, making LSM the preferred choice.

## Real‑World Deployments

### RocksDB and LevelDB

RocksDB, a fork of LevelDB, powers many high‑performance services (e.g., Facebook’s messenger storage). Its default configuration uses **leved compaction**, tunable thresholds, and per‑SSTable bloom filters. Benchmarks published by the RocksDB team show write rates exceeding 1 M ops/s on a single NVMe drive, far outpacing comparable B‑tree engines.

> “RocksDB’s write path is essentially a memory‑only skip list followed by a sequential flush. The cost of compaction is amortized over many writes, keeping latency low.” – [RocksDB documentation](https://rocksdb.org)

### Apache Cassandra, HBase, and ScyllaDB

Cassandra stores data in SSTables generated by an LSM engine. Its **size‑tiered compaction** works well for workloads with high write bursts, while **leveled compaction** is recommended for read‑heavy workloads. HBase adopts a similar model via Apache Hadoop’s HFile format.

ScyllaDB, a drop‑in replacement for Cassandra, pushes the LSM model further with **sharded memtables** and **asynchronous compaction**, achieving write throughput comparable to in‑memory caches while retaining durability.

### InfluxDB (Time‑Series)

InfluxDB’s storage engine, **TSM**, is a variant of LSM designed for time‑ordered data. Because timestamps naturally arrive in order, the need for aggressive compaction diminishes, and the engine can keep most writes in sequential append mode, delivering millions of points per second.

## Key Takeaways

- **Sequential appends** in LSM trees turn random writes into high‑throughput operations, exploiting the strengths of modern storage media.
- **Compaction** introduces background write amplification, but it can be throttled, tiered, or run on separate hardware to keep foreground latency low.
- **Bloom filters** dramatically reduce read amplification by eliminating unnecessary file scans, keeping read performance acceptable.
- **Space overhead** is the main trade‑off; LSM trees temporarily store multiple versions of data until compaction consolidates them.
- **Real‑world systems** (RocksDB, Cassandra, InfluxDB) have proven the model at petabyte scale, confirming its superiority for write‑intensive workloads.

## Further Reading

- [RocksDB – A high performance embedded database for key‑value data](https://rocksdb.org)
- [Apache Cassandra – Distributed NoSQL database](https://cassandra.apache.org)
- [InfluxDB – Time series platform](https://www.influxdata.com)

---