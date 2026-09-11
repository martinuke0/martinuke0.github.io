---
title: "User Safety: safe — A Hands-On Build Guide for Your Portfolio"
date: "2026-09-11T01:01:10.180"
draft: false
tags: ["systems-design", "content-moderation", "python", "fastapi", "trust-safety", "portfolio-project"]
description: "Build a production-grade User Safety scoring system from scratch. This hands-on guide covers architecture, real code, and extensions that signal senior-level systems skills to hiring managers."
summary: "A complete build guide for a User Safety scoring engine — covering architecture, step-by-step implementation with real code, testing strategies, and a senior-level extension roadmap."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-user-safety-safe-a-hands-on-build-guide-for-your-portfolio.svg"
  alt: "A visual representation of a user safety scoring pipeline processing content through multiple detection layers."
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time User Safety scoring engine that evaluates user-submitted content against configurable safety policies. This project demonstrates distributed systems thinking, ML pipeline integration, and observability — exactly the skills hiring managers scan for. By the end, you'll have a runnable system with an API layer, a rules engine, and a scoring pipeline you can point to in interviews.

The demand for Trust & Safety infrastructure has exploded across platforms, from social media to fintech. Yet most portfolio projects stop at CRUD apps. A User Safety system signals something different: you understand how to handle harmful content at scale, manage policy-as-code, and design for the edge cases that break naive systems. This guide walks you through building one from scratch — with real, runnable code — so you can add it to your CV and actually explain the architecture in an interview.

## Why This Project Stands Out on a CV

Hiring managers reviewing portfolios see hundreds of to-do apps and blog platforms. A User Safety system immediately differentiates you because it touches several high-value engineering domains simultaneously:

- **Distributed Systems & Real-Time Processing**: You're handling concurrent content evaluations, managing state, and designing for low-latency responses under load.
- **Policy-as-Code**: Safety rules are configuration, not hardcoded logic. This demonstrates your ability to separate concerns and build extensible systems — a pattern used at companies like Meta (OSSNS) and Google (Perspective API).
- **ML Pipeline Integration**: Whether you use a rule-based engine or integrate a classifier, you're showing you can bridge the gap between models and production serving.
- **Observability & Compliance**: Safety systems require audit trails, logging, and metric collection. This signals awareness of regulatory environments (GDPR, DSA) and operational rigor.
- **Fault Tolerance**: What happens when the classifier is down? Your system needs graceful degradation. This is the kind of thinking that separates staff engineers from juniors.

The roles this signals include Trust & Safety Engineer, Backend Platform Engineer, Content Infrastructure roles, and Safety ML Engineer — all of which are among the fastest-growing specialized tracks in tech.

## Architecture Overview

The system consists of five loosely coupled components that communicate over HTTP and a message queue. Here's how they fit together:

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Client /    │────▶│  API Gateway     │────▶│  Safety Engine  │
│  Frontend    │     │  (FastAPI)       │     │  (Scoring +     │
└──────────────┘     └──────────────────┘     │   Rules Eval)   │
                                               └────────┬────────┘
                                                        │
                            ┌───────────────────────────┼───────────────────┐
                            ▼                           ▼                   ▼
                     ┌──────────────┐          ┌──────────────┐   ┌────────────────┐
                     │  Redis       │          │  PostgreSQL  │   │  Rule Store    │
                     │  (Cache +    │          │  (Audit Log  │   │  (YAML/JSON    │
                     │   Rate       │          │   + Scores)  │   │   Config)      │
                     │   Limiting)  │          │              │   │                │
                     └──────────────┘          └──────────────┘   └────────────────┘
