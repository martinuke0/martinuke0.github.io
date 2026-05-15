---
title: "Why LSM Trees Outperform B-Trees for Write Heavy Workloads"
date: "2026-05-15T02:00:11.363"
draft: false
tags: ["LSM", "B-Tree", "databases", "write performance", "storage engines"]
description: "An in‑depth look at why log‑structured merge‑trees (LSM) consistently beat B‑trees on write‑heavy workloads, covering architecture, compaction, and real‑world trade‑offs."
summary: "The article explains the fundamental design of LSM trees, contrasts them with B‑trees for write‑intensive scenarios, and outlines when each structure shines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-why-lsm-trees-outperform-b-trees-for-write-heavy-workloads.svg"
  alt: "Diagram comparing LSM tree levels with a B‑tree node hierarchy."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees batch writes into sequential logs and defer expensive re‑writes through background compaction, giving them far higher throughput than B‑trees on write‑heavy workloads. The trade‑off is higher read latency and more storage overhead, which can be mitigated with bloom filters and tiered caching.

Write‑intensive applications—time‑series databases, log aggregation services, and key‑value stores—often hit a performance ceiling with traditional B‑tree indexes. The root cause is the random‑write nature of B‑trees: each insert or update may trigger a page split, a disk seek, and a write‑ahead log flush. Log‑Structured Merge (LSM) trees were invented to turn those random writes into sequential appends, letting the storage medium operate where it is strongest. In this post we unpack the mechanics of both structures, compare their write paths, and explore the practical consequences for system designers.

## How LSM Trees Work

An LSM tree consists of a hierarchy of immutable, sorted files (often called *levels* or *tiers*) plus a small mutable component called the *memtable*. The basic workflow is:

1. **Write to Memtable** – Incoming key‑value pairs are inserted into an in‑memory balanced tree (usually a skip list or a red‑black tree).  
2. **Flush to Disk** – When the memtable reaches a size threshold, it is frozen and written to disk as a sorted string table (SSTable).  
3. **Compaction** – Background processes merge overlapping SSTables from lower levels into higher ones, discarding obsolete versions and tombstones.

Because the memtable is in memory, writes are essentially O(1) amortized: they only involve a pointer update and a possible memory allocation. The expensive part—writing to persistent storage—happens as a single sequential I/O operation, which SSDs and modern HDDs handle far more efficiently than scattered writes.

### Example: Simple Write Path in Python

```python
class LSMTree:
    def __init__(self, memtable_limit=4_000_000):
        self.memtable = {}
        self.mem_limit = memtable_limit
        self.sstables = []          # List of on‑disk sorted files

    def put(self, key, value):
        self.memtable[key] = value
        if self._memtable_size() >= self.mem_limit:
            self._flush_memtable()

    def _memtable_size(self):
        # Rough estimate: sum of key/value byte lengths
        return sum(len(k) + len(v) for k, v in self.memtable.items())

    def _flush_memtable(self):
        sorted_items = sorted(self.memtable.items())
        filename = f"sstable_{len(self.sstables)}.sst"
        with open(filename, "w") as f:
            for k, v in sorted_items:
                f.write(f"{k}\t{v}\n")
        self.sstables.append(filename)
        self.memtable.clear()
```

The `put` operation never touches disk until the memtable limit is exceeded, at which point a *single* sequential write creates a new SSTable. Real‑world implementations (RocksDB, LevelDB, Cassandra) add checksums, compression, and index blocks, but the core idea stays the same.

## B‑Tree Write Path

B‑trees store data in a balanced hierarchy of pages (or nodes) that are kept partially full to guarantee logarithmic depth. The write algorithm looks like this:

1. **Locate Leaf Page** – A binary search descends from the root to the appropriate leaf node.  
2. **Insert / Update** – If the leaf has free slots, the key/value is added and the page is marked dirty.  
3. **Page Split** – If the leaf is full, it is split into two pages, and a new key is promoted to the parent. This may cascade up to the root, possibly creating a new level.  
4. **Write‑Ahead Log (WAL)** – Before any page is flushed, the change is recorded in the WAL to guarantee durability.  
5. **Flush Dirty Pages** – Eventually the dirty pages are written back to disk, often in a random order.

Because each insert can require a *read* (to locate the leaf) plus a *write* (to modify the leaf) plus possible *split* I/Os, the per‑operation cost is dominated by random disk seeks. Even on SSDs, which have lower latency than spinning disks, the write amplification caused by splits and copy‑on‑write can be significant.

