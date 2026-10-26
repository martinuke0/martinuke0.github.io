---
title: "Building a User Safety Service: A Portfolio Project for Aspiring Engineers"
date: "2026-10-26T22:00:48.359"
draft: false
tags: ["user-safety", "portfolio", "systems", "fastapi", "content-moderation", "engineering"]
description: "A practical guide to building a user safety service that showcases real systems skills, with runnable FastAPI code, architecture, and testing."
summary: "Learn to build a user safety service that demonstrates systems engineering, API design, and testing for hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-26-building-a-user-safety-service-a-portfolio-project-for-aspiring-engineers.svg"
  alt: "A dashboard showing user safety metrics"
  caption: ""
  relative: false
---

> **TL;DR** — Build a user safety service that ingests user-generated content, applies rule‑based and ML‑based moderation, and returns safety decisions. This project demonstrates API design, asynchronous processing, and observability—skills that hiring managers look for in systems roles. You’ll end up with a runnable FastAPI application, Dockerized, and ready to extend.

In today's platforms, user safety is a first‑class concern. Whether you are building a forum, a chat app, or a marketplace, you need a pipeline that can evaluate content for toxicity, spam, and policy violations. This post walks you through building a compact yet realistic user safety service that you can put on your résumé and discuss in interviews.

## Why This Project Stands Out on a CV

- **End‑to‑end system design** – You will ship a complete service that accepts HTTP requests, processes them asynchronously, persists results, and exposes metrics.  
- **Modern Python stack** – FastAPI, Celery, PostgreSQL, and Redis are widely used in production; showcasing them signals you can work in a real‑world backend.  
- **Safety‑first logic** – Implementing rule‑based filters and integrating a pre‑trained toxicity model demonstrates applied machine learning and ethical considerations.  
- **Observability by default** – Exposing Prometheus metrics and structured logs teaches you to build systems that are debuggable in production.  
- **Containerization** – Packaging the service with Docker and docker‑compose proves you understand deployment‑ready artifacts.  

These skills map directly to roles such as Backend Engineer, SRE, ML Engineer, or Product Infrastructure Engineer, where building reliable, scalable pipelines is core.

## Architecture Overview

The service is composed of four logical components:

1. **API Gateway** – A FastAPI app that receives `/moderate` POST requests, validates input, and returns a decision ID.  
2. **Ingestion Queue** – Celery with Redis as the broker decouples request handling from processing, allowing the API to respond quickly while work happens asynchronously.  
3. **Moderation Workers** – Celery tasks that apply rule‑based checks ( profanity, length, spam patterns) and then call a toxicity model (e.g., a lightweight transformer).  
4. **Persistence & Cache** – PostgreSQL stores the final verdict and metadata; Redis caches frequent results to reduce latency and model load.

A simplified text diagram:

```
Client ──► FastAPI (ingest) ──► Redis (queue) ──► Celery Workers
                │                       │
                ▼                       ▼
           PostgreSQL             Toxicity Model
```

Each component is independently testable, which makes the system easy to extend and reason about.

## Building It Step by Step

### 1. Scaffold the project

Create a directory and set up a virtual environment.

```bash
mkdir user-safety-service
cd user-safety-service
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn celery redis sqlalchemy pg8000 transformers torch
```

### 2. Define the data models

Create `models.py` to describe the `ModerationRequest` and `ModerationResult` tables.

```python
# models.py
from sqlalchemy import Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class ModerationRequest(Base):
    __tablename__ = "requests"
    id = Column(Integer, primary_key=True)
    content = Column(String, nullable=False)
    submitted_at = Column(DateTime, default=datetime.utcnow)

class ModerationResult(Base):
    __tablename__ = "results"
    id = Column(Integer, primary_key=True)
    request_id = Column(Integer, nullable=False)
    is_safe = Column(Boolean, nullable=False)
    toxicity_score = Column(Float)
    rule_violations = Column(String)
    processed_at = Column(DateTime, default=datetime.utcnow)
```

### 3. Build the FastAPI ingestion endpoint

`api.py` exposes a single endpoint that enqueues a task.

```python
# api.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

app = FastAPI()

# Celery setup
celery_app = Celery(
    "user-safety",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

# Database
engine = create_engine("postgresql+pg8000://user:pass@localhost/safety")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class ModeratePayload(BaseModel):
    content: str

@app.post("/moderate")
async def moderate(payload: ModeratePayload):
    # Persist the request
    with SessionLocal() as session:
        req = ModerationRequest(content=payload.content)
        session.add(req)
        session.commit()
        request_id = req.id

    # Enqueue async processing
    celery_app.send_task("tasks.process_moderation", args=[request_id])
    return {"request_id": request_id}
```

### 4. Implement the moderation worker

Create `tasks.py` with the Celery task that runs rule checks and the ML model.

