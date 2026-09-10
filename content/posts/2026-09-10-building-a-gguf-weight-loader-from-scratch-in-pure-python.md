---
title: "Building a GGUF Weight Loader from Scratch in Pure Python"
date: "2026-09-10T00:01:30.451"
draft: false
tags: ["python", "gguf", "binary-formats", "machine-learning", "systems-engineering", "portfolio-project"]
description: "Build a minimal GGUF weight loader in pure Python with zero dependencies. Parse the binary container format — headers, metadata, tensor offsets — and extract model weights to signal real systems engineering skill."
summary: "A hands-on guide to building a zero-dependency GGUF weight loader from scratch in Python, covering the binary container format, tensor extraction, and a roadmap to production-grade features."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-10-building-a-gguf-weight-loader-from-scratch-in-pure-python.svg"
  alt: "A Python script reading a GGUF binary file, with hex dump and tensor metadata visualization."
  caption: ""
  relative: false
---

> **TL;DR** — This post walks you through building a minimal GGUF weight loader in pure Python with zero dependencies on llama.cpp. You'll parse the binary container format — header, metadata key–value pairs, and tensor chunk offsets — to extract model weights directly. The result is a portfolio project that demonstrates binary parsing, systems architecture, and ML infrastructure skills that hiring managers notice.

---

## Why This Project Stands Out on a CV

Most ML engineers can *use* a model. Far fewer can open the container that holds one and walk out with the weights. A GGUF loader built from scratch signals three distinct competencies that hiring managers and senior engineers explicitly look for:

- **Binary format fluency.** You're not reading JSON from an API — you're interpreting magic bytes, version fields, and structured arrays directly from disk. This is the same skill that underlies protocol buffer parsing, database engine work, and embedded systems programming.
- **Zero-dependency discipline.** Shipping a working parser with no external packages demonstrates you understand what the underlying format actually does, rather than relying on a framework to abstract away the details. It mirrors production constraints where you cannot always `pip install`.
- **Cross-layer understanding.** You bridge the gap between the ML modeling world and the systems infrastructure world. You understand what a tensor *is* as a mathematical object and what it *is* as a sequence of bytes on NVMe. That combination is rare and valuable for roles in ML infrastructure, inference engines, and edge deployment.

This project specifically signals readiness for roles in **ML platform engineering**, **inference optimization**, and **systems software** — positions where the line between "model" and "data" blurs.

## Architecture Overview

The loader decomposes into four cleanly separated components. Each has a single responsibility and can be tested independently.

```
┌─────────────────────────────────────────────────────┐
│                  gguf_loader/                        │
│                                                      │
│  ┌──────────────┐  ┌──────────────┐                 │
│  │  GGUFHeader  │  │ GGUFMetadata │                 │
│  │  (magic,     │  │ (key-value   │                 │
│  │   version,   │  │  pairs)      │                 │
│  │   tensor_n)  │  │              │                 │
│  └──────┬───────┘  └──────┬───────┘                 │
│         │                 │                          │
│  ┌──────▼─────────────────▼───────┐                 │
│  │      GGUFParser                │                 │
│  │  • read_header()               │                 │
│  │  • read_metadata()             │                 │
│  │  • read_tensor_definitions()   │                 │
│  │  • extract_tensor(name)        │                 │
│  └──────────────────┬─────────────┘                 │
│                     │                                │
│  ┌──────────────────▼─────────────────┐             │
│  │      GGUFTensor                    │             │
│  │  • name, shape, dtype              │             │
│  │  • offset, byte_size               │             │
│  │  • to_numpy() / to_bytes()         │             │
│  └────────────────────────────────────┘             │
└─────────────────────────────────────────────────────┘
```

The data flow is linear and deterministic:

1. **`GGUFHeader`** reads the first 16 bytes — the magic string `"GGUF"`, the version number, the tensor count, and the metadata key-value pair count. This establishes the contract for everything that follows.
2. **`GGUFMetadata`** consumes the key-value section, storing arbitrary string pairs (model name, quantization parameter, licensing info, etc.).
3. **`GGUFParser`** orchestrates the full parse. It reads tensor definitions (name, dimensionality, data type, file offset, and byte size), then uses those offsets to seek directly into the data section and extract raw bytes.
4. **`GGUFTensor`** wraps the extracted bytes, provides shape information, and offers conversion methods to NumPy arrays or raw byte buffers.

