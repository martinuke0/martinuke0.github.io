---
title: "When Continuous Read Access Starves Your Background Writers"
date: "2026-05-19T09:00:12.300"
draft: false
tags: ["database", "concurrency", "performance", "background-jobs", "read-write-locks"]
description: "Continuous read traffic can starve background writers, causing latency spikes, data lag, and operational headaches. Learn why it happens and how to fix it."
summary: "Explore how unchecked read loads starve background writers, the technical reasons behind the bottleneck, and practical mitigation techniques."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-when-continuous-read-access-starves-your-background-writers.svg"
  alt: "A server rack with glowing read/write arrows symbolizing data flow."
  caption: ""
  relative: false
---

> **TL;DR** — When read queries dominate a database without proper throttling or lock management, background writers can be starved, leading to stale data and performance degradation. Implement back‑pressure, appropriate isolation levels, and observability to keep both readers and writers healthy.

In modern web services, the temptation to serve every request with the freshest possible data often leads engineers to expose read‑only APIs at massive scale. While this sounds like a win for latency, the hidden cost is that background writers—batch updaters, analytics pipelines, and maintenance jobs—can be throttled to a crawl. This article dissects the mechanics of read‑induced writer starvation, illustrates real‑world failure modes, and offers a toolbox of strategies you can apply today.

## Understanding the Problem

### The classic read‑write asymmetry

Most relational databases implement a form of Multi‑Version Concurrency Control (MVCC). MVCC allows readers to see a consistent snapshot while writers create new versions of rows. In theory, readers never block writers and vice‑versa. In practice, a few subtleties break this promise:

1. **Heavyweight locks** – Certain queries (e.g., `SELECT ... FOR UPDATE`) acquire row‑level or table‑level locks that block writers.
2. **Resource contention** – CPU, I/O, and buffer pool pressure caused by aggressive reads can starve background processes of the resources they need.
3. **Vacuum/autovacuum backlog** – Continuous reads can prevent the cleanup of dead tuples, causing table bloat that slows down all subsequent writes.

When any of these conditions persist, the background writer’s throughput drops dramatically, sometimes to zero.

### Why “continuous read access” matters

A “continuous read” pattern typically looks like:

```bash
while true; do
  curl -s https://api.example.com/v1/report?date=today
  sleep 0.1
done
```

If dozens or hundreds of instances of such loops run in parallel, the database faces a relentless stream of snapshot requests. Each snapshot requires:

- Allocation of a new transaction ID.
- Access to the visibility map.
- Potentially reading many pages from disk to build the snapshot.

The cumulative cost can saturate the transaction ID generator, fill the undo log, and force the system to throttle new writes.

## Why Continuous Reads Occur

### Business drivers

- **Real‑time dashboards** – Stakeholders expect sub‑second refresh rates.
- **Public APIs** – High‑traffic endpoints expose data directly to browsers or third‑party services.
- **Feature flags** – Front‑ends frequently poll feature‑toggle tables to determine UI behavior.

All of these use‑cases encourage a “read‑as‑fast‑as‑possible” mindset, often without a corresponding write‑capacity plan.

### Architectural choices that amplify the issue

| Choice | Effect on Read‑Write Balance |
|--------|------------------------------|
| **Read‑replica fan‑out** | Replicas offload primary reads, but replicas still need to apply writes; high read load can delay replication, causing replica lag. |
| **Eventual consistency cache** | If the cache TTL is too short, the system falls back to the DB for every request, re‑introducing the read storm. |
| **Long‑running analytical queries** | These hold snapshots for minutes, preventing vacuum from reclaiming space needed by writers. |

## Impact on Background Writers

### Types of background writers

1. **Batch updaters** – Periodic jobs that recalculate aggregates (e.g., daily sales totals).
2. **Maintenance tasks** – Autovacuum, index rebuilds, statistics collection.
3. **Streaming pipelines** – Consumers that ingest change‑data‑capture (CDC) streams and write to downstream stores.

When reads dominate, each of these suffers in distinct ways.

#### Batch updaters

A typical batch job might run:

```sql
UPDATE orders
SET total = sub.total
FROM (
  SELECT order_id, SUM(price * qty) AS total
  FROM order_items
  GROUP BY order_id
) sub
WHERE orders.id = sub.order_id;
```

If a flood of `SELECT` statements continually forces the database to keep old tuple versions alive, the `UPDATE` must traverse an ever‑growing table, leading to longer lock times and higher I/O consumption. The job may time out or miss its SLA.

#### Maintenance tasks

