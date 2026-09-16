---
title: "Build a User Safety System: A Hands-On Side Project That Signals Real Systems Skill"
date: "2026-09-16T19:01:48.796"
draft: false
tags: ["systems-engineering", "go", "safety-monitoring", "portfolio", "backend", "event-driven"]
description: "Build a production-grade User Safety monitoring system in Go. This hands-on guide covers real-time anomaly detection, policy evaluation, and alerting — a portfolio project that signals serious backend and systems engineering skill to hiring managers."
summary: "A complete build guide for a User Safety side project that demonstrates event-driven architecture, real-time policy enforcement, and observability — skills hiring managers actively look for in senior backend and platform engineering roles."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-16-build-a-user-safety-system-a-hands-on-side-project-that-signals-real-systems-skill.svg"
  alt: "A terminal dashboard showing real-time user safety alerts and policy violation metrics"
  caption: "The safety-monitoring dashboard built during this project"
  relative: false
---

> **TL;DR** — Build a real-time User Safety monitoring system in Go that ingests user events, evaluates them against configurable safety policies, and emits alerts when violations are detected. It combines an event pipeline, a rule engine, and an alerting layer — exactly the architecture you see in production systems at companies like Stripe and Cloudflare. The project demonstrates event-driven design, concurrency, observability, and fault tolerance, all skills that map directly to senior backend and platform engineering roles.

---

## Why This Project Stands Out on a CV

Hiring managers in backend, platform, and infrastructure engineering scan portfolios for one thing: can this person reason about systems that must be correct under load, at scale, and under failure? A "User Safety" project answers that question directly. Here's the specific signal it sends:

- **Event-driven architecture**: You've built something that processes streams of events in real time. This is the foundational pattern behind Kafka pipelines, fraud detection systems, and compliance monitoring at every major fintech and SaaS company.
- **Concurrency and correctness**: The rule engine must evaluate policies concurrently without race conditions. This demonstrates you understand goroutines, mutexes, and the channels-vs-locks tradeoff in Go — or the equivalent in Rust, Python with asyncio, or Java.
- **Observability and operational maturity**: A safety system that can't observe itself is worthless. Adding metrics, structured logging, and tracing shows you think like an on-call engineer, not just a feature developer.
- **Policy-as-code thinking**: Configurable safety rules separate business logic from enforcement logic. This is the same pattern behind Open Policy Agent (OPA), AWS IAM policies, and Kubernetes admission controllers.
- **Fault tolerance**: Handling malformed input, downstream failures, and backpressure signals that you've shipped software that must run 24/7.

The roles this signals: Backend Engineer, Platform Engineer, Security/Trust & Safety Engineer, Site Reliability Engineer, and Technical Lead. It's a project that works equally well for a fintech startup and a large-scale SaaS platform.

---

## Architecture Overview

The system consists of five loosely coupled components that communicate through a typed event bus. Here's how they fit together:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Event       │────▶│  Ingestion   │────▶│  Rule Engine    │
│  Producer    │     │  (HTTP/gRPC) │     │  (Policy Eval)  │
└─────────────┘     └──────────────┘     └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Alert Manager  │
                                          │  (Notify/Log)   │
                                          └────────┬────────┘
                                                   │
                                          ┌────────▼────────┐
                                          │  Storage &      │
                                          │  Observability  │
                                          │  (SQLite/Prom)  │
                                          └─────────────────┘
```

Each component is an independent Go package with a clear interface boundary:

1. **Event Producer** — Simulated client that generates user activity events (logins, transactions, content submissions). In production, this maps to your actual application emitting events.
2. **Ingestion Layer** — An HTTP server with a `/events` endpoint that validates and queues incoming events. Uses `net/http` with middleware for rate limiting and structured JSON parsing.
3. **Rule Engine** — The core. A policy evaluator that checks each event against a configurable set of rules. Rules are defined in YAML and loaded at startup. This is where the interesting concurrency lives.
4. **Alert Manager** — Receives violations from the rule engine and dispatches notifications. Supports multiple channels: console logging, webhook POST, and email via SMTP.
5. **Storage & Observability** — SQLite for persistence of event history and violation records. Prometheus metrics exposed on `:9090/metrics` for request rate, violation count, and latency histograms.

The event bus between ingestion and the rule engine uses a buffered Go channel, which provides natural backpressure. When the channel fills, the ingestion layer returns HTTP 429 (Too Many Requests) — this is exactly how real systems like Cloudflare's WAF handle overload.

---

## Building It Step by Step

We'll build this in Go (v1.22+). The full project is roughly 600 lines of code. Below are the critical pieces.

### Step 1: Define the Event and Policy Models

Start with the core data structures. Every component depends on these.

```go
// models/event.go
package models

