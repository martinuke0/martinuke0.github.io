---
title: "Build an HTTP Load Balancer in Go: A CV-Worthy Side Project"
date: "2026-09-03T01:00:10.083"
draft: false
tags: ["golang", "load-balancer", "systems-design", "side-project", "distributed-systems"]
description: "Hands-on guide to building a least-connections HTTP load balancer with health checks in Go — a CV-grade side project that signals real systems skill."
summary: "A practical, runnable build guide for an HTTP load balancer with health checks and least-connections routing. Architecture, code, and a roadmap to senior-level extensions."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-build-an-http-load-balancer-in-go-a-cv-worthy-side-project.svg"
  alt: "Diagram of a load balancer distributing HTTP requests across backend server nodes."
  caption: ""
  relative: false
---

> **TL;DR** — A load balancer is one of the highest signal-per-line-of-code side projects you can ship: it touches networking, concurrency, failure handling, and observability in ~500 lines of Go. This guide walks you through building a least-connections router with active health checks, then maps out the upgrades — sticky sessions, TLS, Prometheus metrics, and chaos testing — that push it from a tutorial demo to something you'd defend in a staff interview.

Hiring managers in backend, platform, and infrastructure roles have seen every todo app and CRUD API that hits their desk. What makes them stop scrolling is a project that demonstrates you understand *how the internet actually works* at the request-routing layer. NGINX, Envoy, HAProxy, and the AWS ALB all solve the same problem you'll solve here, and being able to explain — and modify — one of those systems is a strong signal you can work on them.

## Why This Project Stands Out on a CV

A load balancer is a "force multiplier" project. In a few hundred lines you touch a surprising number of the competencies a staff engineer is supposed to have:

- **TCP and HTTP at the wire level.** You'll handle `net.Listener`, HTTP/1.1 keep-alive, hop-by-hop headers, and request body streaming — not just `http.Get`.
- **Concurrency under contention.** The least-connections algorithm is fundamentally a concurrent counter; you need to reason about atomic updates, mutex contention, and the cost of `sync/atomic` versus a sharded mutex.
- **Failure as a first-class concern.** Health checks, draining, and timeouts are not bolt-ons; they're half the system. Writing them yourself shows you understand that availability is the absence of cascading failures.
- **Production-shaped observability.** Even minimal structured logs and a `/metrics` endpoint put you ahead of 90% of candidates who never instrument anything.
- **Operability.** A sensible CLI, configuration file, and graceful shutdown tell a reviewer you've shipped something you'd be comfortable paged for.

The roles this signals for: backend engineer, platform engineer, SRE, distributed systems engineer, and infrastructure engineer. It pairs especially well with adjacent projects — a key-value store, a job queue, or a tiny Postgres wire-protocol clone — that share the same concurrency and failure vocabulary.

## Architecture Overview

The design below is intentionally simple but mirrors how real L4/L7 balancers are decomposed. You'll build it in roughly five components.

- **Listener (`net.Listen` on TCP).** Accepts client connections, usually on `:8080`. Wraps accepted sockets so each request can be reverse-proxied upstream.
- **Pool of upstream backends.** A `[]Backend` slice, each holding an `URL`, an atomic connection counter, and a `Healthy` flag guarded by a mutex.
- **Picker (the routing algorithm).** Pure function `(backends) -> Backend`. We start with least-connections, then add round-robin and weighted variants for comparison.
- **Health checker.** A background goroutine that issues `GET /healthz` against each backend on a fixed interval, marks the result, and removes the backend from rotation when it fails N consecutive probes.
- **Reverse proxy.** Reads the request, opens (or reuses) a connection to the chosen backend, copies bytes bidirectionally with `io.Copy`, and updates the counter on connect/disconnect.

```text
            ┌──────────────┐
 client ──▶ │  TCP :8080   │
            └──────┬───────┘
                   │ Accept
            ┌──────▼───────┐    least-conn   ┌────────────┐
            │    Picker    │ ───────────────▶ │  Backend A │
            └──────┬───────┘                 └────────────┘
                   │                            ▲
                   │  ReverseProxy              │ /healthz
                   ▼                            │
            ┌──────────────┐    ticker      ┌───┴────────┐
            │  io.Copy x2  │ ◀──────────────│ HealthChk  │
            └──────────────┘                └────────────┘
```

