---
title: "Why Write-Ahead Logging Prevents Database Corruption During Crashes"
date: "2026-05-13T20:00:51.529"
draft: false
tags: ["databases", "write-ahead logging", "crash recovery", "data integrity", "SQL"]
description: "Explore how write-ahead logging safeguards data by ensuring atomicity and durability, preventing corruption when power or system crashes occur."
summary: "Write-ahead logging (WAL) writes changes to a durable log before modifying the database, allowing recovery after crashes and eliminating corruption."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-13-why-write-ahead-logging-prevents-database-corruption-during-crashes.svg"
  alt: "Diagram of a database log file with arrows showing write-ahead logging flow."
  caption: ""
  relative: false
---

> **TL;DR** — Write-ahead logging (WAL) records every change to a durable log before touching the main database files. If a crash occurs, the log can be replayed to restore a consistent state, eliminating the risk of partially written pages and corruption.

Databases must survive power failures, kernel panics, and unexpected process termination. The most reliable way to guarantee that no transaction leaves the storage engine in an inconsistent half‑written state is to enforce a strict order: *log first, data later*. This principle is the heart of write-ahead logging, and it underpins the crash‑recovery mechanisms of PostgreSQL, SQLite, MySQL InnoDB, and many NoSQL stores. In this article we unpack the mechanics of WAL, examine how it prevents corruption, and discuss the trade‑offs you should weigh when configuring it for production workloads.

## How Write-Ahead Logging Works

At a high level, WAL transforms every logical modification (INSERT, UPDATE, DELETE) into a sequential series of **log records**. Each record contains enough information to redo the change (the *redo* part) and, in some implementations, to undo it (the *undo* part). The workflow can be broken into three distinct phases:

1. **Log Append** – The transaction manager writes a log record to a *write‑ahead log* file that resides on durable storage (usually an SSD or spinning disk). The write is flushed to the OS buffer cache and then to the physical media using an `fsync` or equivalent system call.
2. **Lock & Apply** – After the log record is safely persisted, the engine acquires the necessary page locks and applies the change to the in‑memory buffer pool (the *dirty page*).
3. **Checkpoint** – Periodically, the system writes all dirty pages to the main data files and records a *checkpoint* entry in the log, indicating that everything before that point is safely reflected on disk.

The critical invariant is **WAL‑First**: no data page is ever written to the database file until its corresponding log record is durably stored. This invariant eliminates the classic “write‑behind” race condition where a crash can leave a data page on disk that references a log entry that never made it to the log.

### Log Record Structure

A typical WAL record contains:

- **LSN (Log Sequence Number)** – A monotonically increasing identifier that orders records.
- **Transaction ID** – The transaction that generated the change.
- **Operation Type** – INSERT, UPDATE, DELETE, etc.
- **Payload** – Either the full row image (for redo) or the before‑image (for undo), plus any auxiliary data (e.g., page number, tuple offset).

Below is a minimal example in Python that illustrates how a simple key‑value store could generate a WAL entry before mutating its in‑memory dictionary:

```python
import os
import struct
import json
import time

WAL_PATH = "wal.log"

def append_wal(txn_id, op, key, value=None):
    """Append a JSON‑encoded WAL record and force it to disk."""
    record = {
        "lsn": int(time.time() * 1e6),   # microsecond‑resolution LSN
        "txn": txn_id,
        "op": op,
        "key": key,
        "value": value
    }
    line = json.dumps(record) + "\n"
    with open(WAL_PATH, "ab") as f:
        f.write(line.encode("utf-8"))
        f.flush()
        os.fsync(f.fileno())

def apply_operation(store, record):
    """Apply a WAL record to the in‑memory store."""
    op = record["op"]
    key = record["key"]
    if op == "SET":
        store[key] = record["value"]
    elif op == "DEL" and key in store:
        del store[key]

# Example usage
store = {}
txn_id = 1
append_wal(txn_id, "SET", "user:42", {"name": "Alice", "balance": 100})
apply_operation(store, {"op": "SET", "key": "user:42", "value": {"name": "Alice", "balance": 100}})
print(store)
```

The `append_wal` function writes the record to `wal.log` and immediately forces the write to stable storage with `os.fsync`. Only after that does the caller invoke `apply_operation` to mutate the in‑memory state. If the process crashes between the two calls, the log entry remains, and the recovery routine can replay it later.

## Crash Scenarios and Data Loss

To understand why WAL prevents corruption, consider three common crash scenarios:

### 1. Power Failure During Page Flush

Without WAL, a database might write a dirty page directly to the data file, then crash before the write completes. The resulting page could be partially overwritten, leaving a mixture of old and new bytes—a classic *torn write* that makes the file unreadable. With WAL, the engine first logs the change; if the power goes out, the partially written data page is irrelevant because the log guarantees that the change can be reapplied once the system restarts.

### 2. Transaction Commit Lost Mid‑Way

A transaction typically follows a *prepare* → *commit* protocol. If the commit flag is written to the data file but the log entry for the transaction’s modifications never reaches disk, recovery would see a half‑committed transaction and might have to roll it back, risking inconsistency. WAL forces the commit record itself to be logged and flushed before marking the transaction as committed, ensuring that *either* all of its changes are recoverable *or* none are.

### 3. Buffer Pool Eviction During Crash

Modern engines keep pages in a memory buffer pool for performance. If the process crashes while a dirty page is still only in memory, that page would be lost forever without WAL. The write‑ahead log acts as a safety net: every modification that touched the buffer pool already has a durable counterpart in the log, so the page can be reconstructed during recovery.

