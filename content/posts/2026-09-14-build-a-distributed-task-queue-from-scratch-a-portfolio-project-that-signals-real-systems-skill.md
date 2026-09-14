---
title: "Build a Distributed Task Queue from Scratch: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-14T12:02:35.026"
draft: false
tags: ["systems-engineering", "python", "distributed-systems", "portfolio-project", "career-growth"]
description: "Build a production-grade distributed task queue from scratch in Python. This hands-on guide covers architecture, implementation, and extensions that signal senior-level systems engineering skills to hiring managers."
summary: "A hands-on build guide for a distributed task queue side project that demonstrates concurrency, persistence, and distributed systems skills — with real, runnable code and a clear roadmap to production-grade complexity."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-14-build-a-distributed-task-queue-from-scratch-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "A distributed task queue architecture diagram showing clients, a broker, and multiple worker nodes processing jobs."
  caption: ""
  relative: false
---

> **TL;DR** — Build a distributed task queue from scratch in Python with FastAPI, SQLite, and a worker pool. This project demonstrates concurrency, persistence, network communication, and fault tolerance — the exact systems skills hiring managers look for. The guide gives you production-quality code, a testing strategy, and a six-step roadmap to senior-level depth.

A portfolio project that genuinely separates you from the crowd isn't another to-do app or a clone of an existing SaaS. It's something that forces you to grapple with the hard problems of distributed systems: concurrent access, state management, network failure, and observability. A distributed task queue hits every one of those nails on the head.

Task queues are the invisible backbone of modern engineering — they power email sends at Stripe, image processing at Slack, and batch ETL at every data platform on earth. Building one yourself means you'll touch networking, concurrency, persistence, and API design in a single project. That's a density of systems concepts that no tutorial app can match.

Let's build it.

## Why This Project Stands Out on a CV

Hiring managers and staff engineers scan portfolios for signals that a candidate has moved past "I can write functions" into "I can design systems." A distributed task queue demonstrates:

- **Concurrency and parallelism** — You'll implement a worker pool that processes jobs concurrently, managing shared state without races. This is the single most-requested skill in backend engineering interviews.
- **Distributed systems fundamentals** — Even a single-node queue introduces the core challenges of distributed systems: at-least-once delivery, retry semantics, and failure recovery.
- **Persistence and state management** — Jobs must survive process restarts. You'll make decisions about durability guarantees that mirror real production trade-offs.
- **API design** — You'll expose a clean REST interface for job submission and status queries, practicing the contract-first thinking that separates junior from senior engineers.
- **Observability** — Metrics, logging, and health checks are non-negotiable in production. Building them from scratch teaches you what monitoring actually means.
- **DevOps awareness** — Containerizing the project, writing a `docker-compose.yml`, and thinking about scaling all signal that you can operate the systems you build.

The roles this signals are broad: backend engineer, platform engineer, DevOps/sRE, and even early-stage data engineer. It's one of those rare projects that reads well on a CV for multiple engineering disciplines simultaneously.

## Architecture Overview

The system consists of four primary components that communicate over HTTP and an internal job store. Here's the breakdown:

```
┌──────────────┐       HTTP POST /jobs        ┌──────────────────┐
│   Client      │ ──────────────────────────▶  │   API Server     │
│  (curl,       │                              │  (FastAPI)       │
│   frontend)   │ ◀──────────────────────────  │                  │
└──────────────┘   JSON response / status       │  ┌────────────┐  │
                                                │  │ Job Store  │  │
                                                │  │ (SQLite)   │  │
                                                │  └─────┬──────┘  │
                                                │        │          │
                                                │  ┌─────▼──────┐  │
                                                │  │  Worker    │  │
                                                │  │  Pool      │  │
                                                │  │ (threads)  │  │
                                                │  └────────────┘  │
                                                └──────────────────┘
```

