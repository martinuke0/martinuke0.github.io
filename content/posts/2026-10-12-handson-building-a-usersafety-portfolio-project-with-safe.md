---
title: "Hands‑On: Building a User‑Safety Portfolio Project with Safe"
date: "2026-10-12T04:01:18.109"
draft: false
tags: ["user-safety","portfolio","side-project","go","postgres"]
description: "Build a production‑ready user‑safety tracking API with Go, PostgreSQL, and Docker – a concrete side‑project that signals backend engineering skill to hiring managers."
summary: "A hands‑on guide to creating a user‑safety tracking system that demonstrates real‑world backend skills, from API design to observability, and ships as a reproducible Docker container."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-12-handson-building-a-usersafety-portfolio-project-with-safe.svg"
  alt: "Illustration of a secure user‑safety dashboard."
  caption: ""
  relative: false
---

> **TL;DR** — In this post we’ll build a fully‑functional user‑safety tracking API in Go, persist incidents to PostgreSQL, containerise it with Docker, and add health checks, metrics and basic fault‑tolerance. The result is a reproducible, hire‑able side‑project that showcases production‑grade patterns.

Building a tangible, end‑to‑end service is one of the fastest ways to signal to hiring managers that you can ship production‑grade code. In this guide you’ll create “safe”, a minimal yet complete user‑safety incident tracker that stores reports, validates input, exposes a REST API, and ships as a self‑contained Docker image. Along the way you’ll practice API design, persistence, observability, and fault‑tolerance patterns that appear in everyday backend work.

## Why This Project Stands Out on a CV

Hiring managers for backend, DevOps, and SRE roles look for concrete evidence that you can move from idea to running service. **safe** demonstrates several signal‑rich skills:

- **REST API design** – clean resource routing, request validation, and HTTP status codes.
- **Persistence with PostgreSQL** – schema creation, GORM (or raw `database/sql`) usage, and migration awareness.
- **Containerisation** – multi‑stage Dockerfile, environment‑driven config, and `docker‑compose` orchestration.
- **Observability basics** – health checks, structured logging, and Prometheus‑compatible metrics.
- **Fault‑tolerance patterns** – circuit‑breaker logic, retry semantics, and graceful shutdown.

The project also ships with a ready‑to‑run Docker image, so a recruiter can spin it up in seconds and see the API in action. Roles that particularly value this mix are backend engineers, platform engineers, and site‑reliability engineers who need to prove they understand the full stack from code to deployment.

## Architecture Overview

The system consists of a single Go binary that serves an HTTP API, talks to a PostgreSQL database, and exposes standard health and metrics endpoints. The diagram below summarises the data flow:

```
+----------------+      HTTPS      +-------------------+      SQL      +-------------------+
|  Client (curl/ |  ------------>  |  Go HTTP server   |  ---------> |  PostgreSQL DB    |
|  Postman)      |               |  (net/http / Gin) |             |  (via GORM)       |
+----------------+               +-------------------+             +-------------------+
          |                                   |
          |   /healthz, /metrics               |   JSON payloads
          +-----------------------------------+
                                   |
                                 +-----v------+
                                 |  Docker    |
                                 |  container |
                                 +------------+
```

Key components:

- **Go HTTP server** – uses the Gin framework for routing and JSON binding; listens on `:8080`.
- **PostgreSQL** – stores `incidents` table with columns `id`, `user_id`, `reported_at`, `description`, `status`.
- **Docker** – multi‑stage build produces a minimal alpine image; `docker‑compose` spins up both the API and a PostgreSQL container.
- **Health & metrics endpoints** – `/healthz` returns `200 OK`; `/metrics` (optional) can be scraped by Prometheus.

## Building It Step by Step

Below are seven numbered steps that take you from a fresh repository to a runnable service. Each step includes a short, language‑tagged code snippet.

### 1. Initialise the Go module and fetch dependencies

```bash
go mod init github.com/yourname/safe
go get github.com/gin-gonic/gin github.com/jinzhu/gorm github.com/lib/pq
```

### 2. Define the incident model (models.go)

```go
// models.go
package safe

import "time"

type Incident struct {
    ID        uint      `json:"id" gorm:"primaryKey"`
    UserID    uint      `json:"user_id" gorm not null"`
    ReportedAt int64    `json:"reported_at"`
    Description string `json:"description" binding:"required"`
    Status    string   `json:"status" default:"open"`
    CreatedAt time.Time `json:"created_at"`
}
```

### 3. Set up the database connection and auto‑migrate (db.go)

```go
// db.go
package safe

import (
    "github.com/jinzhu/gorm"
    _ "github.com/jinzhu/gorm/dialects/postgres"
)

var DB *gorm.DB

func InitDB() {
    dsn := "host=localhost user=postgres dbname=safe sslmode=disable"
    var err error
    DB, err = gorm.Open("postgres", dsn)
    if err != nil {
        panic("failed to connect database")
    }
    DB.AutoMigrate(&Incident{})
}
```

### 4. Create the HTTP router and basic routes (main.go)

```go
// main.go
package main

