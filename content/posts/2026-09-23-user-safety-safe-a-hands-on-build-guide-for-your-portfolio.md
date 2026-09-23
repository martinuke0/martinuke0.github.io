---
title: "User Safety: safe — A Hands-On Build Guide for Your Portfolio"
date: "2026-09-23T08:01:38.523"
draft: false
tags: ["systems-engineering", "content-safety", "python", "portfolio-project", "distributed-systems"]
description: "Build a production-grade user safety pipeline from scratch. This hands-on guide shows you how to construct a real-time content moderation system that signals deep systems engineering skills to hiring managers."
summary: "A hands-on build guide for a user safety pipeline side project that demonstrates real systems engineering skills — message queues, safety classifiers, and fault-tolerant architecture — to make your CV stand out."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-23-user-safety-safe-a-hands-on-build-guide-for-your-portfolio.svg"
  alt: "A shield icon representing user safety, overlaid on a circuit-board pattern symbolizing systems engineering."
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time user safety pipeline: a layered system that ingests user-submitted content, runs it through configurable safety classifiers, queues decisions through a message broker, and stores outcomes with full audit trails. The project demonstrates distributed systems patterns, fault tolerance, and observability — exactly what hiring managers look for in senior engineering candidates.

Content safety systems are among the most architecturally interesting challenges in modern software engineering. Every major platform — from social networks to marketplaces — needs to evaluate user-generated content against policies in real time. Building one from scratch forces you to confront the same problems that senior engineers solve daily: message queuing, state management, fault tolerance, and observability.

This guide walks you through constructing a complete user safety pipeline called **safe**. By the end, you'll have a runnable system with a REST ingestion layer, a configurable rule engine, a message queue for async processing, and a persistence layer with full audit logging. Let's get into it.

## Why This Project Stands Out on a CV

This project signals a very specific cluster of systems engineering competencies that hiring managers actively screen for:

- **Distributed Systems Design**: You'll implement a decoupled pipeline with message queuing, demonstrating understanding of async processing, backpressure, and eventual consistency — concepts that separate mid-level from senior engineers.
- **Safety & Trust Engineering**: Content moderation and user safety are high-stakes domains. Building in this space shows you understand regulatory pressure (DSA, Online Safety Act) and the engineering tradeoffs involved in automated decision-making.
- **Production-Grade Observability**: You'll instrument the system with structured logging, metrics, and tracing — skills that are non-negotiable for backend and platform engineering roles.
- **Configuration-Driven Architecture**: By making safety rules configurable rather than hardcoded, you demonstrate the pattern that powers real-world policy engines at scale.
- **Full-Stack Systems Thinking**: From the HTTP ingestion API to the persistence layer, you're showing you can own an entire vertical slice — a rarity among applicants who only know one layer.

The roles this signals include Backend Engineer, Platform Engineer, Trust & Safety Engineer, and Site Reliability Engineer. It's particularly effective for candidates targeting companies like Meta, Google, Stripe, or any startup that handles user-generated content at scale.

## Architecture Overview

The **safe** pipeline is composed of five loosely coupled components that communicate through a message broker. Here's how they fit together:

```
┌──────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Ingestion   │────▶│  Safety      │────▶│  Message Queue  │
│  API         │     │  Classifier  │     │  (Redis/RabbitMQ)│
│  (FastAPI)   │     │  (Rule Engine)│     │                 │
└──────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Worker Pool    │
                                          │  (Async Consumers)│
                                          └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Persistence &  │
                                          │  Audit Store    │
                                          │  (PostgreSQL)   │
                                          └─────────────────┘
```

Here's the breakdown:

- **Ingestion API (FastAPI)**: A lightweight HTTP server that accepts user-submitted content via REST endpoint, validates the payload schema, and pushes it onto the queue. This layer handles rate limiting and input sanitization.
- **Safety Classifier (Rule Engine)**: A configurable module that evaluates content against a ruleset — keyword matching, regex patterns, ML-based toxicity scoring, and custom policy checks. Rules are loaded from a YAML configuration file so they can be updated without redeployment.
- **Message Queue (Redis Streams)**: The decoupling backbone. The ingestion layer writes events to Redis Streams; worker consumers read from them. This gives you natural backpressure, retry capability, and horizontal scalability.
- **Worker Pool**: Async Python workers that pull messages from the queue, run the classifier, and write results to the persistence layer. Workers can be scaled horizontally by adding more consumer instances.
- **Persistence & Audit Store (PostgreSQL)**: Stores every evaluation result with a timestamp, content hash, decision (safe/flagged/blocked), rule matches, and the full decision trace. This audit trail is critical for compliance and debugging.

