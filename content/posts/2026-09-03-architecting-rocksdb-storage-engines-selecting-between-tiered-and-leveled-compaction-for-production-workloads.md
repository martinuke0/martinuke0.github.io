---
title: "Architecting RocksDB Storage Engines: Selecting Between Tiered and Leveled Compaction for Production Workloads"
date: "2026-09-03T00:00:13.995"
draft: false
tags: ["rocksdb", "storage-engines", "compaction-strategies", "lsm-trees", "distributed-systems"]
description: "A production-focused guide to choosing between RocksDB's tiered and leveled compaction strategies, with benchmarks, tradeoffs, and tuning tips."
summary: "Compaction strategy is the single most consequential knob in a RocksDB deployment. This post walks through how tiered (universal) and leveled compaction actually work, what they cost at write and read time, and how to pick one based on your workload shape."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-architecting-rocksdb-storage-engines-selecting-between-tiered-and-leveled-compaction-for-production-workloads.svg"
  alt: "Abstract diagram of an LSM-tree with sorted runs cascading across levels."
  caption: ""
  relative: false
---

> **TL;DR** — RocksDB ships two fundamentally different compaction philosophies: **leveled compaction**, which trades write amplification for predictable read latency and low space amplification, and **tiered (universal) compaction**, which keeps write amplification near 1× but lets reads degrade as the number of sorted runs grows. Production teams should pick by workload shape: leveled for read-heavy OLTP and point lookups, tiered for write-heavy time-series and log-style ingestion, and a hybrid (`CompactionPrioirty::kByCompensatedSize` with leveled) for mixed traffic.

## Why Compaction Strategy Is the Most Important RocksDB Decision

Every RocksDB deployment eventually runs into the same set of symptoms: write stalls under sustained load, tail-latency spikes on point reads, sudden disk-space blowups, or background compaction threads falling irrecoverably behind. Before anyone reaches for `write_buffer_size` or `max_background_jobs`, the first question worth asking is *which compaction strategy is this engine actually running?*

RocksDB organizes data in an LSM-tree: writes go to an in-memory memtable, flush to immutable sorted string tables (SSTs) on disk, and those SSTs are periodically merged by background threads. The merge policy — called **compaction** — is what determines how sorted runs overlap, how many files the engine touches per read, and how many times a byte gets rewritten before it ages out. Three knobs control everything: `compaction_style` (leveled, universal, or FIFO), `num_levels`, and `compaction_pri`.

Picking the wrong one is rarely fatal immediately; it shows up as a slow drift in p99 latency or a steady climb in compaction debt that only becomes visible during a traffic spike. Picking the right one — and tuning the parameters that surround it — is what separates a database that scales linearly from one that falls over at 2× load.

## How the Two Strategies Actually Work

### Leveled Compaction: The Read-Optimized Default

Leveled compaction, the strategy RocksDB inherited from LevelDB, divides the on-disk SSTs into a stack of levels numbered L0 through L7 (or deeper). L0 is special: it is the direct landing zone for memtable flushes, and files in L0 may overlap each other freely. Starting at L1, every level is **non-overlapping**: a key belongs to exactly one SST per level, and level sizes grow by a fixed factor — by default 10× — relative to the previous one.

When L0 fills, one of its files is merged with all overlapping files in L1 to produce a new sorted run at L1. That new run may itself overlap files in L2, triggering another merge, and so on down the stack. The classic visualization:

```
L0:  [a b c] [d e f] [g h i]        ← memtable flushes, may overlap
L1:  [abcdefghi]                     ← sorted, non-overlapping
L2:  [abcdefghi......]               ← ~10× L1 size
L3:  [............................]  ← ~10× L2 size
```

This structure makes reads cheap. A point lookup on a fully compacted LSM at L7 touches at most one SST per level — typically 7–8 file reads, of which most resolve via the in-memory bloom filter and block cache. The **read amplification** is bounded by `num_levels`, regardless of how much data is stored.

The cost is **write amplification (WA)**: a single byte written into L0 typically gets rewritten at every level it traverses. With a level size ratio of 10 and 7 levels, the worst-case WA is on the order of:

```
WA ≈ num_levels × size_ratio ≈ 7 × 10 = ~50×
```

In practice, RocksDB's "bottommost" optimizations (avoiding key re-emission on the lowest level) bring this down to roughly 8–20× for typical key-value workloads. For SSDs, where each write has finite endurance, that amplification is real money.

### Tiered (Universal) Compaction: The Write-Optimized Alternative

Tiered compaction takes the opposite bet. Instead of merging toward non-overlapping levels, it keeps the **current set of sorted runs** and periodically merges only the smallest runs together to form a new, larger run. SST files in different runs can overlap arbitrarily.

```
R1: [a d g]      ← small, recent
R2: [b e h]
R3: [c f i]
R4: [....................]  ← large, old
```

A read has to consult every run whose key range could contain the target. With `num_runs` runs and a bloom filter per file, point lookup cost scales with the number of runs — easily 10–20× worse than a fully leveled LSM under the same data volume.

In return, **write amplification stays close to 1×**. The data is written once into memtable, flushed once to L0-style files, and then merged only occasionally — and when it is merged, the merge consolidates runs without rewriting each individual key through every level. For write-heavy workloads (time-series, telemetry, append-only event logs), this is often a far better fit.

The tradeoff is captured neatly in the **LSM-tuning analysis** by Dayan and Idreos, later extended in the RocksDB wiki: every LSM exists on a frontier between write amplification, read amplification, and space amplification, and moving toward one moves you away from the others.

## Patterns in Production: Who Picks What

### When Leveled Wins

Leveled compaction is the right default for OLTP, point lookups, and any workload where **read p99 matters more than write throughput**. Real examples:

- **MyRocks at Facebook/Meta**: Meta's MySQL-on-RocksDB engine defaulted to leveled compaction with `level0_file_num_compaction_trigger=2` and `max_bytes_for_level_base=256MB`. Their published [MyRocks engineering notes](https://github.com/facebook/mysql-5.6/wiki/MyRocks-Engineering-Notes) emphasize that leveled compaction is what makes MyRocks viable as a drop-in replacement for InnoDB on OLTP workloads, because InnoDB's competitive feature is consistent point-read latency.
- **TiKV's RocksDB tier**: TiKV, the storage layer of TiDB, uses RocksDB with leveled compaction for its primary raftstore. The design is documented in the [TiKV architecture guide](https://tikv.org/deep-dive-2-storage-engine/), which calls out that random point reads on Raft-log-derived data have tight latency SLOs that leveled compaction supports well.
- **etcd's embedded bbolt**: Not RocksDB, but instructive — etcd deliberately chose a B+tree rather than an LSM precisely because they want O(log N) reads and small datasets. When teams choose RocksDB at all, they are usually choosing *against* bbolt's read-friendliness.

For leveled compaction, two parameters matter most:

- `level_compaction_dynamic_level_bytes=true` lets RocksDB compute level sizes from the actual data volume rather than from a static base. This keeps the bottommost level large, which reduces the total number of levels and therefore the worst-case read amplification.
- `compaction_pri=kByCompensatedSize` (sometimes called "compaction priority by compensated size") makes the compactor preferentially pick files that free the most space. Under workloads with a high update rate, this dramatically reduces space amplification because old versions of overwritten keys are reclaimed faster.

### When Tiered Wins

Tiered compaction shines for **append-mostly, read-light workloads**:

