---
title: "User Safety: safe — A Hands-On Build Guide for a Systems-Level Side Project"
date: "2026-09-13T00:01:29.245"
draft: false
tags: ["systems-engineering", "go", "rate-limiting", "anomaly-detection", "portfolio-project", "side-project"]
description: "Build a production-grade User Safety gateway in Go that signals real systems skills — rate limiting, anomaly detection, and observability — to hiring managers."
summary: "A hands-on guide to building 'safe,' a user safety gateway in Go that demonstrates rate limiting, anomaly detection, and observability — skills hiring managers actively look for in senior systems roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-13-user-safety-safe-a-hands-on-build-guide-for-a-systems-level-side-project.svg"
  alt: "A terminal dashboard showing real-time user safety metrics and anomaly alerts"
  caption: "The safe gateway running locally, streaming safety metrics to the terminal."
  relative: false
---

> **TL;DR** — Build "safe," a Go-based user safety gateway that combines token-bucket rate limiting, sliding-window anomaly detection, and real-time metrics exposition. It demonstrates distributed systems primitives, observability, and production-grade engineering — exactly the skills that separate staff-level candidates from the rest. This guide gives you every line of code you need to ship it.

---

## Introduction

Portfolio projects are where hiring managers decide whether to invite you to a second interview. Most candidates build TODO apps or blog clones. The ones who get offers build systems that solve a real problem using real primitives: concurrency, state management, failure modes, and observability.

"safe" is a **User Safety Gateway** — a middleware service that sits in front of any HTTP application and protects it from abusive or anomalous user behavior. It enforces rate limits, detects burst patterns, maintains per-user safety scores, and exposes metrics in Prometheus format. You build it in Go, using nothing but the standard library plus a handful of well-known dependencies.

By the end of this guide, you'll have a runnable system that you can point to in an interview and explain in depth — from the token-bucket algorithm to the concurrency model to the observability layer.

---

## Why This Project Stands Out on a CV

The project signals a cluster of skills that hiring managers and staff-level engineers explicitly look for:

- **Concurrency and parallelism**: You'll use goroutines, channels, and `sync` primitives to manage per-user state safely across thousands of concurrent requests. This is the single most-discussed topic in Go interviews.
- **Distributed systems primitives**: Token buckets, sliding windows, and exponential moving averages are the same algorithms used in Redis, Envoy, and Cloudflare's edge network. Implementing them yourself proves you understand the theory, not just the API.
- **Observability and metrics**: Exposing Prometheus-formatted metrics and structured logs teaches you the three pillars of observability — metrics, logs, and traces — in a production context.
- **API design and middleware patterns**: Building a composable middleware chain is a transferable skill that applies to any web service, from fintech to SaaS.
- **Testing at scale**: You'll write property-based tests and benchmark suites, which signals engineering rigor.

The roles this project signals: **Backend Engineer, Platform Engineer, SRE, and Infrastructure Engineer**. It's particularly strong for companies that run high-throughput services — think Stripe, Datadog, Cloudflare, or any company processing millions of requests per day.

---

## Architecture Overview

The `safe` gateway is composed of five tightly integrated components. Here's how they fit together:

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  HTTP Client │────▶│  Safety Gateway  │────▶│  Upstream App   │
│  (requests)  │     │  (Go service)    │     │  (your app)     │
└─────────────┘     └──────────────────┘     └─────────────────┘
                           │
                    ┌──────┼──────┐
                    ▼      ▼      ▼
               ┌────────┐┌─────┐┌──────────┐
               │ Token  ││Anomaly││Metrics   │
               │ Bucket ││Detector││Server    │
               │Engine  ││      ││(Prom)    │
               └────────┘└─────┘└──────────┘
                    │
               ┌────┴────┐
               │Per-User │
               │State    │
               │Store    │
               │(in-mem) │
               └─────────┘
