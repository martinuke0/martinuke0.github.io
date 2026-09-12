---
title: "Implementing Debezium CDC Pipelines: Exactly-Once State, Schema Evolution, and Backfills"
date: "2026-09-12T08:01:28.895"
draft: false
tags: ["debezium", "cdc", "kafka", "exactly-once", "schema-evolution", "data-engineering"]
description: "A production-focused guide to building Debezium CDC pipelines with exactly-once semantics, automated schema evolution, and reliable backfill strategies."
summary: "Learn how to implement Debezium-based change data capture pipelines that guarantee exactly-once state, handle schema evolution gracefully, and execute reliable backfills at scale."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-implementing-debezium-cdc-pipelines-exactly-once-state-schema-evolution-and-backfills.svg"
  alt: "Debezium CDC pipeline architecture diagram showing data flow between databases, Kafka, and sinks"
  caption: ""
  relative: false
---

> **TL;DR** — Building production-grade Debezium CDC pipelines requires more than wiring a connector to Kafka. You need exactly-once semantics via Kafka Transactions and idempotent sinks, a schema registry strategy that handles evolving source tables without breaking consumers, and a backfill framework that reconciles snapshot data with streaming changes. This post walks through all three with concrete patterns and real production tradeoffs.

Change data capture has become the backbone of modern data platforms. Instead of polling databases or running brittle batch jobs, teams use Debezium to stream every insert, update, and delete as an immutable event log. But moving from a working prototype to a pipeline you can trust at 3 AM on a Saturday is a different challenge entirely. The hard problems are exactly-once delivery, schema evolution, and backfills — and they compound on each other in ways that surprise most teams the first time around.

## Architecture: The CDC Pipeline in Production

A typical Debezium-based pipeline has four layers. The **source database** emits WAL (Write-Ahead Log) entries. The **Debezium connector** reads the WAL and publishes change events to Apache Kafka. The **Kafka Streams or ksqlDB layer** transforms, filters, and enriches those events. Finally, the **sink** materializes the data into a downstream system — a data warehouse, a search index, or a read-optimized database.

```
[ PostgreSQL / MySQL ]
        |
   [ Debezium Connector ]
        |
   [ Apache Kafka ]
        |
   [ Kafka Streams / ksqlDB ]
        |
   [ Sink: Snowflake / Elasticsearch / PostgreSQL ]
```

Each layer introduces failure modes. The connector can lose its position in the WAL if the offsets topic is corrupted. Kafka brokers can rebalance and cause transient pauses. The stream processor can crash mid-transformation. And the sink can receive duplicates or out-of-order records. The rest of this post addresses how to harden each of these layers against real-world failure.

## Exactly-Once State Across the Pipeline

Exactly-once semantics (EOS) in a CDC pipeline is not a single switch you flip. It is a property that must be enforced at every hop. Debezium itself guarantees *at-least-once* delivery — it will not lose events, but it can deliver them more than once if the connector restarts before committing offsets.

### Kafka Transactions for End-to-End EOS

Starting with Kafka 0.11, producers and consumers support transactional messaging. The key insight is that you can atomically write output records to Kafka *and* commit the consumer offsets in the same transaction. If the transaction succeeds, both the output and the offsets are visible. If it fails, neither is.

In Kafka Streams, this is enabled by setting `processing.guarantee` to `exactly_once_v2`:

```properties
application.id=cdc-enricher
processing.guarantee=exactly_once_v2
commit.interval.ms=100
```

With `exactly_once_v2`, Kafka Streams uses the transactional producer under the hood. Every processing batch is wrapped in a transaction that includes the output topic writes and the offset commits. If the application crashes, the transaction is aborted and the offsets are not advanced — so the records are reprocessed from the last committed position.

The critical configuration detail is `commit.interval.ms`. Setting it too low increases transaction overhead; setting it too high increases the replay window on failure. For most production pipelines, 100–500 ms is the sweet spot.

### Idempotent Sinks

Kafka transactions only cover the Kafka-to-Kafka path. When writing to an external sink — say, a Snowflake table or an Elasticsearch index — you need idempotency on the consumer side. The standard pattern is to use the source table's primary key as the record key and to upsert in the sink.

```python
# Pseudocode for an idempotent sink writer
def write_to_sink(record):
    key = record.key()        # e.g., "user:42"
    payload = record.value()  # full row after transformation

    # Upsert using the key — duplicates are silently ignored
    sink.upsert(
        table="users",
        key=key,
        values=payload,
        conflict_column="id"
    )
```

For systems that do not support upsert natively, you can write to a staging table and merge. Snowflake's `MERGE` statement, BigQuery's partitioned table with `INSERT` and `ON CONFLICT`, and Elasticsearch's document ID all provide this guarantee.

### The Exactly-Once Illusion with Exactly-Once Bridges

There is a subtlety most teams miss: exactly-once in Kafka does not automatically mean exactly-once end-to-end. If your Kafka Streams application writes to Kafka transactionally but your sink consumer is not idempotent, you still get duplicates in the final system. The bridge between Kafka EOS and sink EOS requires you to either:

- Use a connector that supports EOS (e.g., the Confluent S3 Sink Connector with `exactly.once=true`).
- Implement a two-phase commit between Kafka and the sink.
- Design the sink to be naturally idempotent via upserts or deduplication windows.

The third option is the most common in practice because it avoids the complexity of distributed transactions across heterogeneous systems.

## Schema Evolution Without Breaking Consumers

Schema evolution is the silent killer of CDC pipelines. A source developer adds a column, renames a field, or changes a type — and suddenly the downstream consumer throws a deserialization error and the pipeline stalls.

### The Schema Registry as the Single Source of Truth

Confluent Schema Registry (or an equivalent like Apicurio) should sit between the Debezium connector and the Kafka topic. Debezium produces Avro-encoded change events, and the serializer registers each schema version automatically.

```properties
# Debezium connector configuration
value.converter=io.confluent.connect.avro.AvroConverter
value.converter.schema.registry.url=http://schema-registry:8081
key.converter=io.confluent.connect.avro.AvroConverter
key.converter.schema.registry.url=http://schema-registry:8081
```

Every time a source table's schema changes, Debezium emits a new schema version. The registry enforces compatibility rules — `BACKWARD`, `FORWARD`, or `FULL` — so that consumers are never caught off guard.

### Compatibility Modes and When to Use Them

- **`BACKWARD`**: New schemas can read old data. Use this when consumers are upgraded *after* producers. This is the safest default for most CDC pipelines.
- **`FORWARD`**: Old schemas can read new data. Use when consumers are upgraded before producers.
- **`FULL`**: Both backward and forward compatible. The strictest mode, useful when you cannot control deployment order.

```json
// Schema registry compatibility check
POST /config/cdc-value
{
  "compatibility": "BACKWARD"
}
```

### Handling Common Schema Changes

**Adding a column.** This is the easiest case. With `BACKWARD` compatibility, new events include the new field with a default value, and old consumers simply ignore the unknown field. Avro's schema resolution handles this automatically.

**Renaming a column.** This is a breaking change in Avro because the field name is part of the schema identity. The safe approach is to add a new column, backfill it from the old one, and deprecate the old column over two releases.

**Changing a field type.** Converting a `string` to an `int` is not supported by Avro's resolution rules. You must handle this with a custom transformation in Kafka Streams:

```java
// Kafka Streams transformation for type migration
KStream<String, GenericRecord> migrated = source.mapValues(record -> {
    GenericRecord newRecord = new GenericData.Record(newSchema);
    // Convert string "42" to int 42
    String oldValue = record.get("user_id").toString();
    newRecord.put("user_id", Integer.parseInt(oldValue));
    // Copy all other fields unchanged
    for (Schema.Field field : newSchema.fields()) {
        if (!field.name().equals("user_id")) {
            newRecord.put(field.name(), record.get(field.name()));
        }
    }
    return newRecord;
});
```

**Dropping a column.** With `BACKWARD` compatibility, consumers that still reference the old schema will receive a default value for the missing field. This is safe only if you have verified that all consumers handle the default correctly.

### The Tombstone Problem

When a row is deleted in the source database, Debezium emits a delete event with a tombstone value (null). Kafka's log compaction will remove the key if the value is null, which is correct behavior — but only if your consumer expects it. If your sink is a key-value store and receives a tombstone, it must delete the corresponding key.

```python
def handle_delete(record):
    if record.value() is None:
        sink.delete(table="users", key=record.key())
    else:
        sink.upsert(table="users", key=record.key(), values=record.value())
```

## Backfills: Reconciling Snapshots with Streaming Changes

Backfills are the most operationally dangerous part of a CDC pipeline. When a new consumer joins the system, or when you need to rebuild a materialized view, you must take a snapshot of the entire source table and then apply all changes that occurred during the snapshot. If the snapshot and the change stream overlap, you get duplicates or inconsistencies.

### The Snapshot-Then-Stream Pattern

