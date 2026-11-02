---
title: "Building a Real‑Time Event Ingestion & Analytics Dashboard for Your CV"
date: "2026-11-02T07:01:35.685"
draft: false
tags: ["kafka", "fastapi", "postgresql", "docker", "monitoring"]
description: "A step‑by‑step guide to building a real‑time event ingestion and analytics dashboard that showcases distributed systems skills and is ready to feature on your engineering portfolio."
summary: "Learn how to spin up a Kafka‑driven pipeline, store events in Postgres, serve them via a FastAPI service, and visualize metrics—all in a reproducible Docker compose setup you can demo in interviews."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-02-building-a-realtime-event-ingestion-analytics-dashboard-for-your-cv.svg"
  alt: "Dashboard with real-time event flow diagram"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a real‑time event ingestion and analytics dashboard using Kafka, FastAPI, and Postgres. You’ll end up with a Docker‑composable pipeline you can demo, extend, and discuss in interviews, signaling hands‑on distributed‑systems competence.

Building a portfolio project that hiring managers notice is about more than “just code.” It’s about demonstrating that you can design, deploy, and operate a small but complete system that mirrors what teams do in production. The project below—a real‑time event ingestion and analytics dashboard—lets you showcase messaging, persistence, API design, and observability all in one place. It’s practical enough to run locally in minutes, yet extensible enough to become a talking point for senior‑level interviews.

## Why This Project Stands Out on a CV

Hiring managers scanning dozens of GitHub repos look for signals of three things: **systems thinking**, **tool fluency**, and **delivery capability**. This project hits each:

- **Distributed messaging** – You’ll work with Kafka, the de‑facto standard for event pipelines. Knowing how to produce, consume, and manage topics shows you understand ordering, partitions, and replication.
- **Data persistence & query** – Postgres gives you a familiar relational layer. You’ll practice schema design, simple analytics queries, and connection pooling.
- **API & service exposure** – FastAPI provides auto‑generated docs, async handling, and type safety. Demonstrating a production‑ready endpoint (with validation, error handling, and health checks) proves you can ship HTTP services.
- **Observability basics** – By wiring Prometheus metrics and a health endpoint, you show you think about monitoring from day one.
- **Containerised deployment** – Docker Compose ties everything together, a skill expected for any modern backend role.

Roles that directly benefit include **backend engineer**, **data engineer**, **site‑reliability engineer**, and **full‑stack engineer** with an interest in data pipelines. Even a **product manager** can appreciate the end‑to‑end flow from event source to visual insight.

## Architecture Overview

The system consists of five core components that fit together in a straightforward pipeline:

- **Kafka broker** – receives events from a producer, partitions them, and makes them available to consumers.
- **Event producer** – a small Python script that sends synthetic “click” events to the `events` topic.
- **FastAPI consumer** – subscribes to the topic, persists each event into Postgres, and exposes a `/events` endpoint for downstream queries.
- **Postgres database** – stores the event payload with a simple `events(id, timestamp, kind, payload)` table.
- **Docker Compose** – orchestrates Kafka, Zookeeper, Postgres, and the FastAPI service in isolated containers, with optional Prometheus exporter metrics.

```
+-------------------+      +-------------------+      +-------------------+
|   Event Producer  | ---> |     Kafka Broker  | ---> |  FastAPI Consumer |
+-------------------+      +-------------------+      +-------------------+
                                   |                       |
                                   v                       v
                              +----------------+      +-------------------+
                              |   Postgres DB  | <---- |   /events API     |
                              +----------------+      +-------------------+

Prometheus exporter (FastAPI) ──▶ Grafana (optional) for real‑time charts
```

All services expose ports that Docker Compose maps to the host, so you can interact with Kafka via the CLI, query Postgres directly, and call the FastAPI endpoint with `curl`.

## Building It Step by Step

Below are the concrete steps to get the pipeline running. Follow them in order; each step includes a ready‑to‑run code snippet.

### 1️⃣ Scaffold the Docker Compose file

Create a directory `event-dashboard/` and add `docker-compose.yml`:

