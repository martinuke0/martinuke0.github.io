---
title: "Mastering the USE Method: Investigating System Bottlenecks through Utilization, Saturation, and Errors"
date: "2026-05-31T04:00:42.090"
draft: false
tags: ["performance", "monitoring", "observability", "systems", "ops"]
description: "Learn how to apply the USE Method—Utilization, Saturation, and Errors—to pinpoint production bottlenecks in Linux, Kafka, and cloud services with concrete patterns and real‑world code."
summary: "A step‑by‑step guide that shows engineers how to gather and interpret utilization, saturation, and error metrics, then translate them into actionable architecture changes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-31-mastering-the-use-method-investigating-system-bottlenecks-through-utilization-saturation-and-errors.svg"
  alt: "A dashboard visualizing utilization, saturation, and errors across a distributed system."
  caption: ""
  relative: false
---

> **TL;DR** — The USE Method reduces noisy data to three actionable signals: utilization (how busy a resource is), saturation (how much demand exceeds capacity), and errors (failed operations). By instrumenting each layer—CPU, disk, network, Kafka, Postgres—and correlating those three metrics, you can isolate the true bottleneck in minutes instead of hours.

In modern production environments the sheer volume of telemetry can obscure the very problem you’re trying to solve. CPU graphs, latency heat maps, and thousands of alerts compete for attention, and engineers waste precious time chasing red herrings. The USE Method, popularized by Brendan Gregg, cuts through the noise by forcing you to ask three simple questions for **every** resource: *Is it utilized? Is it saturated? Is it erroring?* This post walks through the method from first principles to concrete implementation on Linux servers, Kafka clusters, and PostgreSQL instances, and shows how to embed the patterns into an observability pipeline that scales with your organization.

## The Core of the USE Method

### Utilization – “How busy is the resource?”

Utilization measures the proportion of time a resource is actively doing work. For a CPU, it’s the percentage of cycles spent executing non‑idle instructions. For a network interface, it’s the ratio of bits transmitted to the link’s maximum bandwidth.

*Key insight*: High utilization **does not** automatically imply a problem. A well‑sized service may run at 70 % CPU 24/7 and still meet latency SLOs. The danger appears when utilization approaches the resource’s physical limit **and** other signals (saturation, errors) confirm pressure.

### Saturation – “Is demand outpacing capacity?”

Saturation is the queue depth or wait time that forms when demand exceeds the resource’s ability to service requests. It’s the “traffic jam” indicator that tells you a resource is a bottleneck, regardless of its utilization number.

Examples:
- **CPU run queue length** (`/proc/loadavg` third field) – a long run queue means tasks are waiting for CPU time.
- **Disk I/O latency** (`iostat -x` “await”) – high latency signals the storage subsystem cannot keep up.
- **Network drops** (`netstat -s` “receive errors”) – indicate the NIC or upstream link is saturated.

### Errors – “Are operations failing?”

Even a perfectly utilized, unsaturated resource can become a problem if it starts returning errors. Errors can be explicit (HTTP 5xx, Kafka `RETRY_EXHAUSTED`) or implicit (timeout exceptions, kernel “device busy” messages). Errors are the clearest symptom that something is broken, and they often precede measurable saturation.

## Collecting the Right Signals

Instrumenting the three metrics across the stack requires a mix of OS‑level tools, language‑specific exporters, and service‑specific APIs. Below is a minimal Bash‑based collector that you can drop into a cron job or a sidecar container. It writes JSON lines to stdout, which Prometheus or Loki can ingest.

```bash
#!/usr/bin/env bash
# collect_use.sh – lightweight USE metric exporter

timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# ---------- CPU ----------
cpu_util=$(top -bn1 | grep '^%Cpu' | awk '{print 100-$8}')   # $8 is idle%
cpu_runq=$(awk '{print $3}' /proc/loadavg)                  # 1‑minute run queue avg

# ---------- Disk ----------
disk_util=$(iostat -dx 1 2 | tail -n +7 | awk 'NR==1 {print $14}')   # %util
disk_await=$(iostat -dx 1 2 | tail -n +7 | awk 'NR==1 {print $10}') # await (ms)
disk_err=$(iostat -dx 1 2 | tail -n +7 | awk 'NR==1 {print $13}')   # %iowait as proxy

# ---------- Network ----------
net_bytes=$(cat /sys/class/net/eth0/statistics/tx_bytes)
net_err=$(cat /sys/class/net/eth0/statistics/tx_errors)

# ---------- Kafka (via JMX) ----------
kafka_lag=$(curl -s http://localhost:9092/jmx?qry=kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions | jq -r '.value')

# ---------- PostgreSQL ----------
pg_conn=$(psql -U postgres -t -c "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';")
pg_err=$(psql -U postgres -t -c "SELECT sum(numbackends) FROM pg_stat_database;")  # simplified error proxy

# Emit JSON line
cat <<EOF
{
  "timestamp":"$timestamp",
  "cpu":{"utilization":$cpu_util,"saturation":$cpu_runq},
  "disk":{"utilization":$disk_util,"saturation":$disk_await,"errors":$disk_err},
  "network":{"utilization":$((net_bytes/1024/1024)),"errors":$net_err},
  "kafka":{"under_replicated_partitions":$kafka_lag},
  "postgres":{"active_sessions":$pg_conn,"connections":$pg_err}
}
EOF
```

