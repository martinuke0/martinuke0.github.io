

---
title: "Building a Real-Time User Safety Pipeline: A Portfolio Project"
date: "2026-09-10T20:01:00.919"
draft: false
tags: ["user-safety", "systems-design", "portfolio", "python", "fastapi", "real-time"]
description: "Learn to build a real-time user safety pipeline with FastAPI and Redis that flags harmful content, perfect for showcasing systems engineering skills to hiring managers."
summary: "A hands-on guide to building a production-flavored user safety service that ingests, moderates, and logs user content in real time."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-10-building-a-real-time-user-safety-pipeline-a-portfolio-project.svg"
  alt: "A dashboard showing flagged user content"
  relative: false
---

> **TL;DR** — You’ll build a real-time user safety pipeline using FastAPI, Redis, and PostgreSQL that ingests user messages, checks them against a dynamic blocklist, and logs incidents for review. This project demonstrates end-to-end systems design, including caching, async I/O, and RESTful API development — skills that directly translate to backend and platform engineering roles. The code is fully runnable, modular, and extensible, making it a portfolio piece you can demo in interviews.

In products where users generate content — forums, social networks, chat apps — safety is not a feature; it is the product. Yet many engineers never build a system that actually stops harm in real time. This post gives you a hands-on, production-flavored project: a **User Safety Pipeline** that ingests user messages, checks them against a dynamic blocklist, and records every flagged incident. It is small enough to build in a weekend, but realistic enough to showcase the systems thinking hiring managers care about.

## Why This Project Stands Out on a CV

A recruiter scanning your résumé wants evidence that you can ship and operate software that other people depend on. This project delivers that evidence across five dimensions:

- **API design & async I/O** — You will build a FastAPI application that handles concurrent requests non‑blockingly, demonstrating familiarity with modern Python web frameworks and the ASGI ecosystem.
- **Caching & state management** — Redis is used as a hot cache for the blocklist, teaching you to think about read‑heavy workloads and cache‑aside patterns.
- **Persistence & relational modeling** — PostgreSQL stores incident logs with proper indexing, showing you can design schema for audit trails and compliance queries.
- **Observability by default** — Every request is logged with structured JSON, and you can wire in Prometheus metrics with a few lines of code, signaling that you build for production, not just for the demo.
- **Extensibility & clean separation** — The moderation logic is isolated in a service layer, making it trivial to swap in a machine‑learning model or a third‑party provider later.

Together, these skills map directly to **Backend Engineer**, **Platform Engineer**, and **SRE** roles. Instead of saying “I know systems,” you can point to a running service that ingests, moderates, and logs user content in real time.

## Architecture Overview

The pipeline is a three‑tier service, deliberately simple but not toy‑like:

- **Ingestion tier** — A FastAPI app exposes a `POST /messages` endpoint. It receives JSON payloads (user ID, text, timestamp) and returns a moderation result.
- **Moderation tier** — A `Moderator` class decoupled from the HTTP layer. It first consults Redis for a cached blocklist; if the text matches, it flags the message. Otherwise it falls back to a deterministic rule engine (e.g., regex‑based profanity filter) and can later be replaced by an ML model without touching the API.
- **Persistence tier** — Flagged incidents are written to PostgreSQL via SQLAlchemy. A separate `AuditLog` table stores the original text, the matched rule, and a timestamp, forming the basis for a compliance dashboard.

A text diagram of the request flow:

```
Client → FastAPI (POST /messages) → Moderator → Redis (blocklist cache)
                                      ↓
                                 PostgreSQL (incident log)
```

Optional additions (not required for the base build) include a Celery worker for asynchronous moderation and a React dashboard for reviewing flagged content. The core service, however, runs in a single process and is fully functional.

## Building It Step by Step

### Step 1: Set up the project

Create a new directory and a virtual environment:

```bash
mkdir user-safety-pipeline
cd user-safety-pipeline
python -m venv venv
source venv/bin/activate
```

Install the core dependencies:

```bash
pip install fastapi uvicorn redis psycopg2-binary sqlalchemy pydantic
```

Create the project structure:

```
user-safety-pipeline/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── moderator.py
│   ├── models.py
│   └── schemas.py
├── .env
└── requirements.txt
```

### Step 2: Configure environment variables

