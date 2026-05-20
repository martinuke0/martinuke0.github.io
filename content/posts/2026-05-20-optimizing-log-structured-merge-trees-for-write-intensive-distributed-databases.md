---
title: "Optimizing Log-Structured Merge Trees for Write-Intensive Distributed Databases"
date: "2026-05-20T01:00:13.344"
draft: false
tags: ["LSM", "distributed databases", "performance", "compaction", "architecture"]
description: "Explore how LSM trees can be tuned for massive write workloads in distributed databases, covering architecture, performance trade‑offs, and practical compaction patterns."
summary: "A deep dive into LSM tree internals for write‑heavy clusters, with real‑world patterns from RocksDB, Cassandra, and ScyllaDB."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-20-optimizing-log-structured-merge-trees-for-write-intensive-distributed-databases.svg"
  alt: "Diagram of a multi‑level LSM tree with compaction arrows."
  caption: ""
  relative: false
---

> **TL;DR** — In write‑intensive distributed databases, LSM trees achieve high throughput by separating mutable memtables from immutable SSTables, but careful architecture choices, adaptive compaction policies, and observability are essential to keep read latency and storage overhead in check.

Write‑heavy workloads dominate modern services such as telemetry ingestion, event streaming, and ad‑tech pipelines. Log‑Structured Merge (LSM) trees have become the de‑facto storage engine for systems that must sustain millions of writes per second while still serving low‑latency reads. This post unpacks the architecture of a distributed LSM, quantifies its performance characteristics, and walks through the compaction patterns that keep the system healthy at scale. All examples reference production‑grade stacks—RocksDB, Apache Cassandra, and ScyllaDB—so you can see how the theory translates into day‑to‑day ops.

## Architecture Overview

### Core Components

An LSM tree is built around three logical layers:

1. **Memtable (in‑memory mutable structure)** – usually a skip‑list or a balanced tree that accepts writes instantly.  
2. **Immutable Memtables (a.k.a. “flush buffers”)** – once the active memtable reaches a size limit, it is frozen and handed off to the background flusher.  
3. **Sorted String Tables (SSTables)** – persisted, immutable files on disk, organized into *levels* (L0, L1, …). Each level obeys size‑ratio rules (commonly 10×) to bound write amplification.

In a distributed deployment each node runs its own LSM instance, but the overall system must coordinate **replication**, **sharding**, and **global compaction scheduling**. The diagram below illustrates a typical setup:

```
+-------------------+          +-------------------+          +-------------------+
|  Client Requests |  -->     |  Node A (LSM)     |  <--->   |  Node B (LSM)     |
|  (write/read)     |          |  - Memtable       |          |  - Memtable       |
+-------------------+          |  - Immutable      |          |  - Immutable      |
                               |    Memtables      |          |    Memtables      |
                               |  - SSTable Levels |          |  - SSTable Levels |
                               +-------------------+          +-------------------+
```

### Data Flow in a Distributed LSM

1. **Write Path** – The client sends a mutation to a coordinator node. The coordinator forwards the request to the *primary* replica for the target partition. The primary places the record into its active memtable, assigns a monotonically increasing *sequence number*, and acknowledges the client once the write is persisted to the local *write‑ahead log* (WAL).  
2. **Replication** – Background threads stream the WAL entry to secondary replicas. Because the LSM write path is asynchronous, replication adds minimal latency.  
3. **Flush & Compaction** – When the memtable reaches `memtable_size` (e.g., 64 MiB) it is frozen. A *flusher* writes it as an L0 SSTable. Periodically, a *compactor* merges overlapping SSTables according to the chosen compaction strategy (size‑tiered, leveled, or hybrid). In a cluster, compaction can be *coordinated* across nodes to avoid hotspot I/O.

The **write‑ahead log** guarantees durability even if the process crashes before the memtable is flushed. The WAL is typically a simple append‑only file; tools like `fsync` or `O_DSYNC` ensure the data reaches the storage medium.

## Performance Characteristics

