---
title: "Where Stream Processing Systems Draw the Line for Late Data"
date: "2026-05-18T23:00:55.674"
draft: false
tags: ["stream-processing", "late-data", "watermarks", "apache-flink", "real-time-analytics"]
description: "Explore how modern stream processing platforms define and manage late‑arriving events, from watermarks to allowed lateness, and learn practical design patterns."
summary: "A deep dive into how stream engines decide what counts as late data, the mechanisms they expose, and best‑practice patterns for robust pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-where-stream-processing-systems-draw-the-line-for-late-data.svg"
  alt: "Illustration of a data stream with timestamps and a watermark line."
  caption: ""
  relative: false
---

> **TL;DR** — Stream processing systems use *watermarks* and configurable *allowed‑lateness* windows to decide when data is “late.” Each engine (Flink, Beam, Spark, Kafka Streams) draws the line differently, offering side‑outputs or retractions for data that arrives after the cutoff. Understanding these mechanisms lets you balance latency, correctness, and operational complexity.

Real‑time analytics hinges on the assumption that events arrive roughly in the order they happen. In practice, network hiccups, batch uploads, and clock skew cause *late data*—records whose event‑time timestamp is earlier than the current processing progress. How far a system tolerates this lateness determines both result accuracy and end‑to‑end latency. This article explains the core concepts (event time, watermarks, allowed lateness), surveys the policies of the major stream processing engines, and presents practical patterns for building pipelines that stay correct even when the clock runs against you.

## Understanding Stream Processing and Event Time

### Event Time vs. Processing Time

* **Event time** is the timestamp embedded in the data (e.g., a sensor reading’s generation time).  
* **Processing time** is the wall‑clock time when the system actually sees the record.

Most analytical queries care about *event time* because it reflects the real world, not the quirks of the network. However, processing pipelines only see events as they arrive, so they need a way to infer when they have “caught up” with the event‑time stream.

### The Role of Watermarks

A **watermark** is a monotonically increasing marker that the system emits to say, “I have seen all events with timestamps ≤ W.” Anything arriving with a timestamp ≤ W after the watermark is considered *late*.

Watermarks can be generated in several ways:

```python
# Example: Flink watermark generator in Python (PyFlink)
from pyflink.datastream import WatermarkStrategy
from datetime import timedelta

def timestamp_extractor(event):
    return event['event_ts']

watermark_strategy = WatermarkStrategy \
    .for_bounded_out_of_orderness(timedelta(seconds=30)) \
    .with_timestamp_assigner(timestamp_extractor)

# This tells Flink that events may be up to 30 seconds late.
```

The choice of out‑of‑orderness bound directly determines the lateness threshold. A tighter bound yields lower latency but higher risk of dropping or mis‑aggregating late events.

## Strategies for Handling Late Data

### Allowed Lateness

Many engines let you *extend* the window after the watermark fires. This is called **allowed lateness**. The window continues to accept updates for a configurable period, and any late events that fall within that period trigger *retractions* (updates) to previously emitted results.

```sql
-- Spark Structured Streaming example
SELECT
  window(event_time, '5 minutes', '1 minute') as win,
  product_id,
  sum(quantity) as total_qty
FROM events
GROUP BY win, product_id
WITH WATERMARK event_time AS INTERVAL 10 MINUTES
```

In Spark, the `WITH WATERMARK` clause defines the watermark, and the window will stay open for an additional 10 minutes of event‑time lateness.

### Side Outputs / Dead‑Letter Queues

When an event is *beyond* the allowed lateness, systems often provide a **side output** (Flink) or **dead‑letter queue** (Beam) where the late record can be routed for separate handling—e.g., manual inspection, re‑processing, or archival.

```java
// Flink side‑output for late events (Java API)
final OutputTag<Event> lateTag = new OutputTag<Event>("late-events"){};

WindowedStream<Event, String, TimeWindow> windowed = stream
    .keyBy(event -> event.getKey())
    .window(TumblingEventTimeWindows.of(Time.minutes(5)))
    .allowedLateness(Time.minutes(2))
    .sideOutputLateData(lateTag);

DataStream<Event> lateEvents = windowed.getSideOutput(lateTag);
lateEvents.addSink(new LateEventSink());
```

