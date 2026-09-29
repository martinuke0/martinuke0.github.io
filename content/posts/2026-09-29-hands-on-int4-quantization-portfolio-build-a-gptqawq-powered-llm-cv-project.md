---
title: "Hands-On Int4 Quantization Portfolio: Build a GPTQ/AWQ-Powered LLM CV Project"
date: "2026-09-29T08:01:48.474"
draft: false
tags: ["quantization", "gptq", "awq", "cv", "side-project"]
description: "A practical guide to building an int4-quantized LLM inference side project using GPTQ and AWQ, showcasing real systems skills for engineers."
summary: "Learn how to quantize a language model to int4, integrate GPTQ and AWQ, and ship a runnable CV project that impresses hiring managers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-29-hands-on-int4-quantization-portfolio-build-a-gptqawq-powered-llm-cv-project.svg"
  alt: "Int4-quantized language model on a laptop"
  caption: ""
  relative: false
---

> **TL;DR** — You’ll quantize a LLM to int4 using GPTQ and AWQ, package a minimal Python demo, and end up with a tangible CV piece that signals production‑grade quantization know‑how to hiring managers. The guide walks through installing dependencies, running the quantization scripts, and testing inference locally. By the end you have a runnable side project that demonstrates low‑latency inference, model‑size reduction, and real‑world engineering patterns.

A short introduction: This post is a hands‑on build guide for a portfolio‑ready side project. You’ll take a small open‑source language model, quantize it to 4‑bit (int4) with the GPTQ and AWQ algorithms, and expose a simple CLI that runs inference. The result is a lightweight, fast model you can demo in interviews, point to on GitHub, and discuss the engineering trade‑offs you made along the way. It’s concrete, runnable, and directly showcases skills that hiring managers for ML‑focused engineering roles look for.

## Why This Project Stands Out on a CV

- **Model optimization skill** – You prove you can reduce a 7 B parameter model to ~4 GB while preserving > 85 % of original accuracy, a concrete metric interviewers can quiz you on.  
- **Familiarity with production quantization pipelines** – GPTQ (weight‑only, post‑training) and AWQ (activation‑aware) are the two dominant open‑source methods; knowing both shows you can choose the right tool for latency vs. fidelity.  
- **Systems‑level engineering** – Writing the quantization script, converting formats, and building a CLI forces you to handle file I/O, memory mapping, and Python packaging—exactly the kind of glue‑code work senior engineers do.  
- **Visible, runnable artifact** – A GitHub repo with a `demo.py` that prints a sentence in under 200 ms on a laptop is a concrete piece you can share, far more compelling than a theoretical write‑up.  
- **Roles it signals for** – ML Systems Engineer, Inference Engineer, Generative AI Research Engineer, and any position where you’ll ship low‑latency model serving on constrained hardware.

## Architecture Overview

The project consists of four loosely coupled components:

- **Model source** – a small Hugging Face transformer (e.g., `facebook/opt-350m` or `meta-llama/Llama-2-7b-hf`).  
- **GPTQ quantizer** – a script that reads the FP16 model, groups weights, and writes a INT4 sparse weight file (`*.safetensors`).  
- **AWQ converter** – takes the GPTQ output and applies activation‑aware scaling, producing an AWQ‑compatible checkpoint.  
- **Inference wrapper** – a minimal Python module that loads the AWQ checkpoint, runs a `generate()` call, and prints the result via a CLI.

```
model (FP16)
   │
   ├─► gptq_quantize.py  ──► int4 weight file
   │
   └─► awq_convert.py    ──► awq checkpoint
                         │
                         └─► inference_demo.py  ──► CLI output
```

The diagram emphasizes that the heavy lifting (quantization) happens once, after which the lightweight AWQ checkpoint can be swapped in any serving pipeline that supports AWQ (e.g., `vLLM`, `text-generation-inference`).

## Building It Step by Step

Below are the concrete, language‑tagged code snippets you can copy‑paste. They assume a Unix‑like shell and Python 3.10+.

### 0. Create a clean environment

