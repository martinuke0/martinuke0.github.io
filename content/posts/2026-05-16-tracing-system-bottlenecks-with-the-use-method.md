---
title: "Tracing System Bottlenecks With the USE Method"
date: "2026-05-16T10:00:48.256"
draft: false
tags: ["performance", "monitoring", "USE method", "system bottlenecks", "observability"]
description: "Learn how to identify and resolve performance bottlenecks in complex systems using the USE method, a practical framework for utilization, saturation, and errors."
summary: "The USE method offers a concise way to spot where resources are strained, helping engineers quickly narrow down performance problems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-tracing-system-bottlenecks-with-the-use-method.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — The USE method (Utilization‑Saturation‑Errors) lets you focus on the three most telling metrics for any resource, making bottleneck detection fast and repeatable. By gathering the right data, visualizing it, and following a disciplined analysis flow, you can pinpoint the exact component that’s slowing your system and act with confidence.

Modern distributed applications run on layers of compute, storage, networking, and orchestration. When latency spikes or throughput drops, the first instinct is to “look at the logs” or “restart the service.” Those steps are useful, but they often mask the underlying resource that is actually saturated. The USE method, popularized by Brendan Gregg, cuts through the noise by asking three simple questions for *every* resource: **Is it over‑utilized? Is it saturated? Is it generating errors?** This article walks you through the theory, the tooling, and a step‑by‑step workflow you can adopt today.

## Understanding the USE Method

The USE method is deliberately minimalist. Instead of trying to collect hundreds of metrics, you focus on three that together give a high‑signal view of health.

| Dimension   | What to Measure                                 | Typical Metric Examples |
|------------|------------------------------------------------|--------------------------|
| Utilization| How much of the resource’s capacity is being used| CPU %busy, memory %used, disk I/O throughput |
| Saturation | How much demand exceeds the resource’s ability to serve | Run queue length, I/O wait time, network queue depth |
| Errors      | How many operations are failing or being retried | Packet drops, disk I/O errors, HTTP 5xx count |

If any of the three dimensions is abnormal, the resource is a candidate for the bottleneck. The power comes from *applying this checklist uniformly* across servers, containers, and even logical components such as thread pools.

