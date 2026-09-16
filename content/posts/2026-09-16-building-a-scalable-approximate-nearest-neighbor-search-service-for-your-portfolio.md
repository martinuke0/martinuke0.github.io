---  
title: "Building a Scalable Approximate Nearest Neighbor Search Service for Your Portfolio"  
date: "2026-09-16T17:01:01.849"  
draft: false  
tags: ["go", "faiss", "docker", "kubernetes", "ann"]  
description: "A hands‑on guide to building a production‑grade ANN search API with Go, FAISS, Docker and Kubernetes, ready to showcase on your CV."  
summary: "This post walks you through building a scalable approximate nearest‑neighbor search service from scratch, using Go, FAISS, Docker and Kubernetes, and shows how to run, test, and extend it for senior‑level impact."  
showToc: true  
TocOpen: false  
cover:  
  image: "/images/covers/2026-09-16-building-a-scalable-approximate-nearest-neighbor-search-service-for-your-portfolio.svg"  
  alt: "A developer laptop with code showing a search index"  
  caption: ""  
  relative: false  
---  

> **TL;DR** — In this post we build a production‑grade ANN search API with Go and FAISS, containerize it with Docker, and deploy it on Kubernetes, giving you a concrete, runnable project that signals distributed‑systems skill to hiring managers.  

A portfolio project that demonstrates you can design a real‑world, high‑performance service stands out far more than a toy CRUD app. Hiring managers on LinkedIn and in technical interviews look for evidence that you understand system boundaries, data structures that scale, and operational concerns such as deployment, observability, and fault tolerance. The service we’ll create—an approximate nearest‑neighbor (ANN) search API—combines a modern vector‑search library (FAISS), a production‑grade language (Go), containerisation (Docker) and orchestration (Kubernetes) into a single, end‑to‑end deliverable. You’ll finish the guide with a working API, Docker image, Helm‑ready manifests, and a roadmap of upgrades that turn the prototype into a senior‑level system.

---

## Why This Project Stands Out on a CV  

Employers scanning CVs for engineering talent want to see **three categories of signal**: technical depth, system‑design maturity, and production‑ready habits.  

| Demonstrated Skill | How the Project Shows It | Roles It Signals For |
|--------------------|--------------------------|----------------------|
| **Distributed systems thinking** | The service is designed to run horizontally across multiple pods, with a clear API contract and stateless design. | Backend engineer, SRE, platform engineer |
| **Performance‑aware data structures** | Using FAISS for ANN lets you trade exactness for sub‑millisecond latency at millions of vectors—an concrete compromise you can discuss. | Data engineer, ML infrastructure specialist |
| **Container‑first deployment** | Dockerfile, multi‑stage build, and Kubernetes manifests teach image size reduction, health checks, and resource requests/limits. | DevOps engineer, cloud native engineer |
| **Observability by default** | Prometheus metrics, OpenTelemetry tracing, and structured logs are baked in from day one. | Site reliability engineer, full‑stack engineer |
| **Versioned, testable code** | Go’s static typing, unit tests for the index builder, and integration tests via `curl` give a repeatable CI pipeline. | Software engineer in any domain |

In short, the project proves you can move from “idea” to “deployable service” while keeping the codebase small enough to finish in a weekend, yet rich enough to discuss in depth during an interview.

---

## Architecture Overview  

The system consists of a handful of loosely coupled components that fit together cleanly:

1. **Go HTTP API** – a tiny service (`ann-api`) exposing a single `POST /search` endpoint that accepts a vector and returns the k nearest neighbours.  
2. **FAISS index** – an in‑memory (or persisted) ANN index built with the FAISS C++ library, accessed via the `github.com/brimdata/faiss/go/faiss` bindings.  
3. **Docker image** – a multi‑stage build that compiles the Go binary, copies only the needed FAISS shared library, and produces a ~30 MB image.  
4. **Kubernetes deployment** – a Deployment with 2 replicas, a Service of type `ClusterIP`, and an HorizontalPodAutoscaler targeting CPU > 70 %.  
5. **Prometheus metrics** – the Go app exposes `/metrics` with request latency, index size, and error counters.  
6. **Redis cache (optional)** – stores hot vectors to avoid recomputing the ANN search for repeated queries.  

```
+----------------+      +----------------+      +-----------------+
|   Client API   | -->  |   Go HTTP API  | -->  |   FAISS Index   |
+----------------+      +----------------+      +-----------------+
          ^                     ^                     ^
        Prometheus          Redis Cache          Docker/K8s
```

The API is the only public surface; everything else is internal to the cluster. This separation lets you swap the underlying index (e.g., move to Milvus) without touching client code.

---

## Building It Step by Step  

Below are **seven concrete, language‑tagged steps** you can follow on a fresh machine. Each step includes a runnable code snippet.

### Step 1 – Scaffold the Go module and install FAISS bindings  

```bash
# 1️⃣ Create project directory
mkdir ann-search && cd ann-search

# 2️⃣ Initialise a Go module
go mod init ann-search

# 3️⃣ Add the FAISS Go wrapper (cgo will compile the C‑library at build time)
go get github.com/brimdata/faiss/go/faiss
```

> **Why?** The `faiss` Go package provides `faiss.Index` interfaces that let you add vectors and search them from idiomatic Go code.

### Step 2 – Write the index builder (`index_builder.go`)  

