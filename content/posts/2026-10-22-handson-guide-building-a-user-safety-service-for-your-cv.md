---
title: "Hands‑On Guide: Building a User Safety Service for Your CV"
date: "2026-10-22T18:02:23.915"
draft: false
tags: ["python", "fastapi", "opa", "cv", "portfolio"]
description: "Build a runnable User Safety service with FastAPI and OPA, demonstrating policy‑driven data validation and privacy checks for CV and hiring portfolios."
summary: "A hands‑on guide to building a policy‑driven User Safety service with FastAPI and OPA, perfect for a portfolio that signals real‑world engineering skill."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-22-handson-guide-building-a-user-safety-service-for-your-cv.svg"
  alt: "User safety service interface with policy icons"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you’ll build a runnable User Safety service using FastAPI and Open Policy Agent, validating user data against privacy policies and exposing a clean API for your CV.

Building a portfolio project that demonstrates real‑world systems skills is a powerful way to stand out to hiring managers. In this guide you’ll create a **User Safety service** that validates incoming user data (email, age, etc.) against configurable policies written in OPA’s Rego language, serves the decisions through a FastAPI endpoint, and includes tests, Docker‑ready deployment steps, and a clear roadmap for production‑grade extensions. The project is small enough to finish in a weekend yet extensible enough to discuss policy‑as‑code, API design, and observability—topics that recur in senior‑level engineering interviews.

## Why This Project Stands Out on a CV

- **Policy‑as‑code**: Writing Rego policies turns abstract safety rules into version‑controlled, testable artifacts—exactly the pattern used at companies like Stripe and HashiCorp.  
- **API design with FastAPI**: You’ll practice building OpenAPI‑compatible endpoints, request validation with Pydantic, and automatic interactive docs (`/docs`).  
- **OPA integration**: Demonstrates familiarity with decentralized policy evaluation, a skill increasingly demanded for RBAC, GDPR compliance, and feature flagging.  
- **Testing & CI**: Adding pytest tests and a simple GitHub Actions workflow shows you can ship reliable code, not just prototypes.  
- **Roles signaled**: Backend engineer, data‑privacy engineer, DevOps/SRE candidate, or any position that deals with user‑generated data and compliance.

The project therefore signals three overlapping competency areas—**secure data handling**, **policy‑driven architecture**, and **production‑ready software engineering**—making it a concise yet rich talking point for interviews.

## Architecture Overview

```mermaid
flowchart LR
    A[Client] -->|HTTP| B(FastAPI App)
    B -->|eval request| C[OPA Server]
    C -->|decision (safe/deny)| B
    B -->|JSON response| A
```

- **API Layer (`app.py`)**: FastAPI app exposing `/validate` that receives `{email, age}` and forwards the payload to OPA.  
- **Policy Engine (OPA)**: Evaluates Rego policies stored in `policy.rego`. OPA can run as a standalone binary or as a gRPC/HTTP sidecar; here we invoke the CLI for simplicity.  
- **Policy Store (`policy.rego`)**: Plain‑text Rego that defines what “safe” means (e.g., valid email format, minimum age).  
- **Test Harness (`tests/`)**: `pytest` cases that call the FastAPI endpoint and assert the policy decision, plus a `Makefile` target `test` that runs both unit and integration checks.

This tiny diagram captures the full request‑flow while staying lightweight enough to run on a laptop.

## Building It Step by Step

Below are **numbered steps** with **real, language‑tagged code snippets** you can copy‑paste.

### Step 1 – Scaffold the project

```bash
mkdir user-safety && cd user-safety
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install "fastapi[all]" uvicorn opa-python
```

### Step 2 – Write the Rego policy

Create `policy.rego`:

```rego
package user.safe

# Simple email‑format check + minimum age of 13
default safe = false

safe {
    valid_email := input.email =~ r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    age_ok := input.age >= 13
}
```

### Step 3 – Create the FastAPI application

`app.py`:

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import subprocess
import json

app = FastAPI(title="User Safety Service")

class ValidatePayload(BaseModel):
    email: str
    age: int

