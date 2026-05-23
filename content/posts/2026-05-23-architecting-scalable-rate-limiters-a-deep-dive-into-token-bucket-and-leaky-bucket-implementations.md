---
title: "Architecting Scalable Rate Limiters: A Deep Dive into Token Bucket and Leaky Bucket Implementations"
date: "2026-05-23T12:00:07.442"
draft: false
tags: ["rate limiting","token bucket","leaky bucket","architecture","scalability","distributed systems"]
description: "Explore how to design scalable rate limiters using token bucket and leaky bucket algorithms, with production patterns, code samples, and architecture trade‑offs."
summary: "A practical guide to building high‑throughput, distributed rate limiters with token and leaky bucket techniques."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-23-architecting-scalable-rate-limiters-a-deep-dive-into-token-bucket-and-leaky-bucket-implementations.svg"
  alt: "Diagram of token bucket and leaky bucket mechanisms."
  caption: ""
  relative: false
---

> **TL;DR** — Token bucket and leaky bucket are the two workhorses for high‑performance rate limiting. By sharding state, leveraging atomic counters, and coupling the algorithms with modern data stores like Redis or Cassandra, you can enforce per‑user, per‑API, or per‑service quotas at millions of requests per second with deterministic latency.

Rate limiting is no longer a “nice‑to‑have” feature; it’s a core guardrail for any SaaS platform that must protect downstream services, enforce SLAs, and prevent abuse. While the concept is simple—allow only *N* requests in a given window—the engineering challenges explode when you need to scale the limiter across multiple data centers, keep latency sub‑millisecond, and survive node failures. This post walks through the token bucket and leaky bucket algorithms, shows production‑ready implementations, and compares architectural patterns that make them work at internet scale.

## The Problem Space

Modern APIs often expose a handful of endpoints that collectively serve billions of requests per day. Engineers must answer three questions:

1. **Throughput** – How many requests can the limiter evaluate per second without becoming a bottleneck?
2. **Consistency** – Do we need strict per‑client limits (strong consistency) or is eventual consistency acceptable?
3. **Failure Isolation** – What happens when the limiter’s backing store is unavailable?

A naïve in‑process limiter works for a single instance but collapses under horizontal scaling. The solution is to externalize the state (tokens or leaky bucket counters) to a low‑latency, highly available store and design the algorithm to be *idempotent* and *partitionable*.

## Token Bucket: Theory and Production Patterns

The token bucket algorithm models a bucket that fills at a constant rate *r* (tokens per second) up to a maximum capacity *C*. Each incoming request consumes one token; if the bucket is empty, the request is throttled.

### Core Algorithm

```python
import time
import threading

class TokenBucket:
    def __init__(self, rate: float, capacity: int):
        self.rate = rate          # tokens per second
        self.capacity = capacity  # max tokens
        self.tokens = capacity
        self.timestamp = time.monotonic()
        self.lock = threading.Lock()

    def allow(self, tokens: int = 1) -> bool:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.timestamp
            # Refill based on elapsed time
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.timestamp = now
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
```

The code above is perfect for a single‑process service but fails when multiple workers need to share the same bucket. The next sections show how to distribute it.

### Distributed Implementation with Redis

Redis offers atomic `INCRBY` and Lua scripting, which lets us perform the refill‑and‑consume step in a single round‑trip. The Lua script below implements a token bucket that lives in a Redis key:

```lua
-- KEYS[1] = bucket key
-- ARGV[1] = current timestamp (ms)
-- ARGV[2] = refill rate (tokens per ms)
-- ARGV[3] = capacity
-- ARGV[4] = tokens requested
local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens = tonumber(bucket[1]) or tonumber(ARGV[3])
local last_ts = tonumber(bucket[2]) or 0
local now = tonumber(ARGV[1])
local delta = now - last_ts
local refill = delta * tonumber(ARGV[2])
tokens = math.min(tonumber(ARGV[3]), tokens + refill)
if tokens < tonumber(ARGV[4]) then
    -- Not enough tokens
    redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
    return 0
else
    tokens = tokens - tonumber(ARGV[4])
    redis.call('HMSET', KEYS[1], 'tokens', tokens, 'ts', now)
    return 1
end
```

