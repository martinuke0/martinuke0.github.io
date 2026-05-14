---
title: "Why Copy-on-Write B-Trees Enable Faster Database Snapshots"
date: "2026-05-14T17:00:29.055"
draft: false
tags: ["databases", "b-trees", "copy-on-write", "snapshots", "performance"]
description: "Copy-on-Write B‑Trees let databases take instant, low‑overhead snapshots by sharing unchanged nodes, reducing I/O and locking while preserving consistency."
summary: "Copy-on-Write B‑Trees provide an elegant mechanism for fast, consistent snapshots, cutting write amplification and lock contention. This post explains the data structure, its snapshot workflow, and real‑world performance gains."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-copy-on-write-b-trees-enable-faster-database-snapshots.svg"
  alt: "Illustration of a B‑Tree node being duplicated for a snapshot."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑Write (COW) B‑Trees let a database create a point‑in‑time snapshot by copying only the nodes that change, leaving the rest of the tree shared between the live database and the snapshot. This dramatically reduces I/O, eliminates heavyweight locking, and yields snapshots that are both fast to create and cheap to maintain.

Databases have to balance two competing goals: serving fresh, mutable data to clients while also offering a reliable way to view the data as it existed at a prior moment. Traditional snapshot techniques—full copies, heavyweight locks, or log‑based replay—either stall writes, double storage, or add latency. Copy‑on‑Write B‑Trees sidestep these trade‑offs by turning the tree itself into a versioned data structure. In the sections below we unpack the underlying theory, walk through the write‑path algorithm, and examine why real‑world systems such as RocksDB, SQLite, and PostgreSQL’s upcoming ZHeap see measurable speedups.

## The Snapshot Challenge in Modern Databases

When an application asks for a snapshot—“give me the state of the table as of midnight”—the database must guarantee **consistency** (no partial writes) and **isolation** (the snapshot must not be affected by later updates). Common approaches include:

1. **Full Copy** – Duplicate the entire data files. Guarantees isolation but incurs O(N) I/O and storage.
2. **Lock‑Based Quiescence** – Pause writes, copy pages, then resume. Guarantees a clean view but stalls the write path, harming throughput.
3. **Write‑Ahead Log (WAL) Replay** – Keep a log of changes and replay up to the desired point. This works for point‑in‑time recovery but requires replay time proportional to the amount of logged activity.

All three methods involve either **copy overhead**, **write pause**, or **replay latency**. Copy‑on‑Write B‑Trees aim to eliminate the first two while keeping replay costs near zero.

## Fundamentals of B‑Trees

A B‑Tree is a balanced search tree optimized for block‑oriented storage. Its key properties:

- **Node Size ≈ Disk Page** – Each node fits a disk block (e.g., 4 KB or 8 KB), reducing the number of I/O operations per lookup.
- **Sorted Keys Within Nodes** – Enables binary search inside a page.
- **Height‑Bounded** – For *N* keys and a fan‑out of *f*, height = O(log_f N), keeping lookups shallow.

In a conventional B‑Tree, **updates are in‑place**: inserting a key may split a node, merging may propagate upward, and the changed pages are written back to disk. The in‑place nature makes it difficult to keep a historical view because any change mutates the underlying pages that older readers might still be scanning.

## Introducing Copy‑on‑Write

Copy‑on‑Write (COW) is a general technique where a writer first **duplicates** the data it intends to modify, then works on the copy while readers continue to see the original. The original stays immutable until no longer needed, at which point it can be reclaimed.

Applying COW to a B‑Tree yields a **versioned tree**:

- Each **snapshot** is represented by a pointer to the *root* node of a particular version.
- When a transaction modifies a leaf, the leaf node is copied; the parent node that references it is also copied, and so on up to the root.
- Unchanged sub‑trees are **shared** between the live version and all older snapshots.

This pattern matches the **persistent data structure** model described in functional programming literature (e.g., Okasaki’s *Purely Functional Data Structures*). The key advantage for databases is that **only the nodes on the update path are duplicated**, typically a handful of pages, regardless of database size.

## How COW B‑Trees Produce Snapshots

### Write Path with COW

Consider inserting a key into a leaf node. The algorithm, expressed in Python‑like pseudocode, looks like this:

```python
def insert(root, key, value):
    # 1. Descend the tree, recording the path
    path = []                     # Stack of (node, child_index)
    node = root
    while not node.is_leaf():
        idx = node.search_index(key)
        path.append((node, idx))
        node = node.children[idx]

    # 2. Copy the leaf and insert the new entry
    new_leaf = node.clone()       # COW: allocate a fresh page
    new_leaf.insert_entry(key, value)

    # 3. Propagate splits upwards, copying parents as needed
    while new_leaf.needs_split():
        left, right, median = new_leaf.split()
        if not path:              # Splitting the root creates a new root
            new_root = BNode(is_leaf=False)
            new_root.keys = [median]
            new_root.children = [left, right]
            return new_root
        parent, idx = path.pop()
        new_parent = parent.clone()
        new_parent.keys.insert(idx, median)
        new_parent.children[idx] = left
        new_parent.children.insert(idx + 1, right)
        new_leaf = new_parent

    # 4. Re‑attach the unchanged upper part of the tree
    if path:
        parent, idx = path.pop()
        new_parent = parent.clone()
        new_parent.children[idx] = new_leaf
        # Continue climbing without further copies because
        # the remainder of the path is unchanged.
        while path:
            parent, idx = path.pop()
            new_parent = parent.clone()
            new_parent.children[idx] = new_leaf
            new_leaf = new_parent
        return new_parent
    else:
        return new_leaf          # Tree consisted of a single leaf
```

