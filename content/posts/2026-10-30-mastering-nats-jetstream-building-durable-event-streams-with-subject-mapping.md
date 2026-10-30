---
title: "Mastering NATS JetStream: Building Durable Event Streams with Subject Mapping"
date: "2026-10-30T10:01:28.404"
draft: false
tags: ["NATS", "JetStream", "Event Streaming", "Subject Mapping", "Durable", "Message Queuing"]
description: "Learn how to design durable event streams with NATS JetStream using subject mapping, covering architecture, patterns, and production best practices."
summary: "A practical guide to NATS JetStream subject mapping for building resilient, high‑throughput event pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-30-mastering-nats-jetstream-building-durable-event-streams-with-subject-mapping.svg"
  alt: "NATS JetStream architecture diagram"
  caption: ""
  relative: false
---

> **TL;DR** — NATS JetStream provides durable, at-least-once delivery for event streams, and subject mapping lets you route and transform messages without writing custom code. By defining explicit subject patterns, you can enforce consistency, enable replay, and scale horizontally across clusters.

Event streaming is a cornerstone of modern microservice architectures, and NATS JetStream has emerged as a lightweight yet powerful platform for building durable pipelines. While the core publish/subscribe model of NATS is familiar, JetStream introduces persistent streams and the ability to map subjects, which unlocks a new level of flexibility. In this post, we’ll dive deep into subject mapping: why it matters, how to design it for production, and the patterns that keep your event bus resilient and observable.

## Why Subject Mapping Matters

Subject mapping in JetStream is more than a routing convenience; it’s a contract that defines how events flow through your system. Without it, developers often resort to ad‑hoc topic names that quickly become a maintenance nightmare. A well‑crafted mapping strategy provides:

- **Explicit contracts** – each event type has a predictable subject, making it easier to version and document.
- **Built‑in transformation** – you can rewrite or filter subjects on the fly, eliminating the need for external routers.
- **Replay capability** – because streams are tied to subjects, you can replay a specific event type without touching unrelated data.
- **Isolation** – different teams can own distinct subject hierarchies, reducing coupling and enabling independent scaling.

In a real‑world e‑commerce platform, for example, order events might be published to `order.created`, `order.updated`, and `order.cancelled`. By mapping these to a single stream `ORDER_EVENTS`, the downstream services can consume the entire lifecycle while retaining the ability to filter by specific actions.

## Core Concepts

### Subjects and Streams

In NATS, a subject is a hierarchical string separated by dots (e.g., `us.east.order.created`). A JetStream stream stores messages for one or more subjects. The relationship is defined when you create the stream:

```bash
nats stream create ORDER_EVENTS \
  --subjects "order.*,order.>" \
  --retention limits \
  --discard old \
  --max-age 24h \
  --max-bytes 10GB \
  --replicas 3
```

Here, `order.*` matches exactly one token after `order`, while `order.>` matches any number of trailing tokens. This simple wildcard syntax is the foundation of subject mapping.

### Mapping Rules

JetStream supports two types of subject mapping:

1. **Static mapping** – you explicitly list subjects when creating the stream.
2. **Dynamic mapping** – you use wildcards to capture a family of subjects, then optionally rewrite them with a `--target` flag.

Dynamic mapping is particularly useful for multi‑tenant scenarios. For instance, a SaaS provider can ingest events from each customer under `tenant.{customerID}.events.>` and map them to a single internal stream `INTERNAL_EVENTS` while preserving the original subject for auditing.

```yaml
# Example of a stream configuration with subject rewriting
apiVersion: jetstream.nats.io/v1beta1
kind: Stream
metadata:
  name: INTERNAL_EVENTS
spec:
  subjects:
    - "tenant.*.events.>"
  retention: limits
  discard: old
  maxAge: "24h"
  maxBytes: 10000000000
  replicas: 3
  # Rewriting is done via the 'target' field in the JetStream API
  # or via the 'nats stream edit' command with --target
```

## Architecture in Production

### Cluster Topology

A production JetStream cluster typically consists of a set of **stream servers** and **consumer servers**. The stream servers hold the persistent storage, while consumer servers handle subscription and delivery. Subject mapping influences where streams are placed:

- **High‑throughput subjects** (e.g., `metrics.*`) should reside on nodes with fast SSDs and ample memory.
- **Long‑retention subjects** (e.g., `audit.*`) may be placed on nodes with large capacity drives.

Using NATS’s **super‑cluster** topology, you can group stream servers into **regions** (e.g., `us-east`, `eu-west`) and route subjects accordingly. This reduces latency for local consumers and provides geographic redundancy.

### Stream Placement

