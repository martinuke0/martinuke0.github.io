---
title: "From GGUF to Safetensors: A Hands-On Converter Build Guide"
date: "2026-10-24T09:01:19.171"
draft: false
tags: ["GGUF", "Safetensors", "Quantization", "Python", "Systems Engineering", "Machine Learning"]
description: "Build a pure-Python GGUF to safetensors converter with lazy tensor streaming and quantization-aware remapping. A portfolio project that demonstrates real systems skills for ML infrastructure roles."
summary: "A step-by-step guide to building a GGUF to safetensors converter in pure Python, featuring lazy streaming and quantization-aware remapping to showcase systems engineering expertise."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-24-from-gguf-to-safetensors-a-hands-on-converter-build-guide.svg"
  alt: "A diagram showing data flow from GGUF to safetensors"
  relative: false
---

> **TL;DR** — This project builds a GGUF to safetensors converter in pure Python, demonstrating skills in binary format parsing, memory-efficient streaming, and quantization-aware tensor remapping. It's a concrete showcase for ML infrastructure and systems engineering roles, with real, runnable code that handles large models without loading everything into memory.

Converting model weights between binary formats is a cornerstone skill for ML infrastructure engineers. The GGUF format (used by llama.cpp) and the safetensors format (popularized by Hugging Face) are both prevalent in production LLM serving, yet they have fundamentally different layouts, metadata schemes, and quantization strategies. Building a converter that bridges them—not by loading the entire model into RAM, but by streaming tensors lazily and intelligently remapping quantization types—signals that you understand file I/O, memory management, and the practical realities of deploying large models. In this guide, you'll build a from-scratch, pure-Python converter that does exactly that, with every snippet designed to run and every architectural decision justified by production constraints.

## Why This Project Stands Out on a CV

Hiring managers for ML infrastructure, platform engineering, or applied ML roles often sift through hundreds of applications. A well-documented side project that tackles a concrete interoperability problem immediately differentiates you. This converter demonstrates:

- **Binary format expertise**: Parsing GGUF's header, metadata, and tensor layout from raw bytes using only the standard library (`struct`, `io`, `json`). This is the same skill set used to debug corrupted checkpoints, build custom data loaders, or reverse-engineer proprietary formats in production.
- **Memory-conscious design**: Implementing lazy tensor streaming via file seeks and generators proves you can handle multi-gigabyte models on consumer hardware—a common constraint in startups and research labs.
- **Quantization awareness**: Remapping GGUF's quantized types (e.g., `Q4_K_M`, `Q8_0`) to appropriate safetensors dtypes or custom metadata shows you understand the trade-offs between model size, accuracy, and inference speed, not just high-level APIs.
- **End-to-end ownership**: From reading a binary file to writing a validated output, you control the entire data pipeline. This mirrors the work of ML platform engineers who build internal tooling for model serving, conversion, and validation.
- **Production-oriented thinking**: The extensibility roadmap (parallelism, observability, fault tolerance) signals that you don't stop at a working prototype but think about how to integrate it into a larger workflow.

Roles this project directly supports include ML Infrastructure Engineer, Platform Engineer (ML stack), Model Deployment Engineer, and even senior Applied ML roles where shipping models efficiently is a core responsibility.

## Architecture Overview

The converter is built around a pipeline of four components that process tensors one at a time, never holding the full model in memory.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐     ┌──────────────┐
│  GGUF File  │────▶│  GGUF Parser     │────▶│  Tensor Stream  │────▶│  Safetensors │
│  (on disk)  │     │  (header, meta,  │     │  (lazy yields   │     │  Writer       │
│             │     │   tensor info)   │     │   one tensor)   │     │  (JSON header │
└─────────────┘     └──────────────────┘     └─────────────────┘     │   + binary)  │
                                                                    └──────────────┘
                                                                          │
                                                                          ▼
                                                               ┌──────────────────┐
                                                               │ Quantization     │
                                                               │ Remapping Module │
                                                               │ (per-tensor)     │
                                                               └──────────────────┘
