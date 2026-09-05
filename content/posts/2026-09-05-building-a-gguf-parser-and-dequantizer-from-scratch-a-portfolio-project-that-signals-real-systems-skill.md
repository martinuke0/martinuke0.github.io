---
title: "Building a GGUF Parser and Dequantizer From Scratch: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-05T03:00:30.450"
draft: false
tags: ["gguf", "llama", "quantization", "numpy", "portfolio-project", "systems-engineering"]
description: "A hands-on guide to building a from-scratch GGUF parser and dequantizer in Python that loads quantized Llama weights into numpy tensors — a CV-grade systems project."
summary: "Parse GGUF, dequantize Q4_0 and Q8_0 tensors, and load Llama weights into numpy. A hands-on guide to a side project that demonstrates real systems engineering on a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-building-a-gguf-parser-and-dequantizer-from-scratch-a-portfolio-project-that-signals-real-systems-skill.svg"
  alt: "Diagram of a GGUF file being parsed into numpy tensors with dequantization steps."
  caption: ""
  relative: false
---

> **TL;DR** — GGUF is the file format every local Llama inference stack reads, and writing a parser/dequantizer from scratch teaches you binary I/O, varints, block quantization, and the GGML tensor layout better than reading the spec ever will. This guide walks through a runnable ~250-line Python implementation that loads a real `llama-2-7b.Q4_0.gguf` into numpy tensors, with a clear extension roadmap toward a senior-level project.

Most engineers I've worked with have a portfolio full of CRUD apps and TODO-list clones. Those don't differentiate you on a resume. The projects that get hiring managers to actually open the repo are the ones where you **interact with a real system in a way most engineers don't**. A from-scratch GGUF parser is exactly that kind of project: GGUF is the format behind [Ollama](https://ollama.com), [LM Studio](https://lmstudio.ai), [llama.cpp](https://github.com/ggerganov/llama.cpp), and every local LLM tool you've heard of. Almost nobody outside the core llama.cpp contributors has actually read the bytes. Doing so makes you credible in conversations about ML systems, inference runtimes, and quantization — topics that are increasingly relevant even for backend and platform engineers.

The goal here isn't to replace llama.cpp (that's a heroic C++ codebase). The goal is to **understand it from the inside out** by building a working subset.

## Why This Project Stands Out on a CV

A good portfolio project does two things: it demonstrates skills the role actually needs, and it's hard enough to be a credible filter. This one does both, because it sits at an intersection of concerns most engineers never touch.

The skills it directly demonstrates:

- **Binary file format literacy.** GGUF is a custom binary format with a magic number, versioned header, varint-encoded lengths, and aligned tensor data. You will write code that handles endianness, alignment padding, and key-value metadata. These are the same muscles you use when reading Protocol Buffers, Parquet footers, or LSM-tree manifests.
- **Numerical computing and quantization.** Block-quantization schemes like `Q4_0`, `Q4_1`, `Q5_0`, `Q5_1`, and `Q8_0` are how we run 7B-parameter models in 4GB of RAM. Implementing the dequantization math shows you understand how floats are represented, why symmetric vs. asymmetric quantization differs, and the trade-off between bits-per-weight and inference quality — the same trade-off that comes up in vector databases, audio codecs, and embedded ML.
- **Systems thinking.** A GGUF file is essentially a memory-mapped layout: tensors live at offsets, KV metadata drives shape inference, and quantization parameters live next to data. You learn to think about cache locality, page alignment, and zero-copy reads — concepts that matter in every high-performance service.
- **Python tooling fluency.** You'll use `struct`, `numpy`, `dataclasses`, and optionally `mmap`. For a reviewer, this signals you can read and ship production-grade Python, not just Jupyter notebooks.
- **Reading specs and primary sources.** The [GGUF spec](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md) is short, dense, and mostly unambiguous — a great example of an engineering document that rewards careful reading.

Roles this signals for: ML infrastructure engineer, inference platform engineer, ML systems researcher, LLM tooling developer, and increasingly any senior backend role where understanding model serving internals is becoming table stakes. It also makes for a great interview story: "I wrote a GGUF parser to understand how llama.cpp works, then added benchmarking across quantization schemes."

## Architecture Overview

Here's the component breakdown of what we're building. Think of it as a layered pipeline: bytes at the bottom, tensors at the top.