The critical insight here is that GGUF stores tensor data as a **flat sequence of chunks** — each tensor has a defined byte offset and size within the file. There is no indexing layer. The parser must compute positions correctly, which is where most bugs live.

## Building It Step by Step

We'll build this incrementally. Each step adds a component. The full codebase is runnable with nothing but Python 3.8+ and NumPy (used only for the final array conversion — the parser itself has zero dependencies).

### Step 1: Define the Constants and Header Structure

The GGUF format begins with a 4-byte magic, followed by a `uint32` version, a `uint64` tensor count, and a `uint64` metadata count. All integers are little-endian.

```python
import struct
from dataclasses import dataclass
from typing import Dict, List, Tuple

# GGUF magic bytes and dtype codes
GGUF_MAGIC = b"GGUF"

# Quantization type codes (subset of llama.cpp's ggml_type enum)
DT_TYPES = {
    0: "F32",   # float32
    1: "F16",   # float16
    2: "Q4_0",  # 4-bit quantized
    3: "Q4_1",  # 4-bit quantized
    4: "Q5_0",  # 5-bit quantized
    5: "Q5_1",  # 5-bit quantized
    6: "Q8_0",  # 8-bit quantized
    7: "Q8_1",  # 8-bit quantized
    8: "Q4_0_S",
    9: "Q4_1_S",
    10: "Q4_K_S",
    11: "Q4_K_M",
    12: "Q5_K_S",
    13: "Q5_K_M",
    14: "Q6_K",
    15: "Q8_K",
    16: "I8",
    17: "I16",
    18: "I32",
    19: "I64",
    20: "BOOLEAN",
    21: "COUNT",
}

@dataclass
class GGUFHeader:
    version: int
    tensor_count: int
    metadata_count: int

    @classmethod
    def from_file(cls, f):
        magic = f.read(4)
        if magic != GGUF_MAGIC:
            raise ValueError(f"Not a GGUF file. Got magic: {magic!r}")
        version, tensor_count, metadata_count = struct.unpack("<III", f.read(12))
        return cls(version=version, tensor_count=tensor_count, metadata_count=metadata_count)
```

The `<III` format string in `struct.unpack` means: little-endian, three unsigned 32-bit integers. Note that the tensor count and metadata count are `uint64` in the spec but many real files use values that fit in `uint32`. For full spec compliance, use `<QII` — we'll correct this in the production version.

### Step 2: Parse Metadata Key-Value Pairs

After the header, the file contains a sequence of key-value pairs. Each pair is prefixed by the key length and value length (both `uint64`), followed by the raw bytes.

```python
@dataclass
class GGUFMetadata:
    pairs: Dict[str, str]

    @classmethod
    def from_file(cls, f, count: int) -> "GGUFMetadata":
        pairs = {}
        for _ in range(count):
            key_len = struct.unpack("<Q", f.read(8))[0]
            key = f.read(key_len).decode("utf-8")
            val_len = struct.unpack("<Q", f.read(8))[0]
            val = f.read(val_len).decode("utf-8")
            pairs[key] = val
        return cls(pairs=pairs)

    def get(self, key: str, default: str = None) -> str:
        return self.pairs.get(key, default)
```

Common metadata keys you'll encounter in real GGUF files include `general.name`, `llama.attention.head_count`, `tokenizer.model`, and `quantization_version`. These are the same keys that `llama.cpp` uses to configure the model at load time.

### Step 3: Parse Tensor Definitions

Each tensor definition contains: the name length and name string, the number of dimensions, the dimension array, the quantization type (as a `uint32`), the file offset (`uint64`), and the total byte size (`uint64`).

```python
@dataclass
class GGUFTensor:
    name: str
    shape: List[int]
    dtype_code: int
    dtype: str
    offset: int
    byte_size: int

    @classmethod
    def from_file(cls, f) -> "GGUFTensor":
        name_len = struct.unpack("<Q", f.read(8))[0]
        name = f.read(name_len).decode("utf-8")

        n_dims = struct.unpack("<I", f.read(4))[0]
        # Dimensions are stored in reverse order in GGUF (last dimension first)
        dims = list(struct.unpack(f"<{n_dims}q", f.read(8 * n_dims)))
        dims.reverse()  # Convert to natural (C-style) order

        dtype_code = struct.unpack("<I", f.read(4))[0]
        dtype = DT_TYPES.get(dtype_code, f"UNKNOWN_{dtype_code}")

        offset, byte_size = struct.unpack("<QQ", f.read(16))

        return cls(
            name=name,
            shape=dims,
            dtype_code=dtype_code,
            dtype=dtype,
            offset=offset,
            byte_size=byte_size,
        )
```

