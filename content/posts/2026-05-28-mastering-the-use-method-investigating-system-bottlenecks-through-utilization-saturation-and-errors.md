---
title: "Mastering the USE Method: Investigating System Bottlenecks through Utilization, Saturation, and Errors"
date: "2026-05-28T08:00:10.425"
draft: false
tags: ["performance", "monitoring", "observability", "systems", "engineering"]
description: "Learn how to apply the USE Method—Utilization, Saturation, and Errors—to pinpoint production bottlenecks, with real‑world Kafka and PostgreSQL examples and actionable patterns."
summary: "A practical guide for engineers to master the USE Method, transform raw metrics into clear bottleneck insights, and implement production‑ready monitoring architectures."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-28-mastering-the-use-method-investigating-system-bottlenecks-through-utilization-saturation-and-errors.png"
  alt: "Diagram of system metrics overlaying a server rack."
  caption: ""
  relative: false
---

> **TL;DR** — The USE Method lets you turn three simple metrics—Utilization, Saturation, and Errors—into a systematic bottleneck‑hunting process. By wiring those signals into a real‑time pipeline (Kafka → Prometheus → Grafana) you can spot, alert on, and resolve performance constraints before they cascade into outages.

System performance problems are rarely mysterious; they are usually the result of one or more resources operating at the edge of their capacity. The USE Method, popularized by Brendan Gregg, gives engineers a repeatable checklist that maps directly onto the metrics most observability platforms already expose. In this post we’ll unpack each component, show how to collect the right data at scale, and walk through a production‑grade architecture that turns raw numbers into actionable alerts.

## Understanding the USE Method

### Utilization

Utilization measures **how busy a resource is** relative to its theoretical maximum. For a CPU core, it’s the percentage of time spent executing non‑idle instructions; for a disk, it’s the fraction of I/O bandwidth consumed; for a network interface, it’s the proportion of link capacity used.

> “High utilization alone isn’t a problem—only when it approaches the resource’s limit does it become a symptom of pressure.” – Brendan Gregg, *Systems Performance*.

Key points:

- **CPU:** `user + system` time vs. total time (ignore `iowait` unless you’re measuring I/O‑bound workloads).  
- **Memory:** Not a classic utilization metric, but *active* memory vs. total can indicate pressure.  
- **Disk:** Bytes per second / device’s rated throughput.  
- **Network:** Packets/bytes per second / link speed.

### Saturation

Saturation captures **how much demand is being queued** because the resource cannot service requests instantly. It’s the ratio of *wait time* to *service time* or, more concretely, the length of a queue relative to its processing rate.

Typical saturation signals:

| Resource | Saturation Metric | Typical Threshold |
|----------|-------------------|-------------------|
| CPU      | Run queue length (`runqueue`) / cores | > 2 |
| Disk     | Average I/O latency / service time | > 2 |
| Network  | TX/RX queue depth / NIC buffers | > 0.8 |
| Locks    | Contention time / lock hold time | > 0.1 |

A resource may show moderate utilization but high saturation—meaning it’s **blocked** and requests are piling up.

### Errors

Errors are the **failure modes** that surface when a resource is over‑committed or mis‑configured. They provide the final piece of the puzzle, confirming that the observed pressure is having a tangible impact on the workload.

Common error signals:

- **CPU:** `SIGKILL` due to out‑of‑memory (OOM) killer invoking because of memory pressure, not CPU, but often correlated.  
- **Disk:** I/O timeouts, `ENOSPC` (no space), `EIO` (hardware error).  
- **Network:** Retransmission spikes, TCP reset storms, `ECONNREFUSED`.  
- **Application:** HTTP 5xx, database deadlocks, circuit‑breaker trips.

When all three dimensions line up—high utilization, high saturation, and rising errors—you’ve found a **bottleneck**.

## Collecting Metrics at Scale

### Choosing the Right Toolchain

