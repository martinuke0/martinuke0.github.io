

---
title: "Build a Distributed Task Queue: A Portfolio Project for Systems Engineers"
date: "2026-09-12T15:01:49.783"
draft: false
tags: ["distributed-systems", "python", "task-queue", "systems-engineering", "portfolio", "backend"]
description: "Learn to build a distributed task queue from scratch with Python and Redis. This hands-on guide covers architecture, implementation, testing, and senior-level extensions."
summary: "A practical guide to building a distributed task queue that demonstrates real systems skills for hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-build-a-distributed-task-queue-a-portfolio-project-for-systems-engineers.svg"
  alt: "A distributed system architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Build a distributed task queue using Python, Redis, and Flask that demonstrates concurrency, decoupling, and fault tolerance. This project signals real systems skill to hiring managers and can be extended with persistence, scaling, and observability.

As a working or aspiring engineer, you need a portfolio project that does more than showcase CRUD operations. Hiring managers for backend and systems roles want evidence that you understand how software behaves under load, how components communicate across a network, and how to handle failure gracefully. A distributed task queue is a perfect vehicle for that: it touches message brokering, concurrency, persistence, and observability — all core systems engineering concepts.

In this guide, you'll build a complete, runnable distributed task queue from scratch. We'll use Python with Redis as the broker and PostgreSQL for durable storage, implement a Flask API to enqueue tasks, and create a horizontally scalable worker pool. By the end, you'll have a project that you can demo, extend, and discuss in interviews with real depth.

## Why This Project Stands Out on a CV

A task queue is a canonical distributed system primitive, and building one yourself signals several high-value skills:

- **Concurrency and parallelism:** You'll manage multiple worker threads or processes consuming from a shared queue, handling race conditions and synchronization.
- **Decoupling and async processing:** You'll demonstrate how to separate the producer (API) from the consumer (workers), a pattern used in everything from email sending to batch ETL jobs.
- **Fault tolerance:** Implementing retries, dead-letter queues, and timeouts shows you think about failure modes, not just happy paths.
- **Data persistence:** Using PostgreSQL for durable task storage and Redis for fast queue operations teaches when to use each type of store.
- **Horizontal scaling:** The architecture naturally supports adding more workers without code changes, which is a direct talking point for scalability discussions.

On a CV, this project can be described as "Designed and implemented a distributed task queue with Redis and PostgreSQL, supporting at-least-once delivery, retries, and horizontal worker scaling." That sentence immediately signals systems engineering experience and invites deeper discussion in interviews.

## Architecture Overview

The system consists of four main components:

1. **Task Producer (Flask API)** — A lightweight REST API that accepts task definitions and enqueues them into Redis. It is stateless and can be scaled horizontally behind a load balancer.
2. **Task Broker (Redis)** — Redis acts as the central message broker. It stores pending tasks in sorted sets (for priority) and lists (for FIFO queues), and tracks task state (pending, processing, completed, failed). Redis provides low-latency operations and atomicity for queue manipulations.
3. **Task Workers (Python threads/processes)** — Workers continuously poll Redis for new tasks. Each worker runs a loop that atomically pops a task, executes it, and updates its status. Multiple workers can run on the same or different machines.
4. **Task Storage (PostgreSQL)** — For durability, completed and failed tasks are persisted to PostgreSQL. This provides a historical record and supports retry logic by allowing workers to re-fetch failed tasks.

A simple text diagram of the flow:

```
[Producer API] ──(enqueue)──> [Redis Broker]
                                  │
                    ┌─────────────┴─────────────┐
                    │                           │
              [Worker 1]                 [Worker N]
                    │                           │
                    └─────────────┬─────────────┘
                                  │
                          (persist results)
                                  │
                                  ▼
                          [PostgreSQL]
```

This architecture is inspired by production systems like Celery, Sidekiq, and Amazon SQS, but we build the core logic ourselves to demonstrate understanding.

## Building It Step by Step

Let's implement the system. We'll use Python 3.10+, Redis, PostgreSQL, and the Flask web framework. First, install the required packages:

```bash
pip install flask redis psycopg2-binary pydantic
```

We'll also need a `requirements.txt` file:

```text
flask==2.3.2
redis==4.5.1
psycopg2-binary==2.9.7
pydantic==1.10.2
```

### Step 1: Project Structure

Create the following directory layout:

```
task_queue/
├── app.py
├── models.py
├── broker.py
├── worker.py
├── config.py
└── requirements.txt
```

### Step 2: Define the Task Model

In `models.py`, we define the Task data structure using Pydantic for validation:

```python
from pydantic import BaseModel
from typing import Optional, Dict, Any
from enum import Enum

class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class Task(BaseModel):
    id: str
    name: str
    payload: Dict[str, Any]
    status: TaskStatus = TaskStatus.PENDING
    retries: int = 0
    max_retries: int = 3
    created_at: str
    completed_at: Optional[str] = None
```

