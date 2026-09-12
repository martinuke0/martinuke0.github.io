

---
title: "Zero to Portfolio: Building a Systems-Ready CV Side Project"
date: "2026-09-12T03:01:11.782"
draft: false
tags: ["portfolio", "systems", "engineering", "Hugo", "career", "devops"]
description: "A practical guide to building a portfolio site that showcases real systems skills, with runnable code and production-grade extensions."
summary: "Learn how to build a portfolio/CV side project from scratch that signals genuine systems engineering expertise to hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-zero-to-portfolio-building-a-systems-ready-cv-side-project.svg"
  alt: "A sleek dashboard displaying project metrics"
  caption: ""
  relative: false
---

> **TL;DR** — Build a lightweight, containerized portfolio service that serves your CV as JSON, expose it via a simple frontend, and ship it with CI/CD, observability, and horizontal scaling hooks. This project demonstrates end‑to‑end systems thinking, from API design to deployment, and gives hiring managers a concrete artifact to evaluate your engineering judgment.

A portfolio that merely lists technologies is easy to overlook. What stands out is a *running system* that shows you can design, implement, operate, and evolve a service in a production‑like environment. In this guide you will build a personal “CV API” backed by a small FastAPI service, containerize it with Docker, orchestrate it with Kubernetes, and wire it to a static frontend. The result is a deployable artifact that proves you understand the full software‑delivery lifecycle.

## Why This Project Stands Out on a CV

- **End‑to‑end ownership** – You will write the API, the data model, the container, the CI pipeline, and the monitoring config. Recruiters see a candidate who can ship and maintain a service, not just write libraries.
- **Systems thinking** – By adding horizontal scaling, fault tolerance, and observability later, you demonstrate awareness of reliability, performance, and cost—skills that map directly to senior or staff‑level roles.
- **Concrete evidence** – A live URL (or a Docker image) is far more persuasive than a bullet list. Hiring managers can curl your endpoint, inspect the OpenAPI spec, and watch the Grafana dashboard.
- **Toolchain fluency** – The project uses FastAPI, Docker, Kubernetes, GitHub Actions, Prometheus, and Grafana. These are the same tools used in many production environments, showing you can operate in the real world.

## Architecture Overview

The system is composed of four layers:

1. **Data layer** – A SQLite database (or Postgres in later extensions) stores CV entries (experience, education, projects).  
2. **API layer** – A FastAPI service exposes `/cv` endpoints, validates input with Pydantic, and serves JSON.  
3. **Frontend** – A static HTML/JS page fetches the API and renders a clean résumé. It is built with plain JavaScript, no build step required.  
4. **Ops layer** – Docker containers, a Kubernetes Deployment, a GitHub Actions CI pipeline, and Prometheus/Grafana for metrics.

```
┌─────────────┐      ┌───────────────┐      ┌──────────────┐
│   Browser   │◄────►│  FastAPI app  │◄────►│   SQLite     │
│   (static)  │      │  (container)  │      │   (volume)   │
└──────┬──────┘      └───────┬───────┘      └──────────────┘
       │                      │
       │   HTTP (JSON)        │   /metrics (Prometheus)
       │                      │
       ▼                      ▼
┌──────────────────────────────────────────────┐
│          Kubernetes cluster (minikube)       │
│  ┌─────────────┐   ┌─────────────────────┐   │
│  │  Deployment │   │  Service (NodePort) │   │
│  └─────────────┘   └─────────────────────┘   │
└──────────────────────────────────────────────┘
```

## Building It Step by Step

### 1. Scaffold the project

Create a directory `cv‑service` and initialize a Python virtual environment.

```bash
mkdir cv-service && cd cv-service
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn pydantic sqlite3
```

### 2. Define the data model

Create `models.py`:

```python
from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class Experience(BaseModel):
    company: str
    title: str
    start: date
    end: Optional[date] = None
    description: str

class Education(BaseModel):
    institution: str
    degree: str
    start: date
    end: Optional[date] = None

class Project(BaseModel):
    name: str
    description: str
    url: Optional[str] = None

class CV(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    summary: str
    experience: List[Experience]
    education: List[Education]
    projects: List[Project]
```

