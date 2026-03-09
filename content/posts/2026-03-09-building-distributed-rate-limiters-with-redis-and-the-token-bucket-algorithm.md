---
title: "Building Distributed Rate Limiters with Redis and the Token Bucket Algorithm"
date: "2026-03-09T08:00:19.284"
draft: false
tags: ["distributed-systems", "rate-limiting", "redis", "system-design", "token-bucket"]
---

## Introduction

In modern web services, protecting APIs from abuse, ensuring fair resource allocation, and maintaining a predictable quality‑of‑service are non‑negotiable requirements. **Rate limiting**—the practice of restricting how many requests a client can make in a given time window—addresses these concerns. While a simple in‑process limiter works for monolithic applications, today’s micro‑service ecosystems demand a **distributed** solution that works across multiple instances, data centers, and even cloud regions.

This article walks you through the complete design and implementation of a **distributed rate limiter** built on **Redis** using the **Token Bucket algorithm**. We’ll cover the theory behind token buckets, why Redis is a natural fit, practical implementation details, edge‑case handling, scaling strategies, and real‑world patterns you can adopt immediately.

> **Note:** The concepts herein are language‑agnostic, but we’ll provide concrete examples in Python and Node.js to illustrate key patterns.

---

## Table of Contents
*(Only included when the article exceeds 10,000 words; omitted here for brevity.)*

---

## 1. Fundamentals of Rate Limiting

Before diving into distributed designs, it’s essential to understand the problem space and the most common algorithms.

### 1.1 What Is a Rate Limit?

A rate limit defines a maximum number of allowed operations (e.g., API calls) per unit of time for a given **key** (user ID, IP address, API token, etc.). Typical specifications look like:

- **100 requests per minute**
- **10,000 requests per day**
- **5 writes per second**

### 1.2 Why Rate Limiting Matters

- **Prevent DoS attacks** – throttle malicious traffic before it overwhelms downstream services.
- **Fairness** – ensure premium customers or critical services get the resources they need.
- **Cost control** – limit expensive operations (e.g., database writes) to stay within budget.
- **Compliance** – enforce contractual API usage limits.

### 1.3 Common Algorithms

| Algorithm | Description | Strengths | Weaknesses |
|-----------|-------------|-----------|------------|
| Fixed Window | Count requests in a static time bucket (e.g., minute). | Simple, easy to implement. | Bursty traffic can cause “thundering herd” at bucket boundaries. |
| Sliding Window Log | Store timestamps of each request and slide a window over them. | Precise, smooth throttling. | High memory overhead; not scalable. |
| Leaky Bucket | Treat requests as water flowing into a bucket that leaks at a constant rate. | Guarantees constant output rate. | Not as intuitive for burst allowance. |
| **Token Bucket** | Tokens are added to a bucket at a fixed rate; each request consumes a token. | Allows bursts while enforcing an average rate. | Requires careful handling of token replenishment in distributed contexts. |

The **Token Bucket** algorithm strikes a balance between simplicity and flexibility, making it the most popular choice for API gateways, CDN edge nodes, and micro‑service meshes.

---

## 2. The Token Bucket Algorithm Explained

### 2.1 Core Mechanics

- **Bucket capacity (C)** – maximum number of tokens the bucket can hold.
- **Refill rate (R)** – tokens added per second (or other time unit).
- **Current token count (T)** – the number of tokens available at a given moment.

When a request arrives:

1. **Replenish** the bucket based on elapsed time since the last update.
2. **Check** if `T >= 1` (or the request’s cost).
3. If enough tokens exist, **consume** the required tokens and allow the request.
4. Otherwise, **reject** or delay the request.

### 2.2 Mathematical Model

Let `t_last` be the timestamp of the last update, `t_now` the current timestamp, and `Δt = t_now - t_last`. The bucket is replenished by:

```
T = min(C, T + R * Δt)
```

The algorithm guarantees:

- **Maximum burst size** = `C` (all tokens can be used instantly).
- **Sustained rate** = `R` (average tokens per second).

