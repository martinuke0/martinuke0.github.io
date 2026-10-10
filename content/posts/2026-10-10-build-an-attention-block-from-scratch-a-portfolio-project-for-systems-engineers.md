---
title: "Build an Attention Block from Scratch: A Portfolio Project for Systems Engineers"
date: "2026-10-10T21:01:18.967"
draft: false
tags: ["machine-learning", "systems", "portfolio", "transformer", "attention", "python"]
description: "A hands-on guide to building a scalable attention block from scratch, with real code, testing, and production extensions to showcase systems engineering skills."
summary: "Learn to implement a transformer attention block from scratch in Python, package it as a service, and extend it with production-grade features."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-10-build-an-attention-block-from-scratch-a-portfolio-project-for-systems-engineers.svg"
  alt: "A diagram of attention mechanism"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a transformer attention block from scratch in Python, packaging it as a FastAPI service, and adding production-grade extensions like horizontal scaling and observability. By the end, you have a portfolio project that demonstrates both ML implementation and systems engineering skills, appealing to hiring managers in AI infrastructure roles.

Building a portfolio project that catches the eye of hiring managers requires more than a tutorial follow-along. It needs to showcase *systems thinking* — the ability to take a core algorithm, turn it into a runnable service, and then harden it for production. In this guide, you’ll build an attention block (the core of modern transformers) from the ground up, wrap it in a lightweight API, and then extend it with the kind of scalability and resilience metrics that senior engineers care about. We’ll use Python, PyTorch, FastAPI, Docker, and Kubernetes — all tools you’ll find in real AI infrastructure teams.

## Why This Project Stands Out on a CV

Most candidates list “transformer” or “attention” on their résumé, but few can show the actual implementation or explain how it runs in a serving environment. This project demonstrates three layers of skill that hiring managers actively seek:

1. **Algorithmic depth** — You implement scaled dot-product attention and multi-head attention manually, proving you understand the math and not just the API call.
2. **Systems packaging** — You containerize the model, expose it via a production-grade web framework, and orchestrate it with Kubernetes. This signals you can ship ML models, not just train them.
3. **Production hardening** — You add horizontal scaling, observability, and fault tolerance. These are the topics that separate a “data scientist” from an “ML platform engineer.”

If you’re targeting roles like AI Infrastructure Engineer, ML Systems Engineer, or Platform Engineer, this project gives you concrete talking points: “I built a custom attention service that scales to X requests per second and emits Prometheus metrics.”

## Architecture Overview

The project is structured as a small microservice stack. Below is a high-level breakdown of the components and how they interact:

- **Attention Module** (`attention.py`) — The core logic. Implements `ScaledDotProductAttention` and `MultiHeadAttention` using only PyTorch tensor operations. No high-level transformer libraries.
- **Service API** (`api.py`) — A FastAPI application that exposes a `/score` endpoint. It accepts sequences of vectors and returns the attention-weighted output.
- **Container Runtime** (`Dockerfile`) — Packages the service with its dependencies into a Docker image, ensuring reproducibility.
- **Orchestration** (`k8s/`) — Kubernetes manifests (Deployment, Service, HorizontalPodAutoscaler) that scale the service based on CPU or custom metrics.
- **Observability** (`metrics.py`) — Exposes Prometheus metrics (latency, request count, error rate) via a `/metrics` endpoint.
- **Benchmarking** (`bench.py`) — A Locust load test script that simulates real traffic and measures throughput and latency.

```
Client → LoadBalancer → [Pod: FastAPI + Attention] → Prometheus (metrics)
                          ↓
                     Redis (optional cache)
```

In its basic form, the service runs in a single container. The extensions later add a Redis cache, circuit breakers, and automated scaling.

## Building It Step by Step

### Step 1: Set up the project

Create a new directory and set up a Python virtual environment. We’ll use PyTorch for tensor operations and FastAPI for serving.

```bash
mkdir attention-service
cd attention-service
python -m venv venv
source venv/bin/activate
pip install torch fastapi uvicorn prometheus-client locust docker
```

### Step 2: Implement the attention module

Create `attention.py`. This file contains the mathematical core of the transformer.

