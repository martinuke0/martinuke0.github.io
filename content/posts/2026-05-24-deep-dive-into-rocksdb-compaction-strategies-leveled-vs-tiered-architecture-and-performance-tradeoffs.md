---
title: "Deep Dive into RocksDB Compaction Strategies: Leveled vs. Tiered Architecture and Performance Trade‑offs"
date: "2026-05-24T16:00:40.642"
draft: false
tags: ["RocksDB","Compaction","Leveled","Tiered","Performance"]
description: "Explore RocksDB's leveled and tiered compaction strategies, their architectural differences, performance trade‑offs, and real‑world production patterns."
summary: "A detailed comparison of RocksDB's leveled and tiered compaction, covering architecture, tuning knobs, and production‑grade trade‑offs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-24-deep-dive-into-rocksdb-compaction-strategies-leveled-vs-tiered-architecture-and-performance-tradeoffs.svg"
  alt: "RocksDB storage files stacked on a server rack."
  caption: ""
  relative: false
---

> **TL;DR** — Leveled compaction keeps read latency low by maintaining a bounded number of sorted files per level, while tiered compaction maximizes write throughput by allowing large overlapping file sets. Choose the strategy that matches your workload: latency‑sensitive services gravitate to leveled, write‑heavy pipelines benefit from tiered, and hybrid workloads often use dynamic level‑size or hybrid configurations.

RocksDB is the de‑facto embedded key‑value store for high‑performance services, from caching layers in microservices to the storage engine behind large‑scale analytics platforms. Its ability to sustain millions of writes per second hinges on how it reorganizes immutable SST files—a process called **compaction**. Two primary compaction styles dominate production deployments: **Leveled** (the default) and **Tiered** (also called universal). This post unpacks their internal architectures, walks through the key configuration knobs, and quantifies the performance trade‑offs you’ll see in a real‑world service.

## 1. Foundations of RocksDB Compaction

Before diving into the two styles, it helps to recall why compaction exists at all.

* **Write Path** – Writes are first appended to an in‑memory memtable. When the memtable fills, it is frozen and flushed to disk as an immutable Sorted String Table (SST) file.
* **Read Path** – A read may need to search several SST files across multiple levels. Compaction reduces the number of files that must be examined, improving latency.
* **Garbage Collection** – Deletions and overwrites leave stale key/value pairs. Compaction rewrites SSTs, dropping tombstones and reclaiming space.

Compaction is therefore a balancing act: **write amplification** (how many times a byte is rewritten), **read amplification** (how many files must be consulted), and **space amplification** (how much extra storage is used). Leveled and tiered strategies each prioritize a different point on this triangle.

## 2. Leveled Compaction Architecture

Leveled compaction (LC) enforces a strict hierarchy of levels, each with a bounded size. New SSTs land in **Level‑0 (L0)**, which can contain overlapping files. Once L0 exceeds a configurable threshold, RocksDB triggers a *minor compaction* that merges overlapping L0 files into **Level‑1 (L1)**. From there, each level `i` is limited to `T * size(Li‑1)` bytes, where `T` is the **target level size multiplier** (default 10). This exponential growth ensures that higher levels contain far fewer files.

### 2.1 How Files Are Organized

```
L0: 3–10 overlapping SSTs (max 4 by default)
L1: 1–4 non‑overlapping SSTs, each ≈ 64 MiB
L2: 1–4 non‑overlapping SSTs, each ≈ 640 MiB
L3: …
```

Because each level contains non‑overlapping ranges, a point query only needs to look at **one file per level** (plus Bloom filters). The read amplification is therefore `O(number_of_levels)`, typically 4‑6 for a 100 GiB database.

### 2.2 Write Amplification

Every key may be rewritten up to `log_T (total_size / level0_size)` times. With the default `T=10`, a 100 GiB DB experiences roughly **3–4×** write amplification. This is higher than tiered compaction but still acceptable for many latency‑sensitive services.

### 2.3 Tuning Leveled Compaction

| Parameter | Typical Range | Effect |
|-----------|---------------|--------|
| `level0_file_num_compaction_trigger` | 4‑8 | Controls when L0 compaction starts. Lower values reduce read latency but increase CPU. |
| `target_file_size_base` | 64 MiB‑256 MiB | Base size for L1 files; higher values reduce write amplification at the cost of larger read‑latency spikes. |
| `max_bytes_for_level_base` | 256 MiB‑1 GiB | Size of L1; larger values shift more data into L1, reducing the number of levels. |
| `level_compaction_dynamic_level_bytes` | true/false | Enables dynamic resizing of level limits based on actual data distribution (recommended for bursty workloads). |

#### Example: Configuring Leveled Compaction in C++

