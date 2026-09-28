---
title: "Build a Distributed Rate Limiter: A CV-Worthy Side Project"
date: "2026-09-28T12:01:54.673"
draft: false
tags: ["go", "distributed-systems", "rate-limiting", "redis", "golang", "gRPC"]
description: "A hands-on guide to building a distributed rate limiter that signals real systems engineering skills to hiring managers."
summary: "Learn to build a distributed rate limiter using Go and Redis, with gRPC, observability, and fault tolerance — a portfolio project that stands out."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-28-build-a-distributed-rate-limiter-a-cv-worthy-side-project.svg"
  alt: "A code editor displaying a distributed rate limiter implementation with Redis and Go."
  caption: ""
  relative: false
---

> **TL;DR** — Build a distributed rate limiter in Go backed by Redis, exposing a gRPC API with Prometheus metrics. This project demonstrates distributed systems, fault tolerance, and observability — exactly what senior engineering roles look for.

A single-line side project that packs a punch: a distributed rate limiter. It’s the kind of thing that shows up in production at every scale‑aware company, and building one from scratch forces you to confront concurrency, network partitions, and observability in a way a toy app never will. This guide walks you through a complete, runnable implementation you can drop into your portfolio and talk about in interviews with confidence.

## Why This Project Stands Out on a CV

A distributed rate limiter signals a specific cluster of skills that hiring managers actively seek:

- **Distributed Systems Fundamentals** — You’ve dealt with shared state, atomicity, and network latency.
- **Concurrency & Parallelism** — Go’s goroutines and channels are first‑class citizens in the implementation.
- **Production Observability** — Prometheus metrics and health checks show you care about what happens after deploy.
- **Fault Tolerance** — Handling Redis failures gracefully proves you think beyond the happy path.
- **API Design** — gRPC forces you to think about contracts, versioning, and backward compatibility.

This project positions you for roles like Backend Engineer, Infrastructure Engineer, or SRE — anywhere reliability at scale matters.

## Architecture Overview

The system is composed of a few well‑defined pieces that communicate over the network:

```
+-----------------+       +-------------------+       +------------+
|  gRPC Client    | ----> |  Rate Limiter     | ----> |  Redis     |
|  (any language) |       |  Service (Go)     | <---- |  Server    |
+-----------------+       |  - gRPC endpoint  |       +------------+
                          |  - Prometheus     |
                          |    metrics        |
                          |  - Health check   |
                          +-------------------+
```

- **Go Application** — The core service, compiled to a single binary. It hosts a gRPC server, a Prometheus metrics endpoint, and a health check endpoint.
- **Redis** — The centralized counter store. All rate‑limit decisions are made atomically via a Lua script executed on the Redis server, ensuring consistency even under high concurrency.
- **gRPC** — The API layer. Clients send a request with a key (e.g., user ID) and a limit; the service responds with allow/deny.
- **Prometheus** — Scrapes metrics like `requests_total`, `allowed_total`, `denied_total`, and `redis_latency_ms`.

## Building It Step by Step

We’ll use Go 1.22+, Redis 7+, and the following libraries: `github.com/go-redis/redis/v8`, `google.golang.org/grpc`, `github.com/prometheus/client_golang`.

### Step 1: Project Scaffold

```bash
mkdir rate-limiter && cd rate-limiter
go mod init github.com/yourname/rate-limiter
go get github.com/go-redis/redis/v8 google.golang.org/grpc github.com/prometheus/client_golang
```

### Step 2: Define the gRPC Proto

Create `proto/ratelimit.proto`:

```protobuf
syntax = "proto3";
package ratelimit;

service RateLimiter {
  rpc Allow (AllowRequest) returns (AllowResponse);
}

message AllowRequest {
  string key = 1;
  int32 max_requests = 2;
  int32 window_seconds = 3;
}

message AllowResponse {
  bool allowed = 1;
  int64 remaining = 2;
}
```

Generate Go code with `protoc` and the Go plugins. For brevity, assume `proto/ratelimit.pb.go` is generated.

### Step 3: Atomic Rate Limiting with Redis Lua

The core logic lives in a Lua script executed atomically on Redis. This prevents race conditions without distributed locks.

```go
// internal/limiter/limiter.go
package limiter

import (
	"context"
	"fmt"
	"time"

	"github.com/go-redis/redis/v8"
)

const luaScript = `
local key = KEYS[1]
local max = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = 1

local bucket = redis.call('hmget', key, 'count', 'last_refill')
local count = tonumber(bucket[1]) or 0
local last_refill = tonumber(bucket[2]) or now

local elapsed = now - last_refill
local refill_count = math.floor(elapsed / window)
count = math.max(0, count - refill_count)

if count < max then
  count = count + 1
  redis.call('hmset', key, 'count', count, 'last_refill', now)
  redis.call('expire', key, window * 2)
  return {1, max - count}
else
  return {0, 0}
end
`

type Limiter struct {
	client *redis.Client
	script *redis.Script
}

func NewLimiter(client *redis.Client) *Limiter {
	return &Limiter{
		client: client,
		script: redis.NewScript(luaScript),
	}
}

func (l *Limiter) Allow(ctx context.Context, key string, max int64, window time.Duration) (bool, int64, error) {
	now := time.Now().Unix()
	res, err := l.script.Run(ctx, l.client, []string{key}, max, int64(window.Seconds()), now).Result()
	if err != nil {
		return false, 0, err
	}
	arr := res.([]interface{})
	allowed := arr[0].(int64) == 1
	remaining := arr[1].(int64)
	return allowed, remaining, nil
}
```

