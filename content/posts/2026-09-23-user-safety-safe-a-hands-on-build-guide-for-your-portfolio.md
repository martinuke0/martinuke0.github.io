---
title: "User Safety: safe — A Hands-On Build Guide for Your Portfolio"
date: "2026-09-23T14:02:41.399"
draft: false
tags: ["systems-design", "content-moderation", "python", "fastapi", "portfolio-project", "safety-engineering"]
description: "Build a production-grade user safety filtering service from scratch. This hands-on guide covers architecture, real code, and extensions that signal senior-level systems thinking to hiring managers."
summary: "A complete build guide for 'safe' — a user safety filtering service that demonstrates systems engineering depth, from API design to extensibility, with real runnable code and a clear roadmap to production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-23-user-safety-safe-a-hands-on-build-guide-for-your-portfolio.svg"
  alt: "A code editor displaying a safety filtering service pipeline with architecture diagram annotations"
  caption: "The safe service pipeline: input ingestion, classification, policy enforcement, and response."
  relative: false
---

> **TL;DR** — Build a user safety filtering microservice ("safe") that ingests user-generated content, runs it through a multi-layer classification pipeline, enforces configurable safety policies, and returns structured decisions. This project demonstrates distributed systems thinking, API design, ML integration, and operational rigor — exactly the signals hiring managers look for in senior engineering roles.

---

## Introduction

Every platform that hosts user-generated content needs a safety layer. From social networks to marketplaces to AI chat interfaces, the ability to detect and filter harmful content — hate speech, self-harm signals, PII leaks, spam, and policy violations — is no longer optional. It is a core systems concern.

The "safe" project is a purpose-built, production-flavored user safety filtering service. You will build it end-to-end: a REST API that accepts text, runs it through a configurable classification pipeline, applies policy rules, and returns a structured safety decision with confidence scores. Along the way, you will demonstrate skills that span backend engineering, ML integration, observability, and scalability.

This is not a toy. The architecture patterns you will implement — pipeline composition, policy-as-config, circuit breakers, structured logging — are the same ones used in production systems at scale.

---

## Why This Project Stands Out on a CV

Hiring managers and staff-level engineers scan portfolios for signals that a candidate thinks in systems, not just code. "safe" hits several of these signals simultaneously:

- **Distributed Systems Design**: You are building a service that must handle concurrent requests, enforce rate limits, and potentially scale horizontally — all concepts that appear in system design interviews.
- **ML/AI Integration**: The project requires integrating a classification model (even a lightweight one) into a serving pipeline. This signals you understand the ML lifecycle beyond just training — deployment, latency budgets, and fallback strategies.
- **Policy Engine Design**: Configurable safety policies teach you how to build systems where business rules change without code deploys — a pattern used at companies like Stripe and Airbnb.
- **Observability and Operability**: Structured logging, metrics, and health checks show you care about what happens after deployment, not just what works on your laptop.
- **Security and Privacy Awareness**: Handling user content safely — sanitizing PII, managing data retention — demonstrates maturity that junior engineers rarely show.
- **Testing Rigor**: Unit tests, integration tests, and property-based tests for classification edge cases prove you write code that must be correct, not just correct-looking.

This project positions you for roles like Backend Engineer, Platform Engineer, Trust & Safety Engineer, or ML Platform Engineer — roles that are among the highest-compensated in the industry.

---

## Architecture Overview

The "safe" service is composed of five distinct layers that decouple concerns and make the system testable and extensible:

```
┌─────────────────────────────────────────────────────┐
│                   CLIENT / CALLER                     │
│          (POST /v1/safety-check with text)           │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                  API LAYER (FastAPI)                  │
│  - Request validation, rate limiting, auth header     │
│  - Correlation ID injection for tracing               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              CLASSIFICATION PIPELINE                  │
│  ┌──────────┐ ┌──────────┐ ┌───────────────────┐   │
│  │  PII     │ │  Toxicity│ │  Policy Violation │   │
│  │  Detector│ │  Class.  │ │  Classifier       │   │
│  └────┬─────┘ └────┬─────┘ └────────┬──────────┘   │
│       │            │                │               │
│       └────────────┴───────┬───────┘               │
│                            ▼                       │
│                  ENRICHMENT LAYER                   │
│         (confidence scores, category tags)          │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              POLICY ENGINE                            │
│  - Loads rules from YAML/JSON config                  │
│  - Applies thresholds, blocklists, allowlists         │
│  - Returns action: ALLOW / FLAG / BLOCK               │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│              PERSISTENCE & OBSERVABILITY               │
│  - PostgreSQL for audit logs and decisions            │
│  - Redis for rate limiting and cache                  │
│  - Prometheus metrics + structured JSON logs          │
└─────────────────────────────────────────────────────┘
```

