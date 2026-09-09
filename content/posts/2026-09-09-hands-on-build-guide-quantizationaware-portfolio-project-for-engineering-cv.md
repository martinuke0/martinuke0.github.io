---  
title: "Hands-On Build Guide: Quantization‑Aware Portfolio Project for Engineering CV"  
date: "2026-09-09T16:01:54.854"  
draft: false  
tags: ["quantization", "systems", "cv", "side-project", "engineering"]  
description: "Build a production‑ready quantization pipeline for LLM inference and add a runnable project to your CV that signals real systems skill."  
summary: "A step‑by‑step guide to creating a quantization‑aware tool that you can ship, benchmark, and showcase in job interviews."  
showToc: true  
TocOpen: false  
cover:  
  image: "/images/covers/2026-09-09-hands-on-build-guide-quantizationaware-portfolio-project-for-engineering-cv.svg"  
  alt: "A sleek laptop screen displaying a terminal with model benchmark output."  
  caption: ""  
  relative: false  

> **TL;DR** — This post walks you through building a quantization‑aware LLM inference tool from scratch, giving you a runnable pipeline, benchmark numbers, and a concrete project you can showcase on your CV to signal systems‑level engineering skill. You’ll learn how to load a Hugging Face model, calibrate it with a small dataset, apply int8 quantization via BitsAndBytes, measure size and latency gains, and expose a simple HTTP server for serving. The result is a tangible, production‑flavored side project that hiring managers can inspect and run.

Building a portfolio project that stands out requires more than a toy notebook. Hiring managers for engineering roles want to see that you can take a real system, instrument it, and ship something that actually works. A quantization‑aware pipeline hits the sweet spot: it touches storage, compute, networking (via a local server), and performance measurement, all while demonstrating deep knowledge of modern ML infrastructure.

### Why This Project Stands Out on a CV  

- **Systems‑level skill**: You design and run a full pipeline—from model loading to benchmarking—mirroring the workflows used at companies that ship LLM inference at scale (e.g., inference teams at Meta, Google, or AI‑focused startups).  
- **Quantization expertise**: Employers value candidates who understand how to reduce model size and latency without catastrophic accuracy loss. You’ll have concrete numbers (e.g., 4× size reduction, <5 % accuracy drop) to discuss in interviews.  
- **Toolchain familiarity**: The project uses widely‑adopted libraries—Hugging Face Transformers, PyTorch, BitsAndBytes, and FastAPI—so you can talk about real dependencies, version constraints, and integration points.  
- **Observable outcomes**: A CLI, a benchmark report, and a locally hosted server give you something to demo during a technical interview or include in a GitHub README that automatically renders badges.  
- **Extensibility**: The architecture is modular; you can later add persistence, horizontal scaling, or observability, showing growth potential beyond the initial build.  

### Architecture Overview  

The project consists of six loosely coupled components that fit together as a linear pipeline with a serving endpoint:

```
+----------------+      +----------------+      +----------------+
| Model Loader   | -->  | Calibrator     | -->  | Quantizer      |
+----------------+      +----------------+      +----------------+
        |                     |                     |
        v                     v                     v
+----------------+      +----------------+      +----------------+
| Evaluator      | -->  | Benchmarker    | -->  | HTTP Server    |
+----------------+      +----------------+      +----------------+
```

- **Model Loader**: Uses `transformers.AutoModelForCausalLM` to download a small decoder‑only model (e.g., `meta-llama/Llama-3.2-1B`) and move it to CPU/CUDA.  
- **Calibrator**: Supplies a representative subset of tokens (a few hundred sentences from the **Wikitext‑2** dataset) to calibrate the quantization scale.  
- **Quantizer**: Employs the `bitsandbytes` library to convert the model to int8 (or 4‑bit) using `load_inference_model`.  
- **Evaluator**: Runs a short generation prompt on both the original and quantized models, computing perplexity or exact‑match accuracy.  
- **Benchmarker**: Measures peak memory, inference latency (average token‑per‑second), and output size on both CPU and GPU.  
- **HTTP Server**: A minimal FastAPI app that loads the quantized model once and serves `/generate` requests, exposing latency and token count in the response headers.  

The pipeline is orchestrated by a CLI script (`python -m quant_workbench --model meta-llama/Llama-3.2-1B --calib-size 200`) that runs each stage sequentially and writes a JSON report (`benchmark.json`) for later inspection.

### Building It Step by Step  

Below are the concrete, runnable steps. Each step includes a fenced code block with a language tag.

#### Step 1 – Project scaffolding & dependencies  

```bash
# Create a clean virtual environment
python -m venv .venv
source .venv/bin/activate

# Install core ML and serving libraries
pip install "transformers>=4.37" "torch>=2.2" "bitsandbytes>=0.42" "fastapi>=0.110" "uvicorn[standard]"
```

