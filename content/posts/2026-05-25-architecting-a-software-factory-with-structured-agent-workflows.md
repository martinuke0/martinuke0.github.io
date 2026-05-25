---
title: "Architecting a Software Factory with Structured Agent Workflows"
date: "2026-05-25T02:00:39.308"
draft: false
tags: ["software factory", "agent workflows", "pipeline patterns", "production", "architecture"]
description: "Explore concrete patterns and production pipelines for building a software factory using structured agent workflows, with Kafka and Airflow implementations."
summary: "A deep dive into architecting a software factory, covering workflow patterns, pipeline design, and production deployment using proven tools."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-25-architecting-a-software-factory-with-structured-agent-workflows.svg"
  alt: "Diagram of agents orchestrating a software factory pipeline."
  caption: ""
  relative: false
---

> **TL;DR** — Structured agent workflows let you compose reusable, observable micro‑services into a scalable software factory. By combining pattern‑driven design with Kafka‑backed event streams and Airflow‑orchestrated pipelines, you can ship code, run tests, and deploy artifacts reliably at enterprise scale.

Building a software factory means treating the entire lifecycle of a code change—lint, test, build, containerize, and deploy—as a repeatable, observable pipeline. In production, the hardest part is not the individual steps but the glue that coordinates them, handles failures, and provides traceability. This post walks through the patterns that make agent‑centric workflows robust, shows a concrete architecture built on Kafka and Apache Airflow, and shares production‑ready snippets you can copy into your own environment.

## Why Structured Agent Workflows Matter

### The problem with ad‑hoc scripts

Most teams start with a handful of Bash scripts that invoke `docker build`, `pytest`, or `kubectl`. Over time these scripts diverge:

* **Hidden dependencies** – scripts assume a particular Python version or a local Docker daemon.
* **Scattered state** – logs end up in `/tmp`, making troubleshooting difficult.
* **No retry semantics** – a flaky network call aborts the whole pipeline.

When you scale to dozens of services, the cost of these hidden assumptions grows exponentially.

### The agent‑first approach

An *agent* is a small, single‑purpose service that:

1. **Exposes a well‑defined API** (REST, gRPC, or message‑based).
2. **Encapsulates its own state** (e.g., a Docker image tag, a test report).
3. **Publishes events** to a central bus (Kafka) on success or failure.

These agents can be composed into *workflows*—directed acyclic graphs (DAGs) that describe the order of execution. Because each node is a contract‑driven service, you gain:

* **Observability** – every state change is an event you can query.
* **Idempotency** – re‑running a step simply reprocesses the same input.
* **Extensibility** – swap a unit test agent for a security scan without touching the DAG.

## Core Patterns for Agent‑Based Pipelines

### 1. Event‑Driven Chaining

Instead of a master script pulling results, each agent publishes a Kafka message like `code.build.completed`. Downstream agents subscribe to the topic and trigger when the payload matches their criteria.

```yaml
# kafka-topics.yaml
---
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: code-build-completed
spec:
  partitions: 12
  replicas: 3
  config:
    retention.ms: 86400000
```

> **Note:** Using a partitioned topic lets you scale consumers horizontally while preserving ordering per key (e.g., per repository).

### 2. Correlation IDs & Saga Coordination

A *saga* tracks the lifecycle of a change request across agents. Each request gets a UUID (`correlation_id`) that travels with every event, enabling end‑to‑end tracing in tools like Jaeger or OpenTelemetry.

```python
# saga.py
import uuid
import json
from kafka import KafkaProducer

producer = KafkaProducer(bootstrap_servers="kafka:9092",
                         value_serializer=lambda v: json.dumps(v).encode())

def start_saga(repo, commit):
    saga_id = str(uuid.uuid4())
    event = {"saga_id": saga_id,
             "repo": repo,
             "commit": commit,
             "type": "saga.started"}
    producer.send("saga-events", event)
    return saga_id
```

### 3. Circuit Breaker & Retry Middleware

Agents should never block the whole pipeline on a transient failure. A lightweight middleware layer can wrap HTTP calls with exponential back‑off and circuit‑breaker semantics.

```go
// retry.go (Go example)
func DoWithRetry(req *http.Request) (*http.Response, error) {
    backoff := backoff.NewExponentialBackOff()
    var resp *http.Response
    operation := func() error {
        var err error
        resp, err = http.DefaultClient.Do(req)
        if err != nil || resp.StatusCode >= 500 {
            return fmt.Errorf("transient failure")
        }
        return nil
    }
    err := backoff.Retry(operation, backoff)
    return resp, err
}
```

## Architecture Overview

