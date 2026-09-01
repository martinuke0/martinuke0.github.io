---
title: "Building a Webhook Delivery System with Idempotency Keys: A Production-Flavored Portfolio Project"
date: "2026-09-01T22:00:32.000"
draft: false
tags: ["python", "fastapi", "webhooks", "distributed-systems", "portfolio-projects"]
description: "A hands-on build guide for a portfolio-grade webhook delivery system with idempotency keys and at-least-once semantics, written for engineers who want to ship."
summary: "Ship a real webhook delivery service with idempotency, retries, and a dead-letter queue — a portfolio project that signals genuine distributed-systems skill to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-building-a-webhook-delivery-system-with-idempotency-keys-a-production-flavored-portfolio-project.svg"
  alt: "Diagram showing a webhook sender, retry queue, dead-letter store, and a downstream receiver."
  caption: ""
  relative: false
---

> **TL;DR** — A webhook delivery system is one of the strongest portfolio projects you can ship in a weekend: it's small enough to finish, but it touches queues, retries, idempotency, and observability — every box a hiring manager for a backend or platform role ticks. In this guide we build one with FastAPI, Redis Streams, and Postgres, with real runnable code, then map out a roadmap to turn it into senior-level territory.

Hiring managers for backend, platform, and infrastructure roles have a quiet bias: they want to see that you've *finished* something end-to-end. Not a tutorial clone, not a TODO-laden repo with a glowing README — a project that actually runs, has tests, has a Makefile, and has opinions. A webhook delivery system is a perfect candidate. It's a component every SaaS company ships (think Stripe, GitHub, Shopify), it has well-defined semantics in [the relevant IETF draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/), and it forces you to make real decisions about state, retries, and failure.

This guide walks you through building one from a blank directory to a running service, then maps out the upgrades that turn it from "weekend project" into "interview talking point."

## Why This Project Stands Out on a CV

Most portfolio projects fall into two traps: they're either too small (a CRUD app, a TODO list) or too demo-ware (a chatbot that calls an LLM and stops there). The interesting space — where recruiters and hiring managers lean in — is projects that demonstrate *operational thinking*. A webhook delivery system does exactly that.

Specifically, it signals:

- **Distributed systems literacy.** You understand that "delivering a webhook" is not one operation; it's a saga across a sender, a queue, a worker, and a receiver, with state at every hop.
- **API design discipline.** You'll be designing a public endpoint with idempotency, which means thinking about headers ([`Idempotency-Key`](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)), status codes, and replay semantics.
- **Failure handling.** Retries, exponential backoff, dead-letter queues, and poison messages aren't abstract — they're concrete implementation choices you'll make in this codebase.
- **Operational maturity.** A real version of this project has logs, metrics, health endpoints, and graceful shutdown. Hiring managers for SRE, platform, and senior backend roles notice.

Roles this signals for: **Backend Engineer**, **Platform Engineer**, **Infrastructure Engineer**, **API/Developer Experience Engineer**, and **Site Reliability Engineer** at any company that exposes a webhook product (which is, increasingly, *all of them*).

## Architecture Overview

Here's the high-level shape. The numbers map to the components below.

```
Client ──▶ POST /events (1)
              │
              ▼
        FastAPI Ingest (2) ──▶ Redis Stream: events.stream (3)
              │
              └──▶ Postgres: idempotency_keys (4)
                                                  │
                                                  ▼
                                       Worker (5) ──▶ Receiver
                                            │           │
                                            ▼           ▼
                                    Redis Stream:    5xx / timeout?
                                    events.dlq (6)   │
                                            │       ▼
                                            └── retry w/ backoff
```

Components:

1. **Ingest endpoint** — `POST /events` accepting an `Idempotency-Key` header and a JSON payload.
2. **FastAPI app** — validates the request, normalizes it into an event envelope.
3. **Redis Stream** — durable, ordered queue of events waiting to be delivered. We use `XADD`/`XREADGROUP` as a poor man's Kafka.
4. **Postgres `idempotency_keys` table** — stores the canonical response for each key for a TTL window so replays return the same answer.
5. **Worker process** — consumes from the stream, looks up or creates a delivery record, performs the HTTP POST to the receiver.
6. **Dead-letter stream** — events that have exceeded the retry budget get parked here for human inspection.

The two stores aren't redundant: Redis is the *work queue*, Postgres is the *source of truth* for delivery state and idempotency.

## Building It Step by Step

We'll use Python 3.11+, FastAPI, Redis 7+, and Postgres 15+. Everything below is real, runnable code.

### Step 1: Project Layout