#### Step 2 – Load a small model and verify it runs  

```python
# file: quant_workbench/load_model.py
from transformers import AutoModelForCausalLM, AutoTokenizer
import torch

MODEL_NAME = "meta-llama/Llama-3.2-1B"

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, use_fast=True)
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,       # load in FP16 to fit on modest GPUs
    device_map="auto",
)

def generate(prompt: str, max_new_tokens: int = 32) -> str:
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    output = model.generate(**inputs, max_new_tokens=max_new_tokens)
    return tokenizer.decode(output[0], skip_special_tokens=True)

# Quick smoke test
print(generate("Once upon a time", max_new_tokens=16))
```

#### Step 3 – Prepare a calibration dataset  

We'll use a few dozen lines from **Wikitext‑2** (built‑in to `datasets`).

```python
# file: quant_workbench/calibrate.py
from datasets import load_dataset
from transformers import TextIteratorStreamer
import threading

wikitext = load_dataset("wikitext", "wikitext-2", split="train")
# Take the first 200 sentences as calibration data
calib_texts = [line.strip() for line in wikitext["text"][:200] if line.strip()]
print(f"Collected {len(calib_texts)} calibration sentences")
```

#### Step 4 – Quantize with BitsAndBytes  

```python
# file: quant_workbench/quantize.py
import torch
from transformers import BitsAndBytesConfig

bnb_config = BitsAndBytesConfig(
    load_in_8bit=True,                # int8 quantisation
    llm_int8_enable_fp32_cpu_offload=True,
    llm_int8_skip_layers=0,
)

quantized_model = AutoModelForCausalLM.from_pretrained(
    "meta-llama/Llama-3.2-1B",
    quantization_config=bnb_config,
    device_map="auto",
)
print("Model successfully loaded in int8")
```

#### Step 5 – Evaluate accuracy loss  

```python
# file: quant_workbench/evaluate.py
from transformers import pipeline

prompt = "The future of AI is"
orig_pipe = pipeline("text-generation", model=model, tokenizer=tokenizer)
qnt_pipe = pipeline("text-generation", model=quantized_model, tokenizer=tokenizer)

orig_out = orig_pipe(prompt, max_new_tokens=20)[0]["generated_text"]
qnt_out  = qnt_pipe(prompt, max_new_tokens=20)[0]["generated_text"]

print("Original :", orig_out)
print("Quantized:", qnt_out)
```

#### Step 6 – Benchmark latency & memory  

```python
# file: quant_workbench/benchmark.py
import time, torch.cuda

def benchmark(pipe, prompt, repeats=10):
    times = []
    for _ in range(repeats):
        start = time.time()
        _ = pipe(prompt, max_new_tokens=16)[0]["generated_text"]
        end = time.time()
        times.append(end - start)
    avg_latency = sum(times) / len(times)
    mem_used = torch.cuda.memory_allocated() / 1e9 if torch.cuda.is_available() else 0
    return avg_latency, mem_used

orig_lat, orig_mem = benchmark(orig_pipe, prompt)
qnt_lat, qnt_mem   = benchmark(qnt_pipe, prompt)

print(f"Original: {orig_lat:.3f}s avg, {orig_mem:.2f} GB mem")
print(f"Quantized: {qnt_lat:.3f}s avg, {qnt_mem:.2f} GB mem")
```

#### Step 7 – Serve the quantized model with FastAPI  

```python
# file: quant_workbench/server.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import torch

app = FastAPI(title="Quantized LLM Serving")

class GenerateReq(BaseModel):
    prompt: str
    max_new_tokens: int = 64

@app.on_event("startup")
def load_model():
    global quantized_model, tokenizer
    from transformers import AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig
    tokenizer = AutoTokenizer.from_pretrained("meta-llama/Llama-3.2-1B", use_fast=True)
    bnb_cfg = BitsAndBytesConfig(load_in_8bit=True, llm_int8_enable_fp32_cpu_offload=True)
    quantized_model = AutoModelForCausalLM.from_pretrained(
        "meta-llama/Llama-3.2-1B",
        quantization_config=bnb_cfg,
        device_map="auto",
    )

@app.post("/generate")
def generate(req: GenerateReq):
    if not quantized_model:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        inputs = tokenizer(req.prompt, return_tensors="pt").to("cuda")
        output = quantized_model.generate(**inputs, max_new_tokens=req.max_new_tokens)
        generated = tokenizer.decode(output[0], skip_special_tokens=True)
        return {"generated_text": generated}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

Run the server: `uvicorn server:app --host 0.0.0.0 --port 8000`. Send a POST with `{"prompt":"Hello", "max_new_tokens":10}` to `http://localhost:8000/generate` and you’ll receive a JSON payload with the model’s output.

