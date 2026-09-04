---
title: "Throughput vs Latency: Why Optimizing One Will Almost Always Break the Other"
date: "2026-09-04T12:42:12.326"
draft: false
tags: ["performance", "systems-design", "distributed-systems", "observability", "backend-engineering"]
description: "Throughput and latency are not the same metric, and optimizing for one usually hurts the other. A practical guide for engineers who have to pick."
summary: "Throughput and latency measure different things, and most of the systems pain we feel at scale comes from pretending they don't. Here is how they actually trade off, with real production patterns."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-throughput-vs-latency-why-optimizing-one-will-almost-always-break-the-other.svg"
  alt: "Two conveyor belts running at different speeds, one fast and one slow, photographed from above."
  caption: ""
  relative: false
---

> **TL;DR** — Latency is how long one operation takes; throughput is how many operations complete per second. They are coupled by Little's Law, which means you cannot push one arbitrarily high without consequences for the other. Every "we made it faster" story in production is really a story about which side of that trade-off you chose to spend your budget on.

If you have ever watched a dashboard where p99 latency is climbing while requests-per-second stays flat, you have already met the central tension in this post. Throughput and latency look like two flavors of "performance," but they answer different questions and respond to different knobs. Treat them as one metric and you will spend weeks chasing a number that does not exist.

This post walks through what each metric actually means, how they relate through queueing theory, where the trade-offs show up in real systems, and the patterns engineers use to get the best of both when they cannot get all of both.

## What "Throughput" and "Latency" Actually Mean

**Latency** is the time from when a request enters a system to when it produces a response. For a single API call, it is measured in milliseconds or microseconds. We almost never talk about average latency in production — we talk about percentiles: p50 (median), p95, p99, and p99.9. A service with 5 ms p50 and 2,000 ms p99 is not "fast." It is occasionally catastrophic, and that tail is what your users actually feel.

**Throughput** is the rate at which a system completes work, typically measured in requests per second (RPS), messages per second, or bytes per second. Throughput is a system-level property. You can only meaningfully measure it once requests are flowing through.

The trap is that "fast" colloquially means both. "This query is fast" might mean *my individual query returned in 8 ms* (latency) or *we can run 100,000 of these per second* (throughput). Those are not the same claim and the engineering work to improve them is not the same.

## The Trade-off: Little's Law

