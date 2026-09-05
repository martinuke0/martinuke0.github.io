---
title: "Inside Redpanda: How a Kafka-Compatible Engine Replaces ZooKeeper for Streaming"
date: "2026-09-05T00:00:27.511"
draft: false
tags: ["redpanda", "kafka", "kafka", "streaming", "raft", "distributed-systems"]
description: "Redpanda drops ZooKeeper and rewires Kafka's controller quorum around Raft. Here is how the engine works under the hood."
summary: "A deep dive into Redpanda's C++ core, the Raft-based controller quorum that replaces ZooKeeper, and what tradeoffs come with deleting a coordination service from your streaming stack."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-inside-redpanda-how-a-kafka-compatible-engine-replaces-zookeeper-for-streaming.svg"
  alt: "Stylized illustration of streaming partitions and a Raft consensus diagram."
  caption: ""
  relative: false
---

> **TL;DR** — Redpanda is a Kafka-API-compatible streaming engine written in C++ that removes ZooKeeper by running cluster metadata on an embedded Raft consensus group inside the brokers themselves. The result is lower tail latency, simpler operations, and a single binary to deploy — but the design also relocates failure modes that used to live in ZooKeeper into the broker process.

A few years ago, "running Kafka" really meant "running Kafka and ZooKeeper." Two clusters, two sets of JVM tuning parameters, two quorum systems to monitor, and a healthy amount of hair-pulling whenever one fell behind. [The KIP-500 design doc](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum) made it clear that the Kafka community saw this as a wart, and the eventual KRaft mode shipped that vision years later. Redpanda took a different path: it skipped ZooKeeper entirely on day one and built the whole thing in C++ on top of Raft.

This post walks through the engine: how metadata is stored, how leadership actually works, what changes at the wire protocol level, and where the new architecture pushes complexity.

## The ZooKeeper Tax on Streaming

To appreciate what Redpanda is doing, it helps to remember what ZooKeeper was actually doing inside a classic Kafka deployment.

Kafka's brokers are stateless about cluster membership. They don't independently decide who is the leader of partition 7 — they ask the controller, and the controller asks ZooKeeper. Every broker registration, every topic creation, every ISR change flows through a ZooKeeper znode. The controller is just a hot standby that watches ZooKeeper and pushes the resulting state out to the rest of the cluster.

This split had three costs that engineers felt daily:

