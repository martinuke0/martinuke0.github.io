---
title: "Hands‑On: Build a Production‑Grade Metrics Pipeline with Go, Prometheus & Grafana"
date: "2026-10-29T03:00:44.977"
draft: false
tags: ["go", "systems", "devops", "monitoring", "side-project"]
description: "Build a production‑grade metrics pipeline with Go, Prometheus, and Grafana – a hands‑on side project that showcases real‑world systems engineering skills."
summary: "A step‑by‑step guide to building a personal metrics pipeline that collects, stores, and visualizes system metrics using Go, Prometheus, and Grafana."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-29-handson-build-a-productiongrade-metrics-pipeline-with-go-prometheus-grafana.svg"
  alt: "A sleek dashboard displaying real-time system metrics"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you'll build a fully runnable metrics pipeline in Go that scrapes system metrics, stores them in PostgreSQL, and visualizes them with Grafana. The project uses Prometheus client libraries, Docker Compose for local orchestration, and demonstrates production‑grade patterns like health checks, error handling, and observability. By the end you'll have a portfolio piece that hiring managers can inspect, run, and extend.

Welcome! A strong side project can turn a blank CV line into a concrete conversation starter. Hiring managers for backend, SRE, and data‑engineering roles love to see a runnable system that shows you can design, build, and operate real infrastructure. In this guide you’ll create a personal metrics pipeline: a Go service that exposes OS‑level metrics, a Prometheus server that scrapes and stores them, PostgreSQL (via TimescaleDB) for long‑term retention, and Grafana for beautiful dashboards. Everything runs locally with Docker Compose, so you can demo it in minutes and then extend it to production‑grade scale.

## Why This Project Stands Out on a CV

- **Go systems programming** – You’ll write idiomatic Go, manage a module, and use the official Prometheus client library, proving you can ship production‑grade services.  
- **Observability fundamentals** – Designing a metrics pipeline teaches you how services expose health data, a core skill for SRE and backend roles.  
- **Docker‑based orchestration** – Docker Compose mirrors how teams prototype micro‑service stacks before moving to Kubernetes, showing you understand deployment pipelines.  
- **Data persistence & time‑series modeling** – Using PostgreSQL with TimescaleDB demonstrates you can map streaming data to a relational store, a pattern common in fintech and IoT back‑ends.  
- **Visualization & storytelling** – Grafana dashboards let you turn raw numbers into actionable insights, a skill valued by product‑focused engineering teams.  

Roles that typically flag this project: **Backend Engineer**, **Site Reliability Engineer**, **DevOps Engineer**, **Data Engineer**, and **Platform Engineer**. The combination of code, config, and a live dashboard gives recruiters something tangible to inspect, run, and ask about in interviews.

## Architecture Overview

The pipeline consists of four primary components that fit together in a simple request‑flow diagram:

```
[Go Exporter] ──► [Prometheus Server] ──► [PostgreSQL (TimescaleDB)] ──► [Grafana]
     │                     │                     │                     │
     │                     │                     │                     └─► Dashboards & Alerts
     │                     │                     └─► Remote Write (optional)
     │                     └─► Metric Scrape & Storage
     └─► Exposes /metrics endpoint (HTTP)
```

- **Go exporter**: A tiny HTTP service (`/metrics`) that collects process‑level metrics (CPU, memory, request counters) using the `prometheus/client_golang` library.  
- **Prometheus server**: Scrapes the `/metrics` endpoint every 15 seconds, rules can aggregate or filter, and stores raw samples in its TSDB.  
- **PostgreSQL + TimescaleDB**: Acts as long‑term storage; Prometheus can be configured with *remote write* to push data here, enabling queries beyond the default 15‑day retention.  
- **Grafana**: Connects to PostgreSQL (or Prometheus directly) and renders dashboards, alert panels, and can embed the pipeline in a personal portfolio site.

Auxiliary pieces you’ll add later: **Alertmanager** for routing alerts, **OpenTelemetry** for tracing, and **Kubernetes** manifests for horizontal scaling.

## Building It Step by Step

Below are five numbered steps, each with a concrete, language‑tagged code snippet you can copy‑paste.

### Step 1 – Initialize a Go module and write the metrics exporter

```bash
go mod init metrics-pipeline
```

**main.go** (language tag: `go`)

