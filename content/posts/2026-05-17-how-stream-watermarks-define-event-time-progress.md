---
title: "How Stream Watermarks Define Event Time Progress"
date: "2026-05-17T06:00:54.050"
draft: false
tags: ["streaming","watermarks","event-time","apache-flink","data-engineering"]
description: "Learn how stream watermarks convey event‑time progress, letting systems process out‑of‑order data, trigger windows, and maintain correct state consistently."
summary: "Watermarks are the backbone of event‑time handling in modern stream processors. This post explains their purpose, generation, and impact on windowing."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-how-stream-watermarks-define-event-time-progress.svg"
  alt: "Illustration of a flowing data stream with timestamp markers."
  caption: ""
  relative: false
---

> **TL;DR** — Watermarks are timestamps that travel with a data stream, indicating the system’s belief about the highest event‑time that has arrived. They let window operators fire, handle out‑of‑order records, and keep state consistent without waiting for the physical end of the stream.

In a world where data arrives from sensors, logs, and user interactions at unpredictable intervals, stream processors need a reliable way to reason about **event time** – the time when something actually happened – rather than the time it was observed. Watermarks provide that reasoning, turning a chaotic flow of timestamps into a well‑ordered progression that drives windowing, triggers, and late‑data handling.

## What Is Event Time?

Event time is the logical clock attached to each record, usually representing when the event occurred in the source system. Contrast this with **processing time**, which is simply the wall‑clock time on the machine that runs the operator. Processing‑time semantics are easy to implement but can produce misleading results when events are delayed, reordered, or replayed.

* **Why event time matters**
  * Guarantees that analytics reflect the true order of real‑world happenings.
  * Enables accurate aggregations across time‑based windows (e.g., hourly sales totals).
  * Allows for deterministic results even when network latency varies.

Most modern stream frameworks – Apache Flink, Apache Beam, Kafka Streams, Pulsar Functions – expose the concept of event time and require the user to define how the system should **track its progress**. That progress indicator is the watermark.

## Understanding Watermarks

A **watermark** is a monotonically increasing timestamp that travels downstream with the data. It signals, “All events with an event‑time **earlier** than this watermark have (or are expected to have) arrived.” Operators can then safely close windows, emit results, and purge state.

### Generation Strategies

Watermark generation is not a one‑size‑fits‑all problem. Different sources and workloads call for different strategies:

1. **Periodic Watermarks** – The source emits a watermark every *n* milliseconds based on the highest observed timestamp minus a fixed lag (the *allowed lateness*). This is the default in Flink’s `BoundedOutOfOrdernessTimestampExtractor`.

   ```python
   # Example: Flink periodic watermark generator (Python API)
   from pyflink.datastream import TimeCharacteristic, StreamExecutionEnvironment
   from pyflink.datastream.functions import TimestampAssigner, WatermarkStrategy

   class MyTimestampAssigner(TimestampAssigner):
       def extract_timestamp(self, element, record_timestamp):
           # element is a tuple (event_time, payload)
           return element[0]

   # Allow up to 5 seconds of out‑of‑order data
   strategy = WatermarkStrategy.for_bounded_out_of_orderness(Duration.of_seconds(5)) \
                               .with_timestamp_assigner(MyTimestampAssigner())

   env = StreamExecutionEnvironment.get_execution_environment()
   env.set_stream_time_characteristic(TimeCharacteristic.EventTime)
   stream = env.from_source(my_source, strategy, "my_source")
   ```

2. **Punctuated Watermarks** – The source injects a watermark **only** when it encounters a special “punctuation” record that explicitly carries a watermark timestamp. This works well when the source can guarantee that a particular record type marks progress (e.g., “heartbeat” messages from IoT devices).

3. **Monotonic Watermarks** – When the source itself guarantees strictly increasing timestamps (e.g., a log file written in order), the framework can simply forward the latest timestamp as the watermark.

4. **Hybrid Approaches** – Some pipelines combine periodic and punctuated watermarks to adapt to bursty traffic while still providing a safety net.

Choosing the right strategy hinges on three questions:

* How much out‑of‑order data can the system tolerate?
* What is the expected latency for the downstream results?
* Does the source have a natural “progress marker”?

### Watermark Semantics

Watermarks are *inclusive* of the timestamp they carry: a watermark of **t = 12:00:00** guarantees that **no event with timestamp ≤ 12:00:00** will appear later. Consequently, windows that end at 12:00:00 can be fired as soon as the watermark passes that point.

A subtle but important nuance is the difference between **event‑time watermark** and **processing‑time watermark**. The former is derived from the data itself; the latter is based on the wall clock and is useful for debugging or for systems that cannot access event timestamps.

## How Watermarks Drive Windowing

Window operators are the most visible consumer of watermarks. Whether you’re computing a tumbling window of 5 minutes or a sliding window with a 1‑minute hop, the operator needs to know *when* it can safely emit the aggregated result.

### Tumbling and Sliding Windows

