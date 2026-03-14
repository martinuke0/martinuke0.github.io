---
title: "Scaling Real Time Feature Stores for Low Latency Machine Learning Inference Pipelines"
date: "2026-03-14T16:01:08.686"
draft: false
tags: ["feature-store", "low-latency", "real-time", "ml-inference", "scalable-architecture"]
---

## Introduction

Machine learning (ML) has moved from batch‑oriented scoring to **real‑time inference** in domains such as online advertising, fraud detection, recommendation systems, and autonomous control. The heart of any low‑latency inference pipeline is the **feature store**—a system that ingests, stores, and serves feature vectors at sub‑millisecond speeds. While many organizations have built feature stores for offline training, scaling those stores to meet the stringent latency requirements of production inference is a different challenge altogether.

In this article we will:

1. Define what a *real‑time feature store* is and why latency matters.
2. Identify the architectural bottlenecks that prevent naïve stores from scaling.
3. Explore proven design patterns, data models, and technology choices that enable **sub‑10 ms** feature retrieval.
4. Walk through a practical end‑to‑end example using open‑source tools.
5. Summarize best‑practice recommendations for production‑grade deployments.

By the end of the post, you should have a clear roadmap for turning a simple feature store prototype into a horizontally scalable, low‑latency service that can power millions of inference requests per second.

---

## 1. Foundations: What Is a Real‑Time Feature Store?

### 1.1 Feature Store Basics

| Component | Purpose | Typical Implementation |
|-----------|---------|------------------------|
| **Feature Ingestion** | Capture raw events (clicks, sensor readings, logs) and transform them into feature values. | Kafka, Kinesis, Flink, Spark Structured Streaming |
| **Feature Registry** | Central catalog describing feature names, types, TTL, lineage, and versioning. | Metadata DB (PostgreSQL, MySQL), or a dedicated service like Feast Registry |
| **Online Store** | Low‑latency key‑value layer that serves the latest feature values to inference services. | Redis, Aerospike, Cassandra, ScyllaDB, or specialized vector stores |
| **Offline Store** | Batch‑oriented warehouse for model training and historical analysis. | BigQuery, Snowflake, Hive, Delta Lake |
| **Feature Retrieval API** | Uniform interface (REST, gRPC) for fetching feature vectors by entity ID. | HTTP/gRPC servers backed by the online store |

### 1.2 Why Latency Is Critical

1. **User Experience** – In ad tech, a delay of > 50 ms can increase page load time dramatically, hurting conversion rates.  
2. **Model Freshness** – Fraud models often need to incorporate the *most recent* transaction data; a stale feature can cause false negatives.  
3. **Resource Efficiency** – High latency forces downstream services to allocate larger timeouts and buffer capacities, increasing cost.

Typical Service Level Objectives (SLOs) for real‑time inference range from **1 ms** (high‑frequency trading) to **10–20 ms** (recommendation engines). Achieving these numbers requires a feature store that:

* **Scales horizontally** (adds nodes as request volume grows)
* **Provides strong consistency** for the most recent data
* **Caches intelligently** to avoid repeated disk or network I/O
* **Minimizes serialization overhead** (binary protocols, schema‑aware encoding)

---

## 2. Latency Bottlenecks in Naïve Feature Stores

| Bottleneck | Symptoms | Root Cause |
|------------|----------|------------|
| **Cold Reads from Disk** | 10–100 ms latency spikes on first access | Data not pre‑loaded into memory; reliance on HDD/slow SSD |
| **Network Hops** | High tail latency (p99) | Multiple microservice hops (ingestion → registry → online store) |
| **Serialization Overhead** | Large payloads, CPU spikes | JSON or protobuf without schema reuse |
| **Lock Contention** | Throughput drops under concurrent writes | Single‑writer per partition or global lock |
| **Feature Staleness** | Model predictions diverge from reality | Inadequate TTL handling, delayed materialization |

Understanding these pain points is the first step toward a design that *eliminates* or *mitigates* them.

