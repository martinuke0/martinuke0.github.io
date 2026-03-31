---
title: "The Rise of Local LLM Orchestrators: Managing Personal Compute Clusters for Private AI Development"
date: "2026-03-31T22:00:18.275"
draft: false
tags: ["LLM", "Orchestration", "Private AI", "Edge Computing", "Open Source"]
---

## Introduction

Large language models (LLMs) have moved from research curiosities to production‑ready services in just a few years. The public‑facing APIs offered by OpenAI, Anthropic, Google, and others have democratized access to powerful text generation, reasoning, and coding capabilities. Yet, for many organizations and power users, the “cloud‑only” model presents three fundamental concerns:

1. **Data privacy and compliance** – Sensitive documents, medical records, or proprietary code often cannot be sent to third‑party servers without rigorous legal review.  
2. **Cost predictability** – Pay‑per‑token pricing can explode when models are used intensively for internal tooling or batch processing.  
3. **Latency & control** – Real‑time, on‑device inference eliminates round‑trip latency and gives developers the ability to tweak model parameters, quantization levels, and hardware utilization.

Enter **local LLM orchestrators**—software stacks that coordinate multiple compute nodes (GPUs, CPUs, ASICs, or even edge devices) within a private network, turning a personal workstation or a modest home‑lab into a fully fledged AI development platform. This article explores why these orchestrators are gaining traction, dissects their architecture, walks through a practical setup, and outlines best practices for secure, scalable, and cost‑effective private AI development.

---

## Why Private AI Development Matters

| Concern | Cloud‑only model | Private/local model |
|---------|------------------|---------------------|
| **Data residency** | Data leaves the premises, often stored in multi‑tenant environments. | All data stays on‑premises, satisfying GDPR, HIPAA, or corporate policies. |
| **Cost transparency** | Billing is opaque; hidden fees for data transfer, storage, and request overhead. | Fixed hardware investment; operational cost is electricity and maintenance. |
| **Customization** | Limited to provider‑supplied hyper‑parameters and model versions. | Full control over model quantization, fine‑tuning, and inference pipelines. |
| **Latency** | Network latency varies (10‑200 ms typical). | Sub‑millisecond local memory access; deterministic performance. |
| **Vendor lock‑in** | Migration requires re‑training or costly model export. | Portable artifacts (ONNX, GGUF) can be moved between orchestrators. |

These drivers are especially compelling for:

- **Healthcare providers** handling PHI (Protected Health Information).  
- **Financial institutions** needing to keep trade secrets and client data behind firewalls.  
- **Research labs** that want to experiment with model modifications without exposing intellectual property.  
- **Individual developers** who want to tinker with cutting‑edge LLMs without a monthly API bill.

---

## Evolution of LLM Deployment Models

### 1. Cloud‑first Era (2020‑2022)

The first wave of LLM adoption relied heavily on hosted APIs. Companies built SaaS products on top of OpenAI’s GPT‑3 or Anthropic’s Claude, leveraging the “infrastructure as a service” model to avoid hardware headaches.

### 2. Edge and On‑Premise Shift (2023‑2025)

With the release of quantized model formats (e.g., GGML, GGUF) and the democratization of consumer‑grade GPUs (RTX 30/40 series, AMD Radeon 6000 series), developers discovered that inference could run on a laptop for many use‑cases. Open‑source inference engines such as **llama.cpp**, **vLLM**, and **DeepSpeed** made it possible to squeeze 13‑B and even 70‑B parameters into a single consumer GPU with 4‑bit quantization.

### 3. Orchestrated Personal Clusters (2025‑present)

The next logical step is to treat a collection of personal devices as a **cluster**—a mini‑data‑center. Orchestrators abstract hardware heterogeneity, provide scheduling, versioning, and observability, and expose a unified API (often compatible with standard OpenAI‑style endpoints). This mirrors the cloud experience but stays inside the user’s network.

---

## What Is a Local LLM Orchestrator?

At its core, an orchestrator is a **control plane** that:

1. **Discovers** available compute resources (GPU, CPU, TPU).  
2. **Schedules** inference or fine‑tuning jobs across those resources.  
3. **Manages** model artifacts (download, version, quantize, cache).  
4. **Monitors** health, latency, and resource utilization.  
5. **Enforces** security policies (authentication, encryption, isolation).

Think of it as a lightweight Kubernetes for LLM workloads, but optimized for a single‑owner environment and with a focus on **model‑centric** operations rather than generic containers.

### Comparison with Cloud Orchestrators

| Feature | Cloud (AWS, GCP) | Local LLM Orchestrator |
|---------|------------------|------------------------|
| **Scale** | Thousands of nodes across regions | Typically 1‑10 nodes in a LAN |
| **Multi‑tenant** | Yes (IAM, RBAC) | Usually single tenant, optional multi‑user support |
| **Billing** | Pay‑as‑you‑go | Capital expense + electricity |
| **Network** | High‑throughput, low‑latency cross‑region | LAN speeds (10 GbE or Wi‑Fi 6) |
| **Complexity** | High (IAM, VPC, quotas) | Moderate (Docker, systemd, Prometheus) |
| **Vendor lock‑in** | Possible (proprietary services) | Minimal (open‑source components) |

---

## Architectural Building Blocks

Below is a reference diagram (textual) of a typical orchestrator stack:

```
+--------------------------------------------------------+
|                 API Gateway (FastAPI)                 |
+----------------------+---------------------------------+
                       |
+----------------------+------------------------------+
|   Scheduler / Dispatcher (Ray Serve / Dask)            |
+----------------------+------------------------------+
|   |               |               |                |
|   v               v               v                v
| +-----+   +-----+   +---------+   +--------+   +--------+
| |GPU1 |   |GPU2 |   |CPU Node|   |TPU/FPGA|   |Edge IoT|
| +-----+   +-----+   +---------+   +--------+   +--------+
|   ^         ^          ^            ^            ^
|   |         |          |            |            |
|   +--- Model Store (artifact registry, S3‑like) ---+
|   |   (gguf, onnx, safetensors)                     |
|   +-------------------------------------------------+
|   |   Monitoring (Prometheus) + Grafana UI         |
|   +-------------------------------------------------+
|   |   Security Layer (Zero‑Trust, mTLS)             |
+--------------------------------------------------------+
```

### 1. Compute Nodes

- **GPU servers**: RTX 4090, A100, or consumer‑grade GPUs with CUDA/ROCm support.  
- **CPU‑only nodes**: Useful for embedding retrieval or lightweight decoding.  
- **Accelerators**: Google Coral TPU, AWS Inferentia (if you have a local edge device).  

### 2. Model Store / Artifact Registry

A simple object storage (MinIO, local filesystem, or an NFS share) holds versioned model files. Metadata such as quantization level, tokenizer config, and SHA‑256 checksum are stored alongside.

### 3. Scheduler / Dispatcher

Frameworks like **Ray Serve**, **Dask**, or even **Celery** can route incoming inference requests to the most appropriate node based on:

- Current load (GPU memory usage, GPU utilization).  
- Model compatibility (some nodes only support 4‑bit GGUF, others 8‑bit).  
- Latency SLAs (critical vs. batch jobs).

### 4. Monitoring & Observability

- **Prometheus** scrapes metrics (`gpu_memory_used_bytes`, `inference_latency_seconds`).  
- **Grafana** dashboards visualize trends.  
- **ELK** or ** Loki** for logs.

### 5. Security & Isolation

- **Zero‑trust networking**: Mutual TLS between components.  
- **Encrypted storage**: LUKS or filesystem‑level encryption for model artifacts.  
- **RBAC**: Simple token‑based auth (JWT) for API users.

---

## Popular Open‑Source Orchestrators

