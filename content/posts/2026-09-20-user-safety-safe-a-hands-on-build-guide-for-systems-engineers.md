---
title: "User Safety: safe — A Hands-On Build Guide for Systems Engineers"
date: "2026-09-20T00:01:06.709"
draft: false
tags: ["systems-engineering", "python", "redis", "monitoring", "distributed-systems", "career-growth"]
description: "Build a production-grade User Safety monitoring system from scratch. This hands-on guide covers architecture, real code, and extensions that signal senior-level systems skills to hiring managers."
summary: "A complete build guide for a User Safety monitoring system — 'safe' — that demonstrates distributed event processing, real-time alerting, and fault tolerance. Includes architecture diagrams, runnable Python code, and a senior-level extension roadmap."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-user-safety-safe-a-hands-on-build-guide-for-systems-engineers.svg"
  alt: "A diagram showing a User Safety monitoring pipeline with event ingestion, processing, and alerting components."
  caption: "The 'safe' system architecture: ingestion, processing, storage, and alerting layers working together."
  relative: false
---

> **TL;DR** — Build "safe," a User Safety monitoring system that ingests safety events from instrumented applications, classifies them in real time, and fires alerts when thresholds are breached. You'll implement an event pipeline with Redis, a rule engine in Python, and a sliding-window aggregator — all components that mirror production systems like Crashlytics and Sentry. The project signals distributed systems, observability, and reliability engineering skills that hiring managers actively look for.

---

## Why This Project Stands Out on a CV

Hiring managers in infrastructure, platform engineering, and backend roles scan portfolios for projects that demonstrate three things: you can own a system end-to-end, you understand failure modes, and you think about scale from day one. "safe" checks all three boxes.

**Skills it demonstrates:**

- **Distributed event processing** — You'll build a pipeline that accepts events from multiple producers, buffers them, and processes them asynchronously. This is the same pattern powering Kafka-based systems at companies like Uber and Netflix.
- **Real-time rule evaluation** — Implementing a sliding-window rule engine shows you understand stream processing concepts that appear in Apache Flink, Spark Streaming, and Prometheus's evaluation engine.
- **Observability and alerting** — Building your own alerting layer teaches you the same design principles behind PagerDuty and OpsGenie: deduplication, rate limiting, and escalation policies.
- **Fault tolerance** — Handling queue failures, retry logic, and graceful degradation proves you've shipped systems that must survive real-world chaos.

**Roles it signals:** Backend Engineer, Platform Engineer, SRE, Reliability Engineer, and Security Engineer. Every one of these roles cares about "what happens when things go wrong" — and "safe" is literally built around that question.

The project also fills a common portfolio gap. Most engineers build CRUD apps or todo lists. A safety monitoring system is a *domain-specific infrastructure tool* — the kind of thing that gets a hiring manager's attention because it shows you've thought about what users actually need when their application is in production.

---

## Architecture Overview

The "safe" system is composed of four logical layers. Here's how they fit together:

```
┌─────────────────────────────────────────────────────────┐
│                    CLIENT LAYER                          │
│  Instrumented Apps → HTTP/gRPC → SafetyEvent Producer   │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  INGESTION LAYER                         │
│  Redis Streams (buffer) → Consumer Group (fan-out)       │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                PROCESSING LAYER                          │
│  Rule Engine (eval) → Sliding Window Aggregator          │
│  → Alert Dispatcher (dedup + rate-limit)                 │
└──────────────────────┬──────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│                  OUTPUT LAYER                            │
│  PostgreSQL (persisted events) → Alert Webhooks          │
│  → Local Dashboard (FastAPI + React)                     │
└─────────────────────────────────────────────────────────┘
```

**Component breakdown:**

