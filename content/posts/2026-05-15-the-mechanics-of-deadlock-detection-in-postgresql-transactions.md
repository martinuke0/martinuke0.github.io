---
title: "The Mechanics of Deadlock Detection in PostgreSQL Transactions"
date: "2026-05-15T11:57:14.344"
draft: false
tags: ["postgresql", "deadlock", "transactions", "database", "performance"]
description: "Explore how PostgreSQL detects deadlocks in multi‑transaction workloads, the internal wait‑for graph, cycle detection algorithm, and practical ways to monitor and avoid them."
summary: "A deep dive into PostgreSQL's deadlock detection mechanism, covering lock tracking, graph analysis, and actionable tuning tips."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-15-the-mechanics-of-deadlock-detection-in-postgresql-transactions.svg"
  alt: "Illustration of database transaction deadlock."
  caption: ""
  relative: false
---

> **TL;DR** — PostgreSQL builds a wait‑for graph from the lock table, runs a fast cycle‑detection algorithm, and aborts one transaction to break the deadlock. Understanding the graph, the detection trigger points, and the log output lets you diagnose and eliminate deadlocks before they cripple your application.

Deadlocks are one of the most baffling concurrency problems you can encounter in a relational database. When two or more transactions each hold a lock the other needs, they block forever—unless the engine steps in. PostgreSQL’s deadlock detector is a compact, highly optimized component that runs every time a transaction tries to acquire a lock that is already held. In this article we unpack the data structures, the algorithmic steps, and the operational knobs that make PostgreSQL’s deadlock detection both reliable and performant.

## What Is a Deadlock?

A deadlock occurs when a set of transactions form a circular wait for resources:

1. Transaction **A** holds lock **L1** and requests **L2**.  
2. Transaction **B** holds **L2** and requests **L1**.  

Both transactions block forever because each is waiting for the other to release its lock. In PostgreSQL, locks are taken on tables, rows (via `SELECT ... FOR UPDATE`), advisory lock keys, and other internal objects.

Deadlocks are not limited to two participants; a classic example involves three transactions each waiting on the next:

- **T1** → **T2** → **T3** → **T1**

The key property is a *cycle* in the wait‑for relationship. Detecting that cycle early allows the server to abort one of the participants, returning an error to the client so the application can retry.

## How PostgreSQL Tracks Locks

PostgreSQL stores lock information in a shared memory structure called the **lock manager**. Each lock request creates a `LOCK` entry, and each holder creates a `PROCLOCK` entry that links a backend process (`PGPROC`) to the lock.

### The Lock Table

The lock table lives in a fixed‑size shared memory segment (`LockMgrData`). Its layout can be simplified as:

```c
typedef struct LOCKTAG {
    uint32    locktag_field1;
    uint32    locktag_field2;
    uint32    locktag_field3;
    uint32    locktag_field4;
} LOCKTAG;

typedef struct LOCK {
    LOCKTAG   tag;          // What is being locked (relation, tuple, etc.)
    int       nRequested;   // Total number of waiters
    PROCLOCK *holders;      // Linked list of current owners
    PROCLOCK *waiters;      // Linked list of waiters
} LOCK;
```

When a transaction issues `SELECT ... FOR UPDATE`, PostgreSQL creates a **row‑level lock** (`LockTag` type `LOCKTAG_RELATION`) that points to the specific tuple. The lock manager then attempts to add the transaction to the `holders` list. If the lock is already held in a conflicting mode, the transaction is appended to the `waiters` list and put to sleep.

You can inspect the current lock state with the built‑in view `pg_locks`:

```sql
SELECT pid, locktype, mode, granted, relation::regclass
FROM pg_locks
WHERE NOT granted
ORDER BY pid;
```

The `granted` column tells you whether the entry is a holder (`true`) or a waiter (`false`). The deadlock detector works off this very structure.

## The Detection Algorithm

PostgreSQL does *not* run a heavyweight graph algorithm on every lock request. Instead, it employs a **two‑phase approach**:

1. **Fast Path** – a quick check for obvious cycles using a *wait‑for edge* count.
2. **Full Graph Scan** – only when the fast path cannot rule out a deadlock.

### Wait‑for Graph Construction

