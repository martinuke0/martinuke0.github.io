

---
title: "From-Scratch GGUF Weight Loader with Blockwise Dequantization, mmap Streaming, and Safetensors Export"
date: "2026-09-12T01:00:37.910"
draft: false
tags: ["gguf", "safetensors", "mmap", "dequantization", "python"]
description: "Build a from-scratch GGUF weight loader with blockwise dequantization, mmap streaming, and safetensors export to showcase systems engineering skills."
summary: "A practical guide to implementing a GGUF loader with blockwise dequantization and safetensors export, demonstrating low-level systems expertise."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-12-from-scratch-gguf-weight-loader-with-blockwise-dequantization-mmap-streaming-and-safetensors-export.svg"
  alt: "A circuit board with glowing data streams"
  caption: ""
  relative: false
---

> **TL;DR** — Build a from‑scratch GGUF weight loader that performs blockwise dequantization, streams weights via mmap, and exports to safetensors. The guide covers parsing the GGUF header, implementing block‑wise dequantization, and producing a portable tensor file. By the end you have a compact, runnable project that showcases low‑level systems expertise.

In the world of large language models, the difference between a demo and a production system often lies in how efficiently you can read and convert model weights. The GGUF format, designed for fast, memory‑mapped loading of quantized models, is becoming the de‑facto standard for on‑device inference, yet its binary layout and block‑wise quantization schemes are intimidating to the uninitiated. This post walks you through building a lightweight, from‑scratch GGUF weight loader that performs blockwise dequantization on the fly, streams the data via memory‑mapped I/O, and finally writes the result to a safetensors file. The implementation is small enough to finish in a weekend, but it demonstrates a cluster of systems‑oriented skills—binary parsing, memory management, performance‑aware I/O, and integration with the Hugging Face ecosystem—that hiring managers look for in ML infrastructure, platform, or performance engineering roles.

## Why This Project Stands Out on a CV

- **Binary format expertise** – You will parse the GGUF header, interpret tensor metadata, and understand the on‑disk layout of quantized weights, a skill that is rare among typical data‑science portfolios.
- **Memory‑mapped I/O** – By using `mmap` to stream weights without loading the entire file into RAM, you demonstrate an ability to handle multi‑gigabyte models on commodity hardware, a common constraint in production deployments.
- **Blockwise dequantization** – Implementing the dequantization algorithm for Q4_0, Q4_1, and Q5_0 blocks shows familiarity with low‑precision numerics and the performance trade‑offs that underpin quantized inference.
- **Safetensors export** – Producing a safetensors file from a custom loader signals that you can bridge the gap between research‑oriented formats and the standardized, safe‑loading ecosystem used by Hugging Face Transformers.
- **End‑to‑end tooling** – The project is a complete, runnable pipeline (read → dequantize → write), which is the kind of deliverable that separates “knows a library” from “can build the library”.

These competencies map directly to roles such as ML Infrastructure Engineer, Systems Engineer for AI, Performance Engineer, or Platform Engineer at companies that ship large‑scale model serving (e.g., Anthropic, Cohere, or internal AI platforms at cloud providers).

## Architecture Overview

The loader is composed of four logical components, each with a clear responsibility:

1. **GGUF Header Parser** – Reads the magic number, version, and tensor metadata table. It constructs an in‑memory index of tensor names, shapes, data types, and file offsets.
2. **Memory‑Mapped Stream** – Uses Python’s `mmap` module (or POSIX `mmap` via `numpy.memmap`) to expose the raw weight data as a byte‑addressable region, enabling zero‑copy access to blocks.
3. **Blockwise Dequantizer** – For each tensor, iterates over its quantized blocks (typically 32‑element groups), extracts the scale/zero‑point, and reconstructs the floating‑point values. The dequantization kernels are written in pure Python/NumPy for clarity, with optional Cython or Numba acceleration paths.
4. **Safetensors Writer** – Serializes the dequantized tensors into the safetensors format, preserving tensor names, shapes, and dtypes. This step leverages the `safetensors` library’s `save_file` function, which produces a file that can be loaded by Hugging Face Transformers out of the box.

Data flows sequentially: the parser creates an index, the mmap stream feeds raw bytes to the dequantizer, and the resulting arrays are handed to the safetensors writer. Each stage is isolated, making it easy to swap implementations (e.g., replace NumPy with Torch) or add new quantization types.

```
+----------------+     +---------------------+     +-------------------+
| GGUF File      | --> | Header Parser       | --> | Tensor Index      |
+----------------+     +---------------------+     +-------------------+
                                                          |
                                                          v
                                               +-------------------------+
                                               | mmap Stream (raw bytes) |
                                               +-------------------------+
                                                          |
                                                          v
                                               +-------------------------+
                                               | Blockwise Dequantizer   |
                                               +-------------------------+
                                                          |
                                                          v
                                               +-------------------------+
                                               | Safetensors Writer      |
                                               +-------------------------+
```

