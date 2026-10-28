---
title: "Inside Apache Pulsar: Segment-Centric Architecture and Tiered Storage"
date: "2026-10-28T06:01:03.381"
draft: false
tags: ["Apache Pulsar", "Messaging", "Tiered Storage", "Architecture", "Data Infrastructure"]
description: "How Apache Pulsar's segment-centric design and tiered storage solve long-term retention and scalability challenges in production messaging systems."
summary: "Pulsar's segment-based storage model decouples compute from storage, enabling tiered storage to offload cold data to cheap object stores without breaking consumer replay."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-28-inside-apache-pulsar-segment-centric-architecture-and-tiered-storage.svg"
  alt: "Apache Pulsar architecture diagram showing segments flowing from brokers to tiered storage"
  caption: ""
  relative: false
---

> **TL;DR** — Apache Pulsar's segment-centric architecture treats each topic as a stream of immutable segments, which decouples compute from storage and makes tiered storage a natural extension rather than a bolt-on feature. By offloading cold segments to cheap object storage like S3 or GCS, teams can retain years of message history without the exponential I/O penalty that comes from keeping everything on local disks.

Traditional message brokers like Kafka have long relied on a log-structured storage model where each partition is a contiguous append-only file on local disk. That model works brilliantly until you need to retain data for compliance, feed downstream analytics pipelines, or replay weeks of history for debugging. Apache Pulsar approaches the problem from a different angle: it breaks the topic into segments, and segments become the unit of both replication and tiered storage.

## Why Traditional Messaging Storage Falls Short

In Kafka, a partition is a single directory of segment files, but those segments live on the broker's local filesystem. When you need to retain data for a long time, you either scale out horizontally with more brokers and more disks, or you accept that old segments will be deleted. Tiered storage in Kafka (via KIP-405) tries to solve this by offloading old segments to object storage, but the architecture still couples partition assignment to broker-local segments, which complicates rebalancing and replay.

Pulsar's design starts from a different premise: the broker should be stateless, and storage should be a separate, shared service. This is possible only because the storage layer is organized around segments, not partitions.

## The Segment-Centric Model: Topics as Segment Streams

In Pulsar, every topic is a logical stream of messages, but physically it is split into segments. A segment is an immutable, append-only unit of data with a unique identifier. Segments are created as the topic grows, typically when the current segment reaches a configurable size threshold (default 5 MB) or age threshold.

The key insight is that a segment is not tied to a specific broker. When a segment is created, it is assigned to a storage node in the BookKeeper cluster (or to a tiered storage backend). The broker that is currently serving the topic writes to that segment, but the segment itself lives in a distributed ledger that survives broker failures and rebalancing.

This means:
- **Broker failure**: The topic's leader broker fails; a standby broker takes over and continues writing to the same open segment.
- **Rebalancing**: A segment can be moved between BookKeeper ensembles without copying data, because the segment's metadata points to its current location.
- **Consumer replay**: Any consumer can read from any segment, at any offset, because segments are immutable and addressable by ID.

## Segments as the Unit of Storage and Replication

Each segment in BookKeeper is replicated across multiple bookies (storage nodes) using a quorum write protocol. The default replication factor is 3, and writes are acknowledged only after a quorum of bookies confirms the append. This gives Pulsar strong durability guarantees without requiring the broker to maintain any local state.

Compare this to Kafka, where replication is tied to the broker that owns the partition leader. If the leader fails, a follower must be elected, and during that window the partition is unavailable. Pulsar's segment-based replication means the storage layer is independent of the broker layer, so broker failures are invisible to the storage durability contract.

## Tiered Storage: Offloading Cold Segments

Tiered storage in Pulsar is not an afterthought; it is a direct consequence of the segment model. When a segment is no longer being actively written, it can be offloaded from BookKeeper to a cheaper, long-term storage backend. The broker simply updates the segment's metadata to point to the new location, and all subsequent reads are redirected transparently.

Supported backends include:
- **Amazon S3** — The most common choice for teams already invested in AWS.
- **Google Cloud Storage** — Native integration with GCS, including IAM-based access control.
- **Azure Blob Storage** — For shops standardized on Azure.
- **Self-hosted S3-compatible stores** — MinIO, Ceph, or any S3-compatible object store.

The offload process is incremental and non-blocking. A segment is only offloaded after it is sealed (no more writes), and the broker continues to serve reads from BookKeeper until the offload is complete. Once the segment is in object storage, reads are fetched on demand, with optional caching to avoid latency spikes for repeated access.

