---
title: "Zero-to-Hero with the vLLM Router: Load Balancing and Scaling vLLM Model Servers"
date: "2026-01-04T11:24:53.784"
draft: false
tags: ["vLLM", "LLM infrastructure", "load balancing", "MLOps", "tutorial"]
---

## Introduction

vLLM has quickly become one of the most popular inference engines for serving large language models efficiently, thanks to its paged attention and strong OpenAI-compatible API. But as soon as you move beyond a single GPU or a single model server, you run into familiar infrastructure questions:

- How do I distribute traffic across multiple vLLM servers?
- How do I handle failures and keep latency predictable?
- How do I roll out new model versions without breaking clients?

This is where the **vLLM Router** comes in.

This tutorial walks you from zero to productive with the vLLM Router from a developer’s perspective:

- What the vLLM Router is and why it’s needed
- How request routing and load balancing work conceptually
- How it integrates with multiple vLLM model servers
- How to set up a basic router configuration
- A simple end-to-end example you can adapt
- Common pitfalls in production
- Best practices for scaling and reliability
- A short list of high-quality learning resources

The goal is to be concise but complete enough that you can design and operate a small production-ready vLLM deployment.

---

## 1. What Is the vLLM Router and Why Do You Need It?

At a high level, the **vLLM Router** is a lightweight HTTP service that:

- Exposes an **OpenAI-compatible API** (e.g., `/v1/chat/completions`, `/v1/completions`)
- Sits in front of **one or more vLLM model servers**
- **Routes and load balances** requests across those servers
- Handles **health checking, failover, and simple routing policies**

You can think of it as a purpose-built “application load balancer” for vLLM.

### 1.1. Problems it solves

Without the router, each vLLM instance:

- Listens on its own host/port (e.g., `http://gpu-1:8001`, `http://gpu-2:8001`)
- Exposes the OpenAI-compatible API directly
- Has **no built-in coordination** with other instances

This leads to several challenges:

1. **Horizontal scaling**  
   - You can run multiple `vllm serve` instances, but **clients must choose** which one to call.
   - Naive client-side load balancing becomes brittle and hard to manage.

2. **High availability**  
   - If one vLLM instance dies, clients that call it will fail.
   - You need failover and health checking somewhere.

3. **Multi-model & version routing**  
   - You may want `gpt-4.1-mini` traffic to go to one pool and `gpt-4.1-large` to another.
   - You may want to A/B test a new model version for a subset of traffic.

4. **Operational simplicity**  
   - You want clients to target a **single base URL** (e.g., `https://llm.mycompany.com`) and not care about server details.

The router centralizes these concerns:

- **One public endpoint** → many backend vLLM servers
- **Configurable routing policies** per model
- **Health-checked backends** and optional retries
- Better separation between **application logic** and **inference fleet management**

---

## 2. Core Architecture and Concepts

Let’s define the main components and how they interact.

### 2.1. Components

1. **vLLM Model Servers (Backends)**  
   Processes started with something like:

   ```bash
   vllm serve mistralai/Mistral-7B-Instruct-v0.3 \
     --host 0.0.0.0 \
     --port 8001
   ```

   Each:

   - Loads one model (or a small set)
   - Owns one or more GPUs
   - Exposes HTTP API (OpenAI-compatible)

2. **vLLM Router**

   A separate service that:

   - Listens on a public port (e.g., 8000)
   - Accepts OpenAI-style requests
   - Chooses a backend based on config (model name, policy, etc.)
   - Forwards the request and streams the response back

3. **Clients**

   - Use any OpenAI-compatible SDK or plain HTTP
   - Point to the router’s URL instead of a backend instance

### 2.2. Request flow

A typical `/v1/chat/completions` request looks like this:

1. Client sends:

   ```http
   POST /v1/chat/completions HTTP/1.1
   Host: router.example.com
   Content-Type: application/json

   {
     "model": "mistral-7b",
     "messages": [
       {"role": "user", "content": "Explain vLLM Router in one sentence."}
     ],
     "stream": true
   }
   ```

2. Router:

   - Parses `model` (`"mistral-7b"`)
   - Looks up backend pool(s) that can handle this model
   - Picks one backend according to load balancing policy
   - Forwards the HTTP request to e.g. `http://10.0.0.11:8001/v1/chat/completions`
   - Streams the backend’s response back to the client

3. Client:

   - Reads the streamed response as if talking directly to vLLM

