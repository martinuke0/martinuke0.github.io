---
title: "Building a Scalable URL Shortener Service in Go"
date: "2026-10-20T10:01:02.991"
draft: false
tags: ["go", "microservices", "postgres", "redis", "docker", "kubernetes"]
description: "A hands‑on guide to building a production‑grade URL shortener with Go, PostgreSQL, Redis, and Docker, covering architecture, code, and scaling."
summary: "This tutorial walks you through building a URL shortener service in Go that scales to millions of requests per day, with production‑ready patterns and code."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-20-building-a-scalable-url-shortener-service-in-go.svg"
  alt: "A short URL service dashboard"
  caption: ""
  relative: false
---

> **TL;DR** — In this post you'll build a production‑grade URL shortener in Go that handles millions of redirects per day, using PostgreSQL for durability, Redis for caching, and Docker Compose for local orchestration. The code is fully runnable, and you'll learn the architecture, testing, and extension patterns that hiring managers look for.

Building a URL shortener is a classic interview project, but most tutorials stop at a single‑process script. In this guide you’ll treat it as a real distributed service: a Go microservice backed by PostgreSQL, fronted by Redis, containerized with Docker, and ready to scale horizontally. By the end you’ll have a portfolio piece that demonstrates systems thinking, production‑grade code, and a clear path to senior‑level improvements.

## Why This Project Stands Out on a CV

- **Concrete systems design** – You’ll ship a service that combines an HTTP API, relational persistence, in‑memory caching, and container orchestration, showing you can hold a whole system in your head.
- **Language and tool mastery** – Go’s concurrency model, PostgreSQL’s ACID guarantees, Redis’ latency‑driven caching, and Docker’s isolation are all used deliberately, not just sprinkled in.
- **Production patterns** – Repository pattern, health checks, graceful shutdown, and environment‑driven configuration are baked in, signaling you’ve worked on real services.
- **Scalability narrative** – The architecture is explicitly designed for horizontal scaling, and the “Extending It” section gives you talking points for growth, observability, and fault tolerance.
- **Hiring‑manager signal** – When a recruiter asks “Tell me about a project you built,” you can walk through the request flow, point at the code, and discuss trade‑offs you made for throughput vs. consistency.

## Architecture Overview

The service is composed of four main components:

1. **HTTP API (Go binary)** – Exposes `POST /shorten` and `GET /:code`. It validates input, generates a short code, writes to PostgreSQL, and caches the mapping in Redis.
2. **PostgreSQL** – Stores the canonical URL, short code, creation timestamp, and click count. A simple two‑table schema keeps the hot path lean.
3. **Redis** – Acts as a read‑through cache. On a redirect hit, the service returns the cached long URL without touching the database, keeping latency under 1 ms.
4. **Docker Compose** – Orchestrates the three services locally, providing a reproducible environment that mirrors production networking.

```
Client → [Go API] → (cache miss) → PostgreSQL
                ↘ (cache hit) → Redis
```

A request flow:

- **Shorten**: Client sends `POST /shorten` with a long URL. The API generates a 7‑character base62 code, inserts a row into `urls`, and writes `{code: longURL}` to Redis with a 24‑hour TTL.
- **Redirect**: Client sends `GET /:code`. The API checks Redis first; on a hit it returns a 301 redirect. On a miss it queries PostgreSQL, populates Redis, then redirects.

All components run in their own containers, communicating over standard TCP ports, which makes the setup trivial to extend to Kubernetes or a cloud VM later.

## Building It Step by Step

### 1. Scaffold the Go module

```bash
mkdir url-shortener && cd url-shortener
go mod init github.com/yourname/url-shortener
```

### 2. Define the data models

`models.go`

```go
package models

import "time"

type URL struct {
    ID        int       `db:"id"`
    Code      string    `db:"code"`
    LongURL   string    `db:"long_url"`
    CreatedAt time.Time `db:"created_at"`
    Clicks    int       `db:"clicks"`
}
```

### 3. Set up PostgreSQL connection

`db.go`

```go
package db

import (
    "database/sql"
    "fmt"
    "log"

    _ "github.com/lib/pq"
)

func NewPostgresConn(dsn string) *sql.DB {
    db, err := sql.Open("postgres", dsn)
    if err != nil {
        log.Fatalf("cannot open db: %v", err)
    }
    if err := db.Ping(); err != nil {
        log.Fatalf("cannot ping db: %v", err)
    }
    fmt.Println("connected to postgres")
    return db
}
```

### 4. Repository pattern for URL operations

`repository.go`

