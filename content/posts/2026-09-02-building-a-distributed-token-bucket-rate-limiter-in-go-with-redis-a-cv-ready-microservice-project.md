---
title: "Building a Distributed Token Bucket Rate Limiter in Go with Redis: A CV-Ready Microservice Project"
date: "2026-09-02T00:00:46.544"
draft: false
tags: ["go", "redis", "microservices", "rate-limiting", "system-design"]
description: "A hands-on build guide for a distributed token bucket rate limiter microservice in Go, backed by Redis. Real code, tests, and a roadmap from junior to senior-grade project."
summary: "Build a production-shaped distributed rate limiter in Go and Redis using a token bucket algorithm. Includes runnable code, atomic Lua scripts, integration tests, and a roadmap to extend it for your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-building-a-distributed-token-bucket-rate-limiter-in-go-with-redis-a-cv-ready-microservice-project.svg"
  alt: "Go and Redis logos side by side with token bucket diagram"
  caption: ""
  relative: false
---

> **TL;DR** — A distributed token bucket rate limiter is a small project that punches well above its weight on a CV. It touches concurrency, Redis atomicity, HTTP middleware, observability, and fault tolerance — the exact stack hiring managers screen for. This guide walks you through a runnable Go service (using `redis/go-redis` and a server-side Lua script for atomicity), shows you how to test it, and gives you a six-step roadmap to harden it from a weekend hack into senior-staff-grade work.

A rate limiter is one of those components that looks trivial — "just count requests" — until you actually build one and discover it has to be **distributed, atomic, fair across multiple instances, and survive Redis going down**. That tension between simplicity and rigor is what makes it a perfect CV project. It's small enough to finish in a weekend but deep enough that you can talk about it intelligently in a system design interview for an hour.

The version we'll build here is a token bucket implemented in Go, stored in Redis, and exposed both as an HTTP middleware and as a standalone gRPC service. By the end you'll have ~400 lines of focused, runnable code and a clear list of upgrades that turn it from "follows a tutorial" into "solves a real problem."

## Why This Project Stands Out on a CV

Hiring managers and tech leads skim portfolios looking for **signal of how you think**, not whether you can copy a Stack Overflow answer. A rate limiter hits an unusual number of these signals in a small surface area:

- **Distributed systems thinking.** You have to reason about atomicity, consistency, and what happens when a node crashes mid-decrement. That's the same vocabulary used in Kafka offset commits, Postgres advisory locks, and payment idempotency.
- **Algorithmic literacy.** Token bucket, leaky bucket, fixed window, sliding window, GCRA — being able to compare them and pick one is a tell. The [Stripe engineering blog](https://stripe.com/blog/rate-limiters) and [Cloudflare's blog](https://blog.cloudflare.com/counting-things-a-lot-of-different-things/) both have great writeups of these tradeoffs.
- **Production-shaped code.** You'll write a Lua script, structured logging with `slog`, Prometheus metrics, a Dockerfile, and integration tests. That's the same shape as the code review you'll get on day one.
- **A concrete conversation piece.** "Tell me about a hard bug you fixed" gets an instant answer: a race condition you actually hunted down, not a hypothetical.
- **Role signaling.** Backend, platform, infrastructure, and senior backend roles all list rate limiting as a relevant system. SREs care because it's the kind of thing that pages them at 3 AM. It is one of the rare projects that looks credible for several adjacent roles simultaneously.

The tradeoff is that **a weak version of this project is worse than no project**. A `map[string]int` with a mutex is a tutorial, not a portfolio piece. The bar is "would I trust this in production with a small SLA?" We'll get there.

## Architecture Overview

The system has four logical components. Keep them separated in your code so each can be reasoned about, tested, and replaced independently.

- **HTTP layer (Gin or `net/http`)**: receives the incoming request, extracts the rate limit key (user ID, API key, IP), and asks the limiter whether to allow or reject. Returns `429 Too Many Requests` with `Retry-After` and `X-RateLimit-*` headers when over the limit.
- **Limiter core (Go)**: implements the token bucket algorithm. The bucket's state — `tokens` (float) and `last_refill` (unix nanos) — lives in Redis. The core is **stateless** in the Go process: all coordination happens in Redis.
- **Storage layer (Redis)**: stores one hash per bucket keyed by the rate limit identifier. All state mutations happen via a Lua script so the read-compute-write is atomic. This is the single most important design decision in the project.
- **Observability layer (`slog` + Prometheus)**: every allow/deny decision increments a counter, every Redis call is timed, and p99 latency is recorded. The metrics endpoint at `/metrics` is what makes the project credible in an interview.

```
┌──────────┐    1. GET /api/orders/42
│  Client  │ ──────────────────────────▶ ┌──────────────┐
└──────────┘                              │  Gin router  │
                                          │  + mw.Auth() │
                                          └──────┬───────┘
                                                 │ key = userID
                                                 ▼
                                          ┌──────────────┐
                                          │ Token Bucket │ ── EVAL ──▶ Redis
                                          │   (Go core)  │ ◀─ tokens ─┘
                                          └──────┬───────┘
                                                 │ allow / deny
                                                 ▼
                                          ┌──────────────┐
                                          │   Handler    │ ── 200 OK / 429 ─▶ Client
                                          └──────────────┘
```

A single Redis instance handles all coordination. The Go service is **horizontally scalable** with no further work — any number of replicas can point at the same Redis, and the atomic Lua script guarantees correctness.

## Building It Step by Step

The full source lives in about a dozen small files. We'll go through the parts that matter.

### Step 1: Project Layout and Dependencies

```bash
mkdir ratelimiter && cd ratelimiter
go mod init github.com/yourname/ratelimiter
go get github.com/gin-gonic/gin
go get github.com/redis/go-redis/v9
go get github.com/prometheus/client_golang/prometheus
go get github.com/prometheus/client_golang/prometheus/promhttp
```

```text
ratelimiter/
├── cmd/server/main.go         # composition root
├── internal/limiter/
│   ├── bucket.go              # token bucket math
│   ├── redis_store.go         # Redis client + Lua script
│   └── limiter.go             # the Allow() method
├── internal/middleware/
│   └── http.go                # Gin middleware
├── internal/observability/
│   └── metrics.go             # Prometheus counters/histograms
├── scripts/refill.lua         # atomic refill-and-decrement
├── test/integration_test.go
├── Dockerfile
└── docker-compose.yml
```

### Step 2: The Token Bucket Math

A token bucket has two parameters: `capacity` (max tokens) and `refill_rate` (tokens per second). Each request consumes one token. If the bucket is empty, the request is denied.

The "trick" is that the bucket refills **lazily**: instead of a background goroutine adding tokens on a timer, every call to `Allow` computes how many tokens *would* have been added since the last call. This is what makes the algorithm stateless on the server side.

```go
// internal/limiter/bucket.go
package limiter

import "time"

type Decision struct {
    Allowed     bool
    TokensLeft  float64
    RetryAfter  time.Duration
}

type Config struct {
    Capacity    float64
    RefillRate  float64 // tokens per second
}

func decide(cfg Config, tokens, lastRefillNanos float64, now time.Time, cost float64) Decision {
    elapsed := now.Sub(time.Unix(0, int64(lastRefillNanos))).Seconds()
    if elapsed < 0 {
        elapsed = 0
    }
    refilled := tokens + elapsed*cfg.RefillRate
    if refilled > cfg.Capacity {
        refilled = cfg.Capacity
    }

    if refilled >= cost {
        return Decision{
            Allowed:    true,
            TokensLeft: refilled - cost,
        }
    }
    missing := cost - refilled
    wait := time.Duration(missing / cfg.RefillRate * float64(time.Second))
    return Decision{
        Allowed:    false,
        TokensLeft: refilled,
        RetryAfter: wait,
    }
}
```

The pure function is easy to unit test without touching Redis. That separation — pure math in one file, I/O in another — is what makes this project reviewable.

### Step 3: The Atomic Lua Script

This is the heart of the system. Without atomicity, two concurrent requests can both read `tokens=0.5`, both decide they're allowed, and both consume — oversubscribing the bucket by 100%. Redis runs Lua scripts atomically (single-threaded execution), which solves this in a few lines.

```lua
-- scripts/refill.lua
-- KEYS[1] = bucket key, e.g. "rl:user:42"
-- ARGV[1] = capacity (float)
-- ARGV[2] = refill_rate per second (float)
-- ARGV[3] = now in unix nanoseconds (int)
-- ARGV[4] = cost (float, usually 1)
-- Returns: {allowed (1/0), tokens_left (string float), retry_after_ms (int)}

local key      = KEYS[1]
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])
local now      = tonumber(ARGV[3])
local cost     = tonumber(ARGV[4])

local data = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(data[1])
local ts     = tonumber(data[2])

if tokens == nil then
    tokens = capacity
    ts = now
end

local elapsed_s = (now - ts) / 1e9
if elapsed_s < 0 then elapsed_s = 0 end

tokens = math.min(capacity, tokens + elapsed_s * rate)

local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
    tokens = tokens - cost
    allowed = 1
else
    local missing = cost - tokens
    retry_after_ms = math.ceil((missing / rate) * 1000)
end

redis.call("HMSET", key, "tokens", tokens, "ts", now)
-- Expire idle buckets after 1 hour of disuse to bound memory
redis.call("PEXPIRE", key, 3600000)

return {allowed, tostring(tokens), retry_after_ms}
```

Note the `tostring(tokens)` — Redis Lua returns floats as strings to avoid precision loss. The Go side parses them back with `strconv.ParseFloat`.

### Step 4: The Redis Store Wrapper

```go
// internal/limiter/redis_store.go
package limiter

import (
    "context"
    _ "embed"
    "strconv"
    "time"

    "github.com/redis/go-redis/v9"
)

//go:embed refill.lua
var refillLua string

type Store struct {
    rdb     *redis.Client
    script  *redis.Script
    cfg     Config
}

func NewStore(rdb *redis.Client, cfg Config) *Store {
    return &Store{
        rdb:    rdb,
        script: redis.NewScript(refillLua),
        cfg:    cfg,
    }
}

func (s *Store) Allow(ctx context.Context, key string, cost float64) (Decision, error) {
    now := time.Now().UnixNano()
    res, err := s.script.Run(
        ctx, s.rdb,
        []string{"rl:" + key},
        s.cfg.Capacity, s.cfg.RefillRate, now, cost,
    ).Result()
    if err != nil {
        return Decision{}, err
    }
    arr, ok := res.([]interface{})
    if !ok || len(arr) != 3 {
        return Decision{}, redis.ErrClosed // malformed response
    }
    allowed, _ := arr[0].(int64)
    tokensStr, _ := arr[1].(string)
    retryMs, _ := arr[2].(int64)

    tokens, _ := strconv.ParseFloat(tokensStr, 64)
    return Decision{
        Allowed:    allowed == 1,
        TokensLeft: tokens,
        RetryAfter: time.Duration(retryMs) * time.Millisecond,
    }, nil
}
```

The `//go:embed` line compiles the Lua file into the binary. No "missing script" deployment errors. The script is registered as a `*redis.Script`, which uses `EVALSHA` after the first call and falls back to `EVAL` on `NOSCRIPT` — a small optimization that shows you understand Redis internals.

### Step 5: The HTTP Middleware

```go
// internal/middleware/http.go
package middleware

import (
    "net/http"
    "strconv"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/yourname/ratelimiter/internal/limiter"
    "github.com/yourname/ratelimiter/internal/observability"
)

func RateLimit(store *limiter.Store, keyFn func(*gin.Context) string) gin.HandlerFunc {
    return func(c *gin.Context) {
        start := time.Now()
        key := keyFn(c)
        if key == "" {
            c.Next()
            return
        }
        dec, err := store.Allow(c.Request.Context(), key, 1)
        observability.Decisions.WithLabelValues(strconv.FormatBool(dec.Allowed)).Inc()
        observability.Latency.Observe(time.Since(start).Seconds())

        c.Header("X-RateLimit-Limit", strconv.FormatFloat(store.Cfg().Capacity, 'f', 0, 64))
        c.Header("X-RateLimit-Remaining", strconv.FormatFloat(dec.TokensLeft, 'f', 0, 64))
        if err != nil {
            // Fail-open or fail-closed? Make it explicit.
            c.Next()
            return
        }
        if !dec.Allowed {
            c.Header("Retry-After", strconv.Itoa(int(dec.RetryAfter.Seconds())+1))
            c.AbortWithStatusJSON(http.StatusTooManyRequests, gin.H{
                "error":       "rate_limited",
                "retry_after": dec.RetryAfter.Seconds(),
            })
            return
        }
        c.Next()
    }
}
```

Notice the explicit **fail-open decision** when Redis is unreachable. That's a real production trade-off — fail-open gives availability, fail-closed gives protection. Calling it out in code and a README is the kind of thing that impresses reviewers.

### Step 6: The Composition Root and a Real Endpoint

```go
// cmd/server/main.go
package main

import (
    "context"
    "log/slog"
    "net/http"
    "os"

    "github.com/gin-gonic/gin"
    "github.com/prometheus/client_golang/prometheus/promhttp"
    "github.com/redis/go-redis/v9"
    "github.com/yourname/ratelimiter/internal/limiter"
    "github.com/yourname/ratelimiter/internal/middleware"
    "github.com/yourname/ratelimiter/internal/observability"
)

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
    slog.SetDefault(logger)

    rdb := redis.NewClient(&redis.Options{Addr: os.Getenv("REDIS_ADDR")})
    if err := rdb.Ping(context.Background()).Err(); err != nil {
        slog.Error("redis unreachable", "err", err)
        os.Exit(1)
    }

    store := limiter.NewStore(rdb, limiter.Config{Capacity: 10, RefillRate: 1})
    observability.Register()

    r := gin.New()
    r.Use(gin.Recovery())
    r.GET("/healthz", func(c *gin.Context) { c.JSON(200, gin.H{"ok": true}) })
    r.GET("/metrics", gin.WrapH(promhttp.Handler()))

    api := r.Group("/api")
    api.Use(middleware.RateLimit(store, func(c *gin.Context) string {
        return c.GetHeader("X-API-Key") // or c.Param("tenant") in real life
    }))
    api.GET("/ping", func(c *gin.Context) {
        c.JSON(200, gin.H{"pong": true})
    })

    slog.Info("listening", "addr", ":8080")
    if err := r.Run(":8080"); err != nil {
        slog.Error("server died", "err", err)
    }
}
```

That's the entire service. ~400 lines of focused code.

## Running and Testing It

A project that doesn't run is a project that doesn't exist. Set up Docker Compose so reviewers can `docker compose up` and see results in 30 seconds.

```yaml
# docker-compose.yml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  ratelimiter:
    build: .
    environment:
      REDIS_ADDR: redis:6379
    ports: ["8080:8080"]
    depends_on: [redis]
```

```dockerfile
# Dockerfile
FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /out/ratelimiter ./cmd/server

FROM gcr.io/distroless/static-debian12
COPY --from=build /out/ratelimiter /ratelimiter
EXPOSE 8080
ENTRYPOINT ["/ratelimiter"]
```

### Unit Tests for the Math

```go
// internal/limiter/bucket_test.go
package limiter

import (
    "testing"
    "time"
)

func TestRefill(t *testing.T) {
    cfg := Config{Capacity: 10, RefillRate: 2}
    now := time.Unix(0, 0)
    dec := decide(cfg, 0, 0, now, 1)
    if !dec.Allowed { t.Fatal("should allow") }
}

func TestDeny(t *testing.T) {
    cfg := Config{Capacity: 1, RefillRate: 1}
    now := time.Unix(0, int64(2*time.Second))
    dec := decide(cfg, 0, 0, now, 5)
    if dec.Allowed { t.Fatal("should deny, cost > capacity") }
}
```

### Integration Test with a Real Redis

Use [`testcontainers-go`](https://golang.testcontainers.org/) to spin up Redis in Docker for the test, and verify the atomicity guarantee.

```go
// test/integration_test.go
func TestConcurrentAllowance(t *testing.T) {
    ctx := context.Background()
    redisC, _ := rediscontainer.RunContainer(ctx, testcontainers.WithImage("redis:7-alpine"))
    rdb := redis.NewClient(&redis.Options{Addr: redisC.URI()})
    store := limiter.NewStore(rdb, limiter.Config{Capacity: 100, RefillRate: 0})

    var wg sync.WaitGroup
    var allowed int64
    for i := 0; i < 500; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            d, _ := store.Allow(ctx, "user:1", 1)
            if d.Allowed { atomic.AddInt64(&allowed, 1) }
        }()
    }
    wg.Wait()
    if allowed != 100 {
        t.Fatalf("expected exactly 100 allowed, got %d", allowed)
    }
}
```

That test catches the race condition you'd hit if you naively did `GET` + `SET` from Go. Run it with `go test -race ./...`.

### Smoke Test

```bash
docker compose up -d
# Burst 15 requests against an endpoint with capacity 10, refill 1/s
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "X-API-Key: demo" http://localhost:8080/api/ping
done
```

You should see ten `200`s and five `429`s. Then wait five seconds and try again — the bucket will have refilled five tokens.

## Extending It: Your Roadmap to Senior-Level

A weekend build is the **floor**, not the ceiling. The path from "junior" to "senior staff" is paved with the following upgrades. Pick three and you'll have a project that lands interviews.

1. **Multi-tier limits (per-IP, per-user, per-tenant simultaneously).** Real systems have layered limits — Cloudflare rate limits at edge, then per-route. Implementing this means a slice of `*Store`s and middleware composition. *It shows you understand defense in depth and the principle of least privilege.*
2. **Sliding window or GCRA algorithm option behind a feature flag.** Different workloads want different algorithms. Token bucket allows bursts; sliding window enforces a stricter average. *It demonstrates algorithmic breadth and that you've read the literature, not just one blog post.*
3. **Prometheus + Grafana dashboard with RED metrics.** Wire `rate(allow_total[5m])`, `rate(deny_total[5m])`, and a histogram of Lua execution time. Add alerts on p99 > 5ms. *It proves you think about operability, not just functionality.*
4. **Redis Cluster and Sentinel support.** Cluster means the Lua script must declare its keys, and the client must hash-tag them: `rl:{user:42}:api`. *It forces you to confront sharding, which most "tutorial" projects quietly ignore.*
5. **Graceful degradation with a local fallback bucket.** When Redis is slow, fall back to an in-process `golang.org/x/time/rate` limiter. The fail-open decision becomes "fail-soft: allow with degraded accuracy." *This is the kind of fault-tolerance reasoning that staff-level candidates are expected to articulate.*
6. **Benchmark suite with `go test -bench` and `wrk`.** Measure the throughput ceiling of the Go binary and the Lua script. The [Redis `redis-benchmark` tool](https://redis.io/docs/management/optimization/benchmarks/) and [the `wrk` load generator](https://github.com/wg/wrk) are your friends. *Benchmarks are how you turn "it works" into "it works at 50k QPS on a single core."*

## Key Takeaways

- A distributed token bucket is one of the highest signal-to-size ratios you can build: a few hundred lines of Go and Lua, but it exercises concurrency, atomicity, observability, and graceful degradation.
- The single most important design choice is making the refill-and-decrement **atomic** via a server-side Lua script. Without it, the rate limiter is broken under load.
- Separate pure logic (token math) from I/O (Redis). The pure part is trivially unit-testable; the I/O part needs integration tests with a real Redis (`testcontainers` is perfect).
- Production-shaped details — `slog`, Prometheus metrics, `Retry-After` headers, a Dockerfile, and an explicit fail-open vs. fail-closed decision — are what separate "tutorial" from "portfolio."
- A senior-grade version adds multi-tier limits, algorithm choice, real observability, Redis Cluster awareness, graceful degradation, and published benchmarks. Pick three and you'll have a talking point that holds up in a 45-minute system design interview.

## Further Reading

- [Stripe — Scaling your API with rate limiters](https://stripe.com/blog/rate-limiters) — the canonical walkthrough of the algorithm tradeoffs and production failure modes.
- [Cloudflare — Counting things, a lot of different things](https://blog.cloudflare.com/counting-things-a-lot-of-different-things/) — how Cloudflare does sliding-window counting at edge scale.
- [Redis — EVAL and Lua scripting](https://redis.io/docs/latest/develop/interact/programmability/eval-intro/) — the official reference for atomic Lua execution, which is the foundation of this whole design.
- [Redis — Go client `go-redis`](https://redis.uptrace.dev/) — best-in-class Go client; the `Script` type and `EVALSHA` handling are explained in its guide.
- [IETF — RateLimit Headers for HTTP draft-09](https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/) — the emerging standard for `RateLimit-Policy` and `RateLimit` response headers.
- [Uber — Himeji: robust and fast global rate limiter](https://www.uber.com/blog/himeji/) — a real-world case study of rate limiting at extreme scale, useful for the "what next" interview conversation.
- [Google SRE Book — Handling Overload](https://sre.google/sre-book/handling-overload/) — the chapter on load shedding directly informs the fail-open vs. fail-closed decision in your middleware.