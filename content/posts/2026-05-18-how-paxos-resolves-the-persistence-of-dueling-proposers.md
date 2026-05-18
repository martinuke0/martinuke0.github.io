---
title: "How Paxos Resolves the Persistence of Dueling Proposers"
date: "2026-05-18T02:01:00.174"
draft: false
tags: ["distributed systems", "consensus", "paxos", "fault tolerance", "algorithms"]
description: "Explore how the Paxos consensus algorithm eliminates endless conflicts between competing proposers, ensuring safety and liveness in distributed systems."
summary: "This article explains why dueling proposers can stall Paxos and how the protocol’s phases, ballot numbers, and leader election guarantee progress."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-how-paxos-resolves-the-persistence-of-dueling-proposers.svg"
  alt: "Illustration of nodes reaching consensus in a distributed system."
  caption: ""
  relative: false
---

> **TL;DR** — Paxos prevents endless clashes between multiple proposers by using monotonically increasing ballot numbers, a two‑phase commit, and an implicit leader election that forces all participants to agree on a single proposal, thereby preserving both safety and liveness.

In distributed systems, achieving agreement among unreliable nodes is notoriously hard. The Paxos algorithm, introduced by Leslie Lamport in 1998, is a cornerstone of fault‑tolerant consensus. One of its most subtle challenges is handling *dueling proposers*: two or more nodes simultaneously trying to drive different values through the protocol. Left unchecked, such competition can lead to livelocks where no value ever gets chosen. This post walks through the mechanics that let Paxos resolve that persistence, from ballot numbers to the implicit leader election that emerges from the protocol’s own rules.

## The Problem of Dueling Proposers

When a client submits a command to a replicated state machine, any node may act as a *proposer* and start the Paxos process. If two proposers, say **P1** and **P2**, launch concurrently with different values, they each issue a *prepare* request (Phase 1a) to a quorum of acceptors. Because acceptors must promise not to accept lower‑numbered proposals, the two proposers can end up repeatedly overwriting each other's promises:

1. **P1** sends `Prepare(1)`; a majority of acceptors respond with *promise*.
2. **P2** sends `Prepare(2)` before **P1**’s `Accept` reaches a quorum.
3. Acceptors that already promised to **P1** must now reject **P2**’s lower‑numbered request, or vice‑versa depending on timing.

If the network is asynchronous or messages are delayed, each proposer may continually see its own promises invalidated, leading to an endless *duel* where no value ever reaches the *learn* phase. The core question is: **How does Paxos guarantee that this duel eventually ends?**

## Paxos Foundations: Prepare and Accept Phases

Paxos is built on two tightly coupled phases:

* **Phase 1 (Prepare/Promise)** – A proposer selects a *proposal number* (also called a *ballot number*) and asks a quorum of acceptors to promise not to accept any proposal with a lower number. Acceptors respond with the highest-numbered proposal they have already accepted, if any.
* **Phase 2 (Accept/Chosen)** – After receiving promises from a majority, the proposer sends an *accept* request with either:
  * The value from the highest accepted proposal it learned in Phase 1, **or**
  * Its own value if none were reported.

Only when a quorum of acceptors records the same proposal number and value does the value become *chosen* and can be learned by learners.

The critical safety property—*only one value can be chosen*—relies on the quorum intersection: any two majorities overlap in at least one acceptor, which guarantees that conflicting values cannot both be accepted.

## Ballot Numbers as a Tie‑Breaker

Ballot numbers are the engine that drives progress out of duels. They must satisfy two constraints:

1. **Monotonicity** – Every new proposer must generate a number higher than any it has seen.
2. **Uniqueness** – No two concurrent proposers should generate the same number.

A common practical scheme concatenates a *node identifier* with a *local counter*, e.g., `counter*MAX_NODES + node_id`. This ensures that even if two nodes increment their counters simultaneously, the combined value remains unique and totally ordered.

### Python Example: Comparing Ballot Numbers

```python
# ballot.py
def ballot_number(counter: int, node_id: int, max_nodes: int = 1024) -> int:
    """
    Encode a ballot number as a single integer.
    The higher the counter, the higher the overall number.
    node_id breaks ties when counters are equal.
    """
    return counter * max_nodes + node_id

def compare(ballot_a: int, ballot_b: int) -> int:
    """
    Returns:
        -1 if a < b
         0 if a == b
         1 if a > b
    """
    return (ballot_a > ballot_b) - (ballot_a < ballot_b)

# Example usage
if __name__ == "__main__":
    a = ballot_number(5, 3)   # 5*1024 + 3 = 5123
    b = ballot_number(5, 7)   # 5*1024 + 7 = 5127
    print(compare(a, b))      # Output: -1 (a < b)
```

By ensuring that every new prepare request carries a strictly larger ballot number, Paxos forces acceptors to *upgrade* their promises, effectively **preempting** lower‑numbered dueling proposals. Once a proposer obtains a quorum of promises for its high ballot, any lower‑numbered proposer will be rejected outright.

## Leader Election and the Role of the Coordinator

While Paxos does not prescribe a separate leader election service, the *highest-numbered proposer* that successfully completes Phase 1 naturally becomes the **coordinator** for that instance. This emergent leader has two powerful abilities:

1. **Lock‑step Progress** – The coordinator can continue issuing `Accept` messages for its ballot without competing proposals interfering, because any new proposer must generate an even higher ballot, which would require a fresh round of Phase 1.
2. **Value Selection** – If any acceptor had previously accepted a different value under a lower ballot, the coordinator must adopt that value (the *value‑adoption rule*). This ensures safety while still allowing progress.

