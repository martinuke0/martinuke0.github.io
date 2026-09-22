---
title: "Build a Production-Grade Inference Pipeline: A Hands-On CV Project"
date: "2026-09-22T22:00:40.764"
draft: false
tags: ["inference", "machine-learning", "fastapi", "systems-engineering", "python", "portfolio"]
description: "Build a production-grade inference pipeline from scratch. This hands-on guide covers async request handling, model batching, caching, and observability — the exact systems skills hiring managers look for."
summary: "A step-by-step guide to building a real-time ML inference service with async processing, request batching, and observability — designed to demonstrate production systems engineering on your CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-22-build-a-production-grade-inference-pipeline-a-hands-on-cv-project.svg"
  alt: "A code editor showing an inference pipeline architecture diagram with arrows connecting model loader, request queue, and API server components."
  caption: ""
  relative: false
---

> **TL;DR** — Build a real-time inference pipeline: an async API server that loads ML models, batches incoming requests, runs inference with timeout enforcement, caches results, and emits structured metrics. This project signals distributed systems, ML infrastructure, and observability skills in a single repo — exactly what hiring managers screening for senior engineering roles look for.

You do not need a decade of experience to demonstrate systems thinking on a CV. What you need is a single project that forces you to make real architectural decisions — about concurrency, fault tolerance, latency budgets, and observability — and to implement them with real code. This guide walks you through building exactly that: a production-flavored inference pipeline that serves machine learning models over HTTP with request batching, async processing, result caching, and structured telemetry.

The project is deliberately scoped to be completable in a weekend but deep enough that each extension maps to a senior-level systems concept. By the end, you will have a working service with real code, real tests, and a roadmap that turns a weekend project into a portfolio piece that opens doors.

## Why This Project Stands Out on a CV

Inference pipelines sit at the intersection of machine learning and distributed systems. When a hiring manager sees this project, they see a candidate who understands far more than model training. Specifically, this project demonstrates:

- **Concurrent request handling** — you have implemented async I/O, connection pooling, and non-blocking execution patterns. These are the same primitives used in systems like [Envoy](https://www.envoyproxy.io/) and [Nginx](https://nginx.org/).
- **ML infrastructure operations** — model lifecycle management (loading, versioning, hot-swapping) is a hard problem that most ML engineers never touch. Demonstrating it signals you can own the full stack from model to endpoint.
- **Observability and SLO thinking** — structured logging, metrics emission, and tracing are not optional in production. Including them shows you think beyond "it works on my machine."
- **Performance engineering** — request batching and caching are concrete techniques for optimizing throughput and latency. You can quantify improvements with benchmarks, which is exactly how senior engineers communicate impact.
- **Fault tolerance** — timeout enforcement, circuit breaking, and graceful degradation are patterns that separate toy projects from systems that survive real traffic.

This project signals roles like ML Infrastructure Engineer, Backend Systems Engineer, and SRE — positions that sit at the critical intersection of data and infrastructure and command some of the highest salaries in the industry.

## Architecture Overview

The service is composed of five loosely coupled components that communicate through well-defined interfaces. Here is the architecture as a text diagram:

```
┌──────────────┐     HTTP/2      ┌──────────────────┐
│   Client      │ ──────────────▶ │   API Gateway     │
│  (curl,       │                 │  (FastAPI +       │
│   browser)    │                 │   Uvicorn)        │
└──────────────┘                 └────────┬─────────┘
                                          │
                                          ▼
                               ┌──────────────────────┐
                               │  Request Batcher      │
                               │  (async queue +       │
                               │   coalescing timer)   │
                               └──────────┬───────────┘
                                          │
                              ┌───────────▼───────────┐
                              │  Model Loader         │
                              │  (lazy load +         │
                              │    hot-swap)          │
                              └───────────┬───────────┘
                                          │
                              ┌───────────▼───────────┐
                              │  Inference Engine     │
                              │  (torch / onnx /      │
                              │    tokenizer)         │
                              └───────────┬───────────┘
                                          │
                              ┌───────────▼───────────┐
                              │  Response Pipeline    │
                              │  (cache lookup →      │
                              │    result → metrics)  │
                              └───────────────────────┘
```

Each component has a single responsibility:

- **API Gateway** — receives HTTP requests, validates payloads, and enqueues them into the batcher. Built with FastAPI for its native async support and automatic OpenAPI documentation.
- **Request Batcher** — coalesces incoming requests into micro-batches using an async queue and a time-based flush window. This is where throughput optimization happens.
- **Model Loader** — lazily loads models on first request and supports hot-swapping versions without downtime. Uses a registry pattern to manage multiple model instances.
- **Inference Engine** — the actual compute kernel. Wraps the model's forward pass with tokenization, GPU memory management, and timeout enforcement.
- **Response Pipeline** — handles cache lookups (LRU cache for repeated inputs), formats responses, and emits structured metrics via OpenTelemetry.

The components communicate through Python's `asyncio` primitives — `Queue`, `Event`, and `Lock` — which keeps the entire system single-threaded yet highly concurrent without the overhead of multiprocessing.

## Building It Step by Step

The implementation uses Python 3.12+, FastAPI, Uvicorn, and PyTorch. Below are the core code snippets for each component. Clone the starting template and follow along.

### Step 1: Project Scaffolding

```bash
mkdir inference-pipeline && cd inference-pipeline
python -m venv .venv && source .venv/bin/activate
pip install fastapi uvicorn[standard] torch onnxruntime python-multipart \
    opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp \
    redis aioredis cachetools pytest pytest-asyncio
```

Create the project structure:

```
inference-pipeline/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI entry point
│   ├── api/
│   │   └── routes.py      # HTTP endpoints
│   ├── core/
│   │   ├── batcher.py     # Request coalescing
│   │   ├── loader.py      # Model lifecycle
│   │   ├── engine.py      # Inference execution
│   │   └── cache.py       # LRU result cache
│   ├── metrics/
│   │   └── telemetry.py   # OpenTelemetry setup
│   └── models/
│       └── registry.py    # Model version management
├── tests/
│   ├── test_batcher.py
│   ├── test_engine.py
│   └── test_api.py
├── configs/
│   └── default.yaml
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

### Step 2: The Request Batcher

The batcher is the heart of the throughput optimization. Instead of processing each request individually, it coalesces requests arriving within a configurable time window into a single batch, reducing kernel launch overhead.

```python
# app/core/batcher.py
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, TypeVar

T = TypeVar("T")

@dataclass
class BatchedRequest:
    payload: Dict[str, Any]
    future: asyncio.Future
    timestamp: float = field(default_factory=time.monotonic)

class RequestBatcher:
    """Coalesces incoming requests into micro-batches."""

    def __init__(
        self,
        batch_size: int = 32,
        flush_interval_ms: float = 50.0,
        processor: Callable[[List[Dict[str, Any]]], Any] = None,
    ):
        self.batch_size = batch_size
        self.flush_interval = flush_interval_ms / 1000.0
        self.processor = processor
        self._queue: asyncio.Queue[BatchedRequest] = asyncio.Queue()
        self._current_batch: List[BatchedRequest] = []
        self._flush_event = asyncio.Event()
        self._running = False

    async def start(self):
        """Start the background batching loop."""
        self._running = True
        while self._running:
            try:
                # Wait for first request with timeout
                req = await asyncio.wait_for(
                    self._queue.get(), timeout=self.flush_interval
                )
                self._current_batch.append(req)

                # Drain additional requests up to batch_size
                while len(self._current_batch) < self.batch_size:
                    try:
                        req = self._queue.get_nowait()
                        self._current_batch.append(req)
                    except asyncio.QueueEmpty:
                        break

                # Process the batch
                await self._flush()

            except asyncio.TimeoutError:
                if self._current_batch:
                    await self._flush()

    async def enqueue(self, payload: Dict[str, Any]) -> Any:
        """Add a request to the batch and return its result."""
        future = asyncio.get_event_loop().create_future()
        req = BatchedRequest(payload=payload, future=future)
        await self._queue.put(req)
        return await future  # Suspend until result is available

    async def _flush(self):
        """Execute the batch and resolve all futures."""
        batch = self._current_batch
        self._current_batch = []
        if not batch:
            return
        try:
            payloads = [r.payload for r in batch]
            results = await self.processor(payloads)
            for req, result in zip(batch, results):
                req.future.set_result(result)
        except Exception as e:
            for req in batch:
                req.future.set_exception(e)

    async def stop(self):
        """Graceful shutdown: flush remaining requests."""
        self._running = False
        self._flush_event.set()
        if self._current_batch:
            await self._flush()
```

This pattern — a background loop that drains a queue into batches and resolves futures — is the same architecture used by [TensorFlow Serving's batching system](https://www.tensorflow.org/tfx/serving/serving_config#model_batching). The key insight is that GPU kernels have fixed launch overhead; batching N requests into one kernel call amortizes that cost across all N requests, often yielding 5–10x throughput improvement.

### Step 3: The Model Loader and Inference Engine

```python
# app/core/loader.py
import torch
from typing import Dict, Optional
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ModelVersion:
    name: str
    version: str
    path: str
    loaded_at: datetime = field(default_factory=datetime.utcnow)
    model: Optional[torch.nn.Module] = None

class ModelLoader:
    """Lazy-loads and manages model versions with hot-swap support."""

    def __init__(self):
        self._registry: Dict[str, ModelVersion] = {}
        self._active: Optional[ModelVersion] = None
        self._lock = asyncio.Lock()

    async def load(self, name: str, version: str, path: str) -> torch.nn.Module:
        async with self._lock:
            model_version = ModelVersion(name=name, version=version, path=path)
            model_version.model = torch.load(path, map_location="cpu")
            model_version.model.eval()
            self._registry[f"{name}:{version}"] = model_version
            self._active = model_version
            return model_version.model

    def get_active(self) -> ModelVersion:
        if self._active is None:
            raise RuntimeError("No model loaded. Call load() first.")
        return self._active

    async def hot_swap(self, name: str, version: str, path: str):
        """Load a new model version without dropping in-flight requests."""
        new_model = await self.load(name, version, path)
        # Swap atomically: in-flight requests use the old model,
        # new requests use the new model
        self._active = self._registry[f"{name}:{version}"]
        return new_model
```

```python
# app/core/engine.py
import asyncio
import time
from typing import List, Dict, Any
import torch

class InferenceEngine:
    """Executes batched inference with timeout enforcement."""

    def __init__(self, model_loader: "ModelLoader", timeout_ms: int = 5000):
        self._loader = model_loader
        self._timeout = timeout_ms / 1000.0

    async def run_batch(self, payloads: List[Dict[str, Any]]) -> List[Any]:
        """Run inference on a batch with per-request timeout."""
        model_version = self._loader.get_active()
        model = model_version.model

        results = []
        for payload in payloads:
            try:
                result = await asyncio.wait_for(
                    self._single_inference(model, payload),
                    timeout=self._timeout
                )
                results.append({"status": "success", "result": result})
            except asyncio.TimeoutError:
                results.append({"status": "timeout", "result": None})
            except Exception as e:
                results.append({"status": "error", "error": str(e)})
        return results

    async def _single_inference(self, model, payload: Dict[str, Any]):
        """Execute a single forward pass on the model."""
        # Simulate tokenization and tensor preparation
        input_tensor = self._prepare_input(payload)
        with torch.no_grad():
            output = model(input_tensor)
        return output.tolist()

    def _prepare_input(self, payload: Dict[str, Any]):
        """Convert payload to model input tensor."""
        # In production, this would handle tokenization, padding, etc.
        return torch.tensor(payload.get("inputs", [0]))
```

The timeout enforcement via `asyncio.wait_for` is critical in production. Without it, a single stalled request can block an entire worker thread and cascade into a full outage. This is the same pattern used by [Envoy's per-request timeout](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/timeout_config).

### Step 4: The API Routes and Cache Layer

```python
# app/core/cache.py
from cachetools import LRUCache
import hashlib
import json
from typing import Any, Optional

class ResultCache:
    """LRU cache for inference results keyed by input hash."""

    def __init__(self, maxsize: int = 10_000):
        self._cache = LRUCache(maxsize=maxsize)

    def _key(self, payload: Dict[str, Any]) -> str:
        """Deterministic hash of the payload for cache lookup."""
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    def get(self, payload: Dict[str, Any]) -> Optional[Any]:
        key = self._key(payload)
        return self._cache.get(key)

    def set(self, payload: Dict[str, Any], result: Any):
        key = self._key(payload)
        self._cache[key] = result
```

```python
# app/api/routes.py
from fastapi import FastAPI, HTTPException
from app.core.batcher import RequestBatcher
from app.core.loader import ModelLoader
from app.core.engine import InferenceEngine
from app.core.cache import ResultCache
from app.metrics.telemetry import emit_metric

app = FastAPI(title="Inference Pipeline", version="1.0.0")

# Initialize components
model_loader = ModelLoader()
cache = ResultCache(maxsize=10_000)

async def process_batch(payloads: list) -> list:
    # Check cache first
    cached_results = []
    uncached_payloads = []
    for payload in payloads:
        cached = cache.get(payload)
        if cached is not None:
            cached_results.append({"status": "cached", "result": cached})
        else:
            uncached_payloads.append(payload)

    # Run inference on uncached payloads
    if uncached_payloads:
        engine = InferenceEngine(model_loader)
        inferences = await engine.run_batch(uncached_payloads)
        for inf in inferences:
            if inf["status"] == "success":
                cache.set(uncached_payloads[inferences.index(inf)], inf["result"])
        return cached_results + inferences
    return cached_results

batcher = RequestBatcher(
    batch_size=32,
    flush_interval_ms=50.0,
    processor=process_batch,
)

@app.on_event("startup")
async def startup():
    await model_loader.load("default", "v1", "./models/default.pt")
    asyncio.create_task(batcher.start())

@app.post("/infer")
async def infer(payload: dict):
    emit_metric("inference_requests_total", 1)
    try:
        result = await batcher.enqueue(payload)
        return result
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Inference timed out")

@app.post("/models/{name}/versions/{version}")
async def deploy_model(name: str, version: str, path: str):
    await model_loader.hot_swap(name, version, path)
    return {"status": "deployed", "name": name, "version": version}
```

### Step 5: Observability with OpenTelemetry

```python
# app/metrics/telemetry.py
from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter,
)
from opentelemetry.sdk.resources import Resource