```python
# tasks.py
from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from transformers import pipeline
import re

celery_app = Celery(
    "user-safety",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
)

engine = create_engine("postgresql+pg8000://user:pass@localhost/safety")
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Load a pre‑trained toxicity classifier
toxicity_pipe = pipeline("text-classification", model="cardiffnlp/twitter-roberta-base-offensive")

def rule_checks(content: str) -> list:
    violations = []
    if len(content) > 500:
        violations.append("too_long")
    if re.search(r"badword", content, re.IGNORECASE):
        violations.append("profanity")
    return violations

@celery_app.task(name="tasks.process_moderation")
def process_moderation(request_id: int):
    with SessionLocal() as session:
        req = session.query(ModerationRequest).get(request_id)
        if not req:
            return

        violations = rule_checks(req.content)
        # Run ML model
        ml_result = toxicity_pipe(req.content)[0]
        toxicity_score = ml_result["score"] if ml_result["label"] == "toxicity" else 0.0

        is_safe = not violations and toxicity_score < 0.5

        result = ModerationResult(
            request_id=request_id,
            is_safe=is_safe,
            toxicity_score=toxicity_score,
            rule_violations=",".join(violations),
        )
        session.add(result)
        session.commit()
```

### 5. Add observability

Instrument the API with Prometheus metrics.

```python
# metrics.py
from prometheus_client import Counter, Histogram, generate_latest
from fastapi import Response

REQUEST_COUNT = Counter("moderate_requests_total", "Total moderation requests")
REQUEST_LATENCY = Histogram("moderate_request_duration_seconds", "Latency of /moderate")

@app.middleware("http")
async def add_metrics(request, call_next):
    REQUEST_COUNT.inc()
    with REQUEST_LATENCY.time():
        response = await call_next(request)
    return response

@app.get("/metrics")
def metrics():
    return Response(generate_latest())
```

### 6. Containerize the service

Create a `Dockerfile` and `docker-compose.yml`.

```Dockerfile
# Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

```yaml
# docker-compose.yml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - db
  worker:
    build: .
    command: celery -A tasks worker --loglevel=info
    depends_on:
      - redis
      - db
  redis:
    image: redis:7-alpine
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: safety
```

## Running and Testing It

1. **Start the stack**

```bash
docker compose up --build
```

2. **Send a test request**

```bash
curl -X POST http://localhost:8000/moderate \
     -H "Content-Type: application/json" \
     -d '{"content": "This is a harmless message."}'
```

You should receive a JSON payload with a `request_id`.

3. **Check the result**

After a few seconds, query the database:

```bash
docker compose exec db psql -U user -d safety -c "SELECT * FROM results;"
```

You will see a row with `is_safe` set to `true` (or `false` for toxic content).

4. **Unit tests**

Create `test_tasks.py` to verify rule checks and ML integration.

```python
# test_tasks.py
from tasks import rule_checks

def test_rule_checks():
    assert rule_checks("short") == []
    assert "too_long" in rule_checks("a" * 600)
```

Run with `pytest`.

## Extending It: Your Roadmap to Senior‑Level

1. **Add authentication and rate limiting** – Protect the endpoint with API keys and limit per‑client throughput to prevent abuse.  
2. **Introduce Kafka for event streaming** – Replace Redis/Celery with Kafka topics to handle higher throughput and enable replayable logs.  
3. **Implement fault tolerance** – Use retries with exponential backoff and circuit‑breaker patterns around the ML model call.  
4. **Deploy observability stack** – Add Prometheus server, Grafana dashboards, and alerting on latency and error rates.  
5. **Add A/B testing framework** – Allow different moderation thresholds to be tested against each other on a percentage of traffic.  
6. **Package as a Helm chart** – Deploy to a Kubernetes cluster with Helm, including horizontal pod autoscaler and pod‑disruption‑budget settings.

Each upgrade addresses a real production concern: security, scalability, reliability, and operational visibility.

## Key Takeaways

- Build a complete, runnable service that ingests content, applies rule‑based and ML moderation, and persists results.  
- Use FastAPI for the API layer, Celery with Redis for async processing, and PostgreSQL for durable storage.  
- Instrument the system with Prometheus metrics and expose them via a `/metrics` endpoint.  
- Containerize with Docker and orchestrate with docker‑compose for a reproducible local environment.  
- Extend the project with authentication, Kafka, fault‑tolerant patterns, full observability, A/B testing, and Kubernetes deployment to demonstrate senior‑level engineering.

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/) – Learn the latest patterns for building APIs.  
- [Celery Official Guide](https://docs.celeryq.dev/) – Understand task queues, brokers, and worker configuration.  
- [PostgreSQL Documentation](https://www.postgresql.org/docs/) – Dive into indexing, transactions, and JSON support.  
- [Redis Documentation](https://redis.io/docs/) – Explore caching strategies and pub/sub for real‑time messaging.  
- [Transformers Pipeline Reference](https://huggingface.co/transformers/main_classes/pipelines.html) – Integrate pre‑trained models for content moderation.