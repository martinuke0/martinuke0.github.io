---
title: "Architecting Double-Entry Ledger Systems: Schema, Concurrency, and Auditability for Financial Integrity"
date: "2026-09-02T22:00:49.685"
draft: false
tags: ["databases", "postgres", "fintech", "system-design", "accounting"]
description: "A production-oriented guide to designing double-entry ledger systems, covering schemas, isolation levels, and immutable audit trails."
summary: "How to design a double-entry ledger that stays correct under concurrency: event-sourced schema, Postgres constraints, and append-only audit trails."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-architecting-double-entry-ledger-systems-schema-concurrency-and-auditability-for-financial-integrity.svg"
  alt: "Stylized ledger book with debits and credits balanced on facing pages."
  caption: ""
  relative: false
---

> **TL;DR** — A correct ledger is enforced by the database, not the application. Use a normalized schema with per-account transaction sequences, enforce double-entry invariants through check constraints and triggers, and serialize per-account writes with row-level locks under `READ COMMITTED`. Append every change to an immutable audit log so that the state of the system at any point in time can be reconstructed.

## Why Double-Entry Matters in Software

Accounting's central guarantee is simple: the sum of all debits always equals the sum of all credits. In a hand-written ledger, this is a discipline enforced by clerks and verified by trial balances. In software, we get to do better — we can make the database *physically incapable* of recording an unbalanced transaction.

This matters for more than banks. Any system that tracks obligations between parties — wallets, marketplaces, ad-tech revenue share, payroll, insurance reserves, even internal cost allocation — has the same shape. Get the ledger right and the rest of the system becomes much easier to reason about. Get it wrong and you will spend years writing reconciliation jobs that try to patch over a model that does not conserve value.

The reference implementation in this post targets PostgreSQL, but the same patterns apply to CockroachDB, MySQL with InnoDB, and Oracle. The core idea is the same: model the ledger as a sequence of immutable events that are guaranteed by the schema to be balanced.

## Core Schema: Accounts, Transactions, and Postings

The minimum viable schema has three tables. Everything else is optimization.

```sql
CREATE TABLE accounts (
    id          BIGSERIAL PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL,
    currency    CHAR(3) NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('asset','liability','equity','revenue','expense')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Accounts are the buckets money lives in. Each one has a direction implied by its kind — assets and expenses increase with debits, while liabilities, equity, and revenue increase with credits. The `kind` column is what lets you build a real chart of accounts.

```sql
CREATE TABLE transactions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    posted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    description  TEXT NOT NULL,
    reference    TEXT,
    metadata     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE posting_side AS ENUM ('debit', 'credit');

CREATE TABLE postings (
    id              BIGSERIAL PRIMARY KEY,
    transaction_id  UUID NOT NULL REFERENCES transactions(id),
    account_id      BIGINT NOT NULL REFERENCES accounts(id),
    side            posting_side NOT NULL,
    amount_minor    BIGINT NOT NULL CHECK (amount_minor > 0),
    currency        CHAR(3) NOT NULL,
    seq             BIGINT NOT NULL
);
```

A few choices deserve attention:

- **Amounts are stored as `BIGINT` minor units** (cents, pence, fils). Floating point has no place in a ledger — `0.1 + 0.2 ≠ 0.3` and the bugs are spectacular.
- **`currency` lives on the posting**, not the account, so a single transaction can move money across currencies. The FX rate is then a separate posting pair against a dedicated FX account.
- **`seq` is a per-account monotonic counter** that lets you read an account's balance at any moment in time, and lets you detect out-of-order writes if you ever shard.

### The Balance Invariant

For every transaction, the sum of debit postings must equal the sum of credit postings *per currency*. This is the invariant that makes the whole system work. You can enforce it directly in Postgres with a deferred trigger so the whole transaction is visible to the check:

```sql
CREATE OR REPLACE FUNCTION assert_transaction_balanced()
RETURNS trigger AS $$
DECLARE
    imbalance RECORD;
BEGIN
    FOR imbalance IN
        SELECT currency,
               SUM(CASE WHEN side = 'debit'  THEN amount_minor ELSE 0 END) AS dr,
               SUM(CASE WHEN side = 'credit' THEN amount_minor ELSE 0 END) AS cr
        FROM postings
        WHERE transaction_id = NEW.transaction_id
        GROUP BY currency
    LOOP
        IF imbalance.dr <> imbalance.cr THEN
            RAISE EXCEPTION 'unbalanced transaction %: % dr=% cr=%',
                NEW.transaction_id, imbalance.currency, imbalance.dr, imbalance.cr;
        END IF;
    END LOOP;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER postings_balance_check
    AFTER INSERT ON postings
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW
    EXECUTE FUNCTION assert_transaction_balanced();
