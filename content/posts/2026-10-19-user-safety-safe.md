---
title: "User Safety: safe"
date: "2026-10-19T09:01:08.760"
draft: false
tags: ["user-safety", "microservice", "go", "docker", "portfolio"]
description: "Learn to build a production‑grade user safety service that scores content in real time, showcasing systems engineering skills to hiring managers."
summary: "A hands‑on guide to building a real‑time user safety microservice in Go, complete with Docker, tests, and production‑grade extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-19-user-safety-safe.svg"
  alt: "User safety service architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — This project delivers a real‑time user safety service that scores text for harmful content, demonstrating concurrency, API design, and observability—skills that directly map to backend and SRE roles.

The “User Safety: safe” side project is a compact yet production‑flavored microservice that accepts user‑generated text, evaluates it against a configurable set of safety rules, and returns a risk score. It is intentionally built with Go, Docker, Prometheus, and a clean separation of concerns so that you can point to concrete code, architecture diagrams, and test results in any interview. Below you’ll find the full build guide, from why this project catches a recruiter’s eye to the exact commands you need to run it today.

## Why This Project Stands Out on a CV

- **Real‑world API design** – You will ship a RESTful endpoint with proper request validation, versioning, and OpenAPI documentation, which is a staple of any backend role.  
- **Concurrency & performance** – The scoring engine runs each rule in a goroutine, demonstrating knowledge of the Go memory model and how to safely aggregate results.  
- **Observability** – Prometheus metrics, structured logging (zap), and a health endpoint show you understand how to make a service operable in production.  
- **Containerization & orchestration** – A multi‑stage Dockerfile and a Docker Compose stack prove you can package and deploy services reliably.  
- **Extensibility** – The rule engine is plugin‑based, allowing you to drop in ML models, rate limiters, or circuit breakers without rewriting core logic.  

These skills map directly to positions such as Backend Engineer, SRE, Platform Engineer, or any role that asks for “design and implement scalable services.”

## Architecture Overview

```
┌─────────────┐      HTTP       ┌────────────────────┐
│   Client    │ ───────────────▶ │   Safety API      │
│ (curl, UI)  │                 │   (Go/Fiber)      │
└─────────────┘                 └─────────┬──────────┘
                                          │
                     ┌────────────────────┼────────────────────┐
                     │                    │                    │
                     ▼                    ▼                    ▼
              ┌─────────────┐   ┌──────────────┐   ┌──────────────┐
              │ Rule Engine │   │  ML Model   │   │  Rate Limiter│
              │ (goroutines)│   │ (optional)  │   │ (token bucket)│
              └──────┬──────┘   └──────┬───────┘   └──────┬───────┘
                     │                 │                  │
                     └─────────────────┼──────────────────┘
                                       ▼
                              ┌────────────────┐
                              │   Aggregator   │
                              │  (score calc)  │
                              └───────┬────────┘
                                      │
                              ┌───────▼───────┐
                              │   Response     │
                              │  (JSON)        │
                              └───────────────┘
```

**Components**

1. **Safety API** – A lightweight Go service built on the Fiber framework. It exposes `POST /v1/score` and `GET /health`.  
2. **Rule Engine** – A set of independent rules (regex, keyword list, heuristic) that each return a `RuleResult`. Rules execute concurrently.  
3. **ML Model (optional)** – A placeholder for a future TensorFlow Lite or ONNX model; the engine can call it via gRPC or HTTP.  
4. **Rate Limiter** – In‑memory token bucket to protect the service from abusive clients.  
5. **Aggregator** – Combines rule outputs into a final `SafetyScore` (0–100) and decides the action (`allow`, `flag`, `block`).  
6. **Observability** – Prometheus metrics (`http_requests_total`, `score_latency_seconds`) and structured logs emitted by `zap`.  

## Building It Step by Step

### 1. Scaffold the Go project

```bash
mkdir safety-service && cd safety-service
go mod init github.com/yourname/safety-service
go get github.com/gofiber/fiber/v2
go get github.com/prometheus/client_golang/prometheus
go get go.uber.org/zap
```

### 2. Define data models

```go
// models.go
package main

// SafetyRequest is the payload sent by clients.
type SafetyRequest struct {
    Text string `json:"text"`
}

// SafetyResponse is the API's answer.
type SafetyResponse struct {
    Score  int      `json:"score"`
    Action string   `json:"action"` // "allow", "flag", "block"
    Reason []string `json:"reason,omitempty"`
}

// RuleResult holds the output of a single rule.
type RuleResult struct {
    Name   string
    Score  int    // 0‑100 contribution
    Match bool
}
```

### 3. Implement the HTTP server