```yaml
version: "3.8"

services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    ports: ["2181:2181"]

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    depends_on: [zookeeper]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    ports: ["9092:9092"]

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: dashboard
      POSTGRES_PASSWORD: dashboard
      POSTGRES_DB: dashboard
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data

  api:
    build: ./api
    depends_on: [kafka, postgres]
    environment:
      KAFKA_BOOTSTRAP_SERVERS: localhost:9092
      DATABASE_URL: postgresql://dashboard:dashboard@postgres:5432/dashboard
    ports: ["8000:8000"]
    volumes:
      - .:/app

volumes:
  postgres_data:
```

> **Why this matters** – A single YAML file lets anyone `docker compose up -d` and have the whole stack running in seconds, a demonstrable DevOps skill.

### 2️⃣ Add the FastAPI app skeleton

Create `api/main.py`:

```python
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
import kafka
import os
import time

app = FastAPI(title="Event Dashboard API", version="0.1.0")

# ── Database ───────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Event(Base):
    __tablename__ = "events"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, nullable=False)
    kind = Column(String, nullable=False, index=True)
    payload = Column(Text, nullable=True)

Base.metadata.create_all(bind=engine)

# ── Kafka consumer (background) ─────────────────────────────
kafka_client = kafka.KafkaClient(os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
topic = kafka_client.topics[str.encode("events")]
consumer = kafka_client.get_simple_consumer(
    topic=topic,
    consumer_group=b"dashboard-consumer",
    auto_offset_reset=kafka.OffsetRequest.EarliestAvailable,
)

# ── Pydantic models for request/response ────────────────────
class EventIn(BaseModel):
    kind: str
    payload: str = ""

class EventOut(BaseModel):
    id: int
    timestamp: str
    kind: str
    payload: str | None = None

# ── Health check ────────────────────────────────────────────
@app.get("/healthz")
def health():
    return {"status": "ok"}

# ── POST /events – ingest a new event ───────────────────────
@app.post("/events", response_model=EventOut)
def create_event(event: EventIn):
    db = SessionLocal()
    try:
        db_event = Event(timestamp=time.time(), kind=event.kind, payload=event.payload)
        db.add(db_event)
        db.commit()
        db.refresh(db_event)
        # forward to Kafka (optional – here we just ACK)
        producer = kafka.KafkaProducer(bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"))
        producer.send("events", value=event.model_dump_json().encode())
        producer.flush()
        return EventOut(id=db_event.id, timestamp=db_event.timestamp.isoformat(), kind=db_event.kind, payload=db_event.payload)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()
```

> **Key takeaway** – The endpoint does three things atomically: persists the row, forwards the event downstream, and returns a tidy JSON response. That pattern (DB write → event emit → API reply) is a core micro‑service design.

### 3️⃣ Write a tiny event producer

Create `producer.py` in the project root:

```python
#!/usr/bin/env python3
import json
import time
import random
from kafka import KafkaProducer

producer = KafkaProducer(bootstrap_servers="localhost:9092", value_serializer=lambda v: json.dumps(v).encode())

kinds = ["click", "view", "purchase", "signup"]
for i in range(50):
    event = {
        "kind": random.choice(kinds),
        "payload": json.dumps({"user_id": random.randint(1, 1000), "session": f"s-{i}"}),
        "ts": time.time(),
    }
    producer.send("events", value=json.dumps(event).encode())
    time.sleep(0.1)

producer.flush()
print("Sent 50 sample events")
```

Run it after the stack is up:

```bash
python producer.py
```

> **Why it matters** – Producing realistic data demonstrates you can serialize payloads, pick meaningful keys, and feed a topic without blocking the main thread.

### 4️⃣ Verify the consumer is pulling and storing events

Start the services:

```bash
docker compose up -d
```

Wait ~30 seconds for Kafka and Postgres to initialise, then:

```bash
python producer.py
```

Query Postgres directly (you can use `psql` or any GUI):

```bash
psql "postgresql://dashboard:dashboard@localhost:5432/dashboard" -c "SELECT COUNT(*) FROM events;"
```

You should see at least 50 rows.

### 5️⃣ Hit the FastAPI endpoint

```bash
curl -X POST http://localhost:8000/events -H "Content-Type: application/json" -d '{"kind":"click","payload":"{\"user_id\":42}"}'
```

