---
title: "Build a Production-Ready Feature Flag Service for Your Portfolio"
date: "2026-09-11T11:00:51.421"
draft: false
tags: ["go", "redis", "devops", "fullstack", "side-project"]
description: "Hands-on guide to building a feature flag service from scratch, with real code, architecture diagrams, and production patterns that signal systems skills to hiring managers."
summary: "Build a local-first feature flag service in Go with Redis backing, React UI, and observability — a concrete portfolio project that demonstrates real systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-build-a-production-ready-feature-flag-service-for-your-portfolio.svg"
  alt: "Feature flag service architecture diagram with Go backend, Redis cache, and React frontend"
  caption: ""
  relative: false
---

> **TL;DR** — Build a local-first feature flag service in Go with Redis backing and a React UI in under an afternoon. You'll practice HTTP servers, distributed caching, feature rollout logic, and observability — skills that hiring managers see as "production-ready" rather than toy projects.

Building a personal portfolio project that actually signals real systems skill is harder than it looks. Most guides stop at "create a to-do app" and leave you with code that works on localhost but nowhere else. Hiring engineers want to see that you can design for rollout, observability, and failure — not just syntax. In this guide, we'll build a feature flag service from scratch using Go for the backend, Redis for distributed state, and a minimal React frontend. Along the way you'll wire up HTTP routing, health checks, a simple UI, and production patterns like feature rollout percentages, time-based flags, and metrics emission. By the end you'll have a runnable, extensible service you can point to in interviews, point to in your GitHub, and extend into a real system.

## Why This Project Stands Out on a CV

A feature flag service sits at the intersection of backend services, distributed systems, and product engineering. When you list this project, you're signaling several things to recruiters and hiring managers:

- **HTTP services & API design**: You understand routing, request validation, and versioned endpoints. Go's `net/http` or a lightweight router like `gorilla/mux` gives you a solid foundation.
- **Distributed state & caching**: You've dealt with cache invalidation, consistency models, and the trade-offs of a Redis-backed store versus a pure in-memory map.
- **Feature rollout logic**: You can implement percentage-based rollouts, user-segment targeting, and time-windowed flags — the kind of logic that powers real product experiments.
- **Observability by default**: You've added health endpoints, structured logging, and metric counters that a team can monitor.
- **Full-stack awareness**: A minimal React UI shows you can wire a frontend to a backend API, handle loading states, and render dynamic data.

Roles that particularly value this signal: backend engineers moving into platforms, SREs evaluating feature-flag infrastructure, and product-focused engineers who need to ship experiments fast. Unlike a generic CRUD app, this project has moving parts that mirror a micro-service you'd maintain at scale. As [Martin Fowler describes](https://martinfowler.com/bliki/FeatureFlag.html) the feature-flag pattern, the real value isn't the flag itself but the infrastructure around safe rollouts and experiments.

## Architecture Overview

The system has four core components, arranged in a simple client-server pattern:

- **Go backend** (`/flags` endpoint): Handles read/write of feature flags, evaluates rollout rules against a user context, and serves flags over HTTP. Uses Redis as the backing store for persistence and sharding.
- **Redis**: Stores the canonical flag state. Key pattern: `flag:{key}` -> JSON blob of `{default, enabled, rollout_percentage, since, until}`. Clients connect via `redis:6379`; the Go client uses a connection pool with retry-on-failure.
- **React frontend**: A single-page app that calls the Go `/flags/:key` endpoint, shows the resolved boolean, and displays the rollout reason (e.g., "50% rollout", "user in segment", "always on").
- **Health & metrics endpoint** (`/ready`, `/live`): Standard Kubernetes-probe-compatible endpoints that expose flag cache hit rate and Redis round-trip latency.

```text
+--------+     HTTPS/HTTP     +--------+     RESP       +--------+
| React  |  <------------->  | Go API | <----------> | Redis  |
| UI     |     /flags/:key    | (Go)   |   pub/sub    | (6379) |
+--------+                  +--------+              +--------+
        ^                              ^
        |                              |
        |          /health, /metrics  |
        +------------------------------+
```

## Building It Step by Step

### Step 1: Scaffold the Go module and dependencies

```bash
go mod init github.com/yourhandle/flagship
go get github.com/redis/go-redis/v9
go get github.com/gorilla/mux
```

### Step 2: Define the flag schema and in-memory store

```go
package main

import (
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/redis/go-redis/v9"
	"github.com/gorilla/mux"
)

type Flag struct {
	Key        string    `json:"key"`
	Default    bool      `json:"default"`
	Enabled    bool      `json:"enabled"`
	RolloutPct int       `json:"rollout_pct"`
	Since      time.Time `json:"since,omitempty"`
	Until      time.Time `json:"until,omitempty"`
}

type Evaluator struct {
	redis  *redis.Client
	cache  map[string]*Flag
	mu     sync.RWMutex
}

func NewEvaluator(r *redis.Client) *Evaluator {
	return &Evaluator{
		redis: r,
		cache: make(map[string]*Flag),
	}
}
```

### Step 3: Implement the flag-evaluation logic

The core of

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