**How it works in production**

| Step | Detail |
|------|--------|
| **Sharding** | Use a hash of the client identifier (API key, IP, JWT sub) to route to a specific Redis cluster shard. This spreads load evenly and keeps hot keys localized. |
| **TTL** | Set a short expiration (e.g., 5 seconds) on each bucket key to allow automatic cleanup of idle clients. |
| **Cold Start** | On first hit, the script falls back to the configured capacity, ensuring a “burst” of *C* requests is allowed. |
| **Fail‑Open vs Fail‑Close** | In a Redis outage you can fall back to a local in‑process bucket for a limited time (fail‑open) or reject all traffic (fail‑close) depending on your risk posture. |

The Lua script runs in < 0.5 ms on a properly provisioned Redis node, making it suitable for high‑QPS APIs. Companies like Stripe and GitHub use a similar pattern to protect their public endpoints.

### Scaling Beyond a Single Redis Instance

When you need > 10 M QPS, a single Redis cluster becomes a bottleneck. The typical pattern is **client‑side token pre‑allocation**:

1. Each worker node requests a “token lease” of *N* tokens from Redis (e.g., 1 000 tokens).
2. The worker then serves requests locally until the lease expires, at which point it renews.
3. Lease renewal is performed using a CAS (compare‑and‑set) Lua script to avoid race conditions.

This reduces Redis round‑trips by a factor of *N* while preserving global rate limits.

## Leaky Bucket: Theory and Production Patterns

The leaky bucket algorithm can be visualized as a bucket that leaks at a constant rate *r* (requests per second). Incoming requests are enqueued; if the queue exceeds capacity *C*, excess requests are dropped. Unlike token bucket, leaky bucket enforces a strict output rate, smoothing bursts.

### Core Algorithm

```go
type LeakyBucket struct {
    capacity   int
    rate       float64 // requests per second
    queue      int
    lastLeak   time.Time
    mu         sync.Mutex
}

func NewLeakyBucket(rate float64, capacity int) *LeakyBucket {
    return &LeakyBucket{
        rate:     rate,
        capacity: capacity,
        lastLeak: time.Now(),
    }
}

// Allow returns true if the request can be queued.
func (b *LeakyBucket) Allow() bool {
    b.mu.Lock()
    defer b.mu.Unlock()

    now := time.Now()
    elapsed := now.Sub(b.lastLeak).Seconds()
    leaked := int(elapsed * b.rate)

    if leaked > 0 {
        b.queue = max(0, b.queue-leaked)
        b.lastLeak = now
    }

    if b.queue < b.capacity {
        b.queue++
        return true
    }
    return false
}
```

Again, this works for a single instance. To distribute, we need a central store that can atomically manage the queue length.

### Distributed Implementation with Apache Cassandra

Cassandra’s lightweight transactions (LWT) let us implement a compare‑and‑set on a counter column. The pattern:

```cql
-- Table definition
CREATE TABLE rate_limiter.leaky_bucket (
    bucket_id text PRIMARY KEY,
    queue int,
    last_leak timestamp
);
```

The update logic (pseudo‑CQL with LWT):

```cql
BEGIN BATCH
    UPDATE rate_limiter.leaky_bucket
    SET queue = ?, last_leak = ?
    WHERE bucket_id = ?
    IF queue = ?;   -- compare old queue value
APPLY BATCH;
```

A service writes the current `queue` and `last_leak` after calculating the leaked amount. If the `IF` clause fails, the service retries with the fresh values. While slower than Redis, Cassandra’s multi‑region replication makes it attractive for globally distributed APIs where latency budgets are looser (e.g., 10–20 ms).

### Integration with Kafka and gRPC