The side output isolates late data without contaminating the main result stream.

### Reprocessing and State Updates

Some use cases (e.g., financial compliance) cannot tolerate any loss of late events. One approach is to **reprocess** the affected window entirely when a late event arrives, using the engine’s *state* to recompute aggregates and emit corrected results.

In Beam, this is achieved through *retractions*:

```python
# Beam Python SDK – using allowed lateness and retractions
pipeline = beam.Pipeline(options=options)

(events
 | 'Read' >> beam.io.ReadFromPubSub(topic='projects/.../topics/events')
 | 'AssignTimestamps' >> beam.Map(lambda e: beam.window.TimestampedValue(e, e['event_ts']))
 | 'Window' >> beam.WindowInto(
        beam.window.FixedWindows(300),
        allowed_lateness=120,
        trigger=beam.trigger.AfterWatermark(late=beam.trigger.AfterProcessingTime(60)),
        accumulation_mode=beam.trigger.AccumulationMode.DISCARDING)
 | 'Sum' >> beam.CombinePerKey(sum)
 | 'Write' >> beam.io.WriteToBigQuery(...)
)
```

The `allowed_lateness=120` seconds tells Beam to keep the window alive for two minutes after the watermark, and the trigger ensures updated results are emitted.

## How Major Systems Define the Late Data Boundary

### Apache Flink

* **Watermark strategy:** User‑defined `WatermarkStrategy` with bounded out‑of‑orderness or periodic punctuated watermarks.  
* **Allowed lateness:** Configurable per window via `.allowedLateness(Time)`; late events beyond that are sent to a side output.  
* **State handling:** Flink stores window state locally; when a late event arrives within allowed lateness, it recomputes the window and emits a *retraction* (the updated aggregate).  
* **Operational tip:** Use *idle source detection* (`.withIdleness(Duration)`) to avoid stalled watermarks in partitions that temporarily stop sending data.

### Apache Beam (Google Dataflow)

* **Watermarks:** Propagated automatically from sources; can be overridden with `WithTimestamp` and `WatermarkEstimator`.  
* **Allowed lateness:** Set per `WindowInto` via `allowed_lateness`. Late events beyond this are dropped unless a side output is defined.  
* **Re‑emission:** Beam’s default triggers (after watermark) fire once, but you can add *early* and *late* triggers to emit provisional results and later corrections.  
* **Operational tip:** Choose *continuous* watermarks for streaming sources (e.g., Pub/Sub) to keep latency low, but be aware that very aggressive watermarks increase the chance of dropped data.

### Apache Spark Structured Streaming

* **Watermark clause:** `WITH WATERMARK event_time AS INTERVAL X`. Spark drops state older than `event_time - X` and treats any event older than that as late.  
* **Late handling:** No built‑in side output; late events are simply ignored. To capture them, you must pre‑filter and write to a separate sink.  
* **Trigger model:** Supports *processing‑time* and *continuous* triggers; the watermark advances only when a micro‑batch completes, so batch interval influences lateness tolerance.  
* **Operational tip:** Align the micro‑batch interval with the watermark delay (e.g., 5 min batch, 10 min watermark) to avoid excessive state buildup.

### Kafka Streams

* **Grace period:** `TimeWindows.of(Duration.ofMinutes(5)).grace(Duration.ofMinutes(2))` defines how long after the window end late records are accepted.  
* **Suppression:** `suppress(Suppressed.untilWindowCloses(...))` can hold results until the grace period expires, emitting a final result only once.  
* **Late record handling:** Events arriving after the grace period are dropped; you can capture them via a `branch` before the aggregation.  
* **Operational tip:** Use `TimestampExtractor` that falls back to record metadata when the payload lacks a timestamp, reducing the chance of unintentionally late data.

## Operational Considerations

### Latency vs. Completeness Trade‑off

