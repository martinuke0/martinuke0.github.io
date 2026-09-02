---
title: "Implementing Bloom Filters in LSM-Trees: Reducing Read Amplification"
date: "2026-09-02T04:00:54.070"
draft: false
tags: ["lsm-tree", "bloom-filter", "storage-engine", "rocksdb", "distributed-systems"]
description: "How bloom filters power LSM-tree reads in RocksDB, Cassandra, and ScyllaDB — with sizing math, false-positive tradeoffs, and tuning tactics."
summary: "A practical deep dive into how bloom filters are integrated into LSM-tree storage engines to slash read amplification, with concrete examples from RocksDB, Cassandra, and ScyllaDB."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-implementing-bloom-filters-in-lsm-trees-reducing-read-amplification.svg"
  alt: "Diagram of an LSM-tree with bloom filters guarding each SSTable."
  caption: ""
  relative: false
---

> **TL;DR** — LSM-trees write fast but pay a steep tax on reads: a point lookup may touch every level of the sorted run stack. A per-SSTable bloom filter turns that worst case into a tight constant, dropping read amplification from O(L) to roughly 1 disk hit per level that *might* contain the key. The trick is sizing the filter correctly — too small and false positives kill you, too large and you waste memory that could fund block cache.

## The Read Problem with LSM-Trees

A log-structured merge-tree is a write-optimized data structure. New writes go to an in-memory memtable, flush into immutable sorted string tables (SSTables), and get compacted in the background. The reward is sequential writes and high throughput. The price is paid on the read side.

Consider a point lookup for a single key. The engine must consult:

1. The active memtable (and any immutable memtables being flushed).
2. The L0 SSTables, which are typically not range-partitioned and overlap.
3. Each subsequent level's sorted run, looking for the file whose key range covers the target.
4. The actual block inside that file, decoded and compared.

Worst case, a cache miss at every level means `L` SSTable reads per point query. If `L = 5` (a common compaction depth for a 10x fanout), that's five disk hits to answer "is this key present?". The mathematical name for this is *read amplification* (sometimes abbreviated R-AMP), and it is the canonical weakness of the LSM design.

A bloom filter is a probabilistic data structure that answers a single question cheaply: *"is this key definitely not in the set, or is it probably in the set?"* It never produces a false negative. It can produce a false positive, and that rate is a tunable parameter called ε (epsilon). For LSM-tree reads, that asymmetry is exactly what we want — a cheap way to *eliminate* most disk lookups.

## Bloom Filter Mechanics, Refresher

A standard bloom filter is a bit array of `m` bits, initially zero, plus `k` independent hash functions. To insert a key:

1. Hash the key with each of the `k` functions.
2. Set each of the `k` resulting bit positions to 1.

To query:

1. Hash the key with each of the `k` functions.
2. If *any* of the resulting bit positions is 0, the key is **definitely not** in the set.
3. If *all* positions are 1, the key is **probably** in the set (with probability 1 − ε).

The two design knobs are `m` (bits per entry) and `k` (hash count). Given a target false positive rate `ε` and an expected number of entries `n`, the optimal `m` and `k` are:

```
m = -n * ln(ε) / (ln(2))^2
k = (m / n) * ln(2) = -log2(ε)
```

For ε = 0.01 (1%), you need about 9.6 bits per key and 7 hash functions. For ε = 0.001 (0.1%), about 14.4 bits and 10 hashes. The cost is linear in entry count, which matters for storage engines that hold billions of keys per SSTable.

