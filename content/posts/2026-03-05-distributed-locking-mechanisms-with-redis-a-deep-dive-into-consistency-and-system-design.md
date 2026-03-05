---
title: "Distributed Locking Mechanisms with Redis: A Deep Dive into Consistency and System Design"
date: "2026-03-05T23:00:51.457"
draft: false
tags: ["redis", "distributed-systems", "locking", "consistency", "system-design"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Distributed Locks?](#why-distributed-locks)  
3. [Fundamentals of Consistency in Distributed Systems](#fundamentals-of-consistency-in-distributed-systems)  
4. [Redis as a Lock Service: Core Concepts](#redis-as-a-lock-service-core-concepts)  
5. [The Classic SET‑NX + EX Pattern](#the-classic-set‑nx‑ex-pattern)  
6. [Redlock: Redis’ Official Distributed Lock Algorithm](#redlock-redis-official-distributed-lock-algorithm)  
   - 6.1 [Algorithm Steps](#algorithm-steps)  
   - 6.2 [Correctness Guarantees](#correctness-guarantees)  
   - 6.3 [Common Misconceptions](#common-misconceptions)  
7. [Designing a Robust Locking Layer](#designing-a-robust-locking-layer)  
   - 7.1 [Choosing the Right Timeout Strategy](#choosing-the-right-timeout-strategy)  
   - 7.2 [Handling Clock Skew](#handling-clock-skew)  
   - 7.3 [Fail‑over and Node Partitioning](#fail‑over-and-node-partitioning)  
8. [Practical Implementation Examples](#practical-implementation-examples)  
   - 8.1 [Python Example Using redis‑py](#python-example-using-redis-py)  
   - 8.2 [Node.js Example Using ioredis](#nodejs-example-using-ioredis)  
   - 8.3 [Java Example Using Lettuce](#java-example-using-lettuce)  
9. [Testing and Observability](#testing-and-observability)  
   - 9.1 [Unit Tests with Mock Redis](#unit-tests-with-mock-redis)  
   - 9.2 [Integration Tests in a Multi‑Node Cluster](#integration-tests-in-a-multi‑node-cluster)  
   - 9.3 [Metrics to Monitor](#metrics-to-monitor)  
10. [Pitfalls and Anti‑Patterns](#pitfalls-and-anti-patterns)  
11. [Alternatives to Redis for Distributed Locking](#alternatives-to-redis-for-distributed-locking)  
12. [Conclusion](#conclusion)  
13. [Resources](#resources)  

---

## Introduction

Distributed systems are everywhere—from micro‑service back‑ends that power modern web applications to large‑scale data pipelines that process billions of events per day. In such environments, *coordination* becomes a first‑class concern. One of the most common coordination primitives is a **distributed lock**: a mechanism that guarantees exclusive access to a shared resource across multiple processes, containers, or even data centers.

Redis, originally built as an in‑memory data store, has evolved into a de‑facto platform for distributed coordination. Its speed, simplicity, and rich command set make it an attractive choice for implementing locks. However, the ease of writing a naïve lock can hide subtle consistency problems that only surface under failure scenarios.

This article provides a **comprehensive, in‑depth exploration** of distributed locking with Redis. We will:

* Review why locks are needed in distributed contexts and what consistency means for them.  
* Dissect the classic `SET NX EX` pattern and the more rigorous **Redlock** algorithm.  
* Walk through real‑world design decisions—timeouts, clock skew, fail‑over, and observability.  
* Provide production‑ready code samples in Python, Node.js, and Java.  
* Highlight common pitfalls and compare Redis to alternative lock services.

By the end of this deep dive, you should be able to design, implement, and operate a reliable distributed locking layer that respects the CAP theorem, avoids split‑brain scenarios, and integrates cleanly with modern CI/CD pipelines.

---

## Why Distributed Locks?

Before diving into the technicalities, let’s clarify **when** and **why** you would reach for a distributed lock.

| Scenario | Problem | Distributed Lock Solution |
|----------|---------|---------------------------|
| **Job Scheduling** | Multiple workers may pick the same job from a queue, leading to duplicate processing. | Acquire a lock on the job ID before execution. |
| **Cache Stampede** | Many requests simultaneously miss a cached value, causing a thundering herd on the backend. | Serialize the cache rebuild behind a lock. |
| **Shared Resource Access** | Multiple services need exclusive access to a limited external API quota. | Guard the quota consumption with a lock. |
| **Leader Election** | Only one instance should act as the primary coordinator. | Use a lock as a “leader lease”. |
| **Transactional Updates** | Two services attempt to modify the same database row concurrently. | Serialize the updates via a lock on the row key. |

In each case, the lock must provide **mutual exclusion** (only one holder at a time) **and** **liveness** (the lock eventually becomes available). Achieving these guarantees in a distributed environment—where nodes can crash, messages can be delayed, and clocks can drift—is non‑trivial.

---

## Fundamentals of Consistency in Distributed Systems

Consistency for a lock means that **at any point in time, at most one client believes it holds the lock**. Two classic consistency models are relevant:

1. **Linearizability** – Operations appear to occur atomically at some point between their invocation and response. For locks, this translates to “the moment a client obtains the lock, no other client can think it has it”.

2. **Safety vs. Liveness** –  
   *Safety* ensures that no two clients hold the lock simultaneously (no split‑brain).  
   *Liveness* guarantees that a client eventually acquires the lock if it keeps trying (no deadlock).

The **CAP theorem** tells us that in the presence of network partitions, a system must sacrifice either consistency or availability. Distributed lock implementations typically **prioritize safety** (consistency) over availability, because a split‑brain lock can corrupt data, whereas a temporarily unavailable lock merely delays work.

Redis, when run in a single node, cannot survive a crash without losing the lock state. To achieve higher reliability, we must **replicate** the lock across multiple Redis instances—this is where Redlock shines.

---

## Redis as a Lock Service: Core Concepts

Redis offers three primitive commands that are essential for lock building:

| Command | Description |
|---------|-------------|
| `SET key value NX EX ttl` | Atomically set a key only if it does not exist (`NX`) with an expiration (`EX`). Returns `OK` on success. |
| `DEL key` | Delete a key. If the key does not exist, nothing happens. |
| `EVAL script keys args...` | Run a Lua script atomically on the server. Used for safe lock release (compare‑and‑delete). |

The **`SET … NX EX`** pattern is the foundation of most Redis‑based locks because it provides *atomic set‑if‑absent with TTL*—exactly what a lock needs: a unique token that expires if the client crashes.

However, a single Redis instance is a **single point of failure**. To mitigate this, the Redlock algorithm uses **multiple independent Redis nodes** (usually five) and requires a majority quorum to consider a lock “acquired”.

---

## The Classic SET‑NX + EX Pattern

### How It Works

```redis
SET resource_lock <unique-token> NX EX 30
```

* **`resource_lock`** – The lock key, usually derived from the resource identifier.  
* **`<unique-token>`** – A UUID or random string generated by the client; it proves ownership.  
* **`NX`** – Only set if the key does not already exist.  
* **`EX 30`** – Expire the key after 30 seconds to avoid deadlocks if the client crashes.

If the command returns `OK`, the client has the lock. Otherwise, another client already holds it.

### Releasing the Lock Safely

A naïve `DEL resource_lock` could delete a lock owned by another client if the original holder’s TTL expires and a new client acquires it. The safe pattern uses a **Lua script** that checks the token before deletion:

```lua
-- unlock.lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

```redis
EVALSHA <sha1-of-unlock.lua> 1 resource_lock <unique-token>
```

Only the owner can successfully delete the key, guaranteeing *ownership* semantics.

### Limitations

* **Single‑node reliability** – If the Redis node crashes, the lock is lost.  
* **Clock‑drift tolerance** – The TTL is enforced by Redis’s own clock; the client must trust it.  
* **Network partitions** – A client may think it holds the lock while the network is partitioned, leading to split‑brain if another client acquires the same lock on a different node.

These shortcomings motivate the **Redlock** algorithm.

---

## Redlock: Redis’ Official Distributed Lock Algorithm

In 2015, Salvatore Sanfilippo (Antirez), the creator of Redis, published the **Redlock** algorithm. It is designed to provide a *fault‑tolerant* lock across multiple Redis instances while preserving safety.

### Algorithm Steps

1. **Generate a unique token** (e.g., UUID).  
2. **Attempt to acquire the lock on N independent Redis nodes** (commonly N = 5) using the `SET key token NX PX ttl` command (PX = milliseconds).  
3. **Record the acquisition time** (the moment the client sent the first `SET`).  
4. **If the client acquires the lock on at least ⌈N/2⌉+1 nodes** (a majority) **and the total elapsed time is less than the TTL**, the lock is considered **acquired**.  
5. **If the majority is not reached**, release the lock on any nodes where it was set (using the safe Lua script).  
6. **To release**, run the Lua script on all N nodes with the same token.

### Correctness Guarantees

| Property | Explanation |
|----------|-------------|
| **Safety (Mutual Exclusion)** | A lock can be held by at most one client because at least one node in the majority will reject a conflicting acquisition. |
| **Liveness** | If a client keeps retrying with exponential back‑off, it will eventually acquire the lock unless a majority of nodes are permanently unavailable. |
| **Fault Tolerance** | The algorithm tolerates up to ⌊(N‑1)/2⌋ node failures or network partitions. |

### Common Misconceptions

* **“Redlock is only safe if all nodes are in the same data center.”**  
  *Correct*: While latency differences affect the TTL budget, Redlock works across data centers as long as the timeout accounts for the worst‑case round‑trip time plus clock drift.

* **“You can use a single Redis node with Redlock and be safe.”**  
  *Incorrect*: The algorithm’s safety stems from the quorum; a single node offers no redundancy.

* **“The TTL must be longer than the longest possible operation.”**  
  *True*: If the operation exceeds the TTL, the lock may expire while still in use, causing another client to acquire it prematurely. Use a *watchdog* to extend the TTL if needed (see “Lock Renewal”).

---

## Designing a Robust Locking Layer

Implementing Redlock directly in application code can be error‑prone. A well‑architected **locking library** abstracts the complexity and enforces best practices.

### Choosing the Right Timeout Strategy

* **Static TTL** – Simple but risky if operation time varies.  
* **Dynamic TTL (Watchdog)** – Periodically extend the lock while the holder is still active.  
* **Back‑off and Retry** – Exponential back‑off reduces contention and avoids “thundering herd” on lock release.

**Best practice**: Set the TTL to **significantly larger** than the expected critical section duration (e.g., 10×) and use a watchdog that renews the lock every `TTL/3` seconds.

### Handling Clock Skew

Redis nodes use their own local clocks for key expiration. If clocks diverge, the effective TTL may differ across nodes, breaking the majority guarantee. Mitigation strategies:

* **Synchronize clocks** via NTP or chrony on all Redis hosts.  
* **Add a safety margin** to the TTL (e.g., add 500 ms).  
* **Prefer PX (millisecond) TTL** to reduce granularity errors.

### Fail‑over and Node Partitioning

When a node becomes unreachable, the client should:

1. **Mark the node as unhealthy** (circuit breaker pattern).  
2. **Continue attempts with the remaining nodes**; as long as a majority remains reachable, the lock can still be acquired.  
3. **Re‑integrate** the node once health checks pass.

**Quorum calculations** must be dynamic: the required majority is ⌈`available_nodes`/2⌉+1, not a static number.

---

## Practical Implementation Examples

Below are minimal yet production‑ready implementations for three popular languages. All examples assume a **five‑node Redis cluster** reachable at `redis://host{i}:6379` (i = 1..5).

### Python Example Using `redis-py`

```python
# redlock.py
import time
import uuid
import redis
from typing import List

# ---------- Configuration ----------
REDIS_NODES = [
    "redis://127.0.0.1:6379/0",
    "redis://127.0.0.1:6380/0",
    "redis://127.0.0.1:6381/0",
    "redis://127.0.0.1:6382/0",
    "redis://127.0.0.1:6383/0",
]

TTL_MS = 30000  # 30 seconds
RETRY_DELAY = 0.2  # seconds
MAX_RETRIES = 3
# -----------------------------------

class Redlock:
    def __init__(self, nodes: List[str]):
        self.clients = [redis.from_url(url) for url in nodes]

    def _acquire_instance(self, client, resource, token):
        return client.set(resource, token, nx=True, px=TTL_MS)

    def acquire(self, resource: str, retry: int = MAX_RETRIES) -> str | None:
        token = str(uuid.uuid4())
        for _ in range(retry):
            start = time.time()
            acquired = 0
            for client in self.clients:
                if self._acquire_instance(client, resource, token):
                    acquired += 1
            elapsed = (time.time() - start) * 1000  # ms
            if acquired >= (len(self.clients) // 2) + 1 and elapsed < TTL_MS:
                return token
            # failed – clean up partial locks
            self.release(resource, token)
            time.sleep(RETRY_DELAY)
        return None

    def release(self, resource: str, token: str):
        # Lua script for safe delete
        script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """
        for client in self.clients:
            try:
                client.eval(script, 1, resource, token)
            except redis.RedisError:
                pass  # ignore failures during release

# ---- Usage Example ----
if __name__ == "__main__":
    lock = Redlock(REDIS_NODES)
    lock_key = "order:12345:process"
    token = lock.acquire(lock_key)
    if token:
        try:
            print("Lock acquired, processing order...")
            # critical section
            time.sleep(5)  # simulate work
        finally:
            lock.release(lock_key, token)
            print("Lock released.")
    else:
        print("Could not acquire lock.")
```

**Key points**

* `acquire` returns a **token** only if a majority is obtained within the TTL.  
* The `release` method runs the Lua script on **all nodes**, guaranteeing safe deletion.  
* The implementation includes a **retry loop** with exponential back‑off (can be added) and a **watchdog** can be built on top by periodically calling `extend`.

### Node.js Example Using `ioredis`

```javascript
// redlock.js
const Redis = require('ioredis');
const { v4: uuidv4 } = require('uuid');

const NODES = [
  { host: '127.0.0.1', port: 6379 },
  { host: '127.0.0.1', port: 6380 },
  { host: '127.0.0.1', port: 6381 },
  { host: '127.0.0.1', port: 6382 },
  { host: '127.0.0.1', port: 6383 },
];

const TTL_MS = 30000; // 30 seconds
const RETRY_DELAY = 200; // ms
const MAX_RETRIES = 3;

class Redlock {
  constructor(nodes) {
    this.clients = nodes.map(conf => new Redis(conf));
    this.unlockScript = `
      if redis.call("GET", KEYS[1]) == ARGV[1] then
        return redis.call("DEL", KEYS[1])
      else
        return 0
      end
    `;
  }

  async acquire(resource) {
    const token = uuidv4();
    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      const start = Date.now();
      let successes = 0;

      await Promise.all(this.clients.map(async client => {
        const ok = await client.set(resource, token, 'PX', TTL_MS, 'NX');
        if (ok === 'OK') successes += 1;
      }));

      const elapsed = Date.now() - start;
      if (successes >= Math.floor(this.clients.length / 2) + 1 && elapsed < TTL_MS) {
        return token;
      }

      // Clean up partial locks
      await this.release(resource, token);
      await new Promise(res => setTimeout(res, RETRY_DELAY));
    }
    return null;
  }

  async release(resource, token) {
    await Promise.all(this.clients.map(client => client.eval(this.unlockScript, 1, resource, token).catch(() => {})));
  }
}

// ---- Usage ----
(async () => {
  const lock = new Redlock(NODES);
  const key = 'invoice:6789:generate';
  const token = await lock.acquire(key);
  if (token) {
    try {
      console.log('Lock acquired – generating invoice...');
      // critical section
      await new Promise(r => setTimeout(r, 4000));
    } finally {
      await lock.release(key, token);
      console.log('Lock released.');
    }
  } else {
    console.log('Failed to acquire lock.');
  }
})();
```

### Java Example Using Lettuce

```java
// Redlock.java
import io.lettuce.core.*;
import io.lettuce.core.api.StatefulRedisConnection;
import io.lettuce.core.api.sync.RedisCommands;

import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;

public class Redlock {
    private static final long TTL_MS = 30_000L;
    private static final int MAX_RETRIES = 3;
    private static final long RETRY_DELAY_MS = 200L;

    private final List<RedisClient> clients;
    private final String unlockScript = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """;

    public Redlock(List<RedisURI> uris) {
        this.clients = new ArrayList<>();
        for (RedisURI uri : uris) {
            clients.add(RedisClient.create(uri));
        }
    }

    public String acquire(String resource) throws InterruptedException {
        String token = UUID.randomUUID().toString();
        for (int attempt = 0; attempt < MAX_RETRIES; attempt++) {
            long start = System.currentTimeMillis();
            int successes = 0;
            for (RedisClient client : clients) {
                try (StatefulRedisConnection<String, String> conn = client.connect()) {
                    RedisCommands<String, String> sync = conn.sync();
                    String res = sync.set(resource, token,
                            SetArgs.Builder.nx().px(Duration.ofMillis(TTL_MS)));
                    if ("OK".equals(res)) successes++;
                } catch (Exception ignored) {}
            }
            long elapsed = System.currentTimeMillis() - start;
            if (successes >= (clients.size() / 2) + 1 && elapsed < TTL_MS) {
                return token;
            }
            // Cleanup
            release(resource, token);
            Thread.sleep(RETRY_DELAY_MS);
        }
        return null;
    }

    public void release(String resource, String token) {
        for (RedisClient client : clients) {
            try (StatefulRedisConnection<String, String> conn = client.connect()) {
                RedisAsyncCommands<String, String> async = conn.async();
                async.eval(unlockScript, ScriptOutputType.INTEGER, new String[]{resource}, token);
            } catch (Exception ignored) {}
        }
    }

    // Example usage
    public static void main(String[] args) throws Exception {
        List<RedisURI> nodes = List.of(
                RedisURI.create("redis://127.0.0.1:6379"),
                RedisURI.create("redis://127.0.0.1:6380"),
                RedisURI.create("redis://127.0.0.1:6381"),
                RedisURI.create("redis://127.0.0.1:6382"),
                RedisURI.create("redis://127.0.0.1:6383")
        );
        Redlock lock = new Redlock(nodes);
        String key = "batch:process:2026-03-05";
        String token = lock.acquire(key);
        if (token != null) {
            try {
                System.out.println("Lock acquired – performing batch job...");
                Thread.sleep(8000); // simulate work
            } finally {
                lock.release(key, token);
                System.out.println("Lock released.");
            }
        } else {
            System.out.println("Unable to acquire lock.");
        }
    }
}
```

All three snippets follow the same logical steps: generate a token, attempt `SET NX PX` on each node, verify majority, and clean up via a Lua script.

---

## Testing and Observability

A lock implementation is only as good as its tests and monitoring.

### Unit Tests with Mock Redis

* Use libraries such as **`fakeredis`** (Python) or **`ioredis-mock`** (Node) to simulate Redis behavior.  
* Verify that `acquire` returns `null` when fewer than a majority of nodes succeed.  
* Test the Lua script’s safety by mocking a scenario where the token mismatches.

### Integration Tests in a Multi‑Node Cluster

* Spin up a **Docker Compose** environment with five Redis containers.  
* Introduce network partitions using `tc` or Docker’s `--network` options to ensure the client respects quorum.  
* Simulate node crashes while holding a lock and confirm that the lock expires correctly.

### Metrics to Monitor

| Metric | Description |
|--------|-------------|
| `redis_lock_acquire_success_total` | Counter of successful lock acquisitions. |
| `redis_lock_acquire_failure_total` | Counter of failed attempts (including retries). |
| `redis_lock_hold_duration_seconds` | Histogram of how long locks are held. |
| `redis_node_health` | Gauge (1 = healthy, 0 = down) per node. |
| `redis_lock_expiration_rate` | Number of locks that expired without explicit release (potential leaks). |

Expose these via **Prometheus** or a similar scraping endpoint; alert when the failure rate spikes or when expirations exceed a threshold.

---

## Pitfalls and Anti‑Patterns

| Pitfall | Why It’s Dangerous | Mitigation |
|---------|--------------------|------------|
| **Using a static short TTL** | Operations may exceed the TTL, causing premature lock release and data races. | Set TTL > expected duration × 2 and implement a watchdog to extend it. |
| **Locking around I/O that can block indefinitely** | If the process hangs, the lock may expire while the operation is still in progress. | Keep critical sections short; move long I/O outside the lock or use a *lease* pattern with explicit renewal. |
| **Storing business data directly in the lock key** | Increases key size, slows `SET` and `GET`, and may cause accidental key collisions. | Keep lock keys lightweight; store any payload in a separate hash if needed. |
| **Relying on `DEL` without token verification** | Leads to *lost‑lock* bugs where one client deletes another’s lock. | Always use the compare‑and‑delete Lua script. |
| **Assuming Redis persistence (RDB/AOF) guarantees lock durability** | Persistence is asynchronous; a crash can lose the lock state. | Treat locks as *ephemeral*; rely on TTL and majority quorum, not on disk persistence. |
| **Using a single Redis instance for production locks** | Single point of failure; loss of lock leads to duplicate processing. | Deploy at least five independent nodes and use Redlock. |
| **Neglecting client‑side clock drift** | If the client’s notion of time differs from Redis’s, it may incorrectly assume a lock is still valid. | Do not use client‑side timers for expiration; rely on Redis‑enforced TTL. |

---

## Alternatives to Redis for Distributed Locking

| Service | Strengths | Trade‑offs |
|---------|-----------|------------|
| **Zookeeper** | Strong consistency via Zab consensus; built‑in recipes for locks and leader election. | Higher latency, operational complexity, requires JVM ecosystem. |
| **etcd** | Raft‑based, lightweight, HTTP/JSON API, good integration with Kubernetes. | Slightly slower than in‑memory Redis; requires careful lease management. |
| **Consul** | Service discovery + KV store; supports sessions for lock semantics. | Not as performant for high‑throughput lock contention. |
| **Database Row Locks** | Leverages existing RDBMS; ACID guarantees. | Limited scalability; locks held for the duration of a transaction can block other queries. |
| **Hazelcast / Apache Ignite** | In‑memory data grids with native lock APIs. | Requires cluster management; higher memory footprint. |

Redis remains a **sweet spot** for many micro‑service architectures: sub‑millisecond latency, simple client libraries, and a proven Redlock implementation. However, if you need **linearizable consistency guarantees across geographically dispersed data centers**, a consensus‑based store like etcd or Zookeeper may be preferable.

---

## Conclusion

Distributed locking is a cornerstone of reliable coordination in modern, highly‑parallel applications. Redis provides a fast, developer‑friendly platform, but building a **correct** lock requires more than a single `SET NX EX`. By embracing the **Redlock algorithm**, respecting quorum, handling clock skew, and employing robust timeout strategies, you can achieve a lock service that:

* Guarantees **mutual exclusion** even under node failures and network partitions.  
* Offers **liveness** through retries and exponential back‑off.  
* Integrates cleanly with observability pipelines, letting you detect contention and failures early.

The code examples in Python, Node.js, and Java demonstrate how to turn the algorithm into a reusable library. Pair these implementations with thorough unit/integration testing, metrics collection, and a well‑tuned retry/back‑off policy, and you’ll have a production‑grade distributed lock ready for high‑traffic workloads.

Remember, a lock is a **synchronization primitive**, not a silver bullet. Keep critical sections as small as possible, avoid long‑running I/O inside the lock, and always design for failure. With those principles and the patterns described here, Redis can serve as a reliable backbone for your system’s coordination needs.

---

## Resources

- **Redis Documentation – Distributed Locks** – Official guide covering `SET NX EX` and Redlock.  
  [https://redis.io/docs/reference/patterns/distributed-locks/](https://redis.io/docs/reference/patterns/distributed-locks/)

- **“Redis – A Distributed Lock Implementation” (Antirez Blog)** – The original post by Salvatore Sanfilippo introducing Redlock.  
  [https://redis.io/topics/distlock](https://redis.io/topics/distlock)

- **“Designing Distributed Systems: The CAP Theorem and Beyond”** – A deep dive into consistency models and their impact on lock design.  
  [https://martinfowler.com/articles/capTheorem.html](https://martinfowler.com/articles/capTheorem.html)

- **etcd – Distributed Key‑Value Store** – For readers interested in Raft‑based alternatives.  
  [https://etcd.io/docs/v3.5/learning/](https://etcd.io/docs/v3.5/learning/)

- **Prometheus – Monitoring Distributed Locks** – Guidance on exposing lock metrics.  
  [https://prometheus.io/docs/practices/instrumentation/](https://prometheus.io/docs/practices/instrumentation/)