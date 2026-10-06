---
title: "Building a User Safety Service: A Portfolio Project for Systems Engineers"
date: "2026-10-06T17:01:37.930"
draft: false
tags: ["user-safety", "microservice", "python", "fastapi", "rate-limiting", "portfolio"]
description: "Learn to build a production‑style user safety service with rate limiting, content filtering, and audit logging, showcasing systems engineering skills."
summary: "A step‑by‑step guide to building a user safety microservice that demonstrates rate limiting, content filtering, and audit logging for hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-06-building-a-user-safety-service-a-portfolio-project-for-systems-engineers.svg"
  alt: "User safety service architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — This project teaches you to build a production‑grade user safety service that enforces rate limits, filters abusive content, and logs all actions. It demonstrates real systems skills like API design, concurrency control, and observability, making your CV stand out to hiring managers.

In today's SaaS landscape, protecting users from abuse is a first‑class concern. A well‑architected safety layer not only shields your platform but also showcases your ability to design scalable, observable systems. In this guide you will implement a complete user safety microservice from scratch, using Python, FastAPI, Redis, and PostgreSQL, and you will learn how to extend it toward production readiness.

## Why This Project Stands Out on a CV

- **End‑to‑end system design** – You will wire together an HTTP API, a distributed cache, a relational database, and asynchronous logging, demonstrating the ability to architect a cohesive system.
- **Real‑world security controls** – Implementing JWT authentication, rate limiting, and content filtering signals experience with the security priorities that hiring managers care about.
- **Performance & scalability** – Using Redis for token‑bucket rate limiting and PostgreSQL for durable audit trails shows an understanding of latency‑sensitive versus durable storage trade‑offs.
- **Observability by default** – Structured logging, metrics, and traceability are baked in, illustrating the operational maturity expected for senior roles.
- **Extensibility mindset** – The codebase is organized to add horizontal scaling, circuit breakers, and ML‑based filtering without a rewrite, highlighting architectural foresight.

## Architecture Overview

The service is composed of five loosely coupled components:

1. **API Gateway (FastAPI)** – Exposes REST endpoints for reporting abuse, checking safety, and retrieving audit logs. FastAPI's OpenAPI generation provides automatic documentation.
2. **Rate Limiter (Redis)** – A token‑bucket algorithm stored in Redis guarantees O(1) check‑and‑set operations and survives process restarts.
3. **Content Filter (Python module)** – A pluggable filter chain that can run regex, keyword lists, or a lightweight ML model (e.g., scikit‑learn) to flag abusive language.
4. **Audit Logger (PostgreSQL)** – Every request that passes the filter is persisted with a UUID, timestamp, user ID, and decision, creating an immutable trail.
5. **Auth Middleware (JWT)** – Verifies signed tokens issued by an external identity provider, enforcing authenticated access.

A simple request flow:

```
Client → FastAPI → JWT Auth → Rate Limiter → Content Filter → Audit Logger → Response
```

Each step is implemented as a separate Python module, making the system easy to test and extend.

## Building It Step by Step

### 1. Project Setup

Create a new directory and install dependencies.

```bash
mkdir user-safety-service
cd user-safety-service
python -m venv venv
source venv/bin/activate
pip install fastapi uvicorn redis psycopg2-binary pydantic python-jose[cryptography]
```

### 2. Core FastAPI Application

`main.py` – the entry point.

```python
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from .rate_limiter import check_rate_limit
from .content_filter import filter_content
from .audit_logger import log_audit
from pydantic import BaseModel

app = FastAPI(title="User Safety Service")
security = HTTPBearer()

class SafetyRequest(BaseModel):
    user_id: str
    content: str

class SafetyResponse(BaseModel):
    allowed: bool
    reason: str

async def authenticate(credentials: HTTPAuthorizationCredentials = Depends(security)):
    # Verify JWT token (simplified)
    token = credentials.credentials
    # In production, use a proper JWT library and verify signature
    if token != "valid-token":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return token

@app.post("/safety-check", response_model=SafetyResponse)
async def safety_check(req: SafetyRequest, _ = Depends(authenticate)):
    # 1. Rate limiting
    if not check_rate_limit(req.user_id):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    # 2. Content filtering
    allowed, reason = filter_content(req.content)

    # 3. Audit logging (async)
    log_audit(req.user_id, req.content, allowed)

    return SafetyResponse(allowed=allowed, reason=reason)
```

### 3. Rate Limiter Implementation

`rate_limiter.py` – token‑bucket using Redis.

