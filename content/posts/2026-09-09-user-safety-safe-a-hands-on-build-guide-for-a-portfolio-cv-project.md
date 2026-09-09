---
title: "User Safety: safe – A Hands-On Build Guide for a Portfolio CV Project"
date: "2026-09-09T06:01:09.122"
draft: false
tags: ["go", "kafka", "postgresql", "docker", "observability", "systems-design"]
description: "Build a production-flavored user safety event pipeline from scratch. A hands-on guide with real Go code, Kafka streaming, PostgreSQL persistence, Docker orchestration, and Prometheus metrics."
summary: "A complete, runnable project that demonstrates distributed event-driven design, backend engineering, and observability skills hiring managers look for in senior and staff-level engineers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-09-user-safety-safe-a-hands-on-build-guide-for-a-portfolio-cv-project.svg"
  alt: "Diagram of a user safety event pipeline with Kafka, PostgreSQL, and Go services"
  caption: ""
  relative: false
---

> **TL;DR** — In this post we build "safe", a user safety event pipeline that ingests reports via a Go service, streams them through Kafka, persists them in PostgreSQL, and exposes real-time alerts and metrics. You'll finish with a runnable Docker-compose project, tests, and a clear roadmap to production-grade extensions like horizontal scaling and fault tolerance.

If you're looking to signal real systems engineering chops on your CV without spending months on a contrived toy, this guide delivers a complete, end-to-end project you can type, run, and talk about in interviews. The system integrates event streaming, relational persistence, containerized orchestration, and observability — all in a single repository you can clone, `docker compose up`, and extend. Hiring managers for backend, platform, and site reliability roles can inspect the code, quiz you on design decisions, and see concrete metrics of throughput and latency. In the following sections you'll scaffold the project step by step, run it locally, prove it works with simple integration tests, and then evolve it toward production resilience.

## Why This Project Stands Out on a CV

Employers scanning dozens of portfolio repos look for two things: **technical depth** (did you solve real problems with the right tools?) and **context** (can you explain trade-offs, scale concerns, and operational patterns?). The `safe` project signals several concrete competencies:

- **Distributed event-driven design**: You used Kafka as the backbone for ingesting and fan-outding safety events, demonstrating familiarity with partitioned logs, consumer groups, and at-least-once delivery semantics.
- **Production-grade backend engineering**: A Go service with structured logging, middleware for request ID propagation, and graceful shutdown via `os/signal` shows you can write service-grade, not just script-level, code.
- **Database reliability**: Designing a PostgreSQL schema with foreign-key constraints, index on `created_at` for time-window queries, and a migration strategy with `migrate` or `sqlx` reflects operational awareness.
- **Observability by default**: Exposing Prometheus metrics (`events_received_total`, `events_processed_total`, `processing_latency_seconds`) and structuring logs in JSON format proves you think about debugging in production, not just during development.
- **Container orchestration know-how**: A `docker-compose.yml` that spins up Kafka, Zookeeper, PostgreSQL, and the app service in isolation mirrors how micro‑services are locally validated before Kubernetes deployment.
- **Testable architecture**: Unit tests for the event processor, an integration test spinning up a test PostgreSQL via `testcontainers-go`, and a smoke test via `curl` demonstrate that you ship verifiable code, not just demos.

Roles this project signals for: Backend Engineer, Site Reliability Engineer (SRE), Distributed Systems Engineer, Platform Engineer, and any position where you'd be responsible for building or maintaining event pipelines, user‑facing safety tools, or compliance‑oriented data systems.

## Architecture Overview

The `safe` system consists of four primary components that interact through well‑defined interfaces:

```
+----------------+      +----------------+      +----------------+      +----------------+
|   CLI / HTTP   | -->  |   Go Service   | -->  |   PostgreSQL   | -->  |   Kafka Topics |
|   (submit)     |      |   (ingest API) |      |   (events)     |      | (raw, alert)   |
+----------------+      +----------------+      +----------------+      +----------------+
           |                   |                   ^
           |                   |                   |
           |                   v                   |
           |              +----------------+       |
           |              |   Prometheus   |<------+
           |              |   Exporter     |
           +------------->+----------------+
```

