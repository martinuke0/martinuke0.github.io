---
title: "Inside OpenTelemetry's Span Processor: Tail-Sampling and Adaptive Bucket Aggregations"
date: "2026-09-04T06:00:43.615"
draft: false
tags: ["opentelemetry", "observability", "sampling", "metrics", "distributed-tracing"]
description: "A deep dive into OpenTelemetry span processor design, covering tail-based sampling strategies and adaptive histogram bucket aggregations for production telemetry."
summary: "How modern span processors decide what to keep, what to drop, and how to bucket latency without lying to you. We unpack tail-sampling evaluators and adaptive bucket strategies used in OpenTelemetry Collector pipelines."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-opentelemetry.svg"
  alt: "Abstract visualization of telemetry data flowing through processor pipelines with sampling decision nodes."
  caption: ""
  relative: false
---

> **TL;DR** — A span processor is the unsung brain of an OpenTelemetry pipeline: it sees every span first, decides what survives tail-sampling, and aggregates what gets exported. Get the evaluators wrong and you keep 2% of your error traces. Get the histogram buckets wrong and your p99 dashboards quietly rot. This post walks through both, with patterns you can ship.

If you've ever stared at a Grafana dashboard wondering why the p99 latency on a perfectly healthy service looks like a saw blade, the answer is almost never "the service is broken." It's almost always that something upstream — usually a span processor — made a decision on your behalf without telling you. OpenTelemetry gives you a beautifully composable pipeline ([Collector architecture](https://opentelemetry.io/docs/collector/architecture/)) and then hands you a toolbox full of ways to subtly lie to your future self.

Two decisions matter more than any others in that pipeline: **what to keep** and **how to bucket it**. The first is the job of tail-sampling processors. The second is the job of the metrics processor and its histogram aggregation strategy. Both look deceptively simple. Both have shipped subtle bugs at companies you have heard of.

## The Span Processor in the Pipeline

A span is a unit of work. A processor is anything that transforms, filters, enriches, or routes spans. In the [OpenTelemetry Collector](https://github.com/open-telemetry/opentelemetry-collector), processors sit between receivers and exporters:

```text
receivers → processors → exporters
```

The two processors that matter most for this post are:

- **`tail_sampling_processor`** — sees the full trace, decides whether to keep it.
- **`metrics`** processor (specifically the histogram aggregation) — decides how to bucket numeric measurements into Prometheus-style metrics.

Both are "lossy" by design. A good span processor is one whose losses are deliberate, documented, and reversible through configuration — not accidental.

## Tail-Sampling: Decisions That Need the Whole Picture

Head sampling (the default) decides whether to keep a trace at the very first span. That's a 1% sample of 100% of traces, decided before you know whether the trace contains a 5xx error or a payment failure. It's fast and cheap, and it's wrong for almost every interesting question.

Tail sampling waits. It buffers spans, groups them by trace ID, and only makes a keep/drop decision when the trace is complete (or when a timeout fires). The [official tail sampling processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor) supports a policy-based model: you declare *policies* and the processor keeps any trace that matches any of them.

```yaml
processors:
  tail_sampling:
    decision_wait: 10s
    num_traces: 50000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: slow-traces
        type: latency
        latency: { threshold_ms: 2000 }
      - name: probabilistic
        type: probabilistic
        probabilistic: { sampling_percentage: 5 }
```

Three policies above, three different intents. The first is "never lose an error trace." The second is "keep the slow ones so we can find the cause." The third is "for everything else, keep 5% so we have volume statistics." This is the standard production shape, and it's worth understanding *why* each piece exists.

### Policy Composition and the OR Semantics

Policies in the tail sampler are OR-combined: a trace is kept if **any** policy says keep. That sounds obvious until you realize the consequences:

- A trace with one ERROR span and nine OK spans is kept by the `errors` policy — you retain the full context of the failure, including the upstream and downstream spans that were healthy. This is the entire point.
- A 1.8s trace with no errors is kept by `slow-traces` but dropped by `probabilistic` (which only decides on a per-trace hash). The OR semantic means the slower policy wins. Good.
- A fast, successful trace is dropped by the first two and sampled by the third at 5%. This is where you get your "baseline" — the traces you keep purely to compute rates and averages on healthy traffic.

A common mistake is to add an `and` policy combination assuming priority. There is no priority. If two policies conflict, both are evaluated independently. If you need priority, you implement it with multiple processors in series, not multiple policies in one.

### What the Evaluators Actually Look At

Each policy type is an *evaluator*. The [evaluator interface](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/processor/tailsamplingprocessor/internal/sampling/evaluator.go) receives a batch of spans that share a trace ID and returns a `Decision` (Sampled or NotSampled). The interesting evaluators:

- **`status_code`** — looks at the trace's overall status. Fast, cheap, high-signal. This is policy #1 in any sane config.
- **`latency`** — compares the trace duration against a threshold. Requires the full trace to arrive, which is why `decision_wait` exists.
- **`string_attribute`** — keeps traces that have a specific attribute, e.g. `http.target = "/api/checkout"`. Useful for canary cohorts.
- **`probabilistic`** — hash-based, deterministic, per-trace. Same trace ID → same decision across restarts. Use this if you need reproducible sampling for A/B analysis.
- **`composite`** — nested AND/OR/NOT. Where the real production logic lives.

A composite evaluator lets you express things like "keep traces where status is ERROR **or** (status is OK **and** latency > 2s **and** user.tier = 'premium')". This is how mature shops isolate VIP regression from background noise.

### The Memory Budget Problem

Tail sampling has a cost the docs mention but rarely emphasize: **the processor holds every in-flight trace in memory until the decision wait expires**. With `num_traces: 50000` and a 10s wait, you're buffering up to 50k traces of arbitrary depth. A single trace with 10,000 spans (think: a deeply batched job or a fan-out search) can pin a non-trivial amount of RAM.

The mitigations, in order of effectiveness:

1. **Drop trace IDs at the receiver** for known-noisy sources (e.g. health checks, `/metrics`, k8s liveness probes) using a `filter` processor *before* the tail sampler. This is the single biggest win most teams miss.
2. **Lower `num_traces` and add load-based shedding** — at the cost of dropping traces during spikes.
3. **Use the `load_based` sampler** as a pre-filter so the tail sampler only sees traces that already passed an upstream gate.

A realistic production setup has *two* sampling stages:

```yaml
processors:
  # Stage 1: cheap head sampling at the agent (sidecar or daemonset)
  probabilistic_sampler:
    sampling_percentage: 10

  # Stage 2: tail sampling at the gateway
  tail_sampling:
    decision_wait: 15s
    num_traces: 100000
    policies:
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
```

The 10% head sample keeps memory bounded; the tail sample makes the final decision. This is the architecture most large-scale teams converge on, and it matches the pattern described in the [Honeycomb tail-sampling guide](https://docs.honeycomb.io/manage-data-volume/tail-sampling/) and the [Grafana Agent sampling docs](https://grafana.com/docs/agent/latest/flow/reference/components/otelcol.processor.tail_sampling/).

## Adaptive Bucket Aggregations: Where p99s Go to Die

Now the harder problem. Suppose you decide to keep a trace. The trace contains numeric measurements: HTTP durations, DB query times, queue waits. You want to export these as Prometheus histograms so Grafana can compute p50/p90/p99. The question is: **how do you bucket the values?**

A "bucket" is a counter that says "I have seen N values in the range (a, b]." Prometheus computes p99 by linear interpolation across the cumulative bucket counts. The math is simple; the consequences of choosing bad bucket boundaries are severe.

### The Problem With Default Buckets

The default Prometheus histogram buckets are `[.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10]`. These are tuned for the latency distribution of a 2014-era web request. In 2026, with services doing async work, batched DB queries, and cold-start penalties, those boundaries routinely miss the actual mass of the distribution. You end up with a histogram where 70% of values fall in the `+Inf` bucket, which means **Prometheus reports the p99 as a literal placeholder** — it just shows the upper bound of the last finite bucket.

OpenTelemetry's metrics SDK exposes explicit bucket boundaries through the [ExplicitBucketHistogram aggregation](https://opentelemetry.io/docs/specs/otel/metrics/data-model/#histogram), and the Collector can also translate OTel histograms into Prometheus format via the [prometheus exporter](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/exporter/prometheusexporter). The choice of boundaries is yours.

### Static Buckets: The "Just Pick Numbers" Approach

Most teams pick static buckets that look plausible and forget about them. A common pattern:

```yaml
processors:
  metrics:
    histogram: explicit
    explicit:
      buckets: [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30]
```

This works until it doesn't. The day a vendor rolls out a feature that pushes p99 from 800ms to 12s, every histogram query in your dashboards returns a different number depending on which bucket happens to contain the bulk of the new data. Engineers start arguing about whether the service got slower. The service did not get slower — the bucket boundaries are now lying to you.

### Adaptive Buckets: Let the Distribution Tell You

An **adaptive** bucket strategy observes the incoming values and adjusts boundaries to keep quantile estimation error bounded. The two most common shapes in production:

1. **Log-linear exponential growth** — bucket boundaries at `b * r^i` for some base `b` and ratio `r`. Used by HdrHistogram and by the [t-digest](https://github.com/tdunning/t-digest) when configured with exponential centroids. Simple, predictable, and works well when you know roughly the order of magnitude of values.
2. **t-digest** — a probabilistic data structure that keeps more centroids where the data is dense. Excellent for highly skewed distributions, which is exactly what latency looks like in practice. The [Prometheus client_golang](https://prometheus.io/docs/practices/histograms/#errors-of-quantile-estimation) and the [OpenTelemetry Go SDK](https://github.com/open-telemetry/opentelemetry-go-contrib/tree/main/otelconf) both have native t-digest implementations.

A t-digest doesn't have "buckets" in the Prometheus sense — it has *centroids*. To export to Prometheus, you have to convert. This is where most production systems make a choice:

- **Export native histograms.** Prometheus 2.40+ supports [native histograms](https://prometheus.io/docs/prometheus/latest/feature_flags/#native-histograms), which is a sparse representation of bucket counts that doesn't require a fixed bucket schema. The OTel Collector's `prometheus` exporter can emit these if you enable the feature flag on the Prometheus server side.
- **Convert to classic buckets at export time.** Pick a fixed bucket schema and quantize the t-digest into it. The OTel Collector doesn't do this conversion out of the box; you typically run a small sidecar or use a downstream service (Grafana Mimir's [metrics-generator](https://grafana.com/docs/mimir/latest/operators-guide/architecture/components/metrics-generator/) does this) to materialize classic histograms from the native ones.

### Patterns in Production: What Actually Ships

Three patterns recur in teams that have gotten this right:

**Pattern 1: Dual emission.** Emit both classic and native histograms from the same source. Dashboards that don't yet support native histograms still work; new dashboards can opt into higher resolution. The [Prometheus migration guide](https://prometheus.io/docs/prometheus/latest/feature_flags/#native-histograms) walks through this in detail.

**Pattern 2: Per-endpoint buckets.** Don't use one bucket schema for the whole service. Use route- or endpoint-specific bucket boundaries, configured via the OTel Collector's `resource` processor. A `/healthz` endpoint doesn't need microsecond resolution; a `/payments/charge` endpoint needs sub-millisecond resolution in the low end and minute-scale resolution in the high end. The [OTel resource processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/resourceprocessor) lets you attach attributes that downstream bucket selection can key on.

**Pattern 3: A periodic re-bucketing job.** Keep the streaming aggregation cheap (e.g. t-digest), and run a periodic job — daily or hourly — that examines the recent distribution and writes a new bucket schema for the next window. This is what [Vector](https://vector.dev/docs/) and [Veneur](https://github.com/stripe/veneur) do internally. The downside is that your dashboards' bucket boundaries change over time, so any historical comparison needs to be bucket-aware. The upside is that your p99 numbers are correct.

### A Note on "Correctness" of Quantile Estimation

A common misconception: "more buckets = better." The math, as laid out in the [Prometheus histogram docs](https://prometheus.io/docs/practices/histograms/#errors-of-quantile-estimation), says something more specific. Quantile estimation error is bounded by the bucket width around the quantile of interest. If you put 50 buckets between 0 and 1 second, your p99 estimate at 800ms is excellent — but you've wasted all your resolution on a range that doesn't contain p99.

The right answer: **allocate resolution where the mass is**. That's what t-digest does automatically and what static buckets fail to do. If you must use static buckets (and many Prometheus operators still require them), the next-best thing is to log your actual p99 once a quarter and adjust the bucket boundaries around it. Boring, manual, but it works.

## Putting It Together: A Real Pipeline

A representative production pipeline, combining both halves of this post, looks like this:

```yaml
receivers:
  otlp:
    protocols: { grpc: {}, http: {} }

processors:
  # 1. Drop noise before it costs memory
  filter/health:
    metrics:
      exclude:
        match_type: regexp
        metric_names: [".*_health_.*", "http_server_request_duration_seconds_bucket"]
    spans:
      exclude:
        match_type: regexp
        attributes: ["http.target"]

  # 2. Head sample to bound load
  probabilistic_sampler:
    sampling_percentage: 10

  # 3. Tail sample for the keepers
  tail_sampling:
    decision_wait: 15s
    num_traces: 75000
    policies:
      - name: errors
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: slow
        type: latency
        latency: { threshold_ms: 2000 }
      - name: vip
        type: string_attribute
        string_attribute:
          key: user.tier
          values: ["premium", "enterprise"]
      - name: baseline
        type: probabilistic
        probabilistic: { sampling_percentage: 2 }

  # 4. Aggregate into histograms with native + classic emission
  batch:
    timeout: 10s
    send_batch_size: 1024

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
    # native histograms require the receiver to be on Prometheus 2.40+
    add_metric_suffixes: true
  otlp/backend:
    endpoint: "ingest.example.com:4317"

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [filter/health, probabilistic_sampler, tail_sampling, batch]
      exporters: [otlp/backend]
    metrics:
      receivers: [otlp]
      processors: [filter/health, batch]
      exporters: [prometheus, otlp/backend]
```

Note the asymmetric pipeline: traces go through *both* sampling stages; metrics go through filtering and batching but not tail sampling, because metrics are already aggregated and don't have the same "wait for the full picture" requirement. This asymmetry is intentional, and conflating the two pipelines is one of the more common architectural mistakes in greenfield OTel deployments.

## Key Takeaways

- **Tail sampling is a memory budget in disguise.** The `decision_wait` and `num_traces` settings aren't just config — they define how much of your cluster's RAM is dedicated to "thinking before exporting." Filter aggressively before this stage.
- **Policy composition is OR-only.** If you need priority, use multiple processors in series, not multiple policies in one. Composite evaluators handle the AND/OR/NOT logic within a single decision.
- **Default Prometheus buckets are a 2014 default.** Don't use them unmodified. Either use native histograms, or pick buckets that bracket your real p99.
- **t-digest is the right tool for latency.** It's adaptive, it's bounded-memory, and it concentrates resolution where the data is dense. Native histograms in Prometheus 2.40+ let you actually use it.
- **Per-endpoint bucket strategies** outperform a single global bucket schema whenever your service has heterogeneous workloads (sync APIs, async jobs, batch).
- **Buckets are a contract with your future dashboards.** Changing them silently is a form of breaking change. Document them, version them, and treat them as part of your service's observability API.

## Further Reading

- [OpenTelemetry Collector Architecture](https://opentelemetry.io/docs/collector/architecture/)
- [Tail Sampling Processor (Collector Contrib)](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor)
- [OpenTelemetry Metrics Data Model — Histograms](https://opentelemetry.io/docs/specs/otel/metrics/data-model/#histogram)
- [Prometheus Native Histograms](https://prometheus.io/docs/prometheus/latest/feature_flags/#native-histograms)
- [Quantile Estimation Error in Prometheus Histograms](https://prometheus.io/docs/practices/histograms/#errors-of-quantile-estimation)
- [t-digest: A New Data Structure for Accurate Quantile Estimation](https://github.com/tdunning/t-digest)
- [Grafana Mimir Metrics Generator](https://grafana.com/docs/mimir/latest/operators-guide/architecture/components/metrics-generator/)
- [Honeycomb Tail Sampling Guide](https://docs.honeycomb.io/manage-data-volume/tail-sampling/)