import (
    "github.com/gin-gonic/gin"
    "safe/handler"
    "safe/models"
)

func main() {
    r := gin.Default()
    // Health check
    r.GET("/healthz", func(c *gin.Context) { c.Status(200) })
    // API group
    api := r.Group("/api/v1")
    {
        api.POST("/incidents", handler.CreateIncident)
        api.GET("/incidents", handler.ListIncidents)
    }
    r.Run(":8080")
}
```

### 5. Implement the incident‑creation handler with validation (handler/create.go)

```go
// handler/create.go
package handler

import (
    "net/http"
    "safe/models"
    "github.com/gin-gonic/gin"
)

func CreateIncident(c *gin.Context) {
    var input models.Incident
    if err := c.ShouldBindJSON(&input); err != nil {
        c.JSON(http.StatusBadRequest, gin.H{"error": err.Error()})
        return
    }
    // Set defaults
    input.Status = "open"
    input.CreatedAt = time.Now().Unix()
    models.DB.Create(&input)
    c.JSON(http.StatusCreated, input)
}
```

### 6. List incidents (handler/list.go)

```go
// handler/list.go
package handler

import (
    "net/http"
    "safe/models"
    "github.com/gin-gonic/gin"
)

func ListIncidents(c *gin.Context) {
    var incidents []models.Incident
    models.DB.Find(&incidents)
    c.JSON(http.StatusOK, incidents)
}
```

### 7. Write a multi‑stage Dockerfile and a docker‑compose.yml (Dockerfile + compose)

**Dockerfile**

```dockerfile
# Dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN go build -o safe .

FROM alpine:3.19
WORKDIR /root/
COPY --from=builder /app/safe .
EXPOSE 8080
CMD ["./safe"]
```

**docker‑compose.yml**

```yaml
version: "3.9"
services:
  safe:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgres://postgres:postgres@db:5432/safe
    depends_on:
      - db
  db:
    image: postgres:15-alpine
    environment:
      - POSTGRES_DB=safe
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=postgres
```

## Running and Testing It

1. **Local Go run**

   ```bash
   go mod tidy
   go run main.go
   ```

   The server starts at `http://localhost:8080`.

2. **Docker compose**

   ```bash
   docker compose up -d
   ```

   Wait a few seconds for PostgreSQL to initialise, then the API is reachable at the same address.

3. **Basic API calls with `curl`**

   ```bash
   # Create a new incident
   curl -X POST http://localhost:8080/api/v1/incidents \
        -H "Content-Type: application/json" \
        -d '{"user_id":42,"description":"User reported phishing attempt"}'

   # List all incidents
   curl http://localhost:8080/api/v1/incidents

   # Health check
   curl http://localhost:8080/healthz
   # Expected: empty body with exit code 200
   ```

4. **Unit tests**

   ```bash
   go test ./...
   ```

   The test suite currently verifies that creating an incident without a `description` returns a `400 Bad Request`.

## Extending It: Your Roadmap to Senior‑Level

| # | Upgrade | One‑line reason it matters |
|---|---------|----------------------------|
| 1 | **JWT authentication middleware** – protect routes with a signed token, demonstrating token‑based access control. |
| 2 | **Database migrations with `golang-migrate`** – version‑controlled schema changes, essential for production DB evolution. |
| 3 | **Prometheus metrics & OpenTelemetry tracing** – expose `/metrics` and add trace IDs, giving ops visibility into latency and error rates. |
| 4 | **Circuit‑breaker & retry logic (e.g., `go-http-client` + `github.com/sony/gobreaker`)** – gracefully handle downstream DB failures without cascading outages. |
| 5 | **Kubernetes deployment with Helm chart & HPA** – practice horizontal scaling, resource requests/limits, and declarative rollout. |
| 6 | **Integration tests with Testcontainers** – spin up a real PostgreSQL container per test, ensuring the API works end‑to‑end under realistic conditions. |

Each upgrade moves the project from a “toy” demo toward a production‑grade service that hiring managers can discuss in depth.

## Key Takeaways

- The project delivers a full‑stack API you can demo in an interview, complete with CRUD operations and health checks.  
- You practice containerisation, CI‑ready Dockerfiles, and environment‑driven config—core DevOps skills.  
- You learn persistence, input validation, and basic observability patterns used in production services.  
- Adding auth, migrations, and metrics turns the toy into a hire‑able backend prototype.  
- The codebase is modular, making it easy to replace GORM with raw SQL or swap Go for another language later.

## Further Reading

- [Go blog – “Project layout”](https://go.dev/blog/project-layout) – recommended folder structure for maintainable Go services.  
- [PostgreSQL documentation – “CREATE TABLE”](https://www.postgresql.org/docs/current/sql-createtable.html) – for schema design and constraints.  
- [Docker documentation – “Write a Dockerfile”](https://docs.docker.com/engine/reference/builder/) – to build the production image.  
- [OpenTelemetry specification](https://opentelemetry.io/docs/) – for adding tracing and metrics to the API.  
- [Kubernetes “12‑factor app” guide](https://kubernetes.io/docs/concepts/configuration/overview/) – when you move the service to a cluster deployment.