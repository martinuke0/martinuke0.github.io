---
title: "Designing Multi-Cluster Kubernetes Autoscaling with Custom Metrics: Real-Time Production Strategies"
date: "2026-09-26T22:01:16.857"
draft: false
tags: ["Kubernetes", "Autoscaling", "Custom Metrics", "Multi-Cluster", "HPA", "KEDA", "Production Engineering"]
description: "A deep dive into building multi-cluster Kubernetes autoscaling pipelines driven by custom metrics — from Prometheus to HPA to KEDA — with production-tested strategies, failure modes, and architecture patterns."
summary: "Explore how to design multi-cluster Kubernetes autoscaling powered by custom metrics. Learn the end-to-end pipeline from metrics collection to scaling decisions, production-tested patterns, and the failure modes that catch teams off guard."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-26-designing-multi-cluster-kubernetes-autoscaling-with-custom-metrics-real-time-pro.svg"
  alt: "Kubernetes cluster autoscaling diagram with custom metrics pipeline"
  caption: ""
  relative: false
---

> **TL;DR** — Multi-cluster Kubernetes autoscaling with custom metrics requires stitching together a metrics pipeline (Prometheus → Metrics Adapter → HPA), choosing the right scaling engine (HPA, VPA, or KEDA), and designing failover strategies that prevent cascading failures across clusters. This post walks through the production architecture, configuration patterns, and the real-world pitfalls that turn autoscaling from a promise into a liability.

## The Scaling Problem Nobody Warns You About

Most teams start with the default Horizontal Pod Autoscaler (HPA) — CPU and memory thresholds — and call it a day. That works until your application's real bottleneck is something the resource metrics can't see: queue depth, request latency p99, concurrent WebSocket connections, or RabbitMQ queue saturation.

When default metrics stop reflecting reality, you need custom metrics. And when a single cluster can't absorb traffic spikes, you need multiple clusters. The intersection of these two requirements — custom metrics and multi-cluster scaling — is where most production Kubernetes systems either shine or collapse under load.

The core challenge isn't any single component. It's the pipeline: collecting the metric, exposing it to the Kubernetes API, feeding it to the autoscaler, and doing all of this across clusters without introducing latency or single points of failure.

## Architecture: The End-to-End Metrics-to-Scale Pipeline

### The Metrics Collection Layer

Every custom-metric autoscaling pipeline starts with observability. Prometheus is the de facto standard, but the details matter. You need:

- **Scraping targets** that emit application-level metrics (queue depths, request rates, error ratios).
- **Recording rules** that pre-aggregate high-cardinality data so the metrics adapter isn't querying millions of time series on every scaling interval.
- **Retention tuning** — custom metrics for autoscaling don't need long retention, but you do need them available within the HPA's evaluation window (default 15 seconds).

```yaml
# prometheus/recording-rules.yaml
groups:
  - name: autoscaling_rules
    rules:
      - record: job:http_request_rate:rate5m
        expr: |
          sum(rate(http_requests_total{status=~"2.."}[5m])) by (job, namespace, pod)
      - record: queue:depth:avg
        expr: |
          avg(rabbitmq_queue_messages_ready{queue="processing"}) by (namespace, job)
```

The recording rules are critical. Without them, the metrics adapter queries Prometheus directly on every HPA evaluation cycle, and under load, this becomes a feedback loop: scaling events generate more Prometheus queries, which consume resources, which triggers more scaling events.

### The Metrics Adapter Layer

The Kubernetes Metrics API server sits between Prometheus and the HPA. The `prometheus-adapter` is the most widely used implementation. It translates Prometheus queries into the `custom.metrics.k8s.io` API that HPA consumes.

```yaml
# prometheus-adapter/config.yaml
rules:
  - seriesQuery: 'http_requests_total{namespace!="",pod!=""}'
    resources:
      overrides:
        namespace: {resource: "namespace"}
        pod: {resource: "pod"}
    name:
      matches: "^(.*)_total"
      as: "${1}_per_second"
    metricsQuery: |
      sum(rate(<<.Series>>{<<.LabelMatchers>>}[2m])) by (<<.GroupBy>>)
```

The `metricsQuery` template is where multi-cluster complexity enters the picture. Each cluster has its own Prometheus instance and its own adapter. The HPA in each cluster only sees that cluster's metrics — which is correct behavior, but it means you need a coordination layer if you want cluster-level decisions.

### The Autoscaling Decision Layer

Three engines compete for this role, and the choice shapes everything downstream:

1. **HPA (Horizontal Pod Autoscaler)** — built into Kubernetes, understands CPU/memory/custom metrics natively. Best for stateless workloads with relatively predictable scaling patterns.
2. **VPA (Vertical Pod Autoscaler)** — adjusts pod resource requests and limits. Complements HPA but cannot be used alongside it for the same resource. Best for stateful or memory-intensive workloads.
3. **KEDA (Kubernetes Event-Driven Autoscaling)** — external scaler framework that supports 50+ trigger types (Kafka, RabbitMQ, Prometheus, AWS SQS, Azure Service Bus). Best for event-driven workloads and scenarios where HPA's metric types fall short.

