

---
title: "Implementing Apache Pulsar Tiered Storage: Backlog Offload and Read Path Tradeoffs"
date: "2026-09-21T06:00:56.898"
draft: false
tags: ["Apache Pulsar", "Tiered Storage", "Backlog Offload", "Read Path", "Performance"]
description: "Deep dive into Apache Pulsar tiered storage: backlog offload, read path tradeoffs, and production deployment patterns for scalable messaging."
summary: "Learn how Apache Pulsar's tiered storage can offload backlog to cost‑effective storage while balancing read latency and throughput."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-implementing-apache-pulsar-tiered-storage-backlog-offload-and-read-path-tradeoffs.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — Apache Pulsar's tiered storage moves old messages to cheaper object storage, slashing storage costs, but reading those messages adds latency and requires careful tuning of the read path. This article explains the architecture, offload mechanisms, and the tradeoffs you must balance in production.

Apache Pulsar is a distributed messaging and streaming platform that natively supports tiered storage, allowing brokers to offload backlog data to low‑cost object stores such as Amazon S3, Google Cloud Storage, or Azure Blob Storage. By separating the hot data path from the cold data path, Pulsar can retain unlimited message history without expanding the expensive local disk, but this convenience introduces new challenges for read latency, consistency, and operational complexity. In this post, we will walk through the internal architecture of tiered storage, examine how backlog offload works under the hood, and analyze the tradeoffs that affect the read path in a production environment.

## Architecture of Tiered Storage

### Core Components

- **Broker** – Handles producer/consumer traffic and coordinates the tiered storage workflow.
- **BookKeeper** – Provides the underlying distributed log storage; each topic segment is a BookKeeper ledger.
- **Managed Ledger** – The higher‑level abstraction that manages topic state, including offload decisions.
- **Offload Manager** – A component within the broker that triggers offload, copies data to the object store, and updates metadata.
- **Object Store** – The target storage system (S3, GCS, Azure Blob) where offloaded segments reside.

### Offload Workflow

When a topic’s backlog exceeds a configured threshold, the Offload Manager selects a segment (or a set of segments) and initiates an offload operation:

1. **Segment Selection** – Based on size or time‑based policy.
2. **Copy to Object Store** – The broker streams the segment data to the object store, producing a unique object key.
3. **Metadata Update** – The Managed Ledger records the object key and marks the segment as “offloaded”.
4. **Local Retention** – Optionally, the broker may retain a small “index” or “metadata” block locally to speed up subsequent reads.

A typical broker configuration snippet looks like this:

```yaml
# broker.conf
managedLedgerOffloadThreshold: 1000000000   # 1 GB
offloadMaxReadLatency: 500ms
tieredStorageEnabled: true
```

## Backlog Offload Strategies

### Time‑based vs Size‑based Offload

- **Time‑based** – Offload segments older than a configurable age (e.g., 24 hours). This is useful when data decay is predictable.
- **Size‑based** – Offload when the total backlog size crosses a threshold (e.g., 1 GB). This provides tighter control over local disk usage.

In practice, many operators combine both: a segment is eligible for offload if it is older than *X* **or** the backlog exceeds *Y* bytes.

### Impact on Storage Costs

Assuming a local SSD cost of $0.10 / GB‑month and an S3 Standard cost of $0.023 / GB‑month, offloading a 10 TB backlog yields an estimated saving of roughly $7,700 per month. The exact figure depends on retention, request patterns, and cross‑region replication.

## Read Path Tradeoffs

### Latency Overheads

When a consumer requests a message that resides in an offloaded segment, the broker must fetch the segment from the object store. This introduces:

- **Network Round‑Trip** – Typically 5–30 ms intra‑region.
- **Object Store Request Latency** – S3 GetObject adds ~10–50 ms.
- **Deserialization** – Parsing the segment header and locating the specific message.

The cumulative effect can push read latencies from sub‑millisecond (local) to tens of milliseconds, which is acceptable for batch consumers but may violate SLAs for low‑latency applications.

### Throughput Considerations

- **Concurrency** – The broker can issue multiple concurrent object store requests, but each consumes a thread and file descriptor.
- **Caching** – Frequently accessed offloaded segments can be cached in memory or on local SSD, reducing effective latency.
- **Prefetching** – Aggressive prefetch of upcoming segments can smooth throughput for sequential workloads.

### Caching and Prefetching

A common pattern is to maintain an LRU cache of recently read offloaded segments. The cache size is often set to 10–20 % of the total offloaded data, providing a hit ratio of ~80 % for read‑heavy topics. Prefetching can be tuned via `offloadPrefetchThreshold` to start downloading the next segment when the current one is 70 % consumed.

## Patterns in Production

### Deployment Topology

- **Single‑Region** – All brokers and the object store reside in one region; simplest but limited fault tolerance.
- **Multi‑Region** – Brokers in each region write to a regional bucket; cross‑region reads may incur higher latency.
- **Hybrid** – Hot data stays on local SSD, while cold data is tiered to a shared object store across regions.

### Monitoring and Alerting

Key metrics to track:

- `pulsar_offload_total_bytes` – total bytes offloaded.
- `pulsar_offload_read_latency_seconds` – average latency for reading offloaded segments.
- `pulsar_offload_cache_hit_ratio` – effectiveness of the segment cache.

Alert when read latency exceeds a threshold (e.g., 200 ms) or when cache hit ratio drops below 60 %.

## Key Takeaways

- Tiered storage dramatically reduces long‑term storage cost by moving cold data to object stores.
- Offload decisions can be time‑based, size‑based, or a combination of both.
- Reading offloaded segments adds latency; caching and prefetching are essential for maintaining throughput.
- Production deployments should monitor offload volume, read latency, and cache effectiveness.
- Properly tuned tiered storage can coexist with low‑latency consumers by keeping hot data locally.

## Further Reading

- [Apache Pulsar Tiered Storage Documentation](https://pulsar.apache.org/docs/concepts/tiered-storage/)
- [Pulsar Architecture Overview](https://pulsar.apache.org/docs/concepts/architecture/)
- [Running Pulsar in Production](https://pulsar.apache.org/docs/cookbooks/standalone/)
- [Apache Pulsar GitHub Repository](https://github.com/apache/pulsar)