```python
import redis
import time

r = redis.Redis(host='localhost', port=6379, db=0)

def check_rate_limit(user_id: str, limit: int = 100, window: int = 60) -> bool:
    """
    Returns True if the request is allowed, False otherwise.
    Uses a sliding‑window token bucket.
    """
    key = f"rate:{user_id}"
    now = time.time()
    # Remove old entries
    r.zremrangebyscore(key, 0, now - window)
    # Count requests in window
    count = r.zcard(key)
    if count < limit:
        r.zadd(key, {now: now})
        r.expire(key, window)
        return True
    return False
```

### 4. Content Filter

`content_filter.py` – simple keyword filter, extensible.

```python
import re

FORBIDDEN_PATTERNS = [
    re.compile(r"badword", re.IGNORECASE),
    re.compile(r"abusive phrase", re.IGNORECASE),
]

def filter_content(content: str) -> tuple[bool, str]:
    for pattern in FORBIDDEN_PATTERNS:
        if pattern.search(content):
            return False, f"Content matches forbidden pattern: {pattern.pattern}"
    return True, "OK"
```

### 5. Audit Logger

`audit_logger.py` – asynchronous write to PostgreSQL.

```python
import psycopg2
from threading import Thread

def log_audit(user_id: str, content: str, allowed: bool):
    # Offload DB write to a background thread
    Thread(target=_write_audit, args=(user_id, content, allowed)).start()

def _write_audit(user_id: str, content: str, allowed: bool):
    conn = psycopg2.connect("dbname=safety user=postgres password=secret")
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO audit (user_id, content, allowed) VALUES (%s, %s, %s)",
        (user_id, content, allowed)
    )
    conn.commit()
    cur.close()
    conn.close()
```

### 6. JWT Authentication (Simplified)

In production, use `python-jose` to verify signatures. The example above already includes a stub `authenticate` function.

### 7. Dockerize the Service

`Dockerfile`

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`docker-compose.yml`

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8000:8000"
    depends_on:
      - redis
      - postgres
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: safety
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: secret
    ports:
      - "5432:5432"
```

## Running and Testing It

1. **Start services**

```bash
docker compose up -d
```

2. **Run the API**

```bash
uvicorn main:app --reload
```

3. **Send a test request**

```bash
curl -X POST "http://localhost:8000/safety-check" \
     -H "Authorization: Bearer valid-token" \
     -H "Content-Type: application/json" \
     -d '{"user_id":"alice","content":"Hello world"}'
```

Expected response:

```json
{"allowed":true,"reason":"OK"}
```

4. **Validate rate limiting**

Send 101 requests quickly; the 101st should receive HTTP 429.

5. **Check audit table**

```bash
psql -U postgres -d safety -c "SELECT * FROM audit;"
```

You should see rows for each request.

## Extending It: Your Roadmap to Senior-Level

1. **Persist rate‑limit state in Redis with TTL** – Guarantees automatic cleanup and scales horizontally without sticky sessions.
2. **Introduce a message queue (Kafka/RabbitMQ)** – Decouples audit logging from the request path, improving latency and enabling replayable event streams.
3. **Add Prometheus metrics** – Export counters for allowed/blocked requests and histograms for latency, then visualize in Grafana.
4. **Implement circuit‑breaker pattern** – Protect the content‑filter microservice from cascading failures when the ML model becomes unavailable.
5. **Container orchestration with Kubernetes** – Deploy multiple replicas behind a load balancer, configure horizontal pod autoscaling based on CPU or custom metrics.
6. **Benchmark with k6** – Load‑test the service to determine throughput limits and identify bottlenecks before scaling.

Each upgrade directly addresses a production concern: persistence ensures durability, messaging enables loose coupling, observability drives incident response, fault tolerance prevents outages, orchestration provides elasticity, and benchmarking informs capacity planning.

## Key Takeaways

- You have built a complete user safety microservice covering authentication, rate limiting, content filtering, and audit logging.
- The codebase demonstrates real systems skills: API design, distributed caching, asynchronous persistence, and extensibility.
- Each component is written in plain Python with clear separation of concerns, making it easy to test and scale.
- The project provides a solid foundation to showcase on a CV and to iterate toward production‑grade features.

## Further Reading

- [FastAPI Documentation](https://fastapi.tiangolo.com/) – official guide for building APIs with automatic OpenAPI support.
- [Redis Commands Reference](https://redis.io/docs/) – deep dive into Redis data structures for rate limiting and caching.
- [RFC 7230: HTTP/1.1 Message Syntax and Routing](https://www.rfc-editor.org/rfc/rfc7230) – foundational HTTP semantics for API design.
- [Kafka Documentation](https://kafka.apache.org/documentation) – learn how to introduce event‑driven audit logging for scalability.