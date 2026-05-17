---
title: "When Write Skew Breaks Snapshot Isolation Consistency"
date: "2026-05-17T16:00:59.212"
draft: false
tags: ["database", "consistency", "snapshot-isolation", "write-skew", "transactional-systems"]
description: "An in‑depth exploration of how write skew can violate snapshot isolation, with examples, detection techniques, and practical prevention strategies."
summary: "Discover why write skew undermines snapshot isolation and learn concrete methods to detect and avoid this subtle anomaly."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-when-write-skew-breaks-snapshot-isolation-consistency.svg"
  alt: "Diagram illustrating concurrent transactions causing write skew."
  caption: ""
  relative: false
---

> **TL;DR** — Write skew is a subtle anomaly that can corrupt data even under snapshot isolation. By understanding its mechanics, adding proper constraints, or switching to stricter isolation levels, you can safeguard consistency in modern transactional systems.

Snapshot isolation (SI) is often marketed as “almost as strong as serializability, but with better performance.” For many workloads that involve mostly read‑heavy queries, SI delivers exactly that: each transaction sees a *snapshot* of the database as of its start time, and concurrent writes are allowed as long as they touch different rows. However, the promise of SI hides a dangerous edge case—*write skew*. When two transactions read overlapping data and then write disjoint rows based on those reads, the database can end up in an invalid state that would be impossible under true serializability.

In this article we will:

* Review the guarantees that snapshot isolation provides.
* Define write skew and illustrate it with concrete SQL examples.
* Show why write skew breaks the consistency model that many developers assume SI enforces.
* Discuss detection techniques, from explicit constraints to modern conflict‑resolution mechanisms.
* Offer practical recommendations for preventing write skew in production systems.

The goal is to give you a mental model that lets you spot potential write‑skew bugs before they surface in production, and to equip you with actionable tools to eliminate them.

## Snapshot Isolation Overview

Snapshot isolation is defined by three core rules, as described in the PostgreSQL documentation[^1]:

1. **Read Consistency** – A transaction reads from a *snapshot* taken at its start time; it never sees changes made by concurrent transactions.
2. **Write Conflict Detection** – If two concurrent transactions attempt to modify the *same* row, the later one aborts with a serialization error.
3. **No Phantom Prevention** – Unlike serializable isolation, SI does not automatically prevent *phantom* rows from appearing in a range query.

These rules mean that SI allows **write‑write conflicts** to be detected, but it does **not** prevent **read‑write** conflicts that do not target the same physical row. Write skew lives exactly in that gap.

### Formal definition

Formally, a transaction *T* under SI sees a database state *S* that satisfies:

```
S = state_at_start(T) ∪ writes_by(T)
```

No other transaction’s writes are visible, except those that *T* itself performed. The only abort condition is a *write‑write* conflict on the same primary key.

## What Is Write Skew?

Write skew occurs when two concurrent transactions:

1. Read overlapping rows (or overlapping logical conditions).
2. Make decisions based on those reads.
3. Write to *different* rows, thereby avoiding the write‑write conflict detection.

Because each transaction’s snapshot does not include the other’s writes, each makes a decision that appears correct in isolation, yet the combined effect violates an application‑level invariant.

### Classic banking example

Consider a simple banking schema that enforces the invariant “an account must never have a negative balance”. A naïve implementation might rely on a *CHECK* constraint on each row:

```sql
CREATE TABLE accounts (
    id      SERIAL PRIMARY KEY,
    balance NUMERIC NOT NULL CHECK (balance >= 0)
);
```

Now imagine two concurrent withdrawals from the same account, each of $60, while the account holds $100. Under SI:

* **Tx1** starts, sees balance = 100, decides it can withdraw $60, writes new balance = 40.
* **Tx2** starts *almost at the same time*, also sees balance = 100, decides it can withdraw $60, writes new balance = 40.

Both transactions modify the *same row*, so SI will abort the later one—write skew does **not** happen here because the conflict is on the same primary key.

### Write skew on *different* rows

The anomaly becomes visible when the invariant spans **multiple rows**. Suppose we have a table of doctors and their on‑call status, and a hospital policy that at least one doctor must be on call at any time:

```sql
CREATE TABLE doctors (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    on_call     BOOLEAN NOT NULL
);
```

The invariant is: `SELECT COUNT(*) FROM doctors WHERE on_call = TRUE >= 1`.

