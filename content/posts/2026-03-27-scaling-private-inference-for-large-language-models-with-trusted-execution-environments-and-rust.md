---
title: "Scaling Private Inference for Large Language Models with Trusted Execution Environments and Rust"
date: "2026-03-27T11:00:36.696"
draft: false
tags: ["LLM", "Trusted Execution Environments", "Rust", "Privacy", "Scalability"]
---

## Introduction

Large language models (LLMs) such as LLaMA 2, GPT‑4, or Claude have moved from research curiosities to production‑grade services that power chat assistants, code generators, and domain‑specific copilots. The value of these models lies in their *knowledge*—the patterns learned from billions of tokens. Yet that value is also the source of a critical tension:

* **Privacy** – Many enterprises need to run inference on proprietary or personally identifiable data (PII). Sending raw user inputs to a cloud provider can violate regulations (GDPR, HIPAA) or expose trade secrets.
* **Scalability** – State‑of‑the‑art LLMs contain tens to hundreds of billions of parameters. Running them at scale requires careful orchestration of CPU, GPU, and memory resources.
* **Trust** – Even if the inference service is hosted on a reputable cloud, customers often demand *cryptographic proof* that their data never left a protected boundary.

**Trusted Execution Environments (TEEs)**—hardware‑isolated enclaves such as Intel SGX, AMD SEV‑SNP, or Intel TDX—offer a solution: they guarantee that code and data inside the enclave cannot be inspected or tampered with by the host OS, hypervisor, or even the cloud provider. When combined with a systems language that emphasizes memory safety and zero‑cost abstractions, **Rust** becomes a natural fit for building high‑performance, privacy‑preserving inference pipelines.

This article provides a **deep‑dive** into how you can **scale private inference** for large language models using TEEs and Rust. We will cover:

1. The technical background of LLM inference and TEEs.
2. Architectural patterns that enable scalability while preserving confidentiality.
3. A step‑by‑step implementation guide (including code snippets) that demonstrates loading a quantized model into an enclave and serving secure token generation.
4. Performance‑tuning techniques: batching, multi‑enclave orchestration, and hardware acceleration.
5. Security considerations and real‑world use cases.
6. Future directions in confidential computing.

By the end of this article, you should have a solid mental model and concrete tools to start building **private, scalable LLM services** that you can run on‑premise, in the cloud, or at the edge.

---

## 1. Background

### 1.1 Large Language Model Inference Basics

LLM inference consists of three core steps:

1. **Tokenization** – Convert raw text into a sequence of integer IDs using a vocabulary (e.g., BPE).
2. **Forward Pass** – Feed the token IDs through the transformer stack (attention layers, feed‑forward networks) to compute logits for the next token.
3. **Sampling** – Apply temperature, top‑k / top‑p, or beam search to turn logits into a concrete token.

For a model with *N* parameters, the forward pass has a computational complexity of **O(N × L)** where *L* is the sequence length. Memory consumption is roughly **O(N + L)**; the model weights dominate.

Modern inference pipelines use **quantization** (e.g., 4‑bit or 8‑bit) and **model parallelism** (tensor or pipeline) to fit large models into GPU memory. However, when you move the computation inside a TEE, you face additional constraints:

* **Enclave Memory Limits** – SGX enclaves traditionally cap at ~128 MiB of EPC (Enclave Page Cache). Recent platforms (e.g., SGX2, TDX) raise this limit, but still far below the several gigabytes needed for a 7‑B model.
* **Restricted System Calls** – Enclaves cannot directly call the OS; they must go through *ocalls* (outside calls) which add latency.
* **No Direct GPU Access** – Most TEEs do not expose a raw GPU interface to the enclave; you must either run inference on CPU inside the enclave or use a *secure co‑processor* model.

Understanding these constraints informs the design choices discussed later.

### 1.2 Privacy Risks in Conventional LLM Inference

| Scenario | Risk |
|----------|------|
| SaaS chat API | User prompts and generated outputs are visible to the provider’s logs. |
| On‑premise deployment without isolation | Malicious insider could dump model weights or intercept data via OS-level tools. |
| Cloud VM with shared hardware | Side‑channel attacks (e.g., cache‑timing) can leak secrets from the model or data. |

