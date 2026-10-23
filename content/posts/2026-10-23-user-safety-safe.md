---
title: "User Safety: safe"
date: "2026-10-23T02:01:36.351"
draft: false
tags: ["user-safety", "systems-engineering", "python", "fastapi", "redis", "machine-learning"]
description: "Build a user safety API that filters toxic content, demonstrating systems engineering, FastAPI, and ML integration for hiring managers."
summary: "A practical guide to building a user safety microservice that scores text for toxicity using a FastAPI endpoint, Redis caching, and a scikit-learn model, perfect for showcasing systems skills on a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-23-user-safety-safe.svg"
  alt: "User safety service diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time user safety service that scores text for toxicity using a FastAPI endpoint, a scikit-learn model, and Redis caching. This project demonstrates systems engineering, API design, and ML integration—skills that hiring managers look for in backend and platform roles.

In the race to stand out as a systems engineer, a side project that ships a working, scalable service is far more compelling than a theoretical blog post. This guide walks you through building **User Safety: safe**, a production-flavored microservice that classifies user-generated text for toxic language. By the end, you'll have a runnable FastAPI app, a trained toxicity classifier, and a caching layer that together signal real-world backend competence.

## Why This Project Stands Out on a CV

This project surfaces a cluster of skills that map directly to senior-level job descriptions:

- **REST API design & FastAPI mastery** – you'll ship a documented, async endpoint that handles JSON payloads and returns structured predictions.
- **Machine learning integration** – training a scikit-learn pipeline and serving it behind an HTTP API demonstrates you can bridge data science and production.
- **Caching with Redis** – adding a cache layer shows you understand performance, hot paths, and trade‑offs between latency and freshness.
- **Containerization & deployment** – packaging the service in a Docker image proves you can think about environments, dependencies, and reproducibility.
- **Observability basics** – structured logging, Prometheus metrics, and health checks are expected in any modern platform role.

Together, these competencies signal that you can own a service end‑to‑end, from model training to scaling in production. They are frequently cited in postings for **Backend Engineer**, **ML Engineer**, **Platform Engineer**, and **SRE** positions.

## Architecture Overview

The service is composed of four logical components:

1. **Client** – any HTTP client (browser, mobile app, curl) sends a JSON payload `{"text": "..."}` to the `/predict` endpoint.
2. **FastAPI Application** – the entry point that validates input, orchestrates caching, and returns the toxicity score.
3. **Model Service** – a thin wrapper around a trained scikit-learn model that transforms raw text into a probability.
4. **Redis Cache** – stores recent predictions keyed by the SHA‑256 hash of the input text, reducing latency and model load for repeated content.

A simplified text diagram:

```
Client ──HTTP──▶ FastAPI ──▶ Redis (cache hit?)
                  │
                  └──▶ Model Service (cache miss)
```

All components run inside a single Docker container for simplicity, but the architecture is already split into separate modules so you can later extract the model service or cache into their own processes.

## Building It Step by Step

### 1. Project Setup

Create a new directory and set up a Python virtual environment:

```bash
mkdir user-safety-safe
cd user-safety-safe
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn redis scikit-learn pandas numpy joblib
```

### 2. Data Acquisition and Model Training

For a minimal viable product, we'll use a small labeled dataset of toxic comments. In a real project you'd source from [Toxic Comments dataset](https://www.kaggle.com/datasets/justmeantoxicity/toxic-comments-train), but for brevity we'll simulate with a few examples.

Create `train_model.py`:

```python
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
import joblib

# toy dataset
data = {
    "text": [
        "You are an idiot",
        "I love this product",
        "Go to hell",
        "Have a great day",
        "You're so stupid",
        "This is wonderful"
    ],
    "toxic": [1, 0, 1, 0, 1, 0]
}
df = pd.DataFrame(data)

# build pipeline
pipeline = Pipeline([
    ("tfidf", TfidfVectorizer(ngram_range=(1, 2))),
    ("clf", LogisticRegression())
])

pipeline.fit(df["text"], df["toxic"])
joblib.dump(pipeline, "model.joblib")
print("Model saved as model.joblib")
```

Run it:

```bash
python train_model.py
```

### 3. FastAPI Application Skeleton

Create `app.py`:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import joblib
import hashlib
import redis
import os

app = FastAPI(title="User Safety: safe")

# Load model
model = joblib.load("model.joblib")

# Redis connection
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    db=0,
    decode_responses=True
)

class TextRequest(BaseModel):
    text: str

def get_cache_key(text: str) -> str:
    return "safety:" + hashlib.sha256(text.encode()).hexdigest()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict")