### 2.3 Advantages for Distributed Systems

- **Stateless request handling** – the decision only depends on the current token count.
- **Graceful burst handling** – occasional spikes won’t be dropped if tokens are available.
- **Predictable latency** – token check is O(1) when stored in a fast key‑value store.

---

## 3. Why a Distributed Rate Limiter?

In a single‑process environment, you can keep the token count in memory. However, modern services run **multiple instances**, **auto‑scale**, and often span **multiple regions**. A distributed limiter must:

- **Share state** across all instances to enforce a global limit.
- **Provide low latency** – a rate‑limit check should be faster than the request itself.
- **Be fault‑tolerant** – a single node failure must not break the limiter.
- **Scale horizontally** – as traffic grows, the limiter should not become a bottleneck.

Redis, a high‑performance in‑memory data store, satisfies these criteria and offers atomic operations that are critical for correct token bucket updates.

---

## 4. Redis as the Backbone for Distributed Token Buckets

### 4.1 Key Features We Leverage

| Feature | Why It Matters |
|---------|----------------|
| **Atomic commands** (e.g., `INCRBY`, `GETSET`, Lua scripting) | Guarantees race‑free token updates. |
| **TTL support** | Allows automatic bucket expiration for inactive keys. |
| **High throughput** (single‑threaded core with event‑loop) | Keeps per‑request latency low (< 1 ms). |
| **Persistence options** (RDB, AOF) | Provides durability in case of restarts. |
| **Cluster mode** | Enables horizontal scaling across shards. |

### 4.2 Data Model

For each rate‑limit key (e.g., `user:1234:api`), we store a **hash** with fields:

- `tokens` – current token count (float for sub‑token precision).
- `timestamp` – last refill timestamp in milliseconds.
- `capacity` – bucket capacity (optional, can be stored in config).
- `rate` – refill rate (tokens per millisecond, derived from R).

Example Redis hash:

```
HSET rate_limit:user:1234:api tokens 42.5 timestamp 1710001234567 capacity 100 rate 0.0166667
```

The hash is compact, and a TTL (e.g., 1 hour) ensures stale entries are reclaimed automatically.

---

## 5. Designing a Distributed Token Bucket

### 5.1 High‑Level Flow

1. **Client request** → API gateway or service.
2. **Limiter middleware** extracts the limit key (user ID, API token, IP).
3. **Redis operation** atomically:
   - Replenishes tokens based on elapsed time.
   - Checks token availability.
   - Consumes tokens if allowed.
4. **Response** – request proceeds or receives `429 Too Many Requests`.

### 5.2 Atomicity with Lua Scripts

Redis Lua scripts run atomically, meaning the entire token bucket logic can be executed in a single round‑trip. This eliminates race conditions across multiple service instances.

#### 5.2.1 Sample Lua Script (Redis 5+)

```lua
-- KEYS[1] = rate limit key (e.g., "rate_limit:user:1234")
-- ARGV[1] = capacity (C)
-- ARGV[2] = refill_rate (R) tokens per millisecond
-- ARGV[3] = current_timestamp (ms)
-- ARGV[4] = tokens_needed (usually 1)
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local needed = tonumber(ARGV[4])

-- Load bucket state
local bucket = redis.call('HMGET', key, 'tokens', 'timestamp')
local tokens = tonumber(bucket[1])
local last_ts = tonumber(bucket[2])

if tokens == nil then
  tokens = capacity
  last_ts = now
else
  -- Refill tokens based on elapsed time
  local delta = now - last_ts
  local refill = delta * refill_rate
  tokens = math.min(capacity, tokens + refill)
  last_ts = now
end

local allowed = tokens >= needed
if allowed then
  tokens = tokens - needed
  redis.call('HMSET', key,
    'tokens', tokens,
    'timestamp', last_ts)
  -- Optional: set a TTL to auto‑expire inactive buckets
  redis.call('EXPIRE', key, 3600)
else
  -- Update the bucket state even if request is denied
  redis.call('HMSET', key,
    'tokens', tokens,
    'timestamp', last_ts)
  redis.call('EXPIRE', key, 3600)
end

return { allowed and 1 or 0, tokens }
```