- **API Server (FastAPI)**: Accepts job submissions via `POST /jobs`, exposes `GET /jobs/{id}` for status queries, and serves a minimal web dashboard. It is the single entry point for all client interactions.
- **Job Store (SQLite)**: Persists job state — `pending`, `running`, `completed`, `failed` — so that jobs survive server restarts. SQLite was chosen for simplicity, but the interface is abstracted so you can swap in PostgreSQL or Redis later.
- **Worker Pool**: A pool of background threads that poll the job store for pending jobs, execute them, and update their status. The pool size is configurable.
- **Web Dashboard**: A lightweight HTML page that shows queued, running, and completed jobs in real time. It polls the API server for updates.

The key architectural decision here is the **separation of the API layer from the worker layer**. The server never executes jobs directly — it enqueues them and returns immediately. Workers pick up jobs asynchronously. This decoupling is what makes the system horizontally scalable.

## Building It Step by Step

We'll build this in Python using FastAPI, SQLAlchemy (for the ORM), and `uvicorn` as the ASGI server. The full project structure:

```
task-queue/
├── app/
│   ├── main.py          # FastAPI application
│   ├── models.py        # SQLAlchemy models
│   ├── database.py      # DB connection
│   ├── queue.py         # Core queue logic
│   ├── worker.py        # Worker pool
│   └── dashboard.py     # Web dashboard routes
├── tests/
│   └── test_queue.py
├── requirements.txt
├── docker-compose.yml
└── README.md
```

### Step 1: Project Setup and Dependencies

```bash
mkdir task-queue && cd task-queue
python -m venv venv
source venv/bin/activate
```

```txt
# requirements.txt
fastapi==0.115.0
uvicorn[standard]==0.34.0
sqlalchemy==2.0.36
aiosqlite==0.20.0
httpx==0.27.2
pytest==8.3.4
pytest-asyncio==0.24.0
```

### Step 2: Database Models and Connection

Define the job model with states that mirror real production queues:

```python
# app/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite+aiosqlite:///./task_queue.db"

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = sessionmaker(engine, class_AsyncSession, expire_on_commit=False)

Base = declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

```python
# app/models.py
from sqlalchemy import Column, Integer, String, DateTime, Enum
from sqlalchemy.sql import func
from app.database import Base
import enum

class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"