* **Tumbling windows** are non‑overlapping, fixed‑size intervals. When the watermark exceeds the end timestamp of a window, the window is closed and its result is emitted.

  ```bash
  # Flink SQL example: tumbling window on event time
  SELECT
      TUMBLE_START(event_time, INTERVAL '5' MINUTE) AS window_start,
      COUNT(*) AS event_cnt
  FROM sensor_stream
  GROUP BY TUMBLE(event_time, INTERVAL '5' MINUTE);
  ```

* **Sliding windows** overlap; each event may belong to multiple windows. The watermark still dictates when each individual window can be closed.

  ```sql
  -- Sliding window with 1‑minute hop and 5‑minute size
  SELECT
      HOP_START(event_time, INTERVAL '1' MINUTE, INTERVAL '5' MINUTE) AS win_start,
      AVG(value) AS avg_val
  FROM measurements
  GROUP BY HOP(event_time, INTERVAL '1' MINUTE, INTERVAL '5' MINUTE);
  ```

In both cases, the operator holds onto state for *open* windows. Once the watermark passes a window’s end, the state can be cleared, freeing memory.

### Late Data Handling

Even with generous allowed lateness, some events may still arrive **after** the watermark has moved past their window. Frameworks provide two mechanisms:

1. **Side Outputs** – Late events can be redirected to a separate stream for special handling (e.g., alerts, re‑processing).

   ```python
   # Flink Python API: side output for late events
   from pyflink.datastream import OutputTag

   late_tag = OutputTag("late-events", Types.TUPLE([Types.LONG(), Types.STRING()]))

   windowed_stream = stream \
       .key_by(lambda x: x[1]) \
       .window(TumblingEventTimeWindows.of(Time.minutes(5))) \
       .allowed_lateness(Time.minutes(2)) \
       .side_output_late_data(late_tag) \
       .reduce(my_reduce_function)

   late_stream = windowed_stream.get_side_output(late_tag)
   ```

2. **Updating Results** – Some applications tolerate *retractions*: when a late event arrives, the previously emitted result is corrected. Beam’s *accumulating* trigger and Flink’s *retractable* window operators support this pattern.

The choice between side outputs and result updates depends on the downstream consumer’s tolerance for revisions.

## Implementations in Popular Engines

### Apache Flink

Flink treats watermarks as first‑class citizens. The **WatermarkStrategy** API (introduced in Flink 1.11) unifies timestamp extraction and watermark generation. Flink also offers **idle source detection** – when a source stops emitting data, it can be marked idle so that its lack of timestamps does not hold back the global watermark.

Key points:

* Global watermarks are the minimum of all parallel source watermarks.
* Operators receive watermarks *per partition* and compute a *local* minimum before forwarding.
* Configurable **allowed lateness** per window, defaulting to 0 (strict event‑time).

### Apache Beam

Beam’s model abstracts watermarks across runners (Flink, Dataflow, Spark). The SDK provides **TimestampedValue** objects and **WatermarkEstimator** interfaces for custom sources. Beam’s **triggering** system (e.g., *AfterWatermark*, *AfterProcessingTime*) lets you define exactly when to emit results relative to watermarks.

* Beam’s **bounded** vs **unbounded** pipelines handle watermarks differently: bounded pipelines can set the final watermark to `Infinity`, while unbounded pipelines rely on continuous watermark advancement.
* The Beam model includes **PCollection** watermark propagation, ensuring downstream transforms always see the most recent progress.

### Kafka Streams

Kafka Streams does not expose watermarks as a separate primitive. Instead, it uses **stream‑time** (derived from record timestamps) and **punctuation** APIs to simulate watermark-like behavior. Users can schedule *punctuators* that run at a fixed interval, effectively providing a periodic watermark.

```java
// Java: schedule a punctuator that fires every 10 seconds
builder.stream("input-topic")
       .process(() -> new Processor<String, String>() {
           @Override
           public void init(ProcessorContext context) {
               context.schedule(Duration.ofSeconds(10), PunctuationType.WALL_CLOCK_TIME,
                   timestamp -> {
                       // This is where you could emit a "watermark" event
                       // or trigger window cleanup.
                   });
           }
           // ...
       });
```

While less explicit, the underlying concepts of event‑time progress and late‑data handling are still present.

## Key Takeaways

- **Watermarks are timestamps that travel with the data**, indicating the highest event‑time the system believes has been fully observed.
- **Generation strategies** (periodic, punctuated, monotonic) should match source characteristics and latency requirements.
- **Window operators rely on watermarks** to know when a window can be closed, emitted, and its state cleared.
- **Late data** can be redirected to side outputs or used to update previously emitted results, depending on business needs.
- **All major stream processors** (Flink, Beam, Kafka Streams) implement watermarks or equivalent mechanisms, though the APIs differ.

## Further Reading

- [Apache Flink Documentation – Watermarks & Event Time](https://nightlies.apache.org/flink/flink-docs-release-1.18/docs/dev/datastream/event-time/generating_watermarks/)
- [Apache Beam Programming Guide – Timestamps, Windows, and Triggers](https://beam.apache.org/documentation/programming-guide/#timestamps-windows-and-triggers)
- [Kafka Streams – Punctuations and Stream Time](https://kafka.apache.org/documentation/streams/developer-guide/processing-time)