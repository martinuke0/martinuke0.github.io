---
title: "Mastering Edge AI: Zero‑to‑Hero Guide with TinyML and Hardware Acceleration"
date: "2026-03-08T02:00:25.625"
draft: false
tags: ["Edge AI", "TinyML", "Hardware Acceleration", "Microcontrollers", "Machine Learning"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is Edge AI and Why TinyML Matters?](#what-is-edge-ai-and-why-tinyml-matters)  
3. [Core Concepts of TinyML](#core-concepts-of-tinyml)  
   - 3.1 [Model Size and Quantization](#model-size-and-quantization)  
   - 3.2 [Memory Footprint & Latency](#memory-footprint--latency)  
4. [Choosing the Right Hardware](#choosing-the-right-hardware)  
   - 4.1 [Microcontrollers (MCUs)](#microcontrollers-mcus)  
   - 4.2 [Hardware Accelerators](#hardware-accelerators)  
5. [Setting Up the Development Environment](#setting-up-the-development-environment)  
6. [Building a TinyML Model from Scratch](#building-a-tinyml-model-from-scratch)  
   - 6.1 [Data Collection & Pre‑processing](#data-collection--pre‑processing)  
   - 6.2 [Model Architecture Selection](#model-architecture-selection)  
   - 6.3 [Training and Quantization](#training-and-quantization)  
7. [Deploying to an MCU with TensorFlow Lite for Microcontrollers](#deploying-to-an-mcu-with-tensorflow-lite-for-microcontrollers)  
   - 7.1 [Generating the C++ Model Blob](#generating-the-cpp-model-blob)  
   - 7.2 [Writing the Inference Code](#writing-the-inference-code)  
8. [Leveraging Hardware Acceleration](#leveraging-hardware-acceleration)  
   - 8.1 [Google Edge TPU](#google-edge-tpu)  
   - 8.2 [Arm Ethos‑U NPU](#arm-ethos‑u-npu)  
   - 8.3 [DSP‑Based Acceleration (e.g., ESP‑DSP)](#dsp‑based-acceleration)  
9. [Real‑World Use Cases](#real‑world-use-cases)  
10. [Performance Optimization Tips](#performance-optimization-tips)  
11. [Debugging, Profiling, and Validation](#debugging‑profiling‑and-validation)  
12. [Future Trends in Edge AI & TinyML](#future-trends-in-edge-ai‑tinyml)  
13. [Conclusion](#conclusion)  
14. [Resources](#resources)  

---  

## Introduction  

Edge AI is rapidly reshaping how we think about intelligent systems. Instead of sending raw sensor data to a cloud server for inference, modern devices can **run machine‑learning (ML) models locally**, delivering sub‑second responses, preserving privacy, and dramatically reducing bandwidth costs.  

The **TinyML** movement brings this vision to the most constrained devices—microcontrollers (MCUs) with just a few kilobytes of RAM and modest clock speeds. By marrying **tiny neural networks** with **hardware acceleration** (Edge TPUs, NPUs, DSPs), developers can achieve impressive performance while staying within the tight power budgets required for battery‑operated or energy‑harvesting applications.

This guide aims to take you from **zero knowledge** of Edge AI to a **heroic level of competence**: you’ll understand the theory, select appropriate hardware, train a model, quantize it, deploy it, and finally squeeze out every ounce of performance with hardware accelerators. All examples are concrete, reproducible, and designed for a hands‑on learning experience.

---

## What Is Edge AI and Why TinyML Matters?  

**Edge AI** refers to the execution of AI algorithms on devices situated at the “edge” of a network—smartphones, wearables, industrial sensors, drones, and even tiny IoT nodes. The benefits are threefold:

1. **Latency:** Inference happens locally, often within milliseconds, enabling real‑time control loops (e.g., obstacle avoidance on a drone).  
2. **Privacy & Security:** Sensitive data never leaves the device, reducing exposure to network attacks.  
3. **Bandwidth & Cost:** No need to stream high‑volume sensor data to the cloud, saving on data plans and server costs.

**TinyML** is the sub‑discipline that makes Edge AI feasible on *resource‑constrained* hardware. While traditional deep learning models may require megabytes of storage and gigaflops of compute, TinyML models can fit into **<100 KB** of flash and run on **<10 KB** of RAM.  

> **Note**  
> TinyML does not imply “low accuracy.” With clever architecture design, quantization‑aware training, and hardware‑specific optimizations, TinyML models can achieve **near‑state‑of‑the‑art** performance on tasks like keyword spotting, vibration anomaly detection, and simple image classification.

---

## Core Concepts of TinyML  

### Model Size and Quantization  

The most powerful tool for shrinking a model is **quantization**—converting 32‑bit floating‑point weights and activations to lower‑precision formats (8‑bit integer, 16‑bit float, or even binary).  

* **Post‑Training Quantization (PTQ):** Fast, performed after training. Works well when the dataset is representative.  
* **Quantization‑Aware Training (QAT):** Simulates quantization during training, yielding higher accuracy for aggressive precision reductions.

### Memory Footprint & Latency  

Two metrics dominate TinyML design:

| Metric | Why It Matters | Typical Target (Tiny Devices) |
|--------|----------------|------------------------------|
| **Flash (Program) Size** | Determines if the model fits on the MCU’s non‑volatile storage. | < 200 KB |
| **RAM (Working Memory)** | Holds activations, input buffers, and runtime stack. | < 30 KB |
| **Inference Latency** | Impacts real‑time responsiveness. | ≤ 50 ms for most audio/vision tasks |

Balancing these constraints often requires **model pruning**, **depthwise separable convolutions**, and **compact architectures** such as MobileNet‑V1/V2, EfficientNet‑B0, or custom MLPs.

---

## Choosing the Right Hardware  

### Microcontrollers (MCUs)  

| MCU | CPU | Flash | RAM | Typical Power | Ideal Use‑Case |
|-----|-----|-------|-----|---------------|----------------|
| **Arduino Nano 33 BLE** | Arm Cortex‑M4F @ 64 MHz | 1 MB | 256 KB | ~5 mA (idle) | Simple audio keyword spotting |
| **ESP‑32‑S3** | Xtensa LX7 Dual‑core @ 240 MHz | 4 MB | 520 KB | ~10 mA (Wi‑Fi off) | Wi‑Fi enabled sensor nodes |
| **STM32H7** | Arm Cortex‑M7 @ 480 MHz | 2 MB | 1 MB | ~30 mA | More demanding vision pipelines |

When you need **hardware acceleration**, you look beyond the core CPU.

### Hardware Accelerators  

| Accelerator | Architecture | Peak Compute | Interface | Toolchain |
|-------------|--------------|--------------|-----------|-----------|
| **Google Edge TPU** | ASIC, 8‑bit integer | 4 TOPS | USB, PCIe, M.2 | TensorFlow Lite (Edge TPU Compiler) |
| **Arm Ethos‑U55** | NPU, 8‑bit integer | 2 TOPS | SPI, I2C, MIPI | Arm NN, TensorFlow Lite for Microcontrollers |
| **Kendryte K210** | RISC‑V + KPU (CNN accelerator) | 0.5 TOPS | SPI, UART | MaixPy, TensorFlow Lite |
| **ESP‑DSP (ESP‑32)** | SIMD DSP extensions | ~0.5 GFLOPS | Integrated | ESP‑IDF, ESP‑DSP library |

Choosing an accelerator depends on **availability**, **software support**, and **power envelope**. For hobbyists, the **Coral USB Accelerator** (Edge TPU) offers a plug‑and‑play experience. For production, an **Arm Ethos‑U**‑based MCU (e.g., NXP i.MX RT600) provides a tighter integration.

---

## Setting Up the Development Environment  

Below is a quick checklist for a **Linux/macOS** workstation (the steps are similar on Windows with WSL2).  

1. **Install Python 3.10+**  
   ```bash
   sudo apt-get install python3-pip python3-venv   # Ubuntu/Debian
   # or brew install python@3.10                 # macOS
   ```

2. **Create a virtual environment**  
   ```bash
   python3 -m venv tinyml-env
   source tinyml-env/bin/activate
   ```

3. **Install TensorFlow and TFLite tools**  
   ```bash
   pip install --upgrade pip
   pip install tensorflow==2.16.0 tflite-support==0.4.2
   ```

4. **Install Edge TPU compiler (optional)**  
   ```bash
   echo "deb https://packages.cloud.google.com/apt coral-edgetpu-stable main" | sudo tee /etc/apt/sources.list.d/coral-edgetpu.list
   curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
   sudo apt-get update
   sudo apt-get install edgetpu-compiler
   ```

5. **Set up MCU toolchains**  
   * **Arduino CLI** for Arduino boards  
   * **ESP‑IDF** for ESP‑32 series  
   * **Arm GNU Toolchain** for STM32/NXP  

   Each vendor provides detailed installation guides; make sure the `PATH` includes the tool binaries.

6. **Clone example repositories**  
   ```bash
   git clone https://github.com/tensorflow/tflite-micro.git
   cd tflite-micro
   ```

With the environment ready, you can move on to **model creation**.

---

## Building a TinyML Model from Scratch  

### Data Collection & Pre‑processing  

For this guide, we’ll build a **keyword‑spotting** model that detects the word “hey robot” from a continuous audio stream. The dataset is the **Google Speech Commands v2** (public domain).  

```python
import tensorflow as tf
import pathlib

DATASET_PATH = pathlib.Path('speech_commands_v2')
AUTOTUNE = tf.data.AUTOTUNE

def load_wav(file_path):
    audio = tf.io.read_file(file_path)
    waveform, _ = tf.audio.decode_wav(audio, desired_channels=1)
    # Pad / truncate to 1 second (16 kHz)
    waveform = tf.squeeze(waveform)
    waveform = waveform[:16000]
    zero_padding = tf.zeros([16000] - tf.shape(waveform), dtype=tf.float32)
    waveform = tf.concat([waveform, zero_padding], 0)
    return waveform
```

* **Feature extraction:** Convert raw waveform to **log‑mel spectrograms** (40 mel bins, 32 ms windows).  

```python
def wav_to_log_mel(waveform):
    spectrogram = tf.signal.stft(waveform, frame_length=640, frame_step=320)
    magnitude = tf.abs(spectrogram)
    mel_filterbank = tf.signal.linear_to_mel_weight_matrix(
        num_mel_bins=40,
        num_spectrogram_bins=magnitude.shape[-1],
        sample_rate=16000,
        lower_edge_hertz=20,
        upper_edge_hertz=4000)
    mel_spectrogram = tf.tensordot(magnitude, mel_filterbank, 1)
    log_mel = tf.math.log(mel_spectrogram + 1e-6)
    return tf.expand_dims(log_mel, -1)  # Add channel dim
```

### Model Architecture Selection  

A compact **Depthwise Separable Convolution** network works well for keyword spotting.  

```python
def build_model(num_classes=2):
    inputs = tf.keras.Input(shape=(49, 40, 1))  # (time, mel, channel)
    x = tf.keras.layers.Conv2D(8, (3, 3), activation='relu')(inputs)
    x = tf.keras.layers.DepthwiseConv2D((3, 3), activation='relu')(x)
    x = tf.keras.layers.GlobalAveragePooling2D()(x)
    x = tf.keras.layers.Dense(16, activation='relu')(x)
    outputs = tf.keras.layers.Dense(num_classes, activation='softmax')(x)
    return tf.keras.Model(inputs, outputs)
```

The model has **≈ 12 k parameters**, well within TinyML limits.

### Training and Quantization  

```python
# Prepare dataset
train_ds = ...  # Use tf.data pipeline with wav_to_log_mel()
val_ds   = ...

model = build_model()
model.compile(optimizer='adam',
              loss='sparse_categorical_crossentropy',
              metrics=['accuracy'])

model.fit(train_ds, epochs=20, validation_data=val_ds)
```

After achieving ~95 % accuracy on the validation set, we **quantize** using QAT for best results.

```python
import tensorflow_model_optimization as tfmot

qat_model = tfmot.quantization.keras.quantize_model(build_model())
qat_model.compile(optimizer='adam',
                  loss='sparse_categorical_crossentropy',
                  metrics=['accuracy'])
qat_model.fit(train_ds, epochs=5, validation_data=val_ds)
```

Export the quantized model to TensorFlow Lite:

```python
converter = tf.lite.TFLiteConverter.from_keras_model(qat_model)
converter.optimizations = [tf.lite.Optimize.DEFAULT]
converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
converter.representative_dataset = lambda: iter(train_ds.map(lambda x, y: x).batch(1))
tflite_model = converter.convert()

# Save model
with open('keyword_spot.tflite', 'wb') as f:
    f.write(tflite_model)
```

The resulting file is **~19 KB**.

---

## Deploying to an MCU with TensorFlow Lite for Microcontrollers  

### Generating the C++ Model Blob  

The TensorFlow Lite for Microcontrollers (TFLM) runtime expects a **C header** containing a byte array of the model. Use the `xxd` utility:

```bash
xxd -i keyword_spot.tflite > keyword_spot_model.h
```

The header defines:

```c
unsigned char keyword_spot_tflite[] = {
  0x1c, 0x00, 0x00, 0x00, /* ... */
};
unsigned int keyword_spot_tflite_len = 19421;
```

### Writing the Inference Code  

Below is a minimal Arduino sketch for an **Arduino Nano 33 BLE** using the TFLM library.

```cpp
#include <Arduino.h>
#include "tensorflow/lite/micro/all_ops_resolver.h"
#include "tensorflow/lite/micro/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "keyword_spot_model.h"   // <-- generated header

// -----------------------------------------------------------------
// Configuration constants
constexpr int kTensorArenaSize = 10 * 1024; // 10KB arena (adjust as needed)
uint8_t tensor_arena[kTensorArenaSize];

// -----------------------------------------------------------------
MicroErrorReporter micro_error_reporter;
tflite::ErrorReporter* error_reporter = &micro_error_reporter;

const tflite::Model* model = nullptr;
tflite::MicroInterpreter* interpreter = nullptr;
TfLiteTensor* input = nullptr;
TfLiteTensor* output = nullptr;

// -----------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  // Load model
  model = tflite::GetModel(keyword_spot_tflite);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    error_reporter->Report("Model schema version mismatch!");
    while (1);
  }

  // Resolve operators (use AllOpsResolver for simplicity)
  static tflite::AllOpsResolver resolver;

  // Instantiate interpreter
  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaSize, error_reporter);
  interpreter = &static_interpreter;

  // Allocate tensors
  TfLiteStatus allocate_status = interpreter->AllocateTensors();
  if (allocate_status != kTfLiteOk) {
    error_reporter->Report("AllocateTensors() failed");
    while (1);
  }

  // Grab input and output tensors
  input = interpreter->input(0);
  output = interpreter->output(0);

  Serial.println("Keyword Spotting model ready!");
}

// -----------------------------------------------------------------
void loop() {
  // 1. Capture audio into a 1‑second buffer (e.g., using I2S)
  //    For brevity, we assume `audio_buffer` holds 16k int16 samples.
  int16_t audio_buffer[16000];
  // ... fill audio_buffer ...

  // 2. Pre‑process: convert to log‑mel spectrogram (same as training)
  //    This step is often done on the MCU using fixed‑point math.
  //    Here we just copy raw PCM into the input tensor for demo.
  for (int i = 0; i < input->bytes / sizeof(int8_t); ++i) {
    // Simple scaling from int16 to int8 (quantized)
    input->data.int8[i] = audio_buffer[i] >> 8; // naive quantization
  }

  // 3. Run inference
  TfLiteStatus invoke_status = interpreter->Invoke();
  if (invoke_status != kTfLiteOk) {
    error_reporter->Report("Invoke failed!");
    return;
  }

  // 4. Interpret results
  int8_t hotword_score = output->data.int8[0]; // index 0 = "hey robot"
  int8_t silence_score = output->data.int8[1];
  Serial.print("Score (hey robot): ");
  Serial.println(hotword_score);
  Serial.print("Score (silence): ");
  Serial.println(silence_score);

  // Simple decision rule
  if (hotword_score > silence_score + 10) {
    Serial.println("🔊 Hey robot detected!");
    // Trigger your application logic here
  }

  delay(200); // Throttle loop
}
```

**Key points to keep in mind:**

* **Tensor arena size**: Adjust until `AllocateTensors()` succeeds. Using an accelerator often reduces needed RAM.
* **Quantized input**: The model expects int8 values. You can implement a more accurate **float‑to‑int8** conversion using the scale/zero‑point stored in the model’s input tensor metadata.
* **Pre‑processing on MCU**: For production, implement the mel‑spectrogram pipeline with fixed‑point math or use the **CMSIS‑DSP** library (Arm) to accelerate FFT and filterbank steps.

---

## Leveraging Hardware Acceleration  

Running the same model on a plain MCU may consume **10–30 ms** per inference. With an accelerator, you can drop that to **<2 ms** and drastically cut power.

### Google Edge TPU  

The Edge TPU only accepts **int8** models compiled with the Edge TPU Compiler (`edgetpu_compiler`).  

```bash
edgetpu_compiler keyword_spot.tflite
# Generates: keyword_spot_edgetpu.tflite
```

**Integration on a Raspberry Pi (or any Linux host)**:

```python
import numpy as np
import tflite_runtime.interpreter as tflite

interpreter = tflite.Interpreter(
    model_path='keyword_spot_edgetpu.tflite',
    experimental_delegates=[tflite.load_delegate('libedgetpu.so.1')]
)
interpreter.allocate_tensors()
input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()

# Assume `log_mel` is a NumPy array shaped (1, 49, 40, 1) dtype=int8
interpreter.set_tensor(input_details[0]['index'], log_mel)
interpreter.invoke()
output = interpreter.get_tensor(output_details[0]['index'])
print('Edge TPU output:', output)
```

The Edge TPU delivers **~2 ms** latency for a 19 KB model, consuming **~0.5 W**.

### Arm Ethos‑U NPU  

Many modern MCUs (e.g., NXP i.MX RT600) embed the **Ethos‑U55** NPU. The workflow is similar but uses the **Arm NN** SDK.

```bash
# Convert model to Arm NN format
armnnConverter -m keyword_spot.tflite -o keyword_spot.armnn
```

The C++ inference loop then calls `armnn::IOptimizedNetwork` and runs on the NPU automatically. Documentation is available on Arm’s developer site.

### DSP‑Based Acceleration (e.g., ESP‑DSP)  

For ESP‑32‑S3, the **SIMD DSP instructions** can accelerate the mel‑spectrogram computation. The ESP‑IDF provides the `esp_dsp` library:

```c
#include "esp_dsp.h"
// Example: Compute FFT on a 256‑point frame
float32_t real[256], imag[256];
esp_dsp_fft_f32(real, imag, 256);
```

While not a full NN accelerator, the DSP reduces pre‑processing latency, allowing the MCU to spend more cycles on inference.

---

## Real‑World Use Cases  

| Use‑Case | Typical Model | Hardware Choice | Benefits |
|----------|---------------|----------------|----------|
| **Smart Home Voice Assistant** | Keyword spotting, command classification | Edge TPU + Raspberry Pi Zero 2W | Sub‑100 ms wake‑word detection, offline privacy |
| **Predictive Maintenance (vibration)** | 1‑D CNN on accelerometer data | STM32H7 + Ethos‑U55 | Detect bearing faults on the edge, avoid costly downtime |
| **Wildlife Acoustic Monitoring** | Bird‑call classification (tiny CNN) | ESP‑32‑S3 + DSP | Battery life > 1 year, remote deployment |
| **Gesture Recognition on Wearables** | 2‑D CNN on IMU spectrogram | Arduino Nano 33 BLE | Immediate feedback, low‑latency UI |
| **Industrial Vision (defect detection)** | Tiny MobileNetV2 | i.MX RT1060 + Ethos‑U | Real‑time inspection on production line |

These examples illustrate how **model size, latency, and power** dictate the hardware‑software stack.

---

## Performance Optimization Tips  

1. **Profile Memory Usage** – Use `tflite::MicroProfiler` to see per‑operator memory peaks. Reduce arena size if possible.  
2. **Operator Fusion** – Some accelerators support fusing Conv+ReLU or Depthwise+BatchNorm, cutting memory traffic.  
3. **Prune Redundant Channels** – Remove filters with near‑zero weights, then fine‑tune.  
4. **Use Fixed‑Point DSP for Pre‑Processing** – CMSIS‑DSP or ESP‑DSP can compute mel spectrograms in ~5 ms on Cortex‑M7.  
5. **Batch Inference (if latency budget permits)** – Process multiple audio frames at once to amortize overhead.  
6. **Dynamic Voltage & Frequency Scaling (DVFS)** – Lower MCU clock when idle; ramp up only during inference.  

---

## Debugging, Profiling, and Validation  

* **Unit‑Test the Pre‑Processing Pipeline** on the host before porting to MCU.  
* **Run TFLite Micro Benchmarks** (`tflite_micro_benchmark`) to compare CPU vs. accelerator runtimes.  
* **Validate Quantization Accuracy** with the `tflite::Interpreter::Invoke()` on a representative dataset; compute **post‑training loss** vs. float baseline.  
* **Use Serial Logging and LED Indicators** for quick field debugging.  

A typical debugging flow:

```c
// Print tensor dimensions and scales
Serial.printf("Input shape: %d %d %d %d\n",
    input->dims->data[0], input->dims->data[1],
    input->dims->data[2], input->dims->data[3]);
Serial.printf("Input scale: %f, zero_point: %d\n",
    input->params.scale, input->params.zero_point);
```

---

## Future Trends in Edge AI & TinyML  

1. **Automated Model Compression (AutoML for TinyML)** – Tools like **TensorFlow Model Optimization** and **Neural Architecture Search** will generate optimal models for a target MCU automatically.  
2. **On‑Device Continual Learning** – Lightweight algorithms (e.g., TinyMeta) will allow devices to adapt to new patterns without cloud retraining.  
3. **Standardized TinyML Benchmarks** – The **MLPerf Tiny** suite is becoming the de‑facto metric for comparing MCU and accelerator performance.  
4. **Integration of Vision Transformers (ViT) in Tiny Form** – Recent research shows that **tiny ViTs** can fit under 50 KB with competitive accuracy on simple image tasks.  
5. **Energy‑Harvesting Edge Nodes** – Combining ultra‑low‑power MCUs with solar or kinetic harvesters will enable truly autonomous AI sensors.

Staying aware of these trends will help you future‑proof your Edge AI projects.

---

## Conclusion  

Mastering Edge AI with TinyML is a **journey from data collection to efficient on‑device inference**. By following this guide you have:

* Gained an understanding of the **fundamental constraints** (flash, RAM, latency).  
* Trained a **compact, quantized model** that fits comfortably on a microcontroller.  
* Learned how to **export, compile, and embed** the model into a C++ firmware project.  
* Explored **hardware acceleration options**—Edge TPU, Arm Ethos‑U, and DSP‑based pipelines—that can cut inference time by an order of magnitude.  
* Seen **real‑world applications** and **optimization strategies** that bridge the gap between prototype and production.

The ecosystem continues to evolve, but the core workflow remains: **design, quantize, profile, and accelerate**. With the tools and concepts outlined here, you’re equipped to build intelligent, low‑power devices that run **anywhere**, **anytime**, and **securely**—the true promise of Edge AI.

Happy building!  

---  

## Resources  

1. **TensorFlow Lite for Microcontrollers Documentation** – Official guide covering model conversion, API usage, and supported hardware.  
   [TensorFlow Lite Micro](https://www.tensorflow.org/lite/microcontrollers)  

2. **Google Coral Edge TPU Documentation** – Detailed instructions on compiling models, using the Edge TPU Compiler, and deploying on Linux hosts or embedded boards.  
   [Coral Edge TPU Docs](https://coral.ai/docs/edgetpu/)  

3. **Arm Machine Learning Software Development Kit (ML SDK)** – Provides tools for converting models, running on Ethos‑U NPUs, and using CMSIS‑NN for optimized CPU inference.  
   [Arm ML SDK](https://developer.arm.com/tools-and-software/open-source-software/developer-tools/arm-ml-sdk)  

4. **TinyML Community – GitHub Repository** – A curated collection of tutorials, benchmark suites, and example projects for a variety of MCUs and accelerators.  
   [TinyML Community Repo](https://github.com/tinyml)  

5. **MLPerf Tiny Benchmark Suite** – Standardized benchmark for measuring performance and power of TinyML solutions across devices.  
   [MLPerf Tiny](https://mlcommons.org/en/inference-tiny/)  