```bash
# bash
python -m venv .quant-cv
source .quant-cv/bin/activate
pip install --upgrade pip
pip install auto-gptq auto-awq transformers tqdm
```

### 1. Pick a model small enough for a laptop

```python
# python – model_selection.py
from transformers import AutoModelForCausalLM, AutoTokenizer

model_id = "facebook/opt-350m"          # 350 M params → ~1 GB FP16
model = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype="float16")
tokenizer = AutoTokenizer.from_pretrained(model_id)
model.save_pretrained("opt-350m-fp16")
print("Saved FP16 model to ./opt-350m-fp16")
```

### 2. GPTQ int4 quantization

```python
# python – gptq_quantize.py
from auto_gptq import AutoGPTQQuantizer

quantizer = AutoGPTQQuantizer.from_pretrained(
    model_id="facebook/opt-350m",
    quantize_config_dict={"bits": 4, "group_size": 128}
)
quantizer.save_quantized("./opt-350m-gptq-int4")
print("GPTQ int4 model saved to ./opt-350m-gptq-int4")
```

*Why it matters*: GPTQ performs weight‑only quantization, which is fast to run and produces a compact `.safetensors` file ideal for side‑project distribution.

### 3. AWQ activation‑aware conversion

```python
# python – awq_convert.py
from auto_awq import AWQQuantizer

awq_quantizer = AWQQuantizer.from_pretrained(
    model_type="opt",
    model_path="./opt-350m-gptq-int4",
    quant_config={"bits": 4, "group_size": 128}
)
awq_quantizer.save_quantized("./opt-350m-awq-int4")
print("AWQ int4 model saved to ./opt-350m-awq-int4")
```

*Why it matters*: AWQ adds activation‑aware scaling, typically recovering a few percentage points of perplexity loss while keeping the same int4 footprint.

### 4. Minimal inference demo

```python
# python – inference_demo.py
import torch
from auto_awq import AWQForCausalLM
from transformers import AutoTokenizer

model_path = "./opt-350m-awq-int4"
model = AWQForCausalLM.from_pretrained(model_path, device_map="cpu")
tokenizer = AutoTokenizer.from_pretrained(model_path)

prompt = "Write a short tagline for a data‑engineer portfolio."
inputs = tokenizer(prompt, return_tensors="pt")
output = model.generate(**inputs, max_new_tokens=30)
print(tokenizer.decode(output[0], skip_special_tokens=True))
```

Run it with:

```bash
python inference_demo.py
# Expected output (example):
# Write a short tagline for a data‑engineer portfolio: "Turning data into decisions, one pipeline at a time."
```

### 5. Package as a reusable CLI (optional)

```python
# python – cli.py  (uses argparse)
import argparse
from inference_demo import model, tokenizer

parser = argparse.ArgumentParser(description="Run AWQ‑quantized LLM demo")
parser.add_argument("--prompt", type=str, default="Explain int4 quantization in one sentence.")
args = parser.parse_args()

inputs = tokenizer(args.prompt, return_tensors="pt")
output = model.generate(**inputs, max_new_tokens=30)
print(tokenizer.decode(output[0], skip_special_tokens=True))
```

Now you have a **run‑once** quantization pipeline and a **run‑anywhere** inference binary—exactly the kind of end‑to‑end project hiring managers love to see on a CV.

## Running and Testing It

1. **Verify the quantization** – After step 2, inspect the file size:

   ```bash
   ls -lh opt-350m-gptq-int4/*.safetensors
   # Should be ~4 GB for a 350 M model (vs ~2 GB FP16)
   ```

2. **Confirm inference correctness** – Run `python inference_demo.py` and check that the generated text matches the prompt style. A quick sanity check is to compare perplexity on a held‑out token sequence against the original FP16 model (you should see a modest increase, e.g., 1.15×).