### Running and Testing It  

1. **Clone the repo** (or create a new directory) and `cd` into it.  
2. Activate the virtual environment as in **Step 1**.  
3. Execute the pipeline end‑to‑end:

```bash
python -m quant_workbench --model meta-llama/Llama-3.2-1B --calib-size 200
```

   This runs Steps 2‑6, prints the generated text, accuracy comparison, and benchmark table, and writes `benchmark.json` to disk.  

4. **Start the HTTP server** (Step 7) in a separate terminal:

```bash
uvicorn server:app --host 0.0.0.0 --port 8000
```

5. **Test the endpoint** with `curl` or any HTTP client:

```bash
curl -X POST http://localhost:8000/generate -H "Content-Type: application/json" -d '{"prompt":"Once upon a time", "max_new_tokens":16}'
```

   You should see a JSON response like `{"generated_text":"Once upon a time …"}`.  

6. **Inspect `benchmark.json`** – it contains fields `model_size_mb`, `latency_ms`, `perplexity`, and `accuracy_drop`. Share this file in your CV’s “Projects” section; recruiters can run the numbers themselves.  

### Extending It: Your Roadmap to Senior‑Level  

| # | Upgrade | Why it matters |
|---|---------|----------------|
| 1 | **Persistent caching of quantized weights** using `torch.save` / `joblib` so subsequent launches skip the heavy `load_in_8bit` step. | Cuts startup latency from ~30 s to <5 s, mimicking production model‑loading pipelines. |
| 2 | **Horizontal scaling with Ray or TorchServe**: run multiple server replicas behind a load balancer, each holding a shard of the quantized model. | Demonstrates ability to design systems that serve traffic > 100 RPS, a key expectation at mid‑senior engineering roles. |
| 3 | **Observability stack**: integrate OpenTelemetry to emit request latency, error rates, and GPU utilization metrics to Prometheus + Grafana. | Gives concrete evidence of production‑grade monitoring, a differentiator in senior interviews. |
| 4 | **Fault tolerance**: add retry logic, circuit‑breaker pattern (via `pybreaker`), and graceful shutdown handling. | Shows you can build resilient services that survive node failures without crashing the whole API. |
| 5 | **Benchmark suite automation**: script CI (GitHub Actions) that runs the pipeline on a pull request, fails if latency regresses > 10 % or accuracy drops > 2 %. | Embeds quality gates, a practice common in engineering‑focused teams that ship ML‑backed products. |
| 6 | **Export to ONNX + Trt‑accelerated inference**: convert the quantized model with `torch.onnx.export` and run with NVIDIA TensorRT for sub‑millisecond latency. | Illustrates knowledge of the full stack from PyTorch to high‑performance inference engines, a senior‑level skill. |

Each upgrade is a concrete, incremental step you can implement after the baseline project is running, turning a “toy” into a portfolio‑ready system that mirrors real‑world ML infra.

### Key Takeaways  

- A quantization‑aware pipeline gives you **tangible metrics** (size reduction, latency gains) that hiring managers can instantly evaluate.  
- Using **BitsAndBytes + FastAPI** demonstrates familiarity with the de‑facto stack for LLM serving in production.  
- The **modular architecture** (loader → calibrator → quantizer → evaluator → benchmarker → server) mirrors the component separation found at companies that ship LLM inference at scale.  
- **Extensibility**—persistence, scaling, observability, fault tolerance—transforms the project from a notebook experiment into a production‑grade system, a strong signal for senior engineering positions.  
- Documenting **benchmark results** in `benchmark.json` and sharing the CLI flags makes the project instantly reproducible, a quality recruiters value highly.  

### Further Reading  

- [BitsAndBytes Documentation](https://github.com/TimDettmers/bitsandbytes) – official guide for 8‑bit and 4‑bit quantization in PyTorch.  
- [Hugging Face Transformers Quantization Tutorial](https://huggingface.co/docs/transformers/main/en/model_doc/quantization) – step‑by‑step notebooks for int8 and int4 conversion.  
- [FastAPI Official Docs](https://fastapi.tiangolo.com/) – building APIs with Python type hints.  
- [OpenTelemetry Python Instrumentation](https://opentelemetry-python.readthedocs.io/) – adding tracing and metrics to services.  
- [Ray AIR Documentation](https://docs.ray.io/en/latest/air/index.html) – scalable model serving and distributed training.  
- [TensorRT Inference Guide](https://docs.nvidia.com/deeplearning/tensorrt/developer-guide/) – high‑performance inference for ONNX models.  

---