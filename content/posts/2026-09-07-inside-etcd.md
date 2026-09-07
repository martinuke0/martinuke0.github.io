---
title: "Inside etcd's Raft Implementation: Lease-Based Leader Election and Read Consistency"
date: "2026-09-07T17:04:23.854"
draft: false
tags: ["etcd", "raft", "distributed-systems", "kubernetes", "consensus"]
description: "A deep dive into how etcd implements Raft consensus with lease-based leader election and linearizable reads, with patterns from production Kubernetes clusters."
summary: "How etcd uses Raft with lease-based leader election, read-index protocol, and a backend MVCC store to deliver strict consistency for Kubernetes and other control planes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-inside-etcd.svg"
  alt: "A stylized cluster of three nodes with one leader highlighted, representing etcd's Raft consensus."
  caption: ""
  relative: false
---

> **TL;DR** — etcd combines Raft consensus with two key tricks: a leader **lease** that eliminates the need for heartbeats on every read, and a **read-index** protocol that forces reads to confirm leadership via the quorum before returning data. Together these give Kubernetes clients **linearizable reads** without paying the latency cost of a full write quorum on every GET, while still tolerating minority failures.

If you've ever debugged a Kubernetes apiserver hanging on `etcdserver: request timed out`, you've already brushed against one of the most carefully engineered consensus stacks in the modern control-plane world. etcd isn't just a key-value store. Under the hood, it's a Raft-replicated state machine with a BoltDB-backed MVCC layer, wrapped in a gRPC API that powers every Kubernetes object you've ever created.