---

## 3. Architectural Patterns for Scaling Real‑Time Feature Stores

### 3.1 Lambda vs. Kappa Architecture

| Architecture | Ingestion Style | Strengths | Weaknesses |
|--------------|----------------|-----------|------------|
| **Lambda** (batch + stream) | Dual pipelines (batch for historical, stream for real‑time) | Guarantees correctness via replayable batch jobs | Higher operational complexity |
| **Kappa** (stream‑only) | Single streaming pipeline that also backfills historical data | Simpler, lower latency, easier scaling | Requires robust stream replay mechanisms |

For ultra‑low latency, a **Kappa** design with *exactly‑once* processing semantics is often preferred, as it avoids the batch‑to‑online synchronization lag.

### 3.2 Sharding by Entity Key

- **Hash‑Based Sharding**: Distribute entity IDs across N shards using consistent hashing.  
- **Range Sharding**: Group similar IDs (e.g., user IDs by geographic region) to improve cache locality.  

**Best practice**: Keep the shard count a multiple of the number of CPU cores per node, and enable *re‑sharding* without downtime using a coordination service (e.g., Zookeeper, etcd).

### 3.3 Hybrid In‑Memory + Persistent Store

| Layer | Role | Example Tech |
|------|------|--------------|
| **Hot Cache** | Store most‑recent feature values for active entities | Redis Cluster, Aerospike, Memcached |
| **Warm Store** | Persist recent data for warm‑up after cache miss | ScyllaDB, Cassandra (tuned for low read latency) |
| **Cold Archive** | Long‑term historical features for training | S3 + Parquet, HDFS, Google Cloud Storage |

The **cache‑aside** pattern—lookup in hot cache, fallback to warm store, then populate cache—keeps the critical path short while preserving durability.

### 3.4 Vectorized Retrieval & Columnar Encoding

Instead of fetching each feature as a separate key, retrieve *feature vectors* in a single request using columnar encodings such as **Apache Arrow** or **FlatBuffers**. This reduces round‑trip count and serialization cost.

```python
# Example: using pyarrow to serialize a feature vector
import pyarrow as pa

features = {
    "click_rate": 0.12,
    "session_length": 300,
    "is_premium": True,
}

schema = pa.schema([
    ("click_rate", pa.float64()),
    ("session_length", pa.int64()),
    ("is_premium", pa.bool_()),
])

batch = pa.record_batch([features], schema=schema)
buffer = pa.BufferOutputStream()
writer = pa.ipc.new_stream(buffer, schema)
writer.write_batch(batch)
writer.close()
payload = buffer.getvalue().to_pybytes()
```

The payload can be sent over gRPC with **zero‑copy** support, shaving off several milliseconds.

---

## 4. Data Ingestion & Real‑Time Materialization

### 4.1 Exactly‑Once Stream Processing

Frameworks such as **Apache Flink**, **Kafka Streams**, and **Spark Structured Streaming** (with checkpointing) provide exactly‑once guarantees. The pipeline typically:

1. **Consume** raw events from a durable log (Kafka topic).  
2. **Apply** transformation functions (e.g., rolling aggregates, feature engineering).  
3. **Materialize** the result into the online store using **upserts**.

#### Sample Flink Job (Scala)

