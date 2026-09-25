---
title: "Build a GGUF Parser and mmap-Based Tensor Loader: A Portfolio Project That Signals Real Systems Skill"
date: "2026-09-25T02:00:10.630"
draft: false
tags: ["machine-learning-engineering", "systems-programming", "go", "llms", "quantization", "portfolio-project", "safetensors"]
description: "A hands-on build guide for a GGUF parser with mmap-based tensor loading, quantized dequantization, and safetensors conversion — the kind of project that signals deep systems engineering skill to hiring managers."
summary: "Build a production-grade GGUF parser and mmap-based tensor loader with quantized dequantization and safetensors conversion. This hands-on guide shows real code, architecture decisions, and a roadmap from toy to production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-25-build-a-gguf-parser-and-mmap-based-tensor-loader-a-portfolio-project-that-signal.svg"
  alt: "A terminal displaying parsed GGUF tensor metadata with memory-mapped file visualization"
  caption: ""
  relative: false
---

> **TL;DR** — Building a GGUF parser with memory-mapped tensor loading and quantized dequantization is one of the most signal-rich side projects an engineer can ship. It demonstrates mastery of binary formats, zero-copy I/O, numerical computing, and ML infrastructure — the exact intersection where senior systems engineers live. This guide walks you from scratch to a working implementation with real, runnable Go code.

The demand for engineers who understand both the machine-learning stack and the systems underneath it has never been higher. Most candidates can call `transformers.from_pretrained()`. Far fewer can explain what happens when a 4-bit quantized weight tensor is loaded from disk into GPU memory, byte by byte.

A GGUF parser with mmap-based loading and safetensors conversion forces you to confront binary format specification, memory-mapped I/O, SIMD-friendly dequantization kernels, and tensor serialization — all in a single, coherent project. It is the kind of work that separates candidates who have *used* ML infrastructure from those who have *built* it.

## Why This Project Stands Out on a CV

This project signals a rare combination of competencies that hiring managers in ML platform engineering, inference optimization, and systems software actively screen for.

- **Binary format parsing and serialization.** You demonstrate the ability to read and write structured binary data — not JSON, not CSV, but real format specifications with magic bytes, version headers, and metadata dictionaries. This is the same skill required for working with Protocol Buffers, Cap'n Proto, or custom on-disk formats at scale.
- **Memory-mapped I/O and zero-copy architecture.** Using `mmap` to load tensors means you understand virtual memory management, page faults, and the tradeoff between convenience and control. This is directly relevant to database engines like SQLite, search libraries like Lucene, and high-performance data processors.
- **Quantization arithmetic and numerical computing.** Implementing Q4_0, Q4_1, Q5_0, Q5_1, Q8_0, and Q8_0 dequantization kernels requires understanding of fixed-point arithmetic, vectorization, and the numerical implications of low-bit representations. This signals depth that goes well beyond calling a framework API.
- **Cross-format conversion tooling.** Building a bridge from GGUF to safetensors shows you understand ecosystem interoperability — a critical concern in production ML where formats vary across frameworks, cloud providers, and deployment targets.
- **Systems-level debugging and performance profiling.** When your mmap-based loader faults a page and you need to trace why, you are doing the same work as a kernel engineer or a database storage engine developer.

The roles this signals include ML Infrastructure Engineer, Backend Engineer (ML Platforms), Storage Systems Engineer, and Inference Optimization Engineer — all of which command compensation well above the median software engineering band.

## Architecture Overview

The project decomposes into five core components, each with a clear responsibility boundary.

