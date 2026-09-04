---
title: "Inside Apache Flink's Checkpointing Algorithm: How Exactly-Once State Guarantees Survive Pipeline Failures"
date: "2026-09-04T08:00:45.246"
draft: false
tags: ["apache-flink", "streaming", "exactly-once", "checkpointing", "distributed-systems", "stateful-processing"]
description: "A deep dive into Apache Flink's Chandy-Lamport based checkpointing algorithm, showing how exactly-once state survives job manager failover and operator crashes."
summary: "How Apache Flink's distributed snapshot algorithm coordinates barriers across operators, persists state to durable storage, and recovers jobs after failure without losing or duplicating records."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-apache-flink.svg"
  alt: "Diagram of Flink checkpoint barriers flowing through a streaming pipeline with aligned state snapshots."
  caption: ""
  relative: false
---

> **TL;DR** — Flink's exactly-once guarantees are not a single mechanism but a protocol: operators inject *checkpoint barriers* into the data stream, the job manager persists a globally consistent snapshot of all operator state to durable storage, and on failure the streams are rewound and the state is rehydrated from that snapshot. Understanding barriers, alignment, and the recovery loop is the difference between a job that loses data and one that doesn't.

## Why Checkpointing Is Harder Than It Looks

A streaming job looks deceptively simple — data in, transformations, data out. The hard part is **state**: a windowed aggregation, a join buffer, a RocksDB-backed value table. Every operator that touches a record may also touch state, and that state has to be consistent with the records it has processed. The moment a TaskManager dies, you have two competing concerns:

1. **Don't lose state.** A window over the last 60 seconds can't be recomputed if you don't remember what arrived in the last 60 seconds.
2. **Don't replay records into state that already reflects them.** Otherwise the count goes from 1,000 to 2,000 for the same data and your downstream consumer sees duplicates.