### Write Path Latency

Because writes only touch RAM and an append‑only WAL, per‑operation latency is usually **sub‑millisecond** even under heavy load. The dominant cost is the **fsync** call, which can be mitigated by:

| Technique                              | Effect on Latency | Trade‑off |
|----------------------------------------|-------------------|-----------|
| Batch `fsync` every *N* writes         | Reduces syscalls | Higher risk of loss on crash |
| Use `fdatasync` (skip metadata)        | Slightly faster  | May lose file‑size metadata |
| Deploy NVMe or Optane storage           | Near‑memory speeds| Higher hardware cost |

### Read Amplification

Reads must search every level that could contain the key. In a pure *leveled* design, the worst‑case read touches **one SSTable per level** (≈ log₁₀ N). In *size‑tiered* designs the number of levels is smaller, but each level may contain many overlapping files, increasing the **read amplification factor (RAF)**.

Real‑world numbers (derived from the ScyllaDB benchmark suite, see [ScyllaDB performance guide](https://www.scylladb.com/2021/09/01/scylla-performance-guide/)):

| Workload | LSM Style   | Avg. Read Latency (µs) |
|----------|-------------|------------------------|
| 95% writes, 5% reads | Size‑tiered (default) | 140 |
| 80% writes, 20% reads | Leveled (RocksDB)      | 95 |
| 50% writes, 50% reads | Hybrid (Tuned)         | 78 |

The table shows that **read‑heavy mixes benefit from leveled compaction**, while pure write workloads can afford the lower write amplification of size‑tiered compaction.

### Benchmarks Across Engines

| Engine   | Max Writes/sec (single node) | Typical Write Amplification | Compaction Overhead |
|----------|------------------------------|-----------------------------|---------------------|
| RocksDB  | ~1.5 M                        | 2–4×                        | CPU‑bound on SSDs   |
| Cassandra| ~800 k                       | 5–8× (size‑tiered)          | Network‑bound for replication |
| ScyllaDB | ~2.2 M                        | 1.5–2× (leveled)            | Parallel compaction pipelines |

ScyllaDB’s **shard‑per‑core** architecture allows compaction to run on every CPU core without locking, dramatically reducing pause times.

## Compaction Patterns

### Size‑Tiered vs. Leveled

| Property                | Size‑Tiered                              | Leveled                                   |
|-------------------------|------------------------------------------|-------------------------------------------|
| **Write Amplification** | Low (few merges)                         | Higher (every level rewritten)            |
| **Read Amplification**  | High (many overlapping SSTables)        | Low (single SSTable per level)           |
| **Space Overhead**      | Moderate (duplicate keys across tiers)   | Tight (≤ 10× total data size)            |
| **Best For**            | Pure write‑heavy, append‑only logs       | Mixed read/write workloads                |

In a distributed system you can **mix** strategies per table: hot tables (e.g., event logs) stay size‑tiered, while hot‑read tables (e.g., user profiles) switch to leveled.

### Parallel Compaction in Distributed Settings

ScyllaDB introduced **“Compaction Groups”**, a mechanism that groups SSTables by partition key range and schedules compaction on the node that owns the range. This yields two benefits:

1. **I/O locality** – only the disks that store the affected SSTables are exercised.  
2. **CPU parallelism** – each core can compact its own group without contention.

A simplified configuration snippet (YAML) for a ScyllaDB node:

```yaml
compaction:
  type: LeveledCompactionStrategy
  max_sstable_size_in_mb: 160
  enable_parallel_compaction: true
  max_thread_pool_size: 8
```

The `enable_parallel_compaction` flag toggles the multi‑threaded pipeline described in the ScyllaDB paper *“ScyllaDB: A Modern, High‑Performance NoSQL Database”* (see <https://www.scylladb.com/2020/06/15/scylla-db-whitepaper/>).

### Adaptive Thresholds

Static thresholds (e.g., “flush when memtable hits 64 MiB”) can cause **write stalls** under bursty traffic. Modern LSM engines expose **adaptive policies**:

- **Dynamic Memtable Sizing** – increase the target size when CPU and I/O headroom are available, shrink during contention.  
- **Write‑Rate Limiting** – throttle incoming writes based on current compaction backlog, a technique borrowed from Google’s Bigtable (see <https://research.google/pubs/pub38125/>).  

A sample `rocksdb` option set in C++:

```cpp
rocksdb::Options opts;
opts.write_buffer_size = 64 << 20;        // 64 MiB base
opts.max_write_buffer_number = 4;        // up to 4 concurrent memtables
opts.soft_pending_compaction_bytes_limit = 1ULL << 30; // 1 GiB
opts.hard_pending_compaction_bytes_limit = 2ULL << 30; // 2 GiB
```

When the *soft* limit is crossed, RocksDB begins throttling writes; crossing the *hard* limit triggers an automatic *pause* until compaction catches up.

## Patterns in Production

### Case Study: ScyllaDB at a Global Ad‑Tech Platform

- **Workload**: 1.8 B events per hour, 99.99% writes, sub‑10 ms read latency for real‑time bidding.  
- **Setup**: 12‑node cluster, each node with 2 × NVMe 2 TB, 64 vCPU cores.  
- **Tuning**:
  - Enabled **Leveled Compaction** for the “user profile” table (read‑heavy).  
  - Kept **Size‑Tiered** for the “event log” table.  
  - Configured **memtable size** to 128 MiB and **max\_write\_buffer\_number** to 6, allowing bursts up to ~750 MiB of in‑flight data.  
  - Deployed **Prometheus** alerts on `scylla_compaction_pending_tasks` to auto‑scale nodes when pending compactions > 200.

Result: Sustained **2.3 M writes/s** cluster‑wide with **average read latency 7 ms**, and no compaction‑induced stalls observed over a 30‑day window.

### Monitoring and Tuning

| Metric                     | Ideal Range (Leveled) | Ideal Range (Size‑Tiered) | Alert Threshold |
|----------------------------|-----------------------|---------------------------|------------------|
| `memtable_flushes_total`   | < 200/s               | < 400/s                   | > 500/s          |
| `compaction_pending_tasks` | ≤ 50 per node         | ≤ 150 per node            | > 200 per node   |
| `sstable_read_amplification`| ≤ 2.5                 | ≤ 5.0                     | > 6.0            |
| `disk_write_rate`          | ≤ 80 % of IOPS budget | ≤ 90 % of IOPS budget     | > 95 %           |

Prometheus query example for pending compactions:

```promql
sum by (instance) (scylla_compaction_pending_tasks) > 200
```

When the alert fires, operators can either **increase `max_background_compactions`** (if CPU is free) or **add a node** to spread the I/O load.

## Key Takeaways

- **Separate mutable and immutable layers**: Memtables give you sub‑millisecond writes; immutable SSTables keep the on‑disk layout stable for reads.  
- **Choose compaction strategy per workload**: Size‑tiered for pure write logs, leveled (or hybrid) for mixed read/write tables.  
- **Parallel and adaptive compaction** dramatically reduces pause times; enable it on modern SSD/NVMe hardware.  
- **Monitor write‑amplification, read‑amplification, and pending compaction queues** to catch back‑pressure before it impacts latency.  
- **Tune memtable size and flush thresholds dynamically** to survive traffic spikes without sacrificing durability.

## Further Reading

- [RocksDB Documentation – Compaction Styles](https://rocksdb.org/blog/2020/09/07/compaction.html)  
- [Apache Cassandra Architecture Overview](https://cassandra.apache.org/doc/latest/architecture.html)  
- [ScyllaDB – Whitepaper on Parallel Compaction](https://www.scylladb.com/2020/06/15/scylla-db-whitepaper/)  
- [Google Bigtable Paper (PDF)](https://research.google/pubs/pub38125/)  
- [LSM‑Tree Wikipedia Entry](https://en.wikipedia.org/wiki/Log-structured_merge-tree)