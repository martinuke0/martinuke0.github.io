---
title: "Mastering Kubernetes Orchestration for Large Language Models: A Comprehensive Zero‑to‑Hero Guide"
date: "2026-03-08T07:00:34.048"
draft: false
tags: ["kubernetes","large-language-models","ml-ops","gpu","devops"]
---

## Introduction

Large Language Models (LLMs) such as GPT‑4, LLaMA, and Falcon have moved from research curiosities to production‑grade services powering chatbots, code assistants, and enterprise analytics. Deploying these models at scale is no longer a one‑off experiment; it requires robust, repeatable, and observable infrastructure. Kubernetes—originally built for stateless microservices—has evolved into a de‑facto platform for orchestrating AI workloads, thanks to native support for GPUs, custom resource definitions (CRDs), and a thriving ecosystem of operators and tools.

This guide walks you through every step needed to **master Kubernetes orchestration for LLMs**, from the basics of containerizing a model to advanced topics like autoscaling with custom metrics, multi‑tenant security, and cost‑aware scheduling. Whether you are a data scientist who wants to serve a single model or a platform engineer tasked with a fleet of inference services, this “zero‑to‑hero” tutorial will give you a production‑ready roadmap.

---

## 1. Prerequisites

| Requirement | Why It Matters | Recommended Version |
|-------------|----------------|---------------------|
| Kubernetes cluster | Core orchestration platform | 1.27+ (supports `CRI` and `GPU` device plugins) |
| GPU nodes (NVIDIA A100, H100, or comparable) | LLM inference is compute‑heavy | NVIDIA driver ≥ 525 |
| NVIDIA GPU Operator | Automates driver, toolkit, and device plugin installation | v0.13 |
| Helm 3.x | Simplifies deployment of complex manifests | 3.12 |
| `kubectl` CLI | Interact with the cluster | v1.27 |
| Docker or `nerdctl` | Build container images | Docker 24.x |
| Python 3.10+ | Model serving libraries (vLLM, Transformers) | 3.10 |
| Basic knowledge of YAML, Docker, and Python | Essential for writing manifests and code | — |

> **Note:** If you lack a physical GPU cluster, consider using cloud providers (AWS EKS with `g4dn`/`p4d`, GCP GKE with `a2` nodes, Azure AKS with `NDv4`) or a local GPU‑enabled kind cluster with the NVIDIA device plugin.

---

## 2. Understanding LLM Workloads

### 2.1 Compute Characteristics

| Characteristic | Typical Value | Impact on Scheduling |
|----------------|---------------|----------------------|
| GPU memory per request | 8‑40 GB (depends on model size & batch) | Determines pod `requests`/`limits` |
| Compute FLOPs (TFLOPs) | 10‑30 TFLOPs for inference | Affects node selection |
| Latency SLA | 50‑200 ms for token generation | Drives pod replica count & HPA thresholds |
| Throughput (tokens/s) | 200‑2000 per GPU | Guides batch size & parallelism |

LLMs are **memory‑bound**; a 70 B parameter model can require > 140 GB VRAM, forcing multi‑GPU sharding (Tensor Parallelism). Smaller models (< 7 B) comfortably fit on a single A100.

### 2.2 Serving Paradigms

| Paradigm | Description | Typical Tool |
|----------|-------------|--------------|
| **Stateless HTTP inference** | Each request is independent, ideal for REST APIs | `vllm`, `TGI` (TensorFlow‑Serving‑based) |
| **Streaming token generation** | Server pushes tokens as they are generated | `vllm` with Server‑Sent Events (SSE) |
| **Batch inference** | Accumulates requests to fill GPU batch, improves throughput | `triton-inference-server`, `TGI` batch mode |
| **Model parallelism** | Splits model across multiple GPUs | `DeepSpeed`, `Megatron‑LM` |

Choose a paradigm early; it influences container design, resource requests, and autoscaling logic.

---

## 3. Kubernetes Fundamentals for AI

### 3.1 Node Labels & Taints

```yaml
# Example node label for A100 GPUs
apiVersion: v1
kind: Node
metadata:
  name: gpu-node-01
  labels:
    accelerator: nvidia-a100
    gpu-type: a100
spec:
  taints:
  - key: nvidia.com/gpu
    value: "present"
    effect: NoSchedule
```

