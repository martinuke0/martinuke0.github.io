---
title: "Probabilistic Data Structures for High‑Cardinality Estimation in Distributed Observability Streams"
date: "2026-05-13T05:00:31.111"
draft: false
tags: ["observability","cardinality","probabilistic-data-structures","distributed-systems","stream-processing"]
description: "Explore how HyperLogLog, Linear Counting, and Count‑Min Sketch enable efficient high‑cardinality estimation in distributed observability pipelines, balancing accuracy, memory, and latency."
summary: "A deep dive into probabilistic sketches for cardinality estimation, covering theory, implementation, and operational best practices for modern observability streams."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-probabilistic-data-structures-for-highcardinality-estimation-in-distributed-observability-streams.svg"
  alt: "Diagram of distributed data streams feeding probabilistic sketches."
  caption: ""
  relative: false
---

> **TL;DR** — Probabilistic sketches such as HyperLogLog, Linear Counting, and Count‑Min Sketch let you estimate millions of unique identifiers with kilobytes of memory. When integrated into a distributed observability stack, they provide near‑real‑time cardinality insights without overwhelming network or storage budgets.

Observability platforms constantly ingest telemetry—traces, logs, metrics—from thousands of services. A recurring challenge is **high‑cardinality estimation**: counting distinct request IDs, error codes, or user identifiers across a globally distributed mesh. Traditional set storage scales linearly with the number of uniques, quickly exhausting memory and bandwidth. Probabilistic data structures (sketches) offer a compelling alternative: they sacrifice a bounded error for orders‑of‑magnitude savings in space and compute, making them ideal for streaming pipelines that must remain low‑latency and fault‑tolerant.

## Why High Cardinality Matters

1. **Capacity planning** – Knowing how many distinct clients hit an endpoint guides autoscaling decisions.  
2. **Anomaly detection** – Sudden spikes in unique error codes often signal a new failure mode.  
3. **Billing & quota enforcement** – Cloud providers charge per unique API key or device; accurate counts prevent over‑billing.  

In a distributed environment, each node only sees a fragment of the total stream. If every node stores a full hash set, the aggregate memory footprint becomes prohibitive. Moreover, transmitting raw sets to a central aggregator would saturate the network. Sketches solve both problems by summarizing locally and merging efficiently.

## Core Probabilistic Sketches

### HyperLogLog (HLL)

HyperLogLog estimates the cardinality of a multiset using the distribution of leading zeros in hashed values. Its core formula:

\[
\text{estimate} = \alpha_m \cdot m^2 \cdot \bigg(\sum_{i=1}^{m} 2^{-M[i]}\bigg)^{-1}
\]

where *m* = 2^p registers, *M[i]* stores the max observed zero run length, and αₘ is a bias‑correction constant.

*Key properties*  

| Property | Typical Value |
|----------|---------------|
| Memory   | 1.5 KB for ~2 % error |
| Merge    | Register‑wise max |
| Update   | O(1) per element |

HLL shines when you need **sub‑percent relative error** on billions of uniques. Most open‑source observability stacks (e.g., Prometheus’s `hll` function) expose it natively.

#### Python Example

```python
# Install with: pip install datasketch
from datasketch import HyperLogLog

hll = HyperLogLog(p=14)  # 2^14 ≈ 16 384 registers → ~0.8 % error
for uid in stream_of_user_ids():
    hll.update(uid.encode('utf‑8'))

print(f"Estimated uniques: {int(hll.count())}")
```

### Linear Counting (LC)

Linear Counting predates HLL and uses a bitmap of *m* bits. Each incoming element hashes to a bit index; the bit is set to 1. Cardinality is inferred from the proportion of zero bits:

\[
\hat{n} = -m \cdot \ln\bigg(\frac{V}{m}\bigg)
\]

where *V* is the number of zero bits remaining.

*When to use*  

- **Very low cardinalities** (tens of thousands) where HLL’s bias correction overhead isn’t worth it.  
- Environments where **deterministic** behavior is preferred; LC’s estimate is a direct function of observed zeros.

