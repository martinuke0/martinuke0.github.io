---
title: "Build a Durable Postgres Job Queue: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-02T10:00:46.775"
draft: false
tags: ["postgres", "python", "job-queue", "system-design", "backend"]
description: "A hands-on build guide for a durable Postgres job queue with retries, exponential backoff, and a dead-letter queue — the kind of CV project hiring managers actually notice."
summary: "Build a production-flavored job queue on Postgres with SKIP LOCKED, exponential backoff, and a dead-letter queue. A substantive portfolio project that demonstrates real backend systems skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-build-a-durable-postgres-job-queue-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Architecture diagram of a Postgres-backed durable job queue"
  caption: ""
  relative: false
---

> **TL;DR** — A job queue is one of the highest signal-to-effort projects you can put on a CV: it exercises concurrency, failure handling, and schema design in a way hiring managers immediately recognize. This guide walks through building a durable queue on Postgres using `SELECT ... FOR UPDATE SKIP LOCKED`, with retries, exponential backoff, and a dead-letter table — all runnable locally in under 200 lines of Python.

Hiring managers skim portfolios. They don't read every README. The projects that land interviews are the ones where the reader can tell in five seconds that you understand how real systems work — concurrency, failure, observability, durability. A job queue is one of those projects. It's small enough to build in a weekend, but it forces you to make every decision that distinguishes a toy from a production system.

This is a hands-on build guide. You'll write real code, run it against a real Postgres instance, watch it retry, and watch it dead-letter. By the end, you'll have a project you can talk about fluently in interviews.

## Why This Project Stands Out on a CV

A job queue touches a disproportionate number of skills that backend interviews probe. When a hiring manager sees "Postgres job queue with retries and DLQ" on your CV, here's what they infer:

- **You understand concurrency primitives.** Picking `SELECT ... FOR UPDATE SKIP LOCKED` over naive `SELECT` and showing it in your code is a quiet flex. It signals you've read the [Postgres locking docs](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS) and understand why naive queues race.
- **You know failure modes aren't optional.** Retries with exponential backoff plus a dead-letter queue is exactly the pattern shipped in [Sidekiq](https://github.com/sidekiq/sidekiq), [BullMQ](https://docs.bullmq.io/), and [Celery](https://docs.celeryq.dev). Demonstrating you know this vocabulary matters.
- **You think in trade-offs.** You chose Postgres over Redis Streams or RabbitMQ — and you can articulate why. For solo projects and small-to-mid scale systems, Postgres-as-queue is defensible: one less operational dependency, transactional enqueue, and the queue rides along in your existing backups.
- **You can ship something end-to-end.** The project has a schema, a worker, a producer, a CLI, and a test harness. That's a system, not a snippet.

The roles this signals for: **backend engineer**, **platform engineer**, **infrastructure engineer**, **SRE**, and **data platform engineer** (where the queue is used to schedule ETL jobs). It's not a front-end or ML project — and that's the point. It's a depth signal.

## Architecture Overview

The system has four moving parts:

- **Producer** — accepts jobs (HTTP, CLI, or library call) and writes them to the `jobs` table inside a transaction.
- **`jobs` table** — the queue. Columns: `id`, `payload` (JSONB), `run_at` (next eligible time), `attempts`, `max_attempts`, `status` (`queued`, `running`, `dead`), and `last_error`.
- **Worker loop** — claims due jobs, executes them, marks them done, or schedules a retry with backoff. Claims use `SELECT ... FOR UPDATE SKIP LOCKED` so multiple workers never grab the same row.
- **`dead_letter_jobs` table** — jobs that exhausted retries. Keeps the full payload and the final error so they can be inspected, replayed, or alerted on.

Text diagram:

```
                    +------------+
   enqueue()  ----> |   jobs     | <---- claim()   +-----------+
   (producer)       | (FOR UPDATE|  (SKIP LOCKED)  |  Worker   |
                    | SKIP LOCKED)                 |  loop     |
                    +------------+                 +-----------+
                          |                              |
                          | run_at <= now()              | success
                          v                              v
                    claim() returns              mark done -> DELETE
                    one row at a time
                          |
                          | failure
                          v
                  backoff: run_at = now() + base*2^attempts + jitter
                          |
                          | attempts >= max_attempts
                          v
                  +------------------+
                  | dead_letter_jobs |
                  +------------------+
```