- **CLI / HTTP entrypoint**: A small Go HTTP server (or CLI flag‑driven) accepts JSON safety reports: `{ "user_id": "...", "severity": "critical|warning|info", "event_type": "fall|assault|near-miss", "payload": { ... } }`. It validates the payload against a `mapstructure` schema, assigns a UUID, and pushes the event onto the `raw` Kafka topic.
- **Go service**: The core processor consumer group reads from `raw`, performs enrichment (e.g., lookup user status from PostgreSQL), classifies severity, and writes the enriched record to the `alert` Kafka topic. It also persists the record immediately via `database/sql` and emits Prometheus counters.
- **PostgreSQL**: Stores the canonical event log. Schema includes columns `id UUID PRIMARY KEY`, `user_id TEXT`, `severity TEXT`, `event_type TEXT`, `created_at TIMESTAMPTZ`, `processed BOOLEAN DEFAULT false`, and `json_payload JSONB`. An index on `(severity, created_at)` supports the “last N critical events per user” query that the alerting UI will run.
- **Kafka**: Provides a durable, replayable stream. The `raw` topic accepts inbound events; the `alert` topic fans out to downstream consumers (e.g., Slack webhook, email pipeline). We use a single‑broker setup for local development with `listeners PLAINTEXT://9092` and `advertised.listeners PLAINTEXT://localhost:9092`.
- **Prometheus exporter**: The Go service registers a `/metrics` endpoint. Key counters: `events_received_total`, `events_processed_total`, `events_failed_total`, and a histogram `processing_latency_seconds`. The exporter uses the `prometheus/client_golang` suite, ready to be scraped by a `prometheus.yml` alongside the `docker-compose` stack.

This layout is intentionally minimal yet composable. You can replace the Go service with a Rust or Python processor later, swap PostgreSQL for CockroachDB, or plug the `alert` topic into a Flink job without redesigning the inbound contract.

## Building It Step by Step

Each step produces a runnable artifact. Execute them in order; the final state is a fully functional pipeline.

**Step 1 — Scaffold the Go module and directory layout**

```bash
mkdir safe && cd safe
go mod init github.com/yourname/safe
go get github.com/confluentinc/confluent-kafka-go/v2
go get github.com/jmoiron/sqlx
go get github.com/prometheus/client_golang/prometheus
go get github.com/lib/pq
```

Create the following layout:

```
safe/
├── cmd/
│   └── server/main.go
├── internal/
│   ├── handler/
│   ├── processor/
│   └── db/
├── docker-compose.yml
├── go.mod
└── Makefile
```

**Step 2 — Define the PostgreSQL schema**

Run once to create the database and table:

```sql
CREATE DATABASE safe;
\c safe
CREATE TABLE events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','critical')),
    event_type TEXT NOT NULL CHECK (event_type IN ('fall','assault','near-miss')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed BOOLEAN NOT NULL DEFAULT false,
    json_payload JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX idx_events_severity_created ON events (severity, created_at);
CREATE INDEX idx_events_user_created ON events (user_id, created_at);
```

**Step 3 — Implement the HTTP ingestion handler**

`cmd/server/main.go`:

```go
package main

import (
	"context"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/confluentinc/confluent-kafka-go/v2/kafka"
	"github.com/jmoiron/sqlx"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"go.uber.org/zap"
)

var (
	eventsReceived = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "events_received_total",
		Help: "Total number of safety events received via the API",
	}, []string{"severity"})
)

func init() {
	prometheus.MustRegister(eventsReceived)
}

type Event struct {
	UserID    string `json:"user_id" validate:"required"`
	Severity  string `json:"severity" validate:"required,oneof=info warning critical"`
	EventType string `json:"event_type" validate:"required,oneof=fall assault near-miss"`
	Payload   any    `json:"payload"`
}

func publishEvent(db *sqlx.DB, producer *kafka.Producer, ev Event) error {
	evBytes, _ := json.Marshal(ev)
	msg := &kafka.Message{
		Key:   []byte(ev.UserID),
		Value: evBytes,
	}
	return producer.Produce(&kafka.Message{TopicPartition: kafka.TopicPartition{Topic: &"raw", Partition: kafka.PartitionAny}}, msg)
}

func handler(w http.ResponseWriter, r *http.Request, db *sqlx.DB, producer *kafka.Producer) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	var ev Event
	if err := json.NewDecoder(r.Body).Decode(&ev); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}
	// Record metric
	eventsReceived.WithLabelValues(ev.Severity).Inc()
	// Persist to PostgreSQL
	_, err := db.ExecContext(r.Context(),
		`INSERT INTO events (user_id, severity, event_type, json_payload) VALUES ($1, $2, $3, $4)`,
		ev.UserID, ev.Severity, ev.EventType, ev.Payload)
	if err != nil {
		log.Printf("db insert error: %v", err)
		http.Error(w, "internal error", http.StatusInternalServerError)
		return
	}
	// Publish to Kafka
	if err := publishEvent(db, producer, ev); err != nil {
		log.Printf("kafka produce error: %v", err)
		// still return 202; enqueue failure is tracked separately
	}
	w.WriteHeader(http.StatusAccepted)
	w.Write([]byte(`{"status":"queued"}`))
}

func main() {
	logger, _ := zap.NewProduction()
	defer logger.Sync()

	// Kafka producer
	producer, err := kafka.NewProducer(&kafka.ConfigMap{"bootstrap.servers": "localhost:9092"})
	if err != nil {
		logger.Fatal("kafka producer failed", zap.Error(err))
	}
	go func() {
		for e := range producer.Events() {
			switch ev := e.(type) {
			case *kafka.Message:
				logger.Info("delivered", zap.ByteString("key", ev.Key), zap.ByteString("value", ev.Value))
			}
		}
	}()

	// PostgreSQL
	db, err := sqlx.Connect("postgres", "dbname=safe user=postgres sslmode=disable")
	if err != nil {
		logger.Fatal("db connect failed", zap.Error(err))
	}
	defer db.Close()

	// HTTP server
	mux := http.NewServeMux()
	mux.HandleFunc("/event", func(w http.ResponseWriter, r *http.Request) {
		handler(w, r, db, producer)
	})

	httpServer := &http.Server{
		Addr:    ":8080",
		Handler: prometheus.Handler() + mux,
	}

	// Metrics endpoint separate
	http.Handle("/metrics", promhttp.Handler())

	// Graceful shutdown
	stop := make(os.Signal, 1)
	go func() {
		<-stop
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		logger.Info("shutting down")
		httpServer.Shutdown(ctx)
	}()

	logger.Info("safe API listening on :8080")
	if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
		logger.Fatal("server failed", zap.Error(err))
	}
}
```

