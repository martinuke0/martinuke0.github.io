---
title: "Architecting Change Data Capture with Debezium and PostgreSQL: A Production Pipeline Walkthrough"
date: "2026-09-07T16:58:11.281"
draft: false
tags: ["debezium", "postgresql", "change-data-capture", "kafka", "data-engineering", "event-driven"]
description: "A production-focused walkthrough of CDC with Debezium and Postgres, covering WAL mechanics, connector config, Kafka topics, and backpressure patterns."
summary: "How to design a reliable CDC pipeline from PostgreSQL to downstream systems using Debezium — covering WAL internals, connector configuration, schema evolution, and the failure modes you'll hit in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-architecting-change-data-capture-with-debezium-and-postgresql-a-production-pipeline-walkthrough.svg"
  alt: "Diagram showing PostgreSQL WAL flowing through Debezium into Kafka topics and downstream sinks."
  caption: ""
  relative: false
---

> **TL;DR** — Change Data Capture with Debezium turns PostgreSQL's write-ahead log into a durable stream of row-level events that downstream systems can consume in near real time. A production-grade CDC pipeline needs careful attention to the replication slot, the connector configuration, topic naming, idempotent consumers, and schema evolution — skip any of those and you'll get either silent data loss or a noisy downstream.

There's a particular kind of bug that only shows up after a Postgres primary has been running for a few months: the analytics dashboard quietly drifts from the operational database, the search index falls behind, and nobody notices until a customer complains. Polling-based replication — running a `SELECT` every few seconds against a `updated_at` timestamp — eventually fails because someone forgets to add the column to a new table, or the poll interval doesn't survive a traffic spike.

Change Data Capture (CDC) solves this by reading the database's own transaction log. In PostgreSQL, that log is the Write-Ahead Log (WAL), and [Debezium](https://debezium.io/documentation/) is the de facto engine for turning that log into a stream of structured events. This post walks through how to design a CDC pipeline that survives the things that kill naive ones: schema changes, rebalances, backpressure, and the inevitable primary failover.

## How Postgres WAL Becomes a Stream

Before configuring anything, it's worth understanding what Debezium actually reads. PostgreSQL stores every committed change — inserts, updates, deletes, even DDL — in the WAL before it's applied to the heap. The logical decoding layer, introduced in 9.4 and matured over the years, exposes those changes as a stream of messages through a *replication slot*.

A logical replication slot is a server-side cursor that tracks how far a consumer has read through the WAL. The Postgres primary will retain WAL segments until every slot has consumed them — which is both a feature (durability) and a footgun (an idle slot will eventually fill your disk). The Debezium Postgres connector creates one slot per connector, typically named after the connector's logical name.

Each WAL record produces an event with this shape:

- **Before image** — the row's state before the change (or `null` for inserts).
- **After image** — the row's state after the change (or `null` for deletes).
- **Operation** — `c` (create/read), `u` (update), `d` (delete), `r` (initial snapshot read).
- **Transaction metadata** — `xid` and `lsn`, which let you reason about ordering and boundaries.

The connector publishes these as JSON (or Avro/Protobuf via Confluent Schema Registry) to Kafka topics. By default, it sends one topic per table, named `<topic.prefix>.<schema>.<table>`. That naming convention is one of the most important design decisions in the whole pipeline — it determines which downstream consumers see which data, and how partition keys behave.

## The Production Connector Configuration

A connector configuration that works on day one often breaks under load. The defaults are conservative; in production you'll tune most of them. Here is a configuration I have shipped in production for a payments service running about 2,000 transactions per second across 40 tables:

```json
{
  "name": "payments-cdc",
  "config": {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "database.hostname": "postgres-primary.prod.internal",
    "database.port": "5432",
    "database.user": "debezium_replica",
    "database.password": "${file:/secrets/debezium.properties:password}",
    "database.dbname": "payments",
    "topic.prefix": "cdc.payments",

    "plugin.name": "pgoutput",
    "slot.name": "debezium_payments_cdc",
    "publication.name": "debezium_payments_pub",
    "publication.autocreate.mode": "filtered",

    "table.include.list": "public.orders,public.order_items,public.payments,public.refunds,public.customers",

    "snapshot.mode": "initial",
    "snapshot.locking.mode": "none",
    "snapshot.fetch.size": "10240",

    "decimal.handling.mode": "double",
    "time.precision.mode": "connect",
    "hstore.handling.mode": "json",

    "tombstones.on.delete": "true",
    "delete.retention.ms": "86400000",

    "transforms": "route,addHeaders",
    "transforms.route.type": "org.apache.kafka.connect.transforms.RegexRouter",
    "transforms.route.regex": "([^.]+)\\.([^.]+)\\.([^.]+)",
    "transforms.route.replacement": "$1.$3",
    "transforms.addHeaders.type": "org.apache.kafka.connect.transforms.InsertHeader",
    "transforms.addHeaders.header": "cdc_source",
    "transforms.addHeaders.value.literal": "debezium"
  }
}
```

