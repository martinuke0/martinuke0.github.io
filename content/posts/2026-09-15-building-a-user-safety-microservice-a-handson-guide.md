

---
title: "Building a User Safety Microservice: A Hands‑On Guide"
date: "2026-09-15T20:01:31.421"
draft: false
tags: ["user-safety", "microservice", "go", "docker", "testing"]
description: "Learn to build a production‑grade user safety microservice that validates and filters user input, with real code, Docker, and testing strategies."
summary: "A practical guide to building a user safety microservice that validates and filters input, with runnable Go code and Docker."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-15-building-a-user-safety-microservice-a-handson-guide.svg"
  alt: "A dashboard showing user safety metrics"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a lightweight user safety service that validates and filters user‑generated content, giving you a concrete portfolio piece that demonstrates API design, containerization, and automated testing. By the end you’ll have a runnable Go microservice, a Docker Compose setup, and a CI pipeline that proves correctness under load.

Building a side project that signals real systems skill is a powerful way to stand out to hiring managers. In this post we’ll construct a user safety microservice that checks incoming text for prohibited content, returns a safety score, and can be extended into a production‑grade system. The implementation is deliberately simple enough to finish in an afternoon, yet it touches the same concerns you’ll find in large‑scale content moderation platforms.

## Why This Project Stands Out on a CV

- **End‑to‑end product ownership** – you define the API, implement business logic, package it in a container, and write tests that cover happy paths and failure modes.
- **Demonstrable proficiency in Go** – a language prized for backend services because of its lightweight concurrency model and fast startup time.
- **Container‑first delivery** – you ship a Docker image and a `docker‑compose.yml`, showing you understand modern deployment patterns.
- **Testing discipline** – unit tests, integration tests, and a CI workflow that runs them automatically.
- **Scalability awareness** – the architecture is intentionally stateless, making horizontal scaling straightforward.
- **Observability basics** – you can plug in Prometheus metrics and structured logging with minimal code changes.

These signals map directly to roles such as **Backend Engineer**, **Platform Engineer**, or **Site Reliability Engineer**, where building reliable, observable services is core to the job.

## Architecture Overview

The service is a single binary that exposes a JSON HTTP API. It receives a `POST` request with a `text` field, runs a set of safety rules, and returns a verdict.

```
Client ──HTTP──► API Gateway (optional) ──► User Safety Service
                     │
                     ▼
              Safety Engine (rule set)
                     │
                     ▼
              Response (safe / unsafe)
```

**Components**

- **HTTP Server** – listens on `:8080`, parses JSON, calls the engine.
- **Safety Engine** – a pure function that applies regex patterns and a blocklist.
- **Metrics** – optional Prometheus endpoint at `/metrics`.
- **Logging** – structured JSON logs to stdout.

The design is intentionally **stateless**; all state lives in the process, so you can run multiple replicas behind a load balancer without sticky sessions.

## Building It Step by Step

### 1. Scaffold the project

```bash
mkdir user-safety-service
cd user-safety-service
go mod init user-safety
```

### 2. Write the core service

Create `main.go`:

```go
package main

import (
    "encoding/json"
    "log"
    "net/http"
    "regexp"
    "strings"
)

// SafetyRequest is the expected payload.
type SafetyRequest struct {
    Text string `json:"text"`
}

// SafetyResponse is the returned verdict.
type SafetyResponse struct {
    Safe   bool     `json:"safe"`
    Reason []string `json:"reason,omitempty"`
}

// bannedWords is a simple blocklist.
var bannedWords = []string{
    "spam", "phishing", "malware",
}

// regex for profanity (example)
var profanityRegex = regexp.MustCompile(`\b(damn|crap)\b`)

// checkSafety applies rules and returns a response.
func checkSafety(text string) SafetyResponse {
    var reasons []string

    lower := strings.ToLower(text)
    for _, w := range bannedWords {
        if strings.Contains(lower, w) {
            reasons = append(reasons, "banned word: "+w)
        }
    }

    if profanityRegex.MatchString(lower) {
        reasons = append(reasons, "profanity detected")
    }

    return SafetyResponse{
        Safe:   len(reasons) == 0,
        Reason: reasons,
    }
}

func safetyHandler(w http.ResponseWriter, r *http.Request) {
    if r.Method != http.MethodPost {
        http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        return
    }

    var req SafetyRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "invalid JSON", http.StatusBadRequest)
        return
    }

    resp := checkSafety(req.Text)
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(resp)
}

func main() {
    http.HandleFunc("/safety", safetyHandler)
    log.Println("listening on :8080")
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

### 3. Add a Dockerfile

```dockerfile
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum ./
COPY . .
RUN go build -o /user-safety .

FROM alpine:3.19
RUN addgroup -S app && adduser -S app -G app
USER app
COPY --from=build /user-safety /user-safety
EXPOSE 8080
CMD ["/user-safety"]
```

### 4. Create a `docker-compose.yml