Two design choices worth calling out:

1. **We never `DELETE` a job on success unless we want a full audit trail.** Most production queues keep successful jobs for a retention window. For this project, deleting on success keeps the table small.
2. **Backoff is stored on the row (`run_at` advances), not computed in worker memory.** This means a worker can die, restart, and pick up exactly where it left off. Durability comes for free from Postgres.

## Building It Step by Step

The full project fits in about 200 lines of Python. We'll use a minimal stack: Postgres 14+, Python 3.10+, and the `psycopg` driver. No ORM, no Celery, no Redis. The point is to see the mechanism.

### Step 1: Schema

Create a database and run:

```sql
CREATE TABLE jobs (
    id            BIGSERIAL PRIMARY KEY,
    payload       JSONB        NOT NULL,
    run_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    attempts      INT          NOT NULL DEFAULT 0,
    max_attempts  INT          NOT NULL DEFAULT 5,
    status        TEXT         NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'dead')),
    last_error    TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX jobs_due_idx
    ON jobs (run_at)
    WHERE status = 'queued';

CREATE TABLE dead_letter_jobs (
    id            BIGSERIAL PRIMARY KEY,
    original_id   BIGINT       NOT NULL,
    payload       JSONB        NOT NULL,
    attempts      INT          NOT NULL,
    last_error    TEXT,
    died_at       TIMESTAMPTZ  NOT NULL DEFAULT now()
);
```

The partial index on `status = 'queued'` is the kind of detail that makes a CV reviewer pause and nod. It keeps the working set tiny even if `jobs` grows to millions of historical rows.

### Step 2: The producer

The producer inserts a job and commits. That's it — the durable part is the transaction.

```python
import json
import psycopg

def enqueue(conn, payload: dict, max_attempts: int = 5):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (payload, max_attempts)
            VALUES (%s, %s)
            RETURNING id
            """,
            (json.dumps(payload), max_attempts),
        )
        job_id = cur.fetchone()[0]
    conn.commit()
    return job_id
```

Why a transaction? Because if the `INSERT` succeeds and the client crashes before the response is sent, the job is still queued. The unit of durability is the commit.

### Step 3: The claim — the heart of the system

This is the line that does the actual work of being a queue:

```python
def claim(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'running',
                attempts = attempts + 1
            WHERE id = (
                SELECT id
                FROM jobs
                WHERE status = 'queued'
                  AND run_at <= now()
                ORDER BY run_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, payload, attempts, max_attempts
            """,
        )
        row = cur.fetchone()
    conn.commit()
    return row
```

Three things to understand here:

- **`FOR UPDATE SKIP LOCKED`** is the magic. When worker A claims row 17, worker B's `SELECT` skips it and goes to row 18. No blocking, no double-processing. This is the exact mechanism used by [Sidekiq's `queues` table](https://github.com/sidekiq/sidekiq/wiki/Ent-Periodic-Jobs) and is the canonical Postgres queue pattern, as described in the [CockroachDB post on `SKIP LOCKED`](https://www.cockroachlabs.com/docs/v23.1/select-for-update#skip-locked-clause).
- **We `UPDATE` and `RETURN` in one statement.** The `UPDATE ... WHERE id = (SELECT ... FOR UPDATE SKIP LOCKED)` pattern atomically picks a row and marks it as `running`. No race window between "select" and "update."
- **We increment `attempts` here, not in the worker.** That way, even if the worker crashes after claiming but before processing, the retry counter still advanced, and we don't infinitely retry a poison message.

### Step 4: The handler registry

Jobs need handlers. A tiny registry keeps the worker generic.

```python
HANDLERS = {}

def register(name):
    def deco(fn):
        HANDLERS[name] = fn
        return fn
    return deco

@register("send_email")
def send_email(payload):
    print(f"would send email to {payload['to']}")
    if payload.get("fail"):
        raise RuntimeError("simulated failure")

@register("resize_image")
def resize_image(payload):
    print(f"would resize {payload['src']} -> {payload['dst']}")
```

### Step 5: The worker loop with retries and backoff

```python
import time
import random

BASE_BACKOFF = 2.0  # seconds

def backoff_delay(attempts: int) -> float:
    return BASE_BACKOFF * (2 ** (attempts - 1)) + random.uniform(0, 1)

def process(conn, row):
    job_id, payload_json, attempts, max_attempts = row
    payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
    handler = HANDLERS[payload["task"]]
    try:
        handler(payload)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        if attempts >= max_attempts:
            dead_letter(conn, job_id, payload, attempts, str(e))
        else:
            retry(conn, job_id, attempts, str(e))

def retry(conn, job_id, attempts, error):
    delay = backoff_delay(attempts)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs
            SET status = 'queued',
                run_at = now() + (%s * interval '1 second'),
                last_error = %s
            WHERE id = %s
            """,
            (delay, error, job_id),
        )
    conn.commit()

def dead_letter(conn, job_id, payload, attempts, error):
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO dead_letter_jobs
                (original_id, payload, attempts, last_error)
            VALUES (%s, %s, %s, %s)
            """,
            (job_id, json.dumps(payload), attempts, error),
        )
        cur.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
    conn.commit()

def worker_loop(dsn: str):
    conn = psycopg.connect(dsn, autocommit=False)
    while True:
        row = claim(conn)
        if row is None:
            time.sleep(0.5)
            continue
        process(conn, row)
```

Two details that signal seniority:

- **`random.uniform(0, 1)` jitter** on backoff. Without jitter, all retrying jobs wake up at the same instant and stampede the downstream. This is the same reasoning [AWS documents for retry behavior](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/).
- **`conn.rollback()` before retry/dead-letter.** If the handler raised, the transaction is poisoned. Rollback, then start a fresh statement.

### Step 6: A CLI to drive it

```python
import argparse

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["enqueue", "work", "dlq"])
    p.add_argument("--task", default="send_email")
    p.add_argument("--fail", action="store_true")
    p.add_argument("--dsn", default="postgresql://localhost/queue_demo")
    args = p.parse_args()

    conn = psycopg.connect(args.dsn)

    if args.cmd == "enqueue":
        payload = {"task": args.task, "to": "user@example.com", "fail": args.fail}
        print(f"enqueued id={enqueue(conn, payload)}")
    elif args.cmd == "work":
        conn.close()
        worker_loop(args.dsn)
    elif args.cmd == "dlq":
        with conn.cursor() as cur:
            cur.execute("SELECT id, original_id, attempts, last_error FROM dead_letter_jobs")
            for row in cur.fetchall():
                print(row)
```

That's the whole system. Schema, producer, claim, handler, worker, CLI. About 200 lines.

## Running and Testing It

```bash
createdb queue_demo
psql queue_demo < schema.sql
pip install psycopg
```

Enqueue a job that will fail every time:

```bash
python queue.py enqueue --task send_email --fail
```

Start a worker in another terminal:

```bash
python queue.py work
```

You'll see the job attempted five times with growing delays (~2s, ~4s, ~8s, ~16s, plus jitter), then vanish from `jobs`. Check the DLQ:

```bash
python queue.py dlq
# (1, 1, 5, 'simulated failure')
```

The interesting test: run **two workers in parallel** (`python queue.py work` in two terminals), enqueue 100 jobs, and watch them split roughly evenly. That's `SKIP LOCKED` working. If you replaced it with `FOR UPDATE` without `SKIP LOCKED`, worker B would block on every row worker A had touched, and throughput would collapse.

A quick test that proves the retry path:

```python
def test_retry_then_success():
    state = {"calls": 0}
    @register("flaky")
    def flaky(payload):
        state["calls"] += 1
        if state["calls"] < 3:
            raise RuntimeError("not yet")
    # enqueue, run worker, assert state["calls"] == 3 and row deleted
```

For a real portfolio, write a `tests/` directory that covers: claim under contention, backoff timing, dead-lettering, idempotency (a job whose handler is called twice shouldn't double-charge a card), and graceful worker shutdown.

## Extending It: Your Roadmap to Senior-Level

A working queue gets you the interview. These upgrades get you the offer. Each one is a small, well-scoped PR — and each one teaches a concept a senior engineer is expected to know.

- **Use a dedicated connection and a `LISTEN`/`NOTIFY` channel so workers wake instantly when a job is enqueued, instead of polling.** *Replaces the `time.sleep(0.5)` poll with push-based wakeup, the same pattern Postgres uses internally for triggers and used by [pg_listen](https://www.postgresql.org/docs/current/sql-notify.html).*
- **Add a Prometheus `/metrics` endpoint exporting `jobs_enqueued_total`, `jobs_processed_total`, `jobs_in_dlq`, and a histogram of processing latency.** *Observability is the difference between "the queue works" and "I know why the queue is slow at 3am," and it's exactly what tools like [Prometheus](https://prometheus.io/) exist to provide.*
- **Run multiple worker processes behind a supervisor, then add a `worker_id` column to `jobs` and a heartbeat (`updated_at` updated every N seconds). A separate reaper marks workers whose heartbeat is stale and re-queues their jobs.** *This is the [Sidekiq reliable fetch](https://github.com/sidekiq/sidekiq/wiki/Reliability) model and is how you survive `kill -9`.*
- **Add jittered exponential backoff with a hard cap (e.g. 5 minutes) and a per-job `backoff_strategy` enum (`fixed`, `linear`, `exponential`).** *Backoff tuning is one of the most common production queue bugs — too aggressive and you DDoS yourself, too slow and your DLQ fills.*
- **Benchmark it: write a `benchmark.py` that enqueues 10,000 jobs and reports throughput at 1, 2, 4, 8 workers. Plot it with `matplotlib`.** *A graph in your README titled "Throughput vs. worker count" reads like a benchmark from a database vendor's blog post.*
- **Add idempotency keys: a unique index on `(task_name, idempotency_key)` so a retried `charge_card` call never runs twice.** *Idempotency is the unsexy feature that distinguishes a queue from a payment system, and it's documented in detail in the [Stripe API docs](https://stripe.com/docs/api/idempotent_requests).*
- **Add at-least-once delivery semantics with a `started_at` and a per-job lease timeout. If a worker dies mid-job, the row is released after the lease expires.** *This is the contract [Amazon SQS](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html) gives you, and it lets you reason about correctness under crash.*

Pick three. Each one is a paragraph in your interview story.

## Key Takeaways

- **Postgres is a perfectly good queue for most solo and small-team systems.** The trick is `FOR UPDATE SKIP LOCKED`, which gives you safe concurrency without a separate broker.
- **Durability comes from transactions, not from the worker process.** Enqueue and claim are the only places that need transactional care; the handler itself should be idempotent.
- **Retries need backoff, and backoff needs jitter.** Without jitter, your retry storm becomes a self-DDoS.
- **A dead-letter table is not optional in production.** It's the only place you can look when a job is failing and the on-call engineer needs answers.
- **The CV value is the decisions, not the lines of code.** A reviewer should be able to see `SKIP LOCKED`, the partial index, the heartbeat pattern, and the metrics endpoint and immediately know you understand the domain.

## Further Reading

- [PostgreSQL docs — Explicit Locking (`FOR UPDATE`, `SKIP LOCKED`)](https://www.postgresql.org/docs/current/explicit-locking.html) — the primary source for the locking primitive that makes the whole system work.
- [CockroachDB — `SELECT FOR UPDATE` and `SKIP LOCKED`](https://www.cockroachlabs.com/docs/v23.1/select-for-update#skip-locked-clause) — a clear, worked explanation of how `SKIP LOCKED` behaves under contention, useful for interviews.
- [Sidekiq — Best Practices for Reliable Jobs](https://github.com/sidekiq/sidekiq/wiki/Best-Practices) — the production reference for many of the patterns above (reliable fetch, idempotency, error handling).
- [AWS Builders' Library — Timeouts, Retries, and Backoff with Jitter](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/) — the canonical writeup on why exponential backoff alone is insufficient and how jitter fixes thundering herds.
- [Amazon SQS Visibility Timeout](https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html) — the at-least-once delivery contract that should inform how you implement the lease-timeout upgrade.
- [Stripe API — Idempotent Requests](https://stripe.com/docs/api/idempotent_requests) — the cleanest production writeup of idempotency keys, directly applicable to the idempotency upgrade.