The dimension reversal is a subtle but critical detail. GGUF stores dimensions in **reverse order** compared to the standard NumPy/PyTorch convention. A tensor with shape `[768, 4096]` in PyTorch is stored as `[4096, 768]` in the GGUF header. Getting this wrong means your weight matrices are transposed silently — a bug that's nearly impossible to catch without comparing against known values.

### Step 4: Build the Parser and Extract Weights

The parser ties everything together. It opens the file, reads the header, metadata, and tensor definitions, and provides a method to extract any tensor by name.

```python
class GGUFParser:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.header: GGUFHeader = None
        self.metadata: GGUFMetadata = None
        self.tensors: List[GGUFTensor] = []
        self._tensor_index: Dict[str, GGUFTensor] = {}

    def parse(self):
        with open(self.filepath, "rb") as f:
            self.header = GGUFHeader.from_file(f)
            self.metadata = GGUFMetadata.from_file(
                f, self.header.metadata_count
            )
            self.tensors = [
                GGUFTensor.from_file(f)
                for _ in range(self.header.tensor_count)
            ]
            # Build a name-based lookup for O(1) access
            self._tensor_index = {t.name: t for t in self.tensors}
        return self

    def get_tensor(self, name: str) -> GGUFTensor:
        if name not in self._tensor_index:
            available = list(self._tensor_index.keys())[:5]
            raise KeyError(
                f"Tensor '{name}' not found. Available: {available}..."
            )
        tensor = self._tensor_index[name]
        with open(self.filepath, "rb") as f:
            f.seek(tensor.offset)
            raw_bytes = f.read(tensor.byte_size)
        tensor.data = raw_bytes
        return tensor

    def list_tensors(self) -> List[str]:
        return [t.name for t in self.tensors]

    def summary(self) -> str:
        return (
            f"GGUF v{self.header.version} — "
            f"{self.header.tensor_count} tensors, "
            f"{len(self.metadata.pairs)} metadata entries\n"
            f"Model: {self.metadata.get('general.name', 'unknown')}\n"
            f"Sample tensors: {', '.join(self.list_tensors()[:5])}..."
        )
```

### Step 5: Convert Extracted Bytes to Usable Arrays

The final step is converting raw bytes into NumPy arrays. For quantized types, this requires dequantization logic — but for the minimal loader, we'll handle the unquantized types (`F32`, `F16`) and leave quantized types as raw byte buffers.

```python
import numpy as np

def tensor_to_numpy(tensor: GGUFTensor) -> np.ndarray:
    """Convert a GGUF tensor's raw bytes to a NumPy array."""
    dtype_map = {
        0: np.float32,   # F32
        1: np.float16,   # F16
        16: np.int8,     # I8
        17: np.int16,    # I16
        18: np.int32,    # I32
    }
    np_dtype = dtype_map.get(tensor.dtype_code)
    if np_dtype is None:
        raise NotImplementedError(
            f"Dtype {tensor.dtype} (code {tensor.dtype_code}) "
            f"requires custom dequantization. "
            f"Return raw bytes instead."
        )
    arr = np.frombuffer(tensor.data, dtype=np_dtype)
    return arr.reshape(tensor.shape)
```

For quantized types like `Q4_0` or `Q5_1`, you'd need to implement the dequantization kernel described in the [llama.cpp source](https://github.com/ggerganov/llama.cpp/blob/master/ggml-common.h) — specifically the `ggml_quantize_q4_0` and `ggml_dequantize_q4_0` functions. That's a substantial undertaking on its own and is an excellent extension target.

## Running and Testing It

### Local Setup

