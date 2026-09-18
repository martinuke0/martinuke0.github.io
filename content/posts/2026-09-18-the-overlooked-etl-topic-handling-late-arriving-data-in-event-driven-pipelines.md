

---
title: "The Overlooked ETL Topic: Handling Late Arriving Data in Event-Driven Pipelines"
date: "2026-09-18T22:01:30.510"
draft: false
tags: ["data-pipelines", "etl", "stream-processing", "kafka", "late-data"]
description: "Learn how to design ETL pipelines that gracefully handle late arriving data without breaking downstream analytics, using real-world patterns from event-driven architectures."
summary: "Late data is inevitable in event-driven systems. This post shows practical patterns—watermarks, allowed lateness, and log-based reprocessing—to keep your ETL pipelines accurate and reliable."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-the-overlooked-etl-topic-handling-late-arriving-data-in-event-driven-pipelines.svg"
  alt: "A clock overlaying a data pipeline diagram, symbolizing late arriving data"
  caption: ""
  relative: false
---

> **TL;DR** — In event-driven ETL pipelines, late arriving data is not an edge case but a daily reality. Ignoring it silently corrupts aggregates; embracing it with explicit watermarks, allowed lateness, and idempotent reprocessing turns a liability into a correctness guarantee. This post walks through the three production patterns that ship.

---

Event-driven pipelines have become the backbone of modern data platforms, but most ETL tutorials still assume neat, ordered batches that arrive on a predictable schedule. Real-world systems—clickstreams, IoT sensors, mobile telemetry—rarely cooperate. Messages are delayed, reordered, or duplicated, and if your downstream analytics don’t account for that, your dashboards will drift from truth without anyone noticing.

This post focuses on a topic that rarely gets the attention it deserves: **how to handle late arriving data in event-driven ETL pipelines**. We’ll anchor the discussion in concrete systems (Kafka, Flink, dbt) and show the architecture patterns that working teams actually use in production.

## Why Late Data Breaks More Than Just Counts

A late event isn’t just a missing row; it’s a correctness landmine. Consider a simple revenue aggregation:

- **Batch-oriented ETL** assumes all records for a day arrive before the window closes. A single late sale lands in the next day’s bucket, inflating one day and deflating another.
- **Streaming ETL** with naive windowing drops out-of-order events entirely, silently undercounting revenue.
- **Downstream BI tools** (Looker, Tableau) then present these numbers as ground truth, and stakeholders make decisions on flawed data.

The root cause is usually a missing **watermark** or an unconfigured **allowed lateness**. These concepts aren’t theoretical—they’re the difference between a pipeline that *works* in demo mode and one that survives in production.

## Architecture: The Three Levers You Control

To handle late data systematically, you need to design around three levers. Each one corresponds to a real configuration in Kafka, Flink, or your stream processor of choice.

### 1. Watermarks: Defining “On-Time”

A watermark is a timestamp that tells the engine “no events older than this will arrive.” It’s not a guarantee; it’s a heuristic. In practice, watermarks are derived from event timestamps and the observed max out-of-order delay.

```java
// Flink: watermark with bounded out-of-order delay
WatermarkStrategy
    .<Event>forBoundedOutOfOrderness(Duration.ofSeconds(30))
    .withTimestampAssigner((event, timestamp) -> event.getTimestamp());
```

The 30-second bound here is a business decision, not a technical one. If your mobile SDKs occasionally buffer for 45 seconds, you’ll drop events. The fix is to **monitor watermark lag** and alert when the actual delay exceeds the configured bound.

### 2. Allowed Lateness: The Safety Net

Even with a watermark, some events will slip through. Allowed lateness gives them a second chance. In Flink, this is configured per window:

```java
stream
    .keyBy(Event::getTenantId)
    .window(TumblingEventTimeWindows.of(Time.seconds(60)))
    .allowedLateness(Time.seconds(120))  // 2-minute grace period
    .sideOutputLateData(lateEventsTag);
```

Events that arrive during the grace period trigger an **update** to the previous window’s aggregate. Events that miss the grace period are emitted to a side output for dead-letter handling or reprocessing.

### 3. Idempotent Reprocessing: The Recovery Mechanism

If late data is inevitable, your pipeline must be able to *recompute* past results without double-counting. This is where the batch and stream worlds converge:

- **Log-based reprocessing**: Kafka’s compacted topics retain the latest state. You can replay a topic into a Flink job that writes to a mutable store (e.g., PostgreSQL with upserts) instead of an append-only table.
- **dbt + incremental models**: For batch ETL, use `dbt`’s `incremental` materialization with a `unique_key`. Late events merge into the existing table instead of creating duplicates.

```sql
-- dbt incremental model for daily revenue
{{ config(materialized='incremental', unique_key='event_id') }}

SELECT
    event_id,
    DATE(event_timestamp) AS event_date,
    amount
FROM {{ source('raw_events', 'sales') }}
WHERE event_timestamp >= '{{ var("start_date") }}'
```

This pattern is what makes “late data” a **correctness feature** rather than a bug.

## Patterns in Production: What Real Teams Do

### Pattern A: The Lambda Architecture (Simplified)

Many teams run a simplified Lambda: a streaming layer (Kafka → Flink) for real-time dashboards and a batch layer (Kafka → S3 → dbt) for nightly reconciliation. The streaming layer uses allowed lateness; the batch layer reprocesses everything from the raw log. This gives you low-latency *and* eventual correctness.

### Pattern B: The Kappa Architecture (Pure Streaming)

If you’ve standardized on Kafka, you can go full Kappa: one pipeline, no batch. The trick is to use **change-data-capture (CDC)** from your source systems and store raw events in a topic with a long retention (e.g., 30 days). Late events are handled by reprocessing from the topic into a serving layer (e.g., a materialized view in ClickHouse).

### Pattern C: The Data Contract Approach

Define a **schema contract** (using JSON Schema or Avro) that includes a `delay_tolerance` field. Consumers can then decide how to handle events based on this metadata. Tools like Confluent Schema Registry enforce this at the producer level, and late events are flagged without custom code.

## Key Takeaways

- **Watermarks are a heuristic, not a promise.** Monitor them; alert when actual delay exceeds the bound.
- **Allowed lateness is a grace period, not a fix.** Use it to update windows, but have a dead-letter path for events that miss it.
- **Idempotency is non-negotiable.** Whether via Kafka compaction, dbt incremental models, or upserts, your pipeline must handle reprocessing without double-counting.
- **Lambda vs. Kappa is a tradeoff, not a religion.** Choose based on your latency requirements and operational maturity.
- **Data contracts with explicit delay tolerance** make late-data handling a first-class concern, not an afterthought.

## Further Reading

- [Apache Flink Documentation: Event Time & Watermarks](https://nightlies.apache.org/flink/flink-docs/stable/docs/concepts/time/)
- [Confluent Schema Registry: Late Data Handling](https://docs.confluent.io/platform/current/schema-registry/avro.html)
- [dbt Incremental Models: The Complete Guide](https://docs.getdbt.com/reference/dbt-configs/incremental-models/)
- [Kafka for the Rest of Us: Handling Out-of-Order Events](https://www.confluent.io/blog/out-of-order-events/)
- [The Data Engineering Handbook: Late Data Patterns](https://www.oreilly.com/library/view/data-engineering-handbook/9781492092543/)