---
title: "Skip Lists in Python, Zero to Hero: Deep Dive and System Design Connections"
date: "2025-12-06T17:13:45.63"
draft: false
tags: ["skip list", python", data structures", system design", algorithms", "distributed systems"]
---

## Introduction

Skip lists are a beautiful idea: a simple, probabilistic alternative to balanced trees that delivers expected O(log n) search, insert, and delete, yet is easier to implement and friendlier to concurrency. They’ve quietly powered critical systems for decades—from leaderboards and rate limiters to LSM-tree memtables and Redis sorted sets.

In this post, you’ll go from beginner to hero:
- Understand the intuition, guarantees, and design of skip lists
- Implement a production-quality skip list in Python
- Learn how skip lists show up in system design
- Get practical guidance on performance, determinism, and trade-offs
- Explore advanced variants and when to use them

If you’re building systems that need fast ordered access, range queries, or rank-based operations, skip lists belong in your toolkit.

> Key idea: Skip lists maintain multiple “express lanes” above a sorted linked list. Randomized towers of pointers allow jumping over sections, delivering expected logarithmic time without complex rotations or node splits.

## Table of Contents

- [Introduction](#introduction)
- [What Is a Skip List?](#what-is-a-skip-list)
- [Why Skip Lists: Intuition and Complexity](#why-skip-lists-intuition-and-complexity)
- [Anatomy of a Skip List](#anatomy-of-a-skip-list)
- [Python Implementation (Search, Insert, Delete, Range)](#python-implementation-search-insert-delete-range)
  - [Core API](#core-api)
  - [Usage Examples](#usage-examples)
- [System Design Use Cases](#system-design-use-cases)
  - [Leaderboards and Ordered Sets](#leaderboards-and-ordered-sets)
  - [LSM-Trees and Memtables](#lsm-trees-and-memtables)
  - [Scheduling, Windows, and TTLs](#scheduling-windows-and-ttls)
  - [Concurrency and Lock-Free Variants](#concurrency-and-lock-free-variants)
- [Performance Considerations](#performance-considerations)
  - [Choice of p and Max Levels](#choice-of-p-and-max-levels)
  - [Memory, Cache Locality, and Python Overheads](#memory-cache-locality-and-python-overheads)
  - [Benchmarking vs Alternatives](#benchmarking-vs-alternatives)
- [Determinism, Replication, and Sharding](#determinism-replication-and-sharding)
- [Variants and Extensions](#variants-and-extensions)
- [Production Notes for Python Users](#production-notes-for-python-users)
- [Testing and Validation](#testing-and-validation)
- [Conclusion](#conclusion)
- [Resources](#resources)

## What Is a Skip List?

A skip list is an ordered, probabilistically balanced linked structure. The bottom layer is a regular sorted linked list. Higher layers contain “express” links that skip over multiple nodes, formed by promoting nodes upward with probability p (often 0.5). Each node may have a tower of forward pointers.

Operations traverse from the topmost layer downward, making large jumps initially and smaller ones near the target. This yields expected O(log n) time for search, insert, and delete.

Compared with balanced trees:
- Similar asymptotic average performance
- Simpler implementation: no rotations, fewer invariants
- Typically better support for lock-free concurrent designs (on JVM, C/C++)
- Range scans are natural (it’s a linked list under the hood)

## Why Skip Lists: Intuition and Complexity

Think of a highway:
- Level 0: local roads (every house)
- Level 1: arterial roads (every 2nd house)
- Level 2: express roads (every 4th house)
- …

If you promote with probability p, the expected number of nodes at level i is n·p^i. The expected height is O(log_{1/p} n), and at each level you take O(1/p) steps on average. Summed across levels, expected work is O(log n).

Expected complexities (with p=0.5):
- Search: O(log n)
- Insert: O(log n) + pointer updates
- Delete: O(log n)
- Range scan of k items: O(log n + k)

> Note: These are expected bounds. In the worst case (pathologically unlucky promotions), height can grow to O(n), though the probability is astronomically small.

## Anatomy of a Skip List

Key components:
- Head/sentinel node with maximum height
- Nodes with a variable number of forward pointers (their “tower”)
- Random level generator: coin flips with probability p until tails or max level
- Comparator or key function to maintain order
- Optional: span/width metadata for rank queries (indexable skip lists)

Design choices:
- Probability p: commonly 0.5 or 0.25 (trade-off between height and pointer count)
- Max level: set to ceil(log_{1/p}(N_max)) for expected bounds
- Stability: unique keys or allow duplicates via composite key (score, id)

## Python Implementation (Search, Insert, Delete, Range)

Below is a clean, well-documented Python skip list. It supports:
- insert(key, value)
- get(key) -> value or None
- remove(key)
- contains, len
- iteration in order
- range(min_key, max_key) iteration
- customizable probability p and max level

> Note: For deterministic behavior across runs, seed the random generator or use a deterministic level function as discussed later.

```python
import random
from typing import Any, Callable, Generator, Iterable, Optional, Tuple

class SkipListNode:
    __slots__ = ("key", "value", "forward", "level")
    def __init__(self, key: Any, value: Any, level: int):
        # level is number of levels this node spans: indices [0..level-1]
        self.key = key
        self.value = value
        self.level = level
        self.forward = [None] * level  # type: list[Optional[SkipListNode]]


class SkipList:
    def __init__(
        self,
        p: float = 0.5,
        max_level: int = 32,
        key_fn: Optional[Callable[[Any], Any]] = None,
        rng: Optional[random.Random] = None,
    ):
        if not (0.0 < p < 1.0):
            raise ValueError("p must be in (0, 1)")
        if max_level < 1:
            raise ValueError("max_level must be >= 1")
        self.p = p
        self.max_level = max_level
        self.key_fn = key_fn or (lambda x: x)
        self.rng = rng or random.Random()
        # Head sentinel with full height
        self.head = SkipListNode(None, None, max_level)
        self.size = 0

    def __len__(self) -> int:
        return self.size

    def _random_level(self) -> int:
        lvl = 1
        while lvl < self.max_level and self.rng.random() < self.p:
            lvl += 1
        return lvl

    def _less(self, a: Any, b: Any) -> bool:
        return self.key_fn(a) < self.key_fn(b)

    def get(self, key: Any) -> Optional[Any]:
        node = self.head
        # Start from highest level down to 0
        for level in range(self.max_level - 1, -1, -1):
            while node.forward[level] and self._less(node.forward[level].key, key):
                node = node.forward[level]
        node = node.forward[0]
        if node and self.key_fn(node.key) == self.key_fn(key):
            return node.value
        return None

    def contains(self, key: Any) -> bool:
        return self.get(key) is not None

    def insert(self, key: Any, value: Any) -> None:
        update = [None] * self.max_level
        node = self.head
        # Find predecessors at each level
        for level in range(self.max_level - 1, -1, -1):
            while node.forward[level] and self._less(node.forward[level].key, key):
                node = node.forward[level]
            update[level] = node

        # If key exists, update
        candidate = node.forward[0]
        if candidate and self.key_fn(candidate.key) == self.key_fn(key):
            candidate.value = value
            return

        # Insert new node with random height
        lvl = self._random_level()
        new_node = SkipListNode(key, value, lvl)

        # Splice into list for each level
        for i in range(lvl):
            new_node.forward[i] = update[i].forward[i]
            update[i].forward[i] = new_node

        self.size += 1

    def remove(self, key: Any) -> bool:
        update = [None] * self.max_level
        node = self.head
        for level in range(self.max_level - 1, -1, -1):
            while node.forward[level] and self._less(node.forward[level].key, key):
                node = node.forward[level]
            update[level] = node

        target = node.forward[0]
        if not (target and self.key_fn(target.key) == self.key_fn(key)):
            return False

        for i in range(target.level):
            if update[i].forward[i] is target:
                update[i].forward[i] = target.forward[i]

        self.size -= 1
        return True

    def __iter__(self) -> Iterable[Tuple[Any, Any]]:
        node = self.head.forward[0]
        while node:
            yield node.key, node.value
            node = node.forward[0]

    def iter_range(self, min_key: Any, max_key: Any, inclusive: bool = True) -> Generator[Tuple[Any, Any], None, None]:
        if self._less(max_key, min_key):
            return
        # Walk down to first >= min_key
        node = self.head
        for level in range(self.max_level - 1, -1, -1):
            while node.forward[level] and self._less(node.forward[level].key, min_key):
                node = node.forward[level]
        node = node.forward[0]

        # Yield while within range
        while node:
            if self._less(max_key, node.key):
                break
            if inclusive or (self._less(min_key, node.key) and self._less(node.key, max_key)):
                yield node.key, node.value
            node = node.forward[0]
```

### Core API

- insert(key, value): Add or update a key
- get(key): Retrieve value or None
- remove(key): Delete by key; returns True if found
- contains(key): O(log n) membership test
- iter(self): Iterate from smallest key
- iter_range(min_key, max_key, inclusive=True): Efficient range scan

> Important: This implementation assumes unique keys. For duplicates (e.g., multiple items with same score), compose the key: (score, unique_id).

### Usage Examples

Basic use:

```python
sl = SkipList()

# Insert
for k in [5, 1, 3, 9, 7]:
    sl.insert(k, f"val-{k}")

print(len(sl))  # 5
print(sl.get(3))  # "val-3"
print(sl.contains(8))  # False

# Range query
print(list(sl.iter_range(3, 7)))  # [(3, "val-3"), (5, "val-5"), (7, "val-7")]

# Update and delete
sl.insert(3, "updated")
sl.remove(5)
print(list(sl))  # [(1, "val-1"), (3, "updated"), (7, "val-7"), (9, "val-9")]
```

Leaderboard (score-ordered):

```python
players = SkipList(key_fn=lambda k: (k[0], k[1]))  # key=(score, user_id)
# Insert with (score, user_id) to break ties by user_id
players.insert((1500, "alice"), {"name": "Alice", "score": 1500})
players.insert((1800, "bob"), {"name": "Bob", "score": 1800})
players.insert((1750, "carol"), {"name": "Carol", "score": 1750})

# Top-N (descending): iterate and reverse or store negative score
top3 = list(players)[::-1][:3]
print([p[1]["name"] for p in top3])  # ['Bob', 'Carol', 'Alice']
```

Time-windowed events:

```python
import time

events = SkipList(key_fn=lambda k: k)  # key is timestamp (ms)

def add_event(payload):
    ts = int(time.time() * 1000)
    events.insert(ts, payload)

def get_last_minute():
    now = int(time.time() * 1000)
    return list(events.iter_range(now - 60_000, now))
```

## System Design Use Cases

### Leaderboards and Ordered Sets

- Objective: Maintain a set of items ordered by score or timestamp; support top-K queries, rank lookups, and range scans.
- Why skip lists: They naturally support ordered inserts and range queries with expected O(log n + k) complexity.
- Real-world: Redis sorted sets (ZSET) historically use a combination of a hash table (for O(1) lookups) and a skip list (for ordered operations like ZRANGE). This hybrid gives both fast by-key access and ordering by score.

Patterns:
- Composite key (score, id) to break ties
- Maintain both dict and skip list in application if you need O(1) lookups and ordered scans

### LSM-Trees and Memtables

- In LSM-tree storage engines (e.g., RocksDB), the in-memory memtable is often a skip list.
- Benefits: Fast ordered writes, sorted iteration during flush/compaction, simplicity. As data grows, memtables flush to SSTables on disk, which remain sorted for fast range queries and merges.

### Scheduling, Windows, and TTLs

- Use the key as a deadline or expiration time to efficiently:
  - Pop the next due task
  - Sweep expired keys (range scan up to now)
  - Implement sliding windows (time-based range)

This is common in rate limiters, task schedulers, and session cleanup routines.

### Concurrency and Lock-Free Variants

- Skip lists lend themselves to fine-grained locking and lock-free algorithms because insertions and deletions modify localized pointer sets.
- Java’s ConcurrentSkipListMap is a core building block for concurrent ordered maps.
- In C/C++, lock-free skip lists are widely studied and used in high-performance systems.

> Python note: Due to the GIL, truly parallel writes aren’t possible in CPython threads; consider multiprocessing or using a battle-tested C/C++ or JVM implementation if high write concurrency is required.

## Performance Considerations

### Choice of p and Max Levels

- p controls promotion rate:
  - p = 0.5: Typical; height ≈ log2(n). About 2 forward pointers per node on average.
  - p = 0.25: Shorter towers; fewer pointers; slightly more steps per level.
- max_level: Choose ceil(log_{1/p}(N_max)). For N up to 2^32 with p = 0.5, max_level=32 is safe.

Rule of thumb:
- If memory is tight, lower p
- If you prefer lower height and fewer comparisons, higher p (e.g., 0.5)

### Memory, Cache Locality, and Python Overheads

- Skip lists have more pointers than trees on average but avoid rotations and complicated rebalance logic.
- Cache locality: Arrays (like sorted arrays or B-trees) can be better due to contiguity. Skip lists are linked and can cause more cache misses.
- Python overhead: Each node is a Python object with lists of references; overhead is significant for large N. For production-scale workloads, prefer:
  - C extension or Cython
  - A library like “sortedcontainers” (though it uses different internals)
  - Offload to Redis/RocksDB for persistent, process-external storage

### Benchmarking vs Alternatives

Simple benchmark sketch:

```python
import random, time
from bisect import insort

def bench():
    N = 50_000
    keys = list(range(N))
    random.shuffle(keys)

    # SkipList insert
    sl = SkipList()
    t0 = time.time()
    for k in keys:
        sl.insert(k, k)
    t1 = time.time()

    # Python sorted list insert using bisect: O(n) per insert
    arr = []
    t2 = time.time()
    for k in keys:
        insort(arr, k)
    t3 = time.time()

    print(f"SkipList inserts: {t1 - t0:.3f}s")
    print(f"bisect+list inserts: {t3 - t2:.3f}s")

if __name__ == "__main__":
    bench()
```

Expected: SkipList insert scales near O(n log n) overall; list+bisect insert is O(n^2) because insertion shifts elements. For read-heavy workloads with rare inserts, a sorted array can still be competitive due to contiguous memory and very fast binary search.

> Always benchmark with your workload. Factors like object allocation, GC, and memory locality can dwarf asymptotics in Python.

## Determinism, Replication, and Sharding

- Deterministic level selection: In distributed systems or when replicating operations, relying on random() can diverge structures between replicas. Options:
  - Seed PRNG identically and ensure identical operation order (fragile), or
  - Make level a function of the key (e.g., hash(key) to generate a pseudo-random level deterministically).

Example deterministic level:

```python
import hashlib

def deterministic_level(key: Any, p=0.5, max_level=32) -> int:
    # Hash the comparable presentation of key
    h = int.from_bytes(hashlib.blake2b(repr(key).encode(), digest_size=8).digest(), "big")
    lvl = 1
    threshold = int(p * (1 << 64))
    while lvl < max_level and (h & ((1 << 64) - 1)) < threshold:
        h = (1103515245 * h + 12345) & ((1 << 64) - 1)  # LCG step
        lvl += 1
    return lvl
```

- Replication strategy: Rather than replaying random insert operations, replicate the resulting (key, value, level) or use deterministic levels so every replica builds an identical structure.
- Sharding: Partition by a consistent hash of key or by range. For range-heavy workloads, range sharding preserves locality; but beware hotspots.

## Variants and Extensions

- Indexable Skip List: Maintain spans (widths) per level to support get-by-rank and rank-of-key in O(log n). Useful for leaderboards (e.g., position of a player).
- Skip List with Duplicates: Use (score, id) or store a multimap at each key.
- Weighted Skip List: Adjust promotion probabilities or maintain additional metadata to optimize particular queries.
- Skip Graphs: Overlay multiple skip lists to support distributed routing in P2P systems.
- Lock-Free and Hazard-Pointer Variants: For low-latency concurrent writes in systems languages.

## Production Notes for Python Users

- If you need a general-purpose sorted mapping in Python:
  - “sortedcontainers” provides SortedList/SortedDict with excellent performance
  - For ultra-high performance with persistence: Redis ZSET, RocksDB (memtable skip list)
- Concurrency:
  - CPython GIL limits parallel writes; consider multiprocessing or an external service
  - If you must use threads, guard operations with a lock (coarse-grained is fine for many workloads)
- Persistence and durability:
  - In-memory skip lists lose data on crash; pair with a write-ahead log (WAL) or use a database designed for this

## Testing and Validation

Basic correctness tests:

```python
def test_basic():
    sl = SkipList(rng=random.Random(42))  # reproducible
    data = list(range(1000))
    random.shuffle(data)
    for x in data:
        sl.insert(x, str(x))
    assert len(sl) == 1000
    for x in range(1000):
        assert sl.get(x) == str(x)
    for x in [0, 10, 500, 999]:
        assert sl.remove(x) is True
        assert sl.get(x) is None
    assert len(sl) == 996

def test_range():
    sl = SkipList()
    for x in [1, 3, 5, 7, 9]:
        sl.insert(x, x)
    assert list(sl.iter_range(2, 8)) == [(3,3), (5,5), (7,7)]

if __name__ == "__main__":
    test_basic()
    test_range()
    print("tests passed")
```

Property-based testing idea:
- Insert N unique keys, then assert iteration yields sorted order
- Compare behavior against Python’s dict+sorted for random operations
- For indexable variant, cross-check rank operations with a ground truth list

## Conclusion

Skip lists offer an elegant blend of simplicity, performance, and practicality. They deliver expected O(log n) operations without the complexity of rebalancing trees, and they shine in real-world systems that require fast ordered access and range queries.

In Python, a straightforward implementation can carry you far for moderate workloads or teaching. For high-performance or concurrency-heavy use cases, look to C-backed libraries or external systems like Redis and RocksDB. In distributed or replicated settings, remember determinism: make levels a function of the key or replicate levels to avoid divergence.

Whether you’re building leaderboards, schedulers, or components of an LSM-store, skip lists are a battle-tested choice worth mastering.

## Resources

- Skip Lists: A Probabilistic Alternative to Balanced Trees — William Pugh (original paper)
  - https://epaperpress.com/sortsearch/download/skiplist.pdf
- Redis Sorted Sets (ZSET) and Skip Lists
  - Redis data types: https://redis.io/docs/latest/develop/data-types/sorted-sets/
  - Redis source (skiplist implementation in t_zset.c): https://github.com/redis/redis
- RocksDB Architecture (memtable skip list)
  - https://rocksdb.org/blog/2013/11/19/rocksdb-overview.html
- Java ConcurrentSkipListMap (concurrency reference)
  - https://docs.oracle.com/javase/8/docs/api/java/util/concurrent/ConcurrentSkipListMap.html
- SortedContainers for Python
  - https://github.com/grantjenks/python-sortedcontainers
- Lock-Free Skip Lists (Fraser thesis)
  - http://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-579.pdf
- Deterministic skip list levels (discussion)
  - https://stackoverflow.com/questions/66626666/deterministic-random-choices

> Tip: Read the Pugh paper first, then scan Redis’s implementation—it’s concise and production-grade.