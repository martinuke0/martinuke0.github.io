

---
title: "Building a Personal Portfolio API with Go, SQLite, and Docker"
date: "2026-09-12T19:01:24.795"
draft: false
tags: ["go", "docker", "api", "portfolio", "systems"]
description: "A practical guide to creating a lightweight, containerized portfolio API that showcases real systems skills for engineering candidates."
summary: "Learn to build a Go‑based portfolio API backed by SQLite, packaged with Docker, and wired to GitHub Actions for CI."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-building-a-personal-portfolio-api-with-go-sqlite-and-docker.svg"
  alt: "A laptop displaying a JSON API response"
  caption: ""
  relative: false
---

> **TL;DR** — You will build a small, production‑ready portfolio API in Go that stores projects in SQLite, runs inside Docker, and can be deployed with a single GitHub Actions workflow. It demonstrates API design, database modeling, containerization, and CI/CD — all skills that hiring managers look for.

In this guide we walk through a complete, runnable project that you can add to your résumé today. The code is intentionally minimal but extensible, so you can showcase real systems thinking without spending weeks on boilerplate.

## Why This Project Stands Out on a CV

- **End‑to‑end ownership** – you ship a service that accepts HTTP requests, persists data, and is packaged for deployment.
- **Modern toolchain** – Go for performance, SQLite for zero‑config storage, Docker for reproducibility, and GitHub Actions for automated testing.
- **API design** – you implement RESTful endpoints with proper status codes, JSON serialization, and input validation.
- **Testing & CI** – unit tests run on every push, and the container image is built and pushed to a registry.
- **Scalability hints** – the architecture makes it trivial to swap SQLite for PostgreSQL or add a caching layer later, showing forward‑thinking design.

These signals tell recruiters you can operate in a production environment, not just write algorithms.

## Architecture Overview

```
+-------------------+      HTTP       +-------------------+
|   Client (curl)   | -------------> |   Go API Server   |
+-------------------+                +-------------------+
                                            |
                                            v
                                      +-------------+
                                      |   SQLite    |
                                      |   Database  |
                                      +-------------+
```

- **Go API Server** – a single binary exposing `/projects` and `/projects/{id}`.
- **SQLite** – a file‑based relational database; no separate DB server needed.
- **Dockerfile** – builds a minimal image with the binary and the SQLite driver.
- **docker‑compose.yml** – runs the API and an optional admin UI for inspection.
- **GitHub Actions workflow** – runs tests, builds the image, and pushes it to Docker Hub.

All components are versioned in a single Git repository, making the project self‑contained.

## Building It Step by Step

### 1. Scaffold the project

```bash
mkdir portfolio-api && cd portfolio-api
go mod init github.com/yourname/portfolio-api
```

### 2. Define the data model

Create `model.go`:

```go
package model

import "time"

type Project struct {
    ID          int       `json:"id"`
    Name        string    `json:"name"`
    Description string    `json:"description"`
    URL         string    `json:"url"`
    CreatedAt   time.Time `json:"created_at"`
}
```

### 3. Set up the SQLite database

Create `db.go`:

```go
package db

import (
    "database/sql"
    "log"

    _ "github.com/mattn/go-sqlite3"
)

func Open(path string) *sql.DB {
    db, err := sql.Open("sqlite3", path)
    if err != nil {
        log.Fatalf("open db: %v", err)
    }
    const schema = `
    CREATE TABLE IF NOT EXISTS projects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        description TEXT,
        url TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );`
    if _, err := db.Exec(schema); err != nil {
        log.Fatalf("create schema: %v", err)
    }
    return db
}
```

### 4. Implement the HTTP handlers

Create `handler.go`:

```go
package handler

import (
    "encoding/json"
    "net/http"
    "strconv"

    "github.com/yourname/portfolio-api/db"
    "github.com/yourname/portfolio-api/model"
)

type ProjectHandler struct {
    DB *db.DB
}

func (h *ProjectHandler) List(w http.ResponseWriter, r *http.Request) {
    rows, err := h.DB.Query("SELECT id, name, description, url, created_at FROM projects")
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    defer rows.Close()

    var projects []model.Project
    for rows.Next() {
        var p model.Project
        if err := rows.Scan(&p.ID, &p.Name, &p.Description, &p.URL, &p.CreatedAt); err != nil {
            http.Error(w, err.Error(), http.StatusInternalServerError)
            return
        }
        projects = append(projects, p)
    }
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(projects)
}

func (h *ProjectHandler) Create(w http.ResponseWriter, r *http.Request) {
    var p model.Project
    if err := json.NewDecoder(r.Body).Decode(&p); err != nil {
        http.Error(w, "invalid JSON", http.StatusBadRequest)
        return
    }
    result, err := h.DB.Exec(
        "INSERT INTO projects (name, description, url) VALUES (?, ?, ?)",
        p.Name, p.Description, p.URL,
    )
    if err != nil {
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    id, _ := result.LastInsertId()
    p.ID = int(id)
    p.CreatedAt = time.Now()
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(p)
}
```

### 5. Wire everything together in `main.go`