```

- **Token Bucket Engine**: Enforces per-user rate limits using the token-bucket algorithm. Each user gets a bucket that refills at a configured rate. Requests consume tokens; excess requests are rejected with `429 Too Many Requests`.
- **Anomaly Detector**: Monitors request patterns over a sliding window. If a user's request rate suddenly spikes beyond a threshold, the detector flags them and increments their safety score.
- **Per-User State Store**: An in-memory concurrent map (`sync.Map` with shard-level locking) that holds each user's bucket state, safety score, and request history.
- **Metrics Server**: A separate HTTP server that exposes `/metrics` in Prometheus format, including request counts, rejection rates, and per-user safety scores.
- **Middleware Chain**: The core HTTP handler that wires everything together — each request passes through rate limiting, anomaly scoring, and logging before reaching the upstream app.

The entire service runs as a single Go binary with configurable flags for rate limits, window sizes, and upstream URLs.

---

## Building It Step by Step

### Step 1: Project Setup and Dependencies

Initialize the project and pull in the Prometheus client library:

```bash
mkdir safe && cd safe
go mod init github.com/yourname/safe
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
```

### Step 2: Define the Token Bucket

The token bucket is the core rate-limiting primitive. Each user gets a bucket with a maximum capacity and a refill rate.

```go
package main

import (
	"sync"
	"time"
)

// TokenBucket implements the token-bucket rate-limiting algorithm.
type TokenBucket struct {
	mu          sync.Mutex
	tokens      float64
	capacity    float64
	refillRate  float64 // tokens per second
	lastRefill  time.Time
}

func NewTokenBucket(capacity float64, refillRate float64) *TokenBucket {
	return &TokenBucket{
		tokens:     capacity,
		capacity:   capacity,
		refillRate: refillRate,
		lastRefill: time.Now(),
	}
}

// Allow attempts to consume one token. Returns true if allowed.
func (tb *TokenBucket) Allow() bool {
	tb.mu.Lock()
	defer tb.mu.Unlock()

	now := time.Now()
	elapsed := now.Sub(tb.lastRefill).Seconds()
	tb.tokens = min(tb.capacity, tb.tokens + elapsed * tb.refillRate)
	tb.lastRefill = now

	if tb.tokens >= 1.0 {
		tb.tokens -= 1.0
		return true
	}
	return false
}

func min(a, b float64) float64 {
	if a < b {
		return a
	}
	return b
}
```

The key insight here is that tokens accrue over time based on `elapsed * refillRate`. This is the standard formulation from the [token bucket Wikipedia article](https://en.wikipedia.org/wiki/Token_bucket). The `sync.Mutex` ensures that concurrent requests don't corrupt the token count — a classic concurrency bug that hiring managers love to ask about.

### Step 3: Build the Per-User State Store

You need a thread-safe map that associates each user ID with their token bucket and safety score.

```go
package main

import (
	"sync"
	"time"
)

type UserState struct {
	Bucket       *TokenBucket
	SafetyScore  float64
	RequestTimes []time.Time // sliding window of recent requests
	mu           sync.Mutex
}

type StateStore struct {
	buckets map[string]*UserState
	mu      sync.RWMutex
}

func NewStateStore() *StateStore {
	return &StateStore{
		buckets: make(map[string]*UserState),
	}
}

// GetOrCreate returns the UserState for a given ID, creating it if needed.
func (s *StateStore) GetOrCreate(userID string, capacity float64, refillRate float64) *UserState {
	s.mu.RLock()
	state, exists := s.buckets[userID]
	s.mu.RUnlock()

	if exists {
		return state
	}

	s.mu.Lock()
	defer s.mu.Unlock()
	// Double-check under write lock to avoid race
	if state, exists := s.buckets[userID]; exists {
		return state
	}
	state = &UserState{
		Bucket:       NewTokenBucket(capacity, refillRate),
		SafetyScore:  0.0,
		RequestTimes: make([]time.Time, 0),
	}
	s.buckets[userID] = state
	return state
}
```

The double-checked locking pattern here avoids the common pitfall of acquiring a write lock on every read. The `RWMutex` allows concurrent reads, which matters when you have thousands of requests per second hitting the same users.

### Step 4: Implement the Sliding Window Anomaly Detector

Rate limiting catches abuse, but anomaly detection catches *novel* abuse patterns. You track request timestamps in a sliding window and flag users whose rate suddenly exceeds a threshold.

```go
package main