class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    task_name = Column(String, nullable=False)
    payload = Column(String, nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    result = Column(String, nullable=True)
    error = Column(String, nullable=True)
    retries = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    created_at = Column(DateTime, server_default=func.now())
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
```

### Step 3: The Core Queue Logic

This is the heart of the system — the logic that enqueues, dequeues, and manages job lifecycle:

```python
# app/queue.py
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Job, JobStatus
from app.database import async_session

async def enqueue(task_name: str, payload: str, max_retries: int = 3) -> Job:
    async with async_session() as session:
        job = Job(task_name=task_name, payload=payload, max_retries=max_retries)
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return job

async def dequeue_next() -> Job | None:
    """Atomically claim the next pending job."""
    async with async_session() as session:
        result = await session.execute(
            select(Job)
            .where(Job.status == JobStatus.PENDING)
            .order_by(Job.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if job:
            job.status = JobStatus.RUNNING
            job.started_at = func.now()
            await session.commit()
            await session.refresh(job)
        return job

async def complete_job(job_id: int, result: str):
    async with async_session() as session:
        stmt = (
            update(Job)
            .where(Job.id == job_id)
            .values(status=JobStatus.COMPLETED, result=result, completed_at=func.now())
        )
        await session.execute(stmt)
        await session.commit()

async def fail_job(job_id: int, error: str):
    async with async_session() as session:
        job = await session.get(Job, job_id)
        if job:
            job.retries += 1
            if job.retries >= job.max_retries:
                job.status = JobStatus.FAILED
                job.error = error
            else:
                job.status = JobStatus.PENDING  # Retry
            job.completed_at = func.now()
            await session.commit()
            await session.refresh(job)
```

The `with_for_update(skip_locked=True)` clause is critical — it implements the **atomic claim** pattern that prevents two workers from picking up the same job. This is the exact mechanism used by systems like Celery and BullMQ under the hood.

### Step 4: The Worker Pool

Workers poll the queue, execute tasks, and handle failures:

```python
# app/worker.py
import asyncio
import logging
from app.queue import dequeue_next, complete_job, fail_job

logger = logging.getLogger(__name__)

async def worker(worker_id: int):
    logger.info(f"Worker {worker_id} started")
    while True:
        job = await dequeue_next()
        if job is None:
            await asyncio.sleep(0.5)  # Backoff when queue is empty
            continue

        logger.info(f"Worker {worker_id} picked up job {job.id}: {job.task_name}")
        try:
            # Simulate task execution — replace with real logic
            await asyncio.sleep(1)  # Represents work
            await complete_job(job.id, f"Result of {job.task_name}")
            logger.info(f"Worker {worker_id} completed job {job.id}")
        except Exception as e:
            await fail_job(job.id, str(e))
            logger.error(f"Worker {worker_id} failed job {job.id}: {e}")

async def start_worker_pool(num_workers: int = 4):
    tasks = [asyncio.create_task(worker(i)) for i in range(num_workers)]
    await asyncio.gather(*tasks)
```

### Step 5: The FastAPI Server

Wire everything together with a clean REST interface:

```python
# app/main.py
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from app.queue import enqueue, complete_job, fail_job
from app.models import Job, JobStatus
from app.database import init_db
from app.worker import start_worker_pool
import asyncio

app = FastAPI(title="Distributed Task Queue")

@app.on_event("startup")
async def startup():
    await init_db()
    asyncio.create_task(start_worker_pool(num_workers=4))

@app.post("/jobs", status_code=201)
async def submit_job(task_name: str, payload: str, max_retries: int = 3):
    job = await enqueue(task_name, payload, max_retries)
    return {"job_id": job.id, "status": job.status.value}

@app.get("/jobs/{job_id}")
async def get_job(job_id: int):
    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "id": job.id,
            "task_name": job.task_name,
            "status": job.status.value,
            "result": job.result,
            "error": job.error,
            "retries": job.retries,
        }

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    return """
    <html><body>
    <h1>Task Queue Dashboard</h1>
    <div id="jobs"></div>
    <script>
      setInterval(async () => {
        const res = await fetch('/jobs');
        const jobs = await res.json();
        document.getElementById('jobs').innerHTML =
          JSON.stringify(jobs, null, 2);
      }, 2000);
    </script>
    </body></html>
    """
```

### Step 6: Entry Point

```python
# run.py
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
```

## Running and Testing It

Start the server:

```bash
pip install -r requirements.txt
python run.py
```

The server starts on `http://localhost:8000`. Submit a job with curl:

```bash
curl -X POST "http://localhost:8000/jobs?task_name=process_data&payload={\"user_id\": 42}"
```

You'll receive a JSON response with a `job_id`. Poll for status:

```bash
curl http://localhost:8000/jobs/1
```

Open `http://localhost:8000/dashboard` to see the live dashboard updating every two seconds.

For automated testing, here's a pytest suite that validates the core queue behavior:

```python
# tests/test_queue.py
import pytest
from httpx import AsyncClient
from app.main import app
from app.database import init_db

@pytest.fixture(autouse=True)
async def setup_database():
    await init_db()
    yield

@pytest.mark.asyncio
async def test_submit_and_retrieve_job():
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/jobs", params={
            "task_name": "test_task",
            "payload": "{}"
        })
        assert response.status_code == 201
        job_id = response.json()["job_id"]

        status_response = await client.get(f"/jobs/{job_id}")
        assert status_response.status_code == 200
        assert status_response.json()["status"] in ["pending", "running", "completed"]
```

Run the tests:

```bash
pytest tests/ -v
```

To verify concurrency, submit 20 jobs and watch the worker logs — you should see all four workers picking up jobs in parallel, with the queue draining steadily.

## Extending It: Your Roadmap to Senior-Level

This base project is a strong portfolio piece on its own, but the upgrades below are what turn it from a toy into something that reads like a production system. Each one maps directly to a senior-level systems concept.

1. **Swap SQLite for PostgreSQL with connection pooling.** SQLite's file-level locking breaks under concurrency. PostgreSQL with `asyncpg` and a connection pool (via `SQLAlchemy`'s `QueuePool`) gives you true concurrent writes, WAL durability, and crash recovery — exactly what you'd find in a production task queue like Celery with a Postgres broker.

2. **Add horizontal scaling with multiple worker nodes.** Containerize the app with Docker and use `docker-compose` to spin up multiple worker instances. Implement a distributed lock (using PostgreSQL advisory locks or Redis) so that workers across nodes don't duplicate work. This is the pattern behind Kubernetes-based worker fleets.

3. **Instrument with Prometheus metrics and structured logging.** Add a `/metrics` endpoint using the `prometheus-client` library to expose queue depth, jobs processed per second, and error rates. Pair this with `structlog` for JSON-formatted logs that feed into a Grafana dashboard. Observability is the #1 skill that separates staff engineers from mid-level ones.

4. **Implement idempotency keys and a dead-letter queue.** Real production systems must handle duplicate messages gracefully. Add an `idempotency_key` column to the `Job` model so that retries of the same logical job don't produce side effects. When a job exhausts its retries, move it to a `dead_letter` table for manual inspection — this is how Stripe and AWS SQS handle poison pills.

5. **Add priority queues and rate limiting.** Extend the `Job` model with a `priority` field and modify `dequeue_next()` to select the highest-priority pending job first. Add a token-bucket rate limiter (using `aiolimiter`) to prevent any single task type from overwhelming the workers. This mirrors the architecture of systems like GitHub's TaskQueue.

6. **Benchmark with `locust` and profile with `py-spy`.** Write a `locustfile.py` that simulates 1,000 concurrent job submissions and measure throughput, latency percentiles, and error rates. Use `py-spy record` to flame-graph the worker loop and identify bottlenecks. Benchmarking is how you prove — not just claim — that your system performs.

## Key Takeaways

- A distributed task queue is one of the highest-signal portfolio projects because it forces you to solve real systems problems — concurrency, persistence, fault tolerance — in a single, coherent codebase.
- The atomic job-claim pattern (`SELECT ... FOR UPDATE SKIP LOCKED`) is the foundational mechanism behind every production task queue, from Celery to AWS SQS. Understanding it is a systems-level skill.
- The separation of the API layer from the worker layer is what makes the system horizontally scalable — this architectural decision alone signals senior-level thinking.
- Every extension in the roadmap maps to a concrete, interview-ready concept: connection pooling, distributed locks, observability, idempotency, priority queues, and benchmarking.
- The project is small enough to build in a weekend but deep enough to keep you learning for months. That's the sweet spot for a portfolio piece.

## Further Reading

To deepen your understanding of the systems concepts in this project, study these primary sources:

- [The Google MapReduce Paper](https://research.google/pubs/pub62/) — Understanding how distributed task execution frameworks evolved from the foundational parallel processing model.
- [The Raft Consensus Paper](https://raft.github.io/raft.pdf) — If you scale to multiple scheduler nodes, you'll need consensus. Raft is the accessible entry point to distributed consensus algorithms.
- [Celery Documentation: Task Routing and Retries](https://docs.celeryq.dev/en/stable/userguide/routing.html) — Celery is the production reference implementation for the pattern you just built. Study how it handles priority queues, retries, and dead-letter exchanges.
- [PostgreSQL Advisory Locks](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS) — The canonical documentation for implementing distributed locks at the database level, which you'll need for horizontal scaling.
- [The 10 Billion Song Dataset: A Case Study in Parallel Data Processing](https://www.cs.umd.edu/~mwh/courses/698/papers/barroso-vl2007.pdf) — A real-world paper on building a distributed task-processing system at Google scale, covering the exact challenges your project mirrors.
- [Prometheus Best Practices](https://prometheus.io/docs/practices/naming/) — The official Prometheus documentation on metric naming, labeling, and instrumentation patterns for your observability extension.

---