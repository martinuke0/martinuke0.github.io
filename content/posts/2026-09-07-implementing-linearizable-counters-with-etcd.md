---
title: "Implementing Linearizable Counters with etcd's Transaction API"
date: "2026-09-07T17:00:43.010"
draft: false
tags: ["etcd", "distributed-systems", "consensus", "kubernetes", "transactions"]
description: "Build linearizable distributed counters on etcd using compare-and-swap, ModRevision, and the Transaction API for strong consistency at scale."
summary: "How to design and ship linearizable counters on etcd using the Transaction API, ModRevision guards, and watch-based retry loops."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-implementing-linearizable-counters-with-etcd.svg"
  alt: "Distributed counter synchronization diagram"
  caption: ""
  relative: false
---

> **TL;DR** — etcd gives every key a monotonic `ModRevision` that increments on every write, making it the ideal guard for linearizable counters. By combining `Txn` with `compare(modRevision == X)` followed by a put with an incremented value, you get strict sequential consistency across a cluster — no client-side locks, no read-modify-write races.

If you've ever needed a globally consistent counter — leader election tallies, monotonic job IDs, rate-limit buckets across pods, feature-flag rollout percentages — you've probably hit the same wall: a naive read-modify-write loop in a distributed system is a race condition waiting to happen. Two clients read the same value, both increment, and you lose one of the writes. etcd solves this elegantly with a single API surface: [the `Txn` method](https://etcd.io/docs/v3.5/learning/api/#transaction-rpc), which evaluates a set of conditions and atomically commits a set of operations only if every condition holds. This post walks through how to turn that primitive into a production-grade linearizable counter.

## Why etcd Is Unusually Well-Suited to This

Most distributed key-value stores expose either "fast but eventually consistent" semantics (DynamoDB, Cassandra) or "linearizable but heavy" semantics (Zab-backed ZooKeeper). etcd sits in a sweet spot: it's built on [Raft](https://raft.github.io/raft.pdf), which serializes every write through a single leader, but the API stays simple enough that you don't need a PhD to use it correctly.

What makes counters specifically clean on etcd is a piece of metadata that often goes unnoticed: `ModRevision`. Every successful write bumps the key's modification revision, and revisions are cluster-wide monotonically increasing integers assigned by the Raft log. The official [etcd API guarantees](https://etcd.io/docs/v3.5/learning/api/#response-headers) that if two writes succeed, the one with the lower `ModRevision` happened first. That property is exactly what you need to detect concurrent updates — and it's exposed directly to clients as part of every key-value pair and every range response.

## The Core Pattern: Compare-and-Swap as a Counter

The classic anti-pattern is this:

```python
# WRONG: classic lost-update race
current = client.get("/counter/users")
client.put("/counter/users", current + 1)
```

Between the `get` and the `put`, another client can write. Both clients put the same `current + 1`, and one increment is silently lost. The fix is to make the write conditional on the value (or revision) we observed:

```python
from etcd3 import client

etcd = client()

def increment(key: str, delta: int = 1) -> int:
    """Linearizable increment with bounded retry."""
    while True:
        resp = etcd.get(key)
        new_revision = (resp.mod_revision or 0) + 1
        new_value = (int(resp.value or b"0")) + delta

        succeeded, responses = etcd.transaction(
            compare=[resp.mod_revision == 0],   # placeholder; replaced below
            success=[etcd.transactions.put(key, str(new_value))],
            failure=[],
        )
        # Real implementation uses the condition we built above — see below.
        if succeeded:
            return new_value
```

That code is almost right but misleadingly simple. The compare clause needs to encode the revision we just read. Let's fix it properly:

```python
def increment(key: str, delta: int = 1) -> int:
    while True:
        # 1. Read current state including its ModRevision.
        resp = etcd.get(key)
        observed_revision = resp.mod_revision
        observed_value = int(resp.value or b"0")
        next_value = observed_value + delta

        # 2. Atomic CAS: only commit if revision hasn't moved.
        ok, _ = etcd.transaction(
            compare=[
                etcd.transactions.value(key) == str(observed_value).encode(),
                etcd.transactions.mod(key) == observed_revision,
            ],
            success=[
                etcd.transactions.put(key, str(next_value)),
            ],
            failure=[],
        )

        if ok:
            return next_value

        # 3. Someone else won the race; loop and retry with fresh state.
```

Two things to notice. First, the compare list has two conditions joined by AND: the value must match *and* the ModRevision must match. The revision check is theoretically sufficient — if the revision is the same, the value is the same — but adding the value check makes intent clearer in logs and protects against accidental schema corruption. Second, the loop is unbounded, which is fine for normal traffic but problematic under extreme contention. We'll address that in the *Patterns in Production* section.

### Why ModRevision Beats Value-Only CAS

A counter that compares only on value has a subtle bug: if a key goes from `5` → `6` → `5` (decrement then increment), the second writer's compare succeeds and overwrites `5` again, losing the intermediate `6`. Tracking the revision closes that gap because revisions are append-only — once a write lands, its revision is gone forever. This is the same trick used inside etcd itself for lease-based key leasing, as documented in the [etcd v3 API guide](https://etcd.io/docs/v3.5/learning/api/).

## A Reference Client with Backoff and Watch-Based Retry

For a more production-shaped implementation, we want jittered exponential backoff and a way to wait on changes without busy-spinning. The `watch` API gives us both: we can request a watch starting at a specific revision, and the server pushes notifications when the key changes, eliminating the need for tight polling loops.

```python
import random
import time
from dataclasses import dataclass
from etcd3 import client

@dataclass
class CounterConfig:
    max_retries: int = 16
    base_backoff: float = 0.005
    max_backoff: float = 0.5

class EtcdCounter:
    def __init__(self, key: str, cfg: CounterConfig | None = None):
        self.key = key
        self.cfg = cfg or CounterConfig()
        self.client = client()

    def _backoff(self, attempt: int) -> float:
        # Full jitter: random uniform in [0, capped_exponential].
        cap = min(self.cfg.max_backoff, self.cfg.base_backoff * (2 ** attempt))
        return random.uniform(0, cap)

    def increment(self, delta: int = 1) -> int:
        for attempt in range(self.cfg.max_retries):
            resp = self.client.get(self.key)
            observed_rev = resp.mod_revision or 0
            observed_val = int(resp.value or b"0")
            target_val = observed_val + delta

            ok, _ = self.client.transaction(
                compare=[
                    self.client.transactions.value(self.key) == str(observed_val).encode(),
                    self.client.transactions.mod(self.key) == observed_rev,
                ],
                success=[self.client.transactions.put(self.key, str(target_val))],
                failure=[],
            )
            if ok:
                return target_val

            time.sleep(self._backoff(attempt))

        raise RuntimeError(f"Counter {self.key} failed after {self.cfg.max_retries} retries")

    def get(self) -> int:
        return int(self.client.get(self.key).value or b"0")
```

The full-jitter backoff comes from the [AWS Architecture Blog's classic post](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) on retry strategies — it avoids the synchronized thundering herd that fixed backoffs cause. Under heavy contention, this implementation naturally degrades to one of the slowest clients winning the race, never the fastest, which is the property you want for fairness.

## Patterns in Production

A textbook implementation is one thing; running it on a real cluster is another. Here are four patterns I've seen matter.

### 1. Distinct Keys Per Logical Counter

Don't reuse one key for "users created today" and "users created this hour." etcd writes are serialized, so a single hot key becomes a throughput bottleneck — every increment blocks every other increment cluster-wide until Raft commits. Splitting into `counters/users:2026-09-07` and `counters/users:2026-09-07T17` lets independent increments proceed in parallel as long as they touch different keys. Because revisions are cluster-global, you still get linearizability per logical counter.

### 2. Per-Key Watch for Notification, Not Polling

A common anti-pattern is incrementing in a tight loop with no observability. Instead, when a CAS fails, subscribe to a watch on the key and block until the next revision lands:

```python
def increment_with_watch(self, delta: int = 1) -> int:
    while True:
        resp = self.client.get(self.key)
        next_val = int(resp.value or b"0") + delta

        ok, _ = self.client.transaction(
            compare=[self.client.transactions.mod(self.key) == resp.mod_revision],
            success=[self.client.transactions.put(self.key, str(next_val))],
            failure=[],
        )
        if ok:
            return next_val

        # Wait for the next change before retrying.
        self.client.watch(self.key, start_revision=resp.mod_revision + 1)
```

This trades CPU for latency-tail improvements: under contention, we wait for the cluster to settle instead of generating stampeding traffic. The semantics are described in the [etcd watch API documentation](https://etcd.io/docs/v3.5/learning/api/#watch-api).

### 3. Lease-Backed Counters for Auto-Expiration

If you're counting active sessions, you don't want stale keys cluttering the keyspace forever. Wrap the counter write in a lease:

```python
lease = self.client.lease(60)  # 60-second TTL
self.client.transactions.put(self.key, str(value), lease=lease)
```

When the lease expires, etcd deletes the key. Readers must handle the absent case (treat as zero), and concurrent writers must treat absence as `observed_value == 0` with `observed_revision == 0`. The [etcd lease docs](https://etcd.io/docs/v3.5/learning/api/#lease-api) are clear about TTL semantics, but the gotcha is that leases are tied to keys, not values — when the lease dies, the key is gone and any in-flight CAS will fail until you re-read.

### 4. Batch Increments with Single Txn

If you need to increment five counters atomically (e.g., "increment monthly + daily + hourly + minute + all-time"), put them all in one `Txn`:

```python
ok, _ = self.client.transaction(
    compare=[
        self.client.transactions.mod("/counters/monthly") == monthly_rev,
        self.client.transactions.mod("/counters/daily") == daily_rev,
        self.client.transactions.mod("/counters/hourly") == hourly_rev,
    ],
    success=[
        self.client.transactions.put("/counters/monthly", str(monthly_val)),
        self.client.transactions.put("/counters/daily", str(daily_val)),
        self.client.transactions.put("/counters/hourly", str(hourly_val)),
    ],
    failure=[],
)
```

All conditions must hold, or none of the puts happen. This is the transactional sweet spot that pure KV stores can't offer, and it's why etcd is used for far more than service discovery. As the [etcd maintainers note](https://etcd.io/docs/v3.5/learning/why/), consistency is the design center, not an afterthought.

## Architecture: How This Maps onto Kubernetes etcd

In a Kubernetes cluster, your counter lives in the same etcd that backs `kube-apiserver`. That has two implications.

First, every counter write competes with Kubernetes control-plane writes for Raft throughput. The default etcd configuration targets sub-100ms commit latency for small writes, but at high QPS you'll see fsync saturation. The [etcd tuning guide for Kubernetes](https://etcd.io/docs/v3.5/tuning/) recommends separating heavy workloads onto a dedicated etcd cluster, and counters are exactly the kind of workload that justifies it.

Second, client traffic goes through Kubernetes service IPs and `kube-apiserver` proxies in many setups, which adds latency and failure modes. If your counter is performance-critical, point clients directly at the etcd cluster using the peer endpoints, ideally with TLS and mTLS certificates issued by [etcd-manager or the cert-signing CSR API](https://kubernetes.io/docs/reference/access-authn-authz/certificate-signing-requests/).

A reasonable production topology looks like this:

```
+-----------------+        +------------------+        +-----------------+
| Counter clients |------->| Dedicated etcd   |<------>| kube-apiserver  |
| (Python/Go/Rust)|        | cluster          |        | etcd (separate) |
+-----------------+        +------------------+        +-----------------+
                                   |
                                   v
                          +------------------+
                          | Watch subscribers |
                          | (alerting, audit) |
                          +------------------+
```

Splitting the etcd cluster is not free — you now operate two Raft groups — but for counters that drive billing or safety-critical state, the isolation is worth it.

## Failure Modes and What to Watch

Even with linearizable CAS, real systems fail in interesting ways. A few worth instrumenting from day one:

- **Lease pressure**. Counters backed by short leases (TTL < 30s) can pile up if the cluster is under load — lease TTL extensions compete with your counter writes for Raft slots. The [etcd metrics endpoint](https://etcd.io/docs/v3.5/metrics/) exposes `lease_granted_total` and `lease_revoked_total`, both worth graphing.
- **Read skew across replicas**. etcd linearizable reads force the leader to confirm quorum, but stale reads (set on the client) bypass that. Always use linearizable reads in your CAS loop unless you have a very specific reason. The [etcd client flag for linearizable reads](https://etcd.io/docs/v3.5/dev-guide/api_grpc_gateway/) is `quorum=true` on `Range` — make sure your library doesn't default to `false`.
- **Compaction-induced watch gaps**. etcd periodically compacts old revisions to bound storage, which can break long-running watches. The [etcd `alarm` and `compact` documentation](https://etcd.io/docs/v3.5/op-guide/maintenance/) explains the `--auto-compaction-mode` and `--auto-compaction-retention` knobs. If your watchers rely on old revisions, set retention conservatively or use external revision-tracking.

## Comparing to Alternatives

etc isn't the only option. A quick comparison:

- **Redis `INCR`**. Atomic and fast, but Redis is single-leader within a shard, not consensus-based. If your shard fails over mid-write, you can lose increments. Redis is the right call if you don't need durability guarantees, just speed.
- **Postgres `UPDATE ... RETURNING`** with `SERIALIZABLE` isolation. Genuinely serializable, durable, and supports rich queries — but transactions conflict more readily at high concurrency, causing retry storms. Postgres wins when you also need joins or aggregates on the counter data.
- **DynamoDB conditional updates**. Strongly consistent reads are opt-in and expensive; the API is similar to etcd's `Txn` but lacks native `ModRevision`-style monotonic guards, so you must build them yourself from a version attribute.
- **A custom Raft implementation**. Gives you everything etcd gives you, plus custom operations. Cost: you're now a distributed systems team. Worth it only at scale.

For most teams that already have etcd running for Kubernetes or Consul-style coordination, building counters on top of it is the lowest-friction path to strong consistency.

## Key Takeaways

- **Use `ModRevision`, not value-only CAS.** It's monotonic and append-only, so it closes the loop on decrement-then-increment races that value-based compares miss.
- **Put all conditions in one `Txn`.** A multi-key atomic increment is exactly the workload the Transaction API was built for — don't simulate it with multiple round-trips.
- **Apply full-jitter exponential backoff.** Synchronized retries cause Raft commit contention; full jitter spreads them out.
- **Mind etcd's shared throughput budget.** Every counter write competes with everything else on the cluster; shard hot counters and consider a dedicated cluster for billing or safety-critical state.
- **Watch for compaction, lease pressure, and read skew.** etcd's defaults are sane, but a long-running counter service needs metrics and alerts on `etcd_disk_wal_fsync_duration_seconds`, `lease_granted_total`, and `range_duration_seconds`.

## Further Reading

- [etcd v3 API: Transaction RPC](https://etcd.io/docs/v3.5/learning/api/#transaction-rpc) — the authoritative reference for `Txn` semantics.
- [etcd v3 API: Watch API](https://etcd.io/docs/v3.5/learning/api/#watch-api) — how to react to counter changes without polling.
- [etcd v3 API: Lease API](https://etcd.io/docs/v3.5/learning/api/#lease-api) — TTL semantics for self-expiring counters.
- [etcd Operations Guide: Maintenance](https://etcd.io/docs/v3.5/op-guide/maintenance/) — compaction, defragmentation, and alarm handling.
- [In Search of an Understandable Consensus Algorithm (Raft paper)](https://raft.github.io/raft.pdf) — the consensus protocol etcd implements.
- [AWS Architecture Blog: Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) — the retry strategy powering `EtcdCounter._backoff`.

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
