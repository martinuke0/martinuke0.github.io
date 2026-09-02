---
title: "Inside RocksDB LSM-Tree Compaction: Strategies, Trade-offs, and Production Tuning"
date: "2026-09-02T05:00:49.446"
draft: false
tags: ["rocksdb", "lsm-tree", "storage-engine", "compaction", "performance-tuning"]
description: "A deep dive into RocksDB compaction styles — leveled, universal, FIFO — covering how they work, the trade-offs they impose, and how to tune them for production."
summary: "How RocksDB picks compaction strategies, what each one costs you in write amplification and read latency, and the knobs that matter in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-inside-rocksdb-lsm-tree-compaction-strategies-trade-offs-and-production-tuning.svg"
  alt: "Stylized illustration of stacked sorted runs merging into a single sorted level."
  caption: ""
  relative: false
---

> **TL;DR** — RocksDB's compaction strategy is the single biggest knob for tuning an LSM-tree workload. Leveled compaction minimizes read amplification but burns write bandwidth; universal compaction maximizes write throughput but punishes range scans. Picking the right style — and the right `CompactionOptions` — depends on whether your workload is read-heavy, write-heavy, or time-series.

If you've ever shipped a service backed by RocksDB — or any storage engine descended from LevelDB — you've bumped into the same paradox: writes are blazing fast until they aren't, reads are cheap until they aren't, and somewhere between the two, your disk is doing four to ten times more work than your application thinks it is. That hidden tax is **write amplification**, and compaction is both its source and its lever.

This post walks through how RocksDB compacts data, what each compaction style actually does under the hood, and how to pick and tune one for a real production workload.

## A Quick Refresher: Why LSM-Trees Need Compaction

An LSM-tree (log-structured merge tree) is the dominant write-optimized structure in modern key-value storage. RocksDB, Cassandra's StorageEngine, TiKV, ScyllaDB, and Deno's KV all build on it. Writes go to an in-memory memtable, then flush to disk as a **Sorted String Table (SST)** — an immutable, sorted, block-compressed file. Reads check the memtable, then "walk" the SSTs from newest to oldest looking for the key.

Without compaction, the number of SSTs grows forever, every read touches more files, and deletes (a special "tombstone" marker) never get cleaned up. Compaction is the background process that merges SSTs, drops overwritten and deleted keys, and re-establishes the read invariants the LSM promises.

The cost is exactly what you'd expect: more merging, more I/O, more write amplification.

## The Three Strategies RocksDB Ships

RocksDB exposes its compaction strategy through a single enum-like option: `compaction_style`. There are three values, and each one makes a different bet about what your workload looks like.

### Leveled Compaction (`kCompactionStyleLevel`)

This is the default and the one most production systems use. Data is organized into levels (L0, L1, ..., Lmax), each roughly 10× the size of the one above. L0 is special — files can overlap, so a point query may have to check several. Everything below L0 is non-overlapping within a level, which is what makes leveled reads predictable.

The classic compaction trigger: a file in Ln picks a non-overlapping file in Ln+1, merges them with overlapping Ln+1 files, and writes the result back to Ln+1. The "level" in the name refers to this intra-level disjointness guarantee.

> The Levelled Compaction papers by O'Neil and others showed that, given a fixed per-level size ratio, a leveled LSM-tree can answer point queries by touching O(1) files per level instead of O(N) total. RocksDB inherits this directly.

The price is **write amplification**. Every byte you write can be rewritten 10–30× before it's deep enough to be left alone. The upside is read amplification near 1 for point lookups and bounded I/O for range scans, which is why Facebook still uses leveled compaction for the graph storage behind [TAO](https://www.usenix.org/system/files/conference/atc13/atc13-paper-bronson.pdf).

### Universal Compaction (`kCompactionStyleUniversal`)

Universal (sometimes called "size-tiered") compaction skips the level hierarchy entirely. Instead, it sorts SSTs by size and periodically merges the smallest N files into one bigger file. There are no disjointness guarantees — any file can overlap any other.

The win is **write amplification close to 1** in the steady state: a key is written to one memtable, flushed to one SST, and that's largely it until the file is the smallest one and gets merged with its peers. The loss is that reads can touch many overlapping files, and range scans are essentially full-table scans of the LSM.

Universal is a great fit for write-heavy time-series data, especially if reads are rare or lookups are point queries against a known set of recent keys. Rockset's earlier storage backend and some Cassandra deployments historically used it for the same reason.

### FIFO Compaction (`kCompactionStyleFIFO`)

FIFO is the degenerate case. Files are dropped based on age, not merged. It's the right choice when your data has a TTL and you genuinely never need to read the old stuff — log buffers, ephemeral queues, time-windowed caches. Files are deleted in FIFO order when a TTL elapses or the total size crosses a threshold.

