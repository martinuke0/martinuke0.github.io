---
title: "Architecting FoundationDB's Distributed Transaction Layer: Logs, Sequencers, and Conflict Resolution"
date: "2026-09-11T08:00:43.492"
draft: false
tags: ["distributed systems", "foundationdb", "transactions", "consensus", "architecture"]
description: "A deep dive into FoundationDB's distributed transaction layer, examining how its sequencer, commit proxy, and conflict resolution mechanisms achieve serializable isolation across thousands of nodes."
summary: "FoundationDB's transaction layer achieves serializable isolation through a carefully orchestrated dance of logs, sequencers, and conflict resolution. This post breaks down the architecture, the role of each component, and how the system guarantees correctness under failure."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-architecting-foundationdb.svg"
  alt: "Diagram of FoundationDB's distributed transaction architecture showing sequencers, commit proxies, and logs"
  caption: ""
  relative: false
---

> **TL;DR** — FoundationDB's transaction layer achieves serializable isolation by assigning monotonically increasing sequence numbers through a distributed sequencer, batching writes into a commit log, and resolving conflicts via a deterministic read-version check. The entire correctness argument rests on the log providing total ordering and the sequencer guaranteeing that no two concurrent transactions receive the same sequence number.

FoundationDB is a distributed key-value store that exposes a powerful multi-key transactional API — and it does so without relying on a single centralized lock manager or a heavyweight concurrency control protocol. Instead, the transaction layer achieves serializable isolation through a layered architecture composed of a sequencer, a commit proxy, a log system, and a conflict resolver. Understanding how these pieces fit together reveals one of the most elegant solutions to distributed concurrency control in production systems today.

The design choices made by the FoundationDB team were driven by a single hard constraint: the system must provide strict serializability, not eventual consistency, not snapshot isolation with write conflicts. Every component in the transaction layer exists to serve that guarantee. Let's trace the path of a transaction from client invocation to durable commit.

## The Transaction Lifecycle at a Glance

When a client submits a transaction to FoundationDB, it passes through four distinct phases:

1. **Read** — The client reads key-value pairs from storage servers using a read version.
2. **Conflict Check** — The client reports its read set and write set to the transaction system.
3. **Commit** — The transaction is assigned a sequence number and durably logged.
4. **Answer** — The client receives acknowledgment that the transaction committed.

Each phase involves specific interactions with the sequencer, commit proxy, and log servers. The beauty of the architecture is that no single component bears the full burden of correctness — the guarantee emerges from their composition.

## The Sequencer: Source of Total Order

At the heart of FoundationDB's transaction layer sits the **sequencer**, a component responsible for assigning monotonically increasing sequence numbers to transactions. This is not a trivial role — the sequence number serves as the transaction's timestamp, its position in the global ordering, and the mechanism by which conflicts are ultimately resolved.

The sequencer operates as a replicated state machine. It is implemented using the Raft consensus protocol, meaning there is a primary sequencer and a group of replicas. When a transaction needs a sequence number, the commit proxy forwards the request to the sequencer leader, which appends the request to its Raft log and, once committed, assigns the next sequence number.

```
Client → Commit Proxy → Sequencer (Raft Leader)
                         ├── Appends request to Raft log
                         ├── Replicates to followers
                         └── Assigns sequence number N
```

The critical property here is **total ordering**. Because the sequencer uses Raft, all nodes in the cluster agree on the exact order in which sequence numbers are assigned. This means that even if two clients submit transactions simultaneously, one of them will always receive a lower sequence number than the other. That ordering becomes the basis for conflict resolution.

The sequencer also manages the **commit proxy leader election**. The commit proxy is a stateless component that acts as a front-end to the sequencer and log. Multiple commit proxies can exist, and they coordinate through the sequencer to ensure that only one acts as the leader at a time. If the leader fails, the sequencer triggers an election, and a new commit proxy takes over within seconds.

## The Commit Proxy: Orchestrating the Flow

The **commit proxy** is the component that mediates between clients and the rest of the transaction layer. It is stateless and horizontally scalable — meaning you can run many commit proxies to handle client load. But despite being stateless, the commit proxy plays a crucial role in the protocol.