When a transaction (`TxA`) cannot acquire a lock because another transaction (`TxB`) holds it, PostgreSQL adds a directed edge **TxA → TxB** to an implicit *wait‑for graph*. This graph is not stored explicitly; it is derived on‑the‑fly from the lock manager’s `waiters` and `holders` lists.

The graph construction proceeds as follows:

1. Identify the lock that caused the block.
2. Walk the `holders` list of that lock; for each holder, create an edge from the waiting transaction to the holder.
3. If the waiting transaction already appears as a holder on the same lock (self‑deadlock), abort immediately (this is rare and usually a programming error).

Because the lock manager already links each waiter to the holders, the graph can be generated in **O(k)** where *k* is the number of conflicting holders, typically a small constant.

### Cycle Detection with Tarjan’s Algorithm

When the fast path (a simple edge count) suggests a possible cycle, PostgreSQL invokes a depth‑first search (DFS) based on **Tarjan’s strongly connected components (SCC)** algorithm. The implementation lives in `src/backend/storage/lmgr/deadlock.c` and works with a *stack* of transactions.

Key properties:

- **Linear time** – the algorithm visits each vertex (transaction) and edge (wait‑for relationship) exactly once, giving O(V + E) complexity.
- **Early exit** – as soon as a back edge to an ancestor is found, a cycle is confirmed and the search stops.
- **Minimal memory** – the algorithm reuses the `PGPROC` structures to store DFS numbers, avoiding extra allocations.

Pseudo‑code (simplified):

```c
bool DetectDeadlock(PGPROC *waiter)
{
    Stack s;
    push(s, waiter);
    while (!empty(s)) {
        PGPROC *cur = pop(s);
        if (cur->dfsVisited) continue;
        cur->dfsVisited = true;
        foreach (PGPROC *holder in cur->waitEdges) {
            if (holder->dfsVisited) {
                // Cycle found!
                AbortTransaction(holder);
                return true;
            }
            push(s, holder);
        }
    }
    return false;
}
```

When a cycle is found, PostgreSQL selects **the youngest transaction** (by start timestamp) as the victim. The victim receives the error:

```
ERROR: deadlock detected
DETAIL: Process 12345 waits for ShareLock on transaction 67890; blocked by process 54321.
HINT: See server log for query details.
```

The choice of the youngest victim minimizes wasted work because newer transactions have typically done less work than older ones.

## What Happens When a Deadlock Is Found?

Once the detector identifies a cycle, PostgreSQL performs several steps:

1. **Abort the victim** – the backend rolls back the transaction, releases all its locks, and wakes any waiters that were blocked by those locks.
2. **Log the deadlock** – the server writes a detailed message to the log (level `ERROR`). The log includes the participating PIDs, lock types, and the SQL statements that held the locks, if `log_min_error_statement` or `log_lock_waits` is enabled.
3. **Notify the client** – the client receives the `deadlock_detected` SQLSTATE (`40P01`). Applications can catch this and retry the transaction.

A sample log entry:

```text
2026-05-15 12:03:42.123 UTC [12345] LOG:  deadlock detected
2026-05-15 12:03:42.124 UTC [12345] DETAIL:  Process 12345 waits for ShareLock on transaction 67890; blocked by process 54321.
2026-05-15 12:03:42.124 UTC [54321] DETAIL:  Process 54321 waits for ShareLock on transaction 12345; blocked by process 12345.
2026-05-15 12:03:42.124 UTC [12345] HINT:  See server log for query details.
2026-05-15 12:03:42.124 UTC [12345] STATEMENT:  UPDATE accounts SET balance = balance - 100 WHERE id = 42;
```

The log is invaluable for post‑mortem analysis because it shows both sides of the cycle and the exact statements that caused the conflict.

## Tuning and Avoidance Strategies

Detecting deadlocks is only half the battle; preventing them is often cheaper than handling them at runtime. PostgreSQL provides several knobs and best‑practice patterns.

### 1. Consistent Lock Ordering

If all application code acquires locks in the same order (e.g., always lock `accounts` before `transactions`), cycles cannot form. This is the single most effective defensive technique.

### 2. Reduce Lock Scope