Regulatory frameworks (GDPR Art. 25, HIPAA Privacy Rule) often require **data minimization** and **confidentiality‑by‑design**, which TEEs can help satisfy by providing *attested* execution.

### 1.3 Trusted Execution Environments Overview

| Platform | Key Features | Typical EPC / Secure Memory |
|----------|--------------|----------------------------|
| **Intel SGX** | Enclave isolation, remote attestation, sealed storage. | 128 MiB EPC (SGX2 can request more). |
| **AMD SEV‑SNP** | Full VM encryption, memory integrity, anti‑replay. | Up to several GiB of encrypted RAM (no strict enclave size). |
| **Intel TDX** | Isolated VMs with hardware‑rooted attestation. | Similar to SEV‑SNP, but Intel ecosystem. |
| **Apple Secure Enclave** | Small co‑processor for cryptographic ops. | Very limited memory, not suitable for LLMs. |

**Remote attestation** is the process by which an enclave proves to a remote verifier that it is running the expected code on genuine hardware. The verifier then decides whether to send secret data (e.g., API keys, model weights) into the enclave.

### 1.4 Why Rust is a Perfect Match for TEEs

| Rust Feature | Benefit for TEE Development |
|--------------|----------------------------|
| **Memory safety without GC** | Guarantees against buffer overflows that could corrupt enclave memory. |
| **Zero‑cost abstractions** | No runtime penalty; you can write high‑level code that compiles to efficient assembly. |
| **`no_std` support** | Many enclave SDKs require `no_std` environments; Rust can compile without the standard library. |
| **Strong type system** | Helps model complex data pipelines (tokenizers, tensors) with compile‑time checks. |
| **Cargo ecosystem** | Crates like `serde`, `rand`, and `tokio` have `no_std` variants, facilitating serialization and async I/O inside enclaves. |

Furthermore, the **Rust SGX SDK** and **Fortanix Enclave Development Platform (EDP)** provide first‑class tooling to build, test, and sign enclave binaries.

---

## 2. Architectural Patterns for Private Inference

Designing a private inference service requires balancing **security**, **performance**, and **operational complexity**. Below are three proven patterns.

### 2.1 Enclave‑First (All‑In‑Enclave) Architecture

```
+-------------------+      +-------------------+
|  Client (HTTPS)  | ---> |  Enclave (CPU)    |
|  (TLS Terminated) |      |  - Tokenizer      |
+-------------------+      |  - Model Forward  |
                           |  - Sampling       |
                           +-------------------+
```

*All* model weights, tokenizer, and inference logic reside inside the enclave. The host OS only forwards encrypted network traffic.  

**Pros**
- Strongest confidentiality: no data leaves the enclave.
- Simplified attestation flow (single enclave).

**Cons**
- Limited by enclave memory; large models require *model partitioning* or *on‑demand paging*.
- No direct GPU acceleration (unless using a specialized secure GPU).

### 2.2 Edge‑First (Hybrid) Architecture

```
+-------------------+      +-------------------+      +-------------------+
|  Client (HTTPS)   | ---> |  Edge Service    | ---> |  Enclave (CPU)    |
|  (TLS Terminated) |      |  - Pre‑proc      |      |  - Secure Model   |
+-------------------+      |  - Cache         |      +-------------------+
                           +-------------------+
```

The edge service runs on the same host but **outside** the enclave. It performs non‑sensitive preprocessing (e.g., tokenization) and caches frequently used embeddings. Sensitive parts (e.g., final logits, sampling) stay inside the enclave.

**Pros**
- Allows use of GPU for heavy matrix multiplications outside the enclave (still protected via data encryption).
- Reduces enclave memory pressure.

**Cons**
- Increases attack surface: tokenization pipeline must be verified to avoid leakage.
- Requires careful data sanitization before crossing the enclave boundary.

### 2.3 Model Partitioning & Secure Offloading

For models > 10 B parameters, you can **split** the transformer into two stages:

