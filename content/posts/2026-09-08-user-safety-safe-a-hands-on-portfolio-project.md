

---
title: "User Safety: Safe – A Hands-On Portfolio Project"
date: "2026-09-08T22:01:16.303"
draft: false
tags: ["portfolio", "systems", "user-safety", "fastapi", "docker", "observability"]
description: "Learn to build a real-time user safety service using FastAPI, Redis, and Docker, demonstrating systems engineering skills for hiring managers."
summary: "A practical guide to building a real-time user safety service with FastAPI, Redis, and Docker, showing hiring managers your systems engineering capabilities."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-08-user-safety-safe-a-hands-on-portfolio-project.svg"
  alt: "A dashboard showing real-time safety metrics"
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time user safety service that validates user-generated content, logs violations, and exposes metrics, all containerized with Docker. This project demonstrates API design, caching, persistence, observability, and deployment—skills that directly map to senior systems roles.

In a crowded job market, you need a portfolio piece that proves you can ship production‑grade software, not just write algorithms. A *User Safety* service is a perfect vehicle: it touches APIs, data storage, caching, monitoring, and fault tolerance—all core competencies for backend or full‑stack engineers. Below you’ll find a complete, runnable implementation that you can deploy locally in minutes, then extend into a scalable, observable system.

## Why This Project Stands Out on a CV

- **End‑to‑end system design** – You’ll configure a REST API, a cache, a relational database, metrics collection, and container orchestration, showing you understand how components fit together.
- **Real‑world domain** – Content moderation and safety are critical in social platforms, marketplaces, and collaboration tools; building a working solution signals domain awareness.
- **Production‑ready patterns** – The code uses connection pooling, structured logging, Prometheus metrics, and Docker‑based deployment, which are standard in modern SRE and backend teams.
- **Scalable architecture** – The design is stateless at the API layer, making horizontal scaling trivial—a talking point for senior roles.
- **Observability first** – By exposing metrics and structured logs, you demonstrate the “you build it, you run it” mindset that hiring managers love.

## Architecture Overview

The service is a small micro‑system with five clear boundaries:

1. **API Layer** – FastAPI (Python) exposes `/check` POST endpoint that receives text and returns a safety verdict.
2. **Validation Engine** – A pluggable module that applies rule‑based filters and can later host a ML model.
3. **Cache** – Redis stores recent verdicts to avoid recomputation and reduce latency.
4. **Persistence** – PostgreSQL records every violation with timestamp and payload for audit trails.
5. **Observability** – Prometheus scrapes `/metrics`; Grafana (optional) visualizes request rate, error ratio, and latency.

A simple text diagram:

```
Client ──► FastAPI ──► Redis (cache) ──► PostgreSQL (audit)
                │
                ▼
          Prometheus
```

All components are packaged as Docker containers, orchestrated with `docker‑compose.yml`.

## Building It Step by Step

### Step 1 – Scaffold the Project

Create a directory `user_safety_service` and initialize a virtual environment.

```bash
mkdir user_safety_service
cd user_safety_service
python -m venv venv
source venv/bin/activate
```

Add `requirements.txt`:

```text
fastapi==0.110.0
uvicorn==0.29.0
redis==5.0.3
psycopg2-binary==2.9.9
sqlalchemy==2.0.29
prometheus-client==0.20.0
pydantic==2.7.1
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### Step 2 – Core API with FastAPI

Create `main.py`:

```python
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import redis
import sqlalchemy
from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
import time
import os

# --- Configuration ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/safety")

# --- FastAPI app ---
app = FastAPI(title="User Safety Service")

# --- Prometheus metrics ---
REQUEST_COUNT = Counter("safety_requests_total", "Total requests to safety service", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("safety_request_latency_seconds", "Latency of safety requests", ["method", "endpoint"])

# --- Redis client ---
redis_client = redis.from_url(REDIS_URL, decode_responses=True)

# --- Database setup ---
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Violation(Base):
    __tablename__ = "violations"
    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=False)
    reason = Column(String, index=True)
    created_at = Column(DateTime, default=sqlalchemy.func.now())

Base.metadata.create_all(bind=engine)

# --- Dependency ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic models ---
class SafetyCheckRequest(BaseModel):
    text: str

class SafetyCheckResponse(BaseModel):
    safe: bool
    reason: str | None = None

# --- Safety validator ---
def validate_text(text: str) -> tuple[bool, str | None]:
    # Simple rule‑based filter (replace with ML later)
    banned_words = ["spam", "hate", "violence"]
    for word in banned_words:
        if word in text.lower():
            return False, f"Contains banned word: {word}"
    return True, None