#### Bash Demonstration with `hyperloglog` CLI (for LC)

```bash
# Generate a bitmap of 1 MiB (8 388 608 bits)
dd if=/dev/zero bs=1M count=1 of=bitmap.bin
# Simulate setting bits for 10 000 hashed IDs
python3 set_bits.py bitmap.bin 10000
# Compute estimate using a tiny utility
lc_estimate=$(python3 lc_estimate.py bitmap.bin)
echo "Linear Counting estimate: $lc_estimate"
```

*(The helper scripts are trivial; they hash IDs to bit positions and count zeros.)*

### Count‑Min Sketch (CMS)

While CMS is primarily a frequency estimator, it can be repurposed for **distinct‑value approximations** by tracking a “presence” flag per hash bucket. More commonly, it complements HLL by identifying heavy‑hit keys that dominate a stream.

*Key parameters*  

- **Depth (d)** = number of hash functions → controls confidence (δ).  
- **Width (w)** = number of counters per row → controls error (ε).  

Typical configuration for 1 % error with 99 % confidence: d = 7, w ≈ 2 000.

#### Go Example Using Apache DataSketches

```go
package main

import (
    "fmt"
    "github.com/apache/datasketches-go/cms"
)

func main() {
    sketch := cms.NewCountMinSketch(0.01, 0.99) // ε=1%, δ=1%
    for _, id := range streamOfIDs() {
        sketch.Update([]byte(id))
    }
    fmt.Printf("Estimated frequency of key X: %d\n", sketch.Estimate([]byte("X")))
}
```

## Deploying Sketches in Distributed Observability

### Data Ingestion Pipelines

Most observability stacks rely on **message brokers** (Kafka, Pulsar) or **stream processing frameworks** (Flink, Beam). Sketches can be instantiated at three logical layers:

1. **Edge collector** – Each agent (e.g., OpenTelemetry Collector) maintains a local sketch per metric dimension (service + endpoint).  
2. **Stream processor** – Stateless operators receive raw telemetry, update sketches, and emit *compact sketch objects* downstream.  
3. **Aggregation tier** – A central service merges sketches from all workers, producing a global view.

#### Example: Flink Operator (Java)

```java
public class HllOperator extends ProcessFunction<TelemetryEvent, SketchMessage> {
    private transient HyperLogLog hll;

    @Override
    public void open(Configuration parameters) {
        // 2^15 registers → ~0.4 % error
        hll = new HyperLogLog(15);
    }

    @Override
    public void processElement(TelemetryEvent event, Context ctx, Collector<SketchMessage> out) {
        hll.offer(event.getTraceId().getBytes(StandardCharsets.UTF_8));
        // Emit every 5 seconds
        if (ctx.timerService().currentProcessingTime() % 5000 == 0) {
            out.collect(new SketchMessage(hll.getBytes()));
            hll.clear(); // reset for next window
        }
    }
}
```

The `SketchMessage` payload is a byte array that can be merged by the downstream aggregator using a simple register‑wise max.

### State Management & Merging

Merging is the linchpin for distributed correctness. For HLL and LC, merging is **commutative and associative**, enabling:

- **Exactly‑once semantics** – Even if a node’s sketch is replayed, the final estimate remains unchanged.  
- **Partial failure recovery** – Lost sketches can be recomputed from the raw stream without affecting the global count.

In practice, store sketches in a **key‑value store** (e.g., RocksDB, Redis) keyed by the dimension they represent. Periodic background jobs read, merge, and write back the combined sketch.

#### Pseudocode for Merge Loop

```python
def merge_all_sketches(redis_client, dimension):
    keys = redis_client.scan_iter(match=f"{dimension}:*")
    merged = HyperLogLog(p=14)
    for key in keys:
        raw = redis_client.get(key)
        merged.merge(HyperLogLog.from_bytes(raw))
    redis_client.set(f"{dimension}:merged", merged.to_bytes())
```

