---
title: "Why Copy-on-Write B-Trees Accelerate Database Snapshots"
date: "2026-05-14T15:00:33.533"
draft: false
tags: ["databases","b-trees","copy-on-write","snapshots","performance"]
description: "Copy-on-Write B‑Trees let databases create instant, low‑overhead snapshots by sharing unchanged pages, reducing I/O and simplifying rollback."
summary: "Learn how copy‑on‑write B‑trees work, why they make snapshots cheap, and what trade‑offs you should weigh when choosing this storage engine."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-14-why-copy-on-write-b-trees-accelerate-database-snapshots.svg"
  alt: "Diagram of a B‑Tree with highlighted copy‑on‑write nodes."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑write (COW) B‑trees let a database keep a point‑in‑time view of data without copying the whole structure. By writing new pages only when modifications occur, snapshots become cheap, fast, and safe for concurrent workloads.

Databases that need frequent point‑in‑time backups, fast rollbacks, or multi‑version concurrency control (MVCC) often struggle with the overhead of copying large data structures. Copy‑on‑write B‑trees solve that problem by separating the *write* path from the *read* path, allowing the storage engine to share unchanged pages between the live database and any number of snapshots. In this article we’ll unpack the underlying mechanics, examine why COW B‑trees speed up snapshots, and discuss the performance trade‑offs you’ll encounter when deploying them.

## Copy‑on‑Write Fundamentals

### What “Copy‑on‑Write” Means

Copy‑on‑write is a memory‑management technique that defers the actual duplication of data until a write occurs. The classic example is forked processes in Unix: the child process receives a view of the parent’s address space, but physical pages are only duplicated when either process writes to them. The same principle applies to disk pages in a database engine.

When a page is **read‑only**, multiple logical views can point to the exact same physical block on disk. As soon as a transaction wants to modify that page, the engine allocates a fresh block, copies the original contents, applies the change, and updates the pointer in the tree structure. The old block remains untouched, preserving the state that any existing snapshot expects.

### Benefits for Snapshots

Because snapshots are essentially *pointers* to a particular root page of the B‑tree, creating a snapshot is just a matter of recording the current root’s identifier. No data is copied, no locks are held, and the operation completes in microseconds. Subsequent writes generate new pages, leaving the snapshot’s view intact.

This approach eliminates the need for expensive background copy jobs (as in traditional backup‑while‑running schemes) and avoids the “stop‑the‑world” pauses that can plague systems that lock tables while a backup is taken.

## B‑Tree Structure and the Write Path

### Classic B‑Tree Layout

A B‑tree stores keys in sorted order across a hierarchy of pages (or nodes). Each internal node contains a range of keys and pointers to child pages; leaf nodes hold the actual records or record pointers. The depth of the tree is logarithmic in the number of entries, guaranteeing O(log N) lookup, insert, and delete operations.

In a **non‑COW** B‑tree, an insert that causes a leaf page to overflow triggers a *split*: the page is divided, a new sibling page is allocated, and the parent node is updated. If the parent also overflows, the split propagates upward, potentially rewriting several pages on the path to the root.

### Introducing Copy‑on‑Write

In a COW B‑tree, every modification follows a *write‑path* that creates new versions of the affected pages:

1. **Locate** the leaf page that will receive the new key.
2. **Allocate** a fresh page, copy the old content, apply the insert, and mark the new page as the *version* for this transaction.
3. **Propagate** the change upward: each internal node on the path to the root is also copied, with the pointer to the child updated to reference the newly created page.
4. **Publish** the new root identifier once the transaction commits.

Because each transaction works on its own private copy of the pages it touches, multiple concurrent writers can proceed without stepping on each other. Readers that started before the transaction simply follow the old root and never see the new pages.

### Code Sketch

Below is a minimal Python illustration of a COW insert. It omits many production concerns (locking, durability, page caching) but shows the core idea:

```python
class Page:
    def __init__(self, keys=None, children=None, leaf=True):
        self.keys = keys or []
        self.children = children or []
        self.leaf = leaf

def cow_insert(root, key):
    """Return a new root after inserting `key` using copy‑on‑write."""
    # 1. Find the leaf and the path of ancestors
    path = []          # (parent, index) pairs
    node = root
    while not node.leaf:
        i = next(i for i, k in enumerate(node.keys) if key < k)
        path.append((node, i))
        node = node.children[i]

    # 2. Copy leaf and insert key
    new_leaf = Page(keys=node.keys.copy(), leaf=True)
    new_leaf.keys.append(key)
    new_leaf.keys.sort()

    # 3. Re‑wire ancestors using copies
    child = new_leaf
    for parent, idx in reversed(path):
        new_parent = Page(keys=parent.keys.copy(),
                          children=parent.children.copy(),
                          leaf=False)
        new_parent.children[idx] = child
        child = new_parent

    # 4. New root is the topmost copy
    return child
```

In a real engine the `Page` objects would be serialized to disk pages, and the function would also handle page splits, log records, and crash recovery.

## How COW B‑Trees Enable Efficient Snapshots

### Snapshot Creation Is O(1)

When a database wants to take a snapshot, it simply records the current root page identifier (often called a *generation* or *LSN*). This identifier is stored in a system table or a metadata file. Because the root points to an immutable graph of pages, the snapshot is guaranteed to be consistent without any further action.

```bash
# Example: PostgreSQL's pg_export_snapshot command
psql -c "SELECT pg_export_snapshot();"
```