> **Note** – The script uses `iostat`, `top`, and `curl` to pull metrics. In production you would replace the ad‑hoc JSON with a Prometheus exporter or OpenTelemetry instrumentation to avoid polluting the host with extra processes.

## Interpreting Utilization

### CPU Utilization in Practice

A common misconception is that “CPU > 80 % = bad.” In a microservice that handles 10 k RPS with a 99th‑percentile latency of 2 ms, you might see 95 % utilization and still be comfortably within your SLO. The real test is **how the CPU behaves under load spikes**:

| Utilization | Typical Interpretation |
|-------------|------------------------|
| 0‑30 %      | Over‑provisioned; consider right‑sizing to reduce cost. |
| 30‑70 %     | Healthy operating range for most workloads. |
| 70‑90 %     | Watch for rising run‑queue or latency. |
| > 90 %      | Likely a candidate for scaling or code optimisation. |

If utilization is high but **run‑queue (`saturation`) stays near 0**, the scheduler is keeping up. Conversely, a modest 55 % utilization with a run‑queue of 5 indicates the CPU is **saturated** because tasks spend time waiting for CPU time.

### Disk Utilization and Latency

Disk devices expose `%util` (percentage of time the device was busy) and `await` (average I/O wait in milliseconds). A rule of thumb from the Linux Performance page is:

- `%util > 90 %` **and** `await > 10 ms` → **saturation**.
- `%util > 90 %` **but** `await < 5 ms` → Possibly well‑tuned SSD, still monitor.
- `%util < 70 %` but `await` spikes → Queue buildup, maybe due to lock contention.

### Network Utilization

Network links are often over‑provisioned, but saturation can be hidden behind packet loss. Use `ifstat` or `sar -n DEV` to compute bandwidth usage, then compare against the interface’s rated capacity (e.g., 10 Gbps = 1.25 GB/s). If you see **> 80 %** and **increased TX errors**, the NIC is saturated and you should consider NIC bonding or traffic shaping.

## Interpreting Saturation

### Run‑Queue Length as a Saturation Metric

Linux reports the load average, but the **run‑queue length** (`/proc/loadavg` third field) is a more direct saturation indicator. For a server with *N* CPU cores, a run‑queue > *N* means tasks are queuing. Example:

```text
$ cat /proc/loadavg
2.58 2.73 2.80 1/120 3456
               ^^^
               run‑queue (third field)
```

If the node has 8 cores, a run‑queue of 2.8 is harmless. If the same metric spikes to 12, you have a saturated CPU and need to investigate the offending processes (`top -H -p <pid>`).

### Kafka Under‑Replicated Partitions

Kafka’s `UnderReplicatedPartitions` metric is a classic saturation signal. When a broker falls behind replication, the cluster is **saturated** on the network and disk of the lagging broker. The metric is exposed via JMX; a value > 0 for more than a few minutes should trigger an alert.

```bash
# Quick check via JMX exporter
curl -s http://broker:9092/jmx?qry=kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions | jq .
```

If the count rises, you can:

1. Verify disk I/O on the affected broker (`iostat -x`).
2. Check network errors (`netstat -s`).
3. Consider moving the broker to a faster volume or adding additional replicas.

### PostgreSQL Connection Saturation

PostgreSQL’s `max_connections` sets a hard ceiling. When the number of active sessions approaches this limit, new connections queue in the kernel’s TCP backlog, producing **connection errors** (`FATAL: remaining connection slots are reserved for non‑replication superuser`). Monitoring `pg_stat_activity` for `state = 'active'` and `pg_stat_database` for `numbackends` gives you a saturation view.

```sql
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';
SELECT sum(numbackends) FROM pg_stat_database;
```

If active sessions are 85 % of `max_connections`, you should either increase the limit (with enough RAM) or implement a connection pooler like PgBouncer.

## Interpreting Errors

### Kernel Error Counters

Linux exposes many error counters under `/sys/class/net/*/statistics/`. For example, `tx_errors` increments when the NIC cannot transmit a packet (often due to full buffers). A rising trend correlates with saturation but can also indicate hardware faults. Use `sar -n DEV` to see error spikes aligned with traffic bursts.

### Application‑Level Errors