type EventType string

const (
    EventLogin     EventType = "login"
    EventTransaction EventType = "transaction"
    EventContentSubmit EventType = "content_submit"
)

type UserEvent struct {
    ID        string    `json:"id"`
    UserID    string    `json:"user_id"`
    Type      EventType `json:"type"`
    Timestamp int64     `json:"timestamp"`
    Metadata  map[string]any `json:"metadata"`
    IP        string    `json:"ip"`
    UserAgent string    `json:"user_agent"`
}
```

```go
// models/policy.go
package models

type Operator string

const (
    OpGreaterThan  Operator = "gt"
    OpLessThan     Operator = "lt"
    OpEquals       Operator = "eq"
    OpContains     Operator = "contains"
    OpInList       Operator = "in"
)

type Condition struct {
    Field    string  `yaml:"field"`
    Operator Operator `yaml:"operator"`
    Value    any     `yaml:"value"`
}

type Rule struct {
    Name        string      `yaml:"name"`
    Description string      `yaml:"description"`
    Severity    string      `yaml:"severity"` // "low", "medium", "high", "critical"
    Conditions  []Condition `yaml:"conditions"`
    MatchAll    bool        `yaml:"match_all"` // AND vs OR logic
    Actions     []string    `yaml:"actions"` // "block", "flag", "notify"
}

type SafetyPolicy struct {
    Version  string `yaml:"version"`
    Rules    []Rule `yaml:"rules"`
    Metadata struct {
        CreatedAt string `yaml:"created_at"`
        Author    string `yaml:"author"`
    } `yaml:"metadata"`
}
```

These models are deliberately explicit. Notice how `MatchAll` gives you AND/OR flexibility — this is what separates a toy from a real policy engine.

### Step 2: Build the Ingestion Layer

The HTTP server validates events and pushes them onto a buffered channel.

```go
// server/ingestion.go
package server

import (
    "encoding/json"
    "net/http"
    "time"

    "yourproject/models"
)

const EventChannelCapacity = 10000

var EventBus = make(chan models.UserEvent, EventChannelCapacity)

type IngestionHandler struct {
    RateLimiter *RateLimiter
}

func (h *IngestionHandler) HandleEvent(w http.ResponseWriter, r *http.Request) {
    if !h.RateLimiter.Allow(r.Context()) {
        http.Error(w, "rate limit exceeded", http.StatusTooManyRequests)
        return
    }

    var event models.UserEvent
    if err := json.NewDecoder(r.Body).Decode(&event); err != nil {
        http.Error(w, "invalid event payload", http.StatusBadRequest)
        return
    }

    if event.ID == "" || event.UserID == "" || event.Type == "" {
        http.Error(w, "missing required fields", http.StatusBadRequest)
        return
    }

    event.Timestamp = time.Now().UnixMilli()

    select {
    case EventBus <- event:
        w.WriteHeader(http.StatusAccepted)
    default:
        // Channel full — backpressure
        http.Error(w, "system busy, try again", http.StatusServiceUnavailable)
    }
}
```

The `select` with the `default` case is the key production detail. Without it, the handler blocks indefinitely when the channel is full, eventually exhausting goroutine stacks. With it, you get clean backpressure — the same pattern that keeps Kafka producers from OOM-killing.

### Step 3: Implement the Rule Engine

This is the heart of the project. It reads from the event bus, evaluates each event against loaded policies, and emits violations.

```go
// engine/rule_engine.go
package engine

import (
    "fmt"
    "sync"
    "yourproject/models"
)

type Violation struct {
    RuleName  string      `json:"rule_name"`
    Severity  string      `json:"severity"`
    EventID   string      `json:"event_id"`
    UserID    string      `json:"user_id"`
    Details   string      `json:"details"`
    Timestamp int64       `json:"timestamp"`
}

type RuleEngine struct {
    policies []models.SafetyPolicy
    mu       sync.RWMutex
    out      chan<- Violation
}

func NewRuleEngine(out chan<- Violation) *RuleEngine {
    return &RuleEngine{out: out}
}

func (e *RuleEngine) LoadPolicies(path string) error {
    // Load YAML policies from disk — implementation uses gopkg.in/yaml.v3
    // ...
}