The script returns a two‑element array: `[allowed_flag, remaining_tokens]`.

### 5.3 Integration Patterns

| Pattern | Description | When to Use |
|---------|-------------|-------------|
| **Gateway‑level limiter** | Runs at API gateway (e.g., Kong, Envoy). | Enforce global limits before traffic reaches services. |
| **Service‑level limiter** | Embedded in each micro‑service. | Fine‑grained limits per service (e.g., per‑endpoint). |
| **Hybrid** | Combine both for defense‑in‑depth. | Critical public APIs needing both global and per‑service caps. |

---

## 6. Implementation Walkthrough

Below we provide two concrete implementations: **Python (using `redis-py`)** and **Node.js (using `ioredis`)**. Both follow the same Lua script logic.

### 6.1 Python Example

```python
import time
import redis

# Initialize Redis client (single node or cluster)
r = redis.StrictRedis(host='redis.local', port=6379, db=0)

# Load Lua script into Redis and get its SHA for fast execution
TOKEN_BUCKET_SCRIPT = """
<INSERT LUA SCRIPT FROM SECTION 5.2.1 HERE>
"""
script_sha = r.script_load(TOKEN_BUCKET_SCRIPT)

def is_allowed(key: str, capacity: int, refill_rate: float, tokens_needed: int = 1) -> bool:
    """
    Checks the token bucket for the given key.
    :param key: Redis key, e.g., "rate_limit:user:1234"
    :param capacity: Max tokens the bucket can hold.
    :param refill_rate: Tokens added per millisecond.
    :param tokens_needed: Tokens required for the request.
    :return: True if request is allowed, False otherwise.
    """
    now_ms = int(time.time() * 1000)
    result = r.evalsha(
        script_sha,
        1,                      # number of KEYS
        key,
        capacity,
        refill_rate,
        now_ms,
        tokens_needed,
    )
    allowed, remaining = result
    return bool(allowed)

# Example usage
if __name__ == "__main__":
    USER_KEY = "rate_limit:user:42"
    CAPACITY = 100          # max burst
    REFILL_RATE = 0.1       # 0.1 token per ms = 100 tokens per second

    if is_allowed(USER_KEY, CAPACITY, REFILL_RATE):
        print("Request allowed")
    else:
        print("Rate limit exceeded")
```

**Key points:**

- The script is loaded once (`script_load`) to avoid re‑sending the full Lua source on each call.
- `evalsha` executes the script atomically.
- `REFILL_RATE` is expressed per millisecond for precision; you can compute it as `R / 1000`.

### 6.2 Node.js Example

```js
const Redis = require('ioredis');
const redis = new Redis({ host: 'redis.local', port: 6379 });

const tokenBucketLua = `
<INSERT LUA SCRIPT FROM SECTION 5.2.1 HERE>
`;

let scriptSha = null;

// Pre‑load the script
redis.script('load', tokenBucketLua).then(sha => {
  scriptSha = sha;
});

async function isAllowed(key, capacity, refillRate, tokensNeeded = 1) {
  const nowMs = Date.now();
  const args = [
    1,                // number of KEYS
    key,
    capacity,
    refillRate,
    nowMs,
    tokensNeeded,
  ];
  const result = await redis.evalsha(scriptSha, ...args);
  const [allowed, remaining] = result;
  return Boolean(allowed);
}

// Example usage
(async () => {
  const userKey = 'rate_limit:user:99';
  const capacity = 200;
  const refillRate = 0.05; // 0.05 token per ms = 50 tokens per second

  const allowed = await isAllowed(userKey, capacity, refillRate);
  console.log(allowed ? 'Request allowed' : 'Rate limit exceeded');
})();
```

**Considerations for production:**

