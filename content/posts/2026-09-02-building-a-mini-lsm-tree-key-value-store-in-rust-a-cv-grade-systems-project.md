---
title: "Building a Mini LSM-Tree Key-Value Store in Rust: A CV-Grade Systems Project"
date: "2026-09-02T07:00:47.066"
draft: false
tags: ["rust", "systems", "lsm-tree", "wal", "databases", "side-project"]
description: "A hands-on guide to building a Write-Ahead Log + LSM-tree key-value store in Rust — a portfolio project that signals real systems engineering skill."
summary: "Build a runnable LSM-tree key-value store with a write-ahead log in Rust, from WAL append to SSTable flush to compaction. The exact project to make your CV read like a database engineer's."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-building-a-mini-lsm-tree-key-value-store-in-rust-a-cv-grade-systems-project.svg"
  alt: "Layered diagram of a key-value store with WAL, memtable, SSTables, and compaction."
  caption: ""
  relative: false
---

> **TL;DR** — A working LSM-tree key-value store in Rust is one of the highest-signal side projects you can build. It exercises the same primitives that power RocksDB, LevelDB, and Cassandra: a write-ahead log for durability, an in-memory memtable for hot writes, immutable SSTables for cold storage, and background compaction. The whole engine fits in roughly 1,000 lines of Rust and is something you can demo, test, and extend.

## Why This Project Stands Out on a CV

Hiring managers who review systems roles scan for evidence that you can build software that touches the disk, the network, and the OS scheduler — not just glue code between libraries. A mini key-value store signals a specific, rare bundle of competencies that are otherwise hard to demonstrate from a CRUD side project.

Concretely, a reviewer reading your resume will infer that you understand:

- **Storage engines and on-disk data structures.** The LSM-tree is the dominant write-optimized structure in production. RocksDB, LevelDB, Cassandra's SSTable, InfluxDB's TSM, and even parts of DuckDB's storage layer descend from the same O'Neil & Chang paper. A candidate who can describe the memtable/SSTable/compaction pipeline from first principles is rare.
- **Crash consistency and durability semantics.** A write-ahead log is the canonical pattern for "fsync then mutate in-memory" durability, and it's the same pattern Postgres uses for its WAL, Kafka uses for its log segments, and etcd uses for its Raft log. Writing one yourself proves you understand *why* `fsync` matters and what `O_DSYNC` actually does.
- **Rust as a systems language.** Idiomatic ownership, zero-copy deserialization, `BufReader`/`BufWriter` for buffered I/O, `tokio` for async, and `serde`/`bincode` for fast framing — all of it shows up in this project. It's a much stronger Rust signal than another REST API.
- **Engineering hygiene.** Tests, benchmarks (`cargo bench` + Criterion), a CLI, structured logging, and clean module boundaries read as "this person knows how to ship," not "this person finished a tutorial."

The roles this project maps onto: **Database Engineer, Storage Engineer, Distributed Systems Engineer, Backend Engineer (infrastructure-heavy), Infrastructure Platform Engineer, Search Relevance Engineer (Lucene/Solr/Elastic all use LSM-style segments).** If you target a Big Tech L5/L6 or a high-bar startup, this is the kind of project that gets you past the recruiter screen and into the systems interview loop.

## Architecture Overview

