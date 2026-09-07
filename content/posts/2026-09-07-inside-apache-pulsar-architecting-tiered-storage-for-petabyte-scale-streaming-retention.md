---
title: "Inside Apache Pulsar: Architecting Tiered Storage for Petabyte-Scale Streaming Retention"
date: "2026-09-07T17:10:55.219"
draft: false
tags: ["apache-pulsar", "tiered-storage", "streaming", "architecture", "distributed-systems"]
description: "A deep dive into Apache Pulsar's tiered storage architecture: how BookKeeper, offloaders, and segment stores unlock petabyte-scale retention."
summary: "How Apache Pulsar decouples hot and cold data using BookKeeper, segment stores, and pluggable offloaders to retain petabytes of streaming data affordably."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-inside-apache-pulsar-architecting-tiered-storage-for-petabyte-scale-streaming-retention.svg"
  alt: "Abstract layered visualization of Apache Pulsar's hot and cold storage tiers"
  caption: ""
  relative: false
---

> **TL;DR** — Pulsar splits streaming data into two tiers: hot data lives in BookKeeper for low-latency reads and writes, while cold data gets offloaded to long-term stores like S3 or HDFS. The boundary between tiers is just another segment, which means retention, lookup, and replay work the same whether data is five minutes or five years old.

## Why Tiered Storage Matters at Scale

Most streaming systems were designed when "long term" meant seven days. That worked when log retention was an operational afterthought. It does not work when data products depend on months of replayable history: fraud models retraining on two quarters of clickstream, IoT platforms replaying a year of sensor events for a firmware regression, compliance teams asking for "everything we ever shipped" on a Tuesday afternoon.