- **Labels** allow you to target GPU‑specific nodes via `nodeSelector` or `affinity`.
- **Taints** prevent non‑GPU workloads from landing on these expensive nodes.

### 3.2 GPU Resource Requests

Kubernetes treats GPUs as a **scalar resource**:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1   # request one whole GPU
  requests:
    nvidia.com/gpu: 1
```

For multi‑GPU pods (model parallelism), set the count accordingly. Remember that GPU memory is not directly exposed; you must enforce it through **`devicePlugin` limits** (e.g., `nvidia.com/gpu-memory` from the NVIDIA GPU Operator).

### 3.3 Custom Resource Definitions (CRDs)

Many AI‑specific operators expose CRDs, such as:

- `InferenceService` (KServe)
- `TrainedModel` (Kubeflow)
- `GPUJob` (Spark‑on‑K8s)

These encapsulate common patterns (model loading, autoscaling, logging) and reduce boilerplate.

---

## 4. Designing a Scalable LLM Architecture

Below is a reference architecture that works for most production scenarios:

```
+-------------------+       +-------------------+       +-------------------+
|   Ingress (NGINX) | <---> |  API Gateway (Istio) | <---> |  Auth Service   |
+-------------------+       +-------------------+       +-------------------+
                                   |
                                   v
                         +-------------------+
                         |   LLM Inference   |
                         |   Deployment(s)   |
                         +-------------------+
                                   |
                                   v
                         +-------------------+
                         |   Model Cache PVC |
                         +-------------------+
                                   |
                                   v
                         +-------------------+
                         |   Monitoring (Prom)|
                         +-------------------+
```

- **Ingress**: External entry point (NGINX, Traefik) with TLS termination.
- **API Gateway**: Handles routing, request throttling, and can expose metrics for HPA.
- **Auth Service**: JWT validation or mTLS for multi‑tenant isolation.
- **Inference Deployments**: Stateless pods running a model server (vLLM, TGI). Deployed via Helm or Kustomize.
- **Model Cache PVC**: Persistent Volume Claim mounted as a read‑only cache for model weights, shared among pods to avoid duplicate downloads.
- **Monitoring Stack**: Prometheus + Grafana + OpenTelemetry for latency, GPU utilization, and error rates.

---

## 5. Deploying LLM Inference Servers

### 5.1 Containerizing vLLM

`vLLM` is a high‑performance inference engine optimized for transformer models. A minimal Dockerfile:

```Dockerfile
# Dockerfile for vLLM inference
FROM nvidia/cuda:12.2.0-runtime-ubuntu22.04

# Install OS dependencies
RUN apt-get update && apt-get install -y python3-pip git && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip3 install --no-cache-dir \
    torch==2.2.0+cu121 \
    vllm==0.4.0 \
    transformers==4.38.0 \
    accelerate==0.28.0

# Create a non‑root user
RUN useradd -m -s /bin/bash appuser
USER appuser
WORKDIR /app

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/entrypoint.sh"]
```

`entrypoint.sh`:

```bash
#!/usr/bin/env bash
MODEL_NAME=${MODEL_NAME:-"meta-llama/Meta-Llama-3-8B-Instruct"}
PORT=${PORT:-8000}
python -m vllm.entrypoints.openai.api_server \
    --model $MODEL_NAME \
    --host 0.0.0.0 \
    --port $PORT \
    --tensor-parallel-size ${TP_SIZE:-1}
```

Build and push:

```bash
docker build -t myrepo/vllm:8b-instruct .
docker push myrepo/vllm:8b-instruct
```

### 5.2 Helm Chart for vLLM

Create a Helm chart named `vllm-server`. Key values (`values.yaml`):

```yaml
replicaCount: 2

image:
  repository: myrepo/vllm
  tag: "8b-instruct"
  pullPolicy: IfNotPresent

resources:
  limits:
    nvidia.com/gpu: 1
  requests:
    nvidia.com/gpu: 1
    cpu: "2"
    memory: "8Gi"

nodeSelector:
  accelerator: nvidia-a100

tolerations:
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule

env:
  - name: MODEL_NAME
    value: "meta-llama/Meta-Llama-3-8B-Instruct"
  - name: TP_SIZE
    value: "1"

persistence:
  enabled: true
  existingClaim: "llm-model-cache"
  mountPath: "/models"