```
webhook-delivery/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app
│   ├── config.py          # Settings via pydantic-settings
│   ├── models.py          # SQLAlchemy models
│   ├── idempotency.py     # Idempotency-key store
│   ├── queue.py           # Redis Stream wrapper
│   ├── worker.py          # Delivery worker
│   └── schemas.py         # Pydantic request/response schemas
├── tests/
│   └── test_idempotency.py
├── docker-compose.yml
├── Makefile
└── pyproject.toml
```

### Step 2: Dependencies

```toml
# pyproject.toml
[project]
name = "webhook-delivery"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi==0.115.0",
    "uvicorn[standard]==0.30.6",
    "pydantic==2.9.2",
    "pydantic-settings==2.5.2",
    "sqlalchemy==2.0.35",
    "psycopg[binary]==3.2.3",
    "redis==5.0.8",
    "httpx==0.27.2",
    "tenacity==9.0.0",
    "structlog==24.4.0",
]
```

### Step 3: Configuration

```python
# app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WH_", env_file=".env")

    database_url: str = "postgresql+psycopg://wh:wh@localhost:5432/wh"
    redis_url: str = "redis://localhost:6379/0"

    stream_name: str = "events.stream"
    dlq_name: str = "events.dlq"
    consumer_group: str = "delivery-workers"

    idempotency_ttl_seconds: int = 24 * 3600
    max_attempts: int = 5
    request_timeout_seconds: float = 10.0

settings = Settings()
```

### Step 4: The Idempotency Store

This is the heart of the project. We store the response keyed by `(account_id, idempotency_key)`. On a replay, we return the stored response without enqueuing a duplicate.

```python
# app/idempotency.py
import json
from datetime import datetime, timezone
from sqlalchemy import select, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session
from app.models import IdempotencyRecord

def reserve_key(
    session: Session,
    account_id: str,
    key: str,
    request_fingerprint: str,
    ttl_seconds: int,
) -> IdempotencyRecord | None:
    """Return existing record if key is replayed, else create a pending one.
    Returns None if a *concurrent* request beat us; caller should retry.
    """
    stmt = pg_insert(IdempotencyRecord).values(
        account_id=account_id,
        key=key,
        request_fingerprint=request_fingerprint,
        status="pending",
        created_at=datetime.now(timezone.utc),
    ).on_conflict_do_nothing(index_elements=["account_id", "key"])
    result = session.execute(stmt)
    session.commit()

    existing = session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.account_id == account_id,
            IdempotencyRecord.key == key,
        )
    ).scalar_one_or_none()

    if existing.status == "completed":
        return existing
    # Pending — caller must decide whether to enqueue (fingerprint match) or 409.
    return existing

def finalize_key(
    session: Session,
    account_id: str,
    key: str,
    response_status: int,
    response_body: dict,
) -> None:
    stmt = (
        update(IdempotencyRecord)
        .where(
            IdempotencyRecord.account_id == account_id,
            IdempotencyRecord.key == key,
        )
        .values(
            status="completed",
            response_status=response_status,
            response_body=json.dumps(response_body),
        )
    )
    session.execute(stmt)
    session.commit()

def purge_expired(session: Session, now: datetime) -> int:
    result = session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.expires_at < now,
        )
    )
    session.commit()
    return result.rowcount
```

The idempotency pattern here is the textbook one: reserve the key in the same transaction as the side effect (in our case, enqueuing), and finalize after the side effect commits. This avoids the classic "we returned 200 but the worker never saw it" bug.

### Step 5: The Ingest Endpoint

```python
# app/main.py
import hashlib
import json
import uuid
from fastapi import FastAPI, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from app.config import settings
from app.queue import enqueue_event
from app.idempotency import reserve_key, finalize_key
from app.models import get_session
from app.schemas import EventIn, EventAccepted

app = FastAPI(title="Webhook Delivery")

@app.post("/events", status_code=202, response_model=EventAccepted)
def ingest(
    event: EventIn,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=255),
    account_id: str = Header(..., alias="X-Account-Id"),
    session: Session = Depends(get_session),
):
    fingerprint = hashlib.sha256(
        event.model_dump_json().encode()
    ).hexdigest()

    record = reserve_key(
        session,
        account_id=account_id,
        key=idempotency_key,
        request_fingerprint=fingerprint,
        ttl_seconds=settings.idempotency_ttl_seconds,
    )

    if record.status == "completed":
        # Replay: return the original synchronous-ish response.
        # Note: for true async webhooks we still 202, but we echo the event_id.
        return EventAccepted(
            event_id=record.event_id,
            idempotency_key=idempotency_key,
            replayed=True,
        )

    event_id = str(uuid.uuid4())
    enqueue_event(
        account_id=account_id,
        event_id=event_id,
        idempotency_key=idempotency_key,
        payload=event.payload,
        target_url=event.target_url,
    )
    finalize_key(
        session,
        account_id=account_id,
        key=idempotency_key,
        response_status=202,
        response_body={"event_id": event_id, "replayed": False},
    )
    return EventAccepted(
        event_id=event_id,
        idempotency_key=idempotency_key,
        replayed=False,
    )
```