From the client’s perspective, it’s **just an OpenAI-compatible endpoint**.

> **Note:** The exact configuration schema and CLI flags of the vLLM Router may evolve with newer versions. Treat the examples in this article as **patterns** and always check the official docs for your vLLM version.

---

## 3. Request Routing & Load Balancing

The core responsibilities of the router are **routing** and **load balancing**.

### 3.1. Routing by model name

The most basic routing rule is **model-based routing**:

- Each request includes `"model": "some-model-name"`.
- The router’s config maps that model name to one or more backend pools.

Common patterns:

- **One model, many backends** (scale-out):

  ```text
  "mistral-7b" → [backend A, backend B, backend C]
  ```

- **Multiple logical names for same model** (aliases):

  ```text
  "chat-default" → "mistralai/Mistral-7B-Instruct-v0.3"
  "mistral-7b"   → "mistralai/Mistral-7B-Instruct-v0.3"
  ```

- **Versioned models**:

  ```text
  "mistral-7b-v1" → pool 1
  "mistral-7b-v2" → pool 2
  ```

This lets you **abstract physical deployments** behind stable logical names.

### 3.2. Load-balancing strategies

Router implementations typically support simple but effective policies, such as:

- **Round-robin**  
  - Each request is sent to the next backend in order.
  - Simple and works well with roughly similar hardware.

- **Random**  
  - Pseudo-randomly picks backends.
  - Avoids synchronized load spikes in some edge cases.

- **Least-connections / load-aware** (if supported)  
  - Picks the backend with fewest active requests or tokens in flight.
  - Better utilization if some GPUs are faster or have fewer pending requests.

- **Sticky / session-aware** (via conversation ID or custom key)  
  - Keeps all requests for a given conversation on the same backend.
  - Important if your application implicitly depends on hidden state or caching.

> **Practical tip:** For most deployments where all GPUs are similar, **round-robin** is more than good enough. Optimize the policy only if you see persistent imbalances.

### 3.3. Health checking and failover

To avoid sending traffic to dead or overloaded backends, the router generally:

- Performs **periodic health checks** (e.g., simple HTTP GET or lightweight completion).
- Marks a backend as **unhealthy** if checks fail or time out.
- Skips unhealthy backends in the load-balancing algorithm.
- Optionally **retries** a failed request on another backend if it’s safe to do so.

This is crucial for:

- Gracefully handling node restarts, OOM crashes, or GPU errors
- Enabling rolling upgrades (take a node out, upgrade, put it back)

---

## 4. Integrating the Router with Multiple vLLM Model Servers

Let’s walk through common integration patterns.

### 4.1. Homogeneous pool: same model, multiple GPUs

This is the simplest and most common scenario:

- You want to serve **one model at scale** (e.g., `mistralai/Mistral-7B-Instruct-v0.3`)
- You have multiple GPUs or nodes
- Each vLLM instance loads the same model

Example fleet:

- `http://10.0.0.11:8001` → Mistral-7B on GPU 0
- `http://10.0.0.12:8001` → Mistral-7B on GPU 1
- `http://10.0.0.13:8001` → Mistral-7B on GPU 2

Router config (conceptual):

- Logical model: `"mistral-7b"`
- Backends: `[10.0.0.11:8001, 10.0.0.12:8001, 10.0.0.13:8001]`
- Policy: round-robin

Clients always use `"model": "mistral-7b"`, and the router spreads traffic.

### 4.2. Heterogeneous pool: multiple models, multiple pools

You might serve several models with different performance/quality profiles:

- `"mistral-7b-chat"` → general use, cheap
- `"llama-3-70b-instruct"` → premium
- `"embedding-3-small"` → embeddings

Each pool has its own vLLM servers and GPUs. The router config maps logical model names to the respective pools.

This enables:

- **Multi-tier products** (basic vs premium)
- **Different latency/throughput targets** per pool
- Independent scaling of each model based on usage

### 4.3. Versioning and canary deployments

You can route by model name and/or by percentage of traffic to do:

- **Canary testing:** e.g., 5% of `"chat-default"` requests to v2
- **Blue/green deployments:** switch `"chat-default"` from v1 to v2 atomically
- **Shadow traffic:** send copies of traffic to a new model for evaluation (if/when router or external infra supports mirroring)

Often, you combine the router with an external API gateway or service mesh (like Envoy, NGINX, or a Kubernetes Ingress) to handle the more advanced traffic-splitting logic.

