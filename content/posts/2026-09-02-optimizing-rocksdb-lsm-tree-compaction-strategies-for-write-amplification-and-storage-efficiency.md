---
title: "Optimizing RocksDB LSM-Tree Compaction: Strategies for Write Amplification and Storage Efficiency"
date: "2026-09-02T02:00:51.048"
draft: false
tags: ["rocksdb", "lsm-tree", "compaction", "storage", "performance"]
description: "Practical RocksDB compaction tuning: leveled, universal, FIFO, and tiered strategies to cut write amplification and reclaim storage in production."
summary: "How RocksDB's compaction strategies trade off write amplification, read amplification, and space amplification — and how to tune them for real workloads."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-optimizing-rocksdb-lsm-tree-compaction-strategies-for-write-amplification-and-storage-efficiency.svg"
  alt: "Stack of sorted runs in an LSM-tree being merged by a compactor."
  caption: ""
  relative: false
---

> **TL;DR** — RocksDB's compaction strategy is the single biggest lever you have for trading off write amplification, read amplification, and space amplification. Picking the right base strategy (leveled, universal, FIFO, or tiered) and tuning its parameters around your workload's key size, update pattern, and read/write ratio is what separates a database that's burning flash at 30x write amp from one running cleanly at 3x.

If you've ever opened a RocksDB dashboard and watched the "write amplification" chart creep past 10x while your SSDs quietly aged, you already know that compaction is where storage engines live or die. RocksDB doesn't have one compaction policy — it has a small library of them, plus a sophisticated tuning surface behind each one. The right configuration can drop write amp by an order of magnitude. The wrong one can turn a hot database into a thrashing mess.

This post walks through what compaction actually does in an LSM-tree, why the four base strategies behave so differently, and which knobs matter when you're tuning for production.

## What Compaction Actually Does

RocksDB stores data in an LSM-tree. Writes go to an in-memory memtable, flush to an immutable sorted run on disk (an SST file), and then background threads merge sorted runs together. That merging is compaction.

Every compaction reads N files and writes 1 new file. That I/O is the **write amplification** — the ratio of bytes physically written to disk versus logical bytes the application wrote. If you write 1 GB and the compactor eventually writes 30 GB while reorganizing it, your write amp is 30x. SSDs have finite endurance, so this number has a direct cost.

Compaction also dictates:

- **Read amplification**: how many SST files a point query might have to check.
- **Space amplification**: how much extra disk the live data occupies across levels versus its raw size.
- **Compaction stall rate**: how often foreground writes block because the compactor can't keep up.

The strategy you pick sets the shape of the trade-off curve. The parameters dial it in.

## The Four Base Strategies

RocksDB ships with `kCompactionStyleLevel`, `kCompactionStyleUniversal`, `kCompactionStyleFIFO`, and `kCompactionStyleNone`. In practice, almost everyone uses one of the first three. They optimize for different points on the trade-off curve, and understanding why is the foundation for tuning.

### Leveled Compaction (`level_compaction_dynamic_level_bytes=true`)

This is the default, and the one you'll use for transactional, latency-sensitive workloads — anything OLTP-shaped. Files are organized into levels L0 through Ln. L0 contains memtable flushes that haven't been merged; L1 through Ln each contain non-overlapping key ranges. A compaction picks one file in Ln and merges it with all overlapping files in L(n+1), producing a new sorted L(n+1).

The big win: point and range queries touch at most one file per level, giving you predictable low-latency lookups even under heavy churn. The cost: high write amplification, because every byte can move through several levels before reaching the bottom. In a 6-level DB with a 10x level size ratio, theoretical write amp is around 10–30x for cold data.

```text
L0: [flush A] [flush B] [flush C]
L1:  [sst1]            [sst2]
L2:  [sst10][sst11][sst12][sst13][sst14]
```

When `sst1` in L1 merges down, it overlaps with every L2 file in its key range — and the result has to be rewritten into a new L2 file. This is the leveled "rewrite everything in the level" pattern that drives write amp.