In all three cases, the common thread is that **the log survives the crash**, while the volatile in‑memory structures do not. By replaying the log, the engine can bring the database back to a *consistent* state that reflects all committed transactions and none of the uncommitted ones.

## Recovery Process Using WAL

When a database restarts after an abnormal termination, it follows a deterministic recovery algorithm:

1. **Identify the Last Checkpoint** – The engine reads the most recent checkpoint LSN from the control file. All pages flushed before this LSN are guaranteed to be on disk.
2. **Redo Phase** – Starting from the checkpoint LSN, the engine scans forward through the WAL, reapplying every *redo* record to the corresponding pages in memory. This phase ensures that any changes that were logged but not yet reflected on disk become visible.
3. **Undo Phase (Optional)** – If the engine supports *undo* logs, it rolls back any transactions that were in progress at the time of the crash (i.e., those without a commit record). This restores atomicity.
4. **Write a New Checkpoint** – After the redo/undo phases, the engine writes a fresh checkpoint, marking the point up to which the database is now consistent.

The redo phase is *idempotent*: applying the same log record multiple times yields the same result, which simplifies recovery logic. PostgreSQL’s documentation provides a clear illustration of this process in the context of its WAL subsystem [as described here](https://www.postgresql.org/docs/current/wal-intro.html).

### Example: Recovering a Tiny Key‑Value Store

Continuing the Python example above, a simple recovery routine could look like this:

```python
def recover(store):
    """Replay the WAL file to rebuild the in‑memory store."""
    if not os.path.exists(WAL_PATH):
        return
    with open(WAL_PATH, "rb") as f:
        for line in f:
            record = json.loads(line.decode("utf-8"))
            apply_operation(store, record)

# Simulate a crash and recovery
store = {}
recover(store)          # Rebuild from WAL
print("Recovered store:", store)
```

Because each `SET` or `DEL` operation was logged before being applied, the store can be reconstructed exactly as it was before the crash, even though the original in‑memory dictionary vanished.

## Performance Considerations

WAL introduces extra I/O, but the impact can be mitigated with careful tuning:

| Aspect                | Impact & Mitigation |
|-----------------------|---------------------|
| **Write Amplification** | Every logical change results in at least two writes (log + data). Use batch commits and larger log segments to amortize the cost. |
| **fsync Overhead**    | Frequent `fsync` calls can dominate latency. Group multiple log records into a single `fsync` (e.g., commit every N records or every T milliseconds). |
| **Log Size Management** | Unbounded log growth leads to storage pressure. Implement automatic log truncation after successful checkpoints, as PostgreSQL does with its `pg_recycle` mechanism. |
| **Checkpoint Frequency** | More frequent checkpoints reduce recovery time but increase write load. Choose a checkpoint interval that balances acceptable recovery windows with normal throughput. |
| **Parallelism**       | Modern engines parallelize log writes across multiple log buffers (e.g., MySQL InnoDB’s multiple log files). This spreads I/O across disks and improves scalability. |

A practical rule of thumb: aim for **sub‑millisecond commit latency** on SSDs by batching log writes, and schedule **checkpoints every 5–15 minutes** for workloads where a few seconds of recovery time is acceptable.

## Common Misconceptions

1. **“WAL eliminates all data loss.”**  
   WAL guarantees *no corruption* and *atomicity*, but it does not protect against *logical* data loss (e.g., a user accidentally deletes rows). Backups remain essential.

2. **“If I have a RAID array, I don’t need WAL.”**  
   RAID protects against hardware failures, not against software crashes that leave the database in an inconsistent state. WAL works at the logical level, independent of underlying storage redundancy.

3. **“Turning off WAL speeds up bulk loads.”**  
   Some systems allow *WAL bypass* for bulk operations (e.g., `COPY` in PostgreSQL with `UNLOGGED` tables). This trades durability for speed and must be used with an understanding that a crash during the load could corrupt the table.

4. **“WAL is only for relational databases.”**  
   NoSQL stores like MongoDB’s *oplog* and Apache Kafka’s *commit log* adopt the same principle: write-ahead logs enable replay and fault tolerance across diverse data models.

## Key Takeaways

- Write-ahead logging enforces a strict *log‑first* ordering, ensuring that every change is durably recorded before any on‑disk data page is altered.
- In the event of a crash, the WAL provides a reliable source for *redo* (and optionally *undo*) operations, allowing the database to recover to a consistent state without corruption.
- Checkpointing, log truncation, and careful `fsync` batching are essential to keep WAL’s performance impact manageable.
- WAL is a universal technique, not limited to relational databases; any system that requires atomic, durable state transitions can benefit.
- Proper configuration—balancing commit latency, checkpoint frequency, and log size—maximizes both safety and throughput.

## Further Reading

- [PostgreSQL Write-Ahead Logging (WAL) Overview](https://www.postgresql.org/docs/current/wal-intro.html) – Detailed explanation of PostgreSQL’s WAL architecture and recovery process.  
- [SQLite Write-Ahead Logging Mode](https://www.sqlite.org/wal.html) – How SQLite implements WAL for embedded applications.  
- [MySQL InnoDB Crash Recovery](https://dev.mysql.com/doc/refman/8.0/en/innodb-crash-recovery.html) – InnoDB’s approach to redo logs and checkpointing.  
- [The Architecture of the Apache Kafka Distributed Log](https://kafka.apache.org/documentation/#design) – A non‑SQL example of write-ahead logging for streaming data.  
- [Microsoft SQL Server Transaction Log Architecture](https://learn.microsoft.com/en-us/sql/relational-databases/sql-server-transaction-log-architecture) – Insight into how a commercial RDBMS uses WAL for ACID compliance.