The cleanest way to see the relationship is [Little's Law](https://en.wikipedia.org/wiki/Little%27s_law), which for a stable system states:

> L = λ × W

Where:
- **L** is the average number of items in the system (concurrency in flight)
- **λ** (lambda) is the throughput, items per second
- **W** is the average time each item spends in the system (latency)

Rearranged: throughput = concurrency / latency. If you fix concurrency (because your pool sizes, thread counts, or connection limits are fixed), then **latency and throughput are inversely proportional**. Cut latency in half and you roughly double throughput — *assuming you can fill the pipeline*.

This is why "we tuned the hot loop and got 2x throughput" is often really a story about cutting latency so the same hardware could complete more work per second. It is also why batching, which increases per-request latency, can increase throughput: the same fixed concurrency is doing more useful work per operation.

The corollary is the one that bites teams in production: **if you fix latency and try to push throughput past what the system can handle, latency has nowhere to go but up**. That is what we call the *knee* of the curve, and the *cliff* right after it.

## Why Optimizing One Breaks the Other

Three concrete mechanisms cause the trade-off in real systems.

### 1. Resource Contention

Every request uses CPU, memory, disk, and network. When you try to increase throughput by accepting more concurrent requests, those resources get shared. Context switches rise, CPU caches thrash, and the [Linux kernel spends more time scheduling than running](https://www.kernel.org/doc/html/latest/scheduler/sched-design-CFS.html). Each individual request slows down. You added load and got *both* higher latency *and* lower effective throughput at the tail.

### 2. Queueing

When requests arrive faster than they can be processed, they queue. This is unavoidable at any non-trivial load. Queueing theory, specifically the [M/M/1 model](https://en.wikipedia.org/wiki/M/M/1_queue), tells us that average waiting time grows super-linearly as utilization approaches 100%. At 50% utilization, a request waits on average one service-time. At 90%, it waits nine. At 99%, ninety-nine.

That is why dashboards that show CPU at 95% and p99 at 800 ms are not mysterious — they are textbook. Throughput did not actually go up; what went up was the queue depth in front of a saturated service.

### 3. Coordination Overhead

Distributed systems have to coordinate. Two-phase commits, consensus rounds, lock acquisition, retries on contention — each of these adds latency to *every* operation when you scale them up. A single Postgres write at low concurrency takes 2 ms; the same write under contention for the same row can take hundreds of milliseconds because of lock waits, as any team that has hit [lock contention in Postgres](https://www.postgresql.org/docs/current/explicit-locking.html) can attest.

## Patterns in Production

The trade-off is real, but it is not hopeless. Mature systems attack it on multiple fronts.

### Batching

Batching is the canonical "trade latency for throughput" move. Instead of processing one event at a time, accumulate up to *N* events or *T* milliseconds, then process them together. This amortizes fixed costs — syscall overhead, network round-trips, disk seeks, transaction commit — across many units of work.

```python
# Bad — one event per commit
for event in stream:
    db.commit_one(event)

# Better — batched commit, higher latency per event, much higher throughput
buffer = []
for event in stream:
    buffer.append(event)
    if len(buffer) >= 500 or time_since_flush() > 50:
        db.commit_many(buffer)
        buffer.clear()
```

[Kafka producers](https://kafka.apache.org/documentation/#producerconfigs) expose this directly via `linger.ms` and `batch.size`. Network calls are expensive; a producer that batches intelligently will use less CPU and get higher throughput *and* lower p99 even though per-message latency is higher.

### Pipelining and Concurrency

The mirror image is concurrency. Instead of one request in flight at a time, run hundreds. Each one is still slow, but the *aggregate* rate climbs. This is what every async HTTP client, every [Tokio runtime](https://tokio.rs/), and every connection pool is doing.

```rust
// Tokio-style: many requests in flight
let mut handles = vec![];
for url in urls {
    handles.push(tokio::spawn(async move {
        reqwest::get(url).await
    }));
}
for h in handles { let _ = h.await?; }
```

The catch is that pipelining only helps until you saturate some bottleneck downstream. After that, latency climbs because the queue is growing, and the p99 you cared about gets worse. This is where Little's Law shows up again: throughput is bounded by concurrency / latency.

### Caching

Caching is unusual: it can improve *both* latency and throughput for the same workload. A request served from cache avoids the work entirely, so it returns faster *and* uses fewer resources, leaving headroom for more requests. The trade-off shifts to staleness and memory cost.

[Redis](https://redis.io/docs/latest/develop/use/patterns/) and [Memcached](https://memcached.org/) are the obvious examples, but the same pattern shows up in CPU caches, kernel page caches, CDN edges, and read-through database caches. The mistake teams make is treating cache as free — eviction storms, cold starts, and thundering herds can briefly destroy both metrics.

### Asynchrony and Decoupling

If a request does not need an immediate response, do not wait for one. Push the request onto a queue and let a worker drain it later. The user's API call becomes "accepted" in milliseconds; the work happens in the background.

This is the entire premise of message queues like [Kafka](https://kafka.apache.org/), [RabbitMQ](https://www.rabbitmq.com/), and [AWS SQS](https://docs.aws.amazon.com/AQS/latest/DeveloperGuide/sqs-short-and-long-polling.html), and of stream processors like [Flink](https://flink.apache.org/) and [Kafka Streams](https://kafka.apache.org/documentation/streams/). Throughput at the *front door* becomes effectively unbounded. The trade-off has not disappeared — it has moved to the worker fleet, where you now care about *consumer* throughput and *end-to-end* latency.

### Backpressure and Load Shedding

The mature answer to "more requests than we can handle" is not to silently degrade. It is to push back. Backpressure means signaling upstream to slow down. Load shedding means dropping or rejecting requests explicitly with a clear error code (HTTP 429, 503) instead of letting them pile up.

[Envoy](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_routing), [gRPC](https://grpc.io/docs/guides/performance/), and most modern service meshes implement circuit breakers for this. The reasoning is the same as queueing theory: a request that waits 30 seconds and times out is worse for the user *and* worse for the system than one that is rejected immediately. You protect throughput for the requests you do accept and you give the caller a chance to retry intelligently.

## Where the Metrics Diverge the Most

A few system types are worth calling out because their trade-offs are unusually sharp.

### Storage systems

Databases sit at an awkward intersection. A single-row lookup has great latency but low throughput per connection. To get throughput, you need batching, pipelining, and connection pooling — and any of those can blow up tail latency. [The OLTP vs OLAP split](https://aws.amazon.com/compare/the-difference-between-olap-and-oltp/) is essentially an admission that one engine cannot optimize for both; you pick one and bolt the other on with a replica or a warehouse.

### Stream processing

[Flink](https://flink.apache.org/) and [Kafka Streams](https://kafka.apache.org/documentation/streams/) make the trade-off explicit through checkpointing. Frequent checkpoints give low end-to-end latency but cost throughput. Infrequent checkpoints are the reverse. The default configuration is a guess; production tuning usually involves picking one to optimize and accepting the cost on the other.

### ML inference

A single GPU call has high latency relative to a CPU request but enormous throughput for batched inference. The classic production pattern is to expose a synchronous, low-throughput endpoint for interactive use and an asynchronous, high-throughput batching endpoint for bulk workloads. Same model, two deployment shapes.

### Edge and CDN systems

Latency to the user is bounded by physics. Throughput scales with how much you can cache at the edge. A well-tuned CDN can have single-digit-millisecond latency and millions of RPS at the same time — because the cache hit avoids the work. This is one of the rare cases where the trade-off genuinely disappears.

## Measuring Both, Honestly

You cannot optimize what you cannot measure, and you cannot measure either of these honestly without thinking about the other.

**For latency**, prefer histograms over averages. [HDR Histogram](https://github.com/HdrHistogram/HdrHistogram) and [Prometheus histograms](https://prometheus.io/docs/practices/histograms/) let you compute real percentiles. Report p50, p95, p99, and p99.9. Track the *maximum observed* too — it catches rare failures that averages smooth over.

**For throughput**, measure completed work per unit time, not requests-received. A system that accepts 100,000 requests/second but only completes 10,000/second has throughput of 10,000 — the other 90,000 are in a queue, and they are dragging latency through the roof.

**Watch both on the same dashboard.** This is the single most useful piece of advice in this post. If you have a graph of throughput and a graph of latency side by side, the shape of the curve will tell you almost everything: knee, cliff, saturation, recovery. Tools like [Grafana](https://grafana.com/) make this trivial; there is no excuse not to do it.

## Key Takeaways

- **Latency is per-request, throughput is per-second.** They are not the same number, and a system can be great at one and terrible at the other.
- **Little's Law binds them.** At fixed concurrency, latency and throughput trade off directly. Raising one without changing the other requires changing concurrency or doing less work per request.
- **Queueing theory is not optional.** As utilization approaches 100%, average wait time grows super-linearly. This is why "just a bit more load" produces "somehow 10x worse latency."
- **Caching is the rare win-win** because it reduces work per request, which helps both metrics at once. Every other optimization is a trade.
- **Measure percentiles, not averages,** and put latency and throughput on the same graph. The shape of the curve will diagnose problems faster than any alert.
- **Use backpressure and load shedding** instead of letting queues grow without bound. A rejected request is better than a 30-second timeout.

## Further Reading

- [Little's Law — Wikipedia](https://en.wikipedia.org/wiki/Little%27s_law)
- [The Tail at Scale — Jeffrey Dean and Luiz André Barroso, Communications of the ACM](https://cacm.acm.org/research/the-tail-at-scale/)
- [Designing Data-Intensive Applications — Martin Kleppmann](https://dataintensive.net/)
- [M/M/1 Queue — Wikipedia](https://en.wikipedia.org/wiki/M/M/1_queue)
- [HdrHistogram — Gil Tene](https://github.com/HdrHistogram/HdrHistogram)
- [Prometheus Histograms and Summaries](https://prometheus.io/docs/practices/histograms/)
- [Envoy Circuit Breaking Documentation](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/circuit_breaking)