```bash
# Create a clean virtual environment
python -m venv .venv
source .venv/bin/activate

# Install only numpy (the parser itself needs nothing)
pip install numpy

# Download a small GGUF model for testing
# The Hugging Face hub has many quantized models
pip install huggingface_hub
python -c "
from huggingface_hub import hf_hub_download
path = hf_hub_download(
    'bartowski/Meta-Llama-3-8B-Instruct-GGUF',
    'Meta-Llama-3-8B-Instruct.Q4_K_M.gguf',
    local_dir='./models'
)
print(f'Downloaded to {path}')
"
```

### Running the Loader

```python
from gguf_loader import GGUFParser

parser = GGUFParser("./models/Meta-Llama-3-8B-Instruct.Q4_K_M.gguf")
parser.parse()

# Print a summary of the file
print(parser.summary())

# List all tensor names
for name in parser.list_tensors()[:10]:
    print(f"  {name}")

# Extract a specific weight tensor
tok_embeddings = parser.get_tensor("tok_embeddings.weight")
print(f"\nTensor: {tok_embeddings.name}")
print(f"Shape: {tok_embeddings.shape}")
print(f"Dtype: {tok_embeddings.dtype}")
print(f"File offset: {tok_embeddings.offset}")
print(f"Byte size: {tok_embeddings.byte_size}")

# Convert to NumPy (works for F32/F16 tensors)
# For quantized models, extract a metadata value instead
version = parser.metadata.get("quantization_version", "unknown")
print(f"\nQuantization version: {version}")
```

### Writing Unit Tests

```python
# test_gguf_loader.py
import pytest
import tempfile
import struct
import os
from gguf_loader import GGUFParser, GGUFHeader, GGUFMetadata, GGUFTensor

def _write_minimal_gguf(path: str):
    """Create a minimal valid GGUF file for testing."""
    with open(path, "wb") as f:
        # Header
        f.write(b"GGUF")
        f.write(struct.pack("<III", 3, 1, 2))  # version=3, 1 tensor, 2 metadata
        # Metadata: key 'general.name', value 'test-model'
        f.write(struct.pack("<Q", len("general.name")))
        f.write(b"general.name")
        f.write(struct.pack("<Q", len("test-model")))
        f.write(b"test-model")
        # Metadata: key 'llama.attention.head_count', value '32'
        f.write(struct.pack("<Q", len("llama.attention.head_count")))
        f.write(b"llama.attention.head_count")
        f.write(struct.pack("<Q", len("32")))
        f.write(b"32")
        # Tensor definition
        f.write(struct.pack("<Q", len("test.weight")))
        f.write(b"test.weight")
        f.write(struct.pack("<I", 2))            # 2 dims
        f.write(struct.pack("<qq", 128, 256))    # reversed dims
        f.write(struct.pack("<I", 0))            # dtype F32
        f.write(struct.pack("<QQ", 128, 131072)) # offset=128, byte_size=128*256*4
        # Tensor data (128*256*4 bytes of zeros)
        f.write(b"\x00" * (128 * 256 * 4))

def test_header_parsing():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _write_minimal_gguf(tmp.name)
        parser = GGUFParser(tmp.name)
        parser.parse()
        assert parser.header.version == 3
        assert parser.header.tensor_count == 1
        assert parser.header.metadata_count == 2
        os.unlink(tmp.name)

def test_metadata_parsing():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _write_minimal_gguf(tmp.name)
        parser = GGUFParser(tmp.name)
        parser.parse()
        assert parser.metadata.get("general.name") == "test-model"
        assert parser.metadata.get("llama.attention.head_count") == "32"
        os.unlink(tmp.name)

def test_tensor_extraction():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        _write_minimal_gguf(tmp.name)
        parser = GGUFParser(tmp.name)
        parser.parse()
        tensor = parser.get_tensor("test.weight")
        assert tensor.shape == [256, 128]  # reversed back to natural order
        assert tensor.offset == 128
        os.unlink(tmp.name)

def test_invalid_magic():
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(b"NOTG")
        tmp.flush()
        with pytest.raises(ValueError):
            GGUFParser(tmp.name).parse()
        os.unlink(tmp.name)
```

Run with `pytest test_gguf_loader.py -v`. All four tests should pass.

## Extending It: Your Roadmap to Senior-Level

The minimal loader is a strong portfolio piece. The following upgrades transform it into something that mirrors production ML infrastructure and demonstrates engineering maturity at a senior level.