1. **Front‑End (Public)** – First *k* transformer layers run on the host (CPU/GPU) without exposing raw inputs.
2. **Back‑End (Secure)** – Remaining layers, including the final logits, run inside the enclave.

Data exchanged between stages is **encrypted** (e.g., using a symmetric key sealed to the enclave). This pattern preserves privacy for the most sensitive part of inference (the final decision) while still leveraging hardware acceleration for the bulk of the computation.

---

## 3. Scaling Strategies Inside TEEs

Even with a solid architecture, scaling private inference to serve thousands of requests per second requires careful engineering. Below are the levers you can pull.

### 3.1 Batching and Parallelism

Most modern LLM inference services use **dynamic batching**: collect multiple incoming requests into a single tensor and run a single forward pass. Inside an enclave:

* Use **Rust threads** (`std::thread`) or **`rayon`** for intra‑enclave parallelism.  
* Leverage **Intel SGX2's dynamic memory allocation** to grow EPC on demand (subject to OS limits).  
* **Batch size** must be tuned to fit within EPC; larger batches improve GPU‑like throughput but increase memory pressure.

```rust
/// Simple dynamic batch collector inside an SGX enclave.
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const MAX_BATCH: usize = 32;
const BATCH_TIMEOUT_MS: u64 = 10;

#[derive(Clone)]
struct InferenceRequest {
    tokens: Vec<u32>,
    response_tx: crossbeam_channel::Sender<String>,
}

struct BatchCollector {
    pending: Arc<Mutex<Vec<InferenceRequest>>>,
}

impl BatchCollector {
    fn new() -> Self {
        Self {
            pending: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Called by the outer ocall handler when a new request arrives.
    fn submit(&self, req: InferenceRequest) {
        let mut guard = self.pending.lock().unwrap();
        guard.push(req);
        if guard.len() >= MAX_BATCH {
            self.flush();
        }
    }

    /// Flushes the batch either when full or after timeout.
    fn flush(&self) {
        let batch = {
            let mut guard = self.pending.lock().unwrap();
            std::mem::take(&mut *guard)
        };
        if batch.is_empty() {
            return;
        }

        // Run inference (placeholder)
        let outputs = self.run_batch(&batch);
        for (req, out) in batch.into_iter().zip(outputs) {
            let _ = req.response_tx.send(out);
        }
    }

    fn run_batch(&self, batch: &[InferenceRequest]) -> Vec<String> {
        // Here you would call the actual transformer forward pass.
        // For illustration we just echo back the token count.
        batch
            .iter()
            .map(|r| format!("Processed {} tokens", r.tokens.len()))
            .collect()
    }

    /// Background thread that triggers timeout‑based flushes.
    fn start_timeout_thread(&self) {
        let pending = self.pending.clone();
        std::thread::spawn(move || loop {
            std::thread::sleep(Duration::from_millis(BATCH_TIMEOUT_MS));
            let now = Instant::now();
            let mut guard = pending.lock().unwrap();
            if !guard.is_empty() && now.elapsed().as_millis() >= BATCH_TIMEOUT_MS as u128 {
                // Release lock before running inference to avoid deadlock.
                drop(guard);
                // In a real implementation, you would call `self.flush()`.
            }
        });
    }
}
```

> **Note:** The code above is `no_std`‑compatible with minor adjustments (replace `std::sync` with `spin` or `lock_api` crates). It demonstrates how you can collect requests inside the enclave and process them in batches.

### 3.2 Memory Management & Paging

When EPC is insufficient, SGX automatically **pages** enclave memory to untrusted RAM, encrypting each page. This incurs a **~30‑µs** penalty per page fault, dramatically affecting latency.

* **Pre‑allocate** a contiguous buffer for model weights (e.g., using `mmap` inside the enclave) to avoid fragmentation.
* **Chunk the model** into 4 MiB pages and load them on‑demand, keeping the most‑used layers hot.
* Use **quantization** (4‑bit or 8‑bit) and **sparse representations** to shrink the memory footprint.

### 3.3 Multi‑Enclave Orchestration