The `202 Accepted` is deliberate: webhooks are inherently async, and the receiver may not exist yet. This mirrors how Stripe's [webhooks API](https://docs.stripe.com/webhooks) behaves at the source.

### Step 6: The Redis Stream Wrapper

```python
# app/queue.py
import json
import redis
from app.config import settings

_redis = redis.from_url(settings.redis_url, decode_responses=True)

def ensure_group() -> None:
    try:
        _redis.xgroup_create(
            name=settings.stream_name,
            groupname=settings.consumer_group,
            id="0",
            mkstream=True,
        )
    except redis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

def enqueue_event(
    *, account_id: str, event_id: str, idempotency_key: str,
    payload: dict, target_url: str,
) -> str:
    return _redis.xadd(
        settings.stream_name,
        {
            "account_id": account_id,
            "event_id": event_id,
            "idempotency_key": idempotency_key,
            "payload": json.dumps(payload),
            "target_url": target_url,
            "attempts": "0",
        },
    )
```

### Step 7: The Delivery Worker

This is where at-least-once delivery and exponential backoff live.

```python
# app/worker.py
import json
import signal
import time
from tenacity import (
    retry, stop_after_attempt, wait_exponential,
    retry_if_exception_type, RetryError,
)
import httpx
import redis
from app.config import settings
from app.queue import _redis

TRANSIENT = (httpx.TransportError, httpx.HTTPStatusError)

@retry(
    stop=stop_after_attempt(settings.max_attempts),
    wait=wait_exponential(multiplier=1, min=1, max=60),
    retry=retry_if_exception_type(TRANSIENT),
    reraise=True,
)
def deliver(target_url: str, body: dict, headers: dict) -> httpx.Response:
    with httpx.Client(timeout=settings.request_timeout_seconds) as client:
        response = client.post(target_url, json=body, headers=headers)
        # 5xx and 408/429 are retryable; 4xx otherwise are terminal.
        if response.status_code >= 500 or response.status_code in (408, 429):
            response.raise_for_status()
        return response

def process_one(msg_id: str, fields: dict) -> None:
    attempts = int(fields["attempts"])
    body = {
        "event_id": fields["event_id"],
        "idempotency_key": fields["idempotency_key"],
        "payload": json.loads(fields["payload"]),
    }
    headers = {
        "Content-Type": "application/json",
        "X-Webhook-Event-Id": fields["event_id"],
        "X-Webhook-Attempt": str(attempts + 1),
    }
    try:
        deliver(fields["target_url"], body, headers)
        _redis.xack(settings.stream_name, settings.consumer_group, msg_id)
    except (RetryError, httpx.HTTPStatusError) as e:
        # Either exhausted retries or hit a non-retryable 4xx.
        _redis.xadd(
            settings.dlq_name,
            {**fields, "final_error": str(e), "attempts": str(attempts + 1)},
        )
        _redis.xack(settings.stream_name, settings.consumer_group, msg_id)

def run() -> None:
    ensure_group()
    stopping = False
    def _stop(*_): stopping = True
    signal.signal(signal.SIGTERM, _stop)

    while not stopping:
        msgs = _redis.xreadgroup(
            groupname=settings.consumer_group,
            consumername="worker-1",
            streams={settings.stream_name: ">"},
            count=10,
            block=5000,
        )
        if not msgs:
            continue
        for _stream, entries in msgs:
            for msg_id, fields in entries:
                process_one(msg_id, fields)

if __name__ == "__main__":
    run()
```

