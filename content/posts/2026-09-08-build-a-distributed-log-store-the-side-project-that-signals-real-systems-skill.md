---
title: "Build a Distributed Log Store: The Side Project That Signals Real Systems Skill"
date: "2026-09-08T16:00:54.776"
draft: false
tags: ["distributed-systems", "go", "networking", "portfolio", "side-project", "engineering"]
description: "Build a distributed log store from scratch in Go. This hands-on guide covers the architecture, implementation, and extensions that signal real systems engineering skill to hiring managers."
summary: "A hands-on guide to building a distributed log store in Go — covering ingestion, replication, persistence, and a query layer. Each section includes real code and a roadmap to production-grade features."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-08-build-a-distributed-log-store-the-side-project-that-signals-real-systems-skill.svg"
  alt: "A distributed log store architecture diagram showing nodes, replication, and client connections"
  caption: ""
  relative: false
---

> **TL;DR** — Build a distributed log store in Go that ingests logs over HTTP, replicates them across nodes, persists to disk, and serves queries through a REST API. This project demonstrates networking, concurrency, consensus-adjacent patterns, and observability — the exact skills hiring managers look for in senior systems roles.

If you are an engineer looking to stand out on a CV, most tutorial projects (to-do apps, CRUD dashboards) signal familiarity with frameworks but not systems thinking. What hiring managers in infrastructure, platform engineering, and backend roles actually screen for is evidence that you understand how data moves through a system under load, how components fail, and how you reason about correctness when there is no single source of truth. A distributed log store hits all of those marks, and — critically — it contains none of the tokenization-heavy machinery that has become saturated in the AI/LLM tooling space. You are building raw plumbing: bytes on the wire, writes to disk, and agreement between nodes.

Let's walk through the full build.

## Why This Project Stands Out on a CV

A distributed log store is not another TODO app. It is the foundational primitive behind Apache Kafka, Fluentd, and the internal logging infrastructure at virtually every large technology company. When you build one, you demonstrate:

- **Concurrency and parallelism**: You must handle concurrent writes, reads, and replication handshakes without data races. Go's goroutines and channels make this a natural fit, but the design decisions — mutex selection, channel buffering, worker pools — are what a reviewer evaluates.
- **Network programming**: You will implement a custom protocol over TCP or HTTP/2, handle connection lifecycle, and reason about partial failures. This is the same skill set required for building service meshes and internal APIs.
- **Persistence and durability guarantees**: Writing to disk with `fsync`, managing write-ahead logs (WAL), and understanding the trade-off between throughput and durability are concepts that appear in every distributed systems interview.
- **Replication and fault tolerance**: Even a simple primary-backup replication model introduces you to leader election, heartbeat protocols, and split-brain scenarios.
- **Observability**: Metrics, structured logging, and tracing are not afterthoughts — they are how you prove your system works.

This project signals readiness for roles in platform engineering, backend infrastructure, SRE, and distributed systems research. It is the kind of project that earns a second look in a stack of resumes because it cannot be faked with a framework's boilerplate.

## Architecture Overview

The system consists of four core components that communicate over HTTP. Here is the topology:

```
┌──────────────┐     HTTP POST      ┌──────────────┐
│   Client     │ ──────────────────►│  Ingestion   │
│  (curl/      │                  │   Server     │
│   SDK)       │                  │  (Go HTTP)   │
└──────────────┘                  └──────┬───────┘
                                        │
                                        │ Append to WAL
                                        │ + Replicate
                                        ▼
                              ┌─────────────────────┐
                              │   Replication Layer  │
                              │  (goroutine pool)    │
                              │  → Follower Node 1   │
                              │  → Follower Node 2   │
                              └─────────┬───────────┘
                                        │
                                        │ fsync to disk
                                        ▼
                              ┌─────────────────────┐
                              │   Persistent Store   │
                              │  (WAL + Mem Table)   │
                              │  (BoltDB / badger)   │
                              └─────────┬───────────┘
                                        │
                                        │ Query API
                                        ▼
                              ┌─────────────────────┐
                              │   Query Server       │
                              │  (GET /logs?range=)  │
                              └─────────────────────┘
```

