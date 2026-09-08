---
title: "User Safety: A Hands-On Portfolio Project for Real‑World Engineering"
date: "2026-09-08T07:01:36.970"
draft: false
tags: ["security", "python", "fastapi", "postgres", "docker", "celery"]
description: "Build a production‑ready user‑safety service that validates input, detects malicious patterns, and logs audits – a concrete project that signals backend and security skills to hiring managers."
summary: "A step‑by‑step guide to building a user‑safety service with FastAPI, Postgres, Celery and Docker that you can run, test, and extend for senior‑level impact."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-08-user-safety-a-hands-on-portfolio-project-for-realworld-engineering.svg"
  alt: "User safety service architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — In this post we build a runnable user‑safety service with FastAPI, Postgres, and Celery that validates inbound payloads, flags suspicious patterns, and stores audit logs. The project is containerised, testable, and easy to extend with persistence, scaling and observability – perfect for a CV that shows you can ship real‑world backend systems.

Building a portfolio project that hiring managers can immediately evaluate is about more than “hello world.” It needs to demonstrate that you can design a small but complete system: API layer, data store, async processing, containerisation, and observability. *User Safety* does exactly that – a service that receives user‑submitted data, validates it against known malicious patterns, persists safe records, and logs every decision for audit or downstream analytics. The stack (FastAPI + SQLAlchemy + Postgres + Celery + Redis) is industry‑standard, so the code you write is directly transferable to real‑world back‑end roles (backend engineer, security engineer, DevOps, data platform).

## Why This Project Stands Out on a CV

- **Input‑validation & secure coding** – You’ll write Pydantic models with regex‑based sanitisation, a skill that shows up in every backend interview when discussing SQL injection or XSS prevention.  
- **Pattern‑detection logic** – Implementing simple YARA‑like or regex rules for common attacks (e.g., base64‑encoded shells, script tags) proves you can turn threat‑intelligence into runnable code.  
- **Async task processing** – Celery integration shows you understand background job queues, result back‑ends, and worker reliability – a must‑have for any production‑grade service.  
- **Persistence & schema design** – SQLAlchemy models, migrations with Alembic, and Postgres constraints demonstrate full‑stack data‑model thinking.  
- **Containerisation & CI‑ready** – A Dockerfile and docker‑compose file make the project runnable on any developer laptop or CI runner, signalling DevOps fluency.  
- **Observability scaffolding** – Structured logging, health checks, and metrics endpoints give you a talking point for monitoring and debugging interviews.

The roles this project signals for include **Backend Engineer**, **Security Engineer**, **Site Reliability Engineer (SRE)**, and **API Platform Engineer**. Hiring managers can clone the repo, run it, and immediately see a working API, a Postgres schema, and a Celery worker processing “unsafe” payloads – a concrete, end‑to‑end demo rather than a toy snippet.

## Architecture Overview

The system consists of six core components that fit together in a straightforward request‑response‑async pipeline:

- **Client API** – HTTP client (curl, browser, or any HTTP consumer) sends a JSON payload to `/v1/safety`.  
- **FastAPI Application** – Validates the payload with Pydantic, stores a “safe” record in Postgres, and publishes a message to a Redis broker if the payload is flagged as suspicious.  
- **Postgres DB** – Holds two tables: `users_safe` (approved records) and `safety_audit` (log of every inspection, including verdict and timestamps).  
- **Celery Worker** – Consumes the “suspicious” messages, runs pattern‑matching rules, writes an audit entry, and can optionally forward alerts to an external system (e.g., Slack).  
- **Redis** – Dual‑purpose: broker for Celery tasks and cache for rate‑limit counters.  
- **Docker / docker‑compose** – Spins up FastAPI, Postgres, Redis, and the Celery worker with a single `docker compose up --build`.