| Goal | Recommended Tool | Why |
|------|------------------|-----|
| High‑resolution time series | **Prometheus** (scrape interval ≤ 15s) | Native support for counters, gauges, histograms |
| Distributed tracing | **Jaeger** or **OpenTelemetry** | Correlates latency spikes with resource metrics |
| Stream‑processing of alerts | **Kafka** + **ksqlDB** | Guarantees ordered, replayable metric streams |
| Dashboarding | **Grafana** | Rich templating, alert rule engine |
| Centralized logging | **Elastic Stack** | Searchable error logs for the “Errors” pillar |

### Example Prometheus Scrape Config (yaml)

```yaml
scrape_configs:
  - job_name: 'node_exporter'
    static_configs:
      - targets: ['10.0.1.10:9100', '10.0.1.11:9100']
    metrics_path: /metrics
    relabel_configs:
      - source_labels: [__address__]
        regex: '(.*):.*'
        target_label: instance
        replacement: '${1}'
  - job_name: 'kafka_exporter'
    static_configs:
      - targets: ['10.0.2.20:9308']
```

This configuration pulls CPU, disk, and network metrics from `node_exporter` while also exposing Kafka broker statistics via `kafka_exporter`. The `instance` label normalizes hostnames for downstream alert rules.

### Remote Write to a Central Store

In multi‑region deployments, you can forward raw samples to a central Prometheus or Cortex cluster:

```yaml
remote_write:
  - url: "https://prometheus-central.example.com/api/v1/write"
    bearer_token: "REDACTED"
    queue_config:
      capacity: 2500
      max_shards: 5
```

Remote write guarantees that even if a local collector crashes, the data is safely persisted for later analysis—a critical requirement for the “Errors” dimension.

## Architecture Patterns for Real‑Time Bottleneck Detection

### End‑to‑End Data Flow

```
[Application] → [StatsD/OTLP] → [Kafka] → [Prometheus Remote Write] → [Cortex] → [Grafana]
                                 ↘︎                 ↘︎
                              [Alertmanager]      [Jaeger]
```

1. **Instrumentation**: Applications emit counters and histograms via OpenTelemetry SDKs.  
2. **Kafka Bridge**: A lightweight `otel-collector` forwards metrics to a Kafka topic (`metrics.raw`). Kafka provides durability and decouples producers from consumers.  
3. **Prometheus Remote Write**: A consumer reads from `metrics.raw` and pushes to a central Prometheus cluster.  
4. **Alertmanager**: Prometheus evaluates USE‑based alert rules; Alertmanager routes alerts to Slack, PagerDuty, or Opsgenie.  
5. **Grafana**: Dashboards visualize utilization, saturation, and error trends side‑by‑side.

### Sample Alert Rule for Disk Saturation

```yaml
groups:
  - name: use-method.rules
    rules:
      - alert: DiskSaturationHigh
        expr: (rate(node_disk_io_time_seconds_total[5m]) / node_disk_reads_completed_total) > 2
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Disk {{ $labels.device }} on {{ $labels.instance }} is saturated"
          description: |
            Utilization: {{ printf \"%.2f\" (node_disk_io_time_seconds_total / node_disk_io_time_seconds_total) }}%
            Saturation (avg latency / service time) > 2×.
            Check for I/O backlog or mis‑aligned RAID layout.
```

The expression computes **average I/O latency** (`io_time_seconds_total / reads_completed_total`) and compares it to the device’s service time. If the ratio exceeds **2**, the rule fires, satisfying the saturation criterion.

### Correlating Errors with Utilization

Use Grafana’s **Alert List** panel to join error logs with metric heatmaps:

```sql
SELECT
  timestamp,
  message
FROM elasticsearch_logs
WHERE message LIKE '%ERROR%'
  AND host = '{{ $labels.instance }}'
ORDER BY timestamp DESC
LIMIT 50
```

When an alert triggers, the panel instantly surfaces the most recent error entries, letting engineers verify the “Errors” pillar without leaving the dashboard.

## Applying the Method to a Production Service

Consider a microservice stack that processes inbound HTTP requests, writes to PostgreSQL, and publishes events to a Kafka topic. We’ll walk through each resource.

### CPU Utilization on the API Tier

- **Metric**: `process_cpu_seconds_total` (Prometheus)  
- **Threshold**: > 80 % sustained for 5 min  

```bash
# Quick sanity check on a Linux host
top -b -n1 | grep $(pgrep -f myservice)
```

