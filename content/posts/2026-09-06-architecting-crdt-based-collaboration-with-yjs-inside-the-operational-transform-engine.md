---
title: "Architecting CRDT-Based Collaboration with Yjs: Inside the Operational Transform Engine"
date: "2026-09-06T18:00:30.960"
draft: false
tags: ["crdt", "yjs", "collaboration", "operational-transform", "distributed-systems"]
description: "How Yjs uses CRDTs and an operational transform engine to power real-time multi-user editing at scale."
summary: "A deep dive into Yjs's CRDT architecture and operational transform engine — the data structures, conflict resolution rules, and patterns that make collaborative editing feel instant."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-architecting-crdt-based-collaboration-with-yjs-inside-the-operational-transform-engine.svg"
  alt: "Diagram of Yjs document state diverging and merging between two clients"
  caption: ""
  relative: false
---

> **TL;DR** — Yjs is a high-performance CRDT framework for real-time collaboration. Instead of running a single authoritative server, every client holds a replica of the document and merges changes through a deterministic conflict-free data structure. The operational transform layer underneath is what makes that merge fast, network-efficient, and eventually consistent across thousands of concurrent edits.

When two users type into the same Google Doc at the same time, neither sees flicker, lost keystrokes, or duplicated lines. That seamless experience is the product of decades of research into distributed consistency, and most of the modern stacks that power it converge on the same idea: **replicated data types that converge by construction**, not by central arbitration.