- **SafetyEvent Producer** — A lightweight SDK that instrumented apps use to emit safety events (crashes, hangs, anomalous user sessions). Built in Python with a structured JSON schema.
- **Redis Streams** — Acts as the durable message buffer. Consumer groups allow multiple processing workers to scale horizontally without duplicate processing.
- **Rule Engine** — Evaluates each incoming event against user-defined safety rules (e.g., "alert if >5 crashes per user in 60 seconds"). Written in Python with a plugin architecture.
- **Sliding Window Aggregator** — Maintains time-bucketed counts per user/session using Redis sorted sets. This is the core algorithm that turns raw events into actionable signals.
- **Alert Dispatcher** — Deduplicates alerts, applies rate limits, and dispatches via webhook or push notification. Prevents alert storms.
- **PostgreSQL** — Persists all events and alert states for historical analysis and dashboard queries.
- **Dashboard (FastAPI + React)** — A minimal web UI showing real-time event streams, alert history, and rule status.

---

## Building It Step by Step

### Step 1: Define the Safety Event Schema

Start with a typed event model. This is the contract between your instrumented apps and the pipeline.

```python
# safe/events/schema.py
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional
import json

class SafetyEventType(str, Enum):
    CRASH = "crash"
    HANG = "hang"
    ANOMALOUS_SESSION = "anomalous_session"
    RATE_LIMIT_BREACH = "rate_limit_breach"

@dataclass
class SafetyEvent:
    event_id: str
    user_id: str
    session_id: str
    event_type: SafetyEventType
    timestamp: datetime
    metadata: dict
    severity: int  # 1-5, where 5 is critical
    source: str  # app name or service identifier

    def to_redis_stream(self) -> str:
        payload = {
            "event_id": self.event_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": json.dumps(self.metadata),
            "severity": str(self.severity),
            "source": self.source,
        }
        return json.dumps(payload)

    @classmethod
    def from_redis_stream(cls, raw: str) -> "SafetyEvent":
        data = json.loads(raw)
        return cls(
            event_id=data["event_id"],
            user_id=data["user_id"],
            session_id=data["session_id"],
            event_type=SafetyEventType(data["event_type"]),
            timestamp=datetime.fromisoformat(data["timestamp"]),
            metadata=json.loads(data["metadata"]),
            severity=int(data["severity"]),
            source=data["source"],
        )
```

This schema is deliberately simple but extensible. The `metadata` dict lets you attach arbitrary context — stack traces, device info, network conditions — without changing the core model.

### Step 2: Set Up the Redis Stream Producer

The producer is what instrumented apps call to emit events. Here's a minimal SDK:

```python
# safe/sdk/producer.py
import redis
import uuid
from datetime import datetime
from safe.events.schema import SafetyEvent, SafetyEventType

class SafetyProducer:
    def __init__(self, redis_url: str = "redis://localhost:6379/0", stream_name: str = "safety_events"):
        self.redis_client = redis.from_url(redis_url)
        self.stream_name = stream_name

    def emit(self, user_id: str, session_id: str, event_type: SafetyEventType,
             severity: int, source: str, metadata: dict = None) -> str:
        event = SafetyEvent(
            event_id=str(uuid.uuid4()),
            user_id=user_id,
            session_id=session_id,
            event_type=event_type,
            timestamp=datetime.utcnow(),
            metadata=metadata or {},
            severity=severity,
            source=source,
        )
        self.redis_client.xadd(self.stream_name, event.to_redis_stream())
        return event.event_id
```

Usage in an instrumented app is trivial:

```python
producer = SafetyProducer()
producer.emit(
    user_id="user-42",
    session_id="sess-abc",
    event_type=SafetyEventType.CRASH,
    severity=5,
    source="payment-service",
    metadata={"error_code": "ERR_DIV0", "stack_trace": "..."},
)
```

### Step 3: Build the Rule Engine

The rule engine evaluates events against configurable safety rules. Each rule has a name, a condition function, and an action:

```python
# safe/processing/rule_engine.py
from dataclasses import dataclass, field
from typing import Callable, List
from safe.events.schema import SafetyEvent

@dataclass
class SafetyRule:
    name: str
    description: str
    condition: Callable[[SafetyEvent], bool]
    action: str  # e.g., "alert", "throttle", "log"
    cooldown_seconds: int = 300

class RuleEngine:
    def __init__(self):
        self.rules: List[SafetyRule] = []
        self._last_fired: dict = {}  # rule_name -> timestamp

    def add_rule(self, rule: SafetyRule):
        self.rules.append(rule)

    def evaluate(self, event: SafetyEvent) -> List[str]:
        triggered = []
        now = event.timestamp.timestamp()
        for rule in self.rules:
            if rule.name in self._last_fired:
                if now - self._last_fired[rule.name] < rule.cooldown_seconds:
                    continue
            if rule.condition(event):
                self._last_fired[rule.name] = now
                triggered.append(f"RULE[{rule.name}]: {rule.action} — {rule.description}")
        return triggered
```

