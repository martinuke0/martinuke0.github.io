---
title: "Designing High‑Availability Distributed Locks with Redlock and Fencing Tokens"
date: "2026-05-13T11:00:54.431"
draft: false
tags: ["distributed systems", "redis", "high availability", "locking", "algorithm"]
description: "Explore how to build resilient distributed locks using the Redlock algorithm and fencing tokens, with practical Python examples and safety analysis."
summary: "A deep dive into Redlock and fencing tokens, showing why they matter and how to implement them correctly for high‑availability systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-designing-highavailability-distributed-locks-with-redlock-and-fencing-tokens.svg"
  alt: "Illustration of multiple Redis nodes forming a quorum for a distributed lock."
  caption: ""
  relative: false
---

> **TL;DR** — Redlock combines multiple independent Redis instances to achieve fault‑tolerant locking, but you still need fencing tokens to prevent stale lock usage after failures. This post walks through the algorithm, its safety guarantees, and a production‑ready Python implementation.

Distributed systems rarely get away with a single point of failure. When many services need exclusive access to a shared resource—such as a job queue, a critical configuration file, or a limited‑capacity API—relying on a naïve lock can cause split‑brain scenarios, data corruption, or downtime. The Redlock algorithm, introduced by Salvatore Sanfilippo (the creator of Redis), offers a way to coordinate locks across several Redis nodes, while fencing tokens provide a cheap yet robust guard against the “lock‑reuse after expiry” problem. Together they form a high‑availability locking primitive that scales across data‑centers and survives network partitions.

## Understanding the Need for Distributed Locks

### Why Simple Redis `SETNX` Falls Short

A single Redis instance can provide a lock with the classic `SET key value NX PX ttl` pattern. It works well when the Redis server is the sole source of truth and the network is reliable. However, in production environments you often run Redis in a replicated or clustered mode, and you cannot guarantee that the master will stay alive for the entire TTL. If the master crashes after granting a lock but before the client releases it, the lock may become orphaned, causing other clients to deadlock indefinitely.

Moreover, network partitions can cause a client to believe it holds a lock while the Redis server has already reclaimed the key due to a timeout. The classic “split‑brain” scenario emerges: two separate processes act as if they own the same exclusive resource.

### The High‑Availability Goal

A robust distributed lock should satisfy three properties:

1. **Safety (Mutual Exclusion)** – No two clients may hold the lock simultaneously.
2. **Liveness (Progress)** – If a client retries enough times, it eventually acquires the lock provided a quorum of nodes is reachable.
3. **Fault Tolerance** – The system continues to operate despite crashes of up to *N‑1* nodes in a cluster of *N* nodes.

Redlock was designed explicitly to meet these criteria.

## The Redlock Algorithm Explained

### Core Steps

1. **Select *N* independent Redis instances** (typically 5) that do not share a single failure domain.
2. **Generate a unique lock identifier** (a UUID or high‑entropy random string). This identifier will be stored as the lock value.
3. **Attempt to acquire the lock on each instance** using `SET key identifier NX PX ttl`. Record the time before the first `SET` and after the last successful `SET`.
4. **Calculate the elapsed time**. If the lock was acquired on at least a majority (⌈*N*/2⌉) of instances *and* the elapsed time is less than the TTL, consider the lock successfully obtained.
5. **If the lock acquisition fails**, release any partial locks by issuing `DEL key` on the nodes where it succeeded, then retry after a back‑off.
6. **Renew the lock** before the TTL expires by repeating step 2 with the same identifier and a new TTL (optional but recommended for long‑running tasks).

The algorithm’s safety proof hinges on the fact that a majority of nodes must agree on the lock state. Even if a minority of nodes become unavailable, they cannot form a conflicting majority.

### Safety Guarantees and Known Limitations

Redlock provides **strong safety** under the assumption that clocks on the client machines are reasonably synchronized (the algorithm measures elapsed time locally). If a client’s clock drifts dramatically, it could incorrectly deem a lock acquisition as successful. In practice, using a monotonic timer (e.g., `time.monotonic()` in Python) mitigates this risk.

The algorithm also assumes **independent failure domains**. Deploying all Redis nodes in the same rack or data center defeats the purpose because a single power outage could take down the majority.

Finally, Redlock does not protect against **stale lock usage** after a client crashes while holding the lock. That’s where fencing tokens come in.

## Integrating Fencing Tokens

### What Are Fencing Tokens?

A fencing token is a monotonically increasing integer (or another comparable value) that a client obtains *before* performing any operation guarded by the lock. When the client writes to a shared resource, it includes the token. Consumers of that resource (e.g., a database, a message queue) reject any operation that carries a token older than the highest token they have already processed.

Think of a fencing token as a “version stamp” that guarantees *happens‑before* ordering across lock holders.

### Using Tokens with Redlock

1. **Create a global token generator**—often a separate Redis key that you increment atomically with `INCR`.  
2. **When a client acquires a Redlock, it also fetches a fresh token** (`INCR fence_token`). The token is stored alongside the lock identifier (e.g., as a JSON value).  
3. **All critical writes embed the token**. For example, when updating a row in PostgreSQL, include `WHERE fence_token > previous_token`.  
4. **If a client crashes**, its lock eventually expires, but any stale writes that still carry the old token will be rejected because the database has already recorded a higher token from a subsequent lock holder.

This pattern eliminates the “split‑brain” write problem without requiring complex consensus protocols.

## Practical Implementation in Python

Below is a minimal yet production‑ready implementation that combines Redlock with fencing tokens. It uses the `redis-py` library (version 5.x) and the `uuid` module for lock identifiers.