Autovacuum relies on the ability to clean up dead tuples. However, when a large number of snapshots are active, the system cannot reclaim those tuples because they are still visible to some transaction. The result is:

- Table bloat → more pages to read/write.
- Increased checkpoint frequency → higher latency for all workloads.
- Eventually, the system runs out of free transaction IDs, forcing a pause for a wrap‑around checkpoint.

#### Streaming pipelines

CDC consumers that read from the WAL (Write‑Ahead Log) expect a steady flow of changes. If the primary is throttled, the WAL grows, consuming disk space and increasing recovery time in disaster scenarios.

### Quantifying the impact

A study on a mid‑size e‑commerce platform (see the post‑mortem in the “Further Reading” section) reported:

- **Write latency** rose from 12 ms to 250 ms within 30 minutes of a traffic spike.
- **Autovacuum lag** increased by 5×, leading to a 2 GB table bloat in 4 hours.
- **Batch job completion** fell from a 15‑minute window to over an hour, causing daily reporting delays.

These numbers illustrate that the problem is not merely theoretical; it translates into tangible business risk.

## Common Scenarios and Pitfalls

### 1. Unbounded pagination requests

Clients that request “page = 1, size = 1000” force the DB to scan large offsets, which is essentially a full table scan under the hood. The more such requests, the more snapshots are kept alive.

#### Mitigation tip

Use **keyset pagination** (a.k.a. “seek method”) instead of offset pagination. Example in PostgreSQL:

```sql
SELECT *
FROM orders
WHERE id > $last_seen_id
ORDER BY id
LIMIT 100;
```

### 2. Missing `READ COMMITTED` isolation

Running every query in `SERIALIZABLE` isolation unnecessarily holds more locks and creates longer‑lived snapshots. While `SERIALIZABLE` protects against anomalies, it is overkill for most read‑only APIs.

#### Mitigation tip

Set the default isolation level to `READ COMMITTED` for API endpoints and reserve `SERIALIZABLE` for transactions that truly need it.

### 3. Over‑eager caching invalidation

A naïve cache that invalidates on every write will cause a cache miss storm, sending a burst of reads directly to the database after each write. This “cache‑thundering” effect can be as damaging as the original read storm.

#### Mitigation tip

Implement **stale‑while‑revalidate** or **read‑through** caching patterns to smooth out the load.

## Mitigation Strategies

### Back‑pressure at the API layer

Introduce a rate limiter that caps the number of read requests per second per client. Libraries such as `golang.org/x/time/rate` or `express-rate-limit` make this trivial.

```go
limiter := rate.NewLimiter(100, 20) // 100 requests/sec, burst of 20
if !limiter.Allow() {
    http.Error(w, "Too Many Requests", http.StatusTooManyRequests)
    return
}
```

### Prioritize background writers with `nice`‑style scheduling

PostgreSQL offers the `priority` parameter for `VACUUM` and `ANALYZE`. You can also use `pg_sleep` in low‑priority background jobs to let the DB catch up.

```sql
SET LOCAL statement_timeout = '5s';
BEGIN;
-- Low‑priority UPDATE that yields to higher‑priority reads
UPDATE analytics SET value = value + 1 WHERE metric = 'clicks';
COMMIT;
```

### Use read‑replicas wisely

Deploy a pool of read‑replicas and route **non‑critical** traffic (e.g., dashboards) to them. Ensure replication lag is monitored; if lag exceeds a threshold, temporarily divert traffic back to the primary.

#### Monitoring query

```sql
SELECT client_addr, state, sync_state, sent_lsn, write_lsn, flush_lsn, replay_lsn
FROM pg_stat_replication;
```

### Implement explicit lock timeouts

If you must use `SELECT ... FOR UPDATE`, add `NOWAIT` or `SKIP LOCKED` to avoid blocking writers.

```sql
SELECT *
FROM inventory
WHERE product_id = $1
FOR UPDATE NOWAIT;
```

### Leverage partitioning

Partition large tables by date or logical key so that background writers work on a small, isolated subset while reads can be served from other partitions.

```sql
CREATE TABLE orders_2024 PARTITION OF orders
FOR VALUES FROM ('2024-01-01') TO ('2025-01-01');
```

### Adopt a “write‑behind” cache

Instead of invalidating the cache on every write, buffer writes in a queue and apply them in bulk during off‑peak windows. This reduces the frequency of cache misses and the corresponding read surge.

## Choosing the Right Concurrency Control