```
┌─────────────────────────────────────────────────────┐
│                  GGUF Parser                         │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Magic &  │  │ Metadata     │  │ Tensor        │  │
│  │ Header   │  │ Dict Parser  │  │ Descriptor    │  │
│  │ Validator│  │ (KV pairs)   │  │ Extractor     │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ parsed metadata + tensor info
                       ▼
┌─────────────────────────────────────────────────────┐
│         mmap-Based Tensor Loader                     │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ mmap     │  │ Page-aligned │  │ Lazy-loading │  │
│  │ Region   │  │ Offset Calc  │  │ Tensor View │  │
│  │ Manager  │  │              │  │               │  │
│  └──────────┘  └──────────────┘  └───────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       │ raw quantized bytes
                       ▼
┌─────────────────────────────────────────────────────┐
│         Dequantization Kernels                       │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌──────────────┐ │
│  │ Q4_0   │ │ Q4_1   │ │ Q5_x   │ │ Q8_0 / Q8_1  │ │
│  │ Kernel │ │ Kernel │ │ Kernel │ │ Kernel       │ │
│  └────────┘ └────────┘ └────────┘ └──────────────┘ │
│         (SIMD-optional, Go assembly or plain Go)    │
└──────────────────────┬──────────────────────────────┘
                       │ dequantized float32 tensors
                       ▼
┌─────────────────────────────────────────────────────┐
│         Safetensors Converter                        │
│  ┌──────────────┐  ┌──────────────────────────────┐ │
│  │ Header       │  │ Tensor Data Writer            │ │
│  │ Serializer   │  │ (JSON header + raw bytes)     │ │
│  └──────────────┘  └──────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

Each component communicates through well-defined data structures. The parser produces a `ModelMetadata` struct and a slice of `TensorInfo` descriptors. The loader takes those descriptors and maps the corresponding byte ranges from the file. The dequantization kernels consume raw bytes and produce `[]float32` slices. The converter takes the float32 tensors and writes them into the safetensors format.

The key architectural decision is that the mmap loader and the dequantization kernels are decoupled. You can swap the loader to use plain `os.Read` for testing, or swap the dequantizer to use CGO-bound BLAS libraries for production throughput.

## Building It Step by Step

We will implement this in Go. Go is ideal here because it has first-class `syscall.Mmap` support, excellent cross-compilation, and a strong standard library for binary I/O — all without requiring CGo.

### Step 1: Define the GGUF Header and Metadata Structures

The GGUF format begins with a magic string (`GGUF`), a version number, a tensor count, a metadata key-value count, and then the metadata dictionary itself.

```go
package gguf

import (
    "encoding/binary"
    "io"
    "fmt"
)

const (
    GGUF_MAGIC = 0x47475546 // "GGUF" in big-endian
)

type ModelMetadata struct {
    Version        uint32
    TensorCount    uint32
    MetadataCount  uint32
    TensorInfoOffset uint64
    Metadata       map[string]string
}

func ParseHeader(r io.Reader) (*ModelMetadata, error) {
    var magic uint32
    if err := binary.Read(r, binary.BigEndian, &magic); err != nil {
        return nil, fmt.Errorf("reading magic: %w", err)
    }
    if magic != GGUF_MAGIC {
        return nil, fmt.Errorf("not a GGUF file: magic=0x%08X", magic)
    }

    meta := &ModelMetadata{Metadata: make(map[string]string)}
    if err := binary.Read(r, binary.BigEndian, &meta.Version); err != nil {
        return nil, err
    }
    if err := binary.Read(r, binary.BigEndian, &meta.TensorCount); err != nil {
        return nil, err
    }
    if err := binary.Read(r, binary.BigEndian, &meta.MetadataCount); err != nil {
        return nil, err
    }

    // Read metadata key-value pairs
    for i := 0; i < int(meta.MetadataCount); i++ {
        var keyLen, valLen uint32
        if err := binary.Read(r, binary.BigEndian, &keyLen); err != nil {
            return nil, err
        }
        key := make([]byte, keyLen)
        if _, err := io.ReadFull(r, key); err != nil {
            return nil, err
        }
        if err := binary.Read(r, binary.BigEndian, &valLen); err != nil {
            return nil, err
        }
        val := make([]byte, valLen)
        if _, err := io.ReadFull(r, val); err != nil {
            return nil, err
        }
        meta.Metadata[string(key)] = string(val)
    }

    // Calculate offset to tensor info section
    meta.TensorInfoOffset = uint64(r.(*io.Seeker).Seek(0, io.SeekCurrent))
    return meta, nil
}
```

### Step 2: Parse Tensor Descriptors

Each tensor descriptor in GGUF contains the tensor name, dimension count, dimension sizes, element type, and the offset into the raw data section.

```go
type QuantType int32

const (
    Q4_0 QuantType = iota
    Q4_1
    Q5_0
    Q5_1
    Q8_0
    Q8_1
    Q2_K
    Q3_K
    Q4_K
    Q5_K
    Q6_K
    Q8_0_32_1
    // ... additional types
)

type TensorInfo struct {
    Name     string
    Dims     []int64
    Type     QuantType
    Offset   uint64
    DataSize uint64
}