- Use `SELECT ... FOR UPDATE SKIP LOCKED` when you can tolerate missing rows.
- Prefer `UPDATE ... WHERE ... RETURNING` to lock only the rows you actually modify.
- Keep transactions short; the longer a transaction holds a lock, the higher the probability of intersecting with another transaction’s lock request.

### 3. Adjust `deadlock_timeout`

PostgreSQL waits `deadlock_timeout` (default 1 second) before triggering a deadlock check. Setting it lower (e.g., `100ms`) makes the system more aggressive at detecting deadlocks, at the cost of slightly higher CPU usage for the detection routine.

```bash
ALTER SYSTEM SET deadlock_timeout = '200ms';
SELECT pg_reload_conf();
```

### 4. Enable Detailed Logging

Turn on `log_lock_waits` and `log_min_error_statement` to capture the exact SQL that participates in a deadlock. This makes debugging far easier.

```conf
log_lock_waits = on
log_min_error_statement = error
```

### 5. Use Advisory Locks Sparingly

Advisory locks (`pg_advisory_lock`) are user‑defined and not part of the automatic deadlock detection unless they conflict with other advisory locks. Treat them as a separate coordination mechanism and avoid nested advisory lock patterns that could create cycles.

### 6. Monitor with `pg_stat_activity` and Extensions

The view `pg_stat_activity` shows queries waiting for locks (`wait_event_type = 'Lock'`). Combine it with `pg_locks` to build a live wait‑for picture.

```sql
SELECT a.pid, a.query, l.locktype, l.mode, l.granted
FROM pg_stat_activity a
JOIN pg_locks l ON a.pid = l.pid
WHERE l.granted = false;
```

For automated monitoring, extensions like **pg_deadlock_report** or **pg_stat_statements** can alert you when deadlocks exceed a threshold.

## Monitoring Deadlocks with pg_stat_activity and Logs

Even with best practices, deadlocks can slip through, especially in high‑concurrency workloads. A pragmatic monitoring setup includes:

1. **Log Parsing** – Use a log aggregation tool (e.g., ELK stack) to parse `deadlock detected` lines and count occurrences per hour.
2. **Alerting** – Set alerts when the count exceeds your SLA (e.g., more than 5 deadlocks in 10 minutes).
3. **Live View** – Periodically run the combined `pg_stat_activity` / `pg_locks` query above to spot transactions that are waiting a long time (e.g., > `deadlock_timeout`).

Example Bash script to dump waiting queries:

```bash
#!/usr/bin/env bash
psql -d mydb -Atc "
SELECT a.pid,
       now() - a.query_start AS waiting_time,
       a.query,
       l.locktype,
       l.mode
FROM pg_stat_activity a
JOIN pg_locks l ON a.pid = l.pid
WHERE l.granted = false
ORDER BY waiting_time DESC
LIMIT 10;
"
```

Running this script every 30 seconds gives you a snapshot of potential deadlock candidates before PostgreSQL aborts a victim.

## Key Takeaways

- PostgreSQL builds an implicit wait‑for graph from its lock manager’s `waiters` and `holders` lists each time a lock request blocks.
- A fast edge‑count filter precedes a full **Tarjan SCC** scan, guaranteeing O(V + E) detection time.
- The youngest transaction in a cycle is chosen as the victim, rolled back, and reported with SQLSTATE `40P01`.
- Detailed logs (enabled via `log_lock_waits` and `log_min_error_statement`) provide the exact statements and lock types involved, essential for root‑cause analysis.
- Prevent deadlocks by enforcing a consistent lock order, keeping transactions short, and using `SKIP LOCKED` or row‑level updates when possible.
- Tune `deadlock_timeout` and monitor waiting queries with `pg_stat_activity` + `pg_locks` to catch problematic patterns early.

## Further Reading

- [PostgreSQL Documentation – Concurrency Control](https://www.postgresql.org/docs/current/mvcc.html)  
- [Deadlock Detection in PostgreSQL source code (deadlock.c)](https://github.com/postgres/postgres/blob/master/src/backend/storage/lmgr/deadlock.c)  
- [Wikipedia – Deadlock](https://en.wikipedia.org/wiki/Deadlock)  