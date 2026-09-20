---
title: "Implementing Exactly-Once Stateful Streaming with Apache Pulsar and RocksDB"
date: "2026-09-20T16:01:08.454"
draft: false
tags: ["Apache Pulsar", "RocksDB", "Exactly-Once Semantics", "Stateful Streaming", "Stream Processing", "Distributed Systems"]
description: "Learn how to build exactly-once stateful streaming pipelines using Apache Pulsar and RocksDB, covering architecture patterns, fault tolerance, and production best practices."
summary: "A deep dive into combining Apache Pulsar's messaging backbone with RocksDB's embedded state engine to achieve exactly-once semantics in stateful stream processing."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-20-implementing-exactly-once-stateful-streaming-with-apache-pulsar-and-rocksdb.svg"
  alt: "Apache Pulsar and RocksDB logos on a dark background representing exactly-once stateful streaming."
  caption: "Apache Pulsar and RocksDB powering exactly-once stateful streaming pipelines."
  relative: false
---

> **TL;DR** — Exactly-once stateful streaming is the gold standard for financial, e-commerce, and real-time analytics workloads where duplicate or lost state is unacceptable. Apache Pulsar provides the distributed log and messaging substrate with built-in message deduplication and transaction support, while RocksDB delivers a high-performance embedded key-value store for local state management. Together, they form a production-grade stack for exactly-once processing semantics that scales horizontally and survives node failures without data loss or duplication.

## Why Exactly-Once Semantics Matter

In distributed stream processing, the spectrum of delivery guarantees ranges from at-most-once through at-least-once to exactly-once. At-most-once sacrifices correctness for speed — events vanish into the void. At-least-once ensures no event is lost but introduces the headache of idempotent consumers and duplicate state updates. Exactly-once guarantees that every message is processed precisely one time, with state mutations committed atomically alongside message offsets.

For industries like financial services, real-time fraud detection, inventory management, and regulatory reporting, the cost of a duplicate debit or a missed event is measured in dollars and compliance violations. Consider a payment processing pipeline handling 50,000 transactions per second. Under at-least-once semantics with network retries, even a 0.1% duplication rate produces 50 spurious transactions per second — each requiring manual reconciliation or automated reversal logic. Exactly-once eliminates this class of bugs entirely.

The challenge is that exactly-once semantics are deceptively difficult to implement. They require atomic commits across two independent systems: the message broker (which tracks consumer offsets) and the state store (which holds aggregate computations, joins, and windowed results). If either side commits independently, the system can drift into an inconsistent state where a message is considered processed but its side effects are lost, or vice versa.

## Apache Pulsar's Streaming Foundation

Apache Pulsar separates the serving layer from the storage layer using a tiered architecture. BookKeeper (or managed ledger) handles durable log storage, while brokers serve as stateless front-ends that route reads and writes. This separation gives Pulsar several properties that are directly relevant to exactly-once processing:

- **Message deduplication at the broker level.** Producers can assign a unique `produceSequenceId` to each message, and the broker ensures that duplicates are not persisted. This eliminates the need for idempotent producers at the application level.
- **Transaction support.** Pulsar supports distributed transactions spanning multiple topics, allowing producers to batch writes and commit or abort atomically. This is the foundation for the "consume-transform-produce" pattern that underpins exactly-once stream processing.
- **Key-shared subscription mode.** Unlike traditional publish-subscribe where messages are round-robin distributed, key-shared routing ensures that all messages with the same key land on the same consumer instance. This is essential for stateful operations keyed by entity ID.
- **Managed cursor offsets.** Consumer positions are stored as managed cursors in BookKeeper, persisting independently of any broker instance. Offsets can be committed atomically with state updates through Pulsar's transaction API.

The transaction API is the critical piece. A Pulsar transaction allows a producer to write to multiple topics and a consumer to acknowledge offsets within a single atomic boundary. The `TxnID` coordinates the commit across all participants, and the managed ledger ensures durability even if individual brokers fail mid-transaction.