In many production systems (e.g., Google’s Chubby, Apache ZooKeeper), a *static* leader is elected using a separate algorithm (Raft’s leader election, ZAB’s primary). However, even in pure Paxos, the **implicit leader** emerges after the first successful prepare, and dueling proposers are forced to back off until they can generate a higher ballot, which effectively restarts the election.

### Bash Illustration: Simulating a Paxos Round

```bash
#!/usr/bin/env bash
# Simulate two proposers (P1=1, P2=2) trying to win a round

declare -A promises   # acceptor_id -> ballot_number
declare -A accepted   # acceptor_id -> value

# Function to send a prepare
prepare() {
    local proposer=$1
    local ballot=$2
    echo "Proposer $proposer sends Prepare($ballot)"
    for a in {1..5}; do
        if [[ -z ${promises[$a]} || ${promises[$a]} -lt $ballot ]]; then
            promises[$a]=$ballot
            echo "  Acceptor $a promises to $proposer"
        else
            echo "  Acceptor $a rejects (already promised $((promises[$a])))"
        fi
    done
}

# Proposer 1 starts with ballot 10
prepare 1 10
# Proposer 2 starts with ballot 12 (higher)
prepare 2 12
# Observe that acceptors now only promise to the higher ballot
```

Running the script shows that acceptors discard the lower ballot’s promises once a higher one arrives, illustrating the *preemption* that ends duels.

## Ensuring Liveness: The Paxos Liveness Guarantees

Safety (no two values chosen) is straightforward; liveness (eventually a value is chosen) hinges on two assumptions:

1. **Partial Synchrony** – After some unknown *global stabilization time* (GST), messages are delivered within a known bound.
2. **Failure‑Free Majority** – At least a majority of acceptors remain up and can communicate.

Under these conditions, a proposer that keeps increasing its ballot number will eventually receive a quorum of promises that *no other proposer can preempt* because any competing proposer must generate an even higher ballot, which triggers a fresh round of Phase 1. The system thus converges on a single coordinator, and the chosen value is learned.

If the system is *completely asynchronous* (no timing guarantees), Paxos cannot guarantee liveness, as the classic FLP impossibility result shows. In practice, engineers combine Paxos with timeouts and *leader lease* mechanisms to bound the window of duels.

## Common Pitfalls and Real‑World Implementations

| Pitfall | Why It Happens | Mitigation |
|---------|----------------|------------|
| **Unbounded Ballot Growth** | Each retry increments a counter indefinitely, leading to integer overflow in naïve implementations. | Use 64‑bit integers; wrap safely after a defined limit; or employ *epoch* numbers combined with counters. |
| **Non‑Intersecting Quorums** | Configuring read/write quorums that don’t intersect (e.g., using 2/3 of nodes for reads and writes in a 5‑node cluster). | Enforce the classic majority quorum rule (`⌈N/2⌉ + 1`). |
| **Leader Starvation** | Continuous arrival of higher ballots from flaky nodes can prevent any proposer from completing a round. | Introduce *back‑off* timers; prefer a stable leader via a separate election service (as in Raft). |
| **Network Partitions** | Split brain where each partition thinks it has a majority. | Require a *lease* or *heartbeat* mechanism to detect and dissolve partitions. |

### Real‑World Systems that Build on Paxos

* **Google Chubby** – Uses a *primary* replica that runs a variant of Paxos; dueling proposers are eliminated by electing a master via a separate lease protocol.  
* **Apache ZooKeeper** – Implements the *Zab* protocol, which is essentially Paxos with a leader election phase that explicitly prevents duels.  
* **Microsoft Azure Cosmos DB** – Internally runs a multi‑master Paxos variant with *sticky* leaders to reduce the likelihood of concurrent proposals.

Each of these systems demonstrates the same underlying principle: **the highest ballot number wins, and once a leader holds that ballot, all other proposers must back off or start a new round**, thus resolving duels.

## Key Takeaways

- Paxos uses **monotonically increasing, unique ballot numbers** to preempt lower‑numbered proposals, turning dueling proposers into a single active coordinator.
- The **two‑phase commit (prepare → accept)** guarantees that any value chosen is the highest‑numbered one known to a quorum, preserving safety.
- **Implicit leader election** emerges after the first successful prepare; the leader holds the highest ballot and can drive the instance to completion without interference.
- Liveness is assured under **partial synchrony** and a **majority of responsive acceptors**, but engineers often add timeouts and lease mechanisms to handle real‑world network variability.
- Production systems (Chubby, ZooKeeper, Cosmos DB) adopt Paxos‑style protocols with explicit leader election or “sticky” leaders to keep duels from persisting.

## Further Reading

- [The original Paxos paper (Lamport, 1998)](https://lamport.azurewebsites.net/pubs/paxos.pdf) – The foundational description of the algorithm and its safety proofs.  
- [Paxos Made Simple (Lamport, 2001)](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf) – A concise, highly accessible walkthrough of the protocol.  
- [Understanding Distributed Systems – Chapter on Consensus](https://www.amazon.com/Understanding-Distributed-Systems-Andrew-Tanenbaum/dp/0132143011) – Provides broader context on where Paxos fits among consensus algorithms.  
- [ZooKeeper - ZAB Protocol Overview](https://zookeeper.apache.org/doc/current/zookeeperProgrammers.html#sc_zab) – Shows a practical implementation that extends Paxos with explicit leader election.  
- [Raft vs Paxos: A Comparative Study](https://raft.github.io) – While not about Paxos directly, this site offers insight into design trade‑offs that also affect how dueling proposers are handled.