Many streaming platforms need to throttle producers or consumers. Embedding a leaky bucket in a **Kafka interceptor** works as follows:

1. Interceptor extracts the client ID from the request metadata.
2. It calls a micro‑service (written in Go) that runs the distributed leaky bucket logic.
3. If the service returns `false`, the interceptor throws a `ThrottlingException`, causing the client to back off.

Because the interceptor runs in the producer’s JVM, the extra network hop is negligible compared to the broker round‑trip.

## Architecture Comparison

| Dimension | Token Bucket | Leaky Bucket |
|-----------|--------------|--------------|
| **Burst handling** | Allows up to *C* immediate requests; ideal for APIs that need occasional spikes. | Queues bursts and releases them at a fixed rate; smoother traffic but higher latency for bursts. |
| **Implementation complexity** | Simple atomic decrement; easier to shard. | Requires queue length management; LWT or Lua scripts are more involved. |
| **Typical backing store** | Redis (in‑memory, low latency). | Cassandra or PostgreSQL (strong consistency, durability). |
| **Failure mode** | If store unavailable, either reject or fall back to local bucket (risk of over‑issuance). | If store unavailable, queue can stall, causing back‑pressure; safer to reject. |
| **Use cases** | Public API rate limits, per‑user quotas, burst‑tolerant services. | Messaging pipelines, write‑heavy services, where output rate must be capped. |

Both patterns can coexist: a token bucket for per‑client burst limits, followed by a leaky bucket that smooths aggregate traffic before hitting downstream services.

## Patterns in Production

### 1. Hierarchical Limiting

Combine **global** and **local** buckets:

- **Global bucket** (Redis) enforces overall platform QPS.
- **Local bucket** (in‑process) enforces per‑instance limits, protecting the instance from sudden spikes even if the global bucket grants tokens.

The request flow:

```
client → API gateway (local bucket) → token bucket service (global) → backend
```

If the local bucket rejects, the request never hits Redis, preserving bandwidth.

### 2. Dynamic Rate Adjustment

Use **feedback loops** to adjust *r* (refill rate) based on downstream latency:

```python
if backend_latency > 200ms:
    new_rate = max(min_rate, current_rate * 0.8)
else:
    new_rate = min(max_rate, current_rate * 1.05)
redis.hset(bucket_key, 'rate', new_rate)
```

This pattern is described in detail by the **Google Cloud Architecture Center** for adaptive throttling.

### 3. Multi‑Region Consistency with CRDTs

When you must enforce limits across regions without a single point of failure, **Conflict‑free Replicated Data Types (CRDTs)** can approximate a token bucket. Each region maintains a local counter; periodic anti‑entropy merges reconcile token consumption. The trade‑off is eventual consistency, which is acceptable for non‑critical quotas (e.g., promotional offer limits).

## Key Takeaways

- Token bucket is the go‑to algorithm for burst‑friendly rate limiting; implement it with Redis Lua scripts for sub‑millisecond latency.
- Leaky bucket provides strict output pacing; Cassandra LWT or PostgreSQL advisory locks give strong consistency at the cost of higher latency.
- Sharding by client identifier distributes load; pre‑allocating token leases reduces round‑trips dramatically.
- Combine hierarchical buckets (local + global) to protect both the application instance and the overall platform.
- Adaptive rate adjustments and CRDT‑based approximations enable smarter, globally consistent throttling.

## Further Reading

- [Token bucket algorithm – Wikipedia](https://en.wikipedia.org/wiki/Token_bucket)
- [Leaky bucket algorithm – Wikipedia](https://en.wikipedia.org/wiki/Leaky_bucket_algorithm)
- [Rate Limiting on Google Cloud Architecture Center](https://cloud.google.com/architecture/rate-limiting)
- [AWS API Gateway Throttling](https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-request-throttling.html)
- [Redis Lua scripting documentation](https://redis.io/docs/manual/programmability/eval-intro/)