1. **Add a memory-mapped I/O layer using `mmap`.** Instead of `f.read()` and `f.seek()`, map the entire GGUF file into virtual memory. This eliminates repeated syscalls and is how `llama.cpp` itself achieves fast model loading on large files (7B+ parameter models can be 4–8 GB). It signals you understand how operating systems manage file I/O and why zero-copy reads matter at scale.

2. **Implement a full dequantization engine for Q4_K_M and Q5_K_S.** These are the most common quantization types in production GGUF files. Writing the dequantization kernels requires understanding bit-packing, lookup tables, and the mathematical rationale behind different quantization schemes. This is the single highest-value addition you can make — it's the difference between reading a model and actually running it.

3. **Add structured logging and observability with `logging` and OpenTelemetry.** Instrument every parse step — header read, metadata consumption, tensor extraction — with timing metrics and structured log events. Export them to a local OTLP endpoint. This demonstrates you understand that production systems aren't just correct; they're observable. A hiring manager who has ever debugged a silent model load failure at 2 AM will appreciate this immediately.

4. **Build a tensor caching layer with LRU eviction.** When loading large models, not all tensors are needed simultaneously. Implement an LRU cache that holds recently accessed tensors in memory and evicts them when a memory budget is exceeded. This directly mirrors how inference engines manage GPU memory and signals you understand the tension between latency and capacity.

5. **Add a gRPC or REST API wrapper around the parser.** Expose the loader as a microservice with endpoints like `GET /tensor/{name}` and `GET /metadata`. Containerize it with Docker and add a `docker-compose.yml` for local testing. This transforms a script into a service and demonstrates you can think in terms of distributed systems, not just functions.

6. **Implement a benchmarking harness comparing your parser against `llama.cpp`'s `llama-cli` load time.** Use Python's `timeit` or `pytest-benchmark` to measure parse latency across model sizes. Plot the results with `matplotlib`. This is the kind of empirical, data-driven engineering that separates senior engineers from everyone else — you're not guessing about performance, you're measuring it.

## Key Takeaways

- A GGUF loader built from scratch demonstrates **binary parsing, zero-dependency discipline, and cross-layer ML-systems understanding** — three skills that are rare and highly valued.
- The GGUF format is **linear and offset-based**: tensors are defined by name, shape, dtype, file offset, and byte size. There is no internal index, so correctness depends entirely on computing positions accurately.
- **Dimension reversal** is a critical gotcha — GGUF stores shapes in reverse order compared to standard frameworks. Missing this produces silently transposed weight matrices.
- The minimal implementation uses only Python's `struct` module and can be extended with `numpy` for array conversion. Quantized types require implementing dequantization kernels from the [llama.cpp source](https://github.com/ggerganov/llama.cpp).
- The extension roadmap — `mmap`, full dequantization, observability, caching, API wrapping, and benchmarking — maps directly to senior-level engineering competencies in ML infrastructure.

## Further Reading

- [GGUF Format Specification](https://github.com/ggerganov/llama.cpp/blob/master/docs/gguf.md) — The canonical specification maintained by Georgi Gerganov. This is the primary source document that defines every field, data type, and version change in the format. Study it before writing a single line of parsing code.
- [llama.cpp source: ggml-common.h](https://github.com/ggerganov/llama.cpp/blob/master/ggml-common.h) — The dequantization kernels and quantization type definitions live here. If you want to implement full dequantization, this is where the actual bit-twiddling logic resides.
- [Hugging Face GGUF Model Hub](https://huggingface.co/models?other=gguf) — The primary repository of GGUF-converted models. Download test files of varying sizes to benchmark your parser and validate edge cases across different quantization types.
- [Python struct Module Documentation](https://docs.python.org/3/library/struct.html) — The official reference for `struct.pack` and `struct.unpack`. Essential for understanding format strings, byte order, and alignment — the foundation of all binary parsing in Python.
- [Memory-Mapped File I/O in Python](https://docs.python.org/3/library/mmap.html) — The `mmap` module documentation. Study this when implementing the memory-mapped I/O upgrade from the extension roadmap.
- [OpenTelemetry Python SDK](https://opentelemetry.io/docs/instrumentation/python/getting-started/) — The canonical getting-started guide for adding observability to Python services. Use this when implementing the logging and metrics upgrade.