When a client wants to commit a transaction, it sends a `CommitTransactionRequest` to the commit proxy. The proxy then:

1. Contacts the sequencer to obtain a sequence number for the transaction.
2. Writes the transaction's writeset to the **log** (more on this shortly).
3. Returns a response to the client indicating success or failure.

The commit proxy is also responsible for handling **read version requests**. When a client wants to read data, it asks the commit proxy for the current read version. The proxy queries the sequencer for the latest committed sequence number and returns that as the read version. This ensures that every read sees a consistent snapshot of the database.

```python
# Simplified commit proxy logic
def handle_commit_request(client_txn):
    # Step 1: Get a sequence number from the sequencer
    seq_num = sequencer.get_next_sequence()
    
    # Step 2: Write the transaction to the log
    log.append(TransactionRecord(
        sequence_number=seq_num,
        writeset=client_txn.writeset,
        readset=client_txn.readset
    ))
    
    # Step 3: Return success to client
    return CommitResponse(status="committed", sequence_number=seq_num)
```

The commit proxy's statelessness is a deliberate architectural choice. It means that if a commit proxy crashes, any other commit proxy can pick up the work without data loss or protocol violation. The state lives in the sequencer (sequence numbers) and the log (transaction records).

## The Log: Durable Ordering Guarantees

The **log** is the durable store that records every committed transaction in sequence number order. It is implemented as a replicated log using Raft, similar to the sequencer, but with a different purpose: the log provides durability and ordering for the actual transaction data.

Each entry in the log contains:

- The **sequence number** assigned by the sequencer.
- The **writeset** — the keys the transaction intends to write and their new values.
- The **readset** — the keys the transaction read, along with the read versions.
- The **write timestamp** — the sequence number at which the transaction committed.

The log servers replicate entries using Raft, ensuring that once a transaction is logged, it is durable even if individual log servers fail. The log is the single source of truth for what has been committed. Storage servers read from the log to materialize the key-value state that clients eventually read.

The interaction between the log and the storage servers is worth understanding. Storage servers periodically take snapshots of the key-value state and apply changes from the log. When a client reads a key, it can read from any storage server, which serves the most recent snapshot plus any log entries applied since the snapshot was taken.

```
Log Servers (Raft) ──→ Storage Servers ──→ Clients (reads)
  │
  └── Committed transactions in sequence order
```

This separation of concerns is important: the log handles ordering and durability, while the storage servers handle serving reads efficiently. A client reading from a storage server does not need to contact the log directly — it simply reads the latest materialized state at the appropriate read version.

## Conflict Resolution: The Deterministic Check

FoundationDB's conflict resolution model is what makes it fundamentally different from systems that use locks or optimistic concurrency control with arbitrary validation. The conflict check is **deterministic** and happens **before** the transaction commits.

Every transaction declares two sets:

- **Read set**: The keys read during the transaction, along with the read version.
- **Write set**: The keys written during the transaction, along with the intended new values.

When the commit proxy processes a commit request, it checks whether the transaction's read set overlaps with any previously committed transaction's write set that has a sequence number between the transaction's read version and its own sequence number. If there is an overlap, the transaction is aborted.

This is the formal condition for serializability:

> A transaction T with read set R(T) and sequence number N(T) is valid if and only if no transaction T' with write set W(T') and sequence number N(T') where N(T') is between the read version of T and N(T) has W(T') ∩ R(T) ≠ ∅.

In plain terms: if any key you read was written by a transaction that committed after you started reading but before you committed, your transaction is aborted. This prevents the "read skew" anomaly and guarantees serializability.

```
Transaction T1: reads {k1, k2}, writes {k3}
Transaction T2: reads {k3}, writes {k4}

If T1 commits at seq 10, and T2 reads k3 at read version 10,
then T2 checks: was k3 written between version 10 and T2's seq?
If yes → abort T2. If no → commit T2.
```

The conflict check is performed by the commit proxy, which has access to the log. The proxy can efficiently determine whether any conflicting writes have been committed by scanning the log for overlapping keys. In practice, this is optimized using interval trees and other data structures that allow fast range queries over the key space.

## Patterns in Production: How This Architecture Scales

The FoundationDB transaction layer exemplifies several patterns that are critical for building scalable distributed systems:

**Separation of sequencing from logging.** The sequencer assigns order; the log records data. This separation allows each component to be optimized independently. The sequencer needs only to maintain a small Raft group for ordering, while the log can be scaled across many nodes for throughput.

**Stateless front-ends.** The commit proxy is stateless, which means it can be load-balanced arbitrarily. There is no sticky session requirement, no state to replicate, and no failover protocol for the proxy itself. This is a significant operational advantage — adding capacity means spinning up more commit proxies.

**Deterministic conflict resolution.** By checking conflicts before commit and using a total order from the sequencer, FoundationDB avoids the need for distributed locks, two-phase commit, or any blocking protocol. The protocol is wait-free from the client's perspective: either the transaction commits or it aborts, with no indefinite waiting.

**Snapshot isolation via read versions.** The read version mechanism gives each client a consistent snapshot of the database at the moment it began reading. This is not an approximation — it is a precise guarantee backed by the sequencer's total order. Storage servers serve reads from materialized snapshots, so read throughput is not bottlenecked by the log or sequencer.

## Failure Modes and Recovery

No distributed system article is complete without examining what happens when things break. FoundationDB's transaction layer is designed with explicit failure modes in mind.

**Sequencer failure.** If the sequencer leader fails, Raft elects a new leader within seconds. In-flight transactions that haven't received a sequence number are retried by the client. Since the sequencer is the source of ordering, a new leader continues from where the old one left off — the Raft log ensures no sequence numbers are skipped or duplicated.

**Log server failure.** Log servers replicate using Raft, so the loss of a minority of log servers does not affect availability. If a majority fails, the log becomes unavailable, and no new transactions can commit. This is the same durability guarantee as any Raft-based system: you can lose f nodes out of 2f+1, but not more.

**Commit proxy failure.** Since commit proxies are stateless, their failure is transparent. Clients retry their requests to a different proxy. There is no state to recover and no protocol violation possible.

**Network partitions.** In a network partition, the side containing the sequencer and log majority continues to operate. The other side cannot commit new transactions because it cannot reach the sequencer or log. This is a deliberate trade-off: FoundationDB prioritizes consistency over availability during partitions, which is appropriate for a system that guarantees strict serializability.

## Key Takeaways

- FoundationDB achieves strict serializability through a sequencer that assigns total order via Raft, not through locks or timestamps from a centralized clock.
- The commit proxy is stateless and horizontally scalable, acting as an orchestration layer between clients and the sequencer/log.
- Conflict resolution is deterministic: a transaction is aborted if its read set overlaps with any committed write set that falls between its read version and its sequence number.
- The log provides durable, ordered recording of all committed transactions, serving as the single source of truth for storage servers.
- Separating sequencing from logging allows each subsystem to be independently optimized and scaled.
- Failure recovery is straightforward because the protocol is stateless at the front-end and relies on Raft's well-understood guarantees at the back-end.

## Further Reading

- [FoundationDB Architecture Document](https://apple.github.io/foundationdb/architecture.html) — The official architecture whitepaper that describes the transaction layer, storage layer, and cluster controller in exhaustive detail.
- [FoundationDB Record Layer Documentation](https://foundationdb.com/documentation.html) — Additional documentation covering the record layer built on top of the transaction API, including how conflicts are handled at the object level.
- [The Case for Strict Serializability](https://cmu.edu/~drh/papers/ser.pdf) — A seminal paper by Daniel J. Abadi et al. that formalizes the serializability guarantees FoundationDB provides and compares them against other isolation levels.
- [Raft Consensus Algorithm](https://raft.github.io/) — The consensus protocol underlying FoundationDB's sequencer and log replication, with interactive visualizations and formal correctness proofs.
- [FoundationDB on GitHub](https://github.com/apple/foundationdb) — The open-source implementation, including the transaction layer code, which is a valuable resource for understanding the protocol in practice.