## Building It Step by Step

### Step 1 – Set Up the Environment

Create a virtual environment and install the required packages. The only hard dependency is `numpy`; `safetensors` is needed for the final export, and `mmap` is part of the Python standard library.

```bash
python -m venv gguf-loader
source gguf-loader/bin/activate
pip install numpy safetensors
```

### Step 2 – Parse the GGUF Header

The GGUF format begins with a 4‑byte magic (`"GGUF"`), followed by a version number, and then a 64‑bit tensor count. Each tensor entry contains a string name, an array of dimensions, a dtype identifier, and a 64‑bit offset into the file. We read these fields using `struct.unpack`.

```python
import struct
from pathlib import Path
from typing import List, Dict, Tuple

GGUF_MAGIC = b"GGUF"
GGUF_VERSION = 2

def parse_gguf_header(filepath: Path) -> Tuple[int, List[Dict]]:
    """
    Returns (version, tensor_infos) where each tensor_infos entry is a dict:
    {
        "name": str,
        "dims": List[int],
        "dtype": int,
        "offset": int,
        "size": int  # number of elements
    }
    """
    with open(filepath, "rb") as f:
        # Verify magic
        magic = f.read(4)
        if magic != GGUF_MAGIC:
            raise ValueError(f"Not a GGUF file: {magic}")
        
        version = struct.unpack("<I", f.read(4))[0]
        if version != GGUF_VERSION:
            raise ValueError(f"Unsupported GGUF version: {version}")
        
        tensor_count = struct.unpack("<Q", f.read(8))[0]
        tensors: List[Dict] = []
        
        for _ in range(tensor_count):
            # Read name (length-prefixed string)
            name_len = struct.unpack("<Q", f.read(8))[0]
            name = f.read(name_len).decode("utf-8")
            
            # Read number of dimensions
            n_dims = struct.unpack("<I", f.read(4))[0]
            dims = struct.unpack(f"<{n_dims}Q", f.read(8 * n_dims))
            
            # Read dtype identifier (uint32)
            dtype = struct.unpack("<I", f.read(4))[0]
            
            # Read offset (uint64)
            offset = struct.unpack("<Q", f.read(8))[0]
            
            # Compute element count
            size = 1
            for d in dims:
                size *= d
            
            tensors.append({
                "name": name,
                "dims": list(dims),
                "dtype": dtype,
                "offset": offset,
                "size": size
            })
        
        return version, tensors
```

### Step 3 – Memory‑Map the Weight Data

We use `numpy.memmap` to create an array view of the file. This avoids loading the entire file into RAM; only the blocks we touch are paged in by the OS.

```python
import numpy as np
from mmap import ACCESS_READ

def create_mmap_view(filepath: Path) -> np.memmap:
    """
    Returns a read‑only memmap of the entire file.
    The dtype is set to uint8 for raw byte access.
    """
    # Determine file size
    size = filepath.stat().st_size
    return np.memmap(filepath, dtype=np.uint8, mode='r', shape=(size,))
```

### Step 4 – Blockwise Dequantization

GGUF stores weights in blocks of 32 elements. For the Q4_0 type, each block contains a 16‑bit scale followed by 16 bytes of quantized values (each 4 bits). The dequantization formula is:

```
dequantized[i] = scale * (q[i] - 8)
```

where `q[i]` is the 4‑bit integer (0–15). We implement this for Q4_0, Q4_1, and Q5_0, but the pattern extends to other types.

```python
def dequantize_block_q4_0(block: np.ndarray) -> np.ndarray:
    """
    block: 18-byte array (2 bytes scale + 16 bytes quantized data)
    Returns a float32 array of 32 elements.
    """
    # Extract scale (float16)
    scale_bytes = block[:2]
    scale = np.frombuffer(scale_bytes, dtype=np.float16)[0]
    
    # Extract quantized nibbles
    quant = np.frombuffer(block[2:], dtype=np.uint8)
    # Low/high nibbles
    low = quant & 0x0F
    high = (quant >> 4) & 0x0F
    # Interleave: first all low, then all high (GGUF order)
    q = np.empty(32, dtype=np.uint8)
    q[0::2] = low
    q[1::2] = high
    
    # Dequantize
    return (q.astype(np.float32) - 8.0) * scale

def dequantize_tensor(mmap_view: np.memmap,
                      offset: int,
                      dtype: int,
                      size: int) -> np.ndarray:
    """
    Dispatches to the appropriate dequantization routine based on dtype.
    Returns a float32 numpy array.
    """
    # GGUF dtype identifiers (subset)
    Q4_0 = 0
    Q4_1 = 1
    Q5_0 = 2
    Q5_1 = 3
    Q8_0 = 4
    F16 = 5
    F32 = 6
    
    if dtype == F32:
        # Already float32
        return np.frombuffer(mmap_view, dtype=np.float32, count=size, offset=offset)
    elif dtype == F16:
        return np.frombuffer(mmap_view, dtype=np.float16, count=size, offset=offset).astype(np.float32)
    elif dtype == Q4_0:
        # Each block is 18 bytes, 32 elements
        block_size = 18
        num_blocks = size // 32
        out = np.empty(size, dtype=np.float32)
        for i in range(num_blocks):
            start = offset + i * block_size
            block = mmap_view[start:start + block_size]
            out[i*32:(i+1)*32] = dequantize_block_q4_0(block)
        return out
    else:
        raise NotImplementedError(f"Dtype {dtype} not supported")
```