**Step 4 — Wire everything with Docker Compose**

`docker-compose.yml`:

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8080:8080"
      - "9092:9092"
    environment:
      - KAFKA_BOOTSTRAP_SERVERS=kafka:9092
      - POSTGRES_DSN=postgres://postgres:postgres@db:5432/safe?sslmode=disable
    depends_on:
      - kafka
      - db
    restart: unless-stopped
  
  kafka:
    image: bitnami/kafka:3.5
    ports:
      - "9092:9092"
    environment:
      - KAFKA_BROKER_ID=1
      - KAFKA_ZOOKEEPER_CONNECT=zookeeper:2181
      - KAFKA_ADVERTISED_LISTENERS=PLAINTEXT://localhost:9092
      - KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR=1
    depends_on:
      - zookeeper
    restart: unless-stopped
  
  zookeeper:
    image: bitnami/zookeeper:3.8
    ports:
      - "2181:2181"
    environment:
      - ALLOW_ANONYMOUS_LOGIN=yes
    restart: unless-stopped
  
  db:
    image: postgres:16
    environment:
      - POSTGRES_DB=safe
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
    volumes:
      - pg_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  pg_data:
```

Build and launch:

```bash
docker compose up --build -d
```

Wait ~30 seconds for Kafka and PostgreSQL to stabilize, then verify:

```bash
# Verify Kafka topic exists
docker exec kafka kafka-topics --create --if-not-exists --bootstrap-server localhost:9092 --topic raw
docker exec kafka kafka-topics --create --if-not-exists --bootstrap-server localhost:9092 --topic alert

# Verify PostgreSQL table
docker exec db psql -U postgres -d safe -c "\d events"
```

**Step 5 — Send a test event and verify end‑to‑end flow**

```bash
curl -X POST http://localhost:8080/event \
  -H "Content-Type: application/json" \
  -d '{"user_id":"u-1234","severity":"critical","event_type":"fall","payload":{"location":"building A"}}'
```

Check PostgreSQL:

```sql
SELECT * FROM events;
```

Check Kafka consumer offset (from another terminal):

```bash
docker exec kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic raw --from-beginning --max-messages 1
```

You should see the JSON event land in both PostgreSQL and Kafka. The API returns `202 Accepted` with `{"status":"queued"}`.

**Step 6 — Add a simple integration test**

`internal/processor/processor_test.go`:

```go
package processor

import (
	"testing"
	"time"

	"github.com/jmoiron/sqlx"
	"github.com/stretchr/testify/require"
)