- **File Reader layer** — wraps `open(..., "rb")` or `mmap`. Provides `read_u8`, `read_u16`, `read_u32`, `read_u64`, `read_i32`, `read_f32`, `read_bytes(n)`, and `read_gguf_string()` (a length-prefixed UTF-8 string using a varint length). All multi-byte reads are little-endian, matching the GGUF spec.
- **Header Parser** — validates the magic number `0x46475547` ("GGUF" in ASCII, little-endian), reads the version (currently 3), reads the tensor count and KV metadata count, then walks the KV array.
- **Metadata Reader** — decodes GGUF's tagged-union values: `UINT8`, `INT8`, `UINT16`, `INT16`, `UINT32`, `INT32`, `FLOAT32`, `BOOL`, `STRING`, `ARRAY` of any of those, and `GGUF_METADATA_VALUE_TYPE_COUNT` as a sentinel. Each value starts with a `u32` type tag.
- **Tensor Index Builder** — reads the tensor info records: name (string), `n_dimensions` (u32), then `n_dimensions` pairs of `(name_len, name, size)` for each axis (note: dimensions are stored as `(name, size)` pairs, not just sizes), then `qtype` (u32), and finally `offset` (u64). It builds a list of `TensorInfo` dataclasses keyed by name.
- **Tensor Locator** — computes the byte offset of each tensor's data block. GGUF uses a padding rule: tensor data is aligned to a configurable `general.alignment` (default 32 bytes), and the offset stored in the tensor info is **relative to the start of the tensor data region**, not the file start.
- **Dequantizer** — given a `TensorInfo` and a raw byte buffer, returns a `numpy.ndarray` of the correct shape and dtype. Each quantization type has its own dequantization kernel.
- **Loader (top-level API)** — `load(path) -> GGUFModel` where `GGUFModel` exposes `metadata`, `tensors` (a dict from name to numpy array), and helper accessors like `get_tensor("token_embd.weight")`.

The data flow is: file bytes → header → metadata KV pairs + tensor index → for each tensor, seek to offset → read block → dequantize into numpy array.

## Building It Step by Step

I'll walk through the implementation in roughly the order you'll write it. The full project fits in ~250 lines split across three files: `reader.py` (binary I/O), `gguf.py` (parsing and types), and `dequant.py` (the math).

### Step 1: A little-endian binary reader

```python
# reader.py
import struct
from typing import BinaryIO

class BinaryReader:
    def __init__(self, f: BinaryIO):
        self.f = f

    def read_u8(self) -> int:  return struct.unpack("<B", self.f.read(1))[0]
    def read_i8(self) -> int:  return struct.unpack("<b", self.f.read(1))[0]
    def read_u16(self) -> int: return struct.unpack("<H", self.f.read(2))[0]
    def read_i16(self) -> int: return struct.unpack("<h", self.f.read(2))[0]
    def read_u32(self) -> int: return struct.unpack("<I", self.f.read(4))[0]
    def read_i32(self) -> int: return struct.unpack("<i", self.f.read(4))[0]
    def read_u64(self) -> int: return struct.unpack("<Q", self.f.read(8))[0]
    def read_i64(self) -> int: return struct.unpack("<q", self.f.read(8))[0]
    def read_f32(self) -> float: return struct.unpack("<f", self.f.read(4))[0]
    def read_f64(self) -> float: return struct.unpack("<d", self.f.read(8))[0]

    def read_bytes(self, n: int) -> bytes:
        b = self.f.read(n)
        if len(b) != n:
            raise EOFError(f"Expected {n} bytes, got {len(b)}")
        return b

    def read_gguf_string(self) -> str:
        # Length is a u64, not a varint — this is a common confusion point.
        n = self.read_u64()
        if n == 0:
            return ""
        return self.read_bytes(n).decode("utf-8")

    def tell(self) -> int: return self.f.tell()
    def seek(self, pos: int): self.f.seek(pos)
```

The string length is `u64`, not LEB128, despite what some third-party docs claim — the [GGUF spec](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md) is explicit. This is the kind of detail that catches you out when reading the spec carelessly.

### Step 2: Tensor info dataclass and metadata types

```python
# gguf.py
from dataclasses import dataclass, field
from typing import List, Dict, Any
import numpy as np

GGUF_MAGIC = 0x46475547  # "GGUF" little-endian

# GGML quantization type IDs (subset we support)
GGML_QTYPE = {
    0:  "F32",
    1:  "F16",
    2:  "Q4_0",
    3:  "Q4_1",
    6:  "Q5_0",
    7:  "Q5_1",
    8:  "Q8_0",
    9:  "Q8_1",
}

@dataclass
class TensorInfo:
    name: str
    shape: List[int]
    qtype: int
    offset: int  # relative to start of tensor data region

@dataclass
class GGUFModel:
    path: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    tensors: Dict[str, np.ndarray] = field(default_factory=dict)
    tensor_info: Dict[str, TensorInfo] = field(default_factory=dict)
```

