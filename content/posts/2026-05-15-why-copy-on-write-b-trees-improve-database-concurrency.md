---
title: "Why Copy on Write B-Trees Improve Database Concurrency"
date: "2026-05-15T06:00:11.250"
draft: false
tags: ["databases", "b-trees", "concurrency", "copy-on-write", "mvcc"]
description: "Copy‑on‑write B‑trees let databases serve concurrent reads and writes without locking, boosting throughput and simplifying crash recovery for modern workloads."
summary: "Copy‑on‑write B‑trees enable high‑concurrency database operations by allowing readers to see a stable snapshot while writers modify a new version of the tree. The article explains the underlying mechanics, performance benefits, and practical implementation tips."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-why-copy-on-write-b-trees-improve-database-concurrency.svg"
  alt: "Diagram of a B-Tree node being duplicated on write."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑write (COW) B‑trees let a database keep multiple immutable versions of its index structure side‑by‑side, so readers can work on a stable snapshot while writers create a new version. This eliminates most lock contention, improves throughput, and simplifies crash recovery.

Modern applications demand thousands of concurrent transactions, yet traditional B‑tree indexes rely on heavy lock coupling that stalls readers whenever a writer modifies a page. By treating each node as immutable and allocating a fresh copy on every update, COW B‑trees turn a single mutable structure into a versioned data structure that naturally supports multi‑version concurrency control (MVCC). The result is higher concurrency, simpler recovery, and predictable performance even under write‑heavy workloads.

## The Problem with Traditional B‑Tree Concurrency

### Lock‑Based Approaches

Conventional B‑tree implementations protect pages with latches (short‑lived mutexes) or locks (longer‑lived). A typical write path looks like this:

1. Acquire an exclusive latch on the target leaf page.
2. Modify the page (insert, delete, split).
3. Release the latch.

If a reader needs to scan the same leaf, it must acquire a shared latch. When a writer holds the exclusive latch, all readers block until the write finishes. In high‑traffic systems this leads to *latch contention*, where the CPU spends cycles waiting rather than doing useful work.

### Write‑Ahead Logging Overhead

To guarantee durability, most databases write a *redo* record to a write‑ahead log (WAL) before modifying the page on disk. The WAL adds latency and, more importantly, forces the system to keep *in‑flight* pages in memory until they are safely flushed. This coupling of logging and page modification further magnifies contention, especially when many concurrent transactions generate interleaved log writes.

## Copy‑on‑Write B‑Trees: Core Concepts

### Immutable Nodes and Versioning

In a COW B‑tree, every node is treated as **immutable** once it is part of a version. When a transaction wants to insert a key, it does not modify the existing leaf. Instead, it:

1. Allocates a new leaf node that contains the original entries plus the new key.
2. Copies the parent node, updating the child pointer to the new leaf.
3. Recursively copies ancestors up to the root, creating a new root version.

The old version remains untouched, allowing any transaction that started before the write to continue reading from the previous root. This process is often called *path copying*.

### Structural Sharing

Because only the nodes along the modified path are duplicated, the majority of the tree is **shared** between versions. If a write only touches a single leaf, the rest of the tree (potentially millions of nodes) stays the same, saving both memory and I/O. Structural sharing is the key to making COW B‑trees practical for large indexes.

## How COW Enables Concurrency

### Multi‑Version Concurrency Control (MVCC)

COW B‑trees are a natural fit for MVCC because each committed transaction can be associated with a **snapshot root**. Readers simply follow the root pointer that corresponds to the transaction’s start timestamp. Since the tree nodes they traverse never change, there is no need for read latches.

