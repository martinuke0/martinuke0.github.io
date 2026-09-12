

---
title: "Building a User Safety Service: A Practical Guide for Your CV"
date: "2026-09-12T20:01:41.917"
draft: false
tags: ["safety", "microservice", "fastapi", "machine-learning", "devops", "portfolio"]
description: "A hands-on guide to building a user safety microservice that detects toxic content, ships in Docker, and scales horizontally—perfect for your CV."
summary: "Learn to build a Dockerized microservice that scores user-generated text for toxicity using a transformer model, with full CI/CD and scaling guidance."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-building-a-user-safety-service-a-practical-guide-for-your-cv.svg"
  alt: "A dashboard showing safety scores for user messages"
  caption: ""
  relative: false
---

> **TL;DR** — Build a FastAPI microservice that scores user text for toxicity using a transformer model, containerize it with Docker, and extend it with persistence, scaling, and observability to showcase real systems skill.

In a market crowded with “todo” apps and simple CRUD services, hiring managers look for evidence that you understand how software behaves under load, how to enforce safety guarantees, and how to ship and operate a service that matters. A user‑safety microservice ticks all those boxes: it combines machine‑learning inference, API design, container orchestration, and production‑grade concerns like observability and fault tolerance. Below is a complete, runnable blueprint you can clone, extend, and list on your résumé.

## Why This Project Stands Out on a CV

- **End‑to‑end systems thinking** – you will design a service that receives untrusted input, applies a model, returns a decision, and logs the outcome, mirroring real‑world content‑moderation pipelines.
- **Production‑ready stack** – FastAPI, Docker, PostgreSQL, Prometheus, and optionally Kubernetes demonstrate familiarity with the modern Python ecosystem and cloud‑native tooling.
- **Safety‑first mindset** – implementing rate limiting, input validation, and audit logging shows you care about security and compliance, a hot topic for platforms handling user‑generated content.
- **Scalability proof** – the architecture is explicitly designed for horizontal scaling; you can show how to add replicas, partition data, and tune autoscaling policies.
- **Observability** – exposing metrics, tracing requests, and configuring alerts prove you understand how to operate a service in production, not just write code.

## Architecture Overview

The service is a stateless API front‑ended by a lightweight inference layer. Below is a high‑level breakdown:

- **API Gateway (FastAPI)** – HTTP endpoint `/score` accepts JSON `{ "text": "..." }` and returns `{ "score": 0.0–1.0, "flagged": bool }`.
- **Model Service** – loads a transformer model (e.g., `unitary/toxic-bert`) in a separate process to avoid blocking the event loop.
- **Persistence (PostgreSQL)** – stores every request with its score, timestamp, and client IP for audit trails.
- **Cache (Redis)** – optional short‑term cache to avoid repeated inference on identical text.
- **Metrics & Tracing** – Prometheus metrics (request count, latency, score distribution) and OpenTelemetry traces exported to a backend like Jaeger.
- **Containerization** – Docker image with a multi‑stage build; `docker‑compose.yml` for local dev.
- **Orchestration (optional)** – Kubernetes manifests for production deployment, including horizontal pod autoscaler and pod‑disruption‑budget.

A simple ASCII diagram:

```
Client ──► FastAPI ──► Model Service ──► PostgreSQL
                │                │
                ▼                ▼
            Redis Cache    Prometheus
```

## Building It Step by Step

Below are the core files you need to get a working service. All code is production‑grade but trimmed for brevity.

### 1. Project layout

```
safety-service/
├── app/
│   ├── main.py
│   ├── model.py
│   └── db.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── k8s/
    └── deployment.yaml
```

### 2. FastAPI entry point (`app/main.py`)

```python
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import time
import logging

from .model import predict_toxicity
from .db import log_request
from .metrics import REQUEST_COUNT, REQUEST_LATENCY

app = FastAPI(title="User Safety Service")
logger = logging.getLogger("safety")

class ScoreRequest(BaseModel):
    text: str

class ScoreResponse(BaseModel):
    score: float
    flagged: bool

@app.post("/score", response_model=ScoreResponse)
async def score_endpoint(req: ScoreRequest, request: Request):
    start = time.time()
    try:
        score = await predict_toxicity(req.text)
        flagged = score > 0.7  # configurable threshold
        await log_request(req.text, score, request.client.host)
        return ScoreResponse(score=score, flagged=flagged)
    except Exception as exc:
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail="Internal error") from exc
    finally:
        REQUEST_COUNT.labels(method="POST", endpoint="/score").inc()
        REQUEST_LATENCY.labels(endpoint="/score").observe(time.time() - start)
```

### 3. Model inference (`app/model.py`)

```python
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_NAME = "unitary/toxic-bert"
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
model.eval()

async def predict_toxicity(text: str) -> float:
    """Return probability that the text is toxic."""
    inputs = tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    with torch.no_grad():
        logits = model(**inputs).logits
    # Model outputs a single logit; apply sigmoid for probability
    prob = torch.sigmoid(logits[0][0]).item()
    return prob
```

### 4. Persistence (`app/db.py`)

```python
import asyncpg
from datetime import datetime

DB_DSN = "postgres://user:pass@localhost:5432/safety"

async def log_request(text: str, score: float, ip: str):
    conn = await asyncpg.connect(DB_DSN)
    try:
        await conn.execute(
            "INSERT INTO requests (text, score, ip, created_at) VALUES ($1, $2, $3, $4)",
            text, score, ip, datetime.utcnow()
        )
    finally:
        await conn.close()
```

