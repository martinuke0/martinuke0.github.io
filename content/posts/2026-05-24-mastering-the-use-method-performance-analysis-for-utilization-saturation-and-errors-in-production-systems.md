---
title: "Mastering the USE Method: Performance Analysis for Utilization, Saturation, and Errors in Production Systems"
date: "2026-05-24T07:00:53.225"
draft: false
tags: ["performance", "monitoring", "ops", "observability", "systems"]
description: "Learn how to apply the USE method—Utilization, Saturation, Errors—to production systems, with concrete metrics, patterns, and tooling for Kafka, PostgreSQL, and cloud services."
summary: "A practical guide to mastering the USE method in real-world environments, showing how to collect, interpret, and act on utilization, saturation, and error signals."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-24-mastering-the-use-method-performance-analysis-for-utilization-saturation-and-errors-in-production-systems.svg"
  alt: "Diagram of utilization, saturation, and error metrics overlaid on a server rack."
  caption: ""
  relative: false
---

> **TL;DR** — The USE method lets you turn raw metrics into actionable insights by looking at Utilization, Saturation, and Errors together. By instrumenting Kafka, PostgreSQL, and Kubernetes with Prometheus, you can spot bottlenecks before they become outages and drive systematic performance improvements.

Production systems are noisy, distributed, and constantly evolving. Engineers who rely on a single metric—CPU percent, request latency, or error count—often chase ghosts. The USE method, popularized by Brendan Gregg, gives a disciplined three‑lens view that aligns directly with the resources you actually provision: CPU, memory, disk, network, and the software queues that sit on top of them. This post walks through each lens, shows how to extract the right signals from real‑world stacks (Kafka, PostgreSQL, GKE), and stitches the pieces together into a repeatable architecture for continuous performance analysis.

## Understanding the USE Method

The acronym stands for **U**tilization, **S**aturation, and **E**rrors. The core idea is simple:

| Lens        | What you measure                                   | Why it matters                                          |
|-------------|----------------------------------------------------|---------------------------------------------------------|
| Utilization | How much of a resource is being used (CPU, I/O)   | High utilization indicates heavy load; low utilization may signal under‑provisioning or idle capacity. |
| Saturation  | How much demand exceeds capacity (queue lengths)  | Saturation is the first sign of a bottleneck; a resource can be under‑utilized yet saturated if queues grow. |
| Errors      | Faults, retries, and timeouts at the resource level| Errors are the symptom that a saturated or over‑utilized component is failing to meet its contract. |

When you evaluate all three together, you avoid common pitfalls:

* **CPU 90 %** looks bad, but if the run‑queue length is near zero you have headroom.  
* **Disk I/O 20 %** seems idle, yet a long write‑back queue tells you the disk is saturated.  
* **Error rate 0 %** is comforting, but if latency spikes you might be silently throttling requests.

The USE method is not a checklist; it’s a mental model that you apply to every *resource* in your stack. Below we map the model onto concrete production components.

## Utilization: Metrics and Tools

### CPU and Core Utilization

For Linux workloads, `node_exporter` exposes `node_cpu_seconds_total`. A typical Prometheus query to compute per‑core utilization over the last minute is:

```promql
100 - (avg by (instance, cpu) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)
```

In a Kubernetes pod, you can drill down to the cgroup level:

```promql
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="prod"}[30s])) * 100
```

**What to watch:**  
* **Sustained > 70 %** across all cores may indicate the need for scaling.  
* **Spikes > 90 %** for less than 10 seconds are often benign (GC pauses, burst traffic).  

### Memory Utilization vs. Working Set

Memory is a classic case where utilization alone is misleading. `node_memory_Active_bytes` approximates the *working set*—the portion actually in use. Compare it to total memory:

```promql
(node_memory_Active_bytes / node_memory_MemTotal_bytes) * 100
```

If utilization is 80 % but the active set is only 30 %, you have a lot of cached or idle pages. This informs decisions about heap sizing in Java services or `shared_buffers` in PostgreSQL.

### Disk I/O Utilization

Modern SSDs expose `node_disk_io_time_seconds_total`. To get utilization:

```promql
rate(node_disk_io_time_seconds_total[1m]) * 100
```

For Kafka brokers, the relevant metric is `kafka_server_broker_topic_metrics_bytesin_total`. Correlate broker throughput with disk I/O to catch scenarios where network traffic is high but the disk cannot keep up.

### Network Utilization

`node_network_receive_bytes_total` and `node_network_transmit_bytes_total` give raw byte counters. A normalized utilization query:

```promql
100 * (rate(node_network_receive_bytes_total[1m]) + rate(node_network_transmit_bytes_total[1m])) / (node_network_speed_bytes * 8)
```

Replace `node_network_speed_bytes` with the interface’s advertised speed (e.g., 1 Gbps = 125 000 000 bytes/s).

## Saturation: Detecting Bottlenecks

Saturation is the *queue* length that forms when demand outpaces service rate. It’s often the first indicator that a resource is about to become a failure point.

### Run‑Queue Length (CPU)

Linux exposes `node_load1`, but the more precise metric is `node_schedstat_run_seconds_total`. A short‑term saturation view:

```promql
rate(node_schedstat_run_seconds_total[30s]) * 1000  # milliseconds of run‑queue per second
```

A run‑queue > 100 ms consistently signals CPU saturation even if utilization appears modest.

### Disk Queue Depth

`node_disk_io_time_weighted_seconds_total` captures the time I/O requests spend waiting. Compute average queue depth:

```promql
(rate(node_disk_io_time_weighted_seconds_total[1m]) / rate(node_disk_io_time_seconds_total[1m]))
```

A depth > 2 on SSDs is a red flag; on spinning disks, > 5 may be acceptable.

### Kafka Consumer Lag

Kafka’s `consumer_lag` metric (available via `kafka_consumer_group_lag`) directly measures the number of messages waiting to be processed:

```promql
max by (consumer_group, topic) (kafka_consumer_group_lag)
```

If lag grows beyond a few thousand records, the consumer side is saturated—perhaps due to back‑pressure in downstream services.

### PostgreSQL Connection Pool Saturation

`pg_stat_activity` shows the number of active connections. In a connection‑pooled environment (e.g., PgBouncer), monitor `pgbouncer_pool_total` and `pgbouncer_pool_waiting`:

```sql
SELECT pool, cl_active, cl_waiting FROM pgbouncer_pool;
```

A high `cl_waiting` count indicates the pool is saturated and new queries are queuing.

## Errors: Signal vs. Noise

Error metrics must be contextualized with utilization and saturation. A sudden spike in HTTP 5xxs may be caused by a saturated downstream cache, not a bug in the front‑end service.

### HTTP Error Rates

Assuming `haproxy_http_responses_total`:

```promql
sum(rate(haproxy_http_responses_total{code=~"5.."}[1m])) by (service)
  / sum(rate(haproxy_http_responses_total[1m])) by (service)
  * 100
```

Set an alert at > 0.5 % for 5‑minute windows, but correlate with CPU saturation to avoid false positives.

### Kafka Produce Errors

`kafka_producer_record_error_total` surfaces serialization or broker‑side rejections:

```promql
rate(kafka_producer_record_error_total[5m])
```

If errors rise while `kafka_producer_record_send_total` stays flat, the broker is likely saturated.

### PostgreSQL Error Classes

`pg_stat_database_xact_rollback` counts transaction rollbacks, which often correlate with lock contention:

```promql
rate(pg_stat_database_xact_rollback[1m])
```

Cross‑reference with `pg_locks` view to pinpoint the offending relation.

### Noise Reduction Techniques

1. **Error Budgeting** – Define acceptable error rates per SLO and silence alerts below that threshold.  
2. **Dynamic Thresholds** – Use `alertmanager`'s `for` clause combined with a moving average to avoid flapping.  
3. **Root‑Cause Tagging** – Enrich logs with `component` and `resource` fields (via OpenTelemetry) so you can slice errors by the saturated resource that generated them.

## Architecture: Continuous USE Monitoring in Production

A robust architecture collects, stores, and visualizes the three lenses without adding prohibitive overhead.