The data flow is what reviewers look for on a diagram: control plane (health checks) and data plane (request proxying) are *separated*, which is exactly how Envoy, Linkerd, and HAProxy describe their own internals in their docs (see [Envoy's architecture overview](https://www.envoyproxy.io/docs/envoy/latest/intro/architecture)).

## Building It Step by Step

We'll build a runnable Go module. Use Go 1.22+ so you can lean on the standard library's `net/http/httputil` and `slices` package.

### Step 1 — Project skeleton

Create the module:

```bash
mkdir -p goloadb && cd goloadb
go mod init github.com/yourname/goloadb
```

Lay out three files: `main.go` (CLI + lifecycle), `pool.go` (backend pool + picker), `health.go` (active health checks).

### Step 2 — The backend pool and least-connections picker

The picker is the heart of the project. Least-connections routes each new request to the backend currently serving the fewest in-flight connections, which empirically beats round-robin when request duration is variable — see [the Haproxy docs](https://www.haproxy.org/download/1.8/doc/proxy-protocol.txt) on dynamic weighting.

```go
// pool.go
package main

import (
    "sync"
    "sync/atomic"
)

type Backend struct {
    URL       string
    Healthy   atomic.Bool
    Inflight  atomic.Int64
    mu        sync.Mutex
    fails     int
}

type Pool struct {
    backends []*Backend
}

func NewPool(urls []string) *Pool {
    p := &Pool{}
    for _, u := range urls {
        b := &Backend{URL: u}
        b.Healthy.Store(true)
        p.backends = append(p.backends, b)
    }
    return p
}

// Pick returns the healthy backend with the fewest in-flight connections.
// Ties are broken by slice order, giving stable behavior under contention.
func (p *Pool) Pick() *Backend {
    var best *Backend
    for _, b := range p.backends {
        if !b.Healthy.Load() {
            continue
        }
        if best == nil || b.Inflight.Load() < best.Inflight.Load() {
            best = b
        }
    }
    return best
}

func (b *Backend) Acquire() { b.Inflight.Add(1) }
func (b *Backend) Release() { b.Inflight.Add(-1) }
```

Two design notes for the interview conversation. First, `atomic.Int64` makes the picker lock-free on the hot path — important, because every request hits it. Second, draining a backend on shutdown is a one-liner: set `Healthy.Store(false)` and wait for `Inflight` to hit zero. That's the same trick Envoy uses for graceful drain, as documented in the [Envoy lifecycle docs](https://www.envoyproxy.io/docs/envoy/latest/intro/life_of_a_request).

### Step 3 — The active health checker

Active probing is the difference between "balance" and "load balance". Without it, your pool routes traffic to a backend whose container died three restarts ago. The classic design — used by HAProxy and Kubernetes' HTTPGet probes — is a fixed interval with a consecutive-failure threshold before marking unhealthy.

```go
// health.go
package main

import (
    "context"
    "log/slog"
    "net/http"
    "time"
)

func (p *Pool) RunHealthChecks(ctx context.Context, interval time.Duration, threshold int) {
    ticker := time.NewTicker(interval)
    defer ticker.Stop()
    for {
        select {
        case <-ctx.Done():
            return
        case <-ticker.C:
            for _, b := range p.backends {
                go p.check(b, threshold)
            }
        }
    }
}

func (p *Pool) check(b *Backend, threshold int) {
    client := &http.Client{Timeout: 2 * time.Second}
    resp, err := client.Get(b.URL + "/healthz")
    b.mu.Lock()
    defer b.mu.Unlock()
    if err != nil || resp.StatusCode != http.StatusOK {
        b.fails++
        if b.fails >= threshold && b.Healthy.Load() {
            b.Healthy.Store(false)
            slog.Warn("backend marked unhealthy", "url", b.URL, "fails", b.fails)
        }
        return
    }
    b.fails = 0
    if !b.Healthy.Load() {
        b.Healthy.Store(true)
        slog.Info("backend recovered", "url", b.URL)
    }
}
```

The pattern worth highlighting in a write-up: failures are *consecutive*, not a ratio. A single transient timeout shouldn't evict a backend. This matches the semantics of Kubernetes' `failureThreshold` as described in the [Kubernetes probes docs](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/).

### Step 4 — The reverse proxy

We're not using `httputil.ReverseProxy` here on purpose — writing the proxy by hand is where the educational value lives. You'll handle connection management, the `X-Forwarded-For` header, and the all-important `Connection: close` decision on backend failure.

```go
// main.go (excerpt)
func (p *Pool) ServeHTTP(w http.ResponseWriter, r *http.Request) {
    b := p.Pick()
    if b == nil {
        http.Error(w, "no healthy backends", http.StatusServiceUnavailable)
        return
    }
    b.Acquire()
    defer b.Release()

    // Hop-by-hop headers we must not forward (RFC 7230 §6.1)
    // https://www.rfc-editor.org/rfc/rfc7230#section-6.1
    r.Header.Del("Connection")
    r.Header.Del("Keep-Alive")
    r.Header.Del("Proxy-Authenticate")
    r.Header.Del("Proxy-Authorization")
    r.Header.Del("Te")
    r.Header.Del("Trailers")
    r.Header.Del("Transfer-Encoding")
    r.Header.Del("Upgrade")
    r.Header.Set("X-Forwarded-For", clientIP(r))

    client := &http.Client{
        Timeout: 10 * time.Second,
    }
    req, err := http.NewRequestWithContext(r.Context(), r.Method, b.URL+r.RequestURI, r.Body)
    if err != nil {
        http.Error(w, err.Error(), http.StatusBadGateway)
        return
    }
    req.Header = r.Header.Clone()

    resp, err := client.Do(req)
    if err != nil {
        http.Error(w, "upstream error", http.StatusBadGateway)
        return
    }
    defer resp.Body.Close()

    for k, vs := range resp.Header {
        for _, v := range vs {
            w.Header().Add(k, v)
        }
    }
    w.WriteHeader(resp.StatusCode)
    io.Copy(w, resp.Body)
}
```

This is roughly 50 lines and exercises the same primitives a production proxy does. Mentioning RFC 7230 in your README is the kind of detail that lands well in an interview.

### Step 5 — Lifecycle, CLI, graceful shutdown

```go
func main() {
    addr := flag.String("addr", ":8080", "listen address")
    upstreams := flag.String("upstreams", "http://127.0.0.1:9001,http://127.0.0.1:9002,http://127.0.0.1:9003", "comma-separated backends")
    flag.Parse()

    pool := NewPool(strings.Split(*upstreams, ","))

    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()
    go pool.RunHealthChecks(ctx, 2*time.Second, 3)

    srv := &http.Server{
        Addr:    *addr,
        Handler: pool,
        ReadHeaderTimeout: 5 * time.Second,
    }

    go func() {
        log.Printf("goloadb listening on %s", *addr)
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatal(err)
        }
    }()

    stop := make(chan os.Signal, 1)
    signal.Notify(stop, os.Interrupt, syscall.SIGTERM)
    <-stop

    log.Println("shutting down, draining backends...")
    for _, b := range pool.backends {
        b.Healthy.Store(false)
    }
    shutdownCtx, c2 := context.WithTimeout(context.Background(), 15*time.Second)
    defer c2()
    srv.Shutdown(shutdownCtx)
}
```

That's the whole thing. ~250 lines of code, but every line is doing something you'd be asked about in a systems interview.

## Running and Testing It

You'll want at upstream. A tiny echo server is enough to prove routing works:

```go
// echo.go (dev only)
package main

import (
    "fmt"
    "net/http"
    "os"
)

func main() {
    port := os.Args[1]
    name := os.Args[2]
    http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(200)
    })
    http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
        fmt.Fprintf(w, "hello from %s\n", name)
    })
    http.ListenAndServe(":"+port, nil)
}
```

Spin up three of them on different ports, each with a different `--name`:

```bash
# in three terminals
go run echo.go 9001 alpha
go run echo.go 9002 beta
go run echo.go 9003 gamma

# in a fourth terminal
go run . -addr :8080 -upstreams http://127.0.0.1:9001,http://127.0.0.1:9002,http://127.0.0.1:9003
```

Now prove routing and failure handling:

```bash
# Send 100 requests and watch distribution skew with least-conn
hey -n 1000 -c 50 http://127.0.0.1:8080/

# Kill the 'alpha' backend. Within ~6s (3 × 2s) it should be evicted
# and traffic should land on beta/gamma only.
```

Adding a small integration test cements the behavior. Here's a `health_test.go` worth shipping:

```go
func TestHealthCheckEvicts(t *testing.T) {
    pool := NewPool([]string{"http://127.0.0.1:65530"}) // dead port
    pool.check(pool.backends[0], 1)
    if pool.backends[0].Healthy.Load() {
        t.Fatal("expected unhealthy")
    }
    if pool.Pick() != nil {
        t.Fatal("expected no pickable backend")
    }
}
```

For load testing, [wrk](https://github.com/wg/wrk) and [k6](https://k6.io) both expose the latency distribution you need to claim your balancer "added less than 1ms p99". Quote numbers in your README — that's what interviewers actually read first.

## Extending It: Your Roadmap to Senior-Level

This is where most candidates stop. The interview-winning move is to ship at least two of these upgrades, each one chosen because it tells a different story.

- **Weighted least-connections + sticky sessions.** Add per-backend weights and a cookie-based affinity map. Reason: demonstrates you can reason about stateful routing without violating HTTP semantics — the same problem solved by [Envoy's consistent hashing](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/load_balancing/load_balancers) load balancer.
- **TLS termination with `crypto/tls`.** Listen on `:443`, serve a cert from Let's Encrypt, and forward plaintext upstream. Reason: a load balancer that doesn't speak TLS is a toy; SRE roles especially expect you to have configured one at least once.
- **Prometheus metrics endpoint.** Count requests, errors, in-flight per backend, and p99 latency via [the `prometheus/client_golang` library](https://github.com/prometheus/client_golang). Reason: "show me a Grafana dashboard for your project" is a real interview question and observability is half the answer.
- **Configuration file + hot reload.** Move backends into YAML, watch the file with `fsnotify`, and reparse on change. Reason: every production LB supports reload — it's how you swap backends without dropping traffic, and it forces you to design a config-validation pipeline.
- **Chaos testing with Toxiproxy.** Wrap backends in [Toxiproxy](https://github.com/Shopify/toxiproxy) and inject 200ms latency or packet loss. Reason: proves your health checker and timeouts are actually correct, not just "works on my machine".
- **Layer 4 TCP mode.** Skip the HTTP parsing entirely, hash on source IP, and forward raw bytes. Reason: shows you understand the L4/L7 tradeoff that defines the difference between HAProxy and NGINX in real deployments.

Pick two, ship them well, and write a blog post per upgrade linking back to this one. That's a six-month portfolio arc that ends with you being able to talk about load balancing at the level of a [Google SRE chapter](https://sre.google/sre-book/addressing-cascading-failures/) on cascading failures.

## Key Takeaways

- A load balancer is one of the densest CV-signal projects you can ship — networking, concurrency, failure handling, and observability in a few hundred lines of Go.
- Least-connections routing with atomic counters is the sweet spot: more interesting than round-robin, simpler than consistent hashing, and enough to start a real interview conversation.
- Health checks are not optional and not a footnote — they're half the system. Get the consecutive-failure threshold and the probe timeout right.
- Production polish (graceful shutdown, structured logs, Prometheus metrics, config hot-reload) is what separates a tutorial from something you'd defend in a staff interview.
- The roadmap above — TLS, sticky sessions, chaos testing, L4 mode — is a six-month path to "I've shipped a real proxy" rather than "I've read a tutorial".

## Further Reading

Primary sources to study next, in roughly the order I'd recommend:

- [RFC 7230 — HTTP/1.1: Message Syntax and Routing](https://www.rfc-editor.org/rfc/rfc7230) — the canonical reference for hop-by-hop headers and message forwarding, the rules your proxy must respect.
- [RFC 7231 — HTTP/1.1: Semantics and Content](https://www.rfc-editor.org/rfc/rfc7231) — covers the methods and status codes your backend decisions need to understand.
- [HAProxy Documentation — Load Balancing Algorithms](https://www.haproxy.org/download/1.8/doc/load-balancing.txt) — deep dive into least-conn, weighted least-conn, and the source-IP hashing variants you'll want to implement next.
- [Envoy Architecture Overview](https://www.envoyproxy.io/docs/envoy/latest/intro/architecture) — how a modern L7 proxy is decomposed into listeners, filters, clusters, and health checking. Re-reading this after building your own version is genuinely eye-opening.
- [Kubernetes Liveness, Readiness, and Startup Probes](https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/) — the operational reference for what "active health check" actually means in a production scheduler.
- [Google SRE Book — Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/) — the best plain-language argument for why your health-check thresholds, timeouts, and load-shedding logic matter more than your routing algorithm.
- [NGINX Architecture & Load Balancing](https://docs.nginx.com/nginx/admin-guide/load-balancer/http-load-balancer/) — the production incumbent. Read this last; you'll understand roughly half of it, and that half will teach you what your next six months should look like.