# --- Endpoints ---
@app.post("/check", response_model=SafetyCheckResponse)
async def check_safety(req: SafetyCheckRequest):
    # Increment request counter
    REQUEST_COUNT.labels(method="POST", endpoint="/check").inc()
    # Measure latency
    with REQUEST_LATENCY.labels(method="POST", endpoint="/check").time():
        # 1. Check cache
        cached = redis_client.get(req.text)
        if cached:
            safe, reason = cached.split("::", 1)
            return SafetyCheckResponse(safe=safe == "True", reason=reason if reason else None)

        # 2. Validate
        safe, reason = validate_text(req.text)

        # 3. Cache result (TTL 5 minutes)
        redis_client.setex(req.text, 300, f"{safe}::{reason or ''}")

        # 4. Persist if violation
        if not safe:
            db = SessionLocal()
            try:
                db.add(Violation(text=req.text, reason=reason))
                db.commit()
            finally:
                db.close()

        return SafetyCheckResponse(safe=safe, reason=reason)

@app.get("/metrics")
async def metrics():
    return generate_latest()

@app.get("/health")
async def health():
    return {"status": "ok"}
```

### Step 3 – Add Docker Compose

Create `docker-compose.yml`:

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - REDIS_URL=redis://redis:6379
      - DATABASE_URL=postgresql://user:pass@db:5432/safety
    depends_on:
      - redis
      - db
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  db:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: safety
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - pg_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml

volumes:
  redis_data:
  pg_data:
```

Add `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'safety'
    static_configs:
      - targets: ['api:8000']
    metrics_path: /metrics
```

Create a `Dockerfile`:

```Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 4 – Run the Stack

```bash
docker compose up --build
```

The API will be available at `http://localhost:8000`, Prometheus at `http://localhost:9090`.

## Running and Testing It

### Health Check

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### Safety Endpoint

```bash
curl -X POST http://localhost:8000/check \
     -H "Content-Type: application/json" \
     -d '{"text":"hello world"}'
# {"safe":true,"reason":null}
```

```bash
curl -X POST http://localhost:8000/check \
     -H "Content-Type: application/json" \
     -d '{"text":"this is spam and hate"}'
# {"safe":false,"reason":"Contains banned word: spam"}
```

### Verify Persistence

Open a PostgreSQL client:

```bash
docker compose exec db psql -U user -d safety -c "SELECT * FROM violations;"
```

You should see the rows for each unsafe request.

### Observe Metrics

```bash
curl http://localhost:8000/metrics | grep safety_requests_total
```

Prometheus UI will show the same data in graph form.

## Extending It: Your Roadmap to Senior-Level

1. **Plug in a Machine Learning Model** – Replace the rule‑based filter with a transformer (e.g., `distilbert-base-uncased`) served via TorchServe. *Why it matters:* Shows you can integrate inference pipelines and manage model latency.
2. **Add Rate Limiting & Quotas** – Use Redis `INCR` with TTL to enforce per‑user limits. *Why it matters:* Prevents abuse and demonstrates API governance.
3. **Horizontal Scaling with Kubernetes** – Deploy the API as a Deployment with multiple replicas behind a Service. *Why it matters:* Proves you understand stateless scaling and load distribution.
4. **Distributed Tracing** – Instrument with OpenTelemetry and export to Jaeger. *Why it matters:* Enables end‑to‑end latency analysis in microservice architectures.
5. **Circuit Breaker Pattern** – Wrap Redis/DB calls with a library like `py‑circuit` to fail fast on downstream outages. *Why it matters:* Improves fault tolerance and prevents cascading failures.
6. **Benchmarking & Load Testing** – Use `locust` to simulate 1000 concurrent users and capture throughput/latency curves. *Why it matters:* Provides data‑driven evidence of performance for capacity planning.

## Key Takeaways

- A portfolio project should showcase **API design, caching, persistence, observability, and deployment** in a single, coherent system.
- **Containerization** with Docker and orchestration via `docker‑compose` (or later Kubernetes) signals production readiness.
- **Metrics and logging** are not afterthoughts—they are first‑class citizens, proving you can monitor and debug in real time.
- The architecture is **stateless at the API layer**, making horizontal scaling straightforward and interview‑friendly.
- Extending the service with ML, rate limiting, tracing, and fault‑tolerance patterns demonstrates a path from junior to senior engineering.

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/) – Build production APIs with automatic OpenAPI docs.
- [Redis Command Reference](https://redis.io/commands/) – Deep dive into caching, rate limiting, and pub/sub patterns.
- [PostgreSQL Performance Tuning](https://www.postgresql.org/docs/current/performance-tips.html) – Indexing and query optimization for audit tables.
- [Prometheus Monitoring Best Practices](https://prometheus.io/docs/tutorials/monitoring_2016/) – Instrumenting microservices with metrics.
- [Kubernetes Deployment Guide](https://kubernetes.io/docs/tutorials/kubernetes-basics/) – Scaling stateless services horizontally.
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) – Standard for distributed tracing and metrics collection.