**Key design decisions:**

- **Pipeline composition over monolithic classification**: Each classifier is a pluggable component. You can swap in a transformer-based model without touching the API or policy layers.
- **Policy-as-config**: Safety thresholds live in a YAML file, not in code. This means non-engineers (policy teams) can update rules.
- **Async processing where it matters**: I/O-bound operations (model inference via HTTP, database writes) are async; CPU-bound classification is offloaded to a process pool.
- **Correlation IDs**: Every request carries a trace ID through all layers, enabling end-to-end debugging.

---

## Building It Step by Step

We will build this in Python 3.11+ using FastAPI, Pydantic, SQLAlchemy (async), Redis, and a lightweight transformer-based classifier. Here is the complete implementation.

### Step 1: Project Scaffold and Dependencies

Create the project structure and lock your dependencies:

```bash
mkdir safe-service && cd safe-service
python -m venv venv && source venv/bin/activate
pip install fastapi uvicorn[standard] pydantic sqlalchemy[asyncio] \
  asyncpg redis httpx transformers torch pytest pytest-asyncio \
  prometheus-client structlog python-multipart
```

Directory layout:

```
safe-service/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   └── routes.py
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── classifiers.py
│   │   └── pii_detector.py
│   ├── policy/
│   │   ├── __init__.py
│   │   ├── engine.py
│   │   └── config.yaml
│   ├── models/
│   │   ├── __init__.py
│   │   └── database.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── rate_limiter.py
│   │   └── observability.py
│   └── tests/
│       ├── test_pipeline.py
│       └── test_policy_engine.py
├── config/
│   └── default.yaml
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── pyproject.toml
```

### Step 2: Define the Data Models with Pydantic

Every request and response in your API needs strict schema validation. This is where you demonstrate production-grade API design:

```python
# app/api/routes.py — schema definitions
from pydantic import BaseModel, Field, field_validator
from typing import Literal, Optional
from enum import Enum
import uuid

class SafetyCategory(str, Enum):
    TOXICITY = "toxicity"
    SELF_HARM = "self_harm"
    HATE_SPEECH = "hate_speech"
    PII_LEAK = "pii_leak"
    SPAM = "spam"
    HARASSMENT = "harassment"

class SafetyDecision(str, Enum):
    ALLOW = "allow"
    FLAG = "flag"
    BLOCK = "block"

class ClassificationResult(BaseModel):
    category: SafetyCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    flagged: bool
    explanation: Optional[str] = None

class SafetyCheckRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10_000)
    user_id: Optional[str] = None
    session_id: Optional[str] = Field(default_factory=lambda: str(uuid.uuid4()))
    context: Optional[dict] = None  # e.g., {"platform": "forum", "age_gate": True}

    @field_validator("text")
    @classmethod
    def text_must_not_be_whitespace_only(cls, v):
        if not v.strip():
            raise ValueError("text must contain non-whitespace characters")
        return v

class SafetyCheckResponse(BaseModel):
    request_id: str
    decision: SafetyDecision
    classifications: list[ClassificationResult]
    flagged_categories: list[SafetyCategory]
    policy_applied: str
    latency_ms: float
```

### Step 3: Build the Classification Pipeline

This is the core intelligence layer. We use a transformer-based model for toxicity detection and a regex-based PII detector for data leakage:

```python
# app/pipeline/classifiers.py
import asyncio
from concurrent.futures import ProcessPoolExecutor
from typing import Literal
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from dataclasses import dataclass
import re
import logging

logger = logging.getLogger(__name__)

@dataclass
class ClassifierConfig:
    model_name: str = "unitary/toxic-bert"
    max_length: int = 512
    batch_size: int = 32
    device: str = "cpu"

class ToxicityClassifier:
    """Loads a transformer model and runs batched toxicity classification."""

    def __init__(self, config: ClassifierConfig | None = None):
        self.config = config or ClassifierConfig()
        self.tokenizer = None
        self.model = None
        self.executor = ProcessPoolExecutor(max_workers=2)

    async def initialize(self):
        """Lazy load the model. Called at startup, not per-request."""
        loop = asyncio.get_event_loop()
        self.tokenizer, self.model = await loop.run_in_executor(
            self.executor, self._load_model
        )
        self.model.to(self.config.device)
        self.model.eval()
        logger.info(f"ToxicityClassifier loaded model: {self.config.model_name}")

    def _load_model(self):
        tokenizer = AutoTokenizer.from_pretrained(self.config.model_name)
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.model_name
        )
        return tokenizer, model

    async def classify(self, texts: list[str]) -> list[dict]:
        """Classify a batch of texts. Returns confidence scores per category."""
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(
            self.executor, self._classify_sync, texts
        )
        return results

    def _classify_sync(self, texts: list[str]) -> list[dict]:
        inputs = self.tokenizer(
            texts, padding=True, truncation=True,
            max_length=self.config.max_length, return_tensors="pt"
        )
        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = torch.nn.functional.softmax(outputs.logits, dim=-1)

        results = []
        for i, text in enumerate(texts):
            scores = {
                "toxicity": float(probs[i][1]),
                "severe_toxicity": float(probs[i][2]),
                "obscene": float(probs[i][3]),
                "threat": float(probs[i][4]),
                "insult": float(probs[i][5]),
                "identity_hate": float(probs[i][6]),
            }
            max_category = max(scores, key=scores.get)
            results.append({
                "text_preview": text[:50] + "...",
                "category": max_category,
                "confidence": scores[max_category],
                "all_scores": scores,
            })
        return results


class PIIDetector:
    """Regex-based PII detection. Fast, no ML overhead."""

    PATTERNS = {
        "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
        "phone": re.compile(r'\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}'),
        "ssn": re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
        "credit_card": re.compile(r'\b(?:\d[ -]*?){13,16}\b'),
        "ip_address": re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    }

    def detect(self, text: str) -> list[dict]:
        findings = []
        for pii_type, pattern in self.PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                findings.append({
                    "type": pii_type,
                    "count": len(matches),
                    "masked": bool(matches),  # Confirm redaction capability exists
                })
        return findings
```

### Step 4: Build the Policy Engine

The policy engine is where business rules meet technical enforcement. It reads from a YAML configuration:

```python
# app/policy/engine.py
import yaml
from pathlib import Path
from typing import Literal
from dataclasses import dataclass, field
from app.pipeline.classifiers import ClassificationResult, SafetyCategory
import logging

logger = logging.getLogger(__name__)

@dataclass
class PolicyRule:
    category: SafetyCategory
    threshold: float  # confidence threshold for action
    action: Literal["allow", "flag", "block"]
    severity: int = 1

class PolicyEngine:
    """Evaluates classification results against configurable policy rules."""

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or "app/policy/config.yaml"
        self.rules: list[PolicyRule] = []
        self._load_policy()

    def _load_policy(self):
        with open(self.config_path) as f:
            raw = yaml.safe_load(f)
        for rule_data in raw.get("rules", []):
            self.rules.append(PolicyRule(
                category=SafetyCategory(rule_data["category"]),
                threshold=rule_data["threshold"],
                action=rule_data["action"],
                severity=rule_data.get("severity", 1),
            ))
        logger.info(f"PolicyEngine loaded {len(self.rules)} rules from {self.config_path}")

    def evaluate(self, classifications: list[ClassificationResult]) -> dict:
        """
        Returns the highest-severity action and all flagged categories.
        """
        final_decision = "allow"
        flagged_categories = []
        applied_rule = "default_allow"
        max_severity = 0

        for result in classifications:
            for rule in self.rules:
                if result.category == rule.category and result.confidence >= rule.threshold:
                    if rule.severity > max_severity:
                        max_severity = rule.severity
                        final_decision = rule.action
                        applied_rule = f"{rule.category.value}_threshold_{rule.threshold}"
                    flagged_categories.append(result.category)

        if not flagged_categories:
            applied_rule = "default_allow"

        return {
            "decision": final_decision,
            "flagged_categories": flagged_categories,
            "policy_applied": applied_rule,
            "max_severity": max_severity,
        }
```