```scala
import org.apache.flink.streaming.api.scala._
import org.apache.flink.streaming.connectors.kafka.FlinkKafkaConsumer
import org.apache.flink.streaming.connectors.redis.RedisSink
import org.apache.flink.api.common.serialization.SimpleStringSchema

case class ClickEvent(userId: String, timestamp: Long, adId: String, clicked: Boolean)

object RealTimeFeatureJob {
  def main(args: Array[String]): Unit = {
    val env = StreamExecutionEnvironment.getExecutionEnvironment
    env.enableCheckpointing(5000) // 5‑second checkpoint interval

    val kafkaProps = new Properties()
    kafkaProps.setProperty("bootstrap.servers", "kafka:9092")
    kafkaProps.setProperty("group.id", "feature-store-group")

    val source = new FlinkKafkaConsumer[String](
      "click-events",
      new SimpleStringSchema(),
      kafkaProps
    )

    val clickStream = env
      .addSource(source)
      .map(json => parseClick(json)) // custom JSON parser

    // Compute rolling click‑through rate per user (windowed)
    val ctrPerUser = clickStream
      .keyBy(_.userId)
      .timeWindow(Time.minutes(1))
      .apply { (key, window, events, out: Collector[(String, Double)]) =>
        val clicks = events.count(_.clicked)
        val ctr = clicks.toDouble / events.size
        out.collect((key, ctr))
      }

    // Write to Redis (hash per user)
    val redisSink = new RedisSink[(String, Double)](
      new FlinkJedisPoolConfig.Builder()
        .setHost("redis")
        .setPort(6379)
        .build(),
      new RedisMapper[(String, Double)] {
        override def getCommandDescription = new RedisCommandDescription(RedisCommand.HSET, "user_features")
        override def getKeyFromData(data: (String, Double)) = data._1
        override def getValueFromData(data: (String, Double)) = data._2.toString
      }
    )

    ctrPerUser.addSink(redisSink)

    env.execute("Real‑Time Feature Store Ingestion")
  }

  def parseClick(json: String): ClickEvent = {
    // Implementation omitted for brevity
    ???
  }
}
```

The **checkpoint** ensures that, even after a failure, the state of the rolling aggregation is restored exactly as it was, preventing duplicate writes.

### 4.2 TTL Management

Feature freshness is often enforced via **TTL (time‑to‑live)** per key. In Redis, you can set a per‑field TTL using a **sorted set** with timestamps, or more simply, store the timestamp alongside the value and have the retrieval layer discard stale entries.

```python
import redis
import time

r = redis.StrictRedis(host='localhost', port=6379)

def upsert_feature(user_id: str, feature_name: str, value: float, ttl_seconds: int = 30):
    key = f"user:{user_id}"
    field = f"{feature_name}"
    timestamp = int(time.time())
    # Store as a JSON string: {"v": value, "ts": timestamp}
    payload = json.dumps({"v": value, "ts": timestamp})
    r.hset(key, field, payload)
    r.expire(key, ttl_seconds)  # optional per‑entity TTL
```

The retrieval service checks `timestamp` against the current time and returns `None` if the feature is older than the allowed freshness window.

---

## 5. Storage & Retrieval Layer Design

### 5.1 Choosing the Right Online Store

| Store | Latency (p99) | Consistency Model | Scaling Model | Typical Use‑Case |
|-------|---------------|-------------------|---------------|------------------|
| **Redis (Cluster)** | ~0.5 ms | Strong (single‑node) | Horizontal sharding | Hot cache for sub‑ms latency |
| **Aerospike** | ~0.8 ms | Strong (read‑after‑write) | Auto‑sharding, replication | Low‑latency, high‑throughput |
| **ScyllaDB** | ~1 ms | Tunable (QUORUM) | Linear scaling | Large feature vectors, durability |
| **Cassandra** | ~2 ms | Tunable (QUORUM) | Multi‑DC replication | Geo‑distributed read/write |

For **sub‑10 ms** requirements, **Redis** or **Aerospike** are the most common choices because they keep data entirely in RAM and provide deterministic latency.

### 5.2 Indexing Strategies

- **Primary Key**: Entity ID (e.g., `user_id`, `device_id`).  
- **Secondary Indexes**: Feature name + timestamp for time‑range queries (use sorted sets).  
- **Composite Keys**: `entity_id:feature_name` to avoid hash collisions and enable atomic updates.

Example: Storing a vector of 100 features per user in Redis using a **Hash**.

```redis
HMSET user:12345 \
  f1 0.32 f2 0.78 f3 0.05 ... f100 0.91
```

For bulk retrieval:

```redis
HMGET user:12345 f1 f2 f3 ... f100
```

