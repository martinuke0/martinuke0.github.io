---
title: "Mastering the USE Method: Performance Analysis for Utilization, Saturation, and Errors in Production Systems"
date: "2026-05-29T03:00:09.708"
draft: false
tags: ["performance","monitoring","USE method","observability","production"]
description: "Master the USE method—Utilization, Saturation, Errors—to locate bottlenecks in Kafka, PostgreSQL, and Kubernetes, with patterns and code snippets."
summary: "This post walks through the USE method, showing how to instrument and interpret utilization, saturation, and error metrics in real‑world Kafka, PostgreSQL, and Kubernetes deployments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-29-mastering-the-use-method-performance-analysis-for-utilization-saturation-and-errors-in-production-systems.svg"
  alt: "Diagram of utilization, saturation, and error metrics overlaying a production stack."
  caption: ""
  relative: false
---

> **TL;DR** — The USE method gives you three concrete lenses—Utilization, Saturation, and Errors—to turn raw metrics into actionable signals. By wiring those lenses into Kafka, PostgreSQL, and Kubernetes, you can spot capacity limits before they become outages.

Performance teams spend countless hours chasing “why is latency high?” only to discover a missing metric or an ambiguous alert. The USE method, popularized by Brendan Gregg, collapses that chaos into a repeatable three‑step routine. In this article we’ll:

* Define each component of the USE method in production‑ready terms.  
* Show how to instrument three cornerstone platforms (Kafka, PostgreSQL, Kubernetes) with Prometheus and native tooling.  
* Present architectural patterns that make the data durable, query‑able, and alert‑friendly.  

By the end you’ll have a checklist you can copy‑paste into any microservice‑centric stack.

## The USE Method Overview

The acronym stands for **U**tilization, **S**aturation, and **E**rrors. Each metric answers a specific question about a resource:

| Dimension | Core Question | Typical Metric Examples |
|-----------|---------------|--------------------------|
| Utilization | *How much of the resource is being used?* | CPU % busy, disk I/O throughput, network bandwidth. |
| Saturation | *Is demand outpacing capacity?* | Run queue length, disk queue depth, connection pool wait time. |
| Errors | *Is the resource failing to do its job?* | Packet drops, request timeouts, failed commits. |

The key is **not** to collect everything, but to focus on these three signals for every critical component. When all three are low, the system is healthy. When any spikes, you have a concrete hypothesis to test.

### Utilization

Utilization is the easiest to grasp: it’s the percentage of a resource’s capacity that is actively doing work. In Linux, `cpu_usage_seconds_total` (Prometheus) divided by `system_cpu_seconds_total` yields a CPU utilization curve. For Kafka, the broker’s `kafka_server_BrokerTopicMetrics_BytesInPerSec` tells you how much inbound traffic you’re moving relative to the NIC’s line rate.

*Tip:* Always pair a raw utilization metric with its **capacity** (e.g., `node_cpu_capacity`). Without the denominator you can’t tell if “90 %” is close to a hard limit or just a baseline.

### Saturation

Saturation surfaces **back‑pressure**. A resource can be 30 % utilized but still saturated if its queue is growing. Classic examples:

* **Run queue** (`node_load1` vs. `node_cpu_cores`) – a long run queue means the scheduler can’t keep up.  
* **Disk queue depth** (`node_disk_io_time_seconds_total` / `node_disk_reads_completed_total`) – high depth indicates I/O bottleneck.  
* **Kafka request queue** (`kafka_network_RequestMetrics_RequestQueueSize`) – growing queue predicts latency spikes.

When saturation rises, you should look for **capacity expansion** (more cores, faster SSD) or **load shedding** (throttling producers, back‑pressure to clients).

### Errors

Errors are the final guardrail. Even a perfectly utilized and unsaturated system can fail if the error rate climbs. Typical error signals:

* **Network drops** (`node_network_receive_errs_total`).  
* **Database deadlocks** (`postgres_deadlocks_total`).  
* **Kafka under‑replicated partitions** (`kafka_server_ReplicaManager_UnderReplicatedPartitions`).  