_resource = Resource.create({"service.name": "inference-pipeline"})
_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
_provider = MeterProvider(resource=_resource, metric_readers=[_reader])
metrics.set_meter_provider(_provider)
_meter = metrics.get_meter("inference-pipeline", "1.0.0")

_request_counter = _meter.create_counter(
    "inference_requests_total",
    description="Total inference requests",
)
_latency_histogram = _meter.create_histogram(
    "inference_latency_ms",
    description="Inference latency in milliseconds",
)

def emit_metric(name: str, value: int):
    if name == "inference_requests_total":
        _request_counter.add(value)
```

This setup exports metrics to any OTLP-compatible backend — Prometheus, Grafana, Datadog, or New Relic. The histogram is essential for tracking P50, P95, and P99 latency, which are the SLOs that actually matter in production.

## Running and Testing It

### Local Development

Start the service with Uvicorn, which provides ASGI server capabilities with HTTP/2 support:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

A single worker is intentional here — the `asyncio` event loop handles all concurrency within one process. Adding multiple workers with `--workers 4` would require a shared Redis cache and a message queue to coordinate batching across processes, which is exactly the extension discussed later.

### Smoke Test

Verify the service is alive and a model is loaded:

```bash
# Start the service, then in another terminal:
curl -X POST http://localhost:8000/infer \
  -H "Content-Type: application/json" \
  -d '{"inputs": [1, 2, 3, 4]}'