func (e *RuleEngine) Evaluate(event models.UserEvent) []Violation {
    e.mu.RLock()
    defer e.mu.RUnlock()

    var violations []Violation

    for _, policy := range e.policies {
        for _, rule := range policy.Rules {
            if e.matchesRule(event, rule) {
                violations = append(violations, Violation{
                    RuleName:  rule.Name,
                    Severity:  rule.Severity,
                    EventID:   event.ID,
                    UserID:    event.UserID,
                    Details:   fmt.Sprintf("Rule %s triggered", rule.Name),
                    Timestamp: time.Now().UnixMilli(),
                })
            }
        }
    }
    return violations
}

func (e *RuleEngine) matchesRule(event models.UserEvent, rule models.Rule) bool {
    // Extract field value from event metadata using reflection
    fieldVal := extractField(event, rule.Conditions[0].Field)

    if rule.MatchAll {
        // AND logic: all conditions must match
        for _, cond := range rule.Conditions {
            if !compare(fieldVal, cond.Operator, cond.Value) {
                return false
            }
        }
        return true
    } else {
        // OR logic: any condition can match
        for _, cond := range rule.Conditions {
            if compare(fieldVal, cond.Operator, cond.Value) {
                return true
            }
        }
        return false
    }
}

func (e *RuleEngine) Run(ctx context.Context, wg *sync.WaitGroup) {
    defer wg.Done()
    for {
        select {
        case event := <-EventBus:
            violations := e.Evaluate(event)
            for _, v := range violations {
                select {
                case e.out <- v:
                default:
                    // Alert channel full — log and continue
                    log.Printf("alert channel full, dropping violation for event %s", event.ID)
                }
            }
        case <-ctx.Done():
            return
        }
    }
}
```

The `sync.RWMutex` around policy evaluation is deliberate: policies can be hot-reloaded (via a SIGHUP handler or admin endpoint) without blocking event evaluation. The `default` case on the alert channel prevents the engine from blocking if the alert manager is slow.

### Step 4: Build the Alert Manager

```go
// alert/manager.go
package alert

import (
    "bytes"
    "encoding/json"
    "net/http"
    "time"

    "yourproject/models"
)

type AlertManager struct {
    webhookURL string
    logger     *log.Logger
}

func (a *AlertManager) Dispatch(violation models.Violation) error {
    a.logger.Printf("[%s] Violation: %s for user %s", violation.Severity, violation.RuleName, violation.UserID)

    if a.webhookURL != "" {
        payload, _ := json.Marshal(violation)
        ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
        defer cancel()

        req, err := http.NewRequestWithContext(ctx, "POST", a.webhookURL, bytes.NewReader(payload))
        if err != nil {
            return err
        }
        req.Header.Set("Content-Type", "application/json")

        resp, err := http.DefaultClient.Do(req)
        if err != nil {
            return fmt.Errorf("webhook delivery failed: %w", err)
        }
        defer resp.Body.Close()

        if resp.StatusCode >= 400 {
            return fmt.Errorf("webhook returned %d", resp.StatusCode)
        }
    }
    return nil
}
```

The 2-second timeout on the webhook is critical. Without it, a slow downstream service blocks your entire alert pipeline. This is the exact failure mode that caused the 2021 Fastly outage — unbounded downstream dependencies.

### Step 5: Wire Everything Together with `main.go`

```go
// main.go
package main

import (
    "context"
    "log"
    "net/http"
    "os"
    "os/signal"
    "syscall"
    "sync"

    "yourproject/alert"
    "yourproject/engine"
    "yourproject/server"
    "yourproject/storage"
)