The naive fix is bigger disks. That works until it doesn't. A single Pulsar topic on a busy cluster can ingest gigabytes per second. Even at modest scale, keeping weeks of data on local journal drives becomes a cost problem long before it becomes a stability problem. Pulsar's answer, formalized years ago and now standard across [the Apache Pulsar documentation](https://pulsar.apache.org/docs/concepts-tiered-storage), is to acknowledge that hot and cold data have different access patterns and treat them as fundamentally different storage problems.

Hot data — the last few minutes or hours — is read often, written often, and needs millisecond latency. Cold data — days, weeks, months — is read rarely, written never, and only needs to be cheap and durable. Building one system that does both well is hard. Building two systems and gluing them together is straightforward, as long as the glue is invisible.

## The Two-Tier Mental Model

Pulsar's tiered storage is built on a clean separation between two layers:

- **Hot tier**: BookKeeper ledgers, co-located with brokers, backed by local SSDs or NVMe.
- **Cold tier**: Long-term object stores (S3, GCS, Azure Blob, HDFS, or filesystem), addressed via pluggable offloaders.

A topic is not "in" one tier or the other. A topic is a logical stream; the physical segments that make it up may live in either tier at any moment. A reader who asks for offsets from yesterday might hit BookKeeper for the tail and S3 for the head of the historical window. The broker handles the join.

This is the architectural decision that makes the rest of the system possible. Once you stop asking "where does this topic live?" and start asking "which segments live where?", almost every hard problem becomes a caching problem.

## BookKeeper: The Hot Tier Done Right

BookKeeper is the unsung half of Pulsar. Most people meet it as "the thing that stores messages" and move on. That undersells it. BookKeeper is a replicated log primitive that gives Pulsar three properties that are surprisingly hard to get at the same time:

1. **Strong durability** via write-ahead replication across an ensemble of bookies, configurable per ledger.
2. **Tail latency that's predictable**, because reads and writes don't share disk head with compaction, as described in [the BookKeeper overview](https://bookkeeper.apache.org/docs/latest/overview/overview/).
3. **Independent segment lifecycles**, because each segment is a separate ledger that can be sealed, replicated, and ultimately offloaded on its own schedule.

A Pulsar topic is partitioned, and each partition is a sequence of ledgers. Brokers write entries to the active ledger; once that ledger hits a size threshold or an age threshold, it seals and a new one opens. Sealing is the moment tiered storage becomes possible: a sealed ledger is immutable, so it can be copied anywhere without coordination.

In production, the typical config looks something like this:

```yaml
managedLedgerDefaultEnsembleSize: 3
managedLedgerDefaultWriteQuorum: 3
managedLedgerDefaultAckQuorum: 2
managedLedgerMaxSizePerSegmentMb: 512
managedLedgerSegmentSizeBootstrapThreads: 4
```

Three replicas, quorum writes, half-gigabyte segments. That last number matters more than people expect: it's the unit at which tiered storage operates. Bigger segments mean fewer round trips to S3 during offload; smaller segments mean faster cold reads because the broker can prefetch in finer granularity. There's no universally correct value, but anything in the 128 MB to 1 GB range tends to work well.

## Cold Tier: Offloaders and Segment Stores

When a ledger is sealed, it becomes eligible for offload. An offloader is a Pulsar component — typically running alongside the broker or as a dedicated function — that reads the sealed ledger from BookKeeper, packages it into a segment in the cold store, and records the mapping in the topic's metadata.

The mechanics look like this:

1. Broker detects a sealed ledger older than `offloadThreshold` (size or age).
2. Offloader reads entries from the bookie ensemble in parallel.
3. Entries are written to the cold store as an immutable object — typically one segment per ledger.
4. Metadata is updated to point the cursor at the cold segment.
5. Once the offload is acked and cursors confirm no readers need the hot copy, the local ledger can be deleted.

The offloader interface is intentionally pluggable. The same broker can offload to S3 in one cluster and HDFS in another. Pulsar ships with first-class support for AWS S3, GCS, Azure Blob, and HDFS, and the extension surface is small enough that teams have written offloaders for MinIO, Ceph, and even S3-compatible appliances.

> **Note on terminology.** Pulsar has gradually moved toward calling the cold tier a "segment store" rather than just "long-term storage." The newer framing emphasizes that the cold tier is a queryable, addressable storage layer, not just an archive. Offloading is the act of moving a segment into the store; the store itself is the persistent layer below it.

## Why Segments Are the Right Unit

A lot of systems try to do tiered storage at the topic level or the partition level. Pulsar does it at the segment level, and that choice has outsized consequences.

A segment is small enough that offload is fast and predictable. A 512 MB segment on a healthy bookie ensemble can be read and uploaded in seconds. That means offload can run frequently, the hot tier can stay small, and recovery from offload failures doesn't require replaying a multi-gigabyte blob.

A segment is large enough that cold storage overhead is negligible. S3 PUT costs, list operations, and metadata overhead are all amortized over hundreds of thousands of entries per segment. You don't end up with billions of tiny objects.

A segment has a stable identity. Because ledgers are sealed and named, the cold tier can use the ledger ID as a content-addressable key. Idempotent uploads, retries, and crash recovery are all trivial. The offloader can crash, restart, and resume without leaving duplicates.

Most importantly, a segment boundary is a natural place to switch storage tiers without changing the read API. To a Pulsar client, reading an offset is reading an offset. Whether the broker fetched the bytes from a local journal or streamed them from S3 is invisible.

## Architecture in a Real Production Cluster

Let me walk through how this looks when it's actually deployed, because the on-paper architecture leaves out a lot of operational detail.

A typical Pulsar deployment for petabyte retention has four moving parts:

- **Brokers**: stateless serving tier. Handle produce, consume, and admin.
- **Bookies**: stateful storage tier for hot data. Run on dedicated nodes with local NVMe.
- **ZooKeeper (or the embedded metadata store in newer releases)**: cluster coordination and leader election.
- **Cold store**: S3, HDFS, or equivalent. Lives outside the cluster entirely.

Brokers don't store data. That's the first thing newcomers get wrong. Brokers cache, but they don't persist. If a broker dies mid-request, the client fails over to another broker, which reads the same data from the same bookies. This is what makes Pulsar horizontally elastic for serving: you can add brokers without rebalancing data.

Bookies don't serve reads directly to most clients, but they do serve the historical tail to consumers via "tailing reads" exposed through the brokers. The bookie's primary job is durable ingestion: take a write, replicate it, ack it, and hand the sealed ledger off to the offloader when the time comes.

The offloader is where retention policy actually lives. It's configured per namespace, and the relevant knobs are familiar to anyone who has run Kafka with log compaction or tiered storage:

```yaml
offloadThresholdBytes: 1073741824  # 1 GiB per segment
offloadThresholdSeconds: 86400     # 24 hours
offloadDirectory: "s3://pulsar-cold/prod-cluster"
```

Once a sealed segment crosses both thresholds, it's eligible. The offloader picks it up, uploads it, and updates metadata. Within minutes, that data is paying S3 storage prices instead of NVMe prices.

## Cold Reads: How Replay Actually Works

The more interesting question is what happens when a consumer asks for data that's been offloaded. Two cases matter.

**Case 1: subscription was active when offload happened.** The subscription cursor is tracked in ZooKeeper (or the equivalent metadata store) and is updated atomically with the offload completion. When the consumer's position moves into the offloaded region, the broker notices, fetches the segment from cold storage, caches it locally — typically in a tiered cache that itself uses local disk and memory — and streams it to the consumer. The consumer sees a slightly higher first-read latency for that segment and then normal latency.

**Case 2: new consumer reading historical data.** This is the case that worries operators the most. A new analytics job starts, opens a subscription at `EARLIEST`, and starts asking for data from six months ago. Every segment it touches is cold. Pulsar handles this with a read-ahead cache on the broker: as soon as the broker detects a consumer reading from a cold segment, it prefetches adjacent segments and warms the cache. A well-tuned prefetch turns a multi-hour replay into something that finishes in minutes, because cold storage throughput is the bottleneck and prefetch hides it.

The cache itself is a tiered affair. Recent offloaded segments sit in memory or local SSD; older ones are evicted and re-fetched on demand. For very large replay jobs, operators often run a dedicated "catch-up" consumer pool that warms the cache for the rest of the cluster.

## Patterns in Production: What Teams Actually Do

A few patterns come up repeatedly in the field.

**Namespace-scoped policies.** Most teams don't configure offload per topic. They configure it per namespace, with one set of policies for transactional data, another for telemetry, another for audit logs. Audit logs might offload after 24 hours to S3-IA; telemetry might stay hot for a week because it gets replayed often.

**Cross-region cold replication.** The cold tier is a natural place to handle disaster recovery. Offload to S3 in `us-east-1` with a lifecycle rule that replicates to `us-west-2`, and you've got cross-region DR that doesn't cost you a hot cluster in the second region. The hot cluster can be reconstructed from cold storage if needed.

**Compaction alongside tiering.** Pulsar supports topic compaction, and it's complementary to tiered storage rather than competing. A compacted topic stores only the latest value per key; tiered storage keeps the full history. Many teams run both: compacted for the current state, tiered for the audit trail.

**Separation of compute and storage.** Because offloaded data lives in S3, broker pools can be resized without touching storage. This is the property that lets teams run Pulsar for batch-style workloads — read six months of events, compute aggregates, write back — without provisioning a cluster that can hold six months of hot data.

## Common Failure Modes and How to Handle Them

Tiered storage is not free of operational complexity. A few things bite repeatedly.

**Offloader lag.** If the offloader falls behind, the hot tier grows. Bookies fill up, and eventually the cluster rejects writes. The fix is almost always to scale the offloader, not to disable offload. Monitoring should track offload backlog explicitly: count of sealed-but-not-offloaded ledgers, total bytes pending, oldest pending segment age.

**Cold store throttling.** S3 will throttle you if you burst too hard. Pulsar's offloader has backpressure and per-segment parallelism limits, but teams that turn off those limits to "go faster" usually end up with HTTP 503 storms and a wedged offload pipeline. The default limits are conservative for a reason.

**Cache stampedes.** A new analytics job reading from `EARLIEST` can produce a thundering herd against the cold store. The fix is staggered prefetch and per-segment request coalescing. If you're seeing this in production, it's worth tuning the broker's `managedLedgerOffloadPrefetchThread` settings explicitly.

**Metadata drift.** Offload metadata lives in ZooKeeper. If ZK loses state, the broker can't find cold segments. Pulsar mitigates this with explicit metadata reconciliation on broker startup, but it's a reminder that the cold tier is only as good as the metadata pointing at it.

## How Pulsar Compares to Alternatives

Kafka users will recognize the shape of this from [KIP-405](https://cwiki.apache.org/confluence/display/KAFKA/KIP-405%3A+Tiered+Storage) and the various tiered storage implementations that followed. The architectural comparison is instructive.

Kafka's tiered storage — introduced as a preview and now generally available — does roughly the same thing at roughly the same unit (log segments) with roughly the same offload pattern. The differences are in the details: how metadata is tracked, how the serving tier interacts with the storage tier, and how the boundary is managed during failover. Pulsar's approach, designed from the ground up around BookKeeper, has the advantage of a clean separation between serving brokers and storage bookies; Kafka's design has to retrofit tiered storage onto a system that historically fused them.

The bigger difference is operational. Pulsar's hot tier is a separate set of processes (bookies) that can be scaled, monitored, and failed independently of brokers. That separation makes "tiered storage" feel less like a feature and more like an architectural invariant.

## Key Takeaways

- Pulsar's tiered storage is built on segment-level offloading: sealed BookKeeper ledgers are uploaded to a cold store once they cross configurable size or age thresholds.
- The unit of offload is the segment, which gives you predictable offload jobs, low cold-storage metadata overhead, and a read API that's identical across tiers.
- The cold tier is pluggable via the offloader interface; S3, GCS, Azure Blob, and HDFS are all first-class.
- Cold reads are served by brokers via a prefetch cache, so replay latency is dominated by cold-store throughput, not by metadata lookups.
- Operational discipline matters: monitor offload backlog, respect cold-store rate limits, and tune prefetch to prevent cache stampedes.
- The architectural separation between brokers and bookies is what makes tiered storage feel native rather than bolted on.

## Further Reading

- [Pulsar Concepts: Tiered Storage](https://pulsar.apache.org/docs/concepts-tiered-storage)
- [Apache BookKeeper Overview](https://bookkeeper.apache.org/docs/latest/overview/overview/)
- [Pulsar Administration: Configuring Tiered Storage](https://pulsar.apache.org/docs/admin-tiered-storage)
- [StreamNative: Tiered Storage in Apache Pulsar](https://streamnative.io/blog/engineering/2021-04-12-tiered-storage-in-apache-pulsar)
- [Kafka KIP-405: Tiered Storage](https://cwiki.apache.org/confluence/display/KAFKA/KIP-405%3A+Tiered+Storage)