```

You should receive a JSON response with the inference result. The first request will be slow (model loading); subsequent identical requests will return instantly from the LRU cache.

### Load Test with Locust

To prove the batching actually improves throughput, use Locust to simulate concurrent traffic:

```python
# locustfile.py
from locust import HttpUser, task, between

class InferenceUser(HttpUser):
    wait_time = between(0.01, 0.1)  # High concurrency simulation

    @task
    def infer(self):
        self.client.post("/infer", json={"inputs": [1, 2, 3, 4]})
```

```bash
pip install locust
locust -f locustfile.py --headless -u 200 -r 50 --run-time 60s
```

Compare throughput with batching disabled (process one request at a time) versus enabled. You should see a measurable difference — on a GPU-equipped machine, batching 32 requests typically yields 5–10x higher requests-per-second compared to sequential processing. This is the concrete benchmark you can cite on your CV or in an interview.

### Unit Tests

```python
# tests/test_batcher.py
import pytest
import asyncio
from app.core.batcher import RequestBatcher

@pytest.mark.asyncio
async def test_batch_coalescing():
    """Verify that multiple enqueued requests are processed together."""
    processed = []

    async def mock_processor(payloads):
        processed.extend(payloads)
        return [{"result": p} for p in payloads]

    batcher = RequestBatcher(
        batch_size=4,
        flush_interval_ms=100.0,
        processor=mock_processor,
    )
    asyncio.create_task(batcher.start())

    await batcher.enqueue({"id": 1})
    await batcher.enqueue({"id": 2})
    await batcher.enqueue({"id": 3})
    await batcher.enqueue({"id": 4})

    await asyncio.sleep(0.5)  # Allow flush
    assert len(processed) == 4
    await batcher.stop()

@pytest.mark.asyncio
async def test_timeout_enforcement():
    """Verify that slow requests raise TimeoutError."""
    from app.core.engine import InferenceEngine

    class SlowLoader:
        def get_active(self):
            return type("M", (), {"eval": lambda self: None})()

    engine = InferenceEngine(SlowLoader(), timeout_ms=1)
    result = await engine.run_batch([{"inputs": [1]}])
    assert result[0]["status"] == "timeout"
