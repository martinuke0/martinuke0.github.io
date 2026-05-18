---
title: "How CRDTs Reconcile Concurrent Edits Without a Central Server"
date: "2026-05-18T17:00:56.156"
draft: false
tags: ["CRDT", "distributed-systems", "collaboration", "eventual-consistency", "peer-to-peer"]
description: "Explore how conflict‑free replicated data types let multiple users edit the same document concurrently without a central server, guaranteeing convergence and low latency."
summary: "An in‑depth look at the mathematics and engineering behind CRDTs that enable seamless, server‑less collaborative editing."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-how-crdts-reconcile-concurrent-edits-without-a-central-server.svg"
  alt: "Diagram of distributed nodes syncing edits."
  caption: ""
  relative: false
---

> **TL;DR** — CRDTs let each replica apply local edits instantly and then exchange compact operation or state metadata; because the operations are mathematically commutative and idempotent, all replicas converge to the same document without ever needing a master server.

Concurrent editing is the holy grail of modern collaboration tools. Users expect their changes to appear instantly, even when they are offline or connected through a flaky peer‑to‑peer mesh. Traditional client‑server architectures solve this by funneling every edit through a single authority that serialises operations and resolves conflicts. That approach introduces latency, a single point of failure, and scaling headaches. Conflict‑free Replicated Data Types (CRDTs) flip the problem on its head: every replica can accept edits locally, and the system guarantees eventual convergence without any central coordinator. In this article we unpack the mathematics, the concrete data structures, and the networking patterns that make server‑less collaboration possible.

## The Problem of Concurrent Editing

When two users type at the same time, their edits may interleave in ways that are ambiguous without additional context. A naïve merge algorithm that simply concatenates the two streams of characters will produce garbled output, and a naïve “last write wins” policy discards valuable work. Centralised systems avoid this by:

1. **Serialising all operations** on a single authoritative log.
2. **Running a conflict‑resolution policy** (e.g., Operational Transformation) at the server.
3. **Broadcasting the resolved state** back to clients.

While effective, this design forces every edit to travel to the server, adds round‑trip latency, and creates a single point of outage. In a peer‑to‑peer scenario—think of a fully distributed note‑taking app or a collaborative IDE running over a mesh network—there is no always‑available server to play that role. The challenge is to let each replica edit autonomously while still guaranteeing that, after all messages have been exchanged, every replica ends up with exactly the same document.

## Foundations of CRDTs

CRDTs are a family of data structures built on three algebraic guarantees:

* **Commutativity** – applying operation *A* then *B* yields the same result as applying *B* then *A*.
* **Associativity** – grouping of operations does not affect the final state.
* **Idempotence** (for state‑based CRDTs) – merging the same state twice does not change the result.

When these properties hold, the order in which replicas receive updates becomes irrelevant; all replicas will converge to a common state once they have seen the same set of updates.

### State‑based (CvRDT) vs Operation‑based (CmRDT)

| Aspect | State‑based (Convergent) | Operation‑based (Commutative) |
|--------|--------------------------|-------------------------------|
| **What is sent** | Full state (or a compact digest) | Individual operations (e.g., “insert ‘a’ at position 5”) |
| **Merge function** | `state = merge(state, received_state)` – must be **idempotent**, **commutative**, **associative** | `apply(op)` – operations must **commute** |
| **Network load** | Potentially larger payloads, but can be throttled with anti‑entropy | Small, incremental messages; easier to bandwidth‑throttle |
| **Typical use‑case** | Counters, sets where the full state is cheap | Text sequences, complex structures where operation size is tiny compared to full state |

Both families can be combined in a single application. For example, a collaborative editor may use an operation‑based sequence CRDT for the text itself, while a state‑based G‑Counter tracks the number of edits per replica for analytics.

### Core Algebraic Properties in Practice

Consider a **grow‑only counter** (G‑Counter). Each replica *i* maintains an integer `c[i]`. The local increment operation simply does `c[i] += 1`. When two replicas exchange their vectors, they merge by taking the element‑wise maximum:

```python
def merge(v1, v2):
    """Element‑wise max merge for a G‑Counter."""
    return [max(a, b) for a, b in zip(v1, v2)]
```

Because `max` is commutative, associative, and idempotent, any order of merges yields the same final vector, and the sum of all entries is the globally consistent count.

## Popular CRDT Designs for Text

Text is the most demanding CRDT use‑case because edits are not just additive; they include deletions, moves, and re‑ordering. Several sequence CRDTs have emerged over the past decade, each trading off metadata size, operation latency, and implementation complexity.

### RGA (Replicated Growable Array)

RGA assigns a unique identifier (UID) to each character when it is inserted. The UID is a tuple `(replica_id, counter)`. Deletions are *tombstones*: the character stays in the underlying array but is marked as invisible. The total order is derived from the UID’s lexical order, guaranteeing a deterministic sequence.

### Logoot

Logoot generates a *position identifier* (PID) that lives in a dense ordered space (think of a real number line). When inserting between two existing PIDs, the algorithm chooses a new PID that lexicographically falls between them. Because the space is virtually infinite, collisions are rare, and tombstones can be eliminated after a *garbage‑collection* phase.

### LSEQ

LSEQ improves on Logoot by using a *balanced tree* of intervals to keep the identifier length logarithmic in the number of insertions. It reduces metadata overhead in long‑running documents, which is essential for mobile devices with limited bandwidth.

### WOOT (WithOut Operational Transform)

WOOT predates many of the above and stores both visible characters and *tombstones* in a linked list. Its merge algorithm is simple but suffers from unbounded growth of tombstones, making it unsuitable for large documents without aggressive pruning.

Below we walk through a minimal Python implementation of an RGA‑style sequence. The code is deliberately stripped down to the core ideas; production‑ready libraries such as **Automerge** or **Yjs** add layers for compression, network transport, and conflict diagnostics.

```python
# rga.py
from dataclasses import dataclass, field
from typing import List, Tuple, Dict

@dataclass(order=True, frozen=True)
class UID:
    replica: str
    counter: int

@dataclass
class Char:
    uid: UID
    value: str
    visible: bool = True

class RGA:
    def __init__(self, replica_id: str):
        self.replica_id = replica_id
        self.counter = 0
        self.sequence: List[Char] = []          # Linear storage
        self.index: Dict[UID, int] = {}         # UID → position in list

    def _next_uid(self) -> UID:
        self.counter += 1
        return UID(self.replica_id, self.counter)

    def local_insert(self, pos: int, ch: str) -> Char:
        """Insert character `ch` at logical position `pos`."""
        uid = self._next_uid()
        new_char = Char(uid, ch)
        self.sequence.insert(pos, new_char)
        self._rebuild_index()
        return new_char

    def local_delete(self, uid: UID) -> None:
        """Mark a character as deleted (tombstone)."""
        idx = self.index.get(uid)
        if idx is not None:
            self.sequence[idx].visible = False

    def remote_insert(self, char: Char) -> None:
        """Integrate an insert received from another replica."""
        # Find the correct position by UID ordering
        pos = 0
        while pos < len(self.sequence) and self.sequence[pos].uid < char.uid:
            pos += 1
        self.sequence.insert(pos, char)
        self._rebuild_index()

    def remote_delete(self, uid: UID) -> None:
        idx = self.index.get(uid)
        if idx is not None:
            self.sequence[idx].visible = False

    def _rebuild_index(self) -> None:
        self.index = {c.uid: i for i, c in enumerate(self.sequence)}

    def to_string(self) -> str:
        return ''.join(c.value for c in self.sequence if c.visible)
```

The `RGA` class demonstrates the two essential CRDT operations:

1. **Insert** – generate a globally unique `UID`, place the character according to UID ordering, and broadcast the `Char` object.
2. **Delete** – broadcast the `UID` of the character to be tombstoned; the receiver marks the same character invisible.

Because the `UID` ordering is total and deterministic, every replica that receives the same set of inserts arrives at the same linear order, regardless of network latency or message reordering.

### Example: A Simple Grow‑Only Counter (State‑based)