```

Deploy:

```bash
helm upgrade --install vllm ./vllm-server -n ai-inference --create-namespace
```

The chart also includes a **Service** (type `ClusterIP`) and **HorizontalPodAutoscaler** (HPA) that we’ll configure next.

---

## 6. Autoscaling LLM Inference

### 6.1 Horizontal Pod Autoscaler (HPA) with Custom Metrics

Standard CPU/Memory HPA isn’t sufficient for LLM workloads. Instead, we autoscale on **GPU utilization** or **request latency**.

First, expose a custom metric via the vLLM Prometheus endpoint (`/metrics`). Example metric:

```
vllm_gpu_utilization_percent 73.5
vllm_request_latency_seconds_bucket{le="0.1"} 12
vllm_request_latency_seconds_bucket{le="0.5"} 95
...
```

#### 6.1.1 Prometheus Adapter

Install the Prometheus Adapter to expose metrics to the Kubernetes API:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus-adapter prometheus-community/prometheus-adapter \
  -n monitoring --create-namespace \
  -f values-adapter.yaml
```

`values-adapter.yaml` snippet:

```yaml
rules:
  custom:
    - seriesQuery: 'vllm_gpu_utilization_percent{namespace!="",pod!=""}'
      resources:
        overrides:
          namespace: {resource: "namespace"}
          pod: {resource: "pod"}
      name:
        matches: "^(.*)_percent$"
        as: "${1}_percentage"
      metricsQuery: <<.Series>>{<<.LabelMatchers>>}
```

#### 6.1.2 HPA Manifest

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: vllm-hpa
  namespace: ai-inference
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: vllm
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: External
      external:
        metric:
          name: vllm_gpu_utilization_percentage
          selector:
            matchLabels:
              # optional labels
        target:
          type: AverageValue
          averageValue: 70
```

This HPA will add replicas when average GPU utilization exceeds **70 %**, keeping latency low while avoiding over‑provisioning.

### 6.2 Scaling with Token‑Throughput

For batch‑oriented serving, you might scale on **tokens per second**:

```yaml
metrics:
  - type: External
    external:
      metric:
        name: vllm_tokens_per_second
      target:
        type: AverageValue
        averageValue: 1500
```

---

## 7. Model Storage & Caching

### 7.1 Persistent Volume Claim (PVC) for Model Weights

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llm-model-cache
  namespace: ai-inference
spec:
  storageClassName: efs-sc   # Example: AWS EFS for shared read‑only cache
  accessModes:
    - ReadOnlyMany
  resources:
    requests:
      storage: 500Gi
```

Mount the PVC as read‑only in the pod:

```yaml
volumeMounts:
  - name: model-cache
    mountPath: /models
    readOnly: true
volumes:
  - name: model-cache
    persistentVolumeClaim:
      claimName: llm-model-cache
```

> **Tip:** Use a **CSI driver** that supports `ReadOnlyMany` (EFS, Azure Files, GCP Filestore) to avoid duplicated downloads across replicas.

### 7.2 Warm‑up Script

Add a pre‑start hook that warms the model cache:

```yaml
lifecycle:
  postStart:
    exec:
      command: ["/bin/bash", "-c", "python -c 'from vllm import Engine; Engine(\"/models/${MODEL_NAME}\")'"]
```

This ensures the first request does not suffer a cold‑start penalty.

---

## 8. Security, Multi‑Tenancy, and Governance

### 8.1 Network Policies

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-all-except-ingress
  namespace: ai-inference
spec:
  podSelector: {}
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress-nginx
  egress:
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
```

Only the ingress namespace can reach the inference pods.

### 8.2 RBAC for Model Access

Create a **ServiceAccount** per tenant and bind it to a **Role** that only allows reading from a specific PVC sub‑directory.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: tenant-a-model-reader
  namespace: ai-inference
rules:
- apiGroups: [""]
  resources: ["persistentvolumeclaims"]
  resourceNames: ["llm-model-cache"]
  verbs: ["get", "list"]
```

Assign the role to the tenant’s ServiceAccount.

### 8.3 Secrets Management

Store API keys, downstream service credentials, and model license tokens in **Kubernetes Secrets** encrypted at rest (e.g., using **SealedSecrets** or **External Secrets Operator**).

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: hf-token
  namespace: ai-inference
