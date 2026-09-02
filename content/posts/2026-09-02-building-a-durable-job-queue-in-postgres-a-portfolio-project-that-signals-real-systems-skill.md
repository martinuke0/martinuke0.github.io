---
title: "Building a Durable Job Queue in Postgres: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-02T16:00:50.142"
draft: false
tags: ["postgres", "job-queue", "python", "system-design", "portfolio"]
description: "A hands-on build guide for a durable Postgres-backed job queue with retries, exponential backoff, and a dead-letter queue — designed as a CV-grade side project."
summary: "Build a production-flavored job queue on Postgres from scratch: schema, worker loop, retries with exponential backoff, and a dead-letter queue. A portfolio project that demonstrates real distributed systems thinking."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-building-a-durable-job-queue-in-postgres-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Diagram of a Postgres-backed job queue with workers, retries, and a dead-letter table."
  caption: ""
  relative: false
---

> **TL;DR** — You'll build a real, runnable job queue on Postgres with `SELECT ... FOR UPDATE SKIP LOCKED`, retries driven by exponential backoff with jitter, and a dead-letter queue for poison messages. It's a weekend-sized project that surfaces the same engineering concerns — idempotency, observability, backpressure — that production queues like Sidekiq, SQS, and Celery solve every day.

## Why This Project Stands Out on a CV

Hiring managers skim dozens of CRUD apps, todo lists, and weather dashboards. What stops the scroll is a project that visibly grapples with **concurrency, failure, and state** — the three forces that separate toy software from real systems. A Postgres-backed job queue checks all three.

Specifically, this project demonstrates:

- **Concurrency primitives.** You'll use `SELECT ... FOR UPDATE SKIP LOCKED`, the same pattern Sidekiq, River, and `pg_cron` rely on for safe concurrent dequeues without a separate broker. Hiring managers recognize the phrase — it signals you understand how queues actually work under the hood.
- **Retry semantics and backpressure.** Exponential backoff with jitter, max-attempt caps, and a dead-letter queue (DLQ) are not decorations. They're how every production system handles transient failure and poison messages. Stating "implemented a DLQ with replay semantics" on a CV reads very differently from "built a Flask app."
- **Idempotency thinking.** Real job queues must survive worker crashes mid-execution, which means jobs need idempotency keys and the worker has to think about exactly-once effects. That single concern is a senior-engineer interview topic.
- **Operational awareness.** The project naturally grows dashboards, structured logs, metrics, and graceful shutdown. Each of these is a checkbox on a backend job description.

The roles it signals for: **Backend Engineer**, **Platform/Infrastructure Engineer**, **Site Reliability Engineer**, and **Data Engineer** (because ETL pipelines are job queues with extra steps). For new grads, it's the single best way to answer "tell me about a system you designed" without sounding like everyone else.

## Architecture Overview

The whole system is intentionally small. You can draw it on a napkin.

**Components:**

- **Postgres** — the source of truth. Holds the `jobs` table (active work), the `dead_letter_jobs` table (poison messages), and a small `job_runs` table (audit trail).
- **Producers** — any code that does `INSERT INTO jobs (...)`. Your web app, a cron tick, an API endpoint. They're decoupled from workers entirely.
- **Workers** — one or more Python processes running a poll loop. Each loop iteration claims a job with `SELECT ... FOR UPDATE SKIP LOCKED`, executes it, and either marks it complete or schedules a retry.
- **The retry timer** — implemented as a `not_before` timestamp on the row. A worker that "fails" doesn't re-enqueue immediately; it updates `not_before = now() + backoff(attempt)`. Other workers naturally skip it until that time passes.
- **The DLQ** — when `attempts >= max_attempts`, the job is moved to `dead_letter_jobs` for human inspection. The original `jobs` row is deleted, so it can't accidentally retry.
- **Observability layer** — a few `psql` queries and a tiny `/metrics` endpoint you can wire to Prometheus later.

**Text diagram:**

```
[Producer] --INSERT--> jobs
                         |
                         v
[Worker A] --FOR UPDATE SKIP LOCKED--> execute --> success: DELETE
                         |                       |
                         |                       +-- failure: UPDATE attempts++, not_before
                         |
                         +-- attempts >= max --> move to dead_letter_jobs
```

No Redis, no RabbitMQ, no Kafka. Just Postgres doing what it's already good at: serializable transactions and row-level locking. That constraint is the point — it forces you to confront the real problems instead of outsourcing them to a broker.

## Building It Step by Step

The complete project is roughly 300 lines of Python and 60 lines of SQL. We'll build the schema first, then the worker, then the producer.