For contrast, here is a compact implementation of a G‑Counter, which is often used as a building block for more complex CRDTs (e.g., version vectors).

```python
# gcounter.py
from typing import Dict

class GCounter:
    def __init__(self, replica_id: str):
        self.replica_id = replica_id
        self.state: Dict[str, int] = {}

    def increment(self, n: int = 1) -> None:
        self.state[self.replica_id] = self.state.get(self.replica_id, 0) + n

    def merge(self, other: "GCounter") -> None:
        for rid, val in other.state.items():
            self.state[rid] = max(self.state.get(rid, 0), val)

    def value(self) -> int:
        return sum(self.state.values())
```

Both examples highlight the *commutative* nature of the merge: the order in which `remote_insert`, `remote_delete`, or `merge` calls arrive does not affect the final document.

## How Replicas Sync Without a Central Authority

CRDTs themselves do not prescribe a transport layer; they only guarantee that *any* sequence of merges will converge. In practice, peer‑to‑peer systems adopt one or more of the following patterns:

### Gossip / Epidemic Dissemination

Each replica periodically selects a random peer and exchanges its *digest* (e.g., a hash of the latest version vector). If the peer has newer updates, it sends the missing operations. This “anti‑entropy” approach is robust to churn and scales logarithmically with the number of nodes, as demonstrated in the original **Cassandra** and **Riak** designs.

```bash
# Example: simple gossip loop in bash (pseudo‑code)
while true; do
    peer=$(shuf -n1 peers.txt)
    curl -X POST http://$peer/sync -d @local_state.json
    sleep 5
done
```

### Publish‑Subscribe Mesh

Libraries like **Yjs** and **Automerge** expose a *room* abstraction on top of WebRTC or WebSocket servers. Peers join the room, and updates are broadcast to all members. Even though a signaling server is used to establish connections, the *authoritative* state never lives on that server; it merely relays messages.

### CRDT‑aware Conflict Resolution

Because operations commute, a replica can apply an incoming operation *immediately*, even if it has not yet seen earlier operations from the same origin. The local state remains *optimistically* consistent, and later merges will retroactively adjust positions if needed. This is the “optimistic UI” pattern seen in Google Docs and Notion.

## Handling Deletions and Tombstones

Deletion is the most subtle operation for sequence CRDTs. A naïve approach that physically removes a character breaks the guarantee that remote replicas can still identify the same element. The common solution is to retain a *tombstone*—metadata that records that a given UID has been removed.

### OR‑Set (Observed‑Remove Set)

An **Observed‑Remove Set** stores two internal structures:

* **Add‑Set** – a set of `(element, tag)` pairs.
* **Remove‑Set** – a set of tags that have been removed.

When adding an element, a fresh tag (often a UUID) is generated. Deleting the element adds the tag to the Remove‑Set. The element is considered present only if there exists at least one tag in the Add‑Set that is not in the Remove‑Set.

```python
# orset.py
import uuid
from typing import Set, Tuple

Tag = str
Element = str

class ORSet:
    def __init__(self):
        self.adds: Set[Tuple[Element, Tag]] = set()
        self.removes: Set[Tag] = set()

    def add(self, element: Element):
        tag = str(uuid.uuid4())
        self.adds.add((element, tag))

    def remove(self, element: Element):
        # Remove all tags associated with the element
        for e, t in list(self.adds):
            if e == element:
                self.removes.add(t)

    def lookup(self) -> Set[Element]:
        return {e for e, t in self.adds if t not in self.removes}
```

The OR‑Set pattern underlies many CRDT libraries’ delete logic, ensuring that a delete is *observed* by all replicas that have ever seen the corresponding add.

### Garbage Collection

Tombstones, if left unchecked, cause unbounded growth. Real‑world CRDT implementations employ *garbage‑collection* phases:

1. **Version Vectors** – each replica tracks the highest operation ID it has seen from every other replica.
2. **Safe‑Delete** – once all replicas have acknowledged receipt of an operation, its tombstone can be purged.
3. **Compaction** – libraries like **Yjs** compress the operation log into a binary *snapshot* and discard older entries.

