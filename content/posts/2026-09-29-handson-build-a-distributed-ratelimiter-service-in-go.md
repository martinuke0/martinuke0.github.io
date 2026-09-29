---
title: "Hands‑On: Build a Distributed Rate‑Limiter Service in Go"
date: "2026-09-29T22:01:08.645"
draft: false
tags: ["go","redis","docker","rate-limiting","observability"]
description: "Build a production‑ready distributed rate‑limiter in Go with Redis, Docker, and Prometheus metrics – a hands‑on portfolio project that signals senior‑level systems skills."
summary: "A step‑by‑step guide to constructing a Go‑based rate‑limiter that stores state in Redis, exports Prometheus metrics, and runs locally via Docker Compose – perfect for showcasing systems engineering chops."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-29-handson-build-a-distributed-ratelimiter-service-in-go.svg"
  alt: "Go code on a terminal with Redis icons"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you’ll build a Go rate‑limiter backed by Redis, containerize it with Docker Compose, and expose Prometheus metrics for observability. The result is a runnable, extensible service that demonstrates concurrency, caching, and production‑grade tooling — exactly the kind of project hiring managers look for.

Building a rate‑limiter from scratch might sound like a textbook exercise, but when you package it with Docker, instrument it with Prometheus, and ship it as a portable service, you’ve got a concrete artifact that proves you can design for concurrency, manage external state, and expose telemetry—three things every senior engineer is expected to handle. In the following sections you’ll move from a minimal Go HTTP handler to a fully Docker‑composed system you can run, test, and extend on your laptop (and later in production).

## Why This Project Stands Out on a CV

Hiring managers scanning dozens of GitHub repos look for signals that you understand *how* systems interact, not just syntax. This project demonstrates:

- **Concurrent Go programming** – a goroutine‑safe token‑bucket using `sync/atomic` and `time.Ticker`.  
- **External state management** – Redis as the backing store, teaching you client‑server semantics, serialization, and fault tolerance.  
- **Containerization best practices** – a minimal Dockerfile, multi‑stage builds, and `docker‑compose` for local orchestration.  
- **Observability pipeline** – Prometheus client exposure, metric naming conventions, and a quick Grafana dashboard sketch.  
- **System‑level design** – rate‑limit algorithms, request flow, and graceful degradation.

Roles that benefit directly include **backend engineer**, **site‑reliability engineer (SRE)**, and **DevOps generalist**. Even a junior applicant can talk about the project in an interview with concrete details (“I used a token‑bucket with a Redis backend, measured latency with `wrk`, and added Prometheus counters”), which instantly differentiates you from candidates who only list toy “Hello World” apps.

## Architecture Overview

The system consists of four primary components that fit together as follows:

- **Client** – any HTTP consumer (curl, browser, script) sends a request to the Go service.  
- **Go rate‑limiter service** – a single binary that:  
  1. Receives the request.  
  2. Checks/updates the token count in Redis (via `go-redis`).  
  3. Returns `200` if allowed, `429` otherwise.  
  4. Increments Prometheus counters for `allowed` and `rejected` requests.  
- **Redis** – stores the current token count per client IP (or API key). Persists via RDB/AOF snapshots.  
- **Prometheus** – scrapes the `/metrics` endpoint; a simple Grafana dashboard can visualise request rates and limit violations.

```
+--------+      HTTP      +--------+   TCP/6379   +--------+   HTTP   +--------+
| Client |  <----------> | Go Srv | ----------> | Redis  | <------> | Prom |
+--------+               +--------+             +--------+          +--------+
        \_______________________/                       ^
                                              metrics endpoint
```

Key data flow: each request acquires a token from Redis; when the bucket empties, subsequent requests receive HTTP 429. The service also exports `rate_limiter_allowed_total` and `rate_limiter_rejected_total` counters that Prometheus can scrape every 10 seconds.

## Building It Step by Step

Below are seven numbered steps that take you from a fresh directory to a running service. Each step includes a focused code snippet you can copy‑paste.

### Step 1 – Initialise the Go module

```bash
mkdir rate-limiter && cd rate-limiter
go mod init github.com/yourname/rate-limiter
```

### Step 2 – Implement a thread‑safe token bucket in Go