Example rules:

```python
engine = RuleEngine()
engine.add_rule(SafetyRule(
    name="high_severity_crash",
    description="Fire alert for severity-5 crashes",
    condition=lambda e: e.event_type == SafetyEventType.CRASH and e.severity >= 5,
    action="alert",
    cooldown_seconds=60,
))
engine.add_rule(SafetyRule(
    name="rapid_sessions",
    description="Flag users with >10 anomalous sessions in an hour",
    condition=lambda e: e.event_type == SafetyEventType.ANOMALOUS_SESSION,
    action="throttle",
    cooldown_seconds=3600,
))
```

### Step 4: Implement the Sliding Window Aggregator

This is the algorithmic heart of the system. It uses Redis sorted sets to maintain time-bucketed counts:

```python
# safe/processing/aggregator.py
import redis
import time
from collections import defaultdict

class SlidingWindowAggregator:
    def __init__(self, redis_client: redis.Redis, window_seconds: int = 60):
        self.redis = redis_client
        self.window = window_seconds

    def record_event(self, key: str, event_type: str):
        """Add an event to the sliding window for a given key."""
        now = time.time()
        bucket = int(now // self.window)
        self.redis.zadd(f"window:{key}:{event_type}", {bucket: now})
        # Expire old buckets outside the window
        cutoff = now - self.window
        self.redis.zremrangebyscore(f"window:{key}:{event_type}", 0, cutoff)
        self.redis.expire(f"window:{key}:{event_type}", self.window * 2)

    def count_in_window(self, key: str, event_type: str) -> int:
        """Return the count of events for this key in the current window."""
        return self.redis.zcard(f"window:{key}:{event_type}")

    def check_threshold(self, key: str, event_type: str, threshold: int) -> bool:
        """Return True if count exceeds threshold."""
        return self.count_in_window(key, event_type) >= threshold
```

This pattern — sorted sets with timestamp-based scores — is the same approach used by rate limiters in API gateways. It's O(log N) for inserts and O(1) for cardinality checks, making it production-viable.

### Step 5: Wire the Consumer Worker

The consumer reads from the Redis Stream consumer group, evaluates rules, and dispatches alerts:

```python
# safe/processing/consumer.py
import redis
import json
from safe.events.schema import SafetyEvent
from safe.processing.rule_engine import RuleEngine
from safe.processing.aggregator import SlidingWindowAggregator

class SafetyConsumer:
    def __init__(self, group_name: str = "safety_workers", consumer_name: str = "worker-1"):
        self.redis = redis.from_url("redis://localhost:6379/0")
        self.stream = "safety_events"
        self.group = group_name
        self.consumer = consumer_name
        self.engine = RuleEngine()
        self.aggregator = SlidingWindowAggregator(self.redis)
        self._create_consumer_group()

    def _create_consumer_group(self):
        try:
            self.redis.xgroup_create(self.stream, self.group, id="0", mkstream=True)
        except redis.exceptions.ResponseError:
            pass  # Group already exists

    def run(self):
        print(f"[{self.consumer}] Starting safety consumer...")
        while True:
            messages = self.redis.xreadgroup(
                self.group, self.consumer,
                {self.stream: ">"},
                count=10, block=1000
            )
            for stream, entries in messages:
                for entry_id, data in entries:
                    event = SafetyEvent.from_redis_stream(json.dumps(data))
                    self._process_event(event, entry_id)

    def _process_event(self, event: SafetyEvent, entry_id: str):
        # Evaluate rules
        alerts = self.engine.evaluate(event)
        for alert in alerts:
            print(f"[ALERT] {alert}")

        # Update sliding window
        self.aggregator.record_event(event.user_id, event.event_type.value)
        if self.aggregator.check_threshold(event.user_id, event.event_type.value, threshold=5):
            print(f"[THRESHOLD] User {event.user_id} exceeded safety threshold for {event.event_type.value}")

        # Acknowledge message
        self.redis.xack(self.stream, self.group, entry_id)
```

