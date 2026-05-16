---
title: "Why Exactly-Once Delivery Requires Consumer Idempotency"
date: "2026-05-16T11:00:53.082"
draft: false
tags: ["messaging","distributed-systems","idempotency","exactly-once","event-driven"]
description: "Exactly-once delivery sounds ideal, but achieving it demands idempotent consumers; this post explains the why, the pitfalls, and practical patterns."
summary: "Exactly-once delivery cannot be guaranteed without making consumers idempotent; this article breaks down the technical reasoning and shows how to implement idempotency in real systems."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-why-exactly-once-delivery-requires-consumer-idempotency.svg"
  alt: "Illustration of a message broker with duplicate messages being filtered by an idempotent consumer."
  caption: ""
  relative: false
---

> **TL;DR** — Exactly-once delivery is impossible to guarantee on the network layer alone; the only reliable way to achieve it is to make the consumer itself idempotent, using deduplication, deterministic processing, and durable state.

In distributed systems, the promise of “exactly‑once” semantics tempts architects to design pipelines that never lose or repeat data. In practice, network partitions, broker retries, and at‑least‑once delivery models make duplicates inevitable. The only way to turn that inevitability into a functional guarantee is to require the consumer to be idempotent. This article unpacks why, explores common sources of duplicate delivery, and provides concrete patterns for building idempotent consumers that work at scale.

## The Myth of Exactly-Once Guarantees

Many messaging platforms advertise “exactly‑once” as a feature, but the term is often misunderstood.

1. **Broker‑level semantics** – Systems like Apache Kafka provide *transactional* writes that prevent duplicate *productions* within a partition, but they still expose the consumer to at‑least‑once delivery because acknowledgments are sent *after* the broker has persisted the record, not after the consumer has processed it.  
2. **Network unreliability** – TCP guarantees ordered delivery, yet packet loss or connection resets cause the producer or broker to resend messages. The consumer sees the same logical event twice.  
3. **Process crashes** – If a consumer crashes after acknowledging a message but before persisting its side effects, the broker may redeliver the same message after the consumer restarts.