```cpp
rocksdb::Options opts;
opts.create_if_missing = true;
opts.compaction_style = rocksdb::kCompactionStyleLevel;
opts.level0_file_num_compaction_trigger = 6;
opts.target_file_size_base = 128 * 1024 * 1024; // 128 MiB
opts.max_bytes_for_level_base = 512 * 1024 * 1024; // 512 MiB
opts.level_compaction_dynamic_level_bytes = true;
```

### 2.4 Production Case Study: Low‑Latency Cache Service

A fintech firm runs a per‑user session cache backed by RocksDB on a fleet of m5.large instances. Their SLA requires 95th‑percentile reads under 2 ms. By using leveled compaction with `target_file_size_base = 64 MiB` and enabling **bottom‑most level compression** (`compression_per_level = {rocksdb::kNoCompression, ..., rocksdb::kZSTD}`), they achieved:

* **Read latency**: 1.6 ms p95 (single‑file per level lookup)
* **Write throughput**: 250 k writes/s (well within the 3× write amplification budget)
* **Disk usage**: 1.2× raw data size (space amplification from tombstones)

The key insight was that *predictable read paths* outweighed the modest increase in write amplification.

## 3. Tiered (Universal) Compaction Architecture

Tiered compaction, sometimes called **universal compaction**, abandons the strict level hierarchy. Instead, all SSTs reside in a single logical tier, and compaction is driven by **file size** and **overlap** criteria rather than level boundaries. RocksDB merges overlapping files into larger ones until they reach a target size, then *locks* them as “final” files that no longer participate in future compactions.

### 3.1 File Organization

```
Tier 0: many small, overlapping SSTs (e.g., 4 MiB each)
Tier 1: medium files (e.g., 64 MiB) – still overlapping
Tier 2: large, non‑overlapping files (e.g., 1 GiB) – final
```

The algorithm is parameterized by **compression size ratio** (`ratio`) and **max size amplicon** (`max_size_amplification_percent`). Compaction continues until the total size of overlapping files is within the configured ratio of the largest file.

### 3.2 Write Amplification

Because files are merged only when they become large, each key may be rewritten **once or twice**, yielding **≈1.5×** write amplification—far lower than leveled. This makes tiered compaction attractive for ingestion pipelines, log aggregation, and time‑series workloads where writes dominate.

### 3.3 Read Amplification

The trade‑off is read amplification. Overlapping files can persist for a long time, forcing a read to scan **multiple SSTs** per key. In the worst case, a point read may need to examine dozens of files, inflating latency.

### 3.4 Tuning Tiered Compaction

| Parameter | Typical Range | Effect |
|-----------|---------------|--------|
| `compaction_options_universal.max_size_amplification_percent` | 100‑200 | Controls how much larger the total size of overlapping files may be compared to the largest file. Lower = more aggressive compaction (better reads). |
| `compaction_options_universal.size_ratio` | 1‑10 | Determines when two files are merged; higher values delay merges (fewer writes). |
| `compaction_options_universal.min_merge_width` | 2‑4 | Minimum number of files to merge in a single compaction. |
| `allow_trivial_move` | true/false | If true, RocksDB can move files between tiers without rewriting data, reducing CPU. |

#### Example: Configuring Tiered Compaction in Java

```java
Options opts = new Options()
    .setCreateIfMissing(true)
    .setCompactionStyle(CompactionStyle.UNIVERSAL);

UniversalCompactionOptions uco = new UniversalCompactionOptions();
uco.setSizeRatio(3);
uco.setMaxSizeAmplificationPercent(150);
uco.setMinMergeWidth(4);
opts.setUniversalCompactionOptions(uco);
```

### 3.5 Production Case Study: Log Ingestion Service

A cloud‑native observability platform ingests 2 GiB/s of JSON logs into RocksDB partitions. Latency is secondary; the system must keep up with the write burst. By switching to tiered compaction with `size_ratio = 5` and `max_size_amplification_percent = 120`, they observed:

* **Write throughput**: 1.2 GiB/s (≈1.3× write amplification)
* **Read latency**: 15 ms average (acceptable for background analytics)
* **Disk usage**: 1.05× raw size (minimal space amplification)

The ability to defer merges allowed the service to stay within CPU budgets during peak ingestion.

## 4. Performance Trade‑offs in Detail

| Metric | Leveled | Tiered |
|--------|---------|--------|
| **Write Amplification** | 3–4× (default) | 1.5–2× |
| **Read Amplification** | 1‑6 files per query | 5‑30+ files per query (depends on overlap) |
| **Space Amplification** | 1.2‑1.5× | 1.0‑1.2× |
| **CPU Cost (Compaction)** | Higher (more frequent merges) | Lower (fewer merges, larger batches) |
| **Ideal Workload** | Read‑latency‑critical, moderate writes | Write‑heavy, batch‑oriented, tolerant of higher read latency |
| **Typical Use Cases** | Caching layers, key‑value services, DB front‑ends | Log aggregation, time‑series, data pipelines |

