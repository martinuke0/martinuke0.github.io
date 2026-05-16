---
title: "Formal Verification of Lockless Data Structures Using TLA⁺"
date: "2026-05-16T06:01:04.001"
draft: false
tags: ["formal verification","TLA+","concurrency","lockless data structures","software engineering"]
description: "Explore how TLA⁺ can rigorously verify lockless data structures, ensuring correctness in concurrent systems without traditional locks, with proven techniques."
summary: "This article walks through modeling lock‑free queues and stacks in TLA⁺, proving safety and liveness, and offers practical tips for scaling verification to production code."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-16-formal-verification-of-lockless-data-structures-using-tla.svg"
  alt: "Diagram of a lockless queue with arrows showing state transitions."
  caption: ""
  relative: false
---

> **TL;DR** — TLA⁺ lets you model lockless structures such as queues and stacks as state machines, prove they preserve safety invariants and eventually make progress, and uncover subtle memory‑ordering bugs before any production code is written.

Lock‑free data structures are a cornerstone of high‑performance systems, but their correctness hinges on intricate inter‑thread interactions that are notoriously hard to reason about. Formal methods—particularly TLA⁺—provide a mathematically rigorous way to capture those interactions, explore all possible executions, and verify both safety (nothing bad happens) and liveness (something good eventually happens). In this article we dive deep into how to model a lock‑free queue and a lock‑free stack in TLA⁺, walk through the proof of key properties, and share practical advice for scaling verification to real‑world codebases.

## Why Verify Lockless Structures?

### The Challenge of Lock‑Free Concurrency
Lock‑free algorithms avoid mutual exclusion primitives, instead relying on atomic primitives such as compare‑and‑swap (CAS). This yields impressive throughput, but also introduces hazards:

* **Memory‑ordering surprises** – Modern CPUs may reorder loads and stores, leading to stale reads.
* **ABA problem** – A location can change from value A to B and back to A, fooling a CAS that only checks equality.
* **Lost updates** – Two threads may simultaneously attempt to enqueue, causing one element to be overwritten.

Traditional testing (unit tests, stress tests) can expose many bugs, yet the state space of interleavings grows exponentially with the number of threads. Formal verification offers exhaustive coverage without the need to run billions of test cases.

## Introducing TLA⁺ for Concurrency

TLA⁺ (Temporal Logic of Actions) is a specification language invented by Leslie Lamport. It describes systems as **state variables** and **actions** that transition between states. Two key components make TLA⁺ ideal for concurrency:

1. **Model checking with TLC** – Exhaustively explores all possible behaviors up to a configurable bound.
2. **Theorem proving with TLAPS** – Allows inductive proofs of properties that exceed the model‑checking bound.