```

`DEFERRABLE INITIALLY DEFERRED` is the magic ingredient. It lets the application insert both legs of a transaction in any order, and the check only fires at `COMMIT` time. If the inserts don't balance, the entire transaction rolls back and the ledger stays correct by construction — as described in the [PostgreSQL trigger documentation](https://www.postgresql.org/docs/current/triggers.html).

## Concurrency: How to Avoid Lost Updates

Most ledger bugs are not schema bugs — they are race conditions. Two transfers read the same balance, both decide the sender has enough, and both proceed. Classic lost update. The fix is to choose your isolation level carefully and lock the right rows.

For a single-node Postgres deployment, the working recipe is:

1. Run at `READ COMMITTED` (the default).
2. Inside the transaction, `SELECT ... FOR UPDATE` the rows of every account the transaction will touch.
3. Re-read the balance after acquiring the lock and validate.
4. Insert the postings, commit, release the locks.

```sql
BEGIN;

-- Lock accounts in a deterministic order to prevent deadlocks
SELECT id FROM accounts
WHERE code = ANY(ARRAY['cash:usd', 'fees:usd', 'merchant:usd'])
ORDER BY code
FOR UPDATE;

-- Validate the sender has enough
SELECT current_balance_minor('cash:usd');  -- helper function

-- Re-validate under the lock; raise if insufficient
-- ...

INSERT INTO transactions (description, created_by)
VALUES ('Payout to merchant', 'job-4271') RETURNING id;

INSERT INTO postings (transaction_id, account_id, side, amount_minor, currency, seq)
VALUES
    (:txn_id, (SELECT id FROM accounts WHERE code='cash:usd'),     'debit',  1000, 'USD',
        next_account_seq('cash:usd')),
    (:txn_id, (SELECT id FROM accounts WHERE code='fees:usd'),     'credit',   25, 'USD',
        next_account_seq('fees:usd')),
    (:txn_id, (SELECT id FROM accounts WHERE code='merchant:usd'), 'credit',  975, 'USD',
        next_account_seq('merchant:usd'));