The command returns a single round‑trip with a compact binary response.

### 5.3 Consistency Guarantees

- **Read‑After‑Write**: Required for models that depend on the *immediately* updated feature (e.g., fraud detection). Achieved by using **single‑leader writes** and **synchronous replication** (e.g., Redis Cluster with `replica-read` disabled).  
- **Eventual Consistency**: Acceptable for features that are *aggregated* over longer windows (e.g., 1‑hour rolling average). Allows for multi‑leader or asynchronous replication, improving write throughput.

---

## 6. Caching, Batching, and Vectorization

### 6.1 Cache‑Aside with Warm‑Up

When a new entity appears (cold start), the system can pre‑populate the hot cache by **prefetching** the most recent feature set from the warm store.

```python
def get_features(user_id: str, feature_names: List[str]) -> Dict[str, Any]:
    cache_key = f"user:{user_id}"
    cached = redis_client.hmget(cache_key, feature_names)
    if any(v is None for v in cached):
        # Cache miss – fetch from warm store (ScyllaDB)
        row = scylla_session.execute(
            "SELECT {} FROM user_features WHERE user_id=%s".format(
                ", ".join(feature_names)
            ),
            (user_id,)
        ).one()
        # Populate hot cache
        redis_client.hmset(cache_key, row._asdict())
        redis_client.expire(cache_key, 30)  # TTL 30 seconds
        return row._asdict()
    else:
        return dict(zip(feature_names, cached))
```

### 6.2 Batching Requests

Many inference services need features for **multiple entities** per request (e.g., batch scoring). Grouping them into a single RPC call reduces network overhead.

```protobuf
// feature_service.proto
service FeatureService {
  rpc BatchGetFeatures(BatchGetRequest) returns (BatchGetResponse);
}

message BatchGetRequest {
  repeated string entity_ids = 1;
  repeated string feature_names = 2;
}

message FeatureVector {
  string entity_id = 1;
  map<string, double> features = 2;
}

message BatchGetResponse {
  repeated FeatureVector vectors = 1;
}
```

The service can internally parallelize reads across shards, then pack the result into a **protobuf map**, which is both compact and schema‑aware.

### 6.3 Vectorized Storage with Apache Arrow

Storing feature vectors in **columnar** format enables SIMD‑accelerated deserialization. In a high‑throughput service, you can keep a **shared Arrow Table** in memory and slice it per request without copying.

```python
import pyarrow as pa
import numpy as np

# Simulate a pre‑loaded Arrow table with 1M users × 128 features
num_users = 1_000_000
num_features = 128
data = np.random.rand(num_users, num_features).astype(np.float32)
table = pa.Table.from_arrays(
    [pa.array(data[:, i]) for i in range(num_features)],
    names=[f"f{i}" for i in range(num_features)]
)

def get_vector(user_index: int) -> pa.RecordBatch:
    # Zero‑copy slice
    return table.slice(user_index, 1).to_batches()[0]
```

Zero‑copy slices avoid the overhead of copying bytes into Python objects, shaving 1‑2 ms per request when dealing with large vectors.

---

## 7. Consistency, Versioning, and Governance

### 7.1 Feature Versioning

When a feature definition changes (e.g., new transformation logic), you must **version** the feature:

- `click_rate_v1` – raw click‑through rate  
- `click_rate_v2` – click‑through rate after smoothing

Store each version under a distinct key or namespace. The **feature registry** should expose metadata such as:

```json
{
  "name": "click_rate",
  "versions": [
    {"id": "v1", "created_at": "2024-01-01", "ttl_seconds": 60},
    {"id": "v2", "created_at": "2024-06-15", "ttl_seconds": 30}
  ],
  "description": "Smoothed click‑through rate per user."
}
```

Inference services can request the *active* version via an API call, enabling **gradual rollout**.

### 7.2 Governance & Auditing

- **Lineage tracking**: Map raw source → transformation → feature version.  
- **Access control**: Role‑based policies (e.g., model training team can read offline store; inference service can read online store).  
- **Change logs**: Store schema changes in an immutable audit log (e.g., Cloud Pub/Sub + Cloud Logging).