```python
import torch
import torch.nn as nn
import torch.nn.functional as F

class ScaledDotProductAttention(nn.Module):
    def __init__(self, d_k: int, dropout: float = 0.1):
        super().__init__()
        self.d_k = d_k
        self.dropout = nn.Dropout(dropout)

    def forward(self, q: torch.Tensor, k: torch.Tensor, v: torch.Tensor,
                mask: torch.Tensor = None) -> torch.Tensor:
        """
        Computes attention scores, applies softmax, and returns weighted sum.
        Args:
            q: Query tensor (batch_size, seq_len, d_k)
            k: Key tensor   (batch_size, seq_len, d_k)
            v: Value tensor (batch_size, seq_len, d_v)
            mask: Optional attention mask (batch_size, seq_len)
        """
        scores = torch.matmul(q, k.transpose(-2, -1)) / torch.sqrt(torch.tensor(self.d_k, dtype=torch.float32))
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float('-inf'))
        attn = F.softmax(scores, dim=-1)
        attn = self.dropout(attn)
        return torch.matmul(attn, v)

class MultiHeadAttention(nn.Module):
    def __init__(self, d_model: int, num_heads: int = 8, d_k: int = 64, dropout: float = 0.1):
        super().__init__()
        assert d_model == num_heads * d_k, "d_model must be divisible by num_heads"
        self.num_heads = num_heads
        self.d_k = d_k
        self.W_q = nn.Linear(d_model, d_model)
        self.W_k = nn.Linear(d_model, d_model)
        self.W_v = nn.Linear(d_model, d_model)
        self.W_o = nn.Linear(d_model, d_model)
        self.attention = ScaledDotProductAttention(d_k, dropout)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: torch.Tensor = None) -> torch.Tensor:
        batch_size, seq_len, _ = x.shape
        # Linear projections and reshape for multi-head
        q = self.W_q(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        k = self.W_k(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        v = self.W_v(x).view(batch_size, seq_len, self.num_heads, self.d_k).transpose(1, 2)
        # Apply attention across all heads
        if mask is not None:
            mask = mask.unsqueeze(1)  # add head dimension
        out = self.attention(q, k, v, mask)
        # Concatenate heads and project
        out = out.transpose(1, 2).contiguous().view(batch_size, seq_len, -1)
        out = self.dropout(self.W_o(out))
        return out
```

### Step 3: Build the FastAPI service

Create `api.py`. This file wires the attention module to a REST endpoint and adds Prometheus metrics.

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch
import time
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from attention import MultiHeadAttention

app = FastAPI(title="Attention Service")

# Prometheus metrics
REQUEST_COUNT = Counter("attention_request_total", "Total requests to attention service")
REQUEST_LATENCY = Histogram("attention_request_latency_seconds", "Latency of attention requests")

# Initialize model (small configuration for demo)
model = MultiHeadAttention(d_model=512, num_heads=8, d_k=64)
model.eval()

class AttentionRequest(BaseModel):
    sequence: list  # list of lists (batch_size, seq_len, d_model)
    mask: list = None

@app.get("/metrics")
async def metrics():
    return generate_latest()

@app.post("/score")
async def score(req: AttentionRequest):
    with REQUEST_LATENCY.time():
        try:
            x = torch.tensor(req.sequence, dtype=torch.float32)
            mask = torch.tensor(req.mask, dtype=torch.bool) if req.mask else None
            with torch.no_grad():
                out = model(x, mask)
            REQUEST_COUNT.inc()
            return {"output": out.tolist()}
        except Exception as e:
            REQUEST_COUNT.inc()
            raise HTTPException(status_code=500, detail=str(e))
```

### Step 4: Containerize the service

Create a `Dockerfile` to ensure the environment is reproducible.

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

Create `requirements.txt`:

```
torch==2.0.1
fastapi==0.95.0
uvicorn==0.22.0
prometheus-client==0.16.0
```

Build and run locally:

```bash
docker build -t attention-service .
docker run -p 8000:8000 attention-service
```

### Step 5: Add Kubernetes manifests

Create a directory `k8s` with `deployment.yaml`, `service.yaml`, and `hpa.yaml`.

`deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: attention-service
spec:
  replicas: 2
  selector:
    matchLabels:
      app: attention-service
  template:
    metadata:
      labels:
        app: attention-service
    spec:
      containers:
      - name: attention-service
        image: attention-service:latest
        ports:
        - containerPort: 8000
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "1"
            memory: "1Gi"
