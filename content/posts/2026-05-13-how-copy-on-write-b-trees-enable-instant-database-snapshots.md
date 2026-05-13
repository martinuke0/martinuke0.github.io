---
title: "How Copy-on-Write B-Trees Enable Instant Database Snapshots"
date: "2026-05-13T21:00:51.702"
draft: false
tags: ["databases", "b-tree", "copy-on-write", "snapshots", "performance"]
description: "Explore how copy-on-write B‑trees power instant, zero‑copy snapshots in modern databases, reducing latency and storage overhead while preserving ACID guarantees."
summary: "Copy‑on‑write B‑trees let databases take point‑in‑time snapshots instantly, without blocking writes. This post explains the mechanics, trade‑offs, and real‑world implementations."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-how-copy-on-write-b-trees-enable-instant-database-snapshots.svg"
  alt: "Diagram of a B-tree node being duplicated for copy‑on‑write."
  caption: ""
  relative: false
---

> **TL;DR** — Copy‑on‑write (COW) B‑trees let a database clone its entire logical state in a single, lock‑free operation. By sharing unchanged pages and only duplicating the nodes touched by a write, COW B‑trees provide instant, space‑efficient snapshots without sacrificing transaction throughput.

Databases must balance three competing goals: durability, concurrency, and low‑latency reads. Traditional snapshot techniques—full table copies, log‑based replay, or heavy‑weight locking—either pause writes or consume large amounts of I/O. Copy‑on‑write B‑trees flip the problem on its head: they make the *write* operation cheap to duplicate, turning snapshot creation into a near‑zero‑cost pointer swap. In this article we unpack the data‑structure fundamentals, walk through the exact steps a COW B‑tree takes to snapshot, discuss consistency guarantees, and examine how major systems such as PostgreSQL, RocksDB, and SQLite put the theory into practice.

## Fundamentals of B‑Trees

A B‑tree is a balanced search tree optimized for block‑oriented storage. Each node holds multiple keys and child pointers, fitting neatly into a disk page (often 4 KB or 8 KB). The invariants are simple:

1. All leaf nodes reside at the same depth.
2. Keys within a node are sorted.
3. Every internal node with *k* children stores *k‑1* separator keys.

Because pages are the unit of I/O, B‑trees minimize the number of reads required to locate a record: a lookup follows a path of height *h* (typically 3–4 levels for terabyte‑scale tables). Insertions and deletions may split or merge nodes, but the tree stays balanced.

### Why B‑Trees Matter for Snapshots

Snapshots require a *stable* view of the data at a point in time. In a naïve B‑tree, mutating a node overwrites the on‑disk page, destroying the previous version. To preserve the old version, the system would need to copy the entire tree—a prohibitive O(N) operation. The breakthrough is to make the *write* operation itself COW‑aware, so that only the pages that change are duplicated, while the rest of the structure remains shared between the live database and the snapshot.

## Copy‑On‑Write Mechanics

Copy‑on‑write is a versioning strategy: before a mutable page is altered, the system creates a fresh copy and writes the new data there. The original page remains untouched and can be referenced by any snapshot that was taken earlier.

### Page Allocation Flow

```python
def cow_write(page_id, new_content):
    """
    Perform a copy‑on‑write update on a B‑tree page.
    """
    # 1. Look up the current physical address of the logical page.
    old_addr = page_table[page_id]

    # 2. Allocate a new physical page.
    new_addr = allocate_page()

    # 3. Copy the old page's contents.
    new_page = read_page(old_addr)
    new_page.update(new_content)

    # 4. Write the modified page back.
    write_page(new_addr, new_page)

    # 5. Update the page table atomically.
    page_table[page_id] = new_addr
```

The key point is step 5: the logical mapping from *page_id* to *physical address* is updated atomically (often via a compare‑and‑swap or a write‑ahead log). All readers that already hold the old address continue to see the pre‑write state, while new readers see the updated page.

### Tree‑Level COW

When a leaf page is COW‑updated, its parent node must also be updated to point to the new leaf address. This cascades upward:

1. **Leaf change** → allocate new leaf, write it, update parent pointer.
2. **Parent change** → allocate new parent, write it, update its own parent pointer.
3. Continue until reaching the root.

Because each level only copies a single node, the total cost of a write is *O(h)*, where *h* is the tree height (usually < 5). The snapshot operation, by contrast, simply records the current root pointer.

## Snapshot Creation Workflow

With COW in place, taking a snapshot is essentially a single atomic step:

```bash
# Pseudocode for a snapshot command
snapshot_id=$(uuidgen)
root_addr=$(read_root_pointer())
# Store the root address in the snapshot metadata table
insert_snapshot(snapshot_id, root_addr)
```

1. **Read the current root address** – this is a single pointer read from a well‑known location (often a fixed page or a shared memory segment).
2. **Persist the root address** – write it to a snapshot catalog table, durable via the WAL.
3. **Return a snapshot identifier** – applications can later use this ID to open a read‑only transaction anchored at that root.

No pages are copied during step 1; the whole database state is now reachable through the saved root pointer. Subsequent writes will diverge, allocating new pages, while the snapshot continues to follow the old chain of pages.

### Isolation Guarantees

Because each snapshot sees a *consistent* set of pages, it enjoys **snapshot isolation** automatically. The snapshot is immune to later writes, and readers never block writers. This matches the MVCC model used by PostgreSQL and SQLite, where each transaction holds a snapshot of the database at its start time.

## Consistency and Isolation Guarantees

### ACID in the Presence of COW

