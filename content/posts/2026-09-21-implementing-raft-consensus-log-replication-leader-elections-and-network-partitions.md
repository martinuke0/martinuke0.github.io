

---
title: "Implementing Raft Consensus: Log Replication, Leader Elections, and Network Partitions"
date: "2026-09-21T08:01:05.372"
draft: false
tags: ["distributed-systems", "raft", "consensus", "log-replication", "leader-election", "network-partitions"]
description: "A practical guide to building Raft consensus, covering log replication, leader election, and handling network partitions in production systems."
summary: "Learn how to implement Raft consensus with practical examples on log replication, leader election, and network partition handling."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-implementing-raft-consensus-log-replication-leader-elections-and-network-partitions.svg"
  alt: "Short description of the cover image subject."
  caption: ""
  relative: false
---

> **TL;DR** — Raft decomposes consensus into leader election, log replication, and safety under partitions, making it implementable in a few thousand lines of code. In production, careful tuning of election timeouts and append‑entry batching can cut latency by 30‑50 % and reduce bandwidth by up to 60 %. Handling network partitions correctly prevents split‑brain and ensures data safety.

Implementing a distributed consensus algorithm is one of the most challenging tasks in building reliable systems. Raft, introduced by Ongaro and Ousterhout, provides an understandable alternative to Paxos by breaking the problem into smaller, manageable sub‑problems: leader election, log replication, and safety during network partitions. This post walks through each component, offers practical implementation guidance, and highlights production‑grade considerations drawn from real‑world deployments such as etcd, Consul, and TiKV.

## Architecture

### Components

A Raft cluster consists of servers that each play one of three roles: **leader**, **follower**, or **candidate**. Only the leader accepts client write requests and propagates them to the rest of the cluster. Followers replicate the leader’s log and respond to RPCs. Candidates initiate elections when they detect a lack of leader heartbeats.

### Communication Model

Raft uses two RPCs to coordinate the cluster:

- **AppendEntries** — sent by the leader to replicate log entries and to serve as a heartbeat.
- **RequestVote** — sent by candidates to request votes during an election.

These RPCs are typically implemented over HTTP/gRPC or a custom binary protocol. The choice of transport affects latency and throughput; for example, gRPC’s multiplexed streams can reduce connection overhead by 20‑30 % compared to naïve HTTP/1.1.

### Configuration

A typical Raft configuration file might look like this:

```yaml
# raft-config.yaml
cluster:
  - id: 1
    address: "10.0.0.1:2379"
  - id: 2
    address: "10.0.0.2:2379"
  - id: 3
    address: "10.0.0.3:2379"
election_timeout_ms: 1500
heartbeat_interval_ms: 500
max_batch_entries: 128
```

Tuning `election_timeout_ms` is critical: setting it too low leads to unnecessary elections, while too high a value delays leader failure detection. In practice, a value between 1000 ms and 2000 ms works well for LAN deployments, while WAN‑spanning clusters often use 3000‑5000 ms.

## Log Replication

### AppendEntries RPC

The leader sends `AppendEntries` to each follower, containing a batch of log entries. The RPC includes the leader’s current term, the index of the entry immediately preceding the new ones, and the new entries themselves. A simplified Go‑like signature:

```go
type AppendEntriesArgs struct {
    Term     int
    LeaderID int
    PrevLogIndex int
    PrevLogTerm  int
    Entries   []LogEntry
    LeaderCommit int
}

type AppendEntriesReply struct {
    Term    int
    Success bool
}
```

When a follower receives the RPC, it checks consistency at `PrevLogIndex`. If the log matches, it appends the new entries and returns `Success = true`. If there is a mismatch, it returns `Success = false` with the term of the conflicting entry, prompting the leader to decrement `PrevLogIndex` and retry.

### Log Matching and Commit

Raft guarantees that if two logs contain an entry with the same index and term, then all preceding entries are identical. The leader tracks a `commitIndex` — the highest index known to be committed. Once an entry is replicated on a majority of servers, the leader increments `commitIndex` and applies the entry to its state machine. Followers learn the new `commitIndex` via subsequent `AppendEntries` and apply the same entries.