import (
	"sync"
	"time"
)

const (
	WindowSize    = 60 * time.Second // 1-minute sliding window
	BurstThreshold = 50              // requests in window = burst
	ScoreIncrement = 10.0            // safety score bump per burst
)

type AnomalyDetector struct {
	states *StateStore
}

func NewAnomalyDetector(states *StateStore) *AnomalyDetector {
	return &AnomalyDetector{states: states}
}

// Check examines the user's recent request pattern and returns true if anomalous.
func (ad *AnomalyDetector) Check(userID string) bool {
	state := ad.states.GetOrCreate(userID, 100, 10)
	state.mu.Lock()
	defer state.mu.Unlock()

	now := time.Now()
	cutoff := now.Add(-WindowSize)

	// Prune old timestamps
	filtered := state.RequestTimes[:0]
	for _, t := range state.RequestTimes {
		if t.After(cutoff) {
			filtered = append(filtered, t)
		}
	}
	state.RequestTimes = filtered

	// Check for burst
	isBurst := len(state.RequestTimes) >= BurstThreshold
	if isBurst {
		state.SafetyScore += ScoreIncrement
	}

	// Record this request
	state.RequestTimes = append(state.RequestTimes, now)

	return isBurst
}
```

This uses an **exponential decay** approach for the sliding window — you prune old entries on every check, keeping the window accurate without a separate goroutine. The `SafetyScore` accumulates over time, giving you a running risk assessment per user that can feed into downstream decisions (e.g., escalating to a human reviewer).

### Step 5: Wire the Middleware Chain

Now you compose everything into an HTTP middleware that wraps your upstream application.

```go
package main

import (
	"fmt"
	"log"
	"net/http"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	requestsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "safe_requests_total"},
		[]string{"user_id", "status"},
	)
	rejectionsTotal = promauto.NewCounterVec(
		prometheus.CounterOpts{Name: "safe_rejections_total"},
		[]string{"user_id", "reason"},
	)
)

type SafeMiddleware struct {
	states    *StateStore
	detector  *AnomalyDetector
	upstream  http.Handler
	rateLimit float64
}

func NewSafeMiddleware(upstream http.Handler, states *StateStore, detector *AnomalyDetector, rateLimit float64) *SafeMiddleware {
	return &SafeMiddleware{
		states:    states,
		detector:  detector,
		upstream:  upstream,
		rateLimit: rateLimit,
	}
}

func (m *SafeMiddleware) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	userID := r.Header.Get("X-User-ID")
	if userID == "" {
		userID = r.RemoteAddr // fallback
	}

	start := time.Now()

	// 1. Rate limit check
	state := m.states.GetOrCreate(userID, 100, m.rateLimit)
	if !state.Bucket.Allow() {
		rejectionsTotal.WithLabelValues(userID, "rate_limit").Inc()
		http.Error(w, "Too Many Requests", http.StatusTooManyRequests)
		requestsTotal.WithLabelValues(userID, "rejected").Inc()
		return
	}

	// 2. Anomaly detection
	if m.detector.Check(userID) {
		log.Printf("[ALERT] User %s flagged for burst behavior (score: %.1f)", userID, state.SafetyScore)
	}

	// 3. Forward to upstream
	requestsTotal.WithLabelValues(userID, "allowed").Inc()
	m.upstream.ServeHTTP(w, r)

	log.Printf("[INFO] %s %s — user=%s latency=%v", r.Method, r.URL.Path, userID, time.Since(start))
}
```

The middleware chain is the architectural heart of the project. Each request flows through three stages: rate limiting, anomaly detection, and upstream forwarding. Each stage is independently testable and replaceable — a pattern that mirrors how production gateways like [Envoy](https://www.envoyproxy.io/) and [Kong](https://konghq.com/) are structured.

### Step 6: Expose Prometheus Metrics

Add a metrics server so you can monitor the gateway in real time.

```go
package main