```go
package main

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// Counter for HTTP requests by method and path.
var httpRequests = prometheus.NewCounterVec(
	prometheus.CounterOpts{
		Name: "http_requests_total",
		Help: "Total number of HTTP requests.",
	},
	[]string{"method", "path"},
)

func init() {
	prometheus.MustRegister(httpRequests)
}

// handler increments the counter and returns a simple JSON payload.
func handler(w http.ResponseWriter, r *http.Request) {
	httpRequests.With(r.Method, r.URL.Path).Inc()
	w.Header().Set("Content-Type", "application/json")
	jsonResp := `{"status":"ok"}`
	w.Write([]byte(jsonResp))
}

func main() {
	// Expose /metrics at /metrics path.
	http.Handle("/metrics", promhttp.Handler())
	// Simple health endpoint.
	http.HandleFunc("/healthz", handler)
	// Listen on port 9090 (matches Prometheus default scrape config).
	http.ListenAndServe(":9090", nil)
}
```

Run it with `go run main.go`; visit `http://localhost:9090/metrics` to see Prometheus‑formatted metrics.

### Step 2 – Dockerize the Go service

Create a **Dockerfile** (language tag: `dockerfile`):

```dockerfile
# Use the official Golang image as a build stage.
FROM golang:1.22-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./
RUN go build -o metrics-exporter .

# Final stage: a minimal runtime image.
FROM alpine:3.20
RUN addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=builder /src/metrics-exporter .
USER app

EXPOSE 9090
CMD ["./metrics-exporter"]
```

Build and tag the image:

```bash
docker build -t metrics-exporter:latest .
```

### Step 3 – Spin up the full stack with Docker Compose

Create **docker-compose.yml** (language tag: `yaml`):

```yaml
version: "3.9"

services:
  exporter:
    image: metrics-exporter:latest
    container_name: metrics-exporter
    ports:
      - "9090:9090"
    restart: unless-stopped

  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"   # note: we map host 9090 → prometheus 9090; exporter also on 9090 inside its network
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
    restart: unless-stopped

  postgres:
    image: timescale/timescaledb:2.14-pg15
    container_name: postgres
    environment:
      POSTGRES_USER: metrics
      POSTGRES_PASSWORD: metricspwd
      POSTGRES_DB: metricsdb
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
    depends_on:
      - postgres
    restart: unless-stopped

volumes:
  pgdata:
  grafana-data:
```

### Step 4 – Prometheus configuration to scrape the exporter and write to PostgreSQL

Create **prometheus.yml** (language tag: `yaml`):

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: "metrics-exporter"
    static_configs:
      - targets: ["exporter:9090"]
        labels:
          environment: "local"

  - job_name: "postgres"
    static_configs:
      - targets: ["postgres:9187"]   # PostgreSQL exporter exporter
```

To enable remote write to TimescaleDB, add at the bottom of the file:

```yaml
remote_write:
  - url: "http://postgres:9189/api/write"
    username: "metrics"
    password: "metricspwd"
    write_relabel_configs:
      - source_labels: [__name__]
        regex: "^http_requests_total$"
        action: keep
```

*(Prometheus’s remote‑write endpoint can be any HTTP API; the example assumes a simple forwarder, but the official `prometheus-remote-write` proxy or a Thanos sidecar can bridge to PostgreSQL/TimescaleDB.)*

### Step 5 – Launch everything and verify

```bash
docker compose up -d
```

- **Exporter**: `curl http://localhost:9090/metrics` → you should see `http_requests_total` and process‑level metrics.  
- **Prometheus**: Open `http://localhost:9090/graph` and type `http_requests_total` to confirm scraping.  
- **PostgreSQL**: `psql -h localhost -U metrics -d metricsdb` → `\dt` lists the `_timescaledb_catalog` tables.  
- **Grafana**: Browse to `http://localhost:3000`, log in with `admin/admin`, and add PostgreSQL as a data source using the credentials from the compose file. Import a simple dashboard (e.g., “System CPU & Memory”) that queries the `pg_stat_activity` and custom metrics tables.

You now have a fully functional, locally‑run metrics pipeline that you can demo, extend, and eventually push to a cloud environment.

## Running and Testing It

