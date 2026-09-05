---
title: "Inside NATS JetStream: Building Exactly-Once Delivery with Replicated Logs and Consumer Acks"
date: "2026-09-05T21:00:29.491"
draft: false
tags: ["nats", "jetstream", "exactly-once", "message-queue", "distributed-systems"]
description: "How NATS JetStream achieves exactly-once delivery using replicated Raft logs, consumer acks, and deduplication at the stream layer."
summary: "A deep dive into the architecture behind JetStream's exactly-once semantics — covering Raft-replicated streams, per-consumer ack tracking, redelivery semantics, and the dedup window that ties it all together."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-inside-nats-jetstream-building-exactly-once-delivery-with-replicated-logs-and-consumer-acks.svg"
  alt: "Diagram of NATS JetStream stream replication across three nodes"
  caption: ""
  relative: false
---

> **TL;DR** — JetStream delivers exactly-once by combining Raft-replicated streams (so messages survive node failures), per-consumer ack tracking with heartbeats and redelivery (so in-flight messages are never lost), and a server-side dedup window (so retries from clients never create duplicates downstream). The result is a system where idempotency is enforced at the storage layer rather than being left to application code.

## Why Exactly-Once Is Harder Than It Sounds

Distributed message systems have a long history of promising exactly-once delivery. The honest answer, as articulated in the [Kafka documentation on delivery semantics](https://kafka.apache.org/documentation/#semantics), is that "exactly-once is the holy grail." Any network can drop a packet, any process can crash mid-message, and any client can retry an ack that already arrived at the server. Each of these failures creates the conditions for either lost messages or duplicates.

JetStream, the persistence layer built into [NATS](https://docs.nats.io/nats-concepts/jetstream), attacks the problem in two layers. The first is the **stream**, a Raft-replicated log that survives node loss without losing or reordering messages. The second is the **consumer**, which tracks which messages have been acknowledged and which need redelivery. Together they enforce idempotency at the server boundary, so applications that use JetStream's dedup features can treat the queue as exactly-once even if their own code is not perfectly idempotent.

The interesting design questions all live in the interaction between those two layers. How does ack state survive a consumer restart? How does redelivery interact with replication? And what does "exactly-once" actually mean when the server can crash between storing a message and recording an ack?

## The Stream Layer: Raft-Replicated Logs

Every JetStream stream is backed by a replicated log stored across $N$ nodes (typically 3 or 5). The replication protocol is a variant of [Raft](https://raft.github.io/), the same consensus algorithm used by etcd and Consul. When a producer publishes a message, it lands on the leader, the leader appends it to its log, and the entry is replicated to a quorum before being acknowledged back to the producer.

The relevant guarantees for exactly-once are:

- **No message loss under quorum failure.** A message is acknowledged to the producer only after a majority of replicas have written it to disk. If two of three nodes die, the surviving node still has the message and can re-form a quorum.
- **Total ordering within a stream.** Each message has a monotonic sequence number assigned by the leader. Consumers see these numbers in the same order regardless of which replica they read from.
- **Bounded retention with disk persistence.** Messages live until they are either explicitly deleted, expire via `MaxAge`, or are trimmed by `MaxMsgs`/`MaxBytes`/`MaxSeq`. This is what makes ack tracking durable.

JetStream exposes three replication modes, set at stream creation:

| Mode | Replicas | Survives | Use case |
| --- | --- | --- | --- |
| `file` | 1 | Disk-only failure | Dev, single-node |
| `raft` | N (typically 3) | Node loss up to (N-1)/2 | Production |
| Interest-based / mirror | Cross-cluster | Region loss | DR |

For exactly-once work, `raft` is the only mode that actually delivers the guarantee. A single-node stream is fine for testing but cannot survive the leader crashing mid-write.

## The Consumer Layer: Acks, Heartbeats, and Redelivery

If the stream is the durable log, the consumer is the cursor. A JetStream consumer is a named, persistent position in the stream with its own ack state. The state machine is straightforward on paper:

1. Consumer pulls a batch of messages from the stream.
2. Each message carries a sequence number and a stream ID.
3. Consumer processes them and sends an ack back to the server, either per-message or per-batch.
4. If the consumer dies, the server redelivers any unacked messages to a new consumer instance.

The complication is that "dies" is ambiguous. A consumer might have processed a message, sent an ack, and crashed before the ack reached the server. So JetStream treats any message that has been delivered but not explicitly acknowledged as **pending**, and pending messages are eligible for redelivery.

This is where the *at-least-once* part of "exactly-once delivery" comes from. The system will, under failure conditions, redeliver a message that may have already been processed. The exactly-once guarantee is then enforced by one of two mechanisms: either the application is itself idempotent, or the message is published with a deduplication header that JetStream uses to filter out duplicates at the stream layer.

## Ack Timing: The Window for Duplicates

The single most important knob on a consumer is `AckWait`. This is the deadline by which an ack must arrive after delivery. If the deadline expires, the server assumes the consumer crashed and reschedules the message for redelivery. JetStream also tracks `AckFloor` — the highest contiguous sequence number for which all prior messages have been acked — and uses this to advance the cursor efficiently.

A typical consumer configuration looks like this:

```text
Durable Name:        ORDER_PROCESSOR
Ack Policy:          explicit
Ack Wait:            30s
Max Deliver:         5
Deliver Policy:      all
Filter Subject:      orders.created
```

Two of these fields matter most for exactly-once:

- **`AckWait`** should be longer than the worst-case processing time, but short enough that a dead consumer is detected quickly. For a worker that processes an order in 100ms, 30s is generous; for one that calls a third-party API, you may want 60s or more.
- **`MaxDeliver`** caps the number of times a single message will be redelivered before being moved to a dead-letter stream. Without this, a poison message that always crashes the handler will be redelivered forever.

The redelivery flow under failure looks like this:

```text
Producer ──► Stream (Raft log) ──► Consumer A
                                       │
                                       │ crash, no ack
                                       ▼
                                   Server timeout
                                       │
                                       ▼
                                   Consumer B receives
                                   same sequence number
```

The new consumer sees the same sequence number the old one saw. This is the duplication window that exactly-once must close.

## Server-Side Deduplication

JetStream's cleanest answer to the duplicate problem is the **message deduplication window**, controlled by the `duplicate_window` field on a stream. When a producer publishes a message with an `Nats-Msg-Id` header, the server records that ID against the message. If the same ID appears again within the window (default 2 minutes, configurable up to the stream's `MaxAge`), the duplicate is silently discarded before it ever reaches the stream.

This works because the dedup check happens on the **publish** path, before the message is written to the Raft log. The window is bounded so the dedup table itself doesn't grow without limit.

```go
nc, _ := nats.Connect(nats.DefaultURL)
js, _ := nc.JetStream()

// dedup by MsgId; replays within 2 minutes are dropped
_, err := js.Publish("orders.created", payload, nats.MsgId(orderID))
```

The contract is simple: the application picks a stable, unique identifier for each logical event. An order ID, a transaction hash, a UUID generated upstream — anything that will be the same on retry. JetStream then guarantees that this message ID appears in the stream at most once.

For the guarantee to hold end-to-end, the producer also needs idempotent publishing. JetStream supports this through a publish sequence number: the client maintains a monotonically increasing counter, sends it with each publish, and the server rejects any publish whose sequence number is lower than the last one it accepted. Combined with `MsgId` dedup, you get the strongest version of the guarantee JetStream offers — described in detail in the [JetStream messages documentation](https://docs.nats.io/nats-concepts/jetstream/streams).

### Patterns in Production

The pattern that consistently works in production is layered:

1. **At the producer**: a stable `MsgId` (often the primary key of the business entity) plus, if you need it, a publish sequence number.
2. **At the stream**: `duplicate_window` set to at least 2× the worst-case retry latency. If your producer can retry for 5 minutes under failure, set the window to 10 minutes.
3. **At the consumer**: explicit ack policy with `AckWait` longer than processing time, and a `MaxDeliver` cap that routes poison messages to a dead-letter stream for human inspection.

A concrete example: an order processing pipeline where each order flows through a JetStream stream into a worker that calls a payment gateway. The order ID is the `MsgId`. If the worker times out and the message is redelivered, the new worker instance calls the payment gateway again — but the gateway itself is idempotent on order ID, so the second call is a no-op. The JetStream layer prevents two *messages* from existing; the payment gateway prevents two *charges*.

## Exactly-Once vs. Effectively-Once

It is worth being precise about what JetStream does and does not guarantee. The system guarantees:

- A published message with a `MsgId` will appear in the stream exactly once (modulo the dedup window).
- A consumed message will be delivered to *some* live consumer instance until it is acked.
- Acks are themselves replicated, so the ack state survives the same failures as the stream.

It does not, on its own, guarantee that a side effect (a database write, an email send, a charge) happens exactly once. The application remains responsible for making its handlers idempotent. JetStream makes the queue exactly-once; it cannot make your external systems exactly-once without help.

This is the same distinction drawn in the [Confluent article on exactly-once semantics](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/): the message system deduplicates, the application must too.

## Key Takeaways

- JetStream's exactly-once story rests on three pillars: Raft-replicated streams for durability, per-consumer ack state for progress tracking, and server-side `MsgId` deduplication for the final closure of duplicates.
- The `AckWait` and `MaxDeliver` settings are the operational levers for tuning how aggressively the system redelivers under failure; both must be calibrated to the worker's actual behavior.
- Deduplication works because the check happens on the publish path, before the message enters the Raft log — meaning duplicates never occupy storage in the first place.
- The guarantee is "exactly-once into the stream" and "at-least-once out, deduplicated downstream." Application handlers must still be idempotent for the full pipeline to be exactly-once.
- A `duplicate_window` shorter than your producer's worst-case retry interval silently re-introduces duplicates. Set the window to at least 2× the retry budget.

## Further Reading

- [JetStream Concepts (NATS Documentation)](https://docs.nats.io/nats-concepts/jetstream)
- [Stream Configuration and Replicas (NATS Documentation)](https://docs.nats.io/nats-concepts/jetstream/streams)
- [Consumers and Acknowledgement (NATS Documentation)](https://docs.nats.io/nats-concepts/jetstream/consumers)
- [Raft Consensus Algorithm](https://raft.github.io/)
- [Exactly-Once Semantics in Kafka (Confluent)](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)