def predict(request: TextRequest):
    key = get_cache_key(request.text)
    cached = redis_client.get(key)
    if cached:
        return {"text": request.text, "toxic_probability": float(cached), "source": "cache"}

    proba = model.predict_proba([request.text])[0][1]
    redis_client.setex(key, 3600, str(proba))  # cache 1 hour
    return {"text": request.text, "toxic_probability": float(proba), "source": "model"}
```

### 4. Adding Structured Logging and Metrics

Extend `app.py` with logging and Prometheus metrics (install `prometheus_client`):

```python
import logging
from prometheus_client import Counter, Histogram, generate_latest
from fastapi import Response

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("safety")

REQUEST_COUNT = Counter("safety_requests_total", "Total requests", ["endpoint"])
PREDICTION_TIME = Histogram("safety_prediction_seconds", "Prediction latency")

@app.post("/predict")
def predict(request: TextRequest):
    REQUEST_COUNT.labels(endpoint="/predict").inc()
    with PREDICTION_TIME.time():
        # ... existing logic ...
```

### 5. Dockerization

Create a `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

And a `requirements.txt`:

```
fastapi==0.104.1
uvicorn==0.24.0
redis==5.0.1
scikit-learn==1.3.2
pandas==2.1.4
numpy==1.26.2
joblib==1.3.2
prometheus-client==0.19.0
```

Build and run:

```bash
docker build -t user-safety-safe .
docker run -p 8000:8000 -e REDIS_HOST=host.docker.internal user-safety-safe
```

## Running and Testing It

Once the container is up, verify the service:

```bash
curl -X POST http://localhost:8000/predict -H "Content-Type: application/json" -d '{"text":"You are an idiot"}'
```

Expected output:

```json
{"text":"You are an idiot","toxic_probability":0.92,"source":"model"}
```

Repeat the request; the second call should hit the cache (`"source":"cache"`). Check health:

```bash
curl http://localhost:8000/health
```

For automated testing, add a simple `pytest` file:

```python
# test_app.py
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200

def test_predict():
    r = client.post("/predict", json={"text":"I hate you"})
    assert r.status_code == 200
    assert "toxic_probability" in r.json()
```

Run with `pytest -v`.

## Extending It: Your Roadmap to Senior-Level

Take this prototype from “toy” to “production‑ready” with these concrete upgrades:

1. **Persist predictions in PostgreSQL** – store full request/response pairs for audit and offline model retraining, using SQLAlchemy or asyncpg.
2. **Horizontal scaling with Kubernetes** – deploy the FastAPI pod behind a Deployment and expose via a Service; use a Redis cluster for shared cache.
3. **Full observability stack** – ship logs to Loki, trace requests with Jaeger, and build Grafana dashboards from Prometheus metrics.
4. **Fault‑tolerant model serving** – wrap the model call in a retry with exponential backoff and a circuit‑breaker (e.g., `py-breaker`) to prevent cascading failures.
5. **Load testing with k6** – script realistic traffic patterns, measure p95 latency, and tune Redis TTL and pool sizes.
6. **Model serving with Triton Inference Server** – containerize the model, serve via gRPC, and leverage concurrent model execution for higher throughput.

Each upgrade directly maps to a concern that senior engineers handle daily: data durability, multi‑tenant scaling, debugging in production, resilience under load, and performance benchmarking.

## Key Takeaways

- **Ship a working service** – a FastAPI + Redis + scikit‑learn stack is a concrete proof of end‑to‑end system ownership.
- **Showcase API design** – clean endpoints, input validation, and caching demonstrate production‑grade thinking.
- **Highlight ML integration** – training and serving a model behind HTTP bridges the gap between data science and backend engineering.
- **Containerize for reproducibility** – Docker packaging proves you can deliver software that runs anywhere.
- **Add observability** – metrics and logging are no longer optional; they signal readiness for on‑call duties.
- **Plan for scale** – a roadmap of persistence, Kubernetes, and fault tolerance shows you can grow the project beyond a side‑gig.

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/) – the definitive guide to building async APIs with Python.
- [scikit‑learn User Guide](https://scikit-learn.org/stable/user_guide.html) – deep dive into pipelines, vectorizers, and model evaluation.
- [Redis Commands Reference](https://redis.io/docs/latest/) – everything you need to know about caching strategies and data structures.
- [Prometheus Instrumentation](https://prometheus.io/docs/latest/instrumentation/) – learn how to expose metrics that feed Grafana dashboards.
- [Kubernetes Basics](https://kubernetes.io/docs/tutorials/kubernetes-basics/) – the canonical walkthrough for deploying containerized services.
- [Toxic Comments Dataset (Kaggle)](https://www.kaggle.com/datasets/justmeantoxicity/toxic-comments-train) – a real‑world dataset for training toxicity classifiers.