When you define a stream with multiple replicas, JetStream distributes the stream across the cluster. Subject mapping can be used to **pin** a stream to a specific set of nodes by leveraging **labels**:

```bash
nats stream create ORDER_EVENTS \
  --subjects "order.*,order.>" \
  --replicas 3 \
  --label "region=us-east,storage=ssd"
```

Only nodes matching the labels will be considered for replica placement, ensuring that latency‑sensitive order events stay on low‑latency hardware.

## Patterns in Production

### Event Versioning

Subject mapping enables a clean versioning strategy. A common pattern is to embed the version in the subject:

```
v1.order.created
v2.order.created
```

You can create separate streams for each version, or use a single stream with a wildcard that captures both. The latter simplifies consumer logic because you can subscribe to `order.created` and receive all versions, then filter internally.

### Multi‑Tenant Routing

For SaaS platforms, isolating tenants is critical. By using a tenant identifier in the subject, you can route each tenant’s events to a dedicated stream or to a shared stream with a **subject filter**:

```bash
nats stream create TENANT_EVENTS \
  --subjects "tenant.*.events.>" \
  --target "internal.events" \
  --replicas 3
```

Here, all tenant events are rewritten to `internal.events`, allowing a single consumer group to process them while preserving the original subject for logging and auditing.

## Step‑by‑Step Implementation

### Creating a Stream

The simplest way to create a stream is via the NATS CLI:

```bash
nats stream create MY_STREAM \
  --subjects "events.*,events.>" \
  --retention limits \
  --discard old \
  --max-age 7d \
  --max-bytes 5GB \
  --replicas 3
```

### Defining Subject Mappings

You can also define mappings programmatically using the JetStream API. Below is a Python example that creates a stream with a dynamic subject mapping:

```python
import asyncio
from nats.js.api import StreamConfiguration, RetentionPolicy, DiscardPolicy
from nats.js.client import JetStreamContext

async def create_stream():
    nc = await nats.connect("nats://localhost:4222")
    js = nc.jetstream()

    config = StreamConfiguration(
        name="MY_STREAM",
        subjects=["events.*,events.>"],
        retention=RetentionPolicy.LIMITS,
        discard=DiscardPolicy.OLD,
        max_age=7 * 24 * 60 * 60,  # 7 days
        max_bytes=5 * 1024 * 1024 * 1024,  # 5 GB
        replica_count=3,
        # You can add a 'target' field to rewrite subjects
        # target="internal.events"
    )
    await js.create_stream(config)
    await nc.close()

asyncio.run(create_stream())
```

### Publishing and Consuming

Publishing is straightforward:

```python
await js.publish("events.order.created", b"{'order_id': 123}")
```

Consuming can be done with **pull consumers** or **push consumers**. A pull consumer is ideal for work‑queue patterns:

```python
subscription = await js.pull_subscribe("events.*", durable="worker")
msg = await subscription.fetch(batch=1, timeout=1)
await msg.ack()
```

For real‑time processing, a push consumer with a queue group ensures load balancing:

```python
await js.subscribe("events.*", queue="workers", cb=handler)
```

## Monitoring and Observability

### Metrics

JetStream exposes a rich set of Prometheus metrics. Key indicators include:

- `jetstream_stream_messages_total` – total messages stored per stream.
- `jetstream_consumer_ack_pending` – number of unacknowledged messages per consumer.
- `jetstream_stream_replicas` – replica count and health.

You can visualize these in Grafana dashboards to detect backpressure or replication lag.

### Logging

Enable **debug logging** during development, then switch to **info** level in production. Structured logs (JSON) make it easier to correlate events across services. For example:

```json
{
  "level": "info",
  "msg": "message published",
  "subject": "events.order.created",
  "stream": "MY_STREAM",
  "size": 42
}
```

## Key Takeaways

- Subject mapping transforms NATS JetStream from a simple pub/sub system into a flexible event routing layer.
- Use wildcards and rewriting to enforce contracts, isolate tenants, and enable replay.
- Design your cluster topology with stream placement in mind; leverage labels and regions for latency optimization.
- Implement versioning in subjects to evolve your event schema without breaking consumers.
- Monitor stream health with Prometheus metrics and structured logs for rapid troubleshooting.

## Further Reading

- [NATS JetStream Documentation](https://docs.nats.io/jetstream)
- [JetStream Subject Mapping Guide](https://docs.nats.io/jetstream/subject-mapping)
- [NATS CLI Stream Management](https://docs.nats.io/nats-cli/jetstream)
- [Scaling JetStream with Super Clusters](https://docs.nats.io/jetstream/clusters)
- [Monitoring NATS with Prometheus](https://docs.nats.io/monitoring/prometheus)