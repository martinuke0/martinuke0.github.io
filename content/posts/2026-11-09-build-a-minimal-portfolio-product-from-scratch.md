---
title: "Build a Minimal Portfolio Product from Scratch"
date: "2026-11-09T22:00:40.049"
draft: false
tags: ["portfolio", "side-project", "backend", "docker", "microservices"]
description: "Build a minimal portfolio product from scratch: a deployable micro‑service with API, CI, and observability, perfect for signaling engineering skill."
summary: "A step‑by‑step guide to building a minimal, deployable portfolio product that showcases real‑world engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-09-build-a-minimal-portfolio-product-from-scratch.svg"
  alt: "A sleek laptop displaying a code editor with a terminal output."
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a minimal, production‑ready micro‑service (Flask + Docker + GitHub Actions) that you can ship today. It demonstrates API design, containerisation, automated testing, and basic observability—exactly the kind of hands‑on work hiring managers look for in a portfolio project.

Building a personal portfolio piece that feels like real work is one of the most effective ways to signal engineering competence without needing a full‑time job. Hiring managers on LinkedIn and in technical interviews want to see that you can take an idea, package it, ship it, and iterate on it. The project we’ll create is a tiny but complete micro‑service: a JSON‑based “Hello, World” API with a health endpoint, containerised with Docker, CI‑tested via GitHub Actions, and instrumented with simple metrics. Along the way you’ll practice version‑controlled code, container best practices, and basic observability—skills that translate directly to roles in backend engineering, DevOps, and platform teams.

## Why This Project Stands Out on a CV

- **API design & HTTP semantics** – You’ll define routes, request/response models, and status codes, showing you can build consumable services.  
- **Containerisation** – Dockerising the app demonstrates knowledge of isolated environments, multi‑stage builds, and reproducible deployments.  
- **CI/CD pipeline** – GitHub Actions workflows that run tests, lint, and build images prove you can automate quality gates.  
- **Observability basics** – Adding a health check and Prometheus‑compatible metrics gives you a foothold into monitoring patterns used in production.  
- **Git‑first workflow** – Using pull requests, code review, and branch protection mirrors industry‑standard collaboration.

The project signals readiness for backend, full‑stack, or platform engineering roles where you’ll be expected to ship code, keep it running, and instrument it for health checks.

## Architecture Overview

The system consists of a single Python process running Flask, wrapped by Docker, with optional health‑check and metrics endpoints. A minimal GitHub Actions pipeline builds, tests, and pushes the image.  

```
+----------------+      +-------------------+      +-------------------+
|  Developer     | ---> |   GitHub repo     | ---> |   Docker image    |
|  (code, PRs)   |      |   (source)        |      |   (build, push)   |
+----------------+      +-------------------+      +-------------------+
                                         |
                                         v
+----------------+      +-------------------+      +-------------------+
|   Docker run   | ---> |   Flask API       | ---> |   Health / Metrics |
|   (container)  |      |   (Python)        |      |   endpoints       |
+----------------+      +-------------------+      +-------------------+
```

- **Flask app** (`app.py`) – Exposes `/` (welcome) and `/healthz` (simple 200 OK).  
- **Dockerfile** – Multi‑stage build: install dependencies, copy source, run with `gunicorn` for modest concurrency.  
- **GitHub Actions** – Lint (`flake8`), test (`pytest`), build image, push to Docker Hub (or GitHub Packages).  
- **Health endpoint** – Used by orchestrators (Kubernetes, Docker Compose) to verify liveness.  

This one‑component architecture is deliberately simple, yet each piece mirrors patterns you’ll encounter in larger systems.

## Building It Step by Step

### Step 1 – Initialise the repository

```bash
mkdir portfolio-product && cd portfolio-product
git init
```

Create a `README.md` with a brief description; this will be the first file hiring managers see.

### Step 2 – Write the Flask application (`app.py`)

```python
"""Minimal Flask micro‑service for a portfolio project."""
from flask import Flask, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return jsonify({"message": "Hello, portfolio!"}), 200

@app.route("/healthz", methods=["GET"])
def health():
    """Kubernetes‑style health check."""
    return "", 200

if __name__ == "__main__":
    # Development server; production uses gunicorn
    app.run(host="0.0.0.0", port=8080)
```

*Why it matters:* The code shows proper JSON responses, status codes, and a health endpoint that container orchestrators expect.

### Step 3 – Add a `requirements.txt`

```text
Flask==2.3.3
gunicorn==21.2.0
pytest==7.4.3
flake8==4.0.1
```

These pins ensure reproducible builds.

### Step 4 – Write tests (`tests/test_app.py`)

```python
import pytest
from app import app

client = app.test_client()

def test_index():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"message": "Hello, portfolio!"}

def test_health():
    resp = client.get("/healthz")
    assert resp.status_code == 200
```