### Step 4: gRPC Server with Prometheus Metrics

```go
// internal/server/server.go
package server

import (
	"context"
	"net"

	"google.golang.org/grpc"
	pb "yourmodule/proto"
	"yourmodule/internal/limiter"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"net/http"
)

var (
	requestsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "requests_total",
		Help: "Total rate limit requests",
	}, []string{"key", "result"})
)

type Server struct {
	pb.UnimplementedRateLimiterServer
	limiter *limiter.Limiter
}

func NewServer(lim *limiter.Limiter) *Server {
	return &Server{limiter: lim}
}

func (s *Server) Allow(ctx context.Context, req *pb.AllowRequest) (*pb.AllowResponse, error) {
	allowed, remaining, err := s.limiter.Allow(ctx, req.Key, req.MaxRequests, time.Duration(req.WindowSeconds)*time.Second)
	result := "denied"
	if allowed {
		result = "allowed"
	}
	requestsTotal.WithLabelValues(req.Key, result).Inc()
	return &pb.AllowResponse{Allowed: allowed, Remaining: remaining}, err
}

func (s *Server) Start() {
	lis, _ := net.Listen("tcp", ":50051")
	grpcServer := grpc.NewServer()
	pb.RegisterRateLimiterServer(grpcServer, s)
	go grpcServer.Serve(lis)

	// Prometheus metrics endpoint
	http.Handle("/metrics", promhttp.Handler())
	go http.ListenAndServe(":2112", nil)
}
```

### Step 5: Main Entry Point

```go
// cmd/server/main.go
package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/go-redis/redis/v8"
	"yourmodule/internal/limiter"
	"yourmodule/internal/server"
)

func main() {
	ctx := context.Background()
	rdb := redis.NewClient(&redis.Options{Addr: "localhost:6379"})
	if _, err := rdb.Ping(ctx).Result(); err != nil {
		log.Fatal("cannot connect to Redis:", err)
	}

	lim := limiter.NewLimiter(rdb)
	srv := server.NewServer(lim)
	srv.Start()

	quit := make(chan os.Signal, 1)
	signal.Notify(quit, syscall.SIGINT, syscall.SIGTERM)
	<-quit
	log.Println("shutting down")
}
```

## Running and Testing It

Start Redis locally (Docker makes this trivial):

```bash
docker run -p 6379:6379 redis:7-alpine
```

Build and run the service:

```bash
go build -o rate-limiter ./cmd/server
./rate-limiter
```

You now have a gRPC server on `:50051` and a Prometheus endpoint on `:2112/metrics`.

To test, use a simple Go client or `grpcurl`:

```go
// client/main.go
conn, _ := grpc.Dial("localhost:50051", grpc.WithInsecure())
client := pb.NewRateLimiterClient(conn)
res, _ := client.Allow(ctx, &pb.AllowRequest{Key: "user:1", MaxRequests: 5, WindowSeconds: 10})
fmt.Println(res.Allowed, res.Remaining)
```

Verify metrics:

```bash
curl localhost:2112/metrics | grep requests_total
```

You’ll see counters incrementing with `allowed` or `denied` labels.

## Extending It: Your Roadmap to Senior-Level

Each upgrade adds a layer of production‑grade thinking that hiring managers notice:

1. **Redis Cluster Mode** — Switch the client to `redis.NewClusterClient` and shard keys across nodes. This demonstrates horizontal data scaling and partition tolerance.
2. **Consistent Hashing for Multi‑Tenant Routing** — Add a sidecar that routes requests to the correct Redis shard based on a consistent hash of the key, minimizing reshuffling on node addition.
3. **Distributed Tracing with Jaeger** — Instrument the gRPC server with OpenTelemetry and export traces. This shows you understand request lifecycle visibility across services.
4. **Circuit Breaker on Redis Calls** — Use `github.com/sony/gobreaker` to fail fast when Redis is unhealthy, falling back to a local token bucket. This proves fault‑tolerance design.
5. **Benchmarking with Vegeta** — Run `vegeta attack -rate=1000 -duration=30s` against the gRPC endpoint and analyze latency percentiles. This demonstrates performance engineering.
6. **Configuration Management** — Replace hardcoded values with a `viper`-driven config that reads from envvars and a YAML file. This signals production operational maturity.

## Key Takeaways

- A distributed rate limiter is a compact project that forces you to implement atomicity, concurrency, and observability — skills that translate directly to production systems.
- Using Redis Lua scripts eliminates the need for distributed locks and is a pattern you’ll reuse in many real‑world scenarios.
- gRPC + Prometheus + health checks give your project a production‑flavored API surface and monitoring stack out of the box.
- Each extension (clustering, tracing, circuit breaking) maps to a senior‑level concept that you can discuss knowledgeably in interviews.

## Further Reading

- [Redis Lua Scripting Documentation](https://redis.io/docs/manual/programmability/eval/) — The primary source for the atomic script pattern used here.
- [gRPC Official Documentation](https://grpc.io/docs/) — The canonical guide to defining services and generating code.
- [Prometheus Client Libraries](https://prometheus.io/docs/instrumenting/writing_exporters/) — How to instrument your Go application correctly.
- [The Redis Handbook](https://redis.com/redis-best-practices/) — Best practices for Redis in production, including memory management and persistence.
- [OpenTelemetry Go Instrumentation](https://opentelemetry.io/docs/instrumentation/go/) — For adding distributed tracing as an extension.
- [Vegeta: HTTP Load Testing Tool](https://github.com/tsenart/vegeta) — The canonical tool for benchmarking your gRPC service under load.
