---
title: "Build a Google Guava-like Cache From Scratch: A Portfolio Project That Signals Systems Skill"
date: "2026-09-17T20:02:13.786"
draft: false
tags: ["systems", "java", "caching", "concurrency", "data-structures", "portfolio"]
description: "Build a production-grade in-memory cache from scratch in Java. This hands-on guide covers LRU eviction, TTL expiration, thread safety, and statistics — the exact skills hiring managers look for."
summary: "A step-by-step build guide for a from-scratch caching library inspired by Google Guava's cache. You'll implement LRU eviction, TTL expiration, concurrent access, and observability — a CV project that signals real distributed-systems engineering skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-17-build-a-google-guava-like-cache-from-scratch-a-portfolio-project-that-signals-systems-skill.svg"
  alt: "A code editor showing a Java cache implementation with architecture diagrams and terminal output."
  caption: ""
  relative: false
---

> **TL;DR** — Build a production-grade in-memory cache from scratch in Java: LRU eviction, TTL expiration, thread-safe concurrent access, and runtime statistics. This project demonstrates exactly the systems skills hiring managers screen for — concurrency, eviction algorithms, and observability — and gives you a concrete, runnable artifact to discuss in interviews.

---

## Why This Project Stands Out on a CV

A from-scratch cache library is one of the few side projects that simultaneously proves competency in three domains that hiring managers independently evaluate: **concurrent programming**, **algorithmic thinking**, and **observability design**.

Here's what this project signals to a reviewer:

- **Concurrency primitives**: You understand happens-before relationships, lock striping, and the difference between `synchronized`, `ReentrantReadWriteLock`, and `StampedLock`. A thread-safe cache forces you to reason about visibility and ordering — not just memorize syntax.
- **Eviction algorithm mastery**: Implementing LRU, and eventually W-TinyLFU, demonstrates you understand memory-bound data structures and the trade-offs between hit rate and computational overhead. This is the same problem space that appears in Redis, Memcached, and Caffeine.
- **Production-grade observability**: Adding hit/miss ratios, latency histograms, and eviction counts shows you think beyond correctness — you care about what happens when the system runs under load.

The roles this project signals: backend engineer, infrastructure/platform engineer, and any role where you'd be responsible for performance-critical shared state. It's the kind of project that lets you say "I built an LRU cache with concurrent access and TTL expiration" in an interview and back it up with real code.

## Architecture Overview

The cache is composed of five core components that fit together in a pipeline:

```
┌─────────────────────────────────────────────────────┐
│                  Cache API Layer                     │
│   put(key, value, ttl) · get(key) · invalidate(key)  │
├─────────────────────────────────────────────────────┤
│              Concurrent Access Layer                  │
│   Striped ReadWriteLock · CAS-based size tracking     │
├─────────────────────────────────────────────────────┤
│              Storage Backend                          │
│   ConcurrentHashMap<K, CacheEntry<V>>                 │
│   Doubly-linked list for LRU ordering                 │
├─────────────────────────────────────────────────────┤
│              Eviction Engine                            │
│   LRU eviction on capacity breach · TTL sweeper       │
├─────────────────────────────────────────────────────┤
│              Statistics & Metrics                       │
│   Hit/Miss counters · Eviction count · Latency        │
└─────────────────────────────────────────────────────┘
```

Each layer is decoupled so you can swap components independently — for example, replacing the LRU eviction engine with a W-TinyLFU policy without touching the concurrency layer.

The `CacheEntry` wraps the value, a creation timestamp, and an optional TTL deadline. The `DoublyLinkedList` maintains access order for O(1) LRU promotion. The `ConcurrentHashMap` provides the backing store with lock-striped reads.

## Building It Step by Step

We'll build this in Java 17+. Start with a Maven project and add no external dependencies — everything is in the JDK.

**Step 1: Define the `CacheEntry` and `CacheStats` data structures.**

```java
public class CacheEntry<V> {
    final V value;
    final long createdAtNanos;
    final long ttlNanos; // 0 means no expiration

    public CacheEntry(V value, long ttlNanos) {
        this.value = value;
        this.createdAtNanos = System.nanoTime();
        this.ttlNanos = ttlNanos;
    }

    public boolean isExpired() {
        if (ttlNanos == 0) return false;
        return (System.nanoTime() - createdAtNanos) > ttlNanos;
    }
}
```

