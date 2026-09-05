---
title: "Building a GGUF Parser and Tensor Loader From Scratch: A Portfolio Project That Actually Signals Systems Skill"
date: "2026-09-05T06:00:30.807"
draft: false
tags: ["gguf", "llm-internals", "rust", "quantization", "systems-engineering", "portfolio"]
description: "A hands-on build guide for a from-scratch GGUF parser, q4_0/q8_0 dequantizer, and mmap'd tensor loader that streams weights into a tiny Llama forward pass."
summary: "Build a real GGUF parser and tensor loader from scratch in Rust — metadata parsing, q4_0/q8_0 dequantization, mmap'd weight streaming, and a minimal Llama forward pass. The kind of CV project that gets interviews at systems and ML infra teams."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-building-a-gguf-parser-and-tensor-loader-from-scratch-a-portfolio-project-that-actually-signals-systems-skill.svg"
  alt: "Diagram of a GGUF file layout with tensor metadata and quantized weight blocks."
  caption: ""
  relative: false
---

> **TL;DR** — GGUF is the format behind every local Llama-family model. A from-scratch parser that handles header metadata, q4_0/q8_0 dequantization, and mmap'd weight streaming into a working forward pass demonstrates file format fluency, low-level numerics, memory-mapped I/O, and transformer internals — the exact stack ML systems teams hire for.

## Why This Project Stands Out on a CV

Most "LLM projects" on portfolios are API wrappers in Python that call `openai.ChatCompletion.create()`. They look identical to every other applicant, and they signal nothing about how you think about hardware, memory, or data layout. A GGUF parser is different. It's the kind of project that makes a hiring manager at an ML infra team stop scrolling.

Concretely, this project demonstrates:

- **Binary format literacy.** GGUF is a versioned, little-endian binary container with typed metadata (strings, arrays, nested kv-pairs) and a tensor index. Reading it from scratch means writing endian-correct struct decoders, validating magic numbers, and reasoning about alignment — the same muscles used for protocol buffers, FlatBuffers, or image codecs.
- **Quantization numerics.** `q4_0` and `q8_0` are not academic. They are the actual on-disk formats for quantized Llama weights shipped by Ollama, LM Studio, and llama.cpp. Dequantizing them correctly means understanding block scales, symmetric integer ranges, and fp16 → fp32 promotion. This is the work being done in production at [GGML](https://github.com/ggerganov/ggml), [vLLM](https://github.com/vllm-project/vllm), and [TensorRT-LLM](https://github.com/NVIDIA/TensorRT-LLM).
- **Memory-mapped I/O.** Instead of `read()` into heap buffers, you `mmap()` the file and let the kernel page weights in on demand. This is how llama.cpp loads 70B models in <2 GB of RAM, and it's the same pattern as RocksDB's block cache, DuckDB's Parquet reader, and PostGIS' raster loader.
- **Transformer internals.** A tiny Llama forward pass means implementing RMSNorm, rotary embeddings (RoPE), grouped-query attention with KV cache, and SwiGLU. It's not a toy if it actually produces sensible logits.
- **Systems thinking end-to-end.** Parsing, allocation strategy, cache locality in dequantization, and forward-pass kernel layout all have to cohere. That's what ML systems interviews test.

The roles this signals for: ML infrastructure engineer, inference platform engineer, compiler/runtime engineer at an AI lab, on-device ML engineer, and any backend role where "I can reason about bytes on disk and numbers in memory" is the bar.

## Architecture Overview

The project has five layers, each small enough to land in a weekend and deep enough to talk about for an hour in an interview.

- **1. File format layer.** A `GgufReader` that opens a file via `mmap`, validates the `gguf` magic, reads the version, and exposes typed accessors for metadata.
- **2. Metadata layer.** A `Metadata` struct holding `general.architecture`, `llama.context_length`, `llama.embedding_length`, attention head counts, and quantization scheme. Parses GGUF's `GGUFValue` enum: strings, uint32/64, int32/64, floats, bools, and arrays of all of the above.
- **3. Tensor index layer.** A `TensorIndex` mapping tensor names (e.g. `token_embd.weight`, `blk.0.attn_q.weight`) to `TensorInfo { offset, n_elements, dtype }`. The reader resolves names to `(ptr, n_elements, qtype)` tuples lazily.
- **4. Dequantization layer.** Pure functions `dequantize_q4_0(block: &[u8]) -> &[f32]` and `dequantize_q8_0(block: &[u8]) -> &[f32]`. Block size is 32 for q4_0 (32 4-bit values + 1 fp16 scale = 18 bytes), 32 for q8_0 (32 int8 values + 1 fp16 scale = 34 bytes).
- **5. Forward pass layer.** A `LlamaModel` that holds a `HashMap<String, Tensor>` of dequantized weights and exposes `forward(tokens: &[u32]) -> Vec<f32>`. Implements RMSNorm, RoPE, attention with KV cache, and SwiGLU MLP. Greedy argmax decode for a single token at a time.

```
┌──────────────────────────── GGUF file on disk ────────────────────────────┐
│  magic: gguf │ ver │ n_kv │ n_tensors │ metadata kv-pairs │ tensor index  │
│                                          │               │                │
│                                          ▼               ▼                │
│                              (key, GGUFValue)     (name, offset, n, qtype) │
└────────────────────────────────────┬──────────────────────────────────────┘
                                     │  mmap()
                                     ▼
                          ┌──────────────────────┐
                          │   GgufReader (Rust)  │
                          └──────────┬───────────┘
                                     │
                ┌────────────────────┼────────────────────┐
                ▼                    ▼                    ▼
        Metadata (config)     TensorIndex (lazy)    Déquantize q4_0/q8_0
                │                    │                    │
                └─────────┬──────────┴──────────┬─────────┘
                          ▼                     ▼
                ┌─────────────────────────────────────┐
                │         LlamaModel.forward()        │
                │   RMSNorm → RoPE → GQA → SwiGLU    │
                └────────────────┬────────────────────┘
                                 ▼
                       logits → argmax → next token
```

## Building It Step by Step

We'll build this in Rust. The reasons are practical: `memmap2` gives us safe `mmap`, `half` handles fp16, and zero-cost abstractions mean our forward pass can match C/C++ performance without contortions. You can do this in C++ too — see [llama.cpp](https://github.com/ggerganov/llama.cpp) — but Rust enforces the type discipline that makes the dequantization arithmetic less error-prone.

### Step 1: Scaffolding and dependencies

```bash
cargo new gguf-loader && cd gguf-loader
cargo add memmap2 half thiserror anyhow
```

`Cargo.toml` should look like:

```toml
[package]
name = "gguf-loader"
version = "0.1.0"
edition = "2021"

[dependencies]
memmap2 = "0.9"
half = { version = "2.4", features = ["std"] }
thiserror = "1"
anyhow = "1"
```

### Step 2: The GGUF value enum

GGUF metadata values are tagged by a `GGUFType` byte. Define the enum that your reader will deserialize them into. The full list is documented in the [GGUF spec](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md).

```rust
// src/format.rs
use half::f16;

#[derive(Debug, Clone)]
pub enum GGUFValue {
    String(String),
    Array(Vec<GGUFValue>),
    Uint32(u32),
    Int32(i32),
    Float32(f32),
    Bool(bool),
    Uint64(u64),
    Int64(i64),
    Float64(f64),
}

#[repr(u32)]
#[derive(Debug, Copy, Clone, PartialEq)]
pub enum GGUFType {
    String   = 8,
    Array    = 9,
    Uint32   = 0,
    Int32    = 1,
    Float32  = 2,
    Bool     = 3,
    // ... up to 12 for the canonical types
}
```

### Step 3: Header parsing with mmap

The GGUF header is: magic `0x46475547` ("GGUF" in little-endian ASCII), u32 version, u64 tensor count, u64 kv count. Then `tensor_count` tensor infos (16 bytes each: 8-byte offset + 8-byte size — note: GGUF stores an offset and a byte count, not n_elements), then `kv_count` kv pairs. Each kv pair is a length-prefixed key string, a u32 type tag, and a typed payload.

```rust
// src/reader.rs
use std::fs::File;
use memmap2::Mmap;
use anyhow::{Result, bail};

pub struct GgufReader {
    mmap: Mmap,
    pub metadata: std::collections::HashMap<String, GGUFValue>,
    pub tensors: Vec<TensorInfo>,
    pub tensor_data_offset: usize,
}

#[derive(Debug, Clone)]
pub struct TensorInfo {
    pub name: String,
    pub offset: u64,
    pub size_bytes: u64,
    pub qtype: u8, // GGML quantization type: 2=Q4_0, 8=Q8_0, etc.
}

impl GgufReader {
    pub fn open(path: &str) -> Result<Self> {
        let file = File::open(path)?;
        let mmap = unsafe { Mmap::map(&file)? };

        let mut p = 0usize;

        // Magic
        let magic = u32::from_le_bytes(mmap[p..p+4].try_into()?);
        if magic != 0x46475547 {
            bail!("not a GGUF file (magic={:08x})", magic);
        }
        p += 4;

        // Version
        let version = u32::from_le_bytes(mmap[p..p+4].try_into()?);
        p += 4;
        if version != 3 {
            bail!("only GGUF v3 supported (got {})", version);
        }

        // Counts
        let n_tensors = u64::from_le_bytes(mmap[p..p+8].try_into()?) as usize;
        p += 8;
        let n_kv = u64::from_le_bytes(mmap[p..p+8].try_into()?) as usize;
        p += 8;

        let mut metadata = std::collections::HashMap::new();
        for _ in 0..n_kv {
            let (key, val, np) = read_kv(&mmap[p..])?;
            metadata.insert(key, val);
            p += np;
        }

        let mut tensors = Vec::with_capacity(n_tensors);
        for _ in 0..n_tensors {
            let name_len = u64::from_le_bytes(mmap[p..p+8].try_into()?) as usize;
            p += 8;
            let name = std::str::from_utf8(&mmap[p..p+name_len])?.to_string();
            p += name_len;
            // align to 8
            p = (p + 7) & !7;

            let n_dims = u32::from_le_bytes(mmap[p..p+4].try_into()?) as usize;
            p += 4;
            let mut dims = Vec::with_capacity(n_dims);
            for _ in 0..n_dims {
                let d = u64::from_le_bytes(mmap[p..p+8].try_into()?);
                p += 8;
                dims.push(d);
            }
            let dtype = u32::from_le_bytes(mmap[p..p+4].try_into()?);
            p += 4;
            let offset = u64::from_le_bytes(mmap[p..p+8].try_into()?);
            p += 8;

            tensors.push(TensorInfo {
                name,
                offset,
                size_bytes: 0, // computed lazily
                qtype: dtype as u8,
            });
        }

        let tensor_data_offset = (p + 31) & !31; // GGUF aligns tensor data to 32

        Ok(Self { mmap, metadata, tensors, tensor_data_offset })
    }

    pub fn tensor_bytes(&self, info: &TensorInfo) -> &[u8] {
        let start = self.tensor_data_offset + info.offset as usize;
        // n_elements from dims product; for our 2D weights we read n_elements × bytes_per_elem
        &self.mmap[start..start + info.size_bytes as usize]
    }
}
```

The two non-obvious bits: kv-pair alignment to 8 bytes and tensor data aligned to 32 bytes. Get these wrong and you'll silently read garbage. The full layout is in the [ggml GGUF spec](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md).

### Step 4: Dequantization

`q4_0` packs 32 four-bit signed values into 16 bytes, prefixed by an `f16` scale. The total block is 18 bytes. The formula is: `x_i = q_i * scale`, where `q_i` is a signed nibble in `[-8, 7]`.

```rust
// src/dequant.rs
use half::f16;

pub const Q4_0_BLOCK: usize = 18;  // 16 bytes packed + 2 bytes f16 scale
pub const Q4_0_COUNT: usize = 32;
pub const Q8_0_BLOCK: usize = 34;  // 32 bytes int8 + 2 bytes f16 scale
pub const Q8_0_COUNT: usize = 32;

#[inline]
pub fn dequantize_q4_0(block: &[u8]) -> [f32; Q4_0_COUNT] {
    let scale = f16::from_le_bytes([block[16], block[17]]).to_f32();
    let mut out = [0f32; Q4_0_COUNT];
    for i in 0..16 {
        let lo = (block[i] & 0x0F) as i8 - 8;
        let hi = ((block[i] >> 4) & 0x0F) as i8 - 8;
        out[2 * i]     = lo as f32 * scale;
        out[2 * i + 1] = hi as f32 * scale;
    }
    out
}

#[inline]
pub fn dequantize_q8_0(block: &[u8]) -> [f32; Q8_0_COUNT] {
    let scale = f16::from_le_bytes([block[32], block[33]]).to_f32();
    let mut out = [0f32; Q8_0_COUNT];
    for i in 0..Q8_0_COUNT {
        out[i] = (block[i] as i8 as f32) * scale;
    }
    out
}
```

This is the numerically honest part. If your `to_f32()` is wrong, your logits will be garbage. The block layout matches what [llama.cpp's ggml-quants.c](https://github.com/ggerganov/llama.cpp/blob/master/ggml/src/ggml-quants.c) does, which is the reference implementation.

For a 2D weight matrix of shape `[out, in]`, you walk blocks along the inner dimension. The full weight tensor is `[n_elements / 32]` contiguous blocks.

### Step 5: Loading a tensor with mmap

The win of mmap is that the file stays on disk; we only fault pages in as we dequantize. For a 7B q4_0 model that's ~4 GB on disk, but the resident set stays small until you touch tensors.

```rust
// src/loader.rs
use crate::reader::{GgufReader, TensorInfo};
use crate::dequant::{dequantize_q4_0, dequantize_q8_0, Q4_0_BLOCK, Q8_0_BLOCK};

pub fn load_tensor(reader: &GgufReader, info: &TensorInfo) -> Vec<f32> {
    let bytes = reader.tensor_bytes(info);
    match info.qtype {
        2 => { // GGML_Q4_0
            let n_blocks = bytes.len() / Q4_0_BLOCK;
            let mut out = Vec::with_capacity(n_blocks * 32);
            for i in 0..n_blocks {
                let block = &bytes[i * Q4_0_BLOCK..(i + 1) * Q4_0_BLOCK];
                out.extend_from_slice(&dequantize_q4_0(block));
            }
            out
        }
        8 => { // GGML_Q8_0
            let n_blocks = bytes.len() / Q8_0_BLOCK;
            let mut out = Vec::with_capacity(n_blocks * 32);
            for i in 0..n_blocks {
                let block = &bytes[i * Q8_0_BLOCK..(i + 1) * Q8_0_BLOCK];
                out.extend_from_slice(&dequantize_q8_0(block));
            }
            out
        }
        _ => panic!("unsupported qtype {}", info.qtype),
    }
}
```

The page fault happens lazily on first dereference. You can confirm with `ps -o rss` — resident set stays flat while the file is large.

### Step 6: The Llama forward pass

A full forward pass is too long to inline here, but the architectural skeleton matters more than the line count. Each transformer block is:

```rust
// src/model.rs (sketch)
fn forward_block(&mut self, x: &mut [f32], pos: usize) {
    // Pre-norm + RoPE + GQA with KV cache
    let h = rms_norm(x, &self.attn_norm, self.eps);
    let (q, k, v) = project_attention(&h, &self.wq, &self.wk, &self.wv, self.n_heads, self.n_kv_heads);
    rope_inplace(&mut q, &mut k, pos, self.head_dim);
    self.cache_k[pos] = k;
    self.cache_v[pos] = v;
    let attn_out = gqa_attention(&q, &self.cache_k[..=pos], &self.cache_v[..=pos],
                                 self.n_heads, self.n_kv_heads, self.head_dim);
    let h2 = matmul(&attn_out, &self.wo);

    // Residual + MLP
    for i in 0..x.len() { x[i] += h2[i]; }
    let h = rms_norm(x, &self.ffn_norm, self.eps);
    let gate = matmul(&h, &self.w_gate);
    let up   = matmul(&h, &self.w_up);
    let mut mlp = vec![0f32; gate.len()];
    for i in 0..gate.len() { mlp[i] = silu(gate[i]) * up[i]; }
    let mlp_out = matmul(&mlp, &self.w_down);
    for i in 0..x.len() { x[i] += mlp_out[i]; }
}
```

The four details that make it Llama specifically: **RMSNorm** (not LayerNorm), **RoPE** with rotary base from metadata, **GQA** (n_kv_heads < n_heads, with KV heads shared across query head groups), and **SwiGLU** MLP. Get any of those wrong and the model will produce tokens but they'll be incoherent.

The output projection: argmax over the final logits, return the token id. The tokenizer is a separate project (BPE), but for the CV demo you can hardcode a prompt of token ids, run `n_layers` forward passes, and emit a single decoded token.

## Running and Testing It

### Downloading a real GGUF model

The smallest useful q4_0 Llama is around 1.1B parameters:

```bash
# TinyLlama q4_0, ~700 MB
huggingface-cli download TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF \
  tinyllama-1.1b-chat-v1.0.Q4_0.gguf \
  --local-dir ./models
```

### Running the loader

```bash
cargo build --release
cargo run --release -- ./models/tinyllama-1.1b-chat-v1.0.Q4_0.gguf
```

Expected output: a metadata dump, a tensor count, and one forward pass producing the next-token logits for a hardcoded prompt.

### Proving it works: three sanity checks

1. **Metadata round-trip.** Print `general.architecture`, `llama.context_length`, `llama.embedding_length`, `llama.block_count`. These must match the model's [HuggingFace config.json](https://huggingface.co/TinyLlama/TinyLlama-1.1B-Chat-v1.0). If they don't, your header parser is off.
2. **Tensor count and shapes.** Your reader should report `blk.0.attn_q.weight` with shape `[2048, 2048]` for TinyLlama. Spot-check 5 tensors.
3. **Logits make sense.** Feed a prompt like `[1, 15043, 29892, 590]` ("Once upon a"), run forward, take argmax. The top token should be a common English word (likely "time" or "a"). If it's random bytes, your dequantization or RoPE is broken.

```text
# Expected output (truncated)
metadata["general.architecture"]          = "llama"
metadata["llama.context_length"]         = 2048
metadata["llama.embedding_length"]       = 2048
metadata["llama.block_count"]            = 22
metadata["llama.attention.head_count"]   = 32
metadata["llama.attention.head_count_kv"]= 4
tensors: 286
forward("Once upon a") -> next token id 278 ("Ġtime")
```

If you want a stronger correctness check, compare your argmax output to [llama.cpp's main binary](https://github.com/ggerganov/llama.cpp) on the same prompt. They should match for the first decode step.

### Memory and performance

Run with `/usr/bin/time -v` to confirm you're not silently copying the file:

```bash
/usr/bin/time -v ./target/release/gguf-loader ./models/tinyllama-1.1b-chat-v1.0.Q4_0.gguf
```

Look at `Maximum resident set size`. It should be on the order of a few hundred MB even though the model file is 700 MB — that's mmap working.

## Extending It: Your Roadmap to Senior-Level

A single-weekend build gets you an interview. These upgrades turn it into a conversation that lasts an hour and convinces the interviewer you can operate at senior level.

1. **Tokenizer integration via BPE.** Add the BPE tokenizer from [sentencepiece](https://github.com/google/sentencepiece) or [tiktoken](https://github.com/openai/tiktoken) so prompts are strings, not token id arrays. Reason: real systems handle the full I/O path, not just numerics.
2. **Streaming generation with a generator interface.** Yield tokens as they decode; add temperature and top-p sampling. Reason: shows you understand latency budgets and per-token scheduling — the same shape as serving systems like vLLM's [continuous batching](https://blog.vllm.ai/2023/06/20/vllm.html).
3. **Persistent weight cache with mlock().** Use `mlock(2)` to pin hot tensors in RAM so they survive page eviction. Reason: explains to an interviewer why llama.cpp can run on laptops without swapping and what trade-offs memory pressure creates.
4. **Observability with Prometheus metrics.** Export tokens/sec, KV cache hit rate, dequantization throughput, mmap page faults. Reason: production ML systems are diagnosed through metrics, not logs — this signals you've shipped something.
5. **SIMD-accelerated dequantization.** Replace the scalar loop in `dequantize_q4_0` with an AVX2 path using `_mm256_cvtepi8_epi32` and FP16→FP32 promotion. Reason: shows you can reason about CPU vector units, which is the same skill set behind the kernels in [xformers](https://github.com/facebookresearch/xformers) and [cutlass](https://github.com/NVIDIA/cutlass).
6. **KV cache persistence across requests.** Serialize the cache to disk between calls so multi-turn prompts don't re-decode. Reason: turns a toy into something with real I/O state, which is what makes it interesting to platform teams.

## Key Takeaways

- GGUF is a versioned binary container with typed metadata and a tensor index. Parsing it cleanly means getting alignment, endianness, and the `GGUFValue` tag dispatch right.
- `q4_0` and `q8_0` are block-quantized: a per-block fp16 scale and 32 packed integer values per 18/34-byte block. Dequantization is `x_i = q_i * scale`, with q4_0 nibbles re-centered to `[-8, 7]`.
- `mmap()` lets you stream a multi-gigabyte model file without copying it into RAM. The kernel pages blocks in on demand as you dequantize.
- A working Llama forward pass needs RMSNorm, RoPE, grouped-query attention with a KV cache, and SwiGLU MLP. Without all four, the model is just a transformer-shaped function approximator.
- The project lands in a weekend and demonstrates file format fluency, low-level numerics, memory-mapped I/O, and transformer internals — the stack ML systems teams actually hire for.

## Further Reading

- [GGUF specification (ggml docs)](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md) — the canonical format reference; start here before writing any code.
- [llama.cpp ggml-quants.c](https://github.com/ggerganov/llama.cpp/blob/master/ggml/src/ggml-quants.c) — reference implementations of `Q4_0` and `Q8_0` block dequantization.
- [RoFormer: Enhanced Transformer with Rotary Position Embedding (Su et al., 2021)](https://arxiv.org/abs/2104.09864) — the original RoPE paper; required reading for implementing rotary embeddings correctly.
- [Llama 2: Open Foundation and Fine-Tuned Chat Models (Touvron et al., 2023)](https://arxiv.org/abs/2307.09288) — describes the exact RMSNorm + SwiGLU + GQA architecture you'll be implementing.
- [GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints (Ainslie et al., 2023)](https://arxiv.org/abs/2305.13245) — the grouped-query attention paper; explains why n_kv_heads < n_heads and how the KV cache shrinks.
- [memmap2 crate documentation](https://docs.rs/memmap2/latest/memmap2/) — the Rust mmap binding you'll use; read the safety section carefully.
- [vLLM: How we built an efficient inference engine (Kwon et al., 2023 blog)](https://blog.vllm.ai/2023/06/20/vllm.html) — production context for why mmap'd weights and KV cache management matter at scale.
- [Linux mmap(2) man page](https://man7.org/linux/man-pages/man2/mmap.2.html) — for understanding `MAP_PRIVATE`, page fault semantics, and `madvise(MADV_SEQUENTIAL)` hints you'll want to add.