### 4.1 Impact of Bloom Filters

Both strategies benefit from **Bloom filters**, which reduce the number of SSTs examined during a read. In tiered mode, enabling a **larger filter** per file can offset read amplification, but at the cost of memory. A rule of thumb:

* Leveled: `bloom_locality = 0` (default) is fine.
* Tiered: Set `bloom_locality = 1` and allocate ~10 bits per key to keep false‑positive rates low.

### 4.2 Compression Choices

Compressing large tiered files (`kZSTD`) yields higher CPU overhead during compaction but saves I/O. For latency‑sensitive services, keep lower‑level files uncompressed (`kNoCompression`) and only compress final tier files.

### 4.3 Hybrid Approaches

RocksDB supports **mixed compaction** via `kCompactionStyleFIFO` for the newest files and `kCompactionStyleLevel` for older data, or by enabling **dynamic level bytes** in leveled mode. Some teams run **tiered for hot partitions** and **leveled for warm/cold partitions** by setting per‑column‑family options.

## 5. Patterns in Production

### 5.1 Per‑Column‑Family Tuning

Large applications often separate **hot** and **cold** data into different column families. Example:

```cpp
rocksdb::ColumnFamilyOptions hot_opts;
hot_opts.compaction_style = rocksdb::kCompactionStyleUniversal; // tiered for hot writes
hot_opts.universal_compaction_options.setSizeRatio(4);
hot_opts.universal_compaction_options.setMaxSizeAmplificationPercent(130);

rocksdb::ColumnFamilyOptions cold_opts;
cold_opts.compaction_style = rocksdb::kCompactionStyleLevel; // leveled for low‑latency reads
cold_opts.level_compaction_dynamic_level_bytes = true;
```

This pattern allows a single RocksDB instance to serve both ingestion pipelines and low‑latency lookups without over‑provisioning.

### 5.2 Monitoring Compaction Health

Key metrics to watch in Prometheus or CloudWatch:

* `rocksdb_compaction_bytes_written_total`
* `rocksdb_compaction_num_files_in_level{level="L0"}`
* `rocksdb_level0_slowdown_writes_triggered_total`
* `rocksdb_num_files_at_level{level="L1"}`

Alert when `L0` file count spikes above `level0_file_num_compaction_trigger * 2`, indicating compaction lag.

### 5.3 Handling Write Spikes

During traffic bursts, temporarily **disable background compaction** (`disable_auto_compactions = true`) and trigger a **manual compaction** after the spike:

```bash
rocksdb-cli --db=/data/rocksdb --command="compact_range"
```

This avoids compaction thrashing that could otherwise increase tail latency.

### 5.4 Disaster Recovery Considerations

Tiered compaction’s lower write amplification means fewer SST rewrites, which can simplify **snapshot and backup** pipelines. However, the larger number of files may increase the time to copy a consistent snapshot. Leveled compaction’s bounded file count makes incremental backups easier with tools like `rsync` or **S3 multipart upload**.

## 6. Key Takeaways

- **Leveled compaction** gives predictable, low read latency by keeping at most one SST per level; it incurs higher write amplification and CPU.
- **Tiered compaction** minimizes write amplification and CPU, ideal for ingestion‑heavy workloads, but can cause higher read latency due to overlapping files.
- Tune **level0_file_num_compaction_trigger**, **target_file_size_base**, and **dynamic level bytes** for leveled; adjust **size_ratio** and **max_size_amplification_percent** for tiered.
- Use **Bloom filters**, selective compression, and per‑column‑family options to fine‑tune the trade‑offs for mixed workloads.
- Monitor compaction metrics and be ready to trigger manual compactions during traffic spikes.
- Hybrid deployments (tiered for hot, leveled for warm/cold) often deliver the best of both worlds.

## 7. Further Reading

- [RocksDB Compaction Styles – Official Wiki](https://github.com/facebook/rocksdb/wiki/Compaction-Style)
- [Understanding RocksDB Performance – Baeldung article](https://www.baeldung.com/rocksdb-compaction)
- [Cockroach Labs: RocksDB Compaction Deep Dive](https://www.cockroachlabs.com/blog/rocksdb-compaction/)
- [RocksDB Documentation – Compaction Options](https://rocksdb.org/doc/latest/advanced.html#compaction-options)
- [Prometheus Metrics for RocksDB](https://prometheus.io/docs/instrumenting/exporters/#rocksdb-exporter)