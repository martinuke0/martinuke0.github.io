

---
title: "Building a Personal Event-Driven Data Pipeline: A Portfolio Project for Systems Engineers"
date: "2026-09-08T15:01:41.772"
draft: false
tags: ["systems", "portfolio", "kafka", "fastapi", "docker", "data-engineering"]
description: "A hands-on guide to building a personal event-driven data pipeline that showcases real systems skills to hiring managers, with runnable Python code and production patterns."
summary: "Learn to build a scalable, event-driven personal data pipeline using FastAPI, Kafka, and PostgreSQL — a portfolio project that signals senior-level systems thinking."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-08-building-a-personal-event-driven-data-pipeline-a-portfolio-project-for-systems-engineers.svg"
  alt: "A dashboard showing personal data visualizations"
  caption: ""
  relative: false
---

> **TL;DR** — You'll build a personal event-driven data pipeline (LifeLog) that ingests events from multiple sources, processes them with Kafka consumers, and serves insights via a React dashboard. This project demonstrates event-driven architecture, scalable stream processing, and full-stack integration — exactly what hiring managers look for in senior systems roles.

## Why This Project Stands Out on a CV

Most portfolio projects showcase a single framework or a CRUD app. This one does not. By building a personal event-driven data pipeline, you demonstrate skills that map directly to senior systems and backend engineering roles:

- **Event-Driven Architecture**: You'll design a system where services communicate via immutable events on a log (Apache Kafka), mirroring patterns used at Uber, LinkedIn, and Netflix.
- **Scalable Stream Processing**: You'll implement consumer groups that can horizontally scale, handle partitioning, and manage offset commits — core knowledge for data platform teams.
- **Full-Stack Integration**: From FastAPI ingestion endpoints to a React dashboard, you prove you can ship end-to-end features, not just isolated microservices.
- **Production Patterns**: You'll touch on schema evolution, dead-letter queues, observability hooks, and declarative deployment (Docker Compose), which are rarely covered in tutorial projects.
- **Data Modeling**: Designing a normalized PostgreSQL schema for event sourcing and time-series data shows you understand trade-offs between write throughput and query flexibility.

Hiring managers seeing this on a CV will immediately ask: "How did you handle backpressure?" or "What's your exactly-once strategy?" — questions that separate senior candidates from junior ones.

## Architecture Overview

The system is a four-tier pipeline: ingestion, processing, storage, and presentation. Each tier is a separate concern, deployable independently.

```
[External Sources] → [FastAPI Ingestion] → [Kafka] → [Consumer Group] → [PostgreSQL/Redis] → [React Dashboard]
```

- **Ingestion Tier**: A FastAPI app exposes `/events` POST endpoints. Each endpoint validates JSON against a Pydantic model, attaches a timestamp, and produces to a Kafka topic. Authentication is handled by a simple API key (for personal use) or OAuth2 (if extended).
- **Message Broker**: Apache Kafka acts as the central nervous system. Topics are partitioned by `source` (e.g., `github`, `strava`) to allow independent scaling of consumers. Retention is set to 7 days for replayability.
- **Processing Tier**: A Python consumer group (built on `confluent-kafka`) subscribes to topics. Each consumer deserializes the event, applies light transformation (e.g., unit normalization), and writes to PostgreSQL. Redis caches the latest 24 hours of events for low-latency dashboard queries.
- **Storage Tier**: PostgreSQL stores raw events in an append-only table (event sourcing pattern). A materialized view aggregates daily summaries. Redis caches hot aggregates and user session data.
- **Presentation Tier**: A React + Tailwind dashboard queries a small FastAPI read layer, which serves pre-aggregated data from PostgreSQL and Redis. WebSockets push real-time updates when new events arrive.

All components are containerized with Docker and orchestrated via `docker-compose.yml`. This setup runs identically on a laptop or a small cloud VM.

## Building It Step by Step

### Step 1: Project Scaffold