| Project | Core Language | Notable Features | Typical Use‑Case |
|---------|---------------|------------------|-----------------|
| **vLLM + Ray Serve** | Python | High‑throughput serving, speculative decoding, tensor parallelism. | Enterprise‑grade serving on multi‑GPU rigs. |
| **llama.cpp + text-generation-webui** | C++ / Python | 4‑bit/8‑bit GGUF inference, minimal dependencies, web UI. | Hobbyist laptops or single‑GPU setups. |
| **DeepSpeed Inference** | Python | ZeRO‑3, off‑load to CPU, supports 100‑B+ models. | Large‑scale research clusters. |
| **Modal** | Python (cloud‑edge hybrid) | Serverless functions that can run on local hardware via “Modal Workers”. | Rapid prototyping with optional cloud fallback. |
| **OpenAI Private Deployments** | Proprietary (OpenAI) | Managed private instance with OpenAI API compatibility. | Enterprises needing official support. |

Each of these can be combined—for example, using **vLLM** for heavy‑weight models and **llama.cpp** for low‑latency, low‑resource tasks—under a single API gateway.

---

## Setting Up Your First Personal Compute Cluster

Below is a step‑by‑step guide for a **home‑lab** consisting of:

- One desktop with an RTX 4090.  
- One modest server (AMD Threadripper, no GPU) for retrieval and preprocessing.  
- A NAS (Synology) acting as the **model store**.

### 1. Hardware Checklist

| Component | Minimum Spec | Recommended |
|-----------|--------------|-------------|
| GPU Node | RTX 3060 (12 GB VRAM) | RTX 4090 (24 GB VRAM) |
| CPU Node | 8‑core AMD/Intel | 24‑core Threadripper |
| Memory | 32 GB DDR4 | 128 GB DDR5 |
| Storage | 1 TB NVMe SSD | 2 TB NVMe + 8 TB HDD (NAS) |
| Networking | Gigabit Ethernet | 10 GbE switch (optional) |
| Power | 650 W PSU | 1000 W + UPS |

### 2. OS & Driver Installation

```bash
# Ubuntu 22.04 LTS (recommended)
sudo apt update && sudo apt upgrade -y

# NVIDIA driver (latest stable)
sudo ubuntu-drivers autoinstall
# Verify
nvidia-smi
```

If you prefer AMD GPUs, install the ROCm stack accordingly.

### 3. Container Runtime

We’ll use **Docker** for isolation and reproducibility.

```bash
# Install Docker Engine
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
newgrp docker
```

Create a **docker‑compose.yml** that launches three services:

1. **api-gateway** – FastAPI exposing `/v1/completions`.  
2. **scheduler** – Ray Serve.  
3. **model-store** – MinIO (S3‑compatible).

```yaml
version: "3.9"
services:
  minio:
    image: minio/minio:RELEASE.2024-03-01T23-02-04Z
    container_name: minio
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - minio-data:/data

  api-gateway:
    image: python:3.11-slim
    container_name: api-gateway
    working_dir: /app
    volumes:
      - ./gateway:/app
    environment:
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=minioadmin
      - MINIO_SECRET_KEY=minioadmin
    depends_on:
      - scheduler
    ports:
      - "8000:8000"

  scheduler:
    image: rayproject/ray:2.9.0
    container_name: ray-scheduler
    command: ["ray", "start", "--head"]
    ports:
      - "6379:6379"
      - "8265:8265"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all

volumes:
  minio-data:
```

Create the **gateway** folder with a simple FastAPI app:

```python
# gateway/main.py
import os
import uuid
import httpx
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET = os.getenv("MINIO_SECRET_KEY")

class CompletionRequest(BaseModel):
    model: str
    prompt: str
    max_tokens: Optional[int] = 256
    temperature: Optional[float] = 0.7
    top_p: Optional[float] = 0.9

@app.post("/v1/completions")
async def completions(req: CompletionRequest, authorization: Optional[str] = Header(None)):
    # Very simple token check (replace with JWT in production)
    if authorization != "Bearer secret-token":
        raise HTTPException(status_code=401, detail="Invalid token")
    # Forward request to Ray Serve deployment
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://scheduler:8000/infer",
            json=req.dict(),
        )
    return resp.json()
```

