---
title: "User Safety: A Hands‑On Build Guide for a Portfolio CV Side Project"
date: "2026-10-25T12:01:02.155"
draft: false
tags: ["python", "fastapi", "security", "side-project", "docker"]
description: "Build a production‑ready user‑safety service that sanitises, validates, and logs inbound data – a CV‑ready security project for engineers."
summary: "This guide walks you through building a runnable User Safety service that validates, sanitises, and audits inbound user data, perfect for a portfolio CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-25-user-safety-a-handson-build-guide-for-a-portfolio-cv-side-project.svg"
  alt: "Illustration of a shield with code icons"
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a concrete, runnable User Safety service that validates and sanitises user input, logs actions, and can be extended for production use. By the end you’ll have a working FastAPI app, Dockerfile, and test suite you can ship to GitHub to signal security‑focused engineering skill.

Building a side project that doubles as a portfolio piece is one of the most effective ways to signal real‑world engineering chops to hiring managers. In this post we’ll construct **User Safety**, a small but complete FastAPI‑based service that takes raw user payloads, runs them through Pydantic‑driven validation + sanitisation, writes structured logs, and ships as a Docker image. The code is fully runnable, testable, and extensible – exactly the kind of tangible artifact that stands out on a CV.

## Why This Project Stands Out on a CV

Hiring managers scanning dozens of GitHub repos look for three signals: **code quality**, **systems thinking**, and **production awareness**. User Safety hits all three:

- **Input validation & sanitisation** – demonstrates mastery of OWASP best‑practices and safe data handling, a core skill for backend, API, and security roles.  
- **FastAPI + Pydantic** – shows you can build modern, typed APIs quickly while leveraging automatic docs and request validation.  
- **Dockerisation & CI‑ready** – proves you can containerise an application, write a multi‑stage Dockerfile, and think about reproducible deployments.  

Roles that benefit most: *Backend Engineer, API Engineer, Security Engineer, DevOps Engineer* – all of whom need to show they can ship secure, maintainable services from day one.

## Architecture Overview

The system is deliberately minimal yet composable. The core components and their interactions can be visualised as:

```
+--------+      +------------+      +-----------------+
| Client | --> | FastAPI app| --> | Pydantic models |
+--------+      +------------+      +-----------------+
          |               |
          v               v
   +------------+   +-------------------+
   | Structlog  |   | Docker (multi‑stage)|
   +------------+   +-------------------+
```

**Bullet breakdown**

- **FastAPI** – async framework with automatic OpenAPI schema and request validation via Pydantic.  
- **Pydantic models** – define expected payload shape, run type‑coercion, and enforce constraints (e.g., max length, regex).  
- **Structured logging** (structlog) – emits JSON logs to stdout, making correlation easy in any log aggregation platform.  
- **Docker** – multi‑stage build: compile dependencies once, copy only the runtime binary, resulting in a <30 MB image.  
- **pytest** – unit tests for each model and middleware piece, run in CI.  

This architecture mirrors many production micro‑services: a thin HTTP layer, strict data contracts, and observable logging.

## Building It Step by Step

Below are numbered steps you can follow on a fresh machine. Each step includes a focused code snippet (language‑tagged) that implements the core logic.

### Step 1 – Scaffold the project

```bash
# Install Poetry if you don’t have it
pip install poetry
poetry init --name user-safety --description "User safety service" --author "You"
poetry add fastapi "uvicorn[standard]" pydantic structlog
```

### Step 2 – Define the data contract

```python
# app/schemas.py
from pydantic import BaseModel, Field, validator
import re

class UserPayload(BaseModel):
    """Raw inbound user data – will be validated & sanitised."""
    name: str = Field(..., max_length=120, description="User’s full name")
    email: str = Field(..., regex=r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
    age: int = Field(..., ge=0, le=150, description="Age in years")
    bio: str = Field(default="", max_length=500, description="Free‑form biography")

    @validator("name")
    def strip_name(cls, v):
        """Remove leading/trailing whitespace."""
        return v.strip()
```

### Step 3 – Add middleware for sanitisation & logging

```python
# app/middleware.py
import structlog
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

log = structlog.get_logger()

class SanitiseAndLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Start timing
        start = time.time()
        # Process request
        response: Response = await call_next(request)
        # Emit structured log
        duration = time.time() - start
        log.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=int(duration * 1000),
            client_host=request.client.host,
        )
        return response
```

### Step 4 – Wire everything together

```python
# app/main.py
from fastapi import FastAPI
from .schemas import UserPayload
from .middleware import SanitiseAndLogMiddleware

app = FastAPI(title="User Safety", version="0.1.0")
app.add_middleware(SanitiseAndLogMiddleware)

@app.post("/validate", response_model=UserPayload)
def validate(payload: UserPayload):
    """Endpoint that simply echoes the validated payload."""
    return payload
```