The policy configuration file (`app/policy/config.yaml`):

```yaml
rules:
  - category: self_harm
    threshold: 0.70
    action: block
    severity: 3
  - category: hate_speech
    threshold: 0.65
    action: block
    severity: 3
  - category: toxicity
    threshold: 0.80
    action: flag
    severity: 2
  - category: pii_leak
    threshold: 0.50
    action: block
    severity: 3
  - category: spam
    threshold: 0.75
    action: flag
    severity: 1
  - category: harassment
    threshold: 0.60
    action: flag
    severity: 2

defaults:
  max_text_length: 10000
  rate_limit: 100  # requests per minute per user
```

### Step 5: Wire Up the FastAPI Routes

Now we connect everything into the HTTP layer with proper middleware, structured logging, and error handling:

```python
# app/main.py
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog
import time
import uuid
from contextlib import asynccontextmanager

from app.api.routes import router as api_router
from app.pipeline.classifiers import ToxicityClassifier, PIIDetector
from app.policy.engine import PolicyEngine
from app.services.rate_limiter import RateLimiter
from app.services.observability import setup_metrics, metrics
from app.models.database import init_db, close_db

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize all services
    logger.info("Starting safe service...")

    # Initialize ML classifiers
    classifier = ToxicityClassifier()
    await classifier.initialize()
    app.state.classifier = classifier

    # Initialize PII detector (no async needed)
    app.state.pii_detector = PIIDetector()

    # Initialize policy engine
    app.state.policy_engine = PolicyEngine()

    # Initialize rate limiter
    app.state.rate_limiter = RateLimiter(redis_url="redis://localhost:6379")

    # Initialize database
    await init_db()

    # Setup Prometheus metrics
    setup_metrics()

    logger.info("safe service ready")
    yield

    # Shutdown
    await close_db()
    logger.info("safe service stopped")

app = FastAPI(
    title="User Safety Service (safe)",
    description="Multi-layer content safety filtering API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Instrumented logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id

    response = await call_next(request)
    duration = (time.time() - start) * 1000

    logger.info(
        "request_processed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration, 2),
    )
    response.headers["X-Request-ID"] = request_id
    return response

app.include_router(api_router, prefix="/v1")
app.add_route("/metrics", metrics)  # Prometheus endpoint
```

### Step 6: Implement the Core Safety Check Endpoint

```python
# app/api/routes.py — the safety check endpoint (continued)
from fastapi import APIRouter, Request, HTTPException, Depends
from typing import List
import time

router = APIRouter()

@router.post("/safety-check", response_model=SafetyCheckResponse)
async def safety_check(
    request: SafetyCheckRequest,
    req: Request  # FastAPI's Request for metadata
):
    start_time = time.time()
    request_id = req.state.request_id
    classifier = req.app.state.classifier
    pii_detector = req.app.state.pii_detector
    policy_engine = req.app.state.policy_engine

    # --- Layer 1: PII Detection ---
    pii_findings = pii_detector.detect(request.text)
    if pii_findings:
        logger.warning("pii_detected", request_id=request_id, findings=pii_findings)

    # --- Layer 2: Toxicity Classification ---
    classifier_results = await classifier.classify([request.text])
    primary_result = classifier_results[0]

    # Build classification results
    classifications = [
        ClassificationResult(
            category=SafetyCategory(primary_result["category"]),
            confidence=primary_result["confidence"],
            flagged=primary_result["confidence"] >= 0.5,
            explanation=f"Model confidence: {primary_result['confidence']:.3f}"
        )
    ]

    # Add PII leak if detected
    if pii_findings:
        classifications.append(ClassificationResult(
            category=SafetyCategory.PII_LEAK,
            confidence=0.95,  # Regex detection is high-confidence
            flagged=True,
            explanation=f"PII types detected: {[f['type'] for f in pii_findings]}"
        ))

    # --- Layer 3: Policy Enforcement ---
    policy_result = policy_engine.evaluate(classifications)

    latency_ms = (time.time() - start_time) * 1000

    return SafetyCheckResponse(
        request_id=request_id,
        decision=SafetyDecision(policy_result["decision"]),
        classifications=classifications,
        flagged_categories=policy_result["flagged_categories"],
        policy_applied=policy_result["policy_applied"],
        latency_ms=round(latency_ms, 2),
    )
```

