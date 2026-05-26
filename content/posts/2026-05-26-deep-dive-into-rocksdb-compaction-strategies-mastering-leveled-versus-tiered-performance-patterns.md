---
title: "Deep Dive into RocksDB Compaction Strategies: Mastering Leveled versus Tiered Performance Patterns"
date: "2026-05-26T11:00:40.382"
draft: false
tags: ["RocksDB","Compaction","Leveled","Tiered","Performance"]
description: "Explore how RocksDB's leveled and tiered compaction strategies differ, their performance trade‑offs, tuning knobs, and real‑world patterns for production workloads."
summary: "An in‑depth look at RocksDB's compaction engines, with concrete guidance on when to choose leveled vs. tiered and how to tune them for latency‑critical services."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-26-deep-dive-into-rocksdb-compaction-strategies-mastering-leveled-versus-tiered-performance-patterns.svg"
  alt: "Close‑up of a server rack with a glowing SSD, symbolizing low‑latency storage."
  caption: ""
  relative: false
---

> **TL;DR** — Leveled compaction gives predictable read latency by keeping each level size‑bounded, while tiered compaction maximizes write throughput at the cost of larger read amplification. Choose leveled for latency‑sensitive workloads (e.g., user‑facing services) and tiered for ingestion‑heavy pipelines (e.g., log aggregation), then fine‑tune the relevant knobs—`target_file_size_base`, `max_bytes_for_level_base`, and `level0_file_num_compaction_trigger`—to hit your SLA.

RocksDB powers many high‑scale systems, from Facebook’s social graph to Kafka’s persistent log store. Its performance hinges on how it reorganizes immutable SST files on disk, a process called **compaction**. While the default “leveled” mode works well for many OLTP workloads, the “tiered” mode (also known as “universal”) shines when write volume overwhelms the system. This article dissects both strategies, walks through the internal data paths, and provides production‑ready tuning patterns you can apply today.

## 1. RocksDB Architecture Primer

Before diving into compaction, it helps to visualize the storage stack:

1. **MemTable** – an in‑memory sorted map (usually a skiplist) that receives writes.
2. **Write‑Ahead Log (WAL)** – an append‑only file ensuring durability.
3. **SSTables** – immutable, sorted string tables flushed from the MemTable.
4. **Levels / Tiers** – logical groupings of SSTables that dictate when and how files are merged.

When the MemTable fills, RocksDB writes a new SST file to **Level‑0**. From there, compaction policies decide when to merge files into deeper levels (or tiers) to reclaim space, eliminate duplicate keys, and keep read paths short.

### 1.1 Why Compaction Matters

- **Read Amplification** – the number of SST files a read must scan. Higher amplification means more disk I/O and higher latency.
- **Write Amplification** – the total amount of data rewritten during compactions. Excessive rewrite can saturate I/O and increase SSD wear.
- **Space Amplification** – temporary storage overhead while files are being merged.

Balancing these three amplifications is the essence of any compaction strategy.

## 2. Leveled Compaction (LC)

Leveled compaction organizes data into a series of *levels* (L0, L1, …, LN) where each level after L0 has a strict size bound, typically `10×` the size of the previous level. Files in a level never overlap; they cover disjoint key ranges. This property enables **point reads** to touch at most one file per level, yielding predictable latency.

### 2.1 How Leveled Works

1. **L0 Overlap** – L0 files can overlap arbitrarily. When the number of L0 files exceeds `level0_file_num_compaction_trigger` (default 4), RocksDB selects a subset and compacts them into L1.
2. **Size‑Bounded Levels** – L1 is limited to `max_bytes_for_level_base` (default 256 MiB). If L1 exceeds this, RocksDB picks overlapping L1 files and merges them with the selected L0 files into L2, respecting the size bound of L2 (`max_bytes_for_level_multiplier * max_bytes_for_level_base`).
3. **Compaction Trigger** – Each level has a *target file size* (`target_file_size_base` multiplied by the level index). When a level’s total size exceeds its bound, a compaction is scheduled.

The result is a **log‑structured merge tree (LSM)** where each key lives in at most one file per level, keeping read amplification close to `#levels + 1`.

### 2.2 Tuning Leveled for Low Latency

| Parameter | Typical Range | Effect |
|-----------|----------------|--------|
| `target_file_size_base` | 4 MiB – 64 MiB | Smaller files reduce write amplification but increase manifest overhead. |
| `max_bytes_for_level_base` | 64 MiB – 512 MiB | Shrinking this tightens level sizes, lowering read amplification at the cost of more frequent compactions. |
| `level0_file_num_compaction_trigger` | 2 – 8 | Lower values trigger earlier compactions, reducing L0 read spikes. |
| `soft_pending_compaction_bytes_limit` / `hard_pending_compaction_bytes_limit` | 1 GiB / 2 GiB (example) | Prevents background compaction backlog from exploding. |

