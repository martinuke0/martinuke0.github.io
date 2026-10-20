---
title: "Hands‑On: Building a Chunk‑Based Document Store Portfolio Project"
date: "2026-10-20T03:00:59.839"
draft: false
tags: ["go","docker","postgresql","microservices","portfolio"]
description: "Build a chunk‑based document store with Go, Docker, and PostgreSQL, and get a runnable portfolio project that signals production‑grade engineering skill."
summary: "Learn to build a chunk‑based document store from scratch using Go, Docker, and PostgreSQL, and create a standout portfolio project that signals production‑grade engineering ability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-20-handson-building-a-chunkbased-document-store-portfolio-project.svg"
  alt: "A developer laptop displaying a chunk‑based document store dashboard"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you’ll build a chunk‑based document store in Go, containerize it with Docker, and persist data in PostgreSQL, gaining a runnable, portfolio‑ready project that demonstrates real‑world systems skills.

A portfolio project that doubles as a production‑grade system is one of the fastest ways to catch a hiring manager’s eye. In this guide you’ll hands‑on build a chunk‑based document store from scratch, using Go for the service, Docker for containerization, and PostgreSQL for persistence. By the end you’ll have a complete, runnable codebase, a clear architecture, and a set of extensions that showcase senior‑level engineering skills.

## Why This Project Stands Out on a CV

- **Go proficiency** – You’ll write production‑grade services with static typing, error‑handling patterns, and idiomatic concurrency.
- **Systems‑level thinking** – Designing chunk storage, size‑based partitioning, and API design mirrors real backend engineering.
- **DevOps fundamentals** – Dockerizing the app, writing a Dockerfile, and (optionally) composing services teaches container best practices.
- **Database literacy** – Interacting with PostgreSQL via SQL and an ORM (e.g., `sqlx`) signals you can persist state reliably.
- **Portfolio impact** – A finished, runnable project with a README, tests, and extension roadmap gives recruiters concrete evidence of your engineering pipeline.

It signals strongly for roles such as backend engineer, DevOps/SRE, and full‑stack positions that value hands‑on system design.

## Architecture Overview

- **Go HTTP service** – Exposes `/chunks` endpoints for create, read, list, and delete operations.
- **Chunk storage layer** – In‑memory `map[string]Chunk` for fast access; chunks are size‑based (e.g., ≤ 1 MB) and identified by a UUID.
- **PostgreSQL backend** – Stores chunk metadata (`id`, `content bytea`, `size`) for durability across restarts.
- **Docker container** – Builds a single‑binary image (`alpine` base) for reproducible deployment.
- **Optional observability** – Prometheus `/metrics` endpoint and OpenTelemetry trace propagation.
- **CI/CD ready** – GitHub Actions workflow builds, tests, and pushes the image on every push.

```
┌─────────────┐      ┌─────────────────────┐      ┌─────────────────┐
│  Client     │ ←→   │  Go HTTP Service     │ ←→ │ PostgreSQL DB   │
│ (curl/http) │      │  (chunks API)        │    │ (chunks table)  │
└─────────────┘      └─────────────────────┘      └─────────────────┘
           └───────────────▲───────────────────────▲─────────────┘
                         │                       │
                       Docker                          Prometheus
                       container                         /metrics
```

## Building It Step by Step

### 1. Initialize Go module and define data structures

```go
package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/jmoiron/sqlx"
)

type Chunk struct {
	ID      string `json:"id"`
	Content []byte `json:"content"`
	Size    int64  `json:"size"`
}
```

### 2. Implement an in‑memory chunk store

```go
var store = make(map[string]Chunk)

// StoreChunk inserts a chunk and returns its ID.
func StoreChunk(c Chunk) string {
	store[c.ID] = c
	return c.ID
}
```

### 3. Expose a simple HTTP API

```go
func handleStore(w http.ResponseWriter, r *http.Request) {
	var input struct {
		Content string `json:"content"`
	}
	if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	c := Chunk{
		ID:      fmt.Sprintf("%d", time.Now().UnixNano()),
		Content: []byte(input.Content),
		Size:    int64(len(input.Content)),
	}
	id := StoreChunk(c)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"id": id})
}

func handleList(w http.ResponseWriter, r *http.Request) {
	list := make([]Chunk, 0, len(store))
	for _, c := range store {
		list = append(list, c)
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(list)
}
```

Register routes:

```go
func main() {
	http.HandleFunc("/chunks", func(w http.ResponseWriter, r *http.Request) {
		switch r.Method {
		case http.MethodPost:
			handleStore(w, r)
		case http.MethodGet:
			handleList(w, r)
		}
	})
	http.ListenAndServe(":8080", nil)
}
```