- **Connection pooling** – `ioredis` handles pooling automatically.
- **Error handling** – fallback to a “fail‑open” or “fail‑closed” policy if Redis is unreachable.
- **Script SHA caching** – reload on `NOSCRIPT` errors.

---

## 7. Handling Edge Cases and Advanced Scenarios

### 7.1 Variable Request Costs

Some operations are heavier than others (e.g., write vs. read). Extend the algorithm by passing a custom `tokens_needed` value per request.

```lua
-- In Lua script, replace `needed = tonumber(ARGV[4])` with the incoming cost.
```

### 7.2 Multi‑Tenant Limits

When serving multiple customers, you may need **different capacities and refill rates** per tenant. Store these parameters in a separate configuration store (e.g., a database) and inject them into the limiter at request time.

### 7.3 Distributed Clock Skew

Redis timestamps are derived from the client’s clock (`now_ms`). To avoid inconsistencies:

- **Use Redis server time** via the `TIME` command inside the Lua script.
- Or synchronize your application servers using NTP and accept a small drift (≤ 10 ms).

#### Example: Using Redis server time in Lua

```lua
local server_time = redis.call('TIME')
local now = tonumber(server_time[1]) * 1000 + tonumber(server_time[2]) / 1000
```

### 7.4 Burst Control for Global vs. Per‑User Limits

You may enforce a **global API limit** (total requests across all users) alongside per‑user limits. Implement a **hierarchical bucket**:

1. Global bucket check first.
2. If passed, check per‑user bucket.

Both checks can be combined in a single Lua script that reads two keys and returns a combined decision.

### 7.5 Graceful Degradation

When Redis is unavailable, you have two strategies:

- **Fail‑open** – allow all requests (risk of overload).
- **Fail‑closed** – reject all requests (risk of service outage).

A common pattern is **circuit‑breaker**: after N consecutive Redis failures, switch to fail‑closed for a short back‑off period, then attempt recovery.

---

## 8. Scaling the Limiter

### 8.1 Redis Cluster Sharding

Redis Cluster distributes keys across 16384 hash slots. By using a **consistent key naming scheme** (`rate_limit:{tenant}:{user}`), the load spreads automatically.

### 8.2 Hot Key Mitigation

A single high‑traffic API key can become a hot spot. Mitigate by:

- **Key salting** – append a short random suffix and store multiple sub‑buckets, then aggregate results.
- **Leaky bucket fallback** – for extreme hot keys, switch to a simpler fixed‑window counter.

### 8.3 Multi‑Region Replication

