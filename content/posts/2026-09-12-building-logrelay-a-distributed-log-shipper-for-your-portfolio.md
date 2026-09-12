---
title: "Building LogRelay: A Distributed Log Shipper for Your Portfolio"
date: "2026-09-12T02:01:30.964"
draft: false
tags: ["systems-engineering", "go", "networking", "portfolio", "distributed-systems"]
description: "A hands-on guide to building LogRelay, a distributed log shipper that demonstrates systems skills like backpressure, batching, and persistence to hiring managers."
summary: "Build LogRelay, a distributed log shipper that signals real systems engineering skills. Learn how to implement backpressure, batching, and persistence in Go."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-building-logrelay-a-distributed-log-shipper-for-your-portfolio.svg"
  alt: "A diagram of a distributed log shipper architecture"
  caption: ""
  relative: false
---

> **TL;DR** — Build LogRelay, a distributed log shipper in Go that handles network ingestion, batching, and persistent storage. It demonstrates backpressure, fault tolerance, and systems architecture—exactly what hiring managers look for on a CV.

We are drowning in CRUD applications. Every junior developer builds a to-do app or a blog platform, and by the time they hit the interview stage, those projects blur into a meaningless sea of boilerplate. If you want to signal real systems skill to hiring managers, you need a project that grapples with the messy realities of distributed computing: network failures, resource contention, and data durability. 

LogRelay is a distributed log shipper designed to solve exactly this problem. It ingests log lines over TCP, buffers them with strict backpressure, batches them for efficiency, and persists them to a Write-Ahead Log (WAL) before forwarding them to a downstream system like Kafka or Elasticsearch. It is practical, deeply technical, and entirely buildable in a weekend.

## Why This Project Stands Out on a CV

A log shipper is the plumbing of modern observability. By building one, you demonstrate proficiency in several high-value domains that CRUD apps simply cannot touch.

*   **Network Programming and the OSI Model:** You are working directly with TCP sockets, handling connection timeouts, and managing byte streams. This proves you understand how data actually moves across a network, rather than just calling an HTTP client.
*   **Backpressure and Concurrency:** If your downstream system slows down, your shipper must not crash or drop data. Implementing a bounded buffer with Go channels demonstrates a sophisticated understanding of concurrency and flow control.
*   **Data Durability and the WAL:** Writing to a Write-Ahead Log before acknowledging receipt to the client shows you respect the CAP theorem and understand how systems like Kafka and Postgres guarantee fault tolerance.
*   **Roles It Signals:** This project directly signals readiness for roles like Backend Engineer, SRE, or Platform Engineer. It shows you can architect the infrastructure that keeps large-scale applications observable and resilient.

## Architecture Overview

LogRelay is designed around a pipeline pattern, where data flows through discrete, bounded stages. This decouples the network ingestion layer from the persistence layer, allowing each to scale and fail independently. 

The architecture consists of four primary components:

1.  **TCP Receiver:** Listens for incoming connections on a configured port. It reads lines of text, parses them, and pushes them into a buffered channel.
2.  **Backpressure Buffer:** A fixed-capacity Go channel. If the downstream system is slow and the channel fills up, the receiver blocks, applying backpressure to the network clients. This prevents out-of-memory crashes.
3.  **Batcher and Persistor:** A background worker drains the buffer channel, aggregates logs into batches, and writes them to a local WAL file. This ensures that even if the process crashes, no data is lost.
4.  **Outbound Sender:** A separate worker reads from the WAL and forwards the batched logs to a downstream sink, such as a Kafka broker or standard output.

```text
[Client] -> TCP -> [Receiver] -> [Buffered Channel] -> [Batcher] -> [WAL File] -> [Sender] -> [Downstream (Kafka/Stdout)]
```

## Building It Step by Step

We will implement the core logic of LogRelay in Go. The project relies on the standard library for networking and file I/O, keeping the focus on systems concepts rather than framework abstractions.

### Step 1: The TCP Receiver
The receiver is responsible for accepting connections and reading bytes. We use `net.Listen` to create a TCP socket and `bufio.Scanner` to parse incoming stream data into discrete lines. We must set a read deadline to prevent goroutine leaks from idle connections.

```go
package main

import (
    "bufio"
    "net"
    "time"
)

type LogEvent struct {
    Timestamp time.Time
    Payload   string
}

func startReceiver(addr string, ch chan<- LogEvent) {
    ln, err := net.Listen("tcp", addr)
    if err != nil {
        panic(err)
    }
    defer ln.Close()

    for {
        conn, err := ln.Accept()
        if err != nil {
            continue
        }
        go handleConnection(conn, ch)
    }
}

func handleConnection(conn net.Conn, ch chan<- LogEvent) {
    defer conn.Close()
    conn.SetReadDeadline(time.Now().Add(30 * time.Second))
    
    scanner := bufio.NewScanner(conn)
    for scanner.Scan() {
        event := LogEvent{
            Timestamp: time.Now(),
            Payload:   scanner.Text(),
        }
        // Apply backpressure: blocks if channel is full
        ch <- event 
        conn.SetReadDeadline(time.Now().Add(30 * time.Second))
    }
}
```

### Step 2: The Batcher and WAL Persistor
The batcher drains the channel, groups events, and writes them to a file. We use a `sync.Mutex` to ensure writes to the WAL are atomic, and a `bufio.Writer` to minimize disk I/O syscalls.