Below is a high‑level diagram of a production‑grade software factory built on the patterns above. The key components are:

* **Kafka Cluster** – central event bus.
* **Airflow Scheduler** – orchestrates DAGs that *invoke* agents via HTTP or Kafka.
* **Agent Registry** – a service‑mesh (e.g., Istio) that provides service discovery and mutual TLS.
* **Observability Stack** – Prometheus + Grafana for metrics, Loki for logs, Jaeger for traces.
* **State Store** – PostgreSQL stores saga metadata and artifact versions.

```
┌─────────────────────┐      ┌─────────────────────┐
│   Git Repository    │      │   Artifact Registry │
│   (GitHub, GitLab)  │      │   (Docker, Helm)    │
└─────────┬───────────┘      └───────┬─────────────┘
          │                          │
          ▼                          ▼
   ┌─────────────┐          ┌─────────────────┐
   │  Webhook →  │          │  Artifact Push  │
   │  Airflow    │          │  Event → Kafka  │
   └─────┬───────┘          └───────┬─────────┘
         │                          │
         ▼                          ▼
   ┌─────────────┐          ┌─────────────────┐
   │ Airflow DAG │───►─────►│   Build Agent   │
   │ (orchestration)│      │ (Docker Build) │
   └─────┬───────┘          └───────┬─────────┘
         │                          │
         ▼                          ▼
   ┌─────────────┐          ┌─────────────────┐
   │ Test Agent  │◄───────►│  Publish Event  │
   │ (pytest)    │          │  code.test.done│
   └─────┬───────┘          └───────┬─────────┘
         │                          │
         ▼                          ▼
   ┌─────────────┐          ┌─────────────────┐
   │ Deploy Agent│◄───────►│  Deploy Event   │
   │ (kubectl)   │          │  code.deploy   │
   └─────────────┘          └─────────────────┘
```

*The diagram is simplified; in production each arrow represents a Kafka topic or an HTTP call wrapped by the middleware described earlier.*

## Pipeline Design in Apache Airflow

Airflow provides a familiar DAG definition language while allowing us to offload heavy lifting to agents. The DAG below demonstrates a *code‑to‑deploy* pipeline that respects the event‑driven patterns.

```python
# airflow_dag.py
from airflow import DAG
from airflow.operators.http_operator import SimpleHttpOperator
from airflow.providers.apache.kafka.operators.kafka import KafkaProducerOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "devops",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="software_factory",
    start_date=datetime(2026, 1, 1),
    schedule_interval=None,
    default_args=default_args,
    catchup=False,
) as dag:

    trigger_build = SimpleHttpOperator(
        task_id="trigger_build",
        http_conn_id="agent_build",
        endpoint="/build",
        method="POST",
        data='{"repo":"{{ dag_run.conf.repo }}","commit":"{{ dag_run.conf.commit }}"}',
        headers={"Content-Type": "application/json"},
    )

    wait_build = KafkaProducerOperator(
        task_id="wait_build",
        topic="code-build-completed",
        bootstrap_servers="kafka:9092",
        value="{{ ti.xcom_pull(task_ids='trigger_build') }}",
        consumer_group="airflow-build-waiter",
        timeout=600,
    )

    trigger_test = SimpleHttpOperator(
        task_id="trigger_test",
        http_conn_id="agent_test",
        endpoint="/test",
        method="POST",
        data='{{ ti.xcom_pull(task_ids="wait_build") }}',
    )

    wait_test = KafkaProducerOperator(
        task_id="wait_test",
        topic="code-test-completed",
        bootstrap_servers="kafka:9092",
        value="{{ ti.xcom_pull(task_ids='trigger_test') }}",
        consumer_group="airflow-test-waiter",
        timeout=600,
    )

    trigger_deploy = SimpleHttpOperator(
        task_id="trigger_deploy",
        http_conn_id="agent_deploy",
        endpoint="/deploy",
        method="POST",
        data='{{ ti.xcom_pull(task_ids="wait_test") }}',
    )

    trigger_build >> wait_build >> trigger_test >> wait_test >> trigger_deploy
```

Key points:

* **Idempotent triggers** – each `SimpleHttpOperator` sends a POST with a payload that includes the `correlation_id`. The agent validates the ID before starting work.
* **Kafka wait operators** – they block until the expected event arrives, turning an asynchronous system into a deterministic DAG.
* **Timeouts** – if an agent fails to emit an event within 10 minutes, Airflow marks the step failed, and the saga’s circuit‑breaker logic can compensate (e.g., roll back a partially built image).

## Production Implementation Details

### 1. Deploying Agents with Docker Compose & Kubernetes