---

## 5. Setting Up a Basic vLLM Router Configuration

This section outlines a **concrete but generic pattern** for setting up:

- Multiple vLLM servers
- A router in front of them
- A client that talks to the router

> **Disclaimer:** The actual CLI flags and config keys for the vLLM Router may change across versions. Use this section as a **conceptual template** and verify exact options in the official docs for your vLLM version.

### 5.1. Prerequisites

- Python 3.9+ (commonly used with vLLM)
- vLLM installed:

  ```bash
  pip install vllm
  ```

- At least **one GPU** (two or more to see real load balancing behavior)

### 5.2. Start two vLLM model servers (backends)

Let’s run two identical servers on different ports. In reality they’d often be on separate hosts.

```bash
# Backend 1
CUDA_VISIBLE_DEVICES=0 \
vllm serve mistralai/Mistral-7B-Instruct-v0.3 \
  --host 0.0.0.0 \
  --port 8001

# Backend 2
CUDA_VISIBLE_DEVICES=1 \
vllm serve mistralai/Mistral-7B-Instruct-v0.3 \
  --host 0.0.0.0 \
  --port 8002
```

Check both are up:

```bash
curl http://localhost:8001/v1/models
curl http://localhost:8002/v1/models
```

You should see JSON lists of models from each backend.

### 5.3. Create a (conceptual) router config

Assume a YAML config file named `router.yaml`:

```yaml
# router.yaml (illustrative example – check official docs for exact schema)
listen: "0.0.0.0:8000"

models:
  # Logical model name that clients use
  mistral-7b:
    # Backends that can serve this model
    backends:
      - name: "mistral-7b-gpu0"
        url: "http://localhost:8001"
      - name: "mistral-7b-gpu1"
        url: "http://localhost:8002"

    # Load-balancing policy
    load_balancer:
      policy: "round_robin"

    # Optional: timeouts, retry limits, etc.
    timeouts:
      request_timeout_ms: 60000
      connect_timeout_ms: 2000
    retries:
      max_attempts: 2
      retry_on: ["connection_failure", "timeout"]
```

Key ideas:

- `listen`: where the router exposes the OpenAI-compatible API
- `models`: mapping from **logical model name** to a **pool of backends**
- Each backend has a `url` that points to a `vllm serve` instance
- Optional timeouts and retries improve resilience

### 5.4. Run the router

The router is typically started via a CLI that takes a config file. Conceptually:

```bash
vllm router --config router.yaml
```

When it’s running, you should see logs indicating:

- Listening address/port
- Registered models and backends
- Health check results (if enabled by default)

Now your stack looks like:

```text
Client → vLLM Router (0.0.0.0:8000)
          ↙           ↘
  Backend 1 (8001)   Backend 2 (8002)
```

---

## 6. Simple End-to-End Example

This section walks you through an end-to-end run:

1. Two backends
2. One router
3. A client sending a chat request

We’ll use `curl` first, then a simple Python example.

### 6.1. Sanity check with curl

With both backends and the router running, call the router:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "mistral-7b",
    "messages": [
      {"role": "user", "content": "Describe vLLM in one paragraph."}
    ],
    "max_tokens": 128,
    "temperature": 0.3,
    "stream": false
  }'
```

Expected behavior:

- Router reads `"model": "mistral-7b"`
- Chooses either backend 1 or backend 2 per round-robin
- Forwards the request to e.g. `http://localhost:8001/v1/chat/completions`
- Streams back JSON response compatible with OpenAI API, e.g.:

```json
{
  "id": "chatcmpl-...",
  "object": "chat.completion",
  "created": 1710000000,
  "model": "mistral-7b",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "vLLM is ..."
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 80,
    "total_tokens": 92
  }
}
```

If you repeat the request several times, the router should alternate between backends (visible in backend logs).

### 6.2. Python client example

Because the router speaks OpenAI-compatible HTTP, you can use any OpenAI client by just changing the base URL.

Here’s a simple Python client using `openai`-style SDK (pseudo-code; check your OpenAI SDK version for exact imports):

```python
import os
import requests

ROUTER_URL = "http://localhost:8000/v1/chat/completions"

def chat(prompt: str) -> str:
    payload = {
        "model": "mistral-7b",  # logical name defined in router config
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "max_tokens": 128,
        "temperature": 0.5,
        "stream": False,
    }

    resp = requests.post(ROUTER_URL, json=payload, timeout=60)
    resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"]

if __name__ == "__main__":
    answer = chat("Give me three bullet points on why to use vLLM.")
    print(answer)
```