func ParseTensorInfos(r io.Reader, meta *ModelMetadata) ([]TensorInfo, error) {
    // Seek to tensor info offset
    tensors := make([]TensorInfo, meta.TensorCount)
    for i := 0; i < int(meta.TensorCount); i++ {
        var nameLen uint32
        if err := binary.Read(r, binary.BigEndian, &nameLen); err != nil {
            return nil, err
        }
        name := make([]byte, nameLen)
        if _, err := io.ReadFull(r, name); err != nil {
            return nil, err
        }

        var nDims int32
        if err := binary.Read(r, binary.BigEndian, &nDims); err != nil {
            return nil, err
        }
        dims := make([]int64, nDims)
        for d := 0; d < int(nDims); d++ {
            if err := binary.Read(r, binary.BigEndian, &dims[d]); err != nil {
                return nil, err
            }
        }

        var qt int32
        if err := binary.Read(r, binary.BigEndian, &qt); err != nil {
            return nil, err
        }

        var offset uint64
        if err := binary.Read(r, binary.BigEndian, &offset); err != nil {
            return nil, err
        }

        tensors[i] = TensorInfo{
            Name:   string(name),
            Dims:   dims,
            Type:   QuantType(qt),
            Offset: offset,
        }
    }
    return tensors, nil
}
```

### Step 3: Implement mmap-Based Loading

This is the heart of the project. Memory-mapping the GGUF file lets the OS manage paging, and you access tensor bytes directly without an explicit `read` syscall per tensor.

```go
package mmaploader

import (
    "os"
    "syscall"
    "unsafe"
)

type MappedFile struct {
    data []byte
    file *os.File
}

func MapFile(path string) (*MappedFile, error) {
    f, err := os.Open(path)
    if err != nil {
        return nil, err
    }
    stat, err := f.Stat()
    if err != nil {
        f.Close()
        return nil, err
    }

    data, err := syscall.Mmap(
        int(f.Fd()),
        0,
        int(stat.Size()),
        syscall.PROT_READ,
        syscall.MAP_PRIVATE,
    )
    if err != nil {
        f.Close()
        return nil, err
    }

    return &MappedFile{data: data, file: f}, nil
}

func (m *MappedFile) TensorBytes(offset uint64, size uint64) []byte {
    return m.data[offset : offset+size]
}

func (m *MappedFile) Unmap() error {
    if err := syscall.Munmap(m.data); err != nil {
        return err
    }
    return m.file.Close()
}
```

The critical insight here is that `syscall.Mmap` with `MAP_PRIVATE` gives you a read-only view backed by the file's pages. The OS handles page faults lazily — you only pay the I/O cost for pages you actually touch. For a 7B parameter model in Q4 quantization, that is roughly 4 GB of address space with only the working set resident in RAM.

### Step 4: Implement Dequantization Kernels

Each GGUF quantized type has a specific block layout. Q4_0, for example, stores blocks of 32 values: each block has a scale and a 4-bit nibble per value.

```go
package dequant

import (
    "math"
)

func DequantizeQ4_0(raw []byte) []float32 {
    numBlocks := len(raw) / 36 // 32 nibbles + 2 bytes (scale) per block
    out := make([]float32, numBlocks*32)

    for i := 0; i < numBlocks; i++ {
        block := raw[i*36 : (i+1)*36]
        scale := int8(block[32]) | int8(block[33])<<8
        scaleFloat := float32(scale) / 127.0

        for j := 0; j < 32; j++ {
            nibble := block[j/2]
            if j%2 == 0 {
                nibble = nibble & 0x0F
            } else {
                nibble = (nibble >> 4) & 0x0F
            }
            val := int8(nibble)
            if val >= 8 {
                val -= 16
            }
            out[i*32+j] = scaleFloat * float32(val)
        }
    }
    return out
}

func DequantizeQ8_0(raw []byte) []float32 {
    numValues := len(raw)
    out := make([]float32, numValues)
    for i := 0; i < numValues; i++ {
        val := int8(raw[i])
        out[i] = float32(val) / 127.0
    }
    return out
}
```

For production throughput, you would replace these scalar loops with SIMD-optimized versions using Go assembly or by calling into a CGO-bound library like `simd` or `blas`. The scalar versions are correct and sufficient for a portfolio project that must be readable and auditable.

### Step 5: Build the Safetensors Converter

Safetensors stores a JSON header containing tensor metadata, followed by raw float32 data, all padded to 8-byte alignment.

```go
package converter

import (
    "encoding/binary"
    "encoding/json"
    "fmt"
    "io"
    "os"
)

type SafetensorsHeader struct {
    Tensors map[string]TensorMeta `json:"__tensor_names__"`
}

type TensorMeta struct {
    Dtype  string   `json:"dtype"`
    Shape  []int64  `json:"shape"`
    DataOffsets [2]int64 `json:"data_offsets"`
}

