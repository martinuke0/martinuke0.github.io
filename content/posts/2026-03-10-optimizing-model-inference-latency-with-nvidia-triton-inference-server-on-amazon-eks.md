---
title: "Optimizing Model Inference Latency with NVIDIA Triton Inference Server on Amazon EKS"
date: "2026-03-10T16:01:18.364"
draft: false
tags: ["NVIDIA Triton","Amazon EKS","Model Inference","Latency Optimization","MLOps"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Latency Matters in Production ML](#why-latency-matters-in-production-ml)  
3. [NVIDIA Triton Inference Server: A Quick Overview](#nvidia-triton-inference-server-a-quick-overview)  
4. [Why Run Triton on Amazon EKS?](#why-run-triton-on-amazon-eks)  
5. [Preparing the AWS Environment](#preparing-the-aws-environment)  
   - 5.1 [Creating an EKS Cluster with `eksctl`](#creating-an-eks-cluster-with-eksctl)  
   - 5.2 [Setting Up IAM Roles & Service Accounts](#setting-up-iam-roles--service-accounts)  
6. [Deploying Triton on EKS](#deploying-triton-on-eks)  
   - 6.1 [Helm Chart Basics](#helm-chart-basics)  
   - 6.2 [Customizing `values.yaml`](#customizing-valuesyaml)  
   - 6.3 [Launching the Deployment](#launching-the-deployment)  
7. [Model Repository Layout & Versioning](#model-repository-layout--versioning)  
8. [Latency‑Optimization Techniques](#latency‑optimization-techniques)  
   - 8.1 [Dynamic Batching](#dynamic-batching)  
   - 8.2 [GPU Allocation & Multi‑Model Sharing](#gpu-allocation--multi‑model-sharing)  
   - 8.3 [Model Warm‑up & Cache Management](#model-warm‑up--cache-management)  
   - 8.4 [Request/Response Serialization Choices](#requestresponse-serialization-choices)  
   - 8.5 [Network‑Level Tweaks (Service Mesh & Ingress)](#network‑level-tweaks-service-mesh--ingress)  
9. [Monitoring, Profiling, and Observability](#monitoring-profiling-and-observability)  
   - 9.1 [Prometheus & Grafana Integration](#prometheus--grafana-integration)  
   - 9.2 [Triton’s Built‑in Metrics](#tritons-built‑in-metrics)  
   - 9.3 [Tracing with OpenTelemetry](#tracing-with-opentelemetry)  
10. [Autoscaling for Consistent Latency](#autoscaling-for-consistent-latency)  
    - 10.1 [Horizontal Pod Autoscaler (HPA)](#horizontal-pod-autoscaler-hpa)  
    - 10.2 [KEDA‑Based Event‑Driven Scaling](#keda‑based-event‑driven-scaling)  
11. [Real‑World Case Study: 30 % Latency Reduction](#real‑world-case-study-30‑latency-reduction)  
12. [Best‑Practice Checklist](#best‑practice-checklist)  
13. [Conclusion](#conclusion)  
14. [Resources](#resources)  

---

## Introduction

Model inference latency is often the decisive factor between a delightful user experience and a frustrated one. As machine‑learning workloads transition from experimental notebooks to production‑grade services, the need for a robust, low‑latency serving stack becomes paramount. NVIDIA’s **Triton Inference Server** (formerly TensorRT Inference Server) is purpose‑built for high‑throughput, low‑latency serving of deep‑learning models on CPUs and GPUs. When combined with **Amazon Elastic Kubernetes Service (EKS)**—a fully managed Kubernetes offering—organizations gain a scalable, secure, and cloud‑native platform for serving models at scale.

This article walks you through a complete, production‑ready workflow for **optimizing inference latency** with Triton on EKS. We’ll cover everything from cluster provisioning to fine‑grained performance tuning, with concrete code snippets, Helm configurations, and real‑world insights. By the end, you’ll have a repeatable blueprint that can be adapted to any deep‑learning model, whether you’re serving vision, speech, or recommendation workloads.

---

## Why Latency Matters in Production ML

| Use‑Case | Latency Target | Business Impact |
|----------|----------------|-----------------|
| Real‑time video analytics | < 30 ms per frame | Enables live alerts, reduces false positives |
| Conversational AI (chatbots) | < 100 ms per turn | Keeps conversation flow natural |
| Fraud detection | < 200 ms per transaction | Allows immediate blocking of suspicious activity |
| Recommendation engines | 20‑50 ms per request | Improves click‑through rates and revenue |

Even when throughput is high, a single outlier request that spikes latency can degrade SLA compliance and erode user trust. Therefore, **latency optimization is not a nicety; it’s a requirement** for many production ML services.

---

## NVIDIA Triton Inference Server: A Quick Overview

Triton abstracts the complexities of serving models across multiple frameworks (TensorFlow, PyTorch, ONNX, TensorRT, etc.) and hardware accelerators. Key capabilities include:

- **Model versioning** – serve multiple versions side‑by‑side.
- **Dynamic batching** – automatically combine incoming requests into a single GPU kernel launch.
- **Concurrent model execution** – run several models on one GPU.
- **HTTP/REST, gRPC, and NVIDIA’s proprietary protocol** – flexible client integration.
- **Built‑in metrics** – Prometheus‑compatible statistics for latency, throughput, GPU utilization, etc.
- **Model warm‑up** – pre‑run inference to cache kernels and memory.

All of these features can be leveraged from within a Kubernetes cluster using a **Docker image** (`nvcr.io/nvidia/tritonserver:<tag>`) and a **Helm chart** that handles pod spec, service, config maps, and RBAC.

---

## Why Run Triton on Amazon EKS?

| Feature | EKS Advantage |
|---------|----------------|
| **Managed control plane** | No need to patch the Kubernetes master; AWS handles upgrades, HA, and security patches. |
| **Integration with IAM** | Fine‑grained pod‑level permissions via IAM Roles for Service Accounts (IRSA). |
| **Native support for GPU node groups** | Use `eksctl` or the console to provision EC2 instances with NVIDIA GPUs (e.g., p3, g4dn, g5). |
| **Built‑in observability stack** | Amazon CloudWatch Container Insights, Prometheus Operator, and Managed Grafana can be attached with minimal effort. |
| **Scalable networking** | AWS Load Balancer Controller, Service Mesh (App Mesh or Istio), and VPC CNI provide low‑latency intra‑cluster traffic. |

Running Triton on EKS means you can **scale horizontally** (more pods) and **vertically** (larger GPU instances) while keeping operational overhead low.

---

## Preparing the AWS Environment

### 5.1 Creating an EKS Cluster with `eksctl`

First, install `eksctl` (>= 0.149.0) and `awscli`. Then, create a cluster with a dedicated GPU node group:

```bash
# Define variables for reuse
CLUSTER_NAME=triton-eks
REGION=us-west-2
GPU_INSTANCE_TYPE=g5.xlarge   # 4 vCPU, 16 GiB, 1 NVIDIA A10G GPU
CPU_INSTANCE_TYPE=m5.large    # For control plane and sidecars

# Create the cluster
eksctl create cluster \
  --name $CLUSTER_NAME \
  --region $REGION \
  --version 1.28 \
  --with-oidc \
  --ssh-access \
  --ssh-public-key ~/.ssh/id_rsa.pub \
  --managed

# Add GPU node group
eksctl create nodegroup \
  --cluster $CLUSTER_NAME \
  --region $REGION \
  --name gpu-ng \
  --node-type $GPU_INSTANCE_TYPE \
  --nodes 3 \
  --nodes-min 1 \
  --nodes-max 6 \
  --ssh-access \
  --ssh-public-key ~/.ssh/id_rsa.pub \
  --managed \
  --instance-selector 'gpu=true' \
  --labels role=triton-gpu
```

> **Note:** The `--instance-selector 'gpu=true'` flag ensures only GPU‑enabled instance types are considered. Adjust `nodes-max` based on your expected peak traffic.

### 5.2 Setting Up IAM Roles & Service Accounts

Triton pods need permission to read model artifacts from an S3 bucket. Create an IAM policy and attach it to a service account:

```json
# triton-s3-policy.json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::my-triton-models",
        "arn:aws:s3:::my-triton-models/*"
      ]
    }
  ]
}
```

```bash
aws iam create-policy \
  --policy-name TritonS3Access \
  --policy-document file://triton-s3-policy.json

# Create a Kubernetes service account linked to the policy
eksctl create iamserviceaccount \
  --name triton-sa \
  --namespace triton \
  --cluster $CLUSTER_NAME \
  --attach-policy-arn arn:aws:iam::<ACCOUNT_ID>:policy/TritonS3Access \
  --approve \
  --override-existing-serviceaccounts
```

The `triton-sa` service account will be referenced in the Helm chart to provide the pods with S3 read access without embedding credentials.

---

## Deploying Triton on EKS

### 6.1 Helm Chart Basics

NVIDIA maintains an official Helm chart for Triton in the `nvidia` repository. Add the repo and update:

```bash
helm repo add nvidia https://helm.ngc.nvidia.com/nvidia
helm repo update
```

### 6.2 Customizing `values.yaml`

Create a `values.yaml` file that reflects your latency‑focused configuration. Below is a starter template:

```yaml
# values.yaml
replicaCount: 2

image:
  repository: nvcr.io/nvidia/tritonserver
  tag: 24.04-py3
  pullPolicy: IfNotPresent

serviceAccount:
  create: false
  name: triton-sa

resources:
  limits:
    nvidia.com/gpu: 1
    cpu: "4"
    memory: "16Gi"
  requests:
    nvidia.com/gpu: 1
    cpu: "2"
    memory: "8Gi"

# Enable the Prometheus exporter
metrics:
  enabled: true
  port: 8002

# Model repository configuration
modelRepository:
  # Use a sidecar container that syncs from S3 to an emptyDir
  s3:
    enabled: true
    bucket: my-triton-models
    region: us-west-2
    prefix: /
    syncInterval: 300 # seconds

# Triton server arguments
triton:
  args:
    - "--model-repository=$(MODEL_REPO)"
    - "--log-info=true"
    - "--log-verbose=1"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--strict-model-config=false"
    - "--allow-metrics=true"
    - "--allow-gpu-metrics=true"
    - "--http-port=8000"
    - "--grpc-port=8001"
    - "--metrics-port=8002"
    - "--backend-config=tensorflow,version=2"
    - "--model-control-mode=poll"
    - "--rate-limit=2000" # max requests per second per pod
    - "--backend-config=onnxruntime,execution_mode=ORT_SEQUENTIAL"
    - "--backend-config=trt,precision_mode=FP16"
    - "--backend-config=trt,force_compute_precision=FP16"
    - "--backend-config=trt,disable_tensorrt=False"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"
    - "--backend-config=python,shm-default-byte-size=1073741824"

# Dynamic batching configuration (global)
dynamicBatching:
  enabled: true
  maxBatchSize: 32
  preferredBatchSize: [8,16,32]
  maxQueueDelayMicroseconds: 1000 # 1 ms
  defaultQueueDelayMicroseconds: 500

# Liveness / readiness probes
livenessProbe:
  httpGet:
    path: /v2/health/live
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /v2/health/ready
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
```

**Key latency‑related knobs:**

- `dynamicBatching.maxQueueDelayMicroseconds` – lower values reduce wait time before a batch is formed.
- `rate-limit` – caps request burst per pod, preventing queuing spikes.
- `backend-config` for TensorRT (`precision_mode=FP16`) – reduces compute latency on compatible GPUs.
- `model-control-mode=poll` – enables hot‑reloading without restarting the server.

### 6.3 Launching the Deployment

```bash
helm install triton nvidia/triton-inference-server \
  -n triton --create-namespace \
  -f values.yaml
```

Verify the pods are running:

```bash
kubectl get pods -n triton -w
```

You should see something like:

```
NAME                     READY   STATUS    RESTARTS   AGE
triton-6c8d5f5b5c-abcde  1/1     Running   0          2m
triton-6c8d5f5b5c-fghij  1/1     Running   0          2m
```

The service is exposed via a **LoadBalancer** (or an Ingress controller if you prefer). Retrieve the external endpoint:

```bash
kubectl get svc triton -n triton
```

The `EXTERNAL-IP` column gives you the address to send HTTP/gRPC requests.

---

## Model Repository Layout & Versioning

Triton expects a specific directory structure:

```
/models
 └─ resnet50
      ├─ 1
      │   └─ model.onnx
      └─ config.pbtxt
```

- **Version directories** (`1`, `2`, …) hold the actual model files.
- **`config.pbtxt`** defines input/output shapes, data types, and batching preferences.

Example `config.pbtxt` for an ONNX ResNet‑50 model:

```protobuf
name: "resnet50"
platform: "onnxruntime_onnx"
max_batch_size: 32
input [
  {
    name: "input"
    data_type: TYPE_FP32
    dims: [3, 224, 224]
  }
]
output [
  {
    name: "probabilities"
    data_type: TYPE_FP32
    dims: [1000]
  }
]
dynamic_batching {
  preferred_batch_size: [8, 16, 32]
  max_queue_delay_microseconds: 1000
}
```

When you push a new version to the S3 bucket, the sidecar syncer (configured in `values.yaml`) will detect the change within the `syncInterval` (default 5 min) and Triton will automatically load the new version without downtime.

---

## Latency‑Optimization Techniques

### 8.1 Dynamic Batching

Dynamic batching is the most impactful latency reducer when the request rate is moderate to high. Triton collects incoming requests for up to `maxQueueDelayMicroseconds` before launching a GPU kernel. The trade‑off is **latency vs. throughput**:

- **Low delay (e.g., 500 µs)** → minimal wait, higher per‑request latency but lower GPU idle time.
- **Higher delay (e.g., 2000 µs)** → more opportunity to pack requests, better throughput but increased tail latency.

Empirically, a **1 ms queue delay** works well for 10‑30 QPS workloads on a single A10G GPU.

**Implementation tip:** Use the `TRITON_SERVER_DYNAMIC_BATCHING_QUEUE_DELAY_US` environment variable to override the Helm default per deployment.

### 8.2 GPU Allocation & Multi‑Model Sharing

If you have several lightweight models (e.g., text classifiers), you can **share a GPU** across multiple Triton pods using **Multi‑Model GPU Sharing**:

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
  requests:
    nvidia.com/gpu: 0.5   # Fractional GPU requests supported on G5 instances
```

Kubernetes will schedule two pods per GPU, each receiving ~50 % of the GPU memory. Combine this with **CUDA MPS (Multi‑Process Service)** for better context-switch performance.

### 8.3 Model Warm‑up & Cache Management

Cold starts are a common source of latency spikes. Triton provides a `--model-warmup` flag that can be used to preload kernels:

```yaml
triton:
  args:
    - "--model-repository=$(MODEL_REPO)"
    - "--model-warmup={\"name\":\"resnet50\",\"batch_size\":1,\"inputs\":[{\"name\":\"input\",\"shape\":[1,3,224,224],\"data_type\":\"TYPE_FP32\"}],\"outputs\":[{\"name\":\"probabilities\",\"shape\":[1,1000],\"data_type\":\"TYPE_FP32\"}],\"iterations\":10}"
```

Running warm‑up for 10 iterations ensures that the first real inference does not pay the kernel compilation cost.

### 8.4 Request/Response Serialization Choices

- **gRPC** is generally faster than HTTP/REST because it avoids JSON encoding overhead.
- For binary payloads (e.g., images), use **protobuf `bytes`** fields or **TensorFlow Record** format.
- Enable **HTTP/2** on the load balancer to reuse connections.

**Client example (Python gRPC):**

```python
import grpc
import tritonclient.grpc as grpcclient

triton_client = grpcclient.InferenceServerClient(
    url="triton.mycompany.com:8001",
    verbose=False,
    ssl=False)

# Prepare input
inputs = grpcclient.InferInput('input', [1, 3, 224, 224], "FP32")
inputs.set_data_from_numpy(image_np)

# Run inference
response = triton_client.infer(
    model_name='resnet50',
    inputs=[inputs],
    request_id='req-123')

output = response.as_numpy('probabilities')
print(output.shape)
```

### 8.5 Network‑Level Tweaks (Service Mesh & Ingress)

When you route traffic through an **Ingress controller** (e.g., AWS Load Balancer Controller) or a **service mesh** (AWS App Mesh, Istio), the added hop can add 1‑2 ms of latency. To mitigate:

- Use **TCP (gRPC) passthrough** rather than HTTP/1.1 termination.
- Enable **proxy‑protocol** on the ALB/NLB to preserve client IPs without extra processing.
- Keep the Triton service in a **dedicated VPC subnet** that is colocated with the GPU node group to minimize cross‑AZ traffic.

---

## Monitoring, Profiling, and Observability

### 9.1 Prometheus & Grafana Integration

Deploy the Prometheus Operator via Helm:

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm install prometheus prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace
```

Triton’s metrics endpoint (`/metrics` on port 8002) is scraped automatically because `metrics.enabled=true`. A typical dashboard panel for **per‑model latency**:

```promql
histogram_quantile(0.95, sum(rate(triton_inference_request_duration_seconds_bucket{model_name="resnet50"}[1m])) by (le))
```

This shows the 95th‑percentile latency over the last minute.

### 9.2 Triton’s Built‑in Metrics

Key metrics to monitor:

| Metric | Description |
|--------|-------------|
| `triton_inference_request_success_total` | Count of successful inference calls. |
| `triton_inference_request_failure_total` | Count of failed calls (helps detect model crashes). |
| `triton_gpu_utilization_percent` | GPU usage per pod (helps detect under‑utilization). |
| `triton_inference_queue_size` | Number of pending requests waiting for batch formation. |
| `triton_model_load_time_seconds` | Time taken to load each model version. |

Export these to CloudWatch using the **Prometheus Remote Write** integration if you need centralized AWS monitoring.

### 9.3 Tracing with OpenTelemetry

For end‑to‑end latency analysis, instrument the client and the server:

```yaml
# Add OpenTelemetry collector sidecar
sidecars:
  - name: otel-collector
    image: otel/opentelemetry-collector:0.96.0
    args: ["--config=/conf/collector.yaml"]
    volumeMounts:
      - name: collector-config
        mountPath: /conf
volumes:
  - name: collector-config
    configMap:
      name: otel-collector-config
```

The collector can export to **AWS X-Ray** or **Jaeger**, allowing you to see where latency spikes (network, queuing, GPU kernel) occur.

---

## Autoscaling for Consistent Latency

### 10.1 Horizontal Pod Autoscaler (HPA)

The classic HPA can react to CPU or custom metrics. For latency‑driven scaling, use **custom metrics** based on `triton_inference_queue_size`:

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: triton-hpa
  namespace: triton
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: triton
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Pods
      pods:
        metric:
          name: triton_inference_queue_size
        target:
          type: AverageValue
          averageValue: "5"
```

When the average queue size exceeds 5 requests, the HPA adds more pods, reducing per‑pod load and thus latency.

### 10.2 KEDA‑Based Event‑Driven Scaling

**KEDA (Kubernetes Event‑Driven Autoscaling)** can scale based on external metrics such as **SQS message depth** or **Kafka lag**. If your inference requests are queued in an SQS queue, you can tie scaling directly to the number of pending messages:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: triton-sqs-scaler
  namespace: triton
spec:
  scaleTargetRef:
    name: triton
  minReplicaCount: 2
  maxReplicaCount: 12
  triggers:
    - type: aws-sqs-queue
      metadata:
        queueURL: https://sqs.us-west-2.amazonaws.com/123456789012/inference-requests
        queueLength: "20"
        activationQueueLength: "10"
```

KEDA will spin up pods as the queue length grows, ensuring that latency stays within SLA even during traffic spikes.

---

## Real‑World Case Study: 30 % Latency Reduction

**Background**  
A media‑streaming company deployed a ResNet‑101 model for live thumbnail generation. Initial latency averaged **120 ms** per frame, exceeding the 80 ms SLA.

**Actions Taken**

| Step | Configuration | Measured Impact |
|------|----------------|-----------------|
| 1️⃣ Reduce `maxQueueDelayMicroseconds` from **2000 µs** to **500 µs** | `dynamicBatching.maxQueueDelayMicroseconds = 500` | Dropped tail latency by 15 ms |
| 2️⃣ Enable FP16 TensorRT precision | `--backend-config=trt,precision_mode=FP16` | Throughput ↑ 20 %, latency ↓ 10 ms |
| 3️⃣ Warm‑up the model (20 iterations) | `--model-warmup` flag | Eliminated cold‑start spikes |
| 4️⃣ Deploy two pods per GPU (fractional GPU request) | `nvidia.com/gpu: 0.5` per pod | Better GPU utilization, latency ↓ 5 ms |
| 5️⃣ Switch client from HTTP/REST to gRPC with HTTP/2 | Updated client library | Reduced serialization overhead by ~2 ms |

**Result**  
Overall average latency fell from **120 ms** to **84 ms**, a **30 % reduction**, comfortably meeting the SLA.

---

## Best‑Practice Checklist

- **Cluster & Node Setup**
  - Use GPU‑optimized instance types (A10G, V100, T4) with the latest NVIDIA drivers.
  - Enable **EFA** (Elastic Fabric Adapter) for low‑latency intra‑node communication if you have multi‑node GPU clusters.
- **Triton Configuration**
  - Turn on **dynamic batching** with a low `maxQueueDelayMicroseconds`.
  - Use **FP16/INT8** precision where model accuracy permits.
  - Define `max_batch_size` in `config.pbtxt` aligned with your hardware memory.
- **Model Management**
  - Store models in S3 and use the sidecar syncer for hot‑reloading.
  - Keep a **single version** in production; stage new versions in a separate bucket prefix.
- **Networking**
  - Deploy a **Network Load Balancer (NLB)** for TCP (gRPC) traffic.
  - Keep the Triton service in a **private subnet** to avoid internet hops.
- **Observability**
  - Scrape Triton metrics with Prometheus.
  - Set alerts on `triton_inference_queue_size` and 95th‑percentile latency.
- **Autoscaling**
  - Use HPA with custom queue‑size metrics.
  - Consider KEDA for event‑driven scaling from message queues.
- **Security**
  - Use IRSA for S3 access; avoid embedding AWS keys.
  - Enable **encryption at rest** for model buckets and **TLS** on the load balancer.

---

## Conclusion

Optimizing inference latency is a multi‑dimensional challenge that spans **hardware selection, server configuration, network topology, and observability**. NVIDIA Triton Inference Server provides a rich set of features—dynamic batching, model versioning, and GPU‑aware scheduling—while Amazon EKS delivers a managed, scalable orchestration layer that integrates seamlessly with AWS’s security and monitoring ecosystem.

By following the step‑by‑step guide above—provisioning a GPU‑enabled EKS cluster, deploying Triton with a latency‑focused Helm chart, fine‑tuning batching and precision, and wiring up robust monitoring and autoscaling—you can achieve **sub‑100 ms latency** for demanding production workloads. The real‑world case study demonstrates that even modest configuration tweaks can yield **30 % latency reductions**, translating directly into better user experiences and tighter SLA compliance.

Stay iterative: profile your workload, adjust batching windows, experiment with precision modes, and let the observability stack drive data‑backed decisions. With this foundation, your team will be equipped to serve any deep‑learning model at scale, confidently meeting the latency expectations of modern AI‑driven applications.

---

## Resources
- [NVIDIA Triton Inference Server Documentation](https://docs.nvidia.com/deeplearning/triton-inference-server/)  
- [Amazon EKS Best Practices Guide](https://docs.aws.amazon.com/eks/latest/userguide/best-practices.html)  
- [Prometheus Monitoring for Triton Metrics](https://github.com/triton-inference-server/server/blob/main/docs/monitoring.md)  
- [KEDA – Kubernetes Event‑Driven Autoscaling](https://keda.sh/)  
- [AWS Load Balancer Controller – gRPC Support](https://docs.aws.amazon.com/eks/latest/userguide/aws-load-balancer-controller.html)  

---