The command above returns a snapshot ID that other sessions can use to run queries as of that moment. Internally PostgreSQL’s MVCC uses a COW B‑tree for its indexes, so the snapshot is just a reference to a particular root version.

### Reads Are Lock‑Free

Readers that operate under a snapshot follow the versioned pointers that existed when the snapshot was taken. Since writers never modify those pages in place, readers never encounter partially applied changes or need to acquire shared locks. This is why many high‑throughput OLTP systems (e.g., SQLite’s WAL mode, CockroachDB) achieve excellent read scalability.

### Write Amplification Is Bounded

A common misconception is that COW always doubles write I/O because every modified page is copied. In practice the overhead is bounded by the height of the tree:

- **Leaf modification** → copy leaf (1 page)
- **Internal node updates** → copy each node on the path (≈ log₍f₎ N pages, where *f* is the fan‑out)

If a B‑tree has a fan‑out of 100 (typical for 8 KB pages on modern SSDs), a database with billions of rows will have a height of about 3–4. Therefore a single insert may result in copying only 4–5 pages, which is modest compared to the total data size.

### Garbage Collection of Stale Pages

Snapshots are not permanent; they eventually expire. The engine periodically scans the set of active roots, marks all reachable pages, and reclaims the unreferenced ones. This process is similar to a *mark‑and‑sweep* garbage collector:

```text
1. Gather all live root IDs (current DB + active snapshots).
2. Walk each tree, marking visited pages.
3. Delete any page not marked.
```

Because the walk is sequential and page‑aligned, it can be performed efficiently on SSDs or even in the background without impacting foreground transactions.

### Real‑World Example: SQLite’s Write‑Ahead Log (WAL)

SQLite combines a COW B‑tree with a write‑ahead log. When a transaction commits, the new root is written to the WAL file, and the old root remains reachable by any snapshot that opened the database before the commit. The snapshot can be accessed simply by opening the database in *read‑only* mode with the `sqlite3_snapshot_open` API. As detailed in the official SQLite documentation, this design enables **instantaneous** backups that are safe to copy while the database continues to serve traffic.

## Trade‑offs and Performance Considerations

### Increased Storage Footprint

While COW reduces snapshot latency, it does increase the amount of storage required to hold multiple versions of pages. In write‑heavy workloads, the churn of pages can fill up disk space quickly if snapshots are retained for long periods. Administrators must balance snapshot retention policies against available storage.

### Write Amplification on Page Splits

If a leaf page is full, the insert triggers a split, which creates **two** new leaf pages and updates the parent. The parent may also need to split, propagating upward. In the worst case, a single insert can cause O(log N) new pages *plus* the split overhead, leading to a temporary spike in write I/O.

### Cache Pressure

Because each transaction works on its own copies of pages, the buffer pool (or page cache) can become fragmented. Frequently accessed hot pages may be duplicated across many transactions, reducing cache hit rates. Some engines mitigate this by **page deduplication** or by limiting the number of concurrent snapshots.

### Recovery Complexity

Crash recovery must reconcile the fact that multiple versions of the same page may exist on disk. The recovery algorithm typically replays the log forward to the latest committed root, discarding any unreferenced pages. This adds complexity to the write‑ahead log and requires a robust **checkpoint** process to prune stale data.

### When Not to Use COW B‑Trees

- **Purely append‑only workloads** where snapshots are rarely needed. The extra copy overhead may not justify the benefits.
- **Embedded devices with severe storage constraints** where the extra page versions cannot be tolerated.
- **Analytical databases** that rely on columnar storage and heavy batch writes; they often employ different snapshot mechanisms (e.g., Parquet file versioning).

## Key Takeaways

- **Instant snapshots**: COW B‑trees turn snapshot creation into an O(1) operation that records only the root page identifier.
- **Read‑only isolation**: Readers follow immutable page versions, eliminating lock contention and enabling MVCC.
- **Bounded write cost**: Each write copies only the pages on the path to the root (typically 3–5 pages), keeping write amplification low.
- **Garbage collection**: Stale pages are reclaimed via a background mark‑and‑sweep, keeping disk usage under control when snapshots expire.
- **Trade‑offs**: Extra storage, potential cache pressure, and more complex recovery logic must be weighed against the snapshot speed gains.
- **Real‑world adoption**: Engines such as SQLite, PostgreSQL (MVCC), CockroachDB, and many LSM‑tree hybrids borrow heavily from the COW B‑tree concept.

## Further Reading

- [Copy‑on‑Write on Wikipedia](https://en.wikipedia.org/wiki/Copy-on-write) – Overview of the COW technique across operating systems and databases.  
- [SQLite Write‑Ahead Logging](https://www.sqlite.org/wal.html) – Detailed description of SQLite’s WAL mode and its interaction with COW B‑trees.  
- [PostgreSQL MVCC Documentation](https://www.postgresql.org/docs/current/mvcc.html) – Explanation of how PostgreSQL implements multi‑version concurrency control using versioned tuples and index structures.  
- [B‑Tree Basics (Oracle)](https://www.oracle.com/database/technologies/btree.html) – Technical article on B‑tree page layouts and split algorithms.  
- [RocksDB – A High Performance Embedded Database](https://rocksdb.org) – While primarily an LSM‑tree, RocksDB discusses snapshot semantics that are comparable to COW B‑trees.