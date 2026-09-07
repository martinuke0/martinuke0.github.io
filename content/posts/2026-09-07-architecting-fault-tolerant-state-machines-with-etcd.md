---
title: "Architecting Fault-Tolerant State Machines with etcd's Raft: Lease Semantics and Split-Brain Recovery"
date: "2026-09-07T17:04:55.040"
draft: false
tags: ["raft", "etcd", "distributed-systems", "consensus", "kubernetes"]
description: "How etcd's Raft implementation uses leader leases and quorum logic to prevent split-brain, with patterns for production state machine design."
summary: "A practitioner's deep dive into how etcd's Raft implementation prevents split-brain through leader leases, quorum checks, and recovery protocols — with patterns for building fault-tolerant state machines on top."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-architecting-fault-tolerant-state-machines-with-etcd.svg"
  alt: "Diagram of a Raft cluster with one leader, two followers, and lease timing arrows."
  caption: ""
  relative: false
---

> **TL;DR** — etcd's Raft layer uses a *leader lease* plus a strict quorum of `floor(N/2)+1` votes to ensure only one leader can ever commit a log entry per term. Split-brain isn't prevented by the lease alone — it's prevented by the combination of lease-bounded commits, persistent term counters, and a recovery protocol where a stale leader steps down the moment it discovers a higher term. Get any of those three wrong, and your state machine will silently fork.

If you've ever watched a Kubernetes API server refuse writes during a brief network partition, or watched `etcdctl endpoint status` flip its leader mid-incident, you've already seen etcd's Raft implementation working exactly as designed. Most engineers treat etcd as a "reliable key-value store" and never look under the hood. That's a mistake — the way etcd handles leases, leadership transfer, and split-brain recovery is a masterclass in consensus engineering, and the patterns transfer directly to any state machine you build on top.

This post walks through the architecture: how Raft's lease semantics actually work in etcd's Go implementation, where the failure modes hide, and how to design a state machine that survives the messy realities of production deployments.

## Why Lease Semantics Matter More Than You Think

Raft's core safety property is **election safety**: at most one leader per term. But there's a subtler property that matters for state machines: **a leader must be sure no other leader exists at the same term** before it commits an entry. This is where leases come in.

In etcd's implementation (which lives in `go.etcd.io/raft`), a leader's authority over a term is bounded by a *lease interval*, typically set equal to the election timeout. The leader only commits log entries if it can prove it still holds the quorum from the previous election round. Specifically, the leader tracks the time of the last successful heart from a majority of followers. If that window expires, the leader *voluntarily* stops committing — it doesn't wait for the election timeout to fire.

This is the first line of defense against split-brain. Without it, a leader could commit entries on the wrong side of a network partition and overwrite a new leader's commits once connectivity returns. With it, the leader pauses, steps down, and rejoins the cluster as a follower.

The critical insight: **leases are a probabilistic guarantee, not an absolute one**. They rely on bounded clock skew between the leader and the quorum. etcd assumes a maximum skew of roughly `election_timeout / 2`, which is why the default `election-timeout` is set to 1000ms — large enough to tolerate realistic NTP drift while still being shorter than typical failure detection windows.

## The Raft Log: Where State Lives

etcd's Raft is a *log-based* consensus protocol. Every state machine transition is a log entry, replicated to a quorum before it's applied. The log entry has a fixed structure:

```text
type Entry struct {
    Term  uint64
    Index uint64
    Type  EntryType     // NormalEntry, ConfChangeAddNode, etc.
    Data  []byte        // serialized proposal
}
```

A state machine consuming this log sees a strictly ordered, gap-free sequence of entries up to a known `commitIndex`. This is the contract that makes state machine replication tractable: you only need to think about "what does entry N do?" because you'll never see N+1 before N.

In etcd v3, the data field is an internal `pb.Request` proto. For your own state machine, you'll serialize your own command type — a workflow transition, a feature flag toggle, a Kubernetes-style object update.

## Patterns in Production: Building a State Machine on Top

Let's move from theory to a concrete pattern. Suppose you're building a workflow engine where each task has states (`Pending → Running → Succeeded`/`Failed`). You want HA across three availability zones. You choose etcd as the consensus layer.

The pattern looks like this:

