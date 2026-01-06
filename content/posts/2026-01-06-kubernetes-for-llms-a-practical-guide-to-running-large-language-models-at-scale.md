---
title: "Kubernetes for LLMs: A Practical Guide to Running Large Language Models at Scale"
date: "2026-01-06T07:51:10.188"
draft: false
tags: ["kubernetes", "llm", "mlops", "ai-infrastructure", "devops"]
---

Large Language Models (LLMs) are moving from research labs into production systems at an incredible pace. As soon as organizations move beyond simple API calls to third‑party providers, a question appears:

**“How do we run LLMs ourselves, reliably, and at scale?”**

For many teams, the answer is: **Kubernetes**.

This article dives into **Kubernetes for LLMs**—when it makes sense, how to design the architecture, common pitfalls, and concrete configuration examples. The focus is on **inference (serving)**, with notes on **fine‑tuning and training** where relevant.

---

## Why Kubernetes for LLMs?

Running LLMs is different from typical microservices:

- They require **GPUs**, often with large memory.
- They have **heavy startup times** and large model downloads.
- They benefit from **batching**, **caching**, and **specialized runtimes**.
- They can be **expensive**, so autoscaling and scheduling matter.

Kubernetes is a strong fit because it provides:

- **Standardization**: Same platform for web apps, APIs, and LLMs.
- **Portability**: Cloud‑agnostic deployments (if you design for it).
- **Autoscaling**: Horizontal Pod Autoscaler (HPA), KEDA, cluster autoscalers.
- **Ecosystem**: Operators, KServe, Kubeflow, Ray, monitoring stacks, etc.
- **Multi‑tenancy & isolation**: Namespaces, ResourceQuotas, NetworkPolicy.

But to make Kubernetes work well for LLMs, you have to design for their specifics, especially **GPU scheduling, networking, and observability**.

---

## Core Building Blocks: Kubernetes + GPUs

To run LLMs, you’ll almost always need GPUs. A typical high‑level setup:

1. **GPU‑enabled Kubernetes nodes** (e.g., `nvidia-tesla-t4`, `a10g`, `h100`).
2. **GPU device plugin** (e.g., NVIDIA Device Plugin DaemonSet).
3. **Container images** with CUDA, drivers, and the model runtime.
4. **Pods** that request GPU resources.
5. **Deployments** or specialized CRDs (KServe, Seldon, Ray, etc.) to manage LLM servers.

### GPU‑Aware Pod Spec

Kubernetes doesn’t know “GPU” natively; it uses **extended resources** exposed by the device plugin.

A basic pod requesting 1 GPU:

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: llm-inference-pod
spec:
  containers:
    - name: llm-server
      image: my-registry/llm-server:latest
      resources:
        limits:
          nvidia.com/gpu: 1   # Request 1 GPU
          cpu: "4"
          memory: "32Gi"
        requests:
          cpu: "2"
          memory: "16Gi"