### Step 3: Implement the Redis Broker

The broker handles all interactions with Redis. In `broker.py`:

```python
import redis
import json
import uuid
from datetime import datetime
from models import Task, TaskStatus

class TaskBroker:
    def __init__(self, host='localhost', port=6379, db=0):
        self.r = redis.Redis(host=host, port=port, db=db, decode_responses=True)
        self.queue_key = "task_queue:pending"
        self.processing_key = "task_queue:processing"
        self.completed_key = "task_queue:completed"
        self.failed_key = "task_queue:failed"

    def enqueue(self, name: str, payload: dict) -> str:
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            name=name,
            payload=payload,
            created_at=datetime.utcnow().isoformat()
        )
        # Store task definition in Redis hash
        self.r.hset(f"task:{task_id}", mapping=task.dict())
        # Push task ID into the pending queue (LPUSH for FIFO)
        self.r.lpush(self.queue_key, task_id)
        return task_id

    def dequeue(self) -> Optional[Task]:
        # Atomically move one task from pending to processing
        task_id = self.r.rpoplpush(self.queue_key, self.processing_key)
        if not task_id:
            return None
        task_data = self.r.hgetall(f"task:{task_id}")
        if not task_data:
            return None
        task = Task(**task_data)
        task.status = TaskStatus.PROCESSING
        self.r.hset(f"task:{task_id}", mapping=task.dict())
        return task

    def mark_completed(self, task_id: str):
        self.r.hset(f"task:{task_id}", "status", TaskStatus.COMPLETED)
        self.r.hset(f"task:{task_id}", "completed_at", datetime.utcnow().isoformat())
        self.r.lrem(self.processing_key, 1, task_id)
        self.r.rpush(self.completed_key, task_id)

    def mark_failed(self, task_id: str, error: str):
        task_data = self.r.hgetall(f"task:{task_id}")
        if not task_data:
            return
        task = Task(**task_data)
        task.retries += 1
        task.status = TaskStatus.FAILED
        self.r.hset(f"task:{task_id}", mapping=task.dict())
        self.r.lrem(self.processing_key, 1, task_id)

        if task.retries < task.max_retries:
            # Requeue for retry
            self.r.lpush(self.queue_key, task_id)
        else:
            # Move to dead-letter queue
            self.r.rpush(self.failed_key, task_id)
```

### Step 4: Create the Flask Producer API

In `app.py`, we expose a simple API to enqueue tasks:

```python
from flask import Flask, request, jsonify
from broker import TaskBroker
import logging

app = Flask(__name__)
broker = TaskBroker()

@app.route('/tasks', methods=['POST'])
def create_task():
    data = request.json
    if not data or 'name' not in data or 'payload' not in data:
        return jsonify({"error": "Missing 'name' or 'payload'"}), 400

    task_id = broker.enqueue(name=data['name'], payload=data['payload'])
    return jsonify({"task_id": task_id, "status": "enqueued"}), 202

@app.route('/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    task_data = broker.r.hgetall(f"task:{task_id}")
    if not task_data:
        return jsonify({"error": "Task not found"}), 404
    return jsonify(task_data)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
```

### Step 5: Implement the Worker

Workers poll the broker and execute tasks. For demonstration, we'll define a simple task registry that maps task names to functions. In `worker.py`:

```python
import time
import logging
from broker import TaskBroker
from concurrent.futures import ThreadPoolExecutor

# Define your task functions here
def send_email(payload: dict):
    print(f"Sending email to {payload.get('to')} with subject: {payload.get('subject')}")
    time.sleep(0.5)  # Simulate network delay
    return {"sent": True}

def generate_report(payload: dict):
    print(f"Generating report for user {payload.get('user_id')}")
    time.sleep(1)
    return {"report_id": "12345"}

TASK_REGISTRY = {
    "send_email": send_email,
    "generate_report": generate_report,
}

def execute_task(task):
    func = TASK_REGISTRY.get(task.name)
    if not func:
        raise ValueError(f"Unknown task: {task.name}")
    try:
        result = func(task.payload)
        return result
    except Exception as e:
        logging.error(f"Task {task.id} failed: {e}")
        raise

def worker_loop(broker, worker_id):
    logging.info(f"Worker {worker_id} started")
    while True:
        task = broker.dequeue()
        if not task:
            time.sleep(0.1)  # Avoid busy-waiting
            continue
        logging.info(f"Worker {worker_id} executing task {task.id}")
        try:
            execute_task(task)
            broker.mark_completed(task.id)
            logging.info(f"Task {task.id} completed")
        except Exception as e:
            broker.mark_failed(task.id, str(e))
            logging.warning(f"Task {task.id} failed, marked for retry or dead-letter")

if __name__ == '__main__':
    import sys
    num_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 4
    broker = TaskBroker()
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        for i in range(num_workers):
            executor.submit(worker_loop, broker, i)
```

