---
title: "User Safety: safe – a Hands‑On Portfolio CV Project"
date: "2026-10-25T17:01:05.805"
draft: false
tags: ["portfolio","cv","safety","systems","python","docker"]
description: "Build a user‑safe portfolio app that demonstrates authentication, rate‑limiting, and audit logging—real‑world skills hiring managers love."
summary: "A practical, runnable Flask‑based service that adds auth, rate‑limiting, and audit logging so you can showcase production‑grade security skills on your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-25-user-safety-safe-a-handson-portfolio-cv-project.svg"
  alt: "A sleek laptop screen showing a terminal with a secure login prompt"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a small but complete Flask service that enforces authentication, rate‑limits requests, and logs every action. You'll end up with a runnable project that proves you can ship production‑grade security features from day one.

In this post you'll create a minimal yet fully functional user‑safe API that can be cloned, run, and extended. The stack is deliberately lightweight—Flask, Flask‑JWT‑Extended, Redis, and PostgreSQL—so you can spin it up on a laptop or a cheap cloud VM in under an hour.

## Why This Project Stands Out on a CV

Hiring managers scan dozens of repos; a project that mirrors production‑grade patterns instantly differentiates you. **User Safety: safe** demonstrates the following concrete skills:

- **JWT‑based authentication** with token issuance, verification, and revocation—core for any API‑first backend role.  
- **Rate‑limiting** using a token‑bucket algorithm backed by Redis, showing you can protect services from abuse.  
- **Audit logging** to PostgreSQL, proving you can design immutable change‑trails required for compliance (GDPR, SOC 2).  
- **Containerisation** with Docker and a `docker‑compose.yml`, a must‑have for modern DevOps pipelines.  
- **Database schema design** (SQLAlchemy models, migrations) and writing idempotent migration scripts.  

Roles that directly benefit include **Backend Engineer**, **Security‑focused SRE**, **Full‑Stack Developer**, and **API Product Owner**. The project also gives you talking points for interviews (“I built a rate‑limited auth service that throttles 100 req/min per IP”) that go far beyond “todo list” examples.

## Architecture Overview

The system is a single‑process Flask app, but each concern is isolated so it scales horizontally later:

```
Flask app
│
├─ /auth        → JWT issuance & verification (Flask‑JWT‑Extended)
├─ /api         → protected routes, request validation
├─ rate‑limiter → Redis‑backed token bucket (redis‑rate‑limit)
└─ logger       → PostgreSQL audit table (SQLAlchemy)
```

- **Flask** handles HTTP routing and middleware.  
- **Flask‑JWT‑Extended** creates signed access tokens and provides `@jwt_required()` decorator.  
- **Redis** stores per‑IP request counters with a TTL, enabling fast rate checks.  
- **PostgreSQL** persists user data and an immutable `audit_log` table.  
- **Docker** wraps the service plus Redis and PostgreSQL containers, ensuring reproducible local runs.

A text diagram of the request flow:

```
Client → HTTPS → Flask → JWT check → Rate‑limit check (Redis) → Route handler → Audit log (Postgres) → Response
```

## Building It Step by Step

Below are five numbered steps, each with a runnable code snippet (Python‑tagged). Copy‑paste them into a fresh directory; the full repo is provided at the end.

### Step 1 – Scaffold the project and install dependencies

```bash
mkdir user-safe && cd user-safe
python -m venv .venv
source .venv/bin/activate
pip install Flask Flask-SQLAlchemy Flask-JWT-Extended redis psycopg2-binary docker-compose
```

### Step 2 – Configure the database and migrations

```python
# app.py  (first lines)
from flask import Flask
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql+psycopg2://safe_user:safe_pass@db:5432/safe"
db = SQLAlchemy(app)
```

Run migrations once the models are defined:

```bash
flask db init
flask db migrate -m "initial schema"
flask db upgrade
```

### Step 3 – Add JWT authentication

```python
from flask_jwt_extended import JWTManager, create_access_token, jwt_required

app.config["JWT_SECRET_KEY"] = "change-me-in-production"
jwt = JWTManager(app)

@app.route("/login", methods=["POST"])
def login():
    # In a real app you would verify credentials against the DB
    identity = "user_1"
    access_token = create_access_token(identity=identity)
    return {"access_token": access_token}
```

### Step 4 – Implement Redis‑backed rate limiting

```python
import redis
from flask import request, jsonify

r = redis.Redis(host="redis", port=6379, db=0, decode_responses=True)

def check_rate(limit=100, window=60):
    key = f"rate:{request.remote_addr}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, window)          # set TTL on first insertion
    if count > limit:
        return jsonify(error="rate limited"), 429
    return None                         # allow the request
```

Use it as a before‑request hook:

```python
@app.before_request
def rate_middleware():
    if request.endpoint not in ("login", "static"):
        reason = check_rate()
        if reason:
            return reason
```

### Step 5 – Add audit logging and a protected endpoint

```python
from datetime import datetime
from flask_jwt_extended import get_jwt_identity

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, default=1)
    action = db.Column(db.String(128))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@app.route("/log", methods=["POST"])
@jwt_required()
def log_action():
    data = request.get_json()
    user_id = int(get_jwt_identity().split("_")[-1])   # dummy extraction
    entry = AuditLog(user_id=user_id, action=data["action"])
    db.session.add(entry)
    db.session.commit()
    return {"status": "logged"}, 201
```

