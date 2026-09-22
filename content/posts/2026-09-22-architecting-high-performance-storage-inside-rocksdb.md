---
title: "Architecting High-Performance Storage: Inside RocksDB's LSM-Tree Compaction Strategy"
date: "2026-09-22T03:00:27.936"
draft: false
tags: ["RocksDB", "LSM-Tree", "Storage Engine", "Compaction", "Database Architecture", "Performance Engineering"]
description: "A deep dive into RocksDB's LSM-tree compaction strategies — leveled, universal, and FIFO — examining the tradeoffs between write amplification, read amplification, and space amplification in production systems."
summary: "Explore how RocksDB's LSM-tree compaction strategy manages write-heavy workloads by buffering mutations in memory and flushing sorted runs to disk, then merging them through configurable compaction paths with distinct amplification tradeoffs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-22-architecting-high-performance-storage-inside-rocksdb.svg"
  alt: "RocksDB LSM-tree compaction diagram showing levels and data flow between SST files"
  caption: "Visualization of RocksDB's multi-level LSM-tree architecture with compaction pipelines"
  relative: false
---

> **TL;DR** — RocksDB achieves high write throughput by buffering writes in an in-memory memtable, flushing immutable sorted runs (SST files) to disk, and asynchronously merging them through configurable compaction strategies. Choosing between leveled, universal, and FIFO compaction involves navigating fundamental tradeoffs among write amplification, read amplification, and space amplification — and the wrong choice can cripple a production system under load.

## Why LSM-Trees Beat B-Trees for Write-Heavy Workloads

Traditional B-tree storage engines suffer from a structural weakness: every random insert requires an in-place update to a balanced tree node, often triggering page splits and write-ahead log flushes. Under heavy write loads — think tens of thousands of inserts per second — the random I/O pattern becomes the bottleneck.

The Log-Structured Merge-Tree (LSM-tree) sidesteps this entirely. Instead of modifying existing data on disk, all writes are appended sequentially. The engine maintains a small, in-memory sorted structure called a **memtable**. When the memtable fills, it becomes immutable and is flushed to disk as an immutable sorted run (stored as an SST file). Over time, these sorted runs accumulate and must be merged — a process called **compaction**.

RocksDB, the embedded key-value store forked from Google's LevelDB and now maintained by Meta, Facebook, and the broader open-source community, implements this LSM-tree model with remarkable sophistication. It powers the default storage engine in Apache Cassandra, TiDB, MyRocks (MySQL), and numerous other production systems handling petabytes of data.

The fundamental insight is this: by deferring and batching disk writes, LSM-trees convert random writes into sequential ones, dramatically improving throughput on SSDs and even spinning disks. The cost? Compaction introduces background I/O that competes with foreground reads and writes, and the multi-level hierarchy creates complex tradeoffs that demand careful tuning.

## The Internal Architecture: Memtable, Immutable Layer, and SST Files

Before examining compaction, it helps to understand the full write pipeline in RocksDB.

When an application issues a `Put`, `Delete`, or `Merge` operation, RocksDB does not touch disk immediately. The write is appended to an in-memory **memtable**, which is typically implemented as a skip list (configurable to use a vector-based memtable for small workloads). Writes are also recorded in a **Write-Ahead Log (WAL)** for crash recovery.

```cpp
// Simplified write path in RocksDB
Status DB::Put(const WriteOptions& options, ColumnFamilyHandle* column_family,
               const Slice& key, const Slice& value) {
  WriteBatch batch(key, value);
  WriteToWAL(batch);          // Durability guarantee
  InsertIntoMemtable(batch);  // In-memory sorted structure
  return Status::OK();
}
```

Once the memtable reaches its configured size (default 64 MB), it becomes **immutable**. A background thread flushes it to disk, creating a new **Level 0** SST file. Each SST file contains sorted key-value pairs, optionally compressed (default: LZ4 or ZSTD), and includes an index and bloom filter for efficient point lookups.

At this point, the system may have multiple Level 0 SST files with overlapping key ranges. Unlike a balanced tree, these files are not globally sorted — Level 0 is special because its files can overlap. All subsequent levels (Level 1, Level 2, and so on) contain non-overlapping key ranges, which is what enables efficient binary searches during reads.

This is where compaction enters the picture.

## Compaction: The Engine of LSM-Tree Maintenance

Compaction is the background process that selects SST files, merges their sorted contents, removes overwritten or deleted keys (via sequence number comparison), and writes the result back to a lower level. Without compaction, read performance would degrade catastrophically as the number of overlapping files grows.

RocksDB exposes several compaction strategies, each optimizing for different workload patterns. The choice fundamentally shapes the amplification profile of the system.

### Leveled Compaction (Default)

Leveled compaction is the default strategy in RocksDB and mirrors the architecture described in Google's LevelDB paper. The LSM-tree is organized into multiple levels, each with exponentially increasing size targets:

| Level | Size Ratio | Target Size |
|-------|-----------|-------------|
| L0    | —         | Configurable (triggered by file count) |
| L1    | 10x       | 64 MB (default) |
| L2    | 10x       | 640 MB |
| L3    | 10x       | 6.4 GB |
| ...   | ...       | ... |

The compaction process works as follows: RocksDB selects a file from Level 0 whose key range overlaps with files in Level 1, merges them, and produces a new set of files for Level 1. Any data that spills beyond Level 1's size boundary cascades down to Level 2, and so on.

```
Compaction Input:  L0 file [a-f] + L1 files [a-d], [c-h]
Compaction Output: New L1 files [a-d], [d-f], [f-h]
Cascade:           [f-h] may trigger L1→L2 compaction
```

**Key properties of leveled compaction:**

- **Read amplification is low.** A point lookup requires at most one file check per level (plus bloom filters), typically resulting in O(log_levels) file probes.
- **Write amplification is high.** Each byte of data written to Level L eventually gets rewritten through all subsequent levels. The theoretical write amplification is approximately `O(N)` where N is the number of levels, with a constant factor of roughly 10x per level transition.
- **Space amplification is moderate.** Because data is consolidated at each level, stale data is reclaimed relatively quickly.

Leveled compaction excels in read-heavy or balanced workloads where low-latency point lookups are critical. The cost is sustained background I/O that can starve foreground operations if not properly rate-limited.

### Universal Compaction

Universal compaction takes a fundamentally different approach: it merges all SST files within the same level into a single sorted run before moving to the next level. There is no exponential size ratio between levels — instead, the system maintains a single growing level until a file count threshold triggers compaction.

```
Universal compaction:
  Files: [a-c], [b-d], [e-g], [f-h] → Merge all → [a-h]
  Result: Single SST file covering the entire key range
```

**Key properties:**

- **Write amplification is significantly lower** than leveled compaction — often by a factor of 2–5x — because data does not cascade through multiple levels.
- **Read amplification is higher** because a single level may contain many overlapping files, and a point lookup must check multiple SST files (though bloom filters mitigate this).
- **Space amplification is lower** since there is less redundant data across levels.

Universal compaction is well-suited for write-once, read-rarely workloads, such as time-series data ingestion or log aggregation. It also performs well on SSDs where random read overhead is minimal.

### FIFO Compaction

FIFO compaction is the simplest strategy: new data is appended to a single level, and when the level exceeds a configured size threshold, the oldest files are dropped (evicted) to make room. There is no merging or sorting across files.

```
FIFO compaction:
  Level: [file1] [file2] [file3] ... [fileN]
  When size > max_size → Evict file1
```

**Key properties:**

- **Zero compaction overhead** — no merging, no sorting, no background CPU cost.
- **Read amplification is maximal** — every file must be scanned for a point lookup unless bloom filters are configured per-file.
- **Data is not guaranteed to persist** — the oldest data is discarded, making FIFO suitable only for caching or TTL-based workloads.

FIFO compaction is appropriate for scenarios where data has a natural expiration, such as caching layers, session stores, or metrics retention windows.

## Tuning Compaction for Production: The Amplification Triangle

Every compaction strategy navigates a fundamental tension between three forms of amplification:

1. **Write Amplification (WA):** The total bytes written to disk per byte of user data. Leveled compaction can reach 10–67x WA depending on the number of levels. Universal compaction typically stays below 5x.
2. **Read Amplification (RA):** The number of SST files checked per read operation. Leveled compaction achieves RA of O(log_levels) ≈ 3–7. Universal compaction can reach O(files_in_level) ≈ 10–100+.
3. **Space Amplification (SA):** The ratio of total disk space used to actual user data size. Leveled compaction typically runs at 10–20% overhead. Universal compaction can be lower but depends on file overlap.

RocksDB exposes dozens of configuration parameters that let you tune this triangle. The most impactful include:

```ini
# Leveled compaction tuning
level0_file_num_compaction_trigger = 4    # Files in L0 that trigger compaction
level0_slowdown_writes_trigger = 20       # Writes slow down at this L0 file count
level0_stop_writes_trigger = 36           # Writes stop at this L0 file count
target_file_size_base = 64MB              # Base size for L1 SST files
max_bytes_for_level_base = 256MB          # Target size for L1
max_bytes_for_level_multiplier = 10       # Size ratio between levels

# Universal compaction tuning
compression = zstd                        # Compression for SST files
min_write_buffer_number_to_merge = 4      # Memtables merged before flush
compression_options = {level0, zstd, 3}
```

**Critical production insight:** The `level0_slowdown_writes_trigger` and `level0_stop_writes_trigger` parameters are often the difference between a smoothly operating system and a stalled one. When Level 0 accumulates too many overlapping files, RocksDB throttles or halts writes to prevent read latency from exploding. Monitoring these triggers in production — via RocksDB's `rocksdb.num-files-at-level` and `rocksdb.compaction-pending` metrics — is essential.