To switch from local dev to production, you’d simply change:

```python
ROUTER_URL = "https://llm.mycompany.com/v1/chat/completions"
```

without changing your application logic.

---

## 7. Common Pitfalls

When teams start scaling vLLM with a router, they often run into similar issues. Here are the most important ones to avoid.

### 7.1. Model name mismatches

**Symptom:** Requests fail with errors like “model not found” or silently hit the wrong backend.

**Cause:** Inconsistency between:

- The `model` parameter clients send (`"mistral-7b"`)
- The model name the vLLM servers were started with
- The router’s configured logical names and mappings

**Fix:**

- Standardize logical model names (e.g., `"chat-default"`, `"mistral-7b"`)
- Keep a single source of truth (e.g., a `models.yaml` checked into repo)
- Ensure router config and vLLM startup commands align with that file

### 7.2. Mixing incompatible backends in one pool

**Symptom:** Some requests behave differently or fail only on specific backends.

**Cause:** Pool contains backends with **different models, tokenizers, or settings**, e.g.:

- One backend runs `mistral-v0.1`, another runs `mistral-v0.3`
- One is configured with different max context length

**Fix:**

- Ensure a router pool only contains **homogeneous backends** for a given logical model
- Use separate logical model names for different versions (`"mistral-7b-v1"`, `"mistral-7b-v2"`)

### 7.3. Ignoring timeouts and retries

**Symptom:** Hanging requests, clients waiting forever, or intermittent failures.

**Cause:**

- Router or clients use default HTTP timeouts (sometimes “no timeout”)
- No retry policy on transient failures or short-lived network issues

**Fix:**

- Set **explicit timeouts** (connect + total request) in router config and clients
- Enable **limited retries** for safe cases like connection failures
- Avoid retrying streaming responses mid-stream unless you design your protocol to handle duplicates

### 7.4. No health checks / naive failover

**Symptom:** Traffic still goes to dead or overloaded backends for a long time.

**Cause:**

- Router doesn’t probe backends or is misconfigured
- External load balancer (if any) only does TCP checks, not HTTP-level checks

**Fix:**

- Enable or implement **regular health checks** that:
  - Hit a cheap endpoint (e.g., `/v1/models` or a simple test completion)
  - Have realistic timeouts
- Mark backends **unhealthy** on repeated failures and re-check periodically

### 7.5. Ignoring backpressure and queue buildup

**Symptom:** Latency spikes, OOMs, or servers thrashing under load.

**Cause:**

- Each vLLM server has internal concurrency and batch parameters
- If you push too many requests without coordination, queues grow unbounded

**Fix:**

- Tune vLLM settings (e.g., max number of concurrent requests, max tokens per batch) according to GPU memory and workload
- Use router-level or application-level **rate limiting** to protect the fleet
- Monitor tail latencies (p95, p99) and adjust concurrency accordingly

### 7.6. Not planning for router redundancy

**Symptom:** Router becomes a **single point of failure**.

**Cause:**

- Only one router instance is deployed
- External LB or DNS points solely to that instance

**Fix:**

- Run **multiple router instances** and place them behind:
  - A cloud load balancer (e.g., AWS ALB, GCP Load Balancing)
  - A Kubernetes Service / Ingress
- Treat routers as **stateless** and horizontally scalable

---

## 8. Best Practices for Scaling and Reliability

Here are battle-tested patterns for operating vLLM + router in production.

### 8.1. Separate concerns: router vs external gateway

Use layers for clarity:

1. **External API gateway / ingress / LB**  
   - Handles TLS termination, authentication, IP allowlists, rate limiting, WAF, etc.
   - Think: NGINX, Envoy, Traefik, AWS API Gateway, Cloudflare, etc.

2. **vLLM Router**  
   - Handles **model-aware routing and backend pools**
   - Speaks OpenAI-compatible API to clients and backends

3. **vLLM Servers (backends)**  
   - Pure inference: GPU-intensive, no client-specific logic

This separation makes it easier to evolve routing rules without coupling them to security or networking concerns.

### 8.2. Horizontal scaling strategy

Rules of thumb:

- **One `vllm serve` per GPU** (or per small GPU group), unless you have a specific sharding strategy
- Scale horizontally by:
  - Adding more GPU hosts
  - Running more vLLM instances
  - Registering new instances with the router