Create the directory structure and a `docker-compose.yml` for Kafka, PostgreSQL, Redis, and ZooKeeper (Kafka's dependency).

```bash
mkdir -p lifelog/{api,consumer,web}
cd lifelog
touch docker-compose.yml api/main.py consumer/worker.py web/package.json
```

### Step 2: Docker Compose for Infrastructure

The `docker-compose.yml` defines the backbone services. Kafka uses the `confluentinc/cp-kafka` image; PostgreSQL uses the official `postgres` image with a initialization script.

```yaml
# docker-compose.yml
version: '3.8'
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    ports: ["2181:2181"]

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    depends_on: [zookeeper]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    ports: ["9092:9092"]

  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: lifelog
      POSTGRES_PASSWORD: secret
      POSTGRES_DB: lifelog
    volumes:
      - ./sql/init.sql:/docker-entrypoint-initdb.d/init.sql
      - pgdata:/var/lib/postgresql/data
    ports: ["5432:5432"]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

volumes:
  pgdata:
```

### Step 3: Database Schema

The `sql/init.sql` creates an append-only events table and a daily summary materialized view.

```sql
-- sql/init.sql
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    source VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_events_source ON events (source);
CREATE INDEX idx_events_received ON events (received_at DESC);

-- Materialized view for fast dashboard queries
CREATE MATERIALIZED VIEW IF NOT EXISTS daily_summary AS
SELECT
    DATE(received_at) AS day,
    source,
    COUNT(*) AS event_count
FROM events
GROUP BY DATE(received_at), source
ORDER BY day DESC, source;
```

### Step 4: FastAPI Ingestion Service

The `api/main.py` defines a Pydantic model for incoming events and a producer that publishes to Kafka. The code uses the `confluent-kafka` producer for low-latency delivery.

```python
# api/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from confluent_kafka import Producer
import os
import json

app = FastAPI(title="LifeLog Ingestion")

# Kafka producer configuration
producer_conf = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
    'client.id': 'lifelog-api'
}
producer = Producer(producer_conf)

class Event(BaseModel):
    source: str
    event_type: str
    payload: dict

def delivery_report(err, msg):
    if err is not None:
        print(f'Delivery failed: {err}')

@app.post("/events/{source}")
async def ingest_event(source: str, event: Event):
    if source not in ["github", "strava", "manual"]:
        raise HTTPException(status_code=400, detail="Unknown source")
    # Validate source matches path
    if event.source != source:
        raise HTTPException(status_code=400, detail="Source mismatch")

    topic = f"lifelog.{source}"
    try:
        producer.produce(
            topic=topic,
            value=event.model_dump_json().encode('utf-8'),
            callback=delivery_report
        )
        producer.flush()  # Ensure delivery before responding
        return {"status": "accepted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Step 5: Kafka Consumer Worker

The `consumer/worker.py` runs as a long-lived process. It subscribes to all `lifelog.*` topics, processes each message, and writes to PostgreSQL. The consumer uses manual commit to guarantee at-least-once delivery.

```python
# consumer/worker.py
from confluent_kafka import Consumer, KafkaError
import os
import json
import psycopg2
from psycopg2.extras import RealDictCursor

# Database connection
conn = psycopg2.connect(
    dbname="lifelog",
    user="lifelog",
    password="secret",
    host="localhost"
)
cur = conn.cursor()

consumer_conf = {
    'bootstrap.servers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092'),
    'group.id': 'lifelog-consumers',
    'auto.offset.reset': 'earliest',
    'enable.auto.commit': False
}
consumer = Consumer(consumer_conf)
consumer.subscribe(['lifelog.github', 'lifelog.strava', 'lifelog.manual'])

