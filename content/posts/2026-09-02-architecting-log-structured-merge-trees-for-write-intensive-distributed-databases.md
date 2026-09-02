---
title: "Architecting Log-Structured Merge Trees for Write-Intensive Distributed Databases"
date: "2026-09-02T03:00:46.783"
draft: false
tags: ["distributed-systems", "databases", "lsm-tree", "storage-engine", "system-design"]
description: "A practical deep dive into LSM-tree architecture for write-heavy distributed databases, covering compaction, Bloom filters, and real-world tuning in RocksDB and Cassandra."
summary: "How modern distributed databases turn the write-amplification problem into a throughput advantage, and what it costs you on the read path."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-architecting-log-structured-merge-trees-for-write-intensive-distributed-databases.svg"
  alt: "Diagram of a log-structured merge tree with memtable, immutable memtables, and SSTable levels on disk."
  caption: ""
  relative: false
---

> **TL;DR** — Log-Structured Merge (LSM) trees trade read amplification and write amplification for blazing sequential writes, which is exactly the bargain distributed databases like Cassandra, ScyllaDB, and the storage engines behind Kafka and TiDB need. Getting the architecture right means tuning memtable sizing, compaction strategy (leveled vs. size-tiered), and Bloom filters as a unit — not as independent knobs.

## Why Write-Intensive Systems Don't Use B-Trees

The classic B-tree was designed in an era when memory was scarce and random I/O dominated. It optimizes beautifully for reads: a balanced tree with high fanout gives you O(log n) lookups with at most a handful of disk seeks, and the buffer pool keeps the hot interior nodes resident. Writes, however, are a nightmare. Every insert is an in-place update, which means:

- You must locate the leaf page (random read).
- You must modify it in place (random write).
- You must traverse back up and split or rebalance if the page is full.

In a write-intensive distributed database — think time-series ingestion, clickstream events, ad impressions, IoT telemetry — the workload can easily exceed 100k writes/sec per node. B-trees collapse under that pressure because every write is a small random I/O, and flash storage wears out fast under random write patterns. You need a different shape.