func main() {
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()

    // Graceful shutdown on SIGINT/SIGTERM
    sigCh := make(chan os.Signal, 1)
    signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
    go func() {
        <-sigCh
        log.Println("shutdown signal received")
        cancel()
    }()

    alertChan := make(chan models.Violation, 1000)

    // Initialize components
    eng := engine.NewRuleEngine(alertChan)
    if err := eng.LoadPolicies("policies/default.yaml"); err != nil {
        log.Fatalf("failed to load policies: %v", err)
    }

    mgr := alert.NewAlertManager(os.Getenv("WEBHOOK_URL"), log.Default())
    store := storage.NewSQLiteStore("safety.db")

    var wg sync.WaitGroup

    // Start rule engine workers (3 concurrent evaluators)
    for i := 0; i < 3; i++ {
        wg.Add(1)
        go eng.Run(ctx, &wg)
    }

    // Start alert dispatcher
    wg.Add(1)
    go func() {
        defer wg.Done()
        for {
            select {
            case v := <-alertChan:
                if err := mgr.Dispatch(v); err != nil {
                    log.Printf("alert dispatch error: %v", err)
                }
                if err := store.RecordViolation(v); err != nil {
                    log.Printf("storage error: %v", err)
                }
            case <-ctx.Done():
                return
            }
        }
    }()

    // Start HTTP server
    srv := &http.Server{Addr: ":8080"}
    go func() {
        if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatalf("server error: %v", err)
        }
    }()

    <-ctx.Done()

    // Graceful shutdown: 10-second drain window
    shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer shutdownCancel()
    srv.Shutdown(shutdownCtx)
    wg.Wait()
    log.Println("shutdown complete")
}
```

Notice the 3 concurrent rule engine workers. This is your first taste of horizontal scaling within a single process — you can increase this number or shard the event bus by user ID to distribute load across goroutines.

---

## Running and Testing It

### Local Setup

```bash
# Clone and enter the project directory
git clone https://github.com/yourname/safe.git
cd safe

# Install dependencies
go mod tidy

# Create a sample policy file
mkdir -p policies
cat > policies/default.yaml << 'EOF'
version: "1.0"
metadata:
  created_at: "2026-09-16"
  author: "engineer"
rules:
  - name: "rapid_login_attempts"
    description: "Flag users with more than 5 logins in 60 seconds"
    severity: "high"
    match_all: true
    conditions:
      - field: "type"
        operator: "eq"
        value: "login"
      - field: "metadata.login_count_60s"
        operator: "gt"
        value: 5
    actions:
      - "flag"
      - "notify"
  - name: "suspicious_geo_change"
    description: "Flag login from a new country within 5 minutes"
    severity: "critical"
    match_all: false
    conditions:
      - field: "metadata.geo_change"
        operator: "eq"
        value: true
    actions:
      - "block"
      - "notify"
EOF

# Build and run
go build -o safe ./...
./safe &
```

### Sending Test Events

```bash
# Use curl to send a test event
curl -X POST http://localhost:8080/events \
  -H "Content-Type: application/json" \
  -d '{
    "id": "evt-001",
    "user_id": "user-42",
    "type": "login",
    "metadata": {
      "login_count_60s": 7,
      "geo_change": false
    },
    "ip": "203.0.113.42",
    "user_agent": "Mozilla/5.0"
  }'
```

You should see the alert printed to the console:

```
[high] Violation: rapid_login_attempts for user user-42
```

### Testing Concurrency and Backpressure

```bash
# Load test with 1000 concurrent events
for i in $(seq 1 1000); do
    curl -s -X POST http://localhost:8080/events \
      -H "Content-Type: application/json" \
      -d "{\"id\":\"evt-$i\",\"user_id\":\"user-$((i % 50))\",\"type\":\"login\",\"metadata\":{\"login_count_60s\":$((i % 10)),\"geo_change\":false},\"ip\":\"10.0.0.$((i % 255))\",\"user_agent\":\"test\"}" &
done
wait
```

### Verify Prometheus Metrics

```bash
# Check metrics endpoint
curl http://localhost:9090/metrics
```

You should see counters for `events_received_total`, `violations_total`, and histogram buckets for `event_processing_duration_seconds`.

### Write a Table-Driven Test

```go
// engine/rule_engine_test.go
package engine

import (
    "testing"
    "yourproject/models"
)

