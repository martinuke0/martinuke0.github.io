---
title: "Building a Distributed Rate Limiter in Go: A Portfolio Project That Shows Systems Skills"
date: "2026-10-30T15:01:55.139"
draft: false
tags: ["Go", "Redis", "Distributed Systems", "Rate Limiting"]
description: "Build a distributed rate limiter in Go that showcases real systems skills for your CV, covering scalability, fault tolerance, and observability."
summary: "Implement a production‑grade distributed rate limiter in Go using Redis, demonstrating scalability, fault tolerance, and observability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-30-building-a-distributed-rate-limiter-in-go-a-portfolio-project-that-shows-systems.svg"
  alt: "A diagram of a distributed rate limiter"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a distributed rate limiter in Go that runs on multiple instances, uses Redis for shared state, and includes health checks and metrics. You’ll end up with a runnable project that demonstrates scalability, fault tolerance, and observability—exactly the skills hiring managers look for in systems roles.

In a crowded job market, a side project must prove more than syntax fluency; it needs to show you can design, implement, and operate a system that scales. A distributed rate limiter is an ideal vehicle: it touches concurrency, network programming, persistence, and observability, all while being small enough to finish in a weekend but realistic enough to discuss in an interview.

## Why This Project Stands Out on a CV

- **Concurrency & parallelism** – you’ll use Go routines and channels to handle thousands of requests per second.
- **Distributed state management** – Redis provides a single source of truth across multiple service instances.
- **Fault tolerance** – the design survives Redis outages by falling back to local token buckets.
- **Observability** – expose Prometheus metrics and health endpoints that prove you think about production.
- **Scalability** – the architecture scales horizontally by adding more stateless API nodes.
- **Containerization** – Docker and Docker Compose demonstrate you can package and run the system anywhere.

These skills map directly to senior‑level roles such as Backend Engineer, SRE, or Distributed Systems Engineer.

## Architecture Overview

```
+-------------------+      +-------------------+
|   Client (curl)   | ---> |   API Gateway     |
+-------------------+      +-------------------+
                             |
                             v
                   +-------------------+
                   | Rate Limiter Service |
                   +-------------------+
                             |
                +------------+------------+
                |                         |
          +-----v-----+             +-----v-----+
          | Redis      |             | Local Fallback |
          +------------+             +----------------+
```

1. **Client** – any HTTP client (browser, curl, SDK).
2. **API Gateway / Load Balancer** – distributes traffic across multiple stateless instances (optional but recommended).
3. **Rate Limiter Service** – Go binary that enforces limits using a token bucket algorithm.
4. **Redis** – shared store for global token counts; also acts as a single source of truth.
5. **Local Fallback** – in‑memory bucket used when Redis is unreachable, ensuring the service degrades gracefully.

Each component is independent, allowing horizontal scaling of the service layer while Redis remains the coordination point.

## Building It Step by Step

### 1. Scaffold the Project

```bash
mkdir ratelimit && cd ratelimit
go mod init github.com/yourname/ratelimit
```

Create the following layout:

```
ratelimit/
├── cmd/
│   └── server/
│       └── main.go
├── internal/
│   ├── limiter/
│   │   └── limiter.go
│   ├── redis/
│   │   └── client.go
│   └── http/
│       └── handler.go
├── Dockerfile
├── docker-compose.yml
└── go.mod
```

### 2. Implement the Token Bucket

The core algorithm is a classic token bucket with a refill rate. We’ll store `tokens` and `last_refill` in Redis.

