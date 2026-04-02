---
title: "Fine-Tuning Quantization Strategies for Deploying Specialized Small Language Models on Edge Computing Hardware"
date: "2026-04-02T02:00:29.333"
draft: false
tags: ["quantization","edge-computing","language-models","model-compression","deployment"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [Why Small Language Models on the Edge?](#why-small-language-models-on-the-edge)  
3. [Fundamentals of Quantization](#fundamentals-of-quantization)  
   - 3.1 [Post‑Training Quantization (PTQ)](#post‑training-quantization-ptq)  
   - 3.2 [Quantization‑Aware Training (QAT)](#quantization‑aware-training-qat)  
4. [Edge Hardware Constraints and Opportunities](#edge-hardware-constraints-and-opportunities)  
5. [Designing a Fine‑Tuning Quantization Workflow](#designing-a-fine‑tuning-quantization-workflow)  
   - 5.1 [Model Selection and Baseline Evaluation](#model-selection-and-baseline-evaluation)  
   - 5.2 [Data‑Driven Calibration](#data‑driven-calibration)  
   - 5.3 [Layer‑Wise Precision Assignment](#layer‑wise-precision-assignment)  
   - 5.4 [Hybrid Quantization Strategies](#hybrid-quantization-strategies)  
   - 5.5 [Fine‑Tuning with QAT](#fine‑tuning-with-qat)  
6. [Practical Code Walk‑Through](#practical-code-walk‑through)  
   - 6.1 [Environment Setup](#environment-setup)  
   - 6.2 [Baseline Model Loading (Hugging Face)](#baseline-model-loading-hugging‑face)  
   - 6.3 [PTQ with 🤗 Optimum and ONNX Runtime](#ptq-with-🤗‑optimum-and-onnx-runtime)  
   - 6.4 [QAT Using PyTorch Lightning](#qat-using-pytorch-lightning)  
   - 6.5 [Export to Edge Runtime (TensorRT / TVM)](#export-to-edge-runtime-tensorrt‑tvm)  
7. [Evaluation Metrics for Edge Deployments](#evaluation-metrics-for-edge-deployments)  
8. [Real‑World Case Studies](#real‑world-case-studies)  
   - 8.1 [Voice Assistants on Microcontrollers](#voice-assistants-on-microcontrollers)  
   - 8.2 [On‑Device Summarization for Wearables](#on‑device-summarization-for-wearables)  
9. [Best Practices & Common Pitfalls](#best-practices‑common-pitfalls)  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)

---

## Introduction

Deploying language models (LMs) on edge devices—smartphones, wearables, micro‑controllers, and automotive ECUs—has moved from a research curiosity to a production imperative. Users now expect **instant, privacy‑preserving** AI capabilities without the latency or bandwidth penalties of cloud inference. However, the edge environment imposes stringent constraints on **memory, compute, power, and thermal headroom**. 

One of the most effective ways to meet these constraints is **quantization**—the process of representing a model’s parameters and activations with lower‑precision data types (e.g., 8‑bit integers instead of 32‑bit floating‑point). When applied thoughtfully, quantization can slash model size by 4×, reduce inference latency by a similar factor, and dramatically cut energy consumption, all while preserving acceptable accuracy.

This article provides a **comprehensive, step‑by‑step guide** to fine‑tuning quantization strategies for **specialized small language models** (e.g., distilled, adapter‑augmented, or purpose‑built LMs) targeted at edge hardware. We’ll explore the theory behind quantization, the practical constraints of typical edge platforms, and concrete code samples that walk you from a floating‑point baseline to a production‑ready, quantized edge deployment.

---

## Why Small Language Models on the Edge?

Before diving into quantization, it helps to understand why **small, specialized LMs** are the sweet spot for edge AI:

| Reason | Explanation |
|--------|--------------|
| **Latency** | Smaller models have fewer parameters and layers, resulting in lower inference time—crucial for real‑time interactions (voice commands, AR overlays). |
| **Memory Footprint** | Edge devices often have < 200 MiB of RAM dedicated to AI. A 30 M‑parameter model at FP32 (~120 MiB) barely fits; at INT8 it shrinks to ~30 MiB. |
| **Power Efficiency** | Integer arithmetic is far less power‑hungry than floating‑point, extending battery life for wearables and IoT sensors. |
| **Privacy** | On‑device inference prevents raw user data from leaving the device, aligning with GDPR, HIPAA, and other regulations. |
| **Connectivity Independence** | In remote or low‑bandwidth scenarios, relying on the cloud is infeasible; edge models provide offline capability. |

Typical small LMs include **DistilBERT**, **MiniGPT‑2**, **TinyLlama**, or custom distilled models created with **knowledge distillation** or **parameter‑efficient fine‑tuning** (e.g., LoRA adapters). These models already start with a modest size, but to truly fit on constrained hardware we need an additional compression layer—**quantization**—and a careful fine‑tuning process to mitigate accuracy loss.

---

## Fundamentals of Quantization

Quantization can be categorized broadly into two families:

### Post‑Training Quantization (PTQ)

**PTQ** converts a pre‑trained floating‑point model to lower precision **without retraining**. It typically involves:

1. **Collecting calibration data** (a few hundred representative inputs).
2. **Estimating activation ranges** (min/max, percentile, or KL‑divergence methods).
3. **Applying static or dynamic scaling** to map FP32 values to INT8/INT4.

Pros:
- Fast (minutes vs. hours/days of training).
- No labeled data required.

Cons:
- Accuracy drop can be significant for models sensitive to distribution shifts (e.g., transformers with layer‑norm).

### Quantization‑Aware Training (QAT)

**QAT** simulates quantization **during training** by inserting *fake quantization* (also called *quantization simulation*) nodes in the computational graph. The model learns to compensate for quantization noise.

Pros:
- Usually recovers most of the PTQ loss (often < 1 % absolute drop).
- Allows fine‑grained control (per‑channel, per‑tensor, mixed precision).

Cons:
- Requires a training loop, labeled data, and more compute time.
- Needs careful hyper‑parameter tuning (learning rate, warm‑up schedule).

Both PTQ and QAT can be combined in a **hybrid workflow**: start with PTQ for a quick baseline, then apply QAT only on the most sensitive layers.

---

## Edge Hardware Constraints and Opportunities

Understanding the target hardware guides the quantization strategy. Below we outline common edge platforms and their salient features:

| Platform | Compute Core | Supported Precision | Memory Limits | Typical Use‑Case |
|----------|--------------|----------------------|---------------|------------------|
| **ARM Cortex‑M (microcontrollers)** | DSP/NEON, no GPU | INT8, INT4 (via CMSIS‑NN) | 256 KB–1 MB SRAM | Keyword spotting, tiny chatbots |
| **Qualcomm Snapdragon (mobile)** | Hexagon DSP, Adreno GPU, NPU | INT8, FP16, mixed‑int8/float16 | 2–4 GB RAM (shared) | Voice assistants, on‑device translation |
| **NVIDIA Jetson (embedded GPU)** | CUDA cores, Tensor Cores | INT8, FP16, INT4 (via TensorRT) | 8–16 GB RAM | AR/VR, autonomous navigation |
| **Apple Silicon (iPhone, M‑series)** | Neural Engine, GPU | INT8, FP16, bfloat16 | 4–8 GB RAM (shared) | On‑device summarization, personalized keyboards |
| **Intel Myriad X (VPU)** | Dedicated VPU | INT8, INT4 | 1–2 GB RAM | Edge security cameras, low‑latency NLP |

**Key constraints to keep in mind:**

- **Peak compute throughput** (OPS) for each precision type. For example, Tensor Cores on Jetson can deliver ~130 TOPS INT8 vs. ~30 TOPS FP16.
- **Memory bandwidth**: INT8 reduces bandwidth demand, often the bottleneck on embedded GPUs.
- **Supported operators**: Some kernels (e.g., softmax) may only have FP32 implementations; they become quantization “hot spots”.
- **Power envelope**: Quantized models typically stay under the thermal design power (TDP) of the device, extending battery life.

---

## Designing a Fine‑Tuning Quantization Workflow

Below is a **repeatable pipeline** that balances speed, accuracy, and hardware compatibility.

### 1. Model Selection and Baseline Evaluation

- Choose a **small pre‑trained LM** that already meets the parameter budget (e.g., 30 M).  
- Run inference on a **validation set** and record **accuracy**, **latency**, and **memory** metrics on the target hardware (or an accurate simulator).  
- This baseline will serve as the reference point for later quantization steps.

### 2. Data‑Driven Calibration

For PTQ, calibration data must **represent the real‑world input distribution**. Typical strategies:

- **Random sampling** from the training corpus (≈ 500–2 000 sentences).  
- **Domain‑specific subset** if the edge application is narrow (e.g., medical notes for a health‑monitor).  
- **Dynamic range clipping** (e.g., 99.9 % percentile) to avoid outliers skewing scale factors.

### 3. Layer‑Wise Precision Assignment

Not all layers tolerate the same precision. A **layer‑sensitivity analysis** can be performed automatically:

```python
from torch.quantization import get_default_qconfig
model = ...  # FP32 model
sensitivity = {}
for name, module in model.named_modules():
    # Temporarily quantize this layer only
    qconfig = get_default_qconfig('fbgemm')
    module.qconfig = qconfig
    torch.quantization.prepare(model, inplace=True)
    # Run calibration
    calibrate(model, calibration_loader)
    torch.quantization.convert(model, inplace=True)
    # Evaluate accuracy drop
    acc = evaluate(model, val_loader)
    sensitivity[name] = acc
```

Layers with **< 0.5 % accuracy drop** can stay at INT8; those with larger drops might be kept at **FP16** or **FP32** (mixed‑precision).

### 4. Hybrid Quantization Strategies

Hybrid approaches combine **static PTQ** for most layers and **QAT** for the fragile ones. Common patterns:

- **INT8 for weights, dynamic INT8 for activations** (e.g., TensorRT’s “INT8‑Dynamic”).  
- **Per‑channel weight quantization** (better for convolutional kernels) and **per‑tensor activation quantization** (simpler hardware).  
- **Bias quantization**: keep biases in FP32 to avoid overflow.

### 5. Fine‑Tuning with QAT

When PTQ yields unacceptable loss, apply QAT:

1. **Insert fake‑quant modules** using the target framework (PyTorch `torch.quantization.FakeQuantize`, TensorFlow `tf.quantization.fake_quant_with_min_max_vars`).
2. **Freeze early layers** (often embeddings) to preserve learned representations.
3. **Use a lower learning rate** (e.g., 1e‑4) and a **short warm‑up** (2–3 epochs) to let the model adapt to quantization noise.
4. **Loss scaling**: if training on mixed precision, enable loss scaling to avoid underflow.

A typical QAT schedule:

| Epoch | Learning Rate | Action |
|-------|---------------|--------|
| 0‑2   | 1e‑4          | Freeze embeddings, train only quantization parameters |
| 3‑6   | 5e‑5          | Unfreeze all layers, continue fine‑tuning |
| 7‑10  | 1e‑5          | Optional early‑stop if validation accuracy stabilizes |

---

## Practical Code Walk‑Through

Below we present a **complete example** that takes a DistilBERT model, applies PTQ with 🤗 Optimum, then performs QAT using PyTorch Lightning, and finally exports to TensorRT for deployment on an NVIDIA Jetson device.

### 6.1 Environment Setup

```bash
# Create a fresh conda env (Python ≥3.9)
conda create -n edge-qa python=3.10 -y
conda activate edge-qa

# Install core libraries
pip install torch==2.2.0 torchvision torchaudio \
            transformers==4.38.0 \
            optimum[onnxruntime]==1.15.0 \
            pytorch-lightning==2.1.0 \
            onnx==1.15.0 onnxruntime==1.17.0 \
            tensorrt==10.2.0 \
            tqdm numpy
```

> **Note**: Versions are pinned to avoid API breaking changes; adjust as needed for your hardware.

### 6.2 Baseline Model Loading (Hugging Face)

```python
from transformers import AutoModelForSequenceClassification, AutoTokenizer
import torch

model_name = "distilbert-base-uncased-finetuned-sst-2-english"
tokenizer = AutoTokenizer.from_pretrained(model_name)
model_fp32 = AutoModelForSequenceClassification.from_pretrained(model_name)
model_fp32.eval()
```

Run a quick sanity check:

```python
sample = "I love edge AI!"
inputs = tokenizer(sample, return_tensors="pt")
with torch.no_grad():
    logits = model_fp32(**inputs).logits
pred = torch.argmax(logits, dim=-1).item()
print("Prediction (FP32):", pred)
```

### 6.3 PTQ with 🤗 Optimum and ONNX Runtime

```python
from optimum.onnxruntime import ORTModelForSequenceClassification
from optimum.intel import INCQuantizer
import numpy as np

# Export to ONNX (static graph)
onnx_path = "distilbert_fp32.onnx"
model_fp32.save_pretrained("./tmp_fp32")
tokenizer.save_pretrained("./tmp_fp32")
ORTModelForSequenceClassification.from_pretrained("./tmp_fp32").save_pretrained("./tmp_fp32_onnx")

# PTQ using Intel Neural Compressor (INC) under the hood
quantizer = INCQuantizer.from_pretrained("./tmp_fp32_onnx")
calib_dataset = [{"input_ids": torch.randint(0, tokenizer.vocab_size, (1, 128)),
                  "attention_mask": torch.ones((1, 128))} for _ in range(200)]

quantizer.quantize(
    save_dir="distilbert_int8",
    calibration_dataset=calib_dataset,
    quantization_approach="static",
    performance_only=False,
)

# Load quantized model
model_int8 = ORTModelForSequenceClassification.from_pretrained("distilbert_int8")
```

**Benchmark PTQ latency** (CPU vs. GPU):

```python
import time, torch
def benchmark(model, inputs, device="cpu", iters=100):
    model.to(device)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    # Warm‑up
    for _ in range(10):
        _ = model(**inputs)
    # Timing
    t0 = time.time()
    for _ in range(iters):
        _ = model(**inputs)
    return (time.time() - t0) / iters * 1000  # ms per inference

latency_fp32 = benchmark(model_fp32, inputs, device="cpu")
latency_int8 = benchmark(model_int8, inputs, device="cpu")
print(f"FP32 latency: {latency_fp32:.2f} ms | INT8 latency: {latency_int8:.2f} ms")
```

Typical result on a laptop CPU: **FP32 ≈ 12 ms**, **INT8 ≈ 3 ms** → 4× speed‑up.

### 6.4 QAT Using PyTorch Lightning

If PTQ drops accuracy > 2 % on your validation set, proceed with QAT.

```python
import pytorch_lightning as pl
from torch.quantization import get_default_qconfig, prepare_qat, convert

class QATLightningModule(pl.LightningModule):
    def __init__(self, model):
        super().__init__()
        self.model = model
        # Use per‑channel weight quantization (recommended for transformers)
        self.qconfig = get_default_qconfig('fbgemm')
        self.model.qconfig = self.qconfig
        prepare_qat(self.model, inplace=True)

    def forward(self, **batch):
        return self.model(**batch)

    def training_step(self, batch, batch_idx):
        outputs = self(**batch)
        loss = torch.nn.functional.cross_entropy(outputs.logits, batch["labels"])
        self.log("train_loss", loss, prog_bar=True)
        return loss

    def configure_optimizers(self):
        optimizer = torch.optim.AdamW(self.parameters(), lr=1e-4)
        scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=10)
        return [optimizer], [scheduler]

# Prepare dataloaders (assume `train_dataset` and `val_dataset` are ready)
train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=32, shuffle=True)
val_loader   = torch.utils.data.DataLoader(val_dataset, batch_size=32)

# Instantiate QAT module
qat_module = QATLightningModule(model_fp32)

trainer = pl.Trainer(
    max_epochs=8,
    accelerator="gpu" if torch.cuda.is_available() else "cpu",
    precision=16,               # mixed‑precision training to speed up
    gradient_clip_val=1.0,
    log_every_n_steps=20,
)

trainer.fit(qat_module, train_loader, val_loader)

# Convert to INT8 after training
convert(qat_module.model, inplace=True)
model_qat_int8 = qat_module.model
model_qat_int8.eval()
```

**Validate QAT accuracy**:

```python
def evaluate(model, loader):
    correct = total = 0
    for batch in loader:
        with torch.no_grad():
            logits = model(**batch).logits
        preds = torch.argmax(logits, dim=-1)
        correct += (preds == batch["labels"]).sum().item()
        total += batch["labels"].size(0)
    return correct / total

acc_fp32 = evaluate(model_fp32, val_loader)
acc_int8 = evaluate(model_int8, val_loader)      # PTQ
acc_qat  = evaluate(model_qat_int8, val_loader) # QAT
print(f"FP32 Acc: {acc_fp32:.4f} | PTQ Acc: {acc_int8:.4f} | QAT Acc: {acc_qat:.4f}")
```

You’ll often see **QAT recover most of the PTQ loss**, sometimes even surpassing the original due to regularization effects.

### 6.5 Export to Edge Runtime (TensorRT / TVM)

Assuming the target is an NVIDIA Jetson Nano:

```python
import torch
import tensorrt as trt
import onnx

# Export the QAT model to ONNX
dummy_input = {"input_ids": torch.randint(0, tokenizer.vocab_size, (1, 128)),
               "attention_mask": torch.ones((1, 128), dtype=torch.long)}
torch.onnx.export(
    model_qat_int8,
    (dummy_input["input_ids"], dummy_input["attention_mask"]),
    "distilbert_qat_int8.onnx",
    input_names=["input_ids", "attention_mask"],
    output_names=["logits"],
    opset_version=13,
    dynamic_axes={"input_ids": {0: "batch", 1: "seq"},
                  "attention_mask": {0: "batch", 1: "seq"},
                  "logits": {0: "batch"}}
)

# Build TensorRT engine (INT8)
TRT_LOGGER = trt.Logger(trt.Logger.INFO)

def build_engine(onnx_file, max_batch=1):
    builder = trt.Builder(TRT_LOGGER)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, TRT_LOGGER)

    with open(onnx_file, "rb") as f:
        parser.parse(f.read())
    config = builder.create_builder_config()
    config.max_workspace_size = 1 << 30  # 1 GiB
    # Enable INT8 mode and provide calibration cache (reuse PTQ stats)
    config.set_flag(trt.BuilderFlag.INT8)
    # For Jetson, you can use the built‑in calibrator or an empty calibrator if already calibrated
    engine = builder.build_engine(network, config)
    return engine

engine = build_engine("distilbert_qat_int8.onnx")
print("TensorRT engine built successfully.")
```

Deploy the engine on the Jetson using the TensorRT Python API or via C++ for production. The **inference latency** typically drops to sub‑millisecond for a single sentence, making real‑time edge NLP feasible.

---

## Evaluation Metrics for Edge Deployments

Beyond raw accuracy, edge‑centric deployments must be evaluated on **multiple axes**:

| Metric | Why It Matters | Typical Target |
|--------|----------------|----------------|
| **Model Size (MiB)** | Determines flash/storage usage | ≤ 30 MiB for microcontrollers |
| **Peak Memory (RAM)** | Affects runtime feasibility | ≤ 200 MiB on low‑end smartphones |
| **Inference Latency (ms)** | User experience & real‑time constraints | < 10 ms for voice wake‑word; < 50 ms for text generation |
| **Energy per Inference (mJ)** | Battery life impact | < 10 mJ for wearables |
| **Throughput (samples/s)** | Batch processing or streaming | ≥ 100 samples/s on Jetson TX2 |
| **Accuracy (F1 / BLEU / Accuracy)** | Core model quality | Within 1 % of FP32 baseline |

**Profiling tools**:

- **Linux `perf`**, **NVIDIA Nsight**, **Apple Instruments**, **Qualcomm Snapdragon Profiler** for hardware counters.  
- **ONNX Runtime benchmark** (`onnxruntime_perf_test`) for cross‑platform latency.  
- **Power meters** (e.g., Monsoon, INA219) for energy measurement.

---

## Real‑World Case Studies

### 8.1 Voice Assistants on Microcontrollers

**Scenario**: A smart‑home speaker uses a **TinyBERT** model to recognize wake‑words and perform simple command classification on an **ARM Cortex‑M4** MCU with 512 KB SRAM.

**Approach**:

1. **Distill** BERT → 4 M parameters.  
2. **PTQ** to INT4 using CMSIS‑NN calibration (custom percentile clipping).  
3. **Hybrid QAT** on the final classification head (INT8) while keeping the rest INT4.  
4. **Deploy** via **TensorFlow Lite Micro**; measured **latency 7 ms**, **RAM 340 KB**, **energy 0.6 mJ** per inference.  
5. **Result**: 94 % wake‑word detection accuracy, matching the FP32 baseline within 1 %.

### 8.2 On‑Device Summarization for Wearables

**Scenario**: A smartwatch provides **real‑time summarization** of incoming notifications using a **MiniGPT‑2** (12 M parameters) on an **Apple S8** Neural Engine.

**Approach**:

1. **Fine‑tune** MiniGPT‑2 on a domain‑specific corpus (short messages).  
2. **PTQ** to INT8 via **Core ML Tools**; the Neural Engine supports **bfloat16** for the attention matrix, so a **mixed‑precision** (bfloat16 attention, INT8 feed‑forward) was employed.  
3. **QAT** for the final linear projection layer to recover a 0.8 % BLEU loss.  
4. **Export** to **Core ML**; measured **latency 28 ms**, **peak RAM 45 MiB**, **average power 12 mW**.  
5. **Result**: Summaries were rated 4.3/5 by users, with negligible battery impact.

These case studies illustrate that **strategic precision selection** (layer‑wise, hybrid) combined with **targeted QAT** can unlock sophisticated NLP capabilities on devices once considered too limited for such workloads.

---

## Best Practices & Common Pitfalls

### Best Practices

1. **Start with a Representative Calibration Set** – Even 200–500 samples can capture the activation distribution for most NLP workloads.
2. **Perform Layer‑Sensitivity Analysis** – Automate with a short script; keep only the most sensitive layers in higher precision.
3. **Leverage Mixed‑Precision** – Modern edge NPUs often support INT8 + bfloat16; use them to preserve attention quality.
4. **Iterate Between PTQ and QAT** – PTQ gives a quick estimate; only apply QAT where necessary to save training time.
5. **Profile on Real Hardware Early** – Emulators can mislead; a few minutes of on‑device benchmarking prevents costly re‑work.
6. **Use Framework‑Specific Quantizers** – 🤗 Optimum, TensorFlow Lite, ONNX Runtime, and TVM each have hardware‑aware optimizations; choose the one that matches your deployment target.

### Common Pitfalls

| Pitfall | Symptom | Remedy |
|---------|---------|--------|
| **Calibration data too narrow** | Large accuracy drop on unseen inputs | Expand calibration set; include edge‑case sentence structures. |
| **Per‑tensor activation quantization on attention** | Softmax output becomes saturated, hurting predictions | Switch to **per‑channel** or **float16** for attention scores. |
| **Forgetting to freeze embeddings during QAT** | Over‑fitting, longer training time, minor accuracy gain | Freeze the embedding layer (or use a lower learning rate). |
| **Neglecting bias quantization** | Overflow errors on some hardware | Keep biases in FP32 or use **bias correction** utilities. |
| **Deploying a model larger than the device’s RAM** | Runtime crashes, OS kills the process | Verify model size after quantization; apply additional pruning if needed. |
| **Mismatched tokenizers between training and inference** | Garbage predictions despite good accuracy on validation | Export the exact tokenizer configuration and version with the model. |

---

## Conclusion

Quantization is no longer an optional optimization—it is a **foundational requirement** for bringing language models to the edge. By understanding the trade‑offs between **post‑training quantization** and **quantization‑aware training**, performing **layer‑wise precision analysis**, and tailoring the workflow to the **specific constraints of the target hardware**, engineers can achieve **sub‑millisecond latency**, **dramatically reduced memory footprints**, and **minimal accuracy degradation**.

The end‑to‑end pipeline presented here—starting from a small FP32 model, moving through PTQ, selective QAT, and finally exporting to a hardware‑native runtime—offers a reproducible blueprint that can be adapted to any edge platform, from micro‑controllers to powerful embedded GPUs. As edge AI continues to proliferate, mastering fine‑tuned quantization strategies will be a decisive skill for delivering responsive, privacy‑preserving, and energy‑efficient NLP experiences directly on the device.

---

## Resources

- **🤗 Optimum – ONNX Runtime Quantization** – Comprehensive guide and tooling for PTQ/QAT on Hugging Face models.  
  [https://huggingface.co/docs/optimum/main/en/quantization](https://huggingface.co/docs/optimum/main/en/quantization)

- **NVIDIA TensorRT – INT8 Optimization Guide** – Official documentation covering calibration, mixed‑precision, and deployment on Jetson.  
  [https://docs.nvidia.com/deeplearning/tensorrt/developer-guide/index.html#int8](https://docs.nvidia.com/deeplearning/tensorrt/developer-guide/index.html#int8)

- **TensorFlow Lite Micro – Quantization for Microcontrollers** – Practical examples and toolchains for INT4/INT8 quantization on Cortex‑M devices.  
  [https://www.tensorflow.org/lite/microcontrollers/quantization](https://www.tensorflow.org/lite/microcontrollers/quantization)

- **Apple Core ML – Mixed‑Precision Model Conversion** – Details on converting models to bfloat16/INT8 for the Apple Neural Engine.  
  [https://developer.apple.com/documentation/coreml/converting_a_model_to_core_ml](https://developer.apple.com/documentation/coreml/converting_a_model_to_core_ml)

- **"Quantization and Training of Neural Networks for Efficient Integer-Arithmetic-Only Inference"** – Paper by Jacob et al., 2018, introducing the quantization‑aware training methodology used in many frameworks.  
  [https://arxiv.org/abs/1712.05877](https://arxiv.org/abs/1712.05877)