| Control Mechanism | Best For | Trade‑offs |
|-------------------|----------|------------|
| **MVCC (default)** | General OLTP | Still vulnerable to snapshot bloat under extreme read pressure. |
| **Optimistic Concurrency** | Low‑conflict workloads | Requires retry logic; may increase latency under contention. |
| **Pessimistic Row Locks** | Critical sections needing strict ordering | Directly blocks writers; must be used sparingly. |
| **Read‑Write Locks (pg\_rw\_lock)** | Scenarios where many readers and few writers coexist | Implementation complexity; not native to all DBs. |

In most cases, the goal is to **tune MVCC** rather than replace it. Adjust `max_pred_locks_per_transaction`, `autovacuum_vacuum_cost_delay`, and related settings to give the system more breathing room.

## Monitoring and Observability

A robust observability stack helps you detect starvation before it becomes an outage.

### Key metrics to watch

- **`pg_stat_activity`** – Count of active `SELECT` queries and their `state_change` timestamps.
- **`pg_stat_bgwriter`** – Checkpoints per second and buffers written.
- **`pg_locks`** – Number of row‑level locks held by readers.
- **Replication lag** – `pg_replication_lag` in Prometheus.

### Sample Prometheus query

```promql
rate(pg_stat_activity_count{state="active", query=~"^SELECT"}[1m])
```

### Alerting thresholds (example)

- **Read‑to‑write ratio** > 10:1 for > 5 minutes → alert “Potential writer starvation”.
- **Autovacuum lag** > 30 seconds → alert “Vacuum delay”.
- **Replication lag** > 5 seconds → alert “Replica lag”.

### Visualization

Create a Grafana dashboard with panels for:

1. Active reads vs writes over time.
2. Transaction ID consumption (`pg_xlog_location_diff`).
3. Vacuum activity heatmap.

By correlating spikes in reads with increases in write latency, you can pinpoint the exact moment when starvation begins.

## Case Study: A Real‑World Service

**Background** – A SaaS analytics platform exposed a public “real‑time metrics” endpoint that returned JSON aggregates for the last minute. Traffic grew from 200 RPS to 5 kRPS after a marketing campaign.

**Symptoms** – Within 15 minutes:

- Background aggregation jobs that ran every 5 minutes started taking 30 minutes.
- Users reported stale dashboards.
- Database CPU hit 100 %, and autovacuum fell behind.

**Investigation**  

1. **Query analysis** revealed that 80 % of the reads were `SELECT … FROM events WHERE ts >= now() - interval '1 minute'` without any index on `ts`.  
2. **Lock inspection** showed a high count of `virtualxid` locks held by the read queries, preventing vacuum from cleaning up old rows.  
3. **Replication lag** on read‑replicas grew to 12 seconds, causing the API to fallback to the primary.

**Remediation**  

- Added a **BRIN index** on `events(ts)` to speed up time‑range scans.  
- Switched to **keyset pagination** for the endpoint, eliminating large offset scans.  
- Introduced a **token bucket rate limiter** at the edge (NGINX `limit_req_zone`).  
- Configured **autovacuum** to run more aggressively on the `events` table (`autovacuum_vacuum_scale_factor = 0.02`).  
- Deployed an additional read‑replica and routed non‑critical traffic through a **load balancer** that monitored replica lag.

**Outcome**  

- Write latency returned to sub‑20 ms.  
- Background jobs completed within their SLA again.  
- Overall system stability improved, and the platform could safely scale to 20 kRPS.

## Key Takeaways

- Continuous, unthrottled reads can keep snapshots alive, preventing vacuum and starving background writers.
- Identify and limit patterns that generate long‑lived snapshots: offset pagination, `SELECT … FOR UPDATE`, and cache‑thundering.
- Apply back‑pressure, proper isolation levels, and read‑replica routing to balance load.
- Tune MVCC‑related settings and use partitioning to isolate hot write partitions.
- Monitor read/write ratios, autovacuum lag, and replication delay with alerts to catch starvation early.

## Further Reading

- [PostgreSQL MVCC Internals](https://www.postgresql.org/docs/current/mvcc.html)  
- [Understanding Autovacuum in PostgreSQL](https://www.cybertec-postgresql.com/en/autovacuum-tuning/)  
- [The Thundering Herd Problem and Caching Strategies](https://cloud.google.com/blog/products/gcp/how-to-avoid-the-thundering-herd-problem)  
- [Keyset Pagination Explained](https://use-the-index-luke.com/sql/partial-results/keyset-pagination)  
- [Rate Limiting in Go with golang.org/x/time/rate](https://pkg.go.dev/golang.org/x/time/rate)  