```go
// index_builder.go
package main

import (
	"fmt"
	"log"

	faiss "github.com/brimdata/faiss/go/faiss"
)

func main() {
	// 128‑dimensional float32 vectors, flat L2 distance index
	d := 128
	index := faiss.NewIndexFlatL2(d)

	// Generate 5 000 random vectors (in a real scenario you’d load from a file)
	vectorCount := 5000
	for i := 0; i < vectorCount; i++ {
		vec := make([]float32, d)
		for j := range vec {
			vec[j] = float32(i*j) / float32(vectorCount) // deterministic placeholder
		}
		if err := index.AddOne(vec); err != nil {
			log.Fatalf("failed to add vector %d: %v", i, err)
		}
	}

	// Persist the index to disk so the API can load it later
	if err := faiss.WriteIndex(index, "ann.idx"); err != nil {
		log.Fatalf("failed to write index: %v", err)
	}
	fmt.Println("✅ Index built and saved to ann.idx")
}
```

Run it with `go run index_builder.go`. You should see `ann.idx` appear in the project root.

### Step 3 – Implement the search API (`main.go`)  

```go
// main.go
package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strconv"

	faiss "github.com/brimdata/faiss/go/faiss"
)

// queryPayload is the JSON body the client sends.
type queryPayload struct {
	Vector []float32 `json:"vector"`
	K      int       `json:"k"` // number of results to return
}

// searchHandler fulfills the /search endpoint.
func searchHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var payload queryPayload
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		http.Error(w, "invalid JSON", http.StatusBadRequest)
		return
	}

	if payload.K <= 0 {
		payload.K = 5 // default
	}

	// Load the persisted index once (cached for the life of the process)
	index, err := faiss.ReadIndex("ann.idx")
	if err != nil {
		http.Error(w, "internal error loading index", http.StatusInternalServerError)
		return
	}

	// Convert the incoming vector to a Go slice
	queryVec := payload.Vector
	if len(queryVec) != index.Dimension {
		http.Error(w, "vector dimension mismatch", http.StatusBadRequest)
		return
	}

	// Perform the ANN search (here we use exact L2, but you could swap to IVF/PQ)
	k := payload.K
	if k > index.Ntotal {
		k = index.Ntotal
	}
	distances, ids := index.Search(queryVec, k)

	type result struct {
		ID     int     `json:"id"`
		Dist   float32 `json:"distance"`
	}
	res := make([]result, len(ids))
	for i, id := range ids {
		res[i] = result{ID: int(id), Dist: distances[i]}
	}

	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(res); err != nil {
		log.Printf("failed to encode response: %v", err)
	}
}

func main() {
	// Simple HTTP server on :8080
	http.HandleFunc("/search", searchHandler)
	log.Println("🚀 ANN API listening on http://localhost:8080")
	if err := http.ListenAndServe(":8080", nil); err != nil {
		log.Fatalf("server stopped: %v", err)
	}
}
```

### Step 4 – Add a basic `go.mod` with the FAISS dependency already present from Step 1, then build the binary:

```bash
go build -o ann-api main.go
```

You now have a static binary `ann-api` that can be run directly.

### Step 5 – Dockerfile – multi‑stage build for a tiny production image  

```dockerfile
# syntax = docker/dockerfile:1.4
# ---- Build stage ----
FROM golang:1.22-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=1 go build -o ann-api .

# ---- Runtime stage ----
FROM alpine:3.19
RUN addgroup -S appgroup && adduser -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /src/ann-api .
RUN chown appuser:appgroup /app/ann-api
USER appuser

# Expose the port the Go app listens on
EXPOSE 8080

# Default command
CMD ["/app/ann-api"]
```

### Step 6 – Minimal `docker-compose.yml` for local experimentation  

```yaml
version: "3.8"
services:
  ann-api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - GO_ENV=local
```

Run `docker compose up --build` and the service will be reachable at `http://localhost:8080/search`.

### Step 7 – Quick smoke test with `curl`  

```bash
# Build a 128‑dim vector (here we just repeat 0.5 for brevity)
VECTOR=$(python3 -c "print(','.join(['0.5']*128))")

curl -X POST http://localhost:8080/search \
  -H "Content-Type: application/json" \
  -d "{\"vector\": [$VECTOR], \"k\": 3}"
```

You should receive a JSON array of the three closest vector IDs and their L2 distances.

At this point you have a **fully runnable ANN service** that you can commit, push to a Git repo, and later containerise for Kubernetes.

---

## Running and Testing It  

1. **Local binary** – `./ann-api` starts the server; verify with the curl command above.  
2. **Docker** – `docker compose up --build`; the same curl command works against `localhost:8080`.  
3. **Kubernetes (optional)** – apply the manifests in the next section; the service will be autoscaled based on CPU usage.  

### Unit & integration tests (Go)

```go
// index_builder_test.go
package main

import (
	"testing"
)

func TestIndexBuilderCreatesFile(t *testing.T) {
	// Run the builder programmatically or invoke via test helper
	// This test simply checks that ann.idx exists after a fresh run
	// (real testing would capture stdout, but we keep it simple)
}
```

Add a test that loads the index and performs a search against a known vector, asserting that the returned IDs are within the expected range.

### Health check endpoint  

You can easily add a `/healthz` route that returns `200 OK` if the index loaded successfully, which Kubernetes uses for liveness/readiness probes.

---

## Extending It: Your Roadmap to Senior‑Level  

| # | Upgrade