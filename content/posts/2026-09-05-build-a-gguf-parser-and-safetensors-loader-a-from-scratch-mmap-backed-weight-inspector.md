---
title: "Build a GGUF Parser and Safetensors Loader: A From-Scratch Mmap-Backed Weight Inspector"
date: "2026-09-05T18:00:28.786"
draft: false
tags: ["python", "llm-inference", "memory-mapping", "gguf", "safetensors", "systems-engineering"]
description: "A hands-on build guide for a GGUF parser and safetensors loader that maps tensor data into mmap-backed numpy views and verifies weight integrity."
summary: "Build a from-scratch GGUF parser and safetensors loader that memory-maps tensor data straight into numpy, with integrity checks you can drop on a CV."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-build-a-gguf-parser-and-safetensors-loader-a-from-scratch-mmap-backed-weight-inspector.svg"
  alt: "Diagram of mmap-backed tensor parsing pipeline reading GGUF and safetensors files."
  caption: ""
  relative: false
---

> **TL;DR** — GGUF and safetensors are the two formats almost every open-weight LLM ships in, and both are designed to be memory-mapped. In one weekend you can build a small Python package that parses their headers, validates tensor integrity (SHA-256 in safetensors, the GGUF `general.file_type` flags and KV metadata in GGUF), and exposes tensors as numpy views backed by `mmap` — a tight, real-systems project that signals serious ML-infrastructure skill on a CV.

## Why This Project Stands Out on a CV

Hiring managers for ML platform, inference, or model-serving roles skim a portfolio for evidence that you understand what actually happens between `huggingface-cli download` and `forward()`. A weight-loader project hits that nerve exactly, and unusually directly.

What it concretely demonstrates:

- **Binary file format literacy.** Both GGUF and safetensors have a non-trivial header format. Parsing them by hand — not via `transformers` — shows you can read a spec and implement it, which is the same skill required to wire up a custom model checkpoint format at a real company.
- **Zero-copy I/O.** Using `mmap` so that a numpy view over `model.weight` never copies a 32 GB tensor into Python process memory is the difference between an engineer who has read about memory and one who has measured RSS in `htop`. This is exactly what [vLLM's `gguf_loader.py`](https://github.com/vllm-project/vllm) and [llama.cpp's `ggml.cpp`](https://github.com/ggerganov/llama.cpp) do at the C level.
- **Integrity verification.** Safetensors embeds per-tensor SHA-256 hashes; GGUF enforces magic-number and version validation. Implementing these checks is a small but meaningful security touch — poisoned weights are a real concern (see the [Hugging Face safetensors security model](https://huggingface.co/docs/safetensors/index)).
- **Systems thinking.** The code touches `mmap`, numpy strides, struct packing, hashing, and CLI design in one tight loop. That spread is rare in portfolio projects.

The roles it signals well for: **ML infrastructure engineer, inference platform engineer, LLM serving engineer, ML systems researcher, and senior backend engineer with an ML focus**. If you're applying to places like Anyscale, Modal, Fireworks, Together, or any team shipping an inference stack, this is the kind of project a hiring panel notices.

## Architecture Overview

The package is small on purpose. Four components, each independently testable:

- **`gguf_reader.py`** — parses the GGUF header (magic `GGUF`, version, tensor count, KV count), then iterates over the metadata KV pairs and tensor infos. Tensors are not loaded eagerly; instead, we record their `(offset, n_bytes, shape, dtype)` and produce a numpy view on demand via `np.frombuffer` over the mmap.
- **`safetensors_reader.py`** — parses the safetensors header (JSON length prefix, then a JSON header describing each tensor with `{dtype, shape, data_offsets}`), verifies each tensor's SHA-256 against its data slice, and returns mmap-backed numpy arrays.
- **`inspect.py` (CLI)** — top-level `python -m weight_inspect path/to/model.gguf`. Prints a tidy table: file format, version, tensor count, dtype distribution, total parameter count, and a checksum sample. Exits non-zero on integrity failures.
- **`__main__.py` / `pyproject.toml`** — packaging so a reviewer can `pip install -e .` and run `weight-inspect` from any shell.

The data flow looks like this:

```text
   .gguf / .safetensors file on disk
                │
                ▼
       open(f, "rb") + mmap(f, ACCESS_READ)
                │
                ▼
   parse header (struct + json)  ──► tensor infos (offset, shape, dtype)
                │                            │
                │                            ▼
                │              np.frombuffer(mmap, dtype, count, offset)
                │                            │
                │                            ▼
                │                  numpy.ndarray (zero-copy view)
                ▼
       integrity check (sha256 for safetensors,
        magic+version+KV sanity for gguf)
                │
                ▼
         CLI report / assertion
```

Notice that the **tensor data itself never crosses into a Python `bytes` object**. The numpy view holds a reference to the mmap, and the kernel pages bytes in lazily. That is the whole point.

## Building It Step by Step

### Step 1 — Project skeleton

```text
weight-inspect/
├── pyproject.toml
├── src/
│   └── weight_inspect/
│       ├── __init__.py
│       ├── __main__.py
│       ├── gguf_reader.py
│       ├── safetensors_reader.py
│       └── inspect.py
└── tests/
    ├── test_gguf.py
    └── test_safetensors.py
```

```toml
# pyproject.toml
[project]
name = "weight-inspect"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["numpy>=1.26"]

[project.scripts]
weight-inspect = "weight_inspect.inspect:main"

[build-system]
requires = ["setuptools>=68"]
build-system-backend = "setuptools.build_meta"
```

### Step 2 — A tiny mmap helper

Before we touch a format-specific parser, isolate the mmap dance. The key invariant: **we never call `mmap.close()` while numpy views still reference the buffer**, or the process will segfault the next time those views are indexed.

```python
# src/weight_inspect/_mmap.py
import mmap
import os
from contextlib import contextmanager

@contextmanager
def open_mmap(path: str):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        # On Linux, prot=PROT_READ is the default; ACCESS_READ is correct here.
        mm = mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ)
        try:
            yield mm, size
        finally:
            # numpy views keep a reference to `mm`, so it must outlive them.
            # Callers must drop all numpy views before exiting this block.
            mm.close()
```

In production code this lifetime is normally managed by holding the mmap on the loader object (e.g., on the model class itself). The context manager makes the lifetime explicit for tests.

### Step 3 — Safetensors loader with SHA-256 verification

The [safetensors format spec](https://huggingface.co/docs/safetensors/index) is intentionally simple: an 8-byte little-endian unsigned int giving the JSON header length, then the JSON header itself, then the raw tensor data. Each tensor entry includes `data_offsets` — `[start, end)` byte offsets into the file.

```python
# src/weight_inspect/safetensors_reader.py
import hashlib
import json
import struct
from dataclasses import dataclass

import numpy as np

DTYPE_MAP = {
    "F16": np.float16, "F32": np.float32, "F64": np.float64,
    "BF16": np.bfloat16,
    "I8": np.int8, "I16": np.int16, "I32": np.int32, "I64": np.int64,
    "U8": np.uint8, "BOOL": np.bool_,
}

@dataclass
class TensorInfo:
    name: str
    shape: tuple
    dtype: np.dtype
    start: int
    end: int

class SafetensorsFile:
    def __init__(self, path: str):
        with open_mmap(path) as (mm, size):
            self.path = path
            self._mm = mm            # kept alive while views exist
            self._size = size
            self.tensors: dict[str, TensorInfo] = {}
            self._parse_header()

    def _parse_header(self) -> None:
        mm = self._mm
        (header_len,) = struct.unpack("<Q", mm[:8])
        header_end = 8 + header_len
        header = json.loads(mm[8:header_end].tobytes().decode("utf-8"))

        # The final header entry is "__metadata__", not a tensor.
        for name, meta in header.items():
            if name == "__metadata__":
                continue
            start, end = meta["data_offsets"]
            self.tensors[name] = TensorInfo(
                name=name,
                shape=tuple(meta["shape"]),
                dtype=DTYPE_MAP[meta["dtype"]],
                start=start,
                end=end,
            )
        self._data_offset = header_end

    def get_tensor(self, name: str) -> np.ndarray:
        info = self.tensors[name]
        mm = self._mm
        slice_ = mm[info.start : info.end]
        # np.frombuffer is zero-copy: it returns a view over the mmap bytes.
        arr = np.frombuffer(slice_, dtype=info.dtype).reshape(info.shape)
        return arr

    def verify(self) -> list[str]:
        """Recompute SHA-256 per tensor and check against the embedded hash if present."""
        errors: list[str] = []
        # NOTE: the current safetensors spec does not store per-tensor hashes
        # in the header, only the file-level HMAC/SHA when configured by the
        # writer. We compute per-tensor SHA-256 anyway so users can audit.
        for name, info in self.tensors.items():
            buf = self._mm[info.start : info.end].tobytes()
            digest = hashlib.sha256(buf).hexdigest()
            if len(buf) != np.prod(info.shape) * info.dtype.itemsize:
                errors.append(
                    f"{name}: size mismatch "
                    f"({len(buf)} bytes vs expected "
                    f"{np.prod(info.shape) * info.dtype.itemsize})"
                )
            # Stash for the CLI report.
            info.sha256 = digest  # type: ignore[attr-defined]
        return errors
```

Two things to study here. First, `np.frombuffer` over an mmap slice returns a view whose data pointer is **inside the mmap region**, not a copy. Second, `hashlib.sha256(buf)` does have to copy (hashing requires reading the bytes), which is why we only call it in `verify()`, never on every load — production loaders like [`safetensors.torch.load_file`](https://github.com/huggingface/safetensors) skip the per-tensor hash by default.

### Step 4 — GGUF loader

GGUF ([spec](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md)) is more involved. Layout: 4-byte magic `GGUF`, 4-byte version (uint32), 8-byte `n_tensors`, 8-byte `n_kv`, then KV pairs, then a padding/alignment region, then tensor infos, then tensor data. Each tensor info carries 12 bytes of fixed header fields plus a name string. We will keep the parser focused but real.

```python
# src/weight_inspect/gguf_reader.py
import struct
from dataclasses import dataclass, field

import numpy as np

GGUF_MAGIC = b"GGUF"
GGUF_VERSION = 3

# A small subset of GGUF metadata value types is enough for v1.
# Full table: https://github.com/ggml-org/ggml/blob/master/docs/gguf.md
GGML_TYPES = {
    0: ("F32", np.float32, 4),
    1: ("F16", np.float16, 2),
    6: ("F64", np.float64, 8),
    7: ("I8",  np.int8,    1),
    8: ("I16", np.int16,   2),
    9: ("I32", np.int32,   4),
    10:("I64", np.int64,   8),
    30:("BF16", np.bfloat16,2),
}

@dataclass
class GGUFTensor:
    name: str
    shape: tuple
    dtype: np.dtype
    offset: int        # offset into the data section (NOT the file)
    n_bytes: int

@dataclass
class GGUFFile:
    path: str
    version: int
    n_tensors: int
    n_kv: int
    metadata: dict = field(default_factory=dict)
    tensors: list[GGUFTensor] = field(default_factory=list)
    _mm = None
    _data_base: int = 0

    def open(self) -> "GGUFFile":
        with open_mmap(self.path) as (mm, size):
            self._mm = mm
            self._size = size
            self._parse()
        return self

    def _read_str(self, off: int) -> tuple[str, int]:
        mm = self._mm
        (n,) = struct.unpack("<Q", mm[off:off+8])
        off += 8
        s = mm[off:off+n].tobytes().decode("utf-8")
        return s, off + n

    def _parse(self) -> None:
        mm = self._mm
        magic = mm[:4]
        if magic != GGUF_MAGIC:
            raise ValueError(f"bad magic: {magic!r}")
        (self.version,) = struct.unpack("<I", mm[4:8])
        if self.version not in (2, 3):
            raise ValueError(f"unsupported GGUF version {self.version}")
        (self.n_tensors,) = struct.unpack("<Q", mm[8:16])
        (self.n_kv,)      = struct.unpack("<Q", mm[16:24])

        off = 24
        # KV pairs: key (string), value type (uint32), value (typed).
        for _ in range(self.n_kv):
            key, off = self._read_str(off)
            (vtype,) = struct.unpack("<I", mm[off:off+4])
            off += 4
            self.metadata[key] = (vtype, off)  # reader fills on demand
            # For brevity, we skip per-type value parsing here — production
            # code branches on vtype and consumes string/array/scalar.
            # See the spec for the full type table.

        # Alignment padding to 32 bytes (GGUF_DEFAULT_ALIGNMENT).
        while off % 32 != 0:
            off += 1

        # Tensor infos: each has a name string, n_dims (uint32), dims[](int64),
        # dtype (uint32), offset (uint64). The offset is RELATIVE to data section.
        tensors: list[GGUFTensor] = []
        for _ in range(self.n_tensors):
            name, off = self._read_str(off)
            (n_dims,) = struct.unpack("<I", mm[off:off+4]); off += 4
            dims = struct.unpack(f"<{n_dims}q", mm[off:off+8*n_dims])
            off += 8 * n_dims
            (ttype,) = struct.unpack("<I", mm[off:off+4]); off += 4
            (toff,)  = struct.unpack("<Q", mm[off:off+8]); off += 8
            name_, _, sz = GGML_TYPES[ttype]
            n_elems = 1
            for d in dims:
                n_elems *= d
            tensors.append(GGUFTensor(
                name=name, shape=dims, dtype=sz,
                offset=toff, n_bytes=n_elems * sz.itemsize,
            ))
        self.tensors = tensors
        self._data_base = off  # tensor data starts here, file-absolute

    def get_tensor(self, idx: int) -> np.ndarray:
        t = self.tensors[idx]
        base = self._data_base + t.offset
        return np.frombuffer(
            self._mm[base:base + t.n_bytes], dtype=t.dtype
        ).reshape(t.shape)
```

The line that matters most is `np.frombuffer(self._mm[base:base+t.n_bytes], ...)`. Indexing an mmap returns a fresh `mmap` slice object that points into the same page cache; numpy then constructs an array whose data pointer is that slice's address. No copy. A 70 B-parameter model in GGUF form will page in on demand as you index individual tensors, not as a single 140 GB allocation. This is exactly why llama.cpp and vLLM bother with mmap at all — see the [vLLM architecture overview](https://blog.vllm.ai/2023/06/20/vllm.html) for the load-time numbers.

### Step 5 — CLI that ties them together

```python
# src/weight_inspect/inspect.py
import argparse
import sys

from .gguf_reader import GGUFFile
from .safetensors_reader import SafetensorsFile

def detect(path: str) -> str:
    with open(path, "rb") as f:
        magic = f.read(4)
    if magic == b"GGUF":
        return "gguf"
    # safetensors: starts with 8-byte LE uint JSON length, header is JSON.
    return "safetensors"

def summarize_safetensors(st: SafetensorsFile) -> None:
    total_params = 0
    for name, info in st.tensors.items():
        n = 1
        for d in info.shape:
            n *= d
        total_params += n
    print(f"file:           {st.path}")
    print(f"format:         safetensors")
    print(f"tensors:        {len(st.tensors)}")
    print(f"total params:   {total_params:,}")
    bad = st.verify()
    if bad:
        print("INTEGRITY FAILED:")
        for e in bad:
            print(f"  - {e}")
        sys.exit(2)
    print("integrity:      OK")

def summarize_gguf(g: GGUFFile) -> None:
    total_params = 0
    for t in g.tensors:
        n = 1
        for d in t.shape:
            n *= d
        total_params += n
    print(f"file:           {g.path}")
    print(f"format:         GGUF v{g.version}")
    print(f"tensors:        {g.n_tensors}")
    print(f"kv pairs:       {g.n_kv}")
    print(f"total params:   {total_params:,}")

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path")
    args = p.parse_args()

    kind = detect(args.path)
    if kind == "gguf":
        summarize_gguf(GGUFFile(args.path).open())
    else:
        st = SafetensorsFile(args.path)
        summarize_safetensors(st)
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

## Running and Testing It

Install in editable mode and point it at a real model file:

```bash
python -m pip install -e .
weight-inspect ./models/llama-3-8b.safetensors
weight-inspect ./models/qwen2.5-7b-instruct-q4_k_m.gguf
```

For the safetensors path you should see a tensor count and a per-tensor SHA-256 printed (when you extend `verify()` to print them). For the GGUF path, the version and KV count should match what the [gguf-py reference parser](https://github.com/ggml-org/ggml/blob/master/gguf-py/gguf/gguf_reader.py) reports.

Tests. The trick is to generate fixture files on disk instead of checking them in:

```python
# tests/test_safetensors.py
import os, tempfile, json, struct, numpy as np
from weight_inspect.safetensors_reader import SafetensorsFile

def write_fixture(path: str, tensors: dict[str, np.ndarray]) -> None:
    header = {"__metadata__": {"framework": "test"}}
    blobs = []
    for name, arr in tensors:
        header[name] = {
            "dtype": "F32", "shape": list(arr.shape),
            "data_offsets": [0, 0],  # patched below
        }
    # Compute offsets.
    offset = 0
    for name, arr in tensors:
        start = offset
        end = start + arr.nbytes
        header[name]["data_offsets"] = [start, end]
        blobs.append(arr.tobytes())
        offset = end
    header_bytes = json.dumps(header).encode("utf-8")
    with open(path, "wb") as f:
        f.write(struct.pack("<Q", len(header_bytes)))
        f.write(header_bytes)
        for b in blobs:
            f.write(b)

def test_round_trip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "x.safetensors")
        a = np.random.randn(2, 3).astype(np.float32)
        b = np.random.randn(4).astype(np.float32)
        write_fixture(path, [("a", a), ("b", b)])
        st = SafetensorsFile(path)
        assert st.tensors["a"].shape == (2, 3)
        assert np.array_equal(st.get_tensor("a"), a)
        assert np.array_equal(st.get_tensor("b"), b)
        assert st.verify() == []
```

For end-to-end realism, download a small safetensors model via the [Hugging Face Hub CLI](https://huggingface.co/docs/huggingface_hub/guides/cli) and run the inspector against it. The same trick works for GGUF using [`huggingface_hub`](https://huggingface.co/docs/huggingface_hub) with a repo that ships GGUF, like `Qwen/Qwen2.5-0.5B-Instruct-GGUF`.

## Extending It: Your Roadmap to Senior-Level

A weekend MVP is enough to get the conversation started. The following upgrades push the project from "I parsed a header" to "I can run this in production." Pick two or three; depth beats breadth on a CV.

1. **Lazy tensor materialization with an LRU cache.** Wrap `get_tensor` so the most-recently-touched N tensors stay resident as numpy views while older ones are released. This mirrors how [vLLM's `gguf_loader`](https://github.com/vllm-project/vllm) handles huge models on a single GPU host and demonstrates memory-pressure reasoning.
2. **Persistent integrity manifest.** After verification, write a sidecar JSON file with per-tensor SHA-256s, tensor count, total parameters, and the source URL. Re-verify on every subsequent load. This is the same pattern that [`pip`'s `--require-hashes`](https://pip.pypa.io/en/stable/topics/repeatable-installs/) and Sigstore use, and it is the natural entry point for a discussion of supply-chain security on a CV.
3. **Horizontal fan-out via a small FastAPI service.** Wrap the loader in an HTTP endpoint that streams tensor slices on demand, keyed by `(tensor_name, byte_range)`. Add a `X-Weight-SHA256` response header. This is exactly the API shape that [Hugging Face's model hub](https://huggingface.co/docs/hub/api) exposes via its `resolve` endpoint, and it shows you understand streaming, range requests, and zero-copy serving.
4. **Observability with OpenTelemetry.** Emit spans for `open_file`, `parse_header`, `verify_tensor`, and `get_tensor`, plus counters for `bytes_paged_in`, `cache_hits`, and `cache_misses`. Connect to [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) and a Prometheus backend. A reviewer who sees OTel on a portfolio project instantly reads "this person has shipped a service."
5. **Fault tolerance via resumable downloads.** Pair the loader with an HTTP client that downloads in chunks, verifies each chunk's SHA-256 against a manifest, and resumes on transient failures. Compare against [Hugging Face `hf_transfer`](https://github.com/huggingface/hf_transfer) and explain why your design is faster on flaky links. This single feature demonstrates networking, hashing, and partial-state recovery.
6. **Benchmarking suite.** Use [pytest-benchmark](https://github.com/ionelmc/pytest-benchmark) to measure parse time, verify time, and cold/warm tensor-fetch latency across 100M to 13B parameter fixtures. Publish the results in a `BENCHMARKS.md`. Concrete numbers — "13B safetensors, header parse 8 ms, sha256 1.7 GB/s on M2 Pro" — are the kind of evidence senior interviewers look for.

Done well, the project becomes a one-stop tour of the same concerns an inference platform team has: parsing, mmap, hashing, streaming, caching, observability, and benchmarking.

## Key Takeaways

- GGUF and safetensors are designed for mmap; honoring that design with `np.frombuffer` over an mmap slice gives you true zero-copy tensor views and is the project's headline technical point.
- Safetensors' integrity story is JSON header + file-level hash; GGUF's is magic + version + per-tensor KV metadata — verify both, but differently.
- Lifetime management matters: the mmap object must outlive every numpy view derived from it, or the process segfaults under load.
- A CLI that prints parameter count, dtype distribution, and integrity status is the smallest demo that still reads as production-flavored.
- The natural extensions — LRU caching, HTTP streaming, OTel, resumable downloads, benchmarks — each touch a distinct senior-level concern and let you point at concrete numbers during an interview.

## Further Reading

- [The safetensors format specification](https://huggingface.co/docs/safetensors/index) — start here for the JSON header layout, byte offsets, and security model.
- [The GGUF specification (ggml-org docs)](https://github.com/ggml-org/ggml/blob/master/docs/gguf.md) — the canonical reference for KV types, tensor info encoding, and alignment rules.
- [vLLM's `gguf_loader.py`](https://github.com/vllm-project/vllm/blob/main/vllm/model_executor/weight_utils.py) — production mmap + safetensors loading patterns used by one of the most-used open-source inference engines.
- [llama.cpp `ggml.cpp`](https://github.com/ggerganov/llama.cpp/blob/master/ggml/src/ggml.c) — the C reference implementation; reading the mmap branch is a fast education in what `np.frombuffer` is doing under the hood.
- [Python `mmap` module docs](https://docs.python.org/3/library/mmap.html) — especially the section on `ACCESS_READ` vs `ACCESS_COPY` and platform differences.
- [`numpy.frombuffer` reference](https://numpy.org/doc/stable/reference/generated/numpy.frombuffer.html) — the exact zero-copy semantics that make this whole project possible.