RocksDB and friends use a *blocked* or *prefix-extended* variant, but the math is the same. As [the RocksDB wiki](https://github.com/facebook/rocksdb/wiki/RocksDB-Bloom-Filter) puts it, the filter is consulted *before* any I/O is issued, so the only way an SSTable contributes to read latency is if the filter says "maybe".

## Where the Filter Sits in the Read Path

Picture a query for `user:42` arriving at the storage engine. With bloom filters, the read path collapses dramatically:

```
query(user:42)
  └─ check memtable           → hit, return value
  (cache miss below)
  └─ check L0 SSTable #1 filter → "no" (skip I/O)
  └─ check L0 SSTable #2 filter → "no" (skip I/O)
  └─ check L1 SSTable  filter  → "maybe" (read block, find key)
  └─ check L2 SSTable  filter  → "no" (skip I/O)
  └─ check L3 SSTable  filter  → "no" (skip I/O)
```

In a leveled compaction scheme, the newest version of a key is at the top level, so as soon as one filter says "maybe" and we find a tombstone or a higher version above, we can stop. In a tiered compaction scheme (used by [Cassandra's STCS](https://cassandra.apache.org/doc/latest/cassandra/operating/compaction/)) the situation is similar but with more overlapping runs per level.

The "skip the I/O" branch is where the win lives. A bloom filter lookup is a few nanoseconds against a memory-resident bit array, versus a millisecond-scale disk seek. Even at 0.1% false positive rate, 99.9% of "not present" keys cost nothing on the storage side.

## Patterns in Production

### RocksDB and the Filter Policy

RocksDB exposes `bloom_filter_policy` as a pluggable component. The default `rocksdb::NewBloomFilterPolicy(10)` uses 10 bits per key and is a reasonable baseline. For read-heavy workloads, RocksDB also ships `ribbon_filter` — a learned bloom filter variant from [the Ribbon paper](https://www.cs.cmu.edu/~dga/papers/ribbon-sigir2018.pdf) — that achieves the same false positive rate with roughly 30% less memory. Facebook's MyRocks famously runs ribbon filters because every byte of filter is a byte you can't spend on block cache.

A common production pattern is to set a per-level bits-per-key that decreases with depth:

```cpp
// L0 and L1: more bits (hotter, more overlap)
// L2+: fewer bits (colder, larger, query once per cold read)
auto policy = rocksdb::NewBloomFilterPolicy(
    /*bits_per_key=*/10,
    /*use_block_based_builder=*/true);
options.filter_policy = policy;
```

The intuition: L0 and L1 SSTables are small and frequently consulted, so over-provisioning the filter is cheap. L6 SSTables can be hundreds of GB; spending 14 bits/key on 200M keys is a real 350MB of memory.

### Cassandra and ScyllaDB

Cassandra maintains a per-SSTable bloom filter that is loaded into memory at startup. With the default `bloom_filter_fp_chance` of 0.01, a 10GB SSTable with 100M keys uses about 120MB of RAM just for its filter. ScyllaDB, which is a C++ rewrite of Cassandra's storage layer, ships a faster filter implementation and also [documents the choice carefully](https://docs.scylladb.com/manual/stable/architecture/engines/engines-bloom-filter.html) — they've found that the default 1% FP rate is a sweet spot for most workloads. Going to 0.1% doubles filter memory and only helps if your read workload is dominated by truly absent keys (think time-series with sparse tags).

### HBase and the DeletableFilter

HBase's HFile v3 format includes a "delete-on-read" bloom filter that excludes keys known to be covered by tombstones. This matters for HBase because cells have a three-dimensional schema (row, column, timestamp), and a scan of a wide row can have millions of deleted cells. The deletable filter is a real-world example of the same pattern: don't fetch what you know you don't need.

## Sizing the Filter Correctly

The most common production mistake is under-sizing. If you set 5 bits per key, your false positive rate is around 9% — which means 9 out of every 100 negative lookups will still issue a disk read, defeating most of the benefit. Use the formulas above, or a sizing calculator.

A worked example for a typical RocksDB workload:

- **SSTable size:** 256 MB
- **Average key size:** 32 bytes
- **Average value size:** 1 KB
- **Entries per SSTable:** ~244,000
- **Target FP rate:** 0.1%
- **Required bits per key:** 14.4
- **Filter size:** 244,000 × 14.4 / 8 ≈ 440 KB

That 440 KB filter, if it lives in the block cache, costs almost nothing. The same filter at 1% FP would be ~290 KB; at 10% it would be ~140 KB. The savings from going to 10% are real, but the read-amplification penalty of false positives scales with the *number of SSTables queried*, not linearly with FP rate.

A second mistake is forgetting that the filter memory competes with the block cache. The RocksDB block cache and the filter cache are typically the *same* cache (`LRUCache`). Every byte spent on filters is a byte not available for data blocks. The official [RocksDB tuning guide](https://github.com/facebook/rocksdb/wiki/Memory-usage-in-RocksDB) recommends sizing the block cache to be at least 30% of available memory for read-heavy workloads, then letting the filter share that space.

## False Positives in Practice

Let's model the cost. Suppose you have 5 levels, each with 10 SSTables, and the average per-SSTable FP rate is 1%. For a key that does **not** exist:

```
P(no false positive)  = 0.99^50 ≈ 0.605
P(at least one FP)    = 1 - 0.605 = 0.395
```

So even at 1% per filter, ~40% of negative lookups hit *some* disk. Bump FP down to 0.1%:

```
P(no false positive)  = 0.999^50 ≈ 0.951
P(at least one FP)    ≈ 0.049
```

A 4.9% disk-hit rate on negative lookups is a much more reasonable number. This is why ScyllaDB and others recommend **tightening FP rates for read-heavy workloads** — the compounding effect across many SSTables is the real driver.

For keys that **do** exist, the picture is different. The first SSTable that contains them (typically the topmost level) will return a positive, and the lookup stops. False positives below that don't add cost, because the query has already been satisfied. So FPs hurt your read amplification on *misses* far more than on *hits* — and miss-heavy workloads (caching layers, deduplication, fraud checks) are exactly the case where investing in a tighter filter pays off.

## Alternatives and Variants

Bloom filters are not the only game in town. A few worth knowing:

- **Cuckoo filters** support deletion at the cost of a more complex lookup, and they are [productionized in some systems](https://github.com/seiflotfy/cuckoofilter) for caching layers where items are evicted.
- **Quotient filters** offer better cache locality because all metadata is stored in a contiguous array — useful when the filter itself is too large for L2 cache.
- **Learned indexes / Ribbon filters** (used in newer RocksDB) replace the hash-array structure with a learned model that achieves the same FP rate with less memory.
- **Succinct range filters** (like the [SuRF paper from CMU](https://www.cs.cmu.edu/~huanche1/publications/surf_paper.pdf)) can answer range queries with a probabilistic guarantee, not just point lookups.

For most production systems today, classic bloom filters remain the right default. The variants are useful when you have specific constraints (deletion, ranges, tight memory budgets) that the default doesn't handle.

## Key Takeaways

- A per-SSTable bloom filter converts an O(L) worst-case point lookup into roughly O(1) disk hit per level that *might* contain the key — and often O(1) total.
- Filter sizing is governed by `m = -n * ln(ε) / (ln 2)^2` and `k = -log2(ε)`. The two knobs are bits per key and hash count; the trade-off is memory vs. read amplification.
- A 1% per-filter FP rate compounds badly across many levels. Read-heavy workloads with miss-heavy query shapes (caching, dedup, fraud) are best served by 0.1% or tighter.
- Filter memory competes with block cache memory. The official [RocksDB tuning guide](https://github.com/facebook/rocksdb/wiki/Memory-usage-in-RocksDB) treats them as one shared budget.
- Modern engines (RocksDB, ScyllaDB) ship optimized variants — ribbon filters, blocked filters, hardware-accelerated hashing — and the differences add up at scale.

## Further Reading

- [RocksDB Bloom Filter documentation](https://github.com/facebook/rocksdb/wiki/RocksDB-Bloom-Filter) — the canonical reference for production bloom filters in an LSM engine.
- [Designing Data-Intensive Applications, Chapter 3 (Storage and Retrieval)](https://dataintensive.net/) — Kleppmann's lucid treatment of LSM-trees and read amplification.
- [ScyllaDB Bloom Filter Architecture](https://docs.scylladb.com/manual/stable/architecture/engines/engines-bloom-filter.html) — production sizing guidance from a C++ reimplementation of Cassandra.
- [The Bloom Filter Page (University of Wisconsin)](https://www.eecs.harvard.edu/~michaelm/postscripts/im2005b.pdf) — the original Broder-Mitzenmacher survey, still the cleanest mathematical treatment.
- [Ribbon: A Learned Bloom Filter (SIGIR 2018)](https://www.cs.cmu.edu/~dga/papers/ribbon-sigir2018.pdf) — the paper behind RocksDB's ribbon filter implementation.
- [SuRF: Practical Range Query Filtering with Fast Succinct Tries (SIGMOD 2018)](https://www.cs.cmu.edu/~huanche1/publications/surf_paper.pdf) — extending probabilistic filters to ranges.