def _opa_evaluate(payload: dict) -> bool:
    """Call OPA CLI and return the `safe` boolean decision."""
    request_json = json.dumps(payload)
    result = subprocess.run(
        ["opa", "eval", "-i", "-", "data.user.safe", "input"],
        input=request_json,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(500, f"OPA error: {result.stderr}")
    # OPA prints JSON; extract the result
    decision = json.loads(result.stdout)
    return decision.get("result", {}).get("expressions", [{}])[0].get("value", False)

@app.post("/validate")
def validate(payload: ValidatePayload):
    safe = _opa_evaluate(payload.dict())
    return {"safe": safe, "email": payload.email, "age": payload.age}
```

### Step 4 – Run the service locally

```bash
uvicorn app:app --reload
```

Visit `http://127.0.0.1:8000/docs` to see the auto‑generated OpenAPI UI.

### Step 5 – Quick test with `curl`

```bash
curl -X POST http://127.0.0.1:8000/validate \
     -H "Content-Type: application/json" \
     -d '{"email":"alice@example.com","age":28}'
# Expected: {"safe":true,"email":"alice@example.com","age":28}
```

### Step 6 – Add a minimal pytest suite

Create `tests/test_app.py`:

```python
from fastapi.testclient import TestClient
from app import app

client = TestClient(app)

def test_valid_user():
    resp = client.post("/validate", json={"email":"bob@example.org","age":30})
    assert resp.status_code == 200
    data = resp.json()
    assert data["safe"] is True

def test_invalid_email():
    resp = client.post("/validate", json={"email":"not-an-email","age":20})
    assert resp.status_code == 200
    assert resp.json()["safe"] is False
```

Run with `pytest tests/ -v`.

## Running and Testing It

- **Local development**: `source venv/bin/activate && uvicorn app:app --reload`.  
- **Docker (optional)**: Create a `Dockerfile` that copies the venv, installs deps, and exposes port 8000. A `docker-compose.yml` can also spin up an OPA sidecar if you prefer an always‑running policy server.  
- **CI integration**: Add a GitHub Actions workflow `.github/workflows/ci.yml`:

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with: {python-version: "3.12"}
      - run: pip install -r requirements.txt
      - run: pytest -v
```

- **Manual verification**: Use the `/validate` endpoint with edge cases (missing fields, extremely old ages) to confirm the Rego logic behaves as expected.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence with PostgreSQL + Alembic** – Store each validation request and the policy decision for audit trails and compliance reporting.  
2. **Horizontal scaling with Kubernetes + OPA Gatekeeper** – Deploy the FastAPI service behind a Service, let OPA Gatekeeper enforce cluster‑wide policies, and scale pods via HPA.  
3. **Observability with OpenTelemetry & Prometheus** – Export request latency, policy‑eval duration, and success/failure rates; visualize in Grafana.  
4. **Fault tolerance with circuit breaking (PyRATELIMIT/Hystrix)** – Prevent cascading failures when OPA is slow or unavailable, gracefully degrading to a default “deny”.  
5. **Benchmarking with Locust** – Load‑test the `/validate` endpoint to measure throughput (requests/sec) and identify bottlenecks in the Rego evaluation path.  
6. **Multi‑tenant isolation via namespace‑based Rego policies** – Allow different client organizations to have their own safety rules while sharing the same codebase.

Each upgrade adds a concrete production‑grade capability while keeping the core project recognizable.

## Key Takeaways

- Writing policies in Rego turns ad‑hoc safety checks into version‑controlled, testable assets.  
- FastAPI + OPA gives you a minimal, standards‑compliant API that can be swapped for a gRPC/HTTP OPA server later.  
- Adding pytest and a CI workflow demonstrates that you ship reliable code, not just prototypes.  
- The project signals three overlapping skill sets—secure data handling, policy‑driven architecture, and production‑ready engineering—highly valued by hiring managers.  
- The roadmap upgrades (persistence, K8s scaling, observability, fault tolerance, benchmarking, multi‑tenant isolation) map directly to senior‑level responsibilities.  
- Even a small, runnable service can become a talking point that differentiates a CV in a crowded job market.

## Further Reading

- [Open Policy Agent Docs – “Getting Started”](https://www.openpolicyagent.org/docs/latest) – learn Rego syntax and OPA evaluation workflow.  
- [FastAPI Documentation](https://fastapi.tiangolo.com) – full reference for building the API, Pydantic models, and OpenAPI generation.  
- [PostgreSQL Documentation](https://www.postgresql.org/docs/) – guide for adding persistent storage and Alembic migrations.  
- [Kubernetes Official Docs – “Workloads”](https://kubernetes.io/docs/concepts/workloads/) – concepts for deploying the service and OPA Gatekeeper at scale.  
- [OPA Rego Playground](https://play.openpolicyagent.org) – interactive editor to test policies while you write them.  

---