**Example** – A micro‑service handling 10 k ops/s with 95th‑percentile read latency < 5 ms:

```yaml
target_file_size_base: 8MiB
max_bytes_for_level_base: 128MiB
level0_file_num_compaction_trigger: 3
soft_pending_compaction_bytes_limit: 1073741824   # 1 GiB
hard_pending_compaction_bytes_limit: 2147483648   # 2 GiB
```

These settings keep L1–L3 small enough that a point read touches ≤ 4 files, while the background compaction threads (usually 2–4) can keep up with the write rate.

### 2.3 Failure Modes to Watch

- **L0 Flood** – If write bursts exceed compaction throughput, L0 can accumulate > 100 files, causing read latency spikes. Mitigate by increasing `max_background_compactions` or lowering `level0_file_num_compaction_trigger`.
- **Write Stalls** – When the total pending compaction bytes hit the *hard limit*, RocksDB blocks writes. Adjust the limits or provision faster storage (e.g., NVMe) to avoid stalls.
- **Space Blow‑up** – Aggressive `target_file_size_base` with a small `max_bytes_for_level_base` can cause temporary space usage > 2× the data set during massive compactions.

## 3. Tiered (Universal) Compaction

Tiered compaction, also called **universal compaction**, abandons the strict size hierarchy. Instead, it groups SST files into *tiers* based on overlap and age. Files within a tier can overlap, and compaction merges a set of files into a larger tier when certain thresholds are met. This model is optimized for **write‑heavy** workloads because it reduces the number of times a key is rewritten.

### 3.1 How Tiered Works

1. **File Age Buckets** – New SSTs start in *Tier 0*. As they age (measured in number of compactions), they move to higher tiers.
2. **Size Ratio** – The `universal_compaction_size_ratio` (default 1) controls when files are merged: if the total size of newer files exceeds `size_ratio × size_of_older_tier`, a compaction is triggered.
3. **Overlap Threshold** – `universal_compaction_overlap_ratio` (default 0) determines how much key overlap is allowed before forcing a merge. Setting it > 0 can limit read amplification.
4. **Max Tiers** – `max_background_compactions` still caps parallel compaction threads, but tiered compaction often requires fewer because merges are larger and less frequent.

The net effect is **high write throughput** (often > 100 k ops/s on a single node) with **higher read amplification** because overlapping files must be consulted during reads.

### 3.2 Tuning Tiered for Ingestion Pipelines

| Parameter | Typical Range | Effect |
|-----------|----------------|--------|
| `universal_compaction_size_ratio` | 1 – 10 | Larger ratios delay merges, boosting write throughput but increasing read amplification. |
| `universal_compaction_overlap_ratio` | 0 – 1 | Raising this forces earlier merges of overlapping files, reducing read amplification at the cost of write performance. |
| `max_bytes_for_level_base` (unused) | N/A | Tiered ignores level size limits, simplifying configuration. |
| `allow_ingest_behind` | true/false | Enables *ingest‑behind* where external files are added without immediate compaction, useful for bulk loads. |

**Example** – A log‑aggregation service ingesting 200 MB/s:

```yaml
universal_compaction_size_ratio: 5
universal_compaction_overlap_ratio: 0.1
allow_ingest_behind: true
max_background_compactions: 2
```

Here, the system tolerates up to 5× size before merging, keeping the write path almost lock‑free, while a modest overlap ratio prevents reads from scanning more than ~2 files per key on average.

### 3.3 Failure Modes to Watch

- **Read Amplification Blow‑up** – With `universal_compaction_overlap_ratio = 0`, reads may need to scan dozens of overlapping SSTs. Monitor `rocksdb.estimate-num-keys` and `rocksdb.estimate-live-data-size` to detect.
- **Compaction Storm** – If `size_ratio` is too high and a sudden surge of small files arrives, the background compaction thread may become saturated, leading to a backlog. Reduce `size_ratio` or increase `max_background_compactions`.
- **Space Exhaustion** – Tiered compaction can temporarily allocate space equal to the sum of all pending files. Ensure the underlying volume has headroom (≥ 2× expected data size).

## 4. Patterns in Production

Real‑world systems rarely stick to a single compaction mode; they blend configurations to meet both latency and throughput goals.

### 4.1 Hybrid Approach: Leveled for Hot Keys, Tiered for Cold

- **Hot Partition** – Use a column family with `compaction_style: kCompactionStyleLevel` for user‑profile reads that demand < 2 ms latency.
- **Cold Partition** – Store event logs in a separate column family with `compaction_style: kCompactionStyleUniversal` to maximize ingestion speed.
- **Cross‑CF Queries** – RocksDB supports *multi‑CF* reads; keep the number of overlapping CFs low to avoid compounded read amplification.