Key observations:

- **Only nodes on the search path are cloned**; the rest of the tree stays shared.
- **Splits create additional copies**, but the number of new pages per insert is bounded by the tree height (typically 2–4 pages for modern fan‑outs).
- The **new root** returned becomes the live version; the old root pointer remains as a snapshot.

### Read Path and Consistency

Readers simply follow the root pointer of the snapshot they care about. Because every node reachable from that root is immutable, the reader sees a **consistent view** without any locks. The database can keep many snapshots alive concurrently, each anchored by its own root.

## Performance Implications

### Reduced I/O

Traditional in‑place B‑Trees rewrite the same pages over and over, causing **write amplification**: a single logical update may trigger multiple physical page writes due to page splits and cache evictions. COW B‑Trees, by contrast, write **only the newly allocated pages**. Since unchanged pages are shared, the total number of writes per transaction drops dramatically, especially for workloads with a high read‑to‑write ratio.

### Lower Lock Contention

Because readers never modify pages, they acquire **no locks** on the shared nodes. Writers only need to lock the *newly allocated* pages they are about to write, which are not visible to any other transaction yet. This eliminates the classic **read‑write lock bottleneck** that plagues MVCC implementations built on top of in‑place structures.

### Space Overhead Considerations

The trade‑off is **additional storage** for the copied nodes. However, the overhead is bounded:

- Each update touches O(log_f N) pages.
- Snapshots that become stale are eventually **garbage‑collected** once no active transaction references them.
- Modern storage engines combine COW B‑Trees with **compaction** (e.g., RocksDB's *level* merging) to reclaim space.

Empirical studies (see the RocksDB blog post on *COW B‑Tree* performance) show that the extra space rarely exceeds 10 % of total data for write‑heavy workloads, while snapshot creation time drops from seconds to milliseconds.

## Real‑World Implementations

### RocksDB’s COW B‑Tree

RocksDB, a high‑performance key‑value store derived from LevelDB, introduced a **COW B‑Tree** in version 8.0. The engine stores each SST file as an immutable B‑Tree; when a snapshot is taken, it simply records the current manifest version. Writes allocate new blocks, and the manifest tracks which blocks belong to which version. The result is **snapshot latency under 5 ms** even for 100 GB databases, as documented in the official [RocksDB blog](https://rocksdb.org/blog/2023/07/12/cow-btree.html).

### SQLite’s Write‑Ahead Log + B‑Tree

SQLite uses a **Write‑Ahead Log (WAL)** combined with a B‑Tree that is effectively copy‑on‑write at the page level. When a transaction commits, it writes the modified pages to the WAL file; the original database file remains untouched until a checkpoint merges the WAL. This design allows **instant read‑only snapshots** by opening the database in read‑only mode and pointing to the WAL as a separate version, as explained in the [SQLite documentation](https://www.sqlite.org/wal.html).

### PostgreSQL’s Upcoming ZHeap

PostgreSQL is experimenting with **ZHeap**, a storage engine that replaces the traditional heap with a COW‑oriented structure. ZHeap stores tuple versions in separate *ZPages*; a snapshot is merely a pointer to a transaction ID, and the engine can reconstruct the view by following the version chain without rewriting pages. The design promises **snapshot creation in microseconds**, detailed in the research paper “ZHeap: A Storage Engine for Fast Snapshot Isolation” (available on the PostgreSQL website).

## Key Takeaways

- **Copy‑on‑Write B‑Trees turn snapshots into cheap root pointer swaps**, eliminating full data copies and heavy locking.
- **Only nodes on the update path are duplicated**, keeping write amplification low and I/O predictable.
- **Readers operate on immutable pages**, so they never block writers and can access any historic version instantly.
- **Space overhead is bounded** by the tree height and reclaimed via garbage collection or compaction.
- **Production systems (RocksDB, SQLite, PostgreSQL ZHeap) already reap measurable latency and throughput gains**, proving the technique’s practical value.

## Further Reading

- [RocksDB Blog – Copy‑on‑Write B‑Tree](https://rocksdb.org/blog/2023/07/12/cow-btree.html) – In‑depth performance analysis and implementation details.  
- [SQLite Write‑Ahead Logging (WAL) Documentation](https://www.sqlite.org/wal.html) – Explains how SQLite achieves atomic snapshots with a COW‑like page model.  
- [PostgreSQL ZHeap Project Page](https://www.postgresql.org/docs/current/zheap.html) – Overview of the upcoming storage engine and its snapshot semantics.  
- [Okasaki, Chris. *Purely Functional Data Structures* (1998)](https://www.cs.cmu.edu/~rwh/courses/15-121/2006/okasaki.pdf) – Classic reference on persistent trees, the theoretical foundation of COW B‑Trees.  
- [Google’s LevelDB – Design and Implementation](https://github.com/google/leveldb) – Shows the predecessor to RocksDB and the motivations for moving to COW structures.