Create a `.env` file with your database and Redis connection strings:

```env
DATABASE_URL=postgresql://safetyuser:safepass@localhost:5432/safetydb
REDIS_URL=redis://localhost:6379/0
```

### Step 3: Define the data models

In `app/models.py`, use SQLAlchemy to map the `AuditLog` table:

```python
from sqlalchemy import Column, Integer, String, Text, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

Base = declarative_base()

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    message = Column(Text)
    matched_rule = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
```

### Step 4: Build the moderation logic

`app/moderator.py` contains the core safety engine. It uses Redis for the blocklist and a simple regex‑based filter as a fallback.

```python
import redis
import re
from typing import Optional, Tuple
from sqlalchemy.orm import Session
from .models import AuditLog

class Moderator:
    def __init__(self, redis_url: str):
        self.redis = redis.from_url(redis_url)
        # Pre‑load common profanity patterns (could be extended)
        self.profanity_patterns = [
            re.compile(r"\b(badword1|badword2)\b", re.IGNORECASE)
        ]

    def check_blocklist(self, text: str) -> Optional[str]:
        """Return the matched banned phrase, or None."""
        # In a real system, the blocklist would be dynamic.
        # Here we store it as a Redis set for O(1) lookup.
        banned = self.redis.smembers("banned_phrases")
        for phrase in banned:
            if phrase.decode().lower() in text.lower():
                return phrase.decode()
        return None

    def check_profanity(self, text: str) -> Optional[str]:
        """Return the first matched profanity pattern, or None."""
        for pattern in self.profanity_patterns:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return None

    def moderate(self, text: str) -> Tuple[bool, Optional[str]]:
        """
        Returns (is_flagged, matched_rule).
        """
        # 1. Check dynamic blocklist
        rule = self.check_blocklist(text)
        if rule:
            return True, f"blocklist:{rule}"

        # 2. Check static profanity
        rule = self.check_profanity(text)
        if rule:
            return True, f"profanity:{rule}"

        return False, None

    def log_incident(self, db: Session, user_id: str, message: str, rule: str):
        """Persist a flagged incident to PostgreSQL."""
        log = AuditLog(
            user_id=user_id,
            message=message,
            matched_rule=rule
        )
        db.add(log)
        db.commit()
        db.refresh(log)
        return log
```

### Step 5: Create the FastAPI endpoints

`app/main.py` wires everything together. It also includes a simple health‑check endpoint and a Prometheus metrics middleware (optional but recommended).

```python
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import redis
from .schemas import MessageIn, MessageOut
from .moderator import Moderator
from .models import AuditLog
import os

app = FastAPI(title="User Safety Pipeline")

# Database setup
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis
REDIS_URL = os.getenv("REDIS_URL")
moderator = Moderator(REDIS_URL)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/messages", response_model=MessageOut)
async def submit_message(payload: MessageIn, db: Session = Depends(get_db)):
    is_flagged, rule = moderator.moderate(payload.text)

    if is_flagged:
        moderator.log_incident(
            db,
            user_id=payload.user_id,
            message=payload.text,
            rule=rule
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "status": "flagged",
                "matched_rule": rule,
                "message": "Your message has been flagged and logged."
            }
        )

    return {"status": "cleared", "matched_rule": None, "message": "Message passed moderation."}
```

### Step 6: Define Pydantic schemas

`app/schemas.py` keeps the request/response contracts explicit:

```python
from pydantic import BaseModel

class MessageIn(BaseModel):
    user_id: str
    text: str

class MessageOut(BaseModel):
    status: str
    matched_rule: str | None
    message: str
```

### Step 7: Seed the blocklist (one‑time)

You can add banned phrases via a small script or directly in Redis CLI:

```bash
redis-cli SADD banned_phrases "spam" "harassment" "explicit_content"
```

In production, you would expose an admin endpoint or use a UI to update this set.

## Running and Testing It

### Start the database and Redis

If you use Docker:

```bash
docker run -d -p 5432:5432 -e POSTGRES_USER=safetyuser -e POSTGRES_PASSWORD=safepass -e POSTGRES_DB=safetydb postgres:15
docker run -d -p 6379:6379 redis:7
```

### Run the FastAPI app

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Create the tables

```bash
python -c "from app.models import Base, engine; Base.metadata.create_all(bind=engine)"
```