```
+----------------+      +----------------+      +-------------------+
|   Client API   | -->  |   FastAPI App  | -->  |     Postgres DB   |
+----------------+      +----------------+      +-------------------+
          |                 |  ^  ^  ^  ^  ^  ^  ^  ^  ^  ^  ^  ^  |
          |                 |  |  |  |  |  |  |  |  |  |
          |                 v  |  |  |  |  |  |  |  |
          |          +-----------+|  |  |  |  |  |  |  |
          |          |   Celery   ||  |  |  |  |  |  |
          |          |   Worker   ||  |  |  |  |  |  |
          +---------->+-----------+|  |  |  |  |  |  |
                       |         |  |  |  |  |  |
                       v         v  |  |  |  |  |  |
                +----------+   +--------+  |  |  |
                |   Redis  |   |   Sentry/||  |
                +----------+   +--------+  |  |
                                 |     |   |
                                 v     v   v
                           +--------+  Metrics / Health
                           | Prometheus |
                           +-----------+
```

This diagram highlights where data flows synchronously (API → DB) and asynchronously (API → Celery → DB). The separation of concerns makes each component replaceable – you could swap Postgres for CockroachDB, or Celery for RQ, without rewriting the API logic.

## Building It Step by Step

Below are numbered, self‑contained steps. Follow them in order; each step produces runnable code you can test immediately.

### Step 1 – Project skeleton & virtual environment

```bash
# Create and enter the project directory
mkdir user-safety && cd user-safety

# Python 3.11+ recommended
python3 -m venv .venv
source .venv/bin/activate

# Initialise a minimal git repo (optional but handy)
git init .
```

### Step 2 – Install dependencies

Create `requirements.txt` (you can edit later) and install:

```text
# requirements.txt
fastapi==0.111.0
uvicorn[standard]==0.29.0
sqlalchemy==2.0.32
alembic==1.13.0
pydantic==2.7.0
celery==5.4.0
redis==5.0.1
python-dotenv==1.0.0
pytest==8.2.2
pytest-asyncio==0.23.3
```

Install them:

```bash
pip install -r requirements.txt
```

### Step 3 – Define SQLAlchemy models & Alembic migrations

Create `app/models.py`:

```python
# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.sql import func
from .db import Base

class SafeRecord(Base):
    __tablename__ = "users_safe"

    id = Column(Integer, primary_key=True, index=True)
    payload = Column(Text, nullable=False)
    safe = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class AuditLog(Base):
    __tablename__ = "safety_audit"

    id = Column(Integer, primary_key=True, index=True)
    request_id = Column(String, nullable=False, index=True)
    payload_hash = Column(String, nullable=False)
    verdict = Column(String, nullable=False)   # "safe" | "suspicious"
    details = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

Initialise Alembic:

```bash
alembic init alembic
```

Edit `alembic.ini` to point at the `app/models.py` location if needed (default works because `target_metadata = Base.metadata` is set in `alembic/env.py`).

Create the first migration:

```bash
alembic revision --autogenerate -m "initial tables"
```

Alembic will generate `alembic/versions/<timestamp>_initial.py` containing `CreateTable` for `users_safe` and `safety_audit`. Run it:

```bash
alembic upgrade head
```

### Step 4 – FastAPI app, Pydantic schemas & validation middleware

Create `app/schemas.py`:

```python
# app/schemas.py
from pydantic import BaseModel, Field, validator
import re

# Whitelist of allowed characters for the free‑form payload field.
# This is a very simple example; real systems use richer rule engines.
SAFE_CHAR_RE = re.compile(r"^[-\w.\s]+$")

class SafetyPayload(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=64)
    payload: str = Field(..., min_length=1, max_length=4096)

    @validator("payload")
    def must_be_printable(cls, v):
        if not SAFE_CHAR_RE.match(v):
            raise ValueError("payload contains disallowed characters")
        return v
```

Now the main FastAPI application in `app/main.py`:

```python
# app/main.py
import uuid
import os
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse
from .db import SessionLocal, engine
from .models import SafeRecord, AuditLog
from .schemas import SafetyPayload
from .celery_tasks import flag_suspicious
from sqlalchemy.exc import IntegrityError

app = FastAPI(title="User Safety Service", version="0.1.0")