## RocksDB as the State Backend

RocksDB is an embedded, persistent key-value store built on the Log-Structured Merge-tree (LSM-tree) architecture originally developed at Facebook. Unlike remote state stores (Redis, DynamoDB), RocksDB runs in-process, offering microsecond-latency reads and writes without network overhead. This makes it the natural choice for stateful streaming where every millisecond counts.

Several properties make RocksDB particularly well-suited for streaming state:

1. **Column families.** RocksDB supports multiple column families within a single database instance, each with independent compaction and flush settings. A streaming application can isolate hot keys from cold keys, or separate operational state from metadata.
2. **Write-ahead log (WAL).** Every write is first persisted to a WAL before being applied to the in-memory memtable. On restart, RocksDB replays the WAL to reconstruct state, providing crash durability without requiring periodic snapshots.
3. **Incremental checkpointing.** RocksDB supports incremental checkpoints that capture only the changes since the last checkpoint, reducing the I/O amplification that full snapshots cause during state recovery.
4. **TTL and compression.** Automatic expiration of state entries via time-to-live settings eliminates the need for manual cleanup of stale windowed data. Built-in compression (Snappy, LZ4, ZSTD) keeps state footprint manageable.
5. **Optimized for SSDs.** RocksDB's flush and compaction strategies are tuned for modern NVMe SSDs, achieving sustained write throughput well above 1 GB/s on commodity hardware.

The primary trade-off is that RocksDB's LSM-tree design introduces write amplification during compaction. For streaming workloads with high write throughput, this can cause periodic latency spikes. Mitigations include tuning the `level0_file_num_compaction_trigger`, using pipelined compaction, and separating WAL and data onto different NVMe devices.

## Architecture: Combining Pulsar and RocksDB

The architectural pattern that unites Pulsar and RocksDB for exactly-once processing follows a three-phase commit loop:

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐
│  Pulsar     │────▶│  Processor   │────▶│  RocksDB State  │
│  Topic      │     │  (Consumer)  │     │  (Embedded KV)  │
│             │◀────│              │◀────│                 │
│  Txn Topic  │     │  + RocksDB   │     │  WAL + SSTables │
└─────────────┘     └──────────────┘     └─────────────────┘
        │                   │                    │
        ▼                   ▼                    ▼
   Managed Ledger      Local State Store     Checkpoint Store
```

### Phase 1: Consume and Compute

The processor (a Pulsar consumer) reads messages from a source topic using a key-shared subscription. For each message, it looks up the current state in RocksDB by key, applies the transformation logic (aggregation, join, filter), and writes the updated state back to RocksDB. This write is buffered in RocksDB's memtable and WAL but not yet visible to reads until flushed.

### Phase 2: Transactional Commit

After processing a batch of messages (or after a configurable time interval), the processor opens a Pulsar transaction. Within that transaction, it:

1. Writes the output to the result topic.
2. Commits the consumer offsets for the processed messages.
3. Flushes RocksDB state to a checkpoint location (S3, HDFS, or local disk).

All three operations are bundled into a single `TxnID`. Pulsar's transaction coordinator ensures that either all participants commit or all abort.

### Phase 3: Recovery and Rebalancing

If a processor instance fails, a replacement instance picks up the partition from the last committed transaction. It restores the RocksDB state from the most recent checkpoint and replays any WAL entries that were not yet checkpointed. Because the consumer offsets were committed atomically with the state checkpoint, there is no window where the new instance could reprocess already-handled messages.

## Implementation Walkthrough

Below is a conceptual implementation using Pulsar's Java client and RocksDB's Java bindings. This illustrates the core loop without production-hardened error handling.

### Dependencies

```xml
<dependency>
    <groupId>org.apache.pulsar</groupId>
    <artifactId>pulsar-client</artifactId>
    <version>3.2.0</version>
</dependency>
<dependency>
    <groupId>org.rocksdb</groupId>
    <artifactId>rocksdbjni</artifactId>
    <version>8.6.3</version>