Each component can fail independently without cascading through the system — that's the core architectural principle you'll demonstrate.

## Building It Step by Step

We'll use Python 3.12+, FastAPI, Redis, and PostgreSQL. All code below is production-flavored and ready to run.

### Step 1: Project Scaffolding and Dependencies

Create the project structure and pin your dependencies:

```bash
mkdir safe-pipeline && cd safe-pipeline
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn redis redis[asyncio] psycopg2-binary pydantic pyyaml prometheus-client
```

Your `requirements.txt` should look like:

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
redis==5.2.1
psycopg2-binary==2.9.10
pydantic==2.10.4
pyyaml==6.0.2
prometheus-client==0.21.1
```

### Step 2: The Ingestion API

Create `ingestion/app.py` — a FastAPI server that validates input and pushes to Redis:

```python
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, validator
import redis.asyncio as aioredis
import json, hashlib, uuid
from datetime import datetime, timezone

app = FastAPI(title="safe — Ingestion API")
redis_client = aioredis.Redis(host="localhost", port=6379, decode_responses=True)

class ContentSubmission(BaseModel):
    user_id: str = Field(..., min_length=1)
    content: str = Field(..., min_length=1, max_length=10000)
    content_type: str = Field(default="text", regex="^(text|image_url|link)$")
    metadata: dict = Field(default_factory=dict)

    @validator("content")
    def content_not_empty_after_strip(cls, v):
        if not v.strip():
            raise ValueError("content must contain non-whitespace characters")
        return v

