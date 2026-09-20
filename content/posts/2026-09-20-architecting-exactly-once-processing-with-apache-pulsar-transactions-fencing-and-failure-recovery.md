

---
title: "Architecting Exactly-Once Processing with Apache Pulsar: Transactions, Fencing, and Failure Recovery"
date: "2026-09-20T11:00:51.623"
draft: false
tags: ["Apache Pulsar", "Exactly-Once", "Transactions", "Fencing", "Failure Recovery", "Streaming"]
description: "Learn how to build exactly‑once processing in Apache Pulsar using transactions, fencing, and robust failure recovery patterns for production streaming systems."
summary: "This post explores how to achieve exactly‑once semantics in Apache Pulsar by combining transactions, fencing, and failure recovery techniques for reliable streaming pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-architecting-exactly-once-processing-with-apache-pulsar-transactions-fencing-and-failure-recovery.svg"
  alt: "Apache Pulsar architecture diagram showing transactions and fencing"
  caption: ""
  relative: false
---

> **TL;DR** — Apache Pulsar's transactional messaging and fencing tokens let you build truly exactly‑once pipelines. By wrapping produce/consume operations in transactions and using fencing to isolate stale clients, you can prevent duplicates even during broker failures. This post walks through the core mechanisms, shows production‑grade patterns, and provides code snippets you can adapt.

Exactly‑once processing is a holy grail for streaming engineers. When a system guarantees that each message is processed exactly once, developers can focus on business logic instead of writing idempotency checks or deduplication tables. Apache Pulsar, a cloud‑native distributed pub/sub platform, offers built‑in exactly‑once semantics through two key features: **transactions** and **fencing**. Together they let you build reliable pipelines that survive broker crashes, network partitions, and client restarts without double‑counting or losing data.

## Why Exactly‑Once Matters

In most real‑world applications, a message represents a fact—order placed, payment captured, sensor reading. If the same fact is delivered twice, downstream systems may apply it twice, leading to incorrect aggregates, duplicate charges, or inconsistent state. Traditional at‑least‑once delivery forces you to handle duplicates manually, often with complex key‑value stores or database unique constraints. Exactly‑once semantics eliminate that burden, but they require the messaging system to coordinate producer and consumer acknowledgments atomically.

## Transactions in Pulsar

Pulsar’s transaction API allows you to group one or more **produce** and **consume** operations into an atomic unit. Either all operations succeed and are visible to readers, or none are. This is implemented by a **transaction coordinator** service that logs a two‑phase commit record for each transaction.

A typical transactional flow looks like this:

```java
Transaction transaction = pulsarClient.newTransaction();
try {
    // Produce an event
    producer.send(new MessageBuilder().build());
    // Acknowledge a consumed message
    consumer.ack(msg);
    // Commit the transaction
    transaction.commit();
} catch (Exception e) {
    transaction.rollback();
}
```

The coordinator assigns a unique **transaction ID** and, during the commit phase, writes the ID to a special transaction log topic. Brokers then use this log to ensure that messages produced within a transaction are only visible after the commit completes. If the coordinator crashes before commit, the transaction is rolled back, and the messages are never delivered.

### Key Properties

- **Atomic visibility**: All messages in a transaction become visible to subscribers simultaneously.
- **Isolation**: While a transaction is open, its messages are not visible to other consumers.
- **Recovery**: The coordinator can replay the transaction log after a failure, completing or aborting in‑flight transactions.

## Fencing: Preventing Stale Clients

Even with transactions, a client that has lost its lease can still attempt to produce or consume, causing duplicate processing. Pulsar solves this with **fencing tokens**. Each producer or consumer is issued a monotonically increasing token when it starts. The broker rejects any operation that carries an outdated token.

When a client reconnects, it receives a new, higher token. The old token is “fenced” off, so any messages sent with it are discarded. This guarantees that only the latest incarnation of a client can affect the stream.

```python
from pulsar import Client, Schema

client = Client('pulsar://broker:6650')
producer = client.create_producer(
    topic='orders',
    schema=Schema.STRING,
    producer_name='order-producer',
    # The SDK automatically fetches a fencing token
)
```

The token is attached to each message metadata. The broker compares it against the stored token for that producer; if the incoming token is lower, the message is rejected with a `FencingTokenExpired` error.

## Failure Recovery Patterns

### Checkpointing

In a streaming pipeline, you must persist the consumer’s progress so that after a restart, processing resumes from the last committed offset. With transactions, you can combine **acknowledgment** with **checkpointing** in a single transactional step:

1. Consume a batch of messages.
2. Apply business logic.
3. Write the result to a sink (e.g., a database).
4. Open a transaction.
5. Produce an acknowledgment message to a control topic.
6. Commit the transaction.

If the transaction commits, both the sink update and the offset advancement are atomic. If it fails, the consumer retries from the previous checkpoint.

### Idempotent Consumers

While fencing reduces duplicates, combining it with idempotent consumers provides defense in depth. Design your consumer to handle duplicate messages gracefully. For example, use a unique message ID to deduplicate at the storage layer:

```sql
INSERT INTO events (id, payload)
VALUES (?, ?)
ON CONFLICT (id) DO NOTHING;
```

This way, even if a message slips through fencing, the database ignores the duplicate.

## Architecture: Building a Production Exactly‑Once Pipeline

A production‑grade exactly‑once system on Pulsar typically includes the following components:

- **Pulsar Cluster**: Multiple brokers for fault tolerance; a dedicated **metadata store** (ZooKeeper or etcd) for transaction coordinator state.
- **Transaction Coordinator Service**: A stateless service that can be scaled horizontally; it persists transaction logs in a Pulsar topic.
- **Fencing Token Store**: A lightweight key‑value store (e.g., Redis) that records the latest token per producer/consumer.
- **Sink Connectors**: Connectors that write to databases, data lakes, or search indexes, participating in transactions when possible.
- **Monitoring**: Metrics for transaction commit latency, fencing token mismatches, and consumer lag.

### Deployment Considerations

- **Isolate the transaction coordinator** on dedicated nodes to avoid resource contention.
- **Use topic namespaces** to separate transactional topics from regular ones, simplifying access control.
- **Enable persistent retention** for transaction log topics so that the coordinator can recover after a crash.
- **Configure retry policies** with exponential backoff to handle transient broker failures without overwhelming the system.

## Key Takeaways

- Pulsar’s **transaction API** provides atomic visibility for produce/consume operations.
- **Fencing tokens** prevent stale clients from injecting duplicate messages.
- Combining transactions with **checkpointing** yields exactly‑once state updates.
- Design **idempotent consumers** as a safety net for edge cases.
- Production deployments should isolate the transaction coordinator and monitor fencing token health.

## Further Reading

- [Apache Pulsar Transactions Documentation](https://pulsar.apache.org/docs/concepts/transactions/)
- [Pulsar Reliable Messaging Guide](https://pulsar.apache.org/docs/concepts/reliable-messaging/)
- [Pulsar Architecture Overview](https://pulsar.apache.org/docs/concepts/architecture/)
- [Fencing in Distributed Systems](https://en.wikipedia.org/wiki/Fencing_(distributed_systems))