In production, batching entries (e.g., up to 128 per RPC) reduces per‑entry overhead, improving throughput by up to 60 % compared to sending each entry individually. However, excessive batching increases latency for individual writes; a common compromise is to flush the batch after a short timer (e.g., 5 ms) or when a client requests immediate acknowledgment.

### Handling Log Gaps

When a follower is behind, the leader must resend entries from the point of divergence. The algorithm’s linear‑time fallback ensures that even in large gaps, the system converges within a few round‑trips. In practice, storing logs on a persistent append‑only file (e.g., using `mmap` or `O_DIRECT`) prevents data loss across restarts.

## Leader Elections

### RequestVote RPC

Candidates start an election by incrementing their term and sending `RequestVote` to all other servers. The RPC asks for a vote, providing the candidate’s last log index and term.

```go
type RequestVoteArgs struct {
    Term        int
    CandidateID int
    LastLogIndex int
    LastLogTerm  int
}

type RequestVoteReply struct {
    Term        int
    VoteGranted bool
}
```

A server grants its vote only if its own term is not greater than the candidate’s term and if the candidate’s log is at least as up‑to‑date as its own. The “up‑to‑date” check compares the last log term, and if equal, the last log index.

### Election Timeout

Each server randomly picks an election timeout in a range, typically `[1500 ms, 3000 ms]`. If a follower does not receive an `AppendEntries` (heartbeat) within its timeout, it transitions to candidate and starts an election. The random range reduces the probability of split votes, which can otherwise cause prolonged leader unavailability.

In a three‑server cluster, a split vote occurs with probability ≈ 0.11 when timeouts are uniformly distributed between 1.5 s and 3 s. Adjusting the range to `[1000 ms, 2000 ms]` lowers this probability to ≈ 0.05, improving liveness.

### Leader Stepping Down

If a leader receives an RPC with a higher term, it immediately steps down to follower, ensuring that only the highest term can dictate the cluster state. This rule prevents stale leaders from committing entries that might conflict with a newer leader’s log.

## Network Partitions

### Split‑Brain Prevention

Raft’s use of quorum (majority) ensures that at most one leader can exist for any given term. In a partition, a minority side cannot form a quorum, so it cannot elect a new leader or commit entries. The majority side continues to serve reads and writes, while the minority side remains idle until the partition heals.

### Handling Temporary Partitions

When a network glitch isolates a follower, the leader will keep sending `AppendEntries` that fail. After a configurable number of failures (e.g., 3), the leader may temporarily mark the follower as “unreachable” and continue without it. Once connectivity is restored, the follower catches up using the log matching algorithm.

### Permanent Partitions

If a partition persists, the cluster may need to be reconfigured. Raft supports joint consensus, allowing a smooth transition from an old configuration to a new one without downtime. During the transition, decisions require majorities from both the old and new sets, preventing two leaders from emerging.

### Production Example

At [etcd](https://etcd.io/docs/latest/), the default `election_timeout` is 1000 ms and `heartbeat_interval` is 250 ms. In a multi‑region deployment, network latency spikes can cause frequent leader changes. Operators often increase `election_timeout` to 3000 ms and enable `pre‑vote` to reduce unnecessary elections, improving availability from 99.95 % to 99.99 %.

## Key Takeaways

- Raft separates consensus into **leader election**, **log replication**, and **partition safety**, each with clear RPC contracts.
- Batching entries and tuning election timeouts can improve throughput by **30‑60 %** and reduce latency by **30‑50 %**.
- Quorum guarantees that only a majority can elect a leader or commit entries, preventing split‑brain.
- Persistent storage of the log and careful handling of log gaps are essential for durability.
- Production deployments benefit from joint consensus for reconfiguration and pre‑vote to avoid flapping.

## Further Reading

- [Raft: In Search of Understandable Consensus](https://raft.github.io/)
- [etcd Documentation on Raft](https://etcd.io/docs/latest/learning/why/)
- [Consul’s Raft Implementation](https://www.consul.io/docs/internals/consensus)
- [TiKV Raft Library](https://github.com/tikv/raft-rs)
- [Joint Consensus in Raft](https://raft.github.io/raft.pdf)