Each agent runs as a container behind a sidecar Envoy proxy for mutual TLS. Below is a minimal `docker-compose.yml` for local testing; the same image is promoted to a Helm chart for production.

```yaml
# docker-compose.yml
version: "3.8"
services:
  build-agent:
    image: myorg/build-agent:2.1
    environment:
      - KAFKA_BOOTSTRAP=kafka:9092
      - LOG_LEVEL=info
    ports:
      - "8081:8080"
    depends_on:
      - kafka
  test-agent:
    image: myorg/test-agent:2.1
    environment:
      - KAFKA_BOOTSTRAP=kafka:9092
    ports:
      - "8082:8080"
    depends_on:
      - kafka
  kafka:
    image: bitnami/kafka:3
    environment:
      - KAFKA_CFG_BROKER_ID=1
      - KAFKA_CFG_ZOOKEEPER_CONNECT=zookeeper:2181
    ports:
      - "9092:9092"
  zookeeper:
    image: bitnami/zookeeper:3
    ports:
      - "2181:2181"
```

In production, you would replace this with a Helm release that configures:

* **Horizontal Pod Autoscaling** based on CPU and Kafka lag.
* **PodDisruptionBudgets** to avoid simultaneous restarts.
* **NetworkPolicies** that only allow inbound traffic from the service mesh.

### 2. Secure Event Transport

Kafka TLS encryption and SASL authentication protect payloads. The `kafka.yaml` snippet below shows the security config for Strimzi.

```yaml
# strimzi-kafka.yaml
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: prod-cluster
spec:
  kafka:
    version: 3.5.0
    replicas: 3
    listeners:
      - name: external
        port: 9094
        type: loadbalancer
        tls: true
        authentication:
          type: scram-sha-512
    config:
      offsets.topic.replication.factor: 3
      transaction.state.log.replication.factor: 3
      transaction.state.log.min.isr: 2
  zookeeper:
    replicas: 3
  entityOperator:
    topicOperator: {}
    userOperator: {}
```

### 3. Observability Integration

Each agent emits Prometheus metrics (`/metrics` endpoint) and OpenTelemetry traces. A typical metric definition in Go:

```go
var (
    buildDuration = prometheus.NewHistogramVec(prometheus.HistogramOpts{
        Namespace: "software_factory",
        Subsystem: "build_agent",
        Name:      "duration_seconds",
        Help:      "Duration of Docker builds.",
        Buckets:   prometheus.ExponentialBuckets(1, 2, 10),
    }, []string{"status"})
)

func init() {
    prometheus.MustRegister(buildDuration)
}
```

Traces are exported to Jaeger via the OpenTelemetry collector, allowing you to see the full saga flow from "repo push" to "deployment completed."

## Handling Failure Modes in Production

| Failure Mode                     | Detection                              | Mitigation Strategy |
|----------------------------------|----------------------------------------|---------------------|
| Kafka partition lag              | Consumer lag metrics in Prometheus     | Auto‑scale consumers; enable back‑pressure |
| Agent container crash            | Kubernetes pod restart count           | Restart policy + alert; fallback to previous artifact |
| Network partition between mesh   | Service mesh health checks             | Circuit breaker; fallback to cached artifacts |
| Build timeout (e.g., runaway `npm install`) | Build agent emits `build.timeout` event | Abort saga, notify Slack, trigger rollback |
| Test flakiness                   | High failure rate in `code-test-failed` events | Auto‑retry up to N times, then open ticket |

By codifying these patterns, you turn ad‑hoc failure handling into deterministic, observable logic.

## Key Takeaways

- **Agents as contracts**: Encapsulate each CI/CD step behind an API and publish events, making the workflow composable and observable.
- **Event‑driven DAGs**: Use Kafka topics to turn asynchronous agents into deterministic Airflow pipelines.
- **Saga correlation**: Propagate a UUID through every event to achieve end‑to‑end tracing and idempotent retries.
- **Production guardrails**: Secure Kafka, auto‑scale agents, and integrate Prometheus/Jaeger for real‑time health signals.
- **Failure patterns**: Explicitly model back‑pressure, timeouts, and circuit‑breakers to keep the factory humming under load.

## Further Reading

- [Apache Airflow Documentation](https://airflow.apache.org/docs)
- [Apache Kafka Official Documentation](https://kafka.apache.org/documentation)
- [OpenTelemetry Collector Overview](https://opentelemetry.io/docs/collector/)
- [Strimzi Kafka Operator Guide](https://strimzi.io/docs/operators/latest/)
- [Kubernetes Horizontal Pod Autoscaling](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/)