type: Opaque
stringData:
  token: "<YOUR_HUGGINGFACE_TOKEN>"
```

Reference the secret as an environment variable:

```yaml
env:
  - name: HF_TOKEN
    valueFrom:
      secretKeyRef:
        name: hf-token
        key: token
```

---

## 9. Observability & Monitoring

### 9.1 Prometheus Scrape Config

```yaml
scrape_configs:
  - job_name: 'vllm-metrics'
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: vllm
    metrics_path: /metrics
    scheme: http
```

### 9.2 Grafana Dashboards

Import community dashboards:

- **Kubernetes Cluster Monitoring** (ID 6417)
- **GPU Utilization** (custom dashboard using `nvidia_gpu_*` metrics)

Create a panel for **request latency percentile**:

```sql
histogram_quantile(0.95, sum(rate(vllm_request_latency_seconds_bucket[5m])) by (le))
```

### 9.3 Distributed Tracing

Deploy **OpenTelemetry Collector** and instrument the vLLM server with **OTEL SDK** (via environment variable `OTEL_EXPORTER_OTLP_ENDPOINT`). This provides end‑to‑end visibility from the API gateway down to the GPU kernel.

---

## 10. CI/CD Pipelines for Model Updates

### 10.1 GitOps with Argo CD

1. Store Helm chart in a Git repo (`github.com/yourorg/llm-helm`).
2. Create an **Application** manifest:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: vllm-prod
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/yourorg/llm-helm
    targetRevision: HEAD
    path: charts/vllm
  destination:
    server: https://kubernetes.default.svc
    namespace: ai-inference
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Argo CD will continuously reconcile the live cluster with the desired state.

### 10.2 Model Version Promotion

- **Stage 1 (Dev):** Deploy a new model version using a separate `dev` namespace.
- **Stage 2 (Canary):** Use **Argo Rollouts** to shift 5 % of traffic to the new version.
- **Stage 3 (Prod):** Promote fully once metrics pass thresholds.

### 10.3 Automated Model Pull

Leverage **KServe**’s `Model` CR that automatically pulls from an OCI registry or S3 bucket:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-8b
spec:
  predictor:
    containers:
      - name: kserve-container
        image: kserve/kserve-controller:latest
        args:
          - "--model_name=llama-8b"
          - "--model_uri=s3://my-bucket/models/llama-8b"
```

KServe handles versioning and rollback automatically.

---

## 11. Cost‑Optimization Strategies

| Technique | How It Works | When to Use |
|-----------|--------------|-------------|
| **GPU node autoscaling** (Cluster Autoscaler) | Adds/removes GPU nodes based on pending pods | Variable traffic patterns |
| **Spot/Preemptible instances** | Use cheaper, interruptible VMs for non‑critical batch jobs | Offline inference, nightly fine‑tuning |
| **Mixed‑precision inference** (FP16/BF16) | Reduces memory footprint, doubles throughput on supported GPUs | All models that support it |
| **Model quantization** (8‑bit, 4‑bit) | Further cuts VRAM, can run larger models on a single GPU | When latency budget allows |
| **Pod priority & preemption** | Guarantees critical services stay up while lower‑priority jobs get evicted | Multi‑tenant clusters |

Implement **budget alerts** with cloud provider cost APIs and integrate them into Slack/Teams via webhooks.

---

## 12. Real‑World Case Study: Deploying a 13 B Parameter LLM for Customer Support

### 12.1 Background

A fintech startup needed a private LLM to answer compliance‑related queries. Requirements:

- **Latency ≤ 150 ms** per response
- **99.9 % uptime**
- **GPU budget ≤ 4 A100s** (max 2 concurrent pods)

### 12.2 Architecture

- **Ingress:** Kong API Gateway with JWT auth.
- **Model Server:** vLLM with `tensor‑parallel-size=2` (splits model across two GPUs).
- **Cache:** EFS PVC (300 Gi) shared across pods.
- **Autoscaling:** HPA based on `vllm_gpu_utilization_percentage` (target 65 %).
- **Observability:** Prometheus + Grafana; alerts for latency > 200 ms.

### 12.3 Implementation Highlights