Now you have a fully functional service. The next sections show how to run it and how to evolve it.

## Running and Testing It

1. **Start the infra** – `docker-compose up -d` (see the file below). This launches `web` (Flask), `redis`, and `postgres`.

2. **Run migrations** – inside the running web container:

   ```bash
   docker exec -it user-safe_web_1 sh -c "flask db upgrade"
   ```

3. **Create a test user** – the login endpoint accepts any POST body; grab the returned token.

   ```bash
   TOKEN=$(curl -s -X POST http://localhost:5000/login -H "Content-Type: application/json" -d '{}' | jq -r .access_token)
   ```

4. **Log an action** – include the Bearer token:

   ```bash
   curl -s -X POST http://localhost:5000/log -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"viewed_dashboard"}'
   ```

5. **Verify audit entry** – query PostgreSQL:

   ```bash
   docker exec -it user-safe_db_1 psql -U safe_user -d safe -c "SELECT * FROM audit_log;"
   ```

6. **Test rate limiting** – fire many rapid requests:

   ```bash
   for i in {1..110}; do curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:5000/log -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{"action":"spam"}'; done
   ```

   You should see `429` after the 100th request.

**`docker-compose.yml`** (place at the repo root):

```yaml
version: "3.8"
services:
  web:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DATABASE_URL=postgresql://safe_user:safe_pass@db:5432/safe
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    command: gunicorn -w 4 app:app
  db:
    image: postgres:15
    environment:
      POSTGRES_USER: safe_user
      POSTGRES_PASSWORD: safe_pass
      POSTGRES_DB: safe
    volumes:
      - pg_data:/var/lib/postgresql/data
  redis:
    image: redis:7-alpine
volumes:
  pg_data:
```

### Quick test suite (optional)

```python
# tests/test_basic.py
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app(testing=True)
    with app.test_client() as client:
        yield client

def test_login(client):
    resp = client.post("/login")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "access_token" in data

def test_log_action(client):
    # login first
    login_resp = client.post("/login")
    token = login_resp.get_json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/log", json={"action": "hello"}, headers=headers)
    assert resp.status_code == 201
```

Run with `pytest tests/`.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Distributed rate‑limit store** – replace the single‑Redis instance with a Redis Cluster or use a Redis Lua script for atomic increment+TTL across multiple instances. | Guarantees consistent throttling when the service runs behind a load balancer. |
| 2 | **Horizontal scaling with Gunicorn + Nginx** – run several Flask workers, terminate TLS at Nginx, and rely on the stateless design (no in‑process session state). | Enables you to handle higher QPS and demonstrates production‑grade deployment patterns. |
| 3 | **Observability stack** – instrument with OpenTelemetry, export metrics to Prometheus, and visualise latency/error rates in Grafana. | Gives you concrete data to debug performance issues and satisfies SRE hiring criteria. |
| 4 | **Fault tolerance** – add a circuit‑breaker (e.g., `pybreaker`) around the Redis calls, implement graceful shutdown via `SIGTERM` handler, and expose a `/healthz` endpoint. | Prevents cascading failures and shows you can build resilient services. |
| 5 | **Benchmarking** – load‑test with `locust` or `k6` to measure requests‑per‑second, identify bottlenecks (DB round‑trip vs. Redis), and iterate. | Provides measurable proof of performance and a talking point for performance‑engineer roles. |
| 6 | **Role‑based access control** – integrate Flask‑Permission or OPA policy‑as‑code to enforce granular permissions per endpoint. | Moves the project from “basic auth” to a full authorization model, a frequent interview topic for senior back‑end engineers. |

Pick the upgrades that align with the role you’re targeting; even implementing two of them will markedly raise the project’s signal on a CV.

## Key Takeaways

- **Auth + rate‑limit + audit** is a minimal yet complete security triad that hiring managers can instantly evaluate.  
- The stack (Flask + JWT‑Extended + Redis + Postgres) is lightweight, Docker‑friendly, and mirrors real production services.  
- Containerising the entire setup with `docker‑compose` gives you a reproducible environment you can demo in under an hour.  
- Each upgrade path (distributed rate‑limiting, observability, fault tolerance) maps directly to skills asked in senior‑level interviews.  
- The project is fully runnable, testable, and extensible—turn a “side‑project” into a talking point that proves you can ship production‑grade code.

## Further Reading

- [Flask documentation](https://flask.palletsprojects.com) – core API and routing patterns.  
- [Flask‑JWT‑Extended docs](https://jwt-extended.readthedocs.io) – token creation, refresh, and revocation.  
- [Redis rate‑limiting guide](https://redis.io/docs/operate/atlas/rate-limiting) – token‑bucket implementation details.  
- [OWASP Authentication Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html) – best‑practice password handling and token security.  
- [PostgreSQL documentation](https://www.postgresql.org/docs) – schema design, migrations, and audit‑friendly table patterns.  
- [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/instrumentation/python) – adding tracing and metrics to Flask apps.  

---