That shape is the LSM tree, and it has been quietly winning the storage engine wars since [Google's Bigtable paper](https://research.google/pubs/the-bigtable-a-distributed-storage-system-for-structured-data/) (2006) put it on the map.

## The Anatomy of an LSM Tree

An LSM tree is really three cooperating structures:

1. **Memtable** — an in-memory sorted data structure (typically a skip list or red-black tree). All writes land here first.
2. **Immutable memtable** — a frozen copy of the memtable waiting to be flushed to disk.
3. **SSTables (Sorted String Tables)** — immutable, sorted files on disk, organized into levels.

The flow looks like this: a write enters the memtable, which is sorted by key. When the memtable fills up (say at 64 MB), it becomes immutable and a fresh memtable takes its place. In the background, the immutable memtable is flushed to disk as a new SSTable at Level 0.

Reads are the price you pay. To find a key, the engine must check:

- The active memtable.
- Any immutable memtables waiting to flush.
- Every level of SSTables, from newest to oldest, until it finds the key or runs out of levels.

Naively that's terrible. Every read could touch every level. So the real engineering question is: **how do you keep read amplification under control while still writing fast?**

## Compaction: The Heart of an LSM

Compaction is the background process that merges SSTables, drops tombstones and overwritten values, and reshapes the on-disk layout. It's also where the two dominant strategies diverge.

### Size-Tiered Compaction (STCS)

Used by **Cassandra**, **HBase**, and earlier RocksDB configurations. SSTables are grouped by approximate size, and when a group fills, all its SSTables are merged into one roughly twice the size.

- **Pros**: Excellent write amplification (close to 1x in steady state), great for pure write throughput.
- **Cons**: Poor read amplification, because each level can contain a wide key range. Bloom filters help, but each query still touches more files than necessary.
- **When to use it**: Pure append-mostly workloads where reads are point-in-time or rely on time-based partitioning. Cassandra's default for time-series workloads for a reason.

### Leveled Compaction (LCS)

Used by **RocksDB** (the engine inside CockroachDB, TiKV, and many more), **LevelDB**, and the storage layer of **FasterKV** in Microsoft's FASTER. SSTables are organized into levels where each level's total size is ~10x the previous one, and crucially, **non-overlapping key ranges within a level**.

- **Pros**: Excellent read amplification (each level multiplies your key range by ~10, so you touch at most one SSTable per level per lookup).
- **Cons**: Higher write amplification (typically 10–30x), because every write propagates through multiple levels.
- **When to use it**: Read-heavy or mixed workloads where point lookups, range scans, and predictable latency matter.

There's also a middle ground: **universal compaction** (a hybrid), and tiered/leveled variants like the [Tiered+Leveled approach in ScyllaDB](https://www.scylladb.com/2023/04/13/tiered-storage-compaction-explained/) that try to give you the best of both worlds. ScyllaDB in particular ships an "incremental compaction" scheme where SSTables don't get rewritten wholesale — they get reshuffled incrementally, dramatically reducing write amplification while keeping read performance acceptable.

## Bloom Filters and the Read Path

A Bloom filter is a probabilistic structure that says "definitely not in this file" or "maybe in this file" with a tunable false-positive rate. Every SSTable carries one.

When a read comes in, the engine queries the memtable, then walks levels from newest to oldest. At each level, it asks the Bloom filter: *could this key be in this SSTable?* If the filter says no, we skip the file entirely. If it says yes, we do a real lookup (binary search into a sparse index, then scan the data block).

This is why tuning Bloom filter bits-per-key is a first-class architectural decision. The classic tradeoff:

- **10 bits/key**: ~1% false-positive rate. Reasonable default. Doubles to ~20 for ~0.1%.
- **Memory cost**: 10 bits per key means a 64 GB LSM with ~10 billion entries has ~12.5 GB of Bloom filters. That memory competes with block cache.
- **CPU cost**: Hashing on every read. A heavier filter with more hash functions means more CPU per negative lookup.

In RocksDB you configure this with `bloom_bits` per level, and a common production pattern is to use a larger filter (more bits) at L0 and L1 — where files are small and many — and a smaller filter at deeper levels, where files are large and most reads are caught by earlier levels. [The RocksDB wiki](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) goes into this in more detail.

## Memtable Design: Skip Lists, Concurrent Inserts, and the WAL

The memtable is where every write lands, and it's where you make your latency budget. Two decisions matter most.

**Concurrent insertions.** The original LevelDB used a skip list because it supports lock-free concurrent inserts using atomic compare-and-swap on the next pointers. RocksDB inherited this. C++'s `std::skip_list` doesn't exist, so RocksDB rolled its own. The advantage: you don't serialize writers behind a mutex. Throughput scales linearly with cores up to a point.

**Write-Ahead Log (WAL).** Before a write is acknowledged to the client, it's appended to a sequential WAL file on disk. This is the durability guarantee. The WAL is also the only place in an LSM where you're doing synchronous I/O on the write path, so it's a hot spot. Tuning options:

- **Group commit**: batch multiple client writes into one WAL append. Critical for throughput.
- **fsync frequency**: fsync every write (safest, slowest) vs. every N milliseconds (faster, but you can lose up to N ms of writes on a crash). [Kafka's design](https://kafka.apache.org/documentation/#design) does something similar with its `log.flush.interval.messages` and `log.flush.interval.ms`.
- **WAL on separate disk**: the WAL is the most latency-sensitive I/O, so production deployments often put it on its own SSD or even a battery-backed RAID controller.

When the memtable fills, it gets flushed to disk as a new L0 SSTable, and the WAL can be deleted. This is the key to LSM's write throughput: the synchronous I/O is sequential, and it's amortized over many writes.

## Patterns in Production

Let's ground this in real systems.

**Cassandra's write path.** A write to Cassandra hits the commit log (WAL), then the memtable. When the memtable exceeds `memtable_total_space_in_mb` (default 2048 MB), it's flushed to disk as an SSTable. Compaction merges SSTables according to the configured strategy (`STCS`, `LCS`, or `TWCS` — time-windowed compaction, which is excellent for time-series because it creates one SSTable per time bucket and drops whole buckets on TTL expiry). The [DataStax compaction documentation](https://docs.datastax.com/en/cassandra-oss/3.x/cassandra/operations/opsConfigureCompaction.html) is a good practical reference.

**TiKV / TiDB's storage.** TiKV uses RocksDB with leveled compaction. Each Region (TiKV's replication unit, like a HBase Region) has its own RocksDB instance. Compaction pressure is one of the major operational headaches at scale, and TiKV ships with extensive metrics around `rocksdb.compaction.pending.bytes` and `rocksdb.num.files-at-level{N}` to help operators tune the shape.

**Kafka's log segments.** Kafka isn't usually described as an LSM, but its log segments are essentially the same idea: append-only sequential writes, periodic compaction of "cleaned" topics to remove tombstones, and a tiered storage option in [Confluent's tiered storage](https://docs.confluent.io/platform/current/kafka/tiered-storage.html) that mirrors the SSTable-on-cheap-disk pattern.

**FasterKV and the FASTER project.** Microsoft's FASTER goes one step further with a hybrid log that combines in-memory and on-disk records, supporting both read modes (cache-friendly vs. disk-friendly) and a concurrent prefix hash index. The [FASTER paper](https://www.microsoft.com/en-us/research/project/fa/) is worth reading for anyone serious about state-of-the-art LSM design.

## The Costs You Don't See on the Whiteboard

LSM trees are not free. Three costs deserve explicit attention.

**Write amplification (WAF).** A single logical write might be rewritten 10–30 times before it's deeply buried in a leveled LSM. Flash storage has a finite write endurance, and high WAF directly shortens SSD lifespan. The RocksDB community tracks this carefully; one widely cited production number is that a high-throughput RocksDB instance can hit WAF of 20–50x on a write-heavy workload with default leveled compaction settings.

**Space amplification (SAF).** Because old SSTables can't be deleted until a key is rewritten at a deeper level (or until a tombstone is compacted away), an LSM can use significantly more disk than the logical dataset. STCS is worst here. Monitoring `rocksdb.estimate-live-data-size` versus `rocksdb.size-all-mem-tables` gives you the ratio.

**Compaction stalls.** When compaction can't keep up with the write rate, L0 file count grows, reads slow down, and worst case, writes block until compaction catches up. This is the most common production incident for LSM-based systems. You address it by adding capacity, tuning `max_background_jobs`, switching compaction strategy, or — in extreme cases — using [rate limiting](https://github.com/facebook/rocksdb/wiki/Compaction-IO-and-CPU-budgets) to throttle the compaction itself.

A useful mental model: an LSM is a queue with merging. If you put more in than you merge out, the queue grows. If the queue grows unbounded, reads collapse and eventually writes stall. Every architectural decision is about managing that queue.

## A Tuning Checklist for Production

When you're deploying an LSM-based system in anger, these are the levers that matter most.

1. **Pick the compaction strategy to match the workload.** Time-series with TTL → TWCS or STCS. Mixed OLTP → LCS. Pure append → STCS. Don't use the default without thinking about it.
2. **Size the memtable to absorb write bursts.** Bigger memtables mean fewer flushes and better write throughput, but longer recovery time on restart (you have to replay the WAL). 64–256 MB is a common range.
3. **Set Bloom filter bits per level.** Heavier filters at shallow levels, lighter at deep levels.
4. **Tune compaction concurrency.** `max_background_jobs` in RocksDB, or `compaction_throughput_mb_per_sec` if you want to rate-limit.
5. **Separate WAL and data disks.** WAL is latency-sensitive sequential I/O; SSTable writes are throughput-sensitive; reads are random. They want different storage.
6. **Monitor the L0 file count.** Rising L0 count is the canary that compaction is falling behind. In RocksDB, alert on `rocksdb.num-files-at-level0` crossing a threshold (often 20–30 for leveled).
7. **Set tombstone TTLs explicitly.** A delete in an LSM is a write — a tombstone. Until compaction runs, that tombstone hides the row. Configure `gc_grace_seconds` (Cassandra) or equivalent so the system doesn't accumulate tombstones forever.

## Key Takeaways

- LSM trees turn random writes into sequential writes by buffering in memory and flushing sorted runs to disk, at the cost of higher read and write amplification.
- The compaction strategy is the single most important architectural decision. STCS, LCS, and hybrids like TWCS each have distinct read/write/space amplification profiles.
- Bloom filters are not optional. They are the mechanism that keeps read amplification bounded, and they cost real memory and CPU.
- The memtable plus WAL is the synchronous, latency-sensitive write path. Every other part of the LSM is asynchronous background work, and the system's health depends on that background work keeping up.
- In production, you manage an LSM by monitoring the queue — pending compactions, L0 file counts, live data size — not by tuning individual files.

## Further Reading

- [The Bigtable paper — Google Research](https://research.google/pubs/the-bigtable-a-distributed-storage-system-for-structured-data/) — the original description of the log-structured merge tree in a distributed context.
- [RocksDB Tuning Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) — the practical reference for anyone operating RocksDB at scale.
- [ScyllaDB's Incremental Compaction Strategy](https://www.scylladb.com/2023/04/13/tiered-storage-compaction-explained/) — a modern hybrid approach that reduces write amplification significantly.
- [The Design of the FASTER Key/Value Store](https://www.microsoft.com/en-us/research/project/fa/) — Microsoft's research on pushing the LSM/hybrid-log model further.
- [DataStax Compaction Documentation](https://docs.datastax.com/en/cassandra-oss/3.x/cassandra/operations/opsConfigureCompaction.html) — practical Cassandra compaction tuning, including TWCS for time-series.
- [Confluent Tiered Storage for Apache Kafka](https://docs.confluent.io/platform/current/kafka/tiered-storage.html) — see how a different system applies log-structured thinking to streaming storage.