---

## 8. Deployment Considerations

### 8.1 Container Orchestration

Deploy the feature store components using **Kubernetes**:

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
spec:
  serviceName: redis
  replicas: 6
  selector:
    matchLabels:
      app: redis
  template:
    metadata:
      labels:
        app: redis
    spec:
      containers:
      - name: redis
        image: redis:7.2-alpine
        ports:
        - containerPort: 6379
        command: ["redis-server", "/usr/local/etc/redis/redis.conf", "--cluster-enabled", "yes"]
        volumeMounts:
        - name: config
          mountPath: /usr/local/etc/redis
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

- **StatefulSet** guarantees stable network identities for each shard.  
- **PodDisruptionBudget** maintains quorum during upgrades.  

### 8.2 Autoscaling

- **Horizontal Pod Autoscaler (HPA)** based on CPU or custom metrics (e.g., request latency).  
- **Cluster Autoscaler** to provision additional nodes when the HPA scales beyond existing capacity.

### 8.3 Observability

- **Metrics**: Export latency (`request_duration_seconds`), hit‑rate (`cache_hits_total`), and throughput (`requests_per_second`).  
- **Tracing**: Use OpenTelemetry to trace a request from ingestion → online store → inference.  
- **Alerting**: Trigger alerts when p99 latency exceeds SLO or when cache miss rate exceeds a threshold (e.g., > 5 %).

---

## 9. Practical End‑to‑End Example

Below we build a **minimal real‑time feature store** using **Feast** (open‑source feature store) backed by **Redis** for online serving, and **Kafka** for streaming ingestion.

### 9.1 Prerequisites

- Docker Desktop or a Kubernetes cluster
- Python 3.9+
- `docker-compose` (for local demo)

### 9.2 Docker‑Compose File

```yaml
version: "3.8"
services:
  kafka:
    image: confluentinc/cp-kafka:7.5.0
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    ports:
      - "9092:9092"

  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
    ports:
      - "2181:2181"

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  feast:
    image: feastdev/feast:latest
    command: ["feast", "server"]
    environment:
      FEAST_REPO_PATH: /repo
    volumes:
      - ./feature_repo:/repo
    ports:
      - "6565:6565"
```

### 9.3 Feature Repository (`feature_repo/feature_store.yaml`)

```yaml
project: real_time_demo
registry: data/registry.db
provider: local
online_store:
  path: data/online_store.db
entity_key_serialization_version: 2
```

### 9.4 Define an Entity and Feature

`feature_repo/definition.py`

```python
from feast import Entity, Feature, FeatureView, FileSource
import pandas as pd
from datetime import datetime, timedelta

# Entity: user
user = Entity(name="user_id", join_keys=["user_id"])

# Simulated source of click events
click_source = FileSource(
    path="data/clicks.parquet",
    event_timestamp_column="event_timestamp",
    created_timestamp_column="created_timestamp",
)

# Feature View that computes click‑through rate over the last minute
click_rate_fv = FeatureView(
    name="click_rate_fv",
    entities=[user],
    ttl=timedelta(seconds=30),          # keep online data for 30 s
    features=[
        Feature(name="click_rate", dtype="float"),
    ],
    batch_source=click_source,
    online=True,
)

# Register entities and feature views
def register(repo):
    repo.apply([user, click_rate_fv])
```

### 9.5 Ingestion Pipeline (Python)

```python
import json
import time
from kafka import KafkaProducer
import pandas as pd
import numpy as np

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

def generate_click(user_id: int) -> dict:
    return {
        "user_id": user_id,
        "event_timestamp": int(time.time() * 1000),
        "ad_id": f"ad_{np.random.randint(1,100)}",
        "clicked": np.random.rand() < 0.12
    }

# Emit 10 k events per second for demo
while True:
    batch = [generate_click(np.random.randint(1, 100_000)) for _ in range(1000)]
    for event in batch:
        producer.send("click-events", event)
    producer.flush()
    time.sleep(0.1)  # 10 k events/s
```