The standard approach, as described in the [Debezium documentation](https://debezium.io/documentation/reference/stable/connectors/postgresql.html#postgresql-snapshotting), is:

1. **Lock the tables** (or use a consistent read snapshot in PostgreSQL) and export the full contents.
2. **Record the LSN (Log Sequence Number)** or binlog position at the end of the snapshot.
3. **Start the Kafka connector** from that position so it only captures changes after the snapshot.

```sql
-- PostgreSQL: Get the LSN after the snapshot
SELECT pg_current_wal_lsn();
-- Use this LSN as the snapshot.offset in the connector config
```

The connector configuration for a snapshot-based backfill looks like this:

```json
{
  "name": "inventory-connector",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "pg-host",
    "database.server.name": "dbserver1",
    "table.include.list": "public.inventory",
    "snapshot.mode": "initial",
    "snapshot.locking.mode": "none",
    "offset.storage": "org.apache.kafka.connect.storage.KafkaOffsetBackingStore",
    "offset.storage.kafka.topic": "debezium-offsets",
    "offset.flush.interval.ms": 0
  }
}
```

Setting `snapshot.mode` to `initial` triggers a full table scan on first run. Setting `snapshot.locking.mode` to `none` uses a consistent read snapshot in PostgreSQL, which avoids table locks but requires `REPEATABLE READ` or `SERIALIZABLE` isolation.

### The Problem with Concurrent Changes

The fundamental challenge is that while the snapshot is running, new changes are being written to the WAL. If a row is updated during the snapshot, the snapshot might capture the old version and the WAL might capture the new version — resulting in the consumer seeing the row twice.

Debezium handles this by recording the LSN at the start of the snapshot. After the snapshot completes, the connector emits a `snapshot.complete` event and then begins streaming from that LSN. The consumer must deduplicate: if it sees a row with a timestamp older than the snapshot's LSN timestamp, it discards it.

### Incremental Backfills for Large Tables

For tables with hundreds of millions of rows, a single snapshot can take hours and put unacceptable load on the source database. The alternative is an **incremental backfill**:

1. **Create a watermark** — a timestamp or ID that marks the starting point.
2. **Copy data in batches** using a `WHERE created_at > watermark` query.
3. **Apply changes** from the CDC stream starting at the watermark's corresponding LSN.

```python
def incremental_backfill(table, batch_size=10000):
    watermark = get_last_processed_timestamp()
    offset = 0

    while True:
        batch = db.query(
            f"SELECT * FROM {table} WHERE updated_at > %s ORDER BY id LIMIT %s",
            watermark, batch_size
        )
        if not batch:
            break

        for row in batch:
            produce_to_kafka(topic="backfill", key=row.id, value=row)

        offset += len(batch)
        watermark = batch[-1].updated_at

    # Now start the CDC consumer from the LSN corresponding to watermark
    start_connector_from_lsn(watermark_lsn)
```

This approach trades completeness for speed and reduced source load. It is the right choice when the downstream system can tolerate a brief period where some data is missing from the snapshot phase.

### Validating Backfill Correctness

After a backfill completes, you must verify that the sink matches the source. The standard validation query is a row-count and checksum comparison:

```sql
-- Source
SELECT COUNT(*), MD5(CAST((SELECT * FROM users ORDER BY id) AS TEXT))
FROM users;

-- Sink (e.g., Snowflake)
SELECT COUNT(*), MD5(CAST((SELECT * FROM users ORDER BY id) AS TEXT))
FROM users;
```

If the checksums match, the backfill is correct. If they do not, you need to identify the divergent rows and replay the CDC events for those specific keys.

## Patterns in Production: Lessons from the Trenches

### Offset Management Is Everything

The Debezium connector stores its position in the Kafka `__consumer_offsets` topic. If this topic is deleted or corrupted, the connector loses its place and either reprocesses the entire WAL (causing a massive backfill) or skips events (causing data loss). Back up the offsets topic and monitor its size.

### Monitor LAG, Not Just Throughput

A CDC pipeline can be ingesting millions of events per second while the source database falls further behind. Monitor the **replication lag** — the difference between the current WAL position and the connector's committed offset. Tools like [Burrow](https://github.com/linkedin/Burrow) or Confluent's Kafka Lag Exporter can surface this metric.

### Use Dead Letter Queues for Poison Pills

When a malformed event causes a deserialization failure, the default behavior is to fail the entire task. Configure a dead letter queue so that bad records are quarantined instead of blocking the pipeline:

```properties
errors.tolerance=all
errors.deadletterqueue.topic.name=cdc-dlq
errors.deadletterqueue.context.headers.enable=true
```

## Key Takeaways

- **Exactly-once is a system property, not a connector feature.** You need Kafka transactions, idempotent sinks, and careful offset management working together to achieve true EOS end-to-end.
- **Schema Registry with `BACKWARD` compatibility is the minimum viable strategy.** It lets producers evolve independently while keeping consumers safe. Renames and type changes still require manual migration paths.
- **Backfills are where CDC pipelines break.** Always use a snapshot-then-stream pattern with LSN-based cutover, and validate with checksums before decommissioning the old data pipeline.
- **Incremental backfills beat monolithic ones for large tables.** Batch by timestamp or ID, and overlap with the CDC stream to minimize the window of inconsistency.
- **Monitor replication lag as a first-class metric.** Throughput alone tells you nothing about whether the pipeline is keeping up with the source.

## Further Reading

- [Debezium Documentation — Snapshotting](https://debezium.io/documentation/reference/stable/connectors/postgresql.html#postgresql-snapshotting)
- [Confluent Schema Registry Compatibility Guide](https://docs.confluent.io/platform/current/schema-registry/serdes-develop/compatibilty.html)
- [Apache Kafka — Exactly Once Semantics](https://kafka.apache.org/documentation/#design_exactly_once)
- [Confluent — Designing Event-Driven Systems](https://www.confluent.io/blog/event-driven-microservices-ep-6-designing-for-data-management/)
- [Debezium — MySQL Connector Configuration](https://debezium.io/documentation/reference/stable/connectors/mysql.html)
- [Kafka Streams Exactly-Once V2](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)
- [Victoria Metrics — Monitoring Kafka Consumer Lag](https://docs.victoriametrics.com/solutions/kafka-monitoring/)
