---
title: "Why B-Trees Outperform Binary Search Trees on Disk"
date: "2026-05-13T12:00:51.826"
draft: false
tags: ["B-Tree","Binary Search Tree","Disk I/O","Data Structures","Performance"]
description: "Explore why B‑trees dominate binary search trees for on‑disk storage, covering node fan‑out, cache behavior, and real‑world database use cases."
summary: "B‑trees keep disk reads low and writes efficient, making them the preferred index structure in databases and filesystems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-why-b-trees-outperform-binary-search-trees-on-disk.svg"
  alt: "Illustration of a B-Tree node with multiple keys on a storage disk."
  caption: ""
  relative: false
---

> **TL;DR** — B‑trees store many keys per node, dramatically reducing the number of disk reads required to locate a record. Their wide fan‑out, cache‑friendly layout, and balanced update strategy make them far more efficient than binary search trees (BSTs) for persistent storage.

Disk‑based data structures face a fundamentally different cost model than in‑memory ones. While a CPU can fetch a word from RAM in nanoseconds, a single 4 KB disk block may take milliseconds to read. This disparity forces designers to batch work at the block level. B‑trees were created exactly for that purpose, whereas classic binary search trees (BSTs) were optimized for pointer‑rich, byte‑addressable memory. The result is a stark performance gap when both structures are placed on a hard drive or SSD.

## Disk Access Patterns

### Random vs. Sequential I/O

Modern storage devices still exhibit a noticeable penalty for random reads compared to sequential scans. Even SSDs, which have no moving parts, have higher latency for scattered 4 KB reads because each request must traverse the flash translation layer. A BST forces a new block fetch at every node traversal because each node typically holds only a single key and two child pointers. In the worst case, locating a record of depth *h* triggers *h* separate I/O operations.

A B‑tree, by contrast, packs *m* keys (and *m + 1* child pointers) into a single block. The height of a B‑tree of order *m* is roughly  

\[
\lceil \log_{m} N \rceil
\]

where *N* is the number of stored keys. With *m* = 100 (a realistic block‑size‑derived fan‑out), a tree holding a billion keys is only ~4 levels deep. Thus, a lookup typically incurs **four** disk reads instead of the dozens required by a comparable BST.

### Example: I/O cost comparison

```text
# Approximate I/O operations for 1 000 000 keys
BST depth (worst case) ≈ log2(1,000,000) ≈ 20
B‑Tree order 100 depth ≈ log100(1,000,000) ≈ 3
```

The difference scales linearly with the number of keys, turning a linear‑time I/O cost into a near‑constant one.

## Node Fan‑out and Height

### How fan‑out is derived from block size

A disk block is usually 4 KB (or 8 KB on some systems). A typical key in a database index might be 8 bytes (e.g., a 64‑bit integer) and a child pointer is another 8 bytes. Ignoring overhead, a node can therefore hold:

\[
\frac{4096\text{ bytes}}{8\text{ bytes (key)} + 8\text{ bytes (pointer)}} \approx 256 \text{ entries}
\]

Even after accounting for node metadata (type, key count, etc.), the fan‑out stays in the low‑hundreds. This is why B‑trees are often called “wide” trees.

### Height reduction in practice

| Keys stored | BST worst‑case depth | B‑Tree (order = 256) depth |
|------------|----------------------|----------------------------|
| 10 K       | 14                   | 2                          |
| 1 M        | 20                   | 3                          |
| 1 B        | 30                   | 4                          |

The table illustrates that adding three orders of magnitude to the data set only adds **one** level to a B‑tree, while a BST’s depth grows logarithmically with base 2.

## Cache‑Friendly Layout

### Spatial locality

When a B‑tree node is read into memory, all its keys become instantly available for comparison. A BST node, however, gives you only one key before you must follow a child pointer to a completely different block. This lack of spatial locality means the CPU cache sees far fewer useful bytes per load.

### Prefetching benefits

Because B‑tree nodes are contiguous within a block, modern CPUs and storage controllers can prefetch the next block once the current one is accessed. The prefetcher sees a predictable pattern: after reading node *N*, the next request is likely for one of *N*'s child blocks, which are often stored nearby on the disk (especially on SSDs that employ wear‑leveling and block clustering). BSTs, with their scattered child pointers, defeat most prefetch heuristics.