```go
// internal/limiter/limiter.go
package limiter

import (
	"context"
	"time"

	"github.com/go-redis/redis/v8"
)

type Limiter struct {
	client *redis.Client
	rate   float64       // tokens per second
	burst  float64       // max tokens
}

func New(client *redis.Client, rate, burst float64) *Limiter {
	return &Limiter{client: client, rate: rate, burst: burst}
}

// Allow returns true if a request is allowed, updating the bucket.
func (l *Limiter) Allow(ctx context.Context, key string) (bool, error) {
	now := time.Now().UnixNano()
	// Lua script ensures atomic read‑modify‑write.
	script := `
	 local tokens = tonumber(redis.call('GET', KEYS[1]) or ARGV[2])
	 local last = tonumber(redis.call('GET', KEYS[2]) or ARGV[3])
	 local now = tonumber(ARGV[1])
	 local rate = tonumber(ARGV[4])
	 local burst = tonumber(ARGV[5])

	 local elapsed = now - last
	 tokens = math.min(burst, tokens + elapsed * rate)
	 if tokens >= 1 then
	 tokens = tokens - 1
	 redis.call('SET', KEYS[1], tokens)
	 redis.call('SET', KEYS[2], now)
	 return 1
	 else
	 return 0
	 end
	`
	tokensKey := "tokens:" + key
	lastKey := "last:" + key
	result, err := l.client.Eval(ctx, script, []string{tokensKey, lastKey},
		now, l.burst, now, l.rate, l.burst).Int()
	if err != nil {
		return false, err
	}
	return result == 1, nil
}
```

### 3. Redis Client Setup

```go
// internal/redis/client.go
package redis

import (
	"github.com/go-redis/redis/v8"
)

func NewClient(addr string) *redis.Client {
	return redis.NewClient(&redis.Options{
		Addr:     addr,
		Password: "", // no password for local dev
		DB:       0,
	})
}
```

### 4. HTTP Handler

```go
// internal/http/handler.go
package http

import (
	"context"
	"log"
	"net/http"
	"time"

	"github.com/yourname/ratelimit/internal/limiter"
)

type Handler struct {
	lim *limiter.Limiter
}

func NewHandler(l *limiter.Limiter) *Handler {
	return &Handler{lim: l}
}

func (h *Handler) LimitMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		ctx := context.Background()
		// Use client IP or API key as bucket identifier.
		key := r.RemoteAddr
		allowed, err := h.lim.Allow(ctx, key)
		if err != nil {
			log.Printf("limiter error: %v", err)
			// On error, degrade gracefully: allow request.
			next.ServeHTTP(w, r)
			return
		}
		if !allowed {
			w.Header().Set("Retry-After", "1")
			w.WriteHeader(http.StatusTooManyRequests)
			w.Write([]byte("rate limit exceeded"))
			return
		}
		next.ServeHTTP(w, r)
	})
}
```

### 5. Wire Everything in `main.go`

```go
// cmd/server/main.go
package main

import (
	"log"
	"net/http"
	"os"
	"time"

	"github.com/yourname/ratelimit/internal/http"
	"github.com/yourname/ratelimit/internal/limiter"
	"github.com/yourname/ratelimit/internal/redis"
)

func main() {
	redisAddr := os.Getenv("REDIS_ADDR")
	if redisAddr == "" {
		redisAddr = "localhost:6379"
	}
	// Rate: 100 requests per second, burst of 150.
	rate := 100.0
	burst := 150.0

	redisClient := redis.NewClient(redisClient)
	l := limiter.New(redisClient, rate, burst)

	h := http.NewHandler(l)

	mux := http.NewServeMux()
	// Example protected endpoint.
	mux.HandleFunc("/api/data", func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("hello from protected endpoint"))
	})

	// Health check endpoint.
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("ok"))
	})

	// Apply limiter middleware to all paths except healthz.
	wrapped := h.LimitMiddleware(mux)

	log.Println("server listening on :8080")
	if err := http.ListenAndServe(":8080", wrapped); err != nil {
		log.Fatal(err)
	}
}
```

### 6. Add Metrics (Prometheus)

For brevity, use the `prometheus/client_golang` package.

```go
// internal/http/metrics.go
package http

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	requestsTotal = prometheus.NewCounterVec(
		prometheus.CounterOpts{
			Name: "ratelimit_requests_total",
			Help: "Total number of requests processed.",
		},
		[]string{"status"},
	)
)

func init() {
	prometheus.MustRegister(requestsTotal)
}

func MetricsHandler() http.Handler {
	return promhttp.Handler()
}
```

Include `/metrics` endpoint in `main.go` (exempt from rate limiting).

### 7. Dockerize

```Dockerfile
# Dockerfile
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /server ./cmd/server

FROM alpine:3.19
RUN addgroup -S app && adduser -S app -G app
USER app
COPY --from=build /server /server
EXPOSE 8080
ENTRYPOINT ["/server"]
```

