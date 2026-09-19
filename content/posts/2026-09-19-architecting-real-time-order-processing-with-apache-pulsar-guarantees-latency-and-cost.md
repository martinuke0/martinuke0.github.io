

---
title: "Architecting Real-time Order Processing with Apache Pulsar: Guarantees, Latency, and Cost"
date: "2026-09-19T14:01:30.135"
draft: false
tags: ["Apache Pulsar", "Real-time", "Order Processing", "Event Streaming", "Architecture"]
description: "Learn how to design low-latency, exactly-once order processing pipelines using Apache Pulsar, with guarantees, latency tuning, and cost tradeoffs."
summary: "Apache Pulsar delivers exactly-once semantics and sub-millisecond latency for order processing, while its tiered storage and cost-aware pricing keep expenses predictable."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-19-architecting-real-time-order-processing-with-apache-pulsar-guarantees-latency-and-cost.svg"
  alt: "Order processing pipeline diagram"
  caption: ""
  relative: false
---

> **TL;DR** — Apache Pulsar provides exactly‑once delivery and partition‑level ordering, enabling sub‑millisecond order processing. By separating storage from compute and using tiered storage, you can achieve low latency while controlling cost. Design your pipeline with idempotent producers, compacted topics, and careful consumer‑group sizing to meet SLAs.

In modern e‑commerce, the moment a customer clicks “Place Order” the system must atomically reserve inventory, charge payment, and notify fulfillment—all while presenting a responsive UI. Traditional request‑response stacks often buckle under the resulting burst of synchronous calls, leading to latency spikes and inconsistent state. Event‑driven architectures built on Apache Pulsar address these challenges by decoupling services, guaranteeing delivery semantics, and offering a cost model that scales with throughput rather than idle resources.

## Architecture Overview

A typical Pulsar‑based order processing pipeline consists of three logical layers:

1. **Ingress** – A lightweight API gateway or edge service publishes raw order events to a Pulsar topic (e.g., `orders.raw`). Producers can be written in any language; the Pulsar client handles batching, compression, and retry logic.

2. **Processing** – One or more consumer groups subscribe to the topic. Each group performs a specific transformation: validation, inventory reservation, payment authorization, or enrichment. Because Pulsar supports **partitioned topics**, you can scale consumers horizontally by adding more partitions.

3. **Sink** – Processed events are either written to a durable store (e.g., PostgreSQL, Cassandra) via a Pulsar connector, or forwarded to downstream systems (e.g., Kafka, Kinesis) using Pulsar’s **IO Connectors**.

The diagram below (conceptual) illustrates the flow:

```
[Client] → (HTTP) → [API GW] → Pulsar Producer → orders.raw
                                          ↓
                         ┌-------------------------┐
                         |  Consumer Group A (val) |
                         └-------------------------┘
                                          ↓
                         ┌-------------------------┐
                         |  Consumer Group B (pay) |
                         └-------------------------┘
                                          ↓
                         ┌-------------------------┐
                         |  Sink → DB / Analytics  |
                         └-------------------------┘
```

### Key Design Decisions

- **Topic Partitioning** – Choose a partition key that reflects the entity you want to order by (e.g., `orderId` or `customerId`). This guarantees that all events for a given order are processed by the same consumer, preserving ordering guarantees.

- **Subscription Types** – Use **Exclusive** subscriptions for stateful processors (e.g., inventory reservation) and **Failover** or **Shared** subscriptions for stateless workers (e.g., notification services).

- **Compaction** – For topics that act as a source of truth (e.g., `orders.compacted`), enable topic compaction to retain only the latest value per key, reducing storage footprint.

## Guarantees: Exactly‑Once and Ordering

Apache Pulsar’s delivery semantics are a core differentiator. By default, Pulsar offers **at‑least‑once** delivery, but with the right configuration you can achieve **exactly‑once** processing.

### Exactly‑Once with Transactional Topics

Pulsar introduced **transactional topics** (available since 2.8.0) that allow you to atomically produce and consume across multiple topics. The following Java snippet shows how to configure a producer for exactly‑once:

```java
PulsarClient client = PulsarClient.builder()
        .serviceUrl("pulsar://broker:6650")
        .build();

Producer<byte[]> producer = client.newProducer()
        .topic("orders.raw")
        .enableBatching(true)
        .batchingMaxBytes(1024 * 1024)
        .batchingMaxPublishDelay(5, TimeUnit.MILLISECONDS)
        .compressionType(CompressionType.ZSTD)
        .create();
```

To guarantee exactly‑once, you must also enable **transaction support** on the client and use `Transaction` APIs:

```java
Transaction txn = client.newTransaction()
        .withTimeout(5, TimeUnit.MINUTES)
        .create();

producer.newMessage(txn)
        .key(orderId)
        .value(orderBytes)
        .send();

txn.commit().get();
```

If the transaction fails, you can roll back, ensuring that no partial writes appear to downstream consumers.

### Ordering Guarantees