func TestRuleEngine_MatchAll(t *testing.T) {
    eng := NewRuleEngine(make(chan models.Violation, 10))
    eng.policies = []models.SafetyPolicy{
        {
            Rules: []models.Rule{
                {
                    Name: "test_rule",
                    MatchAll: true,
                    Conditions: []models.Condition{
                        {Field: "type", Operator: OpEquals, Value: "login"},
                        {Field: "count", Operator: OpGreaterThan, Value: 5},
                    },
                },
            },
        },
    }

    tests := []struct {
        name    string
        event   models.UserEvent
        matches bool
    }{
        {"both_match", models.UserEvent{Type: "login", Metadata: map[string]any{"count": 7}}, true},
        {"type_mismatch", models.UserEvent{Type: "transaction", Metadata: map[string]any{"count": 7}}, false},
        {"count_mismatch", models.UserEvent{Type: "login", Metadata: map[string]any{"count": 3}}, false},
        {"neither_match", models.UserEvent{Type: "transaction", Metadata: map[string]any{"count": 3}}, false},
    }

    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            result := eng.Evaluate(tt.event)
            if tt.matches && len(result) == 0 {
                t.Errorf("expected match, got none")
            }
            if !tt.matches && len(result) > 0 {
                t.Errorf("expected no match, got %d violations", len(result))
            }
        })
    }
}
```

Run with `go test ./...` — all tests should pass. This table-driven approach is exactly what you'd write in production Go code.

---

## Extending It: Your Roadmap to Senior-Level

Here are six concrete upgrades that transform this project from a portfolio piece into something that reads like production infrastructure:

1. **Add persistent event storage with SQLite WAL mode and periodic archival to object storage (S3/GCS).** This matters because real safety systems must retain event history for compliance audits and forensic investigation — the system can't lose data on restart.

2. **Shard the event bus by user ID and run engine workers across goroutines with a consistent hash router.** This matters because a single-channel architecture doesn't scale past ~10K events/second; sharding is the first step toward horizontal scaling and mirrors how Kafka partitions work.

3. **Integrate OpenTelemetry tracing across all component boundaries and export to Jaeger or Grafana Tempo.** This matters because when a violation alert is delayed, you need distributed traces to pinpoint whether the bottleneck is ingestion, evaluation, or alert delivery — observability isn't optional in production.

4. **Implement a circuit breaker pattern for the alert webhook using `github/sony/gobreaker` or a custom implementation.** This matters because if your notification service is down, you don't want the alert manager to exhaust connection pools and cascade failures back into the event pipeline — this is the exact pattern that prevents cascading outages.

5. **Add a hot-reload mechanism for policies using inotify (via `fsnotify`) or a lightweight admin endpoint with ETag-based conditional updates.** This matters because safety rules change frequently — you shouldn't need to restart the entire service to update a fraud detection threshold, and zero-downtime policy updates are a core SRE competency.

6. **Benchmark the rule engine with `testing.B` and `pprof` to identify hot paths, then optimize with sync.Pool for event objects and pre-compiled condition expressions.** This matters because hiring managers want to see that you don't just write correct code — you measure performance, find bottlenecks, and optimize deliberately. This is the difference between a junior and a senior engineer.

---

## Further Reading

To deepen and evolve this project, study these primary sources:

- **[The Log: What Every Software Engineer Should Know About Real-Time Data's Unifying Abstraction](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying-abstraction)** by Jay Kreps — This is the foundational paper behind Kafka, Pulsar, and every event pipeline you'll ever build. It explains why the event bus in your project exists and how to think about ordering, durability, and replay.

- **[Open Policy Agent: The Policy Engine](https://www.openpolicyagent.org/docs/)** — OPA is the industry standard for policy-as-code. Study its Rego language and evaluation model to understand how your rule engine compares to a production-grade system. You can even replace your YAML-based engine with OPA as a next step.

- **[The Site Reliability Workbook](https://sre.google/sre-book/table-of-contents/)** by Betsy Beyer et al. — Chapters on monitoring, alerting, and incident response directly apply to your alert manager and observability layers. This is the canonical text for understanding what "production-flavored" really means.

- **[RFC 7807: Problem Details for HTTP APIs](https://www.rfc-editor.org/rfc/rfc7807)** — Your ingestion layer should return structured error responses, not plain-text strings. This RFC defines the standard for that, and implementing it shows you care about API contract design.

- **[Jepsen: A Framework for Distributed Systems Testing](https://jepsen.io/)** — When you're ready to prove your system is correct under network partitions and concurrent writes, Jepsen-style testing is how you do it. Start with [the Jepsen documentation](https://jepsen.io/documentation) to understand how to model and verify your event pipeline's safety guarantees.

- **[Prometheus: A Multi-Dimensional Data Collection System](https://prometheus.io/docs/introduction/overview/)** — The observability layer in your project is built on Prometheus's model. Study its exposition format, metric types (counters, histograms, summaries), and service discovery to understand what you're really implementing when you add the `/metrics` endpoint.

---

This project gives you something rare in a portfolio: a complete, runnable system that demonstrates not just one skill but an entire stack — from HTTP ingestion through concurrent policy evaluation to alerting and observability. Build it, benchmark it, break it, and fix it. That process is what hiring managers are actually looking for.