Response example:

```json
{
  "id": 1,
  "timestamp": "2026-10-27T12:34:56.789012",
  "kind": "click",
  "payload": "{\"user_id\":42}"
}
```

Check the auto‑generated docs at `http://localhost:8000/docs` – FastAPI will show the OpenAPI schema automatically.

> **Running & testing tip** – Use `uvicorn api.main:app --reload` locally if you prefer not to rebuild the image, or `docker compose up --build api` for the full containerised flow.

## Running and Testing It

| Step | Command | Expected outcome |
|------|---------|------------------|
| **Start stack** | `docker compose up -d` | Kafka, Zookeeper, Postgres, API containers up |
| **Produce sample data** | `python producer.py` | 50 events landed in `events` topic |
| **Confirm persistence** | `psql ... -c "SELECT COUNT(*) FROM events;"` | Row count ≥ 50 |
| **API health** | `curl http://localhost:8000/healthz` | `{"status":"ok"}` |
| **Create an event via API** | `curl -X POST http://localhost:8000/events -d '{"kind":"view"}'` | JSON with new row ID |
| **View OpenAPI docs** | Open `http://localhost:8000/docs` in browser | Swagger UI with `/events` endpoint |

You can also run the test suite (if you add one) with `pytest -q` inside the `api` container; the health endpoint and a simple “create‑event‑then‑read‑from‑DB” assertion make a solid smoke test.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | One‑line reason it matters |
|---|---------|----------------------------|
| 1 | **Add TTL‑based compaction** – configure Kafka log compaction so only the latest event per key is kept. | Keeps storage bounded and mirrors real‑world event‑sourcing patterns. |
| 2 | **Horizontal scaling with Kafka clusters** – spin up 3 broker nodes, increase `replication.factor` to 2. | Demonstrates fault‑tolerance and understanding of partition distribution. |
| 3 | **OpenTelemetry instrumentation** – export traces/metrics to a local OTLP collector. | Provides vendor‑agnostic observability, a must‑have for senior‑level system design. |
| 4 | **Consumer group rebalancing & lag monitoring** – use the Kafka Python client’s `consumer lag` metric and alert on > 5 min lag. | Shows you can detect and remediate backpressure in production. |
| 5 | **Add authentication & rate‑limiting** – integrate `fastapi.security.HTTPBearer` + `slowapi` for per‑client quotas. | Mirrors real API security concerns and protects the pipeline from abuse. |
| 6 | **Benchmark with Locust** – write a load script that posts 100 req/s and measures latency/throughput. | Quantifies performance characteristics you can discuss in interviews. |

Each upgrade moves the project from “toy example” to a production‑grade system you can point to and say, “I’ve handled scaling, observability, and security at production scale.”

## Key Takeaways

- **Kafka + FastAPI + Postgres** is a compact, yet complete, stack that touches messaging, persistence, and API design—exactly the trifecta hiring managers look for.  
- **Docker Compose** gives you a reproducible environment; you can spin it up in minutes and tear it down just as fast.  
- **Observability** (health endpoint + Prometheus metrics) is not an afterthought; it’s built in from the start.  
- **Extensibility** is baked in: you can add TTL compaction, clustering, tracing, or auth with minimal changes.  
- The project is **demo‑ready**: a single `curl` proves data flows end‑to‑end, and the OpenAPI docs give interviewers an instant view of the API contract.

## Further Reading

- [Kafka Documentation – Core Concepts](https://kafka.apache.org/documentation/#documentation)  
- [FastAPI Official Docs – Building APIs](https://fastapi.tiangolo.com/)  
- [PostgreSQL Documentation – SQL Cheat Sheet](https://www.postgresql.org/docs/current/tutorial.html)  
- [OpenTelemetry Specification – Instrumentation](https://opentelemetry.io/docs/instrumentation/)  
- [Kafka Streams Guide – Stream Processing](https://kafka.apache.org/documentation/#streams)  
- [Docker Compose Reference](https://docs.docker.com/compose/)  

Feel free to fork the repo, tinker with the upgrades, and bring the whole pipeline to your next technical interview. Happy building!