---
title: "Google Zanzibar: The Global Authorization System Powering Billions of Permissions"
date: "2026-03-25T15:23:21.691"
draft: false
tags: ["Google Zanzibar", "Authorization System", "Distributed Systems", "Access Control", "Spanner", "Scalable Permissions"]
---

# Google Zanzibar: The Global Authorization System Powering Billions of Permissions

In the world of massive-scale internet services, managing who can access what is a monumental challenge. Google Zanzibar addresses this head-on as a **globally distributed authorization system** that handles trillions of access control lists (ACLs) and millions of queries per second while maintaining sub-10ms latency and over 99.999% availability.[2][3] Deployed across services like Google Drive, YouTube, Photos, Calendar, and Maps, Zanzibar ensures consistent, fine-grained permissions for billions of users without compromising speed or reliability.[2][4]

This comprehensive guide dives deep into Zanzibar's architecture, data model, performance optimizations, real-world applications, and open-source alternatives. Whether you're a systems engineer designing authorization for your own service or a developer curious about planetary-scale consistency, you'll find practical insights, examples, and lessons from Google's implementation.

## The Problem Zanzibar Solves: Authorization at Planetary Scale

Modern applications like Google Workspace or YouTube deal with **billions of users sharing trillions of objects**—documents, videos, calendars, and more. Each object has complex permissions: owners, editors, viewers, group-based access, and nested hierarchies.[2][5]

Traditional approaches fall short:
- **Per-service silos**: Each app (e.g., Drive vs. Gmail) implementing its own auth leads to inconsistencies and duplication.
- **Inter-service chatter**: Constant permission checks between services kill performance at scale.
- **Staleness risks**: Distributed systems propagate changes slowly, risking users seeing data they shouldn't (or missing data they should).[5]

Zanzibar centralizes this into a **uniform data model and query language**, providing **external consistency**—authorization decisions respect the causal order of user actions, even amid rapid ACL changes.[2] It targets <10ms p95 latency, processes 12.4 million checks/sec at peak, and achieves 3ms p50 / 20ms p99 latencies.[3]

> **Key Requirements**: Error-free decisions, ultra-low latency, high availability, and support for filtering queries like "What documents can this user see?"[5]

## Core Architecture: Nodes, Caches, and Spanner

Zanzibar is a **distributed system** with three pillars: nodes for request handling, edge caches for speed, and Spanner for durable storage.[1][3]

### Zanzibar Nodes
Each node processes authorization requests and holds shards of data. Requests are **consistent-hashed** to specific nodes, boosting cache hit rates by concentrating related queries.[3] This deduplicates backend calls—multiple identical requests compute once and fan out results.

Nodes use **Leopard**, an in-memory indexing service for nested relationships. Instead of serial Spanner queries for group hierarchies (e.g., user → team → project), Leopard precomputes subgroups, reducing resolution to one index call.[3]

### Edge Caches and Replication
- **Multi-layer caching**: Outermost is Leopard; then server-local caches (LRU-based); inter-service RPC caches.[5]
- **Global replication**: Like a CDN, Zanzibar instances worldwide keep data close to users. Writes to Spanner propagate with strong consistency.[3]
- **Bounded staleness**: Clients tolerate minimal staleness for cache freshness without breaking consistency.[4]

### The Datastore: Google's Spanner
At the heart is **Spanner**, Google's globally distributed database offering **external consistency**—writes from anywhere are immediately visible everywhere, ordered causally.[3] Zanzibar stores **tuples** (user, resource, relation) here, enabling set-based policies over rigid ACLs.[1]

This setup yields **95th-percentile latency <10ms** and **>99.999% availability** over years of production.[2]

## Zanzibar's Data Model: ReBAC and Tuple-Based Relations

Zanzibar's genius is its **Relation-Based Access Control (ReBAC)** model, treating permissions as a **directed acyclic graph (DAG)** of relationships.[4]

### The Triple (Tuple) Format
Permissions are stored as **(user, object, relation)** tuples:
- **User**: Individual, group, or userset (e.g., "user:alice", "group:team-eng").
- **Object**: Resource like "doc:123" or "folder:abc".
- **Relation**: Permission type (e.g., "reader", "editor", "owner").[1][4]

Example tuples:
```
user:alice@company.com -> doc:123#reader
group:team-eng -> doc:123#editor
doc:123 -> folder:projects#parent
user:bob@company.com -> group:team-eng#member
```

### Graph Traversal for Checks
A "Can Alice read doc:123?" check traverses the graph:
1. Direct: alice → doc:123#reader? **Yes!**
2. Indirect: alice → group → doc:123#reader, or via folder hierarchies.[4]

This models complex policies like **nested groups** or **delegated access** (e.g., folder owners inherit child doc permissions).

### Zanzibar Query Language (ZQL)
Developers define policies in a **Turing-complete** language with:
- **Expressiveness**: Unions, intersections, exclusions (e.g., "readers OR editors EXCEPT ex-employees").
- **Userset Rewrites**: Compute dynamic sets (e.g., "all viewers of parent folder").
- **Efficiency**: Optimized for runtime evaluation.[1]

**Practical Example**:
```
# Policy: Editors can read/write; viewers can read; inherit from parent.
doc:123#reader@any: viewer
doc:123#reader@editor: editor
doc:123#reader@parent#reader: folder
```
A check fans out recursively but cancels early if a path grants access (eager cancellation).[7]

