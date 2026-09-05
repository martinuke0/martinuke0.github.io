---
title: "Inside Apache Flink's Two-Phase Commit Sink: Exactly-Once Guarantees Across Sinks"
date: "2026-09-05T09:00:29.839"
draft: false
tags: ["apache-flink", "stream-processing", "exactly-once", "two-phase-commit", "distributed-systems"]
description: "A working engineer's guide to Apache Flink's two-phase commit sink protocol: how checkpoints, the JobManager, and downstream sinks coordinate to deliver true exactly-once semantics."
summary: "How Apache Flink coordinates checkpoints with sink writers via a two-phase commit protocol to deliver end-to-end exactly-once guarantees across Kafka, filesystems, and databases."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-inside-apache-flink.svg"
  alt: "Diagram of Apache Flink coordinator and sink operators exchanging pre-commit and commit calls during a checkpoint barrier."
  caption: ""
  relative: false
---

> **TL;DR** — Apache Flink delivers end-to-end exactly-once semantics by pairing its distributed checkpoint algorithm with a two-phase commit (2PC) protocol at the sink. Each checkpoint acts as the "prepare" phase and the next successful checkpoint acts as the "commit" trigger, which is why sinks must implement `TwoPhaseCommitSinkFunction` and why idempotent or transactional downstream systems are non-negotiable.

## Why Exactly-Once Is Harder Than It Sounds

A streaming pipeline rarely ends at a Flink operator. Records eventually have to land somewhere durable: a Kafka topic, a Postgres table, a S3 prefix, or a JDBC warehouse. Once they leave the JVM, Flink can no longer guarantee anything about them on its own — it can only coordinate.

This is where most teams quietly lose their "exactly-once" promise. They configure Flink with the right checkpointing settings, point the sink at Kafka, and assume the contract holds. In practice, the guarantee is only as strong as the sink's commit protocol, and most built-in sinks fall into one of two camps:

1. **Idempotent sinks** (e.g., legacy Kafka producers with `enable.idempotence=true` and the new `EXACTLY_ONCE` delivery mode) deduplicate retries using producer IDs and sequence numbers. Simple, but bounded to what the broker understands.
2. **Transactional sinks** that implement Flink's `TwoPhaseCommitSinkFunction` and participate in a real distributed commit protocol coordinated by the JobManager.

The second camp is what people usually mean when they say "Flink's two-phase commit sink." It's also the part most engineers have only a fuzzy mental model of — until something silently double-writes during a failover, and suddenly the model gets very crisp, very fast.

This post walks through the protocol layer by layer: how Flink's barrier-based checkpoints work, what the sink is actually doing between `beginTransaction()` and `commit()`, and why every production Flink deployment eventually ends up caring about transaction IDs, operator UIDs, and `KafkaCommitter` threads.

## How Flink Checkpoints Set the Stage

Two-phase commit doesn't make sense without checkpoints, so we have to start there. Flink's checkpointing model, described in the [Apache Flink documentation on fault tolerance](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault-tolerance/), is based on a few moving parts:

- **The JobManager** plays the role of the coordinator. It injects checkpoint barriers into the source streams at a configured interval.
- **Operator subtasks** receive barriers, snapshot their internal state, and forward the barrier downstream. Each subtask reports back with the location of its snapshot.
- **A durable state backend** (RocksDBStateBackend, HashMapStateBackend) stores the snapshots. With `checkpointing.mode=EXACTLY_ONCE`, the source must also be replay-capable — typically Kafka with appropriate offsets stored as operator state.