```

Run all tests:

```bash
pytest tests/ -v --cov=app --cov-report=term-missing
```

Aim for 80%+ coverage. The coverage report becomes a talking point in interviews — it demonstrates engineering discipline and attention to quality.

## Extending It: Your Roadmap to Senior-Level

Each extension below transforms the weekend project into something that could plausibly run in production. They are ordered by complexity, and each one maps to a specific senior-level systems concept.

1. **Add Redis-backed distributed caching** — Replace the in-memory LRU cache with Redis using `aioredis`. This enables cache consistency across multiple service instances and is the foundation for horizontal scaling. *Why it matters: In-memory caches do not scale past a single process; distributed caching is a non-negotiable requirement for any service handling real traffic.*

2. **Implement horizontal scaling with a message queue** — Replace the in-process `asyncio.Queue` with Redis Streams or Kafka. Each worker instance consumes from the stream, processes batches independently, and writes results to a response store. *Why it matters: Horizontal scaling is the primary mechanism for handling load spikes; message queues decouple producers from consumers and provide backpressure.*

3. **Add Prometheus metrics and Grafana dashboards** — Export latency histograms, error rates, batch sizes, and GPU utilization to Prometheus and visualize them in Grafana. Define alerting rules for P99 latency exceeding your SLO. *Why it matters: You cannot improve what you cannot measure; observability is the difference between reactive firefighting and proactive system management.*

4. **Implement circuit breaking and graceful degradation** — Use the [circuitbreaker](https://github.com/fabfuel/circuitbreaker) library to stop routing requests to a failing model backend and return cached or default responses instead. *Why it matters: Fault isolation prevents cascading failures; a system that degrades gracefully instead of crashing entirely is the hallmark of production-grade software.*

5. **Add model version A/B testing** — Extend the model registry to support traffic splitting between versions (e.g., 90% v1, 10% v2) and collect per-version metrics. *Why it matters: Safe model deployment requires canary releases; A/B testing at the inference layer is how ML teams validate new models in production without risking user experience.*

6. **Benchmark with `py-spy` and `nvprof`** — Profile CPU and GPU utilization to identify bottlenecks. Use `py-spy record --native -- python app/main.py` for CPU flamegraphs and NVIDIA's `nvprof` for GPU kernel analysis. *Why it matters: Performance optimization requires evidence, not intuition; profiling data transforms vague "it's slow" complaints into targeted engineering actions.*

## Key Takeaways

- **A single well-architected project beats ten shallow ones.** The inference pipeline demonstrates concurrent systems design, ML infrastructure, observability, and performance engineering — four distinct skill areas in one codebase.
- **Real code with real benchmarks is what hiring managers notice.** A README with Locust load test results and coverage reports signals that you think about quality and performance, not just functionality.
- **The extension roadmap maps directly to senior-level responsibilities.** Each upgrade — distributed caching, circuit breaking, A/B testing — is a concept that appears in production systems at companies like Netflix, Uber, and Google.
- **Observability is not optional.** Structured metrics, tracing, and logging from day one make the difference between a project that looks finished and one that looks production-ready.
- **Infrastructure skills are the highest-leverage differentiator.** Most ML engineers can train models; far fewer can deploy, scale, and monitor them reliably. This project puts you in the latter category.

## Further Reading

To deepen and evolve this project, study these primary sources:

1. [TensorFlow Serving Model Batching Configuration](https://www.tensorflow.org/tfx/serving/serving_config#model_batching) — The canonical documentation on how production inference servers implement request batching, including the batch size and timeout parameters used in this project.
2. [The Envoy Proxy Architecture and Timeout Configuration](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/timeout_config) — A deep dive into how Envoy handles per-request timeouts, retries, and circuit breaking — the exact fault tolerance patterns referenced in the extension roadmap.
3. [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/) — The canonical specification for distributed tracing and metrics. Study this to understand how to instrument your service for production observability.
4. [Designing Data-Intensive Applications by Martin Kleppmann](https://dataintensive.net/) — The definitive book on distributed systems fundamentals. Chapters on stream processing and fault tolerance directly inform the message queue and circuit breaker extensions.
5. [PyTorch Performance Optimization Guide](https://pytorch.org/tutorials/recipes/recipes/performance_tips.html) — Official PyTorch documentation on optimizing inference throughput, including batching strategies, GPU memory management, and torch.jit compilation.
6. [RFC 7231: Hypertext Transfer Protocol (HTTP/1.1): Semantics and Content](https://datatracker.ietf.org/doc/html/rfc7231) — The HTTP specification that underpins every API design decision in this project. Understanding status codes, idempotency, and content negotiation is essential for building correct APIs.

---