In production, many teams run HPA for baseline scaling and KEDA for event-driven spikes. This hybrid approach lets you maintain a stable minimum replica count while scaling aggressively on queue depth or message backlog.

```yaml
# keda-scaledobject.yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: payment-processor-scaler
  namespace: payments
spec:
  scaleTargetRef:
    name: payment-processor
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring.svc:9090
        metricName: rabbitmq_queue_messages_ready
        query: |
          avg(rabbitmq_queue_messages_ready{queue="payments",namespace="payments"})
        threshold: "50"
        activationThreshold: "10"
```

Note the `activationThreshold` — KEDA scales to zero when the metric is below this value, which is a powerful cost optimization but introduces cold-start latency. For latency-sensitive payment processing, you'd set a higher floor.

## Multi-Cluster Strategies: Beyond Simple Replication

### Pattern 1: Active-Active with Metric-Aware Traffic Splitting

In an active-active setup, multiple clusters serve the same workload. Traffic routing (via global load balancers like GCP Cloud Load Balancing, AWS Route 53, or Istio multicluster) distributes requests based on capacity.

The autoscaling challenge here is that each cluster scales independently based on its local metrics. If Cluster A's Prometheus reports a queue depth spike but Cluster B is idle, traffic doesn't automatically rebalance unless your load balancer supports health-based routing.

**Production pattern:** Deploy a global latency-based router with health checks that consider both cluster readiness and queue depth. Use the `external` metric type in HPA to expose a cross-cluster health signal:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: global-traffic-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api-gateway
  minReplicas: 3
  maxReplicas: 50
  metrics:
    - type: Pods
      pods:
        metric:
          name: local_request_rate
        target:
          type: AverageValue
          averageValue: 1000
    - type: External
      external:
        metric:
          metricName: global_cluster_health_score
          metricSelector:
            matchLabels:
              cluster: "us-east-1"
        target:
          type: AverageValue
          averageValue: "0.8"
```

The `global_cluster_health_score` is a custom metric computed by a controller that aggregates latency, error rate, and queue depth across all clusters and publishes it as an external metric. This lets each cluster's HPA consider the global state, not just local pod metrics.

### Pattern 2: Active-Passive with Failover Scaling

For disaster recovery scenarios, a passive cluster sits warm with minimal replicas. When the active cluster's metrics breach thresholds that indicate capacity exhaustion, the passive cluster scales up and takes over traffic.

This pattern requires a cross-cluster alerting and orchestration layer. Tools like ArgoCD with sync waves, or a custom controller watching Prometheus alertmanager webhooks, can trigger the failover sequence:

1. Active cluster HPA hits `maxReplicas` but queue depth continues rising.
2. Alertmanager fires a `ClusterCapacityExhausted` alert.
3. Failover controller scales the passive cluster's deployment from 2 to 30 replicas.
4. Global load balancer shifts traffic to the passive cluster.
5. Active cluster undergoes remediation.

The critical detail is the **scaling speed differential**. A cluster scaling from 2 to 30 replicas doesn't happen instantly — HPA scales at a default rate of 10% per minute (configurable via `behavior`). You need to pre-configure aggressive scaling behavior for failover scenarios:

```yaml
behavior:
  scaleDown:
    stabilizationWindowSeconds: 300
    policies:
      - type: Percent
        value: 10
        periodSeconds: 60
  scaleUp:
    stabilizationWindowSeconds: 0
    policies:
      - type: Percent
        value: 100
        periodSeconds: 15
      - type: Pods
        value: 20
        periodSeconds: 15
    selectPolicy: Max
```

This configuration allows the HPA to double replicas every 15 seconds during failover, which is essential when you're racing against a traffic spike.

### Pattern 3: Sharded Workloads with Cluster-Aware Routing

Some workloads are naturally sharded — each cluster handles a subset of tenants, regions, or data partitions. In this model, autoscaling is simpler because each cluster is independent, but the operational complexity shifts to ensuring shard balance.

If Cluster A serves 60% of tenants and Cluster B serves 40%, a traffic spike affecting Cluster A's tenants doesn't benefit from Cluster B's spare capacity. The solution is a dynamic shard rebalancing controller that:

- Monitors per-cluster load metrics.
- Migrates tenant shards from overloaded to underloaded clusters.
- Updates DNS or service mesh routing accordingly.

This is the most architecturally complex pattern but offers the best cost efficiency at scale. Companies like Spotify and Airbnb use variants of this for their multi-region Kubernetes deployments.

## Production Pitfalls and Failure Modes

### The Metrics Lag Problem

Custom metrics have inherent latency. Prometheus scrapes at interval N, the adapter queries Prometheus at interval N+1, the HPA evaluates at interval N+2. By the time the autoscaler acts, the metric it's reacting to is already stale.

In practice, this means HPA-based scaling on custom metrics is **reactive, not predictive**. During a rapid traffic spike, the system always lags behind demand. The mitigation is a multi-layered approach:

- Use **burst-based scaling** (KEDA's `activationThreshold` + aggressive HPA `behavior`).
- Deploy **predictive scaling** using tools like Karpenter or custom ML-based predictors that look at historical patterns.
- Maintain a **buffer of warm pods** that absorb the initial spike before the metrics pipeline catches up.

### The Cardinality Explosion

Custom metrics with high cardinality — think `request_duration_seconds_by_endpoint_by_user_id` — will kill your metrics adapter and Prometheus. Every unique label combination creates a new time series, and the adapter must query all of them to compute the average value for HPA.

**Production rule:** Limit custom metrics to labels that are stable and low-cardinality: `namespace`, `pod`, `deployment`, `job`. Never include user IDs, session tokens, or request paths in autoscaling metrics.

```yaml
# BAD: high cardinality
metricsQuery: sum(rate(http_requests_total{<<.LabelMatchers>>}[2m])) by (pod, endpoint, user_id)