*Atomicity*: The write‑ahead log (WAL) ensures that the page table updates (step 5 in the COW flow) are either fully applied or not at all. If a crash occurs mid‑write, recovery replays the WAL to reconstruct the correct page table state.

*Consistency*: B‑tree invariants are enforced by the same code paths that handle splits/merges. Because each split creates new nodes via COW, the old nodes remain valid for any snapshot that was taken before the split.

*Isolation*: Snapshots provide **repeatable read** semantics. A transaction that began at snapshot S will always read the same version of any row, even if concurrent transactions commit later. This is the same guarantee offered by PostgreSQL’s *Serializable Snapshot Isolation* when using `SELECT ... FOR SHARE`.

*Durability*: Once the snapshot metadata (root pointer) is flushed to disk, the snapshot is durable. Even if the live database crashes, the snapshot can be re‑mounted by loading the saved root address.

### Garbage Collection

Old pages that are no longer referenced by any active snapshot become candidates for reclamation. Systems typically employ a **reference counting** or **epoch‑based** scheme:

```text
epoch = current_global_epoch()
for each page in free_list:
    if page.last_used_epoch < epoch - safe_margin:
        reclaim(page)
```

Reference counting is simple but can be expensive under heavy concurrency. Epoch‑based reclamation, as described in the *Hazard Pointers* paper, lets writers advance a global epoch and readers announce the epoch they are operating in. Once all readers have moved past an epoch, pages from that epoch are safe to free.

## Performance Implications

### Write Amplification

COW introduces additional writes: each logical update writes the modified page *and* the parent nodes up to the root. However, because the height is tiny, the extra I/O is modest. In practice, write amplification stays under a factor of 2, comparable to traditional B‑tree splits.

### Read Amplification

Read paths are unchanged. A snapshot read follows the same pointer chain as a live read; the only difference is that the root pointer is taken from the snapshot catalog rather than the latest root. Cache locality may improve because a snapshot often accesses a stable set of pages, reducing cache churn.

### Space Overhead

The worst‑case space usage is proportional to the number of writes since the last snapshot, because each write creates a new leaf and a chain of parent copies. Systems mitigate this by:

- **Frequent checkpointing**: periodically merge the live state into a new base and discard older snapshots.
- **Deduplication**: compress identical pages (e.g., using ZSTD) before storing them.
- **Partial snapshots**: only snapshot a subset of tables, reducing the number of pages that need to be retained.

Real‑world numbers: RocksDB reports that a full snapshot of a 500 GB dataset consumes only ~5 GB of additional disk after a few hours of normal write traffic, thanks to high page reuse.

## Real‑World Implementations

### PostgreSQL

PostgreSQL’s MVCC uses a *heap* for row versions and a *B‑tree* for indexes. While the heap is not COW, its **snapshot mechanism** is conceptually similar: a transaction records the current `xmin`/`xmax` values and sees only rows whose visibility fits the snapshot. The index side can be made COW by enabling the `pg_am` “btree” with `wal_level = logical`. The official docs explain the underlying mechanics in the *Multi-Version Concurrency Control* chapter ([PostgreSQL MVCC docs](https://www.postgresql.org/docs/current/mvcc.html)).

### RocksDB

RocksDB implements a **Log‑Structured Merge‑Tree (LSM)**, but its **ColumnFamily** metadata uses a COW B‑tree to manage file manifests. The project’s wiki details the copy‑on‑write approach for snapshotting the manifest file ([RocksDB Copy‑on‑Write](https://github.com/facebook/rocksdb/wiki/Copy-on-Write)). RocksDB’s `CreateSnapshot()` API simply captures the current sequence number; all reads after that use the same immutable view of the data files.

### SQLite

SQLite’s **Write‑Ahead Logging (WAL)** mode stores changes in a separate WAL file, while the main database file remains read‑only for readers. The WAL is effectively a COW log: each writer appends a new frame, and readers can open a consistent snapshot by reading the database file plus the WAL up to a checkpoint (`sqlite3_wal_checkpoint`). The SQLite documentation discusses this in depth ([SQLite WAL](https://sqlite.org/wal.html)).

### ZFS and Filesystem‑Level Snapshots

Although not a database, ZFS’s **COW B‑tree (ZAP)** underpins its instant snapshot feature. ZFS demonstrates that the same data‑structure ideas scale to terabyte‑level filesystems, reinforcing the universality of COW B‑trees ([ZFS Design Overview](https://openzfs.org/wiki/Design_overview)).

## Key Takeaways

- **Instant snapshots** are achieved by persisting a single root pointer; no pages are copied at snapshot time.
- **Copy‑on‑write** duplicates only the pages touched by a write, propagating changes up the B‑tree’s height (usually ≤ 5).
- **Consistency** is guaranteed because each snapshot sees a immutable chain of pages, delivering snapshot isolation without blocking writers.
- **Garbage collection** reclaims pages once no active snapshot references them, typically via epoch‑based reclamation.
- **Real‑world systems** (PostgreSQL, RocksDB, SQLite, ZFS) all rely on the same core principle, proving its practicality and scalability.

## Further Reading

- [PostgreSQL MVCC documentation](https://www.postgresql.org/docs/current/mvcc.html)
- [RocksDB Copy‑on‑Write wiki page](https://github.com/facebook/rocksdb/wiki/Copy-on-Write)
- [SQLite Write‑Ahead Logging (WAL) guide](https://sqlite.org/wal.html)
- [ZFS Design Overview – COW B‑tree details](https://openzfs.org/wiki/Design_overview)
- [The original B‑tree paper by Bayer and McCreight (1972)](https://dl.acm.org/doi/10.1145/361002.361007)