COMMIT;
```

The deterministic lock order is what stops two concurrent transfers from forming a deadlock cycle. A and B both want `cash:usd` and `merchant:usd`; if A locks in the order `cash, merchant` and B locks in the order `cash, merchant` too, one waits. The moment you let code lock in arbitrary order, you will see deadlocks in production within hours.

For a high-throughput, multi-region deployment, you typically want **per-account serialization**, which is exactly what [CockroachDB and Spanner](https://www.cockroachlabs.com/docs/v23.1/architecture/transaction-layer.html) give you. The idea: hash the account ID into a range, and the database serializes all writes that touch the same range. Your application code does not need to think about locks at all, but the schema-level invariants still apply.

## Append-Only Auditability

A ledger that lets you `UPDATE` or `DELETE` a posting is not a ledger — it is a mutable log that someone will edit. The only safe primitive is **insert with a timestamp**, and every state change is a new row.

Two patterns combine to give you full reconstruction:

1. **Postings table is append-only.** Revoke `UPDATE` and `DELETE` on the role your application runs as. Corrections are new, reversing transactions that reference the originals. This is how real accounting systems handle errors — never edit, always reverse.
2. **A separate audit log captures intent.** The application writes a row to an `events` table *before* it writes the transaction, with the business meaning ("user requested withdrawal of $10 from account X"). The transaction and its postings are the *result*; the event is the *reason*.

```sql
CREATE TABLE events (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor         TEXT NOT NULL,
    action        TEXT NOT NULL,
    subject_type  TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    payload       JSONB NOT NULL,
    transaction_id UUID REFERENCES transactions(id)
);
```

With postings immutable and events captured up front, you can answer every audit question:

- **What did the balance of account X look like at time T?** Replay postings up to T.
- **Why was this transaction created?** Look up the event by `transaction_id`.
- **Who saw PII about this user?** That goes in a separate access log, but the same pattern applies.

This is essentially [event sourcing](https://martinfowler.com/eaaDev/EventSourcing.html) applied to finance, and it is the approach that lets you produce a T+1 reconciliation report in minutes instead of days.

## Patterns in Production: Stripe, Modern Treasury, and Block

Most teams do not start from scratch. They either buy a ledger-as-a-service or build on top of Postgres with the patterns above. A few production reference points are worth understanding.

[Stripe's ledger](https://stripe.com/blog/ledgers-the-awesome-power-of-double-entry-accounting) is the canonical example of a double-entry system serving millions of merchants. Stripe's public engineering posts describe how each charge creates a balanced group of postings across accounts like `available`, `pending`, and `fees`, and how the ledger is the source of truth that downstream systems (payouts, reporting, tax) read from.

[Modern Treasury](https://www.moderntreasury.com/journal) publishes a journal with deep dives on money movement, including how they model multi-leg transfers and the operational realities of reversing a posted transaction. Their pattern is similar: immutable postings, virtual accounts per counterparty, and an event log that captures the business intent.

[Block's Cash App](https://engineering.block.xyz/blog) has written about running ledgers at very high QPS, including the use of **per-account sequence numbers** (the `seq` column above) to allow out-of-order replication without violating monotonicity. The `seq` is what lets you reconcile replicas and detect gaps after a failover.

A common production optimization worth mentioning: **don't compute balances on demand.** Materialize them. A `balances` table keyed by `(account_id, currency)` updated by the same trigger that enforces balance is what keeps reads fast. Rebuilding from postings is still the source of truth — it is what your nightly reconciliation job does — but the hot read path hits a single row.

## Reversals, Idempotency, and Operational Concerns

Three things every real ledger needs to handle, and which your schema should not have to be retrofitted to support.

**Idempotency.** A retried network call must not produce a double charge. The standard fix is an `idempotency_key` column on `transactions` (or on the inbound request that produces the transaction) with a unique constraint. If the request has been seen, return the original transaction id; otherwise create a new one. Stripe's idempotency post is a good reference, and the [Idempotency-Key HTTP draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/) is now widely supported in clients.

**Reversals.** Never `DELETE` or `UPDATE` a posting. A reversal is a new transaction whose postings mirror the original with flipped signs. The original `transaction_id` is stored in the metadata of the reversing transaction, forming a chain that auditors can follow. If you need a "void" semantic (cancelling something that hasn't yet settled), gate it on a status column rather than mutating the postings.

**Timezones and posting dates.** `posted_at` is the only timestamp that matters for the ledger. Business dates (the day the transaction "belongs to" for accounting periods) should be a separate column, and you should be very explicit about whether you let backdated postings be created. The safest rule is: backdating is allowed up to N days, and only by a privileged role. This is described well in the [Stripe engineering post on money movement](https://stripe.com/docs/connect/account-balances).

## Reconciliation: How You Know the Ledger Is Right

A ledger is only as trustworthy as the process that proves it. Reconciliation is that process. At minimum you need three:

1. **Internal trial balance.** Every account's debit total minus credit total equals its current balance. This is a one-line SQL query over the postings table and it must always return zero drift.
2. **External reconciliation.** Match ledger balances against the source-of-truth systems (bank statements, payment processor reports, custody balances). Any difference is itself a posting once the cause is found.
3. **Hash chain integrity.** A common hardening is to store a hash of each posting that includes the previous posting's hash for the same account. If anyone ever tampers with the table, the chain breaks and you can detect it. This is overkill for most teams but standard in regulated crypto ledgers.

Reconciliation should be **continuous, not periodic.** If you only reconcile at month-end, you have a month of unknown drift. A small streaming job that ingests postings and verifies invariants as they arrive will catch bugs in days, not months.

## Key Takeaways

- **Store money as `BIGINT` minor units.** Never floats. Never decimals-as-strings in application code.
- **Enforce the double-entry invariant in the database** with a deferred trigger, not in the application. The schema is the last line of defense.
- **Lock account rows in a deterministic order** to prevent deadlocks, and re-validate balances under the lock.
- **Make postings append-only.** Corrections are reversing transactions, not edits. This is what makes the audit trail real.
- **Capture business intent in an events table** alongside the postings, so auditors can answer "why" as well as "what."
- **Reconcile continuously**, not at month-end. The ledger is only correct if you keep proving it.

## Further Reading

- [PostgreSQL Trigger Documentation](https://www.postgresql.org/docs/current/triggers.html)
- [CockroachDB Transaction Layer Architecture](https://www.cockroachlabs.com/docs/v23.1/architecture/transaction-layer.html)
- [Stripe Ledger: The Awesome Power of Double-Entry Accounting](https://stripe.com/blog/ledgers-the-awesome-power-of-double-entry-accounting)
- [Martin Fowler on Event Sourcing](https://martinfowler.com/eaaDev/EventSourcing.html)
- [Modern Treasury Journal on Money Movement](https://www.moderntreasury.com/journal)
- [Idempotency-Key HTTP Header Draft](https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/)