</dependency>
```

### RocksDB Initialization

```java
import org.rocksdb.*;

Options options = new Options()
    .setCreateIfMissing(true)
    .setWriteBufferSize(256 * 1024 * 1024)  // 256 MB memtable
    .setMaxWriteBufferNumber(4)
    .setTargetFileSizeBase(256 * 1024 * 1024)
    .setLevelZeroFileNumCompactionTrigger(8)
    .setUseFsync(true);

// Enable WAL for crash durability
options.setWalTtlSeconds(3600)
    .setWalSizeLimitMB(512);

RocksDB stateStore = RocksDB.open(options, "/data/pulsar-state");
```

### Transactional Processing Loop

```java
import org.apache.pulsar.client.api.*;

PulsarClient client = PulsarClient.builder()
    .serviceUrl("pulsar://broker:6650")
    .build();

Consumer<byte[]> consumer = client.newConsumer()
    .topic("persistent://public/default/input-topic")
    .subscriptionName("exactly-once-sub")
    .subscriptionType(SubscriptionType.KeyShared)
    .subscriptionInitialPosition(SubscriptionInitialPosition.Earliest)
    .enableBatchIndexAcknowledgment(true)
    .subscribe();

Producer<byte[]> producer = client.newProducer()
    .topic("persistent://public/default/output-topic")
    .enableBatching(false)
    .create();

// Processing loop with transaction boundaries
while (true) {
    Message<byte[]> msg = consumer.receive(100, TimeUnit.MILLISECONDS);
    if (msg == null) {
        continue;
    }

    try {
        // Step 1: Read state from RocksDB
        String key = new String(msg.getKey().getBytes(StandardCharsets.UTF_8));
        byte[] currentState = stateStore.get(key.getBytes(StandardCharsets.UTF_8));

        // Step 2: Apply business logic
        byte[] newState = computeUpdate(currentState, msg.getData());
        stateStore.put(key.getBytes(StandardCharsets.UTF_8), newState);

        // Step 3: Produce result within transaction
        producer.newMessage()
            .key(key)
            .value(newState)
            .sendAsync();

        // Step 4: Commit transaction atomically
        producer.flush();
        consumer.acknowledgeAsync(msg.getMessageId());

    } catch (Exception e) {
        consumer.negativeAcknowledge(msg.getMessageId());
        // RocksDB WAL ensures state is recoverable on restart
    }
}
```

### Production-Grade Transaction Pattern

The simplified loop above illustrates the concept but lacks the atomicity guarantees of Pulsar's transaction API. In production, you should use `TransactionBuilder` to create an explicit transaction boundary:

```java
import org.apache.pulsar.client.api.transaction.TxnID;
import org.apache.pulsar.client.api.transaction.TransactionBuilder;

TransactionBuilder txnBuilder = client.newTransaction()
    .withTransactionTimeout(60, TimeUnit.SECONDS)
    .withMaxTransactionTimeout(300, TimeUnit.SECONDS);

TxnID txnID = txnBuilder.build().get();

// Within the transaction:
producer.newMessage(txnID)
    .key(key)
    .value(newState)
    .send();

consumer.acknowledge(msg.getMessageId(), txnID);

// Commit atomically
txnID.commit().get();
```

The `commit()` call coordinates across the producer and consumer, ensuring that the output message is visible only when the offset is also committed. If the commit fails, both sides roll back, and the message is reprocessed on the next cycle.

## Patterns in Production

### Checkpoint and Restore

Periodic checkpointing of the RocksDB state to a durable store (S3, GCS, HDFS) is essential for fast recovery. The checkpoint frequency should balance recovery time against I/O cost. A common pattern is to checkpoint every 5,000 processed messages or every 60 seconds, whichever comes first. Pulsar's transaction commit can trigger the checkpoint write, ensuring that the checkpoint is only durable if the transaction commits.

```java
// Trigger RocksDB checkpoint on transaction commit
CheckpointOptions opts = new CheckpointOptions().setVerifyChecksum(false);
stateStore.createCheckpoint("/checkpoints/txn-" + txnID.toString(), opts);
```

### State TTL and Compaction

Windowed aggregations produce state that is only valid for a bounded period. Setting TTL on RocksDB column families prevents unbounded state growth:

```java
ColumnFamilyOptions cfOptions = new ColumnFamilyOptions()
    .setPeriodicCompactionSeconds(86400)
    .setCompactionFilterFactory(new TTLCompactionFilter(3600)); // 1-hour TTL