A sudden error surge often precedes a crash, so alerting on error rate thresholds (e.g., > 5 % of requests failing over 1 minute) is a best practice.

## Instrumenting Production Systems

Below we dive into concrete instrumentation for three platforms that most LinkedIn engineers already run in production. All examples assume a Prometheus‑scrape architecture, but the same principles apply to OpenTelemetry, Datadog, or CloudWatch.

### Kafka

Kafka exposes JMX metrics that Prometheus can ingest via the `jmx_exporter`. The most useful USE‑related metrics are:

* **Utilization** – `kafka_server_BrokerTopicMetrics_BytesInPerSec_rate` and `BytesOutPerSec_rate`.  
* **Saturation** – `kafka_network_RequestMetrics_RequestQueueSize`.  
* **Errors** – `kafka_server_ReplicaManager_UnderReplicatedPartitions`, `kafka_controller_KafkaController_OfflinePartitionsCount`.

#### Example: Prometheus scrape config (yaml)

```yaml
scrape_configs:
  - job_name: 'kafka-jmx'
    static_configs:
      - targets: ['kafka-broker-1:9100', 'kafka-broker-2:9100']
    metrics_path: /metrics
    scheme: http
```

#### Calculating Utilization in PromQL

```promql
# Kafka inbound utilization as a percentage of a 10 Gbps NIC
100 * sum(rate(kafka_server_BrokerTopicMetrics_BytesInPerSec_rate[1m]))
      / (10 * 1024 * 1024 * 1024)
```

#### Saturation alert

```promql
# Trigger when request queue exceeds 75 % of the configured max (default 1000)
kafka_network_RequestMetrics_RequestQueueSize > 750
```

### PostgreSQL

PostgreSQL ships a built-in `pg_stat_*` view suite. The `postgres_exporter` maps these to Prometheus metrics.

* **Utilization** – `pg_stat_activity_count` (active sessions) vs. `max_connections`.  
* **Saturation** – `pg_stat_bgwriter_buffers_checkpoint` (checkpoint activity) or `pg_stat_replication_write_lag`.  
* **Errors** – `pg_stat_database_deadlocks`, `pg_stat_database_xact_rollback`.

#### Example: Bash snippet to enable `pg_stat_statements`

```bash
#!/usr/bin/env bash
psql -U postgres -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"
psql -U postgres -c "ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';"
pg_ctl reload
```

#### Utilization query (PromQL)

```promql
# Percentage of used connections
100 * pg_stat_activity_count / pg_settings_max_connections
```

#### Errors alert

```promql
# Alert if deadlocks per minute exceed 5
increase(pg_stat_database_deadlocks[1m]) > 5
```

### Kubernetes

Kubernetes surfaces node‑level metrics via the `kubelet` and pod‑level metrics via `kube-state-metrics`. For the USE method we focus on:

* **Utilization** – `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`.  
* **Saturation** – `container_cpu_cfs_periods_total` vs. `container_cpu_cfs_throttled_seconds_total` (CPU throttling), `kube_pod_container_status_waiting_reason` (e.g., `CrashLoopBackOff`).  
* **Errors** – `kubelet_volume_stats_failed_total`, `apiserver_request_total` with `code=5xx`.

#### Example: Annotating a pod for custom error metric

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: api-service
  annotations:
    prometheus.io/scrape: "true"
    prometheus.io/port: "8080"
spec:
  containers:
    - name: api
      image: myorg/api:1.2.3
      ports:
        - containerPort: 8080
```

#### Saturation alert for CPU throttling

```promql
# Alert when more than 20 % of CPU time is throttled over 5 min
sum(rate(container_cpu_cfs_throttled_seconds_total[5m]))
  / sum(rate(container_cpu_cfs_periods_total[5m])) > 0.20