1. **Two quorums to operate.** A 3-broker Kafka cluster was usually a 5-node ensemble, and you had to keep the JMX metrics, log retention, and snapshot policies of both clusters healthy.
2. **Metadata lag.** Controller-to-broker metadata propagation was eventually consistent. Producers in particular saw "unknown topic" errors after creation for a window measured in hundreds of milliseconds. The [`kafka-topics.sh`](https://kafka.apache.org/documentation/#basic_ops) CLI had been papering over this for years with retry loops.
3. **JVM overhead on the hot path.** ZooKeeper is a Java application. Every metadata change crossed a process boundary, got serialized, hit a TCP socket, and crossed another process boundary back.

Redpanda's bet is that all of this can collapse into the broker itself, on the assumption that the consensus algorithm you need is already in the literature and doesn't need a separate product to host it.

## How Redpanda Runs Without ZooKeeper

The headline claim is simple: Redpanda uses [Raft](https://raft.github.io/) to replicate cluster metadata among the brokers, and the brokers serve as both the data plane and the control plane. There is no second cluster to install.

### The controller Raft group

Every Redpanda cluster has a special Raft group called the **controller group**, whose participants are the brokers themselves. The controller group owns the canonical cluster state: topics, partitions, replicas, leadership assignments, and configuration. The log of the controller group is itself a sequence of records describing state changes — `create_topic`, `delete_topic`, `move_partition_leader`, and so on.

When a broker boots, it doesn't phone home to ZooKeeper. It joins the controller group, replays the metadata log from a configured offset, and ends up holding the same view of the cluster as everyone else. This is the same pattern as Kafka's later KRaft mode, but Redpanda has been running it since the project's first release.

Crucially, only one of the controller-group participants is the **controller leader** at any time, and that leader is the sole writer to the metadata log. Followers accept appends and replicate them, but they don't initiate state changes. This is what gives the cluster a single linearizable source of truth without external coordination.

### Where partitions live

Data partitions are organized into **raft groups of their own**, one per partition. The leader of each partition Raft group handles writes; followers replicate. This is structurally identical to Kafka's leader/follower model, and it is also the same shape as Kafka's KRaft partitions — the difference is just that both layers of consensus use the same C++ Raft implementation inside one binary.

The pattern is worth drawing out, because it is the kind of thing that becomes obvious only after you have operated a system for a while:

| Layer | State owned | Replicated by | Failure mode |
|---|---|---|---|
| Controller Raft group | Cluster metadata | Brokers (controllers) | Leader election stalls; cluster accepts no new topics until restored |
| Partition Raft group | Topic records | Partition replicas | Leader election stalls; that partition is unavailable until restored |
| (Kafka + ZooKeeper) | Cluster metadata | ZooKeeper ensemble + Kafka controller | Two failure domains, two JMVs, two quorum sizes to reason about |

### The wire protocol

Despite the internal rewrite, Redpanda speaks the Kafka wire protocol. The same `produce`, `fetch`, `createTopics`, and `Metadata` requests that work against Apache Kafka work against Redpanda, with a handful of unimplemented admin APIs. This is the lever that lets teams swap engines without rewriting applications or changing client libraries — a producer using [`librdkafka`](https://github.com/confluentinc/librdkafka) does not know it is talking to Redpanda.

The protocol compatibility is implemented by an Apache-licensed Kafka request/response layer inside Redpanda's codebase, which makes the project a useful reference for anyone building a Kafka-compatible system. The [Redpanda protocol compatibility docs](https://docs.redpanda.com/current/develop/kafka-clients/) spell out exactly which APIs are supported and at what version.

## Patterns in Production

A consensus-driven metadata layer changes how you operate the cluster. A few patterns that show up repeatedly in production deployments:

### Scaling controllers separately from data

Because every broker is a controller-group participant, you can size the cluster for metadata write throughput without sizing it for partition replication. A common Redpanda topology is a small number of dedicated controllers (often three) running on smaller instances, with a larger pool of data-only nodes handling partitions. The [Redpanda architecture overview](https://docs.redpanda.com/current/get-started/architecture/) describes this as the `controller-only` and `data-only` roles, set via configuration.

This is something classic Kafka cannot do cleanly. With ZooKeeper, every controller is a full broker that just happens to also be a metadata writer, and you cannot put controllers on cheaper nodes because they are carrying partition leadership responsibilities.

### Predictable failover

In a ZooKeeper-backed Kafka cluster, leadership transfer is a multi-step dance: the controller notices a broker is gone, computes the new assignment, writes it to ZooKeeper, and then pushes the change to brokers. In Redpanda, the partition leader's follower detects the missed heartbeat, times out, and runs a local Raft election. The new leader announces itself through the data path; the controller Raft group is informed asynchronously.

The practical effect is that failover time is bounded by the election timeout rather than by ZooKeeper's session expiry plus the controller's processing delay. Operators typically see partition leaders re-elect in the low seconds versus the multi-second tail they saw with the older stack. The exact numbers depend on tuning, but the shape of the curve is consistent across deployments.

### Faster topic creation

Because topic creation is now a Raft append on the controller group rather than a ZooKeeper znode write followed by a Kafka controller cache update, the metadata propagation window shrinks. Producers creating topics on the fly — a common pattern in event-sourced microservices — see `UNKNOWN_TOPIC_OR_PARTITION` errors for shorter windows. The improvement is most visible on cold-start workloads where a service comes up and immediately needs to publish to a topic that was just created.

## The Failure Modes That Moved

Removing a system is rarely free. Redpanda did not eliminate failure modes; it relocated them. Three deserve attention.

### Controller-group health is cluster health

If the controller Raft group loses quorum, the cluster stops accepting metadata changes. New topics cannot be created, partition assignments cannot be rebalanced, and certain admin operations stall. Data partitions keep serving reads and writes, but the cluster is effectively read-mostly until the controller group recovers.

In a ZooKeeper-backed cluster, the equivalent failure mode was ZooKeeper losing quorum, which was catastrophic but rare. In Redpanda, the controller group lives on the same hardware as the data brokers, so the failure modes that affect it are the same ones that affect partitions: a rack power failure, a kernel panic, a noisy-neighbor VM. The mitigation is the same too — spread replicas across failure domains — but the consequence is now more visible because more state lives in that group.

### Disk and memory pressure hit both planes

Classic Kafka could be operated with a relatively small ZooKeeper ensemble whose I/O was dominated by metadata writes. Redpanda's controllers do real work: they persist the metadata log, they compact it, and they serve reads from it under load. If you size controllers on small instances, you must budget for the same kind of disk and memory headroom you would give a broker, even if those controllers hold no partitions.

The [Redpanda tuning guide](https://docs.redpanda.com/current/manage/cluster-maintenance/tune-redpanda/) is explicit about this. The interesting failure is the one where disk fill on a controller node stalls metadata writes first and partitions second — the opposite of what an operator who came from the Kafka+ZooKeeper world might expect.

### Single binary, single bug

A benefit on the upside, a risk on the downside: a memory leak, a deadlock, or a panic in the broker process now takes the controller with it. There is no longer a process boundary between the metadata store and the data store. This is why production deployments tend to run controller-only nodes with restricted partition counts: it isolates the role whose failure takes down the cluster from the role whose failure takes down a workload.

## Inside the C++ Engine

A few words about the language choice, because it shows up in every architectural discussion of Redpanda.

The engine is written in modern C++ (C++17/20 in current releases) using [`seastar`](https://github.com/scylladb/seastar), the asynchronous framework originally built for ScyllaDB. Seastar gives Redpanda a shared-nothing, thread-per-core execution model: each CPU core runs its own event loop with no locks, and inter-core communication happens via explicit message passing. The same model powers ScyllaDB and has been measured at very high throughput per node.

This is a deliberate contrast with the JVM-based Kafka broker, which leans on the JVM's GC and thread pool for concurrency. The trade-off is well-documented in the [Redpanda blog post on seastar](https://redpanda.com/blog/seastar): you give up the JVM's mature tooling and gain predictable tail latency, because there is no GC pause to wait out and no thread pool to saturate. For workloads sensitive to p99 — ad-serving, real-time bidding, leaderboards — the tradeoff is usually worth it.

The cost is that the C++ ecosystem around streaming is thinner than the JVM one. Schema registries, Connect workers, ksqlDB, and the rest of the Confluent stack are JVM applications that talk to Kafka over the wire; they work fine against Redpanda because of protocol compatibility, but they do not share a runtime with it. Teams adopting Redpanda typically keep those JVM tools in their stack and gain the latency benefits only on the broker side.

## When the Architecture Pays Off

Redpanda is not a universal upgrade. The architecture pays off most clearly in three situations:

- **Latency-sensitive single-cluster workloads.** When p99 sub-10ms is a hard requirement, the absence of a JVM in the broker and the shorter failover window are concrete wins. The [Redpanda performance documentation](https://docs.redpanda.com/current/manage/cluster-maintenance/performance/) cites benchmark numbers in this regime.
- **Simplified operations for small teams.** A team that does not want to operate a ZooKeeper ensemble gets a single binary, a single configuration file, and a single set of metrics. For a 3-broker dev cluster this is a meaningful ergonomic win.
- **Edge and small-footprint deployments.** Redpanda runs on hardware as modest as a single-node test cluster on a laptop, and its low memory footprint makes it viable at the edge. The [Redpanda quickstart](https://docs.redpanda.com/current/get-started/quick-start/) demonstrates a single-binary install that takes seconds.

## When to Stay on Kafka

There are also cases where Redpanda's design choices are not an advantage:

- **Heavy reliance on JVM ecosystem tooling.** If your pipeline is built around Kafka Streams, ksqlDB, or Connect workers and you value single-runtime debugging, the Kafka stack has fewer moving parts.
- **Very large clusters with extreme metadata churn.** The controller Raft group is a single linearizable writer. Clusters with thousands of topics and very high topic-creation rates can stress it in ways that a more sharded metadata store would not.
- **Compliance stacks that pin specific vendor versions.** Some regulated environments require running a specific Apache Kafka minor version with a specific ZooKeeper version and specific CVEs patched. Redpanda's release cadence is independent of Apache Kafka's, so the compliance story is different.

## Key Takeaways

- Redpanda replaces ZooKeeper with a Raft consensus group hosted inside the broker process; there is no second cluster to install.
- The controller Raft group owns all cluster metadata, and partition Raft groups own topic data; both layers use the same C++ consensus implementation.
- Protocol compatibility with Kafka means producers and consumers do not need to change when the engine swaps.
- Failover is faster because partition leadership transitions are local Raft elections rather than ZooKeeper-mediated controller updates.
- The failure modes that used to live in ZooKeeper are now inside the broker process, so controller isolation and sizing matter more than they did in the old architecture.
- The C++/Seastar execution model delivers predictable tail latency but trades away the JVM ecosystem that surrounds the classic Kafka stack.

## Further Reading

- [Redpanda Architecture Overview](https://docs.redpanda.com/current/get-started/architecture/)
- [KIP-500: Replace ZooKeeper with a Self-Managed Metadata Quorum](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum)
- [The Raft Consensus Algorithm](https://raft.github.io/)
- [Seastar: High-Performance Server Framework](https://github.com/scylladb/seastar)
- [librdkafka: The Kafka Client Library Used by Most Producers](https://github.com/confluentinc/librdkafka)
- [Apache Kafka Broker Architecture Documentation](https://kafka.apache.org/documentation/#design)