If CPU spikes coincide with a surge in request latency, check the **run queue** (`node_load5 / node_cpu_seconds_total`) to detect saturation.

### Disk Saturation on PostgreSQL

Postgres exposes `pg_stat_bgwriter` counters. Combine them with `node_disk_io_time_seconds_total` to compute write latency.

```sql
SELECT
  pg_stat_bgwriter.checkpoints_timed,
  pg_stat_bgwriter.checkpoints_req,
  pg_stat_bgwriter.buffers_checkpoint,
  pg_stat_bgwriter.buffers_backend,
  pg_stat_bgwriter.buffers_alloc
FROM pg_stat_bgwriter;
```

A high `buffers_checkpoint` rate paired with a disk latency > 10 ms signals that the storage subsystem is **saturated**, even if utilization is only 60 %.

### Network Saturation on Kafka Producers

Kafka’s broker metrics include `request_rate` and `request_queue_time_avg`. An alert rule:

```yaml
- alert: KafkaProducerQueueHigh
  expr: kafka_producer_request_queue_time_avg > 0.5
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Kafka producer queue latency high on {{ $labels.instance }}"
    description: "Saturation detected: average queue time {{ $value }} s exceeds 0.5 s."
```

When this fires, examine the broker’s `BytesInPerSec` vs. NIC capacity to confirm **network utilization**. If both are high, the broker may be **throttled**.

### Errors: HTTP 5xx and PostgreSQL Deadlocks

Instrument your HTTP server with a counter for 5xx responses:

```python
from prometheus_client import Counter

http_5xx_total = Counter('http_5xx_total', 'Number of HTTP 5xx responses', ['handler'])
```

In Grafana, plot `rate(http_5xx_total[1m])` alongside CPU and disk saturation graphs. A spike that aligns with high saturation proves the bottleneck is affecting user‑visible errors.

## Common Pitfalls and Failure Modes

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Treating Utilization as a Binary Flag** | Alert fires at 85 % CPU but latency unchanged | Add a saturation check (run‑queue length) before escalating. |
| **Ignoring Multi‑Tenant Interference** | One service’s high disk I/O hides another’s latency | Tag metrics by `service` and create per‑service alert rules. |
| **Hard‑Coded Thresholds** | Alert storms after a seasonal traffic bump | Use **dynamic thresholds** (e.g., `quantile_over_time`) to adapt to baseline shifts. |
| **Missing Error Context** | High utilization alerts, but engineers can’t reproduce the issue | Correlate alerts with log snippets via Grafana’s **Explore** feature. |
| **Metric Staleness** | Remote write lag causes stale utilization data, leading to false positives | Set `scrape_interval` ≤ 15s and monitor `prometheus_tsdb_head_samples_appended_total` for ingestion health. |

### The “Masking” Failure Mode

When a resource is saturated, error counters may **reset** because the upstream component drops requests silently. To detect this, monitor **drop rates** (`node_network_drop_total`) and **queue lengths** (`kafka_producer_queue_size`). A rising drop count with stable utilization is a classic sign of hidden saturation.

## Key Takeaways

- **Utilization tells you how busy a resource is; saturation tells you whether that busyness is causing wait time; errors confirm the business impact.**  
- **Instrument at the source** (application, OS, broker) and ship metrics through a durable pipeline (Kafka → Prometheus) to avoid data loss.  
- **Alert on the full USE trio**—don’t rely on a single threshold; combine `utilization > X%` **and** `saturation > Y` **and** `error_rate > Z`.  
- **Visual correlation** (Grafana dashboards that place utilization, saturation, and error panels together) reduces MTTR by surfacing the root cause instantly.  
- **Iterate thresholds** based on production baselines; use quantile‑based alerts to adapt to traffic patterns without overwhelming on‑call teams.  

## Further Reading

- [The USE Method – Brendan Gregg’s original article](https://www.brendangregg.com/usemethod.html)  
- [Prometheus Remote Write Documentation](https://prometheus.io/docs/prometheus/latest/remote_write/)  
- [Kafka Monitoring Best Practices (Confluent)](https://developer.confluent.io/monitoring/kafka/)