```

## Architecture Patterns for Observability

Collecting metrics is only half the battle. Production systems need **reliable pipelines**, **long‑term storage**, and **fast query paths**. Below are three patterns that scale with the USE method.

### 1. Sidecar Exporter per Service

Deploy a sidecar container that runs the appropriate exporter (JMX, Postgres, or custom). Benefits:

* **Isolation** – exporter runs in same network namespace, no firewall changes.  
* **Self‑healing** – Kubernetes restarts the sidecar if it crashes, keeping metric continuity.  

#### Diagram (ASCII)

```
+-------------------+      +-------------------+
|   Service Pod     | ---> |  Exporter Sidecar |
| (Kafka Broker)    |      | (jmx_exporter)    |
+-------------------+      +-------------------+
          |                       |
          v                       v
   Prometheus Scrape Endpoint
```

### 2. Metric Aggregation Layer

When you have hundreds of brokers, DB instances, or nodes, a **remote write** to a central TSDB (e.g., Cortex, Thanos) reduces load on the primary Prometheus server.

```yaml
remote_write:
  - url: "https://cortex.example.com/api/v1/push"
    basic_auth:
      username: prometheus
      password: ${CORTEX_PASSWORD}
```

### 3. Alert Routing with Inhibition

USE alerts often overlap (e.g., high utilization *and* high saturation). Use Prometheus Alertmanager inhibition rules to suppress noisy downstream alerts.

```yaml
inhibit_rules:
  - source_match:
      severity: "critical"
    target_match:
      severity: "warning"
    equal: ["alertname", "instance"]
```

## Common Pitfalls and Failure Modes

Even seasoned teams trip over the same traps when applying the USE method.

| Pitfall | Symptom | Remedy |
|---------|---------|--------|
| **Missing capacity reference** | Utilization shows 80 % but you don’t know if that’s 80 % of 2 vCPU or 80 % of 32 vCPU. | Export static capacity metrics (e.g., `node_cpu_cores`). |
| **Stale scrape targets** | Alerts fire on old data after a pod is terminated. | Enable Prometheus `scrape_interval` + `honor_timestamps: true` and use service discovery. |
| **Queue‑depth misinterpretation** | Saturation appears low because queue length is reset on restart. | Persist queue metrics in a short‑term ring buffer (e.g., `rate(queue_size[5m])`). |
| **Error metric over‑aggregation** | Counting all 5xx HTTP responses hides critical “503 Service Unavailable”. | Tag errors by endpoint or error code and alert on the most severe subset. |
| **Alert fatigue** | Multiple USE alerts fire simultaneously, causing on‑call overload. | Use Alertmanager grouping and inhibition, and add a “health‑score” composite metric. |

## Key Takeaways

- **Utilization, Saturation, Errors** form a complete, production‑grade health triangle; always capture all three for every critical component.  
- **Instrument with native exporters** (JMX for Kafka, pg_exporter for PostgreSQL, kubelet for Kubernetes) and expose capacity metrics alongside usage.  
- **Architect for scale**: sidecar exporters, remote‑write aggregation, and alert inhibition keep the pipeline reliable as you grow.  
- **Validate your alerts** with real‑world load tests; a false positive in saturation can mask a true utilization problem.  
- **Iterate**: start with a single service, refine the queries, then roll the pattern out cluster‑wide.

## Further Reading

- [Prometheus Metric Types](https://prometheus.io/docs/concepts/metric_types/) – Deep dive into counters, gauges, and histograms used throughout the examples.  
- [Apache Kafka Monitoring Guide](https://kafka.apache.org/documentation/#monitoring) – Official documentation of JMX metrics and recommended alert thresholds.  
- [PostgreSQL Monitoring and Statistics](https://www.postgresql.org/docs/current/monitoring-stats.html) – Comprehensive list of `pg_stat_*` views and interpretation tips.  
- [Kubernetes Observability Best Practices](https://kubernetes.io/docs/concepts/cluster-administration/monitoring/) – Guidance on exposing node and pod metrics for the USE method.  