| Strategy | Latency impact | Completeness impact |
|----------|----------------|--------------------|
| Tight watermark (e.g., 5 s) | Low (results appear quickly) | High risk of missing late events |
| Generous allowed lateness (e.g., 10 min) | Higher (window stays open) | Near‑complete results, but more state |
| Side‑output + reprocessing | Variable (main flow stays low latency) | Allows full recovery of very late events |

Choosing the right balance depends on SLAs: a dashboard that must refresh every 30 seconds may tolerate a few percent of missed events, while a fraud detection pipeline cannot.

### Monitoring and Alerting

* **Watermark lag:** Emit a metric (`watermark_lag_seconds = current_processing_time - watermark_timestamp`). Alert when lag exceeds a threshold.  
* **Late‑event rate:** Count events routed to side outputs; a sudden spike may indicate upstream source problems.  
* **State size:** Track per‑window state memory; excessive allowed lateness can cause state blow‑up.

Example Prometheus alert rule for Flink watermark lag:

```yaml
# prometheus.yml snippet
alert: WatermarkLagTooHigh
expr: flink_taskmanager_job_task_watermark_lag_seconds > 30
for: 5m
labels:
  severity: warning
annotations:
  summary: "Watermark lag > 30 s for job {{ $labels.job_name }}"
  description: "The job is falling behind event time, which may cause late‑data drops."
```

### Testing Late‑Data Scenarios

1. **Unit test with synthetic timestamps:** Feed events out of order and assert that results match expected retractions.  
2. **Integration test with Testcontainers:** Deploy a mini Kafka + Flink stack, inject late events, and verify side‑output handling.  
3. **Chaos testing:** Randomly delay a subset of source partitions to simulate network latency spikes.

## Best Practices for Designing Late‑Data Tolerant Pipelines

1. **Assign timestamps at the source.** Use a reliable, monotonic field (e.g., ISO‑8601 `event_time`) rather than processing‑time metadata.  
2. **Start with a modest out‑of‑orderness bound** (e.g., 30 s) and monitor late‑event rate before widening it.  
3. **Leverage allowed lateness** only when downstream consumers can handle updates (e.g., dashboards that refresh).  
4. **Emit side outputs for truly late data** and route them to a durable sink (e.g., Cloud Storage, BigQuery) for later batch reconciliation.  
5. **Use idleness detection** for sources that may pause (e.g., IoT devices) to prevent watermarks from stalling.  
6. **Keep window state bounded**: combine tumbling windows with *session gaps* or *eviction policies* to prune old state.  
7. **Document the lateness policy** in your data contracts so downstream teams know the expected completeness guarantees.  

## Key Takeaways

- **Watermarks** are the engine’s way of saying “I’ve seen everything up to this event‑time.”  
- **Allowed lateness** lets windows stay open after a watermark, emitting corrected results for moderately late events.  
- **Side outputs / dead‑letter queues** capture events that arrive after the allowed lateness window, preserving them for batch reprocessing.  
- Each major stream processor (Flink, Beam, Spark, Kafka Streams) exposes these concepts with slightly different APIs and defaults.  
- Balancing **latency** against **completeness** requires careful choice of out‑of‑orderness bounds, allowed lateness, and monitoring of watermark lag.  
- Implement robust **monitoring, alerting, and testing** to detect and respond to abnormal late‑data patterns before they corrupt analytics.

## Further Reading

- [Apache Flink Documentation – Watermark Strategies](https://nightlies.apache.org/flink/flink-docs-master/docs/dev/datastream/overview/#watermarks)  
- [Google Cloud Dataflow (Apache Beam) – Handling Late Data](https://cloud.google.com/dataflow/docs/guides/handling-late-data)  
- [Spark Structured Streaming Programming Guide – Watermarking](https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html#handling-late-data-with-watermarking)  
- [Kafka Streams – Windowing and Grace Periods](https://kafka.apache.org/documentation/streams/developer-guide/dsl-api.html#windowing)  
- [Understanding Event Time and Watermarks in Stream Processing](https://www.confluent.io/blog/event-time-processing-with-apache-kafka/)