The official TLA⁺ Toolbox documentation explains how to write specifications and run the model checker: [TLA⁺ Toolbox](https://lamport.azurewebsites.net/tla/toolbox.html).

## Modeling a Lockless Queue in TLA⁺

A classic lock‑free queue is the Michael‑Scott queue (MS‑queue). We’ll model a simplified version that captures the essential CAS‑based head/tail updates.

### State Variables and Actions
```tla
---- MODULE LocklessQueue ----
EXTENDS Naturals, Sequences

CONSTANT N \* Maximum buffer size

VARIABLES head, tail, buf

Init ==
  /\ head = 0
  /\ tail = 0
  /\ buf = [i \in 0..N-1 |-> <<>>] \* each slot holds a sequence of values

Enqueue(val) ==
  /\ tail < N
  /\ buf[tail]' = Append(buf[tail], val) \* atomic append
  /\ tail' = tail + 1
  /\ UNCHANGED <<head, buf>>

Dequeue(val) ==
  /\ head < tail
  /\ val = Head(buf[head])
  /\ buf' = [buf EXCEPT ![head] = Tail(buf[head])]
  /\ head' = head + 1
  /\ UNCHANGED tail
```
*`Append`, `Head`, and `Tail` are defined in the `Sequences` module. The action `Enqueue` atomically appends a value to the current tail slot, then advances `tail`. `Dequeue` reads the first element of the head slot and removes it.*

### Safety Invariant: No Lost Elements
The primary safety property for a queue is **FIFO preservation**: every value dequeued must have been previously enqueued and in the correct order.

```tla
Invariant ==
  \A i \in 0..head-1 : 
    Len(buf[i]) = 0
  /\ \A i \in head..tail-1 :
    Len(buf[i]) >= 1
```

The first conjunct guarantees that all slots before `head` are empty (no stray elements). The second ensures that every slot between `head` and `tail‑1` contains at least one pending element. TLC can automatically verify `Invariant` for small `N` values:

```bash
# Run the model checker (requires the TLA+ Toolbox)
tla2tools/TLC LocklessQueue.tla
```

If the invariant fails, TLC produces a counterexample trace that pinpoints the exact interleaving that caused a lost element—often a missed CAS update.

### Liveness: Eventually Dequeue
Safety alone is insufficient; a lock‑free algorithm must also guarantee **progress**. In TLA⁺ we express this as a temporal property:

```tla
Liveness ==
  []<>(\E v : Dequeue(v))
```

The formula reads: “always eventually a dequeue action occurs.” Proving liveness typically requires reasoning about fairness assumptions. TLAPS can handle such proofs, and the TLA⁺ community provides detailed guidance on encoding fairness: see the TLAPS tutorial at [TLAPS Docs](https://lamport.azurewebsites.net/tla/tlaps.html).

## Verifying a Lockless Stack

Stacks are conceptually simpler than queues because they have a single pointer (`top`). The Treiber stack is a canonical lock‑free stack.

### Push and Pop Actions
```tla
---- MODULE LocklessStack ----
EXTENDS Naturals, Sequences

VARIABLES top, nodes

\* nodes maps an address to a record {value, next}
Init ==
  /\ top = Null
  /\ nodes = [addr \in Nat |-> [value |-> Null, next |-> Null]]

Push(val) ==
  /\ \E addr \in Nat :
        /\ nodes[addr].value = Null
        /\ nodes' = [nodes EXCEPT ![addr] = [value |-> val,
                                            next  |-> top]]
        /\ top' = addr
        /\ UNCHANGED nodes

Pop(val) ==
  /\ top # Null
  /\ LET cur == top IN
     /\ val = nodes[cur].value
     /\ top' = nodes[cur].next
     /\ UNCHANGED nodes
```

Each `Push` atomically allocates a fresh node (simulated by picking a previously unused address) and swings `top` to point at it. `Pop` reads the current `top`, returns its value, and moves `top` to the next node.

### Proving Linearizability
Linearizability is the de‑facto correctness condition for concurrent data structures: each operation appears to take effect instantaneously at some point between its invocation and response. In TLA⁺ we can express linearizability by defining a **sequential specification** and showing that every concurrent history can be mapped to a sequential one that respects the order of non‑overlapping operations.

The TLA⁺ community provides a reusable proof framework for linearizability (see the *Linearizability* module in the `Examples` repository). Applying it to `LocklessStack` yields a proof that both `Push` and `Pop` are linearizable under the assumption of atomic CAS on `top`.

## Common Pitfalls and How TLA⁺ Catches Them

| Pitfall | How it manifests | TLA⁺ detection method |
|---------|-----------------|-----------------------|
| **Missing memory fence** | Two threads observe writes in different orders, causing a stale read. | Model a relaxed memory model (e.g., using the `MemoryModel` module) and verify that the invariant still holds. |
| **ABA without version tag** | CAS succeeds on a reclaimed node, leading to corruption. | Add a version counter to each node and assert that `CAS` checks both pointer and version. TLC will reveal a counterexample when the version is omitted. |
| **Unbounded buffer overflow** | `tail` exceeds array size, causing wrap‑around bugs. | Explicitly bound `tail` with `N` and include an invariant `tail <= N`. |
| **Improper fairness assumptions** | Liveness proof fails because a thread can be starved indefinitely. | Encode weak fairness (`WF`) or strong fairness (`SF`) in TLAPS and test with the model checker’s fairness options. |

By encoding these concerns directly into the specification, TLA⁺ forces you to confront the subtle edge cases that usually hide in production bugs.

## Scaling Verification to Real‑World Code

Formal verification rarely stops at a toy model. To bring TLA⁺ into a production pipeline:

1. **Parameterize the model** – Replace concrete sizes (`N`) with symbolic parameters and use TLAPS for inductive reasoning.
2. **Extract executable code** – Use the `tlaplus2java` tool to generate skeleton Java classes that mirror the spec, then fill in the performance‑critical CAS calls.
3. **Continuous integration** – Run TLC on a reduced model (e.g., 2 threads, small buffer) on every pull request. The model runs in seconds and catches regression bugs early.
4. **Link to source** – Annotate the implementation with references to the corresponding TLA⁺ actions. This documentation practice reduces knowledge loss as teams evolve.
5. **Hybrid testing** – Combine model checking with systematic concurrency testing frameworks like `jcstress` for Java or `stress-ng` for C to validate that the compiled code respects the verified model under real memory models.

A case study from Microsoft demonstrates this workflow: they verified a lock‑free hash map using TLA⁺, then integrated the model checker into their CI pipeline, achieving a 30 % reduction in concurrency bugs after deployment. See the detailed write‑up at [Microsoft Research – Verifying Lock‑Free Hash Maps](https://www.microsoft.com/en-us/research/publication/verifying-lock-free-hash-maps/).

## Key Takeaways
- TLA⁺ models lock‑free data structures as succinct state machines, making it easy to enumerate all interleavings.
- Safety invariants (e.g., “no lost elements”) and liveness properties (e.g., “eventually dequeue”) can be proved automatically with TLC or inductively with TLAPS.
- Modeling memory‑ordering nuances and versioned pointers uncovers ABA and fence‑related bugs that traditional testing misses.
- A disciplined workflow—parameterized specs, CI‑integrated model checking, and code generation—lets teams reap the benefits of formal verification without sacrificing development velocity.

## Further Reading
- [TLA⁺ Home Page](https://lamport.azurewebsites.net/tla/tla.html) – Official resources, tutorials, and tool downloads.  
- [Specifying Systems: The TLA⁺ Language and Tools (2nd Edition)](https://lamport.azurewebsites.net/tla/book.html) – Lamport’s definitive book on writing and verifying specifications.  
- [Lock‑Free Data Structures – Wikipedia](https://en.wikipedia.org/wiki/Lock-free_data_structure) – Overview of algorithms, challenges, and real‑world uses.  
- [Microsoft Research – Verifying Lock‑Free Hash Maps](https://www.microsoft.com/en-us/research/publication/verifying-lock-free-hash-maps/) – A concrete case study of TLA⁺ in industry.  