For high throughput, you can **run multiple enclaves** in parallel, each handling its own batch queue. A lightweight **orchestrator** outside the enclaves distributes incoming requests and aggregates responses.

```
+-------------------+      +-------------------+      +-------------------+
|  Load Balancer    | ---> |  Enclave #1 (CPU) | ---> |  Result Aggregator |
|  (e.g., Envoy)    |      |  - Inference      |      +-------------------+
+-------------------+      +-------------------+
        |                        |
        v                        v
   +-------------------+   +-------------------+
   |  Enclave #2 (CPU) |   |  Enclave #3 (CPU) |
   +-------------------+   +-------------------+
```

Key considerations:

* **Attestation per enclave** – Each enclave must be individually attested, but you can cache the attestation certificate for the lifetime of the service.
* **Shared model storage** – Store the encrypted model in a **sealed file** on disk; each enclave can load it independently using the same sealing key.
* **Inter‑enclave communication** – Avoid direct shared memory; instead use **message‑passing** over Unix domain sockets with **OCALL** wrappers.

### 3.4 Hardware Acceleration with TEEs

#### 3.4.1 SGX + Intel AVX‑512

SGX enclaves can still use **AVX‑512** instructions, which accelerate matrix multiplication. Use the `aligned_alloc` crate to ensure 64‑byte alignment required by AVX.

#### 3.4.2 SEV‑SNP / TDX + GPU Offload

AMD SEV‑SNP and Intel TDX protect **entire VMs**, allowing the VM to access GPUs directly. In this scenario:

1. **Encrypt** the model weights using a **VM‑sealed key**.
2. **Load** the encrypted model into GPU memory via **CUDA**.
3. Perform the heavy matrix multiplications on the GPU, then **bring the final logits back** into the protected VM for secure sampling.

Rust crates such as `cust` (CUDA bindings) can be compiled with the `sgx` feature flag to work inside a confidential VM.

---

## 4. Practical Implementation Walkthrough

Below we walk through a **minimal but functional** private inference service that runs a **quantized 7‑B LLaMA‑2** model inside an **Intel SGX enclave** using **Rust**. The goal is to illustrate the end‑to‑end flow, not to deliver production‑grade performance.

### 4.1 Prerequisites

| Item | Version |
|------|---------|
| Rust toolchain | `1.78` or newer |
| Intel SGX SDK | `2.19` |
| Fortanix EDP (optional) | `0.5.0` |
| `llama.cpp` quantized model | `ggml‑model‑q4_0.bin` |
| `serde` + `serde_json` | `1.0` |
| `tokio` (for async I/O) | `1.36` |
| `crossbeam-channel` | `0.5` |

> **Tip:** Use the `rustup target add x86_64-fortanix-unknown-sgx` target to compile for SGX.

### 4.2 Project Layout

```
private-llm/
├─ Cargo.toml
├─ src/
│  ├─ lib.rs          # Enclave entry point
│  ├─ inference.rs   # Model loading & forward pass
│  └─ api.rs          # OCALL/ECALL definitions
└─ edl/
   └─ enclave.edl     # SGX interface definition
```

### 4.3 Defining the Enclave Interface (`enclave.edl`)

```edl
enclave {
    from "sgx_tstd.edl" import *;
    from "sgx_tcrypto.edl" import *;

    trusted {
        public void ecall_init_model([in, size=key_len] const uint8_t* key,
                                    size_t key_len,
                                    [in, string] const char* model_path);
        public void ecall_generate([in, size=token_len] const uint32_t* tokens,
                                   size_t token_len,
                                   [out, size=out_len] uint8_t* response,
                                   size_t out_len);
    };

    untrusted {
        void ocall_log([in, string] const char* msg);
    };
};
```

* `ecall_init_model` receives a sealed key and the path to the encrypted model.
* `ecall_generate` takes a token array and returns a generated token (or text).
* `ocall_log` is a simple logging helper.

### 4.4 Enclave Code (`src/lib.rs`)