### 5. Metrics (`app/metrics.py`)

```python
from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    "safety_requests_total",
    "Total number of requests",
    ["method", "endpoint"]
)

REQUEST_LATENCY = Histogram(
    "safety_request_latency_seconds",
    "Latency of requests",
    ["endpoint"]
)
```

### 6. Dockerfile

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 7. docker‑compose.yml

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_DSN=postgres://user:pass@db:5432/safety
    depends_on:
      - db
  db:
    image: postgres:15
    environment:
      POSTGRES_DB: safety
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
    volumes:
      - pgdata:/var/lib/postgresql/data
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
volumes:
  pgdata:
```

### 8. Kubernetes deployment (`k8s/deployment.yaml`)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: safety-service
spec:
  replicas: 3
  selector:
    matchLabels:
      app: safety-service
  template:
    metadata:
      labels:
        app: safety-service
    spec:
      containers:
        - name: api
          image: myrepo/safety-service:latest
          ports:
            - containerPort: 8000
          env:
            - name: DB_DSN
              value: "postgres://user:pass@db:5432/safety"
          resources:
            requests:
              cpu: "200m"
              memory: "256Mi"
            limits:
              cpu: "500m"
              memory: "512Mi"
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: safety-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: safety-service
  minReplicas: 3
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

## Running and Testing It

1. **Clone and build**

```bash
git clone https://github.com/yourname/safety-service.git
cd safety-service
docker compose up --build
```

2. **Run a quick sanity check**

```bash
curl -X POST http://localhost:8000/score \
     -H "Content-Type: application/json" \
     -d '{"text":"I hate you!"}' | jq
```

Expected output (example):

```json
{
  "score": 0.82,
  "flagged": true
}
```

3. **Load test with k6**

Create `k6/script.js`:

```javascript
import http from 'k6/http';
import { check } from 'k6/k6';

export default function () {
    const payload = JSON.stringify({ text: "This is a test sentence." });
    const params = { headers: { "Content-Type": "application/json" } };
    const res = http.post('http://localhost:8000/score', payload, params);
    check(res, { 'status is 200': (r) => r.status === 200 });
}
```

Run:

```bash
k6 run k6/script.js
```

4. **Verify metrics**

Open `http://localhost:8000/metrics` (if you add a Prometheus endpoint) or query the Prometheus UI at `http://localhost:9090` for `safety_requests_total`.

## Extending It: Your Roadmap to Senior‑Level

1. **Persist and query history** – Add a `requests` table with indexes on `created_at` and `score`; expose a `/history` endpoint. *Why it matters:* audit trails are required for compliance and model drift analysis.*

2. **Horizontal scaling with Kubernetes** – Deploy the HPA shown above; use `kubectl` to observe pod count under load. *Why it matters:* demonstrates you can handle traffic spikes without manual intervention.*

3. **Observability suite** – Instrument the service with OpenTelemetry traces, export to Jaeger, and create Grafana dashboards for latency, error rate, and score distribution. *Why it matters:* production teams need visibility to debug and optimize.*

4. **Fault tolerance & retries** – Wrap the model inference with a circuit‑breaker (e.g., `pybreaker`) and exponential back‑off; fall back to a cached score if the model is unavailable. *Why it matters:* prevents cascading failures when the ML service is slow.*

5. **Benchmarking and capacity planning** – Use `k6` to determine requests‑per‑second at 99th‑percentile latency < 200 ms; record CPU/memory usage per replica. *Why it matters:* gives you data to justify autoscaling thresholds and resource requests.*

6. **Model versioning & A/B testing** – Store model versions in a registry (e.g., MLflow) and route a percentage of traffic to a new model for comparison. *Why it matters:* shows you can iterate on ML without breaking the service.

## Key Takeaways

- Build a **stateless FastAPI service** that scores user text with a transformer model.
- Containerize with **Docker** and orchestrate with **Kubernetes** to prove scalability.
- Add **PostgreSQL** persistence, **Redis** caching, and **Prometheus** metrics for production readiness.
- Extend with **tracing**, **circuit‑breakers**, and **A/B testing** to demonstrate senior‑level engineering.
- Use **k6** for load testing and document your findings to showcase analytical skills.

## Further Reading

- [FastAPI documentation](https://fastapi.tiangolo.com/) – official guide on building APIs with Pydantic and dependency injection.
- [Hugging Face Transformers – Toxic BERT](https://huggingface.co/unitary/toxic-bert) – model card and inference examples.
- [PostgreSQL asyncpg driver](https://magicstack.github.io/asyncpg/) – high‑performance async PostgreSQL client for Python.
- [Prometheus Python client](https://github.com/prometheus/client_python) – how to expose metrics for scraping.
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/) – instrumentation for distributed tracing.
- [Kubernetes Horizontal Pod Autoscaler](https://kubernetes.io/docs/tasks/autoscaling/horizontal-pod-autoscale/) – official walkthrough for scaling deployments.
- [Designing Data‑Intensive Applications](https://www.oreilly.com/library/view/designing-data-intensive-applications/9781449337607/) – chapter on reliability and consistency for building safe user systems.