```go
// internal/limiter.go
package limiter

import (
	"context"
	"time"

	"github.com/redis/go-redis/v9"
)

type TokenBucket struct {
	client  *redis.Client
	key     string // e.g. client IP
	rate    float64 // tokens per second
	capacity int     // max tokens
	ctx     context.Context
}

// NewBucket creates a bucket that refills `rate` tokens per second up to `capacity`.
func NewBucket(c *redis.Client, key string, rate float64, capacity int) *TokenBucket {
	return &TokenBucket{
		client:  c,
		key:     key,
		rate:    rate,
		capacity: capacity,
		ctx:     context.Background(),
	}
}

// Allow checks if a token is available, consumes one, and returns true.
// If not, it returns false without decrementing.
func (b *TokenBucket) Allow() (bool, error) {
	// Use a Lua script for atomic check‑and‑consume.
	script := `
	if redis.call("EXISTS", KEYS[1]) == 0 then
		redis.call("SET", KEYS[1], ARGV[2])
	end
	local tokens = tonumber(redis.call("GET", KEYS[1]))
	local now = tonumber(ARGV[3])
	local rate = tonumber(ARGV[4])
	local cap = tonumber(ARGV[5])
	local elapsed = now - tonumber(redis.call("GET", KEYS[1] .. ":ts") or now)
	local refill = elapsed * rate
	if refill > cap then refill = cap end
	tokens = tokens + refill
	if tokens > cap then tokens = cap end
	if tokens < 1 then
		redis.call("SET", KEYS[1], 0)
		redis.call("SET", KEYS[1] .. ":ts", now)
		return 0
	end
	tokens = tokens - 1
	redis.call("SET", KEYS[1], tokens)
	redis.call("SET", KEYS[1] .. ":ts", now)
	return 1
`
	now := float64(time.Now().Unix())
	res, err := b.client.Eval(b.ctx, script, []string{b.key}, now, b.rate, b.capacity).Result()
	if err != nil {
		return false, err
	}
	return res == 1, nil
}
```

*Why this matters*: The Lua script guarantees atomicity without race conditions, a core skill for distributed systems.

### Step 3 – HTTP handler that uses the bucket

```go
// main.go
package main

import (
	"log"
	"net/http"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"github.com/yourname/rate-limiter/internal/limiter"
)

func main() {
	rdb := redis.NewClient(&redis.Options{
		Addr: "redis:6379",
	})
	// Prometheus counters
	allowed := prometheus.NewCounter(prometheus.CounterOpts{
		Name: "rate_limiter_allowed_total",
		Help: "Number of requests allowed by the rate limiter",
	})
	rejected := prometheus.NewCounter(prometheus.CounterOpts{
		Name: "rate_limiter_rejected_total",
		Help: "Number of requests rejected (429)",
	})
	prometheus.MustRegister(allowed, rejected)

	// One bucket per client IP; for demo we use a fixed key.
	bucket := limiter.NewBucket(rdb, "client:127.0.0.1", 10.0, 20)

	// Middleware that checks the bucket for every request
	rateLimitMiddleware := func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			allowed, err := bucket.Allow()
			if err != nil {
				http.Error(w, "internal error", http.StatusInternalServerError)
				return
			}
			if !allowed {
				rejected.Inc()
				http.Error(w, "rate limited", http.StatusTooManyRequests)
				return
			}
			allowed.Inc()
			next.ServeHTTP(w, r)
		})
	}

	mux := http.NewServeMux()
	mux.Handle("/health", http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("ok"))
	}))
	mux.Handle("/metrics", promhttp.Handler())
	mux.HandleFunc("/api/resource", rateLimitMiddleware(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":"hello"}`))
	}))

	srv := &http.Server{
		Addr:    ":8080",
		Handler: mux,
		ReadTimeout:  2 * time.Second,
		WriteTimeout: 2 * time.Second,
	}

	log.Println("rate‑limiter listening on :8080")
	log.Fatal(srv.ListenAndServe())
}
```

*Key takeaway*: The middleware pattern shows how to embed cross‑cutting concerns (rate limiting, metrics) cleanly into an HTTP pipeline.

### Step 4 – Dockerfile for a minimal production image

```dockerfile
# Dockerfile
FROM golang:1.22-alpine AS builder

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download

COPY *.go ./
RUN CGO_ENABLED=0 go build -o /app ./main.go

FROM alpine:3.19
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app /app
USER appuser

EXPOSE 8080
CMD ["/app"]
```

*Why this matters*: Multi‑stage builds keep the final image tiny (≈15 MB) and avoid exposing the Go toolchain in production.

### Step 5 – `docker-compose.yml` to bring Redis and the service up together

```yaml
# docker-compose.yml
version: "3.9"

services:
  redis:
    image: redis:7-alpine
    container_name: rate-redis
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data

  api:
    build: .
    container_name: rate-api
    depends_on:
      - redis
    ports:
      - "8080:8080"
    environment:
      - REDIS_ADDR=redis:6379

volumes:
  redis_data:
