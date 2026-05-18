---
title: "When Snapshot Isolation Fails to Prevent Write Skew"
date: "2026-05-18T10:01:01.368"
draft: false
tags: ["databases", "transaction-isolation", "write-skew", "snapshot-isolation", "consistency"]
description: "Learn why snapshot isolation can still suffer write‑skew anomalies, with banking and scheduling examples, and discover detection tools and fixes for integrity."
summary: "Snapshot isolation prevents many concurrency bugs but still allows the subtle write‑skew anomaly. This article explains why, shows real‑world examples, and offers concrete mitigation techniques."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-when-snapshot-isolation-fails-to-prevent-write-skew.svg"
  alt: "Illustration of two database rows diverging under snapshot isolation."
  caption: ""
  relative: false
---

> **TL;DR** — Snapshot isolation protects against lost updates and dirty reads, yet it cannot stop write‑skew anomalies where concurrent transactions read overlapping data and write disjoint rows. Understanding the root cause, spotting the pattern, and employing serializable isolation or explicit row locks are essential for safe, high‑integrity applications.

Snapshot isolation (SI) is a popular concurrency control level in modern relational databases such as PostgreSQL and MySQL. It offers a compelling blend of performance and safety: each transaction sees a consistent snapshot of the database, and write‑write conflicts are automatically aborted. However, SI is not a panacea. A classic, yet often misunderstood, failure mode is **write skew**—a logical inconsistency that can arise even when no two transactions update the same row. This post dives deep into the mechanics of SI, demonstrates why write skew slips through, and equips you with practical tools to detect and prevent it.

## What Snapshot Isolation Guarantees

### Consistent Snapshot Reads
When a transaction starts under SI, the database records the current **transaction ID** (or a similar logical timestamp). All subsequent reads are served from the version of each row that was committed *before* that ID. This guarantees that the transaction works with a **stable view** of the data, regardless of concurrent modifications.