```rust
#![no_std]
#![feature(rustc_private)]

extern crate sgx_tstd as std;
extern crate sgx_tcrypto as crypto;

use std::vec::Vec;
use std::string::String;
use std::slice;
use crypto::rsgx_seal_data_t;
use crate::inference::{Model, Tokenizer};

static mut GLOBAL_MODEL: Option<Model> = None;
static mut GLOBAL_TOKENIZER: Option<Tokenizer> = None;

/// Helper to log from inside the enclave.
fn log(msg: &str) {
    unsafe {
        ocall_log(msg.as_ptr() as *const i8);
    }
}

/// Initialize the model inside the enclave. The model file is encrypted on disk;
/// we decrypt it using the sealed key provided by the untrusted host.
#[no_mangle]
pub extern "C" fn ecall_init_model(
    sealed_key: *const u8,
    key_len: usize,
    model_path: *const i8,
) {
    // Safety: SGX guarantees that the pointers are valid for the given length.
    let key_slice = unsafe { slice::from_raw_parts(sealed_key, key_len) };
    let path = unsafe { std::ffi::CStr::from_ptr(model_path) }
        .to_str()
        .expect("invalid UTF-8");
    log(&format!("Loading model from {}", path));

    // Decrypt the model file (pseudo‑code)
    let encrypted = std::fs::read(path).expect("cannot read model");
    let decrypted = crypto::rsgx_unseal_data(&rsgx_seal_data_t::from_raw(key_slice))
        .expect("unseal failed")
        .get_decrypt_txt()
        .to_vec();

    // Load the quantized model (using llama.cpp bindings)
    let model = Model::load_from_bytes(&decrypted).expect("model load failed");
    let tokenizer = Tokenizer::load_from_path("tokenizer.model").expect("tokenizer");

    unsafe {
        GLOBAL_MODEL = Some(model);
        GLOBAL_TOKENIZER = Some(tokenizer);
    }

    log("Model initialization complete");
}

/// Perform a single generation step. For simplicity we generate one token at a time.
#[no_mangle]
pub extern "C" fn ecall_generate(
    tokens_ptr: *const u32,
    token_len: usize,
    response_ptr: *mut u8,
    out_len: usize,
) {
    let input_tokens = unsafe { slice::from_raw_parts(tokens_ptr, token_len) };
    let model = unsafe { GLOBAL_MODEL.as_ref().expect("model not initialized") };
    let tokenizer = unsafe { GLOBAL_TOKENIZER.as_ref().expect("tokenizer not initialized") };

    // Run forward pass (pseudo‑code)
    let logits = model.forward(input_tokens);
    let next_id = model.sample(&logits, 0.8, 40); // temperature, top‑k

    // Convert token ID back to UTF‑8 string (may be multi‑byte)
    let output = tokenizer.decode(&[next_id]);

    // Write back to the caller buffer
    let bytes = output.as_bytes();
    let copy_len = core::cmp::min(bytes.len(), out_len);
    unsafe {
        core::ptr::copy_nonoverlapping(bytes.as_ptr(), response_ptr, copy_len);
    }
}
```

> **Important:** The example omits many error checks for brevity. In production you should propagate SGX error codes back to the host.

### 4.5 Model Loading (`src/inference.rs`)

Here we reuse the **`llama.cpp` Rust bindings** (`llama-rs`). The key point is that the model is **quantized to 4‑bit**, shrinking the weight size to ~3 GiB for a 7‑B model, which fits into the EPC of a modern SGX2 machine with paging.