These two requirements are the heart of the **exactly-once** problem, and the algorithm Apache Flink uses to solve it is one of the most carefully engineered pieces of distributed-systems code in any open-source project. The original design draws on [Chandy and Lamport's 1985 paper on distributed snapshots](https://lamport.azurewebsites.net/pubs/chandy.pdf), but Flink's adaptation is shaped by the realities of streaming at scale: backpressure, skewed keys, network partitions, and operators with very different state sizes.

## The Core Idea: Barriers, Not Locks

Flink's checkpointing is built on a single elegant primitive: the **barrier**. A barrier is a special control record that flows through the job graph alongside data records. It marks a logical point in the stream — "everything before this barrier is part of checkpoint N, everything after is part of checkpoint N+1."

When an operator receives a barrier on one of its input channels, it knows it has seen the last record that belongs to the current checkpoint. The operator takes a snapshot of its own state, writes it to durable storage, and forwards the barrier downstream. Once every operator has emitted its barrier and every input channel has absorbed one, the system has a globally consistent snapshot.

This works because barriers are **logical timestamps**, not locks. They don't stop the stream — they travel with it. Data keeps flowing, backpressure is unaffected, and the only synchronization point is a small buffer at channel junctions during *alignment*, which we'll cover below.

## Anatomy of a Checkpoint

A checkpoint is born on the **JobManager** (in modern deployments, often the `Dispatcher` plus the `ResourceManager`, with per-job leader election handled by ZooKeeper or Kubernetes). The lifecycle looks like this:

1. The JobManager's `CheckpointCoordinator` triggers a new checkpoint, assigning it a monotonically increasing ID.
2. The coordinator injects a barrier into each source operator's stream.
3. As barriers propagate through the job graph, each operator takes a snapshot of its own state when it has received barriers from all of its input channels.
4. When an operator finishes its snapshot, it asynchronously writes it to the configured **state backend** (RocksDB, HashMapStateBackend, or in older versions, FsStateBackend) and acknowledges back to the coordinator.
5. Once all operators have acknowledged, the checkpoint is marked `COMPLETED`. If any operator fails or times out, the checkpoint is `FAILED` and the next recovery will fall back to the last successful one.

State backends are pluggable, but the most common in production is [RocksDBStateBackend](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/state_backends/#rocksdbstatebackend), which spills state to local SSDs and uploads incremental files to a distributed filesystem like S3 or HDFS. HashMapStateBackend keeps state in JVM memory and is faster but capped by heap size.

## The Alignment Problem (and Why It Matters)

When an operator has multiple input channels — a `union`, a `keyBy` followed by a window, anything with a join or a co-flat-map — barriers arrive on different channels at different times. Until the last barrier arrives, the operator must not process records from any input beyond the barrier on that input, because doing so would let data from checkpoint N+1 leak into state that is being snapshotted for checkpoint N.

Flink solves this with **input alignment**: when an operator sees a barrier on channel A, it stops reading from channel A and buffers the records it can't process yet. It continues reading from other channels. When the last barrier arrives, it drains the buffers, processes everything up to the barrier, snapshots state, and then emits its own barrier downstream.

Alignment is what gives Flink its **exactly-once** semantics rather than **at-least-once**. Without it, an operator could process a record that "logically" belongs to the next checkpoint while still taking a snapshot for the current one, and on recovery the record would be applied twice.

The cost of alignment is **latency spikes** under backpressure. If channel A is much slower than channel B, the operator stalls B waiting for A. For low-latency workloads, Flink exposes a knob: `CheckpointingMode.AT_LEAST_ONCE` with `enableCheckpointing(..., CheckpointingMode.AT_LEAST_ONCE)` and a side-output for unaligned checkpoints. The [Flink documentation on checkpointing](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/) walks through the trade-offs, and operators that emit a barrier downstream without fully draining are clearly marked in the metrics.

## Unaligned Checkpoints: Trading Guarantees for Latency

For jobs where every millisecond of latency matters — fraud detection, real-time bidding, ad serving — even a small alignment pause is unacceptable. Flink introduced **unaligned checkpoints** to address this. In unaligned mode, an operator does not buffer records while waiting for late barriers. Instead, it stores the in-flight buffers as part of its own snapshot.

The trade-off is that the persisted state now includes not just operator state but also the buffered data, which can be large. Recovery is correct (the buffers are replayed into the right state version), but the per-checkpoint storage cost rises sharply. The [unaligned checkpoints design document](https://cwiki.apache.org/confluence/display/FLINK/FLIP-76%3A+Unaligned+Checkpoints) is one of the clearest explanations of the algorithm; if you operate a low-latency Flink job, it's worth reading end-to-end.

## Patterns in Production: Where Exactly-Once Breaks (and How to Keep It)

Flink's protocol gives you exactly-once **inside the job graph**, but the guarantee ends at the sinks. The most common production failure mode is a sink that doesn't participate in the protocol, which silently downgrades the job to at-least-once.

```java
// Exactly-once: the sink participates in the checkpoint
stream.addSink(new TwoPhaseCommitSinkFunction<>(
    new SimpleStringSerializer(),
    new TransactionalSinkStateSerializer(),
    "jdbc:postgresql://db/app"
) {
    @Override
    protected void beginTransaction() throws Exception { /* BEGIN */ }
    @Override
    protected void invoke(Transaction txn, String value, Context ctx) { /* INSERT */ }
    @Override
    protected void preCommit(Transaction txn) throws Exception { /* PREPARE */ }
    @Override
    protected void commit(Transaction txn) { /* COMMIT */ }
});
```

A two-phase commit sink writes records during normal processing, then **commits** them in the second phase of the checkpoint. If the job fails between pre-commit and commit, the transaction is rolled back and Flink replays the records on recovery. This is the pattern Kafka's exactly-once producer uses internally via [transactional IDs](https://kafka.apache.org/documentation/#producerapi), and it's what makes end-to-end exactly-once possible.

Sinks that don't support transactions — many HTTP-based systems, most NoSQL stores, anything that doesn't expose a two-phase API — require an **idempotent sink** instead. A common pattern is to include the checkpoint ID or a sequence number with each record and let the downstream system dedupe. The Flink community has documented this in the [data sink idempotence guide](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/overview/).

Other patterns that bite teams in production:

- **State size growth.** A windowed aggregation over unbounded data will eventually exhaust any backend. Either use [session windows with a merger](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/operators/windows/), TTL'd value state, or rocksdb state with a configured `state.backend.incremental` policy.
- **Slow checkpoint alignment.** If `checkpointAlignmentTime` keeps climbing, look at skewed keys in the upstream `keyBy`. A keyed operator with a hot key serializes all state access through one task.
- **External side effects.** If your operator calls a third-party API, that call is not part of the checkpoint. Wrap it in a `ProcessFunction` with a side-output for retries, or treat the third party as a transactional sink and write through a buffer.

## Recovery: What Happens When a TaskManager Dies

When a TaskManager heartbeats miss, the JobManager declares it failed and starts the recovery protocol:

1. Cancel all currently running tasks.
2. Select the **latest completed checkpoint** from the `CompletedCheckpointStore`.
3. Re-deploy the entire job graph onto the remaining TaskManagers (or scale up new ones if the cluster has capacity).
4. Reset all operators to the state stored in that checkpoint.
5. Rewind the source connectors to the offset stored in the checkpoint.

For Kafka, the source remembers the offset of the last barrier it processed for the recovered checkpoint. On restart, it seeks to that offset and starts emitting records again, with the next barrier inserted immediately. For filesystems, the source rewinds using a configurable [enumerator strategy](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/file/).

Because the snapshot is consistent — every operator's state matches the data the sources would emit at the same point in the stream — recovery is mathematically equivalent to a non-failed run. That's the property Chandy and Lamport proved in 1985, and it's what Flink's engineers turned into a production system a decade later.

## Key Takeaways

- **Barriers are the abstraction.** Everything in Flink's checkpointing is built around barrier injection, propagation, and acknowledgement, not locks or transactions on the data path.
- **Alignment is what makes it exactly-once.** Skipping alignment (or using at-least-once mode) trades correctness for latency; choose deliberately.
- **The guarantee ends at the sink.** End-to-end exactly-once requires a two-phase commit sink or an idempotent downstream; Flink can't fix a sink that doesn't participate.
- **State backends drive operational cost.** RocksDB with incremental checkpoints and S3 is the default for stateful production jobs; memory-backed state is for dev only.
- **Recovery is replay from a known-good snapshot.** Source offsets, operator state, and barrier positions must all be consistent, or recovery will drift.
- **Watch your metrics.** `checkpointDuration`, `checkpointAlignmentTime`, and `numLateCheckpoints` are the three numbers to alert on.

## Further Reading

- [Chandy & Lamport, "Distributed Snapshots: Determining Global States of Distributed Systems"](https://lamport.azurewebsites.net/pubs/chandy.pdf) — the original algorithm Flink adapts.
- [Apache Flink documentation: Checkpointing](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/) — official reference for barrier semantics, alignment, and modes.
- [FLIP-76: Unaligned Checkpoints](https://cwiki.apache.org/confluence/display/FLINK/FLIP-76%3A+Unaligned+Checkpoints) — the design proposal that introduced unaligned mode for low-latency workloads.
- [Flink Forward talk: "An Overview of End-to-End Exactly-Once Processing in Apache Flink"](https://www.youtube.com/watch?v=1tn7d9QX5Kk) — Piotr Nowojski's deep dive from the team that built the protocol.
- [Kafka producer transactions](https://kafka.apache.org/documentation/#producerapi) — the most common two-phase commit partner for Flink sinks in production.