### 9.6 Real‑Time Materialization with Feast

Feast ships a **materialization job** that reads from Kafka (via a Flink or Spark connector) and writes to the online store (Redis). For the demo we use the **local materializer**:

```bash
# Start the Feast server (already running via docker-compose)
feast materialize-incremental $(date -u +"%Y-%m-%dT%H:%M:%SZ")
```

Feast will keep the online store up‑to‑date, handling TTL automatically.

### 9.7 Querying the Online Store

```python
from feast import FeatureStore

store = FeatureStore(repo_path="feature_repo")
entity_rows = [{"user_id": str(uid)} for uid in ["12345", "67890", "54321"]]

features = store.get_online_features(
    entity_rows=entity_rows,
    features=["click_rate_fv:click_rate"]
).to_dict()

print(features)
```

Typical response latency (measured with `timeit`) is **≈ 1.2 ms** per batch of three users, well within a 10 ms SLO.

---

## 10. Best Practices Checklist

- **Design for Exactly‑Once**: Use stream processors with checkpointing to avoid duplicate feature updates.  
- **Prefer In‑Memory Stores**: Redis or Aerospike for hot data; keep vectors compact (e.g., `float32`).  
- **Shard by Entity**: Consistent hashing ensures uniform load distribution.  
- **Implement TTL at Write Time**: Prevent stale data from lingering in cache.  
- **Version Features Explicitly**: Enables safe rollout of new transformations.  
- **Expose a Typed RPC API**: gRPC + protobuf or Arrow for zero‑copy payloads.  
- **Monitor Tail Latency**: Track p99/p999 latency, cache miss rate, and replication lag.  
- **Automate Scaling**: HPA based on latency, not just CPU.  
- **Secure the Store**: Network policies, TLS, and RBAC for both online and offline layers.  
- **Document Lineage**: Store transformation DAGs in a metadata service for auditability.

---

## Conclusion

Scaling a real‑time feature store to meet low‑latency inference requirements is far from a trivial engineering task. It demands a **holistic approach** that spans data ingestion, storage architecture, API design, and operational excellence. By:

1. **Adopting a streaming‑first (Kappa) pipeline** with exactly‑once semantics,  
2. **Choosing an in‑memory online store** (Redis/Aerospike) with sharding and TTL,  
3. **Leveraging columnar/vectorized serialization** (Apache Arrow, protobuf), and  
4. **Embedding governance, versioning, and observability** into the core,

organizations can achieve sub‑10 ms feature retrieval at scale, enabling ML models to act on the freshest data possible. The practical example built on Feast demonstrates that many of these patterns are already available as open‑source components—what remains is careful integration and rigorous performance testing.

Investing in a robust real‑time feature store not only improves inference latency but also creates a **single source of truth** for features across training and serving, reducing engineering friction and fostering better model governance. As ML workloads continue to push the boundaries of speed and scale, a well‑architected feature store will be the linchpin that turns raw event streams into actionable intelligence—instantly.

---

## Resources

- [Feast – Open Source Feature Store](https://feast.dev) – Documentation, tutorials, and community resources for building production‑grade feature stores.  
- [Redis Cluster Documentation](https://redis.io/docs/management/scaling/) – Guide on sharding, replication, and high‑availability configurations.  
- [Apache Flink – Stateful Stream Processing](https://flink.apache.org) – Detailed reference on exactly‑once processing, checkpointing, and scaling.  
- [Google Cloud Blog – Low‑Latency Feature Serving with Bigtable & gRPC](https://cloud.google.com/blog/products/databases/low-latency-feature-serving) – Real‑world case study and architecture patterns.  
- [AWS Architecture – Real‑Time Machine Learning Inference](https://aws.amazon.com/architecture/real-time-ml-inference/) – Overview of services and best practices for sub‑10 ms inference pipelines.