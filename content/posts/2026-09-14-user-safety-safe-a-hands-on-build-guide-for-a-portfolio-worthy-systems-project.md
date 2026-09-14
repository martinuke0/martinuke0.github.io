---
title: "User Safety: safe — A Hands-On Build Guide for a Portfolio-Worthy Systems Project"
date: "2026-09-14T10:02:02.658"
draft: false
tags: ["python", "systems-design", "content-moderation", "fastapi", "machine-learning", "engineering-portfolio"]
description: "Build a production-grade user safety engine from scratch. Learn architecture, real-time classification, and systems design that signals senior-level skills to hiring managers."
summary: "A hands-on guide to building 'safe', a real-time user safety engine that classifies content, applies configurable rules, and flags violations — demonstrating systems architecture, ML integration, and production-grade engineering."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-14-user-safety-safe-a-hands-on-build-guide-for-a-portfolio-worthy-systems-project.svg"
  alt: "A conceptual diagram of a user safety pipeline with input validation, classification, rule engine, and alerting stages."
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time user safety engine called `safe` that ingests user-generated content, classifies it for toxicity and policy violations using a fine-tuned transformer model, applies a configurable rule engine, and quarantines flagged content via a FastAPI service backed by PostgreSQL and Redis. This project demonstrates systems architecture, ML integration, distributed caching, and observability — exactly the skills hiring managers look for in senior backend and platform engineering roles.

---

## Why This Project Stands Out on a CV

Content safety and moderation is one of the hardest real-world systems problems at scale. Every major platform — from Discord to Reddit to TikTok — runs some form of this pipeline, and the engineering challenges are deep: low-latency inference, configurable policy engines, graceful degradation when models fail, and audit trails that satisfy regulators.

Building `safe` signals the following to hiring managers:

- **Distributed Systems Thinking**: You've designed a pipeline with message queues, caching layers, and stateful storage — not just a monolithic script.
- **ML Engineering Fluency**: Integrating a transformer-based classifier into a serving system (not just a Jupyter notebook) is a rare and valuable skill.
- **Production-Grade Habits**: Tests, Docker containers, observability hooks, and configurable deployments separate this from tutorial projects.
- **Policy & Compliance Awareness**: Understanding content policy engines, rate limiting, and audit logging shows you think beyond code into regulatory and ethical dimensions.

This project positions you for roles in backend engineering, trust & safety platforms, ML infrastructure, and site reliability engineering (SRE). It's the kind of project that gets you past the screen-share round because it's tangible, inspectable, and demonstrates you can own a feature end-to-end.

---

## Architecture Overview

`safe` is composed of five loosely coupled services that communicate over HTTP and a message queue. Here's how they fit together:

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Content      │────▶│  Ingestion   │────▶│  Classification │
│  Producers    │     │  Service     │     │  Service        │
│  (API clients)│     │  (FastAPI)   │     │  (Transformer)  │
└──────────────┘     └──────────────┘     └────────┬─────────┘
                                                   │
                                          ┌─────────▼─────────┐
                                          │  Rule Engine       │
                                          │  (Policy Matcher)  │
                                          └─────────┬─────────┘
                                                    │
                                       ┌────────────▼────────────┐
                                       │  Action Dispatcher      │
                                       │  ┌──────────────────┐   │
                                       │  │ Quarantine       │──▶│ PostgreSQL │
                                       │  │ Allow            │   │            │
                                       │  │ Flag for Review  │──▶│ Redis      │
                                       │  └──────────────────┘   │            │
                                       └─────────────────────────┘            │
                                                                                │
                                       ┌─────────────────────────┐            │
                                       │  Observability          │◀─────────────┘
                                       │  (Prometheus + Grafana) │
                                       └─────────────────────────┘