```

In production, you’ll rarely run standalone Pods; you’ll use **Deployments**, **StatefulSets**, or higher‑level frameworks. But this illustrates the GPU request model.

> **Note**: The resource name `nvidia.com/gpu` is defined by the NVIDIA device plugin. If you use another vendor or plugin, the resource name may differ.

---

## LLM Inference Architectures on Kubernetes

LLM inference on Kubernetes tends to fall into a few patterns.

### 1. Single‑Model, Single‑Tenant Service

Use this when:

- You serve a **single model** (e.g., `Llama-3-8B-instruct`) behind an API.
- You have relatively **predictable load**.
- You can dedicate GPUs to that one model.

Architecture:

- **Deployment**: one or more Pods running an LLM runtime (e.g. vLLM, TGI, Ollama server).
- **Service**: cluster‑internal or external, fronted by Ingress or API gateway.
- **HPA**: scale Pods based on QPS, latency, or GPU utilization via custom metrics.

Pros:

- Simple to reason about.
- Stable performance.
- Easy to monitor.

Cons:

- Wastes capacity if the model is idle.
- Less suitable for many small models / tenants.

### 2. Multi‑Model, Multi‑Tenant Gateway

Use this when:

- You host **many models** or **tenants**.
- You want to share GPUs across workloads.
- You need dynamic model loading/unloading.

Typical setup:

- A **gateway/API service** that:
  - Authenticates and authorizes requests.
  - Routes to specific LLM runtimes, or loads models on demand.
- One or more **shared GPU pools** where runtime servers can load different models.
- An internal **metadata/config service** for model registry (versions, weights).

Common tools:

- **vLLM** with multi‑model support.
- **Text Generation Inference (TGI)** with multiple models.
- Custom routers built with **FastAPI**, **gRPC**, or **Envoy filters**.

Pros:

- Better GPU utilization.
- Centralized security and rate limiting.
- Easier lifecycle management for new models.

Cons:

- More complex routing and scheduling.
- Requires careful design to avoid noisy neighbor issues.

### 3. LLM as Part of a Larger Workflow

Use this when:

- LLM is a **step** in pipelines: RAG workflows, agents, or batch jobs.
- You use orchestration tools (Airflow, Prefect, Argo Workflows, Kubeflow Pipelines).

Pattern:

- LLMs run as **services** in‑cluster (like patterns 1 or 2).
- Workflow steps talk to those services via HTTP/gRPC.
- Vector databases (e.g., Milvus, Qdrant, pgvector) and other components also run on Kubernetes.

Pros:

- Everything lives in a single platform.
- Easier end‑to‑end observability and policy enforcement.

Cons:

- Requires robust capacity planning so workflows don’t starve LLM services.

---

## Choosing an LLM Serving Stack on Kubernetes

Your choice of serving stack affects performance, cost, and developer experience.

### Popular Options

1. **vLLM**
   - High‑throughput LLM inference engine (CUDA + PagedAttention).
   - Good batching and KV cache management.
   - Works with many Hugging Face models.
   - Easy to wrap in a FastAPI or OpenAI‑compatible server.

2. **Text Generation Inference (TGI)**
   - Hugging Face’s production‑grade text generation server.
   - Optimized for transformer models; supports quantization, tensor parallelism.
   - Exposes a REST API.

3. **KServe**
   - Kubernetes‑native model serving framework.
   - CRD‑based: you define `InferenceService` objects instead of raw Deployments.
   - Integrates with Istio/Knative for traffic routing, autoscaling.

4. **BentoML / OpenLLM**
   - Higher‑level frameworks that package models as self‑contained services.
   - Provide tooling for building, versioning, and deploying to Kubernetes.

5. **Ray Serve**
   - Distributed serving on top of Ray.
   - Very useful when LLM inference is part of a larger distributed compute graph.

For most teams getting started, a practical approach is:

- Use **vLLM** or **TGI** inside a **Deployment**.
- Expose an HTTP/gRPC API.
- Add autoscaling and a gateway (Ingress or API gateway).
- Consider KServe or BentoML later when you need more features.

---

## Example: Deploying vLLM on Kubernetes

### Container Image

Your image must include:

- CUDA and matching NVIDIA drivers/libraries (aligned with node GPU drivers).
- Python runtime.
- vLLM and dependencies.
- Model weights or a way to download them on startup.

A simplified Dockerfile (non‑production):

```dockerfile
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

RUN apt-get update && apt-get install -y python3 python3-pip git && \
    rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir vllm==0.4.0 fastapi uvicorn

WORKDIR /app

# Example: simple OpenAI-compatible server using vLLM
COPY server.py /app/server.py

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

`server.py` (very simplified):

```python
from fastapi import FastAPI
from pydantic import BaseModel
from vllm import LLM, SamplingParams

app = FastAPI()
llm = LLM(model="meta-llama/Meta-Llama-3-8B-Instruct")  # or local path

class GenerateRequest(BaseModel):
    prompt: str
    max_tokens: int = 256
    temperature: float = 0.7

@app.post("/v1/generate")
def generate(req: GenerateRequest):
    outputs = llm.generate(
        [req.prompt],
        SamplingParams(
            max_tokens=req.max_tokens,
            temperature=req.temperature
        )
    )
    return {"text": outputs[0].outputs[0].text}
```

> **Production tip**: Don’t download large models at container startup unless you have a local cache. Either bake weights into the image, mount them from a fast object storage cache, or pre‑warm nodes.