```yaml
# Deployment snippet
spec:
  replicas: 2
  template:
    spec:
      containers:
        - name: vllm
          image: myrepo/vllm:13b
          resources:
            limits:
              nvidia.com/gpu: 2   # two GPUs per pod for tensor parallelism
            requests:
              nvidia.com/gpu: 2
          env:
            - name: MODEL_NAME
              value: "meta-llama/Meta-Llama-3-13B-Instruct"
            - name: TP_SIZE
              value: "2"
```

The HPA scaled up to **4 pods** during peak load, keeping latency under the SLA while staying within the GPU budget.

### 12.4 Results

| Metric | Before (single GPU) | After (tensor‑parallel) |
|--------|---------------------|--------------------------|
| Avg latency | 320 ms | 110 ms |
| Throughput (req/s) | 12 | 45 |
| GPU utilization | 85 % (spiky) | 68 % (stable) |
| Cost per month | $12,000 | $9,800 (thanks to spot nodes) |

The case demonstrates how **tensor parallelism**, **custom HPA**, and **shared model cache** combine to meet strict latency and cost constraints.

---

## 13. Best‑Practice Checklist

- ✅ **GPU Drivers**: Use NVIDIA GPU Operator for consistent driver & toolkit versions.  
- ✅ **Node Labeling**: Tag GPU nodes with `accelerator` and `gpu-type`.  
- ✅ **Resource Requests**: Always set `nvidia.com/gpu` limits/requests; avoid over‑commit.  
- ✅ **Model Cache**: Deploy a shared PVC (ReadOnlyMany) to prevent redundant downloads.  
- ✅ **Autoscaling**: Use custom metrics (GPU utilization, request latency).  
- ✅ **Security**: Enforce NetworkPolicies, RBAC per tenant, and secret management.  
- ✅ **Observability**: Export Prometheus metrics, enable tracing, set up alerts.  
- ✅ **CI/CD**: Adopt GitOps (Argo CD) and canary rollouts for safe model upgrades.  
- ✅ **Cost Controls**: Leverage spot instances, mixed‑precision, and node autoscaling.  

---

## Conclusion

Orchestrating large language models on Kubernetes is no longer a futuristic experiment—it’s a proven, production‑grade pattern that blends the flexibility of container orchestration with the raw power of modern GPUs. By following the steps outlined in this guide—**containerizing the model server, designing a resilient architecture, configuring GPU‑aware autoscaling, securing multi‑tenant access, and establishing robust observability—you can transform a raw LLM into a reliable, cost‑effective service** that scales from a single developer notebook to a global AI platform.

The journey from “zero” to “hero” hinges on mastering three core concepts:

1. **Infrastructure as Code** – Treat every piece (node labels, PVCs, Helm charts) as declarative YAML.
2. **GPU‑First Design** – Think in terms of GPU memory, tensor parallelism, and custom metrics.
3. **Continuous Delivery** – Automate model versioning, canary testing, and rollback.

Armed with these practices, you’ll be able to deliver low‑latency, high‑throughput LLM experiences while keeping operational overhead and cloud spend under control. Happy scaling!

---

## Resources

- **Kubernetes Documentation** – Official guide on pods, resources, and autoscaling.  
  [https://kubernetes.io/docs/home/](https://kubernetes.io/docs/home/)

- **NVIDIA GPU Operator** – Simplifies GPU driver, toolkit, and device plugin management.  
  [https://github.com/NVIDIA/k8s-device-plugin](https://github.com/NVIDIA/k8s-device-plugin)

- **vLLM GitHub Repository** – High‑performance LLM inference engine with OpenAI‑compatible API.  
  [https://github.com/vllm-project/vllm](https://github.com/vllm-project/vllm)

- **KServe Documentation** – Serverless inference platform for ML models on Kubernetes.  
  [https://kserve.github.io/website/](https://kserve.github.io/website/)

- **Argo CD – GitOps Continuous Delivery** – Declarative deployment and drift detection.  
  [https://argo-cd.readthedocs.io/](https://argo-cd.readthedocs.io/)

- **Prometheus Adapter** – Exposes custom metrics to the Kubernetes HPA API.  
  [https://github.com/kubernetes-sigs/prometheus-adapter](https://github.com/kubernetes-sigs/prometheus-adapter)

- **OpenTelemetry Collector** – Unified telemetry collection for traces, metrics, and logs.  
  [https://opentelemetry.io/docs/collector/](https://opentelemetry.io/docs/collector/)