```rust
use std::sync::Arc;
use llama_rs::{Model as LlamaModel, Tokenizer as LlamaTokenizer};

pub struct Model {
    inner: Arc<LlamaModel>,
}

impl Model {
    pub fn load_from_bytes(data: &[u8]) -> Result<Self, String> {
        // The llama-rs crate can load from a memory buffer.
        let model = LlamaModel::load_from_buffer(data, Default::default())
            .map_err(|e| format!("load error: {:?}", e))?;
        Ok(Self {
            inner: Arc::new(model),
        })
    }

    /// Forward pass returning raw logits.
    pub fn forward(&self, tokens: &[u32]) -> Vec<f32> {
        // In a real implementation you would manage KV cache, attention masks, etc.
        self.inner.eval(tokens, 0).expect("eval failed")
    }

    /// Simple top‑k sampling.
    pub fn sample(&self, logits: &[f32], temperature: f32, top_k: usize) -> u32 {
        use rand::seq::SliceRandom;
        use rand::thread_rng;

        // Apply temperature scaling
        let scaled: Vec<f32> = logits.iter().map(|l| l / temperature).collect();

        // Get top‑k indices
        let mut indices: Vec<usize> = (0..scaled.len()).collect();
        indices.sort_by(|&i, &j| scaled[j].partial_cmp(&scaled[i]).unwrap());

        let top_indices = &indices[..top_k];
        let probs: Vec<f32> = top_indices
            .iter()
            .map(|&i| scaled[i].exp())
            .collect();

        let sum: f32 = probs.iter().sum();
        let normalized: Vec<f32> = probs.iter().map(|p| p / sum).collect();

        // Sample
        let mut rng = thread_rng();
        let choice = normalized
            .choose_weighted(&mut rng, |p| *p)
            .expect("sampling failed");
        let chosen_idx = top_indices[choice];
        chosen_idx as u32
    }
}

pub struct Tokenizer {
    inner: LlamaTokenizer,
}

impl Tokenizer {
    pub fn load_from_path(path: &str) -> Result<Self, String> {
        let tokenizer = LlamaTokenizer::load(path).map_err(|e| format!("{:?}", e))?;
        Ok(Self { inner: tokenizer })
    }

    pub fn decode(&self, ids: &[u32]) -> String {
        self.inner.decode(ids, true)
    }
}
```

### 4.6 Host Application (Untrusted Side)

The host runs a **Tokio‑based HTTP server** (e.g., using `warp` or `axum`) that forwards requests to the enclave via ECALLs.

```rust
use axum::{
    routing::post,
    Json,
    extract::Extension,
    response::IntoResponse,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use sgx_urts::SgxEnclave;

#[derive(Deserialize)]
struct Prompt {
    text: String,
}

#[derive(Serialize)]
struct Completion {
    reply: String,
}

// Wrapper around the enclave instance.
struct EnclaveHandle {
    enclave: SgxEnclave,
}

impl EnclaveHandle {
    fn new() -> Self {
        // Load the signed enclave file (produced by `sgx_sign`).
        let enclave = SgxEnclave::create(
            "enclave.signed.so",
            SGX_DEBUG_FLAG,
            &mut sgx_misc_attribute_t::default(),
        )
        .expect("failed to create enclave");
        Self { enclave }
    }

    fn init(&self) {
        // Load sealed key and model path (simplified).
        let sealed_key = std::fs::read("sealed_key.bin").unwrap();
        let model_path = std::ffi::CString::new("model.enc").unwrap();
        unsafe {
            ecall_init_model(
                self.enclave.geteid(),
                sealed_key.as_ptr(),
                sealed_key.len(),
                model_path.as_ptr(),
            );
        }
    }

    fn generate(&self, tokens: &[u32]) -> String {
        // Allocate output buffer
        let mut out_buf = vec![0u8; 256];
        unsafe {
            ecall_generate(
                self.enclave.geteid(),
                tokens.as_ptr(),
                tokens.len(),
                out_buf.as_mut_ptr(),
                out_buf.len(),
            );
        }
        // Trim trailing zeros
        let end = out_buf.iter().position(|&b| b == 0).unwrap_or(out_buf.len());
        String::from_utf8_lossy(&out_buf[..end]).to_string()
    }
}

#[tokio::main]
async fn main() {
    let enclave = Arc::new(EnclaveHandle::new());
    enclave.init();

    let app = axum::Router::new()
("/complete", post(handle_completion))
        .layer(Extension(enclave));

    axum::Server::bind(&"0.0.0.0:8080".parse().unwrap())
        .serve(app.into_make_service())
        .await
        .unwrap();
}

async fn handle_completion(
    Json(payload): Json<Prompt>,
    Extension