# Create DB tables on startup (for demo; use Alembic in production)
@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.post("/v1/safety", response_model=dict)
def create_safety(payload: SafetyPayload):
    db = SessionLocal()
    try:
        # Store a "safe" record immediately; the worker will later re‑evaluate.
        record = SafeRecord(payload=payload.payload, safe=True)
        db.add(record)
        db.commit()
        db.refresh(record)

        # Compute a simple hash for audit tracking.
        import hashlib
        ph = hashlib.sha256(payload.payload.encode()).hexdigest()

        # If the payload fails the whitelist (should not happen thanks to Pydantic),
        # we still publish a "suspicious" message for logging.
        flag_suspicious.delay(
            request_id=str(uuid.uuid4()),
            payload_hash=ph,
            user_id=payload.user_id,
            verdict="safe",   # we know it passed validation
        )

        return {
            "id": record.id,
            "user_id": payload.user_id,
            "safe": True,
            "message": "Payload accepted and queued for audit",
        }
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Duplicate payload for this user",
        )
    finally:
        db.close()
```

### Step 5 – Celery worker that performs deeper pattern checks

Create `app/celery_tasks.py`:

```python
# app/celery_tasks.py
import os
from celery import Celery
from .db import SessionLocal
from .models import AuditLog
from .schemas import SafetyPayload
import hashlib

# Celery broker = Redis running locally (see docker‑compose)
celery_app = Celery(
    "safety",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)


@celery_app.task(bind=True, max_retries=3)
def flag_suspicious(self, request_id, payload_hash, user_id, verdict):
    """Background task: run extra checks, write audit entry."""
    db = SessionLocal()
    try:
        # In a real system you would plug in YARA rules, regex, ML model calls, etc.
        # Here we just echo the verdict but could replace with a call to an
        # external threat‑intel service.
        detail = f"hash={payload_hash[:8]}… user={user_id}"
        entry = AuditLog(
            request_id=request_id,
            payload_hash=payload_hash,
            verdict=verdict,
            details=detail,
        )
        db.add(entry)
        db.commit()
    except Exception as exc:
        # Retry on transient DB errors
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    finally:
        db.close()
```

### Step 6 – Dockerise the whole stack

Create `Dockerfile` for the application:

```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (Redis & Postgres will be linked via docker‑compose)
RUN pip install --no-cache-dir fastapi uvicorn sqlalchemy alembic celery redis python-dotenv

# Copy project source
COPY . .

# Expose the FastAPI port
EXPOSE 8000

# Command: start uvicorn + celery worker (docker‑compose will also start Redis & Postgres)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000 & \
     celery -A app.celery_tasks worker --loglevel=info"]
```

Create `docker-compose.yml`:

```yaml
# docker-compose.yml
version: "3.9"

services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - CELERY_BROKER_URL=redis://redis:6379/0
      - CELERY_RESULT_BACKEND=redis://redis:6379/0
      - DATABASE_URL=postgresql://safety:safety@postgres:5432/safety
    depends_on:
      - redis
      - postgres
    volumes:
      - .:/app

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: safety
      POSTGRES_USER: safety
      POSTGRES_PASSWORD: safety
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
```

### Step 7 – Run and verify

```bash
docker compose up --build
```

You should see the API, Redis, and Postgres containers starting. Wait until the API logs show “Uvicorn running on http://0.0.0.0:8000”.

Test the endpoint:

```bash
curl -X POST http://localhost:8000/v1/safety \
  -H "Content-Type: application/json" \
  -d '{"user_id":"engineer01","payload":"hello world safe text"}'