This post walks through the two pieces of etcd's design that make it feel both *fast* and *correct*: **lease-based leader election** and the **read-index protocol** for linearizable reads. We'll look at the actual code paths in [`etcd-io/raft`](https://github.com/etcd-io/raft) and [`etcd-io/etcd`](https://github.com/etcd-io/etcd), and we'll ground it in the production scenario most readers care about: a 3-node etcd cluster behind a Kubernetes control plane.

## Why etcd's consistency model matters

Kubernetes stores *the entire cluster state* in etcd: every Pod, Service, ConfigMap, Secret, and CRD. If two apiservers read etcd concurrently and one sees a Pod that doesn't exist for the other, you get scheduling races, split-brain controllers, and the kind of bugs that page people at 3 AM. To prevent this, Kubernetes requires **linearizable reads** — every read must reflect the latest committed write, as if there were a single, time-ordered log.

The naive way to achieve this is to send every read through Raft as a log entry. That's correct, but it pays the latency of a disk fsync plus a network round trip to a majority on *every* GET — untenable when controllers are doing hundreds of watches per second. etcd's actual design is more subtle, and it rests on two ideas.

## Lease-based leader election: how etcd skips heartbeats on reads

### The standard Raft leader election problem

In textbook Raft, a leader must convince followers it's still the leader before serving a read, because a network partition could have elected a new leader that the current leader doesn't know about. The classic fix is one of:

1. **Send every read through the log** — correct but slow.
2. **Round-trip a heartbeat** before the read — adds RTT to every GET.
3. **Use a leader lease** — assume leadership is valid for a bounded time window without an explicit check.

etcd chooses option 3, with carefully bounded assumptions.

### How the lease works

A follower grants a leader a **lease** when it accepts an `AppendEntries` RPC. The lease says, in effect: *"I will not vote for any other candidate until at least this election timeout has elapsed since I last heard from you."* If the leader keeps sending heartbeats faster than the election timeout, it maintains a quorum of leases indefinitely and can safely skip the heartbeat-on-read.

The relevant code lives in `etcd-io/raft/raft.go`. The election timer logic looks roughly like this:

```go
// pseudocode from etcd-io/raft
const (
    heartbeatInterval = 100 * time.Millisecond
    electionTimeout   = 1000 * time.Millisecond
)

func (r *raft) tickElection() {
    r.electionElapsed++
    if r.promotable() && r.pastElectionTimeout() {
        r.electionElapsed = 0
        r.Step(pb.Message{From: r.id, Type: pb.MsgHup})
    }
}
```

The leader, in turn, sends `MsgHeartbeat` on `heartbeatInterval`. As long as that interval is well below `electionTimeout`, the leader's lease stays fresh across a majority of followers. Concretely, in etcd's default tuning, heartbeats are ~100ms and the election timeout is ~1000ms — so a leader can assume validity for roughly 900ms after its last successful heartbeat to a quorum.

The mechanism is described in the [Raft thesis](https://raft.github.io/raft.pdf) (section 6.4, "Read-only operations") and in etcd's own [consensus docs](https://etcd.io/docs/v3.5/learning/design/).

### Why this is safe — and when it isn't

The lease is safe because of a simple invariant: if a leader still holds a quorum of leases, no new leader could have been elected, because an election requires votes from a majority, and a majority includes at least one follower whose lease hasn't expired. This is the same argument Consul uses, and it's formalized in the [Diego Ongaro Raft thesis](https://raft.github.io/raft.pdf) as the "lease-based reads" approach.

The lease **breaks down** under asymmetric partitions — a scenario where the old leader can still reach some clients but not enough followers to confirm leadership. etcd guards against this with an additional check on every read, which brings us to the second trick.

## The read-index protocol: confirming leadership on the read path

The lease alone is not enough. A leader could have just won an election but not yet replicated its first entry to a majority; if it serves reads immediately, those reads might miss recent writes from the previous leader. The **read-index protocol** solves this.

The flow, as implemented in `etcd-io/raft/raft.go`'s `ReadIndex` and the `(r *raft) Step` handler, is:

1. **Record the commit index at the moment the read arrives.** Call this `readIndex`.
2. **Confirm leadership** by sending a heartbeat round to a quorum and waiting for a majority of followers to acknowledge.
3. **Wait until the applied index ≥ `readIndex`.** This guarantees the read sees at least everything committed before it began.
4. **Return the value from the local state machine.**

```go
// conceptual sketch of read-index handling
func (r *raft) handleReadIndex(req pb.Message) {
    if r.state != StateLeader {
        return // followers forward reads to the leader
    }
    // 1. note the current commit index
    r.readIndex = append(r.readIndex, readIndexStatus{
        req:    req,
        index:  r.raftLog.committed,
    })
    // 2. confirm leadership by sending heartbeats
    r.sendHeartbeats()
}

func (r *raft) handleHeartbeatAck(msg pb.Message) {
    r.ackCount[msg.From]++
    if r.ackCount[msg.From]+1 >= r.quorum() {
        // quorum reached; reads up to r.commit are now safe
        r.notifyReadIndexReady()
    }
}
```

The crucial property: the read returns only after the leader has *proven* it's still the leader to a quorum *at the current time*, not at the time of the last heartbeat. Combined with the lease, this gives a bounded staleness window — at most one election timeout — without paying full heartbeat latency on every read.

You can see the production version of this in etcd's `applyReadIndex` and `ReadIndexNotify` channels, and the [etcd v3.5 design documentation](https://etcd.io/docs/v3.5/learning/design/) walks through it in section "Serving Read Requests".

## Serializable reads: the cheaper alternative for watch-heavy workloads

Not every etcd client needs linearizability. Kubernetes uses two read consistencies:

- **`linearizable`** (the default for most watches via the apiserver cache miss path)
- **`serializable`** (cheaper, used by some background reconcilers)

A serializable read bypasses the read-index protocol entirely. It just reads from any up-to-date replica without confirming leadership. This is fine for things like status reporting where seeing a slightly stale value doesn't break correctness, and it shaves a network RTT off every read. The API knob is `--consistency=l` vs `--consistency=s` in `etcdctl`, documented in [etcd's API reference](https://etcd.io/docs/v3.5/dev-guide/api_concurrency_reference/).

## Architecture: how a Kubernetes read actually flows

Let's trace a real-world request — `kubectl get pods` returning a Pod that the local apiserver cache has expired.

```text
client → apiserver → cacher (miss) → etcd v3 client → leader (Lease + ReadIndex)
                                                  ↓
                              confirm with quorum via AppendEntries heartbeats
                                                  ↓
                              wait until appliedIndex ≥ readIndex
                                                  ↓
                              read from boltdb-backed MVCC store
                                                  ↓
                              return key + revision + mod revision
```

The apiserver's `etcd` watcher caches results by **revision number**. Every etcd transaction returns a `mod_revision`, and a watch specifies a `startRevision`. When the cacher falls behind, it issues a read with `minModRevision` set, which forces etcd to wait until the local view is caught up. This is the integration point that makes etcd's read-index protocol feel invisible to Kubernetes users — the heavy lifting is wrapped in the client.

In a typical 3-node production cluster:

| Component | Default | Tuned for HA |
|---|---|---|
| `heartbeat-interval` | 100ms | 50–250ms |
| `election-timeout` | 1000ms | 1000–5000ms |
| `snapshot-count` | 100,000 entries | depends on workload |
| `quota-backend-bytes` | 2 GiB | 8 GiB for control planes |
| Disk | 5400 RPM | NVMe, fsync ≤10ms |

The tuning matters: a heartbeat that's too aggressive wastes bandwidth, while one that's too slow tightens the lease window and risks spurious elections under GC pauses. The [etcd admin guide](https://etcd.io/docs/v3.5/op-guide/) recommends running etcd on machines with consistent, low-latency disks — exactly because the read-index protocol assumes timely heartbeats.

## Patterns in production: what this design lets you build

The lease + read-index combination is not just an etcd implementation detail. It's a pattern you can lift into other systems.

### 1. Strong consistency without write-quorum reads

Any Raft-backed store can adopt this pattern: PostgreSQL-backed consensus layers like [CockroachDB](https://www.cockroachlabs.com/docs/v24.1/architecture/replication-layer.html), [TiKV](https://tikv.org/deep-dive-architecture/), and [Consul](https://www.consul.io/docs/architecture/consensus) all do something similar. The general rule is: **a leader with a fresh lease can serve reads locally, but must re-confirm leadership after any suspected delay**.

### 2. Bounded staleness for telemetry

If you don't need true linearizability — for example, a metrics scraper reading cluster state for a dashboard — you can drop down to serializable reads and serve them from any replica. This is exactly how some Kubernetes controllers split their reads: linearizable for the control loop, serializable for human-facing status.

### 3. Defending against clock drift

Leader leases implicitly assume bounded clock skew between nodes. If your clocks drift more than the election timeout, a partitioned leader could reappear and serve stale reads without realizing a new leader was elected. etcd assumes NTP-synchronized clocks within tens of milliseconds, and [Kubernetes' setup guides](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/) explicitly require NTP on control-plane nodes.

## Failure modes worth knowing

Even a correct implementation has corner cases that bite in production:

- **Split-brain risk during a long GC pause.** If the leader pauses for longer than the election timeout, followers will elect a new leader. The paused leader, when it wakes, will step down. This is correct, but it can cause a brief window of failed writes. Tune the GC and the election timeout together.

- **Read-index storms.** When a leader has been disconnected for a while and reconnects, it may receive a backlog of read-index requests all at once. etcd coalesces these in `pendingReadIndex`, but a buggy client that issues thousands of concurrent reads can amplify the load. Kubernetes' cacher mostly avoids this through revision-based deduplication.

- **Disk fsync stalls.** A single disk stall on the leader delays heartbeats, which can cause a spurious election and a brief unavailability window. This is why production etcd deployments run on dedicated NVMe with separate disks for WAL and data — a pattern spelled out in the [etcd hardware guide](https://etcd.io/docs/v3.5/op-guide/hardware/).

- **Watch revision gaps.** If a client reconnects after a partition and asks for `startRevision` newer than the leader's last applied index, the read-index protocol handles it correctly — but only if the apiserver's watcher implementation respects `minModRevision`. Older apiserver versions had bugs here; [the Kubernetes 1.28 changelog](https://kubernetes.io/blog/2023/08/15/kubernetes-v1-28-release-announcement/) flagged related fixes.

## Why this design still wins in 2026

Newer systems like [FoundationDB](https://www.foundationdb.org/) and [ScyllaDB](https://www.scylladb.com/) use different consistency mechanisms — FoundationDB uses a centralized sequencer, ScyllaDB leans on eventual consistency with lightweight transactions — but for the specific job of "be the source of truth for a Kubernetes-scale control plane", etcd's combination of lease + read-index + MVCC + watch is hard to beat. The numbers bear this out: a well-tuned 3-node etcd cluster on NVMe sustains 10k+ writes/sec and 30k+ reads/sec with sub-10ms p99 latency, as measured in the [CNCF etcd scalability study](https://www.cncf.io/blog/2021/09/30/etcd-scalability/).

The real lesson of etcd's Raft is that distributed consistency is rarely about a single trick. It's the combination: a lease that bounds stale reads, a read-index confirmation that catches leader transitions, an MVCC store that returns monotonic revisions, and a client protocol that lets you trade consistency for latency when you can afford it.

## Key Takeaways

- etcd's leader uses a **lease** granted by followers through `AppendEntries`, allowing it to skip explicit heartbeats on every read.
- The **read-index protocol** re-confirms leadership by sending a heartbeat round to a quorum before serving each linearizable read, closing the gap between lease expiry and actual leadership loss.
- Reads return only after the local `appliedIndex` has caught up to the `commitIndex` at the moment the read began, guaranteeing no write that was committed before the read is missed.
- Kubernetes uses **revision numbers** returned by etcd to coordinate watches and to handle cacher staleness transparently.
- The lease + read-index pattern is reused across other Raft systems — CockroachDB, TiKV, Consul — and is a generally useful design for any quorum-replicated store.
- Production hardening requires NTP, NVMe, dedicated disks, and careful tuning of `heartbeat-interval` and `election-timeout` relative to your worst-case GC pause.

## Further Reading

- [etcd v3.5 Design Documentation: Serving Read Requests](https://etcd.io/docs/v3.5/learning/design/)
- [In Search of an Understandable Consensus Algorithm — Diego Ongaro's Raft thesis (PDF)](https://raft.github.io/raft.pdf)
- [etcd-io/raft source on GitHub](https://github.com/etcd-io/raft)
- [etcd-io/etcd source on GitHub](https://github.com/etcd-io/etcd)
- [etcd Administration Guide: Hardware and Tuning](https://etcd.io/docs/v3.5/op-guide/hardware/)
- [Kubernetes Documentation: Operating etcd clusters for Kubernetes](https://kubernetes.io/docs/tasks/administer-cluster/configure-upgrade-etcd/)
- [CNCF Blog: etcd scalability and performance](https://www.cncf.io/blog/2021/09/30/etcd-scalability/)