```go
package main

import (
    "os"
    "sync"
    "time"
)

type WAL struct {
    file *os.File
    mu   sync.Mutex
}

func newWAL(path string) (*WAL, error) {
    f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
    if err != nil {
        return nil, err
    }
    return &WAL{file: f}, nil
}

func (w *WAL) WriteBatch(events []LogEvent) error {
    w.mu.Lock()
    defer w.mu.Unlock()
    
    // In production, you'd use a bufio.Writer here
    for _, e := range events {
        _, err := w.file.WriteString(e.Timestamp.Format(time.RFC3339) + " " + e.Payload + "\n")
        if err != nil {
            return err
        }
    }
    return w.file.Sync() // Ensure data hits the disk
}

func batcher(ch <-chan LogEvent, wal *WAL) {
    var batch []LogEvent
    ticker := time.NewTicker(500 * time.Millisecond)
    defer ticker.Stop()

    for {
        select {
        case event := <-ch:
            batch = append(batch, event)
            if len(batch) >= 100 {
                wal.WriteBatch(batch)
                batch = nil
            }
        case <-ticker.C:
            if len(batch) > 0 {
                wal.WriteBatch(batch)
                batch = nil
            }
        }
    }
}
```

### Step 3: The Outbound Sender
The sender reads from the WAL and forwards the data. In a production system, this would connect to Kafka using the `sarama` library. For this guide, we will simulate the sender by reading the WAL and printing to stdout.

```go
package main

import (
    "bufio"
    "fmt"
    "os"
)

func sender(walPath string) {
    f, err := os.Open(walPath)
    if err != nil {
        panic(err)
    }
    defer f.Close()

    scanner := bufio.NewScanner(f)
    for scanner.Scan() {
        // Simulate sending to Kafka or Elasticsearch
        fmt.Println("Sending to downstream:", scanner.Text())
    }
}
```

## Running and Testing It

To prove LogRelay works, you need to verify that data traverses the pipeline without loss and that backpressure actually functions.

1.  **Initialize the project:** Create a `main.go` file and wire the components together. Instantiate the WAL, start the batcher, and start the receiver on port `8080`.
2.  **Generate test traffic:** Use `netcat` to pipe a stream of log lines into your shipper.
    ```bash
    seq 1 1000 | nc localhost 8080
    ```
3.  **Verify persistence:** Check the WAL file to ensure all 1000 lines were written to disk.
    ```bash
    wc -l ./logrelay.wal
    ```
4.  **Test backpressure:** Open a second terminal and start sending data very fast. Then, in a third terminal, stop the batcher process. The `nc` command should hang, demonstrating that the receiver is blocking on the full channel rather than crashing with an out-of-memory error.

## Extending It: Your Roadmap to Senior-Level

A working prototype is great, but a senior engineer knows how to evolve a toy into a production-grade system. Here are six concrete upgrades that will take LogRelay from a portfolio piece to a genuine infrastructure component.

1.  **Implement mTLS for Transport Security:** Wrap the TCP connections with TLS using Go's `crypto/tls` package. *Why it matters:* Unencrypted log streams are a massive security liability; this proves you take data-in-transit seriously.
2.  **Add Horizontal Scaling with Consistent Hashing:** Modify the receiver to hash log topics or sources and route them to specific shards. *Why it matters:* A single receiver is a bottleneck; this demonstrates how to scale stateful network services.
3.  **Integrate Prometheus Metrics for Observability:** Expose a `/metrics` endpoint using the `prometheus/client_golang` library to track buffer depth, batch sizes, and network latency. *Why it matters:* You cannot fix what you cannot measure; this shows you understand production observability.
4.  **Implement Raft Consensus for Fault Tolerance:** Use an embedded library like `hashicorp/raft` to replicate the WAL across multiple nodes. *Why it matters:* Single points of failure are unacceptable in critical logging pipelines; this proves you can build highly available systems.
5.  **Add CPU and Memory Profiling with `pprof`:** Expose the `net/http/pprof` endpoints to analyze goroutine blocking and memory allocations under load. *Why it matters:* Performance optimization requires data, not guesses; this shows you can debug resource contention in production.
6.  **Implement Schema Registry for Log Payloads:** Validate incoming JSON or Protobuf payloads against a schema before writing to the WAL. *Why it matters:* Dirty data breaks downstream consumers; this demonstrates a commitment to data quality and contract enforcement.

## Key Takeaways

*   Building a distributed log shipper forces you to confront the realities of network I/O, concurrency, and data durability, making it a far superior portfolio piece than a standard web app.
*   Backpressure is not just a theoretical concept; it is a necessary mechanism to prevent cascading failures and out-of-memory crashes in resource-constrained systems.
*   A Write-Ahead Log (WAL) is the foundational pattern for ensuring data durability across system crashes, a concept used by everything from Postgres to Kafka.
*   The difference between a toy project and a production system is the addition of observability, security, and fault tolerance.
*   Naming concrete tools like Go, TCP sockets, and WALs in your project description signals to hiring managers that you understand the OSI model and modern infrastructure.

## Further Reading

To deepen your understanding of the systems concepts behind LogRelay, study the primary sources and canonical documentation for the technologies involved.

*   [RFC 5424: The Syslog Protocol](https://datatracker.ietf.org/doc/html/rfc5424) — The foundational standard for structured log messaging, which informs how modern shippers format and transport data.
*   [Kafka: Design](https://kafka.apache.org/documentation/#design) — The official Apache Kafka documentation on distributed log architecture, batching, and the Write-Ahead Log.
*   [The Go Blog: Contexts and Cancelation](https://go.dev/blog/context) — A deep dive into how Go manages concurrency and cancellation, which is essential for preventing goroutine leaks in network servers.
*   [Vector: A High-Performance Observability Data Pipeline](https://vector.dev/) — The open-source project by DataDog that demonstrates how to build a production-grade log shipper using Rust, offering a contrasting architectural perspective.