### How Tiered Storage Works Under the Hood

The flow is:

1. **Sealing**: The broker decides a segment is closed, either because it hit the size limit or because the topic is being unloaded.
2. **Offload trigger**: The broker initiates an offload task. This task reads the segment from BookKeeper and streams it to the object store.
3. **Metadata update**: Once the offload is verified, the broker updates the segment's metadata in the ZooKeeper (or Metadata Store) to include the object store URI and any necessary credentials.
4. **Read path**: When a consumer requests messages from an offloaded segment, the broker fetches the data from object storage, optionally caching it in a local read cache.

The entire process is managed by the broker's `ManagedLedger` framework, which tracks the state of every segment in every topic. There is no manual configuration per topic; tiered storage is enabled globally, and the offload policy (size, age, or manual) is applied uniformly.

## Architecture Patterns: Compute-Storage Separation

The segment-centric model enables a clean separation between compute (brokers) and storage (BookKeeper + object storage). This has profound implications for scaling:

- **Independent scaling**: You can add or remove brokers without touching the storage layer. A burst of traffic means more brokers; a long retention policy means more object storage.
- **Cost efficiency**: Hot data stays on fast SSDs in BookKeeper. Cold data moves to S3 at roughly 1/10th the cost. You don't pay for IOPS on data that is rarely read.
- **Disaster recovery**: Because segments are immutable and replicated, you can reconstruct a topic from object storage alone. BookKeeper is a cache; the long-term source of truth is the object store.

This pattern is similar to what Snowflake and BigQuery do with their storage-compute separation, but applied to the messaging layer. It is also why Pulsar can support functions like "geo-replication" without copying message data — segments are already addressable across regions.

## Real-World Production Scenarios

**Scenario 1: Compliance and Audit Trails.** A financial services firm needs to retain all trade messages for seven years. With Kafka, this would require seven years of broker disk capacity. With Pulsar, hot data (last 30 days) lives in BookKeeper; older segments are offloaded to S3 Glacier. The audit team can replay any message by topic and timestamp without provisioning extra brokers.

**Scenario 2: IoT Event Backfill.** A manufacturing company ingests sensor data from 50,000 devices. During a network outage, messages are buffered in Pulsar. When the outage resolves, the system replays the buffered segments to a downstream analytics pipeline. Because the segments are already in object storage, the replay does not stress the live brokers.

**Scenario 3: Debugging Production Incidents.** A SaaS company keeps a rolling 90-day retention window. When a customer reports a bug that occurred three weeks ago, the engineering team can replay the topic to reproduce the issue. The first read of old segments is slower (fetching from S3), but subsequent reads are cached, so the debugging session feels local.

## Key Takeaways

- **Segments are the fundamental unit** of Pulsar storage. They are immutable, replicated, and decoupled from broker identity.
- **Tiered storage is native**, not an add-on. Offloading cold segments to S3, GCS, or Azure Blob Storage is a metadata update, not a data migration.
- **Compute and storage scale independently.** You can add brokers to handle throughput without adding disks, and you can retain years of history without paying for hot storage.
- **Replay is always available.** Because segments are immutable and addressable, any consumer can read from any point in history, whether the data is in BookKeeper or object storage.
- **Cost follows access patterns.** Hot data on SSDs, cold data on object storage, and the broker layer stays thin and stateless.

## Further Reading

- [Apache Pulsar Tiered Storage Documentation](https://pulsar.apache.org/docs/concepts tiered-storage/) — Official guide to configuring and managing tiered storage in Pulsar.
- [BookKeeper: Distributed Write-Ahead Log](https://bookkeeper.apache.org/) — Deep dive into the ledger-based storage engine that powers Pulsar segments.
- [KIP-405: Support Tiered Storage in Apache Kafka](https://cwiki.apache.org/confluence/display/KAFKA/KIP-405%3A+Support+Tiered+Storage+in+Apache+Kafka) — Contrast this with Kafka's approach to tiered storage and understand the architectural trade-offs.
- [AWS S3 Performance Guidelines](https://docs.aws.amazon.com/whitepapers/latest/object-storage-performance-guidelines.html) — Best practices for optimizing S3 access patterns, relevant when using it as a Pulsar tiered storage backend.
- [Snowflake Architecture: Storage-Compute Separation](https://www.snowflake.com/blog/snowflake-architecture-storage-compute-separation/) — A look at how separation of concerns drives scalability in the data warehouse world, mirroring Pulsar's design philosophy.