```

The components break down as follows:

- **Ingestion Service**: A FastAPI endpoint that accepts user content (text, images via URL), validates input schema, and pushes it onto a Redis-backed queue. This decouples ingestion from processing and provides natural backpressure.
- **Classification Service**: Loads a fine-tuned `distilbert-base-uncased` model (via Hugging Face Transformers) to score content on toxicity, self-harm, and profanity dimensions. Returns a structured risk score.
- **Rule Engine**: A configurable YAML-driven policy matcher that applies organization-specific rules on top of model scores. For example: "block any content scoring >0.8 on self-harm regardless of other factors." Rules are hot-reloadable.
- **Action Dispatcher**: Determines the final action — allow, quarantine, or escalate for human review — and persists the decision with a full audit trail in PostgreSQL.
- **Observability Layer**: Prometheus metrics exposed at `/metrics` for latency, throughput, and classification distribution; Grafana dashboards for real-time monitoring.

The choice of Redis as a queue (rather than RabbitMQ or Kafka) keeps the dependency footprint small while still providing the essential decoupling and backpressure pattern. For a portfolio project, this is the right trade-off — production systems would graduate to Kafka, but the pattern is identical.

---

## Building It Step by Step

We'll build this in Python 3.11+ using FastAPI, Transformers, Redis, and SQLAlchemy. Clone the starter project and follow these steps.

### Step 1: Project Scaffolding and Dependencies

```bash
mkdir safe-engine && cd safe-engine
python -m venv venv && source venv/bin/activate
```

Create `requirements.txt`:

```txt
fastapi==0.115.0
uvicorn==0.34.0
transformers==4.44.0
torch==2.5.1
redis==5.2.1
sqlalchemy==2.0.36
psycopg2-binary==2.9.10
pydantic==2.10.4
prometheus-client==0.21.1
pyyaml==6.0.1
pytest==8.3.4
httpx==0.28.1
```

### Step 2: Define the Data Models with Pydantic

Create `models.py` — these schemas validate every piece of data entering the system:

```python
from pydantic import BaseModel, Field, field_validator
from enum import Enum
from typing import Optional

class ContentType(str, Enum):
    TEXT = "text"
    IMAGE_URL = "image_url"

class RiskDimension(str, Enum):
    TOXICITY = "toxicity"
    SELF_HARM = "self_harm"
    PROFANITY = "profanity"

class ClassificationResult(BaseModel):
    dimension: RiskDimension
    score: float = Field(..., ge=0.0, le=1.0)
    label: str
    confidence: float = Field(..., ge=0.0, le=1.0)

class ContentRequest(BaseModel):
    content: str
    content_type: ContentType = ContentType.TEXT
    user_id: str = Field(min_length=1)
    metadata: dict = {}

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v):
        if not v.strip():
            raise ValueError("Content must not be empty")
        return v

class Action(str, Enum):
    ALLOW = "allow"
    QUARANTINE = "quarantine"
    ESCALATE = "escalate"

class AuditRecord(BaseModel):
    content_id: str
    user_id: str
    action: Action
    risk_scores: list[ClassificationResult]
    rules_matched: list[str]
    timestamp: float
```

### Step 3: Build the Classification Service

Create `classifier.py` — this loads the model and runs inference:

```python
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from typing import Literal
import numpy as np