```

Expected JSON response:

```json
{
  "id": 1,
  "user_id": "engineer01",
  "safe": true,
  "message": "Payload accepted and queued for audit"
}
```

Check the Postgres audit table:

```bash
psql -U safety -d safety -c "SELECT * FROM safety_audit;"
```

You should see a row with `verdict = "safe"` and the hash of the payload.

Terminate the containers (`Ctrl‑C`) when you’re done.

## Running and Testing It

### Local development (without Docker)

If you prefer to run everything on your laptop:

1. **Start Redis** – `redis-server` (or use Docker: `docker run -d -p 6379:6379 redis:7-alpine`).
2. **Start Postgres** – `createdb safety` and ensure the `safety` user has `CREATE` rights, then run `alembic upgrade head`.
3. **Run the FastAPI server** – `uvicorn app.main:app --host 0.0.0.0 --port 8000 &`.
4. **Launch the Celery worker** – `celery -A app.celery_tasks worker --loglevel=info`.
5. **Send a request** – as shown above.

### Automated tests

Add a `tests/` directory with `test_basic.py`:

```python
# tests/test_basic.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_valid_payload():
    resp = client.post("/v1/safety", json={"user_id": "u1", "payload": "safe content"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["safe"] is True
    assert "id" in data

def test_malicious_payload_rejected():
    # Payload with newlines and angle brackets should be rejected by the Pydantic validator.
    resp = client.post("/v1/safety", json={"user_id": "u2", "payload": "<script>alert(1)</script>"})
    assert resp.status_code == 422  # validation error
```

Run:

```bash
pytest tests/ -v
```

All tests should pass, confirming that input validation and basic CRUD work before you even involve the Celery worker.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Persist detection results in Elasticsearch** – enables full‑text searchable audit logs and fast retrieval of historical alerts. |
| 2 | **Horizontal scaling with multiple Celery workers behind a load balancer** – adds fault‑tolerance; if one worker crashes, others continue processing. |
| 3 | **OpenTelemetry instrumentation** – exports traces to Jaeger and metrics to Prometheus, giving you visibility into request latency, error rates, and worker throughput. |
| 4 | **Circuit‑breaker & retry policy (e.g., `pybreaker`)** – prevents cascading failures when the pattern‑matching service or external threat‑intel API is slow/unavailable. |
| 5 | **Load testing with Locust** – benchmark the API under realistic QPS, identify bottlenecks, and verify that response times stay < 100 ms for safe payloads. |
| 6 | **JWT‑based authentication & RBAC** – secures the endpoint so only authorized internal services or logged‑in users can submit safety checks, matching production security standards. |

Each upgrade moves the project from a “toy demo” to a production‑grade service that you can discuss in depth during interviews: scaling considerations, observability best‑practices, and resilience patterns are all concrete, measurable improvements.

## Key Takeaways

- **Real‑world stack** – FastAPI, SQLAlchemy, Postgres, Celery, and Redis are the same tools you’ll use in production back‑end roles.  
- **End‑to‑end flow** – From API validation → DB write → async audit → worker processing gives hiring managers a complete picture of your design ability.  
- **Container‑first** – Docker and docker‑compose make the project runnable on any machine, signalling DevOps competence.  
- **Testability** – Unit tests with `fastapi.testclient` and integration checks via `psql` demonstrate TDD habits.  
- **Extensible architecture** – The modular design (separate Celery task, pluggable pattern‑matching) lets you iterate from a simple regex rule to a full ML‑based detector without rewriting the API.  

## Further Reading

- **[FastAPI documentation](https://fastapi.tiangolo.com/)** – official guide, dependency injection, and async best practices.  
- **[SQLAlchemy 2.0 Core Tutorial](https://docs.sqlalchemy.org/en/20/tutorial.html)** – model design, migrations with Alembic, and core vs. ORM patterns.  
- **[Celery documentation – Getting Started](https://docs.celeryq.dev/en/stable/getting-started/index.html)** – broker configuration, worker lifecycle, and retry policies.  
- **[OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html)** – concrete rules for safe payload sanitisation.  
- **[OpenTelemetry Specification](https://opentelemetry.io/docs/specs/)** – how to instrument Python services for traces and metrics.  
- **[Docker Compose reference](https://docs.docker.com/compose/)** – service networking, volume management, and environment variable injection.  

These primary sources give you the exact building blocks you’ll need to evolve the *User Safety* service into a scalable, observable, and secure system ready for production deployment. Happy building!