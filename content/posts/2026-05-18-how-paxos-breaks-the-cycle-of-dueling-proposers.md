---
title: "How Paxos Breaks the Cycle of Dueling Proposers"
date: "2026-05-18T08:00:59.105"
draft: false
tags: ["distributed-systems","consensus","paxos","fault-tolerance","algorithms"]
description: "Explore how the Paxos consensus algorithm resolves the dueling proposers problem, ensuring safety and liveness in fault‑tolerant distributed systems."
summary: "This article explains the dueling proposers scenario in distributed consensus and walks through Paxos’s mechanisms that break the cycle, guaranteeing progress."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-how-paxos-breaks-the-cycle-of-dueling-proposers.svg"
  alt: "Illustration of nodes exchanging messages in a consensus protocol."
  caption: ""
  relative: false
---

> **TL;DR** — Paxos avoids the endless back‑and‑forth of dueling proposers by forcing each proposer to obtain a majority of promises before any value can be accepted. The prepare‑promise mechanism guarantees that once a value is chosen, all later proposals must respect it, thereby preserving safety while still allowing progress when a stable leader emerges.

In distributed systems, reaching agreement among unreliable processes is notoriously hard. One of the classic obstacles is the *dueling proposers* scenario, where two or more nodes simultaneously try to drive the consensus algorithm forward, each believing it has the right to propose a value. Without a disciplined coordination mechanism, these contenders can starve each other, violating liveness and, in the worst case, even safety. The Paxos algorithm—first described by Leslie Lamport in his seminal paper *The Part-Time Parliament*—introduces a two‑phase protocol that systematically eliminates this race condition. This post unpacks the dueling proposers problem, walks through Paxos’s prepare and accept phases, and shows why the protocol guarantees that the cycle eventually breaks.

## The Dueling Proposers Problem

In any consensus algorithm that allows multiple *proposers* to initiate a value, the system must decide which value will be ultimately chosen. If two proposers send conflicting proposals at roughly the same time, each can receive a subset of acknowledgments from the *acceptors* (the nodes responsible for persisting proposals). Without a global ordering, the acceptors may end up in divergent states:

1. **Proposer A** sends proposal `v1` with ballot number `b1`.
2. **Proposer B** concurrently sends proposal `v2` with ballot number `b2` (`b2 > b1`).
3. Some acceptors receive `b1` first and accept `v1`; others receive `b2` first and accept `v2`.

If the algorithm does not enforce a rule that forces acceptors to reconcile these divergent choices, the system can become stuck: each proposer sees a different majority and keeps retrying, never reaching a single agreed value.

### Why Two Proposers Conflict

- **Independent ballot numbers**: When proposers generate ballot numbers locally (e.g., using timestamps or random IDs), there is no guarantee that the numbers reflect a total order that all acceptors can agree upon.
- **Partial visibility**: Network latency and message loss mean that no proposer can be sure which acceptors have already promised to another proposer.
- **No leader guarantee**: Without a designated leader, every node may assume it has the authority to propose, leading to overlapping attempts.

### Impact on Safety and Liveness

- **Safety violation**: If two different values are considered *chosen* by different majorities, a client reading from the system could observe inconsistent state.
- **Liveness loss**: The system may keep cycling through proposals without ever reaching a stable decision, especially under high contention or network partitions.

These symptoms illustrate why a naïve multi‑proposer design is insufficient for production‑grade fault‑tolerant services.

## Paxos Overview

Paxos structures the consensus problem around three roles:

| Role       | Responsibility                                          |
|------------|----------------------------------------------------------|
| **Proposer** | Generates a *ballot number* and suggests a value.      |
| **Acceptor** | Stores the highest promised ballot and, optionally, the accepted value. |
| **Learner**  | Observes acceptor decisions to learn the chosen value. |

The protocol proceeds in two distinct phases:

1. **Prepare Phase** – A proposer asks a majority of acceptors to *promise* not to accept any proposal with a lower ballot number.
2. **Accept Phase** – After collecting promises, the proposer sends the value (either its own or the highest previously accepted value) to the same majority for acceptance.

If a proposer manages to collect promises from a majority, the protocol guarantees that any later proposal with a higher ballot number must respect the value chosen in the earlier phase. This ordering is the heart of how Paxos resolves dueling proposers.

## How Paxos Breaks the Cycle

### Prepare Phase: Establishing a Unique Ballot

When a proposer `P` wants to drive consensus, it first selects a **ballot number** `b` that is guaranteed to be larger than any ballot it has used before. A common technique is to combine a monotonically increasing *counter* with the proposer’s unique identifier:

```python
def next_ballot(proposer_id, local_counter):
    # Example ballot: (counter, proposer_id)
    return (local_counter + 1, proposer_id)
```

`P` then broadcasts a **Prepare(b)** message to all acceptors. Upon receiving this message, an acceptor `A` performs the following logic:

```python
def on_prepare(b):
    if b > self.promised_ballot:
        self.promised_ballot = b
        # Respond with the highest accepted value, if any
        return ("promise", b, self.accepted_ballot, self.accepted_value)
    else:
        # Reject the prepare; the proposer must try again with a higher b
        return ("reject", self.promised_ballot)
```