## Performance Optimizations: From Millions QPS to Milliseconds

Zanzibar's scale—**trillions of ACLs, millions QPS**—relies on clever tricks.[2]

### Caching Strategies
| Optimization | Description | Impact |
|--------------|-------------|--------|
| **Consistent Hashing** | Routes similar requests to same nodes. | Higher cache hits; deduped computations.[3] |
| **LRU Caches** | Per-server, multi-layer (edge, RPC). | Avoids redundant Spanner reads.[4][5] |
| **Leopard Indexing** | In-memory nested group resolution. | Single call vs. serial queries.[3] |

### Check Evaluation Engine
1. **Boolean Expression Tree**: Check → recursive fan-out (indirect ACLs/groups).
2. **Concurrent Leaves**: Parallel eval of base cases.
3. **Eager Cancellation**: Short-circuit on decisive paths.
4. **Read Pooling**: Batch identical Spanner RPCs.[7]

For "deep or wide" trees (many nested groups), Leopard pre-indexes.

### Handling Filtering Queries
Zanzibar supports **reverse queries** ("What can user X access?") via **reverse indexes**. Crucial for list endpoints (e.g., "User's visible docs").[5]

## Failure Handling and Resilience

Zanzibar is built for the real world:
- **Replication**: Data multi-node for redundancy.[1]
- **Failover**: Traffic auto-reroutes on node failure.
- **Watch API**: Leopard syncs with Spanner changes in real-time.[3]
- **Spanner Guarantees**: No staleness; causal consistency prevents errors.[5]

Over 3+ years: **99.999% uptime**, even at peak loads.[2]

## Real-World Applications at Google

Zanzibar unifies auth across:
- **Drive**: Folder hierarchies, sharing links.
- **YouTube**: Video viewers, channel subscribers.
- **Photos/Calendar**: Event invites, album shares.
- **Cloud/Maps**: API scopes, collaborative edits.[2][4]

**Case Study: Shared Document**:
- Alice owns doc:123, adds Bob as editor.
- Tuple: bob → doc:123#editor.
- Bob shares with team-eng (he's member).
- Check for team member: Graph traversal grants via multiple paths.
- Latency: <10ms globally.[4]

This consistency prevents leaks (e.g., applying old perms to new content).[5]

## Open-Source Implementations and Alternatives

Google's 2019 paper[2] inspired production systems:
- **Authzed/SpiceDB**: Zanzibar-compliant, uses PostgreSQL/CockroachDB. Handles 10M+ QPS.[3]
- **Oso**: Policy engine with ReBAC support.[5]
- **Permify/Aperm**: Kubernetes-native Zanzibar clones.

**Example with SpiceDB** (Go client):
```go
// Define schema
schema := `
definition document {
  relations define parent: folder
  relations define reader: user or group or parent#reader
  relations define editor: user or group
  permissions: read { reader } write { editor }
}`

// Write tuples
client.Write(context.Background(), namespace.NewNamespaceWriteRequest(...))

// Check
checkReq := &v1t1.CheckRequest{
    ResourceAndRelation: &structpb.Struct{ /* doc:123#read */ },
    Subject: &v1t1.SubjectReference{ /* user:alice */ },
}
resp, _ := client.Check(context.Background(), checkReq)
fmt.Println(resp.Membership) // true/false
```

These scale to enterprise needs without Spanner.

## Lessons for Building Your Own Authorization System

1. **Centralize with ReBAC**: Graphs > lists for flexibility.
2. **Cache Aggressively**: Multi-layer, consistent hashing.
3. **Strong Backend**: Prioritize consistency (Spanner-like).
4. **Index Hierarchies**: Avoid N+1 queries.
5. **Measure Everything**: Aim for p99 <20ms.

Common pitfalls: Over-nesting (explodes traversal); ignoring reverse queries.

## Challenges and Limitations

- **Complexity**: Graph policies hard to audit at scale.
- **Vendor Lock**: Google's uses Spanner; OSS needs alternatives.
- **Cost**: In-memory indexes like Leopard are memory-hungry.[3]
- **Evolution**: Post-2019 updates (e.g., SpiceDB extensions) address gaps.

Despite this, Zanzibar's design remains foundational.

## Conclusion

Google Zanzibar redefined scalable authorization, proving a **single system can serve billions** with consistency, speed, and reliability. By modeling permissions as traversable graphs, leveraging Spanner's guarantees, and optimizing with caches/indexes, it handles the impossible: real-time checks at planetary scale.[2][3]

For developers, the open paper and OSS ports democratize these ideas—build Zanzibar-inspired auth without reinventing the wheel. As services grow more collaborative, ReBAC systems like Zanzibar will be table stakes for secure, performant access control.

## Resources
- [Zanzibar: Google's Consistent, Global Authorization System (Original Paper)](https://research.google/pubs/zanzibar-googles-consistent-global-authorization-system/)
- [Authzed Blog: What is Google Zanzibar?](https://authzed.com/blog/what-is-google-zanzibar)
- [SpiceDB Documentation (Open-Source Zanzibar)](https://authzed.com/docs/reference/spicedb)
- [Oso: Implementing Zanzibar-like Policies](https://www.osohq.com/learn/google-zanzibar)
- [Annotated Zanzibar Paper by Authzed](https://authzed.com/z/google-zanzibar-annotated-paper)