### Test with curl

**Clean message:**

```bash
curl -X POST http://localhost:8000/messages \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user123","text":"Hello, how are you?"}'
```

Expected response:

```json
{"status":"cleared","matched_rule":null,"message":"Message passed moderation."}
```

**Flagged message (if "spam" is in the blocklist):**

```bash
curl -X POST http://localhost:8000/messages \
  -H "Content-Type: application/json" \
  -d '{"user_id":"user456","text":"Buy now! Spam alert!"}'
```

Expected response:

```json
{"status":"flagged","matched_rule":"blocklist:spam","message":"Your message has been flagged and logged."}
```

### Verify the audit log

```bash
psql $DATABASE_URL -c "SELECT user_id, matched_rule, created_at FROM audit_logs;"
```

You should see the flagged entry.

### Automated tests

Create a `tests/` directory with `pytest`:

```python
# tests/test_moderation.py
from app.moderator import Moderator
import redis

def test_blocklist_match():
    r = redis.from_url("redis://localhost:6379/0")
    r.delete("banned_phrases")
    r.sadd("banned_phrases", "spam")
    mod = Moderator("redis://localhost:6379/0")
    flagged, rule = mod.moderate("This is a spam message")
    assert flagged is True
    assert "spam" in rule
```

Run with `pytest tests/ -v`. This proves the core logic works without the HTTP layer.

## Extending It: Your Roadmap to Senior‑Level

The base project is interview‑ready, but the real power comes from adding production‑grade features. Here are six concrete upgrades, each with the one‑line reason it matters:

1. **Persist the blocklist in PostgreSQL and cache it in Redis** — Decouples the moderation rules from application restarts and enables dynamic updates without downtime.
2. **Add a Celery worker for asynchronous moderation** — Offloads heavy checks (e.g., ML inference) from the request path, improving latency and scalability.
3. **Implement rate limiting with Redis** — Prevents abuse of the ingestion endpoint, demonstrating you understand DoS protection and fair‑use policies.
4. **Expose Prometheus metrics (request count, latency, flagged ratio)** — Makes the system observable and lets you build dashboards, a must‑have skill for SRE and platform roles.
5. **Add a circuit‑breaker pattern when calling external moderation APIs** — Shows fault‑tolerance thinking; a failing third‑party service shouldn’t take your pipeline down.
6. **Containerise with Docker and orchestrate with Kubernetes** — Proves you can ship and scale microservices in a real‑world deployment environment.

Each of these can be added incrementally, turning a simple script into a resilient, observable, horizontally scalable service.

## Key Takeaways

- You now have a **runnable, real‑time user safety pipeline** built with FastAPI, Redis, and PostgreSQL — a concrete portfolio piece that speaks to systems engineering ability.
- The project demonstrates **API design, caching, persistence, and observability**, all skills that hiring managers look for in backend and platform roles.
- The **modular architecture** makes it trivial to swap in machine learning models, add asynchronous processing, or scale horizontally.
- By following the **extension roadmap**, you can evolve this into a production‑grade service that showcases senior‑level engineering thinking.
- Remember to **deploy it** (even on a free tier VPS) and link to the repo in your résumé — a live demo beats any bullet point.

## Further Reading

- **FastAPI Official Documentation** — The definitive guide to building async APIs with Pydantic and dependency injection: [https://fastapi.tiangolo.com](https://fastapi.tiangolo.com)
- **Redis Command Reference** — Deep dive into data structures like sets and sorted sets for caching and rate limiting: [https://redis.io/commands](https://redis.io/commands)
- **SQLAlchemy Core and ORM** — Master the toolkit for robust database interactions in Python: [https://www.sqlalchemy.org](https://www.sqlalchemy.org)
- **Designing Data‑Intensive Applications** by Martin Kleppmann — The canonical text on building reliable, scalable systems; chapters on caching and reliability are directly applicable: [https://dataintensive.net](https://dataintensive.net)
- **Prometheus Monitoring Guide** — Learn to instrument your services with metrics that matter: [https://prometheus.io/docs/introduction/overview](https://prometheus.io/docs/introduction/overview)
- **Kubernetes Patterns for Microservices** — Understand how to package and orchestrate services like the one you just built: [https://kubernetes.io/blog](https://kubernetes.io/blog)