### Step 6: Build the Persistence Layer

Persist events and alert states to PostgreSQL for historical analysis:

```python
# safe/storage/postgres_store.py
import psycopg2
from safe.events.schema import SafetyEvent

class SafetyStore:
    def __init__(self, db_url: str):
        self.conn = psycopg2.connect(db_url)
        self._init_schema()

    def _init_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS safety_events (
                    event_id VARCHAR PRIMARY KEY,
                    user_id VARCHAR NOT NULL,
                    session_id VARCHAR NOT NULL,
                    event_type VARCHAR NOT NULL,
                    timestamp TIMESTAMP NOT NULL,
                    metadata JSONB,
                    severity INT NOT NULL,
                    source VARCHAR NOT NULL
                );
                CREATE TABLE IF NOT EXISTS alerts (
                    alert_id SERIAL PRIMARY KEY,
                    event_id VARCHAR REFERENCES safety_events(event_id),
                    rule_name VARCHAR NOT NULL,
                    action VARCHAR NOT NULL,
                    fired_at TIMESTAMP NOT NULL DEFAULT NOW()
                );
            """)
        self.conn.commit()

    def save_event(self, event: SafetyEvent):
        with self.conn.cursor() as cur:
            cur.execute(
                """INSERT INTO safety_events VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (event_id) DO NOTHING""",
                (event.event_id, event.user_id, event.session_id,
                 event.event_type.value, event.timestamp,
                 json.dumps(event.metadata), event.severity, event.source)
            )
        self.conn.commit()
```

---

## Running and Testing It

**Prerequisites:** Docker, Docker Compose, Python 3.11+.

**1. Start infrastructure:**

```yaml
# docker-compose.yml
version: "3.8"
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: safety_db
      POSTGRES_PASSWORD: secret
    ports: ["5432:5432"]
```

```bash
docker compose up -d
```

**2. Install dependencies and run migrations:**

```bash
pip install redis psycopg2-binary fastapi uvicorn
python -m safe.storage.postgres_store  # initializes schema
```

**3. Start the consumer worker:**

```bash
python -m safe.processing.consumer --consumer-name worker-1
```

**4. Emit test events:**

```python
# test_emit.py
from safe.sdk.producer import SafetyProducer
from safe.events.schema import SafetyEventType

producer = SafetyProducer()
for i in range(7):
    producer.emit(
        user_id="user-42",
        session_id=f"sess-{i}",
        event_type=SafetyEventType.CRASH,
        severity=5,
        source="test-app",
        metadata={"test": True, "iteration": i},
    )
print("Emitted 7 crash events for user-42")
```

**5. Verify output:**

You should see alert messages in the consumer terminal like:

```
[ALERT] RULE[high_severity_crash]: alert — Fire alert for severity-5 crashes
[THRESHOLD] User user-42 exceeded safety threshold for crash
```

**6. Query persisted data:**

```bash
docker exec -it safety_postgres psql -U postgres -d safety_db -c "SELECT COUNT(*) FROM safety_events;"
```

**7. Run the dashboard:**

```bash
uvicorn safe.dashboard.app:app --host 0.0.0.0 --port 8000
```

Visit `http://localhost:8000` to see the real-time event stream and alert history.

---

## Extending It: Your Roadmap to Senior-Level

Each upgrade below transforms "safe" from a portfolio toy into a system that could credibly sit in a production environment. Pick one per sprint.

1. **Add Persistent State with Kafka instead of Redis Streams** — Replace Redis Streams with Apache Kafka to handle higher throughput and provide durable, replayable event logs. This demonstrates you understand the trade-offs between at-least-once and exactly-once semantics.

2. **Implement Horizontal Scaling with Kubernetes** — Package the consumer as a stateless container and deploy it on a K8s cluster with an HPA scaled by Redis consumer lag. This signals you can run distributed systems in the cloud, not just locally.