The **scheduler** service will host a Ray Serve deployment that loads the requested model from MinIO, runs inference using `vLLM`, and returns the result.

### 4. Deploying the Cluster

```bash
docker compose up -d
# Verify containers
docker compose ps
# Check Ray dashboard
open http://localhost:8265
```

You now have a minimal private LLM API that can be called with any OpenAI‑compatible client.

---

## Managing Model Lifecycle

### 4.1 Downloading & Versioning

Store models in MinIO under a naming convention:

```
/models/<model_name>/<version>/<model_file>.gguf
```

A small Python utility can automate this:

```python
# utils/model_manager.py
import boto3
import hashlib
import pathlib
import requests

s3 = boto3.client(
    "s3",
    endpoint_url="http://localhost:9000",
    aws_access_key_id="minioadmin",
    aws_secret_access_key="minioadmin",
)

def download_and_register(url: str, model_name: str, version: str):
    response = requests.get(url, stream=True)
    response.raise_for_status()
    dest = pathlib.Path(f"./tmp/{model_name}-{version}.gguf")
    dest.parent.mkdir(parents=True, exist_ok=True)

    sha256 = hashlib.sha256()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            sha256.update(chunk)

    checksum = sha256.hexdigest()
    s3.upload_file(str(dest), "models", f"{model_name}/{version}/{dest.name}")

    # Store metadata (simple JSON)
    meta = {
        "model_name": model_name,
        "version": version,
        "checksum": checksum,
        "filename": dest.name,
    }
    s3.put_object(
        Bucket="models",
        Key=f"{model_name}/{version}/metadata.json",
        Body=str(meta).encode(),
    )
    print(f"✅ {model_name}:{version} registered")
```

Run it once to pull, for example, **Llama‑2‑13B‑Chat** in GGUF format.

### 4.2 Quantization & Conversion

If you have a raw PyTorch checkpoint, you can convert it to GGUF with `llama.cpp`:

```bash
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
make
# Convert a 13B checkpoint to 4-bit GGUF
./bin/convert-hf-to-gguf.py \
    --model-dir /path/to/hf/llama-2-13b-chat \
    --outfile llama-2-13b-chat.gguf \
    --outtype q4_0
```

Store the resulting file in the model store as described above.

---

## Scheduling Inference Requests

Below is a **Ray Serve** handler that loads a model on first use and caches it per worker:

```python
# scheduler/serve.py
import os
import ray
from ray import serve
from vllm import LLM, SamplingParams
import boto3
import tempfile

s3 = boto3.client(
    "s3",
    endpoint_url="http://minio:9000",
    aws_access_key_id=os.getenv("MINIO_ACCESS_KEY"),
    aws_secret_access_key=os.getenv("MINIO_SECRET_KEY"),
)
BUCKET = "models"

@serve.deployment(
    name="llm_infer",
    ray_actor_options={"num_gpus": 1},
    autoscaling_config={"min_replicas": 1, "max_replicas": 4},
)
class LLMInfer:
    def __init__(self):
        self.llm_cache = {}

    def _load_model(self, model_name: str, version: str):
        key_prefix = f"{model_name}/{version}"
        # Download model file
        with tempfile.NamedTemporaryFile(suffix=".gguf") as tmp:
            s3.download_fileobj(BUCKET, f"{key_prefix}/model.gguf", tmp)
            tmp.flush()
            # Initialize vLLM instance
            llm = LLM(model=tmp.name, tensor_parallel_size=1)
        self.llm_cache[(model_name, version)] = llm
        return llm

    async def __call__(self, request):
        body = await request.json()
        model = body["model"]
        prompt = body["prompt"]
        max_tokens = body.get("max_tokens", 256)

        name, version = model.split(":")
        llm = self.llm_cache.get((name, version))
        if llm is None:
            llm = self._load_model(name, version)

        sampling_params = SamplingParams(
            max_tokens=max_tokens,
            temperature=body.get("temperature", 0.7),
            top_p=body.get("top_p", 0.9),
        )
        outputs = llm.generate(prompt, sampling_params)
        # vLLM returns a generator; we take the first result
        result = next(outputs)
        return {"choices": [{"text": result.outputs[0].text}]}
```