In Kubernetes:

- Use **one pod per GPU** pattern (e.g., `nvidia.com/gpu: 1` per pod)
- Run a **Deployment** for the router (multiple replicas)
- Expose the router via a **Service + Ingress** or a cloud LB

### 8.3. Stateless routers and autoscaling

Make sure routers:

- **Don’t store per-user or per-conversation state** that can’t be reconstructed
- Use **idempotent or at-least-once-safe semantics** where possible

This allows you to:

- Scale routers based purely on CPU or request QPS
- Replace or upgrade them with **no downtime**

### 8.4. Observability: metrics, logs, tracing

You can’t operate a serious LLM service blind. At minimum:

- **Metrics** (Prometheus, CloudWatch, etc.)
  - QPS per model
  - Error rates per model and backend
  - Latency percentiles (p50, p90, p95, p99)
  - GPU utilization (nvidia-smi scrape or DCGM exporter) per backend

- **Structured logs**
  - Include model name, request IDs, backend chosen, and latency
  - Make it easy to correlate router logs with backend logs

- **Tracing** (optional but powerful)
  - Use distributed tracing (OpenTelemetry, Jaeger, etc.)
  - Tag spans with model name and backend so you can follow a request through the router to vLLM

### 8.5. Safe rollout practices

For model updates and config changes:

- Use **feature flags** or config-driven routing
- Prefer **blue/green or canary rollouts**:
  - Deploy new model to a subset of backends
  - Route a small percentage of traffic via router or external gateway
  - Monitor metrics; roll forward or back quickly
- Automate config validation:
  - Lint router configs before deploy
  - Ensure all referenced backends are reachable and healthy

### 8.6. Multi-tenancy, auth, and quotas

If serving many teams or customers:

- Put auth & multi-tenancy at the **gateway layer**:
  - API keys or OAuth tokens
  - Tenant identification via headers or token claims
- Optionally make routing **tenant-aware**:
  - Different models per tenant (e.g., dedicated premium models)
  - Per-tenant rate limits and quotas

The router doesn’t have to know about tenants; often it’s simpler if it only sees logical model names and traffic patterns.

---

## 9. Summary

The vLLM Router is a key building block when moving from a single-GPU dev setup to a **multi-node, production-grade LLM service**:

- It exposes a **single OpenAI-compatible endpoint** to your clients.
- It **routes and load balances** requests to multiple vLLM backends.
- It enables **multi-model, multi-version, and canary rollouts**.
- It helps you build systems that are **scalable, resilient, and operable**.

To get started:

1. Run multiple `vllm serve` instances (one per GPU).
2. Add a router in front of them with a simple config mapping model names to backends.
3. Point your clients at the router instead of a single backend.
4. Gradually add health checks, timeouts, retries, metrics, and redundancy.

Once this foundation is in place, you can iterate on model quality, latency, and cost without breaking client integrations.

---

## 10. Recommended Learning Resources and Links

Here are high-quality resources to deepen your understanding and keep up with changes:

1. **vLLM GitHub Repository**  
   https://github.com/vllm-project/vllm  
   - Source code for vLLM and often the latest features (including router-related changes).  
   - Check the `docs/` directory and examples for up-to-date usage patterns.

2. **vLLM Official Documentation**  
   https://docs.vllm.ai/  
   - The primary reference for `vllm serve`, configuration options, and router details.  
   - Search for “Serving” and “Router” sections for the most accurate, version-specific instructions.

3. **vLLM Issues & Discussions**  
   https://github.com/vllm-project/vllm/issues  
   https://github.com/vllm-project/vllm/discussions  
   - Real-world operational questions, bug reports, and design discussions.  
   - Useful for seeing how others configure scaling, routing, and GPU usage.

4. **OpenAI API Reference (Protocol Spec)**  
   https://platform.openai.com/docs/api-reference/introduction  
   - Since vLLM and the router implement an OpenAI-compatible API, this is the de facto protocol reference for request/response formats and streaming semantics.

5. **General LLM Serving & MLOps Practices**  
   - *“Building and Scaling LLM Applications”* talks and blog posts from reputable infra teams (OpenAI, Anthropic, Meta, etc.) often cover patterns like model routing, multi-tenancy, and fleet management that map well to vLLM + router setups.

Use the official docs for exact CLI flags and schemas, and rely on community discussions and real-world case studies to refine your production architecture over time.