### Step 1: The Schema

Three tables. The `jobs` table is the work queue. `dead_letter_jobs` is where poison messages go. `job_runs` is a forensic log.

```sql
-- schema.sql
CREATE TABLE IF NOT EXISTS jobs (
    id              BIGSERIAL PRIMARY KEY,
    queue           TEXT        NOT NULL DEFAULT 'default',
    payload         JSONB       NOT NULL,
    idempotency_key TEXT        UNIQUE,
    attempts        INT         NOT NULL DEFAULT 0,
    max_attempts    INT         NOT NULL DEFAULT 5,
    not_before      TIMESTAMPTZ NOT NULL DEFAULT now(),
    locked_by       TEXT,
    locked_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_ready_idx
    ON jobs (queue, not_before)
    WHERE locked_by IS NULL;

CREATE TABLE IF NOT EXISTS dead_letter_jobs (
    id              BIGSERIAL PRIMARY KEY,
    original_job_id BIGINT      NOT NULL,
    queue           TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    last_error      TEXT        NOT NULL,
    attempts        INT         NOT NULL,
    died_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS job_runs (
    id          BIGSERIAL PRIMARY KEY,
    job_id      BIGINT      NOT NULL,
    worker_id   TEXT        NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    success     BOOLEAN,
    error       TEXT
);
```

Three things worth noting. The partial index on `locked_by IS NULL` keeps the polling query cheap as the table grows — this is the trick `pg_cron` and similar tools use. The `idempotency_key` column is a unique constraint so duplicate enqueues are silently dropped. And the `not_before` column is the entire retry mechanism: there is no separate scheduler process.

### Step 2: The Worker Loop

The worker is a poll loop. The key insight is the `FOR UPDATE SKIP LOCKED` clause, which lets multiple workers poll the same table without blocking each other — each transaction claims rows no other transaction has locked.

```python
# worker.py
import os, json, time, signal, random, socket
from datetime import datetime, timezone
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row

WORKER_ID = f"{socket.gethostname()}-{os.getpid()}"
DSN = os.environ.get("DATABASE_URL", "postgresql://localhost/jobs_demo")
POLL_INTERVAL = 0.5  # seconds when the queue is empty
LOCK_TIMEOUT_SECONDS = 30  # reclaim jobs from dead workers

def backoff_seconds(attempt: int) -> float:
    """Exponential backoff with full jitter, capped at 1 hour."""
    base = min(3600, 2 ** attempt)
    return random.uniform(0, base)

@contextmanager
def db():
    conn = psycopg.connect(DSN, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()

def claim_job(conn, queue: str) -> dict | None:
    """Atomically claim one ready job. Returns None if queue is empty."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
            UPDATE jobs
               SET locked_by  = %s,
                   locked_at  = now()
             WHERE id = (
                SELECT id
                  FROM jobs
                 WHERE queue      = %s
                   AND locked_by  IS NULL
                   AND not_before <= now()
              ORDER BY not_before
                   FOR UPDATE SKIP LOCKED
                 LIMIT 1
             )
            RETURNING *;
        """, (WORKER_ID, queue))
        return cur.fetchone()

def record_run_start(conn, job_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO job_runs (job_id, worker_id, started_at)
            VALUES (%s, %s, now());
        """, (job_id, WORKER_ID))

def mark_success(conn, job_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM jobs WHERE id = %s;", (job_id,))
        cur.execute("""
            UPDATE job_runs
               SET finished_at = now(), success = TRUE
             WHERE job_id = %s AND finished_at IS NULL;
        """, (job_id,))

def schedule_retry_or_dlq(conn, job: dict, error: str) -> None:
    """Either bump attempts and push not_before out, or move to DLQ."""
    new_attempts = job["attempts"] + 1
    with conn.cursor() as cur:
        if new_attempts >= job["max_attempts"]:
            cur.execute("""
                INSERT INTO dead_letter_jobs
                    (original_job_id, queue, payload, last_error, attempts)
                VALUES (%s, %s, %s, %s, %s);
            """, (job["id"], job["queue"],
                  json.dumps(job["payload"]), error, new_attempts))
            cur.execute("DELETE FROM jobs WHERE id = %s;", (job["id"],))
        else:
            delay = backoff_seconds(new_attempts)
            cur.execute("""
                UPDATE jobs
                   SET attempts   = %s,
                       not_before = now() + (%s || ' seconds')::interval,
                       locked_by  = NULL,
                       locked_at  = NULL
                 WHERE id = %s;
            """, (new_attempts, str(delay), job["id"]))
        cur.execute("""
            UPDATE job_runs
               SET finished_at = now(), success = FALSE, error = %s
             WHERE job_id = %s AND finished_at IS NULL;
        """, (error, job["id"]))

# --- job handlers ---
HANDLERS = {}

def handler(name):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco

@handler("send_email")
def send_email(payload: dict) -> None:
    # Replace with a real SMTP call in your project
    print(f"[{WORKER_ID}] sent email to {payload['to']}: {payload['subject']}")

@handler("resize_image")
def resize_image(payload: dict) -> None:
    # Idempotency: writing to a deterministic path keyed by payload
    print(f"[{WORKER_ID}] resized {payload['src']} -> {payload['dst']}")

def process_one(queue: str) -> bool:
    """Returns True if a job was processed, False if queue was empty."""
    with db() as conn:
        job = claim_job(conn, queue)
        if not job:
            conn.commit()
            return False
        record_run_start(conn, job["id"])
        conn.commit()

        try:
            handler = HANDLERS[job["payload"]["type"]]
            handler(job["payload"]["data"])
        except Exception as e:
            with db() as conn2:
                schedule_retry_or_dlq(conn2, job, repr(e))
                conn2.commit()
            return True

        with db() as conn2:
            mark_success(conn2, job["id"])
            conn2.commit()
        return True

def reclaim_orphans():
    """Reclaim jobs whose worker died holding a lock."""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE jobs
                   SET locked_by = NULL, locked_at = NULL
                 WHERE locked_at < now() - (%s || ' seconds')::interval;
            """, (str(LOCK_TIMEOUT_SECONDS),))
        conn.commit()

def main():
    queue = os.environ.get("QUEUE", "default")
    running = True
    def stop(*_): running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    while running:
        reclaim_orphans()
        worked = process_one(queue)
        if not worked:
            time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
```