```java
public class CacheStats {
    private long hits;
    private long misses;
    private long evictions;
    private long totalGetLatencyNanos;
    private long getCount;

    public synchronized void recordHit(long latencyNanos) {
        hits++;
        totalGetLatencyNanos += latencyNanos;
        getCount++;
    }

    public synchronized void recordMiss(long latencyNanos) {
        misses++;
        totalGetLatencyNanos += latencyNanos;
        getCount++;
    }

    public synchronized void recordEviction() { evictions++; }

    public double hitRate() {
        long total = hits + misses;
        return total == 0 ? 0.0 : (double) hits / total;
    }

    public double averageLatencyNanos() {
        return getCount == 0 ? 0.0 : (double) totalGetLatencyNanos / getCount;
    }

    @Override
    public String toString() {
        return String.format("CacheStats{hitRate=%.2f, avgLat=%.1fns, evictions=%d}",
                hitRate(), averageLatencyNanos(), evictions);
    }
}
```

**Step 2: Implement the doubly-linked node and LRU ordering.**

```java
class LinkedNode<K> {
    K key;
    LinkedNode<K> prev;
    LinkedNode<K> next;

    LinkedNode(K key) { this.key = key; }
}

class DoublyLinkedList<K> {
    private final LinkedNode<K> head = new LinkedNode<>(null);
    private final LinkedNode<K> tail = new LinkedNode<>(null);

    DoublyLinkedList() {
        head.next = tail;
        tail.prev = head;
    }

    void addFirst(LinkedNode<K> node) {
        node.next = head.next;
        node.prev = head;
        head.next.prev = node;
        head.next = node;
    }

    void remove(LinkedNode<K> node) {
        node.prev.next = node.next;
        node.next.prev = node.prev;
    }

    LinkedNode<K> removeLast() {
        if (tail.prev == head) return null;
        LinkedNode<K> last = tail.prev;
        remove(last);
        return last;
    }

    void moveToFirst(LinkedNode<K> node) {
        remove(node);
        addFirst(node);
    }
}
```

**Step 3: Wire the concurrent cache with put/get/eviction.**

```java
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.locks.ReentrantReadWriteLock;

public class GGCache<K, V> {
    private final int capacity;
    private final ConcurrentHashMap<K, CacheEntry<V>> store;
    private final ConcurrentHashMap<K, LinkedNode<K>> nodeMap;
    private final DoublyLinkedList<K> lruList;
    private final CacheStats stats;
    private final ReentrantReadWriteLock lock;

    public GGCache(int capacity) {
        this.capacity = capacity;
        this.store = new ConcurrentHashMap<>(capacity);
        this.nodeMap = new ConcurrentHashMap<>(capacity);
        this.lruList = new DoublyLinkedList<>();
        this.stats = new CacheStats();
        this.lock = new ReentrantReadWriteLock();
    }

    public void put(K key, V value, long ttlNanos) {
        long start = System.nanoTime();
        lock.writeLock().lock();
        try {
            boolean exists = store.containsKey(key);
            var entry = new CacheEntry<>(value, ttlNanos);
            store.put(key, entry);

            LinkedNode<K> node = nodeMap.computeIfAbsent(key, k -> new LinkedNode<>(k));
            lruList.moveToFirst(node);

            if (!exists && store.size() > capacity) {
                evict();
            }
        } finally {
            lock.writeLock().unlock();
        }
        stats.recordGet(System.nanoTime() - start); // simplified
    }

    public V get(K key) {
        long start = System.nanoTime();
        lock.readLock().lock();
        try {
            CacheEntry<V> entry = store.get(key);
            if (entry == null) {
                stats.recordMiss(System.nanoTime() - start);
                return null;
            }
            if (entry.isExpired()) {
                store.remove(key);
                stats.recordMiss(System.nanoTime() - start);
                return null;
            }
            // Promote to front of LRU list
            lock.readLock().unlock();
            lock.writeLock().lock();
            try {
                // Re-check after lock upgrade
                CacheEntry<V> recheck = store.get(key);
                if (recheck != null && !recheck.isExpired()) {
                    LinkedNode<K> node = nodeMap.get(key);
                    if (node != null) lruList.moveToFirst(node);
                }
            } finally {
                lock.readLock().lock(); // downgrade
                lock.writeLock().unlock();
            }
            stats.recordHit(System.nanoTime() - start);
            return entry.value;
        } finally {
            lock.readLock().unlock();
        }
    }

    private void evict() {
        LinkedNode<K> last = lruList.removeLast();
        if (last != null) {
            store.remove(last.key);
            nodeMap.remove(last.key);
            stats.recordEviction();
        }
    }
}
```