### Data Pipeline Overview

```
+----------------+   scrape   +----------------+   store   +-----------------+
|   Exporters    |----------->|   Prometheus   |--------->|   Thanos /      |
| (node_exporter|            |   (TSDB)       |          |   Cortex        |
|  kafka_exporter|            |                |          |                 |
+----------------+            +----------------+          +-----------------+
        |                                 |                     |
        |                                 v                     v
        |                         +----------------+   +-----------------+
        |                         |   Grafana      |   |   Alertmanager  |
        |                         |   Dashboards   |   |   Routing Rules |
        |                         +----------------+   +-----------------+
        |
        v
+-------------------+
|   OpenTelemetry   |
|   (trace, logs)   |
+-------------------+
```

**Key components:**

* **Exporters** – `node_exporter` for OS metrics, `kafka_exporter` for broker stats, `postgres_exporter` for DB metrics, and OpenTelemetry Collector for traces/logs.
* **Prometheus** – Scrapes at 15‑second intervals; uses `remote_write` to Thanos for long‑term retention.
* **Grafana** – Pre‑built USE dashboards (CPU, Disk, Network, Kafka Lag, DB pool) that overlay utilization, saturation, and error panels side‑by‑side.
* **Alertmanager** – Receives alerts generated from combined queries (e.g., high CPU *and* run‑queue > 100 ms) and routes them to Slack or PagerDuty.

### Pattern: “Saturation‑First” Alerting

Instead of alerting on utilization alone, compose PromQL expressions that require both conditions:

```promql
# CPU saturation alert
(
  (100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100)) > 70
) and (
  rate(node_schedstat_run_seconds_total[30s]) * 1000 > 100
)
```

The alert fires only when the system is both busy **and** the run‑queue is long, dramatically reducing noise.

### Pattern: “Error‑Contextualization” Panel

In Grafana, create a row with three panels:

1. **Utilization** – CPU % and network throughput.  
2. **Saturation** – Run‑queue, Kafka lag, DB pool waiting.  
3. **Errors** – HTTP 5xx rate, Kafka errors, DB rollbacks.

Link the panels via the same time range and variable (e.g., `$service`). When an error spike appears, you instantly see whether a saturated resource is the root cause.

### Scaling the Architecture

* **Horizontal Prometheus** – Deploy the Prometheus Operator with `Shard` CRDs to split scrape targets across instances.  
* **Federation** – Use a global Prometheus that scrapes per‑team Prometheuses for a unified view.  
* **Cold Storage** – Thanos `store` gateways ship older blocks to S3, keeping recent data in RAM for fast alert evaluation.

## Key Takeaways

- **Utilization tells you *how much* you’re using; saturation tells you *whether* you’re keeping up; errors tell you *if* the system is still meeting its contract.**  
- **Instrument every critical resource (CPU, disk, network, Kafka, PostgreSQL) with dedicated exporters; avoid relying on a single “overall health” metric.**  
- **Combine utilization and saturation in alerts to cut noise dramatically—use PromQL `and` operators or Alertmanager routing.**  
- **Contextualize errors with the same three‑lens view; a spike in 5xx without saturation is often a code bug, with saturation it’s a capacity issue.**  
- **Adopt a reusable architecture: exporters → Prometheus → Thanos/Cortex → Grafana + Alertmanager + OpenTelemetry. This pattern scales from a single VM to a multi‑region Kubernetes fleet.**  
- **Regularly review dashboards and SLOs; the USE method is a living discipline, not a one‑time checklist.**

## Further Reading

- [The USE Method – Brendan Gregg’s original guide](https://www.brendangregg.com/usemethod.html)  
- [Prometheus Query Basics](https://prometheus.io/docs/prometheus/latest/querying/basics/)  
- [Kafka Monitoring Best Practices (Confluent)](https://developer.confluent.io/monitoring/kafka/)  
- [PostgreSQL Performance Monitoring with pgBouncer](https://www.pgbouncer.org/monitoring.html)  
- [OpenTelemetry Collector Architecture](https://opentelemetry.io/docs/collector/)