*Why it matters:* Automated tests give you confidence that changes don’t break the API—exactly what a CI pipeline validates.

### Step 5 – Create a `Dockerfile`

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

# Install dependencies in a virtual env
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Production stage: use gunicorn for concurrency
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /app /app
ENV PYTHONUNBUFFERED=1
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8080", "app:app"]
```

*Why it matters:* Multi‑stage builds keep the final image lean, and gunicorn illustrates production‑grade WSGI serving.

### Step 6 – Add a `.github/workflows/ci.yml` for CI/CD

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test-and-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Lint with flake8
        run: |
          flake8 . --count --show --select=E9,F6,F8,W501

      - name: Run tests
        run: |
          pytest

      - name: Build Docker image
        run: |
          docker build -t your-docker-username/portfolio-product:{{ github.sha }} .

      - name: Log in to Docker Hub
        uses: docker/login-action@v2
        with:
          username: your-docker-username
          password: ${{ secrets.DOCKER_TOKEN }}

      - name: Push Docker image
        run: |
          docker push your-docker-username/portfolio-product:{{ github.sha }}
```

*Why it matters:* A single YAML file automates linting, testing, and container publishing—exactly the pipeline expectations for junior‑to‑mid level roles.

### Step 7 – Run locally

```bash
docker build -t portfolio-product .
docker run -p 8080:8080 portfolio-product
```

Visit `http://localhost:8080/` and `http://localhost:8080/healthz` to verify both endpoints return the expected JSON and `200 OK`.

## Running and Testing It

1. **Local Python run** (for quick iteration):

   ```bash
   python -m pip install -r requirements.txt
   python app.py
   ```

   Then curl the endpoints:

   ```bash
   curl http://127.0.0.1:8080/
   curl http://127.0.0.1:8080/healthz
   ```

2. **Docker run** (full container experience):

   ```bash
   docker run -d -p 8080:8080 portfolio-product
   curl http://localhost:8080/healthz   # should return 200 with no body
   ```

3. **GitHub Actions** – Push to `main`; the workflow will run lint, tests, and build the image. Check the “Actions” tab for pass/fail status.

4. **Verification** – After the workflow succeeds, pull the image and run it to confirm the same endpoints work in the container.

## Extending It: Your Roadmap to Senior‑Level

1. **Add persistence with SQLite or PostgreSQL** – Store user‑generated data and demonstrate ORM usage (e.g., SQLAlchemy). *Matters because real services almost always need a data layer.*  
2. **Instrument with OpenTelemetry** – Export traces and metrics to a local Jaeger or Prometheus instance. *Matters for observability in microservice environments.*  
3. **Deploy to a cloud platform** – Use GCP Cloud Run, AWS Fargate, or Azure Container Apps with a managed database. *Matters to show you can move from local to production.*  
4. **Implement rate limiting & authentication** – Employ Flask‑Limiter and JWT validation. *Matters for production‑grade API security.*  
5. **Add a CI gate for security scanning** – Integrate `bandit` for Python security issues and `trivy` for container vulnerability checks. *Matters because supply‑chain security is a hiring priority.*  
6. **Write benchmarking scripts** – Use `locust` or `wrk` to measure throughput and latency under load. *Matters to quantify performance and discuss scaling trade‑offs.*

Each upgrade follows a clear, one‑line rationale, turning the toy project into a portfolio piece that mirrors the complexity of senior‑level engineering work.

## Key Takeaways

- A minimal, containerised micro‑service is a concrete way to demonstrate API design, DevOps pipelines, and observability.  
- Docker multi‑stage builds and GitHub Actions CI/CD are industry‑standard patterns you can list on a CV.  
- Health endpoints and basic metrics give you a foothold into monitoring systems used in production.  
- Incremental upgrades (persistence, tracing, cloud deployment) map directly to senior‑level responsibilities.  
- Real, runnable code (Flask, Python, Docker, YAML) makes the project interview‑ready and instantly verifiable.

## Further Reading

- [Flask documentation – Quickstart](https://flask.palletsprojects.com/en/3.0.x/quickstart/) – the canonical guide for building the app.  
- [Dockerfile reference](https://docs.docker.com/engine/reference/builder/) – explains the multi‑stage build pattern used.  
- [GitHub Actions workflow syntax](https://docs.github.com/en/actions/using-workflows) – for customising the CI pipeline.  
- [OpenTelemetry Python client](https://opentelemetry.io/docs/instrumentation/python/) – the primary source for adding tracing and metrics.  
- [Prometheus node exporter metrics](https://prometheus.io/docs/guides/node-exporter/) – if you want to expose the health endpoint as a metric.  
- [SQLAlchemy ORM documentation](https://docs.sqlalchemy.org/en/20/orm/tutorial.html) – for the persistence upgrade path.  

---