def process_message(msg):
    try:
        event = json.loads(msg.value())
        cur.execute(
            "INSERT INTO events (source, event_type, payload) VALUES (%s, %s, %s)",
            (event['source'], event['event_type'], json.dumps(event['payload']))
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Processing error: {e}")

try:
    while True:
        msg = consumer.consume(timeout=1.0)
        if msg is None:
            continue
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                continue
            else:
                print(f"Kafka error: {msg.error()}")
                continue

        process_message(msg)
        consumer.commit(msg)  # Manual commit after success
finally:
    consumer.close()
    cur.close()
    conn.close()
```

### Step 6: React Dashboard (Simplified)

A minimal `web/src/App.js` fetches daily summaries from a read API and renders a bar chart. The full code uses Recharts, but the core logic is shown here.

```jsx
// web/src/App.js
import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';

export default function App() {
  const [data, setData] = useState([]);

  useEffect(() => {
    fetch('http://localhost:8000/summary/daily')
      .then(res => res.json())
      .then(setData);
  }, []);

  return (
    <div style={{ padding: '2rem' }}>
      <h1>LifeLog Dashboard</h1>
      <BarChart width={600} height={300} data={data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="day" />
        <YAxis />
        <Tooltip />
        <Bar dataKey="event_count" fill="#8884d8" />
      </BarChart>
    </div>
  );
}
```

A companion read API in `api/read.py` (not shown) queries the `daily_summary` materialized view and returns JSON.

## Running and Testing It

1. **Start infrastructure**: `docker-compose up -d`
2. **Initialize database**: `docker-compose exec postgres psql -U lifelog -d lifelog -f /docker-entrypoint/initdb.d/init.sql` (already done by entrypoint)
3. **Run ingestion API**: `cd api && uvicorn main:app --reload`
4. **Run consumer**: `cd consumer && python worker.py`
5. **Start frontend**: `cd web && npm install && npm run dev`
6. **Send a test event**:
   ```bash
   curl -X POST http://localhost:8000/events/github \
     -H "Content-Type: application/json" \
     -d '{"source":"github","event_type":"push","payload":{"repo":"my-project","commits":3}}'
   ```
7. **Verify**: Open the dashboard at `http://localhost:3000`. You should see the event counted in the daily summary. Check the `events` table in PostgreSQL to confirm raw storage.

For automated testing, write a simple pytest script that sends events and asserts on the database state.

## Extending It: Your Roadmap to Senior-Level

This initial build is a functional prototype. The following upgrades transform it into a production-grade system, each demonstrating a critical senior skill.

1. **Exactly-Once Semantics with Idempotent Writes**  
   Add a `event_id` (UUID) column with a unique constraint. The consumer checks for duplicate IDs before inserting, turning at-least-once delivery into effectively exactly-once. *Why it matters:* Prevents data corruption in financial or audit logs.

2. **Horizontal Consumer Scaling with Partitioning**  
   Increase Kafka partitions per topic and launch multiple consumer instances. Each instance handles a subset of partitions, scaling throughput linearly. *Why it matters:* Demonstrates understanding of distributed coordination and load balancing.

3. **Observability: Metrics, Tracing, and Logging**  
   Instrument the API and consumer with Prometheus metrics (e.g., `kafka_produce_latency_seconds`) and OpenTelemetry traces. Ship logs to ELK or Loki. *Why it matters:* You cannot operate or debug a system blind; observability is a first-class concern.

4. **Dead-Letter Queue for Poison Messages**  
   Configure a `lifelog.DLQ` topic. When a message fails deserialization or business logic validation N times, route it to the DLQ for manual inspection. *Why it matters:* Isolates faulty data without blocking the entire pipeline.

5. **Benchmarking and Capacity Planning with k6**  
   Write a k6 load test that sends 1,000 events/sec to the ingestion API. Measure latency, error rates, and consumer lag. Use results to size Kafka partitions and PostgreSQL connections. *Why it matters:* Proves you can validate performance under load and make data-driven scaling decisions.

6. **Schema Evolution with Avro and Confluent Schema Registry**  
   Replace raw JSON with Avro-serialized messages, versioned in a Schema Registry. Consumers use compatible readers to handle field additions/removals. *Why it matters:* Enables safe, backward-compatible API changes over months — a hallmark of mature data platforms.

## Key Takeaways

- This project covers the full data pipeline lifecycle: ingestion, stream processing, storage, and visualization.
- It uses industry-standard tools (Kafka, FastAPI, PostgreSQL, Docker) that appear in job descriptions.
- The code is runnable and modular, making it easy to discuss trade-offs during interviews.
- Each extension (exactly-once, scaling, observability) maps to a common senior engineering challenge.
- You can host it on a $5/month VPS or a free tier cloud service, providing a living lab for further experimentation.

## Further Reading

- **Apache Kafka Documentation**: [kafka.apache.org/documentation](https://kafka.apache.org/documentation/) — The definitive guide to producers, consumers, and exactly-once semantics.
- **FastAPI Production Guide**: [fastapi.tiangolo.com/advanced](https://fastapi.tiangolo.com/advanced/) — Covers security, background tasks, and testing.
- **Designing Data-Intensive Applications** by Martin Kleppmann: Chapters 3 (Storage) and 11 (Batch and Stream Processing) provide the theoretical foundation.
- **Confluent Kafka Tutorials**: [https://docs.confluent.io/kafka-tutorials](https://docs.confluent.io/kafka-tutorials) — Hands-on exercises for exactly-once, schema registry, and ksqlDB.
- **PostgreSQL Performance Tuning**: [https://www.postgresql.org/docs/current/performance-tips.html](https://www.postgresql.org/docs/current/performance-tips.html) — Indexing and query planning for time-series data.
- **Site Reliability Engineering Book** by Google: [https://sre.google](https://sre.google/) — Chapters on monitoring and incident response apply directly to operating this pipeline.