The crucial property here is that **once an acceptor promises to a higher ballot, it can never revert to a lower one**. This creates a *monotonic* ordering across the system.

### Promise Guarantees: Preventing Overwrites

Because each acceptor can only promise a single highest ballot at any time, any two proposers that manage to collect a majority of promises must have overlapping sets of acceptors. The intersection of any two majorities in a system of `N` acceptors is at least `⌈N/2⌉`. Therefore, there is at least one acceptor that has promised to the higher ballot and will refuse to accept a lower one.

Consider two competing proposers `P1` (ballot `b1`) and `P2` (ballot `b2 > b1`). If `P2` succeeds in gathering a majority of promises, every acceptor in that majority has already *rejected* any prepare with a ballot ≤ `b1`. Consequently, `P1` can no longer make progress because it cannot obtain a majority of promises for its lower ballot. The dueling cycle collapses: the higher‑balloted proposer wins the race.

### Accept Phase: Converging on a Single Value

After receiving promises, the proposer decides which value to send in the **Accept(b, v)** message:

1. If any acceptor reported a previously accepted value with ballot `b'` (where `b' < b`), the proposer **must** adopt the value associated with the highest such `b'`.
2. If no acceptor reported an accepted value, the proposer may use its own original value.

The acceptor’s logic for the Accept message mirrors the prepare handling:

```python
def on_accept(b, v):
    if b >= self.promised_ballot:
        self.promised_ballot = b
        self.accepted_ballot = b
        self.accepted_value = v
        return ("accepted", b, v)
    else:
        return ("reject", self.promised_ballot)
```

Because the acceptor only accepts a value when the ballot matches its current promise, the system never records two different values for the same ballot. The **intersection property** ensures that once a value is accepted by a majority, any later proposer will discover that value during its prepare phase and be forced to re‑propose it, preserving safety.

### Leader Election and the Role of the Majority

In practice, many Paxos deployments promote a *stable leader* to reduce the number of prepare rounds. The leader continuously issues proposals with the same ballot (or incrementally higher ballots only when needed). When the leader fails, a new proposer must start a fresh prepare round, automatically increasing its ballot number and thus taking over the role.

The majority quorum is the linchpin: it guarantees that even in the presence of failures, there is always at least one node that remembers the most recent accepted value. This memory is what allows Paxos to *break* the dueling proposers cycle without needing a separate lock service.

## Formal Guarantees

### Safety Proof Sketch

Safety (also called *consistency*) states: **No two distinct values can be chosen**. The proof relies on two lemmas:

1. **Lemma 1 (Promise Monotonicity)** – Once an acceptor promises ballot `b`, it never accepts a proposal with a lower ballot.
2. **Lemma 2 (Majority Intersection)** – Any two majorities of size `⌈N/2⌉` intersect in at least one acceptor.

Assume for contradiction that two values `v` and `v'` are both chosen, associated with ballots `b` and `b'` where `b < b'`. By Lemma 2, there exists an acceptor `A` that participated in both majorities. `A` must have promised `b'` during the later prepare phase, which, by Lemma 1, prevents it from accepting a lower ballot. Therefore `A` could not have accepted `v` in ballot `b`, contradicting the assumption that `v` was chosen. Hence safety holds.

### Liveness Under Partial Synchrony

Liveness (or *progress*) requires that the system eventually chooses a value if a majority of nodes remain non‑faulty and communication eventually becomes reliable. Paxos achieves this under the *partial synchrony* model described by Dwork, Lynch, and Stockmeyer:

- **During asynchronous periods**, proposers may fail to collect a majority of promises, causing retries.
- **Once the network stabilizes**, a proposer (often the elected leader) will be able to broadcast a Prepare with a sufficiently high ballot, receive promises from a majority, and complete the Accept phase.

The key is that the protocol does not rely on time‑outs for correctness—only for efficiency. Therefore, as long as the system eventually behaves synchronously, Paxos guarantees progress, effectively ending the dueling proposers cycle.

## Key Takeaways

- **Prepare‑Promise Mechanism** forces every acceptor to honor a single increasing ballot, preventing lower‑balloted proposals from overwriting higher‑balloted ones.
- **Majority Intersection** ensures that any two competing proposals share at least one acceptor, which acts as a bridge to propagate the chosen value.
- **Higher Ballot Wins** – A proposer with the highest ballot that secures a majority of promises will out‑compete dueling proposers, breaking the endless contention loop.
- **Leader Election** reduces the frequency of prepare rounds, but Paxos remains safe and live even when multiple proposers contend.
- **Safety and Liveness** are formally provable under the assumptions of monotonic promises and partial synchrony, making Paxos a robust foundation for modern distributed databases and coordination services.

## Further Reading

- [The Part-Time Parliament (original Paxos paper)](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf) – Leslie Lamport’s classic description of the algorithm.
- [Paxos Made Simple (Lamport, 2001)](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf) – A more accessible walkthrough with examples.
- [Raft Consensus Algorithm (a Paxos derivative)](https://raft.github.io) – Explains how a leader‑centric design simplifies understanding while preserving Paxos guarantees.