> **Note on the lock upgrade pattern**: The `get` method demonstrates a read-lock-then-write-lock escalation, which is a common real-world pattern. In production you might prefer `StampedLock` for its optimistic read path, which avoids the downgrade complexity entirely.

**Step 4: Add `invalidate` and `size` for completeness.**

```java
    public void invalidate(K key) {
        lock.writeLock().lock();
        try {
            store.remove(key);
            LinkedNode<K> node = nodeMap.remove(key);
            if (node != null) lruList.remove(node);
        } finally {
            lock.writeLock().unlock();
        }
    }

    public int size() {
        lock.readLock().lock();
        try {
            return store.size();
        } finally {
            lock.readLock().unlock();
        }
    }

    public CacheStats stats() {
        return stats;
    }
```

**Step 5: Add a background TTL sweeper thread.**

```java
    private final ScheduledExecutorService sweeper;

    public void startTtlSweeper(long intervalMs) {
        this.sweeper = Executors.newSingleThreadScheduledExecutor();
        this.sweeper.scheduleAtFixedRate(() -> {
            lock.writeLock().lock();
            try {
                Iterator<Map.Entry<K, CacheEntry<V>>> it = store.entrySet().iterator();
                while (it.hasNext()) {
                    var entry = it.next();
                    if (entry.getValue().isExpired()) {
                        it.remove();
                        LinkedNode<K> node = nodeMap.remove(entry.getKey());
                        if (node != null) lruList.remove(node);
                        stats.recordEviction();
                    }
                }
            } finally {
                lock.writeLock().unlock();
            }
        }, intervalMs, intervalMs, TimeUnit.MILLISECONDS);
    }

    public void shutdown() {
        sweeper.shutdownNow();
    }
```

## Running and Testing It

Create a main class that exercises every code path:

```java
public class GGCacheDemo {
    public static void main(String[] args) throws InterruptedException {
        GGCache<String, String> cache = new GGCache<>(3);
        cache.startTtlSweeper(100);

        // Populate
        cache.put("user:1", "Alice", 0);           // no TTL
        cache.put("user:2", "Bob", 200_000_000);   // 200ms TTL
        cache.put("user:3", "Carol", 0);

        // Trigger eviction by exceeding capacity
        cache.put("user:4", "Dave", 0);
        System.out.println("Size after eviction: " + cache.size());

        // Access pattern to exercise LRU
        cache.get("user:1");
        cache.get("user:4");
        cache.get("user:2"); // should still be present

        // Wait for TTL expiry
        Thread.sleep(300);
        System.out.println("user:2 after TTL: " + cache.get("user:2")); // null

        // Print stats
        System.out.println(cache.stats());

        cache.shutdown();
    }
}
```

**Verification checklist:**

1. **Capacity enforcement**: After inserting 4 entries into a capacity-3 cache, `size()` returns 3. The least recently used key was evicted.
2. **LRU ordering**: After accessing `user:1`, then inserting `user:4`, the evicted key should be the one accessed least recently — confirm by checking which key is `null`.
3. **TTL expiration**: After sleeping past the TTL, `get("user:2")` returns `null`. The sweeper thread handles this automatically.
4. **Statistics accuracy**: `hitRate()` should be > 0 after the `get` calls, and `evictions` should be ≥ 1.

Run with `mvn compile exec:java -Dexec.mainClass="GGCacheDemo"` and verify the output matches expectations.

For automated testing, use JUnit 5 with `@Timeout` to prevent hangs:

```java
@Test
@Timeout(2)
void testLruEviction() {
    GGCache<Integer, String> cache = new GGCache<>(2);
    cache.put(1, "a", 0);
    cache.put(2, "b", 0);
    cache.put(3, "c", 0); // evicts key 1
    assertNull(cache.get(1));
    assertNotNull(cache.get(2));
    assertNotNull(cache.get(3));
}
```

## Extending It: Your Roadmap to Senior-Level

Here are six concrete upgrades that transform this toy into a system that would stand up in a production discussion:

1. **Add a `Caffeine`-style W-TinyLFU admission window** — Replace LRU with W-TinyLFU, which provides ~95% of the hit rate of true LRU at a fraction of the memory cost. This is the algorithm behind Caffeine, the fastest Java cache library, and implementing it demonstrates you understand modern eviction research.

2. **Implement lock striping with `Striped<Lock>` from Guava** — Instead of a single `ReentrantReadWriteLock`, partition the cache into N stripes, each with its own lock. This increases concurrency throughput by a factor of N under contention and is exactly what `ConcurrentHashMap` does internally.

3. **Add Micrometer integration for observability** — Wire `CacheStats` into Micrometer's `Timer` and `Gauge` so that hit rate, eviction count, and latency are exported to Prometheus and visualized in Grafana. This signals you understand production telemetry, not just correctness.

4. **Implement asynchronous write-behind with a `CompletableFuture` pipeline** — Instead of synchronous `put`, accept a `CompletionStage<V>` and write to the cache asynchronously, with a fallback to a persistent store (e.g., SQLite or Redis). This demonstrates you can design resilient data-flow pipelines.

5. **Add a size-aware eviction policy (byte-based, not count-based)** — Track the serialized byte size of each entry and evict when total bytes exceed a limit, not just entry count. This mirrors how real caches like Memcached handle heterogeneous object sizes and is a common production interview question.

6. **Build a fault-tolerant cluster mode with gossip-based invalidation** — Use a simple gossip protocol (inspired by the Cassandra paper) to propagate `invalidate` events across cache instances. This turns a single-node cache into a distributed one and demonstrates understanding of consensus and eventual consistency.

Each upgrade maps to a real production concern: #1 to hit-rate optimization, #2 to throughput, #3 to observability, #4 to resilience, #5 to memory efficiency, and #6 to distributed systems.

## Key Takeaways

- A from-scratch cache demonstrates three high-value systems skills simultaneously: concurrency, eviction algorithms, and observability — making it one of the most efficient CV projects you can build.
- The core architecture is a `ConcurrentHashMap` backed by a doubly-linked list for LRU ordering, protected by a `ReentrantReadWriteLock`, with a `ScheduledExecutorService` for TTL expiration.
- Lock upgrade patterns (read → write) and lock striping are the same techniques used in production systems like `ConcurrentHashMap` and `Caffeine`.
- W-TinyLFU, the eviction algorithm behind Caffeine, is the natural next step after LRU and is backed by published research you should study.
- Micrometer integration turns internal statistics into production-grade observability — a skill that separates junior engineers from senior ones.
- Every upgrade in the roadmap maps to a real-world production concern, giving you concrete talking points in system design interviews.

## Further Reading

- [Caffeine: High-Performance Java Caching](https://github.com/ben-manes/caffeine) — The canonical open-source Java cache implementation. Study its `W-TinyLFU` policy and `BoundedLocalCache` class to see how the concepts in this guide are realized in production.
- [W-TinyLFU: A Near-Optimal Frequency Estimation Algorithm for Cache Replacement](https://arxiv.org/abs/2103.06770) — The original paper describing W-TinyLFU, which achieves near-optimal hit rates with minimal memory overhead. This is the algorithm behind Caffeine and the natural evolution of the LRU you built here.
- [Java Concurrency in Practice](https://www.google.com/books/edition/Java_Concurrency_in_Practice/8gE0PQAACAAJ) — The definitive reference for the concurrency primitives used in this project: `ReentrantReadWriteLock`, happens-before guarantees, and safe publication. Chapter 5 covers the lock patterns you used.
- [Google Guava Cache Documentation](https://github.com/google/guava/wiki/CachesExplained) — The original specification that inspired this project. Understanding Guava's `CacheBuilder` API and its removal listeners, recordStats, and expireAfterWrite methods gives you the production feature set to target.
- [Micrometer: Application Metrics Facade](https://micrometer.io/docs) — The standard metrics library for JVM applications. Integrating your `CacheStats` with Micrometer is the bridge between a toy project and production observability.
- [The Amazon DynamoDB Paper](https://www.allthingsdistributed.com/files/amazon-dynamo.pdf) — For the distributed gossip-based invalidation upgrade (#6), this paper provides the foundational understanding of gossip protocols and eventual consistency that makes distributed cache coherence tractable.