Deploy it from the scheduler container:

```bash
ray start --head
serve deploy serve.py:LLMInfer
```

Now any request sent to `http://scheduler:8000/infer` will be serviced by the most appropriate GPU worker, automatically scaling up to four replicas if load spikes.

---

## Monitoring, Scaling, and Auto‑Scaling on a Home Lab

### 1. Prometheus Scrape Config

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: 'ray'
    static_configs:
      - targets: ['scheduler:9090']
  - job_name: 'gpu'
    static_configs:
      - targets: ['localhost:9835']   # nvidia‑smi exporter
```

Run Prometheus as another Docker service:

```yaml
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
```

### 2. Grafana Dashboard

Add a Grafana container that reads from Prometheus. Use community dashboards for `nvidia-smi` and `ray` metrics. Example panels:

- **GPU memory usage per node** (GB).  
- **Inference latency (p50/p95)**.  
- **Ray worker replica count** (auto‑scaled).  

### 3. Auto‑Scaling Policy

Ray Serve’s `autoscaling_config` (shown earlier) automatically spawns new replicas when request queue length exceeds a threshold. You can tune:

```json
{
  "min_replicas": 1,
  "max_replicas": 8,
  "target_ongoing_requests": 5,
  "upscale_delay_s": 30,
  "downscale_delay_s": 120
}
```

Combine this with a **cron job** that shuts down idle GPU nodes during night hours to save electricity.

---

## Security Best Practices

> **⚠️ Important:** Even though the cluster runs in a private network, a misconfiguration can expose your models (which may be proprietary) to the internet. Follow a defense‑in‑depth approach.

### 1. Zero‑Trust Networking

- Use **mutual TLS (mTLS)** between API gateway, scheduler, and model store.  
- Generate a short‑lived client certificate for each user or service.  

```bash
# Generate CA
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 -out ca.crt
# Generate server cert for api-gateway
openssl genrsa -out gateway.key 4096
openssl req -new -key gateway.key -out gateway.csr
openssl x509 -req -in gateway.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out gateway.crt -days 365 -sha256
```

Configure FastAPI to require client certs:

```python
# gateway/main.py (add)
app = FastAPI(
    # Force HTTPS + client cert verification
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    middleware=[
        Middleware(HTTPSRedirectMiddleware)
    ]
)
```

### 2. Encrypted Model Storage

If you store models on a NAS, enable **AES‑256 at‑rest** encryption (Synology’s encrypted shared folder). For local SSDs, use **LUKS**:

```bash
sudo cryptsetup luksFormat /dev/nvme0n1p2
sudo cryptsetup open /dev/nvme0n1p2 encrypted_data
mkfs.ext4 /dev/mapper/encrypted_data
```

Mount the encrypted volume at `/mnt/models` and point MinIO’s data directory there.

### 3. Role‑Based Access Control (RBAC)

Implement a lightweight token service:

```python
# auth/token_service.py
import jwt
from datetime import datetime, timedelta

SECRET = "super‑secret‑jwt‑key"

def generate_token(user: str, scopes: list):
    payload = {
        "sub": user,
        "scopes": scopes,
        "exp": datetime.utcnow() + timedelta(hours=8)
    }
    return jwt.encode(payload, SECRET, algorithm="HS256")