> **Note**: The original description of the method can be found on Brendan Gregg’s site, where he emphasizes “the three most useful metrics for any system resource” — see the [USE method page](https://www.brendangregg.com/usemethod.html).

### Utilization

Utilization tells you whether a resource is being used close to its capacity. High utilization alone isn’t a problem; a well‑designed system may run at 80 % CPU for most of the day. However, sustained utilization near 100 % often indicates that the resource is a limiting factor.

**Common sources**

* **CPU** – `node_cpu_seconds_total` (Prometheus) or `top`‑style `%CPU`.
* **Memory** – `node_memory_Active_bytes` or `free -m`.
* **Disk** – `node_disk_read_bytes_total` and `node_disk_written_bytes_total`.
* **Network** – `node_network_receive_bytes_total`, `node_network_transmit_bytes_total`.

### Saturation

Saturation measures *demand* versus *service capacity*. A resource can be under‑utilized yet still saturated if there is a backlog waiting for service.

**Typical indicators**

* **CPU run queue** – `node_load1` vs number of cores.
* **Disk I/O latency** – `node_disk_io_time_seconds_total` or `iostat -x`.
* **Network queue depth** – `tc -s qdisc show` on Linux.
* **Thread pool queue size** – application‑specific metrics (e.g., `ExecutorService.queueSize`).

### Errors

Errors surface when a resource cannot fulfill requests, often because of saturation or hardware faults.

**Examples**

* **Kernel dmesg errors** – `dmesg | grep -i error`.
* **Filesystem errors** – `smartctl -a /dev/sda` for SMART failures.
* **Application error counters** – Prometheus `http_requests_total{status=~"5.."}`.

## Applying USE in Real‑World Environments

The method is only as good as the data you feed into it. Below is a practical workflow that works with popular open‑source observability stacks (Prometheus + Grafana, Loki for logs, and Jaeger for tracing). Feel free to substitute equivalents like InfluxDB, Datadog, or Splunk.

### 1. Collect the Right Metrics

Start by ensuring you have exporters that expose the three dimensions for every node and service.

```bash
# Install node_exporter on a Linux host (Ubuntu example)
wget https://github.com/prometheus/node_exporter/releases/download/v1.8.0/node_exporter-1.8.0.linux-amd64.tar.gz
tar xzf node_exporter-1.8.0.linux-amd64.tar.gz
sudo cp node_exporter-1.8.0.linux-amd64/node_exporter /usr/local/bin/
sudo useradd --no-create-home --shell /bin/false node_exporter
sudo chown node_exporter:node_exporter /usr/local/bin/node_exporter
# Run as a systemd service
cat <<EOF | sudo tee /etc/systemd/system/node_exporter.service
[Unit]
Description=Prometheus Node Exporter
After=network.target

[Service]
User=node_exporter
Group=node_exporter
ExecStart=/usr/local/bin/node_exporter

[Install]
WantedBy=default.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now node_exporter
```

For containerized workloads, the **cAdvisor** exporter or **kube‑state‑metrics** provide per‑pod CPU and memory utilization, while **cilium** can expose network queue depth.

### 2. Build a USE‑Focused Dashboard

A single Grafana dashboard can surface utilization, saturation, and errors side‑by‑side. Below is a minimal JSON snippet for a CPU panel that follows the USE pattern. (You would import it via Grafana UI → **Dashboard → Import**.)

```json
{
  "type": "timeseries",
  "title": "CPU Utilization & Saturation",
  "targets": [
    {
      "expr": "100 - (avg by (instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)",
      "legendFormat": "{{instance}} Utilization"
    },
    {
      "expr": "avg by (instance) (node_load1) / count by (instance) (node_cpu_seconds_total)",
      "legendFormat": "{{instance}} Run Queue (Saturation)"
    }
  },
  "fieldConfig": {
    "defaults": {
      "unit": "percent",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "color": "green", "value": null },
          { "color": "orange", "value": 80 },
          { "color": "red", "value": 95 }
        ]
      }
    }
  }
}
```

Repeat similar panels for **disk I/O latency**, **network queue depth**, and **error counters**. The visual thresholds (green → orange → red) give you an at‑a‑glance health status.

### 3. Correlate with Traces

When a metric indicates saturation, drill down with distributed traces. For example, if the **disk run queue** spikes, trace the slowest database query using Jaeger:

```bash
# Query Jaeger UI for traces longer than 2 seconds in the last 5 minutes
curl -G 'http://jaeger-query:16686/api/traces' \
  --data-urlencode 'service=order-service' \
  --data-urlencode 'minDuration=2000000' \
  --data-urlencode 'lookback=5m' \
  --data-urlencode 'limit=20' | jq .
```

The trace will reveal whether the latency originates from the application layer, the DB driver, or the underlying storage subsystem.

### 4. Perform Root‑Cause Analysis

Once you have the three dimensions plotted and a suspect trace, follow this structured checklist:

1. **Is utilization high?** If yes, consider scaling out or upgrading the resource.
2. **Is saturation high but utilization moderate?** Look for queue buildup, lock contention, or bursty traffic patterns.
3. **Are errors rising?** Check hardware logs (`dmesg`, SMART data) or application retry loops.

Document each step in an incident post‑mortem to reinforce the habit of using the USE method consistently.

## Common Pitfalls and How to Avoid Them

Even a simple framework can be misapplied. Below are frequent mistakes and corrective actions.

| Pitfall | Why It Happens | Remedy |
|---------|----------------|--------|
| **Collecting too many metrics** | “More data = better insight” mentality leads to noisy dashboards. | Stick to the three core dimensions per resource. Use alerts on these metrics only. |
| **Ignoring baseline behavior** | Jumping to conclusions without knowing normal peaks. | Establish a 30‑day baseline for each metric; configure Grafana’s **stat** panels to show deviation from baseline. |
| **Misreading saturation as utilization** | A run‑queue of 0.5 on a 4‑core machine looks low, but per‑core demand may be high. | Normalize saturation metrics (e.g., run‑queue ÷ cores). |
| **Treating errors as unrelated** | Errors often surface *after* saturation, leading to delayed detection. | Set alerts on error rate *and* on saturation; prioritize the latter for proactive fixes. |
| **One‑off analysis** | Performing USE analysis only during incidents creates a reactive culture. | Schedule weekly health reviews where the team runs the USE checklist on all services. |

## Key Takeaways

- The USE method reduces bottleneck hunting to three high‑signal metrics: **Utilization**, **Saturation**, **Errors**.  
- Instrument every host and service with exporters that expose these dimensions; Prometheus + node_exporter is a solid baseline.  
- A focused Grafana dashboard lets you spot abnormal resources instantly; use color thresholds to guide the eye.  
- Correlate metric spikes with distributed traces (Jaeger, Zipkin) to locate the exact code path responsible.  
- Avoid metric overload, establish baselines, and make USE a regular health‑check ritual, not just an incident‑response tool.  

## Further Reading

- [The USE Method – Brendan Gregg](https://www.brendangregg.com/usemethod.html) – Original description and rationale.  
- [Prometheus Documentation – Exporters Overview](https://prometheus.io/docs/instrumenting/exporters/) – How to collect utilization, saturation, and error metrics.  
- [Grafana Dashboard Best Practices](https://grafana.com/docs/grafana/latest/dashboards/) – Tips for building clear, actionable visualizations.  
- [Jaeger Distributed Tracing](https://www.jaegertracing.io/docs/) – End‑to‑end tracing integration with metric alerts.  
- [Linux Performance Tools – iostat, vmstat, and netstat](https://www.kernel.org/doc/html/latest/driver-api/overview.html) – Command‑line utilities for on‑the‑fly checks