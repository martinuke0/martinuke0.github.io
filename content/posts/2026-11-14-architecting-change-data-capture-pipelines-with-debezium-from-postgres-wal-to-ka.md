---
title: "Architecting Change Data Capture Pipelines with Debezium: From Postgres WAL to Kafka Topics"
date: "2026-11-14T22:01:47.666"
draft: false
tags: ["debezium", "postgres", "kafka", "change-data-capture", "data-engineering"]
description: "A practical guide to building Change Data Capture pipelines with Debezium, streaming PostgreSQL WAL events to Kafka topics with exactly-once semantics and schema evolution."
summary: "From PostgreSQL write-ahead logs to Kafka topics: how to build reliable, schema-aware CDC pipelines with Debezium."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-14-architecting-change-data-capture-pipelines-with-debezium-from-postgres-wal-to-ka.svg"
  alt: "Debezium CDC pipeline flowing from PostgreSQL to Kafka"
  caption: ""
  relative: false
---

> **TL;DR** — Change Data Capture from PostgreSQL's WAL to Kafka via Debezium gives you real-time, schema-aware event streams without polling. By reading the WAL through the Debezium connector, you capture every INSERT, UPDATE, and DELETE as an Avro/JSON record on a Kafka topic, enabling downstream consumers to react instantly. Combined with Kafka Connect and a Schema Registry, you get exactly-once semantics, backpressure resilience, and a decoupled architecture that scales from a single service to enterprise-wide data mesh domains.

Change Data Capture (CDC) has become the nervous system of modern data architectures. Whether you're synchronizing a data warehouse, powering a search index, or building event-driven microservices, the ability to react to data changes as they happen—rather than on a schedule—is a competitive imperative. PostgreSQL's write-ahead log (WAL) is the source of truth for all modifications, but extracting that stream efficiently and reliably requires the right tooling. Debezium, built on top of Kafka Connect, provides a battle-tested connector framework that reads the WAL, normalizes change events, and publishes them to Kafka topics. In this post, we'll walk through the architecture, configuration, and production patterns for wiring Postgres WAL changes to Kafka, and highlight the pitfalls and guardrails that separate a fragile prototype from a robust pipeline.

## Understanding Change Data Capture and the Postgres WAL

At its core, CDC is the practice of detecting and propagating data changes in real time. Traditional extract-transform-load (ETL) pipelines rely on periodic snapshots or trigger-based mechanisms, both of which introduce latency, increased load on the source database, and fragile state management. Log-based CDC, by contrast, reads the native transaction log of the database, which records every row-level modification before it becomes visible to applications.

PostgreSQL's write-ahead log (WAL) is the mechanism by which the database ensures durability and crash recovery. Every INSERT, UPDATE, DELETE, and schema change is first written to the WAL before the data page is modified. PostgreSQL exposes this log through a feature called **logical decoding**, which allows plugins to subscribe to a logical replication slot and receive changes in a structured format (typically JSON or Avro) rather than raw WAL bytes. The `pgoutput` and `test_decoding` plugins are the most common choices for logical decoding, and Debezium leverages `test_decoding` internally to translate WAL events into change records.

The advantages of WAL-based CDC are manifold:
- **Low overhead**: Reading the log does not require row-level locking or trigger execution, minimizing impact on OLTP workloads.
- **Completeness**: Every change is captured, including bulk operations that might bypass triggers.
- **Decoupling**: The extraction logic runs outside the database, leaving the source free to serve application traffic.

However, operating directly on the WAL requires managing replication slots, handling failover, and understanding PostgreSQL's storage internals. This is where Debezium abstracts the complexity while giving you fine-grained control over the stream.

## Debezium Architecture: How It Works Under the Hood

Debezium is not a standalone database reader; it is a set of Kafka Connect connectors that plug into the Kafka Connect runtime. When you deploy a Debezium PostgreSQL connector, the following sequence occurs:

1. **Connector initialization**: The connector establishes a connection to the target database, requests a logical replication slot (creating one if none exists), and performs an initial *snapshot* if configured to do so. The snapshot captures the current state of all tables, which is published to Kafka before the ongoing stream begins.

2. **WAL streaming**: After the snapshot, the connector enters *stream* mode. It polls the logical replication slot for new WAL entries, decodes them using the `test_decoding` output plugin, and translates each event into a structured record containing:
   - **source**: metadata about the origin (database name, server ID, LSN position, transaction ID).
   - **payload**: the actual change data, including the old and new row values.
   - **op**: the operation type (`c`reate, `u`pdate, `d`elete).
   - **ts_ms**: server-side timestamp.

3. **Record publication**: Each decoded record is written to a Kafka topic named after the source table (or a configurable prefix). The key is typically the table's primary key, ensuring that downstream consumers can key by that primary key for exactly-once processing.

4. **Connector lifecycle**: The connector can be paused, resumed, or restarted without losing its position in the WAL stream, thanks to the replication slot's LSN tracking. If the connector crashes, it resumes from the last committed LSN upon restart.

