---
title: "Deep Dive into RocksDB Compaction Strategies: Leveled versus Tiered Architectures for Production Workloads"
date: "2026-05-24T19:00:39.847"
draft: false
tags: ["RocksDB","Compaction","Leveled","Tiered","Production"]
description: "Explore RocksDB's leveled and tiered compaction, compare trade‑offs, and get production‑ready patterns with benchmark insights for low‑latency services at scale."
summary: "A production‑focused comparison of RocksDB’s leveled and tiered compaction, with architecture diagrams, performance numbers, and deployment best practices."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-24-deep-dive-into-rocksdb-compaction-strategies-leveled-versus-tiered-architectures-for-production-workloads.svg"
  alt: "Diagram of RocksDB's LSM tree with leveled and tiered compaction zones."
  caption: ""
  relative: false
---

> **TL;DR** — Leveled compaction gives predictable read latency at the cost of higher write amplification, while tiered (FIFO) compaction excels for write‑heavy, append‑only workloads with looser latency guarantees. Pick the strategy that matches your latency SLAs, data churn, and storage budget, and tune the relevant RocksDB options accordingly.

RocksDB powers everything from real‑time analytics pipelines to high‑throughput caching layers. Its core strength lies in the Log‑Structured Merge (LSM) tree, but the way data moves between levels—*compaction*—determines latency, throughput, and storage efficiency in production. This post unpacks the two dominant compaction models—**Leveled** and **Tiered (FIFO)**—by walking through their architectures, trade‑offs, real‑world benchmarks, and concrete configuration patterns you can copy into your services today.

## Overview of RocksDB Storage Engine

RocksDB stores data as an ordered sequence of immutable **SST files** (Sorted String Tables). New writes are first buffered in a **memtable**; when it fills, the memtable is flushed to disk as an SST. Over time, many SSTs accumulate, and without compaction reads would have to scan across dozens of files, breaking latency guarantees.

### Key‑Value Model and LSM Tree Basics

* **Write Path** – `write → memtable → WAL → flush → SST`.  
* **Read Path** – `memtable → recent SSTs (by level) → Bloom filter → block cache`.  
* **Compaction** – merges overlapping SSTs into new ones, discarding deleted or overwritten keys.

The LSM design trades *write speed* for *read‑amplification* unless compaction keeps the number of overlapping files low. How RocksDB schedules those merges is the crux of today’s discussion.

## Compaction Fundamentals

Compaction is not a monolithic process; RocksDB runs multiple *background jobs* that respect a set of tunable thresholds (e.g., `max_background_compactions`). Compaction policies decide *when* and *what* to merge.

### Why Compaction Matters

| Metric | Impact of Poor Compaction |
|--------|---------------------------|
| **Read latency** | More SST files → more disk seeks, higher latency. |
| **Write amplification** | Re‑writing the same key many times → higher I/O, larger SSD wear. |
| **Space amplification** | Stale keys linger → wasted storage, higher costs. |
| **GC pauses** | Aggressive compaction can starve foreground threads. |

Choosing the right strategy keeps these metrics in the sweet spot for your SLA.

## Leveled Compaction Architecture

Leveled compaction (the default in RocksDB) enforces a **strict size ratio** between successive levels (typically 10:1). Each level holds *non‑overlapping* SSTs, guaranteeing at most one file per key range per level.

### Level Structure and Size Ratios

```
Level 0 (L0)   – 0–4 overlapping SSTs (from recent flushes)
Level 1 (L1)   – ~10 MiB total, non‑overlapping
Level 2 (L2)   – ~100 MiB total, non‑overlapping
Level N (LN)   – size = 10ⁿ × L1
```

* **L0** is special: because flushes can create overlapping files, RocksDB triggers a *minor compaction* when L0 exceeds a threshold (`level0_file_num_compaction_trigger`).  
* **Higher levels** are compacted *level‑by‑level*: L1 → L2, L2 → L3, etc. The target size for each level is controlled by `target_file_size_base` and `max_bytes_for_level_base`.

### Write Amplification and Read Patterns

Leveled compaction reduces **read amplification** dramatically. A point query typically touches **one file per level**, often just 1–2 due to Bloom filters. However, each key may be rewritten up to **log₁₀(TotalData/Level0Size)** times, inflating write amplification.

*Example*: 1 TiB of data, L0 size 64 MiB, level ratio 10 ⇒ write amplification ≈ 8 ×.

#### Code Sample: Tuning Leveled Compaction

```cpp
rocksdb::Options opts;
opts.create_if_missing = true;

// Leveled compaction specific options
opts.compaction_style = rocksdb::kCompactionStyleLevel;
opts.level0_file_num_compaction_trigger = 4;
opts.target_file_size_base = 64 * 1024 * 1024;   // 64 MiB
opts.max_bytes_for_level_base = 256 * 1024 * 1024; // 256 MiB
opts.max_background_compactions = 4;
opts.max_background_flushes = 2;

// Optional: reduce write amplification at the cost of space
opts.compaction_pri = rocksdb::kMinOverlappingRatio;
```

### When Leveled Is the Right Fit

* **Latency‑sensitive services** (e.g., request‑response APIs) where 99‑th percentile read latency must stay sub‑millisecond.  
* **Workloads with moderate write rates** and frequent point lookups.  
* **SSD‑backed clusters** where write amplification is tolerable but space is premium.