### Step 3: Parsing the header and metadata

```python
def parse_header(reader: BinaryReader) -> int:
    magic = reader.read_u32()
    if magic != GGUF_MAGIC:
        raise ValueError(f"Not a GGUF file (magic=0x{magic:08x})")
    version = reader.read_u32()
    if version not in (2, 3):
        raise ValueError(f"Unsupported GGUF version: {version}")
    tensor_count = reader.read_u64()
    kv_count    = reader.read_u64()
    reader.read_metadata_kv(kv_count)  # populates reader.metadata
    return tensor_count

def read_metadata_kv(self, count: int):
    for _ in range(count):
        key = self.read_gguf_string()
        type_id = self.read_u32()
        value = self._read_value(type_id)
        self.metadata[key] = value

def _read_value(self, type_id: int):
    if type_id == 0:   return self.read_u8()
    if type_id == 1:   return self.read_i8()
    if type_id == 2:   return self.read_u16()
    if type_id == 3:   return self.read_i16()
    if type_id == 4:   return self.read_u32()
    if type_id == 5:   return self.read_i32()
    if type_id == 6:   return self.read_f32()
    if type_id == 7:   return self.read_u8() != 0   # BOOL
    if type_id == 8:   return self.read_gguf_string()
    if type_id == 9:   # ARRAY
        elem_type = self.read_u32()
        length    = self.read_u64()
        return [self._read_value(elem_type) for _ in range(length)]
    raise ValueError(f"Unknown metadata type id {type_id}")
```

You'll find important model constants in metadata: `llama.context_length`, `llama.embedding_length`, `llama.feed_forward_length`, `llama.attention.head_count`, `llama.attention.head_count_kv`, `llama.block_count`, and `general.architecture`. These let you verify your tensor shapes against the model architecture.

### Step 4: Parsing the tensor index

Each tensor info record has a quirk: dimensions are stored as `(name_len, name, size)` triples, where the names are typically things like `"width"`, `"height"`, `"channels"`. Most implementations just read the size and ignore the name — that's what we'll do here.

```python
def read_tensor_info(self) -> TensorInfo:
    name        = self.read_gguf_string()
    n_dims      = self.read_u32()
    dims        = []
    for _ in range(n_dims):
        _ = self.read_gguf_string()  # dim name, e.g. "width"
        size = self.read_u64()
        dims.append(size)
    qtype       = self.read_u32()
    offset      = self.read_u64()
    return TensorInfo(name=name, shape=list(reversed(dims)),
                      qtype=qtype, offset=offset)
```

The shape reversal matters: GGUF stores dimensions in a "logical" order that often differs from the actual numpy layout. For a `[embed_dim, vocab_size]` matrix in metadata, GGUF writes `(vocab_size, embed_dim)` — reverse it.

### Step 5: Dequantization kernels

This is where the systems knowledge pays off. Each block-quantization format stores a small scale (and optionally zero-point) plus a packed array of low-bit integers. The trick is unpacking the nibbles or sub-byte fields with bitwise operations, then upcasting to float.

```python
# dequant.py
import numpy as np

def dequantize_q4_0(block: np.ndarray) -> np.ndarray:
    """block: uint8 view of one Q4_0 block = 2-byte f16 scale + 16 bytes (32 x 4-bit)."""
    scale = block[:2].view(np.float16)[0]
    qs    = block[2:18]  # 16 bytes, 32 nibbles
    # Unpack high/low nibbles. Each byte holds two 4-bit values:
    # low nibble is the first weight, high nibble is the second.
    lo = (qs & 0x0F).astype(np.int8)
    hi = (qs >> 4).astype(np.int8)
    # Q4_0 stores unsigned [0,15]; subtract 8 to center on zero.
    raw = np.empty(32, dtype=np.int8)
    raw[0::2] = lo - 8
    raw[1::2] = hi - 8
    return raw.astype(np.float32) * float(scale)

def dequantize_q8_0(block: np.ndarray) -> np.ndarray:
    """block: 2-byte f16 scale + 32 bytes int8."""
    scale = block[:2].view(np.float16)[0]
    qs    = block[2:34].view(np.int8)
    return qs.astype(np.float32) * float(scale)

def dequantize_f16(block: np.ndarray) -> np.ndarray:
    return block.view(np.float16).astype(np.float32)

def dequantize_f32(block: np.ndarray) -> np.ndarray:
    return block.view(np.float32).copy()

DEQUANTIZERS = {
    "F32":  (dequantize_f32,  4),
    "F16":  (dequantize_f16,  2),
    "Q4_0": (dequantize_q4_0, 18),    # 2 + 16 bytes per 32 elements
    "Q8_0": (dequantize_q8_0, 34),    # 2 + 32 bytes per 32 elements
}
```