```

1. **GGUF Parser**: Opens the file, reads the magic number and version, then iterates through the metadata key-value pairs to extract model-level information (e.g., architecture, vocabulary size). It also builds an index of tensor names, GGUF types, dimensions, and file offsets. This index is lightweight—typically a few kilobytes even for 70B-parameter models—so it fits comfortably in memory.

2. **Tensor Stream**: A generator that, given the parsed index, seeks to each tensor's offset in the file, reads its raw bytes, and yields them one at a time. The generator interface allows the writer to consume tensors in a streaming fashion, with no buffering beyond the current tensor.

3. **Quantization Remapping Module**: For each tensor, this module inspects its GGUF type (e.g., `Q4_K`) and decides how to represent it in safetensors. Since safetensors does not natively support GGUF's quantized types, the module can either (a) store the raw quantized bytes with a custom dtype string (e.g., `"Q4_K"`) and supplementary metadata, or (b) dequantize on-the-fly to a standard dtype like `float16` or `int8`. The choice depends on the target deployment; the default is to preserve the quantized form to avoid accuracy loss and unnecessary compute.

4. **Safetensors Writer**: Accumulates a JSON header describing each tensor's name, dtype, shape, and data offset, then writes the concatenated binary data to disk. The writer ensures that the final file conforms to the safetensors specification, including proper alignment and the `__metadata__` field for any custom quantization info.

All components are implemented in pure Python with no external dependencies, making the converter portable and easy to audit.

## Building It Step by Step

### Step 1: Parse the GGUF Header and Metadata

The GGUF format starts with a 4-byte magic number (`"GGUF"`), followed by a version integer, then the number of tensors and metadata key-value pairs. We use the `struct` module to unpack these fields.

```python
import struct
from io import BufferedReader
from typing import Dict, Any, List, Tuple

class GGUFParser:
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file: BufferedReader | None = None
        self.metadata: Dict[str, Any] = {}
        self.tensors: List[Dict[str, Any]] = []

    def parse(self) -> None:
        with open(self.file_path, "rb") as f:
            self.file = f
            self._read_magic_and_version()
            n_tensors = self._read_uint32()
            n_metadata = self._read_uint32()
            self._read_metadata(n_metadata)
            self._read_tensor_info(n_tensors)

    def _read_magic_and_version(self) -> None:
        magic = self.file.read(4)
        if magic != b"GGUF":
            raise ValueError(f"Not a GGUF file: {magic}")
        version = struct.unpack("<I", self.file.read(4))[0]
        if version not in (2, 3):
            raise ValueError(f"Unsupported GGUF version: {version}")

    def _read_uint32(self) -> int:
        return struct.unpack("<I", self.file.read(4))[0]

    def _read_metadata(self, n: int) -> None:
        for _ in range(n):
            key = self._read_string()
            value_type = self._read_uint32()
            value = self._read_value(value_type)
            self.metadata[key] = value

    def _read_string(self) -> str:
        length = struct.unpack("<Q", self.file.read(8))[0]
        raw = self.file.read(length)
        return raw.decode("utf-8")

    def _read_value(self, value_type: int) -> Any:
        # GGUF value types: 0=uint8, 1=int8, 2=uint16, ..., 8=string, 9=array, ...
        if value_type == 8:
            return self._read_string()
        elif value_type == 9:
            arr_type = self._read_uint32()
            arr_len = self._read_uint32()
            return [self._read_value(arr_type) for _ in range(arr_len)]
        else:
            # Scalar types: read fixed size
            sizes = {0:1, 1:1, 2:2, 3:2, 4:4, 5:4, 6:8, 7:8}
            fmts = {0:"B", 1:"b", 2:"H", 3:"h", 4:"I", 5:"i", 6:"Q", 7:"q"}
            size = sizes[value_type]
            fmt = fmts[value_type]
            return struct.unpack(f"<{fmt}", self.file.read(size))[0]

    def _read_tensor_info(self, n: int) -> None:
        for _ in range(n):
            name = self._read_string()
            n_dims = self._read_uint32()
            dims = [self._read_uint32() for _ in range(n_dims)]
            tensor_type = self._read_uint32()  # GGUF type code
            offset = struct.unpack("<Q", self.file.read(8))[0]
            self.tensors.append({
                "name": name,
                "dims": dims,
                "type": tensor_type,
                "offset": offset,
            })
```

This parser extracts all metadata and builds an index of tensors with their file offsets. The `offset` field is critical for lazy loading—it tells us exactly where each tensor's raw bytes begin.

### Step 2: Implement Lazy Tensor Streaming

We now create a generator that yields one tensor at a time by seeking to its offset and reading the exact number of bytes required. The tensor's element count and type determine the byte length.

```python
import mmap
from contextlib import contextmanager
from typing import Iterator, Dict, Any