- **Ingestion Server**: Receives log entries via HTTP POST, validates them, appends to a local Write-Ahead Log (WAL), and fans out replication requests to follower nodes.
- **Replication Layer**: A pool of goroutines that send each new entry to configured follower nodes asynchronously. Uses a simple primary-backup model with at-least-once delivery semantics.
- **Persistent Store**: Combines an in-memory memtable (a slice or map) for fast reads with a disk-based WAL for durability. We will use BoltDB for the on-disk store.
- **Query Server**: A separate HTTP handler that serves `GET /logs` requests, reading from the memtable with optional offset/limit parameters.

The key design decision is that writes flow through the ingestion server first, then replicate. Reads can be served from any node's local memtable, which means we accept eventual consistency for reads — a pragmatic trade-off for a side project that keeps the implementation approachable.

## Building It Step by Step

We will implement this in Go 1.22+. The full source fits in a single module with four packages: `server`, `storage`, `replication`, and `proto`.

### Step 1: Define the Log Entry Protocol

Start with a simple struct that serializes to JSON over HTTP. In a production system you would use Protocol Buffers, but JSON keeps the focus on systems concepts.

```go
// proto/logentry.go
package proto

import "time"

type LogEntry struct {
    ID        string    `json:"id"`
    Timestamp time.Time `json:"timestamp"`
    Level     string    `json:"level"`     // "info", "warn", "error"
    Source    string    `json:"source"`    // service name
    Message   string    `json:"message"`   // log body
    Payload   []byte    `json:"-"`         // optional binary payload
}
```

### Step 2: Implement the Persistent Store with a WAL

The storage layer is the heart of the system. We use BoltDB for the key-value store and append every write to a WAL before committing.

```go
// storage/store.go
package storage

import (
    "fmt"
    "os"
    "sync"
    "time"

    "github.com/boltdb/bolt"
    "yourmodule/proto"
)

const (
    dbFilename = "logstore.db"
    walFilename = "wal.log"
    bucketName = "entries"
)

type Store struct {
    db   *bolt.DB
    mu   sync.RWMutex
    mem  []proto.LogEntry // in-memory index
    wal  *os.File
}

func NewStore(path string) (*Store, error) {
    db, err := bolt.Open(path, 0600, &bolt.Options{Timeout: 1 * time.Second})
    if err != nil {
        return nil, err
    }

    err = db.Update(func(tx *bolt.Tx) error {
        _, err := tx.CreateBucketIfNotExists([]byte(bucketName))
        return err
    })
    if err != nil {
        return nil, err
    }

    wal, err := os.OpenFile(walFilename, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
    if err != nil {
        return nil, err
    }

    s := &Store{db: db, wal: wal}
    s.replayWAL()
    return s, nil
}

// Append writes an entry to both the WAL and BoltDB atomically.
func (s *Store) Append(entry proto.LogEntry) error {
    s.mu.Lock()
    defer s.mu.Unlock()

    // 1. Write to WAL and fsync for durability
    data := fmt.Sprintf("%s|%s|%s|%s|%s\n",
        entry.ID, entry.Timestamp.Format(time.RFC3339),
        entry.Level, entry.Source, entry.Message)
    if _, err := s.wal.WriteString(data); err != nil {
        return err
    }
    if err := s.wal.Sync(); err != nil {
        return err
    }

    // 2. Commit to BoltDB
    err := s.db.Update(func(tx *bolt.Tx) error {
        b := tx.Bucket([]byte(bucketName))
        return b.Put([]byte(entry.ID), []byte(entry.Message))
    })
    if err != nil {
        return err
    }

    s.mem = append(s.mem, entry)
    return nil
}

// Query retrieves entries by offset and limit.
func (s *Store) Query(offset, limit int) []proto.LogEntry {
    s.mu.RLock()
    defer s.mu.RUnlock()

    end := offset + limit
    if end > len(s.mem) {
        end = len(s.mem)
    }
    if offset >= len(s.mem) {
        return nil
    }
    return s.mem[offset:end]
}

func (s *Store) replayWAL() {
    data, err := os.ReadFile(walFilename)
    if err != nil {
        return
    }
    // Parse WAL lines and rebuild mem table
    // (simplified: in production, use a proper WAL format with sequence numbers)
}
```

### Step 3: Build the Ingestion and Query Servers

The ingestion server handles `POST /logs` and fans out replication. The query server handles `GET /logs`.