### Step 6: Add PostgreSQL Persistence (Optional but Recommended)

For durable storage, we can extend the broker to also persist task status to PostgreSQL. This step is more advanced but critical for production. We'll add a `persistence` module that uses `psycopg2` to insert/update tasks in a `tasks` table.

```python
# persistence.py
import psycopg2
from models import Task

class TaskPersistence:
    def __init__(self, dsn):
        self.conn = psycopg2.connect(dsn)
        self.conn.autocommit = True

    def save_task(self, task: Task):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO tasks (id, name, payload, status, retries, max_retries, created_at, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET status = EXCLUDED.status, completed_at = EXCLUDED.completed_at
            """, (task.id, task.name, task.payload, task.status, task.retries, task.max_retries, task.created_at, task.completed_at))
```

You would then modify the broker to call `persistence.save_task(task)` whenever a task's state changes.

## Running and Testing It

To test the system locally, follow these steps:

1. **Start Redis** (if not running):
   ```bash
   redis-server
   ```

2. **Start the Flask API**:
   ```bash
   python app.py
   ```

3. **Start workers** (in separate terminals):
   ```bash
   python worker.py 4
   ```

4. **Enqueue a task** using curl:
   ```bash
   curl -X POST http://localhost:5000/tasks \
     -H "Content-Type: application/json" \
     -d '{"name": "send_email", "payload": {"to": "test@example.com", "subject": "Welcome"}}'
   ```

5. **Check task status**:
   ```bash
   curl http://localhost:5000/tasks/<task_id>
   ```

You should see the worker print the email sending message, and the task status will transition to `completed`. To test failure handling, add a task that raises an exception and observe the retry logic.

For automated testing, you can write a simple pytest script that enqueues tasks and verifies they are processed within a timeout.

## Extending It: Your Roadmap to Senior-Level

This basic implementation is a starting point. Here are concrete upgrades that transform it into a production-flavored system, each with a one-line reason it matters:

1. **Add a PostgreSQL-backed persistence layer** — Ensures tasks survive broker restarts and provides a durable audit trail, which is essential for any real system.
2. **Implement queue partitioning and multiple worker pools** — Allows horizontal scaling by distributing load across independent queues (e.g., high-priority vs. low-priority), preventing head-of-line blocking.
3. **Introduce Prometheus metrics and a Grafana dashboard** — Makes the system observable: you can track queue depth, processing latency, and error rates in real time, a must-have for production SRE work.
4. **Add a dead-letter queue with exponential backoff** — Prevents poison messages from blocking the queue and gives failed tasks a chance to recover after transient outages.
5. **Build a benchmark suite with Locust** — Simulates real traffic to measure throughput and identify bottlenecks, demonstrating performance engineering skills.
6. **Support scheduled and recurring tasks** — Adds cron-like scheduling using Redis sorted sets, expanding the system from a simple queue to a full-featured job scheduler.

## Key Takeaways

- Building a distributed task queue from scratch teaches concurrency, message brokering, and fault tolerance — all core systems engineering skills.
- The project is immediately recognizable to hiring managers as a signal of real-world distributed systems experience.
- Using Redis for fast queue operations and PostgreSQL for durable storage demonstrates an understanding of when to use each technology.
- The architecture is naturally extensible, allowing you to add persistence, scaling, observability, and scheduling as you grow.
- This project can be discussed in interviews with concrete examples of race conditions, retries, and horizontal scaling.

## Further Reading

To deepen your understanding and evolve this project, study these primary sources:

- **Redis Documentation** — The authoritative guide to Redis data structures and commands used in the broker: [https://redis.io/docs/](https://redis.io/docs/)
- **PostgreSQL Documentation** — For durable storage patterns and SQL optimizations: [https://www.postgresql.org/docs/](https://www.postgresql.org/docs/)
- **Celery Documentation** — A production-grade task queue that inspired many design choices: [https://docs.celeryq.dev/](https://docs.celeryq.dev/)
- **Prometheus Official Docs** — Learn how to instrument your workers with metrics: [https://prometheus.io/docs/](https://prometheus.io/docs/)
- **The Art of Command Line** — Not directly related, but a great resource for building CLI tools that interact with your queue: [https://learnxinyminutes.com/docs/bash/](https://learnxinyminutes.com/docs/bash/)
- **Designing Data-Intensive Applications** by Martin Kleppman — The canonical book on distributed systems design, covering replication, partitioning, and consistency: [https://dataintensive.net/](https://dataintensive.net/)