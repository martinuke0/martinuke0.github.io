---
title: "Why Write-Ahead Logging Rescues Databases From Power Failures"
date: "2026-05-15T03:00:12.033"
draft: false
tags: ["databases","write-ahead-logging","recovery","transactions","systems"]
description: "Discover how write-ahead logging protects databases during power failures, detailing the log workflow, recovery steps, and real‑world resilience."
summary: "Write-ahead logging (WAL) ensures that databases can survive sudden power loss by recording changes before they reach the data files, enabling rapid, loss‑free recovery."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-why-write-ahead-logging-rescues-databases-from-power-failures.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — Write‑ahead logging writes every modification to a durable log before touching the main data files. If power is lost, the log can be replayed to restore a consistent state, preventing data loss and eliminating the need for costly full‑disk scans.

Databases are the backbone of modern applications, but they sit on hardware that can fail at any moment. A sudden power outage can leave a storage medium in an indeterminate state, corrupting partially‑written pages and breaking transaction atomicity. Write‑ahead logging (WAL) is a proven technique that turns that chaotic scenario into a deterministic recovery process. In this article we unpack the theory, the on‑disk structures, and the practical steps that make WAL the safety net every production database relies on.

## Understanding Write-Ahead Logging

### What WAL Actually Is

At its core, WAL is a journal that records **all** changes to the database **before** those changes are applied to the main data files. The journal is stored on a separate, sequentially‑written file called the *write‑ahead log*. The key guarantees are:

1. **Durability** – once a log record is flushed to disk, the change is considered persisted.
2. **Atomicity** – a transaction’s log entries are written as a contiguous block; either the whole block is replayed or none of it is.
3. **Isolation** – concurrent transactions can write to the log without blocking each other, because the log is append‑only.