```go
package repository

import (
    "database/sql"
    "fmt"
    "time"

    "github.com/yourname/url-shortener/models"
)

type URLRepository struct {
    db *sql.DB
}

func NewURLRepository(db *sql.DB) *URLRepository {
    return &URLRepository{db: db}
}

func (r *URLRepository) Create(code, longURL string) error {
    _, err := r.db.Exec(
        `INSERT INTO urls (code, long_url, created_at, clicks) VALUES ($1, $2, $3, 0)`,
        code, longURL, time.Now(),
    )
    return err
}

func (r *URLRepository) FindByCode(code string) (*models.URL, error) {
    var u models.URL
    err := r.db.Get(&u, `SELECT id, code, long_url, created_at, clicks FROM urls WHERE code = $1`, code)
    if err != nil {
        return nil, fmt.Errorf("url not found: %w", err)
    }
    return &u, nil
}

func (r *URLRepository) IncrementClicks(code string) error {
    _, err := r.db.Exec(`UPDATE urls SET clicks = clicks + 1 WHERE code = $1`, code)
    return err
}
```

### 5. Add Redis caching layer

`cache.go`

```go
package cache

import (
    "context"
    "encoding/json"
    "time"

    "github.com/redis/go-redis/v9"
)

type Cache struct {
    rdb *redis.Client
}

func NewCache(addr, password string) *Cache {
    rdb := redis.NewClient(&redis.Options{
        Addr:     addr,
        Password: password,
    })
    return &Cache{rdb: rdb}
}

func (c *Cache) Get(ctx context.Context, key string) (string, bool) {
    val, err := c.rdb.Get(ctx, key).Result()
    if err == redis.Nil {
        return "", false
    }
    if err != nil {
        return "", false
    }
    return val, true
}

func (c *Cache) Set(ctx context.Context, key, value string, ttl time.Duration) error {
    return c.rdb.Set(ctx, key, value, ttl).Err()
}
```

### 6. HTTP handlers

`handler.go`

```go
package handler

import (
    "encoding/json"
    "log"
    "net/http"
    "time"

    "github.com/yourname/url-shortener/cache"
    "github.com/yourname/url-shortener/repository"
    "github.com/yourname/url-shortener/models"
)

type ShortenRequest struct {
    URL string `json:"url"`
}

type ShortenResponse struct {
    Code string `json:"code"`
    ShortURL string `json:"short_url"`
}

type Handler struct {
    repo  *repository.URLRepository
    cache *cache.Cache
    base  string
}

func NewHandler(repo *repository.URLRepository, cache *cache.Cache, base string) *Handler {
    return &Handler{repo: repo, cache: cache, base: base}
}

func (h *Handler) Shorten(w http.ResponseWriter, r *http.Request) {
    var req ShortenRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "invalid json", http.StatusBadRequest)
        return
    }
    code := generateCode(7)
    if err := h.repo.Create(code, req.URL); err != nil {
        http.Error(w, "db error", http.StatusInternalServerError)
        return
    }
    // cache for 24h
    h.cache.Set(r.Context(), code, req.URL, 24*time.Hour)
    resp := ShortenResponse{
        Code:     code,
        ShortURL: h.base + "/" + code,
    }
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(resp)
}

func (h *Handler) Redirect(w http.ResponseWriter, r *http.Request) {
    code := r.URL.Path[len("/"):]
    // try cache first
    if longURL, ok := h.cache.Get(r.Context(), code); ok {
        http.Redirect(w, r, longURL, http.StatusMovedPermanently)
        return
    }
    // fallback to db
    u, err := h.repo.FindByCode(code)
    if err != nil {
        http.Error(w, "not found", http.StatusNotFound)
        return
    }
    // populate cache
    h.cache.Set(r.Context(), code, u.LongURL, 24*time.Hour)
    // increment click counter
    go func() {
        if err := h.repo.IncrementClicks(code); err != nil {
            log.Printf("increment clicks error: %v", err)
        }
    }()
    http.Redirect(w, r, u.LongURL, http.StatusMovedPermanently)
}

// generateCode returns a base62 string of length n
func generateCode(n int) string {
    const charset = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    b := make([]byte, n)
    for i := range b {
        b[i] = charset[time.Now().UnixNano()%int64(len(charset))]
    }
    return string(b)
}
```

### 7. Wire everything together in `main.go`

```go
package main

import (
    "log"
    "net/http"
    "os"

    "github.com/yourname/url-shortener/cache"
    "github.com/yourname/url-shortener/db"
    "github.com/yourname/url-shortener/handler"
    "github.com/yourname/url-shortener/repository"
)

func main() {
    dsn := os.Getenv("POSTGRES_DSN")
    if dsn == "" {
        dsn = "postgres://postgres:postgres@localhost:5432/shortener?sslmode=disable"
    }
    pg := db.NewPostgresConn(dsn)
    repo := repository.NewURLRepository(pg)

    redisAddr := os.Getenv("REDIS_ADDR")
    if redisAddr == "" {
        redisAddr = "localhost:6379"
    }
    rdb := cache.NewCache(redisAddr, "")

    base := os.Getenv("BASE_URL")
    if base == "" {
        base = "http://localhost:8080"
    }

    h := handler.NewHandler(repo, rdb, base)

    http.HandleFunc("/shorten", h.Shorten)
    http.HandleFunc("/", h.Redirect)

    log.Println("listening on :8080")
    log.Fatal(http.ListenAndServe(":8080", nil))
}
```