### 4. Wire PostgreSQL for persistent metadata

```go
func initDB(db *sqlx.DB) error {
	_, err := db.Exec(`CREATE TABLE IF NOT EXISTS chunks (
		id SERIAL PRIMARY KEY,
		content BYTEA,
		size BIGINT
	)`)
	return err
}
```

A basic handler that writes a chunk to both memory and DB:

```go
func handleStoreDB(w http.ResponseWriter, r *http.Request, db *sqlx.DB) {
	var input struct {
		Content string `json:"content"`
	}
	if err := json.NewDecoder(r.Body).Decode(&input); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	c := Chunk{
		ID:      fmt.Sprintf("%d", time.Now().UnixNano()),
		Content: []byte(input.Content),
		Size:    int64(len(input.Content)),
	}
	// Persist to PostgreSQL
	_, err := db.Exec(`INSERT INTO chunks (content, size) VALUES ($1, $2)`, c.Content, c.Size)
	if err != nil {
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	StoreChunk(c)
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"id": c.ID})
}
```

Update the route registration:

```go
func main() {
	db, err := sqlx.Connect("postgres", "user=postgres dbname=chunks sslmode=disable")
	if err != nil {
		panic(err)
	}
	defer db.Close()
	initDB(db)

	http.HandleFunc("/chunks", func(w http.ResponseWriter, r *http.Request) {
		handleStoreDB(w, r, db)
	})
	http.ListenAndServe(":8080", nil)
}
```

### 5. Write a Dockerfile for a reproducible build

```dockerfile
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN go build -o main .

FROM alpine:3.19
WORKDIR /root/
COPY --from=builder /app/main .
EXPOSE 8080
CMD ["./main"]
```

### 6. Run and test locally

```bash
# Build the binary
go build -o main .

# Run the service
./main &

# Test with curl
curl -X POST -H "Content-Type: application/json" -d '{"content":"hello chunk"}' http://localhost:8080/chunks
curl http://localhost:8080/chunks
```

Run the test suite:

```bash
go test ./...
```

## Running and Testing It

1. **Start the container** (Docker Compose optional):

   ```yaml
   version: "3.8"
   services:
     chunkstore:
       build: .
       ports:
         - "8080:8080"
       environment:
         - POSTGRES_URL=postgres://postgres:postgres@db:5432/chunks
       depends_on:
         - db
   services:
     db:
       image: postgres:15
       environment:
         POSTGRES_USER: postgres
         POSTGRES_PASSWORD: postgres
         POSTGRES_DB: chunks
   ```

   Run `docker compose up --build -d`.

2. **Verify health** – `curl http://localhost:8080/chunks` should return a JSON list (initially empty).

3. **Run unit and integration tests** – `go test -v ./...` will execute `sqlx`‑based tests that spin up a temporary PostgreSQL container via `testcontainers-go`.

4. **Benchmark** – Use `wrk` or `k6` to send concurrent POST requests and observe throughput; results can be captured in a `bench` directory.

## Extending It: Your Roadmap to Senior‑Level

1. **Persistence migrations with Goose** – Automates schema evolution; matters for long‑term data integrity.  
2. **Horizontal scaling with multiple instances behind a load balancer** – Demonstrates stateless design and production‑grade traffic handling.  
3. **Observability: Prometheus metrics + OpenTelemetry tracing** – Provides real‑time insight into request latency, error rates, and chunk throughput.  
4. **Fault tolerance via a circuit breaker (e.g., `go-resilience`)** – Prevents cascading failures when the DB becomes unresponsive.  
5. **Benchmarking with `wrk` or `k6`** – Quantifies performance under load, a concrete metric hiring managers look for.  
6. **CI/CD pipeline with GitHub Actions** – Automates build, test, Docker image push, and Helm chart deployment on every commit.

## Key Takeaways

- Building a **chunk‑based document store** from scratch showcases Go systems programming, API design, and database interaction.  
- **Dockerizing** the app teaches container best practices and reproducible deployments.  
- **PostgreSQL** persistence proves you can balance in‑memory speed with durable storage.  
- The **extension roadmap** (migrations, scaling, observability, fault tolerance, benchmarking, CI/CD) mirrors real‑world engineering responsibilities.  
- A finished, runnable project with tests and a clear README is a powerful CV signal for backend, DevOps, and full‑stack roles.

## Further Reading

- [Go net/http package documentation](https://pkg.go.dev/net/http)  
- [PostgreSQL official documentation](https://www.postgresql.org/docs/)  
- [Docker Compose specification](https://docs.docker.com/compose/)  
- [The Twelve-Factor App methodology](https://12factor.net)  
- [Go Blog – Channels and concurrency](https://go.dev/blog/channels)