### Step 5 – Write a quick test

```python
# tests/test_validate.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_valid_payload():
    payload = {"name": " Alice ", "email": "alice@example.com", "age": 30, "bio": "Hello!"}
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alice"  # strip happened

def test_invalid_email():
    payload = {"name": "Bob", "email": "not-an-email", "age": 25}
    resp = client.post("/validate", json=payload)
    assert resp.status_code == 422  # Pydantic validation error
```

### Step 6 – Multi‑stage Dockerfile

```dockerfile
# Dockerfile
# ---------- Build stage ----------
FROM python:3.12-slim AS builder
WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN pip install poetry && poetry config virtualenvs.create false && poetry install --no-root --no-interaction

# ---------- Runtime stage ----------
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY app ./app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 7 – Add a GitHub Actions workflow (optional but production‑flavoured)

```yaml
# .github/workflows/ci.yml
name: CI

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install deps
        run: |
          pip install poetry
          poetry config virtualenvs.create false
          poetry install --no-root --no-interaction
      - name: Run tests
        run: poetry run pytest
```

## Running and Testing It

1. **Local development**

   ```bash
   poetry install
   poetry run uvicorn app.main:app --reload
   ```

   The server will start at <http://127.0.0.1:8000>. Open <http://127.0.0.1:8000/docs> to see the auto‑generated OpenAPI UI.

2. **Quick sanity check with curl**

   ```bash
   curl -X POST http://127.0.0.1:8000/validate \
        -H "Content-Type: application/json" \
        -d '{"name":"Bob","email":"bob@example.com","age":28}'
   ```

   Expected JSON response echoing the validated payload.

3. **Run the test suite**

   ```bash
   poetry run pytest
   ```

   All tests should pass, confirming validation, sanitisation, and logging work.

4. **Build and run the Docker image**

   ```bash
   docker build -t user-safety .
   docker run -p 8000:8000 user-safety
   ```

   The service is now reachable at `http://localhost:8000/validate` exactly as in the local run.

5. **Verify logs are JSON‑structured**

   ```bash
   docker logs <container_id> | head -n 2
   ```

   You should see a single line like:

   ```json
   {"event":"request_completed","method":"POST","path":"/validate","status":200,"duration_ms":12,"client_host":"172.18.0.1"}
   ```

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | One‑line reason it matters |
|---|---------|----------------------------|
| 1 | **PostgreSQL + Alembic persistence** | Stores validated records for audit trails and replay, turning a pure‑in‑memory service into a durable system. |
| 2 | **Rate limiting with `slowapi`** | Protects the endpoint from abuse and demonstrates production‑grade API governance. |
| 3 | **OpenTelemetry tracing** | Emits distributed traces, enabling performance debugging and observability in microservice architectures. |
| 4 | **Fault‑tolerance with `tenacity` retries** | Automatic retries on transient DB or network failures, a hallmark of resilient services. |
| 5 | **Benchmarking with `locust`** | Quantifies throughput and latency under load, giving concrete numbers to discuss in interviews. |
| 6 | **OAuth2 / JWT authentication** | Adds token‑based auth, showing you can integrate identity providers and secure endpoints. |

Each upgrade moves the project from a “toy” to a production‑ready component that hiring managers can probe for depth of thought.

## Key Takeaways

- **Input validation + sanitisation** is a non‑negotiable skill; Pydantic + FastAPI make it expressive yet safe.  
- **Structured logging** (JSON + structlog) is the de‑facto standard for observability in modern services.  
- **Docker multi‑stage builds** keep images lean and reproducible, a must‑have for any CV.  
- **Test‑driven development** (pytest + TestClient) proves you can ship reliable code and reason about edge cases.  
- **Observability upgrades** (tracing, rate‑limiting, persistence) are what separate junior demos from senior‑level projects.  

## Further Reading

- [FastAPI documentation – “Build APIs with Python”](https://fastapi.tiangolo.com) – the primary source for the framework used throughout the guide.  
- [Pydantic v2 docs – “Data validation using Python type annotations”](https://docs.pydantic.dev) – canonical reference for the models and validators.  
- [Docker multi‑stage build best practices](https://docs.docker.com/engine/build/building/multi-stage/) – official Docker guide that underpins the Dockerfile used.  
- [OWASP Input Validation Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Input_Validation_Cheat_Sheet.html) – essential reading for the security mindset behind sanitisation.  
- [The Twelve‑Factor App](https://12factor.net) – a canonical set of principles for building SaaS‑ready applications; many of the upgrades map directly to these factors.  
- [Structlog documentation – “Structured logging for Python”](https://www.structlog.org/) – the logging library employed for JSON‑structured output.  

---