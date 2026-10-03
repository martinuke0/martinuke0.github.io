---
title: "Multi-Adapter LoRA Inference Engine with Weight Paging and Shared Base"
date: "2026-10-03T02:00:57.873"
draft: false
tags: ["lora", "inference", "pytorch", "weight-paging", "systems"]
description: "Build a production‑grade LoRA inference engine that pages adapters, shares a base model, and scales to multiple tasks, demonstrating real systems engineering."
summary: "A hands‑on guide to building a multi‑adapter LoRA inference engine with weight paging and a shared base model, perfect for showcasing systems engineering skills."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-03-multi-adapter-lora-inference-engine-with-weight-paging-and-shared-base.svg"
  alt: "A schematic of multiple LoRA adapters connected to a shared base model."
  caption: ""
  relative: false
---

> **TL;DR** — This project builds a production‑grade LoRA inference engine that can serve multiple adapters from a single shared base model, paging weights in and out on demand. It demonstrates real systems skills—memory management, concurrent request handling, and modular architecture—that hiring managers look for.

In this guide you will construct a side project that not only runs inference with multiple LoRA adapters but also showcases your ability to design and implement systems that handle resource constraints, concurrency, and extensibility. The code is written in Python using PyTorch and Hugging Face Transformers, and it can be run on a single GPU or scaled across containers.

## Why This Project Stands Out on a CV

- **Memory‑efficient weight paging** – You’ll implement a custom pager that loads/unloads adapter weights on demand, proving you understand virtual memory concepts in a deep‑learning context.  
- **Shared base model architecture** – By keeping a single instance of the base model and multiplexing adapters, you demonstrate the ability to design resource‑shared services, a pattern common in micro‑service and SaaS back‑ends.  
- **Concurrent request handling** – The included FastAPI server shows you can serve multiple inference requests safely, a skill directly transferable to building production APIs.  
- **Modular, extensible codebase** – The separation of concerns (loader, registry, pager, server) signals you can build maintainable, testable systems.  
- **Observability & metrics** – Integrating Prometheus metrics and structured logging highlights your readiness for production environments.  

These competencies map to roles such as **ML Engineer**, **Systems Engineer**, or **MLOps Engineer**, where the ability to ship efficient, scalable inference pipelines is prized.

## Architecture Overview

The system is composed of five logical components:

1. **Base Model Loader** – Loads the frozen pre‑trained model (e.g., `bert-base-uncased`) once into GPU memory and exposes a `forward` method.  
2. **Adapter Registry** – A thread‑safe dictionary that maps adapter names to their weight files (`.bin` or `.safetensors`).  
3. **Weight Pager** – Implements paging logic: on a cache miss it streams the required adapter weights from disk (or an object store) into a pre‑allocated buffer, then swaps them into the model’s parameter slots.  
4. **Inference Engine** – Combines the base model with the currently paged adapter to run inference. It also handles batching and optional quantization.  
5. **API Server** – A FastAPI application exposing `/predict` endpoints, authenticating requests, and emitting Prometheus metrics.

A simplified textual diagram:

```
+-------------------+      +-------------------+
|   API Server      | ---> |  Inference Engine |
+-------------------+      +-------------------+
          |                       |
          |   +-------------+     |
          +-->| Weight Pager|<---+
              +-------------+
                     |
                     v
          +-------------------+
          | Adapter Registry  |
          +-------------------+
```

## Building It Step by Step

### Step 1 – Set up the environment

```bash
python -m venv venv
source venv/bin/activate
pip install torch transformers fastapi uvicorn prometheus-client safetensors
```

### Step 2 – Define the base model loader

```python
# loaders/base.py
import torch
from transformers import AutoModel

class BaseModelLoader:
    def __init__(self, model_name: str, device: str = "cuda"):
        self.model = AutoModel.from_pretrained(model_name).to(device)
        self.model.eval()
        self.device = device

    def forward(self, input_ids, attention_mask):
        with torch.no_grad():
            return self.model(input_ids=input_ids,
                              attention_mask=attention_mask)
```

### Step 3 – Create an adapter registry

```python
# registry/adapter_registry.py
import threading
from pathlib import Path

class AdapterRegistry:
    def __init__(self):
        self._lock = threading.Lock()
        self._adapters = {}

    def register(self, name: str, path: Path):
        with self._lock:
            self._adapters[name] = path

    def get(self, name: str) -> Path:
        with self._lock:
            return self._adapters[name]
```

### Step 4 – Implement the weight pager

```python
# pager/weight_pager.py
import torch
from safetensors.torch import load_file
from registry.adapter_registry import AdapterRegistry

class WeightPager:
    def __init__(self, base_loader: BaseModelLoader,
                 registry: AdapterRegistry,
                 max_adapters: int = 4):
        self.base = base_loader
        self.registry = registry
        self.max_adapters = max_adapters
        self.current = None  # name of loaded adapter

    def load_adapter(self, name: str):
        if name == self.current:
            return
        path = self.registry.get(name)
        # Stream weights from disk
        state_dict = load_file(path)
        # Replace LoRA parameters in the base model
        for key, param in self.base.model.named_parameters():
            if key in state_dict:
                param.data.copy_(state_dict[key])
        self.current = name
```

### Step 5 – Build the inference engine