### Kubernetes Deployment + Service

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: vllm-llama3
  labels:
    app: vllm-llama3
spec:
  replicas: 1
  selector:
    matchLabels:
      app: vllm-llama3
  template:
    metadata:
      labels:
        app: vllm-llama3
    spec:
      nodeSelector:
        gpu: "nvidia"              # ensure this matches your node labels
      tolerations:
        - key: "gpu-only"
          operator: "Exists"
          effect: "NoSchedule"
      containers:
        - name: vllm-server
          image: my-registry/vllm-llama3:latest
          ports:
            - containerPort: 8000
          resources:
            limits:
              nvidia.com/gpu: 1
              cpu: "6"
              memory: "48Gi"
            requests:
              cpu: "4"
              memory: "32Gi"
          env:
            - name: VLLM_MAX_MODEL_LEN
              value: "4096"
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 60
            periodSeconds: 15
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 30
---
apiVersion: v1
kind: Service
metadata:
  name: vllm-llama3
spec:
  selector:
    app: vllm-llama3
  ports:
    - port: 80
      targetPort: 8000
  type: ClusterIP
```

You’d typically expose this with an **Ingress** and an **IngressController** (NGINX, Traefik, Istio, etc.) or via a managed API gateway.

---

## Autoscaling LLM Workloads

Autoscaling is critical to keep latency low while avoiding runaway GPU costs.

### Horizontal Pod Autoscaling (HPA)

HPA scales Pods based on CPU, memory, or **custom metrics**.

For LLMs, CPU/memory are often poor proxies for **actual load**. Better signals:

- **Requests per second** (QPS).
- **In‑flight requests**.
- **95th percentile latency**.
- **GPU utilization** (via metrics from NVIDIA DCGM exporter or dcgm-exporter).

Assuming you expose a custom metric `llm_requests_per_second`, here’s a basic HPA:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vllm-llama3-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm-llama3
  minReplicas: 1
  maxReplicas: 6
  metrics:
    - type: Pods
      pods:
        metric:
          name: llm_requests_per_second
        target:
          type: AverageValue
          averageValue: "5"  # target 5 RPS per pod
```

You’ll need:

- A metrics adapter (e.g. **Prometheus Adapter**) to expose Prometheus metrics as custom metrics.
- Instrumentation in your LLM server to emit `llm_requests_per_second`.

### Cluster Autoscaler and GPU Node Pools

HPA only adds Pods. To get **more GPU nodes**, you need:

- A **cluster autoscaler** (e.g., AWS Cluster Autoscaler, GKE Autopilot, Karpenter).
- A GPU node pool (e.g., node group with `g4dn.xlarge` or `a10g` nodes).
- Proper **scheduling constraints** so GPU pods land only on GPU nodes.

Example node selector & taint approach:

- Label GPU nodes: `gpu=nvidia`.
- Taint GPU nodes: `gpu-only=true:NoSchedule`.
- Configure LLM pods with:

```yaml
nodeSelector:
  gpu: "nvidia"
tolerations:
  - key: "gpu-only"
    operator: "Exists"
    effect: "NoSchedule"
```

This keeps non‑GPU workloads off your expensive nodes.

---

## Handling Models and Storage

Models are large—often 10s to 100s of GB per model. Storage design matters for:

- **Startup time**.
- **Node reuse** and locality.
- **Cost**.

### Common Strategies

1. **Bake Models Into Images**
   - Pros: Fast startup, no download at runtime.
   - Cons: Massive images (tens of GB), slow pulls, frequent rebuilds on updates.

2. **Download on First Use + Local Cache**
   - Store models in **object storage** (S3, GCS, Azure Blob) or Hugging Face Hub.
   - On startup, download to a local path on the node.
   - Cache using:
     - HostPath volumes (node local disk).
     - `emptyDir` + node‑local disk.
     - DaemonSet that pre‑caches models on GPU nodes.

3. **Network File System (NFS, Lustre, FSx for Lustre, etc.)**
   - Mount shared filesystem as PVC.
   - Pros: Centralized storage, simpler updates.
   - Cons: Latency/bandwidth bottlenecks if not fast enough.