### Example: B‑Tree Insert (Pseudo‑SQL)

```sql
BEGIN;
INSERT INTO kv_store (key, value) VALUES ('user:123', 'Alice');
COMMIT;
```

Behind the scenes the DBMS writes an entry to its WAL, then modifies the leaf page in the B‑tree. If the leaf was already full, additional pages are allocated and the parent node is updated. The overall latency is roughly the sum of several random I/Os.

## Comparing Write Patterns

| Aspect | LSM Tree | B‑Tree |
|--------|----------|--------|
| **Write locality** | Sequential (memtable flush, SSTable writes) | Random (leaf page updates) |
| **Amortized cost per write** | O(1) in‑memory + occasional O(N) compaction | O(log N) page reads + possible O(log N) page splits |
| **Write amplification** | Controlled by compaction strategy (size‑tiered, leveled) | Often 2×–4× due to copy‑on‑write and split |
| **Latency spikes** | Flush or compaction may pause writes, but can be throttled | Split can cause immediate latency spike |
| **Durability path** | WAL + memtable flush (fsync) | WAL + page write (fsync) |

### Real‑World Numbers

- **RocksDB** (LSM) can sustain >1 M writes/sec on a single NVMe drive when using size‑tiered compaction and a 64 MiB memtable.  
- **PostgreSQL** (B‑tree) typically peaks around 150–200 k writes/sec on the same hardware, with latency increasing sharply as the index fills.

These figures are consistent across benchmarks such as the YCSB workload A (write‑only) and have been reported in the literature (see the original LSM paper by O'Neil et al., 1996, and subsequent RocksDB performance studies).

## Trade‑offs and When to Choose

While LSM trees dominate on pure write throughput, they are not a universal replacement for B‑trees. The main downsides are:

1. **Read Amplification** – A point query may need to probe multiple SSTables (often 3–5 levels). Bloom filters mitigate this but add memory overhead.  
2. **Storage Overhead** – Compaction temporarily duplicates data; the on‑disk size can be 1.5×–2× the logical dataset.  
3. **Complexity** – Implementing reliable compaction, handling tombstones, and tuning level size ratios require expertise.

B‑trees excel when:

- **Read‑Heavy Workloads** – Low read latency and single‑page lookup.  
- **Range Queries** – Ordered scans are efficient because data resides in contiguous leaf pages.  
- **Transactional Guarantees** – Fine‑grained locking and MVCC are easier to integrate with traditional B‑tree indexes.

### Hybrid Approaches

Some systems blend both structures:

- **Cassandra** uses an LSM primary store but maintains secondary indexes as B‑trees.  
- **MySQL InnoDB** (B‑tree) can be combined with a write‑optimized log (binary log) for replication, but the core index remains B‑tree.

Choosing the right engine often comes down to the **write‑to‑read ratio** and **acceptable latency variance**. A rule of thumb:

- **Write > 70 %** → LSM, with adequate RAM for bloom filters.  
- **Read > 70 %** → B‑tree, unless range scans dominate and can tolerate higher write cost.

## Key Takeaways

- **Sequential writes** are the secret sauce: LSM trees turn random inserts into large, contiguous disk writes, dramatically reducing latency and I/O cost.  
- **Compaction** trades write efficiency for read amplification; proper tuning (size‑tiered vs. leveled) is essential to keep read latency acceptable.  
- **B‑trees** still win for read‑heavy or range‑query‑centric workloads because they keep data in a single, ordered structure.  
- **Memory matters**: Bloom filters and a sufficiently large memtable are critical to realize LSM’s write advantage without exploding read cost.  
- **Real‑world systems** (RocksDB, Cassandra, HBase) demonstrate that LSM trees are the de‑facto choice for modern high‑throughput services, while relational databases continue to rely on B‑trees for OLTP workloads.

## Further Reading

- [Log‑structured merge‑tree – Wikipedia](https://en.wikipedia.org/wiki/Log-structured_merge-tree)  
- [RocksDB – Official Site](https://rocksdb.org)  
- [Apache Cassandra – Architecture Overview](https://cassandra.apache.org/_/index.html)  
- [B‑tree – Wikipedia](https://en.wikipedia.org/wiki/B-tree)  
- [PostgreSQL Documentation – Index Types](https://www.postgresql.org/docs/current/indexes-types