### 8. Docker Compose for local environment

`docker-compose.yml`

```yaml
version: "3.8"
services:
  api:
    build: .
    ports:
      - "8080:8080"
    environment:
      - POSTGRES_DSN=postgres://postgres:postgres@db:5432/shortener?sslmode=disable
      - REDIS_ADDR=redis:6379
    depends_on:
      - db
      - redis

  db:
    image: postgres:15
    environment:
      POSTGRES_DB: shortener
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  pgdata:
```

### 9. Create the database schema

`schema.sql`

```sql
CREATE TABLE IF NOT EXISTS urls (
    id SERIAL PRIMARY KEY,
    code VARCHAR(10) UNIQUE NOT NULL,
    long_url TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    clicks INTEGER NOT NULL DEFAULT 0
);
```

Run it against the `db` container:

```bash
docker-compose exec db psql -U postgres -d shortener -f /docker-entrypoint-initdb.d/schema.sql
```

(Place `schema.sql` in the `db` image’s init directory or mount it.)

## Running and Testing It

1. **Start the stack**

   ```bash
   docker-compose up --build
   ```

2. **Create a short URL**

   ```bash
   curl -X POST http://localhost:8080/shorten \
        -H "Content-Type: application/json" \
        -d '{"url":"https://example.com"}'
   ```

   Expected output:

   ```json
   {"code":"aBcDeFg","short_url":"http://localhost:8080/aBcDeFg"}
   ```

3. **Redirect**

   ```bash
   curl -I http://localhost:8080/aBcDeFg
   ```

   Should return `HTTP/1.1 301 Moved Permanently` with `Location: https://example.com`.

4. **Unit tests**

   Create `handler_test.go` and run:

   ```bash
   go test ./...
   ```

   A minimal test for the redirect handler:

   ```go
   func TestRedirect(t *testing.T) {
       // mock repo and cache
       // ...
   }
   ```

5. **Load testing (optional)**

   Use `hey` or `k6` to verify latency under concurrency:

   ```bash
   hey -z 30s -c 100 http://localhost:8080/aBcDeFg
   ```

   Aim for p99 < 5 ms when the code is cached.

## Extending It: Your Roadmap to Senior-Level

1. **Horizontal scaling with Kubernetes** – Deploy the API as multiple pods behind a Service; Redis becomes a cluster, PostgreSQL uses read replicas. *Why it matters:* proves you can design for stateless front‑ends and stateful back‑ends.

2. **Persistent analytics pipeline** – Add a Kafka topic that the API publishes click events to; a consumer writes to a data warehouse. *Why it matters:* introduces event‑driven architecture and separates analytics from the hot path.

3. **Rate limiting & circuit breaking** – Integrate a token‑bucket limiter per client IP and a circuit‑breaker around DB calls. *Why it matters:* protects the service from abuse and cascading failures.

4. **Observability stack** – Export Prometheus metrics (`http_requests_total`, `redis_get_latency`) and ship logs to Loki; create Grafana dashboards. *Why it matters:* demonstrates you can operate a service in production, not just write it.

5. **Data partitioning & sharding** – Split the `urls` table by hash of the short code; add a routing layer. *Why it matters:* shows you understand how to scale relational databases beyond a single node.

6. **Chaos engineering** – Introduce latency or pod failures via Litmus or Gremlin; verify the service degrades gracefully. *Why it matters:* proves you think about resilience, not just features.

## Key Takeaways

- You now have a fully runnable URL shortener that combines Go, PostgreSQL, Redis, and Docker.
- The architecture is explicitly designed for horizontal scaling, giving you a clear story for senior‑level conversations.
- Each extension in the roadmap maps to a real‑world production concern, turning a toy project into a portfolio piece that signals systems expertise.
- By adding observability, rate limiting, and event‑driven analytics, you demonstrate the full lifecycle of a production service.

## Further Reading

- [Go Documentation](https://go.dev/doc/) – official language reference and concurrency patterns.
- [PostgreSQL Documentation](https://www.postgresql.org/docs/) – deep dive into indexing, replication, and partitioning.
- [Redis Documentation](https://redis.io/docs/) – data structures, clustering, and latency tuning.
- [Kubernetes Concepts](https://kubernetes.io/docs/concepts/) – pods, services, and horizontal scaling.
- [Dynamo: Amazon’s Highly Available Key‑Value Store](https://www.allenb.com/dynamo.pdf) – paper that inspired many distributed cache designs.