```go
type WorkflowCommand struct {
    WorkflowID string
    FromState  State
    ToState    State
    Payload    []byte
}

func (s *WorkflowSM) Apply(entry pb.Entry) (interface{}, error) {
    var cmd WorkflowCommand
    if err := json.Unmarshal(entry.Data, &cmd); err != nil {
        return nil, err
    }

    // Idempotency check: command keyed by (workflow_id, entry.index)
    if s.applied[entry.Index] {
        return nil, nil
    }

    wf := s.workflows[cmd.WorkflowID]
    if !wf.CanTransition(cmd.FromState, cmd.ToState) {
        return nil, fmt.Errorf("illegal transition")
    }
    wf.State = cmd.ToState
    wf.History = append(wf.History, cmd)
    s.workflows[cmd.WorkflowID] = wf
    s.applied[entry.Index] = true
    return nil, nil
}
```

Three production-grade details to notice:

1. **The state machine is keyed by `entry.Index`, not by command content.** This is the only way to guarantee idempotency if a leader retries an entry after a network blip. The Raft library guarantees each entry is committed at most once, but application-level retries during proposal can still cause duplicates at the proposal stage.

2. **Snapshots must be paired with the applied index.** When the log grows past a threshold (default 100MB or 100k entries in etcd), the leader triggers a snapshot. Your state machine must persist `(appliedIndex, appliedTerm, snapshot)` atomically — otherwise a restart could replay entries that were already applied, or skip ones that weren't.

3. **The `CanTransition` check is the safety net.** Raft guarantees linearizability, not business-logic correctness. If your state machine can transition from `Succeeded` back to `Running`, Raft won't stop you — it'll happily replicate the nonsensical command.