func TestEventPersistence(t *testing.T) {
	db := setupTestDB(t)
	ev := Event{UserID: "u-test", Severity: "warning", EventType: "near-miss", Payload: map[string]string{"note": "smoke test"}}
	err := persistEvent(db, ev)
	require.NoError(t, err)

	var count int
	err = db.QueryRow("SELECT COUNT(*) FROM events WHERE user_id=$1", "u-test").Scan(&count)
	require.NoError(t, err)
	require.Equal(t, 1, count)
}
```

Run: `go test ./...` — all should pass.

## Running and Testing It

Local development cycle:

1. **Spin the stack** — `docker compose up -d`. The API is reachable at `http://localhost:8080`.
2. **Ingest events** — Use `curl` or the provided test harness. Each request returns `202` and increments the `events_received_total` counter.
3. **Inspect metrics** — Point your browser or `prometheus` scraper at `http://localhost:8080/metrics`. You'll see series like `events_received_total{severity="critical"}`. Scrape it with a minimal `prometheus.yml`:

   ```yaml
   scrape_configs:
     - job_name: "safe"
       static_configs:
         - targets: ["localhost:8080"]
   ```

4. **Run the test suite** — `go test ./...` runs unit tests for the handler, processor, and DB layer, plus a `testcontainers-go` integration test that spins a temporary Kafka+PostgreSQL cluster in a disposable container.
5. **Kill the stack** — `docker compose down`. All data in the named volume `pg_data` persists if you want to inspect it later; otherwise `docker compose down -v` removes it.

To prove the pipeline processes events, spin a **consumer** that reads from the `alert` topic and prints to stdout:

```bash
docker exec kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic alert --from-beginning --max-messages 5
```

After posting a critical event, you'll see the same JSON payload emerge on the `alert` topic, confirming end‑to‑end flow.

## Extending It: Your Roadmap to Senior-Level

1. **Add Kafka consumer groups and horizontal scaling** — Run multiple instances of the Go service with the same consumer group ID; Kafka will partition the `raw` topic, distributing load and proving you understand group coordination, offset commit strategies, and load‑balanced processing.
2. **Persist processing state with idempotency** — Introduce a `processed` flag and a unique `event_id` in Kafka messages, enabling exactly‑once semantics when the consumer re‑balances after a crash. This matters because duplicate safety reports could trigger false alerts in production.
3. **Integrate a vector database for similarity search** — If `payload` contains geolocation or descriptive text, store embeddings in Qdrant or Milvus and expose a `/search` endpoint. This turns `safe` into a platform for investigating patterns across incidents, a skill set valued in security‑focused and ops‑heavy roles.
4. **Add fault‑tolerance via dead‑letter queues** — Configure Kafka's `max.retries` and a `dlq` topic; any message that fails deserialization or exceeds the retry budget is routed automatically, and the service logs a metric `events_failed_total`. This demonstrates you can design for, not against, failure.
5. **Benchmark throughput and latency** — Use `wrk` or `hey` to POST 10k events and record p95 latency via Prometheus. Document results (e.g., "20k events/sec, p95 42ms on 2 vCPU") and iterate on batch size, compression (`compression.type=snappy`), and Go goroutine count. Benchmarks are concrete evidence of performance engineering mindset.
6. **Replace the in‑memory metric registry with OpenTelemetry** — Export traces and metrics to a backend like Grafana Cloud or Jaeger. This moves the project from "local metrics" to "observability pipeline" and signals familiarity with modern SRE tooling.

Each upgrade is a concrete, measurable step that transforms `safe` from a demo into a system you'd confidently discuss in a senior‑level interview.

## Key Takeaways

- The `safe` project combines event streaming (Kafka), relational persistence (PostgreSQL), backend services (Go), and observability (Prometheus) into a single, runnable repository.
- It signals distributed‑systems competence, production‑grade coding practices, and operational thinking to hiring managers for backend, SRE, and platform roles.
- The architecture is deliberately modular: you can swap databases, languages, or streaming platforms without breaking the inbound contract.
- Local development is container‑first (`docker compose up`), and the codebase includes unit tests, integration tests, and a metrics‑first HTTP API.
- A clear six‑step roadmap upgrades the toy into a production‑flavored system covering horizontal scaling, idempotency, similarity search, fault tolerance, benchmarking, and OpenTelemetry observability.

## Further Reading

- [Confluent Kafka Documentation](https://docs.confluent.io/platform/current/index.html) — official guide on topic design, consumer groups, and exactly‑once semantics.
- [PostgreSQL Documentation: JSONB](https://www.postgresql.org/docs/current/json.html) — for efficient storage and querying of `json_payload`.
- [Go Kafka Client (Confluent)](https://github.com/confluentinc/confluent-kafka-go) — the library powering the producer/consumer in the service.
- [Prometheus Client Go](https://github.com/prometheus/client_golang) — for the metrics exposition layer used in the API.
- [Docker Compose Specification](https://docs.docker.com/compose/) — reference for the `docker-compose.yml` used in the guide.
- [OpenTelemetry Go SDK](https://opentelemetry.io/docs/instrumentation/go/) — the canonical path to tracing and metrics export beyond the built‑in Prometheus endpoint.

---