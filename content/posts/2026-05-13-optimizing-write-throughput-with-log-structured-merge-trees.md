---
title: "Optimizing Write Throughput with Log-Structured Merge Trees"
date: "2026-05-13T14:00:51.696"
draft: false
tags: ["LSM trees", "write throughput", "database performance", "storage engines", "key-value stores"]
description: "Learn how Log‑Structured Merge (LSM) trees boost write throughput, the trade‑offs of compaction, and practical tuning tips for RocksDB, LevelDB, and Cassandra."
summary: "A deep dive into LSM‑tree internals, compaction strategies, and configuration knobs that let you squeeze maximum write performance from modern storage engines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-optimizing-write-throughput-with-log-structured-merge-trees.svg"
  alt: "Illustration of a log‑structured merge tree with multiple levels"
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees achieve high write throughput by converting random writes into sequential appends and deferring work to background compactions. Properly sizing memtables, tuning compaction thresholds, and monitoring I/O pressure let you keep latency low while sustaining millions of writes per second.

Write‑intensive workloads have become the norm for modern services—from telemetry pipelines to real‑time analytics. Traditional B‑tree storage engines choke under that pressure because each insert triggers a costly random write to disk. Log‑Structured Merge (LSM) trees flip the script: they batch writes in memory, flush them sequentially, and later merge overlapping files in the background. The result is a storage engine that can sustain massive ingest rates while still offering acceptable read latency. This article unpacks the mechanics of LSM trees, explains why compaction is both a blessing and a bottleneck, and provides concrete tuning guidance for the most popular implementations: RocksDB, LevelDB, and Apache Cassandra.

## Foundations of LSM Trees

### What makes an LSM tree different?

At a high level an LSM tree consists of:

1. **MemTable** – an in‑memory sorted data structure (often a skip list). Writes are appended here in O(log N) time.
2. **Immutable MemTables (SSTables)** – when the MemTable fills, it is frozen and written to disk as a sorted string table (SSTable). This write is sequential, which modern SSDs handle extremely efficiently.
3. **Levels** – SSTables are organized into a hierarchy of levels (L0, L1, …). Each level has a size limit, typically a multiple of the previous level (e.g., 10× growth factor).

The key insight is that **writes never hit random disk locations**; they first land in RAM, then become part of a sequential file. The cost of random I/O is deferred to compaction, which runs in the background and can be throttled.

### The write path in practice

```python
# Pseudocode for a RocksDB write
def put(key, value):
    memtable.insert(key, value)               # O(log N) in‑memory insert
    if memtable.is_full():
        flush_memtable_to_sstable()           # Sequential write
        schedule_compaction()                 # Background merge
```

The `flush_memtable_to_sstable` step writes a new SSTable to Level 0. Because Level 0 files can overlap, reads must check multiple files, but this cost is amortized across the high write rate.

## Write Path Anatomy

### 1. MemTable sizing

The size of the MemTable directly influences how often flushes occur. A larger MemTable reduces flush frequency, but it also consumes more RAM and delays visibility of writes to readers that rely on immutable tables.

- **Rule of thumb**: allocate 10–20 % of your total heap to the MemTable (or up to 1 GiB on a 16 GiB instance) and monitor `memtable_flush_pending` metrics.
- **When to shrink**: if you see long GC pauses or OOM events, cut the size in half and observe the impact on latency.

### 2. Write‑Ahead Log (WAL)

Even though the MemTable holds the latest state, a write‑ahead log guarantees durability. The WAL is also sequential, so it adds negligible overhead. In RocksDB you can enable `wal_compression` to save space:

```bash
# Enable WAL compression in RocksDB
rocksdb-cli --set_option wal_compression true
```

### 3. Batching and async writes

Most client libraries allow you to batch multiple `put` operations into a single request. Batching reduces the number of system calls and improves CPU cache utilization.

```python
batch = db.write_batch()
for k, v in data_items:
    batch.put(k, v)
db.write(batch, sync=False)   # async write, WAL guarantees durability
```

## Compaction Strategies for Throughput

Compaction is the engine that keeps the LSM tree from exploding in size. It merges overlapping SSTables, discards deleted keys (tombstones), and re‑writes data into larger, non‑overlapping files. However, compaction consumes I/O bandwidth and CPU, which can throttle writes if not managed carefully.

### Types of compaction

| Strategy | When it runs | Typical impact |
|----------|--------------|----------------|
| **Level‑based** (used by RocksDB, LevelDB) | When a level exceeds its size limit | Predictable I/O, but can cause write spikes during large merges |
| **Size‑tiered** (used by Cassandra) | When a set of SSTables reaches a size threshold | Fewer large merges, smoother I/O but higher read amplification |
| **Universal** (used by some KV stores) | Continuously, based on write rate | Lowest write amplification, higher read amplification |

### Tuning compaction to protect write throughput

1. **Adjust the size ratio** – The default 10× growth factor can be increased to 20× or 30× on SSDs with abundant space, reducing the number of compaction rounds.
2. **Throttle I/O** – Most engines expose a `max_background_compactions` and `max_background_flushes` setting. On a machine with 8 CPU cores, a good starting point is:

   ```yaml
   max_background_compactions: 4
   max_background_flushes: 2
   ```

