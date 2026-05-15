---
title: "Why Log Structured Merge Trees Outperform B‑Trees for Writes"
date: "2026-05-15T10:00:10.992"
draft: false
tags: ["LSM", "B-Tree", "databases", "write performance", "storage engines"]
description: "Log‑Structured Merge (LSM) trees dramatically reduce write amplification compared to B‑trees, making them ideal for high‑throughput workloads in modern databases."
summary: "LSM trees batch writes into immutable files, avoiding costly in‑place updates that B‑trees require. This post explains the mechanics behind their superior write performance."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-why-log-structured-merge-trees-outperform-btrees-for-writes.svg"
  alt: "Diagram comparing LSM tree layers with B‑tree nodes."
  caption: ""
  relative: false
---

> **TL;DR** — LSM trees turn random writes into sequential appends, dramatically lowering write amplification and I/O overhead. B‑trees, by contrast, perform many in‑place updates and page splits, which become a bottleneck under write‑heavy workloads.

Modern data stores—key‑value stores, time‑series databases, and many NoSQL systems—have all migrated from traditional B‑tree‑based storage engines to Log‑Structured Merge (LSM) trees. The shift is not a fad; it is driven by concrete, measurable advantages in how each structure handles writes. In this article we break down the internal mechanics of B‑trees and LSM trees, compare their write paths step‑by‑step, and quantify why LSM trees consistently outperform B‑trees for write‑intensive workloads.

## How B‑Trees Handle Writes

B‑trees have been the workhorse of relational databases for decades. Their balanced, multi‑level node structure enables logarithmic‑time point reads and range scans, but the same structure introduces hidden costs when inserting or updating data.

### In‑Place Updates and Page Splits

When a new key/value pair arrives, the engine locates the leaf page that should contain the key. If there is free space on that page, the record is written *in place*. If the page is full, the engine must:

1. **Split the page** – create two new pages, redistribute the records, and update the parent index node.
2. **Propagate the split** – if the parent is also full, the split bubbles up recursively, potentially all the way to the root.
3. **Write‑ahead logging (WAL)** – before any modification hits the data file, the change is recorded in a sequential log for durability.

Each split incurs additional I/O: two new pages, an updated parent, and possibly a new root. The total write amplification can be 2‑4× the original data size, especially under high write concurrency. Moreover, because pages are updated *in place*, the underlying storage cannot take advantage of sequential write patterns, leading to fragmented writes on HDDs or reduced parallelism on SSDs.

### Write Amplification in Practice

Consider a workload that inserts 1 GB of sorted keys into a B‑tree with a leaf page size of 16 KB. Roughly every 16 KB the leaf fills and triggers a split, causing an extra 16 KB write for the new sibling page and a parent update. The cumulative extra I/O quickly exceeds the original 1 GB payload, and the same data may be rewritten multiple times as higher‑level nodes split.

## Fundamentals of Log‑Structured Merge Trees

LSM trees were introduced in the early 1990s to address exactly these write‑path inefficiencies. The core idea is simple: **never modify data in place**. Instead, writes are appended to immutable structures that are later merged in the background.

### Immutable Sorted Runs

An LSM tree consists of multiple *levels* (often called *tiers*). The lowest level, **Level 0 (L0)**, is an in‑memory structure—commonly a sorted tree such as a skip list or a red‑black tree. When L0 reaches a configurable size threshold (e.g., 64 MB), it is flushed to disk as an immutable *sorted run* (often an SSTable). Subsequent runs are placed in **Level 1 (L1)**, which holds a set of non‑overlapping sorted files.

Because each run is immutable, the write path for a new key/value pair is:

1. Insert into the in‑memory tree (O(log N) but in RAM).
2. When the memory limit is hit, write the entire run to disk in a single sequential I/O operation.
3. Return to step 1.

No random page updates, no splits, and no WAL for the data itself—only the WAL for the in‑memory structure, which is far cheaper.

### Compaction Strategies

Over time, multiple runs accumulate at each level. To keep read performance acceptable, the system performs *compactions*: merging overlapping runs from a lower level into a higher level, discarding obsolete versions of keys, and rewriting a new, larger run.

Compaction is **background**, **batched**, and **sequential**:

```bash
# Example pseudo‑command for a RocksDB compaction
rocksdb --db=/data/mydb --compact_range=0,0
```

The key point is that compaction cost is amortized over many writes. The write amplification introduced by compaction is typically **2‑3×** for a well‑tuned LSM system, compared to the unpredictable 2‑4× of B‑tree page splits. Crucially, the amplification is *predictable* and *controllable* via configuration (size ratio between levels, compaction trigger thresholds).

## Write Path Comparison

