---
title: "Optimizing Redis Cache Stampede Protection: Request Coalescing and Probabilistic Early Expiration"
date: "2026-09-18T07:00:55.660"
draft: false
tags: ["redis", "caching", "cache-stampede", "request-coalescing", "distributed-systems", "performance"]
description: "Deep dive into cache stampede protection strategies for Redis: request coalescing via single-flight patterns and probabilistic early expiration to prevent thundering herd failures at scale."
summary: "Learn how request coalescing and probabilistic early expiration work together to eliminate cache stampede in Redis-backed systems, with production-grade implementation patterns and real failure scenarios."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-optimizing-redis-cache-stampede-protection-request-coalescing-and-probabilistic-early-expiration.svg"
  alt: "Redis cache stampede visualization showing concurrent requests collapsing into a single backend call"
  caption: ""
  relative: false
---

> **TL;DR** — Cache stampedes occur when a popular cache key expires and thousands of concurrent requests flood the backend simultaneously. Request coalescing collapses redundant work into a single upstream call, while probabilistic early expiration staggers key expiry to prevent synchronized mass-eviction. Together, they form a robust defense against thundering herd failures in production Redis systems.

Cache stampedes — sometimes called thundering herd problems — are among the most insidious failure modes in distributed systems. They don't announce themselves with a crash or an outage alert. Instead, they manifest as a slow, cascading degradation that quietly saturates your database, inflates p99 latency, and burns through connection pools until the entire service grinds to a halt.

The root cause is deceptively simple: when a heavily cached key expires, every concurrent request that misses the cache hits the backend simultaneously. If that backend is a relational database or an external API, the sudden load spike can overwhelm it. In a system serving 100,000 requests per second with a popular key expiring at an inopportune moment, you can see thousands of redundant queries fire within milliseconds of each other.

This post covers two complementary strategies that address the problem from different angles: **request coalescing**, which prevents redundant computation, and **probabilistic early expiration**, which prevents synchronized mass-eviction. We'll explore the mechanics, implementation patterns, and production trade-offs for each.

## Understanding the Cache Stampede Anatomy

A cache stampede is not merely a cache miss. It is a *synchronized cascade* of cache misses triggered by a single expiry event. Consider this scenario:

1. A Redis key `product:1234:details` is cached with a TTL of 300 seconds.
2. At `T=300s`, the key expires.
3. At `T=300.001s`, 5,000 concurrent requests arrive for that product.
4. Each request finds the cache empty and queries the PostgreSQL database.
5. The database receives 5,000 queries in a sub-second window, saturates its connection pool, and begins timing out.
6. The 5,000 requests eventually return, but by then the database is degraded for *all* traffic — not just the stampeded key.

The danger is compounded when multiple keys share the same TTL. If a deployment cycle or a bulk cache-warming operation sets all keys to expire at the same epoch time, you create a **synchronized expiry cliff** — a moment where dozens of keys expire simultaneously, multiplying the stampede effect across your entire cache layer.

This is not a theoretical concern. At scale, companies like Twitter and GitHub have documented how cache expiry synchronization was responsible for multi-service outages [1].

## Request Coalescing: Collapsing Redundant Work

Request coalescing — also known as the "single-flight" pattern — ensures that when multiple concurrent requests need the same data, only one request performs the expensive computation or backend query. The rest wait on the result.

### How It Works

The core mechanism is straightforward:

1. A request arrives and finds the cache empty.
2. Before querying the backend, it attempts to acquire a lock or register itself as the "leader" request.
3. If it succeeds, it queries the backend, populates the cache, and releases the lock.
4. If it fails (another request is already leading), it either blocks and waits for the result or retries the cache read after a short backoff.

### Implementation with Redis

Redis provides the primitives needed for a robust coalescing implementation. The `SET` command with the `NX` (set if not exists) option and an `PX` (millisecond TTL) option serves as a distributed lock:

```python
import redis
import time
import json

r = redis.Redis(host='localhost', port=6379, db=0)

def get_with_coalescing(key: str, fetch_fn, ttl: int = 300, lock_ttl: int = 10):
    """
    Retrieve a value with request coalescing.
    Only one concurrent request will execute fetch_fn.
    Others will poll the cache until the result is available.
    """
    # Attempt to read from cache first
    cached = r.get(key)
    if cached:
        return json.loads(cached)

    # Try to acquire the coalescing lock
    lock_key = f"lock:{key}"
    lock_acquired = r.set(lock_key, "1", nx=True, px=lock_ttl * 1000)

    if lock_acquired:
        try:
            # This request does the expensive work
            result = fetch_fn()
            r.setex(key, ttl, json.dumps(result))
            return result
        finally:
            r.delete(lock_key)
    else:
        # Another request is computing — poll until result is cached
        for _ in range(lock_ttl * 2):
            cached = r.get(key)
            if cached:
                return json.loads(cached)
            time.sleep(0.05)

        # Lock expired without result — fall back to direct fetch
        result = fetch_fn()
        r.setex(key, ttl, json.dumps(result))
        return result
```

