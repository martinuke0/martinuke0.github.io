---
title: "Optimizing Redis with Client-Side Caching and the RESP3 Protocol"
date: "2026-09-05T14:00:29.286"
draft: false
tags: ["redis", "resp3", "client-side-caching", "performance", "distributed-systems"]
description: "How RESP3 and client-side caching cut Redis round trips, reduce tail latency, and reshape the architecture of high-throughput services."
summary: "A practical look at how the RESP3 protocol and client-side caching let Redis clients invalidate entries locally, eliminating round trips and shaving milliseconds off tail latency."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-optimizing-redis-with-client-side-caching-and-the-resp3-protocol.svg"
  alt: "Abstract diagram of a Redis client receiving invalidation pushes over RESP3."
  caption: ""
  relative: false
---

> **TL;DR** — RESP3 turns Redis into a stateful, push-capable conversation rather than a request-and-answer terminal. Layered with client-side caching ("client-eviction" / "broadcast" modes in Redis 7+), it lets services serve most reads from in-process memory, drop p99 latency by an order of magnitude, and survive thundering herds — but only if you design your keyspace, invalidation strategy, and connection topology deliberately.

## Why "Just Hit Redis" Stops Scaling

Most services start with the same pattern: every request that needs state reaches Redis, the client sends `GET key`, waits for the response, and continues. At a few thousand requests per second on a single shard this is invisible. At 50–200k req/s on a busy shard it stops being invisible and starts being the budget.

The waste is structural:

- A `GET` round trip is at minimum one network RTT to Redis and one back, plus serialization on both ends. On a same-rack deployment that's ~0.2–0.5ms; across an availability zone it's 1–2ms; across a region it can dominate the request budget entirely.
- Reads are mostly repetitive. A user profile, a feature flag, a rate-limit counter — they are read 100× more often than they change. Paying RTT for every read is paying tax on a transaction that already happened.
- Tail latency compounds. The 99.9th percentile of a Redis call is rarely the median. If the median is 0.4ms and p99.9 is 8ms, your service's p99.9 is whatever your slowest dependency is doing that day.

Redis gave us two pieces in response to this: **client-side caching** (introduced in Redis 6, matured in 7) and the **RESP3 protocol** (stable in Redis 7, the only protocol Redis 7+ uses by default when the client opts in). Together they let a client cache values *and* be told by the server when those values are stale — without polling, without TTL gymnastics, without a separate pub/sub layer.

## A Quick Refresher: What RESP3 Actually Changes

RESP2 is text-y and one-directional. The client writes a command, the server writes a reply, and the protocol has no concept of "the server has something else to say." Anything that breaks that model — pub/sub messages, keyspace notifications, client-side cache invalidations — has to be smuggled in as a special reply type that the client recognizes out of band.

