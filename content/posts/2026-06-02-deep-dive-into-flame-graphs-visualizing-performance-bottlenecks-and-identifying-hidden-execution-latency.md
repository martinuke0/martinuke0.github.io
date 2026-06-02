---
title: "Deep Dive into Flame Graphs: Visualizing Performance Bottlenecks and Identifying Hidden Execution Latency"
date: "2026-06-02T02:00:43.492"
draft: false
tags: ["flamegraphs", "performance", "profiling", "linux", "observability"]
description: "Explore how flame graphs turn raw stack samples into intuitive visualizations, reveal hidden latency, and guide concrete performance fixes in production."
summary: "A practical guide that walks engineers through generating, interpreting, and operationalizing flame graphs for real‑world systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-06-02-deep-dive-into-flame-graphs-visualizing-performance-bottlenecks-and-identifying-hidden-execution-latency.svg"
  alt: "A colorful flame graph rendered from a high‑resolution CPU profile."
  caption: ""
  relative: false
---

> **TL;DR** — Flame graphs turn millions of stack samples into a single, color‑coded image that spots hot paths and hidden latency at a glance. By automating perf → stack collapse → SVG generation, you can pinpoint bottlenecks in Kafka brokers, Postgres queries, or any latency‑critical service within minutes.

Performance engineering is often described as “finding a needle in a haystack.” In practice, the haystack is a massive collection of stack traces, CPU counters, and I/O timestamps. Flame graphs give you a heat‑map of that haystack, letting you see the hottest code paths first. This post walks through the theory, the tooling (Linux perf, Brendan Gregg’s scripts, and open‑source alternatives), how to embed the pipeline into CI/CD, and how to read the resulting SVGs against real production workloads such as Kafka, Airflow, and PostgreSQL.

## What Is a Flame Graph?

A flame graph is a two‑dimensional visualization of stack trace samples:

| Axis | Meaning |
|------|---------|
| **X‑axis** | Cumulative width of all samples that share the same call stack prefix. Wider rectangles = more time spent. |
| **Y‑axis** | Stack depth, with leaf functions at the bottom and callers above. The graph “flames” upward, hence the name. |

The concept was popularized by Brendan Gregg in 2010 and has since become the de‑facto standard for CPU‑bound profiling, latency analysis, and even JavaScript runtime debugging. The key insight is *aggregation*: instead of showing each individual sample, the graph merges identical prefixes, which compresses millions of frames into a few hundred rectangles.

### Why Flame Graphs Beat Traditional Call Graphs

* **Scalability** – A call graph with 10 k nodes quickly becomes unreadable; a flame graph keeps the visual density low because identical stacks collapse.
* **Latency‑First View** – The width directly corresponds to time spent, so the “hot” code is obvious without counting edges.
* **Cross‑Language Compatibility** – As long as you can produce a list of `function;caller;…` lines, the same rendering pipeline works for C, Go, Java, Rust, or Node.js.

## Generating Flame Graphs with Linux perf

Linux perf is the most common source of raw samples on Linux servers. The classic workflow is:

1. **Record** a perf session.
2. **Convert** the binary format to a collapsed stack format.
3. **Render** the collapsed stacks into an SVG.

Below is a minimal Bash script that you can drop into a CI job or an on‑call runbook.

```bash
#!/usr/bin/env bash
set -euo pipefail

# 1️⃣ Record 10 seconds of CPU samples for the target PID.
TARGET_PID=$1
OUTPUT_DIR=${2:-/tmp/flamegraph}
mkdir -p "$OUTPUT_DIR"

perf record -F 99 -p "$TARGET_PID" -g --output "$OUTPUT_DIR/perf.data" -- sleep 10

# 2️⃣ Convert to collapsed stacks (requires Brendan Gregg's stackcollapse-perf.pl)
stackcollapse-perf.pl "$OUTPUT_DIR/perf.data" > "$OUTPUT_DIR/collapsed.txt"

# 3️⃣ Render the SVG (requires flamegraph.pl)
flamegraph.pl "$OUTPUT_DIR/collapsed.txt" > "$OUTPUT_DIR/flamegraph.svg"

echo "Flame graph written to $OUTPUT_DIR/flamegraph.svg"
```