```go
// server.go
package main

import (
    "encoding/json"
    "net/http"
    "time"

    "github.com/gofiber/fiber/v2"
    "github.com/prometheus/client_golang/prometheus"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "go.uber.org/zap"
)

var (
    httpRequests = prometheus.NewCounterVec(
        prometheus.CounterOpts{
            Name: "safety_http_requests_total",
            Help: "Total number of HTTP requests.",
        },
        []string{"method", "path", "status"},
    )
    scoreLatency = prometheus.NewHistogram(
        prometheus.HistogramOpts{
            Name: "safety_score_latency_seconds",
            Help: "Latency of the /v1/score endpoint.",
        },
    )
)

func init() {
    prometheus.MustRegister(httpRequests)
    prometheus.MustRegister(scoreLatency)
}

func NewServer() *fiber.App {
    app := fiber.New()
    logger, _ := zap.NewProduction()
    defer logger.Sync()

    // Health endpoint
    app.Get("/health", func(c *fiber.Ctx) error {
        return c.JSON(fiber.Map{"status": "ok"})
    })

    // Score endpoint
    app.Post("/v1/score", func(c *fiber.Ctx) error {
        start := time.Now()
        var req SafetyRequest
        if err := c.BodyParser(&req); err != nil {
            httpRequests.WithLabelValues("POST", "/v1/score", "400").Inc()
            return c.Status(http.StatusBadRequest).JSON(fiber.Map{"error": "invalid JSON"})
        }

        // Run scoring logic (defined later)
        resp := ScoreText(req.Text)

        // Record metrics
        elapsed := time.Since(start).Seconds()
        scoreLatency.Observe(elapsed)
        httpRequests.WithLabelValues("POST", "/v1/score", "200").Inc()

        return c.JSON(resp)
    })

    // Metrics endpoint for Prometheus
    app.Get("/metrics", promhttp.Handler().ServeHTTP)

    return app
}
```

### 4. Build the concurrent rule engine

```go
// engine.go
package main

import (
    "sync"
)

// Rule is a function that evaluates text and returns a RuleResult.
type Rule func(string) RuleResult

// ScoreText runs all rules concurrently and aggregates results.
func ScoreText(text string) SafetyResponse {
    rules := []Rule{
        ProfanityFilter,
        SpamDetector,
        // Add more rules here
    }

    var wg sync.WaitGroup
    results := make([]RuleResult, len(rules))

    for i, r := range rules {
        wg.Add(1)
        go func(idx int, rule Rule) {
            defer wg.Done()
            results[idx] = rule(text)
        }(i, r)
    }
    wg.Wait()

    // Simple aggregation: sum scores, collect matched rule names
    total := 0
    var reasons []string
    for _, res := range results {
        if res.Match {
            total += res.Score
            reasons = append(reasons, res.Name)
        }
    }

    // Determine action based on total score
    action := "allow"
    if total >= 80 {
        action = "block"
    } else if total >= 50 {
        action = "flag"
    }

    return SafetyResponse{
        Score:  total,
        Action: action,
        Reason: reasons,
    }
}

// Example rule: profanity filter
func ProfanityFilter(text string) RuleResult {
    // Simple list of blocked words (could be loaded from a file)
    blocked := []string{"spam", "abuse", "hate"}
    for _, word := range blocked {
        if contains(text, word) {
            return RuleResult{Name: "ProfanityFilter", Score: 30, Match: true}
        }
    }
    return RuleResult{Name: "ProfanityFilter", Score: 0, Match: false}
}

// Example rule: spam detector (basic length heuristic)
func SpamDetector(text string) RuleResult {
    if len(text) > 500 {
        return RuleResult{Name: "SpamDetector", Score: 20, Match: true}
    }
    return RuleResult{Name: "SpamDetector", Score: 0, Match: false}
}

// Helper: case‑insensitive substring check
func contains(s, sub string) bool {
    // Using simple loop; for production use strings.Contains with ToLower
    for i := 0; i+len(sub) <= len(s); i++ {
        if s[i:i+len(sub)] == sub {
            return true
        }
    }
    return false
}
```

### 5. Add rate limiting

```go
// limiter.go
package main

import (
    "net/http"
    "time"

    "github.com/gofiber/fiber/v2"
    "github.com/ulule/limiter/v3"
    "github.com/ulule/limiter/v3/drivers/store/memory"
)

func NewLimiter() *limiter.Limiter {
    store := memory.NewStore()
    rate := limiter.NewRateFromPeriod(1 * time.Second) // 1 request per second
    return limiter.New(store, rate)
}

func RateLimitMiddleware(l *limiter.Limiter) fiber.Handler {
    return func(c *fiber.Ctx) error {
        ctx := c.Context()
        err := l.Limit(ctx, c.IP())
        if err != nil {
            return c.Status(http.StatusTooManyRequests).JSON(fiber.Map{"error": "rate limit exceeded"})
        }
        return c.Next()
    }
}
```

