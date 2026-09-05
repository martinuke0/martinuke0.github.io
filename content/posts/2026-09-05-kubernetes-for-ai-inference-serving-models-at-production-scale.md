---
title: "Kubernetes for AI Inference: Serving Models at Production Scale"
date: "2026-09-05T18:48:53.043"
draft: false
tags: ["kubernetes", "ai-inference", "mlops", "gpu", "kserve"]
description: "How Kubernetes became the default runtime for serving LLMs and vision models, and the patterns teams use to hit latency, throughput, and cost targets."
summary: "Kubernetes has quietly become the de facto control plane for production AI inference. This post walks through the architecture, the GPU plumbing, and the patterns teams use to serve models that actually meet SLOs."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-kubernetes-for-ai-inference-serving-models-at-production-scale.svg"
  alt: "Diagram of a Kubernetes cluster routing inference requests across GPU nodes to multiple model replicas."
  caption: ""
  relative: false
---

> **TL;DR** — Kubernetes won the AI inference runtime race not because it was designed for it, but because it already solved the hard problems: bin-packing expensive GPUs, rolling out new weights safely, scaling on demand, and giving platform teams one control plane to operate. The interesting work is in the details — request routing, KV-cache aware scheduling, and the gap between "the pod is running" and "the model is serving within SLO."

## Why Kubernetes, Specifically?

Five years ago, most teams I worked with served ML models from a hand-built fleet of EC2 instances behind a load balancer. A startup would launch with a single `gunicorn` process on a p3.2xlarge, add autoscaling by hand, and pray. The first time they needed to serve three models with different GPU footprints, they wrote a Slack bot to manage capacity.

Kubernetes didn't replace that world by being a better model server. It replaced it by being a better *operating system*. The same control plane that already runs your batch jobs, your API, and your CI workers can also run your model servers — with the same rolling updates, the same HPA, the same RBAC, and the same dashboards. That's a much bigger deal than any single inference optimization.

Three concrete forces pushed inference workloads onto Kubernetes:

1. **GPU supply is constrained and expensive.** When an H100 costs ~$3/hour on-demand and ~$2/hour reserved, you can't afford to leave one idle. Kubernetes schedulers can bin-pack inference workloads alongside training and feature stores on the same hardware ([NVIDIA's GPU Operator](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html) is the de facto standard for exposing these resources).
2. **Traffic is bursty and asymmetric.** A chatbot might idle for hours and then spike to 10k req/s during a product launch. The [Horizontal Pod Autoscaler](https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/) on custom Prometheus metrics (queue depth, KV-cache utilization, p99 latency) is what makes this survivable.
3. **Platform teams want one control plane.** You don't want a separate Nomad cluster, a separate autoscaler, and a separate secrets manager for "the ML stuff." As argued in the [CNCF AI/ML whitepaper](https://www.cncf.io/reports/), consolidation wins organizational fights.

The result is that every major model serving framework — vLLM, Triton Inference Server, TensorRT-LLM, vLLM, KServe, Ray Serve — now ships with a Kubernetes-native deployment story.

## The Reference Architecture

A production-grade Kubernetes inference stack has roughly six layers. Each one has multiple mature implementations, which is part of the fun.

```text
┌─────────────────────────────────────────────────────────────┐
│  Clients (web, mobile, batch jobs, agents)                  │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Ingress / Gateway  (Envoy Gateway, Istio, Kong, NGINX)     │
│  - TLS termination, rate limiting, authn                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Routing Layer  (Knative, KServe, custom Gateway API HTTPRoute)│
│  - Traffic split, A/B, canary, model selection by header    │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Model Servers (vLLM, Triton, TensorRT-LLM, SGLang)         │
│  - Batching, KV-cache, speculative decoding, paged attention │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  GPU Node Pool  (H100/A100/L40S, MIG slices, time-slicing)  │
│  - NVIDIA device plugin, GPU Operator, DCGM exporter         │
└─────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Storage & Artifacts  (S3/GCS + InitContainer pull, OCI     │
│  model artifacts, model registry like MLflow or Harbor)     │
└─────────────────────────────────────────────────────────────┘
```

The interesting design decisions are in layers 3 and 4. Everything else is mostly solved.

## Patterns in Production

### Pattern 1: The InitContainer Weight Pull

The single most common anti-pattern I see is mounting model weights from a network filesystem and serving them directly. It works until it doesn't — NFS hiccups cause cold-start latency spikes that blow your p99.