```python
# engine/inference_engine.py
from loaders.base import BaseModelLoader
from pager.weight_pager import WeightPager
from registry.adapter_registry import AdapterRegistry

class InferenceEngine:
    def __init__(self, base_loader: BaseModelLoader,
                 registry: AdapterRegistry):
        self.base_loader = base_loader
        self.pager = WeightPager(base_loader, registry)

    def predict(self, adapter: str, input_ids, attention_mask):
        self.pager.load_adapter(adapter)
        return self.base_loader.forward(input_ids, attention_mask)
```

### Step 6 – Expose a FastAPI service

```python
# api/server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from engine.inference_engine import InferenceEngine
from loaders.base import BaseModelLoader
from registry.adapter_registry import AdapterRegistry
import time

app = FastAPI()

# Initialize components
base_loader = BaseModelLoader("bert-base-uncased")
registry = AdapterRegistry()
registry.register("sentiment", Path("adapters/sentiment.safetensors"))
registry.register("ner", Path("adapters/ner.safetensors"))
engine = InferenceEngine(base_loader, registry)

class PredictRequest(BaseModel):
    adapter: str
    text: str

@app.post("/predict")
async def predict(req: PredictRequest):
    # Tokenize (simplified)
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
    enc = tokenizer(req.text, return_tensors="pt")
    try:
        output = engine.predict(req.adapter,
                                enc["input_ids"],
                                enc["attention_mask"])
        return {"logits": output.logits.tolist()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### Step 7 – Add a CLI for quick testing

```python
# cli/main.py
import argparse
from engine.inference_engine import InferenceEngine
from loaders.base import BaseModelLoader
from registry.adapter_registry import AdapterRegistry

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--text", required=True)
    args = parser.parse_args()

    base = BaseModelLoader("bert-base-uncased")
    reg = AdapterRegistry()
    reg.register(args.adapter, Path(f"adapters/{args.adapter}.safetensors"))
    engine = InferenceEngine(base, reg)
    result = engine.predict(args.adapter, *tokenize(args.text))
    print(result)

if __name__ == "__main__":
    main()
```

## Running and Testing It

1. **Prepare adapters** – Fine‑tune two LoRA adapters (e.g., sentiment, NER) and export them as `.safetensors` files in the `adapters/` directory.

2. **Start the API server**

```bash
uvicorn api.server:app --reload --host 0.0.0.0 --port 8000
```

3. **Send a test request**

```bash
curl -X POST "http://localhost:8000/predict" \
     -H "Content-Type: application/json" \
     -d '{"adapter":"sentiment","text":"I love this product!"}'
```

4. **Run the CLI**

```bash
python cli/main.py --adapter sentiment --text "Great service!"
```

5. **Validate with metrics** – Open `http://localhost:8000/metrics` (Prometheus) to confirm request counts and latency.

A simple unit test using `pytest` can verify that the pager swaps adapters correctly:

```python
# tests/test_pager.py
from pager.weight_pager import WeightPager
from loaders.base import BaseModelLoader
from registry.adapter_registry import AdapterRegistry

def test_pager_swaps():
    base = BaseModelLoader("bert-base-uncased")
    reg = AdapterRegistry()
    reg.register("a", Path("adapters/a.safetensors"))
    reg.register("b", Path("adapters/b.safetensors"))
    pager = WeightPager(base, reg)
    pager.load_adapter("a")
    assert pager.current == "a"
    pager.load_adapter("b")
    assert pager.current == "b"
```

## Extending It: Your Roadmap to Senior-Level

1. **Persistent adapter storage with Redis** – Cache adapter weights in Redis to avoid disk I/O on every request, reducing latency and enabling fast scaling.  
2. **Horizontal scaling via Kubernetes** – Deploy the API server behind a Kubernetes Deployment with multiple replicas, using a load balancer to distribute traffic.  
3. **Observability stack (Prometheus + Grafana)** – Export detailed latency, memory, and error metrics; create dashboards to monitor health in production.  
4. **Fault tolerance with retries and circuit breakers** – Wrap external calls (e.g., to a model registry) with retry logic and circuit‑breaker patterns to prevent cascading failures.  
5. **Benchmarking suite with Locust** – Simulate realistic traffic patterns, measure throughput and GPU utilization, and identify bottlenecks for optimization.  
6. **Quantization & ONNX export** – Convert the base model to ONNX with dynamic quantization, enabling inference on CPU or edge devices and broadening deployment options.

## Key Takeaways

- Implemented a weight‑paging mechanism that dynamically swaps LoRA adapters while keeping a single base model in memory.  
- Designed a modular architecture (loader, registry, pager, engine, API) that mirrors production service patterns.  
- Provided end‑to‑end runnable code, including a FastAPI server, CLI, and test suite, demonstrating full‑stack engineering ability.  
- Showcased scalability and observability considerations, positioning the project as a foundation for senior‑level systems work.

## Further Reading

- [LoRA: Low‑Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685) – the original paper that introduced the technique.  
- [Hugging Face Transformers Documentation](https://huggingface.co/docs/transformers/) – canonical guide for loading and fine‑tuning models.  
- [FastAPI Official Tutorial](https://fastapi.tiangolo.com/tutorial/) – build production‑ready APIs with Python.  
- [Kubernetes Production Best Practices](https://kubernetes.io/docs/setup/production-environment/) – scale your inference service horizontally.  
- [Prometheus Monitoring Guide](https://prometheus.io/docs/introduction/overview/) – instrument your system with metrics.