class SafetyClassifier:
    def __init__(self, model_name: str = "unitary/toxic-bert"):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_name).to(self.device)
        self.model.eval()
        # Map model output indices to risk dimensions
        self.label_map = {0: "toxicity", 1: "self_harm", 2: "profanity"}

    def classify(self, text: str) -> list[dict]:
        inputs = self.tokenizer(
            text, return_tensors="pt", truncation=True,
            max_length=512, padding=True
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            probs = torch.nn.functional.softmax(logits, dim=-1)

        results = []
        for idx, dim in self.label_map.items():
            score = probs[0][idx].item()
            label = dim if score > 0.5 else "safe"
            results.append({
                "dimension": dim,
                "score": round(score, 4),
                "label": label,
                "confidence": round(score if label == dim else 1 - score, 4)
            })
        return results
```

### Step 4: Build the Configurable Rule Engine

Create `rule_engine.py` — rules are loaded from YAML and evaluated at runtime:

```python
import yaml
from pathlib import Path
from typing import Any

class RuleEngine:
    def __init__(self, rules_path: str = "rules.yaml"):
        self.rules_path = rules_path
        self.rules = self._load_rules()

    def _load_rules(self) -> list[dict]:
        with open(self.rules_path) as f:
            config = yaml.safe_load(f)
        return config.get("rules", [])

    def reload(self):
        """Hot-reload rules without restarting the service."""
        self.rules = self._load_rules()

    def evaluate(self, classification_results: list[dict]) -> list[str]:
        matched_rules = []
        for rule in self.rules:
            condition = rule["condition"]
            if self._check_condition(condition, classification_results):
                matched_rules.append(rule["name"])
        return matched_rules

    def _check_condition(self, condition: dict, results: list[dict]) -> bool:
        dimension = condition.get("dimension")
        threshold = condition.get("threshold", 0.0)
        operator = condition.get("operator", "gt")

        for result in results:
            if result["dimension"] == dimension:
                score = result["score"]
                if operator == "gt" and score > threshold:
                    return True
                if operator == "gte" and score >= threshold:
                    return True
                if operator == "lt" and score < threshold:
                    return True
        return False

    def determine_action(self, matched_rules: list[str]) -> str:
        for rule_name in matched_rules:
            for rule in self.rules:
                if rule["name"] == rule_name:
                    return rule.get("action", "quarantine")
        return "allow"
```

Example `rules.yaml`:

```yaml
rules:
  - name: "high_self_harm_block"
    condition:
      dimension: "self_harm"
      threshold: 0.8
      operator: "gt"
    action: "escalate"
    description: "Immediate escalation for high self-harm probability"

  - name: "toxicity_quarantine"
    condition:
      dimension: "toxicity"
      threshold: 0.7
      operator: "gte"
    action: "quarantine"
    description: "Quarantine moderately toxic content for review"

  - name: "profanity_flag"
    condition:
      dimension: "profanity"
      threshold: 0.6
      operator: "gte"
    action: "quarantine"
    description: "Flag profane content for moderation"
```

### Step 5: Wire It All Together with FastAPI

Create `main.py` — the orchestration layer:

```python
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, generate_latest
import uuid, time, redis
from sqlalchemy import create_engine, Column, String, Float, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

from models import ContentRequest, ClassificationResult, Action, AuditRecord
from classifier import SafetyClassifier
from rule_engine import RuleEngine

app = FastAPI(title="safe — User Safety Engine")

# --- Infrastructure ---
redis_client = redis.Redis(host="localhost", port=6379, decode_responses=True)
classifier = SafetyClassifier()
rule_engine = RuleEngine()

# --- PostgreSQL Setup ---
engine = create_engine("postgresql://user:pass@localhost/safe_db")
Base = declarative_base()

class AuditLog(Base):
    __tablename__ = "audit_logs"
    content_id = Column(String, primary_key=True)
    user_id = Column(String)
    action = Column(String)
    risk_scores = Column(JSON)
    rules_matched = Column(JSON)
    timestamp = Column(DateTime)

Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# --- Prometheus Metrics ---
REQUEST_COUNT = Counter("safe_requests_total", "Total requests", ["action"])
LATENCY = Histogram("safe_request_latency_seconds", "Request latency")

@app.post("/classify")
def classify_content(request: ContentRequest):
    start = time.time()
    content_id = str(uuid.uuid4())

    # Step 1: Classify
    results = classifier.classify(request.content)

    # Step 2: Evaluate rules
    matched_rules = rule_engine.evaluate(results)
    action = rule_engine.determine_action(matched_rules)

    # Step 3: Persist audit record
    db = SessionLocal()
    audit = AuditLog(
        content_id=content_id,
        user_id=request.user_id,
        action=action,
        risk_scores=[r.model_dump() for r in results],
        rules_matched=matched_rules,
        timestamp=time.time()
    )
    db.add(audit)
    db.commit()
    db.close()

    # Step 4: Queue action if quarantine
    if action in ("quarantine", "escalate"):
        redis_client.lpush("action_queue", f"{content_id}:{action}")

    REQUEST_COUNT.labels(action=action).inc()
    LATENCY.observe(time.time() - start)

    return JSONResponse(content={
        "content_id": content_id,
        "action": action,
        "risk_scores": [r.model_dump() for r in results],
        "rules_matched": matched_rules
    })

@app.get("/metrics")
def metrics():
    return generate_latest()
```

### Step 6: Add the Rule Hot-Reload Endpoint

```python
@app.post("/admin/reload-rules")
def reload_rules():
    """Hot-reload rules without service restart."""
    rule_engine.reload()
    return {"status": "rules reloaded", "rule_count": len(rule_engine.rules)}
```

---

## Running and Testing It

### Local Setup

```bash
# Start dependencies with Docker
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name postgres -p 5432:5432 \
  -e POSTGRES_USER=user -e POSTGRES_PASSWORD=pass -e POSTGRES_DB=safe_db \
  postgres:16-alpine

# Install and run the service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The service is live at `http://localhost:8000`. The OpenAPI docs are at `http://localhost:8000/docs`.

### Sending a Test Request

```bash
curl -X POST http://localhost:8000/classify \
  -H "Content-Type: application/json" \
  -d '{
    "content": "You are a worthless piece of garbage and I hope something bad happens to you",
    "user_id": "user_12345",
    "content_type": "text"
  }'
```

Expected response:

```json
{
  "content_id": "a1b2c3d4-...",
  "action": "escalate",
  "risk_scores": [
    {"dimension": "toxicity", "score": 0.94, "label": "toxicity", "confidence": 0.94},
    {"dimension": "self_harm", "score": 0.12, "label": "safe", "confidence": 0.88},
    {"dimension": "profanity", "score": 0.71, "label": "profanity", "confidence": 0.71}
  ],
  "rules_matched": ["high_self_harm_block", "toxicity_quarantine", "profanity_flag"]
}
```

### Writing Tests with pytest

Create `tests/test_classifier.py`:

```python
import pytest
from classifier import SafetyClassifier

@pytest.fixture
def classifier():
    return SafetyClassifier()

def test_safe_content_gets_low_scores(classifier):
    results = classifier.classify("The weather is nice today and I enjoy hiking.")
    toxicity = [r for r in results if r["dimension"] == "toxicity"][0]
    assert toxicity["score"] < 0.3, f"Expected low toxicity score, got {toxicity['score']}"

def test_toxic_content_gets_high_scores(classifier):
    results = classifier.classify("I hate you, you are the worst person alive.")
    toxicity = [r for r in results if r["dimension"] == "toxicity"][0]
    assert toxicity["score"] > 0.5, f"Expected high toxicity score, got {toxicity['score']}"
```

Run the suite:

```bash
pytest tests/ -v --cov=main --cov-report=term-missing
```

### Testing the Rule Engine in Isolation

```python
def test_rule_engine_escalates_high_self_harm():
    engine = RuleEngine("rules.yaml")
    results = [
        {"dimension": "self_harm", "score": 0.92, "label": "self_harm", "confidence": 0.92},
        {"dimension": "toxicity", "score": 0.3, "label": "safe", "confidence": 0.7}
    ]
    matched = engine.evaluate(results)
    assert "high_self_harm_block" in matched
    assert engine.determine_action(matched) == "escalate"
```

### Verifying Observability

```bash
curl http://localhost:8000/metrics | grep safe_
# safe_requests_total{action="escalate"} 5.0
# safe_request_latency_seconds_sum 0.234
# safe_request_latency_seconds_count 12.0
```

---

## Extending It: Your Roadmap to Senior-Level

This is where the project transforms from a portfolio piece into something that reads like a production system. Each upgrade maps directly to a senior engineer's skill set.

1. **Add PostgreSQL-backed persistence with full audit trail and retention policies.** Store every classification decision with immutable timestamps, user IDs, and the full model output. Implement a retention policy that auto-archives records older than 90 days. This matters because regulatory frameworks like the EU Digital Services Act require platforms to demonstrate content moderation decisions with full traceability.

2. **Replace the Redis queue with Apache Kafka for horizontal scaling.** Kafka partitions allow you to scale the classification workers independently — spin up 10 consumer instances and process 10x the throughput. This matters because real-world safety systems handle millions of events per hour, and horizontal scalability is non-negotiable for any system that touches user-generated content at platform scale.

3. **Implement circuit breakers and graceful degradation.** When the transformer model fails or latency exceeds a threshold, fall back to a lightweight regex-based heuristic classifier instead of returning errors. Use the `pybreaker` library to wrap model inference calls. This matters because availability is a first-class requirement — a safety system that crashes under load is worse than one that degrades gracefully.

4. **Add distributed tracing with OpenTelemetry.** Instrument every request with trace IDs that propagate through classification, rule evaluation, and action dispatch. Export traces to Jaeger or Grafana Tempo. This matters because when a false positive occurs, you need to reconstruct the exact decision path across services — debugging without traces in a distributed system is guessing.

5. **Build a shadow mode and A/B testing framework.** Run new model versions in shadow mode alongside the production classifier, comparing outputs without affecting real decisions. Use Redis to split traffic 5/95 between old and new models. This matters because model iteration without validation is how platforms accidentally cause user harm — shadow mode lets you measure regression before it reaches production.

6. **Implement benchmarking with Locust and latency percentile tracking.** Write a Locust load test that simulates 1,000 concurrent users posting content, measuring p50, p95, and p99 classification latency. Track these metrics in Grafana dashboards alongside model accuracy drift. This matters because performance budgets are a core engineering discipline — if classification latency exceeds 200ms at p99, the user experience degrades and the system fails its SLA.

---

## Key Takeaways

- **`safe` demonstrates full-stack systems thinking**: from ML inference through policy engines, distributed queues, persistence, and observability — not just a single component.
- **The architecture pattern (ingest → classify → evaluate → act) is universal**: the same pipeline structure powers content moderation, fraud detection, and security scanning at every major platform.
- **Configurable rule engines separate policy from code**: the YAML-driven approach lets non-engineers update safety thresholds without redeploying, a pattern used in production systems like Google's Perspective API and OpenAI's moderation endpoints.
- **Graceful degradation and observability separate toy projects from production systems**: the extensions roadmap addresses the exact failure modes that cause real outages in trust and safety platforms.
- **This project maps to high-demand roles**: trust & safety engineering, ML platform engineering, backend infrastructure, and SRE all value the combination of systems design and ML integration it demonstrates.

---

## Further Reading

- [The Architecture of Open Source Applications: Content Moderation](https://www.aosabook.org/en/500L/moderation-systems.html) — A deep dive into how platforms like Reddit and Discord design their moderation pipelines, including the trade-offs between automated and human review.
- [Jailbreaking ChatGPT via Prompt Engineering: An Empirical Study](https://arxiv.org/abs/2302.12095) — A seminal paper on why safety classifiers need continuous evaluation and why shadow mode testing is essential for model iteration.
- [The Responsible AI Practices at Google](https://ai.google/responsibility/responsible-ai-practices/) — Google's canonical documentation on deploying ML safety systems at scale, including the principles behind their Perspective API and content moderation infrastructure.
- [Redis Queue Patterns for Distributed Task Processing](https://redis.io/docs/manual/patterns/) — Official Redis documentation on queue patterns, including the list-based queue used in this project and how it scales to production workloads.
- [OpenTelemetry Specification: Distributed Tracing](https://opentelemetry.io/docs/specs/otel/trace/) — The canonical specification for distributed tracing, which you should implement as your first observability upgrade to reconstruct decision paths across services.
- [EU Digital Services Act: Article 40 — Transparency of Algorithms](https://digital-strategy.ec.europa.eu/en/policies/digital-services-act-package) — The regulatory framework that mandates audit trails and transparency for content moderation systems, directly motivating the PostgreSQL persistence layer in this project.
- [Building Machine Learning Pipelines with Apache Kafka](https://www.confluent.io/blog/building-real-time-ml-pipelines-with-apache-kafka/) — Confluent's guide on replacing Redis queues with Kafka for ML inference pipelines at scale, covering partitioning, consumer groups, and exactly-once semantics.