> “A transaction under SI sees a snapshot of the database as of the start time of the transaction.” – [PostgreSQL docs](https://www.postgresql.org/docs/current/transaction-iso.html)

### Write‑Write Conflict Detection
If two concurrent transactions attempt to modify the same row, the database detects the conflict at commit time. The later‑committing transaction receives a serialization error (e.g., `ERROR: could not serialize access due to concurrent update`). This protects against lost updates and dirty reads.

## The Write Skew Anomaly

Write skew occurs when two transactions **read** overlapping rows, make decisions based on those reads, and then **write** to *different* rows. Because SI only checks for direct write‑write conflicts, each transaction can commit successfully, leaving the database in an invalid state.

### Classic Banking Example
Consider a simple banking schema:

```sql
CREATE TABLE accounts (
    id      SERIAL PRIMARY KEY,
    balance NUMERIC NOT NULL CHECK (balance >= 0)
);
```

Two accounts, `A` and `B`, each have a balance of 100. The business rule is *“the total balance of both accounts must never drop below 150.”* Two concurrent withdrawals of 80 each can violate this rule under SI.

Transaction **T1** (withdraw from `A`):

```sql
-- T1 starts
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;  -- PostgreSQL's SI
SELECT balance FROM accounts WHERE id = 1;  -- reads 100
UPDATE accounts SET balance = balance - 80 WHERE id = 1;  -- writes row 1
COMMIT;
```

Transaction **T2** (withdraw from `B`) runs at the same time:

```sql
-- T2 starts shortly after T1
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
SELECT balance FROM accounts WHERE id = 2;  -- also reads 100 (snapshot sees original state)
UPDATE accounts SET balance = balance - 80 WHERE id = 2;  -- writes row 2
COMMIT;
```

Both transactions see a snapshot where each account holds 100, decide that the withdrawal is safe, and commit. After both commits the balances are 20 and 20, totalling 40—well below the required 150. No write‑write conflict was detected because each transaction updated a different row.

### Hospital Scheduling Example
A more subtle real‑world case appears in **on‑call scheduling**. Suppose a hospital enforces a rule: *“At least one doctor must be on call at any given time.”* The schedule is stored as rows with a `doctor_id` and a `shift` flag.

```sql
CREATE TABLE oncall (
    doctor_id INT PRIMARY KEY,
    on_call   BOOLEAN NOT NULL
);
```

Two doctors, Alice (id 1) and Bob (id 2), are both marked `TRUE`. Alice decides to take a vacation and clears her flag; Bob does the same concurrently. Both transactions read the table, see that the other doctor is still on call, and each writes `FALSE` for themselves. The resulting schedule has **no** doctor on call, violating the safety rule.

## Why Snapshot Isolation Misses Write Skew

### No Read‑Write Conflict Detection
SI only aborts when two transactions **write the same row**. It does **not** track whether a transaction’s *reads* become stale because another transaction wrote a *different* row. In the examples above, each transaction’s decision is based on a snapshot that becomes invalid only after the other transaction commits.

### Overlapping Transactions Reading the Same Rows
Write skew typically follows this pattern:

1. **T1** reads rows R1, R2 (both satisfy a condition).
2. **T2** reads the same rows R1, R2 (same snapshot).
3. **T1** updates R1 (no conflict with T2).
4. **T2** updates R2 (no conflict with T1).
5. Both commit → the invariant that depended on the joint state of R1 and R2 is broken.

Because the invariant is *global* (involving multiple rows), SI’s row‑level conflict detection is insufficient.

## Detecting Write Skew in Practice

### Logging and Auditing
Most production databases can be configured to log transaction start/commit times, along with the rows each transaction reads (via `pg_stat_activity` in PostgreSQL or the Performance Schema in MySQL). Correlating these logs can surface patterns where two transactions read the same set of rows and then write disjoint rows.

### Using Database Features

#### PostgreSQL’s Serializable Snapshot Isolation (SSI)
PostgreSQL offers a **serializable** isolation level that builds on SI but adds a **dangerous‑structure detection** algorithm. It aborts transactions that could lead to anomalies like write skew.

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- same logic as before
COMMIT;
```

If the two banking withdrawals run under `SERIALIZABLE`, one will receive:

```
ERROR: could not serialize access due to concurrent update
```

#### MySQL’s `READ COMMITTED` + `SELECT ... FOR UPDATE`
InnoDB does not provide true SSI, but you can lock rows you read with `SELECT ... FOR UPDATE`. This converts the read into a write‑lock, forcing the second transaction to wait.

```sql
BEGIN;
SELECT balance FROM accounts WHERE id = 1 FOR UPDATE;
-- perform logic, then UPDATE ...
COMMIT;
```

The lock ensures that only one transaction can make a decision based on the shared data at a time, effectively preventing write skew.

## Mitigation Strategies

### Upgrade to Serializable Isolation
When the underlying DB supports true serializable isolation (PostgreSQL, Oracle, SQL Server), simply set `ISOLATION LEVEL SERIALIZABLE`. The trade‑off is higher abort rates under contention, but correctness is guaranteed.

### Explicit Row Locks (SELECT … FOR UPDATE / LOCK IN SHARE MODE)
If you cannot afford full serializability, lock the rows that participate in the invariant.

```sql
BEGIN;
SELECT on_call FROM oncall WHERE doctor_id = 1 FOR SHARE;
SELECT on_call FROM oncall WHERE doctor_id = 2 FOR SHARE;
-- evaluate invariant
UPDATE oncall SET on_call = FALSE WHERE doctor_id = 1;
COMMIT;
```

`FOR SHARE` (PostgreSQL) or `LOCK IN SHARE MODE` (MySQL) prevents other transactions from acquiring exclusive locks on the same rows, reducing the window for write skew.

### Application‑Level Checks with Retry Logic
Wrap critical sections in a retry loop that catches serialization errors and re‑executes the transaction.

```python
import psycopg2
MAX_RETRIES = 5

for attempt in range(MAX_RETRIES):
    try:
        cur.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;")
        # ... business logic ...
        cur.execute("COMMIT;")
        break
    except psycopg2.errors.SerializationFailure:
        cur.execute("ROLLBACK;")
        if attempt == MAX_RETRIES - 1:
            raise
        # optional backoff before retry
```

Retry logic works with both SI and serializable levels, but it is only effective when the database actually aborts the conflicting transaction.

### Adding Check Constraints
Some invariants can be enforced directly by the DB engine. For the banking example, a **partial index** or a **trigger** that enforces a minimum total balance can catch violations at commit time.

```sql
CREATE OR REPLACE FUNCTION enforce_total_balance()
RETURNS trigger AS $$
BEGIN
    IF (SELECT SUM(balance) FROM accounts) < 150 THEN
        RAISE EXCEPTION 'Total balance below minimum';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER total_balance_chk
AFTER INSERT OR UPDATE ON accounts
DEFERRABLE INITIALLY DEFERRED
FOR EACH STATEMENT EXECUTE FUNCTION enforce_total_balance();
```

Because the trigger runs **after** all row updates in the transaction, it sees the combined effect and can abort the transaction if the invariant is broken.

## Performance Considerations

| Technique                              | Concurrency Impact | Typical Overhead | When to Use |
|----------------------------------------|---------------------|------------------|-------------|
| Serializable Isolation (SSI)           | Low to moderate (more aborts) | Small CPU cost for conflict detection | High‑integrity systems where anomalies are unacceptable |
| `SELECT … FOR UPDATE` (row locks)     | High (locks serialize access) | Minimal CPU, but possible lock contention | Small sets of rows, low contention workloads |
| Application retry loop                 | Variable (depends on abort rate) | Extra round‑trip per retry | Systems that already use SI and can tolerate occasional retries |
| Check constraints / triggers            | Negligible (run once per commit) | Slight CPU for constraint evaluation | Simple invariants that can be expressed in SQL |

Choosing the right mitigation depends on your workload’s contention profile, latency requirements, and the criticality of the invariant. In many OLTP systems, a hybrid approach works well: **use serializable isolation for the few transactions that enforce cross‑row invariants**, while keeping the majority of operations at snapshot isolation for maximum throughput.

## Key Takeaways
- Snapshot isolation guarantees a consistent read snapshot and aborts only on direct write‑write conflicts.
- Write skew arises when concurrent transactions read overlapping rows and write disjoint rows, bypassing SI’s conflict detection.
- Real‑world examples include banking withdrawals and on‑call scheduling, where a global invariant is silently broken.
- Detect write skew by logging read/write patterns or by enabling the database’s serializable mode (e.g., PostgreSQL SSI).
- Mitigate the anomaly with serializable isolation, explicit row locks (`SELECT … FOR UPDATE`), application‑level retry logic, or enforceable check constraints.
- Evaluate performance trade‑offs: serializable isolation may increase abort rates, while row locks reduce concurrency but are deterministic.

## Further Reading
- [PostgreSQL Transaction Isolation Levels](https://www.postgresql.org/docs/current/transaction-iso.html) – official documentation covering SI and serializable modes.  
- [MySQL InnoDB Transaction Model](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-model.html) – details on read‑committed, repeatable read, and lock hints.  
- [Serializable Snapshot Isolation: The Theory and Practice](https://dl.acm.org/doi/10.1145/22145.22146) – classic paper introducing SSI and its correctness guarantees.  