```

`service.yaml`:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: attention-service
spec:
  selector:
    app: attention-service
  ports:
  - port: 80
    targetPort: 8000
  type: LoadBalancer
```

`hpa.yaml`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: attention-service
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: attention-service
  minReplicas: 2
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

### Local execution

If you prefer not to use Docker, you can run the service directly:

```bash
uvicorn api:app --reload
```

### Smoke test

Send a sample request with `curl`. First, generate a random sequence in Python:

```python
import requests, json, random
seq = [[random.random() for _ in range(512)] for _ in range(16)]
r = requests.post("http://localhost:8000/score", json={"sequence": seq})
print(r.status_code, len(r.json()["output"]))
```

### Load testing with Locust

Create `bench.py`:

```python
from locust import HttpUser, task, between
import random

class AttentionUser(HttpUser):
    wait_time = between(1, 5)

    @task
    def send_sequence(self):
        seq = [[random.random() for _ in range(512)] for _ in range(16)]
        self.client.post("/score", json={"sequence": seq})
```

Run Locust:

```bash
locust -f bench.py --host http://localhost:8000
```

Open the web UI at `http://localhost:8089`, spawn users, and observe the request latency histogram. A healthy service should maintain p99 latency under 200 ms at 100 concurrent users.

## Extending It: Your Roadmap to Senior-Level

The base project proves you can build and serve an attention block. The following upgrades transform it into a production-grade system that senior hiring managers will recognize.

1. **Add a Redis cache** — Store frequently used attention outputs to reduce GPU/CPU load. *Why it matters:* Caching is a standard technique for latency-sensitive ML services and demonstrates awareness of cost/performance trade-offs.
2. **Implement circuit breakers with retries** — Use a library like `py-breaker` to fail fast when the model service is unhealthy. *Why it matters:* Fault tolerance is critical in distributed systems; this shows you can prevent cascading failures.
3. **Ship custom metrics to Prometheus and Grafana** — Beyond request counts, track batch size distribution, GPU utilization (if applicable), and queue depth. *Why it matters:* Observability is a cornerstone of SRE culture and enables capacity planning.
4. **Enable horizontal pod autoscaling based on custom metrics** — Expose a custom metric (e.g., request queue length) and configure the HPA to scale on it. *Why it matters:* Real-world traffic is bursty; custom autoscaling proves you understand workload characteristics.
5. **Add model versioning with MLflow** — Log the attention model’s configuration and weights to an MLflow tracking server. *Why it matters:* Model governance and reproducibility are required in regulated industries.
6. **Benchmark with GPU vs. CPU** — Use `torch.cuda.is_available()` to compare throughput and write a short report. *Why it matters:* Showing you can quantify hardware advantages is a hallmark of an infrastructure engineer.

Each of these can be added incrementally; commit them to your GitHub repo and document the performance impact.

## Key Takeaways

- Implementing attention from scratch proves you understand the algorithm, not just the library.
- Packaging it as a FastAPI service demonstrates the ability to ship ML models as software.
- Adding Kubernetes, Prometheus, and caching shows you can operate a scalable, observable system.
- The extension roadmap gives you concrete talking points for senior-level interviews.
- This project is modular: you can swap the attention implementation for other primitives (e.g., LSTM, graph neural network) while keeping the serving infrastructure.

## Further Reading

- **Attention Is All You Need** — The original transformer paper that introduced the scaled dot-product attention mechanism: [arxiv.org/abs/1706.03762](https://arxiv.org/abs/1706.03762)
- **PyTorch Documentation** — Official guides on `nn.MultiheadAttention` and tensor operations: [pytorch.org/docs/stable/nn.html](https://pytorch.org/docs/stable/nn.html)
- **FastAPI Documentation** — Building production-ready APIs with dependency injection and OpenAPI: [fastapi.tiangolo.com](https://fastapi.tiangolo.com)
- **Kubernetes Horizontal Pod Autoscaling** — Deep dive into custom metrics and scaling algorithms: [kubernetes.io/docs/tasks/autoscale/horizontal-pod-autoscale](https://kubernetes.io/docs/tasks/autoscale/horizontal-pod-autoscale/)
- **Prometheus Client Python** — Instrumenting services with histograms and counters: [github.com/prometheus/client_python](https://github.com/prometheus/client_python)