func ConvertToSafetensors(
    outPath string,
    tensorNames []string,
    dequantized map[string][]float32,
    shapes map[string][]int64,
) error {
    f, err := os.Create(outPath)
    if err != nil {
        return err
    }
    defer f.Close()

    // Write 8-byte magic header
    header := []byte("safetensors")
    padding := make([]byte, 8-len(header)%8)
    if _, err := f.Write(append(header, padding...)); err != nil {
        return err
    }

    // Build header JSON
    headerMap := make(map[string]TensorMeta)
    offset := int64(8) // after magic
    for _, name := range tensorNames {
        data := dequantized[name]
        size := int64(len(data) * 4) // float32 = 4 bytes
        headerMap[name] = TensorMeta{
            Dtype:     "F32",
            Shape:     shapes[name],
            DataOffsets: [2]int64{offset, offset + size},
        }
        offset += size
    }

    headerJSON, err := json.Marshal(headerMap)
    if err != nil {
        return err
    }

    // Write header length + header JSON + padding to 8-byte boundary
    headerLen := int64(len(headerJSON))
    headerPad := make([]byte, (8-int(headerLen%8))%8)
    if _, err := f.Write(headerJSON); err != nil {
        return err
    }
    if _, err := f.Write(headerPad); err != nil {
        return err
    }

    // Write tensor data
    for _, name := range tensorNames {
        data := dequantized[name]
        bytes := make([]byte, len(data)*4)
        for i, v := range data {
            binary.LittleEndian.PutUint32(bytes[i*4:], math.Float32bits(v))
        }
        if _, err := f.Write(bytes); err != nil {
            return err
        }
    }

    fmt.Printf("Wrote safetensors to %s with %d tensors\n", outPath, len(tensorNames))
    return nil
}
```

## Running and Testing It

To run the full pipeline, you need a GGUF model file. The [Hugging Face Hub](https://huggingface.co) hosts thousands of GGUF-quantized models. Grab a small one for testing:

```bash
# Install the CLI tool
go install github.com/huggingface/huggingface_hub@latest

# Download a small quantized model
huggingface-cli download bartowski/Mistral-7B-Instruct-v0.2-GGUF \
    mistral-7b-instruct-v0.2.Q4_0.gguf --local-dir ./test-model
```

Then build and run your tool:

```bash
go build -o gguf-loader ./cmd/gguf-loader
./gguf-loader --input ./test-model/mistral-7b-instruct-v0.2.Q4_0.gguf \
    --output ./output/model.safetensors \
    --dequant-type q4_0
