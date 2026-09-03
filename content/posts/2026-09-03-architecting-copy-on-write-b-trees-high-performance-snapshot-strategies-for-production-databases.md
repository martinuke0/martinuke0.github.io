---
title: "Architecting Copy-on-Write B-Trees: High-Performance Snapshot Strategies for Production Databases"
date: "2026-09-03T12:00:34.143"
draft: false
tags: ["databases", "b-trees", "copy-on-write", "snapshots", "storage-engines", "performance"]
description: "How copy-on-write B-trees power MVCC, snapshots, and crash-safe durability in production databases like LMDB, BoltDB, and RocksDB."
summary: "A practical deep dive into copy-on-write B-tree design: page versioning, root promotion, MVCC snapshots, and the GC strategies that keep production storage engines fast under write pressure."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-architecting-copy-on-write-b-trees-high-performance-snapshot-strategies-for-production-databases.svg"
  alt: "Layered diagram of a copy-on-write B-tree showing page versions branching from a stable root."
  caption: ""
  relative: false
---

> **TL;DR** — Copy-on-write B-trees replace mutating pages in place with immutable versions, giving you free MVCC, cheap crash recovery via the root, and atomic snapshots with no locks. The cost is write amplification and a garbage collection problem, both of which production engines (LMDB, BoltDB, BadgerDB, RocksDB's BlobDB) manage with page-level versioning, epoch-based reclamation, and structural sharing.

If you've ever used Git, you already understand the core trick of a copy-on-write (CoW) B-tree: instead of mutating a file, you create a new version that shares most of its structure with the previous one. Every commit is atomic. Rollback is trivial. Branches are nearly free. The same idea, applied one level down to database pages, gives you some of the strongest consistency guarantees available in storage engines today — and it's the reason a single 50 GB LMDB file can survive a power loss without a log replay.

Let's look at how production systems actually build these trees, where they win, where they hurt, and what the GC story looks like at scale.

## Why Copy-on-Write for B-Trees at All?

The traditional approach is a mutable B-tree on top of a write-ahead log (WAL): every modification is appended to the log and periodically flushed into sorted pages (Postgres' heap pages, InnoDB's B+tree pages with doublewrite buffer). This works, but it carries some structural costs:

- Readers need latches or MVCC chains to avoid seeing torn writes.
- Snapshots require either long-running transactions holding the WAL or expensive page-level version chains.
- Crash recovery has to walk the WAL, identify the last consistent checkpoint, and replay forward.

A CoW B-tree flips the model. Pages are immutable once written. A mutation allocates a brand new page, copies in the changed key range, and atomically swaps the parent's child pointer to point at the new page. Only the root pointer needs locking (a single 8-byte CAS on most architectures), and that's also your durability handle — fsync the new root and you've committed the whole tree atomically.

This is what the [LMDB design paper](https://www.lmdb.tech/doc/) calls "coalesce-then-commit": every page is self-contained, page IDs are stable, and the only mutable metadata is the root.

## Anatomy of a CoW B-Tree Page

Every page is a self-describing record. A minimal layout looks like:

```text
+----------------+----------------+----------------+
|  page_header   |   key slots     |  value/child   |
|  (24 bytes)    |   (sorted)      |  pointers      |
+----------------+----------------+----------------+
```

The header carries enough to identify the version and to walk siblings:

```c
struct cow_page_header {
    uint64_t page_id;      // stable identifier
    uint64_t parent_id;    // for upward walks
    uint32_t version;      // incremented per CoW write
    uint32_t key_count;
    uint32_t free_space;
    uint32_t checksum;     // CRC32C over the rest of the page
    uint8_t  flags;        // leaf | branch | tombstone | overflow
};
```

Two flags matter most: `leaf` and `branch`. A branch page's child pointers are themselves page IDs pointing into the same file. A leaf page holds either inline values or overflow page references for large payloads — the pattern RocksDB uses for BlobDB to keep value pointers out of the LSM tree itself, as described in the [RocksDB BlobDB design doc](https://github.com/facebook/rocksdb/wiki/BlobDB).

Because pages are immutable and checksummed, a torn write is detectable: the checksum won't match, the engine discards the page, and the tree is still consistent because nothing else points at it.

## The Mutation Path: From Key to Committed Root

Let's walk through an `UPDATE users SET name = 'Ada' WHERE id = 42` against a CoW engine.

**Step 1 — Path copy.** Starting at the leaf, the engine reads the leaf page, modifies it in a fresh buffer, and allocates a new page ID. Then it walks upward: each parent along the path gets a new page with the modified child pointer replaced. The unchanged sibling subtrees are referenced by their original page IDs.

**Step 2 — Free page management.** The old leaf is *not* reused yet. It might still be visible to a snapshot. A CoW engine keeps a free list and a live set, and a page only becomes reclaimable when no snapshot can see it.

**Step 3 — Root publication.** When the writer reaches the root, it has a candidate new root in memory. A single atomic write to the root slot (or, in mmap-based engines like LMDB, a single msync of the meta page) commits the change. Readers either see the old root or the new one — never a partial rewrite.

In BoltDB, this is observable in the `Tx.Commit()` path, where the meta page is written twice at offsets that alternate to avoid a torn meta on power loss:

```go
// From bolt/db.go — abbreviated
func (db *DB) commit() error {
    // ... write all dirty pages ...
    if err := fdatasync(db.file); err != nil {
        return err
    }
    // Atomic meta swap
    meta := tx.meta
    meta.Txid += 1
    meta.Root = newRoot
    if err := writeMeta(db, meta); err != nil {
        return err
    }
    return fdatasync(db.file)
}
```

The double meta write is the trick that makes a single file crash-safe without a separate journal. Every page already has a checksum; only the meta needs an extra guard. This is documented in Howard Chu's talk on [Lightning Memory-Mapped Database](https://www.youtube.com/watch?v=6Q1N3a5ZVUA) and the [LMDB paper](https://www.lmdb.tech/doc/).

## Snapshot Isolation, Almost Free

Because old pages stick around until they're reclaimed, any consistent point-in-time view of the tree is just *a root pointer*. To take a snapshot, you:

1. Acquire the current root atomically.
2. Increment a global epoch counter (or push a reader epoch).
3. Hold that root until the transaction commits or aborts.

No undo logs. No vacuum churn during reads. No read-write coordination except the root fetch itself.

This is the basis of LMDB's claim that *read transactions are zero-copy*: the reader pins the root, walks the tree using whatever page IDs the root references, and never blocks a writer. The Postgres crowd will recognize the same shape as the visibility machinery behind `REPEATABLE READ`, but CoW avoids the heap tuple version chains entirely.

For analytics-style workloads — long-running reports over a slowly-changing dataset — this is huge. A 30-minute read transaction on a 10 GB LMDB database costs one root snapshot, period. On an InnoDB-style engine you'd be holding purge back and watching the undo tablespace grow.

## Patterns in Production

Different engines use CoW for very different reasons. Looking at four real systems clarifies the design space.

### LMDB: mmap + a single meta page

LMDB maps the entire database into virtual memory. Pages live at offsets derived from page IDs; the kernel page cache is the buffer pool. The only on-disk mutation is the meta page, written to a pair of fixed offsets so any single fsync can't leave it inconsistent. Readers take a snapshot by capturing the meta pointer; writers take an exclusive lock only on commit. The trade-off is that the file size is bounded by `map_size` at open time, so LMDB is best for fixed-size working sets.

### BoltDB (mholt/bbolt): Go-native, fork-friendly

BoltDB takes the same shape but with explicit `*bolt.DB` and `*bolt.Tx` types instead of mmap. It added [nested buckets](https://github.com/etcd-io/bbolt) and per-bucket freelists after forking to etcd-io/bbolt. The CoW model is what makes etcd's watch and lease storage cheap: every compaction produces a new tree, old watchers keep reading the old one until they release.

### BadgerDB: CoW + LSM hybrids

Badger splits keys and values: keys and small values live in a CoW skip-list on top of LSM, while large values go into a separate value log. This is a CoW tree in the sense that the SST files are immutable and the in-memory layers copy-on-write, but the on-disk merge uses LSM compaction rather than tree restructuring.

### RocksDB with BlobDB: not CoW, but informed by it

RocksDB's base engine is an LSM tree — not CoW — but BlobDB stores large values in a separate log-structured file that exposes a similar "immutable chunks addressed by stable IDs" pattern. The motivation is the same: hot keys stay in a compact structure, garbage collection happens out of band.

## Architecture: Page Versioning and Reclamation

If old pages are the engine's biggest advantage, they're also its biggest operational liability. Every write creates a new path from leaf to root. A sustained 10K writes/sec workload on a tree with depth 4 generates ~40K new pages per second, and the old pages have to be reclaimed or the file grows unbounded.

This is the reclamation architecture every production CoW engine implements, in some form:

```text
              +-------------------+
              |   active writers  |
              +---------+---------+
                        |
                  new root atomically published
                        |
                        v
        +---------------+---------------+
        |     live pages (referenced)   |
        +---------------+---------------+
                        |
        readers pin via epoch / refcount
                        |
                        v
  +---------------------+---------------------+
  |     page lifecycle  |                     |
  |  active -> pinned -> unreachable -> free |
  +------------------------------------------+
```

The three production-grade strategies:

1. **Reference counting per page.** Cheap and exact, but contended under hot trees. Suited for low-concurrency workloads.
2. **Epoch-based reclamation (EBR).** Readers register an epoch on entry and clear it on exit; pages unreachable in the oldest pinned epoch are freed. This is what Crossbeam and many CoW engines use.
3. **Hazard pointers or RCU.** Best for read-heavy workloads, slightly more expensive at read time but no epoch stalls.

LMDB uses a particularly elegant version of option 2: a single `MT_MAPID` slot per reader holds the page IDs the reader is touching, and the writer waits for `MT_MAPID` to advance before reclaiming pages from old transactions. It's documented in the [LMDB mdb.c reference](https://www.lmdb.tech/doc/mdb.html).

A practical reclaim policy:

```python
def reclaim(pages, live_roots, free_list):
    """Free pages unreachable from any live root."""
    reachable = walk_all(live_roots)      # O(file size) periodically
    for page_id, page in pages.items():
        if page_id not in reachable:
            if page.refcount == 0 and not pinned_in_epoch(page):
                free_list.append(page)
                del pages[page_id]
```

Walk-all is amortized: most engines do it on commit, not on every write, and skip pages modified in the last N epochs.

## Write Amplification and the Path-Copy Cost

Path copying is O(tree_height), which sounds small but compounds under skewed access. A 4-level tree with 16 KB pages means 64 KB of writes per logical update, before counting the page metadata. Two mitigations show up in real systems:

- **Bulk CoW for range writes.** When you rewrite a large fraction of the tree, batch the path copies. LMDB does this implicitly via its `MDB_APPEND` and sorted-input optimizations; RocksDB avoids it by switching to a sorted string table entirely.
- **Sub-page diffing.** Engines like WiredTiger (which is hybrid CoW + B-tree) store small deltas rather than whole pages when only a few bytes change. The trade-off is more complex GC.

A back-of-the-envelope: if your tree is depth 4 and your working set is 10 GB with 10% churn per minute, you're producing ~30 GB/hour of new pages. Your reclaim strategy has to keep up with that, or you'll fill whatever disk you allocated.

## Snapshot Forking and Branching

One underrated capability of CoW B-trees is cheap branching. Want to spin up an isolated test database from a 100 GB production snapshot? Just copy the root pointer. Both trees share every page until one of them diverges.

This is exactly how [etcd's compaction](https://etcd.io/docs/latest/learning/data-model/) works on top of bbolt: a compacted revision is a new root, and old watchers keep their view. It's also the foundation of database branching tools like [Neon's branching model](https://neon.tech/blog/branching-postgres), which uses a similar idea — immutable page storage + a root pointer — at the storage layer.

For application developers this means:

- Time-travel debugging is a free feature of the storage engine.
- A/B testing against yesterday's data is just keeping two roots alive.
- Restores are copy-on-write too: the backup shares storage with production until you actually read it.

## Crash Recovery: One Fsync to Rule Them All

With a CoW B-tree, recovery is the easiest part of the engine. On startup:

1. Read the meta page. It contains two copies; pick the one with the higher transaction ID whose checksum is valid.
2. The chosen meta gives you a root page ID.
3. Walk the tree lazily, validating checksums as you go. Bad pages are skipped (they weren't visible to any committed transaction anyway).

No log replay. No "did we flush this page?" bookkeeping. The cost is paid in write amplification during normal operation, not in startup time. The [SQLite WAL docs](https://www.sqlite.org/wal.html) discuss a similar trade-off — CoW just pushes it further.

## Failure Modes to Watch

A few things go wrong in CoW systems that don't show up in mutable B-trees:

- **Root thrash under high concurrency.** If every transaction commits through a single root CAS, you serialize writers at the root. LMDB mitigates this with a single-writer mutex (one writer at a time). BoltDB does the same.
- **Free-list corruption.** A bug that frees a page still reachable from an old root turns into a crash that looks random. The fix is structural: free-list operations must be ordered after the transaction that "abandoned" the page is no longer observable.
- **Hole-filled files.** CoW files look sparse on disk even when they're not. Use a filesystem that handles sparse files well (ext4, xfs) and preallocate if your allocator is naïve.
- **Snapshot starvation.** Long-running readers pin pages that would otherwise be freeable. The classic "snapshot too old" problem. Track per-snapshot page counts and alert when any reader holds more than some threshold of the file.

## Key Takeaways

- CoW B-trees replace in-place page mutation with immutable versioning, giving you atomic commits, free MVCC, and crash recovery via a single root pointer.
- The model shines for read-heavy, snapshot-heavy workloads — analytics, watch/lease systems, time-travel — and struggles under sustained write pressure because of write amplification.
- Garbage collection is the operational core: epoch-based reclamation or reference counts decide whether your file grows unbounded or stays bounded.
- LMDB, BoltDB, BadgerDB, and even RocksDB BlobDB show that the CoW idea reappears wherever "lots of concurrent readers + cheap snapshots" matters.
- Crash recovery is trivial, but root serialization, free-list correctness, and snapshot pinning are the real engineering work.

## Further Reading

- [Lightning Memory-Mapped Database: The Design and Implementation of a Fast Distributed Key-Value Store](https://www.lmdb.tech/doc/)
- [Howard Chu — Lightning Memory-Mapped Database (LMDB) overview talk](https://www.youtube.com/watch?v=6Q1N3a5ZVUA)
- [boltdb / bbolt source: commit path and meta page management](https://github.com/etcd-io/bbolt)
- [RocksDB BlobDB: Large Value Storage](https://github.com/facebook/rocksdb/wiki/BlobDB)
- [Crossbeam epoch-based reclamation reference](https://docs.rs/crossbeam/latest/crossbeam/epoch/index.html)
- [etcd data model and compaction overview](https://etcd.io/docs/latest/learning/data-model/)
- [SQLite Write-Ahead Logging for comparison with CoW durability](https://www.sqlite.org/wal.html)