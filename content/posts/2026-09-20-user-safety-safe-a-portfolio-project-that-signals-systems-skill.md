

---
title: "User Safety: Safe — A Portfolio Project That Signals Systems Skill"
date: "2026-09-20T01:01:04.592"
draft: false
tags: ["user-safety", "go", "microservice", "portfolio", "systems-design"]
description: "Build a user safety microservice in Go that validates content, enforces rate limits, and scales horizontally — a portfolio project proving you can ship real systems."
summary: "Build a user safety microservice in Go that validates content, enforces rate limits, and scales horizontally — a portfolio project proving you can ship real systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-user-safety-safe-a-portfolio-project-that-signals-systems-skill.svg"
  alt: "A dashboard showing user safety metrics"
  caption: ""
  relative: false
---

> **TL;DR** — You'll build a runnable Go microservice that validates user-generated content against safety rules, enforces per-user rate limiting, and exposes a clean REST API. It demonstrates systems engineering skills — concurrency, API design, observability, and scalability — that hiring managers look for in backend and platform roles.

In a crowded job market, your portfolio needs to do more than list languages. It needs to show you can design, build, and operate systems that handle real load. **User Safety: Safe** is a compact but production-flavored microservice that does exactly that. It validates user-submitted content for safety, prevents abuse through rate limiting, and is structured to scale. In this guide, you'll build it from scratch in Go, with runnable code, tests, and a clear path to production hardening.

## Why This Project Stands Out on a CV

This project signals several specific skills that hiring managers value for backend, platform, and SRE roles:

- **Production-grade backend development**: You'll build a RESTful API in Go, handling JSON serialization, HTTP status codes, and error handling with the standard library — no frameworks masking the details.
- **Concurrency and systems design**: Go's goroutines and channels are used for rate limiting and concurrent validation, demonstrating you understand shared state and synchronization.
- **Security and abuse prevention**: Implementing a content validator and rate limiter shows you think about trust boundaries and denial-of-service vectors.
- **Observability**: You'll add structured logging and Prometheus metrics, which are critical for debugging and alerting in production.
- **Testing culture**: Writing unit and integration tests proves you care about reliability, not just shipping features.
- **DevOps readiness**: Containerizing the service with Docker shows you can deploy and operate it in a real environment.

Roles this project directly supports: **Backend Engineer**, **Platform Engineer**, **Site Reliability Engineer**, and **Full-Stack Engineer** with a systems focus. It gives you a concrete artifact to discuss in interviews — you can walk through your rate limiter design, your validation pipeline, and how you'd scale it to 10k requests per second.

## Architecture Overview

The service is a single binary with clear separation of concerns:

```
+-------------------+     +-------------------+     +-------------------+
|   HTTP Client     | --> |   API Server      | --> |   Content Validator|
+-------------------+     +-------------------+     +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   Rate Limiter    |
                         +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   Logger/Metrics  |
                         +-------------------+
```

- **API Server** (`net/http` with `ServeMux`): Routes requests, decodes JSON, writes responses. Timeout-aware to prevent slow clients.
- **Content Validator**: Rule-based engine that checks for profanity, length limits, and spam patterns. Easily extensible with new rules.
- **Rate Limiter**: In-memory sliding window limiter per user, with configurable limits and windows. Later replaceable with Redis for distributed deployments.
- **Observability**: Structured logging via `zap` and Prometheus metrics via `prometheus/client_golang`. Exposes a `/metrics` endpoint.
- **Storage**: Initially in-memory; later PostgreSQL for persistence and analytics.

All components are pure Go standard library, with only two third-party dependencies: `zap` for logging and `prometheus/client_golang` for metrics. This keeps the build fast and the code transparent.

## Building It Step by Step

### Step 1: Initialize the project

```bash
mkdir user-safety-safe
cd user-safety-safe
go mod init user-safety-safe
```

### Step 2: Create the main entry point

`main.go` wires everything together and starts the HTTP server:

```go
package main

import (
	"log"
	"net/http"
	"time"

	"user-safety-safe/handler"
	"user-safety-safe/ratelimit"
	"user-safety-safe/validator"
)

func main() {
	// Initialize rate limiter: 10 requests per minute per user
	rl := ratelimit.NewRateLimiter(10, time.Minute)

	// Initialize validator with default rules
	v := validator.NewValidator()

	// Setup handler
	h := handler.NewHandler(v, rl)

	// Register routes
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/content", h.ValidateContent)
	mux.HandleFunc("GET /health", h.HealthCheck)

	// Start server with production timeouts
	server := &http.Server{
		Addr:         ":8080",
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Printf("Server starting on :8080")
	if err := server.ListenAndServe(); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
```

### Step 3: Define data models

`models.go` contains the request/response structs:

```go
package models

type ContentRequest struct {
	UserID  string `json:"user_id"`
	Content string `json:"content"`
}

type ContentResponse struct {
	Safe    bool     `json:"safe"`
	Reasons []string `json:"reasons,omitempty"`
}

type HealthResponse