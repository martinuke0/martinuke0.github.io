---
title: "Deep Dive into RocksDB Compaction Strategies: Leveled versus Tiered Architectures for Production Workloads"
date: "2026-06-01T00:00:47.179"
draft: false
tags: ["RocksDB","Compaction","Leveled","Tiered","Production"]
description: "Explore RocksDB's leveled and tiered compaction strategies, their trade‑offs, architecture patterns, and tuning tips for high‑scale production workloads."
summary: "A practical comparison of RocksDB’s leveled and tiered compaction, with architecture diagrams, performance numbers, and actionable tuning guidelines for production systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-06-01-deep-dive-into-rocksdb-compaction-strategies-leveled-versus-tiered-architectures-for-production-workloads.svg"
  alt: "Diagram comparing RocksDB leveled and tiered compaction layers."
  caption: ""
  relative: false
---

> **TL;DR** — Leveled compaction gives predictable read latency at the cost of higher write amplification, while tiered compaction maximizes write throughput and reduces write amplification but can increase read latency. Choose the strategy that matches your SLA: latency‑critical services lean on leveled, ingestion‑heavy pipelines benefit from tiered, and hybrid workloads often combine both with per‑column‑family tuning.

RocksDB powers everything from social‑media timelines to IoT ingest pipelines, and its performance hinges on how it reorganizes data on‑disk. The two dominant compaction strategies—**Leveled** and **Tiered**—are not interchangeable knobs; they embody fundamentally different trade‑offs in write amplification, read amplification, space amplification, and operational complexity. This post unpacks the internal mechanics, walks through real‑world architecture patterns, and hands you concrete configuration snippets you can drop into a production deployment today.

## RocksDB Compaction Primer

RocksDB stores data as a Log‑Structured Merge‑Tree (LSM‑tree). Writes are first appended to an in‑memory memtable, flushed to immutable SST files, and later merged (compacted) into larger files. Compaction is the engine that keeps read performance acceptable and reclaims space.

### LSM‑Tree Basics

| Phase | What Happens | Typical Disk I/O |
|-------|--------------|------------------|
| **Write** | Memtable → WAL → SST (Level‑0) | Sequential append |
| **Flush** | Memtable → immutable SST (L0) | Small sequential write |
| **Compaction** | Merge overlapping SSTs → new SST(s) at higher level | Random read + sequential write |

Key metrics:

* **Write Amplification (WA)** – total bytes written to SSD per byte of user data.
* **Read Amplification (RA)** – number of SST files examined per key lookup.
* **Space Amplification (SA)** – total on‑disk size vs. logical data size.

The compaction strategy determines how these metrics evolve as the dataset grows.

## Leveled Compaction Architecture

Leveled compaction (the default in RocksDB) enforces a strict hierarchy of levels where each level holds SST files of bounded total size (typically 10× the size of the previous level). Overlaps are eliminated above Level‑0, guaranteeing at most one SST per key per level.

### How Levels Work

```
Level‑0   : 0‑N overlapping SSTs (newly flushed)
Level‑1   : ≤ 10 MiB, non‑overlapping
Level‑2   : ≤ 100 MiB, non‑overlapping
Level‑3   : ≤ 1 GiB, non‑overlapping
...
```

When the size of a level exceeds its target, RocksDB selects a **compaction candidate**—usually the oldest SST in that level—and merges it with overlapping SSTs from the next level, producing a new SST that resides in the higher level. This “push‑down” continues until the topmost level fits its budget.

### Pros and Cons

**Pros**

* Predictable **read amplification**: a point read touches at most `L+1` files (L = max level). In practice, 2‑3 files for most workloads.
* Stable **space amplification**: bounded by the level size factor (≈ 1.2× for default factor 10).
* Good for **random‑read‑heavy** workloads (e.g., key‑value caches, serving layers).

**Cons**

* Higher **write amplification**: each key may be rewritten many times as it traverses levels (often 5‑10×).
* More CPU overhead due to frequent overlapping merges.
* Sensitive to **hotspot** keys that trigger repeated compactions.

### Production Patterns

1. **Serving KV Cache** – Services that must answer queries within a few milliseconds (e.g., user‑profile lookups). Leveled compaction keeps read latency low even under heavy read traffic.
2. **Time‑Series with Fixed Retention** – When older data is periodically expired, the predictable size of each level simplifies disk‑space planning.
3. **Hybrid Column Families** – Use a *default* column family with leveled compaction for read‑heavy tables, while assigning *ingest* column families a tiered policy (see next section).

#### Sample Configuration (YAML)

```yaml
default:
  compression: "lz4"
  compaction_style: "kCompactionStyleLevel"
  target_file_size_base: 64MiB
  max_bytes_for_level_base: 256MiB
  level0_file_num_compaction_trigger: 4
  level0_slowdown_writes_trigger: 20
  level0_stop_writes_trigger: 36
```

## Tiered Compaction Architecture

Tiered compaction (also called **Universal** compaction) relaxes the strict level size limits. Instead of a fixed hierarchy, it groups SST files into *tiers* based on size, allowing many overlapping files within a tier. When a tier grows beyond a configurable threshold, the oldest files are merged into a larger tier.

### How Tiers Work

```
Tier‑0 (Level‑0) : 0‑N overlapping SSTs (flushes)
Tier‑1          : up to 4 GiB, may overlap
Tier‑2          : up to 16 GiB, may overlap
Tier‑3          : up to 64 GiB, may overlap
...
```

Compaction is driven by **size ratio** and **min_merge_width** parameters. The algorithm prefers to merge many small files into a single larger one, dramatically reducing **write amplification**.

### Pros and Cons

**Pros**