A critical configuration knob is `database.history.kafka.bootstrap.servers`, which tells Debezium where to store connector metadata (schema changes, snapshot offsets) in Kafka. This history enables exactly-once delivery even when connectors are rebalanced across Kafka Connect workers.

### Subsection: Connectors, Transformations, and the Kafka Connect Layer

Kafka Connect provides the runtime, but the real power emerges when you combine connectors with **single message transforms (SMTs)**. Common transformations in a CDC pipeline include:

- **`unwrap`**: Flattens the Debezium envelope, emitting only the change event payload. This is useful when you want clean JSON records without the `source` wrapper.
- **`rename`**: Renames fields or flattens nested structures, helpful when migrating between schema formats.
- **`extract`**: Extracts a nested field into a top-level key, often used when separating source metadata from the event data.

For example, if you're piping changes into a stream processing framework that expects flat records, wrapping the output with `unwrap` removes the Debezium-specific nesting and gives you a pure change event. However, you lose the `source` metadata, which may be needed for routing or auditing—so the choice depends on your downstream contract.

### Subsection: Debezium Plugins and Snapshot/Stream Modes

Debezium supports two primary operational modes:

- **Snapshot mode**: Controlled by `snapshot.mode` (values: `initial`, `initial_only`, `never`). `initial` takes a one-time snapshot of each table and then streams changes. `initial_only` snapshots only and stops. `never` skips the snapshot entirely, assuming the consumer already has the data or will populate it via another means.
- **Explicit table filtering**: Via `table.include.list` and `table.exclude.list`, you can restrict which tables are captured, reducing bandwidth and avoiding capturing internal or temporary tables.

For production workloads, `initial` snapshot on first deployment, followed by continuous streaming, is the most common pattern. Subsequent connector restarts resume from the last LSN, avoiding another full snapshot unless the replication slot was dropped.

## Architecture Pattern: Streaming CDC from WAL to Kafka Topics

With the fundamentals in place, let's examine a production-ready architecture for streaming Postgres WAL changes to Kafka. The pattern below assumes you want reliable, schema-aware events that downstream systems can consume without custom parsing logic.

### Schema Evolution with Kafka Schema Registry

One of the most common failure points in CDC pipelines is schema drift. When a `ALTER TABLE` adds a nullable column or changes a default, the shape of the emitted record changes. Without a schema registry, downstream consumers break silently.

Debezium integrates natively with the **Kafka Schema Registry**. By setting `database.history.kafka.bootstrap.servers` and `schema.registry.url`, the connector registers Avro schemas for each table's schema change events. Every time a DDL statement executes, Debezium forwards the new table schema to the registry, and the published records carry a schema ID that consumers can fetch and validate.

The default Avro schema includes all columns, their types, and nullability. When a column is added, the schema is registered as a new version, and older consumers continue to read the previous version until they upgrade. This backward/forward compatibility is what makes CDC at scale viable.

### Connector Configuration for Exactly-Once Semantics

To achieve exactly-once delivery semantics, you need two pieces: idempotent consumers and Kafka transactions. Debezium's connector configuration supports this out of the box when Kafka Connect is running with `transactional.id` set and the connector's `transactional` flag is enabled.