The full-jitter formula `random.uniform(0, 2 ** attempt)` is taken straight from the [AWS Architecture Blog's "Exponential Backoff and Jitter"](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) post — it's the variant that smooths out thundering-herd effects the best.

### Step 3: The Producer

A producer is just a function that inserts a row. You'll typically call it from your web app or a cron tick.

```python
# producer.py
import json
import psycopg

DSN = "postgresql://localhost/jobs_demo"

def enqueue(job_type: str, data: dict, queue: str = "default",
            idempotency_key: str | None = None) -> int:
    with psycopg.connect(DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO jobs (queue, payload, idempotency_key)
                VALUES (%s, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id;
            """, (queue, json.dumps({"type": job_type, "data": data}),
                  idempotency_key))
            row = cur.fetchone()
            conn.commit()
            return row[0] if row else -1

if __name__ == "__main__":
    enqueue("send_email",
            {"to": "[email protected]", "subject": "Welcome!"},
            idempotency_key="welcome-12345")
    enqueue("resize_image",
            {"src": "s3://bucket/a.jpg", "dst": "s3://bucket/a-512.jpg"})
```

The `ON CONFLICT (idempotency_key) DO NOTHING` clause is what makes enqueueing safe to retry — a web request that times out and gets retried by the client won't enqueue twice.

## Running and Testing It

Bring up Postgres and the schema:

```bash
createdb jobs_demo
psql jobs_demo < schema.sql
```

Start one worker in one terminal:

```bash
python worker.py
```

Start another in a second terminal — note how they don't fight over jobs:

```bash
QUEUE=default python worker.py
```

Enqueue some jobs, including one that will fail repeatedly to exercise the retry path:

```python
# demo.py
from producer import enqueue
from worker import HANDLERS, handler

# Register a deliberately-failing handler
@handler("flaky")
def flaky(_):
    raise RuntimeError("simulated transient failure")

for i in range(3):
    enqueue("flaky", {"i": i}, idempotency_key=f"flaky-{i}")
enqueue("send_email", {"to": "[email protected]", "subject": "hi"})
```

Watch the `job_runs` table to see attempts accumulate, then check the DLQ:

```sql
-- jobs in flight
SELECT id, queue, attempts, not_before, locked_by FROM jobs ORDER BY id;

-- runs by job (the audit trail)
SELECT job_id, success, error, finished_at - started_at AS duration
  FROM job_runs ORDER BY started_at DESC LIMIT 10;

-- poison messages
SELECT * FROM dead_letter_jobs;
```

A clean test: enqueue a job that fails, wait long enough for it to hit `max_attempts`, and confirm it ends up in `dead_letter_jobs` with the `last_error` populated. That's your proof the DLQ works.

To prove `SKIP LOCKED` actually parallelizes: open four terminals, run a worker in each, enqueue 1000 jobs, and watch the `locked_by` column distribute across the four worker IDs roughly evenly.

## Extending It: Your Roadmap to Senior-Level

The version above is intentionally small. Each of the following upgrades turns it into something that wouldn't look out of place at a Series-B startup.

1. **Promote to a real client library with connection pooling.** Swap raw `psycopg.connect` for `psycopg_pool.ConnectionPool` and write a small `JobQueue` class exposing `enqueue()`, `enqueue_many()`, and `claim()`. It signals API-design maturity and prevents the connection-exhaustion footgun.
2. **Add structured observability.** Emit JSON logs with `worker_id`, `job_id`, `attempt`, and `duration_ms` on every state transition. Add a `/metrics` endpoint serving Prometheus counters: `jobs_processed_total{queue,result}`, `job_duration_seconds`, `dead_letter_total{queue}`. The presence of these on a CV reads as "this person ships to production."
3. **Add a graceful-shutdown protocol and a dedicated reaper.** On `SIGTERM`, the worker should finish its current job, release its lock heartbeat, and exit. A separate "reaper" process should reclaim jobs whose `locked_at` is older than the heartbeat interval — that's the pattern Postgres-backed tools like [River](https://github.com/riverqueue/river) and Sidekiq's `orphan` job use to survive crashed workers.
4. **Add a fair-queue / priority layer.** Right now `ORDER BY not_before` is FIFO. Add a `priority` column and a `delay_until` column, and write a small scheduler that promotes high-priority jobs first. Hiring managers love this one because it's the same problem Kafka, Sidekiq Pro, and SQS FIFO solve.
5. **Benchmark it honestly.** Use [`pgbench`](https://www.postgresql.org/docs/current/pgbench.html) or a small custom script to enqueue 100,000 jobs, run 8 workers, and report throughput, p50/p99 latency, and DB connection count. Publish the numbers in the repo's README. A project with a benchmark is a project that someone has actually thought about.
6. **Add a tiny web UI for the DLQ.** A FastAPI page that lists `dead_letter_jobs` with "Replay" and "Discard" buttons (replay = `INSERT INTO jobs ... SELECT ...` from the DLQ row). This is a complete, demonstrable product loop and looks great in a 5-minute screen-share.

## Key Takeaways

- `SELECT ... FOR UPDATE SKIP LOCKED` turns Postgres into a capable job queue without a separate broker — and the partial index on `locked_by IS NULL` keeps it fast as the table grows.
- A retry timer doesn't need a separate scheduler. A `not_before` column + a `WHERE not_before <= now()` filter in the polling query is the entire mechanism.
- Exponential backoff with full jitter (the [AWS variant](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/)) is the right default — it dampens thundering-herd effects when many jobs fail at once.
- A DLQ is a feature, not a luxury. It separates "transient failure" from "this message is poison and needs a human."
- Idempotency keys (`UNIQUE` constraint + `ON CONFLICT DO NOTHING`) are the only way to make producer retries safe.
- The "senior" upgrades — observability, graceful shutdown, reaper, fair queuing, benchmark, DLQ UI — are all small, all teachable in a weekend, and all visibly address the same concerns real production queues solve.

## Further Reading

- [PostgreSQL docs: `SELECT ... FOR UPDATE SKIP LOCKED`](https://www.postgresql.org/docs/current/sql-select.html#SQL-FOR-UPDATE-SHARE) — the lock semantics that make concurrent workers safe.
- [AWS Architecture Blog: Exponential Backoff and Jitter](https://aws.amazon.com/blogs/architecture/exponential-backoff-and-jitter/) — the canonical comparison of full-jitter vs. equal-jitter vs. decorrelated-jitter.
- [How Sidekiq Works (Mike Perham)](https://github.com/sidekiq/sidekiq/wiki/How-Sidekiq-Works) — the production reference implementation of a Redis-backed job queue; reading it side-by-side with your Postgres version is illuminating.
- [River for Postgres](https://github.com/riverqueue/river) and [Graphile Worker](https://github.com/graphile/worker) — two real-world Postgres-only job queues whose schemas and worker loops are worth studying.
- [pgwatch2: Postgres monitoring in practice](https://pgwatch.com/) — a reference for what good Postgres observability actually looks like.
- [Designing Data-Intensive Applications, chapter 7 "Transactions"](https://dataintensive.net/) (Martin Kleppmann) — the strongest single book chapter on the isolation-level reasoning your queue depends on.