## Compaction in Practice: Patterns and Pitfalls

### The Space Amp Trap with Large Values

When SST files contain large values (hundreds of KB or MB), the space amplification of leveled compaction becomes painful. During compaction, both the input and output files exist simultaneously on disk, temporarily doubling storage requirements. For a database with 1TB of user data and 100KB average values, a single compaction cycle can spike disk usage by 200–300GB.

**Mitigation strategies include:**

- Setting `max_write_buffer_number` to limit the number of concurrent memtables, reducing the flush-to-disk burst.
- Enabling `compaction_readahead_size` to improve sequential read throughput during compaction.
- Using `bypass_locks` and `parallelize` compaction options to overlap compaction I/O with foreground writes.

### Tiered Compaction: A Modern Alternative

RocksDB also supports **Tiered Compaction** (inspired by Apache Cassandra's size-tiered approach), which groups similarly-sized SST files and merges them in pairs. This strategy achieves low write amplification similar to universal compaction while maintaining better read characteristics through tiered organization.

```
Tiered compaction:
  Tier 1: [a-c] [b-d] → Merge → [a-d]
  Tier 2: [e-g] [f-h] → Merge → [e-h]
  Tier 1+2: [a-d] [e-h] → Merge → [a-h]
```

Tiered compaction is particularly effective for workloads with periodic bulk inserts followed by long idle periods, as it minimizes compaction activity during quiet phases.

### Monitoring and Observability

Production RocksDB deployments require visibility into compaction health. Key metrics to track include:

- `compaction-pending` — Number of compactions queued. Sustained non-zero values indicate the system is falling behind.
- `bytes-written` / `bytes-read` during compaction — Helps identify whether compaction is I/O-bound or CPU-bound.
- `num-running-compactions` — Concurrency level. If this consistently exceeds `max_background_compactions`, you need to increase the limit.
- `stall-micros` — Time spent in write stall conditions. Non-zero values signal that compaction cannot keep pace with writes.

```bash
# Example: Querying RocksDB stats via HTTP endpoint
curl http://localhost:9090/rocksdb_stats | grep -E "compaction|stall|level"
```

## Choosing the Right Strategy

The right compaction strategy depends on your workload profile:

| Workload Pattern | Recommended Strategy | Rationale |
|-----------------|---------------------|-----------|
| Read-heavy, low-latency queries | Leveled | Minimizes read amplification |
| Write-heavy, append-only | Universal | Minimizes write amplification |
| Caching, TTL-based | FIFO | Zero compaction overhead |
| Mixed, unpredictable | Tiered | Balanced amplification profile |
| Write bursts with idle recovery | Universal with rate limiting | Handles spikes gracefully |

There is no universally optimal choice. A financial trading platform serving microsecond-latency reads will favor leveled compaction. A telemetry pipeline ingesting millions of events per second will prefer universal or tiered. The art of RocksDB architecture lies in understanding your workload's read/write ratio, value size distribution, and latency SLOs, then configuring compaction to match.

## Key Takeaways

- **LSM-trees convert random writes to sequential ones** by buffering mutations in memory and flushing sorted runs to disk, making RocksDB ideal for write-heavy workloads.
- **Compaction is the critical background process** that merges sorted runs, removes stale data, and maintains read performance — choosing the wrong strategy can degrade your system under load.
- **Leveled compaction minimizes read amplification** at the cost of higher write amplification, making it ideal for read-heavy workloads with strict latency requirements.
- **Universal compaction minimizes write amplification** at the cost of higher read amplification, suiting write-heavy, append-only workloads.
- **The three amplification dimensions — write, read, and space — form a tradeoff triangle** that no strategy escapes; tuning RocksDB parameters lets you navigate this triangle based on your workload.
- **Monitoring compaction metrics in production is non-negotiable** — write stalls, compaction backlogs, and space spikes are the most common causes of RocksDB-related outages.

## Further Reading

- [RocksDB Official Documentation — Compaction](https://rocksdb.org/doc/Compaction.html) — The definitive reference for compaction configuration, parameters, and behavior across all strategies.
- [LevelDB Paper: A Fast, Scalable Key-Value Store (O'Neil et al.)](https://www.cs.umass.edu/~emery/pubs/o-05leveldb.pdf) — The academic foundation describing the LSM-tree architecture that RocksDB builds upon.
- [RocksDB GitHub Repository](https://github.com/facebook/rocksdb) — The source code, issue tracker, and contribution guidelines for the project.
- [MyRocks: MySQL with RocksDB Storage Engine](https://github.com/facebook/myrocks) — A production deployment of RocksDB inside MySQL, with extensive tuning documentation for real-world workloads.
- [Apache Cassandra Compaction Strategy Comparison](https://cassandra.apache.org/doc/latest/cassandra/operating/sstable_compaction.html) — A practical comparison of LSM compaction strategies across distributed database systems, including size-tiered and leveled approaches.