> **Note:** The script assumes `stackcollapse-perf.pl` and `flamegraph.pl` are on your `$PATH`. Both are part of the [FlameGraph repository](https://github.com/brendangregg/FlameGraph).

### Adding Context: JIT and Java

For JVM workloads you’ll often need `perf script -F +pid,tid,comm,ip,sym` combined with `jstack` or `async-profiler`. The async‑profiler tool can output directly in collapsed format, bypassing the Perl step:

```bash
async-profiler -d 30 -f /tmp/profile.svg -o flamegraph -e cpu <pid>
```

This produces a ready‑to‑publish SVG, which is handy for on‑demand troubleshooting of microservices written in Java or Kotlin.

## Architecture of a Flame Graph Pipeline

Large organizations rarely run flame‑graph generation manually. Instead, they embed it into an observability stack that can:

* **Trigger** on alert (e.g., latency > 95th percentile for Kafka broker).
* **Collect** stack samples from the affected node.
* **Store** collapsed stacks in a time‑series bucket.
* **Render** SVGs on demand for engineers.

Below is a high‑level diagram (described in text for readability):

```
[Alert Manager] ──► [Job Scheduler (K8s CronJob)] ──► [Collector Pod]
        │                                          │
        ▼                                          ▼
   [Prometheus]                               [perf record]
        │                                          │
        ▼                                          ▼
   [Alert] ──► [Sidecar] ──► [stackcollapse] ──► [Object Store (S3)]
                                                │
                                                ▼
                                         [flamegraph service]
                                                │
                                                ▼
                                          [Web UI / Slack]
```

* **Alert Manager** (Prometheus) fires when a latency SLO breaches.
* **Job Scheduler** creates a short‑lived pod that runs `perf record` against the offending process.
* **Sidecar** streams the raw `perf.data` to a central collector, which runs the collapse script.
* **Object Store** holds the collapsed text for later replay or historical comparison.
* **Flamegraph Service** renders SVGs on request, caching them for fast UI display.

### Production Considerations

| Concern | Mitigation |
|---------|------------|
| **Overhead** – `perf` adds ~2–5 % CPU at 99 Hz sampling. | Use adaptive sampling: higher frequency only when alerts fire. |
| **Security** – Raw binaries expose symbols. | Strip symbols in production builds, keep a symbol server for internal rendering only. |
| **Data Retention** – Collapsed stacks are small (<100 KB) but can accumulate. | Rotate after 30 days, store only for incidents that cross the SLO threshold. |

## Interpreting the Visuals: Common Patterns

Once you have an SVG, the real work begins. Below are the most frequent shapes you’ll encounter, with concrete examples from production systems.

### 1. Wide Bottom‑Level Boxes (Leaf‑Heavy Hotspots)

**What it means:** The bulk of time is spent inside a single function that never calls deeper code. Typical for tight loops or system calls.

**Example:** In a Kafka broker, a `fetchRequest` handler that repeatedly calls `ByteBuffer.getInt()` can dominate the graph if a consumer is throttled.

**Action:** Profile the leaf function directly; often a micro‑optimisation (e.g., using `ByteBuffer.getIntLE` or a pooled buffer) yields measurable latency reduction.

### 2. Tall Stacks with a Narrow Base (Deep Call Chains)

**What it means:** Latency is distributed across many layers; the base (root) may be a generic framework method.

**Example:** Airflow’s `DagRun.execute` → `TaskInstance.run` → `PythonOperator.execute` → user‑defined function. If the user function is slow, the flame graph will show a narrow “airflow” column with a wide leaf at depth 4.

**Action:** Insert tracing (OpenTelemetry) at the narrow base to isolate which sub‑task contributes most; consider parallelizing independent tasks.

### 3. Multiple Parallel “Flames” of Similar Width

**What it means:** Several code paths consume comparable time. This is a sign of load‑balancing or contention.

**Example:** A PostgreSQL query planner may dispatch to multiple worker processes that each execute a similar sub‑plan. The flame graph shows several equally wide rectangles labeled `ExecEvalExpr`.

**Action:** Look for shared resources (locks, LRU caches). Optimising a single path won’t help; you need to address the contention point.

### 4. “Red” Color Hotspots (if using color‑by‑self‑time)

Some flame‑graph generators color by self‑time, highlighting functions that spend time *alone*. A red hotspot often indicates a function that’s both CPU‑intensive and not delegating work elsewhere.

**Example:** A custom encryption routine in a Go microservice that performs per‑request RSA decryption. The red rectangle will be labeled `crypto/rsa.decrypt`.

**Action:** Offload to a hardware security module (HSM) or replace RSA with an elliptic‑curve algorithm.

## Real‑World Case Studies

### Kafka Broker Under Heavy Produce Load

**Scenario:** A Kafka cluster experiences 150 ms produce latency spikes during peak ingest. The alert triggers a flame‑graph job targeting the `kafka.Kafka` process.

**Findings:**
* The bottom‑most wide rectangle was `ByteBuffer.putLong`, called inside `ReplicaManager.appendToLocalLog`.
* A secondary flame showed `LogSegment.append` with a narrow base but significant width, indicating disk I/O throttling.

**Resolution Steps:**
1. Switched the JVM’s `-XX:ParallelGCThreads` from 2 to 8, reducing GC pause time (validated by a separate GC‑log flame graph).
2. Enabled `log.dirs` on faster SSDs, shaving ~30 ms off the `LogSegment.append` flame.
3. Added a throttling guard in the producer client to batch messages, reducing the call frequency to `ByteBuffer.putLong`.

**Result:** 95th‑percentile latency dropped from 150 ms to 42 ms, and the flame graph after changes showed a dramatically smaller `ByteBuffer` rectangle.

### PostgreSQL Query with Unexpected CPU Usage

**Scenario:** A reporting query that joins three large tables spikes CPU to 90 % on a primary replica for 5 minutes every night.

**Flame Graph Insights:**
* The top flame was `ExecHashJoin` (wide), with a deep sub‑stack `ExecEvalExpr` repeatedly evaluating a user‑defined PL/pgSQL function.
* The PL/pgSQL function performed a `SELECT` inside a loop—an N+1 query pattern.

**Fix:**
* Refactored the function to a set‑based query, eliminating the inner SELECT.
* Added a materialized view refreshed nightly.

**Outcome:** CPU usage fell to <20 %, and the flame graph post‑fix displayed a thin `ExecHashJoin` flame with no deep sub‑stacks.

### Go Microservice with Goroutine Contention

**Scenario:** A Go‑based payment processor reports intermittent 200 ms request latency despite low overall CPU.

**Approach:** Used `go tool pprof -http=:8080` to generate a flame graph of goroutine stacks.

**Key Observation:** A wide rectangle labeled `runtime.gopark` appeared at depth 3, indicating many goroutines blocked on a channel.

**Root Cause:** A single worker goroutine handling outbound HTTP calls became a bottleneck due to a global `http.Client` with a low `MaxIdleConnsPerHost`.

**Solution:** Switched to a connection pool per worker and increased `MaxIdleConnsPerHost` to 100.

**Result:** Latency median dropped from 200 ms to 45 ms, and the flame graph showed `runtime.gopark` shrink dramatically.

## Patterns in Production: When Flame Graphs Reveal Hidden Latency

| Production System | Typical Hidden Latency Revealed by Flame Graphs | Mitigation |
|-------------------|--------------------------------------------------|------------|
| **Kafka** | Excessive `ByteBuffer` copies during compression | Enable `compression.type=snappy` and reuse buffers |
| **Airflow** | Deep Python call stacks in custom operators | Profile operator code separately, cache results |
| **Postgres** | PL/pgSQL N+1 queries hidden in hash joins | Refactor to set‑based logic, use `EXPLAIN (ANALYZE, BUFFERS)` |
| **Redis** | Blocking `SELECT` in Lua scripts | Split script, use `EVALSHA` with pre‑loaded script |
| **gRPC services (Go)** | Goroutine parking on a global rate‑limiter | Use per‑endpoint limiter, avoid global mutex |

## Key Takeaways

- **Flame graphs turn raw stack samples into an instantly readable heat map**, letting you locate the hottest code paths without digging through logs.
- **A minimal pipeline (perf → collapse → flamegraph)** can be automated via a Bash script or embedded in a CI/CD job, adding only ~3 % CPU overhead during sampling.
- **Interpretation follows a pattern library**: wide leaves = tight loops, tall stacks = deep framework overhead, parallel flames = contention, red rectangles = self‑time hotspots.
- **Production‑grade deployments need a supporting architecture** (alert‑driven jobs, secure symbol storage, retention policies) to keep flame‑graph generation reliable and safe.
- **Concrete fixes emerge quickly**: In the case studies, swapping a buffer implementation, adjusting JVM GC threads, or refactoring PL/pgSQL reduced latency by 60 %–80 % after a single iteration.

## Further Reading

- [Flame Graphs – Brendan Gregg’s original guide](https://www.brendangregg.com/flamegraphs.html)  
- [Linux perf Documentation](https://www.kernel.org/doc/html/latest/tools/perf.html)  
- [Async-profiler – Low‑overhead Java profiler](https://github.com/jvm-profiling-tools/async-profiler)  
- [Prometheus Alertmanager](https://prometheus.io/docs/alerting/latest/alertmanager/)  
- [OpenTelemetry – Distributed tracing standards](https://opentelemetry.io)  