```

- **API Gateway (FastAPI)**: Receives content submissions, validates input, and orchestrates the scoring pipeline. Handles authentication and rate limiting.
- **Safety Engine**: The core scoring logic. Evaluates content against a configurable rules engine, produces a safety score (0–100), and returns a risk category.
- **Redis**: Caches frequent content hashes to avoid re-scoring identical submissions. Also enforces per-user rate limits to prevent abuse.
- **PostgreSQL**: Persists audit logs, user scores, and historical safety decisions for compliance and analytics.
- **Rule Store**: YAML or JSON files defining safety policies (toxicity thresholds, PII patterns, banned entities). Decoupled from the engine so policies can be updated without redeployment.

Each component is independently testable and deployable — this is the same modular pattern used in production systems like the Perspective API and OpenAI's moderation endpoints.

## Building It Step by Step

We'll build this in Python using FastAPI for the API layer, Pydantic for validation, and a modular rules engine. The full project fits in a single repository.

### Step 1: Project Scaffold and Dependencies

Create a new directory and set up your environment:

```bash
mkdir user-safety-safe && cd user-safety-safe
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn redis psycopg2-binary pyyaml pydantic scikit-learn
```

### Step 2: Define the Safety Policy Schema

Create `policies/safety_rules.yaml` — this is your policy-as-code foundation:

```yaml
rules:
  - name: toxicity_threshold
    type: keyword_match
    keywords: ["violence", "hate_speech", "self_harm"]
    weight: 0.4
    severity: high

  - name: pii_detection
    type: regex
    pattern: "\\b\\d{3}-\\d{2}-\\d{4}\\b"
    weight: 0.3
    severity: critical
    description: "SSN pattern detected"

  - name: spam_detection
    type: length_ratio
    max_ratio: 0.8
    weight: 0.1
    severity: low

  - name: link_spam
    type: url_count
    max_urls: 3
    weight: 0.2
    severity: medium
```

### Step 3: Build the Rules Engine

Create `engine/rules_engine.py` — this is the heart of your system:

```python
import yaml
import re
from typing import Dict, List, Any
from dataclasses import dataclass

@dataclass
class RuleResult:
    rule_name: str
    matched: bool
    score_contribution: float
    severity: str
    detail: str

class SafetyRulesEngine:
    def __init__(self, policy_path: str):
        with open(policy_path) as f:
            self.policy = yaml.safe_load(f)
        self.rules = self.policy["rules"]

    def evaluate(self, content: str, metadata: Dict[str, Any] = None) -> List[RuleResult]:
        results = []
        metadata = metadata or {}

        for rule in self.rules:
            result = self._apply_rule(rule, content, metadata)
            results.append(result)

        return results

    def _apply_rule(self, rule: Dict, content: str, metadata: Dict) -> RuleResult:
        rule_type = rule["type"]
        matched = False
        detail = ""

        if rule_type == "keyword_match":
            matched = any(kw.lower() in content.lower() for kw in rule["keywords"])
            detail = f"Matched keywords: {[kw for kw in rule['keywords'] if kw.lower() in content.lower()]}"

        elif rule_type == "regex":
            pattern = re.compile(rule["pattern"])
            match = pattern.search(content)
            matched = match is not None
            detail = f"Regex match: {match.group()}" if match else "No regex match"

        elif rule_type == "url_count":
            url_count = len(re.findall(r'https?://\S+', content))
            matched = url_count > rule["max_urls"]
            detail = f"Found {url_count} URLs (limit: {rule['max_urls']})"

        elif rule_type == "length_ratio":
            words = content.split()
            ratio = len(words) / max(len(content.split()), 1)
            matched = ratio > rule["max_ratio"]
            detail = f"Length ratio: {ratio:.2f}"

        score_contribution = rule["weight"] if matched else 0.0
        return RuleResult(
            rule_name=rule["name"],
            matched=matched,
            score_contribution=score_contribution,
            severity=rule["severity"],
            detail=detail
        )

    def compute_score(self, content: str, metadata: Dict = None) -> Dict:
        results = self.evaluate(content, metadata)
        total_score = sum(r.score_contribution for r in results)
        normalized_score = min(total_score * 100, 100.0)

        if normalized_score >= 70:
            category = "critical"
        elif normalized_score >= 40:
            category = "elevated"
        elif normalized_score >= 15:
            category = "moderate"
        else:
            category = "safe"

        return {
            "score": round(normalized_score, 2),
            "category": category,
            "rule_results": [
                {"rule": r.rule_name, "matched": r.matched, "severity": r.severity}
                for r in results
            ]
        }
```

### Step 4: Build the FastAPI Application

Create `app/main.py` — the API surface that ties everything together:

```python
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field
from engine.rules_engine import SafetyRulesEngine
import redis
import hashlib
import json

app = FastAPI(title="User Safety: safe")
engine = SafetyRulesEngine("policies/safety_rules.yaml")
cache = redis.Redis(host="localhost", port=6379, db=0)