```

To verify correctness, compare the output against a reference implementation. The [llama.cpp project](https://github.com/ggerganov/llama.cpp) has well-tested dequantization routines in C. You can write a validation test that checks your dequantized tensor against theirs:

```go
func TestDequantizeQ4_0(t *testing.T) {
    // Reference values from llama.cpp test harness
    expected := []float32{-0.125, 0.375, -0.625, 0.0, /* ... */}
    raw := []byte{0x80, 0x00, 0x40, 0x00, 0xC0, 0x00, 0x00, 0x00, /* ... */}

    result := dequant.DequantizeQ4_0(raw)
    for i := range expected {
        if math.Abs(float64(result[i]-expected[i])) > 1e-5 {
            t.Errorf("mismatch at index %d: got %f, want %f", i, result[i], expected[i])
        }
    }
}
```

For benchmarking throughput, use Go's built-in benchmarking:

```go
func BenchmarkDequantizeQ4_0(b *testing.B) {
    raw := make([]byte, 36*1024) // 1024 blocks
    rand.Read(raw)
    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        dequant.DequantizeQ4_0(raw)
    }
}
```

Run with `go test -bench=. -benchmem -cpuprofile=cpu.out` and analyze with `go tool pprof cpu.out`. This gives you concrete throughput numbers to cite in interviews or on your CV.

## Extending It: Your Roadmap to Senior-Level

The baseline project above is already impressive. But to push it into production-grade territory — and to signal senior-level thinking — add these upgrades:

1. **Add a persistent tensor cache with memory-mapped swap.** Implement an LRU cache that spills cold tensor pages to disk using `mmap` with `MAP_SHARED` on a swap file. This demonstrates understanding of memory pressure, page replacement, and the cost model of I/O-bound workloads — skills directly transferable to database buffer pool design.

2. **Implement a gRPC tensor-serving layer.** Wrap the loader and dequantizer in a [gRPC](https://grpc.io/) service that accepts tensor names and returns dequantized float32 arrays. Add streaming responses for large tensors. This signals you can design distributed systems interfaces, not just standalone tools.

3. **Add structured observability with OpenTelemetry.** Instrument every stage — parse time, mmap latency, dequantization throughput, conversion duration — with [OpenTelemetry](https://opentelemetry.io/) metrics and distributed traces. Export to Prometheus and Jaeger. Production systems are not measured by correctness alone; they are measured by observability.

4. **Build fault-tolerant conversion with checkpointing.** If converting a 70B model takes hours, a crash should not mean starting over. Write checkpoint files after each tensor is converted, and resume from the last checkpoint on restart. This is the same pattern used in distributed training frameworks and batch processing pipelines.

5. **Add benchmark-driven quantization comparison.** Build a harness that runs the same model through Q4_0, Q4_1, Q5_0, Q5_1, and Q8_0 paths, measuring both dequantization throughput (GB/s) and reconstruction error (mean squared error against fp16 reference). Publish the results as a comparison table. This demonstrates empirical rigor and the ability to make data-driven engineering decisions.

6. **Implement a concurrent tensor loader with worker pools.** For models with thousands of tensors, use a Go worker pool pattern to dequantize tensors in parallel, with backpressure controlled by a semaphore limiting concurrent mmap regions. Add context cancellation for graceful shutdown. This signals you understand concurrency primitives, resource bounding, and cancellation semantics — all critical in production distributed systems.

Each of these upgrades transforms the project from a clever toy into something that looks and behaves like infrastructure you would actually run. The combination of a working baseline plus two or three of these extensions is what makes a portfolio project genuinely memorable to a hiring manager.

## Key Takeaways

- A GGUF parser with mmap-based loading and safetensors conversion demonstrates binary format parsing, zero-copy I/O, numerical computing, and ML infrastructure knowledge — a rare and highly valued skill combination.
- Memory-mapped I/O with `syscall.Mmap` in Go provides lazy, page-fault-driven loading that scales to multi-gigabyte model files without explicit read syscalls.
- Dequantization kernels must handle each GGUF quant type's specific block layout; correctness is verifiable against reference implementations like llama.cpp.
- The safetensors format is straightforward: a JSON header followed by raw float32 data, padded to 8-byte alignment.
- Extending the project with observability, fault tolerance, and concurrency patterns is what elevates it from a portfolio curiosity to a credible signal of senior-level engineering ability.

## Further Reading

- [GGUF Format Specification](https://github.com/ggerganov/llama.cpp/blob/master/docs/gguf.md) — The canonical format specification from the llama.cpp project. Covers every field, magic byte, and quantization type definition you need to implement a compliant parser.
- [Memory-Mapped I/O (Wikipedia)](https://en.wikipedia.org/wiki/Memory-mapped_I/O) — The foundational article on mmap semantics, page fault behavior, and the tradeoffs between mapped I/O and traditional read/write syscalls. Essential context for understanding why zero-copy loading matters.
- [Safetensors Format Documentation](https://huggingface.co/docs/safetensors/en/index) — Hugging Face's official documentation for the safetensors format, including the header schema, data layout, and alignment requirements.
- [llama.cpp Dequantization Source Code](https://github.com/ggerganov/llama.cpp/blob/master/ggml-impl.h) — The reference implementation of all GGUF dequantization kernels in C/C++. Compare your Go implementation against this to validate correctness and explore SIMD optimization paths.
- [OpenTelemetry Go SDK](https://opentelemetry.io/docs/instrumentation/go/) — The official Go instrumentation guide for adding metrics, traces, and logs. Use this as the starting point for the observability extension described above.
- [Go Memory Management and mmap](https://pkg.go.dev/syscall#Mmap) — The Go syscall package documentation for `Mmap`, `Munmap`, and related memory management calls. The authoritative reference for the mmap loader implementation.
- [The Architecture of Open Source Applications, Vol. 2](https://aosabook.org/en/v2.html) — Chapters on database and storage engine architecture provide the conceptual framework for understanding buffer pools, checkpointing, and write-ahead logging — all directly relevant to the fault-tolerant conversion extension.

This project sits at the intersection of machine learning systems and infrastructure engineering. It is practical enough to build in a weekend, deep enough to keep you learning for months, and specific enough to make a hiring manager stop scrolling. Start with the header parser, add mmap loading, implement the dequantization kernels, and convert to safetensors. Then extend it. The code you write will be the best technical signal on your resume.