### Code illustration: B‑Tree node in Python

```python
class BTreeNode:
    def __init__(self, order):
        self.order = order
        self.keys = []          # up to order-1 keys
        self.children = []      # up to order child pointers
        self.leaf = True

    def split_child(self, i):
        """Split the full child at index i into two nodes."""
        child = self.children[i]
        mid = child.order // 2
        new_child = BTreeNode(child.order)
        new_child.leaf = child.leaf
        # Move second half of keys/children to new_child
        new_child.keys = child.keys[mid+1:]
        child.keys = child.keys[:mid]
        if not child.leaf:
            new_child.children = child.children[mid+1:]
            child.children = child.children[:mid+1]
        # Insert median key into current node
        self.keys.insert(i, child.keys[mid])
        self.children.insert(i+1, new_child)
```

The snippet shows how a single node holds many keys, and a split operation touches only **one** disk block (the node being split) rather than a cascade of reads across many levels.

## Write Amplification and Balancing

### BST rotations vs. B‑tree splits/merges

When inserting into a BST, balancing algorithms (e.g., AVL or Red‑Black) may perform a series of rotations that each rewrite a small portion of the tree. On disk, each rotation could involve writing a separate block, leading to *O(log N)* writes for a single insertion.

B‑trees handle imbalance by **splitting** a full node once it exceeds its capacity. The split touches only the node being split and its parent. In the worst case, a split propagates up to the root, but this still touches at most *h* blocks, where *h* is the tree height (usually ≤ 4 for large datasets). Moreover, many insertions can be batched in memory and flushed together, reducing write amplification further.

### Delete handling

Deletion in a BST often requires finding a successor or predecessor, then performing a series of rotations to maintain balance. B‑tree deletions use **merge** or **borrow** operations that also affect a bounded number of nodes. Because each node represents a whole disk block, the cost per delete remains low.

### Write‑ahead logging (WAL) synergy

Database engines frequently combine B‑trees with WAL. The log records the logical operation (insert, delete) once, while the B‑tree pages are written back lazily. This separation would be far less efficient with a BST, where each rotation would demand an immediate page write to preserve structural invariants.

## Real‑World Examples

### PostgreSQL

PostgreSQL’s default index type is a B‑tree. The source code (see `src/backend/access/nbtree`) stores up to 8 KB of keys per page, achieving fan‑outs of 100 + on typical workloads. Benchmark suites consistently show that a B‑tree index on a 10 GB table yields sub‑millisecond point lookups, while a naïve on‑disk BST would take tens of milliseconds.

### Filesystems

The NTFS Master File Table (MFT) and the ext4 extent tree are both B‑tree variants. They rely on the same block‑packing principle to keep directory lookups fast. When a directory contains millions of entries, the tree depth remains shallow, enabling the OS to resolve a file path with only a handful of disk reads.

### Key‑Value stores

RocksDB and LevelDB use **Log‑Structured Merge (LSM) trees**, which are essentially a series of sorted B‑tree‑like runs on disk. Even though the architecture differs, the core insight—that wide nodes reduce I/O—remains the same.

## Key Takeaways

- **Fan‑out matters:** B‑trees pack dozens to hundreds of keys per block, shrinking tree height dramatically compared to binary trees.
- **Fewer I/O operations:** A lookup or update touches only a handful of disk blocks, turning a potentially O(log N) disk‑access pattern into a constant‑ish one.
- **Cache friendliness:** Whole blocks are loaded at once, giving the CPU many keys to compare without additional fetches.
- **Controlled writes:** Splits and merges affect a bounded number of nodes, keeping write amplification low even under heavy insert/delete workloads.
- **Proven in production:** Databases, filesystems, and key‑value stores all rely on B‑tree‑derived structures for on‑disk indexing because of these performance advantages.

## Further Reading

- [B‑Tree Wikipedia article](https://en.wikipedia.org/wiki/B-tree) – comprehensive overview of the data structure and its variants.  
- [PostgreSQL documentation on B‑tree indexes](https://www.postgresql.org/docs/current/indexes-types.html) – explains how PostgreSQL implements and uses B‑trees.  
- [The original B‑tree paper by Bayer and McCreight (1972)](https://dl.acm.org/doi/10.1145/361002.361007) – the foundational research that introduced the concept.  