# GOOD: controlled cardinality
metricsQuery: sum(rate(http_requests_total{<<.LabelMatchers>>}[2m])) by (pod)
```

### The Cascading Failure Scenario

Here's the scenario that keeps SREs awake: Cluster A experiences a memory leak in a deployment. HPA scales up to `maxReplicas`. Pods crash and restart. HPA scales up again. Prometheus scrapes crashing pods, metrics become erratic. The adapter returns NaN values. HPA enters a backoff state. Meanwhile, traffic shifts to Cluster B, which also begins scaling.

The result is a cascading autoscaling event across clusters. The fix requires:

1. **Pod disruption budgets** to prevent simultaneous mass restarts.
2. **HPA stabilization windows** tuned to prevent rapid oscillation.
3. **Per-cluster circuit breakers** — if Cluster A's error rate exceeds 50%, stop sending it traffic and isolate it rather than trying to scale through the failure.
4. **Metric quality checks** in the adapter — filter out metrics from pods in `CrashLoopBackOff` state before they reach HPA.

### The Cost Blind Spot

Custom metrics autoscaling can be expensive in ways teams don't anticipate. Scaling on queue depth might keep 20 replicas running during a sustained moderate load, whereas CPU-based scaling would have scaled down to 8. The queue-depth strategy buys latency guarantees at the cost of 2.5x compute.

Run cost impact analysis using tools like Kubecost or OpenCost alongside your autoscaling decisions. Every custom metric strategy should have a documented cost model:

| Metric Strategy | Avg Replicas | P99 Latency | Monthly Cost |
|---|---|---|---|
| CPU-based | 8 | 450ms | $2,400 |
| Queue-depth (KEDA) | 14 | 120ms | $4,200 |
| Hybrid (CPU + queue) | 11 | 180ms | $3,300 |

## Key Takeaways

- **The metrics pipeline is the bottleneck.** Recording rules in Prometheus and proper `metricsQuery` templates in the adapter aren't optional — they're the difference between a scaling system that works and one that collapses under its own queries.
- **HPA alone is insufficient for multi-cluster.** You need either external metrics, KEDA, or a custom orchestration layer to coordinate scaling decisions across clusters. Each pattern (active-active, active-passive, sharded) has different tradeoffs.
- **Scaling behavior configuration is production-critical.** The default HPA behavior settings are too conservative for failover scenarios. Define aggressive `scaleUp` policies and reasonable `stabilizationWindowSeconds` per workload.
- **Cardinality kills.** Every autoscaling metric must be scoped to low-cardinality labels. Monitor your Prometheus series count and adapter query latency as first-class metrics.
- **Plan for the failure mode, not the happy path.** Cascading autoscaling failures, metric staleness, and cost overruns are the most common production issues. Build circuit breakers, quality filters, and cost dashboards before you go to production.

## Further Reading

- [Kubernetes Autoscaling Documentation](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) — Official HPA, VPA, and KEDA documentation covering configuration, behavior tuning, and metric types.
- [Prometheus Adapter Configuration Guide](https://github.com/kubernetes-sigs/prometheus-adapter/blob/main/docs/configuration.md) — Complete reference for configuring the metrics adapter, including query templates and label mapping.
- [KEDA ScaledObject and Trigger Documentation](https://keda.sh/docs/concepts/scaling-deployments/) — Detailed guide on event-driven autoscaling with 50+ supported trigger types, including Prometheus, Kafka, and cloud-native queues.
- [Multi-Cluster Kubernetes with Istio](https://istio.io/latest/docs/setup/multicluster/) — Official Istio multicluster setup guide covering traffic management, failover, and service discovery across clusters.
- [Designing Multi-Cluster Kubernetes Architecture](https://cloud.google.com/architecture/multi-cluster-kubernetes) — Google Cloud's architectural patterns for multi-cluster deployments, including traffic splitting, failover, and state management.
- [HPA Behavior Tuning and Stability](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/#configure-hpa-scale-down-rate) — Kubernetes documentation on configuring scale-up and scale-down rates, stabilization windows, and policies to prevent oscillation.
- [Karpenter: Provisioning-Driven Autoscaling](https://karpenter.sh/) — AWS's open-source node autoscaler that complements HPA by provisioning nodes based on pod scheduling requirements rather than just CPU/memory thresholds.