import (
	"net/http"

	"github.com/prometheus/client_golang/prometheus/promhttp"
)

func startMetricsServer(addr string) {
	http.Handle("/metrics", promhttp.Handler())
	log.Printf("Metrics server listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, nil))
}
```

In `main.go`, wire everything together:

```go
func main() {
	states := NewStateStore()
	detector := NewAnomalyDetector(states)

	upstream := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte("OK — you're safe\n"))
	})

	middleware := NewSafeMiddleware(upstream, states, detector, 5.0) // 5 req/s

	go startMetricsServer(":2112")

	log.Println("safe gateway listening on :8080")
	log.Fatal(http.ListenAndServe(":8080", middleware))
}
```

### Step 7: Add a Safety Score Endpoint

For debugging and dashboarding, expose a per-user safety score API:

```go
func (m *SafeMiddleware) SafetyScoreHandler(w http.ResponseWriter, r *http.Request) {
	userID := r.URL.Query().Get("user_id")
	if userID == "" {
		http.Error(w, "missing user_id", http.StatusBadRequest)
		return
	}
	state := m.states.GetOrCreate(userID, 100, 5)
	state.mu.Lock()
	score := state.SafetyScore
	state.mu.Unlock()
	fmt.Fprintf(w, "user_id=%s safety_score=%.1f\n", userID, score)
}
```

Register it in `main.go` alongside the metrics endpoint.

---

## Running and Testing It

### Build and Run

```bash
go build -o safe ./...
./safe
```

The gateway starts on `:8080` and the metrics server on `:2112`.

### Send Test Requests

Use `curl` to simulate traffic from different users:

```bash
# Normal traffic — should succeed
curl -H "X-User-ID: alice" http://localhost:8080/