```

### Scaling with Key-Shared Subscriptions

Horizontal scaling is achieved by adding more consumer instances under the same key-shared subscription. Pulsar routes messages with the same key to the same consumer, ensuring that each key's state is managed by exactly one instance. When a new instance joins, Pulsar rebalances partitions dynamically, and the receiving instance restores its partition's state from the latest checkpoint.

### Monitoring and Observability

Production deployments should expose metrics from both Pulsar and RocksDB:

- **Pulsar metrics**: transaction commit latency, message backlog, consumer lag, transaction abort rate.
- **RocksDB metrics**: write amplification ratio, memtable flush rate, compaction pending, stall conditions.

Grafana dashboards that overlay these metrics reveal correlations between RocksDB compaction spikes and Pulsar transaction timeouts — a common failure mode when the state store falls behind the message rate.

## Key Takeaways

- **Exactly-once requires atomic commits across message offsets and state.** Pulsar's transaction API and RocksDB's WAL together provide the necessary durability guarantees without relying on idempotent producers or consumers.
- **Key-shared subscriptions are essential for stateful processing.** They ensure that all events for a given entity are processed by the same consumer, maintaining state consistency without distributed locking.
- **RocksDB's embedded nature eliminates network hops for state access.** The trade-off is write amplification during compaction, which must be tuned for the specific workload's write-to-read ratio.
- **Checkpointing frequency determines recovery time.** More frequent checkpoints reduce the replay window after a failure but increase I/O overhead. The optimal frequency depends on your acceptable recovery point objective (RPO).
- **Monitoring RocksDB compaction metrics alongside Pulsar transaction latency is critical.** Compaction stalls in RocksDB directly cause transaction timeouts in Pulsar, cascading into processing delays.
- **Test failure scenarios explicitly.** Simulate broker failures, state store corruption, and network partitions to validate that your exactly-once guarantees hold under adverse conditions, not just nominal operation.

## Further Reading

- [Apache Pulsar Transactions](https://pulsar.apache.org/docs/en/transactions/) — Official documentation on Pulsar's distributed transaction API, including the transaction coordinator architecture and usage patterns.
- [RocksDB Wiki](https://github.com/facebook/rocksdb/wiki) — Comprehensive documentation on RocksDB configuration, tuning, and compaction strategies for production workloads.
- [Pulsar Functions Stateful Processing](https://pulsar.apache.org/docs/en/functions-state/) — How Pulsar's built-in functions framework uses RocksDB for stateful processing, with examples and configuration options.
- [Exactly-Once Semantics in Stream Processing](https://martin.kleppmann.com/2017/10/11/exactly-once-semantics-are-impossible-and-how-theyre-ok.html) — Martin Kleppmann's seminal analysis of what exactly-once really means in distributed systems and the trade-offs involved.
- [Pulsar Managed Ledger Architecture](https://pulsar.apache.org/docs/en/architecture-managed-ledger/) — Deep dive into Pulsar's storage layer, explaining how managed ledgers provide durability and how cursors track consumer progress.
- [RocksDB Tuning Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide) — Practical tuning recommendations for different workload profiles, including write-heavy streaming scenarios.
- [Apache Pulsar Key-Shared Subscription](https://pulsar.apache.org/docs/en/concepts-messaging/#key-shared-subscription) — Detailed explanation of the key-shared subscription mode and how it enables stateful processing at scale.