Two doctors, Alice and Bob, are currently on call (`on_call = TRUE`). Both decide to go on vacation and set their own `on_call` flag to `FALSE`. Under SI:

* **TxA** (Alice) reads the table, sees two on‑call doctors, decides it is safe to set her own flag to FALSE, writes `on_call = FALSE` for Alice.
* **TxB** (Bob) reads the *same snapshot* (still sees two on‑call doctors), decides it is safe, writes `on_call = FALSE` for Bob.

Because they updated **different rows**, SI does not detect a conflict, and both commit. The final state has zero doctors on call, violating the invariant. This is the textbook *write skew* scenario.

### Why the CHECK constraint fails

Adding a per‑row `CHECK (on_call = TRUE)` does not help, because each row individually satisfies the constraint. The invariant is *global*—it involves aggregation across rows, which a simple CHECK cannot express.

## How Write Skew Violates Consistency

From a theoretical standpoint, snapshot isolation is **not** a serializable isolation level. Serializability guarantees that the outcome of concurrent transactions is equivalent to some serial order. Write skew produces a state that cannot be reproduced by any serial execution of the same transactions.

### Serializability vs. SI

In the doctors example, a serial order would be:

1. **TxA** runs first, sets Alice to `FALSE`. The system now has one on‑call doctor (Bob). The invariant holds.
2. **TxB** runs second, sees only one on‑call doctor (Bob) and should **reject** the update because it would break the invariant.

Since SI allowed both to commit, the final state is **non‑serializable**.

### Real‑world impact

Write skew bugs are subtle because they often surface only under high concurrency or specific timing windows. In production, they have caused:

* **Healthcare scheduling failures** where no staff were on call, leading to delayed patient care.
* **Financial risk exposure** where two traders simultaneously reduced margin requirements, leaving the system under‑collateralized.
* **Inventory miscounts** in e‑commerce platforms where two warehouses each believed stock was sufficient, leading to overselling.

These incidents demonstrate that relying on SI alone can be dangerous for any application that enforces *cross‑row* invariants.

## Detecting and Preventing Write Skew

Because the anomaly is rooted in the lack of *read‑write* conflict detection, the most reliable prevention strategies involve either:

1. **Explicit locking or stricter isolation** (e.g., `SERIALIZABLE`), or
2. **Application‑level checks that translate into row‑level conflicts**.

### 1. Use SERIALIZABLE isolation

