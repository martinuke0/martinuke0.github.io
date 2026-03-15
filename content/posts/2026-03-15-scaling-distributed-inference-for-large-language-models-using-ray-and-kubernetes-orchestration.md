---
title: "Scaling Distributed Inference for Large Language Models Using Ray and Kubernetes Orchestration"
date: "2026-03-15T22:00:49.381"
draft: false
tags: ["distributed inference", "ray", "kubernetes", "large language models", "scaling"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Inference at Scale Is Hard](#why-inference-at-scale-is-hard)  
3. [Ray: A Unified Engine for Distributed Compute](#ray-a-unified-engine-for-distributed-compute)  
4. [Kubernetes: The De‑Facto Orchestrator for Cloud‑Native Workloads](#kubernetes-the-de‑facto-orchestrator-for-cloud‑native-workloads)  
5. [Architectural Blueprint](#architectural-blueprint)  
   - 5.1 [Model Sharding and Parallelism](#model-sharding-and-parallelism)  
   - 5.2 [Ray Serve as the Inference Service Layer](#ray-serve-as-the-inference-service-layer)  
   - 5.3 [Kubernetes Pods as Ray Workers](#kubernetes-pods-as-ray-workers)  
6. [Step‑by‑Step Deployment Guide](#step‑by‑step-deployment-guide)  
   - 6.1 [Containerizing the Model](#containerizing-the-model)  
   - 6.2 [Defining the Ray Cluster on Kubernetes](#defining-the-ray-cluster-on-kubernetes)  
   - 6.3 [Serving the Model with Ray Serve](#serving-the-model-with-ray-serve)  
7. [Scaling Strategies](#scaling-strategies)  
   - 7.1 [Horizontal Pod Autoscaling (HPA)](#horizontal-pod-autoscaling-hpa)  
   - 7.2 [Ray Placement Groups for Resource Guarantees](#ray-placement-groups-for-resource-guarantees)  
   - 7.3 [Dynamic Actor Scaling](#dynamic-actor-scaling)  
8. [Performance Optimizations](#performance-optimizations)  
   - 8.1 [Batching Requests](#batching-requests)  
   - 8.2 [Quantization & Mixed‑Precision](#quantization--mixed‑precision)  
   - 8.3 [Cache‑Aware Scheduling](#cache‑aware-scheduling)  
9. [Monitoring, Logging, and Observability](#monitoring-logging-and-observability)  
10. [Real‑World Case Study: Chatbot‑as‑a‑Service for a FinTech Platform](#real‑world-case-study-chatbot‑as‑a‑service-for-a-fintech-platform)  
11 [Best Practices Checklist](#best-practices-checklist)  
12 [Conclusion](#conclusion)  
13 [Resources](#resources)  

---

## Introduction

Large language models (LLMs) such as GPT‑3, Llama‑2, and Claude have reshaped the AI landscape, delivering unprecedented capabilities in natural language understanding and generation. While training these models demands massive GPU clusters and weeks of compute, **inference**—the stage where end‑users actually interact with the model—poses its own set of scalability challenges. A single request to a 70 B‑parameter LLM can consume multiple gigabytes of GPU memory and tens of milliseconds of compute, and production workloads often demand **thousands of concurrent requests** with low latency.

Enter **Ray** and **Kubernetes**. Ray provides a high‑level, Pythonic abstraction for distributed execution, actor‑based parallelism, and a production‑grade serving layer called **Ray Serve**. Kubernetes, on the other hand, gives you declarative control over container orchestration, automatic scaling, and robust networking. When combined, they form a powerful stack that can:

* **Distribute** model shards across multiple GPUs and nodes.  
* **Scale** inference pods up and down based on real‑time traffic.  
* **Maintain** high availability and graceful failover.  
* **Expose** a simple HTTP/gRPC endpoint that developers can call from anywhere.

This article walks you through the end‑to‑end process of building a **distributed inference service** for large language models using Ray and Kubernetes. We will cover architectural decisions, concrete code snippets, performance‑tuning techniques, and a real‑world case study that demonstrates the impact of a well‑engineered stack.

---

## Why Inference at Scale Is Hard

Before diving into solutions, it is essential to understand the unique constraints that make LLM inference a non‑trivial engineering problem.

| Challenge | Impact on System Design |
|-----------|--------------------------|
| **Model Size** | Models > 30 B parameters exceed the memory of a single GPU; you must split the model across devices (tensor/model parallelism). |
| **Latency Sensitivity** | Interactive applications (chatbots, code assistants) demand sub‑500 ms response times even under load. |
| **Throughput Variability** | Traffic spikes (e.g., a marketing campaign) can increase request rates by an order of magnitude. |
| **Resource Cost** | GPUs are expensive; inefficient utilization leads to high operational expenditure. |
| **Cold‑Start Overhead** | Loading a large model into GPU memory can take seconds to minutes, hurting availability. |
| **Observability** | Distributed inference pipelines generate many metrics (GPU utilization, request latency, queue depth) that need to be aggregated. |

The traditional monolithic approach—run a single model server on a dedicated GPU—fails to address these concerns. You need **horizontal scaling**, **dynamic load balancing**, and **resource‑aware scheduling**, all of which are native capabilities of Ray and Kubernetes.

---

## Ray: A Unified Engine for Distributed Compute

Ray started as a research project at UC Berkeley to simplify the development of distributed Python applications. Its core concepts relevant to inference are:

* **Actors** – Stateful objects that live on a specific node and can process messages (e.g., a model shard).  
* **Tasks** – Stateless functions that can be executed in parallel.  
* **Ray Serve** – A production‑grade model‑serving framework built on top of Ray that handles request routing, batching, and autoscaling.  
* **Placement Groups** – A way to reserve a set of resources (CPU, GPU) across the cluster for a group of actors, guaranteeing collocation when needed.  

Ray abstracts away the low‑level details of RPC, fault tolerance, and scheduling, letting you focus on the business logic of inference.

### Quick Example: A Simple Ray Actor

```python
import ray

ray.init()

@ray.remote(num_gpus=1)
class LLMShard:
    def __init__(self, shard_id, model_path):
        import torch
        self.shard_id = shard_id
        self.model = torch.load(model_path, map_location="cuda")
        self.model.eval()

    def generate(self, prompt):
        # Simplified generation logic
        tokens = self.model.encode(prompt)
        output = self.model.generate(tokens)
        return self.model.decode(output)

# Create two shards for a 70B model split across two GPUs
shard0 = LLMShard.remote(0, "/models/llama2/70b_shard0.pt")
shard1 = LLMShard.remote(1, "/models/llama2/70b_shard1.pt")
```

Ray takes care of placing each actor on a GPU, handling failures, and exposing remote methods.

---

## Kubernetes: The De‑Facto Orchestrator for Cloud‑Native Workloads

Kubernetes (K8s) provides a declarative API to manage containers at scale. Key primitives we’ll use:

| Primitive | Role in Distributed Inference |
|-----------|-------------------------------|
| **Pod** | Smallest deployable unit; each Ray worker runs inside a pod. |
| **Deployment** | Manages replica sets and rolling updates for stateless services (e.g., Ray head node). |
| **StatefulSet** | Guarantees stable network identities for pods that need persistent state (optional for model caching). |
| **Horizontal Pod Autoscaler (HPA)** | Scales the number of worker pods based on custom metrics such as GPU utilization or request latency. |
| **Custom Resource Definitions (CRDs)** | Ray provides a `RayCluster` CRD that simplifies cluster provisioning on K8s. |
| **Service** | Exposes the Ray Serve endpoint via a LoadBalancer or Ingress. |

By deploying Ray on Kubernetes we gain the best of both worlds: **Ray’s fine‑grained scheduling** combined with **K8s’s robust lifecycle management**.

---

## Architectural Blueprint

Below is a high‑level diagram (described textually) of the system:

1. **Client** → Sends HTTP/gRPC request to **Ingress** → **LoadBalancer Service** → **Ray Serve HTTP endpoint**.  
2. **Ray Serve** runs inside a **Ray head pod**; it contains a **router** that dispatches requests to **model actors**.  
3. **Model actors** are Ray actors residing in **worker pods** (each pod may host multiple actors depending on GPU count).  
4. **Placement groups** ensure that a set of actors that together form a model shard get collocated on the same node for low‑latency inter‑GPU communication.  
5. **Metrics Server** + **Prometheus** scrape Ray and K8s metrics; **Grafana** visualizes latency, throughput, GPU memory usage.  
6. **Horizontal Pod Autoscaler** watches custom metrics (e.g., average request queue length) and adds/removes worker pods.

### 5.1 Model Sharding and Parallelism

Two dominant strategies:

* **Tensor Parallelism** – Split each transformer layer’s weight matrix across GPUs. Frameworks like **Megatron‑LM** or **DeepSpeed** implement this.  
* **Pipeline Parallelism** – Divide the model’s layers into stages; each GPU processes a stage, passing activations downstream.

Ray actors can encapsulate either strategy. For example, a **PipelineStage** actor holds a subset of layers and forwards the hidden state to the next stage.

### 5.2 Ray Serve as the Inference Service Layer

Ray Serve provides:

* **Dynamic Batching** – Aggregates multiple requests into a single forward pass, boosting GPU utilization.  
* **Autoscaling** – Adjusts the number of replicas for each backend based on latency SLAs.  
* **Graceful Deployment** – Zero‑downtime rollouts using versioned backends.

### 5.3 Kubernetes Pods as Ray Workers

Each worker pod typically runs a **Ray node** (`ray start --address=...`) and may launch multiple actors. By requesting `resources.limits["nvidia.com/gpu"]` in the pod spec, K8s schedules the pod onto a GPU‑enabled node.

---

## Step‑by‑Step Deployment Guide

### 6.1 Containerizing the Model

Create a Dockerfile that installs Ray, the model libraries, and copies the model weights.

```dockerfile
# Dockerfile
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

# System dependencies
RUN apt-get update && apt-get install -y python3-pip git && rm -rf /var/lib/apt/lists/*

# Python environment
RUN pip install --no-cache-dir \
    torch==2.2.0+cu121 \
    transformers==4.38.2 \
    ray[default]==2.9.0 \
    deepspeed==0.14.2 \
    accelerate==0.28.0

# Copy model files (assume they are baked into the image for simplicity)
COPY models/ /models/

# Entry point script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
```

`entrypoint.sh` will start either a **Ray head** or **worker** based on an environment variable:

```bash
#!/usr/bin/env bash
set -e

if [[ "$RAY_ROLE" == "head" ]]; then
    ray start --head --port=6379 --dashboard-host=0.0.0.0
    # Keep the container alive
    tail -f /dev/null
else
    ray start --address=$RAY_HEAD_SERVICE:6379
    # Worker processes will be launched by the Ray operator
    tail -f /dev/null
fi
```

### 6.2 Defining the Ray Cluster on Kubernetes

Ray provides a **RayCluster** CRD that abstracts the head and worker pods. Below is a minimal manifest.

```yaml
# ray-cluster.yaml
apiVersion: ray.io/v1alpha1
kind: RayCluster
metadata:
  name: llm-inference
spec:
  headGroupSpec:
    serviceType: LoadBalancer
    replicas: 1
    rayStartParams:
      dashboard-host: "0.0.0.0"
    template:
      spec:
        containers:
        - name: ray-head
          image: your-registry/llm-ray:latest
          env:
          - name: RAY_ROLE
            value: "head"
          resources:
            limits:
              nvidia.com/gpu: 1
            requests:
              cpu: "2"
              memory: "8Gi"
  workerGroupSpecs:
    - groupName: gpu-workers
      replicas: 2   # start with 2 workers; HPA will scale
      minReplicas: 2
      maxReplicas: 10
      rayStartParams: {}
      template:
        spec:
          containers:
          - name: ray-worker
            image: your-registry/llm-ray:latest
            env:
            - name: RAY_ROLE
              value: "worker"
            resources:
              limits:
                nvidia.com/gpu: 4   # each worker pod gets 4 GPUs
              requests:
                cpu: "8"
                memory: "32Gi"
```

Apply the manifest:

```bash
kubectl apply -f ray-cluster.yaml
```

The Ray operator will spin up the head service (`llm-inference-head-svc`) and the worker pods. You can inspect the cluster with `ray status` inside any pod.

### 6.3 Serving the Model with Ray Serve

Create a Python module `serve_app.py` that defines the model backend and registers it with Ray Serve.

```python
# serve_app.py
import os
import ray
from ray import serve
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

# -------------------------------------------------
# Helper: load a model shard (adjust for your parallelism lib)
# -------------------------------------------------
def load_shard(shard_id: int, checkpoint_dir: str):
    # Example using DeepSpeed zero‑3 (simplified)
    from deepspeed import init_inference
    model = AutoModelForCausalLM.from_pretrained(
        checkpoint_dir,
        torch_dtype=torch.float16,
        low_cpu_mem_usage=True,
    )
    model = init_inference(
        model,
        mp_size=4,  # number of GPUs per node
        dtype=torch.float16,
        replace_method="auto",
    )
    return model

# -------------------------------------------------
# Backend definition
# -------------------------------------------------
@serve.deployment(
    name="llm_backend",
    num_replicas=2,
    ray_actor_options={"num_gpus": 4},   # each replica gets 4 GPUs
    max_ongoing_requests=64,
    autoscaling_config=serve.AutoscalingConfig(
        min_replicas=2,
        max_replicas=10,
        target_num_ongoing_requests_per_replica=32,
    ),
)
class LLMBackend:
    def __init__(self):
        checkpoint = os.getenv("MODEL_CHECKPOINT", "/models/llama2-70b")
        self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
        self.model = load_shard(shard_id=0, checkpoint_dir=checkpoint)

    async def __call__(self, request):
        # Parse JSON payload {"prompt": "..."}
        payload = await request.json()
        prompt = payload.get("prompt", "")
        inputs = self.tokenizer(prompt, return_tensors="pt").to("cuda")
        # Simple generation; replace with your sampling strategy
        generated_ids = self.model.generate(**inputs, max_new_tokens=128)
        output = self.tokenizer.decode(generated_ids[0], skip_special_tokens=True)
        return {"generated_text": output}

# -------------------------------------------------
# Startup: initialize Ray and Serve
# -------------------------------------------------
if __name__ == "__main__":
    ray.init(address=os.getenv("RAY_ADDRESS"))
    serve.start(detached=True)
    LLMBackend.deploy()
    print("LLM Serve is up and running.")
```

Deploy the backend from any pod (e.g., the head pod):

```bash
kubectl exec -it $(kubectl get pod -l ray.io/cluster=llm-inference -l ray.io/node-type=head -o jsonpath='{.items[0].metadata.name}') -- bash
python serve_app.py
```

Ray Serve automatically creates an HTTP endpoint at `http://<head-service>:8000/llm_backend`. You can test it:

```bash
curl -X POST http://<head-service>:8000/llm_backend -H "Content-Type: application/json" -d '{"prompt":"Explain quantum entanglement in simple terms."}'
```

You should receive a JSON response with the generated text.

---

## Scaling Strategies

### 7.1 Horizontal Pod Autoscaling (HPA)

Kubernetes can scale the worker group based on **custom metrics** exported by Ray Serve. Ray exposes a Prometheus endpoint (`/metrics`) that includes `ray_serve_ongoing_requests`. Create a `PrometheusAdapter` and an HPA manifest:

```yaml
# hpa.yaml
apiVersion: autoscaling/v2beta2
kind: HorizontalPodAutoscaler
metadata:
  name: llm-worker-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: StatefulSet   # or Deployment if you used that
    name: llm-inference-worker
  minReplicas: 2
  maxReplicas: 12
  metrics:
  - type: Pods
    pods:
      metric:
        name: ray_serve_ongoing_requests
      target:
        type: AverageValue
        averageValue: "30"
```

The HPA will add a worker pod whenever the average number of ongoing requests per pod exceeds 30, keeping latency within the target SLA.

### 7.2 Ray Placement Groups for Resource Guarantees

When using **pipeline parallelism**, stages need to be collocated on the same node to avoid costly inter‑node data transfer. Ray’s placement groups let you reserve a set of GPUs together:

```python
import ray
from ray.util.placement_group import placement_group

pg = placement_group(
    name="pipeline_pg",
    bundles=[{"GPU": 4}, {"GPU": 4}],  # two stages, each 4 GPUs
    strategy="STRICT_SPREAD",         # ensure each bundle lands on a distinct node
)
ray.get(pg.ready())
```

You can then create actors with `placement_group=pg` to guarantee that each stage runs on the reserved GPUs.

### 7.3 Dynamic Actor Scaling

Ray Serve’s **autoscaling_config** (shown earlier) automatically spawns or removes replicas of a backend based on request load. Inside the backend you can also **scale actors** manually:

```python
class ShardManager:
    def __init__(self):
        self.shards = [LLMShard.remote(i, path) for i in range(num_shards)]

    async def generate(self, prompt):
        # Simple round‑robin dispatch
        shard = self.shards[hash(prompt) % len(self.shards)]
        return await shard.generate.remote(prompt)
```

If a particular shard becomes a hotspot, you could spin up a duplicate actor and route a portion of traffic to it, then merge results later.

---

## Performance Optimizations

### 8.1 Batching Requests

Dynamic batching aggregates multiple prompts into a single tensor before feeding it to the model. In Ray Serve you enable it by setting `max_batch_size` and `batch_wait_timeout_s`.

```python
@serve.deployment(
    name="llm_backend",
    max_batch_size=32,
    batch_wait_timeout_s=0.01,   # 10 ms max wait
)
class LLMBackend:
    # __call__ now receives a list of requests
    async def __call__(self, requests):
        prompts = [await r.json() for r in requests]
        # Encode all prompts together
        inputs = self.tokenizer(
            [p["prompt"] for p in prompts],
            return_tensors="pt",
            padding=True,
        ).to("cuda")
        generated_ids = self.model.generate(**inputs, max_new_tokens=128)
        outputs = self.tokenizer.batch_decode(generated_ids, skip_special_tokens=True)
        return [{"generated_text": out} for out in outputs]
```

Batching can raise GPU utilization from ~30 % to >80 % without sacrificing latency for typical request sizes.

### 8.2 Quantization & Mixed‑Precision

Running the model in **FP16** (half‑precision) halves memory bandwidth; further gains are possible with **INT8** quantization using libraries like **bitsandbytes** or **GPTQ**.

```python
from transformers import BitsAndBytesConfig

quant_cfg = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_use_double_quant=True,
)

model = AutoModelForCausalLM.from_pretrained(
    checkpoint,
    quantization_config=quant_cfg,
    device_map="auto",
)
```

Quantized models can often fit a 70 B model on a single 40 GB GPU, dramatically reducing cost.

### 8.3 Cache‑Aware Scheduling

LLM inference often repeats the same **prompt prefixes** (e.g., system messages). By caching the key/value attention tensors for these prefixes, you can avoid recomputation. Ray actors can hold a **per‑session cache** in GPU memory:

```python
class CachedLLMActor:
    def __init__(self):
        self.cache = {}  # map from prefix hash -> past_key_values

    async def generate(self, prompt):
        prefix, suffix = split_prompt(prompt)
        if prefix_hash := hash(prefix) in self.cache:
            past_kv = self.cache[prefix_hash]
        else:
            past_kv = self.model.encode_prefix(prefix)
            self.cache[prefix_hash] = past_kv
        # Generate using cached past_kv
        output = self.model.generate(suffix, past_key_values=past_kv)
        return output
```

The cache must be sized carefully to avoid OOM; eviction policies (LRU) are common.

---

## Monitoring, Logging, and Observability

A production inference service must be observable. The stack typically includes:

* **Prometheus** – Scrapes metrics from Ray (`/metrics`), Kubernetes (`kube-state-metrics`), and GPU exporters (`DCGM Exporter`).  
* **Grafana** – Dashboards showing request latency, GPU utilization, queue depth, and autoscaler decisions.  
* **Elastic Stack / Loki** – Centralized log aggregation for tracing request paths across Ray actors.  
* **Jaeger** – Distributed tracing; Ray Serve can emit OpenTelemetry spans for each request.

Example Prometheus scrape config for Ray:

```yaml
scrape_configs:
  - job_name: 'ray'
    static_configs:
      - targets: ['llm-inference-head-svc:8000']  # Ray Serve metrics endpoint
```

A useful Grafana panel:

```text
avg_over_time(ray_serve_request_latency_seconds_sum[5m]) /
avg_over_time(ray_serve_request_latency_seconds_count[5m])
```

Set alerts (via Alertmanager) when latency exceeds 500 ms or GPU memory usage > 90 %.

---

## Real‑World Case Study: Chatbot‑as‑a‑Service for a FinTech Platform

**Background** – A FinTech startup needed a conversational AI that could answer regulatory questions in real time for millions of users. The model of choice was Llama‑2‑70B with a custom fine‑tuned layer for compliance terminology.

**Challenges**  
* Peak traffic of 5 k requests/second during market‑open hours.  
* Latency SLA: 300 ms 95th percentile.  
* Cost constraint: stay under $15 k/month GPU spend.

**Solution Architecture**  

1. **Model Parallelism** – Used **Tensor Parallelism** with 8‑GPU shards (4 nodes × 2 GPUs each) via DeepSpeed ZeRO‑3.  
2. **Ray Serve Backend** – Deployed a single backend with `max_batch_size=64` and `autoscaling_config` targeting 30 ongoing requests per replica.  
3. **K8s HPA** – Configured to scale from 4 to 20 worker pods based on `ray_serve_ongoing_requests`.  
4. **Quantization** – Applied 4‑bit quantization, reducing GPU memory per shard from 45 GB to 13 GB, allowing two shards per 40 GB GPU.  
5. **Caching** – Implemented prefix caching for the standard compliance pre‑amble, cutting per‑request compute by ~15 %.  

**Results**  

| Metric | Before | After |
|--------|--------|-------|
| 95th‑pct latency | 620 ms | 258 ms |
| GPU utilization (avg) | 28 % | 78 % |
| Monthly GPU cost | $22 k | $13 k |
| Peak RPS handled | 2.8 k | 5.2 k |

The combination of Ray’s dynamic batching, Kubernetes auto‑scaling, and model quantization delivered both performance and cost savings, meeting the SLA without over‑provisioning.

---

## Best Practices Checklist

- **Model Partitioning**  
  - Choose tensor vs. pipeline parallelism based on model size and network topology.  
  - Use DeepSpeed or Megatron‑LM for proven implementations.  

- **Resource Reservation**  
  - Leverage Ray placement groups to guarantee collocation for pipeline stages.  
  - Set `resources.limits["nvidia.com/gpu"]` in K8s pod specs to avoid oversubscription.  

- **Autoscaling**  
  - Enable Ray Serve autoscaling **and** K8s HPA for a two‑layer scaling strategy.  
  - Tune `target_num_ongoing_requests_per_replica` to reflect your latency SLA.  

- **Batching & Queue Management**  
  - Set `max_batch_size` and `batch_wait_timeout_s` based on average request size.  
  - Monitor queue depth; high queue length indicates the need for more replicas.  

- **Quantization & Precision**  
  - Start with FP16; move to 4‑bit or 8‑bit only after validating accuracy.  
  - Profile memory with `nvidia-smi` and `torch.cuda.memory_summary()`.  

- **Observability**  
  - Export Ray metrics to Prometheus; create alerts for latency and GPU OOM.  
  - Use OpenTelemetry to trace a request across Ray actor hops.  

- **Security & Multi‑Tenancy**  
  - Deploy each tenant’s model in a separate Ray namespace or Kubernetes namespace.  
  - Use Istio or Linkerd for mTLS between client ingress and Ray Serve.  

- **CI/CD Integration**  
  - Store model artifacts in an immutable artifact repository (e.g., S3 with versioned keys).  
  - Automate Ray Serve deployments with Helm charts and Argo CD.  

---

## Conclusion

Scaling inference for large language models is no longer an academic exercise—enterprises are demanding real‑time, high‑throughput AI services at production scale. By marrying **Ray’s flexible, actor‑based runtime** with **Kubernetes’ battle‑tested orchestration**, engineers gain a powerful, cloud‑native stack that can:

* Distribute massive models across many GPUs without manual placement.  
* Dynamically batch and autoscale to keep latency within tight SLAs.  
* Leverage quantization, caching, and placement groups for optimal performance.  
* Provide full observability and graceful failure handling.

The end‑to‑end guide above equips you with the concrete steps—Dockerizing the model, defining a RayCluster CRD, writing a Ray Serve backend, and configuring autoscaling—to build a production‑grade distributed inference service. As LLMs continue to grow, the patterns described here will remain relevant, enabling you to serve the next generation of AI models efficiently and cost‑effectively.

---

## Resources

- Ray Documentation – Serve & Placement Groups: <https://docs.ray.io/en/latest/serve/index.html>  
- Kubernetes Autoscaling Guide: <https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/>  
- DeepSpeed ZeRO‑3 and Quantization: <https://www.deepspeed.ai/tutorials/zero/>  
- NVIDIA GPU Operator for Kubernetes (GPU scheduling): <https://github.com/NVIDIA/k8s-gpu-operator>  
- Llama‑2 Model Card (Meta AI): <https://ai.meta.com/llama/>  

Feel free to explore these resources, experiment with the code snippets, and adapt the architecture to your own workload. Happy scaling!