```cpp
rocksdb::ColumnFamilyOptions hot_opts;
hot_opts.compaction_style = rocksdb::kCompactionStyleLevel;
hot_opts.target_file_size_base = 8 << 20; // 8 MiB

rocksdb::ColumnFamilyOptions cold_opts;
cold_opts.compaction_style = rocksdb::kCompactionStyleUniversal;
cold_opts.universal_compaction_size_ratio = 4;
```

### 4.2 Tiered as a Staging Layer

Many pipelines ingest raw events via **Kafka → RocksDB → Batch Export**. A common pattern:

1. **Ingest** – Write to a tiered column family with `allow_ingest_behind = true`. Bulk files (e.g., Parquet → SST) are added without immediate compaction.
2. **Compact on Schedule** – Trigger a manual `CompactRange` during off‑peak windows to merge overlapping files, reducing read amplification for downstream analytics.
3. **Archive** – After compaction, move the SST files to cold storage (e.g., GCS) using RocksDB’s `ExportColumnFamily` API.

```bash
# Trigger manual compaction for the "events" CF
rocksdb-cli --db_path=/data/rocksdb --cf=events compact_range "" ""
```

### 4.3 Monitoring Metrics

| Metric | Why It Matters | Typical Alert Threshold |
|--------|----------------|--------------------------|
| `rocksdb.num-files-at-level<N>` | Tracks file count per level; high L0 indicates compaction lag. | L0 > 50 |
| `rocksdb.compaction-pending` | Boolean flag showing pending compactions. | true for > 30 seconds |
| `rocksdb.estimate-pending-compaction-bytes` | Approximation of write‑amplification backlog. | > 2 GiB |
| `rocksdb.read-amplification` (derived) | Number of files a read must check. | > 8 for latency‑critical CFs |
| `rocksdb.write-stall` | Indicates RocksDB is throttling writes. | true for > 10 seconds |

Integrate these metrics into Prometheus and set alerts via Alertmanager. The **Grafana** dashboard shared by the RocksDB community (see the official repo) visualizes these metrics nicely.

## 5. Architecture Considerations

When choosing a compaction strategy, think beyond the DB settings and ask:

1. **Hardware Profile** – NVMe SSDs with high IOPS favor tiered compaction (writes dominate); SATA drives with limited IOPS benefit from leveled compaction to keep read paths short.
2. **Workload Mix** – A 70/30 read/write split usually leans to leveled; > 80% writes pushes you toward tiered.
3. **SLA Priorities** – If 99.9th‑percentile latency is a hard contract, enforce tight `max_bytes_for_level_base` and allocate extra compaction threads.
4. **Multi‑Tenant Isolation** – Use separate column families per tenant, each with its own compaction style, to avoid noisy neighbor effects.

### 5.1 Example Deployment Diagram

```
+-------------------+        +-------------------+        +-------------------+
|  Front‑End API    |  -->   |  RocksDB Instance |  -->   |  Analytics Cluster|
| (Node.js/Go)      |        | (Leveled CF: Users|        | (Batch Export)    |
|                   |        |  Tiered CF: Logs) |        |                   |
+-------------------+        +-------------------+        +-------------------+
          |                           |                         |
          |  Write Path (WAL+Mem)     |  Compaction Threads     |
          +---------------------------+--------------------------+
```

The diagram highlights that **read‑heavy API traffic** hits the leveled column family, while **write‑heavy log streams** funnel into the tiered column family.

## 6. Key Takeaways

- Leveled compaction offers predictable read latency by bounding each level’s size; ideal for user‑facing services.
- Tiered (universal) compaction maximizes write throughput and is suited for ingestion pipelines or bulk data loads.
- Tune `target_file_size_base`, `max_bytes_for_level_base`, and `level0_file_num_compaction_trigger` for low‑latency scenarios; adjust `universal_compaction_size_ratio` and `universal_compaction_overlap_ratio` for high‑throughput pipelines.
- Monitor L0 file count, pending compaction bytes, and read‑amplification metrics to catch compaction stalls early.
- Consider a hybrid column‑family layout: hot data in leveled, cold data in tiered, and use manual compaction windows for batch cleanup.

## 7. Further Reading

- [RocksDB Compaction Guide (official docs)](https://github.com/facebook/rocksdb/wiki/Compaction)
- [Facebook Engineering: Scaling RocksDB for billions of keys](https://engineering.fb.com/2020/06/23/data-infrastructure/rocksdb-at-facebook/)
- [Apache Kafka’s use of RocksDB for the Streams state store](https://kafka.apache.org/documentation/#streamsstate)