This process respects the CRDT convergence guarantee because every replica only discards metadata that is known to be universally observed.

## Real‑World Deployments

| Project | Language / Platform | Primary CRDT Type | Notable Use‑Case |
|---------|---------------------|-------------------|------------------|
| **Automerge** | JavaScript / Rust | Operation‑based (JSON‑CRDT) | Collaborative note‑taking apps, offline‑first editors |
| **Yjs** | JavaScript, TypeScript | Operation‑based (array & map CRDTs) | Real‑time code editors (e.g., **CodeSandbox**), shared whiteboards |
| **Delta‑CRDT** | Erlang/Elixir | State‑based (counters, sets) | Distributed key‑value stores like **Riak** |
| **Swarm** | Go | Operation‑based (log‑structured) | Peer‑to‑peer file sync (IPFS) |
| **Microsoft Fluid Framework** | TypeScript | Hybrid (state + ops) | Office‑online co‑authoring |

These projects prove that CRDTs are not just academic curiosities; they power production services that serve millions of concurrent users.

## Trade‑offs and Limitations

While CRDTs eliminate the need for a central server, they introduce other engineering considerations:

| Concern | Impact | Mitigation |
|---------|--------|------------|
| **Metadata Overhead** | Each character may carry a UID or PID, inflating payload size. | Use compact encoding (e.g., variable‑length integers), periodic compaction, or hybrid approaches that switch to state‑based snapshots. |
| **Garbage Collection Complexity** | Determining when it is safe to delete tombstones requires version vectors and acknowledgments. | Leverage *causal stability* protocols such as **Matrix’s** “sync token” or **Scuttlebutt’s** “fork‑proof” mechanisms. |
| **Network Partitions** | Temporary splits can cause divergent histories that later merge, potentially leading to large conflict resolution bursts. | Design UI to show “offline” status and use *optimistic UI* updates that are reconciled silently. |
| **Limited Expressiveness** | Not all data structures have known CRDT formulations (e.g., arbitrary graphs). | Model complex structures as compositions of existing CRDTs (e.g., maps of sets). |
| **Learning Curve** | Developers must reason about idempotence and commutativity. | Adopt well‑tested libraries and follow community patterns rather than rolling your own CRDT. |

Understanding these trade‑offs helps teams decide whether a server‑less architecture aligns with their product goals.

## Key Takeaways

- **CRDTs guarantee convergence** by ensuring operations are commutative, associative, and (for state‑based types) idempotent, eliminating the need for a central authority.
- **Two families exist**: state‑based (CvRDT) merges whole states, while operation‑based (CmRDT) disseminates individual edits; both are viable for collaborative editing.
- **Sequence CRDTs** such as RGA, Logoot, and LSEQ encode each character with a globally unique identifier, allowing inserts and deletions to be applied in any order.
- **Tombstones** preserve delete intent across replicas; garbage collection strategies are essential to keep metadata size manageable.
- **Peer‑to‑peer sync** relies on gossip, anti‑entropy, or publish‑subscribe meshes, all of which work atop the CRDT’s convergence guarantees.
- **Real‑world libraries** (Automerge, Yjs, Fluid Framework) demonstrate that CRDTs can power large‑scale, low‑latency collaborative applications without a single point of failure.

## Further Reading

- [CRDT Overview – Wikipedia](https://en.wikipedia.org/wiki/Conflict-free_replicated_data_type) – A solid primer that covers the taxonomy of CRDTs and key research papers.
- [Automerge Documentation](https://automerge.org/docs/) – Hands‑on guide to a popular JavaScript/Rust CRDT library for JSON‑like data.
- [Yjs – Efficient CRDT for Real‑time Collaboration](https://github.com/yjs/yjs) – Source code and benchmarks for a high‑performance, modular CRDT framework.
- [The original RGA paper (PDF)](https://hal.inria.fr/inria-00555588) – Technical description of the Replicated Growable Array and its convergence proof.
- [Matrix.org – Sync API and CRDT concepts](https://matrix.org/docs/spec/client_server/latest#syncing) – Real‑world example of CRDT‑inspired synchronization in a federated chat system.