### 3. Implement the API

`api.py`:

```python
from fastapi import FastAPI, HTTPException
from models import CV
import sqlite3
from typing import List

app = FastAPI(title="CV API", version="1.0.0")

def get_db():
    conn = sqlite3.connect("cv.db")
    conn.row_factory = sqlite3.Row
    return conn

# Seed data (run once manually)
def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS cv (
        id INTEGER PRIMARY KEY,
        name TEXT,
        email TEXT,
        phone TEXT,
        summary TEXT
    );
    CREATE TABLE IF NOT EXISTS experience (
        id INTEGER PRIMARY KEY,
        cv_id INTEGER,
        company TEXT,
        title TEXT,
        start TEXT,
        end TEXT,
        description TEXT,
        FOREIGN KEY (cv_id) REFERENCES cv(id)
    );
    CREATE TABLE IF NOT EXISTS education (
        id INTEGER PRIMARY KEY,
        cv_id INTEGER,
        institution TEXT,
        degree TEXT,
        start TEXT,
        end TEXT,
        FOREIGN KEY (cv_id) REFERENCES cv(id)
    );
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY,
        cv_id INTEGER,
        name TEXT,
        description TEXT,
        url TEXT,
        FOREIGN KEY (cv_id) REFERENCES cv(id)
    );
    """)
    conn.commit()
    conn.close()

@app.get("/cv", response_model=CV)
def read_cv():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM cv LIMIT 1")
    row = cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="CV not found")
    cv = dict(row)
    cur.execute("SELECT * FROM experience WHERE cv_id = ?", (row["id"],))
    cv["experience"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM education WHERE cv_id = ?", (row["id"],))
    cv["education"] = [dict(r) for r in cur.fetchall()]
    cur.execute("SELECT * FROM projects WHERE cv_id = ?", (row["id"],))
    cv["projects"] = [dict(r) for r in cur.fetchall()]
    conn.close()
    return cv
```

Run `init_db()` once to create tables, then insert a sample row manually or via a small script.

### 4. Add a simple frontend

Create `static/index.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>My CV</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 2rem; }
    h1 { color: #2c3e50; }
    section { margin-bottom: 1.5rem; }
  </style>
</head>
<body>
  <div id="cv"></div>
  <script>
    fetch('/cv')
      .then(r => r.json())
      .then(data => {
        const container = document.getElementById('cv');
        container.innerHTML = `
          <h1>${data.name}</h1>
          <p>${data.summary}</p>
          <section><h2>Experience</h2>
            ${data.experience.map(e => `
              <div>
                <strong>${e.title}</strong> at ${e.company} (${e.start} – ${e.end || 'present'})
                <p>${e.description}</p>
              </div>`).join('')}
          </section>
          <section><h2>Education</h2>
            ${data.education.map(e => `
              <div>
                <strong>${e.degree}</strong> – ${e.institution} (${e.start} – ${e.end || 'present'})
              </div>`).join('')}
          </section>
          <section><h2>Projects</h2>
            ${data.projects.map(p => `
              <div>
                <strong>${p.name}</strong>: ${p.description}
                ${p.url ? `<a href="${p.url}" target="_blank">link</a>` : ''}
              </div>`).join('')}
          </section>`;
      });
  </script>
</body>
</html>
```

Mount the static files in FastAPI:

```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory="static"), name="static")
```

### 5. Containerize the service

`Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
EXPOSE 8000
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
```

`requirements.txt`:

```
fastapi==0.104.1
uvicorn==0.24.0
pydantic==2.5.0
```

`docker-compose.yml`:

```yaml
version: "3.8"
services:
  cv:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - .:/app
      - cv-data:/app/cv.db
volumes:
  cv-data:
```

### 6. Deploy to Kubernetes (optional but illustrative)

`k8s/deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cv-api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: cv-api
  template:
    metadata:
      labels:
        app: cv-api
    spec:
      containers:
      - name: cv-api
        image: myrepo/cv-service:latest
        ports:
        - containerPort: 8000
        env:
        - name: DATABASE_URL
          value: "sqlite:///app/cv.db"
---
apiVersion: v1
kind: Service
metadata:
  name: cv-api
spec:
  selector:
    app: cv-api
  ports:
  - port: 80
    targetPort: 8000
  type: NodePort
```