> Be careful with FIFO: deletes and updates are append-only, so they don't actually reclaim space. The deleted-key "tombstone" stays in the LSM until the file is dropped wholesale. If your write rate includes a non-trivial fraction of overwrites, FIFO will quietly bloat.

The [`rocksdb` wiki page on compaction](https://github.com/facebook/rocksdb/wiki/Compaction) is the canonical reference for what each style does and how to switch between them.

## What Actually Happens During a Compaction

It's worth understanding the mechanics, because most production tuning is "change a knob that affects this state machine." When a compaction runs, RocksDB does roughly the following:

1. **Pick input files** according to the strategy (the "compaction picker").
2. **Open a MergeIterator** over the inputs, sorted by key. RocksDB's merge iterator merges sorted runs efficiently without loading entire files into memory; you can read the iterator design in the [RocksDB Iterator implementation notes](https://github.com/facebook/rocksdb/wiki/Iterator-Implementation).
3. **Stream the merged output** to one or more new SSTs in the target level. Each output file is built in sorted order, with a Bloom filter generated at flush time and block indexes written as the file closes.
4. **Resolve conflicts** by key order. In leveled compaction, the newer of the (sequence number, key type) pair wins — this is how deletes and overwrites eventually take effect.
5. **Install atomically** by updating the LSM's manifest. Old input files are scheduled for deletion once nothing holds a reference.

The whole pipeline is throttled by the **rate limiter** (controlled by `rate_limiter_bytes_per_sec`) and the **background thread pool** (controlled by `max_background_jobs` and `max_background_compactions`). If compaction can't keep up, you'll see L0 file count climb, get a "stall" warning in the stats, and watch p99 read latency spike.

## The Real Production Trade-offs

It's tempting to read the RocksDB docs and pick the strategy with the lowest write amplification. In practice, three trade-offs dominate every decision.

### Write Amplification vs. Read Amplification vs. Space Amplification

These three are linked by what the [RocksDB tuning guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) calls the LSM triangle. You can shrink one only by growing another.

- **Leveled**: WA ≈ 10–30×, RA ≈ 1–5×, SA ≈ 1.1×.
- **Universal**: WA ≈ 1–5×, RA ≈ 10–50×, SA ≈ 1.5–2×.
- **FIFO**: WA ≈ 1× (no rewrites), RA ≈ N files in window, SA ≈ 1× over the window size.

If you're storing 10 TB and your write amp is 20×, you're pushing 200 TB through your disks per fill cycle. On a single SSD, that's the difference between a three-year drive and a six-month one.

### Read Shape Matters More Than You Think

Point lookups at a known key are cheap on leveled. Range scans across a hot keyspace are cheap on universal *only if* the range is recent, because older levels in leveled have non-overlapping key ranges you can stream linearly. A universal LSM with 100 files of overlapping keys turns a `SELECT * WHERE ts BETWEEN ? AND ?` into a near full-table scan.

This is the precise reason TiKV — which serves both point reads and range queries for TiDB — chose leveled. And it's why Cassandra lets you [set the strategy per table](https://cassandra.apache.org/doc/latest/cassandra/operating/compaction.html) — wide-column time-series workloads favor size-tiered, OLTP-style workloads favor leveled.

### Delete and Update Workloads Are Punishing

A workload that's 30% updates and 10% deletes will write a lot of tombstones and overwrites. In leveled compaction, every key in the LSM will eventually be touched by a compactor to determine the surviving version. In universal, the same is true but the merge window is smaller, so the rework is bounded.

The hidden trap: if your **delete marker** sits in a deeper level than the key it deletes, the compactor has to descend to that level before the delete can be applied. `CompactionOptionsUniversal::enable_trivial_move` and `LevelCompactionOptions::max_table_files_size` are the knobs that decide how eager compaction is about "pulling up" deletes.

## Patterns in Production

A few patterns show up over and over in the systems that ship RocksDB at scale.

### Tiered Storage With `blob_db` or `Titan`

RocksDB 6+ supports [Titan](https://github.com/tikv/titan), a plugin that keeps large values in separate "blob" files and only stores pointers in the LSM. The LSM shrinks dramatically, which lowers write amplification on the metadata path, while the blobs are GC'd in the background. This is essentially universal-style behavior applied to large values while the rest of the LSM stays leveled.

TiKV ships Titan enabled by default in many configurations for this exact reason.

### `level_compaction_dynamic_level_bytes` for Variable Workloads

The default leveled layout assumes each level is roughly 10× the size of the previous one. If your working set is much smaller than the configured `max_bytes_for_level_base`, the lower levels sit empty and you waste space. Setting `level_compaction_dynamic_level_bytes = true` makes RocksDB size levels based on the **last level's actual size**, which is closer to what most production teams want.

The LinkedIn team [described this exact knob in their post on RocksDB tuning](https://engineering.linkedin.com/blog/2019/apache-kafka-pubsub-at-linkedin) (it's a Kafka post, but the principle applies broadly: tune the LSM shape to the data, not to the default).

### Subcompactions for SSD-Friendly Parallelism

A single compaction thread can saturate one disk. RocksDB can split a compaction into subcompactions that each process a disjoint key range in parallel, fully utilizing multiple SSDs. The relevant knob is `max_subcompactions`; the sweet spot is typically the number of compaction threads, which is `max_background_compactions`.

### Throttling to Avoid Read Stalls

If compaction falls behind, L0 files pile up, and reads start touching every one of them. RocksDB exposes a "soft pending" and "hard pending" byte counter, plus stall triggers, in `CompactionOptions`. The most common production recipe is:

1. Set `bytes_per_sync` so each SST is durably fsynced at flush time.
2. Set `rate_limiter_bytes_per_sec` to something like 80% of the disk's steady-state sequential write bandwidth.
3. Watch `rocksdb.compaction.pending.bytes` via the [`Statistics` interface](https://github.com/facebook/rocksdb/wiki/Statistics) and alert above a threshold tied to your memtable size.

## Tuning Knobs That Actually Move the Needle

Most of the dozens of compaction options in RocksDB are second-order. A handful matter for almost every deployment.

- `num_levels`: Defaults to 7. Reduce to 4–5 if your working set is small and you want to lower WA.
- `max_bytes_for_level_base` and `max_bytes_for_level_multiplier`: The "level fanout." Lower multiplier → more levels, more rewrite work, faster reads. Higher multiplier → fewer compactions, slower reads.
- `target_file_size_base`: Larger output files mean fewer files but bigger compactions when they happen. 64–256 MB is a common production range.
- `max_background_compactions` and `max_background_flushes`: The thread pool. Saturate your disk bandwidth before raising this — more threads only help if I/O is the bottleneck.
- `compaction_pri`: `kByCompensatedSize` (default) prioritizes files that would free the most space; `kMinOverlappingRatio` favors compactions that touch fewer overlapping levels. The latter is often better for mixed read/write workloads.
- `compaction_options_fifo.max_table_files_size` or `ttl`: For FIFO, this is the only knob that matters.
- `disable_auto_compactions`: Sometimes you want to turn compaction off entirely during a bulk load and turn it back on afterward. RocksDB supports this; just be ready for the read penalty.

For point-lookup-heavy OLTP, lean toward leveled with a small L1, dynamic levels, and subcompactions. For time-series ingest, use universal with `size_ratio` tuned for your write rate, or FIFO with a TTL that matches your retention.

## Key Takeaways

- **Compaction strategy is a workload decision, not a default.** Leveled for reads, universal for writes, FIFO for ephemeral data. Switching later is a migration.
- **Write amplification is the tax you pay for fast writes.** Leveled costs 10–30×; FIFO and universal cost 1–5×. Plan disk endurance around this.
- **Deletes and updates are the compactor's hardest workload.** Long-lived tombstones and overwrites force traversals through every level that ever held the key.
- **Tune the level fanout, not the per-level size.** `max_bytes_for_level_multiplier` and `level_compaction_dynamic_level_bytes` do more for steady-state performance than almost any other knob.
- **Watch the stall counters, not just throughput.** `rocksdb.compaction.pending.bytes` is the canary for "compaction is falling behind, your p99 is about to spike."
- **Subcompactions and a real rate limiter turn a single disk into a usable storage engine.** Defaults that work in a benchmark fall apart under real production load.

## Further Reading

- [RocksDB Compaction wiki](https://github.com/facebook/rocksdb/wiki/Compaction) — the canonical reference for strategy internals.
- [RocksDB Tuning Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) — the practical guide every RocksDB operator should read first.
- [The Log-Structured Merge-Tree (O'Neil et al., 1996)](https://www.cs.umb.edu/~poneil/lsmtree.pdf) — the original LSM paper; the math behind leveled compaction's read bounds comes from here.
- [RocksDB Iterator Implementation](https://github.com/facebook/rocksdb/wiki/Iterator-Implementation) — for understanding how the merge iterator works during compaction.
- [Dostoevsky: Better Space-Time Trade-Offs for LSM-Tree Based Key Value Stores (Sears & Ramamohan, 2019)](https://www.pingcap.com/blog/dostoevsky-a-better-space-time-trade-off-for-lsm-tree/) — the modern take on hybrid compaction strategies, and what RocksDB's `CompactionOptionsUniversal` approximations are chasing.
- [TiKV's Titan source and design notes](https://github.com/tikv/titan) — a real-world example of pushing value-size bottlenecks out of the LSM via a blob store.