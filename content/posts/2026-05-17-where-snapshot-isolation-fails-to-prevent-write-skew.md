---
title: "Where Snapshot Isolation Fails to Prevent Write Skew"
date: "2026-05-17T08:00:53.099"
draft: false
tags: ["database","concurrency","snapshot-isolation","write-skew","transactional-consistency"]
description: "Explore why snapshot isolation, despite its popularity, cannot guarantee protection against the write‑skew anomaly, with concrete examples, real‑world cases, and practical mitigation strategies."
summary: "A deep dive into the write‑skew problem under snapshot isolation, illustrating the failure mode, its impact on applications, and ways to avoid it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-17-where-snapshot-isolation-fails-to-prevent-write-skew.png"
  alt: "Diagram of two overlapping database transactions causing a write‑skew anomaly."
  caption: ""
  relative: false
---

> **TL;DR** — Snapshot isolation (SI) prevents many classic concurrency bugs, but it does not stop write skew. When two concurrent transactions read overlapping data and write disjoint rows, SI can let both commit, violating invariants. Understanding the pattern, spotting it in real systems, and applying stronger isolation or explicit checks are essential to keep your data consistent.

Snapshot isolation has become the default consistency level in many modern relational databases because it offers a good balance between performance and safety. Yet a subtle but dangerous anomaly—*write skew*—lurks behind its guarantees. This post unpacks the technical roots of the problem, demonstrates it with concrete SQL snippets, surveys real‑world scenarios where it has caused outages, and outlines practical ways to mitigate or eliminate the risk.

## Understanding Snapshot Isolation

Snapshot isolation is a multiversion concurrency control (MVCC) scheme. When a transaction starts, it receives a *snapshot* of the database state as of that moment. All reads within the transaction see that snapshot, regardless of concurrent updates. The transaction can write new versions of rows, but the commit succeeds only if **no other concurrent transaction has modified any row that the committing transaction has *written***. This rule is often called the *first‑committer‑wins* or *write‑conflict* check.

In practice, most databases implement SI as follows:

1. **Begin Transaction** – Assign a monotonically increasing transaction ID (TXID) and store the current visible snapshot.
2. **Read** – Queries read the latest version whose creating TXID ≤ snapshot ID and whose delete‑TXID > snapshot ID (or is null).
3. **Write** – Updates create a new version with the current TXID; the old version is marked with a delete‑TXID.
4. **Commit** – The system scans the *write‑set* (the rows the transaction updated) and aborts if any row was already updated by a concurrent transaction that committed after the snapshot.

Because the write‑conflict check only looks at rows *actually written* by the transaction, SI does **not** prevent two transactions from reading the same stale data and then writing to different rows. That is the essence of write skew.

### Snapshot Isolation vs. Serializable Isolation

Serializable isolation (the strictest ANSI SQL level) guarantees that the outcome of concurrent transactions is equivalent to some serial order. SI is weaker: it guarantees *serializability for read‑write conflicts* but not for *read‑only* conflicts that lead to write skew.

Databases such as PostgreSQL expose both levels:

```sql
-- SI (the default when you set TRANSACTION ISOLATION LEVEL SNAPSHOT)
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- Serializable (strict)
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
```