Key props for a robust Postgres CDC connector:

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "tasks.max": "1",
  "database.hostname": "postgres-prod.example.com",
  "database.port": "5432",
  "database.user": "cdc_user",
  "database.password": "REDACTED",
  "database.dbname": "production",
  "plugin.name": "pgoutput",
  "slot.name": "debezium_slot_prod",
  "publication.autocreate.mode": "positive",
  "table.include.list": "public.orders,public.customers,public.inventory",
  "key.converter": "io.confluent.connect.avro.AvroConverter",
  "key.converter.schema.registry.url": "http://schema-registry:8081",
  "value.converter": "io.confluent.connect.avro.AvroConverter",
  "value.converter.schema.registry.url": "http://schema-registry:8081",
  "schema.registry.url": "http://schema-registry:8081",
  "database.history.kafka.bootstrap.servers": "kafka-broker:9092",
  "schema.history.kafka.bootstrap.servers": "kafka-broker:9092",
  "database.history.kafka.topic": "dbhistory.production",
  "transforms": "unwrap",
  "transforms.unwrap.type": "io.debezium.transforms.UnwrapFromEnvelope"
}
```

Notice the `slot.name`: this must be unique per database. If you run multiple connectors against the same PostgreSQL instance, each needs its own slot, or you'll encounter slot name conflicts that cause the connector to fail on startup.

### Resource Isolation and Connector Per Database

In a microservices or data mesh architecture, you'll often have multiple databases or even multiple PostgreSQL clusters. Debezium's connector-per-database pattern—one Kafka Connect worker (or container) per database—provides clean isolation. Each connector manages its own replication slot, schema history, and topic namespace. If you use a shared Kafka cluster, topic prefixes (`topic.prefix` or `topic.suffix`) can disambiguate events from different sources.

For example, setting `topic.prefix = "cdc."` will produce topics like `cdc.orders`, `cdc.customers`, ensuring that a consumer listening to all CDC topics can filter by prefix without name collisions.

## Common Failure Modes and Production Guardrails

Even with a well-designed architecture, CDC pipelines encounter operational friction. Here are the most frequent failure modes and how to mitigate them.

### WAL Slot Exhaustion and Slot Name Conflicts

PostgreSQL has a finite number of replication slots (`max_replication_slots`). If a Debezium connector is stopped without properly deleting its slot, or if the connector restarts and finds the slot already exists but in an inconsistent state, the connector may block or throw errors. Mitigation:
- Monitor `pg_replication_slots` and set alerts when usage exceeds 80%.
- Use `slot.drop.method = graceful` in the connector config so that stopping the connector cleanly drops the slot.
- For long-running pipelines, consider rotating slot names or using per-environment clusters.

### Connector Restart Loops and LSN Gaps

If the PostgreSQL server is restarted or the WAL is truncated (e.g., via `pg_switch_wal`), the replication slot may point to an LSN that no longer exists in the current WAL. The connector will then attempt to re-snapshot, which can be expensive for large databases. To avoid this:
- Keep `max_wal_size` at a reasonable size (e.g., 1GB) and archive old WALs to disk rather than deleting them immediately.
- Use `pg_wal_keep_segments` or the newer `wal_keep_size` to retain enough history for connector restarts.
- Set `snapshot.mode = initial` only on first deployment; subsequent restarts will resume from the last committed LSN.

### Schema Evolution Breaks

When a DDL change adds a `NOT NULL` column without a default, the Debezium connector may emit records that violate the registered Avro schema, causing deserialization errors downstream. Mitigation:
- Always add new columns with `DEFAULT` or `NULL` initially, then backfill data and alter the column to `NOT NULL` in a separate migration step.
- Use the Schema Registry's compatibility mode (e.g., `BACKWARD`, `FORWARD`, `FULL`) to enforce schema evolution rules.
- Subscribe to Debezium's `schema.change` topic (automatically created) to monitor schema changes in real time and alert on incompatible DDL.

### Security and Credential Management

Hardcoding database passwords in connector configs is a security anti-pattern, especially in Kubernetes or dynamic infrastructure. Use:
- **Kubernetes secrets** mounted as environment variables or volume files.
- **HashiCorp Vault** integration via the `secrets.provider` config (Debezium supports Vault's KV v2 engine).
- **IAM-based authentication** for PostgreSQL (e.g., `pg_pam` or cloud-native IAM auth) to avoid long-lived passwords.

### Monitoring and Alerting

Debezium exposes a rich set of **JMX metrics** and **Prometheus metrics**. Key metrics to watch:
- `debezium.connector.postgresql.records.per.second`: throughput health.
- `debezium.connector.postgresql.errors`: count of decoding or publication errors.
- `debezium.connector.postgresql.lsn.current` vs `lsn.last.commit`: lag detection.
- Connect worker process CPU and memory usage.

Set up alerts on sustained throughput drops, error rate spikes, or LSN lag exceeding a threshold (e.g., 5 minutes behind). Tools like Confluent Control Center, Grafana with the Debezium exporter, or Kubernetes-based Prometheus operators can surface these metrics.

## Key Takeaways

- **Log-based CDC reads PostgreSQL's WAL via logical decoding**, providing a complete, low-overhead stream of row-level changes without triggers or polling.
- **Debezium abstracts the WAL reading complexity** into a Kafka Connect connector that normalizes events, manages replication slots, and integrates with Schema Registry for schema evolution.
- **Exactly-once semantics are achievable** when Debezium runs on Kafka Connect with transactional.id configured, combined with idempotent downstream consumers.
- **Schema Registry integration** is essential for production CDC: it enables backward/forward-compatible Avro schemas, so DDL changes don't break downstream consumers.
- **Replication slot management** is a common pitfall: monitor slot usage, use graceful drop on connector stop, and ensure unique slot names per connector.
- **Security and credential hygiene** should be enforced via Kubernetes secrets or Vault, never hardcoded in connector configs.
- **Monitoring metrics** (throughput, error rate, LSN lag) are your early-warning system for pipeline health; alert on sustained deviations.

## Further Reading

- [Debezium PostgreSQL connector documentation](https://debezium.io/documentation/reference/connectors/postgresql.html)
- [Apache Kafka Connect documentation](https://kafka.apache.org/documentation/#connect)
- [PostgreSQL WAL and logical replication](https://www.postgresql.org/docs/current/wal.html)
- [Kafka Schema Registry guide](https://docs.confluent.io/platform/current/schema-registry/index.html)
- [Debezium design patterns and anti-patterns](https://debezium.io/blog/2

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