The fix is boring: pull weights into a local `emptyDir` (or a [PersistentVolume with a CSI driver](https://kubernetes-csi.github.io/docs/)) during pod startup, and only flip the pod into the Service once the readiness probe passes.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: llama-3-70b-instruct
spec:
  replicas: 3
  template:
    spec:
      containers:
        - name: vllm
          image: vllm/vllm-openai:v0.6.3
          args:
            - "--model=/models/llama-3-70b"
            - "--tensor-parallel-size=4"
            - "--max-model-len=8192"
          ports:
            - containerPort: 8000
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 120
            periodSeconds: 10
          resources:
            requests:
              nvidia.com/gpu: 4
            limits:
              nvidia.com/gpu: 4
      initContainers:
        - name: fetch-weights
          image: amazon/aws-cli:2.17.0
          command: ["/bin/sh", "-c"]
          args:
            - |
              aws s3 sync s3://my-model-bucket/llama-3-70b /models/llama-3-70b \
                --exclude "*" --include "*.safetensors" --include "config.json"
          volumeMounts:
            - name: model-storage
              mountPath: /models
      volumes:
        - name: model-storage
          emptyDir:
            sizeLimit: 200Gi
```

Two things to notice: the readiness probe's `initialDelaySeconds` of 120 is intentional — large models need time to load into GPU memory and warm up the KV cache before they can serve real traffic. And the `emptyDir.sizeLimit` prevents a runaway pod from filling the node's disk.

### Pattern 2: Request-Routed Multi-Model Serving

Most teams don't serve a single model. They serve a base model, a fine-tune, a guardrail classifier, a reranker, and a routing model that decides which to call. This is where [KServe](https://kserve.github.io/website/) shines.

The pattern that works at scale is **header-based routing** at the gateway, with the model server handling multiple loaded models. A request comes in with a header like `x-model: llama-3-70b`, the Gateway API HTTPRoute matches it, and forwards to the right InferenceService.

```text
Client ──▶ Envoy Gateway
              │
              ├── header x-model: llama-3-70b  ──▶ inference-llama (4× H100)
              ├── header x-model: claude-haiku ──▶ inference-claude (1× A100, external)
              └── header x-model: rerank      ──▶ inference-rerank (CPU node)
```

KServe's `Predictor` CRD wraps this cleanly:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: multi-model-router
spec:
  predictor:
    containers:
      - name: triton
        image: nvcr.io/nvidia/tritonserver:24.08-py3
        args:
          - "tritonserver"
          - "--model-repository=/models"
          - "--http-port=8080"
        resources:
          limits:
            nvidia.com/gpu: 2
```

Triton's [ensemble mode](https://github.com/triton-inference-server/server/blob/main/docs/user_guide/architecture.md#ensemble-models) lets you chain a router → classifier → LLM inside a single request, which is how a lot of production "agent" systems are actually built under the hood.

### Pattern 3: GPU Sharing with MIG and Time-Slicing

A single H100 has 80GB of VRAM and roughly 3,000 TFLOPS. Few inference workloads need all of it. NVIDIA's [Multi-Instance GPU (MIG)](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/gpu-operator-mig.html) technology partitions one GPU into up to 7 isolated instances, each with its own memory and compute slice. Kubernetes sees them as separate `nvidia.com/gpu` resources.

The simpler alternative is [time-slicing](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/gpu-time-slicing.html), which lets multiple pods share a GPU but doesn't isolate memory. It's fine for small models or dev environments; it's a footgun in production where one chatty pod can starve three quiet ones.

The rule of thumb I give teams:

- **MIG**: Use when SLAs are tight and workloads are predictable. Costs you ~10–15% of raw throughput vs. passthrough, but gives you real isolation.
- **Time-slicing**: Use for dev/staging and small (≤7B) parameter models in prod.
- **Passthrough (one pod, one GPU)**: Use for the flagship 70B+ model where every FLOP counts.

## Autoscaling That Actually Works

The HPA defaults don't understand inference. A naive `cpu > 70%` autoscale will spin up a new pod, then wait 90 seconds for it to load weights, while your p99 latency quadruples. You need three signals working together.

### Signal 1: Queue Depth

vLLM exposes `vllm:num_requests_waiting` as a Prometheus metric. Scale on `avg(queue_depth) > 4 per replica`. This is the most honest signal of whether users are piling up.

### Signal 2: KV-Cache Utilization

This is the one nobody talks about but everyone needs. As the [vLLM team documents](https://blog.vllm.ai/2023/06/20/vllm.html), the KV cache is what limits concurrent requests. When it fills, new requests are rejected. Scaling on `kv_cache_usage_perc > 0.8` catches backpressure that CPU-based metrics miss.

### Signal 3: p99 Latency

The classic SLO signal. The [KEDA](https://keda.sh/) scaler makes it trivial to scale on Prometheus queries:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: llm-scaler
spec:
  scaleTargetRef:
    name: llama-3-70b-instruct
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus.monitoring:9090
        threshold: "0.8"
        query: |
          histogram_quantile(0.99,
            sum(rate(vllm:request_latency_seconds_bucket{app="llama-3-70b"}[1m]))
            by (le)
          )
```

The trick is to combine all three. KEDA's `formula` trigger lets you do `max(queue_depth_signal, kv_cache_signal, latency_signal)` so any one of them crossing threshold triggers a scale-out.

### Cold Starts Are the Killer

The hardest part of serving large models on Kubernetes is that the HPA doesn't actually solve cold starts. A new replica needs to:

1. Pull the image (30–60s)
2. Pull weights from S3 (30–120s for a 70B model on a fast link)
3. Load weights into GPU memory (20–90s)
4. Warm the KV cache (5–10s)

That's 2–5 minutes from "HPA says scale" to "actually serving." Two mitigations that work:

- **Over-provision with minReplicas.** Set `minReplicas` to ~30% of peak. Yes, it costs money. No, it's not as expensive as the SLA penalty.
- **Keep one warm standby per AZ.** Use [Karpenter](https://karpenter.sh/) or [Cluster Autoscaler](https://github.com/kubernetes/autoscaler) with pre-pulled images and `priorityClassName: inference-warm` so standby pods schedule faster.

## The Inference-Specific Plumbing

A few Kubernetes features that most teams don't know about until they need them.

### Topology Spread Constraints

For multi-GPU inference (tensor parallelism), you want all GPUs on the same NVLink domain — typically the same physical socket. A naive scheduler will happily split your 4× H100 pod across two machines with a 100µs link between them, killing your throughput.

```yaml
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: DoNotSchedule
    labelSelector:
      matchLabels:
        app: llama-3-70b-instruct
```

### PodDisruptionBudgets

Inference workloads are stateful in a meaningful sense — each pod has a loaded model in GPU memory. A node drain that kills two pods simultaneously means losing 50% of your capacity while the other replicas reload.

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: llama-3-70b-pdb
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: llama-3-70b-instruct
```

### Graceful Shutdown PreStop Hooks

When a pod is being terminated (scaling down, node drain, rolling deploy), you want it to:

1. Stop accepting new requests
2. Drain in-flight requests (usually 30–60s for chat completions)
3. Only then let the kernel send SIGTERM

```yaml
lifecycle:
  preStop:
    exec:
      command: ["/bin/sh", "-c", "sleep 30"]
terminationGracePeriodSeconds: 90
```

The `preStop` sleep is a load-balancer hack: most LBs need a few seconds to notice the pod is going away, and you don't want them sending new traffic to a pod that's about to die.

## What People Get Wrong

A few mistakes I see repeatedly across teams I work with.

**Treating inference like a stateless web service.** It's not. The model in GPU memory is state. A rolling deploy with `maxSurge: 25%, maxUnavailable: 25%` can OOM your nodes if the new image is larger or if the old pods haven't finished draining.

**Ignoring the GPU network.** For multi-node inference (tensor parallelism across pods), you need 100+ Gbps inter-node bandwidth. Standard cluster networking won't cut it. [InfiniBand](https://www.nvidia.com/en-us/networking/infiniband/) or RoCE on a dedicated VLAN is non-negotiable for 70B+ models.

**Confusing throughput with goodput.** A vLLM pod that processes 500 tok/s but rejects 30% of requests under load is not a 500 tok/s system. Measure [effective throughput](https://www.anyscale.com/blog/llm-inference-guidebook) — tokens served successfully within SLO.

**Forgetting about prefill vs. decode.** Modern LLM inference has two phases with very different profiles: prefill (compute-bound, processes the prompt) and decode (memory-bound, generates tokens). Production servers need to handle them differently. Triton and vLLM both have chunked prefill and disaggregated serving modes for exactly this reason.

## Key Takeaways

- **Kubernetes won the inference runtime space by being a good OS, not a good model server.** The value is in the control plane, the autoscaler, and the GPU operator — not in the inference container.
- **Cold start is the operational reality.** Plan warm capacity, use init containers to pull weights, and set realistic readiness probe delays.
- **Scale on inference-native metrics** (queue depth, KV-cache utilization, p99 latency) — never on raw CPU.
- **GPU sharing has tradeoffs.** MIG for production isolation, time-slicing for dev, passthrough for flagship models.
- **The networking and topology matter as much as the model server.** NVLink domains, InfiniBand for multi-node, topology spread constraints, and graceful shutdown hooks separate "it works in staging" from "it works at 3am under load."

## Further Reading

- [KServe — Kubernetes-native model serving](https://kserve.github.io/website/)
- [vLLM: PagedAttention for LLM serving](https://blog.vllm.ai/2023/06/20/vllm.html)
- [NVIDIA GPU Operator for Kubernetes](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/overview.html)
- [Triton Inference Server architecture](https://github.com/triton-inference-server/server/blob/main/docs/user_guide/architecture.md)
- [KEDA — Kubernetes-based event-driven autoscaling](https://keda.sh/)
- [CNCF AI/ML Working Group resources](https://www.cncf.io/reports/)