### Accuracy vs. Resource Trade‑offs

| Sketch | Memory (KB) | Typical Error | Merge Cost | Ideal Use‑case |
|--------|------------|---------------|------------|----------------|
| HLL    | 1.5–12      | 0.5 %–2 %      | O(m) register max | Global distinct count |
| LC     | 0.5–2       | 1 %–5 % (when < 10 % fill) | O(m) bitmap OR | Low‑cardinality per‑endpoint |
| CMS    | 4–20        | ε (user‑defined) | O(d·w) add | Heavy‑hit detection + approximate frequencies |

When bandwidth is the primary constraint (e.g., edge devices on cellular), **LC** may be preferable despite higher error because the bitmap can be compressed efficiently (run‑length encoding). Conversely, for cloud‑native microservices with abundant memory, **HLL** provides the best balance of precision and merge simplicity.

## Operational Considerations

### Monitoring Sketch Health

Even probabilistic structures can degrade:

- **Register saturation** – HLL registers hit the maximum value, inflating error.  
- **Bitmap overflow** – LC’s zero‑bit proportion drops below 5 %, causing the logarithmic estimator to diverge.

Expose internal metrics via Prometheus:

```yaml
# Example Prometheus exporter config (Go)
- job_name: 'sketch_aggregator'
  static_configs:
    - targets: ['localhost:9100']
  metrics_path: /metrics
```

Instrumented metrics:

```go
prometheus.NewGaugeVec(
    prometheus.GaugeOpts{
        Name: "hll_registers_max",
        Help: "Maximum register value observed in the HLL sketch.",
    },
    []string{"dimension"},
)
```

Alert on thresholds (e.g., max register > 30) to trigger a **re‑sketch** cycle.

### Handling Skew and Hot Keys

Skewed key distributions (a single user ID generating 80 % of events) can bias estimates. Mitigation strategies:

1. **Key salting** – Append a random salt before hashing, then de‑duplicate on the aggregation side.  
2. **Hybrid sketch** – Combine CMS (to isolate hot keys) with HLL (for the long tail).  
3. **Adaptive register width** – Dynamically increase *p* for dimensions that exceed a cardinality threshold.

#### Adaptive Sketch Pseudocode

```python
def adapt_sketch(sketch, current_estimate):
    if current_estimate > 1_000_000 and sketch.p < 18:
        # Upgrade to higher precision
        new_sketch = HyperLogLog(p=sketch.p + 2)
        new_sketch.merge(sketch)
        return new_sketch
    return sketch
```

### Persistence and Versioning

Sketch formats evolve. Store **version tags** alongside the byte payload:

```json
{
  "version": "hll-v1",
  "payload": "BASE64_ENCODED_BYTES"
}
```

When upgrading libraries, implement a **forward‑compatible migration** that reads older versions, re‑hashes elements if necessary, and writes the new format. This prevents silent corruption when the hash function changes.

## Key Takeaways

- Probabilistic sketches (HLL, LC, CMS) compress massive distinct‑value problems into kilobytes while providing bounded error guarantees.  
- Their **merge‑friendly** nature makes them perfect for distributed observability pipelines that must aggregate across many edge nodes.  
- Choose the sketch based on cardinality range, error tolerance, and resource constraints: HLL for general‑purpose high‑precision counting, LC for low‑cardinality, CMS for heavy‑hit detection.  
- Instrument sketch health metrics (register saturation, bitmap fill) and set alerts to avoid silent degradation.  
- Adopt adaptive precision and hybrid designs to cope with skewed traffic patterns common in production microservice environments.

## Further Reading

- [HyperLogLog algorithm – original paper by Flajolet et al.](https://doi.org/10.1007/978-3-540-79228-4_31)  
- [Apache DataSketches – library documentation and tutorials](https://datasketches.apache.org)  
- [Prometheus documentation on cardinality and sketch functions](https://prometheus.io/docs/prometheus/latest/querying/functions/#hyperloglog)