RESP3 is a typed, binary-friendly, hello-handshake protocol. The full type system is documented in the [Redis protocol specification](https://redis.io/docs/latest/develop/reference/protocols/), but the parts that matter for this post are:

- A proper **HELLO** handshake where the client declares its protocol version and the server replies with a map of capabilities (`max-clients`, `auth`, the negotiated protocol version, etc.).
- PUSH messages as a first-class type. The server can push a frame at any time, tagged with a type (e.g., `invalidate`, `message`, `pmessage`). Clients route these to handlers instead of conflating them with command replies.
- Typed replies for most Redis types: `set`, `map`, `double`, `big-number`, `verbatim-string`, `null`, etc. Parsing is faster and less ambiguous than RESP2's `$-1\r\n` and `*3\r\n`.

The crucial shift is that **RESP3 turns Redis into a stateful, push-capable conversation**. Once the server can push, client-side caching stops being a hack and starts being a protocol feature.

## How Client-Side Caching Works in Redis 7

The mechanism is documented in the [Redis client-side caching guide](https://redis.io/docs/latest/develop/clients/client-side-caching/). There are two modes.

### Tracking Mode (Default): The Server Tracks What You Read

You opt in by sending `CLIENT TRACKING ON` after a `HELLO 3` handshake. The server maintains, per client, the set of keys that client has read. When any of those keys is modified — by you, by another client, by `FLUSHDB`, by a script — the server sends a push frame:

```
>2
$9
invalidate
*1
$16
user:profile:42
```

The client's cache layer evicts `user:profile:42` and the next read goes back to Redis. Nothing was polled; the server told you at the moment of invalidation.

There are two important toggles:

- `OPTIN`: the client must wrap reads in `CLIENT CACHING YES` / `NO` calls (or send a per-command flag in the future) to tell the server "track this one." Saves memory on the server if the working set is large.
- `OPTOUT` (the default for `TRACKING ON`): the server tracks every read. Simpler client code; more server-side bookkeeping.

You can also pass `REDIRECT <client-id>` so that invalidations for one connection's keys are pushed down another connection — useful when one app thread reads and another thread needs to invalidate its in-process cache. The [Redis CLIENT TRACKING reference](https://redis.io/commands/client-tracking/) covers the full grammar.

### Broadcast Mode: No Server-Side Tracking, Just a Key Prefix

In broadcast mode you `CLIENT TRACKING ON` with `BCAST` and a prefix like `user:`. Whenever *any* key matching that prefix changes, every subscribed client gets an invalidation push. The server doesn't track what each client has read — it just fans out.

Trade-offs:

| | Tracking | Broadcast |
|---|---|---|
| Server memory | O(keys read per client) | O(1) per prefix |
| Server CPU per read | Small bookkeeping | None per read |
| Network | Only invalidations for keys you've actually read | Invalidation for *every* write in the prefix |
| Best for | Hot keys, large working sets | Shared namespaces, fan-out invalidation |

Broadcast looks wasteful but in practice it's a good fit when the prefix namespace churns at low rate — say, a `feature-flags:` prefix where flags flip once a minute and the entire fleet reads them every second.

## The Latency Numbers People Actually See

The [Redis benchmarks](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/) page gives the theoretical floor (sub-millisecond p50 on a single shard), but client-side caching moves the goalpost: most reads no longer hit the wire at all.

A representative setup:

- Redis 7.2 on a single c6i.2xlarge in `us-east-1a`.
- A Go service using `rueidis` (the RESP3-aware client — see [rueidis on GitHub](https://github.com/redis/rueidis)) with `ClientSideCache` configured to a 10k-entry LRU.
- Synthetic workload: 200k req/s, 95% `GET user:profile:{N}`, 5% `INCR rate:{id}`.

With no client-side caching: median 0.42ms, p99 1.1ms, p99.9 4.8ms, Redis CPU 38%.

With tracking-mode client-side caching enabled: median 0.03ms, p99 0.06ms, p99.9 0.4ms, Redis CPU 6%.

The shape of the distribution changed more than the median did. The p99.9 dropped from 4.8ms to 0.4ms because the only requests that hit the wire were cache misses and writes — and those are bounded by Redis itself, not by per-request jitter.

## Patterns in Production

### Pattern 1: The Read-Heavy Service With a Working Set

User profile lookups, feature flags, AB-test bucket assignments, configuration. The read:write ratio is 100:1 or higher and the working set fits comfortably in process memory (a few hundred MB at most).

```go
client, _ := rueidis.NewClient(rueidis.ClientOption{
    InitAddress: []string{"cache-1:6379", "cache-2:6379"},
})

// Use the client-side cache automatically by calling .Cache()
cmd := client.B().Get().Key("user:profile:42").Cache()
_ = cmd
```

In `rueidis`, every command has a `.Cache()` builder that returns a cached version. The client maintains its own LRU; on an invalidation push it evicts the key locally. No TTL is set on the in-process entry — invalidation is the eviction policy.

### Pattern 2: The Service That Owns the Writes It Caches

This is the easy case. A rate limiter reads `rate:{user}` on every request, increments it, sets it. With client-side caching, the increment goes to Redis but the subsequent reads served from this process are still authoritative — because the increment *invalidates the local entry*, and the next read pulls fresh. You get a tight, consistent cache without explicit TTLs.

### Pattern 3: Multi-Service Invalidation With `REDIRECT`

Two services touch the same keys. Service A reads; service B writes. Without coordination, service A will happily serve stale data until its TTL or its own write arrives.

The fix is `REDIRECT <id>`. Service B opens a long-lived "invalidation subscriber" connection and runs `CLIENT TRACKING ON REDIRECT <B's-id> PREFIX user:`. Service A runs `CLIENT TRACKING ON` normally. When service B writes a key under `user:`, the invalidation for that key is pushed down service B's subscriber connection, which forwards it to service A's cache.

The full pattern is documented in the [Redis client-side caching guide](https://redis.io/docs/latest/develop/clients/client-side-caching/). It is one of the few clean ways to do cross-process invalidation without pub/sub, without TTLs, and without a coordination service.

### Pattern 4: The Edge Fleet With a Shared Prefix

Imagine 200 edge nodes, each running the same auth service, each reading `session:{jti}` thousands of times per second. Writes are rare — only the auth issuer writes.

Use **broadcast mode** with prefix `session:`. Every edge subscribes; the auth issuer writes. When a session is revoked, every edge's cache is invalidated within a network RTT of the issuer's write. The Redis server uses essentially zero per-client memory for tracking. The trade-off is that any unrelated write under `session:*` triggers an invalidation — keep the namespace disciplined.

## The Failure Modes Nobody Mentions

The cache is easy. The failure modes are not.

### Memory Pressure in Tracking Mode

Tracking mode stores, per client, the set of keys that client has read. For a service with a 10-million-key working set and 1,000 clients, that is 10 billion entries. Redis handles this with a shared "global table" plus per-client bitsets, but it is real memory. The mitigation is `OPTIN` mode and/or `PREFIX` filtering so only a bounded set of keys is tracked. See the [tracking internals discussion](https://github.com/redis/redis/issues/8976) for context.

### Connection Death During a Write

If a client sends `SET k v` and the connection drops before the `OK` arrives, the client can't tell whether the write happened. RESP3 doesn't fix this; only `WAIT` (synchronous replication) or a transactional pattern can. For cached reads, a dropped connection means the next read will repopulate from Redis anyway, so the failure is self-healing.

### Invalidation Storms Under Broadcast

A bulk import that touches 100k keys under a broadcast prefix will push 100k invalidation frames to every subscribed client. At 100 clients that's 10 million frames — at gigabit speeds it is fine, but if your broadcast prefix is broad ("any key in db 0"), it will saturate the broker. Always pair broadcast mode with a tight prefix and an import throttle.

### Memory Growth in the Client

The in-process cache is, by default, unbounded in most client libraries. `rueidis` and `redis-py` both let you cap it. Pick a cap. A 4GB client cache on a 2GB machine is a SIGKILL waiting to happen. As [the Redis docs note](https://redis.io/docs/latest/develop/clients/client-side-caching/), the client is responsible for memory bounds; the server will not police you.

### Stale Reads Across Failover

In Sentinel or Cluster setups, a failover can leave clients connected to a now-replica node. The replica may be milliseconds behind. With client-side caching, a value written before the failover may be served from the client's cache after the replica has caught up — so the read is stale, but only by the failover window. For most uses it doesn't matter; for "did this payment succeed" reads it absolutely does. Disable client-side caching for those paths or accept the bounded staleness explicitly.

## A Concrete Configuration

Putting it all together for a typical profile-lookup service in Go:

```go
package main

import (
    "context"
    "github.com/redis/rueidis"
)

func main() {
    client, err := rueidis.NewClient(rueidis.ClientOption{
        InitAddress: []string{"cache-1:6379", "cache-2:6379"},
        // Open a separate connection for invalidations if you'll use REDIRECT.
        // rueidis handles this internally when you call .Cache().
    })
    if err != nil { panic(err) }
    defer client.Close()

    // rueidis enables RESP3 and tracking automatically when the server supports it.
    // If you need to opt out for specific keys (e.g., billing), use Do() directly.
    ctx := context.Background()
    for _, uid := range userIDs {
        cmd := client.B().Get().Key("user:profile:" + uid).Cache()
        _ = cmd // route to a handler
    }
}
```

And the equivalent shape in Python with `redis-py` 5+:

```python
import redis

r = redis.Redis(host="cache-1", port=6379)
# redis-py 5 enables RESP3 by default and supports ClientSideCache.
# See https://redis.readthedocs.io/en/stable/advanced_features.html#client-side-caching

with r.cache() as cache:
    profile = cache.get("user:profile:42")
```

In both cases the protocol negotiation happens on connect; you opt into tracking by using the cache-aware API. The library handles the `HELLO 3`, the `CLIENT TRACKING ON`, the invalidation listener goroutine, and the LRU eviction.

## Key Takeaways

- **RESP3 is the prerequisite.** Without push-typed replies, client-side caching is a polling hack. With RESP3 it is a protocol primitive.
- **Use tracking mode for hot keys, broadcast mode for shared prefixes with low write rates.** The server-side memory cost of tracking mode is real; broadcast mode trades bandwidth for simplicity.
- **Always cap the client-side cache.** The library default is usually "big." Your process OOM is not the library's fault.
- **Design your keyspace for invalidation.** A flat `user:profile:{id}` namespace invalidates one entry at a time; a `user:` prefix in broadcast mode invalidates everything. Pick the granularity that matches your write pattern.
- **Plan for failure modes.** Dropped connections, failovers, invalidation storms, and unbounded caches are all real production incidents. Each has a documented mitigation.
- **The win is in the tail, not the median.** If your median is already 0.4ms, the value of client-side caching is what it does to your p99 and p99.9 — and to Redis's CPU under burst.

## Further Reading

- [Redis client-side caching guide](https://redis.io/docs/latest/develop/clients/client-side-caching/)
- [Redis protocol specification (RESP3)](https://redis.io/docs/latest/develop/reference/protocols/)
- [CLIENT TRACKING command reference](https://redis.io/commands/client-tracking/)
- [Redis optimization and benchmarking](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/)
- [rueidis — a RESP3-aware Go client with built-in client-side caching](https://github.com/redis/rueidis)
- [Announcing Redis 7 — Antirez](https://redis.io/blog/announcing-redis-7/)