## Tiered (FIFO) Compaction Architecture

Tiered compaction, also called **FIFO** (First‑In‑First‑Out), groups SSTs into *tiers* without enforcing non‑overlap. New files are appended to the newest tier until it reaches a size limit, then a new tier is created. Old tiers are eventually *truncated* based on age or size, discarding the oldest data.

### Tier Design and Garbage Collection

```
Tier 0 (T0) – newest, up to 128 MiB
Tier 1 (T1) – next 128 MiB
...
Tier N (TN) – oldest, kept until TTL expires
```

* No merging across tiers by default; compaction happens only when a tier overflows (`max_bytes_for_tiered_compaction`).  
* Deletions are *not* rewritten; they are simply ignored when reading older tiers, which can increase **read amplification** but keep **write amplification** near 1×.

#### Code Sample: Enabling Tiered Compaction

```cpp
rocksdb::Options opts;
opts.create_if_missing = true;

// Tiered compaction specific options
opts.compaction_style = rocksdb::kCompactionStyleFIFO;
opts.level0_file_num_compaction_trigger = 0; // ignored for FIFO
opts.max_bytes_for_tiered_compaction = 256 * 1024 * 1024; // 256 MiB per tier
opts.ttl = 86400;               // 1‑day TTL for data expiration
opts.compaction_options_fifo.max_table_files_size = 256 * 1024 * 1024;
opts.max_background_compactions = 2;
```

### When Tiered Beats Leveled

* **Write‑heavy ingest pipelines** (e.g., log aggregation, telemetry) where the system writes > 100 k writes/s and can tolerate occasional read spikes.  
* **Append‑only datasets** where data is never updated, making the lack of overlap harmless.  
* **Cost‑sensitive storage**: minimal write amplification reduces SSD wear and extends hardware life.

## Patterns in Production

Both strategies have proven themselves at scale, but most real‑world deployments blend them or switch dynamically based on workload phases.

### Choosing the Right Strategy

| Workload | Desired SLA | Recommended Compaction |
|----------|-------------|------------------------|
| Real‑time key‑value service | ≤ 1 ms read latency, moderate writes | **Leveled** |
| Log collection (10 GB/s) | High ingest, eventual consistency reads | **Tiered** |
| Mixed OLTP + analytics | Variable read/write mix, need flexibility | **Hybrid** (Leveled for hot keys, Tiered for cold) |

**Decision checklist**

1. **Measure write rate** (writes / sec). > 50 k/s → consider Tiered.  
2. **Profile read latency distribution**. Tight 99‑pctile → Leveled.  
3. **Estimate key churn** (percentage of keys overwritten). High churn → Leveled to reclaim space.  
4. **Budget SSD endurance**. If wear is a concern, Tiered reduces write amplification.

### Hybrid Approaches

RocksDB allows **per‑column‑family** compaction settings. A common pattern:

* **CF = "hot"** – Leveled compaction for frequently accessed keys.  
* **CF = "cold"** – Tiered compaction for archival data.

```cpp
rocksdb::ColumnFamilyOptions hot_opts;
hot_opts.compaction_style = rocksdb::kCompactionStyleLevel;

rocksdb::ColumnFamilyOptions cold_opts;
cold_opts.compaction_style = rocksdb::kCompactionStyleFIFO;
cold_opts.ttl = 7 * 24 * 3600; // one week retention
```

This separation isolates the write amplification of hot data from the low‑cost ingest of cold data.

### Monitoring and Tuning

Production teams should instrument the following metrics (available via `rocksdb::DB::GetProperty` or Prometheus exporters):

* `rocksdb.num-files-at-level<N>` – Detect level pressure.  
* `rocksdb.compaction.pending` – Queue length indicates backlog.  
* `rocksdb.bytes-written` vs `rocksdb.bytes-read` – Compute write amplification.  
* `rocksdb.live-files-size` – Overall storage footprint.

Alert on:

* **L0 file count > 8** → imminent stall.  
* **Compaction pending > 2× background threads** → scale up `max_background_compactions`.  
* **Write amplification > 5×** → consider increasing `target_file_size_base` or switching to Tiered for a subset of data.

## Key Takeaways

- **Leveled compaction** offers predictable low read latency by keeping SSTs non‑overlapping, at the expense of higher write amplification (≈ 8× for typical size ratios).  
- **Tiered (FIFO) compaction** minimizes write amplification (≈ 1×) and is ideal for append‑only, high‑throughput pipelines, but read latency can suffer due to overlapping files.  
- Use **per‑column‑family** settings to run both strategies side‑by‑side, isolating hot and cold data paths.  
- Tune `target_file_size_base`, `max_bytes_for_tiered_compaction`, and `ttl` based on your latency SLAs and storage budget.  
- Continuously monitor level file counts, pending compactions, and write amplification to catch performance regressions early.

## Further Reading

- [RocksDB Documentation – Compaction Guide](https://github.com/facebook/rocksdb/wiki/Compaction-Guide)  
- [Facebook Engineering Blog – RocksDB in Production](https://engineering.fb.com/2020/02/04/data-infrastructure/rocksdb/)  
- [Baeldung – RocksDB Tutorial](https://www.baeldung.com/rocksdb)  