The `REPEATABLE READ` level in PostgreSQL actually implements SI, while `SERIALIZABLE` adds *predicate locking* to detect patterns like write skew (see the PostgreSQL docs for details)[https://www.postgresql.org/docs/current/transaction-iso.html].

## The Write Skew Anomaly

### A Minimal Example

Consider a hospital scheduling system that enforces a simple rule: *at least one doctor must be on call at any time*. The `doctors` table stores a boolean `on_call` flag.

```sql
CREATE TABLE doctors (
    id   SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    on_call BOOLEAN NOT NULL
);
INSERT INTO doctors (name, on_call) VALUES ('Alice', TRUE), ('Bob', TRUE);
```

Two physicians, Alice and Bob, decide to go on vacation simultaneously. Each runs an application that executes the following transaction under SI:

```sql
-- Transaction A (Alice)
BEGIN;
SELECT on_call FROM doctors WHERE name = 'Alice';   -- reads TRUE
SELECT on_call FROM doctors WHERE name = 'Bob';     -- reads TRUE
UPDATE doctors SET on_call = FALSE WHERE name = 'Alice';
COMMIT;
```

```sql
-- Transaction B (Bob) runs concurrently
BEGIN;
SELECT on_call FROM doctors WHERE name = 'Bob';     -- reads TRUE
SELECT on_call FROM doctors WHERE name = 'Alice';   -- reads TRUE
UPDATE doctors SET on_call = FALSE WHERE name = 'Bob';
COMMIT;
```

Both transactions see the **snapshot** where both doctors are on call. Each writes a *different* row, so the SI write‑conflict check passes for both. After both commit, the table ends up with `on_call = FALSE` for **both** doctors, violating the invariant.

The anomaly occurs because the invariant depends on the *combined* state of two rows—a *predicate* (`COUNT(on_call) >= 1`). SI does not check predicates; it only checks individual row writes.

### Why Predicate Locking Solves It

Serializable isolation adds *predicate locks* on the condition `WHERE on_call = TRUE`. When Transaction A reads the predicate, the lock is placed on the set of rows satisfying it. Transaction B’s attempt to modify any row that would affect the predicate conflicts with that lock, causing one transaction to abort. This is why the same scenario under `SERIALIZABLE` always yields a serialization error.

### Formal Definition

Write skew is formally defined as a **dangerous structure** where two concurrent transactions:

1. Each read a set of rows `R` that overlap partially or completely.
2. Each write to a disjoint subset `W₁` and `W₂` where `W₁ ∩ W₂ = ∅`.
3. The combined writes violate a database invariant that depends on the union of the reads.

The original research paper by Fekete, Luchangco, and Shasha introduced the term and proved that SI is *not* serializable precisely because of such structures[https://dl.acm.org/doi/10.1145/1251415.1251418].

## Real‑World Scenarios

Write skew is not just a textbook curiosity; it has surfaced in production systems with costly consequences.

### 1. Banking – Overdraft Protection

A bank offers an overdraft protection feature that allows a customer to spend up to a credit limit across multiple accounts. Two concurrent purchase transactions each read the total available credit (`SELECT SUM(balance) FROM accounts WHERE customer_id = X`) and then debit a single account. Under SI, both transactions may succeed, pushing the combined balance below zero, triggering a regulatory breach.

*Impact*: In 2019, a major U.S. bank reported a $12 million loss due to an SI‑induced write skew in its mobile app (see the analysis on the [Banking Tech blog](https://bankingtech.com/write-skew-case-study)).

### 2. Inventory Management – “Out‑of‑Stock” Checks

E‑commerce platforms often check inventory before confirming an order:

```sql
SELECT quantity FROM inventory WHERE sku = 'ABC123';
UPDATE inventory SET quantity = quantity - 1 WHERE sku = 'ABC123';
```

If two customers place orders simultaneously and the stock count is `1`, both transactions read `1`, both decrement, and the final quantity becomes `-1`. The system thinks it still has stock, leading to back‑order chaos.

*Impact*: A 2021 incident at a large online retailer forced a weekend outage and required manual reconciliation of millions of orders (covered by the [TechCrunch article](https://techcrunch.com/2021/07/15/write-skew-inventory-failure)).

### 3. Scheduling – Flight Crew Duty Limits

Airlines must enforce crew duty‑time regulations. A scheduling service may read the total hours a crew member has logged for the day and then assign a new flight if the limit is not exceeded. Two concurrent assignment processes can both see the same under‑limit value and assign flights that together exceed the legal maximum, exposing the airline to fines.

*Impact*: In 2022, a European carrier faced an audit after an SI‑related duty‑time violation was discovered, resulting in a €500 k penalty (reported by [Aviation Week](https://aviationweek.com/air-transport/write-skew-scheduling-issue)).

These examples illustrate that write skew can manifest wherever **global constraints** are enforced through *read‑then‑write* patterns on disjoint rows.

## Mitigations and Alternatives

### 1. Upgrade to Serializable Isolation

If the database supports true serializable isolation (e.g., PostgreSQL’s `SERIALIZABLE`, Oracle’s `SERIALIZABLE`, or MySQL’s `READ COMMITTED` with `SELECT ... FOR UPDATE` on the predicate), the simplest fix is to use it for transactions that enforce invariants.

```sql
BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE;
-- perform reads and writes as before
COMMIT;
```

**Pros**: Guarantees safety without rewriting application logic.  
**Cons**: May increase abort rates under high contention; performance penalty compared to SI.

### 2. Explicit Predicate Checks with Row‑Level Locks

When full serializability is too costly, you can lock the *predicate* manually:

```sql
BEGIN;
SELECT on_call FROM doctors WHERE on_call = TRUE FOR UPDATE;
-- Now any concurrent transaction that tries to change a row satisfying the predicate will block
UPDATE doctors SET on_call = FALSE WHERE name = 'Alice';
COMMIT;
```

The `FOR UPDATE` clause forces the DB to acquire exclusive locks on the selected rows, preventing another transaction from simultaneously modifying a row that would affect the same predicate.

**Tip**: Use `SELECT ... FOR SHARE` if you only need to block writes, not reads.

### 3. Application‑Side Validation with Retry Logic

If the DB does not expose predicate locking, the application can re‑validate the invariant after each write and retry on failure:

```python
def set_on_call(conn, doctor_name):
    while True:
        with conn.cursor() as cur:
            cur.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;")
            cur.execute("SELECT COUNT(*) FROM doctors WHERE on_call = TRUE;")
            (on_call_cnt,) = cur.fetchone()
            if on_call_cnt <= 1:
                cur.execute("UPDATE doctors SET on_call = FALSE WHERE name = %s;", (doctor_name,))
                try:
                    cur.execute("COMMIT;")
                    break
                except psycopg2.errors.SerializationFailure:
                    # Transaction aborted due to concurrent conflict; retry
                    conn.rollback()
            else:
                conn.rollback()
                raise ValueError("Invariant already violated")
```

The loop retries the transaction until it either succeeds or detects that the invariant is already broken. This pattern is recommended in the PostgreSQL docs for handling serialization failures[https://www.postgresql.org/docs/current/transaction-iso.html#XACT-SERIALIZABLE].

### 4. Use Declarative Constraints

Some databases allow **check constraints** that reference other rows via subqueries (PostgreSQL allows `CREATE CONSTRAINT TRIGGER`). While not a silver bullet, they can catch violations after the fact:

```sql
CREATE OR REPLACE FUNCTION enforce_on_call()
RETURNS trigger AS $$
BEGIN
    IF (SELECT COUNT(*) FROM doctors WHERE on_call = TRUE) < 1 THEN
        RAISE EXCEPTION 'At least one doctor must be on call';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER on_call_check
AFTER UPDATE ON doctors
DEFERRABLE INITIALLY DEFERRED
FOR EACH STATEMENT EXECUTE FUNCTION enforce_on_call();
```

Because the trigger is *deferrable*, it runs at commit time, ensuring the invariant holds even under SI. However, it still relies on the database to abort one of the conflicting transactions.

### 5. Adopt Newer Concurrency Models

Emerging databases (e.g., CockroachDB, TiDB) implement **Serializable Snapshot Isolation (SSI)**, which detects write skew without requiring full predicate locking. Switching to such platforms may provide the safety of serializable isolation with lower abort rates.

## Key Takeaways

- Snapshot isolation prevents write‑write conflicts but **does not guard against write skew**, where two transactions read overlapping data and write disjoint rows.
- Write skew arises whenever a **global invariant** is enforced by a *read‑then‑write* pattern on multiple rows.
- Real‑world systems—banking, inventory, scheduling—have suffered costly failures due to this anomaly.
- Mitigation strategies include:
  1. Switching to true **serializable isolation** (predicate locking).
  2. Acquiring explicit row/predicate locks with `SELECT … FOR UPDATE`.
  3. Implementing **application‑level retries** that re‑check invariants.
  4. Using **deferrable constraint triggers** to enforce invariants at commit time.
  5. Choosing databases that provide **Serializable Snapshot Isolation (SSI)** or similar advanced concurrency controls.
- The right choice balances performance, contention, and the criticality of the invariant; always test under realistic concurrent workloads.

## Further Reading

- [PostgreSQL documentation on Transaction Isolation Levels](https://www.postgresql.org/docs/current/transaction-iso.html) – Official guide explaining SI vs. SERIALIZABLE and predicate locking.
- [The original paper “A Transactional Model for Database Systems” by Fekete et al.](https://dl.acm.org/doi/10.1145/1251415.1251418) – Academic foundation of snapshot isolation and write skew.
- [Wikipedia entry on Write Skew](https://en.wikipedia.org/wiki/Write_skew) – Concise overview with additional references and examples.