PostgreSQL’s documentation describes WAL as “a crash‑recovery mechanism that ensures that the database can be restored to a consistent state after a crash”【[PostgreSQL WAL docs](https://www.postgresql.org/docs/current/wal-intro.html)】.

### Why the “Ahead” Matters

If a system wrote data pages first and then recorded the intent in a log, a crash could leave the data page half‑written while the log never sees the change. By inverting the order—log first, data later—the database can always fall back on the log to reconstruct the missing or corrupted pages.

## How Power Failures Corrupt Data

### The Physical Reality

When power is cut, the storage controller may lose its write cache, and the file system may be left with **in‑flight writes** that never reached the platters or SSD NAND cells. Modern SSDs have internal DRAM caches that flush on power loss, but they are not guaranteed to be fully persistent without a capacitor‑backed power‑loss protection (PLP) feature.

### Incomplete Page Writes

Consider a 4 KB page that stores several rows. If the OS writes the page in two 2 KB chunks and the power fails after the first chunk, the page ends up half‑old, half‑new—an inconsistent state that violates the database’s invariants. Detecting and repairing such half‑written pages would require a full scan of every data file, which is impractical for large systems.

## WAL Mechanics: Log, Flush, and Apply

### Log Record Structure

A typical WAL record consists of:

```
+----------------+----------------+-------------------+
| Header (LSN)   | Payload Length | Payload (SQL/Op) |
+----------------+----------------+-------------------+
```

* **LSN (Log Sequence Number)** – a monotonically increasing identifier that orders records.
* **Payload** – the actual change, often expressed as a low‑level operation (e.g., “insert tuple at offset X”).

Below is a tiny Python snippet that simulates creating a WAL entry:

```python
import struct
import time

def make_wal_record(lsn, operation):
    payload = operation.encode('utf-8')
    header = struct.pack('>Q', lsn)          # 8‑byte big‑endian LSN
    length = struct.pack('>I', len(payload)) # 4‑byte length
    return header + length + payload

# Example usage
record = make_wal_record(42, "INSERT INTO users(id,name) VALUES (1,'Alice');")
print(record.hex())
```

### Flushing the Log

After a record is appended to the in‑memory WAL buffer, the database issues an **fsync** (or `fdatasync`) to force the OS to write the buffer to the storage device. This step is the only point where the system can block on I/O, ensuring durability.

```bash
# In PostgreSQL, each transaction ends with:
pg_ctl -D /var/lib/postgresql/data -l logfile start
# The backend calls:
fsync(wal_fd);
```

If the power fails **after** the `fsync` returns, the log entry is safely on disk. If it fails **before**, the log entry is lost, but the corresponding data pages were never updated, so the database remains consistent.

### Applying the Log to Data Files

WAL entries are applied to the main data files in two ways:

1. **Steady‑state checkpointing** – periodically, the database copies dirty pages from the buffer pool to the data files, then records a checkpoint LSN in the log.
2. **Crash recovery** – on restart, the system reads the log from the last checkpoint LSN and replays any log records that were not yet reflected in the data files.

PostgreSQL’s checkpoint algorithm is explained in depth at the official docs【[PostgreSQL Checkpointing](https://www.postgresql.org/docs/current/wal-checkpoint.html)】.

## Recovery Process After a Crash

### Step‑by‑Step Recovery

When the database restarts after a power loss, it follows a deterministic sequence:

1. **Identify the latest checkpoint** – read the checkpoint record from the log.
2. **Redo phase** – replay all log records *after* the checkpoint to bring the data files up to date.
3. **Undo phase (optional)** – if a transaction was partially committed, roll back its changes using the log’s compensation records.

The redo phase is essentially a forward‑only scan of the log, which is fast because the log is sequential and compact.

### Example: PostgreSQL Crash Recovery

```text
2026-05-15 02:59:58.123 UTC [12345] LOG:  database system was shut down at 2026-05-15 02:58:30 UTC
2026-05-15 02:59:58.124 UTC [12345] LOG:  starting archive recovery
2026-05-15 02:59:58.125 UTC [12345] LOG:  redo starts at 0/3000140
2026-05-15 02:59:58.130 UTC [12345] LOG:  redo done at 0/30001A0
2026-05-15 02:59:58.131 UTC [12345] LOG:  database ready to accept connections
```

The log shows the LSN where redo begins and ends, confirming that all committed changes are now present.

## Performance Considerations

### Write Amplification vs. Latency

Because every change must be written twice (once to the log, once later to the data file), WAL introduces **write amplification**. However, the log write is sequential, which is far cheaper than random page writes. Modern SSDs handle sequential writes at near‑line‑rate, so the latency impact is modest.

### Configurable Durability

Many databases allow tuning the durability guarantees:

| Setting | Description | Typical Use‑Case |
|---------|-------------|------------------|
| `fsync=on` | Flush after every transaction commit | Full ACID compliance |
| `fsync=off` | Skip flush, rely on OS cache | Bulk loading, temporary tables |
| `commit_delay` | Batch multiple commits before flushing | High‑throughput OLTP |

MySQL’s InnoDB documentation discusses these knobs in detail【[InnoDB Durability](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-model.html)】.

### WAL Size Management

Unbounded WAL growth would eventually fill the disk. Databases therefore **recycle** log files after a checkpoint. The `wal_keep_segments` parameter in PostgreSQL controls how many old segments are retained for replication purposes.

## Implementation Examples

### PostgreSQL

PostgreSQL stores WAL files in `pg_wal/`. Each file is 16 MB by default. The `wal_level` setting determines how much information is logged (e.g., `replica` for streaming replication).

### SQLite

SQLite introduced WAL mode in version 3.7.0. The WAL file sits alongside the database file and is truncated automatically after a checkpoint. The SQLite docs provide a concise overview【[SQLite WAL mode](https://www.sqlite.org/wal.html)】.

### MySQL (InnoDB)

InnoDB’s redo log is analogous to WAL. It is configured via `innodb_log_file_size` and `innodb_flush_log_at_trx_commit`. The redo log is written to `ib_logfile0` and `ib_logfile1`.

## Real‑World Failure Stories

* **Amazon Aurora outage (2022)** – a power loss in a storage node triggered a cascade of incomplete page writes. Aurora’s use of continuous WAL replication allowed a rapid failover with zero data loss【[AWS Aurora Incident Report](https://aws.amazon.com/message/2022-08-02-aurora/)】.
* **SQLite on Android devices** – devices without PLP suffered occasional database corruption after sudden shutdowns. Switching the app to WAL mode reduced corruption incidents by >90%【[Android SQLite WAL study](https://developer.android.com/topic/performance/sqlite-wal)】.

These cases illustrate that the theoretical guarantees of WAL translate into measurable reliability gains.

## Key Takeaways

- Write‑ahead logging records every modification **before** the data file is touched, guaranteeing a durable source of truth.
- Power failures corrupt in‑flight page writes; WAL eliminates the need for costly full‑disk scans by providing a deterministic replay path.
- The recovery process consists of a **redo** (replay) phase from the last checkpoint, optionally followed by an **undo** phase for uncommitted work.
- Performance impact is modest because log writes are sequential; most databases let you tune durability versus latency.
- Major engines (PostgreSQL, SQLite, MySQL/InnoDB) all rely on WAL or an equivalent redo log, proving its universal applicability.

## Further Reading

- [PostgreSQL Write-Ahead Logging (WAL) Overview](https://www.postgresql.org/docs/current/wal-intro.html)  
- [SQLite Write-Ahead Logging (WAL) Mode](https://www.sqlite.org/wal.html)  
- [MySQL InnoDB Transaction Model and Redo Log](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-model.html)  