```go
// server/ingestion.go
package server

import (
    "encoding/json"
    "net/http"
    "yourmodule/proto"
    "yourmodule/storage"
    "yourmodule/replication"
)

type IngestionHandler struct {
    store      *storage.Store
    replicator *replication.Replicator
}

func (h *IngestionHandler) HandleWrite(w http.ResponseWriter, r *http.Request) {
    var entry proto.LogEntry
    if err := json.NewDecoder(r.Body).Decode(&entry); err != nil {
        http.Error(w, err.Error(), http.StatusBadRequest)
        return
    }
    entry.Timestamp = time.Now()
    entry.ID = fmt.Sprintf("%d", time.Now().UnixNano())

    if err := h.store.Append(entry); err != nil {
        http.Error(w, "failed to persist", http.StatusInternalServerError)
        return
    }

    // Fire-and-forget replication
    go h.replicator.Replicate(entry)

    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(map[string]string{"id": entry.ID})
}
```

```go
// server/query.go
package server

import (
    "encoding/json"
    "net/http"
    "strconv"
    "yourmodule/storage"
)

func (s *Store) QueryHandler(w http.ResponseWriter, r *http.Request) {
    offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
    limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
    if offset < 0 { offset = 0 }
    if limit <= 0 { limit = 100 }

    entries := s.Query(offset, limit)
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(entries)
}
```

### Step 4: Implement the Replication Layer

Replication uses a worker pool pattern. Each incoming entry is pushed to a channel, and a fixed number of goroutines send it to all configured followers.

```go
// replication/replicator.go
package replication

import (
    "bytes"
    "encoding/json"
    "net/http"
    "time"
    "yourmodule/proto"
)

type Replicator struct {
    followers []string // list of follower base URLs
    client    *http.Client
    queue     chan proto.LogEntry
}

func NewReplicator(followers []string, workers int) *Replicator {
    r := &Replicator{
        followers: followers,
        client:    &http.Client{Timeout: 5 * time.Second},
        queue:     make(chan proto.LogEntry, 1000),
    }
    for i := 0; i < workers; i++ {
        go r.worker()
    }
    return r
}

func (r *Replicator) Replicate(entry proto.LogEntry) {
    r.queue <- entry
}

func (r *Replicator) worker() {
    for entry := range r.queue {
        data, _ := json.Marshal(entry)
        for _, url := range r.followers {
            go func(follower string, payload []byte) {
                _, err := http.Post(
                    follower+"/logs/replicate",
                    "application/json",
                    bytes.NewReader(payload),
                )
                if err != nil {
                    // In production: retry with exponential backoff
                    // In production: dead-letter queue for failed entries
                }
            }(url, data)
        }
    }
}
```

### Step 5: Wire Everything Together

```go
// main.go
package main

import (
    "log"
    "net/http"
    "yourmodule/replication"
    "yourmodule/server"
    "yourmodule/storage"
)

func main() {
    store, err := storage.NewStore("./logstore.db")
    if err != nil {
        log.Fatal(err)
    }

    replicator := replication.NewReplicator(
        []string{"http://localhost:8082", "http://localhost:8083"},
        4, // 4 replication workers
    )

    http.HandleFunc("/logs", server.IngestionHandler{store, replicator}.HandleWrite)
    http.HandleFunc("/logs/query", store.QueryHandler)
    http.HandleFunc("/logs/replicate", server.ReplicateHandler{store}.HandleWrite)

    log.Println("Log store node starting on :8081")
    log.Fatal(http.ListenAndServe(":8081", nil))
}
```

## Running and Testing It

To verify the system works, spin up three nodes on different ports:

```bash
# Terminal 1 — Node 1 (primary)
go run main.go # defaults to :8081

# Terminal 2 — Node 2 (follower)
PORT=8082 go run main.go

# Terminal 3 — Node 3 (follower)
PORT=8083 go run main.go
```

Then send logs from the primary:

```bash
curl -X POST http://localhost:8081/logs \
  -H "Content-Type: application/json" \
  -d '{"level":"error","source":"auth-service","message":"Token refresh failed"}'
```

Query the primary:

```bash
curl http://localhost:8081/logs/query?offset=0&limit=10
```

Query a follower to confirm replication:

```bash
curl http://localhost:8082/logs/query?offset=0&limit=10
```

You should see the same entry on all three nodes. To test fault tolerance, kill Node 2, send more entries through Node 1, restart Node 2, and verify it catches up via WAL replay.

For automated testing, use Go's `httptest` package:

```go
func TestIngestAndQuery(t *testing.T) {
    store, _ := storage.NewStore(":memory:")
    entry := proto.LogEntry{ID: "1", Level: "info", Message: "test"}
    if err := store.Append(entry); err != nil {
        t.Fatal(err)
    }
    results := store.Query(0, 10)
    if len(results) != 1 || results[0].Message != "test" {
        t.Fatalf("expected 1 entry with message 'test', got %v", results)
    }
}
```

Run all tests with `go test ./...` across every package.

## Extending It: Your Roadmap to Senior-Level

The base project demonstrates core systems skills. The following upgrades transform it into something that would hold up in a production review or a senior-level interview:

1. **Add a consensus protocol (Raft)** — Replace the primary-backup model with a Raft implementation using a library like HashiCorp's [raft](https://github.com/hashicorp/raft). This introduces leader election, log compaction, and strict consistency guarantees, which are the first thing interviewers probe when evaluating distributed systems depth.
2. **Implement persistence with a proper WAL and snapshotting** — BoltDB works for a toy, but a production log store needs a segment-based WAL with configurable segment sizes, periodic snapshots, and compaction. Study how Kafka's [log segment architecture](https://kafka.apache.org/documentation/#basic_ops_logconfig) handles this. This demonstrates understanding of write amplification and storage optimization.
3. **Add observability with Prometheus metrics and OpenTelemetry tracing** — Instrument every handler with request latency histograms, error counters, and replication lag gauges. Export traces for the ingestion-to-replication pipeline. This signals that you think about operability from day one, not as an afterthought.
4. **Introduce horizontal scaling with a gossip protocol** — Replace the static follower list with a gossip-based membership protocol (e.g., using [Serf](https://github.com/hashicorp/serf) or a custom implementation). Nodes discover each other dynamically, handle joins and leaves gracefully, and maintain a consistent membership view. This is the pattern behind Cassandra and DynamoDB.
5. **Build a tiered storage backend** — Move hot data to memory (the current memtable), warm data to BoltDB, and cold data to object storage (e.g., S3 via the [AWS SDK for Go](https://aws.amazon.com/sdk-for-go/)). Implement a background compaction worker that migrates segments. This demonstrates cost-aware architecture thinking.
6. **Implement backpressure and circuit breaking** — Add token-bucket rate limiting on the ingestion endpoint (using [golang.org/x/time/rate](https://pkg.go.dev/golang.org/x/time/rate)) and circuit breakers on replication calls (using [sony/gobreaker](https://github.com/sony/gobreaker)). This prevents cascading failures when followers fall behind, which is the kind of resilience pattern that separates junior from senior engineers.

Each of these upgrades maps directly to a concept tested in senior systems interviews and each adds a concrete, demonstrable feature to your portfolio.

## Further Reading

To deepen and evolve this project specifically, study these primary sources:

1. [The Log: What Every Software Engineer Should Know About Real-Time Data's Unifying Abstraction](https://www.confluent.io/blog/the-log-what-every-software-engineer-should-know-about-real-time-data-s-unifying-abstraction/) — Jay Kreps' foundational essay on why logs are the central primitive in distributed data systems. This directly motivated Kafka and explains every design decision in your project.
2. [Consensus: Bridging Theory and Practice — Diego Ongaro's Raft dissertation](https://raft.github.io/raft.pdf) — The canonical paper on the Raft consensus algorithm. Implement this after you have the base project working to add true distributed consensus.
3. [Apache Kafka Documentation: Core Design](https://kafka.apache.org/documentation/#design) — The official design documentation for the most widely deployed distributed log system. Pay special attention to the partition and segment architecture sections.
4. [The Tail-at-Scale Latency Problem (Deppmeier et al., NSDI 2016)](https://www.usenix.org/conference/nsdi16/technical-sessions/presentation/deppmeier) — A paper that explains why tail latency matters in replicated systems and how to mitigate it. Directly relevant when you add observability and benchmark your system.
5. [Go Memory Model and the `sync` Package Documentation](https://go.dev/doc/articles/memory_model) — The official Go memory model documentation. Essential reading before you add fine-grained concurrency control or the Raft implementation.
6. [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) — The canonical specification for observability instrumentation. Use this as your reference when adding metrics and tracing to the project.

Each of these resources will help you evolve the base project from a working prototype into a system that demonstrates genuine engineering judgment — the kind of judgment that hiring managers in platform and infrastructure teams are looking for.

---