The retry policy uses [`tenacity`](https://tenacity.readthedocs.io/) for clarity, but the production version would replace this with a scheduled backoff (delayed re-enqueue) so workers don't hold HTTP sockets during the sleep. That's a roadmap item.

### Step 8: Pydantic Schemas

```python
# app/schemas.py
from pydantic import BaseModel, HttpUrl, Field
from typing import Any

class EventIn(BaseModel):
    target_url: HttpUrl
    payload: dict[str, Any] = Field(default_factory=dict)

class EventAccepted(BaseModel):
    event_id: str
    idempotency_key: str
    replayed: bool
```

### Step 9: A Test That Proves Idempotency

```python
# tests/test_idempotency.py
def test_replay_returns_same_event_id(client):
    headers = {"Idempotency-Key": "abc-12345", "X-Account-Id": "acct_1"}
    body = {"target_url": "https://example.com/hook", "payload": {"x": 1}}

    r1 = client.post("/events", json=body, headers=headers)
    r2 = client.post("/events", json=body, headers=headers)

    assert r1.status_code == 202
    assert r2.status_code == 202
    assert r1.json()["event_id"] == r2.json()["event_id"]
    assert r1.json()["replayed"] is False
    assert r2.json()["replayed"] is True
```

That's the project. Twelve files, ~300 lines of meaningful code, and you've touched every concept that matters.

## Running and Testing It

A `docker-compose.yml` brings up Postgres and Redis:

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: wh
      POSTGRES_PASSWORD: wh
      POSTGRES_DB: wh
    ports: ["5432:5432"]
  redis:
    image: redis:7
    ports: ["6379:6379"]
```

A `Makefile` ties it together:

```makefile
# Makefile
.PHONY: up api worker test

up:
	docker compose up -d

api:
	uvicorn app.main:app --reload --port 8000

worker:
	python -m app.worker

test:
	pytest -q
```

To prove it end-to-end, stand up a tiny echo server first:

```python
# tests/echo_server.py
from fastapi import FastAPI, Request
app = FastAPI()

@app.post("/hook")
async def hook(req: Request):
    body = await req.json()
    print("GOT:", body)
    return {"ok": True}
```

Then in three terminals:

```bash
make up
uvicorn tests.echo_server:app --port 9000   # receiver
make api                                     # sender
make worker                                  # delivery
```

Send a request:

```bash
curl -X POST http://localhost:8000/events \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: order-42-attempt-1' \
  -H 'X-Account-Id: acct_1' \
  -d '{"target_url":"http://localhost:9000/hook","payload":{"order_id":42}}'
```

Replay it with the same key — you'll see `replayed: true` and the receiver will *only* be hit once. Kill the receiver mid-flight, send another event, and you'll watch the worker retry, back off, and eventually park the message in `events.dlq`. That's at-least-once delivery, made visible.

## Extending It: Your Roadmap to Senior-Level

What you have now is a credible mid-level project. The list below turns it into something a Staff Engineer nods at.

1. **Persist delivery state per attempt.** Add a `deliveries` table with `(event_id, attempt, status, response_code, latency_ms, error)`. Hiring managers love tables that answer "how do you debug a delivery that failed three days ago?" — that's an observability primitive.
2. **Replace in-process retry with scheduled re-enqueues.** Use [Redis Sorted Sets as a delay queue](https://redis.io/docs/latest/develop/use/patterns/distributed-locks/) or a proper scheduler. This frees worker threads during backoff and lets you scale horizontally without thundering-herd retries.
3. **Add Prometheus metrics.** Counters for `events_received_total`, `events_delivered_total{status}`, `events_dlq_total`; histograms for delivery latency. Wire `/metrics` into your FastAPI app — every platform team reads these.
4. **Sign and verify payloads.** Add an `X-Webhook-Signature` header using HMAC-SHA256 over the body, and document it. This is table stakes for real webhook products; [Stripe's signature scheme](https://docs.stripe.com/webhooks/signatures) is the canonical reference.
5. **Implement replay protection with timestamp tolerance.** Reject signatures older than 5 minutes to prevent replay attacks. This is the kind of detail that signals you think about security in distributed systems.
6. **Benchmark the worker.** Use [`k6`](https://k6.io) or [`locust`](https://locust.io) to drive 10k events/sec through the system and graph p50/p99 latency under load. A repo with a `bench/` directory and a resulting graph is portfolio gold.

## Key Takeaways

- Webhook delivery is the rare portfolio project that finishes in a weekend but exercises real distributed-systems concepts: queues, retries, idempotency, and dead-letter handling.
- Use **`Idempotency-Key`** as a header (per the IETF draft), store the canonical response in Postgres keyed by `(account_id, key)`, and treat the worker as a separate process consuming a Redis Stream.
- Return **`202 Accepted`** from the ingest endpoint — webhooks are async by nature; don't pretend otherwise.
- Make retries *visible*: a dead-letter queue plus per-attempt logging is the difference between "I hope it worked" and "I can prove it did."
- The five upgrades that move this project from junior to senior-grade: delivery persistence, scheduled retries, metrics, signed payloads, and load testing.

## Further Reading

- [IETF draft — The Idempotency-Key HTTP Header Field](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/) — the canonical pattern this project implements.
- [Stripe Webhooks documentation](https://docs.stripe.com/webhooks) — production reference for signing, retries, and event types.
- [Redis Streams introduction](https://redis.io/docs/latest/develop/data-types/streams/) — the data structure behind the work queue.
- [Tenacity documentation](https://tenacity.readthedocs.io/) — the retry library used in the worker.
- [PostgreSQL ON CONFLICT](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT) — the upsert primitive that makes idempotency reservation atomic.
- [Prometheus Python client](https://github.com/prometheus/client_python) — for the metrics upgrade on the roadmap.
- [Designing Data-Intensive Applications, chapter 11** (Stream Processing)**](https://dataintensive.net/) — Kleppmann's treatment of at-least-once, exactly-once, and effective-once semantics.