3. **Benchmark latency** – On a typical laptop CPU (no GPU), measure time‑to‑first‑token:

   ```bash
   python -c "
   import time, torch
   from auto_awq import AWQForCausalLM
   from transformers import AutoTokenizer
   model = AWQForCausalLM.from_pretrained('./opt-350m-awq-int4', device_map='cpu')
   tok = AutoTokenizer.from_pretrained('./opt-350m-awq-int4')
   prompt = 'Hello world'
   inputs = tok(prompt, return_tensors='pt')
   t0 = time.time()
   _ = model.generate(**inputs, max_new_tokens=10)
   print('Latency:', time.time() - t0, 's')
   "
   # Typical result: ~0.12 s on a 2020‑era CPU, well under the 200 ms threshold many interviewers ask about.
   ```

If the latency is higher, you can toggle `device_map="auto"` to offload to a integrated GPU, or reduce `group_size` in the quantizer config.

## Extending It: Your Roadmap to Senior‑Level

1. **Persisted cache with `torch.compile`** – Compile the inference function (`torch.compile(model)`) to fuse kernels and cut latency by ~30 %. *Matters: real‑world serving pipelines spend heavy effort on kernel fusion.*

2. **Horizontal scaling via FastAPI + uvicorn** – Wrap `inference_demo.py` in an async endpoint (`/generate`) and run multiple workers behind a load balancer. *Matters: hiring managers want to see you can move from a single‑process script to a production API.*

3. **Observability with OpenTelemetry** – Export request latency, token count, and model version as OTLP metrics; feed them into Grafana. *Matters: quantized models can behave differently under load; observability catches regressions early.*

4. **Fault tolerance with retry & circuit‑breaker** – Use `tenacity` for exponential back‑off on `model.generate()` and a simple circuit‑breaker to fallback to a less‑quantized model on repeated failures. *Matters: production systems must degrade gracefully rather than crash.*

5. **Benchmarking against `mlperf inference` suite** – Run the official MLPerf Tiny benchmarks on your quantized model and publish the results (throughput, latency). *Matters: concrete benchmark numbers give you credibility when discussing performance trade‑offs.*

6. **Model versioning & DVC integration** – Track the int4 checkpoint, quantization config, and source code with Data Version Control (DVC) so you can reproduce the exact model later. *Matters: reproducibility is a core expectation for senior engineers working on ML pipelines.*

Each upgrade adds a tangible, resume‑worthy skill while keeping the core project functional.

## Key Takeaways

- Quantizing a LLM to int4 with GPTQ and AWQ is a repeatable, script‑able process that fits on a laptop.  
- The resulting AWQ checkpoint is small (~4 GB for a 350 M model) and runs inference in under 200 ms on CPU.  
- Building the full pipeline—from model download → quantization → conversion → CLI demo—demonstrates systems‑level engineering (I/O, packaging, packaging, packaging).  
- The project signals to hiring managers that you can optimize models, choose the right algorithm for the job, and ship production‑ready code.  
- Extending the project with caching, API layering, observability, fault tolerance, benchmarking, and versioning transforms a toy into a senior‑level portfolio piece.  
- Real‑world tools (`auto-gptq`, `auto-awq`, `transformers`, `fastapi`, `open‑telemetry`) are the exact stack you’ll encounter in ML‑focused engineering roles.

## Further Reading

- [GPTQ: Post‑Training Quantization for LLMs](https://github.com/qwopqwopqwop/GPTQ) – the original GPTQ implementation and configuration guide.  
- [AWQ: Activation‑aware Quantization for LLMs](https://github.com/mit-han-lab/awq) – code and paper (arXiv:2305.18552) describing the activation‑aware scaling technique.  
- [AutoGPTQ Documentation](https://github.com/PanQiWei/AutoGPTQ#readme) – API reference for the `AutoGPTQQuantizer` used in the guide.  
- [Hugging Face Transformers – Quantization](https://huggingface.co/docs/transformers/main/en/model_doc/quantization) – overview of supported quantization methods and integration tips.  
- [arXiv:2305.18552 – AWQ: Activation‑aware Quantization for LLM](https://arxiv.org/abs/2305.18552) – the primary research paper that introduced the AWQ algorithm.  

---