Apply with `kubectl apply -f k8s/`.

## Running and Testing It

1. **Local Docker run**  

   ```bash
   docker-compose up --build
   ```

   Visit `http://localhost:8000/static/index.html` to see the rendered CV, and `http://localhost:8000/cv` for the raw JSON.

2. **Smoke test with curl**  

   ```bash
   curl -s http://localhost:8000/cv | jq .
   ```

   Verify that all expected fields appear.

3. **Automated tests**  

   Create `test_api.py`:

   ```python
   from fastapi.testclient import TestClient
   from api import app

   client = TestClient(app)

   def test_get_cv():
       response = client.get("/cv")
       assert response.status_code == 200
       data = response.json()
       assert "name" in data
       assert isinstance(data["experience"], list)
   ```

   Run with `pytest -q`.

4. **CI pipeline**  

   `.github/workflows/ci.yml`:

   ```yaml
   name: CI
   on: [push, pull_request]
   jobs:
     build:
       runs-on: ubuntu-latest
       steps:
       - uses: actions/checkout@v4
       - name: Set up Python
         uses: actions/setup-python@v5
         with:
           python-version: "3.11"
       - name: Install dependencies
         run: |
           python -m pip install --upgrade pip
           pip install -r requirements.txt
           pip install pytest
       - name: Run tests
         run: pytest -q
       - name: Build Docker image
         run: docker build -t cv-service:latest .
   ```

## Extending It: Your Roadmap to Senior-Level

1. **Persist to PostgreSQL** – Replace SQLite with a managed Postgres instance (e.g., Cloud SQL, RDS). This introduces connection pooling, schema migrations (Alembic), and production‑grade durability.  
2. **Horizontal scaling** – Deploy the FastAPI pods behind a Kubernetes HPA (Horizontal Pod Autoscaler) that scales on CPU or custom metrics. Demonstrates stateless design and load‑balancing.  
3. **Observability** – Expose `/metrics` via `prometheus-client`, add a `ServiceMonitor`, and create Grafana dashboards for request latency, error rates, and DB query duration. Shows you can watch the system in real time.  
4. **Fault tolerance & retries** – Use `httpx` with exponential backoff when calling downstream services (e.g., a microservice for skill matching). Implement circuit‑breaker patterns with `pybreaker` to prevent cascading failures.  
5. **Benchmarking & performance tuning** – Load‑test with `locust` or `k6`, identify bottlenecks (e.g., N+1 queries), and add indexing or caching (Redis) to meet SLA targets.  
6. **Security hardening** – Add JWT authentication, rate limiting (e.g., `slowapi`), and scan the container image with `trivy`. Communicates that you care about data protection and compliance.

Each upgrade directly maps to a concern senior engineers handle daily: reliability, scalability, visibility, resilience, performance, and security.

## Key Takeaways

- Build a **complete, runnable artifact** rather than a static list of skills.  
- Use **industry‑standard tools** (FastAPI, Docker, Kubernetes, Prometheus, GitHub Actions) to signal production readiness.  
- Demonstrate **end‑to‑end ownership**: API, data, container, CI/CD, monitoring.  
- Plan **progressive extensions** that showcase senior‑level thinking (scaling, observability, fault tolerance).  
- Provide **evidence** (live endpoint, Docker image, Grafana dashboard) that hiring managers can explore.

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/) – official guide for building APIs with OpenAPI support.  
- [Kubernetes Concepts](https://kubernetes.io/docs/concepts/) – deep dive into pods, services, deployments, and scaling.  
- [Prometheus Monitoring](https://prometheus.io/docs/introduction/overview/) – how to instrument services and create alerts.  
- [GitHub Actions Guide](https://docs.github.com/en/actions) – automating CI/CD workflows.  
- [Designing Data‑Intensive Applications](https://www.oreilly.com/library/view/designing-data-intensive-applications/9781449337608/) – foundational reading for reliability and scalability.  

By following this guide, you will have a portfolio project that not only lists what you know but also proves you can operate a system in the real world.