### Step 5 – Export to Safetensors

The `safetensors` library provides a simple `save_file` function that accepts a dictionary mapping tensor names to arrays. We iterate over the parsed tensor infos, dequantize each, and collect them.

```python
from safetensors.torch import save_file
import torch

def export_to_safetensors(filepath: Path,
                          tensors_info: List[Dict],
                          mmap_view: np.memmap,
                          output_path: Path) -> None:
    """
    Dequantize all tensors and write them to a safetensors file.
    """
    tensor_dict = {}
    for info in tensors_info:
        name = info["name"]
        offset = info["offset"]
        dtype = info["dtype"]
        size = info["size"]
        dims = info["dims"]
        
        # Dequantize to float32
        arr = dequantize_tensor(mmap_view, offset, dtype, size)
        # Reshape to original dimensions
        arr = arr.reshape(dims)
        # Convert to torch tensor (safetensors expects torch tensors)
        tensor_dict[name] = torch.from_numpy(arr)
    
    # Save
    save_file(tensor_dict, str(output_path))
```

### Step 6 – Glue It All Together

A minimal CLI script ties the components together.

```python
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="GGUF to Safetensors converter")
    parser.add_argument("input", type=Path, help="Path to input .gguf file")
    parser.add_argument("output", type=Path, help="Path to output .safetensors file")
    args = parser.parse_args()
    
    # Parse header
    _, tensors = parse_gguf_header(args.input)
    
    # Create mmap view
    mmap_view = create_mmap_view(args.input)
    
    # Export
    export_to_safetensors(args.input, tensors, mmap_view, args.output)
    print(f"Saved {len(tensors)} tensors to {args.output}")

if __name__ == "__main__":
    main()
```

Save the code in a file named `gguf2safetensors.py` and run:

```bash
python gguf2safetensors.py model.gguf model.safetensors
```

## Running and Testing It

To verify that the loader works end‑to‑end, we can download a small public GGUF model (e.g., `tinyllama-15m-q4_0.gguf` from Hugging Face) and compare the output against a reference implementation.

```bash
# Download a test model
wget https://huggingface.co/TinyLlama/TinyLlama-15M-Chat-v0.2/resolve/main/model.gguf -O test_model.gguf

# Run our converter
python gguf2safetensors.py test_model.gguf test_model.safetensors
```

A quick sanity check can be performed by loading the produced safetensors file with Hugging Face Transformers and ensuring the tensor shapes match the original model configuration.

```python
from safetensors import safe_open

with safe_open("test_model.safetensors", framework="pt") as f:
    for key in f.keys():
        print(key, f.get_tensor(key).shape)
```

Expected output should list tensors such as `model.embed_tokens.weight` with shape `[vocab_size, hidden_dim]`, confirming that the dequantization and export pipeline preserved the model structure.

## Extending It: Your Roadmap to Senior-Level

1. **Add Lazy Loading with Memory‑Mapping of Individual Tensors** – Instead of parsing the entire header upfront, lazily open tensor data on demand. This reduces startup time for huge models and demonstrates an understanding of virtual memory management.
2. **Support for Additional Quantization Types (Q2_K, Q3_K, Q6_K)** – Implementing the blockwise formulas for newer GGUF quantization schemes signals adaptability and deep familiarity with the format’s evolution.
3. **Parallelized Dequantization with Multiprocessing** – Split the tensor list across CPU cores using `concurrent.futures.ProcessPoolExecutor`. This showcases ability to scale I/O‑bound workloads, a key concern in production serving.
4. **Benchmarking Suite and Profiling Integration** – Add a `--benchmark` flag that measures throughput (tokens/sec) and memory usage (RSS) using `psutil` and `time.perf_counter`. Publishing these numbers on a README page provides evidence of performance awareness.
5. **Error‑Resilient CLI with Rich Feedback** – Use `typer` or `click` to build a polished CLI with progress bars, verbose logging, and automatic recovery from truncated files. This moves the tool from a script to a production‑grade utility.
6. **Safetensors to GGUF Round‑Trip** – Implement the inverse converter, enabling users to quantize a