### Universal Compaction (`kCompactionStyleUniversal`)

Universal compaction treats the LSM-tree as a single pile of sorted runs and periodically merges the oldest ones. It's the strategy to reach for when you're write-heavy, append-mostly, and willing to trade some read performance for substantially lower write amp. Kafka's Streams state stores, time-series workloads, and write-once-read-many logs all default to universal or a variant.

Without tuning, universal compaction can have high read amplification (a key could live in several files until everything compacts down) and high space amplification. With **size-tiered compaction** (`min_merge_width`, `max_merge_width`), runs of similar size get grouped and merged together — this is what gives the lowest write amp of the four strategies.

The compromise: until runs get merged down, reads may touch N files. You'll typically see 5–10x lower write amp than leveled, but **stalls can be brutal** when a huge compaction kicks off. Universal also keeps deleted/overwritten keys around longer, which means tombstones and stale data linger.

### FIFO Compaction (`kCompactionStyleFIFO`)

FIFO is the simplest strategy. Files are dropped in arrival order once they exceed a TTL or total size threshold. It's explicitly designed for workloads where data expires and you don't want compaction I/O on disk at all — RocksDB itself warns that reads will be expensive once you have many active files.

```cpp
// Pseudocode for FIFO selection
if (file_age > ttl || total_size > max_table_files_size) {
    delete_oldest_file();
}
```

Use FIFO when your data has a clear TTL, your reads are predominantly for recent keys, and you genuinely cannot afford compaction I/O. Edge caches, session stores with hard expiration, and queue-like workloads fit.

### Tiered Compaction (BlobDB and `kCompactionStyleNone` with manual triggers)