Pulsar preserves **order within a partition** as long as the producer uses a consistent partition key. For scenarios requiring global order across partitions, you can:

- Use a **single partition** (not scalable) or
- Implement a **sequencer** service that assigns monotonic sequence numbers and reorders events in the consumer.

In practice, most order processing systems rely on **per‑order ordering**, which aligns naturally with partition‑key design.

## Latency: From Producer to Consumer

Latency in a Pulsar pipeline is influenced by several factors:

| Factor | Impact | Mitigation |
|--------|--------|------------|
| **Producer batching** | Increases end‑to‑end latency if batch window is large | Keep `batchingMaxPublishDelay` low (1‑5 ms) |
| **Network RTT** | Directly adds to message delivery time | Deploy brokers in the same AZ as producers |
| **Consumer prefetch** | Reduces latency by pre‑fetching messages | Tune `receiverQueueSize` (default 1000) |
| **Broker load** | High CPU/IO causes queuing delay | Scale out brokers, use **load‑balanced** topics |
| **Storage tier** | Hot data in SSD, cold in object store | Use **tiered storage** to keep hot set small |

A production‑grade configuration for low‑latency order processing might look like:

```yaml
broker:
  maxMessageSize: 5MB
  maxMessageDispatchedInBatch: 1000
  maxMessageDispatchedInBatchDelayMs: 10

producer:
  batchingEnabled: true
  batchingMaxBytes: 1MB
  batchingMaxPublishDelayMs: 2

consumer:
  receiverQueueSize: 500
  autoAckTimeoutMs: 30000
```

With these settings, end‑to‑end latency typically stays **under 10 ms** for intra‑datacenter traffic, and **under 50 ms** when crossing regions.

## Cost Model: Storage, Throughput, and Operations

Pulsar’s cost model is distinct from many other streaming platforms because it separates **storage** from **compute**.

- **Storage** – Data is stored in a distributed ledger (BookKeeper) and can be tiered to cheaper object storage (e.g., S3, GCS) after a retention period. You pay for the volume of data retained, not for the number of brokers.

- **Throughput** – Broker CPU and network usage scale with message rate. Pulsar’s **horizontal scaling** allows you to add brokers as traffic grows, and you only pay for the resources you consume.

- **Operations** – Because Pulsar uses a **stateless broker** architecture, you can upgrade or replace brokers without data loss, reducing operational overhead.

A rough cost estimate for a mid‑size e‑commerce platform (10 M orders/day, 1 KB each) might be:

| Component | Monthly Cost (USD) |
|-----------|--------------------|
| 3 broker nodes (m5.large) | $1,200 |
| BookKeeper storage (SSD) | $0.10/GB → $300 |
| Tiered storage (S3) | $0.023/GB → $70 |
| Network egress | $0.09/GB → $150 |
| **Total** | **≈ $1,720** |

These numbers are illustrative; actual pricing varies by cloud provider and region.

## Patterns in Production

### 1. **Idempotent Producers**

Always attach a **unique message ID** (e.g., UUID) to each order event. Consumers can deduplicate by maintaining a set of processed IDs, preventing double‑processing in case of retries.

### 2. **Compact Topics for State Snapshots**

Use compacted topics to store the latest state of an order (e.g., `orderStatus`). This allows fast lookups without scanning the entire log.

### 3. **Dead‑Letter Queue (DLQ)**

Configure a DLQ topic (`orders.dlq`) for messages that repeatedly fail processing. A separate service can inspect the DLQ, log errors, and optionally re‑publish after fixing the root cause.

### 4. **Consumer Group Isolation**

Run separate consumer groups for **critical** (inventory) and **best‑effort** (analytics) workloads. This prevents slow analytics queries from impacting latency‑sensitive paths.

### 5. **Monitoring and Alerting**

Leverage Pulsar’s built‑in metrics (via Prometheus) such as `pulsar_broker_publish_rate`, `pulsar_consumer_backlog`, and `pulsar_storage_used`. Set alerts on:

- Backlog > 10 k messages for > 5 minutes
- Average end‑to‑end latency > 20 ms
- Broker CPU > 80 %

## Key Takeaways

- **Exactly‑once** is achievable with transactional topics and idempotent producers.
- **Partition‑key design** is the foundation of ordering guarantees.
- **Low latency** requires tuning batching, network placement, and consumer prefetch.
- **Cost control** comes from tiered storage and stateless broker scaling.
- **Operational resilience** is enhanced by DLQs, compacted topics, and isolated consumer groups.

## Further Reading

- [Apache Pulsar Official Documentation](https://pulsar.apache.org/docs/)
- [Pulsar Transactions Guide](https://pulsar.apache.org/docs/concepts/transactions/)
- [BookKeeper Architecture Overview](https://bookkeeper.apache.org/docs/)
- [Tiered Storage in Pulsar](https://pulsar.apache.org/docs/concepts/tiered-storage/)
- [Pulsar Performance Tuning](https://pulsar.apache.org/docs/performance/tuning/)