* Low **write amplification**: each key is typically rewritten only once or twice.
* Excellent for **write‑heavy ingestion pipelines** (e.g., log aggregation, event streaming).
* Simpler space management; fewer files to track.

**Cons**

* Higher **read amplification**: a point read may scan many overlapping SSTs in the same tier (often 5‑10 files).
* Potential for **space amplification** if stale keys linger across tiers; requires periodic **TTL** or **delete‑range** compactions.
* Less predictable latency spikes during large tier merges.

### Production Patterns

1. **Log Ingestion / Kafka Mirror** – Systems that ingest millions of records per second and tolerate occasional read latency spikes.
2. **Batch Analytics Staging** – Data that is written once, read many times only during a downstream batch job.
3. **Cold Storage** – Historical data that is rarely accessed; tiered compaction minimizes wear on SSDs.

#### Sample Configuration (YAML)

```yaml
ingest:
  compression: "zstd"
  compaction_style: "kCompactionStyleUniversal"
  max_size_amplification_percent: 200
  size_ratio: 1
  min_merge_width: 2
  stop_write_trigger: 1000
```

## Choosing the Right Strategy for Your Workload

Both strategies can coexist within a single RocksDB instance by assigning different **column families**. The decision matrix below helps you match SLA requirements to compaction style.

| Requirement | Recommended Compaction | Typical Settings |
|-------------|------------------------|------------------|
| **< 5 ms read latency** for 99 % of requests | Leveled | `target_file_size_base: 64MiB`, `max_bytes_for_level_base: 256MiB` |
| **> 10 GB/s sustained ingest** | Tiered | `size_ratio: 1`, `max_size_amplification_percent: 200` |
| **Mixed read/write** (50 / 50) | Hybrid (per‑CF) | Leveled for hot CF, Tiered for warm CF |
| **Limited SSD write cycles** | Tiered (lower WA) | Enable `bottommost_level_compaction: kCompactionStyleUniversal` |
| **Strict storage budget** | Leveled (predictable SA) | Keep `level_multiplier` at default 10 |

### Hybrid Deployment Example

```cpp
rocksdb::Options opts;
opts.create_if_missing = true;

// Hot read‑heavy column family
rocksdb::ColumnFamilyOptions hot_cf_opts;
hot_cf_opts.compaction_style = rocksdb::kCompactionStyleLevel;
hot_cf_opts.target_file_size_base = 64 * 1024 * 1024;

// Warm ingest column family
rocksdb::ColumnFamilyOptions warm_cf_opts;
warm_cf_opts.compaction_style = rocksdb::kCompactionStyleUniversal;
warm_cf_opts.size_ratio = 1;
warm_cf_opts.max_size_amplification_percent = 200;

// Open DB with two CFs
std::vector<rocksdb::ColumnFamilyDescriptor> cf_desc = {
    {"default", hot_cf_opts},
    {"ingest", warm_cf_opts}
};
std::vector<rocksdb::ColumnFamilyHandle*> handles;
rocksdb::DB* db;
rocksdb::Status s = rocksdb::DB::Open(opts, "/data/rocksdb", cf_desc, &handles, &db);
```

In this pattern, latency‑critical queries hit the `default` CF with leveled compaction, while bulk writes stream into the `ingest` CF that uses tiered compaction. Periodic **compaction jobs** can later migrate data from `ingest` to `default` once it becomes hot.

## Patterns in Production

### 1. Multi‑Tenant SaaS Platforms

A SaaS provider often stores tenant metadata (read‑heavy) alongside event logs (write‑heavy). By defining a **tenant_meta** column family with leveled compaction and an **event_log** column family with tiered compaction, the system isolates latency spikes to the log tier while keeping tenant lookups sub‑millisecond.

### 2. Geo‑Distributed Edge Caches

Edge nodes receive a continuous stream of configuration updates. Tiered compaction reduces SSD wear, and a periodic **foreground compaction** (triggered via `rocksdb::DB::CompactRange`) consolidates the most recent configs into a single SST, enabling fast reads for the next interval.

### 3. Automated Compaction Tuning

Production teams often employ **Prometheus** alerts on metrics like `rocksdb_write_amplification_total` and `rocksdb_num_files_at_level`. When WA crosses a threshold (e.g., 8×), an automated script can switch a column family from tiered to leveled or adjust `size_ratio`. Example Bash snippet:

```bash
#!/usr/bin/env bash
CF="ingest"
WA=$(curl -s http://localhost:9100/metrics | grep rocksdb_write_amplification_total{cf="$CF"} | awk '{print $2}')
if (( $(echo "$WA > 8.0" | bc -l) )); then
  echo "High WA detected ($WA), switching $CF to leveled..."
  curl -X POST http://localhost:8080/rocksdb/tune -d '{"cf":"'"$CF"'","compaction_style":"level"}'
fi
```

## Key Takeaways

- **Leveled compaction** offers low read amplification and predictable space usage, ideal for latency‑critical services.
- **Tiered compaction** minimizes write amplification and SSD wear, making it the go‑to for high‑throughput ingestion pipelines.
- Use **column families** to apply different compaction styles within the same RocksDB instance, enabling hybrid workloads.
- Monitor **write/read amplification** and adjust `target_file_size_base`, `size_ratio`, and `max_size_amplification_percent` to keep SLAs in check.
- Automate compaction tuning with metric‑driven scripts to react to workload shifts without manual intervention.

## Further Reading

- [RocksDB documentation – Compaction styles](https://github.com/facebook/rocksdb/wiki/Compaction-Style)
- [Facebook Engineering blog – Scaling RocksDB for billions of keys](https://engineering.fb.com/2020/10/15/data-infrastructure/scaling-rocksdb/)
- [Apache Kafka Streams – Integrating RocksDB as a state store](https://kafka.apache.org/documentation/streams/developer-guide/state-store)