---
title: "Inside DuckDB's Vectorized Execution Engine: How Columnar Storage Meets SIMD-Aware Query Processing"
date: "2026-09-07T04:00:29.603"
draft: false
tags: ["duckdb", "columnar-storage", "simd", "vectorized-execution", "olap", "query-engine"]
description: "A deep dive into DuckDB's vectorized execution engine, covering columnar storage, vectorized operators, SIMD-aware query processing, and why this design dominates OLAP workloads."
summary: "How DuckDB combines a columnar in-memory layout with vectorized, SIMD-aware operators to deliver analytical query performance that rivals dedicated warehouses — and why the same ideas are reshaping mainstream engines like Velox and DataFusion."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-inside-duckdb.svg"
  alt: "Stylized diagram of a columnar vector being processed by SIMD lanes."
  caption: ""
  relative: false
---

> **TL;DR** — DuckDB fuses two ideas that, on paper, shouldn't compose cleanly: a pure columnar in-memory format and a vectorized, SIMD-aware execution engine. The result is a single-process analytical database that routinely beats well-resourced cloud warehouses on per-core throughput, because the vector layout is also the operator layout is also the SIMD lane layout.

## Why Vectorization Won the Analytics Era

For most of the database era, the orthodoxy was clear: row stores for transactions, column stores for analytics. The split made sense in the disk era — a row store keeps a full record contiguous so updates and point lookups touch one page, while a column store keeps a single attribute contiguous so a scan over that attribute is cheap.

But that framing is incomplete. By the 2010s, three things changed simultaneously:

1. **Memory got cheaper than disk seeks.** A modern server can hold a 100 GB working set in RAM, and even modest laptops can host 16–32 GB. Compression ratios of 5–10× on columnar data made a "columnar warehouse" practical on a single node.
2. **CPUs became SIMD machines.** Every x86 server ships with AVX2 (256-bit registers, 8 lanes of 32-bit integers or 4 lanes of double-precision floats) and increasingly AVX-512 (512-bit, 16 or 8 lanes). A kernel that uses SIMD can multiply throughput on per-tuple work without any extra cores.
3. **The Volcano model hit a wall.** The classic [iterator / Volcano model](https://15721.courses.cs.cmu.edu/spring/2016/1541/slides/04-volcanostyle.pdf) popularized by Graefe processes one tuple at a time. For OLAP, where millions of tuples share the same operator, that's catastrophic: it starves the CPU's branch predictor, the instruction cache, and the SIMD lanes.

The response, pioneered in systems like [MonetDB/X100](https://www.cidrdb.org/cidr2005/papers/P12.pdf) and shipped commercially in systems like VectorWise and Snowflake, was **vectorized query execution**: process a chunk of tuples (typically 1,024 or 2,048) per operator call instead of one. DuckDB is the open-source apotheosis of that line of thinking, and it goes further — its vector layout is also its SIMD layout.

## The Columnar Memory Layout in DuckDB

DuckDB stores tables in **DataChunks**, which are logical units of a fixed number of rows (typically 2,048, configurable via [`SET vector_size_thread`](https://duckdb.org/docs/configuration/pragmas)). A `DataChunk` is composed of `Vector` objects — one per column. Each `Vector` has three components:
- A **physical type** (INT32, DOUBLE, VARCHAR, STRUCT, etc.).
- A **data buffer** holding the values contiguously.
- A **validity buffer** holding a bitmap indicating which rows are non-null.

This is the standard PAX-style decomposition. For a `SELECT a, b FROM t WHERE a > 10` query, the engine only has to touch the `a` column's data and validity buffers. The `b` column is not loaded, not decompressed, not even allocated in the inner loop.

Three further details matter:

1. **Compression is per-vector, not per-block.** DuckDB applies run-length encoding, dictionary encoding, frame-of-reference, and bitpacking on individual vectors. Because the working set is small (a single 2,048-row vector), the codec can be cheap and inline. The [DuckDB storage documentation](https://duckdb.org/docs/internals/storage) describes the bitpacking strategy used for integer columns.
3. **Strings are dictionary-encoded inside the vector.** When a query references a VARCHAR column, the actual values live in a per-vector dictionary, while the vector holds 32-bit dictionary indices. This keeps the data buffer aligned and predictable, which is exactly what SIMD wants.
4. **Nested types are stored as flat vectors with a child vector and a selection vector** — the same shape Arrow uses. This means DuckDB can ingest Parquet and Arrow with zero-copy on the columnar fast path, and operators can recurse over the child vectors without materializing the parent.

The end result: a DuckDB `Vector` of INT64 values is just `2,048 × 8 = 16 KB` of contiguous, cache-friendly memory. The CPU can stream it through L1 in a handful of cycles.

## What "Vectorized" Actually Means

The contrast with the Volcano iterator model is sharper than most introductions admit. In Volcano:

```
for each tuple t in child.next():
    if predicate(t):
        emit(t)
```

The function call overhead, the indirect branches, and the per-tuple materialization all conspire to keep the CPU from doing anything useful. In a vectorized engine:

```
auto batch = child.next();          // a DataChunk of 2,048 rows
auto sel = filter(batch, predicate); // a SelectionVector of matching indices
emit(batch, sel);
```

The predicate runs as a tight loop over a contiguous buffer. There is no function call per tuple, no virtual dispatch in the inner loop, and the output is itself a vector that feeds the next operator.

In DuckDB specifically, the inner loop of a comparison like `a > 10` typically looks like this at the C++ source:

```cpp
for (idx_t i = 0; i < count; i++) {
    auto val = lhs_data[i];
    result_data[i] = (val > threshold);
}
```

That looks naive — but it's exactly what the compiler wants. With `-O3 -mavx2`, the compiler auto-vectorizes the comparison into a sequence of `_mm256_cmpgt_epi32` instructions. The vector becomes a sequence of `1`s and `0`s packed into 256-bit registers, which can then be turned into a selection vector with `movemask` and a population count.

DuckDB goes further with **explicit SIMD intrinsics** in the hot paths. The hash join build, the bloom filter probe, the min/max over nullable columns, and the Parquet decoder all have hand-written AVX2 paths. The [`duckdb/duckdb` repository](https://github.com/duckdb/duckdb) has dozens of `__m256i` and `__m512i` declarations in `src/common/types/vector.cpp`, `src/execution/operator/join/physical_hash_join.cpp`, and the Parquet reader.

## SIMD-Aware Query Processing: Where the Magic Compounds

Two design choices compose to make DuckDB's per-core numbers look unreasonable.

### 1. The vector size matches the SIMD register width

DuckDB's default vector size (2,048) was chosen as a sweet spot: large enough to amortize function-call cost and saturate the cache prefetcher, small enough to fit comfortably in L1. But the per-operator inner loops are tiled in chunks that map to AVX2 registers:

- A `> 10` predicate on INT32 compiles to a sequence of 32-element chunks per pass (8 lanes × 4 unrolled iterations is a common pattern).
- A hash on INT64 chains three AVX2 multiplications and XORs per 4 lanes.
- A min/max reduction on DOUBLE reduces 4 lanes at a time via `_mm256_min_pd` until a scalar tail handles the leftovers.

The crucial point: **the data layout and the SIMD layout are aligned**. There is no gather, no scatter, no transposing between row-major and column-major. The compiler (and the human, when intrinsics are written by hand) sees a flat array and a register width that divides evenly into it.

### 2. Nulls and selection are first-class, not special cases

Most "vectorized" engines punt on nulls by storing a parallel bitmap and branching on it. DuckDB instead stores the validity bitmap as a flat bitset aligned to vector size and exploits the same SIMD lanes to evaluate predicates on it. The bitmask of matching rows is itself a vector of `1`s/`0`s; a final `movemask` extracts the byte pattern that becomes the selection vector for the next operator. Nulls are folded into the same machinery rather than handled as a slow path.

This compounds: a `SELECT a + b FROM t WHERE a > 10 AND b IS NOT NULL` evaluates two predicates in parallel, merges their bitmasks with `_mm256_and_si256`, and emits a selection vector that is the intersection — without ever materializing the rows that will be discarded.

## Architecture: How a Query Flows Through DuckDB

The end-to-end flow of an analytical query in DuckDB is a useful case study because it's small enough to hold in your head but representative of how any vectorized engine is structured.

```
SQL text
  → Postgres-compatible parser (libpg_query)
  → Binder (names → column refs)
  → Logical planner (relational algebra tree)
  → Optimizer (filter pushdown, join order, projection pull-up)
  → Physical planner (operators + pipelines)
  → Execution (vectorized, in-memory, parallel across cores)
```

The optimizer is interesting precisely because it's *not* trying to be a research toy. It does:

- **Predicate pushdown** — pushing filters into scans so a Parquet row group can be skipped without decompressing it (DuckDB reads Parquet row-group statistics and uses min/max to discard entire groups, as described in the [Parquet metadata spec](https://parquet.apache.org/docs/file-format/metadata/)).
- **Join ordering** — a dynamic programming-based join order optimizer for the small-to-medium queries that dominate interactive analytics.
- **Common subexpression elimination** and **constant folding**.

The physical plan is what the execution engine actually runs. For a query like:

```sql
SELECT region, AVG(amount)
FROM orders
WHERE order_date >= DATE '2026-01-01'
GROUP BY region;
```

the physical plan looks roughly like:

```
HASH_AGGREGATE(region, AVG(amount))
  └── HASH_JOIN(orders, ...)
        └── PARQUET_SCAN(orders, filter=[order_date >= 2026-01-01])
```

Each node is a `PhysicalOperator` with a `GetData` method that returns a `DataChunk`. The execution engine pulls chunks lazily, and the optimizer arranges nodes into **pipelines** that can execute with a single producer-consumer chain — no materialization between operators within a pipeline.

### Parallelism model

DuckDB parallelizes a single statement using a **Morsel-driven** approach, similar to [HyPer's](https://db.in.tum.de/~leis/papers/morsels.pdf) and [Vectorwise's](https://www.cidrdb.org/cidr2015/papers/p1111-boncz.pdf) design:

1. Each thread is assigned a contiguous range of the input — a *morsel*, typically a small batch of rows.
2. Threads build hash tables or sort partitions on their morsels independently.
3. A merge phase combines the per-thread partial results.

The interesting trick is that hash partitioning itself is vectorized: partitioning 2,048 rows through 16 buckets becomes 16 vectorized probes per batch. Each probe is itself SIMD-friendly because the hash values are computed in registers.

This design lets DuckDB scale linearly across cores for the bulk of analytical workloads. On a 16-core machine scanning 100 GB of Parquet, you can reasonably expect to see ~12–14 cores saturated, which is the practical ceiling for this kind of design.

## Patterns in Production: When Vectorized + Columnar Beats the Warehouse

The clearest demonstration of why this design works is DuckDB's behavior on [the Join Order Benchmark](https://github.com/duckdb/duckdb-benchmarks) — a workload derived from the original [Leis et al. paper on join ordering](https://15721.courses.cs.cmu.edu/spring/2016/1541/slides/04-volcanostyle.pdf), which runs 113 queries against the IMDB dataset (~21 GB raw). On a single 16-core workstation, DuckDB runs the full JOB in under a minute in many configurations; on cloud warehouses costing hundreds of dollars per hour, the same workload often takes longer per query because of network hops and shared infrastructure.

Three patterns where the design compounds particularly well:

### Local file analytics

`SELECT count(*), avg(price) FROM 'data/*.parquet'` is DuckDB's home turf. The Parquet reader is itself a vectorized, SIMD-accelerated decoder that produces `DataChunk`s directly. The query engine never has to materialize rows in any other format; columns stay columnar from disk to register. Latency is dominated by Parquet decompression, which is exactly the part of the workload that benefits from SIMD on the integer-decoded dictionary values.

### Embedded ETL

DuckDB is used as an in-process engine for [dbt's](https://github.com/dbt-labs/dbt-duckdb) and [Ibis's](https://ibis-project.org/) transformation layer. Because there's no IPC, no serialization, and no round-trip, the columnar vectors stay in process. A pandas DataFrame can be turned into a vectorized `DataChunk` via Arrow with a single zero-copy step.

### Edge analytics

A 200 MB DuckDB binary with no external dependencies can run a columnar, SIMD-aware engine on a laptop, a Raspberry Pi, or a satellite uplink. The same algorithmic ideas that power Snowflake's vectorized execution (which is built on a similar lineage) are available offline.

## How DuckDB Compares to Other Vectorized Engines

The vectorized columnar pattern isn't unique to DuckDB. The interesting question is what's different about DuckDB's specific take.

| Engine | Vector size | SIMD strategy | Storage |
|---|---|---|---|
| DuckDB | 2,048 (configurable) | Auto-vectorization + explicit intrinsics | Columnar, in-memory + Parquet on disk |
| [Velox](https://velox-lib.io/) | configurable (often 1,024) | Explicit intrinsics, codegen via LLVM | Decoupled, plugs into Meta's Presto/Gluten |
| [Apache DataFusion](https://arrow.apache.org/datafusion/) | 8,192 (default) | Auto-vectorization + Arrow SIMD kernels | In-memory Arrow + Parquet on disk |
| ClickHouse | blocks of 8,192 | explicit SIMD for hashing and string ops | columnar, hybrid disk/memory |
| Snowflake | micro-partitions, internal vectorization | heavily optimized C++ | proprietary cloud storage |

DuckDB's distinctive bet is **integration**: parser, optimizer, executor, storage, and Parquet reader are all in the same binary, all written by the same team, all using the same `Vector` and `DataChunk` types. Velox is more modular — it's a library, not a database — but that modularity has a coordination cost. DataFusion is similar in philosophy to DuckDB but rides on the Arrow ecosystem and emphasizes multi-language UDFs.

The other distinctive bet is **aggressive compiler use**. DuckDB compiles its operators with aggressive inlining and LTO. The same `DataChunk` type flows through `GetData`, `Filter`, `Project`, `HashJoin` — the compiler can see across boundaries and inline aggressively, which compounds the auto-vectorization wins.

## Trade-offs and Where Vectorized Columnar Hurts

The design isn't free. Three honest trade-offs:

1. **Updates are slow.** Mutating a single row requires updating the validity bitmap, the value buffer, possibly the dictionary for VARCHARs, and any indexes. DuckDB is OLAP-only, not OLTP. If your update rate is more than a trickle, look at [DuckLake](https://duckdb.org/2025/05/14/ducklake.html) or a row store.
2. **Small cardinality is awkward.** When a `VARCHAR(2)` column is dictionary-encoded into 3 distinct values but stored as 32-bit indices, you've spent 32 bits per row to encode 2 bits of information. DuckDB mitigates this with smallint-indexed dictionaries, but the compression can't beat a flat layout when the cardinality is genuinely small.
3. **Wide rows are wide.** A query like `SELECT * FROM t` on a 200-column table pulls 200 vectors and feeds them through the operator pipeline. The vector size doesn't help when the bottleneck is cache misses across columns.

These are the reasons Hybrid Transactional/Analytical Processing (HTAP) engines — [TiDB](https://docs.pingcap.com/), [SingleStore](https://www.singlestore.com/), [CockroachDB](https://www.cockroachlabs.com/docs/) — maintain both a row store for transactions and a columnar replica for analytics. Vectorized columnar execution is a *workload-specific* design, not a universal one.

## Key Takeaways

- DuckDB fuses two ideas from the columnar analytics lineage: pure columnar in-memory storage and vectorized, SIMD-aware execution. The same `Vector` type is the storage layout, the operator I/O unit, and the SIMD tile.
- Vectorization (one operator call per ~2,048 rows, not per row) is what makes the CPU's pipeline and branch predictor productive. SIMD is what makes each vectorized call faster on top of that.
- DuckDB compresses and dictionary-encodes per-vector, which keeps the inner loops branch-light and the data buffer cache-friendly — the input to SIMD is exactly the layout SIMD wants.
- The execution model is pipeline-based and morsel-driven for parallelism. Within a pipeline, operators hand `DataChunk`s directly to each other without materialization.
- The same design lineage shows up in Velox, DataFusion, ClickHouse, and Snowflake. DuckDB's distinctive contribution is the depth of integration and aggressive use of auto-vectorization plus hand-written intrinsics in the hot paths.
- The design is OLAP-specialized. Updates are slow, and very wide rows expose the limits of columnar compression. For transactional or mixed workloads, a different engine is the right tool.

## Further Reading

- [The MonetDB/X100 paper (CIDR 2005)](https://www.cidrdb.org/cidr2005/papers/P12.pdf) — the original argument for vectorized execution on columnar data, and the lineage DuckDB inherits from.
- [Morsel-driven parallelism (Boncz et al., VLDB 2014)](https://db.in.tum.de/~leis/papers/morsels.pdf) — the parallelism model DuckDB uses to scale across cores.
- [Vectorized query execution for Apache Arrow and DataFusion](https://arrow.apache.org/blog/2022/11/26/introducing-arrow-datafusion/) — a sibling architecture in the Rust/Arrow world.
- [Velox: Meta's unified execution engine](https://velox-lib.io/) — a C++ vectorized library used to power Presto and other engines.
- [DuckDB's official "Why DuckDB" page](https://duckdb.org/why_duckdb) — the project's own framing of when this engine is and isn't the right tool.
- [DuckDB's internals documentation](https://duckdb.org/docs/internals/overview) — the source of truth for vector sizes, compression, and execution model details.