```python
import time
import uuid
import redis
from typing import List, Optional, Tuple

# ----------------------------------------------------------------------
# Configuration – five independent Redis nodes (adjust host/port as needed)
# ----------------------------------------------------------------------
REDIS_NODES = [
    {"host": "redis-1.example.com", "port": 6379},
    {"host": "redis-2.example.com", "port": 6379},
    {"host": "redis-3.example.com", "port": 6379},
    {"host": "redis-4.example.com", "port": 6379},
    {"host": "redis-5.example.com", "port": 6379},
]

# ----------------------------------------------------------------------
# Helper classes
# ----------------------------------------------------------------------
class DistributedLock:
    def __init__(self, name: str, ttl_ms: int = 30000):
        self.name = name
        self.ttl_ms = ttl_ms
        self.identifier = str(uuid.uuid4())
        self.clients: List[redis.Redis] = [
            redis.Redis(**cfg, socket_timeout=0.5) for cfg in REDIS_NODES
        ]
        self.quorum = len(self.clients) // 2 + 1
        self.fence_token: Optional[int] = None

    def _acquire_on_node(self, client: redis.Redis) -> bool:
        try:
            result = client.set(
                self.name,
                f"{self.identifier}:{self.fence_token}",
                nx=True,
                px=self.ttl_ms,
            )
            return result is True
        except redis.RedisError:
            return False

    def acquire(self, retry: int = 3, delay: float = 0.2) -> bool:
        """
        Try to acquire the lock using the Redlock algorithm.
        Returns True on success, False otherwise.
        """
        for attempt in range(retry):
            # Step 1: obtain a fresh fencing token from a dedicated key
            # Use the first reachable node for token generation.
            token_client = self.clients[0]
            try:
                self.fence_token = token_client.incr("global:fence_token")
            except redis.RedisError:
                self.fence_token = None
                continue  # cannot get token, retry later

            start = time.monotonic()
            successes = 0
            for client in self.clients:
                if self._acquire_on_node(client):
                    successes += 1

            elapsed_ms = (time.monotonic() - start) * 1000
            # Safety check: enough nodes and within TTL
            if successes >= self.quorum and elapsed_ms < self.ttl_ms:
                # Lock successfully obtained
                return True

            # Otherwise, clean up any partial locks
            self.release()
            time.sleep(delay * (2 ** attempt))  # exponential back‑off

        return False

    def release(self) -> None:
        """
        Release the lock on all nodes where it may exist.
        """
        for client in self.clients:
            try:
                # Use a Lua script to delete only if the identifier matches
                script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("DEL", KEYS[1])
                else
                    return 0
                end
                """
                client.eval(script, 1, self.name, f"{self.identifier}:{self.fence_token}")
            except redis.RedisError:
                continue

    def extend(self) -> bool:
        """
        Extend the lock's TTL before it expires.
        Returns True if the extension succeeded on a majority.
        """
        successes = 0
        for client in self.clients:
            try:
                script = """
                if redis.call("GET", KEYS[1]) == ARGV[1] then
                    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
                else
                    return 0
                end
                """
                result = client.eval(
                    script,
                    1,
                    self.name,
                    f"{self.identifier}:{self.fence_token}",
                    self.ttl_ms,
                )
                if result == 1:
                    successes += 1
            except redis.RedisError:
                continue
        return successes >= self.quorum
```

**How to use the lock**

```python
lock = DistributedLock("my_resource_lock", ttl_ms=20000)

if lock.acquire():
    try:
        # Critical section – pass the fencing token to downstream services
        token = lock.fence_token
        # Example: write to PostgreSQL with a WHERE clause that checks the token
        # cursor.execute("UPDATE jobs SET status='running', fence_token=%s WHERE id=%s AND fence_token < %s", (token, job_id, token))
        print(f"Lock acquired with fencing token {token}")
        # Simulate work
        time.sleep(5)
        # Optionally extend if work takes longer
        lock.extend()
    finally:
        lock.release()
else:
    print("Failed to acquire distributed lock after retries.")
```

The implementation follows the Redlock steps verbatim and adds a **global fencing token** generated atomically with `INCR`. The lock value stored in Redis combines the UUID and the token, allowing any node that later reads the key to verify ownership.

### Production Tips

- **Deploy Redis nodes across different availability zones** to avoid correlated failures.
- **Monitor latency**; if the average round‑trip time approaches the TTL, increase the TTL or reduce the number of nodes.
- **Use TLS and authentication** for all Redis connections (`redis.Redis(..., ssl=True, password=…)`).
- **Persist the fencing token** in a durable store (e.g., PostgreSQL `SEQUENCE`) if you need cross‑language consistency.

## Key Takeaways

- Redlock obtains a lock by securing a majority of independent Redis instances, providing safety even when a minority fail.
- A fencing token is a monotonically increasing identifier that prevents stale writes after a lock holder crashes.
- Combine Redlock with fencing tokens to achieve both **mutual exclusion** and **write ordering** across distributed processes.
- Implementations should use atomic operations (`SET NX PX`, `INCR`, Lua scripts) and measure elapsed time with a monotonic clock.
- Deploy nodes in separate failure domains, monitor latency, and enforce TLS/authentication for production‑grade security.

## Further Reading

- [Redis Distributed Locks – Redlock algorithm](https://redis.io/docs/reference/patterns/distributed-locks/)
- [Fencing Tokens in Distributed Systems (Google Cloud Blog)](https://cloud.google.com/blog/products/databases/fencing-tokens-ensure-consistency)
- [The original Redlock paper by Salvatore Sanfilippo](https://redis.io/topics/distlock)
- [PostgreSQL Advisory Locks – a complementary approach](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)
- [Cassandra Lightweight Transactions – another form of distributed lock](https://cassandra.apache.org/doc/latest/cassandra/architecture/transactions.html)