> “MVCC works by providing each transaction with a consistent view of the database at a particular point in time.” – as described in the [PostgreSQL documentation](https://www.postgresql.org/docs/current/mvcc.html).

### Reader‑Writer Isolation without Locks

Because writers allocate new nodes rather than updating existing ones, they never block readers. The only synchronization required is to publish the new root atomically—usually a single pointer store with a memory barrier. This *single‑writer* rule can be enforced with a lightweight compare‑and‑swap (CAS) operation, eliminating the need for heavyweight latch managers.

## Real‑World Implementations

### PostgreSQL’s B‑Tree Indexes

PostgreSQL uses a variant of COW for its B‑tree indexes. When a page split occurs, the new pages are written to disk while the old pages remain readable for in‑flight transactions. The index’s *visibility map* combined with the WAL ensures that readers can still access the original pages until they are no longer needed. See the detailed description in the [PostgreSQL internals docs](https://www.postgresql.org/docs/current/indexes-types.html).

### RocksDB and LSM Trees

Although RocksDB is built on a Log‑Structured Merge (LSM) tree rather than a traditional B‑tree, it employs a similar COW philosophy at the **SSTable** level. New immutable files are created for each flush, and compaction generates fresh files without overwriting existing ones. This design enables high write throughput while providing consistent reads, as explained in the [RocksDB documentation](https://rocksdb.org/).

### SQLite’s WAL and B‑Tree

SQLite’s write‑ahead logging mode stores changes in a separate WAL file, and its B‑tree pages are treated as immutable until a checkpoint merges them back into the database file. The combination of WAL and COW‑style page handling gives SQLite strong concurrency guarantees without the overhead of a full MVCC engine. More information can be found in the [SQLite WAL documentation](https://sqlite.org/wal.html).

## Performance Considerations

### Memory Overhead

Each write allocates new nodes, which can increase memory pressure. However, because only the modified path is copied, the overhead is proportional to **O(log N)** per write, where *N* is the number of keys. Modern allocators and slab caches mitigate fragmentation, and reclaimed nodes from old versions can be recycled after the oldest active transaction completes.

### Write Amplification

COW introduces *write amplification*: a single logical insert may cause multiple physical page writes (leaf + ancestors). In practice, the amplification factor is bounded by the tree height (typically 3–5 for gigabyte‑scale indexes). Techniques such as *batching* multiple inserts into a single copy operation can reduce the effective amplification.

### Cache Locality

Since new nodes are freshly allocated, they are likely to be placed in the CPU cache, improving locality for the writer. Readers, on the other hand, continue to access the old nodes, which may have been evicted. Nevertheless, because most reads are served from the shared upper levels of the tree (root, internal nodes), cache misses are limited.

## Implementation Sketch in Python

Below is a minimal, educational implementation of a COW B‑tree node and an insert operation. It omits many production concerns (disk I/O, concurrency primitives) but demonstrates the core idea of path copying.

```python
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_KEYS = 4  # Small order for simplicity


@dataclass(frozen=True)
class Node:
    """Immutable B‑tree node."""
    keys: Tuple[int, ...] = field(default_factory=tuple)
    children: Tuple[Optional["Node"], ...] = field(default_factory=tuple)
    leaf: bool = True

    def is_full(self) -> bool:
        return len(self.keys) >= MAX_KEYS

    def split(self) -> Tuple[int, "Node", "Node"]:
        """Split a full node and return (median, left, right)."""
        mid = len(self.keys) // 2
        median = self.keys[mid]
        left = Node(keys=self.keys[:mid],
                    children=self.children[:mid + 1],
                    leaf=self.leaf)
        right = Node(keys=self.keys[mid + 1:],
                     children=self.children[mid + 1:],
                     leaf=self.leaf)
        return median, left, right


def insert(root: Node, key: int) -> Node:
    """Insert `key` into the tree, returning a new root."""
    if root.is_full():
        # Split the root and create a new internal node.
        median, left, right = root.split()
        new_root = Node(keys=(median,),
                        children=(left, right),
                        leaf=False)
        return _insert_non_full(new_root, key)
    else:
        return _insert_non_full(root, key)


def _insert_non_full(node: Node, key: int) -> Node:
    """Recursive helper that assumes `node` is not full."""
    if node.leaf:
        # Insert into the leaf's key tuple, preserving order.
        new_keys = tuple(sorted(node.keys + (key,)))
        return Node(keys=new_keys, children=(), leaf=True)

    # Locate child to descend.
    idx = 0
    while idx < len(node.keys) and key > node.keys[idx]:
        idx += 1
    child = node.children[idx]

    # If the child is full, split it first.
    if child.is_full():
        median, left, right = child.split()
        # Build a new internal node with the split results.
        new_keys = node.keys[:idx] + (median,) + node.keys[idx:]
        new_children = (
            node.children[:idx] + (left, right) + node.children[idx + 1:]
        )
        new_node = Node(keys=new_keys, children=new_children, leaf=False)
        # Decide which side to descend into.
        if key > median:
            idx += 1
        child = new_node.children[idx]
        return _insert_non_full(new_node, key)
    else:
        # Recurse without splitting.
        new_child = _insert_non_full(child, key)
        new_children = node.children[:idx] + (new_child,) + node.children[idx + 1:]
        return Node(keys=node.keys, children=new_children, leaf=False)
```

**Explanation of the sketch**

* The `Node` dataclass is frozen, making each instance immutable.
* `insert` checks whether the root is full; if so, it creates a new root (the classic B‑tree split‑root case) and proceeds.
* `_insert_non_full` performs path copying: every time a child is replaced, a new parent node is constructed with the updated child pointer, leaving the original parent untouched.
* The algorithm mirrors the textbook B‑tree insertion but adds the immutable‑node discipline that enables concurrent readers to keep using the old version.

In a real database, the new root would be atomically published (e.g., using `std::atomic<Node*>` in C++), and a garbage collector would reclaim nodes once no active transaction references them.

## Key Takeaways

- **Immutable nodes** eliminate the need for read latches; readers work on a stable snapshot.
- **Path copying** confines write‑side work to `O(log N)` nodes, keeping memory overhead modest.
- **Atomic root publication** provides lock‑free hand‑off from writer to readers, dramatically reducing contention.
- **Structural sharing** means most of the tree remains in place across versions, preserving cache efficiency.
- Real‑world systems (PostgreSQL, RocksDB, SQLite) already rely on COW principles to achieve high concurrency and reliable crash recovery.

## Further Reading

- [PostgreSQL B‑Tree Indexes](https://www.postgresql.org/docs/current/indexes-types.html) – detailed description of PostgreSQL’s index architecture and MVCC handling.  
- [RocksDB – A High Performance Embedded Database](https://rocksdb.org/) – explains how RocksDB’s LSM design uses immutable files for concurrency.  
- [SQLite Write‑Ahead Logging](https://sqlite.org/wal.html) – covers SQLite’s WAL mode and its interaction with B‑tree pages.  
- [Copy‑on‑Write (COW) – Wikipedia](https://en.wikipedia.org/wiki/Copy-on-write) – general overview of the COW technique across operating systems and data structures.  
- [IBM Db2 – Copy‑on‑Write Architecture](https://www.ibm.com/docs/en/db2/11.5?topic=technology-copy-on-write) – a commercial example of COW applied to database storage.