---
title: "Why LSM Trees Outperform B-Trees for Write Heavy Workloads"
date: "2026-05-14T03:00:51.299"
draft: false
tags: ["lsm-trees","b-trees","databases","write-heavy","performance"]
description: "Learn why Log‑Structured Merge (LSM) trees deliver higher write throughput than B‑trees, covering compaction, write paths, and real‑world database deployments."
summary: "LSM trees excel in write‑heavy scenarios by batching writes and deferring compaction, while B‑trees suffer from random I/O. This post breaks down the mechanisms that give LSM trees their edge."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-lsm-trees-outperform-b-trees-for-write-heavy-workloads.svg"
  alt: "Illustration of a Log‑Structured Merge tree versus a B‑tree."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees achieve superior write performance by converting random writes into sequential appends and amortizing compaction costs, whereas B‑trees incur costly random I/O for each write. The trade‑off is more complex reads and background compaction, but for write‑heavy workloads the benefits dominate.

Write‑intensive applications—time‑series ingestion, logging pipelines, and high‑throughput key‑value stores—often struggle with traditional B‑tree indexes. While B‑trees have been the workhorse of relational databases for decades, the Log‑Structured Merge (LSM) tree architecture, popularized by systems like LevelDB, RocksDB, and Apache Cassandra, flips the performance equation on its head. This article dives deep into the structural differences, the write pipelines, and the real‑world consequences that make LSM trees the go‑to choice for write‑heavy workloads.

## The Fundamentals of B‑Trees

### Structure and Invariants

A B‑tree is a balanced multi‑way search tree where each node contains a sorted array of keys and child pointers. The key invariants are:

1. All leaf nodes reside at the same depth.
2. Each internal node (except the root) holds between *⌈m/2⌉* and *m* keys, where *m* is the order.
3. Keys within a node are kept sorted, enabling binary search inside the node.

Because nodes are sized to match a disk page (often 4 KB–16 KB), a single node read/write corresponds to one I/O operation. This design minimizes the number of disk seeks during read queries.

### Write Path in a B‑Tree

When inserting a new key/value pair, the algorithm:

1. Traverses from the root to the appropriate leaf (O(logₘ N) node reads).
2. Inserts the key into the leaf’s sorted array.
3. If the leaf overflows (exceeds *m* keys), it splits, propagating a split key up the tree—potentially causing a cascade of splits up to the root.

Each split requires a **random write** to disk because the affected page may be anywhere on the storage medium. In SSDs, this manifests as extra erase‑program cycles; on spinning disks, it translates to costly seek latency.

#### Example: B‑Tree Insert Pseudocode (Python)

```python
def btree_insert(root, key, value):
    leaf = traverse_to_leaf(root, key)
    leaf.keys.append((key, value))
    leaf.keys.sort(key=lambda kv: kv[0])
    if len(leaf.keys) > MAX_KEYS:
        split_node(leaf)
```

The `split_node` function writes new pages to random locations, making the write path inherently *write‑amplified*.

## The Anatomy of LSM Trees

### Core Idea

An LSM tree stores data in a series of **sorted runs** that are written sequentially. New writes first land in an in‑memory structure (often a **memtable**, typically a skip list or balanced tree). When the memtable fills, it is flushed to disk as an immutable **SSTable** (Sorted String Table). Over time, these SSTables are merged (compacted) into larger runs, preserving order.

The design mirrors a **log‑structured storage system**: writes become appends, eliminating random writes at the cost of deferred background work.

### Levels and Compaction

Most production LSM implementations organize SSTables into **levels** (L0, L1, L2, …). Level *i* contains SSTables of size roughly *Tⁱ* (where *T* is a size ratio, commonly 10). When the total size of a level exceeds its target, SSTables are selected for **compaction**:

1. Merge overlapping SSTables from level *i* with those from level *i+1*.
2. Write the merged, deduplicated output as new SSTables in level *i+1*.
3. Delete the original files.

Compaction is a **sequential read‑write** operation, making it efficient on both HDDs and SSDs.

#### Example: LSM Write Pipeline (Bash)

```bash
# Insert a record into the memtable (in‑process)
echo "key,value" >> /tmp/memtable.log

# When memtable reaches threshold, flush to disk
if [ $(stat -c%s /tmp/memtable.log) -gt $MEMTABLE_MAX ]; then
    mv /tmp/memtable.log /data/lsm/sstables/L0/$(date +%s).sst
    # Trigger background compaction
    systemctl start lsm-compactor.service
fi
```

All flushes are **append‑only**, turning random writes into sequential file creations.

## Write‑Heavy Workloads: Why LSM Wins

### 1. Sequential Appends vs. Random Writes

The primary performance win comes from converting each write into a **sequential append** to the memtable and later to an SSTable. Modern storage devices handle sequential I/O up to 10× faster than random I/O, especially on magnetic disks where seek time dominates.

| Metric               | B‑Tree (random) | LSM (sequential) |
|----------------------|------------------|------------------|
| Avg. write latency   | 4–8 ms (SSD) / 10–15 ms (HDD) | 0.3–0.7 ms (SSD) / 1–2 ms (HDD) |
| Write amplification  | 1.2–1.5×        | 2–4× (depends on compaction) |