### Example: Using an Object Storage Bucket with a PVC Cache

A pattern that works well in many setups:

- Use a **local directory** on each node as a cache.
- Use an **initContainer** to sync from object storage if missing.

```yaml
spec:
  volumes:
    - name: model-cache
      hostPath:
        path: /var/cache/models  # node local path
        type: DirectoryOrCreate
  initContainers:
    - name: init-model
      image: amazon/aws-cli:2.15.0
      command: ["sh", "-c"]
      args:
        - |
          if [ ! -d /models/meta-llama3 ]; then
            echo "Syncing model..."
            aws s3 sync s3://my-model-bucket/meta-llama3 /models/meta-llama3
          else
            echo "Model cache exists, skipping download."
          fi
      volumeMounts:
        - name: model-cache
          mountPath: /models
  containers:
    - name: vllm-server
      # ...
      volumeMounts:
        - name: model-cache
          mountPath: /models
      env:
        - name: MODEL_PATH
          value: /models/meta-llama3
```

This balances startup time and flexibility.

---

## Observability for LLMs on Kubernetes

LLM systems fail in non‑obvious ways: degraded throughput, GPU under‑utilization, tokenization issues, prompt drift. Good observability is crucial.

### Metrics

Combine:

- **Platform metrics**:
  - Pod CPU, memory, restarts.
  - Node GPU utilization, memory usage (via **dcgm-exporter** or **nvidia-dcgm-exporter**).
- **Application metrics**:
  - Requests per second.
  - Latency percentiles (P50, P95, P99).
  - Tokens per second (input and output).
  - Queue length / in‑flight requests.
  - Cache hit rates (KV cache, embedding cache, etc.).

Use:

- **Prometheus** + **Grafana** for metrics + dashboards.
- **Prometheus Adapter** for feeding custom metrics to HPA.

### Logs

Capture:

- Request logs with:
  - Model name, version.
  - Tenant / API key ID.
  - Input length (token count, not raw text).
  - Latency and outcome (success, timeout, error).
- Error logs with stack traces.
- Startup logs (model loading times, memory usage).

Use:

- Cluster log aggregation (e.g., **ELK**, **Loki**, **OpenSearch**, or cloud‑native logging).

> **Privacy note**: Avoid logging full prompts or outputs in production, especially with sensitive data. Log **metadata** and maybe hashed/sampled content with strong governance.

### Tracing

For complex pipelines (RAG, multi‑step workflows), use **distributed tracing**:

- **OpenTelemetry** instrumentation.
- Trace spans from:
  - Ingress / gateway.
  - LLM server.
  - Vector database queries.
  - Downstream tools.

This makes it easier to answer “Where is the latency coming from?” and “Which component is failing?”

---

## Security and Multi‑Tenancy

When multiple teams, apps, or customers share LLM infrastructure, you must think about:

- **API security**
- **Resource isolation**
- **Data separation**

### API Security

- **Authentication**:
  - JWTs, API keys, or OAuth2.
  - Gateway‑level auth (Kong, Istio, Ambassador, Envoy).
- **Authorization**:
  - Map tokens to tenants and rate limits.
  - Restrict which models tenants can access.
- **Rate limiting and quotas**:
  - Per‑tenant QPS limits.
  - Per‑day token limits.

### Kubernetes‑Level Isolation

Use:

- **Namespaces**: Separate teams or environments (`prod`, `staging`, `dev`).
- **ResourceQuota** and **LimitRange**:
  - Prevent noisy neighbors from grabbing all GPUs or CPU.
- **NetworkPolicy**:
  - Restrict cross‑namespace traffic.
  - Limit LLM services to only necessary clients.

Example `ResourceQuota`:

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-llm-quota
  namespace: team-llm
spec:
  hard:
    limits.cpu: "64"
    limits.memory: "256Gi"
    requests.nvidia.com/gpu: "8"