Yjs, an open-source CRDT library originally built by Kevin Jahns, is one of the most production-ready implementations of that idea. It ships in [Evernote's editor](https://www.evernote.com), powers collaborative features in [Affinity's suite](https://affinity.serif.com), and is the runtime behind several open-source editors including [TipTap](https://tiptap.dev) and [ProseMirror's y-prosemirror bindings](https://github.com/yjs/y-prosemirror). Understanding *how* it works under the hood is useful even if you never write a CRDT by hand — because the patterns inside Yjs are the same patterns that show up in operational databases, multi-region replication, and vector clock systems.

This post is a guided tour of Yjs's architecture. We'll start with the problem CRDTs solve, walk through Yjs's core data structures, look at the operational transform engine that merges concurrent updates, and finish with patterns you'd actually use in production.

## Why Centralized Concurrency Control Breaks Down

The "classic" approach to collaborative editing is **Operational Transformation (OT)**, popularized by Google Docs in the early 2010s. Every edit is sent as an operation, the server transforms incoming operations against any operations that were committed concurrently, and clients rebase their buffered operations against whatever the server has already accepted. The system works, but it has two structural weaknesses:

1. **A central server is mandatory.** If the server is unreachable, edits queue locally. If two servers try to coordinate, they have to share an OT log.
2. **Transformation functions are hard to get right.** Google published a [famous paper on correctness in OT](https://dl.acm.org/doi/10.1145/215585.215706) precisely because so many implementations had subtle bugs.

CRDTs (Conflict-free Replicated Data Types) take a different approach. Instead of arbitrating conflicts at commit time, the data structure is *designed* so that any two replicas that apply the same set of operations, in any order, converge to the same state. No server required. No transformation matrix to debug. You can disconnect, edit offline for an hour, and reconcile when you reconnect.

The trade-off is that you have to be more disciplined about the data structure. Yjs picks the right trade-offs for a specific workload: rich-text and structured documents.

## Yjs's Core Data Structures

Yjs is built around two complementary structures that work together: a **document-level shared state tree** and a per-type **CRDT implementation** (e.g., `Y.Text`, `Y.Array`, `Y.Map`). When you call `Y.encodeStateAsUpdate(doc)`, what you serialize is the document's underlying binary log — a compressed sequence of *operations*.

Let's look at the building blocks.

### The YDoc and Shared Types

```js
import * as Y from 'yjs'

const ydoc = new Y.Doc()
const ytext = ydoc.getText('content')
const ymap  = ydoc.getMap('metadata')

// Every mutation goes through the document
ydoc.transact(() => {
  ytext.insert(0, 'Hello')
  ymap.set('author', 'alice')
})
```

A `Y.Doc` is a container for typed shared objects. Each shared object is backed by one of several CRDT implementations registered on the document:

| Shared type   | CRDT backing   | Typical use                                  |
|---------------|----------------|----------------------------------------------|
| `Y.Text`      | `YArray` of items with rich-text attributes  | Editors, code blocks                         |
| `Y.Array`     | `YArray`       | Lists, tables, blocks                        |
| `Y.Map`       | `YMap` (LWW)   | Key-value metadata                           |
| `Y.XmlFragment` | `YArray` with XML rules | ProseMirror/Quill-style rich text     |

The key insight: **these are all CRDTs.** `Y.Map` uses a Last-Writer-Wins (LWW) register with logical clocks. `Y.Text` and `Y.Array` use a more sophisticated structure we'll look at next.

### The YArray: A Doubly-Linked List of Item IDs

The core structure behind `Y.Text` and `Y.Array` is a **YArray** — a sequence of items where each item has a unique `clientID` + `clock` identifier (an `ItemID`). Every client gets a random 53-bit `clientID` on `Y.Doc` construction, and every operation increments that client's logical clock. An item's identity is the pair `(clientID, clock)`, which is globally unique forever.

```js
// Internally, items look roughly like this
{
  id: { client: 123456, clock: 7 },
  origin: { client: 123456, clock: 5 },  // predecessor
  rightOrigin: { client: 987654, clock: 3 }, // left neighbor
  content: 'Hello',
  type: 'Text',
  parent: <reference to YArray>,
  parentSub: null
}
```

When two clients insert text concurrently, their inserts end up in different branches of the linked list. When their updates meet, the **integrate** step merges them deterministically. The merge rule is the heart of the operational transform engine.

## The Operational Transform Engine

Yjs doesn't expose a transformation API the way classical OT systems do. Instead, every operation is a tiny self-contained record that *describes how to place itself relative to existing items*. The merge happens by walking the linked list and resolving order conflicts.

### How a Local Edit Becomes a Delta

When you call `ytext.insert(0, 'Hello')`, Yjs doesn't just append characters. It generates a sequence of operations called a **struct store delta**. There are three primitive ops:

- **`insert`**: create new items, each referencing a left and right neighbor by `ItemID`.
- **`delete`**: mark items as deleted without removing them from the list.
- **`attribute`**: update rich-text attributes (bold, italic, color) on an item range.

```js
// A delta after ytext.insert(0, 'Hello') on client 17, clock 4
{
  insert: [
    { itemID: { client: 17, clock: 4 }, content: 'Hello', origin: null }
  ],
  delete: [],
  attrs: []
}
```

This delta is then:

1. **Applied locally** to the YArray.
2. **Recorded** in the document's update log.
3. **Broadcast** to peers via a `Y.Event`-style observer or a network provider.

### Integration: Merging Concurrent Inserts

Here's the hard part. Two clients, A and B, start from the same state and both insert at position 0:

```
Initial:        "abc"
Client A inserts "X" at 0
Client B inserts "Y" at 0
```

A naive merge would either lose one character or duplicate it. Yjs solves this by giving each inserted item an **origin** (the item to its left) and a **rightOrigin** (the item to its right). When concurrent inserts target the same position, the engine uses a **tie-breaking rule**: items with the smaller `clientID` come first.

After integration, the list is deterministic:

```
Final:          "XYabc"   (assuming clientID A < clientID B)
```

The same rule applies no matter how late an update arrives. If B's insert doesn't reach A for ten minutes, A will still place B's item correctly when it shows up.

### The Algorithm in Pseudocode

The integrate step is short enough to reason about:

```text
function integrate(doc, item):
  conflictMarker = searchMarkerAfter(item.left, item.right)
  while conflictMarker exists and wasInsertedAfter(item, conflictMarker):
    conflictMarker = conflictMarker.next
  insert item before conflictMarker
  doc.structMap.set(item.id, item)
```

The `searchMarkerAfter` function walks the linked list looking for a position that respects both `origin` and `rightOrigin`. Concurrent inserts end up adjacent, and the tie-breaking rule orders them. This is essentially **RGA (Replicated Growable Array)**, a CRDT invented by [Hyperaide et al.](https://hal.inria.fr/inria-00445913/document), with Yjs-specific optimizations for caching and search.

### Why This Is "Operational Transform"

The term "operational transform" is overloaded. In classical OT, transformation means *rewriting an operation against a concurrent one*. In Yjs, the same effect is achieved by **anchoring each operation to a stable predecessor in the linked list** and **walking the list to resolve concurrent placement**. The behavior is identical: two operations that would have collided get a deterministic final order.

The advantage is that Yjs doesn't need a transformation matrix per data type. The placement rule is the same for `Y.Text`, `Y.Array`, `Y.XmlFragment`, and even nested documents.

## Patterns in Production

A CRDT library is only as useful as its network layer and persistence story. Yjs ships with several providers, each designed for a different operational shape.

### Pattern 1: WebSocket Provider for Live Editing

For real-time apps, [`y-websocket`](https://github.com/yjs/y-websocket) is the standard. The server is stateless; it just fans out updates between clients in a "room."

```js
// Client
import { WebsocketProvider } from 'y-websocket'

const wsProvider = new WebsocketProvider(
  'wss://collab.example.com',
  'doc-room-42',
  ydoc
)

// Server
import { setupWSConnection } from 'y-websocket/bin/utils'
wss.on('connection', (conn, req) => {
  setupWSConnection(conn, req, { gc: true })
})
```

For production, you'll want a real signaling service. [Hocuspocus](https://tiptap.dev/docs/hocuspocus/introduction) is the maintained, batteries-included WebSocket server — it adds persistence hooks, authentication, and extensions for scaling horizontally.

### Pattern 2: Snapshot + Update Log for Persistence

Yjs's persistence model is "store everything, snapshot occasionally." A typical Postgres-backed persistence loop looks like this:

```js
async function onUpdate(update, origin) {
  // Append every delta to a log
  await db.query(
    'INSERT INTO yjs_updates (doc_id, update_bin, ts) VALUES ($1, $2, $3)',
    [docId, Buffer.from(update), new Date()]
  )
}

async function loadDoc(docId) {
  const rows = await db.query(
    'SELECT update_bin FROM yjs_updates WHERE doc_id = $1 ORDER BY id',
    [docId]
  )
  return Y.mergeUpdates(rows.map(r => r.update_bin))
}
```

You can compress the log periodically by **compacting** — every N minutes, compute a snapshot (`Y.encodeStateAsUpdate(doc)`) and delete the older rows. Snapshots are bytewise-equivalent to the same delta stream re-applied, so you can reconstruct any historical state if you keep enough rows.

### Pattern 3: Awareness for Cursors and Presence

CRDTs handle document state. **Awareness** handles ephemeral metadata — cursors, selections, who's online. Yjs tracks this in a separate channel so awareness updates don't bloat the document log:

```js
const awareness = wsProvider.awareness
awareness.setLocalStateField('user', {
  name: 'Alice',
  color: '#ff8a65'
})

awareness.on('change', changes => {
  console.log('Peers online:', Array.from(awareness.getStates().entries()))
})
```

### Pattern 4: Subdocuments for Modular Editing

If you build a Notion-style editor where each block is independently editable, use **`Y.Subdocs`**. Each subdocument is its own CRDT that loads and syncs lazily:

```js
const parentDoc = new Y.Doc()
const page1 = parentDoc.get('page-1', Y.YDoc)
const page2 = parentDoc.get('page-2', Y.YDoc)

// Load only page1
await page1.whenLoaded
```

This pattern keeps initial sync fast even with thousands of pages, because peers only download what the user has actually opened.

## Common Failure Modes and How Yjs Handles Them

Working with CRDTs means thinking about scenarios that "don't exist" in single-writer systems. Here are three that bite in production.

### Failure Mode 1: Tombstone Explosion

Items are never physically deleted from a YArray — they're marked as deleted and stay around so concurrent inserts can still reference them. Over time, this bloats memory. Yjs handles this with **garbage collection**:

```js
const doc = new Y.Doc({ gc: true })  // default
```

With `gc: true`, deletions are physically removed once no live item references them as an origin. This is why you should never disable `gc` unless you have a specific reason — for example, supporting offline clients with very stale state.

### Failure Mode 2: Client ID Collisions After Reset

If a client loses its state (e.g., a browser refresh with `IndexedDB` cleared) and reconnects, it gets a *new* `clientID` but the old `clientID` is still present in remote state. Yjs handles this gracefully: the new client's clock starts where the new `clientID` left off, and all old items are recognized as belonging to a different peer. There's no scenario in which a reset corrupts state — that's the central CRDT guarantee.

### Failure Mode 3: Memory Pressure from Long-Lived Documents

A multi-year document can accumulate hundreds of thousands of operations. Compaction isn't optional at that scale. Schedule a background job that:

1. Loads a fresh `Y.Doc`.
2. Applies the current snapshot.
3. Writes a new snapshot and discards old update rows.

A document's effective size plateaus once compaction catches up.

## Comparison with Adjacent Systems

CRDTs are a category, not a single design. To place Yjs:

- **Automerge** is the other major JS CRDT library. It uses a different data model (a `Document` of immutable pieces with causal references) that gives you full history traversal at the cost of larger update payloads and slower merge for text-heavy workloads. [Automerge's docs](https://automerge.org/docs/repositories/meta/) are a good contrast.
- **Liveblocks** and **PartyKit** are managed CRDT services that wrap Yjs (or similar) with auth, presence, and edge replication. Pick these if you want to skip the server.
- **Figma's multiplayer architecture** uses a custom OT system, not Yjs, but solves the same problem for a vector canvas. Their [multiplayer blog post](https://www.figma.com/blog/multiplayer-engine/) is required reading for any collaborative-systems engineer.

Yjs's sweet spot is **rich-text and structured documents on the open web**, where its small bundle size, mature provider ecosystem, and integration with [TipTap](https://tiptap.dev) and [ProseMirror](https://prosemirror.net) pay off the most.

## Key Takeaways

- Yjs replaces central OT arbitration with **CRDT semantics**: every operation is anchored to immutable predecessors, so concurrent edits merge deterministically without a server.
- The core data structure is a **YArray of items with globally-unique `(clientID, clock)` IDs**. Inserts, deletes, and attribute changes are all operations on this structure.
- The "operational transform engine" in Yjs is really a **placement rule plus a tie-breaking rule** that walk the linked list to find a deterministic position for each new item.
- Production patterns include a stateless WebSocket fanout server, an append-only update log with periodic snapshot compaction, and a separate **awareness channel** for cursors and presence.
- Long-running documents need scheduled compaction to keep the YArray from accumulating tombstones. Garbage collection (`gc: true`) is on by default and should usually stay that way.
- Yjs isn't the only CRDT — Automerge, Liveblocks, and Figma's custom stack all solve related problems — but it's the most widely deployed open-source CRDT for collaborative editors on the web.

## Further Reading

- [Yjs Official Documentation](https://docs.yjs.dev)
- [Replicated Growable Arrays (RGA) — the academic paper behind Yjs's array model](https://hal.inria.fr/inria-00445913/document)
- [TipTap Collaboration Guide — production patterns for Yjs in editors](https://tiptap.dev/docs/editor/getting-started/install/collaboration)
- [Hocuspocus — the maintained Yjs WebSocket server](https://tiptap.dev/docs/hocuspocus/introduction)
- [Automerge Documentation — the other major JS CRDT](https://automerge.org/docs/repositories/meta/)
- [Figma's Multiplayer Engine — an OT system in production at scale](https://www.figma.com/blog/multiplayer-engine/)
- [Conflict-free Replicated Data Types — an accessible overview from the CRDT community](https://crdt.tech)