3. **Prioritize write‑heavy compactions** – RocksDB’s `compaction_pri` can be set to `min_overlapping_ratio` to favor merges that will free the most space quickly.

4. **Separate write and compaction disks** – If your hardware permits, mount the WAL and active SSTables on a fast NVMe device while relegating compaction output to a larger, slightly slower SSD. This isolates write latency from background merge activity.

### Real‑world example: Reducing write stalls in Cassandra

Cassandra’s default `compaction_throughput_mb_per_sec` is 16 MiB/s, which can be too aggressive for a busy ingest node. Raising it to 64 MiB/s often eliminates “write stall” warnings without saturating the disk:

```bash
nodetool setcompactionthroughput 64
```

After the change, the node’s `WriteLatency` metric dropped from 12 ms to 4 ms while maintaining a steady ingest rate of 1.2 M writes/second.

## Tuning Parameters in Popular Engines

### RocksDB

| Parameter | Description | Typical Value |
|-----------|-------------|---------------|
| `write_buffer_size` | Size of each MemTable | 64 MiB |
| `max_write_buffer_number` | Max concurrent MemTables before forcing flush | 3 |
| `target_file_size_base` | Target SSTable size for level 1 | 128 MiB |
| `level0_file_num_compaction_trigger` | Number of L0 files that trigger compaction | 4 |
| `compaction_style` | `kCompactionStyleLevel` (default) or `kCompactionStyleUniversal` | `kCompactionStyleLevel` |

**Sample configuration file (`rocksdb.conf`):**

```yaml
write_buffer_size: 67108864          # 64 MiB
max_write_buffer_number: 3
target_file_size_base: 134217728    # 128 MiB
level0_file_num_compaction_trigger: 4
max_background_compactions: 4
max_background_flushes: 2
```

### LevelDB

LevelDB is intentionally minimalist, but you can still tweak a few knobs:

- `write_buffer_size` (default 4 MiB) – increase to 64 MiB for heavy writes.
- `max_open_files` – set to 1000 to avoid file‑descriptor exhaustion during compaction.
- `disable_wal` – **only** for transient data where durability is not required.

```c
// C++ snippet configuring LevelDB
leveldb::Options opt;
opt.create_if_missing = true;
opt.write_buffer_size = 64 << 20;   // 64 MiB
opt.max_open_files = 1000;
opt.disable_wal = false;
```

### Apache Cassandra

Cassandra’s LSM implementation is size‑tiered by default. Key parameters:

- `memtable_total_space_in_mb` – total RAM allocated to memtables across all tables.
- `compaction_throughput_mb_per_sec` – limits background I/O.
- `sstable_size_in_mb` – target size of each SSTable (default 160 MiB).

```yaml
# cassandra.yaml excerpt
memtable_total_space_in_mb: 8192
compaction_throughput_mb_per_sec: 64
sstable_size_in_mb: 256
```

## Monitoring and Observability

Even the best‑tuned LSM tree can degrade if you lose sight of its health. The following metrics are universally available across engines:

| Metric | Meaning | Alert Threshold |
|--------|---------|-----------------|
| `memtable_flush_pending` | Number of MemTables waiting to be flushed | > 5 |
| `level0_file_count` | SSTables in L0 (overlap indicator) | > 12 |
| `compaction_pending_tasks` | Queued compactions | > 10 |
| `write_amp` (write amplification) | Ratio of bytes written to disk vs. bytes ingested | > 5× |
| `read_amp` (read amplification) | Avg. number of SSTables examined per read | > 3 |

Prometheus exporters exist for RocksDB (`rocksdb_exporter`), LevelDB (via custom exporter), and Cassandra (via `cassandra_exporter`). A simple Grafana dashboard can surface spikes in `level0_file_count` that often precede write stalls.

### Example alert rule (Prometheus)

```yaml
# Alert when L0 files exceed safe limit
- alert: LSMLevel0Overflow
  expr: rocksdb_level0_sstables > 12
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Level‑0 SSTable count is high"
    description: |
      The LSM tree has {{ $value }} Level‑0 files, which may cause write stalls.
      Consider increasing `level0_file_num_compaction_trigger` or checking disk I/O.
```

## Key Takeaways

- **Sequential writes**: LSM trees turn random writes into sequential disk appends, dramatically raising write throughput.
- **Compaction is the cost center**: Properly size MemTables, tune level size ratios, and throttle background merges to keep latency low.
- **Engine‑specific knobs matter**: RocksDB, LevelDB, and Cassandra each expose a small set of high‑impact settings; focus on `write_buffer_size`, `max_background_compactions`, and `compaction_throughput_mb_per_sec`.
- **Observability prevents surprises**: Track L0 file count, pending flushes, and amplification metrics; set alerts before stalls affect clients.
- **Hardware alignment**: Pair fast NVMe for active writes with a larger SSD for compaction output, and allocate sufficient RAM for MemTables to minimize flush frequency.

## Further Reading

- [RocksDB documentation – Compaction and Flush Options](https://github.com/facebook/rocksdb/wiki/Compaction-Options)
- [LevelDB source and design overview](https://github.com/google/leveldb)
- [Apache Cassandra Architecture Guide](https://cassandra.apache.org/doc/latest/architecture.html)