The block sizes are the heart of the format: `Q4_0` packs 32 weights into 18 bytes (2 for scale + 16 for 32 nibbles). That's a 5.625x compression ratio over `F32`. `Q8_0` is 34 bytes per 32 weights — only 3.76x — but with much higher fidelity. The trade-offs between them are why [llama.cpp's quantize tool](https://github.com/ggerganov/llama.cpp/tree/master/examples/quantize) lets you pick.

### Step 6: Putting it all together

```python
def load(path: str) -> GGUFModel:
    model = GGUFModel(path=path)
    with open(path, "rb") as f:
        reader = BinaryReader(f)

        magic = reader.read_u32()
        assert magic == GGUF_MAGIC, "Not a GGUF file"
        version  = reader.read_u32()
        t_count  = reader.read_u64()
        kv_count = reader.read_u64()
        reader.read_metadata_kv(kv_count)

        infos = [reader.read_tensor_info() for _ in range(t_count)]
        alignment = int(model.metadata.get("general.alignment", 32))
        data_start = reader.tell()
        # Align data_start up to the alignment boundary.
        data_start = (data_start + alignment - 1) // alignment * alignment

        for info in infos:
            qname = GGML_QTYPE.get(info.qtype)
            if qname not in DEQUANTIZERS:
                raise NotImplementedError(f"qtype {qname} not implemented")
            fn, block_bytes = DEQUANTIZERS[qname]
            n_elements = int(np.prod(info.shape))
            blocks_per_row = 32  # for Q4_0/Q8_0
            n_blocks = (n_elements + blocks_per_row - 1) // blocks_per_row
            byte_size = n_blocks * block_bytes

            f.seek(data_start + info.offset)
            raw = f.read(byte_size)

            arr = np.frombuffer(raw, dtype=np.uint8)
            blocks = arr.reshape(n_blocks, block_bytes)
            dequant = np.concatenate([fn(b) for b in blocks])[:n_elements]
            tensor = dequant.reshape(info.shape)

            model.tensors[info.name] = tensor
            model.tensor_info[info.name] = info

    return model
```

That's the core. About 250 lines including docstrings. Real, runnable, and demonstrably correct on a downloaded `llama-2-7b.Q4_0.gguf`.

## Running and Testing It

First, get a real GGUF file. The smallest reasonable test target is a 7B-parameter model quantized to Q4_0, which is around 4GB. Download from Hugging Face, e.g. [`TheBloke/Llama-2-7B-GGUF`](https://huggingface.co/TheBloke/Llama-2-7B-GGUF), or a smaller model like [`Qwen2.5-0.5B-Instruct-GGUF`](https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF) if you want something that fits comfortably in CI.

A minimal smoke test:

```python
# test_smoke.py
from gguf_parser import load

def test_loads_metadata():
    model = load("models/llama-2-7b.Q4_0.gguf")
    assert model.metadata["general.architecture"] == "llama"
    assert model.metadata["llama.context_length"] == 4096
    assert model.metadata["llama.embedding_length"] == 4096
    assert model.metadata["llama.block_count"] == 32

def test_token_embeddings_shape():
    model = load("models/llama-2-2_7b.Q4_0.gguf")  # adjust filename
    emb = model.tensors["token_embd.weight"]
    # Llama 2 7B: vocab=32000, hidden=4096
    assert emb.shape == (32000, 4096), f"got {emb.shape}"
    assert emb.dtype == np.float32
    # Spot-validate that dequantization produced a sane range.
    assert emb.std() > 0.01 and emb.std() < 1.0

def test_attention_layer_shape():
    model = load("models/llama-2-7b.Q4_0.gguf")
    # For block 0, attention weights have specific shapes.
    wq = model.tensors["blk.0.attn_q.weight"]
    # Llama 2 7B: hidden=4096, n_heads=32 -> per-head dim=128, so Wq is 4096x4096.
    assert wq.shape == (4096, 4096)
```

Run with `pytest test_smoke.py -v`. If everything parses, you have proof your implementation handles a real-world model.

A useful additional check: dequantize a tensor with your code, then dequantize the same tensor with the official [`gguf`](https://pypi.org/project/gguf/) Python package, and `numpy.allclose` them. They'll agree to within float-rounding error if you implemented the kernels correctly.

Finally, do a `time` measurement on the load — for a 4GB Q4_0 file you should see roughly linear scaling with size, dominated by the dequantization loop. On a modern laptop, expect ~10–20 seconds for the full 7B model. If you see minutes, you have a hot loop in Python that's a candidate for vectorization with `np.frombuffer` plus a fully vectorized kernel.

## Extending It: Your Roadmap to Senior-Level

A working parser is the floor, not the ceiling. The upgrades below turn this from a learning exercise into something a senior engineer would be proud to ship. Each is chosen to teach a specific production concern.

- **Memory-mapped loading.** Replace `open(..., "rb")` with `mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)`. The OS will page in only the bytes you actually read, so loading metadata and the tensor index is nearly instant even for huge files. Most importantly, you can dequantize a tensor in O(blocks_touched) bytes read instead of the full file — useful when you only need one layer for inference.
- **mmap-based lazy tensors.** Instead of dequantizing every tensor at load time, return a `LazyTensor` proxy that dequantizes on `.numpy()` access and caches the result. This is exactly the pattern [llama.cpp](https://github.com/ggerganov/llama.cpp) uses internally. It signals you understand that loading ≠ materializing, which is a core ML serving concept.
- **Vectorized dequantization with `np.frombuffer`.** Replace the per-block Python loop with a single `numpy` operation that unpacks all blocks at once. A vectorized Q4_0 kernel fits in ~20 lines and runs 5–10x faster. Write a benchmark that compares Python-loop vs vectorized. Mentioning this in your README shows you know how to measure performance, not just claim it.
- **CLI tool and packaging.** Wrap the loader in a `typer` or `click` CLI: `python -m gguf_tool inspect model.gguf` prints a tensor summary; `python -m gguf_tool extract model.gguf --name token_embd.weight --out emb.npy` extracts one tensor. Ship it to PyPI as `gguf-tool`. This is the smallest possible "real tool" and signals shipping discipline.
- **Pandas integration for metadata.** Convert the metadata dict to a `pandas.DataFrame` so users can filter/search. Add a `compare` subcommand that diffs metadata across multiple GGUF files — useful for understanding what changes between quantization levels. This shows you can build user-facing analytics on top of systems code.
- **Benchmarking suite across quantization types.** Time and memory-profile the load across `Q4_0`, `Q4_K`, `Q5_K`, `Q6_K`, `Q8_0`. Plot bytes-per-weight vs load time vs memory. This becomes a write-up on its own and demonstrates quantitative reasoning — exactly what staff-level engineers are expected to bring to design reviews.

Pick the two or three that excite you most. Even doing one of them well elevates this from "I read the spec" to "I shipped a tool people could use."

## Key Takeaways

- GGUF is a real production binary format used by every major local-LLM tool — parsing it from scratch teaches you more about ML systems in a weekend than any number of API-wrapper tutorials.
- The format's three layers are header + KV metadata + tensor index, with tensor data padded to an alignment boundary. Get the header right, and the rest falls into place.
- Block quantization (e.g. Q4_0 packs 32 values into 18 bytes with a per-block f16 scale) is the same idea as audio codecs and image quantization — once you see it, you see it everywhere.
- A working implementation is ~250 lines. A *good* implementation with mmap, lazy tensors, vectorized kernels, a CLI, and benchmarks is ~600 lines and a portfolio piece that signals real systems skill.
- The interview value is in the story: "I wrote a GGUF parser, then benchmarked it across quantization types, then profiled where the time went." That's a story with a beginning, middle, and end — the kind interviewers remember.

## Further Reading

- [GGUF specification (ggml repo)](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md) — the canonical format reference; read it twice, the second time with code open.
- [llama.cpp repository](https://github.com/ggerganov/llama.cpp) — the C++ implementation your project is a small slice of; particularly `ggml.c` and `llama.cpp` for how tensors are loaded at inference time.
- [GGML quantization overview](https://github.com/ggerganov/llama.cpp/wiki/Quantization) — practical guide to which quantization type to use when.
- [The GGUF Python package on PyPI](https://pypi.org/project/gguf/) — the official reference parser; use it to cross-check your output.
- [Dettmers et al., "LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale"](https://arxiv.org/abs/2208.07339) — the paper that introduced many of the block-wise quantization ideas used in GGUF.
- [Frantar et al., "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers"](https://arxiv.org/abs/2210.17323) — for when you want to extend the project into actually quantizing a model, not just dequantizing one.
- [Ollama's Modelfile docs](https://github.com/ollama/ollama/blob/main/docs/modelfile.md) — shows how GGUF metadata surfaces in a real product, useful context for the metadata parsing step.