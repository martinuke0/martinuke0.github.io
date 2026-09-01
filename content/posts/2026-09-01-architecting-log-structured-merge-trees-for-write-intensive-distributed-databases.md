---
title: "Architecting Log-Structured Merge Trees for Write-Intensive Distributed Databases"
date: "2026-09-01T19:55:39.827"
draft: false
tags: ["lsm-tree", "distributed-databases", "write-intensive", "storage-engines", "system-design"]
description: "How LSM trees power write-heavy distributed databases: from memtables and SSTables to compaction strategies, tiered vs leveled tradeoffs, and production tuning."
summary: "LSM trees are the backbone of modern write-intensive databases like Cassandra, RocksDB, and ScyllaDB. This post walks through the architecture, compaction strategies, and tuning decisions that separate a healthy LSM deployment from a write stall."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-architecting-log-structured-merge-trees-for-write-intensive-distributed-databases.svg"
  alt: "Layered diagram of memtable flushing into sorted SSTables being compacted."
  caption: ""
  relative: false
---

> **TL;DR** — Log-Structured Merge (LSM) trees trade random writes for sequential ones by buffering mutations in memory and flushing immutable sorted runs to disk, then merging them in the background. The compaction strategy you pick — size-tiered, leveled, or a hybrid like RocksDB's universal — is the single biggest lever you have over write amplification, read amplification, and space amplification in systems like [Cassandra](https://cassandra.apache.org/), [RocksDB](https://rocksdb.org/), and [ScyllaDB](https://www.scylladb.com/).

## Why LSM Trees Exist

Classic B-tree based engines like InnoDB or PostgreSQL's heap+btree layout are excellent for reads but punish write-heavy workloads. Every `INSERT` or `UPDATE` requires locating the target page, latching it, and writing it back in place. On a hot index, those page writes queue up, the buffer pool fills, and throughput collapses. The deeper the B-tree, the more random I/O per write.

LSM trees, formalized by O'Neil et al. in their [1996 paper "The Log-Structured Merge-Tree (LSM-Tree)"](https://www.cs.umb.edu/~poneil/lsmtree.pdf), invert that model. Mutations are appended to an in-memory buffer called a **memtable**, then flushed as immutable sorted **SSTables** (Sorted String Tables). Reads must consult the memtable plus several on-disk levels, but writes become purely sequential — fast on both spinning disk and SSD. The trade is paid back in background compaction work that merges overlapping SSTables.

That trade is exactly why every major write-intensive distributed database ships an LSM core:

- **Cassandra** uses an LSM with size-tiered compaction per node, documented in the [Apache Cassandra 4.1 architecture overview](https://cassandra.apache.org/doc/latest/cassandra/architecture/).
- **RocksDB** (embedded in [TiKV](https://tikv.org/), [Kafka Streams](https://kafka.apache.org/documentation/streams/), and [Flink](https://nightlies.apache.org/flink/flink-docs-master/docs/connectors/datastream-kafka/)) offers leveled, universal, and FIFO compaction.
- **ScyllaDB** uses its [seastar-native "Scylla LSM"](https://opensource.docs.scylladb.com/stable/architecture/compaction/index.html) with sharded memtables per CPU core.
- **LevelDB**, [HBase](https://hbase.apache.org/), and [ClickHouse](https://clickhouse.com/docs/en/parts) (MergeTree, a generalized LSM) all follow the same pattern.

## The Anatomy of an LSM Tree

An LSM tree has three logical regions: the memtable in memory, immutable SSTables on disk, and a background process that merges them.

### Memtable: The Write Buffer

A memtable is an ordered, mutable in-memory structure. RocksDB defaults to a [skiplist](https://github.com/facebook/rocksdb/wiki/MemTable); Cassandra uses a copy-on-write tree per memtable; ScyllaDB uses a [segregated B-tree per shard](https://www.scylladb.com/2018/08/14/memtable/). All of them support the same operations: `O(log n)` insert, point lookup, and ordered range scan.

A common production trick is to keep **two memtables**: one mutable, one immutable and being flushed. While the flush thread serializes the immutable memtable to an SSTable, writes continue into the fresh mutable one. This decouples client latency from disk flush time.

To survive crashes, every mutation is also written to a **Write-Ahead Log (WAL)** before entering the memtable. On restart, the WAL is replayed to rebuild the memtable. ScyllaDB takes this further with a [per-shard commitlog](https://opensource.docs.scylladb.com/stable/architecture/commitlog.html) so a stalled shard doesn't block others.

### SSTables: Immutable, Sorted Runs on Disk

An SSTable is a sorted, immutable file or set of files containing key-value entries. Once flushed, it is never modified. Updates create new entries in higher levels; deletes are written as **tombstones**. SSTables typically have three internal components:

1. **Data blocks** — the sorted key-value entries, often compressed (Snappy, ZSTD, LZ4).
2. **Index blocks** — sparse index entries pointing into data blocks for binary search.
3. **Bloom filters** — a probabilistic structure that lets point reads skip SSTables that don't contain a key. RocksDB uses [block-level bloom filters](https://github.com/facebook/rocksdb/wiki/Leveled-Compaction) by default; Cassandra stores a per-SSTable [bloom filter](https://cassandra.apache.org/doc/latest/cassandra/architecture/secondary-indexes.html) keyed on disk layout.

A typical write path looks like this:

```text
client → WAL append (sequential, O(1))
       → memtable insert (in-memory, O(log n))
       → ack

[background flush thread]
memtable (immutable) → SSTable on disk (sequential, sorted, compressed)
```

A typical read path is more involved:

```text
client → memtable (binary search)
       → recent immutable memtable (if present)
       → L0 SSTables (overlapping, check bloom filters)
       → L1, L2, ... (non-overlapping, single hit per level)
       → result
```

The number of disk reads per point lookup is called **read amplification**. The number of disk writes per logical write across all compactions is called **write amplification**. The total disk usage divided by logical dataset size is **space amplification**. The compaction strategy determines how those three values balance.

### Bloom Filters: The Read Amplification Lifesaver

Without bloom filters, every read touches every level. With a 10-bit-per-key bloom filter and a 1% target false-positive rate, point reads skip ~99% of irrelevant SSTables. Cassandra defaults to [a 0.01 false-positive probability](https://cassandra.apache.org/doc/latest/cassandra/operating/bloom_filters.html); RocksDB exposes it via `filter_policy` and `whole_key_filtering`. In production, undersizing the bloom filter is one of the most common causes of read latency cliffs after compaction falls behind.

## Compaction Strategies: Where the Real Engineering Lives

The compaction strategy is the policy that decides *which* SSTables to merge, *when*, and into *what*. There are three families worth understanding.

### Size-Tiered Compaction (STCS)

When the number of SSTables in a level exceeds a threshold (often 4), the smallest ones are merged into a single larger SSTable. This produces fewer, larger SSTables — great for write amplification, terrible for read and space amplification.

Cassandra's default `SizeTieredCompactionStrategy` (STCS) follows this model, as described in the [DataStax compaction documentation](https://docs.datastax.com/en/cassandra-oss/3.x/cassandra/architecture/archDataDistribute.html). STCS works best when the workload is **write-only or time-series with TTL** — exactly the case Cassandra is famous for. It is also the worst choice for point reads because every read may consult many non-overlapping SSTables.

### Leveled Compaction (LCS)

Each level `L(n+1)` is roughly 10× larger than `L(n)`, and SSTables within a level have **non-overlapping key ranges**. When `L(n)` overflows, a sorted run is picked and merged into `L(n+1)`, splitting ranges as needed. This bounds read amplification at roughly `O(log_R N)` where `R` is the level size ratio.

RocksDB's default `kCompactionStyleLevel` is the canonical example. Each level is one-tenth the size of the next by default, as shown in the [RocksDB Leveled Compaction guide](https://github.com/facebook/rocksdb/wiki/Leveled-Compaction). The price is more compactions and higher write amplification. For a workload of 100M keys with a 10× ratio, you get about 7 levels; every key may be rewritten 7 times over its lifetime.

### Universal / FIFO / Hybrid

RocksDB's `kCompactionStyleUniversal` keeps everything in one big sorted run and triggers a compaction when the run exceeds a size threshold. This is closer to STCS but with stricter bounds on number of runs. The hybrid `LeveledUniversal` style, added in RocksDB 7.x, blends both — cold levels use leveled, hot levels use universal — to balance read and write amplification on mixed workloads.

Cassandra also ships a `LeveledCompactionStrategy` (LCS) and a `TimeWindowCompactionStrategy` (TWCS) that aligns SSTable flushes with time buckets, so time-series data expires cleanly via TTL.

```text
STCS:  high write amp, high space amp, low read amp  (worst reads)
LCS:   low read amp, moderate write amp, low space amp
TWCS:  TTL-friendly, predictable file age, used in time-series
```

A practical decision matrix:

| Workload | Recommended strategy |
| --- | --- |
| Time-series with TTL, no point reads | TWCS or STCS |
| Mixed OLTP, point reads, range scans | LCS or RocksDB leveled |
| Heavy overwrite, working set fits in cache | STCS with read amplification bounded by bloom filters |
| Mixed, write-heavy with hot keys | Universal with priority-based compaction |

## Architecture in Production: Cassandra, RocksDB, ScyllaDB

The interesting design differences show up at the distributed level.

### Cassandra

Cassandra runs **one LSM per table per node**. Memtables are per-table and bounded by `memtable_heap_space` or `memtable_offheap_space`. Flushes are triggered by size or by the periodic `MemtableFlushWriter` task. Compaction runs on a dedicated thread pool (`CompactionExecutor`) sized by `concurrent_compactors`.

The two settings that break Cassandra deployments in production are:

- `concurrent_compactors` set too low, causing compaction to fall behind and SSTable count to explode. The rule of thumb in the [Cassandra compaction docs](https://cassandra.apache.org/doc/latest/cassandra/operations/compaction.html) is "number of spindles or 2 per core, whichever is smaller."
- `memtable_flush_writers` set to 1, creating a flush bottleneck on tables receiving tens of MB/s of writes.

Cassandra 4.1's **Tombstone compaction** and **SSTable partitioning improvements** address some of the worst read-amplification pathologies of earlier versions.

### RocksDB

RocksDB is single-node but powers distributed engines like [TiKV](https://docs.pingcap.com/tidb/dev/tikv-overview), where each TiKV instance hosts many RocksDB column families ("CFs"). Each CF is a separate LSM tree sharing the same WAL and thread pools. This is how [TiDB achieves multi-tenant isolation](https://docs.pingcap.com/tidb/dev/performance-tuning-config) — a hot CF doesn't starve a cold one.

Key tunables:

- `write_buffer_size` and `max_write_buffer_number` control memtable sizing and the count of flushed-but-not-yet-compacted L0 files.
- `level0_file_num_compaction_trigger` controls when L0 compacts into L1. Lower values mean less read amplification but more compaction work.
- `target_file_size_base` and `max_bytes_for_level_base` control level sizes. Defaults are 64MB and 256MB; production systems push these into the GB range on SSDs.
- `compression` — ZSTD level 3 is the common production choice, balancing ratio and CPU. The [Facebook RocksDB tuning guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) goes deeper.

A minimal `options.ini` for a write-heavy workload looks like:

```yaml
# RocksDB options excerpt
max_write_buffer_number: 4
min_write_buffer_number_to_merge: 2
write_buffer_size: 268435456   # 256 MB
level0_file_num_compaction_trigger: 4
target_file_size_base: 134217728  # 128 MB
max_bytes_for_level_base: 1073741824  # 1 GB
compression: zstd
bottommost_compression: zstd
```

### ScyllaDB

ScyllaDB's [LSM architecture](https://opensource.docs.scylladb.com/stable/architecture/compaction/index.html) shards the memtable per CPU core, eliminating the single-memtable bottleneck. Each shard has its own memtable and flushes independently. The `compaction_groups` feature (added in ScyllaDB 2022.x) lets a single shard host multiple LSMs with different compaction strategies, so time-series and OLTP workloads can coexist on the same node.

ScyllaDB also runs a **separate compaction thread per shard** by default, which the project calls the "compaction manager." Operators can pin compaction to specific I/O classes via the [`compaction_throughput_mb_per_sec`](https://management.docs.scylladb.com/stable/reference/compaction.html) setting to avoid compaction stealing user-facing I/O.

## Patterns and Anti-Patterns

### Patterns That Actually Ship

1. **Tune `memtable_size` to absorb 30–60 seconds of peak write throughput.** Smaller memtables mean more flushes, more L0 files, more compaction work. Larger memtables mean higher recovery time on restart because of WAL replay.
2. **Use bloom filters aggressively.** 10 bits per key is the minimum. For point-read-heavy workloads, 14–16 bits per key is justified.
3. **Separate WAL from data disks.** RocksDB and Cassandra both support this — the WAL is sequential, write-once, and benefits from low-latency storage, while SSTables are sequential-write-heavy and benefit from throughput storage.
4. **Monitor `pending compactions`, L0 file count, and read amplification.** In RocksDB, `CompactionStats` exposes `NumFilesInLevel`; in Cassandra, `compaction_stats` and `tpstats` in [nodetool](https://cassandra.apache.org/doc/latest/cassandra/tools/nodetool/nodetool.html) are the canonical signals.
5. **Tiered storage for cold SSTables.** [Cassandra 4.0's sstabledir and tiered storage](https://cassandra.apache.org/blog/2021/07/13/introducing-cassandra-tiered-storage.html), and [RocksDB's BlobDB](https://github.com/facebook/rocksdb/wiki/BlobDB), let large values live on cheap object storage while keeping hot keys on local SSD.

### Anti-Patterns That Show Up in Every Postmortem

1. **All writes going to one shard.** A hot partition in a distributed LSM can pin a memtable, fill L0, and stall compaction locally. The fix is sharding the write path (application-side) or choosing a partition key with high cardinality.
2. **Compaction running at full speed during peak traffic.** Compaction competes with flushes and reads. The fix is rate-limiting or scheduling compaction for off-peak.
3. **Ignoring tombstones.** A delete in an LSM writes a tombstone that lives until compaction sees it. Without compaction, deletes accumulate and reads scan every tombstone. Cassandra's [`gc_grace_seconds`](https://cassandra.apache.org/doc/latest/cassandra/operations/compaction/tombstones.html) and RocksDB's `compaction_filter` exist exactly for this.
4. **Mis-sizing the bloom filter.** A 1-bit-per-key bloom filter is a memory saving that costs a 50% false positive rate and a 2× read amplification. Not worth it.

## Failure Modes You Should Plan For

### Write Stall

When L0 fills faster than compaction can drain it, RocksDB triggers a **write stall** — the writer pauses until compactions catch up. The stall manifests as P99 latency spikes with no obvious cause. The [RocksDB write stall docs](https://github.com/facebook/rocksdb/wiki/Write-Stalls) recommend tracking `Stalls(0)` and reacting before the engine hits the `Stalls(2)` (hard stall) threshold. The mitigation is either reducing write rate, increasing compaction parallelism, or moving to a leveled strategy with fewer files per level.

### Compaction Falling Behind

Symptom: SSTable count growing without bound, bloom filter cost increasing, GC pressure rising. Cause: usually one of:

- A bursty ingest (bulk loader, repair, bootstrap)
- Disk I/O saturated by compaction itself
- A few hot partitions creating write skew

Cassandra exposes this as `pending_compactions` in `nodetool compactionstats`. Anything over ~100 pending tasks on a single table warrants investigation.

### Tombstone Accumulation

In Cassandra, a workload with frequent updates and deletes can produce SSTables where most entries are tombstones. Without `tombstone_compaction_interval` or LCS, reads walk dead entries. The **TWCS** strategy makes tombstone expiration predictable because all data in a time window expires together.

### Read Path Bloom Filter Saturation

A 1% false positive sounds small until you have 200 SSTables. The expected number of unnecessary disk seeks per point read becomes `200 × 0.01 = 2`. At 10 bits per key and a 1% target, you're fine. At 4 bits per key, you're at ~10% FPR, and reads degrade sharply.

## Key Takeaways

- LSM trees exist to convert random writes into sequential writes, accepting more complex reads in exchange.
- The memtable + WAL + immutable SSTables pattern is shared by Cassandra, RocksDB, ScyllaDB, HBase, and MergeTree engines. Differences live in compaction strategy and per-shard isolation.
- Compaction strategy is your biggest tuning lever. STCS/TWCS fit write-heavy time-series; LCS fits mixed OLTP; universal/hybrid fit write-heavy with hot keys.
- Bloom filters, L0 file count, and pending compactions are the metrics to instrument. They tell you whether the LSM is healthy or about to stall.
- In distributed LSMs, compaction and flush are per-node or per-shard. Under-provisioning compaction threads is a more common cause of incidents than under-provisioning CPU.
- Anti-patterns (hot partitions, no tombstone GC, undersized bloom filters) show up in nearly every postmortem. Design reviews should check for them explicitly.

## Further Reading

- [The Log-Structured Merge-Tree (LSM-Tree) — O'Neil et al., 1996](https://www.cs.umb.edu/~poneil/lsmtree.pdf)
- [RocksDB Leveled Compaction](https://github.com/facebook/rocksdb/wiki/Leveled-Compaction)
- [Cassandra 4.1 Compaction documentation](https://cassandra.apache.org/doc/latest/cassandra/operations/compaction.html)
- [ScyllaDB Compaction architecture](https://opensource.docs.scylladb.com/stable/architecture/compaction/index.html)
- [TiKV storage engine — RocksDB under the hood](https://docs.pingcap.com/tidb/dev/tikv-overview)
- [Designing Data-Intensive Applications, Chapter 3 (Storage and Retrieval) — Martin Kleppmann](https://dataintensive.net/)