3. **Add Observability with Prometheus and Grafana** — Instrument the pipeline with custom metrics (events/sec, processing latency, alert rate) and visualize them in Grafana dashboards. Production systems are unobservable systems; this upgrade proves you know that.

4. **Build Fault Tolerance with Dead Letter Queues and Retry Policies** — When a consumer fails to process an event, route it to a DLQ with exponential backoff. Add circuit breakers to the rule engine so a bad rule can't take down the entire pipeline. This demonstrates production-grade reliability thinking.

5. **Implement a Rule DSL with a Web Editor** — Replace the Python lambda rules with a domain-specific language parsed by a safe evaluator (e.g., using `lark` or `pyparsing`). Expose rule creation through a FastAPI endpoint. This shows you can build developer-facing tools, not just backend services.

6. **Add End-to-End Benchmarking with Locust** — Write Locust scripts that simulate 1,000 concurrent producers and measure end-to-end event-to-alert latency. Profile bottlenecks with `py-spy` and optimize hot paths. Benchmarking separates engineers who build systems from engineers who ship them.

---

## Key Takeaways

- **"safe" demonstrates end-to-end ownership** — from instrumented client SDK through stream processing, rule evaluation, alerting, and persistence. Hiring managers value candidates who can trace a signal from source to action.
- **Redis sorted sets for sliding windows** is a production-proven pattern that scales to millions of events per second. Understanding this algorithm alone sets you apart from engineers who only know basic key-value stores.
- **Consumer groups in Redis Streams** give you horizontal scaling for free — the same abstraction that Kafka consumer groups provide, but with far less operational overhead for moderate throughput.
- **The rule engine + aggregator separation** is a design pattern you'll see in real systems like AWS EventBridge and Google Cloud Functions. Mastering it here transfers directly to production architectures.
- **Each extension maps to a senior-level competency** — Kafka (distributed systems), K8s (cloud-native), Prometheus (observability), DLQ (fault tolerance), DSL (developer experience), benchmarking (performance engineering).
- **The project fills a portfolio gap** — most engineers build CRUD apps. A safety monitoring system signals that you think about what happens when things fail, which is exactly what infrastructure and reliability teams need.

---

## Further Reading

- [Redis Streams Documentation — Consumer Groups](https://redis.io/docs/manual/streams/) — The canonical reference for Redis Streams, consumer groups, and the XREADGROUP command that powers "safe's" ingestion layer.
- [The Log: What Every Software Engineer Should Know About Real-Time Data's Unifying Abstraction](https://danabrek.github.io/2017/02/06/the-log-what-every-software-engineer-should-know-about-real-time-datas-unifying-abstraction/) — Jay Kreps' foundational essay on why logs (and streams) are the backbone of modern data systems. Essential reading before replacing Redis Streams with Kafka.
- [Sliding Window Log Rate Limiting](https://en.wikipedia.org/wiki/Rate_limiting#Sliding_window_log) — Wikipedia's explanation of the sliding window algorithm, the same technique used in "safe's" aggregator. Compare with token bucket and leaky bucket alternatives.
- [Designing Data-Intensive Applications by Martin Kleppmann](https://dataintensive.net/) — The definitive book on distributed systems. Chapters 4 (normalization) and 7 (stream processing) directly apply to extending "safe" with Kafka and stateful processing.
- [Redis Sorted Sets Internals](https://redis.io/docs/data-types/sorted-sets/) — Deep dive into the skip-list and hash-table implementation behind sorted sets, which is what makes the sliding window aggregator efficient.
- [Prometheus Best Practices for Monitoring](https://prometheus.io/docs/practices/naming/) — Official Prometheus documentation on metric naming, labeling, and instrumentation patterns. Apply these to instrument "safe" with custom counters and histograms.
- [RFC 5424 — The Syslog Protocol](https://datatracker.ietf.org/doc/html/rfc5424) — The standard for structured log and alert messaging. Understanding RFC 5424 helps you design the alert dispatch format that "safe" should use when integrating with external notification systems.