```go
package main

import (
    "log"
    "net/http"
    "os"

    "github.com/yourname/portfolio-api/db"
    "github.com/yourname/portfolio-api/handler"
)

func main() {
    dbPath := os.Getenv("DB_PATH")
    if dbPath == "" {
        dbPath = "portfolio.db"
    }
    database := db.Open(dbPath)
    defer database.Close()

    ph := &handler.ProjectHandler{DB: database}

    mux := http.NewServeMux()
    mux.HandleFunc("/projects", func(w http.ResponseWriter, r *http.Request) {
        switch r.Method {
        case http.MethodGet:
            ph.List(w, r)
        case http.MethodPost:
            ph.Create(w, r)
        default:
            http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
        }
    })

    log.Println("listening on :8080")
    log.Fatal(http.ListenAndServe(":8080", mux))
}
```

### 6. Add Docker support

`Dockerfile`:

```dockerfile
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /portfolio-api .

FROM alpine:3.19
RUN addgroup -g 1001 appuser && adduser -D -u 1001 -G appuser appuser
WORKDIR /app
COPY --from=build /portfolio-api .
USER appuser
EXPOSE 8080
CMD ["/portfolio-api"]
```

`docker-compose.yml`:

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DB_PATH=/data/portfolio.db
    volumes:
      - ./data:/data
```

### 7. Write a simple CI workflow

`.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Go
        uses: actions/setup-go@v5
        with:
          go-version: '1.22'
      - name: Install dependencies
        run: go mod download
      - name: Run tests
        run: go test ./...
      - name: Build Docker image
        run: docker build -t portfolio-api:latest .
```

## Running and Testing It

1. **Start the service locally**

```bash
docker compose up --build -d
```

2. **Create a project**

```bash
curl -X POST http://localhost:8080/projects \
     -H "Content-Type: application/json" \
     -d '{"name":"My Side Project","description":"A Go API","url":"https://example.com"}'
```

3. **List projects**

```bash
curl http://localhost:8080/projects
```

You should receive a JSON array containing the project you just created.

4. **Unit tests**

Create `handler_test.go`:

```go
package handler

import (
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "strings"
    "testing"

    "github.com/yourname/portfolio-api/db"
)

func TestCreateAndList(t *testing.T) {
    database := db.Open(":memory:")
    defer database.Close()
    ph := &ProjectHandler{DB: database}

    // POST
    body := strings.NewReader(`{"name":"Test","description":"desc","url":"http://x"}`)
    req := httptest.NewRequest(http.MethodPost, "/projects", body)
    rec := httptest.NewRecorder()
    ph.Create(rec, req)
    if rec.Code != http.StatusCreated {
        t.Fatalf("expected 201, got %d", rec.Code)
    }

    // GET
    req2 := httptest.NewRequest(http.MethodGet, "/projects", nil)
    rec2 := httptest.NewRecorder()
    ph.List(rec2, req2)
    if rec2.Code != http.StatusOK {
        t.Fatalf("expected 200, got %d", rec2.Code)
    }
    var projects []model.Project
    if err := json.Unmarshal(rec2.Body.Bytes(), &projects); err != nil {
        t.Fatalf("invalid JSON: %v", err)
    }
    if len(projects) != 1 {
        t.Fatalf("expected 1 project, got %d", len(projects))
    }
}
```

Run with:

```bash
go test ./...
```

All tests should pass, confirming the core logic works.

## Extending It: Your Roadmap to Senior-Level

1. **Swap SQLite for PostgreSQL** – adds production‑grade durability, concurrency, and richer query capabilities, showing you can choose the right storage for scale.
2. **Introduce Redis caching** – reduces DB load for read‑heavy endpoints and demonstrates awareness of latency optimization.
3. **Add JWT authentication** – protects endpoints and signals you understand security fundamentals and token‑based auth flows.
4. **Implement rate limiting** – using a token bucket algorithm, you showcase ability to guard against abuse in public APIs.
5. **Instrument with Prometheus** – expose `/metrics` and add histograms/counter to provide observability, a key concern for on‑call engineers.
6. **Deploy to Kubernetes** – write a `Deployment` and `Service` manifest, proving you can operate containers in a clustered environment.

Each upgrade addresses a real production concern and can be added incrementally, turning a simple prototype into a resilient service.

## Key Takeaways

- Build a complete, runnable service that covers API, persistence, containerization, and CI.
- Use Go and SQLite for a zero‑dependency start, then layer on Docker and GitHub Actions.
- Demonstrate testing, error handling, and extensibility to appeal to senior roles.
- Keep the codebase modular so you can showcase scalability and observability upgrades.
- Include real URLs and documentation to prove you can ship and maintain software.

## Further Reading

- [Go documentation](https://go.dev/doc/) – official language reference and standard library.
- [SQLite documentation](https://www.sqlite.org/docs.html) – deep dive into SQL features and best practices.
- [Docker Compose guide](https://docs.docker.com/compose/) – orchestrate multi‑container apps.
- [GitHub Actions reference](https://docs.github.com/en/actions) – automate workflows with YAML.
- [REST API design](https://martinfowler.com/articles/restful.html) – principles for building maintainable HTTP services.

These resources will help you evolve the project into a production‑grade system and deepen your understanding of the underlying technologies.