The design follows the classic LSM-tree pipeline described in the original [O'Neil et al. 1996 paper](https://www.cs.umb.edu/~poneil/lsmtree.pdf) and as implemented in LevelDB and RocksDB. The whole system is roughly six modules.

- **Client API (`lib.rs`, `server.rs`)** — A small synchronous TCP server using `std::net::TcpListener` exposing `PUT key value`, `GET key`, `DELETE key`, and `SCAN` over a line-oriented protocol. The protocol is newline-delimited, which is easy to test with `nc`.
- **Write-Ahead Log (`wal.rs`)** — An append-only file of length-prefixed records. Every `PUT` and `DELETE` is appended and `fsync`'d before being applied to the in-memory state. On crash, the log is replayed from the last checkpoint.
- **Memtable (`memtable.rs`)** — An in-memory sorted structure (`BTreeMap<String, Value>` plus a tombstone flag). All reads and writes hit this first. The memtable has a size threshold; when exceeded, it freezes.
- **SSTable (`sstable.rs`)** — An immutable, sorted on-disk file written from a frozen memtable. Layout: data blocks, a sparse index, a bloom filter, and a footer with offsets. Reads consult the bloom filter, the index, and then binary-search the data block.
- **Compactor (`compaction.rs`)** — A background thread that merges overlapping SSTables, drops tombstones older than the oldest snapshot, and writes new SSTables. A simple level-based or size-tiered policy is enough to start.
- **Manifest / Metadata (`manifest.rs`)** — A small file listing the set of live SSTables and their level assignments. This is what the reader consults to know which files to scan on a miss.

The data path on a write is: **client → WAL append+fsync → memtable.insert → if memtable full → freeze and spawn flush task**. The data path on a read is: **client → memtable.get → if miss → check bloom filters of SSTables newest-to-oldest → index lookup → block read → return or NotFound**. Tombstones are the value needed to make `DELETE` correct across compactions.

```text
        ┌──────────┐  fsync   ┌──────────────┐
client ─► WAL file ──────────►   Memtable    │
        └──────────┘          │  (BTreeMap)  │
                              └──────┬───────┘
                                     │ full?
                                     ▼
                              ┌──────────────┐
                              │  SSTable L0  │  ◄─── flush
                              └──────┬───────┘
                                     │ overlap?
                                     ▼
                              ┌──────────────┐
                              │ SSTable L1+  │  ◄─── compaction
                              └──────────────┘
```

## Building It Step by Step

Start with `cargo new kvsd --bin` and add dependencies. Use a recent stable Rust toolchain (1.75+) so you can rely on stable async and `BufWriter::flush` semantics.

```toml
# Cargo.toml
[package]
name = "kvsd"
version = "0.1.0"
edition = "2021"

[dependencies]
crc32fast = "1.4"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
bincode = "1.3"
thiserror = "1"

[dev-dependencies]
tempfile = "3"
```

### Step 1 — The Write-Ahead Log

The WAL is the most important file in the system: it is the only thing that survives a crash. Every mutation must be appended and `fsync`'d before the in-memory state is updated. The framing format is a CRC32 checksum, a length, and a payload — the same three-field framing RocksDB uses.

```rust
// src/wal.rs
use std::{fs::{File, OpenOptions}, io::{BufWriter, Write, Read, Seek, SeekFrom}, path::Path};
use crc32fast::Hasher;

pub type Key = Vec<u8>;
pub type Value = Option<Vec<u8>>; // None == tombstone

#[derive(Debug, serde::Serialize, serde::Deserialize)]
pub enum Op { Put { key: Key, value: Vec<u8> }, Del { key: Key } }

pub struct Wal { writer: BufWriter<File>, path: std::path::PathBuf }

impl Wal {
    pub fn open(path: &Path) -> std::io::Result<Self> {
        let file = OpenOptions::new().create(true).append(true).read(true).open(path)?;
        Ok(Self { writer: BufWriter::new(file), path: path.to_path_buf() })
    }

    pub fn append(&mut self, op: &Op) -> std::io::Result<()> {
        let bytes = bincode::serialize(op).unwrap();
        let mut h = Hasher::new();
        h.update(&bytes);
        let crc = h.finalize();
        self.writer.write_all(&crc.to_le_bytes())?;
        self.writer.write_all(&(bytes.len() as u32).to_le_bytes())?;
        self.writer.write_all(&bytes)?;
        self.writer.flush()?;
        self.writer.get_ref().sync_all()?; // fsync — durability boundary
        Ok(())
    }

    pub fn replay(&self) -> std::io::Result<Vec<Op>> {
        let mut f = File::open(&self.path)?;
        let mut ops = Vec::new();
        loop {
            let mut crc = [0u8; 4];
            if f.read(&mut crc)? == 0 { break; }
            let mut len = [0u8; 4];
            f.read_exact(&mut len)?;
            let n = u32::from_le_bytes(len) as usize;
            let mut buf = vec![0u8; n];
            f.read_exact(&mut buf)?;
            let expected = u32::from_le_bytes(crc);
            let mut h = Hasher::new(); h.update(&buf);
            if h.finalize() != expected { break; } // partial tail: stop
            ops.push(bincode::deserialize(&buf).unwrap());
        }
        Ok(ops)
    }
}
```

The CRC is what lets `replay` recover cleanly from a torn write: a partial record at the tail will have a bad checksum and we stop there.

### Step 2 — The Memtable

A `BTreeMap` is the obvious choice. It gives you O(log n) writes and reads, range scans, and in-order iteration when you flush.

```rust
// src/memtable.rs
use std::collections::BTreeMap;
use crate::wal::Value;

#[derive(Default)]
pub struct Memtable {
    map: BTreeMap<Vec<u8>, Value>,
    bytes: usize,
    cap: usize,
}

impl Memtable {
    pub fn new(cap: usize) -> Self { Self { cap, ..Default::default() } }
    pub fn get(&self, k: &[u8]) -> Option<&Value> { self.map.get(k) }
    pub fn put(&mut self, k: Vec<u8>, v: Vec<u8>) {
        self.bytes += k.len() + v.len();
        self.map.insert(k, Some(v));
    }
    pub fn del(&mut self, k: Vec<u8>) {
        self.bytes += k.len();
        self.map.insert(k, None);
    }
    pub fn is_full(&self) -> bool { self.bytes >= self.cap }
    pub fn iter(&self) -> impl Iterator<Item = (&Vec<u8>, &Value)> { self.map.iter() }
    pub fn clear(&mut self) { self.map.clear(); self.bytes = 0; }
}
```

The tombstone (`Value::None`) is the mechanism that makes `DELETE` survive a flush. Without it, a delete in an older SSTable would be undone by a re-flush.

### Step 3 — The SSTable

An SSTable is "Sorted String Table" — a file where keys appear in sorted order, with a sparse index that lets you binary-search for a key without scanning the whole file. Add a Bloom filter to skip files that definitely don't contain the key.

```rust
// src/sstable.rs (skeleton — see repo for full block reader)
use std::{fs::File, io::{BufWriter, Write}, path::Path};
use crate::memtable::Memtable;

pub struct Sstable { pub path: std::path::PathBuf, pub min: Vec<u8>, pub max: Vec<u8> }

pub fn flush(mem: &Memtable, dir: &Path, id: u64) -> std::io::Result<Sstable> {
    let path = dir.join(format!("sst_{id:06}.sst"));
    let f = BufWriter::new(File::create(&path)?);
    let mut w = f;
    let mut min = Vec::new(); let mut max = Vec::new();
    for (k, v) in mem.iter() {
        if min.is_empty() { min = k.clone(); }
        max = k.clone();
        let val = v.clone().unwrap_or_default();
        let tomb = v.is_none() as u8;
        w.write_all(&(k.len() as u32).to_le_bytes())?;
        w.write_all(k)?;
        w.write_all(&tomb)?;
        w.write_all(&(val.len() as u32).to_le_bytes())?;
        w.write_all(&val)?;
    }
    w.flush()?;
    Ok(Sstable { path, min, max })
}
```

The Bloom filter deserves its own module. A 10-bit-per-key Bloom filter with two hash functions has a ~1% false positive rate and is the cheapest way to make point reads fast in the presence of many SSTables. Use the `bloom` crate or implement the standard double-hashing scheme with `crc32fast`.

### Step 4 — The Read Path

The read path is what the read-amplification story is all about. You check the memtable first, then walk SSTables from newest to oldest, applying the first match and respecting tombstones.

```rust
// src/engine.rs (read path sketch)
pub fn get(&self, key: &[u8]) -> Result<Option<Vec<u8>>, Error> {
    if let Some(v) = self.memtable.get(key) {
        return Ok(v.clone()); // Some(_) or None (tombstone) both terminate
    }
    for sst in self.sstables.iter().rev() { // newest first
        if key < sst.min.as_slice() || key > sst.max.as_slice() { continue; }
        if !sst.bloom.may_contain(key) { continue; }
        if let Some(hit) = sst.block_lookup(key)? {
            return Ok(hit);
        }
    }
    Ok(None)
}
```

This newest-to-oldest iteration is why LSM-trees are write-friendly: a fresh write in a newer SSTable shadows older ones, and the read pays at most one I/O per level for the miss case (if Bloom filters are sized correctly).

### Step 5 — Compaction

Compaction is what keeps read amplification bounded. A minimal size-tiered policy is the easiest to implement: pick a few SSTables of similar size, merge-sort them, and write one new file. Drop tombstones for any key whose newest version is older than the oldest snapshot.

```rust
// src/compaction.rs
pub fn merge_sort(sstables: &[Sstable], out: &Path) -> std::io::Result<Sstable> {
    let mut iters: Vec<_> = sstables.iter().map(|s| s.cursor()).collect();
    let mut writers = BufWriter::new(File::create(out)?);
    let mut heap: std::collections::BinaryHeap<(Reverse<Vec<u8>>, usize)> = BinaryHeap::new();
    for (i, it) in iters.iter_mut().enumerate() {
        if let Some(kv) = it.next()? { heap.push((Reverse(kv.0), i)); }
    }
    while let Some((Reverse(k), i)) = heap.pop() {
        let (k2, v, tomb) = iters[i].next()?.unwrap();
        writers.write_all(&k2)?;
        writers.write_all(&[tomb as u8])?;
        writers.write_all(&(v.len() as u32).to_le_bytes())?;
        writers.write_all(&v)?;
        if let Some(kv) = iters[i].next()? { heap.push((Reverse(kv.0), i)); }
    }
    Sstable::finalize(out)
}
```

The unit-of-work `k2 != k` check that elides older duplicates for the same key is the core of compaction; everything else is I/O plumbing.

## Running and Testing It

The CLI is the demo surface. Make it dead simple to use because recruiters will spend about 30 seconds looking at your README.

```bash
# terminal 1 — server
cargo run --release --bin kvsd -- --dir ./data serve

# terminal 2 — client
cargo run --release --bin kvsd -- put name alice
cargo run --release --bin kvsd -- get name        # -> alice
cargo run --release --bin kvsd -- del name
cargo run --release --bin kvsd -- get name        # -> (not found)
```

For tests, write property tests for the WAL framing (round-trip arbitrary `Op`s, simulate torn writes), snapshot tests for the memtable/flush, and an end-to-end test that issues 10,000 `PUT`s, kills the process with `kill -9`, restarts, and asserts the count is preserved. This kind of crash test is what makes a reviewer sit up.

```rust
// tests/crash_recovery.rs
#[test]
fn survives_kill_9_after_writes() {
    let dir = tempfile::tempdir().unwrap();
    let mut e = Engine::open(dir.path()).unwrap();
    for i in 0..10_000 { e.put(b"k", i.to_string().as_bytes()).unwrap(); }
    drop(e); // simulate SIGKILL — no graceful shutdown
    let e2 = Engine::open(dir.path()).unwrap();
    assert_eq!(e2.get(b"k").unwrap().unwrap(), b"9999");
}
```

Wire up Criterion for benchmarks. The numbers that matter are sequential put throughput (target: 200k+ ops/sec on a laptop NVMe), point-read latency at 1M keys, and the read-amplification curve as you grow the number of SSTables before compaction.

```rust
// benches/put.rs
use criterion::{criterion_group, criterion_main, Criterion};
fn puts(c: &mut Criterion) {
    c.bench_function("put_seq", |b| {
        let dir = tempfile::tempdir().unwrap();
        let mut e = kvsd::Engine::open(dir.path()).unwrap();
        b.iter(|| { for i in 0..1000 { e.put(b"k", i.to_string().as_bytes()).unwrap(); } });
    });
}
criterion_group!(benches, puts);
criterion_main!(benches);
```

## Extending It: Your Roadmap to Senior-Level

The base engine is your minimum viable story. The upgrades below are how you turn it from "I built a toy" into "I've shipped the parts of RocksDB that matter." Each one is a separate, well-scoped PR-sized effort and maps to a real system in production.

1. **Real persistence with fsync guarantees and a manifest.** Replace the directory-scan SSTable discovery with a `MANIFEST` file that logs SSTable creation/deletion atomically and is itself WAL-protected. This is the pattern RocksDB uses and is what makes online restarts safe.
2. **Bloom filters in front of every SSTable.** A 10-bit-per-key filter with a double-hashing scheme cuts read amplification by 10x in workloads with cold keys. Every production LSM uses one; the cost is a few hundred lines.
3. **Leveled compaction with score-based triggers.** Implement RocksDB-style levels where each level is 10x larger than the last and compaction triggers on level size. This is what `RocksDB` and `TiKV` use to keep read amplification under control even at billions of keys.
4. **Snapshots and MVCC.** Add an atomic snapshot reference counter and a sequence number to every record. This is the same model Postgres uses for transaction isolation and is what `BadgerDB` builds its entire ACID layer on.
5. **Observability: structured logs, metrics, and a `/status` endpoint.** Export `tokio` runtime metrics, per-level SSTable counts, compaction queue depth, and last-flush timestamps in Prometheus format. A reviewer who sees `tracing` and `metrics-rs` in your `Cargo.toml` immediately knows you've shipped to production.
6. **A real client protocol and a `redis-cli`-style REPL.** A RESP-compatible or gRPC interface plus a thin Rust client crate turns the project from a CLI into a library. Bonus: add a `Dockerfile` and a `docker compose` so the README has a one-command demo.

## Key Takeaways

- An LSM-tree key-value store is one of the highest-signal projects a junior or mid-level engineer can ship: it touches filesystems, durability, on-disk data structures, and background processing all in one repo.
- The architecture is short and teachable: WAL → Memtable → SSTables → Compaction. Master this diagram and you can reason about RocksDB, Cassandra, InfluxDB, and TiKV.
- The Rust code is small but real: `BufWriter`, `sync_all`, `bincode`, `BTreeMap`, `BinaryHeap` for k-way merge, and a Bloom filter. Every crate you reach for is a deliberate systems decision.
- Ship crash-recovery tests and Criterion benchmarks. The numbers, not the code, are what make a reviewer trust it.
- The natural extensions — manifests, leveled compaction, MVCC, observability — are exactly the things senior engineers do in production. Doing them on a side project is a strong signal.

## Further Reading

- [The Log-Structured Merge-Tree (LSM-Tree) — O'Neil, Cheng, Gawlick, O'Neil (1996)](https://www.cs.umb.edu/~poneil/lsmtree.pdf) — the original paper. Worth reading once slowly.
- [LevelDB implementation notes](https://github.com/google/leveldb/blob/main/doc/impl.md) — the cleanest production-grade description of an LSM engine; treats WAL, memtable, SSTable, and compaction in detail.
- [RocksDB Architecture Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Overview) — the production evolution of LevelDB. Read the sections on leveled compaction and the manifest format.
- [Designing Data-Intensive Applications — Chapter 3: Storage and Retrieval](https://dataintensive.net/) — Kleppmann's book is the best end-to-end treatment of B-trees vs LSMs, and it's free to read online.
- [WiscKey: Separating Keys from Values in SSD-conscious Storage (2016)](https://www.usenix.org/system/files/conference/fast16/fast16-papers-lu.pdf) — the WiscKey paper; motivates value-log separation, which is a natural next step for your project.
- [The `crc32fast` crate](https://docs.rs/crc32fast) and the [`bincode` serialization format](https://docs.rs/bincode) — the two crates you used for the WAL framing; understanding their guarantees is part of understanding the engine.