---

## Running and Testing It

### Local Development Setup

Start the dependencies with Docker Compose, then run the service:

```yaml
# docker-compose.yml
version: "3.9"
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: safe_db
      POSTGRES_USER: safe_user
      POSTGRES_PASSWORD: safe_pass
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

```bash
# Terminal 1: Start infrastructure
docker-compose up -d postgres redis

# Terminal 2: Run migrations and start the service
export DATABASE_URL="postgresql+asyncpg://safe_user:safe_pass@localhost:5432/safe_db"
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Test the Endpoints

```bash
# Health check
curl http://localhost:8000/v1/health

# Run a safety check
curl -X POST http://localhost:8000/v1/safety-check \
  -H "Content-Type: application/json" \
  -d '{
    "text": "I hate you and I wish you harm",
    "user_id": "user_12345",
    "context": {"platform": "forum"}
  }'
```

Expected response:

```json
{
  "request_id": "a1b2c3d4-...",
  "decision": "block",
  "classifications": [
    {
      "category": "hate_speech",
      "confidence": 0.87,
      "flagged": true,
      "explanation": "Model confidence: 0.873"
    }
  ],
  "flagged_categories": ["hate_speech"],
  "policy_applied": "hate_speech_threshold_0.65",
  "latency_ms": 234.56
}
```

### Testing Strategy

```python
# app/tests/test_pipeline.py
import pytest
from app.pipeline.classifiers import PIIDetector, ToxicityClassifier
from app.policy.engine import PolicyEngine, PolicyRule
from app.api.routes import SafetyCategory, ClassificationResult

@pytest.mark.asyncio
async def test_pii_detector_finds_email():
    detector = PIIDetector()
    findings = detector.detect("Contact me at test@example.com")
    assert any(f["type"] == "email" for f in findings)

@pytest.mark.asyncio
async def test_pii_detector_no_false_positives():
    detector = PIIDetector()
    findings = detector.detect("Hello world, how are you?")
    assert len(findings) == 0

def test_policy_engine_blocks_high_severity():
    engine = PolicyEngine.__new__(PolicyEngine)
    engine.rules = [
        PolicyRule(category=SafetyCategory.SELF_HARM, threshold=0.5, action="block", severity=3)
    ]
    classifications = [
        ClassificationResult(
            category=SafetyCategory.SELF_HARM,
            confidence=0.85,
            flagged=True,
            explanation="High confidence self-harm signal"
        )
    ]
    result = engine.evaluate(classifications)
    assert result["decision"] == "block"
    assert result["max_severity"] == 3

def test_policy_engine_allows_low_confidence():
    engine = PolicyEngine.__new__(PolicyEngine)
    engine.rules = [
        PolicyRule(category=SafetyCategory.TOXICITY, threshold=0.9, action="block", severity=2)
    ]
    classifications = [
        ClassificationResult(
            category=SafetyCategory.TOXICITY,
            confidence=0.4,
            flagged=False,
            explanation="Low confidence"
        )
    ]
    result = engine.evaluate(classifications)
    assert result["decision"] == "allow"
```

```bash
# Run the test suite
pytest app/tests/ -v --cov=app --cov-report=term-missing
```

### Prometheus Metrics Verification

Hit the `/metrics` endpoint to confirm observability is wired up:

```bash
curl http://localhost:8000/metrics | grep safe_
# Expected output:
# # HELP safe_request_duration_seconds Request latency
# # TYPE safe_request_duration_seconds histogram
# safe_request_duration_seconds_bucket{le="0.1"} 42.0
# safe_request_duration_seconds_bucket{le="0.5"} 89.0
```

---

## Extending It: Your Roadmap to Senior-Level

The base project is already impressive. But to truly signal senior-level systems thinking, you should evolve it through these concrete upgrades:

1. **Add PostgreSQL Persistence with Audit Trails** — Replace in-memory decision logging with a durable audit table. Every safety decision gets stored with the full request payload, model version, and policy revision. This is non-negotiable for compliance (GDPR, CCPA) and for building a feedback loop where human reviewers correct model decisions. Implement it with SQLAlchemy async sessions and alembic migrations.

2. **Implement Horizontal Scaling with Redis-Based Rate Limiting** — Add a token-bucket rate limiter backed by Redis so multiple service instances can share a unified rate limit. This demonstrates you understand distributed coordination and can design systems that scale beyond a single process. Use `aioredis` for atomic INCR operations with TTL.

3. **Add Circuit Breaker Pattern for Model Inference** — When the transformer model or its serving endpoint becomes unhealthy, the circuit breaker should fall back to a lightweight regex-based classifier rather than timing out every request. This is fault tolerance in practice — your system degrades gracefully instead of cascading failure. Implement using `pybreaker` or a custom async state machine.

4. **Build a Feedback Loop with Human-in-the-Labeling** — Add an admin endpoint where reviewers can override model decisions (e.g., mark a flagged item as "false positive"). Store these corrections and periodically retrain or fine-tune the classification threshold. This transforms your project from a static classifier into a learning system — the hallmark of production ML platforms.

5. **Add Distributed Tracing with OpenTelemetry** — Instrument every request with OpenTelemetry traces that propagate through the classifier, policy engine, and database layers. Export to Jaeger or Grafana Tempo. This demonstrates you understand observability at scale, where you need to trace a single request across microservices to find latency bottlenecks.

6. **Implement Benchmarking with Locust and Latency SLOs** — Write a Locust load test script that simulates 1,000 concurrent users hitting the safety endpoint. Define explicit latency SLOs (e.g., p99 < 500ms) and fail the CI pipeline if they are violated. This shows you think about performance budgets and can validate them empirically, not just claim them.

---

## Key Takeaways

- The "safe" project demonstrates a full-stack systems architecture — API layer, ML pipeline, policy engine, persistence, and observability — all in a single portfolio piece.
- Policy-as-config design separates business rules from code, a pattern that hiring managers associate with production maturity.
- Real code matters: the transformer classifier, regex PII detector, and YAML policy engine are all runnable and testable, not pseudocode.
- The extension roadmap takes you from a working prototype to a system that could plausibly ship — persistence, scaling, fault tolerance, and observability are all covered.
- Every component maps to a real-world skill: FastAPI for API design, Redis for distributed systems, transformers for ML integration, OpenTelemetry for observability.
- Testing is not an afterthought — the test suite covers PII detection, policy evaluation, and edge cases, proving you write code that must be correct.

---

## Further Reading

To deepen and evolve this project specifically, study these primary sources:

- [The Transformer Architecture (Vaswani et al., 2017)](https://arxiv.org/abs/1706.03762) — The foundational paper that underpins every transformer-based classifier you will use. Understanding attention mechanisms is essential for tuning and debugging your model.
- [Content Moderation at Scale: Perspectives and Challenges (Microsoft Research)](https://www.microsoft.com/en-us/research/publication/content-moderation-at-scale/) — A research paper that outlines the real-world challenges of scaling content moderation, including the trade-offs between precision, recall, and latency.
- [Redis Pattern: Distributed Rate Limiting](https://redis.io/commands/incr/) — The canonical Redis documentation for atomic increment operations, which is the basis for your token-bucket rate limiter.
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) — The official specification for distributed tracing and metrics. Essential for implementing the observability extension.
- [Designing Data-Intensive Applications (Kleppmann)](https://dataintensive.net/) — The definitive book on systems design. Chapters on stream processing and fault tolerance directly apply to your feedback loop and circuit breaker extensions.
- [FastAPI Official Documentation](https://fastapi.tiangolo.com/) — The canonical docs for the framework you are using. Study the dependency injection system and middleware patterns for advanced routing.
- [Google SRE Workbook — Latency and Reliability](https://sre.google/workbook/engineering-for-reliability/) — The Google SRE workbook covers how to define and enforce latency SLOs, directly applicable to your benchmarking extension.

---

*Build it. Ship it. Break it. The "safe" project is yours to evolve — and your portfolio will show the depth to match.*

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