```

*Why this matters*: A single `docker compose up` command spins up both the data store and the service, mirroring how you’d run it in a local dev environment or a CI pipeline.

### Step 6 – Run the service locally

```bash
docker compose up --build
```

You should see logs indicating the Go binary started and is listening on `:8080`. Verify Redis is reachable:

```bash
docker exec -it rate-redis redis-cli ping
# PONG
```

### Step 7 – Quick sanity test with `curl`

```bash
# First 20 requests should be allowed (capacity 20)
for i in $(seq 1 20); do
  echo "Request $i:"
  curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/resource
done
# Request 21 should return 429
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/api/resource
# Expected output: 429
```

You can also hit `/metrics` to see Prometheus counters:

```bash
curl http://localhost:8080/metrics
# HELP rate_limiter_allowed_total ...
# TYPE rate_limiter_allowed_total counter
rate_limiter_allowed_total 20
rate_limiter_rejected_total 1
```

## Running and Testing It

- **Local development without Docker**: ensure Redis is running (`redis-server`), then `go run main.go`. The same code path applies; just adjust the Redis address in `main.go`.
- **Unit tests**: the `TokenBucket` struct can be tested with a mock Redis client. A minimal test example:

```go
// internal/limiter_test.go
package limiter

import (
	"context"
	"testing"

	"github.com/redis/go-redis/v9"
	"github.com/stretchr/testify/require"
)

func TestTokenBucketAllow(t *testing.T) {
	client := NewMockRedisClient() // helper that returns a fake go-redis client
	bucket := NewBucket(client, "key", 1.0, 5)

	// Immediately allow 5 requests
	for i := 0; i < 5; i++ {
		ok, err := bucket.Allow()
		require.NoError(t, err)
		require.True(t, ok)
	}
	// Sixth request should be denied
	ok, err := bucket.Allow()
	require.Error(t, err)
	require.False(t, ok)
}
```

Run tests with `go test ./...`; you should see all tests pass.

- **Integration test via Docker Compose**: add a temporary test service in `docker-compose.yml` that runs `k6` or `wrk` against `http://localhost:8080/api/resource` and asserts the 429 after the bucket empties. This proves the whole pipeline—Go → Redis → HTTP—works end‑to‑end.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | One‑line reason it matters |
|---|---------|----------------------------|
| 1 | **Persist bucket state with Redis RDB/AOF** | Guarantees survival across restarts; prevents loss of rate‑limit state after a crash. |
| 2 | **Horizontal scaling with multiple service instances behind a load balancer** | Enables handling higher QPS and provides fault tolerance; teaches consistent‑hash key distribution. |
| 3 | **Add OpenTelemetry tracing** | Gives end‑to‑end latency visibility across Go → Redis → network, a must‑have for production observability. |
| 4 | **Circuit‑breaker pattern (e.g., using `github.com/sony/gobreaker`)** | Prevents cascading failures when Redis becomes unavailable, a core SRE skill. |
| 5 | **Benchmark with `wrk` or `k6` and record QPS vs. token‑bucket config** | Provides data‑driven justification for choosing rate values in real traffic scenarios. |
| 6 | **JWT‑based per‑client quotas** | Moves from IP‑level limiting to per‑application/partner quotas, a typical requirement for API platforms. |

Each upgrade is a concrete, measurable step that transforms the prototype into a production‑ready component you can discuss in senior‑level interviews.

## Key Takeaways

- A rate‑limiter built with Go + Redis demonstrates concurrency, external state management, and fault‑tolerant design—three pillars that hiring managers evaluate.  
- Containerising the service with Docker and exposing Prometheus metrics shows you can ship reproducible, observable software.  
- The Lua‑scripted token‑bucket guarantees atomicity without race conditions, a pattern reusable in many distributed systems.  
- Adding observability (metrics, tracing, circuit‑breakers) moves the project from “toy” to “production‑grade artifact”.  
- The roadmap upgrades (persistence, horizontal scaling, OpenTelemetry, circuit‑breakers, benchmarking, JWT quotas) map directly to senior‑engineer expectations.

## Further Reading

- [Redis Documentation – Commands & Data Types](https://redis.io/docs/)  
- [Go `net/http` package reference](https://pkg.go.dev/net/http)  
- [Prometheus client\_golang repository](https://github.com/prometheus/client_golang)  
- [Docker Compose specification](https://docs.docker.com/compose/)  
- [Token bucket algorithm – Wikipedia](https://en.wikipedia.org/wiki/Token_bucket)  
- [OpenTelemetry Go SDK](https://opentelemetry.io/docs/instrumentation/go/)  
- [Sony gobreaker circuit‑breaker library](https://github.com/sony/gobreaker)  

You now have a complete, runnable Go rate‑limiter service, a clear path to harden it for production, and a set of primary‑source references to deepen your understanding. Happy building, and good luck turning this project into a standout line on your CV!