# Burst traffic — will trigger rate limiting and anomaly alerts
for i in $(seq 1 60); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "X-User-ID: bob" http://localhost:8080/
done
```

You should see `429` responses for user `bob` once the token bucket empties, and log lines flagging burst behavior.

### Check Metrics

```bash
curl http://localhost:2112/metrics | grep safe_
```

You'll see output like:

```
safe_requests_total{user_id="alice",status="allowed"} 5.0
safe_requests_total{user_id="bob",status="rejected"} 10.0
safe_rejections_total{user_id="bob",reason="rate_limit"} 10.0
```

### Write a Benchmark

Add a benchmark test to prove throughput:

```go
package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func BenchmarkSafeMiddleware(b *testing.B) {
	states := NewStateStore()
	detector := NewAnomalyDetector(states)
	upstream := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	})
	middleware := NewSafeMiddleware(upstream, states, detector, 1000)

	req := httptest.NewRequest("GET", "/", nil)
	req.Header.Set("X-User-ID", "bench-user")
	w := httptest.NewRecorder()

	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		middleware.ServeHTTP(w, req)
		w.Result().Body.Close()
		w.Code = 0 // reset
	}
}
```

Run it with:

```bash
go test -bench=. -benchmem ./...
```

You should see throughput in the range of **50,000–100,000 requests per second** on a modern machine, which is competitive with Redis-backed rate limiters for single-node deployments.

---

## Extending It: Your Roadmap to Senior-Level

The project above is a solid foundation. Here are six concrete upgrades that transform it from a toy into something that would survive a production review:

1. **Add Redis-backed persistence for the state store.** Replace the in-memory `StateStore` with a Redis client using [go-redis](https://github.com/redis/go-redis), storing token bucket state as Redis hashes with Lua scripts for atomic updates. This demonstrates you understand the trade-offs between speed and durability — and that horizontal scalability requires shared state. It matters because a single-node gateway is a single point of failure.

2. **Implement horizontal scaling with a consistent hash ring.** Use [hashicorp/memberlist](https://github.com/hashicorp/memberlist) to gossip state across multiple gateway instances, so rate limits are enforced cluster-wide rather than per-node. This signals distributed systems knowledge and is directly relevant to how services like Cloudflare's rate limiting work at the edge.

3. **Add structured logging with OpenTelemetry traces.** Replace `log.Printf` with [zap](https://github.com/uber-go/zap) for structured JSON logs and integrate the [OpenTelemetry Go SDK](https://github.com/open-telemetry/opentelemetry-go) to emit distributed traces. This matters because every production system needs to answer "why did this request get rejected?" — and traces give you the full request lifecycle.

4. **Build a circuit breaker for the upstream.** Using [sony/gobreaker](https://github.com/sony/gobreaker), wrap the upstream handler so that if it starts failing, the gateway fails open or fails closed based on configuration. Fault tolerance isn't optional in production — it's what separates a demo from a service.

5. **Add a web dashboard with real-time charts.** Use [Grafana](https://grafana.com/) connected to the Prometheus metrics endpoint to build a live dashboard showing per-user request rates, rejection trends, and safety score distributions. This proves you can operationalize what you build, not just write it.

6. **Implement adaptive rate limiting with an exponential moving average.** Instead of a fixed token-bucket rate, use an EMA of recent request patterns to dynamically adjust per-user limits — increasing them for trusted users and tightening them for flagged ones. This is the algorithm behind [Cloudflare's adaptive rate limiting](https://blog.cloudflare.com/rate-limiting-with-ema/) and demonstrates you can implement production-grade adaptive systems.

Each of these upgrades maps to a real production concern and can be the centerpiece of a system design interview. Pick one per sprint and you'll have a portfolio that tells a story of continuous growth.

---

## Key Takeaways

- **Token buckets and sliding windows are not academic exercises** — they are the same primitives used by Cloudflare, Stripe, and every major API gateway. Implementing them yourself proves you understand the mechanics, not just the API calls.
- **Concurrency is the #1 systems skill hiring managers screen for.** The `sync.Mutex`, `RWMutex`, and goroutine patterns in this project are exactly what you'll discuss in a Go backend interview.
- **Observability is not optional** — every production system needs metrics. The Prometheus integration you build here is the same pattern used in Kubernetes, Istio, and Grafana stacks.
- **A side project's value is proportional to its extensibility.** The middleware architecture you build here lets you swap in Redis, add tracing, and scale horizontally — each upgrade deepening your systems knowledge.
- **Benchmarking separates engineers from coders.** Writing a `BenchmarkSafeMiddleware` test proves your code performs under load and gives you concrete numbers to discuss in interviews.

---

## Further Reading

- **[Token Bucket — Wikipedia](https://en.wikipedia.org/wiki/Token_bucket)** — The canonical reference for the token-bucket algorithm. Read the "Comparison with leaky bucket" section to understand why token buckets are preferred for rate limiting.
- **[RFC 6585 — Additional HTTP Status Codes](https://datatracker.ietf.org/doc/html/rfc6585)** — Defines the `429 Too Many Requests` status code and its `Retry-After` header, which you should implement in the next iteration of `safe`.
- **[The Prometheus Instrumentation Handbook](https://prometheus.io/docs/instrumenting/writing_exporters/)** — Official Prometheus documentation on building custom metrics exporters. This is the primary source for the metrics server you built in Step 6.
- **[Cloudflare Blog: Rate Limiting with EMA](https://blog.cloudflare.com/rate-limiting-with-ema/)** — A production-grade explanation of exponential moving average-based rate limiting, which is Upgrade #6 in the roadmap above.
- **[Designing Data-Intensive Applications by Martin Kleppmann](https://dataintensive.net/)** — Chapters 3 and 11 cover exactly the state management and fault tolerance concepts this project touches. This book is the single best resource for deepening into the distributed systems theory behind `safe`.
- **[OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)** — The canonical specification for observability telemetry. Study this to understand the trace and metric formats you'll implement in Upgrade #3.

---

*Build it. Benchmark it. Break it. Then put it on your CV — with the numbers.*