*Source: Performance analysis in the RocksDB paper* ([RocksDB docs](https://rocksdb.org)).

### 2. Amortized Compaction Cost

Compaction introduces **write amplification**, but it is amortized over many writes. For a workload inserting 1 M keys, a B‑tree may trigger thousands of page splits, each incurring a random write. An LSM tree, however, flushes the memtable once (single sequential write) and then performs a few large sequential merges.

The amortized cost per key can be expressed as:

\[
\text{Amplification}_{\text{LSM}} \approx 1 + \frac{\log_T(N)}{B}
\]

where *T* is the level size ratio, *N* the total number of keys, and *B* the average block size. With *T = 10* and *B = 4 KB*, the extra cost stays low even for billions of keys.

### 3. Write Batching and Compression

Because LSM flushes operate on batches of thousands of entries, they can apply **compression** (e.g., Snappy, Zstd) efficiently. The compression ratio reduces the amount of data written to disk, further improving throughput.

```python
import zstandard as zstd

def compress_and_flush(memtable):
    data = b''.join(f"{k}:{v}\n".encode() for k, v in memtable.items())
    compressed = zstd.compress(data, level=3)
    with open(f"/data/lsm/L0/{int(time.time())}.sst", "wb") as f:
        f.write(compressed)
```

Batching also enables CPU‑side optimizations like vectorized sorting before the flush.

## Read Path Trade‑offs

While LSM shines on writes, reads must consult multiple levels:

1. **Memtable** – fast in‑memory lookup (O(log M)).
2. **Bloom Filters** – per‑SSTable probabilistic structures to skip non‑relevant files.
3. **Level Lookup** – at most one SSTable per level (due to non‑overlapping property), reducing I/O.

The cost can be expressed as:

\[
\text{Read\_Cost} = \underbrace{O(\log M)}_{\text{memtable}} + \underbrace{L \times (1 - \text{BF\_hit})}_{\text{disk seeks}}
\]

where *L* is the number of levels. Proper tuning of Bloom filter size (e.g., 10 bits per key) can bring false‑positive rates below 1 %, making most reads hit a single SSTable.

### Real‑World Example: Cassandra

Apache Cassandra uses an LSM design with configurable compaction strategies (Size‑Tiered, Leveled, Time‑Window). A production benchmark on a 48‑core server showed **write throughput of 300 k ops/s** versus **80 k ops/s** for a comparable B‑tree‑based PostgreSQL instance under the same workload ([Cassandra docs](https://cassandra.apache.org/doc/latest)).

## Detailed Compaction Strategies

### Size‑Tiered Compaction (STCS)

- Groups SSTables of similar size.
- Merges when a threshold of *N* files is reached.
- Less I/O but higher read amplification due to overlapping runs.

### Leveled Compaction (LCS)

- Enforces non‑overlapping runs per level.
- Guarantees at most one SSTable per level for a key.
- Higher write amplification, lower read amplification.

Choosing the right strategy depends on the workload mix. For **pure write‑heavy** scenarios, STCS often yields higher write throughput because it postpones merges, whereas LCS is preferable when **read latency** is critical.

## Performance Benchmarks

| System                | Write Throughput (ops/s) | Avg. Read Latency (ms) | Storage Used (GB) |
|-----------------------|--------------------------|-----------------------|------------------|
| RocksDB (LSM, LCS)    | 350 k                    | 0.9                   | 1.2× data size   |
| LevelDB (LSM, STCS)   | 280 k                    | 1.2                   | 1.4× data size   |
| PostgreSQL (B‑Tree)   | 85 k                     | 0.4                   | 1.0× data size   |
| MySQL InnoDB (B‑Tree) | 80 k                     | 0.5                   | 1.0× data size   |

*Sources: Benchmarks from the original LevelDB paper* ([LevelDB PDF](https://static.googleusercontent.com/media/research.google.com/en//archive/leveldb.pdf)) *and RocksDB performance guide*.

The numbers illustrate that LSM systems can sustain **3–4× higher write rates** at the cost of modestly higher read latency and extra storage for multiple SSTable generations.

## Design Considerations for Practitioners

1. **Memtable Size** – Larger memtables reduce flush frequency but increase recovery time after a crash. Typical values: 64 MB–256 MB.
2. **Bloom Filter Allocation** – Allocate ~10 bits/key for a 1 % false‑positive rate; tune based on read‑heavy vs. write‑heavy ratio.
3. **Compaction Throttling** – Limit background I/O to avoid starving foreground reads. RocksDB offers `max_background_compactions` and `rate_limit_mb_per_sec`.
4. **SSD Wear** – While LSM reduces random writes, compaction still generates write amplification. Monitoring write amplification factor (WAF) is essential for SSD longevity.
5. **Hybrid Approaches** – Some systems (e.g., MariaDB ColumnStore) blend LSM for hot data and B‑tree for cold indexes, providing balanced performance.

## Key Takeaways

- **Sequential writes** in LSM trees turn costly random I/O into fast appends, dramatically boosting write throughput.
- **Compaction** amortizes the cost of maintaining sorted order; tuning compaction strategy is critical for workload balance.
- **Read operations** may touch multiple SSTables, but Bloom filters and level organization keep overhead low.
- **Write amplification** is higher in LSM, but modern SSDs handle sequential writes efficiently, and the trade‑off is worthwhile for write‑dominant workloads.
- **Real‑world systems** like RocksDB, LevelDB, and Cassandra prove the model at scale, delivering 3–4× higher writes than traditional B‑tree engines.

## Further Reading

- [Log‑Structured Merge Tree – Wikipedia](https://en.wikipedia.org/wiki/Log-structured_merge-tree)  
- [B‑Tree – Wikipedia](https://en.wikipedia.org/wiki/B-tree)  
- [RocksDB – Official Documentation](https://rocksdb.org)  
- [LevelDB – Google Research Paper (PDF)](https://static.googleusercontent.com/media/research.google.com/en//archive/leveldb.pdf)  
- [Apache Cassandra – Architecture Overview](https://cassandra.apache.org/doc/latest)