etcd's own v3 store uses an MVCC tree backed by a BoltDB file, and each `Txn` is a single Raft entry. That's why `etcdctl put foo bar` is linearizable: the write is a single log entry, committed at index N, and every observer sees it at exactly index N. The [etcd v3 API design](https://etcd.io/docs/v3.5/learning/api/) is worth studying because it deliberately keeps each transaction to a single log entry — multi-key transactions are batched but still atomic at the log level.

## Split-Brain: The Failure Modes You Don't See

Split-brain is what happens when two nodes both believe they're leader and both commit entries. Raft's design *prevents* it under nominal conditions, but real systems fail in interesting ways. Here are the three failure modes that actually bite in production.

### 1. Clock Skew Beyond the Lease Window

If the leader's clock jumps forward (NTP correction, VM resume from suspend), the leader may believe it still holds the quorum even though followers' clocks say the election has timed out. The leader commits entries, then loses leadership moments later.

Mitigation:
- Run etcd nodes on hosts with disciplined clock sources (chrony with multiple upstream NTP servers).
- Set `election-timeout` to at least 10x your expected worst-case clock skew.
- Monitor `etcd_debug_server_lease_revoke_total_v2` — a non-zero value means leases are being invalidated faster than expected.

### 2. Network Partition With Quorum Preservation

This is the *correct* case: a partition splits the cluster 2-1. The majority side continues; the minority side stops committing. When the partition heals, the minority node rejoins as a follower and rolls back any uncommitted entries.

The rollback is handled by the `MsgApp` flow: when the old leader receives an append with a higher term, it sets its term, becomes a follower, and truncates its log back to the last index the new leader acknowledges. There's no ambiguity — the higher term wins, always.

### 3. Asymmetric Network Partitions (The Dangerous One)

An asymmetric partition is when node A can reach node B, but B cannot reach A. Both sides believe they're alive. If A is the leader, B (a follower) times out, starts an election, wins (because A and C form a quorum), and becomes the new leader. A, meanwhile, has not received any indication that an election occurred.

This is where the lease *fails* in theory but Raft's other defenses kick in:

- A's heartbeat timer eventually notices the dropped heartbeats from B (since A's sends are succeeding but replies aren't — wait, actually in Raft, heartbeats are one-way).
- The next time A tries to commit, it requires a quorum acknowledgment. If A can still reach C, it commits. If it can't, it steps down.

The asymmetry is broken by A noticing that it can no longer achieve quorum for *appends*. The lease protects against a leader who has lost contact with *all* followers but doesn't know it. Asymmetric partitions produce two cases:
- Leader loses quorum → leader steps down.
- Follower loses leader → starts election, wins, new leader's higher term forces old leader down.

There's no third case where two leaders commit in the same term. That's the invariant Raft gives you, and it's what the [Raft paper's Figure 2](https://raft.github.io/raft.pdf) State Machine Safety property formally guarantees.

## Lease Recovery: The Protocol That Brings the Cluster Back

When a partition heals, etcd doesn't have a special "recovery" code path — recovery is just the normal Raft protocol running again. But there are subtleties worth understanding.

**Term propagation is the recovery mechanism.** A stale leader rejoining the cluster immediately learns about the higher term from the first `MsgApp` it receives from the current leader. It sets its term, drops any uncommitted entries it had buffered, and becomes a follower. This happens in microseconds — there's no human intervention, no admin command.

**Uncommitted entries from the stale leader are silently dropped.** This is correct: if the entries weren't replicated to a quorum, they were never committed, and per Raft's safety properties, no state machine ever applied them. The [etcd maintainers' guide on recovery](https://etcd.io/docs/v3.5/op-guide/recovery/) documents this explicitly.

**Snapshot transfer handles divergent state.** If the stale leader's log has been truncated past where the new leader's snapshot starts, the stale leader installs the snapshot and continues from there. This is why snapshot frequency matters — the longer between snapshots, the more work to recover a badly behind node.

For your own state machine, this means: design your snapshot format to be **forward-compatible**. If you ship v2 of your command schema but a follower is on v1, the snapshot must deserialize in a way that lets v1 nodes still function (or force a controlled upgrade). etcd uses a feature-gated serialization layer for exactly this reason.

## Operational Guardrails

A few rules from running etcd in production that aren't in the textbook:

1. **Always deploy odd numbers of nodes (3 or 5).** Three nodes tolerate one failure; five tolerate two. With four nodes, you have the worst of both worlds: same fault tolerance as three, but more network traffic per commit.

2. **Use `--initial-cluster-token` to prevent split-cluster incidents.** If you accidentally point two clusters at the same peer URLs (different regions, same network), they'll merge into one cluster with corrupted state. The token makes peer URLs unique to a logical cluster.

3. **Separate etcd traffic from application traffic.** Run etcd on a dedicated network interface or VPC. Every microsecond of latency on the Raft heartbeat path is latency on every write your API server performs. Production deployments typically see 2-5ms median commit latency on dedicated networks; co-tenanted setups can see 20-50ms.

4. **Watch `etcd_server_leader_changes_seen_total_v2`.** This metric counts leadership changes. A steady trickle is normal during rolling restarts. A flood means your network or hosts are unstable — investigate before you hit a real outage.

5. **Test failure injection regularly.** Use [etcd's built-in failure testing framework](https://github.com/etcd-io/etcd/tree/main/tests/functional) or tools like `etcdctl --endpoints` chaos scripts. The clusters that survive real outages are the ones where engineers have practiced the recovery on a Tuesday afternoon.

## Key Takeaways

- etcd's Raft uses a leader **lease** bounded by the election timeout to prevent a leader from committing after it's lost contact with a quorum. The lease is probabilistic — it assumes bounded clock skew.
- **Split-brain is prevented by the combination of lease-bounded commits, persistent term counters, and automatic step-down on higher-term contact.** No single mechanism is sufficient.
- Your **state machine must be idempotent** keyed by `entry.Index`, must produce **forward-compatible snapshots**, and must enforce **application-level invariants** that Raft doesn't know about.
- **Asymmetric partitions resolve safely** because the next failed commit attempt forces the old leader to step down. There's no third case where two leaders commit.
- **Operational discipline matters more than algorithm tweaks.** Odd node counts, dedicated networks, monitored leadership changes, and regular failure drills are what separate a Raft cluster that survives five years from one that loses data in five months.

## Further Reading

- [The Raft Consensus Algorithm (Ongaro & Ousterhout, 2014)](https://raft.github.io/raft.pdf) — the original paper. Figure 2 is the single most important diagram in distributed systems.
- [etcd's Raft library documentation](https://pkg.go.dev/go.etcd.io/raft/v3) — the actual Go implementation, well-commented and used as the reference for Raft in Go.
- [etcd recovery guide](https://etcd.io/docs/v3.5/op-guide/recovery/) — practical procedures for handling the messier failure modes.
- [Finding bugs in etcd's Raft implementation (CMU, 2020)](https://www.cs.cmu.edu/~rdonadev/papers/raft-bugs.pdf) — a sobering read on the gap between the paper and reality.
- [Jepsen analysis of etcd](https://jepsen.io/analyses/etcd-3.4.3) — independent verification of etcd's safety claims under partition.
- [Designing Data-Intensive Applications, Chapter 9 (Consistency and Consensus)](https://dataintensive.net/) — Kleppmann's treatment of leases and fencing tokens as a complement to Raft.