In a microservice built with Spring Boot, HTTP 5xx responses are logged to the `metrics.http.server.requests` histogram. If you see a sudden uptick in `status=5xx` while CPU utilization is modest, the problem is likely **resource exhaustion downstream** (e.g., database connection pool depletion). The USE method tells you to first check **errors**, then **utilization**, then **saturation** to pinpoint the root cause.

### Observability Platforms

Most teams use Grafana Loki or Elastic for logs, Prometheus for metrics, and Jaeger for traces. When an error appears in logs, correlate it with the three USE signals on the same timestamp. Grafana’s **Explore** view lets you overlay a trace timeline with CPU and disk charts, turning a cryptic stack trace into a concrete bottleneck story.

## Architecture Patterns for Applying USE in Production

### 1. Tiered Observability Pipeline

```
[Instrumented Service] → [OpenTelemetry Collector] → [Prometheus] → [Grafana]
                         ↘︎ [Loki]            ↘︎ [Alertmanager]
```

- **Instrument** every tier (OS, container runtime, service) for utilization, saturation, and error metrics.
- **Export** them in a unified namespace (`use_cpu_util`, `use_disk_sat`, `use_net_err`) so alert rules can be generic.
- **Alert** on thresholds that combine the three signals, e.g.:

```yaml
# Alert when CPU is saturated AND errors appear
- alert: HighCpuSaturationWithErrors
  expr: cpu_runqueue > 10 and increase(process_cpu_seconds_total[1m]) > 0.9
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: "CPU saturated with rising errors on {{ $labels.instance }}"
    description: |
      Utilization: {{ $value | printf \"%.2f\" }}%
      Run‑queue > 10, indicating tasks are queuing.
      Check logs for recent error spikes.
```

### 2. Service‑Specific Saturation Guards

For Kafka, embed a **saturation guard** in your producer library:

```java
// Java Kafka producer wrapper
public void sendWithGuard(ProducerRecord<String, String> record) {
    int underReplicated = metrics.getInt("kafka.server", "ReplicaManager", "UnderReplicatedPartitions");
    if (underReplicated > 0) {
        throw new IllegalStateException("Cluster is saturated: " + underReplicated + " under‑replicated partitions");
    }
    producer.send(record);
}
```

The guard aborts non‑critical writes before the cluster collapses, turning a saturation signal into a protective control flow.

### 3. Adaptive Autoscaling Based on Saturation

Kubernetes Horizontal Pod Autoscaler (HPA) can scale on **custom metrics**. Instead of scaling on CPU % alone, you can feed it the run‑queue length (`node_cpu_saturation`) or disk await (`node_disk_await`). Example HPA manifest:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-service
  minReplicas: 2
  maxReplicas: 15
  metrics:
  - type: Pods
    pods:
      metric:
        name: use_cpu_saturation
      target:
        type: AverageValue
        averageValue: "5"   # run‑queue >5 triggers scaling
```

By scaling on saturation, you avoid the “CPU‑only” lag where utilization spikes after the pod count has already grown.

## Common Pitfalls & How to Avoid Them

| Pitfall | Why It Happens | Remedy |
|---------|----------------|--------|
| **Treating Utilization as the sole alarm** | Teams set alerts on `cpu% > 80` and ignore saturation counters. | Add a complementary rule on `run_queue` or `await`. |
| **Missing error aggregation** | Errors are logged in multiple places and never normalized. | Centralize error metrics (e.g., `http_5xx_total`) and expose them with the same `use_` prefix. |
| **Collecting metrics at too low a resolution** | 5‑minute scrape intervals hide short‑lived spikes. | Use a 15‑second scrape interval for high‑frequency resources (CPU, network). |
| **Over‑relying on averages** | Mean latency can look fine while the 99th percentile explodes. | Track both averages and high‑percentile histograms (`_bucket` metrics). |
| **Ignoring back‑pressure signals** | Systems keep ingesting data even after saturation, causing tail‑latency. | Implement circuit‑breaker patterns that respect saturation metrics (see the Kafka guard example). |

## Key Takeaways
- **Utilization tells you how busy a resource is; saturation tells you whether that busy‑ness creates queues; errors tell you if the queues are breaking down.**
- Collect the three signals at every layer (OS, container, service) using lightweight exporters or language‑specific libraries.
- Correlate utilization, saturation, and errors in a single dashboard; alerts should fire only when at least two signals indicate trouble.
- Apply architecture patterns—tiered observability pipelines, saturation guards, and autoscaling on saturation—to turn metrics into automated resilience.
- Regularly review thresholds against production baselines; what is “high” for one workload may be normal for another.

## Further Reading
- [The USE Method – Brendan Gregg’s original article](https://www.brendangregg.com/usemethod.html)  
- [Kubernetes Horizontal Pod Autoscaler v2 – custom metrics guide](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)  
- [Kafka Monitoring – Confluent documentation on JMX metrics](https://docs.confluent.io/platform/current/kafka/monitoring.html)  