Crucially, barriers flow *through* the data stream. They don't pause processing globally; they just force operators to align at logical points where state can be captured consistently across the topology. This is the same idea as [Chandy-Lamport's distributed snapshot algorithm](https://en.wikipedia.org/wiki/Chandy%E2%80%93Lamport_algorithm), and Flink's barrier alignment is its streaming-flavored adaptation.

A checkpoint completes when every subtask has acknowledged its snapshot and the coordinator has written a completed checkpoint metadata record. At that point, the topology has a globally consistent cut through the data — but the external world has *not* yet been told about it. That's the sink's job.

> A useful mental model: every successful checkpoint is a globally consistent "pending write" to the external system. The sink holds that write open until the next checkpoint succeeds.

## Anatomy of the Two-Phase Commit Sink

Flink exposes the 2PC protocol through the `TwoPhaseCommitSinkFunction` abstract class, documented in the [Java API docs](https://nightlies.apache.org/flink/flink-docs-stable/api/java/org/apache/flink/streaming/api/functions/sink/TwoPhaseCommitSinkFunction.html). Subclasses implement four methods that map cleanly to a classic two-phase commit:

```java
public abstract class TwoPhaseCommitSinkFunction<IN, TXN, CONTEXT>
        extends RichSinkFunction<IN> {

    protected abstract void beginTransaction() throws Exception;
    protected abstract void invoke(TXN transaction, IN value, Context context) throws Exception;
    protected abstract void preCommit(TXN transaction) throws Exception;
    protected abstract void commit(TXN transaction) throws Exception;
    protected abstract void abort(TXN transaction) throws Exception;
}
```

The flow on every checkpoint looks like this:

1. **Barrier arrives at the sink.** The sink finishes draining the records in the current transaction (often called "the pending transaction" or `currentTransaction`).
2. **`preCommit(transaction)` is called.** For Kafka this is `flush()` — the producer pushes everything to the broker but does not yet commit offsets. For JDBC this often means a `Connection.commit()` on a *pre-committed* staging transaction.
3. **`commit(transaction)` is called after the JobManager confirms the checkpoint.** Only now does the sink tell the external system "this is permanent." For Kafka, the `KafkaCommitter` thread commits offsets to `__consumer_offsets`. For filesystems, files are atomically renamed from a staging directory.
4. **A new transaction is opened** for the next batch of records via `beginTransaction()`.

The crucial property: `preCommit` happens *before* the checkpoint is acknowledged, while `commit` happens *after*. If the job fails between `preCommit` and `commit`, the next attempt sees a dangling transaction and aborts it. If it fails after `commit`, the downstream system already has the data and the next attempt simply resumes after the last committed checkpoint — no duplicates.

### Why the Sink Needs a Custom Subclass

Out-of-the-box, Flink's `TwoPhaseCommitSinkFunction` does nothing useful on its own. The `invoke()` method that writes records into the transaction is what subclasses implement, and what makes the whole protocol feel concrete. Here is a stripped-down version of how a transactional Kafka sink looks under the hood, modeled after the [Kafka 2PC sink example](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/kafka/) in the Flink docs:

```java
public class ExactlyOnceKafkaSink
        extends TwoPhaseCommitSinkFunction<String, ProducerTransaction, Void> {

    private final String topic;
    private final Properties producerProps;

    public ExactlyOnceKafkaSink(String topic, Properties producerProps) {
        super(new SimpleStringSerializer(), VoidSerializer.INSTANCE);
        this.topic = topic;
        this.producerProps = producerProps;
    }

    @Override
    protected ProducerTransaction beginTransaction() throws Exception {
        KafkaProducer<String, String> producer =
            new KafkaProducer<>(producerProps);
        producer.beginTransaction();
        return new ProducerTransaction(producer);
    }

    @Override
    protected void invoke(ProducerTransaction txn, String value, Context ctx) {
        txn.producer.send(new ProducerRecord<>(topic, value));
    }

    @Override
    protected void preCommit(ProducerTransaction txn) throws Exception {
        txn.producer.flush();
    }

    @Override
    protected void commit(ProducerTransaction txn) {
        txn.producer.commitTransaction();
    }

    @Override
    protected void abort(ProducerTransaction txn) {
        txn.producer.abortTransaction();
    }
}
```

Notice the contract: `beginTransaction` opens a producer-side Kafka transaction, `preCommit` flushes bytes but does not commit, and `commit` triggers `commitTransaction()` only after Flink's checkpoint has been confirmed durable. The `KafkaCommitter` thread is the bridge between Flink's world (operator state holding offsets) and Kafka's world (`__consumer_offsets`); it commits Flink-managed offsets as part of `commit()` so they become visible to downstream consumers exactly when the data does.

## Architecture: Where the Protocol Lives

The interesting bit about 2PC in Flink is not any single component — it's the choreography. Here is how the pieces interact during a successful checkpoint cycle:

1. The **JobManager** (checkpoint coordinator) injects barriers into the source, which travel through the topology and arrive at the sink.
2. The **sink subtask** processes the barrier by calling `preCommit(currentTransaction)`. It then synchronously writes the transaction state into the operator snapshot. At this point, the sink has a "pending" transaction held open against the external system.
3. The sink subtask emits an **ACK** upstream to the coordinator. The barrier continues toward any further sinks.
4. Once the coordinator receives ACKs from all subtasks, it finalizes the checkpoint by writing metadata to durable storage (DFS, S3, GCS).
5. The coordinator calls back into the sink via the `notifyCheckpointComplete()` hook. This is the trigger that runs `commit()` for the transaction that was opened at the previous checkpoint.
7. The sink opens a new transaction for subsequent records.

The recovery story is symmetrical. If the job crashes between step 2 and step 4, the next attempt finds the transaction in `preCommit` state and calls `abort()`. If it crashes after step 5, the transaction is already committed, so recovery simply resumes from the last completed checkpoint. There is no window in which the sink has both acked the data to the external system and lost the internal state to track it.

This is also why the sink's checkpoint state has to contain *both* the application data (offsets, in-flight records, operator state) *and* enough metadata to identify the open transaction. Losing that mapping is exactly what causes silent double-writes during failover — a failure mode described in the [Flink Application Evolution & State Compatibility docs](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/state_backends/).

## Sink Patterns in Production

The protocol is the same, but how teams use it in production varies. Three patterns come up over and over.

### Pattern 1: Kafka → Kafka via the Kafka SQL Connector

The most common Flink pipeline today is Kafka → Flink → Kafka, using the [Kafka SQL connector](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/table/kafka/). When the source and sink are both Kafka with `delivery.guarantee=exactly-once`, Flink's runtime uses `TwoPhaseCommitSinkFunction` transparently. Under the hood, the sink wraps a Kafka producer configured with `transactional.id`, and the connector manages transaction lifecycle. Operators only have to ensure:

- A unique `transactional.id` per parallel sink subtask, derived from the operator UID.
- A unique `client.id` per subtask.
- Sufficient broker-side transaction state log retention (`transaction.state.log.replication.factor` and `min.insync.replicas`) to survive a partial broker outage during commit.

### Pattern 2: Kafka → Filesystem (S3 / HDFS)

The [Streaming File Sink](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/file_sink/) (and its replacement, `FileSink` in `flink-connector-filesystem`) implements 2PC using the **part-file** abstraction. Records are written into in-progress files in a staging directory; on `preCommit` the file is closed and fsynced; on `commit` the file is atomically renamed into the visible output directory via the filesystem's `rename()` semantics (which are atomic on POSIX-compatible object stores like S3, GCS, and modern HDFS).

The catch: this only gives you exactly-once if the downstream consumers also respect the visibility boundary. A Hive partition loader that scans the output directory on a timer might see an in-progress file during recovery. Production teams handle this by either using `RollingPolicy` to make individual files large enough that consumers won't read partial output, or by writing a "finished" marker file as the final step of `commit()` and having consumers wait for it.

### Pattern 3: Kafka → JDBC / Postgres

JDBC sinks are the classic pain point. `TwoPhaseCommitSinkFunction` works, and many teams implement a version that opens a JDBC transaction per checkpoint batch and commits it on `notifyCheckpointComplete()`. But the operational reality is brutal: a Postgres transaction can stay open for the duration of a checkpoint interval (often minutes), holding locks on every touched row. Long-running transactions block autovacuum, balloon `pg_xact`, and cause replication lag spikes.

The pragmatic alternative is the **idempotent upsert** pattern: use `INSERT ... ON CONFLICT DO UPDATE` with a deterministic primary key derived from the source offset or event ID. Combined with Flink's checkpointing, this gives you effectively-once with much friendlier database behavior — at the cost of a small, bounded amount of duplicate work in the rare failure case. The trade-off is spelled out in the [PostgreSQL upsert documentation](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT).

## Failure Modes That Break Exactly-Once in Practice

The protocol is sound, but the surrounding system is not. Five failure modes show up repeatedly in incident reviews:

1. **Sink state is not part of the snapshot.** If a sink writes to an external system *outside* of its `invoke()` method — for example, from a side thread, or in `open()` — that write is invisible to the checkpoint and will be replayed on recovery. Always funnel external writes through `invoke()`.
2. **Non-deterministic parallel subtask assignment.** Flink assigns subtasks to TaskManagers based on available slots. If a job reschedules after failover, the assignment can change, which means the same parallel index might process a different partition of the source. For Kafka transactional sinks, this means the *same* `transactional.id` ends up on two different subtasks across restarts, which corrupts transactions. The fix is to assign stable **operator UIDs** via `uid()` on each operator; Flink then preserves the mapping across restarts. The behavior is documented under [Savepoints vs Checkpoints](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/savepoints/).
4. **Downstream systems that don't support 2PC.** A sink that talks to an HTTP API or an SFTP endpoint has no native transaction to participate in. Flink's checkpoint can still happen, but the sink can only approximate exactly-once by buffering writes and using idempotency keys. Document this honestly in the data contract; don't label the pipeline exactly-once.
5. **Sink parallelism changes between deploys.** If you scale a Kafka 2PC sink from 4 to 8 parallel instances, the new subtasks need new `transactional.id` values. The runtime handles this via the `OperatorID` ↔ subtask mapping, but only if UIDs are set. Otherwise the broker sees two producers fighting over the same transactional id.
7. **Long checkpoint intervals with large transaction buffers.** A 10-minute checkpoint interval means a Kafka transactional producer may hold 10 minutes of records in flight. If the broker's `transaction.max.timeout.ms` is set lower, the producer aborts the transaction silently and you lose data. Match the broker config to the Flink checkpoint interval.

A common postmortem pattern: "We configured `enable.idempotence=true` on the Kafka producer, so we assumed exactly-once." That's only producer-to-broker deduplication. Without the 2PC layer at the Flink sink, you have at-least-once delivery between Flink and Kafka, plus broker-side dedup within a single producer session. Cross-restart, duplicates happen.

## Tuning Knobs That Actually Matter

When you're wiring up a 2PC sink in production, four parameters drive most of the outcomes:

- **`transaction.timeout.ms`** on the Kafka producer. Must be at least the checkpoint interval plus a healthy safety margin. The default of 60 seconds is rarely enough for production checkpoint intervals of 1–5 minutes.
- **`execution.checkpointing.interval`**. Shorter intervals shrink the window of records at risk on failure but increase the cost of committing. The [Flink checkpoint tuning guide](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/config/) recommends starting at 60 seconds and tuning from there.
- **`execution.checkpointing.tolerable-failed-checkpoints`**. Default is zero, which means a single failed checkpoint fails the job. For exactly-once sinks, raising this to 3 or so prevents flapping under transient broker issues — but only if the sink can survive the gap, which 2PC sinks generally can.
- **`execution.checkpointing.min-pause-between-checkpoints`**. Prevents checkpoint storms when processing is bursty.

It's also worth knowing that Flink's `TwoPhaseCommitSinkFunction` requires `checkpointing.mode=EXACTLY_ONCE`. If you set it to `AT_LEAST_ONCE`, the runtime simply skips the 2PC hook entirely — `notifyCheckpointComplete()` is never called, and the sink's `commit()` never fires. The plumbing is the same; the contract is just dormant. Production teams occasionally inherit a job from a colleague who left the mode on `AT_LEAST_ONCE` and then wonder why their "exactly-once" Kafka sink is producing duplicates.

## Key Takeaways

- **2PC in Flink is a sink-side pattern**, not a generic runtime guarantee. The internal state machine is fault-tolerant; the external sink is what determines whether the contract survives.
- **Checkpoints are the prepare phase**; the *next* successful checkpoint's `notifyCheckpointComplete()` is the commit trigger. That's why exactly-once has a measurable "time-to-commit" floor equal to one checkpoint interval.
- **Stable operator UIDs are not optional** for 2PC sinks. Without them, the producer's `transactional.id` mapping breaks on restart and transactions get corrupted.
- **Not every sink should use 2PC.** JDBC sinks often do better with idempotent upserts; HTTP and other non-transactional endpoints need idempotency keys and honest documentation.
- **The protocol is robust; the configuration is fragile.** Most production incidents trace back to mismatched timeouts, missing UIDs, or external systems that silently ignore the protocol.

## Further Reading

- [Fault Tolerance in Apache Flink (official docs)](https://nightlies.apache.org/flink/flink-docs-stable/docs/learn-flink/fault-tolerance/)
- [TwoPhaseCommitSinkFunction API reference](https://nightlies.apache.org/flink/flink-docs-stable/api/java/org/apache/flink/streaming/api/functions/sink/TwoPhaseCommitSinkFunction.html)
- [Kafka SQL Connector — Exactly-Once delivery guarantees](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/table/kafka/)
- [Chandy–Lamport algorithm — Wikipedia](https://en.wikipedia.org/wiki/Chandy%E2%80%93Lamport_algorithm)
- [Kafka producer transactional.id and idempotence](https://kafka.apache.org/documentation/#producerconfigs_transactional.id)