A few decisions in this config are worth highlighting:

**`plugin.name: pgoutput`** — Since Postgres 10, the built-in `pgoutput` plugin is the right choice for almost every deployment. It's maintained alongside the server, doesn't require a shared library installation like `wal2json`, and supports the full feature set Debezium needs. The [PostgreSQL logical replication docs](https://www.postgresql.org/docs/current/logical-replication.html) are clear about when each plugin is appropriate.

**`publication.autocreate.mode: filtered`** — Auto-creating a publication with `ALL TABLES` is a common mistake. It publishes every table in the database, including ones you don't want streamed. Filtered mode creates the publication from the connector's table include list.

**`snapshot.mode: initial`** — On first run, Debezium performs a consistent snapshot using `pg_export_snapshot` and a transaction with `REPEATABLE READ` isolation. After the snapshot, it streams from the slot's confirmed flush LSN. For very large databases, switch to `snapshot.mode: initial_only` for a one-time backfill and a separate connector for ongoing changes.

**`transforms: route`** — Routing collapses the schema name into the topic prefix. Without this, every schema change forces a topic rename. Collapsing `cdc.payments.public.orders` down to `cdc.payments.orders` means downstream consumers don't break when you add a new schema.

**`tombstones.on.delete: true`** — When a row is deleted, Debezium emits a tombstone event with a `null` payload but a non-null key. Downstream Kafka consumers using log compaction need those tombstones to eventually drop the record. The `delete.retention.ms` controls how long the tombstone sticks around before compaction removes it.

## Patterns in Production

### Partition Key Strategy

Every CDC event has a primary key, and that's the partition key that should be used by default. Postgres primary keys are designed to distribute well across partitions and Debezium will hash them automatically. Resist the temptation to use `updated_at` or any non-key column — it causes ordering issues when a single row updates faster than a partition can be processed.

For tables without a primary key, you need to either add one or set `message.key.columns` in the connector. Skipping this is one of the most common ways CDC pipelines lose ordering guarantees.

### Handling Schema Evolution

Postgres allows `ALTER TABLE` operations that are invisible to logical decoding — adding a nullable column, for example. These appear in the stream as schema-changed events, and downstream consumers with strict schemas (Avro, Protobuf) will reject them.

The pattern that works:

1. **Backward-compatible changes only.** Add columns as nullable or with defaults. Never rename a column in place — add a new column, dual-write in application code, then drop the old one in a later deploy.
2. **Configure the schema registry compatibility level** to `BACKWARD` (or `BACKWARD_TRANSITIVE` for stricter guarantees). This means new schema versions must be readable by consumers running the previous version.
3. **Test schema changes against the staging CDC pipeline** before they touch production. A failed schema evolution in production can stop the connector entirely.

The [Debezium documentation on schema evolution](https://debezium.io/documentation/reference/stable/transformations/event-flattening.html) covers the technical mechanics in detail.

### Backpressure and Lag

CDC pipelines fail in production when the consumer can't keep up with the WAL producer. Symptoms are predictable: Kafka consumer lag grows, the WAL retention window expands, and eventually the primary runs out of disk.

The first diagnostic is the connector's published metrics. Debezium exposes `CurrentLSN`, `LastEventReceived`, and `MilliSecondsBehindSource` — the last of these is the lag indicator you want to graph. Anything over a few seconds under steady load means something is wrong.

Common causes and fixes:

- **Consumer is single-partitioned.** A consumer group with one partition can't scale. Increase partitions on the topic, and verify the key distribution is even.
- **Slow downstream writes.** The downstream sink (Elasticsearch, S3, a data warehouse) is the bottleneck. Add batching, increase parallelism, or move to a different write strategy.
- **Network saturation.** Cross-region replication shows up here. Use a higher-throughput Kafka tier or compress the events.
- **Long-running transactions on the primary.** A single transaction holding a snapshot for hours will block WAL advancement. Monitor `pg_stat_activity` for transactions older than your SLA.

### Primary Failover

When the Postgres primary fails and a replica is promoted, the replication slot doesn't follow it automatically. The connector will throw an error and stop. The recovery procedure is well-defined but must be rehearsed:

1. The new primary is promoted and the old primary is demoted.
2. A DBA creates a new logical replication slot on the new primary, matching the `slot.name` from the connector config.
3. The connector is restarted; it will resume from the slot's position, which begins at the current LSN on the new primary.

This means events between the old primary's last commit and the new primary's promotion are lost — unless you've configured `pg_basebackup` style replication with `REPLICA IDENTITY FULL` and have an external WAL archive you can replay from. For most teams, accepting this gap and reconciling from application state is the pragmatic choice. Document it explicitly in your runbook.

### Idempotent Downstream Consumers

CDC events can be delivered more than once. Kafka offers at-least-once semantics, and a rebalance during a consumer commit window will replay events. Every downstream consumer must be idempotent on `(table, primary_key, lsn)` — typically by maintaining its own dedupe table with a TTL matching `delete.retention.ms`.

A common anti-pattern is using the Kafka offset as the idempotency key. Offsets are per-partition, and a rebalance changes them. The event's `lsn` field is stable across replays and tied to the source transaction, which makes it the right deduplication anchor.

## Architecture: A Realistic CDC Topology

For a mid-sized service, a CDC pipeline looks like this:

```
Postgres Primary
    │  logical replication slot (debezium_payments_cdc)
    ▼
Kafka Connect (Debezium connector)
    │  topic prefix: cdc.payments
    ▼
Kafka cluster (3 brokers, rf=3, compacted for state topics)
    │  partitioned by primary key
    ├──▶ Elasticsearch indexer (search & autocomplete)
    ├──▶ S3 / Parquet writer (analytics warehouse)
    ├──▶ Materialize / Flink (joins with reference data)
    └──▶ Audit log sink (compliance retention)
```

Each downstream consumer reads from the same source of truth but applies different transforms. The Elasticsearch indexer needs denormalized documents; the warehouse loader wants raw rows; the audit sink wants the full event payload including the before-image. The schema registry handles compatibility for all of them.

A nuance worth calling out: **not every consumer needs every topic**. The audit sink might want `cdc.payments.refunds` but not `cdc.payments.customers`. Designing topic granularity around consumer needs — rather than one table = one topic forever — is a mature choice that pays off as the system grows.

## Operational Checklist

Before declaring a CDC pipeline production-ready, walk through these items:

- The replication slot is monitored. A stale slot will fill the disk. Alert on `pg_replication_slots.active = false` for any CDC slot.
- The Kafka topic for every table exists with `min.insync.replicas=2` (or higher for tier-1 data).
- The connector is registered with a health check that restarts it on failure, with exponential backoff capped at 5 minutes.
- Schema registry compatibility is set to `BACKWARD` and CI blocks incompatible changes.
- A runbook exists for primary failover, connector restart, and slot recreation.
- Lag is graphed in your observability stack with a page when it exceeds the SLA window.
- A synthetic canary table exists with known writes, and its events appear in downstream sinks within the expected latency.

## Key Takeaways

- CDC from Postgres works by reading the WAL through a logical replication slot — durability is excellent, but a stale slot will fill your disk.
- Debezium's defaults are safe but conservative; production deployments need tuned snapshot modes, transform chains, and explicit table allowlists.
- Partition by primary key, not by time, to preserve per-row ordering across the pipeline.
- Schema evolution must be backward-compatible; configure the schema registry to enforce it and test changes in staging.
- Consumers must be idempotent on `(table, primary_key, lsn)` because at-least-once delivery means duplicates are inevitable.
- Plan for primary failover explicitly — slots don't follow the promoted replica, and the recovery procedure must be rehearsed.
- Graph lag, alert on it, and know the four common causes: under-partitioned consumers, slow downstream writes, network saturation, and long-running primary transactions.

## Further Reading

- [Debezium PostgreSQL Connector Documentation](https://debezium.io/documentation/reference/stable/connectors/postgresql.html)
- [PostgreSQL Logical Replication Internals](https://www.postgresql.org/docs/current/logical-replication.html)
- [Change Data Capture: The Magic Behind Modern Data Architectures (Redgate)](https://www.redgate.com/blog/database-devops/change-data-capture-the-magic-behind-modern-data-architectures)
- [Designing Data-Intensive Applications, Chapter 11 (Stream Processing)](https://dataintensive.net/)
- [Apache Kafka Connect Documentation](https://kafka.apache.org/documentation/#connect)