For globally distributed services, consider **Active‑Active Redis** with CRDTs (e.g., Redis Enterprise's Active‑Active). This provides eventual consistency and low latency for regional traffic while keeping limits globally coherent.

### 8.4 Monitoring Throughput

Track the following metrics in Prometheus or Grafana:

- `rate_limiter_requests_total` (counter)
- `rate_limiter_allowed_total` (counter)
- `rate_limiter_rejected_total` (counter)
- `rate_limiter_latency_seconds` (histogram)

These help you spot bottlenecks and tune bucket parameters.

---

## 9. Testing the Distributed Limiter

### 9.1 Unit Tests

Mock Redis using libraries like `fakeredis` (Python) or `ioredis-mock` (Node) to validate the Lua script’s logic.

### 9.2 Integration Tests

Spin up a real Redis instance (Docker) and run concurrency tests:

```bash
# Bash pseudo‑code
for i in {1..1000}; do
  curl -s http://api.service/endpoint &
done
wait
```

Verify that the number of successful responses respects the configured rate.

### 9.3 Load Testing

Use tools like **k6**, **Locust**, or **hey** to generate sustained traffic and confirm:

- **Latency** of limiter checks stays < 1 ms.
- **Throughput** matches expected limits.
- **Redis CPU** remains below saturation (e.g., < 70 % on a t3.medium).

---

## 10. Security Considerations

- **Key enumeration** – Avoid exposing raw limiter keys in URLs or logs.
- **Rate‑limit bypass** – Ensure the limiter runs **before** any authentication/authorization logic that could be tricked.
- **Redis ACLs** – Use Redis’ built‑in ACL system to restrict the limiter service to only `GET`, `HMSET`, `EVALSHA`, and `EXPIRE` commands.
- **TLS** – Encrypt traffic between services and Redis (especially in cloud environments).

---

## 11. Comparing Token Bucket to Other Algorithms

| Feature | Token Bucket | Fixed Window | Leaky Bucket | Sliding Log |
|---------|--------------|--------------|--------------|-------------|
| **Burst support** | ✅ (capacity) | ❌ | ✅ (via buffer) | ✅ |
| **Memory usage** | O(1) per key | O(1) | O(1) | O(N) per key |
| **Precision** | Approximate (depends on refill granularity) | Coarse (window boundaries) | Approximate | Exact |
| **Implementation complexity** | Medium (needs atomic refill) | Low | Medium | High |
| **Distributed friendliness** | ✅ (Lua script) | ✅ (simple counters) | ✅ (similar to token) | ❌ (requires per‑request timestamps) |

For most API gateway scenarios, **token bucket** offers the best trade‑off between burst tolerance and implementation simplicity.

---

## 12. Real‑World Use Cases

1. **Public API Platforms** – Enforce per‑developer quotas (e.g., 10 k requests/day) while allowing occasional spikes.
2. **E‑commerce Checkout** – Limit the number of order submissions per user to prevent abuse.
3. **Multi‑tenant SaaS** – Provide tiered limits (Free tier 100 rps, Premium 1 k rps) with a single Redis cluster.
4. **IoT Device Ingestion** – Throttle telemetry uploads per device ID to protect downstream processing pipelines.
5. **Email Sending Services** – Control the rate of outbound emails per account to avoid being blacklisted.

---

## 13. Best Practices Checklist

- **Atomic updates** – Always use Lua scripts or Redis transactions.
- **TTL management** – Set reasonable expirations (e.g., 1 hour) to clean up inactive keys.
- **Server‑side time** – Prefer Redis `TIME` to avoid client clock drift.
- **Metrics** – Export success/failure counters and latency histograms.
- **Circuit breaker** – Guard against Redis outages.
- **Key naming** – Include tenant, user, and service identifiers to avoid collisions.
- **Capacity planning** – Size Redis instances (or clusters) based on expected QPS × script cost (~0.5 µs per call).

---

## Conclusion

Distributed rate limiting is a cornerstone of resilient, fair, and secure system design. By pairing the **Token Bucket algorithm** with **Redis’ atomic scripting capabilities**, you gain a solution that:

- Handles bursts gracefully while enforcing a steady average rate.
- Scales horizontally across instances and regions.
- Provides sub‑millisecond latency suitable for high‑throughput APIs.
- Remains simple to reason about and integrate into existing micro‑service stacks.

Implementing the patterns described—Lua‑based atomic bucket updates, TTL‑driven cleanup, hierarchical limits, and robust monitoring—will equip you to protect any modern service from overload, abuse, and unpredictable traffic spikes. As your traffic grows, the same design can be extended with Redis Cluster, active‑active replication, and hot‑key mitigation strategies, ensuring the limiter remains a reliable gatekeeper for years to come.

---

## Resources

- **Redis Documentation – Scripting** – https://redis.io/docs/manual/programmability/eval/
- **Token Bucket Algorithm – Wikipedia** – https://en.wikipedia.org/wiki/Token_bucket
- **Rate Limiting in Distributed Systems – Martin Fowler** – https://martinfowler.com/articles/rate-limiting.html
- **Envoy Rate Limit Service (RLS)** – https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/rate_limit_filter
- **Redis Cluster Specification** – https://redis.io/topics/cluster-spec
- **Prometheus Client Libraries** – https://prometheus.io/docs/instrumenting/clientlibs/
- **Circuit Breaker Patterns – Netflix Hystrix** – https://github.com/Netflix/Hystrix

---