| Aspect                | B‑Tree                                    | LSM Tree                                      |
|-----------------------|-------------------------------------------|-----------------------------------------------|
| Primary write target  | Leaf page (in‑place)                      | In‑memory sorted structure (append‑only)      |
| Disk I/O pattern      | Random writes, page splits                | Large sequential writes (flushes) + compaction |
| Write amplification   | 2‑4× (depends on split frequency)        | 2‑3× (configurable via level size ratios)      |
| Concurrency handling | Locks per page or node                    | Lock‑free in‑memory structure, compaction runs in background |
| Impact on SSD wear    | High (random writes)                      | Lower (sequential writes, wear‑leveling friendly) |

### Code Illustration: Flushing an L0 Run

Below is a minimal Python snippet that simulates flushing an in‑memory run to disk as a sorted file. The example emphasizes sequential I/O and immutability:

```python
import os
import json
from bisect import insort

class LSMTree:
    def __init__(self, memtable_limit=64 * 1024 * 1024, data_dir="data"):
        self.memtable = []               # list of (key, value) tuples, kept sorted
        self.memtable_limit = memtable_limit
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)
        self.run_counter = 0

    def put(self, key: str, value: str):
        # Insert while keeping memtable sorted (O(log N) for bisect)
        insort(self.memtable, (key, value))
        if self._size() >= self.memtable_limit:
            self._flush()

    def _size(self):
        # Rough byte size estimate
        return sum(len(k) + len(v) + 2 for k, v in self.memtable)

    def _flush(self):
        run_path = os.path.join(self.data_dir, f"run_{self.run_counter}.sst")
        with open(run_path, "w", encoding="utf-8") as f:
            for k, v in self.memtable:
                f.write(json.dumps({"k": k, "v": v}) + "\n")
        print(f"Flushed {len(self.memtable)} entries to {run_path}")
        self.memtable.clear()
        self.run_counter += 1

# Example usage
lsm = LSMTree(memtable_limit=1024)  # tiny limit for demo
for i in range(5000):
    lsm.put(f"user:{i}", f"value-{i}")
```

The `put` method inserts into a sorted in‑memory list; once the limit is reached, the entire list is written to a file in one pass. Real‑world engines replace the Python list with a more efficient structure (skip list, memtable) and write to a binary format (SSTable), but the principle remains identical.

## Performance Implications

### Latency vs. Throughput

Because each write only touches RAM until a flush occurs, **write latency** for individual operations is typically sub‑millisecond, independent of the underlying storage speed. Throughput scales linearly with the number of concurrent writers, limited primarily by CPU and memory bandwidth.

In contrast, B‑tree writes must wait for disk I/O on each page split, leading to higher tail latency. Even with write‑back caches, the *worst‑case* latency spikes when a split propagates to the root.

### SSD Wear and Longevity

Flash memory suffers from write amplification: each logical write may trigger multiple physical block erasures. LSM trees' sequential writes align with the SSD’s internal *erase block* size, reducing write amplification to near‑optimal levels. B‑trees, with their random writes and frequent page rewrites, increase wear, shortening SSD lifespan.

### Read‑Write Trade‑offs

Critics often point out that LSM trees make point reads slower because keys may reside in any of the multiple runs. However, modern LSM implementations mitigate this with:

- **Bloom filters** per run to quickly rule out absent keys.
- **Compaction policies** that keep the number of runs per level bounded.
- **Caching layers** (block cache, row cache) that store hot keys in memory.

The net effect is that while a single point read may involve checking a few runs, the overall *read* performance remains comparable to B‑trees for most workloads, especially when the write load dominates.

## Key Takeaways

- **Write Path Simplicity**: LSM trees convert random writes into sequential appends, eliminating page splits and in‑place updates that burden B‑trees.
- **Predictable Amplification**: Compaction‑driven write amplification is configurable and typically lower than the unpredictable amplification caused by B‑tree splits.
- **Hardware Friendliness**: Sequential I/O patterns align with SSD and HDD characteristics, reducing latency, wear, and fragmentation.
- **Scalable Concurrency**: In‑memory memtables allow lock‑free writes, while compactions run asynchronously, preserving high throughput under heavy load.
- **Read Mitigations**: Bloom filters, tiered caching, and smart compaction keep point‑read latency acceptable, making LSM trees a balanced choice for mixed workloads.

## Further Reading

- [Log‑Structured Merge‑Tree (Wikipedia)](https://en.wikipedia.org/wiki/Log-structured_merge-tree) – A concise overview of LSM tree architecture and variants.  
- [RocksDB Blog: LSM vs B‑Tree](https://rocksdb.org/blog/2020/07/15/lsm-vs-btree.html) – An in‑depth performance comparison from the creators of a popular LSM‑based store.  
- [Cockroach Labs Blog: Inside the LSM Tree](https://www.cockroachlabs.com/blog/lsm-trees/) – Practical insights into LSM implementation details and tuning tips.