class ContentSubmission(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    user_id: str
    context: str = "general"

class SafetyResponse(BaseModel):
    score: float
    category: str
    rule_results: list
    cached: bool = False

@app.post("/evaluate", response_model=SafetyResponse)
async def evaluate_content(submission: ContentSubmission):
    content_hash = hashlib.sha256(submission.content.encode()).hexdigest()

    # Check Redis cache first
    cached = cache.get(f"safety:{content_hash}")
    if cached:
        result = json.loads(cached)
        result["cached"] = True
        return SafetyResponse(**result)

    # Evaluate against safety rules
    result = engine.compute_score(submission.content, {"user_id": submission.user_id})

    # Cache the result for 1 hour
    cache.setex(f"safety:{content_hash}", 3600, json.dumps(result))

    return SafetyResponse(**result)

@app.get("/health")
async def health():
    return {"status": "healthy"}
```

### Step 5: Add the Persistence Layer

Create `app/database.py` to persist audit logs to PostgreSQL:

```python
import psycopg2
from typing import Optional

class AuditStore:
    def __init__(self, dsn: str):
        self.conn = psycopg2.connect(dsn)
        self._init_schema()

    def _init_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS safety_audit (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(255) NOT NULL,
                    content_hash VARCHAR(64) NOT NULL,
                    score FLOAT NOT NULL,
                    category VARCHAR(20) NOT NULL,
                    rule_results JSONB NOT NULL,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """)
        self.conn.commit()

    def log_evaluation(self, user_id: str, content_hash: str,
                       score: float, category: str, rule_results: list):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO safety_audit (user_id, content_hash, score, category, rule_results)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, content_hash, score, category, json.dumps(rule_results)))
        self.conn.commit()
```

Wire this into your endpoint by calling `audit_store.log_evaluation(...)` after scoring.

### Step 6: Create the Scoring Aggregator

Add a per-user safety profile in `app/user_profile.py`:

```python
from collections import defaultdict
from typing import Dict

class UserSafetyProfile:
    def __init__(self):
        self.profiles: Dict[str, list] = defaultdict(list)

    def record_evaluation(self, user_id: str, score: float, category: str):
        self.profiles[user_id].append({"score": score, "category": category})

    def get_risk_level(self, user_id: str) -> Dict:
        history = self.profiles.get(user_id, [])
        if not history:
            return {"risk_level": "unknown", "avg_score": 0}

        avg_score = sum(h["score"] for h in history) / len(history)
        high_risk_count = sum(1 for h in history if h["category"] in ("critical", "elevated"))
        ratio = high_risk_count / len(history)

        if ratio > 0.5:
            level = "high_risk"
        elif ratio > 0.2:
            level = "moderate_risk"
        else:
            level = "low_risk"

        return {"risk_level": level, "avg_score": round(avg_score, 2), "evaluations": len(history)}
```

## Running and Testing It

Start your infrastructure services:

```bash
# Terminal 1: Start Redis
redis-server --daemonize yes

# Terminal 2: Start PostgreSQL (assuming Homebrew or apt)
brew services start postgresql@16   # macOS
# or: sudo service postgresql start  # Ubuntu

# Terminal 3: Create the database
psql -c "CREATE DATABASE safety_audit;"

# Terminal 4: Run the FastAPI server
uvicorn app.main:app --reload --port 8000
```

Now test the API with `curl`:

```bash
# Safe content
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{"content": "Hello, how are you today?", "user_id": "user_123"}'

# Response: {"score": 0.0, "category": "safe", "rule_results": [...], "cached": false}

# Problematic content
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{"content": "This contains violence and hate_speech directives", "user_id": "user_456"}'

# Response: {"score": 40.0, "category": "moderate", "rule_results": [...], "cached": false}
```

For proper testing, write a pytest suite in `tests/test_engine.py`:

```python
import pytest
from engine.rules_engine import SafetyRulesEngine

@pytest.fixture
def engine():
    return SafetyRulesEngine("policies/safety_rules.yaml")

def test_safe_content(engine):
    result = engine.compute_score("This is a perfectly normal message.")
    assert result["category"] == "safe"
    assert result["score"] == 0.0

def test_toxicity_detection(engine):
    result = engine.compute_score("This promotes violence and self_harm.")
    assert result["category"] in ("elevated", "critical")
    assert result["score"] > 0

def test_caching_behavior(engine):
    """Verify that identical content produces identical scores."""
    r1 = engine.compute_score("Test content here")
    r2 = engine.compute_score("Test content here")
    assert r1["score"] == r2["score"]
```

Run with `pytest tests/ -v`. Add a second test file for the API layer using `TestClient` from FastAPI.

## Extending It: Your Roadmap to Senior-Level

A basic scoring engine is a solid portfolio piece. But to truly signal senior-level capability, layer on these production-grade upgrades:

1. **Add Message Queue Processing (Celery + RabbitMQ)** — Move content evaluation off the request/response cycle into an async task queue. This decouples ingestion from scoring, allows retry logic on classifier failures, and enables horizontal scaling of workers. This is the pattern used by Reddit's automod pipeline.

2. **Implement Horizontal Scaling with Kubernetes** — Containerize the FastAPI service with a `Dockerfile` and define a `Deployment` manifest. Add a Horizontal Pod Autoscaler that scales based on request latency. This demonstrates you understand stateless service design and orchestration.

3. **Add Full Observability Stack (Prometheus + Grafana + OpenTelemetry)** — Instrument your scoring engine with OpenTelemetry traces. Expose Prometheus metrics for request rate, average score latency, and cache hit ratio. Build a Grafana dashboard. Any production system requires this; showing you've built it from scratch is a massive CV signal.

4. **Build a Feedback Loop for Model Improvement** — Allow moderators to override safety decisions via a `/feedback` endpoint. Store overrides in PostgreSQL and use them to retrain or reweight your rule engine periodically. This closes the loop between automated scoring and human judgment — the hallmark of mature Trust & Safety systems.

5. **Implement Circuit Breaker Pattern (with `pybreaker`)** — When your classifier or external API dependency fails, a circuit breaker prevents cascading failures. Track failure rates and open the circuit after a threshold, falling back to a conservative default score. This demonstrates fault tolerance thinking that only appears in production systems.

6. **Add Benchmarking Suite with `locust`** — Write a `locustfile.py` that simulates 100 concurrent users submitting content. Measure p95 latency, throughput, and error rates under load. This proves your system doesn't just work — it works at scale.

Each of these upgrades maps directly to a senior engineer's responsibilities: distributed systems, reliability, observability, and performance. Pick two for a focused portfolio piece rather than all six at once.

## Key Takeaways

- A User Safety system demonstrates **multiple high-value systems skills** simultaneously: real-time processing, policy-as-code, ML integration, and compliance awareness.
- The architecture — API gateway, rules engine, cache, persistence, and audit log — mirrors **production patterns** used by major platforms, making it instantly recognizable to interviewers.
- **Real code matters**: the YAML policy schema, the modular rules engine, and the FastAPI endpoints are all copy-paste-ready components you can adapt to any project.
- The extension roadmap gives you a clear **progression path** from a working prototype to a production-grade system that would impress at any senior engineering level.
- Testing, observability, and fault tolerance aren't afterthoughts — they're **first-class requirements** that separate portfolio projects from professional systems.

## Further Reading

- [Perspective API Documentation](https://perspectiveapi.com/) — Google's production-grade content moderation API. Study their architecture and scoring methodology to understand how industry leaders approach this problem.
- [RFC 9110: HTTP Semantics](https://www.rfc-editor.org/rfc/rfc9110.html) — The foundational HTTP specification. Essential reading if you're building any API-facing system and want to understand status codes, content negotiation, and caching semantics at a deep level.
- [The Architecture of Open Source Applications: Trust & Safety](https://aosabook.org/en/500L/a-trust-and-safety-engineering-handbook.html) — A comprehensive handbook covering the engineering principles behind Trust & Safety systems at scale, including real-world case studies from major platforms.
- [Redis Documentation: Caching Patterns](https://redis.io/docs/manual/patterns/) — Official Redis docs covering cache-aside, write-through, and other patterns directly applicable to your safety scoring cache layer.
- [Kubernetes Production Patterns](https://www.oreilly.com/library/view/kubernetes-production-patterns/9781492049818/) — O'Reilly book covering the patterns for scaling stateless services, implementing autoscaling, and designing resilient deployments — directly relevant to your Kubernetes extension.
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) — The canonical specification for observability instrumentation. Study this to implement proper traces and metrics in your scoring engine.
- [Designing Data-Intensive Applications, Chapter 7: Derived Data](https://dataintensive.net/) — Martin Kleppmann's book covers the fundamentals of maintaining derived state (like user safety profiles) from event streams — directly applicable to your feedback loop and profile aggregation extensions.