`docker-compose.yml`:

```yaml
# docker-compose.yml
version: "3.8"
services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
  api:
    build: .
    environment:
      - REDIS_ADDR=redis:6379
    ports:
      - "8080:8080"
    depends_on:
      - redis
```

## Running and Testing It

1. **Start services**

```bash
docker compose up -d
```

2. **Verify health**

```bash
curl http://localhost:8080/healthz
# Expected: ok
```

3. **Exercise the limiter**

```bash
# Fire 200 requests concurrently; the first 150 should succeed, the rest get 429.
for i in {1..200}; do
  curl -o /dev/null -s -w "%{http_code}\n" http://localhost:8080/api/data &
done
```

You should see a mix of `200` and `429` responses.

4. **Inspect metrics**

```bash
curl http://localhost:8080/metrics | grep ratelimit_requests_total
```

The counter should reflect the number of allowed and denied requests.

5. **Unit tests**

Create `internal/limiter/limiter_test.go` using `redis` mock or a real Redis instance.

```go
package limiter

import (
	"context"
	"testing"
	"time"

	"github.com/go-redis/redis/v8"
)

func TestAllow(t *testing.T) {
	client := redis.NewClient(&redis.Options{Addr: "localhost:6379"})
	l := New(client, 10, 20) // 10 rps, burst 20
	ctx := context.Background()

	for i := 0; i < 25; i++ {
		allowed, err := l.Allow(ctx, "test-key")
		if err != nil {
			t.Fatal(err)
		}
		if i < 20 && !allowed {
			t.Errorf("expected allowed at iteration %d", i)
		}
		if i >= 20 && allowed {
			t.Errorf("expected denied at iteration %d", i)
		}
	}
}
```

Run with `go test ./...`.

## Extending It: Your Roadmap to Senior-Level

1. **Persistent token store** – replace Redis with a durable backend (e.g., CockroachDB) to survive restarts without losing bucket state. *Why it matters:* eliminates the need for warm‑up after a crash.*

2. **Horizontal scaling** – deploy multiple API pods behind a load balancer; each pod is stateless, so scaling is trivial. *Why it matters:* demonstrates you can design for elasticity.*

3. **Observability suite** – add tracing (OpenTelemetry) and structured logging (Zap) to correlate limit decisions across services. *Why it matters:* production systems require end‑to‑end visibility.*

4. **Fault tolerance** – implement a circuit‑breaker around Redis calls and fall back to a local token bucket; expose a `/ready` endpoint that reflects Redis health. *Why it matters:* shows you can degrade gracefully under partial failures.*

5. **Benchmarking & capacity planning** – use `wrk` or `hey` to measure throughput and latency; feed results into a capacity model that predicts required Redis memory and network bandwidth. *Why it matters:* senior engineers justify infrastructure decisions with data.*

6. **Adaptive rate limiting** – introduce dynamic limits based on client reputation or system load, using a simple heuristic or a more advanced algorithm like Leaky Bucket with priority queues. *Why it matters:* moves the project from static to self‑regulating, a hallmark of mature systems.*

## Key Takeaways

- Build a stateless Go service that enforces limits via a shared Redis store.
- Use atomic Lua scripts to keep token bucket updates consistent across instances.
- Expose health checks and Prometheus metrics to prove production readiness.
- Package with Docker Compose for repeatable local runs.
- Extend with persistence, scaling, observability, fault tolerance, and adaptive logic to showcase senior‑level design thinking.

## Further Reading

- [Redis Documentation](https://redis.io/docs/) – authoritative guide on data structures, scripting, and clustering.
- [Go Concurrency Patterns](https://go.dev/blog/writing-concurrent-code) – deep dive into goroutines, channels, and sync primitives.
- [Token Bucket Algorithm (Wikipedia)](https://en.wikipedia.org/wiki/Token_bucket) – formal definition and rate‑burst analysis.
- [Prometheus Client Golang](https://github.com/prometheus/client_golang) – instrumentation library for metrics.
- [Docker Compose Reference](https://docs.docker.com/compose/) – orchestration of multi‑container applications.
- [Kubernetes Horizontal Scaling](https://kubernetes.io/docs/concepts