Most modern RDBMSes support a true serializable mode that extends SI with *predicate locking* to block phantom rows and write‑skew scenarios. In PostgreSQL, you can enable it per‑transaction:

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- your logic here
COMMIT;
```

If a write‑skew situation is detected, PostgreSQL aborts one of the transactions with the error `SQLSTATE 40001` (serialization_failure). The application can then retry.

**Pros:** Guarantees serializability without rewriting business logic.  
**Cons:** Higher abort rates under contention; may require retry logic.

### 2. Explicit predicate locks (SELECT … FOR UPDATE)

If you cannot afford the performance cost of full serializability, you can lock the *predicate* that the invariant depends on. In the doctors example:

```sql
BEGIN;
SELECT id FROM doctors WHERE on_call = TRUE FOR UPDATE;
-- now the rows satisfying the predicate are locked
UPDATE doctors SET on_call = FALSE WHERE id = :my_id;
COMMIT;
```

The `FOR UPDATE` clause acquires row‑level locks on **all** currently on‑call doctors, turning the read‑write pattern into a write‑write conflict. The second transaction will block (or abort, depending on lock timeout) until the first commits, preserving the invariant.

**Pros:** Fine‑grained control; works under SI.  
**Cons:** May lock more rows than necessary, causing reduced concurrency.

### 3. Add a surrogate “counter” table

Another pattern is to store the invariant in a separate table that can be atomically updated. For the on‑call policy, you could maintain a counter:

```sql
CREATE TABLE on_call_counter (
    id    INT PRIMARY KEY CHECK (id = 1),
    count INT NOT NULL CHECK (count >= 1)
);
```

When a doctor goes on/off call, you update both the `doctors` row **and** the counter in a single transaction, using `SELECT … FOR UPDATE` on the counter row. Since both transactions now touch the **same** counter row, SI will detect the conflict.

**Pros:** Centralizes the invariant; low contention if updates are infrequent.  
**Cons:** Adds schema complexity; requires careful transactional ordering.

### 4. Use database‑provided “assertion” features

Some databases (e.g., Oracle) support **materialized view constraints** that can enforce aggregate conditions. PostgreSQL can emulate this with **exclusion constraints** combined with `WITH (READ ONLY)` queries, but the approach is advanced.

### 5. Leverage modern distributed transaction engines

Systems like CockroachDB implement **serializable snapshot isolation (SSI)** by default, automatically detecting write‑skew anomalies without explicit locking[^2]. If you are building a distributed service, adopting such a platform can offload the complexity.

#### Example: CockroachDB SSI

```sql
BEGIN;
UPDATE doctors SET on_call = FALSE WHERE id = $1;
COMMIT;
```

If two concurrent updates would cause zero on‑call doctors, CockroachDB aborts one transaction with a `restart transaction` error, ensuring serializability.

## Real‑World Cases and Lessons Learned

### Case Study 1: Booking System Overbooking

A major airline used SI on a PostgreSQL backend for seat reservations. The invariant: “no seat may be assigned to more than one passenger”. The system stored each reservation as a row with `flight_id` and `seat_number`. Two concurrent bookings for the same seat were prevented by SI’s write‑write detection because they targeted the same row.

However, the airline also allowed **seat swaps**: a passenger could request a different seat, creating a *new* reservation row and deleting the old one. Two concurrent swaps could lead to a *write skew* where the original seat became double‑booked after both transactions deleted different rows and inserted new ones. After a near‑miss incident, the team switched to `SERIALIZABLE` for all seat‑swap operations, eliminating the bug.

### Case Study 2: Financial Margin Checks

A fintech platform enforced a rule: “total exposure must not exceed $10 M”. Exposure was stored per‑trader in a `positions` table. Two traders simultaneously reduced their positions, each reading the total exposure, deciding it was safe, and committing the reduction. Because each update touched a different trader’s row, SI allowed both, pushing total exposure over the limit. The platform added a **centralized exposure ledger** with a row‑level lock, turning the read‑write pattern into a write‑write conflict.

### Lessons

1. **Identify global invariants early** – any rule that aggregates across rows is a candidate for write skew.
2. **Test under concurrency** – use tools like `pgbench` or `sysbench` to simulate overlapping transactions.
3. **Prefer SERIALIZABLE for critical paths** – the cost is often acceptable compared to the risk of data corruption.
4. **Document the isolation level** – developers frequently assume “default” means “safe”; make the contract explicit.

## Key Takeaways

- Snapshot isolation prevents *write‑write* conflicts but **does not** guard against *read‑write* patterns that affect global invariants.
- **Write skew** occurs when two concurrent transactions read overlapping data, make decisions, and then write to different rows, leaving the database in an invalid state.
- The anomaly is **non‑serializable**; a serial execution order would reject at least one of the conflicting transactions.
- Mitigation strategies include:
  1. Switching to **SERIALIZABLE** isolation (or SSI in distributed databases).
  2. Using **SELECT … FOR UPDATE** to lock the predicate set.
  3. Maintaining a **counter/aggregation table** that all related transactions update.
  4. Leveraging **database‑provided assertions** or **exclusion constraints** where available.
  5. Adopting platforms that implement **serializable snapshot isolation** by default.
- Always **test concurrency** for any business rule that spans multiple rows or tables; a simple unit test cannot reveal write‑skew bugs.

## Further Reading

- [Snapshot Isolation in PostgreSQL](https://www.postgresql.org/docs/current/transaction-iso.html) – official documentation covering SI semantics and serializable mode.  
- [Write Skew – Wikipedia](https://en.wikipedia.org/wiki/Write_skew) – overview of the anomaly with additional examples.  
- [Serializable Snapshot Isolation (SSI) in CockroachDB](https://www.cockroachlabs.com/docs/stable/transactions.html) – how CockroachDB detects and resolves write skew automatically.  
- [Transaction Isolation Levels – Wikipedia](https://en.wikipedia.org/wiki/Isolation_(database_systems)) – comparative guide to isolation levels across DBMSes.  
- [PostgreSQL Concurrency Control – The Serialization Failure Error](https://www.postgresql.org/docs/current/errcodes-appendix.html) – details on handling `SQLSTATE 40001` errors.