```

---

## Special Considerations for LLM Training and Fine‑Tuning

While this article is focused on **inference**, many organizations also want to do **fine‑tuning** or **pre‑training** on Kubernetes.

Key differences from inference:

- Training uses **distributed compute** across many GPUs (8, 16, 64+).
- Communication patterns (e.g., **NCCL**, **RDMA**) are sensitive to network topology.
- Jobs are typically **batch‑oriented**, not long‑lived services.

### Tools and Patterns

- **Kubeflow**: Pipelines, TFJob, PyTorchJob CRDs.
- **Ray**: Distributed training, Ray Cluster CRDs.
- **Lightning AI, Accelerate, DeepSpeed**: integrated with K8s via job controllers or Helm charts.
- **Argo Workflows**: For orchestrating training workflows and evaluation.

A common approach:

- Use **Job** or **custom training CRDs** (e.g., `PyTorchJob`) to run training on dedicated GPU nodes.
- Use **separate node pools** for training vs. inference:
  - Training nodes: large multi‑GPU machines, pre‑emptible or spot where possible.
  - Inference nodes: tuned for low latency, stable capacity.

> **Tip**: Keep training and inference workloads separated at the cluster level if possible (e.g., different clusters) to simplify capacity planning and fault domains.

---

## Performance Tuning for LLMs on Kubernetes

LLM performance is highly sensitive to configuration details. Some tuning levers:

### Model and Runtime

- Use **quantized models** (e.g., 4‑bit, 8‑bit) where quality allows.
- Choose appropriate **model size** for each use case.
- Enable runtime features:
  - KV cache.
  - Continuous batching.
  - Speculative decoding (where supported).

### GPU Utilization

- Monitor:
  - GPU `utilization` (not just memory).
  - GPU memory fragmentation.
- Reduce **undersized batch sizes**; use batching to keep GPUs busy.
- Avoid oversubscribing GPU memory (OOMs cause restarts and long downtime).

### Pod and Node Configuration

- Set realistic **resource requests/limits**:
  - Memory request close to actual usage to improve scheduling.
  - CPU request enough to handle tokenization and orchestrating GPU work.
- Use **hugepages** where appropriate for some runtimes.
- Pin **NUMA** and CPU affinity if you are very performance‑sensitive.

### Cold Starts and Pre‑Warming

- LLM pods are **slow to start**:
  - Image pull time.
  - Model load time.
- Strategies:
  - Keep a **minimum number of warm replicas**.
  - Use **pod priority classes** so LLM pods get scheduled quickly.
  - Pre‑warm nodes with DaemonSets that pull images and pre‑cache models.

---

## CI/CD and Model Lifecycle on Kubernetes

Treat LLMs as **versioned artifacts**:

- Models have versions: `llama3-8b-v1`, `llama3-8b-v2`.
- Container images (or configuration) reference specific model versions.
- Deployments serve specific versions; traffic is shifted gradually.

### Recommended Practices

1. **Separate code and model versions**
   - Code image: LLM server logic, runtime.
   - Model config: points to a specific model (weights) version.

2. **GitOps for Infrastructure**
   - Use tools like **Argo CD** or **Flux**:
     - Store Kubernetes manifests or Helm charts in Git.
     - Review/approve changes via PRs.
     - Roll back easily.

3. **Canary Deployments**
   - Use **progressive delivery**:
     - Start with a small percentage of traffic to new model/version.
     - Monitor metrics (latency, errors, quality scores).
   - Implement with:
     - Istio / Linkerd / NGINX canary, or
     - KServe’s traffic splitting.

4. **Model Registry and Promotion**
   - Maintain a model registry (could be:
     - MLflow Models, or
     - Internal DB with metadata).
   - Promotion pipeline:
     - `staging` → `shadow` → `canary` → `production`.

---

## When Kubernetes Might Not Be the Right Tool (Yet)

Despite its benefits, Kubernetes is not *always* the best answer:

- **Very small scale** (single GPU, single model):
  - Standalone VM with Docker + systemd is simpler.
- **Highly specialized on‑prem HPC**:
  - Traditional HPC schedulers (Slurm, LSF) may be more mature for massive distributed training.
- **Fully managed PaaS options**:
  - If your team is small and vendor lock‑in is acceptable, managed LLM platforms (SageMaker, Vertex AI, Bedrock) can reduce operational burden.

You can also adopt a **hybrid model**:

- Use a managed LLM API for exploratory and low‑volume workloads.
- Use Kubernetes for cost‑sensitive, high‑volume, or regulated workloads where you want more control.

---

## Practical Checklist: Bringing LLMs to Kubernetes

If you’re planning an LLM rollout on Kubernetes, use this checklist as a starting point:

1. **Cluster and Nodes**
   - [ ] GPU node pool available and tested.
   - [ ] NVIDIA (or vendor) device plugin installed and working.
   - [ ] Cluster autoscaler configured for GPU nodes.

2. **LLM Runtime**
   - [ ] Choose serving engine (vLLM, TGI, BentoML, KServe, etc.).
   - [ ] Container image built and pushed.
   - [ ] Model storage strategy decided (image‑baked vs cache vs network FS).

3. **Kubernetes Manifests**
   - [ ] Deployment/StatefulSet with GPU requests.
   - [ ] Service and Ingress/API gateway.
   - [ ] Readiness/liveness probes tuned for long startup times.
   - [ ] Node selectors and tolerations set for GPU nodes.

4. **Autoscaling and Capacity**
   - [ ] HPA with relevant custom metrics (QPS, latency, GPU util).
   - [ ] Cluster autoscaler verified to add/remove GPU nodes.
   - [ ] Baseline and peak capacity planned.

5. **Observability**
   - [ ] Prometheus and Grafana with LLM dashboards.
   - [ ] GPU metrics collector (dcgm‑exporter).
   - [ ] Log aggregation for LLM services.
   - [ ] Optional tracing with OpenTelemetry for multi‑step flows.

6. **Security and Governance**
   - [ ] Authentication and authorization at gateway.
   - [ ] Rate limits and quotas per tenant/app.
   - [ ] Namespaces, ResourceQuota, and NetworkPolicy in place.
   - [ ] Data retention and logging policies for prompts/outputs.

7. **Lifecycle and Quality**
   - [ ] CI/CD pipeline for code and models.
   - [ ] Model registry with metadata and evaluation results.
   - [ ] Canary/shadow deployment practices defined.
   - [ ] Quality monitoring (human eval, automated scoring, safety checks).

---

## Conclusion

Kubernetes is a powerful platform for running LLMs at scale—but it is not “plug and play”. LLM workloads bring unique demands:

- GPU scheduling and autoscaling
- Large model storage and caching
- Throughput‑sensitive serving with batching and caching
- Robust observability and security for multi‑tenant environments

By combining **Kubernetes primitives** (Deployments, Services, HPAs, node pools) with **LLM‑aware runtimes** (vLLM, TGI, KServe) and a solid approach to observability, you can build an LLM platform that is:

- **Scalable**: Automatically adjusts to demand.
- **Cost‑efficient**: Keeps GPUs busy without overspending.
- **Reliable**: Observable, debuggable, and resilient.
- **Extensible**: Ready to integrate with RAG workflows, agents, and new models.

For many organizations, the path forward is iterative: start by serving a single model on GPU‑enabled Kubernetes, build observability and autoscaling, and then gradually evolve into a multi‑tenant LLM platform.

---

## Further Resources

If you’re ready to go deeper, these resources are particularly useful:

- **Kubernetes + GPUs**
  - NVIDIA Kubernetes device plugin:  
    https://github.com/NVIDIA/k8s-device-plugin
  - NVIDIA GPU monitoring tools (DCGM, dcgm-exporter):  
    https://github.com/NVIDIA/gpu-monitoring-tools

- **LLM Serving**
  - vLLM documentation:  
    https://vllm.ai
  - Text Generation Inference (TGI):  
    https://github.com/huggingface/text-generation-inference
  - KServe documentation:  
    https://kserve.github.io/website/

- **MLOps on Kubernetes**
  - Kubeflow:  
    https://www.kubeflow.org/
  - Ray on Kubernetes:  
    https://docs.ray.io/en/latest/cluster/kubernetes/index.html

- **Observability and Autoscaling**
  - Prometheus + Kubernetes:  
    https://prometheus.io/docs/introduction/overview/
  - Kubernetes Horizontal Pod Autoscaler:  
    https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/

Using these building blocks, you can design and operate a robust LLM platform on Kubernetes tailored to your organization’s needs.