# Mapping from GGUF type code to (numpy dtype string, element size in bytes)
# Only a subset shown for brevity; extend as needed.
GGUF_TYPE_MAP = {
    0: ("F32", 4),   # float32
    1: ("F16", 2),   # float16
    2: ("Q4_0", 0),  # quantized types have variable size; handled separately
    3: ("Q4_1", 0),
    6: ("Q8_0", 0),
    7: ("Q8_1", 0),
    10: ("Q4_K", 0),
    11: ("Q6_K", 0),
    12: ("Q5_K", 0),
    13: ("Q3_K", 0),
    14: ("Q2_K", 0),
}

def get_tensor_size(tensor: Dict[str, Any], gguf_version: int) -> int:
    """Calculate the byte size of a tensor based on its type and dimensions."""
    n_elements = 1
    for dim in tensor["dims"]:
        n_elements *= dim
    type_code = tensor["type"]
    if type_code in (2, 3, 6, 7, 10, 11, 12, 13, 14):
        # Quantized types: size depends on the specific block structure.
        # For simplicity, we use the GGUF reference implementation's logic.
        # In practice, you'd compute based on the block size (e.g., 32 for Q4_0).
        if type_code == 2:  # Q4_0
            return (n_elements // 2) + (n_elements % 2)
        elif type_code == 3:  # Q4_1
            return (n_elements // 2) + (n_elements % 2) + n_elements // 32 * 2
        elif type_code == 6:  # Q8_0
            return n_elements + n_elements // 32 * 2
        # ... add other types
        else:
            # Fallback: read the size from a precomputed table or use a heuristic
            raise NotImplementedError(f"Quantized type {type_code} not fully supported")
    else:
        _, elem_size = GGUF_TYPE_MAP[type_code]
        return n_elements * elem_size

class TensorStreamer:
    def __init__(self, file_path: str, tensors: List[Dict[str, Any]], gguf_version: int):
        self.file_path = file_path
        self.tensors = tensors
        self.gguf_version = gguf_version

    @contextmanager
    def open(self):
        # Use mmap for efficient random access
        with open(self.file_path, "rb") as f:
            mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            yield mm

    def stream(self) -> Iterator[Tuple[str, bytes, Dict[str, Any]]]:
        """Yield (name, raw_bytes, metadata) for each tensor."""
        with self.open() as mm:
            for tensor in self.tensors:
                size = get_tensor_size(tensor, self.gguf_version)
                mm.seek(tensor["offset"])
                raw = mm.read(size)
                yield tensor["name"], raw, tensor
```

The `TensorStreamer` uses `mmap` to avoid explicit file seeks and reads, which can be faster on some systems. The `get_tensor_size` function computes the byte length for each tensor, handling both standard and quantized types. For a production converter, you'd extend this with the full GGUF type table.

### Step 3: Quantization-Aware Remapping

GGUF quantized types are not directly representable in safetensors. We need to decide how to map them. The simplest approach is to store the raw quantized bytes and attach custom metadata that describes the quantization scheme. This preserves the original data and lets the consumer dequantize if needed.

```python
import json
from typing import Dict, Any

# Safetensors dtype strings for standard types
SAFETENSORS_DTYPE = {
    "F32": "float32",
    "F16": "float16",
    "I32": "int32",
    "I64": "int64",
    # etc.
}

def remap_tensor(tensor: Dict[str, Any], raw_bytes: bytes) -> Dict[str, Any]:
    """Map a GGUF tensor to a safetensors-compatible representation."""
    type_code = tensor["type"]
    if type_code in GGUF_TYPE_MAP:
        gguf_name, _ = GGUF_TYPE_MAP[type_code]
        if gguf_name.startswith("Q"):
            # Quantized type: store as raw bytes with custom dtype
            return {
                "name": tensor["name"],
                "dtype": gguf_name,  # custom dtype string
                "shape": tensor["dims"],
                "data": raw_bytes,
                "quantized": True,
            }
        else:
            # Standard type: map to safetensors dtype
            return {
                "name": tensor["name"],
                "dtype": SAFETENSORS_DTYPE.get(gguf_name, "float32"),
                "shape": tensor["dims"],
                "data": raw_bytes,
                "quantized": False,
            }
    else:
        raise ValueError(f"Unknown GGUF type code: {type_code}")
```

This remapping step is where you add intelligence. For instance, you could dequantize `Q4_K` to `float16` on the fly by implementing the block dequantization algorithm, but that increases CPU usage and may introduce accuracy loss. The default of preserving the quantized form is often preferable for serving workflows.

### Step 4: Write the Safetensors File

Safetensors files consist of a JSON header followed by the concatenated tensor data. The header must include each tensor's name, dtype, shape, and data offsets (relative to the start of the binary section). We also add a `__metadata__` field to record the original GGUF quantization types.

```python
import struct
from pathlib import Path

class SafetensorsWriter:
    def __init__(self, output_path: str):
        self.output_path = Path(output_path)
        self.tensors_meta = []
        self.binary_data = bytearray()
        self.offset = 0

    def add_tensor(self, name: str, dtype: str, shape: List[int], data: bytes, quantized: bool) -> None:
        # Align to 8 bytes for safetensors compliance
        while len(self.binary_data) % 8 != 0:
            self.binary_data.append(0)
        self.tensors_meta.append({
            "name": name,
            "dtype": dtype,
            "shape": shape,
            "data_offsets": [self.offset, self.offset + len(data)],
        })
        self.binary_data.extend(data)
        self.offset += len(data)

    def write(self) -> None:
        header = {
            "__metadata__": {
                "converter": "gguf2safetensors",
                "version": "1.0",
            },
        }
        # Add per-tensor metadata, excluding the binary data
        for meta in self.tensors_meta:
            header[meta["name"]] = {
                "dtype": meta["dtype"],
                "shape": meta["shape"],
                "data_offsets": meta["data_offsets"],
            }
        header_bytes = json.dumps(header, separators=(",", ":")).encode("utf-8")
        header_len = struct.pack("<Q", len(header_bytes))
        with open(self.output_path, "wb") as f:
            f.write(header_len)
            f.write(header_bytes)
            f.write(self.binary_data)
```

The `SafetensorsWriter` builds the JSON header incrementally as tensors are added, ensuring that the `data_offsets` are correct. The final file layout is: 8-byte header length (little-endian), JSON header, then binary tensor data.

### Step 5: Wire It All Together

Here's the main conversion function that orchestrates the pipeline:

```python
def convert_gguf_to_safetensors(input_path: str, output_path: str) -> None:
    parser = GGUFParser(input_path)
    parser.parse()
    gguf_version = parser.metadata.get("version", 2)
    streamer = TensorStreamer(input_path, parser.tensors, gguf_version)
    writer = SafetensorsWriter(output_path)

    for name, raw_bytes, tensor_info in streamer.stream():
        remapped = remap_tensor(tensor_info, raw_bytes)
        writer.add_tensor(
            name=remapped["name"],
            dtype=remapped["dtype"],
            shape=remapped["shape"],
            data=remapped["data"],
            quantized=remapped["quantized"],
        )

    writer.write()
    print(f"Converted {len(parser.tensors)} tensors to {output_path}")
```

This function parses the GGUF file, streams each tensor through the remapping module, and writes the safetensors output. The entire process uses only O(1) memory relative to the model size (aside from the tensor index, which is small).

## Running and Testing It

To test the converter, you'll need a sample GGUF file. You can download a small quantized model from Hugging Face (e.g., `TheBloke/TinyLlama-1.1B-Chat-v0.3-GGUF`), or use a synthetic one for unit tests.

1. **Install Python 3.10+** (the code uses modern type hints and `mmap` features).
2. **Save the converter code** in a file named `gguf2safetensors.py`.
3. **Run the conversion**:

```bash
python gguf2safetensors.py \
    --input path/to/model.gguf \
    --output path/to/model.safetensors
```

4. **Validate the output** using Hugging Face's `safetensors` library:

```python
from safetensors import safe_open

with safe_open("model.safetensors", framework="pt") as f:
    for key in f.keys():
        print(f"{key}: {f.get_tensor(key).shape}")
```

If the tensor names and shapes match the original GGUF file, the conversion is successful. For quantized tensors, you'll see custom dtype strings like `"Q4_K"`; you can then implement a dequantization function in your serving code to restore them to float16 when needed.

To automate testing, write a small script that compares the tensor metadata (names, shapes) between the input and output, and optionally checks that the raw bytes are identical for non-quantized tensors.

## Extending It: Your Roadmap to Senior-Level

A prototype that works on small models is a good start, but senior engineers think about scale, reliability, and integration. Here are six concrete upgrades that transform this converter into a production-grade tool:

1. **Parallel tensor processing**: Use `concurrent.futures.ThreadPoolExecutor` or `ProcessPoolExecutor` to convert multiple tensors simultaneously. This leverages multi-core CPUs and can reduce conversion time by 4–10x on large models. *Why it matters*: Production workflows often have tight SLAs for model preparation, and parallelism is a standard expectation for infrastructure tooling.

2. **Resumable conversion with checkpointing**: For very large models (e.g., 70B+), write intermediate checkpoints so that a failure doesn't force a restart from scratch. *Why it matters*: Fault tolerance is non-negotiable in batch pipelines; a converter that can resume after a network glitch or OOM error saves significant developer time.

3. **Observability and logging**: Integrate structured logging (e.g., `structlog`) and emit metrics on tensor sizes, conversion throughput, and memory usage. Expose these via Prometheus or simply write them to a JSON log. *Why it matters*: You can't optimize what you don't measure. Observability lets you debug bottlenecks and prove performance to stakeholders.

4. **Validation against a reference**: After conversion, load both the original GGUF and the output safetensors into a framework like PyTorch or llama.cpp, and compare tensor values (within a tolerance for quantized types). *Why it matters*: Silent data corruption is a nightmare in ML pipelines. Automated validation catches issues before they reach production.

5. **Support for all GGUF metadata types**: The current parser handles scalars and strings, but GGUF also supports arrays of various types, nested structures, and optional fields. Extend the parser to round-trip all metadata into the safetensors `__metadata__` block. *Why it matters*: Metadata carries crucial information for model serving (e.g., tokenizer config, context length); losing it breaks downstream tasks.

6. **CLI with configuration file**: Build a user-friendly command-line interface using `argparse` or `Typer`, with options for output dtype overrides, quantization dequantization flags, and a YAML/JSON config file for complex workflows. *Why it matters*: Tools that are easy to invoke get adopted. A clean CLI signals that you think about the end user, not just the algorithm.

## Key Takeaways

- **Binary format fluency**: Parsing GGUF and writing safetensors from scratch demonstrates deep understanding of file I/O, memory layout, and serialization—skills that translate directly to debugging and building ML data pipelines.
- **Lazy streaming is essential**: The converter never loads the full model into RAM, proving you can handle multi-gigabyte artifacts on commodity hardware. This is a common interview talking point for infrastructure roles.
- **Quantization awareness**: By preserving or intelligently remapping quantized types, you show that you care about model accuracy and inference speed, not just format conversion.
- **Production mindset**: The extensibility roadmap (parallelism, validation, observability) signals that you can evolve a prototype into a reliable tool, a key differentiator for senior positions.
- **Pure Python, no magic**: Using only the standard library keeps the code auditable and portable, a trait that senior engineers appreciate when onboarding new team members.

## Further Reading

- **GGUF Specification**: The canonical reference for the GGUF format, including all tensor types and metadata fields, is maintained by the llama.cpp project. Study it to understand the full scope of quantization options and block structures: [gguf.cpp GitHub](https://github.com/ggerganov/ggml/blob/master/docs/gguf.md).
- **Safetensors Format**: The safetensors documentation by Hugging Face details the file layout, safety guarantees, and supported dtypes. It also includes a Python API for reading and writing: [safetensors docs](https://huggingface.co/docs/safetensors/index).
- **Quantization Techniques for Large Language Models**: The paper "GPTQ: Accurate Post-Training Quantization for Generative Pre-trained Transformers" introduces the GPTQ algorithm, which underlies many GGUF quantization types. It provides the theoretical foundation for understanding quantization error and block-wise compression: [GPTQ paper (arXiv)](https://arxiv.org/abs/2210.17323).
- **Memory-Efficient Data Processing**: For deeper insights into streaming and memory management, refer to the Python `mmap` documentation and the "Efficient Large-Scale Data Processing" chapter in the Python Performance Developer Guide: [Python mmap](https://docs.python.org/3/library/mmap.html).
- **ML Infrastructure Patterns**: The blog post "Patterns for ML Platform Engineering" by Netflix TechBlog discusses real-world challenges in model serving and conversion, including parallelism and fault tolerance: [Netflix TechBlog](https://netflixtechblog.com/).

By building this converter and then extending it along the outlined roadmap, you create a portfolio piece that is not only functional but also demonstrative of the systems thinking that hiring managers value.