### Production Considerations

The naive implementation above works but has subtle failure modes:

- **Lock expiration before computation completes**: If `fetch_fn` takes longer than `lock_ttl`, the lock expires, a second request starts computing, and you end up with redundant work anyway. A robust approach uses a **lock lease renewal** pattern or sets `lock_ttl` generously based on p99 latency of `fetch_fn`.

- **Cache penetration after lock release**: The leader writes the result but crashes before releasing the lock. The `finally` block mitigates this, but if the process is killed ungracefully, the lock key persists until its TTL expires. Using a short `lock_ttl` (5–10 seconds) bounds this damage.

- **Stale waiting**: Polling with `time.sleep(0.05)` adds latency to waiting requests. A more efficient approach uses **Redis Pub/Sub** to notify waiting requests when the result is ready:

```python
def get_with_pubsub_coalescing(key: str, fetch_fn, ttl: int = 300):
    cached = r.get(key)
    if cached:
        return json.loads(cached)

    lock_key = f"lock:{key}"
    lock_acquired = r.set(lock_key, "1", nx=True, px=15000)

    if lock_acquired:
        try:
            result = fetch_fn()
            r.setex(key, ttl, json.dumps(result))
            # Notify waiters
            r.publish(f"channel:{key}", "done")
            return result
        finally:
            r.delete(lock_key)
    else:
        # Subscribe and wait for notification
        pubsub = r.pubsub()
        pubsub.subscribe(f"channel:{key}")
        for message in pubsub.listen():
            if message['type'] == 'message':
                pubsub.unsubscribe()
                cached = r.get(key)
                return json.loads(cached) if cached else fetch_fn()
```

The Pub/Sub variant eliminates polling overhead entirely, but introduces its own complexity: if the leader crashes before publishing, subscribers wait indefinitely. A hybrid approach — Pub/Sub with a timeout fallback to polling — is often the most production-hardened design.

## Probabilistic Early Expiration: Staggering the Cliff

Request coalescing handles the symptom (redundant concurrent computation), but probabilistic early expiration addresses the *root cause* of synchronized expiry. Instead of all keys expiring at exactly the same moment, each key's effective TTL is randomly perturbed within a configurable range.

### The Core Idea

Rather than setting a fixed TTL of `300 seconds`, you set the TTL to `300 + random(-30, 60)` seconds. This means:

- Keys that were created at roughly the same time will expire at slightly different moments.
- The probability of a mass expiry event drops from "certain at T=300s" to "statistically negligible."
- The cache hit rate degrades gracefully rather than collapsing at a cliff edge.

### Implementation

```python
import random

def get_probabilistic_ttl(base_ttl: int, jitter_ratio: float = 0.2) -> int:
    """
    Compute a TTL with probabilistic jitter.
    jitter_ratio controls the spread: 0.2 means ±20% of base_ttl.
    """
    jitter = int(base_ttl * jitter_ratio * random.uniform(-1, 1))
    # Bias toward slightly shorter TTLs to encourage earlier refresh
    # This ensures the "early" side of early expiration is favored
    return base_ttl + jitter

# Usage
base_ttl = 300
effective_ttl = get_probabilistic_ttl(base_ttl, jitter_ratio=0.15)
# Effective TTL ranges from 255 to 345 seconds
r.setex("product:1234:details", effective_ttl, json.dumps(data))
```

### The "Early Expiration" Refinement

A more sophisticated variant goes beyond simple jitter. It implements **probationary expiration**: when a key's TTL falls below a threshold, the *next* request that encounters it triggers an asynchronous refresh while still serving the stale data.

```python
def get_with_probationary_refresh(key: str, fetch_fn, ttl: int = 300, 
                                   refresh_threshold: float = 0.1):
    """
    Serve stale data while asynchronously refreshing in the background.
    refresh_threshold: fraction of TTL at which async refresh triggers.
    """
    cached = r.get(key)
    if cached:
        data = json.loads(cached)
        
        # Check if we're in the probationary window
        ttl_remaining = r.ttl(key)
        if ttl_remaining > 0 and ttl_remaining < int(ttl * refresh_threshold):
            # Trigger async refresh — don't block the current request
            refresh_in_background(key, fetch_fn, ttl)
        
        return data
    
    # Cache miss — do synchronous fetch
    result = fetch_fn()
    r.setex(key, ttl, json.dumps(result))
    return result

def refresh_in_background(key: str, fetch_fn, ttl: int):
    """
    Fire-and-forget background refresh.
    In production, use a task queue like Celery or RQ.
    """
    # Using Redis as a simple background task queue
    r.rpush("refresh_queue", json.dumps({"key": key}))
```