| Action | Command | Expected outcome |
|--------|---------|------------------|
| Start the stack | `docker compose up -d` | All four containers run in background. |
| Verify exporter metrics | `curl http://localhost:9090/metrics` | Prometheus‑format lines for `http_requests_total`, `go_memstats_alloc_bytes`, etc. |
| Check Prometheus UI | Open `http://localhost:9090/graph` | Graph of `http_requests_total` over the last minute. |
| Confirm PostgreSQL data | `psql -h localhost -U metrics -d metricsdb -c "SELECT count(*) FROM metrics;` | Rows appear, showing remote‑written samples. |
| Access Grafana | Open `http://localhost:3000` | Login, add data source, and view a pre‑built dashboard of the pipeline. |
| Run a quick load test | `hey -n 1000 -c 10 http://localhost:9090/healthz` | 1000 requests with 10 concurrent clients; observe `http_requests_total` increment in Prometheus. |

If any container fails, inspect logs with `docker compose logs <service>` and ensure port mappings aren’t colliding (the exporter and Prometheus both listen on 9090 inside their own networks, but the host port is shared – we rely on Docker’s internal DNS `exporter` → `prometheus` service discovery).

## Extending It: Your Roadmap to Senior‑Level

1. **Persist metrics with TimescaleDB** – Configure Prometheus remote‑write to push raw samples into PostgreSQL, enabling queries beyond the default 15‑day TSDB retention. *Why it matters:* Long‑term trending, compliance, and integration with other data pipelines.  
2. **Add OpenTelemetry tracing** – Instrument the Go service with `go.opentelemetry.io/otel` to emit spans for HTTP requests, correlating latency with metric spikes. *Why it matters:* Modern observability stacks (Jaeger, Tempo) need trace‑metric linkage for root‑cause analysis.  
3. **Horizontal scaling with Prometheus federation** – Run multiple exporter instances behind a load balancer and federate scrapes into a central Prometheus cluster. *Why it matters:* Demonstrates you can design systems that scale beyond a single node, a key SRE competency.  
4. **Fault‑tolerant alerting via Alertmanager** – Set up Alertmanager rules (e.g., “if `http_requests_total` rate > 500 req/s for 5 min”) and configure receiver (email, Slack, PagerDuty). *Why it matters:* Shows you can close the loop between monitoring and incident response.  
5. **Benchmark the /metrics endpoint** – Use `wrk` or `hey` to measure QPS and latency, then profile with `go tool pprof` to optimize hot paths. *Why it matters:* Quantifies performance boundaries and proves you can deliver low‑overhead observability.  
6. **Deploy to a cloud platform (GKE or AWS ECS)** – Write Terraform or Pulumi manifests to provision a VPC, a managed PostgreSQL (Amazon RDS + Timescale), and a Prometheus‑compatible remote‑write endpoint. *Why it matters:* Moves the project from “local demo” to “production‑ready portfolio piece” that hiring managers can inspect in a real cloud environment.

Each upgrade adds a concrete, production‑grade capability while keeping the core codebase intact, letting you showcase progressive mastery from “working service” to “robust platform”.

## Key Takeaways

- **A runnable metrics pipeline is a tangible signal** of your ability to design, build, and operate real systems.  
- **Go + Prometheus + Grafana** is a lightweight yet industry‑standard stack that hiring managers instantly recognize.  
- **Docker Compose** gives you a reproducible local environment that mirrors production orchestration patterns.  
- **PostgreSQL (TimescaleDB)** adds long‑term storage and SQL‑based analytics, a pattern used in fintech and IoT back‑ends.  
- **Observability upgrades** (tracing, alerting, scaling) transform a “toy” project into a portfolio piece that demonstrates senior‑level engineering thinking.  

## Further Reading

- [Prometheus documentation – scraping and remote write](https://prometheus.io/docs/operating/federation/)  
- [OpenTelemetry Go API – instrumentation guide](https://opentelemetry.io/docs/instrumentation/go/)  
- [TimescaleDB documentation – hypertables and continuous aggregates](https://docs.timescale.com/continuous-aggregates/)  
- [Grafana dashboards – building your first dashboard](https://grafana.com/docs/grafana/latest/dashboards/)  
- [Docker Compose reference – service configuration](https://docs.docker.com/compose/)  
- [Go net/http tutorial – building HTTP services](https://go.dev/doc/nethttp/)  

---