- **Time-series databases** that take a few hundred thousand writes per second and rarely delete: classic examples include the RocksDB-backed versions of Druid's historical nodes and Prometheus-style metric stores. The [Druid storage design docs](https://druid.apache.org/docs/latest/design/segments) describe exactly this pattern — large immutable batches written once and queried in columnar scans, where a few extra disk reads per point are invisible.
- **Kafka Streams state stores** running on RocksDB, where each topic partition creates its own store and the workload is dominated by `put()`. The [Kafka Streams docs](https://kafka.apache.org/documentation/streams/) document the default `RocksDBConfigSetter` patterns, and many teams override the store to use universal compaction to handle update-heavy changelog traffic.
- **Event-sourced log compaction**, where the working set is recent data and old data is rarely touched.

For tiered compaction, two parameters matter most:

- `universal.size_ratio` (often 1, i.e. merge all available runs) determines how aggressively the compactor merges runs. A ratio of 1 produces the smallest read amplification in tiered mode but increases WA somewhat.
- `universal.min_merge_width` and `max_merge_width` (defaults 2 and ∞) control how many runs get pulled into a single merge. Tight bounds control read amplification but can starve compactions under bursty writes.

### Hybrid Setups: kCompactionStyleUniversal Mixed With Leveled

A common production trick is to **use leveled compaction globally but treat one column family differently**. For example, a service might run two column families: `cf_meta` with leveled compaction (small, read-heavy) and `cf_telemetry` with universal compaction (large, write-heavy). RocksDB exposes `cf_options.compaction_style` per column family, which makes this trivial:

```cpp
rocksdb::ColumnFamilyOptions cf_meta_opts;
cf_meta_opts.compaction_style = rocksdb::kCompactionStyleLevel;
cf_meta_opts.level_compaction_dynamic_level_bytes = true;

rocksdb::ColumnFamilyOptions cf_telemetry_opts;
cf_telemetry_opts.compaction_style = rocksdb::kCompactionStyleUniversal;
cf_telemetry_opts.universal.size_ratio = 10;
cf_telemetry_opts.universal.min_merge_width = 4;
```

In TiKV, the raftstore CF uses leveled compaction while the lock CF — which has very different access patterns — is configured separately. The same pattern shows up in the [TiKV RocksDB tuning guide](https://docs.pingcap.com/tidb/dev/tikv-configuration-file) for the `raftdb` and `kvdb` instances.

## Quantifying the Tradeoffs: Amplification Factors

A clean way to reason about the choice is to compute the three amplification factors for your workload:

| Factor | Definition | Leveled | Universal |
|---|---|---|---|
| **Write amplification** | Bytes physically written ÷ bytes logically written | 8–50× depending on level ratio | ~1–5× |
| **Read amplification** | Number of SSTs touched per point lookup | O(log_R N), bounded by `num_levels` | O(num_runs), grows with merge width |
| **Space amplification** | On-disk size ÷ logical data size | ~1.1× (low) | 1.5–2× (overlapping runs) |

These are not independent. The [Monkey LSM-tree survey](http://www.brainvoyager.com/bv/doc/Publications/LSM-tree.pdf) (and the broader literature, including Dayan et al.'s work at Harvard's [IDEA Research Group](https://db.cs.harvard.edu/papers/LSM-Tree-Dayan-SIGMOD2017.pdf)) shows that for any LSM you can improve two of the three factors, but only by sacrificing the third. The practical reading of this is: **know which factor your workload punishes hardest**, then pick the strategy that minimizes it.

A worked example. Suppose you ingest 100 GB/day with a 1 KB average value, and your SSD has a DWPD rating of 0.5 on the deployed volume. With leveled compaction at WA ≈ 20×, you're writing 2 TB of physical bytes per day — comfortably within budget. With universal compaction at WA ≈ 2×, you're writing 200 GB/day. If your reads are point lookups by primary key only, leveled is the obvious pick. If your reads are bulk range scans over recent data, universal is probably better.

## A Decision Framework You Can Actually Use

Here is a flowchart that maps cleanly to real workloads:

1. **Are your reads dominated by point lookups (`Get`) with tight p99 SLOs?** → Leveled, with `compaction_pri=kByCompensatedSize` and dynamic level bytes enabled.
2. **Is your data append-mostly and rarely overwritten or read by key?** → Universal, with `size_ratio` tuned to limit `num_runs`.
3. **Do you have a mix of read-heavy hot data and write-heavy cold data?** → Two column families, one of each strategy.
4. **Are you running out of SSD endurance?** → Universal, or leveled with a smaller `max_bytes_for_level_multiplier`.
5. **Is compaction lag (the count of pending compaction bytes) growing unbounded?** → You're under-provisioned for compaction regardless of strategy. Add `max_background_jobs`, increase `rate_limiter_bytes_per_sec`, or reduce ingest rate.

For most teams new to RocksDB, **leveled compaction with sensible defaults is the right starting point**. The Meta team's [MyRocks best-practice notes](https://github.com/facebook/mysql-5.6/wiki/MyRocks-Engineering-Notes) and the [TiKV tuning documentation](https://docs.pingcap.com/tidb/stable/tikv-overview) both default to leveled, and the reason is that *if you don't yet know your workload shape, leveled has the most predictable read behavior*.

## Tuning Details That Bite in Production

A few knobs that look minor but routinely make the difference between a healthy cluster and a paging on-call:

- **`write_buffer_size` and `max_write_buffer_number`**: control memtable size and the number of memtables allowed before writes stall. With universal compaction, you can usually afford a larger memtable because the cost of a flush is amortized differently than under leveled.
- **`max_background_jobs`**: the total number of compaction + flush threads. The [RocksDB wiki](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) recommends roughly one compaction thread per physical core, but on NUMA systems or container hosts with noisy neighbors, fewer threads with more careful scheduling often wins.
- **`compression_per_level`**: leveled compaction frequently turns off compression at L0 (because files are short-lived) and turns it on at L2+. Universal compaction usually benefits from aggressive compression throughout because runs are large.
- **`bytes_per_sync` and `wal_bytes_per_sync`**: control how aggressively fsync is amortized. On cloud NVMe where latency is already low, larger values improve throughput at the cost of recovery time.
- **`block_cache_size`**: with universal compaction, a larger block cache is more impactful because reads hit more files; with leveled compaction, the bloom filter absorbs most of the point-lookup cost.

The single most common production mistake is to **leave `compaction_pri` at the default (`kByCompensatedSize` is *not* the default — it is `kMinOverlappingRatio` in many builds)**, then be surprised by compaction debt accumulation when overwrites pile up. Verifying this with `rocksdb.getProperty("rocksdb.cfstats")` and `getProperty("rocksdb.num-running-compactions")` during load tests catches the misconfiguration before it hits production.

## Key Takeaways

- Compaction strategy is the highest-leverage decision in a RocksDB deployment; almost every other knob tunes its consequences.
- Leveled compaction is read-optimized: bounded read amplification, predictable latency, but 8–50× write amplification depending on level ratio.
- Universal (tiered) compaction is write-optimized: ~1–5× write amplification, but read cost grows with the number of sorted runs.
- Pick by workload shape: leveled for OLTP/point lookups, universal for append-heavy/log-style ingest, split column families for mixed access patterns.
- Always measure the three amplification factors empirically on your workload — the defaults are good starting points but rarely the final answer.
- Monitor compaction debt (`rocksdb.num-running-compactions`, `rocksdb.cfstats`, pending compaction bytes) and treat unbounded growth as a P1 signal regardless of which strategy you picked.

## Further Reading

- [The Log-Structured Merge-Tree (LSM-Tree)](https://www.cs.umb.edu/~israel/sched/lsm-tree.pdf) — the original O'Neil paper describing the LSM-tree and the tradeoffs it makes.
- [Monkey: Optimal Navigability in LSM-Tree Based Key-Value Stores (Dayan et al., SIGMOD 2017)](https://stratos.seas.harvard.edu/files/stratos/files/monkey_sigmod.pdf) — the academic foundation for understanding WA/RA/SA tradeoffs in LSMs.
- [RocksDB Tuning Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) — the canonical reference for RocksDB-level configuration knobs.
- [Leveled Compaction in RocksDB — Implementation Notes](https://github.com/facebook/rocksdb/wiki/Leveled-Compaction) — official wiki page describing the leveled implementation details.
- [TiKV RocksDB Configuration Reference](https://docs.pingcap.com/tidb/dev/tikv-configuration-file) — a battle-tested production tuning profile from one of the largest RocksDB deployments.
- [MyRocks Engineering Notes](https://github.com/facebook/mysql-5.6/wiki/MyRocks-Engineering-Notes) — Meta's production learnings from running RocksDB as MySQL's storage engine at scale.