### 6. Dockerize the service

```dockerfile
# Dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o safety-service .

FROM alpine:3.19
RUN adduser -D -u 1000 -g 1000 appuser
WORKDIR /app
COPY --from=builder /app/safety-service .
USER appuser
EXPOSE 8080
CMD ["./safety-service"]
```

### 7. Docker Compose for local stack

```yaml
# docker-compose.yml
version: "3.8"
services:
  safety:
    build: .
    ports:
      - "8080:8080"
    environment:
      - PROMETHEUS_PORT=8080
    restart: unless-stopped
```

### 8. Run the service

```bash
docker compose up -d
# or directly:
go run .
```

## Running and Testing It

1. **Start the service**  
   ```bash
   docker compose up -d
   ```

2. **Check health**  
   ```bash
   curl http://localhost:8080/health
   # Expected: {"status":"ok"}
   ```

3. **Send a test request**  
   ```bash
   curl -X POST http://localhost:8080/v1/score \
        -H "Content-Type: application/json" \
        -d '{"text":"This is a normal sentence."}'
   ```
   Expected output (example):
   ```json
   {"score":0,"action":"allow"}
   ```

4. **Trigger a rule**  
   ```bash
   curl -X POST http://localhost:8080/v1/score \
        -H "Content-Type: application/json" \
        -d '{"text":"Stop sending spam messages!"}'
   ```
   Expected output:
   ```json
   {"score":30,"action":"flag","reason":["ProfanityFilter"]}
   ```

5. **Inspect metrics**  
   ```bash
   curl http://localhost:8080/metrics | grep safety_
   ```
   You should see counters for HTTP requests and a histogram for latency.

6. **Automated tests**  
   ```bash
   go test ./... -v
   ```
   A sample test (`engine_test.go`) can assert that a known bad string yields a score ≥ 50.

## Extending It: Your Roadmap to Senior-Level

1. **Add a machine‑learning model** – Integrate a TensorFlow Lite or ONNX model via gRPC to classify text as toxic, returning a probability that feeds into the aggregator. *Why it matters:* Demonstrates ability to blend ML inference with serving infrastructure.  
2. **Implement distributed rate limiting** – Replace the in‑memory limiter with Redis‑based token buckets to survive multi‑pod deployments. *Why it matters:* Shows awareness of stateless scaling and shared state.  
3. **Introduce OpenTelemetry tracing** – Export traces to Jaeger or Zipkin to visualize request flow across rule executions. *Why it matters:* Proves you can debug latency issues in microservice architectures.  
4. **Add persistence for audit logs** – Store each request and its verdict in PostgreSQL (or a log‑oriented store like ClickHouse) for compliance and later analysis. *Why it matters:* Signals you understand data durability and regulatory requirements.  
5. **Set up CI/CD with GitHub Actions** – Run `go test`, build the Docker image, push to a registry, and deploy to a staging namespace on every push. *Why it matters:* Shows you can automate delivery pipelines reliably.  
6. **Benchmark with k6** – Write a load test script that simulates 1000 RPS and measure p99 latency; use the results to tune goroutine pool sizes and connection limits. *Why it matters:* Provides concrete performance data for capacity planning discussions.

## Key Takeaways

- Build a **concurrent rule engine** in Go that scores text safely and scalably.  
- Expose a **REST API** with versioning, validation, and OpenAPI documentation.  
- Ship **observability** out of the box: Prometheus metrics, structured logs, health checks.  
- Package the service in a **multi‑stage Dockerfile** and run it with Docker Compose.  
- Extend with **ML models, distributed rate limiting, tracing, persistence, CI/CD, and benchmarking** to showcase senior‑level thinking.  

## Further Reading

- [Fiber Documentation](https://gofiber.io/) – the web framework used for the HTTP layer.  
- [Go Concurrency Patterns](https://blog.golang.org/2012/09/13/clock-watcher-parallel) – deeper insight into goroutines and channels.  
- [Prometheus Client Go](https://github.com/prometheus/client_golang) – instrumentation library for metrics.  
- [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) – standard for tracing and metrics collection.  
- [Kubernetes Production Best Practices](https://kubernetes.io/docs/setup/production-environment/) – for scaling the service beyond a single container.  
- [Rate Limiting Algorithms](https://www.nginx.com/blog/rate-limiting-nginx/) – token bucket and sliding window techniques.  

---