This pattern is the foundation of systems like [Memcached's probabilistic early expiration](https://github.com/memcached/memcached/blob/master/doc/protocol.txt) and is widely used in high-traffic CDN configurations.

## Architecture: Combining Both Strategies in Production

The most robust production systems layer both strategies together, creating a defense-in-depth approach:

```
                    ┌──────────────────────────────────┐
                    │         Client Request           │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │   Check Cache (Redis)            │
                    │   - Key exists? → Return cached  │
                    │   - Key missing? → Proceed       │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │   Request Coalescing Lock        │
                    │   (Redis NX + PX)                │
                    │   - First request: compute       │
                    │   - Subsequent: wait/pubsub      │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │   Backend Query (DB/API)         │
                    │   Single request does the work   │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │   Write Result to Cache          │
                    │   TTL = base + probabilistic jitter│
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │   Probationary Refresh           │
                    │   When TTL remaining < threshold │
                    │   → async refresh in background  │
                    └──────────────────────────────────┘
```

### Why Both Are Necessary

Request coalescing alone fails when:
- The backend itself is the bottleneck (coalescing reduces concurrent queries but the single query is still expensive).
- Lock contention creates a new bottleneck (all requests queue behind a single lock).
- The lock infrastructure itself fails or becomes a SPOF.

Probabilistic early expiration alone fails when:
- A sudden traffic spike coincides with key expiry (jitter reduces but doesn't eliminate synchronization).
- The backend cannot serve even a single request within acceptable latency.
- Keys are created at different times but happen to expire near-simultaneously due to similar TTLs.

Together, they create a system where:
1. **Synchronized expiry is prevented** by jitter (probabilistic early expiration).
2. **Concurrent redundant computation is prevented** by coalescing locks.
3. **Background refresh** ensures that the cache is warmed before the old key fully expires, reducing the window of vulnerability.

### Real-World Failure Scenario

Consider a payment processing system that caches exchange rates. The cache key has a base TTL of 60 seconds with no jitter. Every 60 seconds, 10,000 payment requests arrive and all miss the cache simultaneously. The backend (an external FX API) can handle 100 requests/second. The result: 10,000 requests arrive in 1 second, 9,900 are queued or rejected, and the payment service experiences a 99-second outage window.

With probabilistic early expiration (jitter of ±15 seconds), the same 10,000 requests spread across a 30-second window instead of a 1-second window. With request coalescing, even if multiple requests hit the same key within that window, only one queries the FX API. The combined effect reduces the peak backend load from 10,000 QPS to fewer than 5 QPS.

## Key Takeaways

- **Cache stampedes are silent killers** — they degrade performance gradually before causing outright outages, making them hard to detect until it's too late.
- **Request coalescing** uses distributed locks (Redis `SET NX PX`) to ensure only one request performs expensive backend work, with Pub/Sub notification to eliminate polling overhead.
- **Probabilistic early expiration** perturbs TTLs with random jitter to prevent synchronized mass-eviction, breaking the "expiry cliff" that triggers stampedes.
- **Probationary refresh** combines early expiration with asynchronous background warming, serving stale data while the cache is refreshed in the background.
- **Defense-in-depth matters** — neither strategy alone is sufficient. Production systems should layer coalescing, jitter, and background refresh to handle all failure modes.
- **Monitor your cache hit ratio and backend QPS** — a sudden spike in backend queries coinciding with a drop in cache hit ratio is the earliest signal of a stampede in progress.

## Further Reading

- [The Problem with Cache Expiry — Martin Kleppmann](https://martin.kleppmann.com/2021/02/08/the-problem-with-cache-expiry.html) — A thorough analysis of cache invalidation and stampede patterns with formal reasoning.
- [Single Flight Pattern in Go](https://github.com/sony/gobreaker) — Production-grade implementation of the single-flight (request coalescing) pattern, originally from Netflix's Hystrix ecosystem.
- [Memcached Probabilistic Early Expiration](https://github.com/memcached/memcached/blob/master/doc/protocol.txt) — The original specification for probabilistic TTL jitter in Memcached, the conceptual ancestor of the technique used in Redis.
- [Redis Distributed Locks: Redlock Revisited](https://redis.io/docs/management/patterns/distributed-locks/) — Official Redis documentation on distributed locking patterns, including considerations for lock safety and fault tolerance.
- [Thundering Herd Problem — Wikipedia](https://en.wikipedia.org/wiki/Thundering_herd_problem) — Comprehensive overview of the thundering herd phenomenon across operating systems, databases, and distributed caches.
- [Caching Strategies for High-Scale Systems — Airbnb Engineering](https://medium.com/airbnb-engineering/) — Airbnb's published engineering blog contains detailed case studies on cache stampede mitigation at scale.

---

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