The consensus in the industry, articulated in the [Kafka Exactly‑Once Semantics guide](https://kafka.apache.org/documentation/#semantics), is that *exactly‑once* can only be promised *end‑to‑end* when **both** the broker and the consumer cooperate. The consumer’s role is to ensure that processing the same message multiple times does not change the final state.

## Sources of Duplicate Delivery

Understanding where duplicates originate helps you choose the right idempotency strategy.

### 1. Broker Retries

Most brokers implement at‑least‑once delivery to avoid message loss. If an acknowledgment is not received within a timeout, the broker will resend the record. For example, RabbitMQ’s *publisher confirms* can be lost, triggering a redelivery.

### 2. Consumer Rebalancing

In a consumer group, partitions are reassigned when instances join or leave. Uncommitted offsets are often reset to the last committed point, causing the new instance to read the same batch again.

### 3. Network Partitions

A temporary network split can cause the producer to think a send failed, leading it to retry while the broker already stored the message. Both copies survive, and the consumer eventually sees the duplicate.

### 4. Application Restarts

If a consumer crashes after processing but before persisting its side effects (e.g., writing to a database), the next start will reprocess the same message, potentially duplicating the effect.

## How Idempotency Closes the Gap

Idempotency is the property that applying the same operation multiple times yields the same result as applying it once. When a consumer is idempotent, duplicates become harmless because the state transition is deterministic and repeatable.

### Deterministic Side Effects

An idempotent consumer must ensure that each logical operation maps to a *single* state change, regardless of how many times the surrounding code runs.

* **Database upserts** – Use `INSERT … ON CONFLICT DO UPDATE` (PostgreSQL) or `MERGE` (SQL Server) so that repeated writes with the same primary key do not create duplicate rows.  
* **External APIs** – Many services provide idempotency keys (e.g., Stripe’s `Idempotency-Key` header). Including a unique key per event guarantees that repeated calls are ignored.

### Duplicate Detection

The most common technique is to keep a *deduplication store* keyed by a unique message identifier (often the broker‑assigned offset or a UUID in the payload). The workflow is:

1. Extract the unique ID.  
2. Check the store atomically: if the ID exists, skip processing.  
3. If not, process the payload, then record the ID as completed.

Below is a Python sketch using Redis for atomic check‑and‑set:

```python
import redis
import json

r = redis.StrictRedis(host='localhost', port=6379, db=0)

def process_message(msg):
    """
    Idempotent consumer that uses Redis SETNX to guard against duplicates.
    """
    msg_id = msg['event_id']          # Assume each event carries a UUID.
    # Use SETNX (set if not exists) with an expiration to avoid unbounded growth.
    if r.setnx(msg_id, 'processing'):
        try:
            # ----- Begin deterministic business logic -----
            # Example: update user balance
            user_id = msg['user_id']
            delta = msg['amount']
            update_user_balance(user_id, delta)
            # ----- End business logic -----
            # Mark as processed permanently
            r.set(msg_id, 'done')
        except Exception as e:
            # Cleanup on failure so the message can be retried
            r.delete(msg_id)
            raise e
    else:
        # Duplicate detected; safely ignore.
        print(f"Duplicate {msg_id} ignored")
```

The `SETNX` command is atomic in Redis, ensuring that two concurrent consumers cannot both think they are the first to process the same ID.

### Stateless vs. Stateful Idempotency

* **Stateless** – When the operation itself is naturally idempotent (e.g., setting a flag to `true`), no external store is needed.  
* **Stateful** – Most real‑world side effects (financial transfers, inventory updates) require external state to remember which events have been applied.

Both approaches can be combined: make the core operation idempotent, then add a lightweight deduplication layer for safety.

## Designing Idempotent Consumers

### 1. Choose a Stable Identifier

The identifier must be *globally unique* and *immutable* for the logical event. Common sources:

| Source               | Example                                   |
|----------------------|-------------------------------------------|
| Broker offset + partition | `topic-3-partition-7-offset-12345` |
| Message UUID in payload   | `"event_id": "c3f5e8a2‑..."`        |
| Composite key (user‑id + timestamp) | `"user:42:2023-09-01T12:00:00Z"` |

### 2. Implement Atomic Deduplication

Use a datastore that supports atomic “check‑and‑set” semantics:

* **Redis** – `SETNX` or Lua scripts for multi‑key transactions.  
* **PostgreSQL** – `INSERT … ON CONFLICT DO NOTHING` inside a transaction.  
* **DynamoDB** – Conditional writes with `ConditionExpression` on a primary key.

Here’s a Bash example using the AWS CLI to conditionally write a record to DynamoDB:

```bash
#!/usr/bin/env bash
EVENT_ID=$1
TABLE_NAME="ProcessedEvents"

aws dynamodb put-item \
    --table-name "$TABLE_NAME" \
    --item "{\"event_id\": {\"S\": \"$EVENT_ID\"}}" \
    --condition-expression "attribute_not_exists(event_id)" \
    && echo "Processing $EVENT_ID" \
    || echo "Duplicate $EVENT_ID detected"
```

If the condition fails, the command exits with a non‑zero status, indicating a duplicate.

### 3. Make Business Logic Idempotent

Even with deduplication, you should design the core operation to be repeatable:

* **Upserts** instead of blind inserts.  
* **Compensating transactions** – If an operation fails after a partial side effect, roll back before exiting.  
* **Monotonic counters** – Use `MAX(current, new)` rather than `+=` when aggregating.

### 4. Handle Out‑of‑Order Events

Exactly‑once does not guarantee order. If your domain requires ordering (e.g., ledger entries), you must:

1. Store events with their sequence numbers.  
2. Process them in order, buffering later events until missing predecessors arrive.  
3. Use *idempotent* replay to fill gaps.

#### Example: Ordering Buffer in Python

```python
from collections import defaultdict
import heapq

pending = defaultdict(list)   # topic -> min‑heap of (seq, msg)

def maybe_process(topic, seq, msg):
    heapq.heappush(pending[topic], (seq, msg))
    # Attempt to process from the smallest seq upward
    while pending[topic] and pending[topic][0][0] == expected_seq[topic]:
        _, next_msg = heapq.heappop(pending[topic])
        process_message(next_msg)      # Idempotent processing
        expected_seq[topic] += 1
```

The buffer ensures that even if duplicates arrive out of order, the consumer only applies each sequence once.

### 5. Expire Deduplication Records

To avoid unbounded storage, set a TTL that exceeds the maximum expected re‑delivery window (e.g., 24 hours). Most stores support expirations:

* Redis `EXPIRE` command.  
* DynamoDB TTL attribute.  
* PostgreSQL `DELETE FROM processed WHERE processed_at < now() - interval '30 days'`.

## Key Takeaways

- Exactly‑once delivery is a *system‑wide* guarantee that cannot be achieved by the broker alone; the consumer must be idempotent.  
- Duplicates arise from broker retries, consumer rebalancing, network partitions, and process crashes.  
- Idempotency can be achieved through deterministic business logic, atomic deduplication stores, and careful choice of unique identifiers.  
- Stateless idempotent operations are ideal, but most real‑world use cases require a stateful deduplication layer (Redis, DynamoDB, PostgreSQL, etc.).  
- Remember to set TTLs or cleanup jobs to keep deduplication data from growing indefinitely, and design for out‑of‑order handling when ordering matters.

## Further Reading

- [Apache Kafka Exactly‑Once Semantics](https://kafka.apache.org/documentation/#semantics) – Official guide on Kafka’s transactional model and its limits.  
- [RabbitMQ Consumer Acknowledgements and Redelivery](https://www.rabbitmq.com/confirms.html) – Explanation of at‑least‑once delivery and how to handle redelivered messages.  
- [AWS DynamoDB Conditional Writes](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/ConditionalWrites.html) – Using condition expressions to implement idempotent writes.  
- [Google Cloud Pub/Sub Exactly‑Once Delivery](https://cloud.google.com/pubsub/docs/exactly-once-delivery) – How GCP approaches exactly‑once and the role of subscriber-side deduplication.  
- [Stripe Idempotency Keys](https://stripe.com/docs/api/idempotent_requests) – Real‑world example of API‑level idempotency for financial transactions.