```

The API gateway checks `scopes` before forwarding to the scheduler (e.g., `inference`, `admin`).

---

## Real‑World Use Cases

### 1. Personal Knowledge Assistant

A researcher installs a private LLM orchestrator on a workstation and syncs their notes, PDFs, and code snippets to a local vector store (e.g., **FAISS**). The assistant can answer queries without ever sending proprietary data to the cloud, and latency stays under 100 ms thanks to GPU‑local inference.

### 2. Healthcare Data Compliance

A clinic runs a 7‑B medical LLM fine‑tuned on de‑identified patient records. By keeping the model on-premises and encrypting the model store, they meet **HIPAA** requirements while still providing clinicians with a conversational decision‑support tool.

### 3. Corporate R&D Sandbox

A fintech startup spins up a small cluster of RTX 4090 machines in a dedicated lab. Engineers can experiment with custom instruction‑tuning, evaluate new prompting strategies, and benchmark cost vs. performance—all without incurring external API spend or exposing trade secrets.

### 4. Edge‑Enabled IoT Devices

Manufacturers embed a **tiny 1‑B LLM** (e.g., **Phi‑1**) on microcontrollers for real‑time anomaly detection. The orchestrator aggregates inference results from dozens of devices, balances load, and pushes updated quantized models over the air.

---

## Future Trends

| Trend | What It Means for Local Orchestrators |
|-------|---------------------------------------|
| **Federated LLM Orchestration** | Multiple personal clusters collaborate on training or fine‑tuning without sharing raw data, using secure aggregation (e.g., DP‑FedAvg). |
| **TinyML LLMs on Microcontrollers** | Sub‑megabyte models will run on MCU‑class hardware, expanding the edge footprint to billions of devices. |
| **Hybrid Cloud‑Edge Orchestrators** | Seamless spill‑over to public cloud when local resources saturate, preserving privacy for the majority of traffic. |
| **Standardized Model Packaging (GGUF v2)** | Unified metadata (quantization, licensing, provenance) will make model exchange across orchestrators frictionless. |
| **AI‑native Operating Systems** | Future OS kernels may expose hardware‑accelerated inference primitives, reducing the need for heavyweight runtimes. |

---

## Conclusion

Local LLM orchestrators are rapidly maturing from hobbyist scripts into production‑grade platforms that rival cloud services in flexibility, observability, and scalability—while offering unmatched privacy, latency, and cost predictability. By combining open‑source inference engines (vLLM, llama.cpp), robust scheduling frameworks (Ray Serve, Dask), and industry‑standard monitoring and security tooling, anyone with a modest GPU can build a private AI development environment that serves personal assistants, compliance‑critical applications, and experimental research.

The key take‑aways for anyone embarking on this journey are:

1. **Start small, design for growth** – Begin with a single GPU container, then layer in a model store, scheduler, and monitoring.  
2. **Automate the model lifecycle** – Use scripts for download, conversion, and versioned storage to keep the pipeline reproducible.  
3. **Secure by design** – Zero‑trust networking, encrypted storage, and token‑based RBAC protect your intellectual property.  
4. **Leverage community dashboards** – Prometheus + Grafana give instant insight into GPU utilization and inference latency, enabling intelligent auto‑scaling.  
5. **Stay future‑proof** – Adopt standards like GGUF, keep an eye on federated learning frameworks, and consider hybrid cloud spill‑over for burst workloads.

With these principles, you can harness the full power of today’s LLMs without surrendering control to external providers—turning your personal compute cluster into a private AI engine that scales with your imagination.

---

## Resources

- **vLLM Documentation** – High‑throughput serving for LLMs  
  [https://github.com/vllm-project/vllm](https://github.com/vllm-project/vllm)

- **llama.cpp & GGUF Format** – Efficient inference on consumer hardware  
  [https://github.com/ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp)

- **Ray Serve Scaling Guide** – Autoscaling policies and deployment patterns  
  [https://docs.ray.io/en/latest/serve/index.html](https://docs.ray.io/en/latest/serve/index.html)

- **Prometheus + Grafana Monitoring** – Open‑source observability stack  
  [https://prometheus.io/docs/introduction/overview/](https://prometheus.io/docs/introduction/overview/)

- **Zero‑Trust Networking with mTLS** – Best practices for service‑to‑service security  
  [https://www.cloudflare.com/learning/security/zero-trust/](https://www.cloudflare.com/learning/security/zero-trust/)

- **HIPAA Compliance for AI** – Guidance on using AI in healthcare environments  
  [https://www.hhs.gov/hipaa/for-professionals/index.html](https://www.hhs.gov/hipaa/for-professionals/index.html)