Tiered compaction — popularized by systems like [Cassandra's TWCS](https://cassandra.apache.org/doc/latest/cassandra/operating/readiness.html) and [ScyllaDB's window-based compaction](https://opensource.docs.scylladb.com/stable/architecture/compaction/compaction-strategies.html) — groups files by time window and merges whole windows together. RocksDB doesn't ship TWCS by name, but you can emulate it through universal compaction with carefully chosen timestamps in the key, or use BlobDB's garbage collection policies for large-value workloads. The big idea: amortize compaction I/O over long windows so write amp drops to close to 1 while read amp stays bounded.

## How RocksDB Picks Compaction Triggers

Whichever strategy you choose, compaction is triggered by the same score function. For leveled, RocksDB computes a score for each level based on how full it is; the highest-scoring level is compacted next. For universal, runs are queued into a sorted run list and the oldest eligible set is merged. For FIFO, age and size gates trigger deletes.

The relevant knobs sit in `DBOptions` and `ColumnFamilyOptions`:

- `level0_file_num_compaction_trigger` — how many L0 files trigger a compaction into L1.
- `max_bytes_for_level_base` / `max_bytes_for_level_multiplier` — the size ratio between levels.
- `target_file_size_base` — the unit of file size in L1+.
- `compaction_pri` — `kByCompensatedSize` (default), `kOldestLargestSeqFirst`, or `kMinOverlappingRatio`. This decides which file in a level to compact next when scores are tied.
- `disable_auto_compactions` — disables background compaction entirely (you'd only do this if you control compaction manually).

If you've never touched these, your DB is using Meta's defaults, which are reasonable for general OLTP but rarely optimal for any specific workload.

## Patterns in Production

A few configurations come up over and over in real deployments.

### Pattern 1: Transactional OLTP — Leveled with Dynamic Levels

For a general-purpose transactional workload (think a metadata store, leader index, or feature lookup DB), leveled compaction with dynamic level sizing is the standard. The `level_compaction_dynamic_level_bytes=true` setting keeps L1 sized relative to L0 instead of fixed at 16 MB, which avoids wasted levels in small databases.

```yaml
# RocksDB options snippet (conceptual)
level_compaction_dynamic_level_bytes: true
max_bytes_for_level_base: 268435456      # 256 MB
max_bytes_for_level_multiplier: 10
target_file_size_base: 67108864          # 64 MB
level0_file_num_compaction_trigger: 4
write_buffer_size: 134217728             # 128 MB memtable
max_write_buffer_number: 3
```

This gives you ~10x level size ratio, ~1 GB at L5, and ~256 GB total. Point reads check at most one file per level; compaction I/O is bounded. Write amp lands in the 10–30x range for cold data, lower for hot.

### Pattern 2: Write-Heavy Time-Series — Universal + BlobDB

For a time-series workload — metrics, audit logs, click streams — the workload is monotonic, append-heavy, and reads mostly recent. Universal compaction with blob storage gives the lowest write amp while keeping recent reads fast.

```cpp
// High-level approach in C++
options.compaction_style = kCompactionStyleUniversal;
options.compaction_options_universal.min_merge_width = 4;
options.compaction_options_universal.max_merge_width = 16;
options.compaction_options_universal.size_ratio = 1; // strict size-tiered
options.compaction_options_universal.compression_size_percent = -1; // always compress
```

Then layer [BlobDB](https://github.com/facebook/rocksdb/wiki/BlobDB) on top to keep large values out of the LSM-tree. With this setup, write amp often drops to 2–5x while keeping recent reads at one or two file lookups. The catch: tombstones must be carefully managed, or space amp will explode. Most time-series workloads solve this by using a TTL column and running a periodic compaction.

### Pattern 3: Tiered/Layered — Manual TTL Compaction

For data with a hard expiration horizon (event logs, ephemeral user state), consider emulating tiered compaction by bucketing keys into time windows and using a separate column family or DB per window. Each window DB uses FIFO compaction with a TTL. When the window expires, the whole DB is dropped.

This is overkill for most apps, but for a multi-tenant logging system handling TB/day, it's a common pattern because it gives you predictable disk usage and zero compaction I/O on cold windows.

## Tuning Compaction for Specific Failure Modes

Strategy is the big lever. The next step is dialing in the parameters to fix the failure mode you're actually seeing.

### Cutting Write Amplification

Write amp is dominated by how many levels data migrates through and how often it migrates. Three concrete levers:

1. **Reduce the level size ratio.** Drop `max_bytes_for_level_multiplier` from 10 to 8 or even 6. Each level is closer in size to the one above it, so fewer bytes move per compaction. The trade-off is more files per level and higher read amp.
2. **Raise `target_file_size_base`.** Larger files mean fewer of them, fewer compactions, fewer bytes rewritten. Going from 32 MB to 128 MB target file size can drop compaction-trigger frequency noticeably.
3. **Pick tiered/universal over leveled.** As discussed, this is the biggest write-amp win but at a real read-amp cost.

The RocksDB wiki has a useful page on [how write amplification is calculated](https://github.com/facebook/rocksdb/wiki/Write-Amplification-Analysis) that walks through the math.

### Cutting Space Amplification

Space amp comes from two sources: tombstones that haven't been merged down yet, and overwritten keys that still live in older files. Three levers:

1. **Run periodic compactions.** A manual `CompactRange()` on a hot range reclaims tombstone space that incremental compactions skip.
2. **Enable `period_compact_seconds`.** Since RocksDB 7.x, you can set a periodic full-compaction interval that handles tombstone garbage collection without a manual trigger.
3. **Use `bottommost_tier` or blob files for cold data.** Putting cold data into a denser, more compressed tier reduces the on-disk footprint without forcing rewrite-heavy compactions.

### Cutting Read Amplification

Read amp comes from bloom filters, block cache hit rate, and how many files a query might touch. To reduce it:

1. **Increase bloom bits per key.** `bloom_filter_bits_per_key=10` instead of the default 5 raises the false positive rate is meaningful for low-cardinality point reads.
2. **Use partitioned filters.** RocksDB supports [partitioned indexes/filters](https://github.com/facebook/rocksdb/wiki/Partitioned-Index-Filter) which let you load only the index block for the relevant file range, cutting read amp significantly for cold ranges.
3. **Right-size the block cache.** A larger block cache means more reads skip disk entirely. Allocate as much RAM as you can spare — modern RocksDB deployments often run with 10–30 GB block caches.

### Avoiding Stalls

Stalls happen when L0 fills up faster than compactions can drain it. Two levers:

1. **Raise `level0_slowdown_writes_trigger` and `level0_stop_writes_trigger`** carefully. Don't raise them so far that OOM becomes the failure; raise them just enough to absorb compaction lag.
2. **Use `max_background_jobs` aggressively.** Modern NVMe drives can sustain many parallel compactions. Setting `max_background_jobs` to 16 or 32 is common in high-throughput installations.

The [official RocksDB compaction tuning wiki](https://github.com/facebook/rocksdb/wiki/Compaction-Tuning) is a great reference for the full tuning matrix. Most production deployments document their chosen parameters in code alongside the rest of the DB options so the team can review the trade-off explicitly.

## How to Measure Whether Tuning Worked

You can't tune what you can't measure. RocksDB exposes a rich set of metrics through `GetProperty()` and through the [Prometheus-compatible stats](https://github.com/facebook/rocksdb/wiki/Statistics) interface. The numbers you actually need to watch:

- `rocksdb.compaction.write.amp` — bytes written to disk divided by bytes the application wrote.
- `rocksdb.compaction.bytes.written` and `rocksdb.compaction.bytes.read` — total compaction I/O.
- `rocksdb.num.files.at.level[N]` — file distribution per level. If L0 spikes above your trigger repeatedly, you're stalling.
- `rocksdb.stall.micros` — time foreground writes spent stalled.
- `rocksdb.estimate.num.keys` versus `rocksdb.estimate.live.data.size` — let you infer space amp.

Set alerts on compaction stall rate and write amp. A 2x regression in write amp usually means someone changed a workload pattern, and a 5x regression usually means something's wrong.

## Key Takeaways

- **Pick the strategy to match the workload shape, not the other way around.** Transactional OLTP wants leveled; time-series and write-heavy append workloads want universal or tiered; TTL-bound data wants FIFO.
- **Use dynamic level sizing by default for leveled compaction** so small databases don't waste level capacity on empty L1.
- **Write amp is the cost of the read-amp guarantee.** Tiered compaction wins write amp, leveled wins read amp — there's no free lunch, and the parameters dial in where on the curve you live.
- **Measure compaction I/O in production.** Stall time and write amp are the metrics that actually tell you whether your tuning is working; don't tune blind.
- **Run periodic compactions or use `period_compact_seconds`** if space amp from tombstones is creeping up — incremental compactions alone won't reclaim tombstone space.
- **Right-size the block cache and bloom filters** before tuning compaction. Many "compaction problems" are really cache problems in disguise.

## Further Reading

- [RocksDB Compaction Tuning wiki](https://github.com/facebook/rocksdb/wiki/Compaction-Tuning) — the canonical tuning reference.
- [RocksDB Write Amplification Analysis](https://github.com/facebook/rocksdb/wiki/Write-Amplification-Analysis) — the math behind write amp in leveled compaction.
- [Leveled Compaction (O'Neil et al., 1996)](https://www.cs.umb.edu/~poneil/lsmtree.pdf) — the original paper on leveled compaction, still the best explanation of why the trade-off exists.
- [Cassandra TWCS documentation](https://cassandra.apache.org/doc/latest/cassandra/operating/readiness.html) — a production-tiered compaction strategy worth studying even if you're not using Cassandra.
- [ScyllaDB Compaction Strategies](https://opensource.docs.scylladb.com/stable/architecture/compaction/compaction-strategies.html) — well-written treatment of tiered vs. leveled trade-offs from a production database vendor.