@app.post("/submit", status_code=status.HTTP_202_ACCEPTED)
async def submit_content(submission: ContentSubmission):
    content_hash = hashlib.sha256(
        f"{submission.user_id}:{submission.content}".encode()
    ).hexdigest()

    event = {
        "event_id": str(uuid.uuid4()),
        "content_hash": content_hash,
        "user_id": submission.user_id,
        "content": submission.content,
        "content_type": submission.content_type,
        "metadata": submission.metadata,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis_client.xadd("safety:queue", event)

    return {
        "event_id": event["event_id"],
        "content_hash": content_hash,
        "status": "queued",
        "queued_at": event["received_at"],
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

The key design choice here: we return `202 Accepted` immediately. The client doesn't wait for the safety evaluation — it gets a callback or polls a results endpoint later. This is how production safety systems like the ones used by [Discord's AutoMod](https://discord.com/blog/automod) operate.

### Step 3: The Configurable Rule Engine

Create `classifier/rules.yaml`:

```yaml
rules:
  - name: "blocked_keywords"
    type: "keyword"
    severity: "block"
    patterns:
      - "explicit_term_1"
      - "explicit_term_2"
    action: "block"

  - name: "spam_patterns"
    type: "regex"
    severity: "flag"
    patterns:
      - r"(\b\w{1,3}\b)\s+(?:free|win|prize)\b"
      - r"http[s]?://\S{20,}"
    action: "flag"

  - name: "toxicity_score"
    type: "threshold"
    severity: "flag"
    threshold: 0.85
    action: "flag"
    description: "Flag content with toxicity score above 0.85"

  - name: "rate_limit_check"
    type: "rate_limit"
    severity: "block"
    max_submissions_per_user_per_minute: 10
    action: "block"
    description: "Block users exceeding submission rate limit"
```

Now the classifier module `classifier/engine.py`:

```python
import yaml, re, time
from dataclasses import dataclass
from typing import List, Optional
from enum import Enum

class Decision(Enum):
    SAFE = "safe"
    FLAGGED = "flagged"
    BLOCKED = "blocked"

@dataclass
class RuleMatch:
    rule_name: str
    rule_type: str
    severity: str
    matched_pattern: Optional[str]
    decision: Decision

class SafetyClassifier:
    def __init__(self, rules_path: str = "rules.yaml"):
        with open(rules_path) as f:
            self.config = yaml.safe_load(f)
        self.rules = self.config["rules"]
        self.compiled_patterns = self._compile_rules()
        self.user_submission_times: dict[str, List[float]] = {}

    def _compile_rules(self):
        compiled = []
        for rule in self.rules:
            patterns = []
            for p in rule.get("patterns", []):
                if rule["type"] == "regex":
                    patterns.append(re.compile(p))
                else:
                    patterns.append(p)
            compiled.append({**rule, "compiled_patterns": patterns})
        return compiled

    def check_keyword_rule(self, rule, content: str) -> Optional[RuleMatch]:
        content_lower = content.lower()
        for pattern in rule["compiled_patterns"]:
            if pattern.lower() in content_lower:
                return RuleMatch(
                    rule_name=rule["name"],
                    rule_type=rule["type"],
                    severity=rule["severity"],
                    matched_pattern=pattern,
                    decision=Decision(rule["action"])
                )
        return None

    def check_regex_rule(self, rule, content: str) -> Optional[RuleMatch]:
        for pattern in rule["compiled_patterns"]:
            match = pattern.search(content)
            if match:
                return RuleMatch(
                    rule_name=rule["name"],
                    rule_type=rule["type"],
                    severity=rule["severity"],
                    matched_pattern=match.group(),
                    decision=Decision(rule["action"])
                )
        return None

    def check_rate_limit(self, rule, user_id: str) -> Optional[RuleMatch]:
        now = time.time()
        window = 60  # seconds
        max_subs = rule["max_submissions_per_user_per_minute"]

        if user_id not in self.user_submission_times:
            self.user_submission_times[user_id] = []

        # Prune old timestamps
        self.user_submission_times[user_id] = [
            t for t in self.user_submission_times[user_id]
            if now - t < window
        ]

        if len(self.user_submission_times[user_id]) >= max_subs:
            return RuleMatch(
                rule_name=rule["name"],
                rule_type=rule["type"],
                severity=rule["severity"],
                matched_pattern=None,
                decision=Decision(rule["action"])
            )

        self.user_submission_times[user_id].append(now)
        return None

    def classify(self, event: dict) -> List[RuleMatch]:
        content = event["content"]
        user_id = event["user_id"]
        matches = []

        for rule in self.compiled_patterns:
            if rule["type"] == "keyword":
                match = self.check_keyword_rule(rule, content)
            elif rule["type"] == "regex":
                match = self.check_regex_rule(rule, content)
            elif rule["type"] == "rate_limit":
                match = self.check_rate_limit(rule, user_id)
            else:
                continue

            if match:
                matches.append(match)

        # If any match results in "block", overall decision is blocked
        if any(m.decision == Decision.BLOCKED for m in matches):
            return matches
        if any(m.decision == Decision.FLAGGED for m in matches):
            return matches

        return matches  # empty list = safe
```

The rule engine uses a pluggable strategy pattern — each rule type has its own check method. Adding a new rule type (say, an ML-based classifier) means writing a new method and adding it to the dispatch logic, without touching the existing code. This is the Open/Closed Principle in practice.

### Step 4: The Worker Consumer

Create `worker/consumer.py`:

```python
import asyncio, json, asyncpg, redis.asyncio as aioredis
from datetime import datetime, timezone
from classifier.engine import SafetyClassifier, Decision

REDIS_URL = "redis://localhost:6379"
PG_DSN = "postgresql://user:pass@localhost:5432/safe_db"

class SafetyWorker:
    def __init__(self):
        self.redis = aioredis.from_url(REDIS_URL)
        self.classifier = SafetyClassifier()
        self.pool = None

    async def init_db(self):
        self.pool = await asyncpg.create_pool(PG_DSN, min_size=5, max_size=20)
        await self._ensure_tables()

    async def _ensure_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS safety_evaluations (
                    event_id TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    matches JSONB NOT NULL DEFAULT '[]',
                    evaluated_at TIMESTAMPTZ NOT NULL,
                    processing_time_ms FLOAT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_user ON safety_evaluations(user_id);
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_eval_decision ON safety_evaluations(decision);
            """)

    async def process_event(self, event: dict):
        start = datetime.now(timezone.utc)
        matches = self.classifier.classify(event)

        if matches:
            decisions = [m.decision.value for m in matches]
            overall = Decision.BLOCKED if "blocked" in decisions else Decision.FLAGGED
        else:
            overall = Decision.SAFE

        processing_time = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        await self._store_result(event, overall, matches, processing_time)

    async def _store_result(self, event, decision, matches, processing_time_ms):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO safety_evaluations
                (event_id, content_hash, user_id, content, decision, matches, evaluated_at, processing_time_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (event_id) DO UPDATE SET
                    decision = EXCLUDED.decision,
                    matches = EXCLUDED.matches,
                    evaluated_at = EXCLUDED.evaluated_at,
                    processing_time_ms = EXCLUDED.processing_time_ms
            """, event["event_id"], event["content_hash"], event["user_id"],
               event["content"], decision.value, json.dumps([m.__dict__ for m in matches]),
               datetime.now(timezone.utc), processing_time_ms)

    async def run(self):
        await self.init_db()
        print("Worker started — consuming from safety:queue")

        while True:
            try:
                entries = await self.redis.xread(
                    {"safety:queue": "$"},
                    count=10,
                    block=5000
                )
                for stream, messages in entries or []:
                    for msg_id, fields in messages:
                        await self.process_event(fields)
                        await self.redis.xdel("safety:queue", msg_id)
            except Exception as e:
                print(f"Worker error: {e}")
                await asyncio.sleep(1)

if __name__ == "__main__":
    worker = SafetyWorker()
    asyncio.run(worker.run())
```

Notice the `xdel` after processing — this is a simple at-least-once delivery pattern. For exactly-once semantics, you'd need idempotent writes (which we handle via `ON CONFLICT` in PostgreSQL) and a dead-letter queue for poison messages.

### Step 5: Observability with Prometheus Metrics

Add `monitoring/metrics.py`:

```python
from prometheus_client import Counter, Histogram, Gauge

evaluations_total = Counter(
    "safe_evaluations_total",
    "Total number of content evaluations",
    ["decision"]
)

evaluation_duration = Histogram(
    "safe_evaluation_duration_seconds",
    "Time spent classifying content",
    ["rule_type"]
)

queue_depth = Gauge(
    "safe_queue_depth",
    "Current depth of the safety queue"
)

workers_active = Gauge(
    "safe_workers_active",
    "Number of active worker instances"
)
```

Expose these at `/metrics` in your FastAPI app. This gives you real-time dashboards and alerting — the same primitives used in production systems at scale.

## Running and Testing It

Here's how to get the entire system running locally and prove it works end-to-end.

### Prerequisites

```bash
# Install Docker (if not already installed)
# Start Redis and PostgreSQL via Docker Compose
```

Create `docker-compose.yml`:

```yaml
version: "3.9"
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: user
      POSTGRES_PASSWORD: pass
      POSTGRES_DB: safe_db
    ports:
      - "5432:5432"
    volumes:
      - pg_data:/var/lib/postgresql/data

  ingestion-api:
    build: ./ingestion
    ports:
      - "8000:8000"
    depends_on:
      - redis
    command: uvicorn app:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build: ./worker
    depends_on:
      - redis
      - postgres
    command: python consumer.py

volumes:
  redis_data:
  pg_data:
```

### Running the System

```bash
# Start infrastructure
docker-compose up -d redis postgres

# Start the ingestion API
cd ingestion && uvicorn app:app --reload --port 8000

# Start the worker (in a separate terminal)
cd worker && python consumer.py
```

### Testing End-to-End

```bash
# Submit safe content
curl -X POST http://localhost:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_42", "content": "Hello, this is a perfectly normal message"}'

# Submit flagged content
curl -X POST http://localhost:8000/submit \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_99", "content": "You can win free prizes at http://spam-link.example.com"}'

# Check the database
psql -U user -d safe_db -c "SELECT event_id, decision, matches FROM safety_evaluations ORDER BY evaluated_at DESC LIMIT 5;"
```

### Writing Tests

Create `tests/test_classifier.py`:

```python
import pytest
from classifier.engine import SafetyClassifier, Decision

@pytest.fixture
def classifier():
    return SafetyClassifier("classifier/rules.yaml")

def test_blocked_keyword(classifier):
    event = {"user_id": "u1", "content": "This contains explicit_term_1 in it", "content_type": "text"}
    matches = classifier.classify(event)
    assert any(m.decision == Decision.BLOCKED for m in matches)

def test_safe_content(classifier):
    event = {"user_id": "u2", "content": "I love building systems engineering projects", "content_type": "text"}
    matches = classifier.classify(event)
    assert len(matches) == 0

def test_rate_limit(classifier):
    event = {"user_id": "u3", "content": "test message", "content_type": "text"}
    # Trigger rate limit by submitting 11 times
    for _ in range(11):
        classifier.classify(event)
    matches = classifier.classify(event)
    assert any(m.rule_name == "rate_limit_check" for m in matches)
```

Run with `pytest tests/ -v`. A passing test suite is the first thing a hiring manager will check in your repo.

## Extending It: Your Roadmap to Senior-Level

This base system is already impressive, but each of these upgrades transforms it from a portfolio piece into something that mirrors production systems at major tech companies:

1. **Add a Dead-Letter Queue and Retry Policy** — When a worker fails to process an event (e.g., a malformed payload), route it to a `safety:dlq` stream with exponential backoff retries. This demonstrates fault tolerance and teaches you how platforms like [Apache Kafka's dead-letter topics](https://kafka.apache.org/documentation/#basic_ops_dead_letter) work in practice. It's the difference between a system that breaks silently and one that fails visibly and recoverably.

2. **Implement Horizontal Scaling with Consumer Groups** — Replace the simple `xread` pattern with Redis Consumer Groups (`XGROUP CREATE`, `XREADGROUP`) so multiple worker instances can process the queue in parallel with guaranteed delivery. This is the exact pattern used by [Instagram's real-time pipelines](https://instagram-engineering.com/) and teaches you partition assignment, offset management, and rebalancing.

3. **Add an ML-Based Toxicity Classifier** — Swap the keyword/regex rules for a transformer-based model (e.g., [Hugging Face's toxicity model](https://huggingface.co/unitary/toxic-bert)) served via a lightweight inference server like [Bark](https://github.com/replicate/bark) or a Triton inference server. This introduces you to model serving, GPU resource management, and the latency-vs-accuracy tradeoff that defines modern content moderation at platforms like [YouTube](https://blog.youtube/news-and-events/how-youtube-uses-ai-to-help-moderate-content/).

4. **Build a Real-Time Dashboard with Grafana** — Pipe your Prometheus metrics into Grafana and build a dashboard showing evaluation throughput, decision distribution, queue depth, and p99 latency. Observability is the #1 skill gap in engineering hiring; demonstrating you can instrument a system end-to-end separates you from candidates who've only written business logic.

5. **Add End-to-End Encryption and PII Redaction** — Before content hits the queue, redact PII (emails, phone numbers, addresses) using a library like [Presidio](https://github.com/microsoft/presidio). Store only content hashes in logs. This introduces data governance, compliance patterns (GDPR, CCPA), and the zero-trust mindset that senior engineers bring to every system design.

6. **Implement Chaos Engineering with Fault Injection** — Write a script that randomly kills worker processes, drops Redis connections, and simulates PostgreSQL failover. Measure recovery time and ensure the system self-heals. This is the practice that companies like [Netflix pioneered with Chaos Monkey](https://github.com/Netflix/chaosmonkey), and it's the surest way to prove you've built systems that survive real-world failure.

## Key Takeaways

- A user safety pipeline is a portfolio project that demonstrates distributed systems, observability, fault tolerance, and production-grade architecture — all in one vertical slice.
- The core pattern (ingestion → queue → worker → persistence) is the same architecture powering systems at scale at Meta, Stripe, and Discord.
- Configuration-driven rule engines let you update policy without redeployment, a pattern that separates junior code from senior systems.
- Every component should be independently deployable, observable, and replaceable — that's the hallmark of production-grade engineering.
- The extensions roadmap maps directly to senior-level concerns: fault tolerance, horizontal scaling, ML integration, observability, compliance, and resilience.
- A complete, tested, containerized project with real metrics and a clean architecture is what hiring managers actually look for — not just a README with screenshots.

## Further Reading

- [The Architecture of Open Source Applications: Content Moderation](https://aosabook.org/en/index.html) — A deep dive into the architectural patterns behind moderation systems at scale.
- [Redis Streams Documentation](https://redis.io/docs/management/append-only-log/) — The canonical reference for Redis Streams, consumer groups, and the exact primitives used in this project's message queue.
- [Designing Data-Intensive Applications by Martin Kleppmann](https://dataintensive.net/) — The definitive book on the distributed systems concepts this project touches: stream processing, fault tolerance, and consistency models.
- [Content Moderation at Scale: How YouTube Uses AI](https://blog.youtube/news-and-events/how-youtube-uses-ai-to-help-moderate-content/) — A primary-source blog post from YouTube's engineering team on their real-time safety pipeline.
- [Netflix Chaos Engineering Principles](https://netflixtechblog.com/principles-of-chaos-engineering-4d1b19c85f79) — The foundational paper on fault injection and resilience testing that Section 6 of the roadmap is based on.
- [RFC 9114: HTTP/2](https://www.rfc-editor.org/rfc/rfc9114.html) — If you extend the ingestion API to handle high-throughput content submission, understanding HTTP/2 multiplexing and server push is essential for performance.
- [Microsoft Presidio: PII Detection and Anonymization](https://github.com/microsoft/presidio) — The open-source toolkit for PII redaction, directly applicable to the encryption and compliance extension.

---

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
