---
title: "How Redis Cluster Works Internally — A Deep Dive"
date: "2025-12-12T16:38:59.337"
draft: false
tags: ["redis","distributed-systems","clustering","sharding","high-availability"]
---

## Table of contents
- Introduction
- High-level overview: goals and building blocks
- Key distribution: hash slots and key hashing
- Cluster topology and the cluster bus
- Replication, failover and election protocol
- Client interaction: redirects and MOVED/ASK
- Rebalancing and resharding
- Failure detection and split-brain avoidance
- Performance and consistency trade-offs
- Practical tips for operating Redis Cluster
- Conclusion
- Resources

## Introduction
Redis Cluster is Redis's native distributed mode that provides horizontal scaling and high availability by partitioning the keyspace across multiple nodes and using master–replica groups for fault tolerance[1]. This article explains the cluster's internal design and runtime behavior so you can understand how keys are routed, how nodes coordinate, how failover works, and what trade-offs Redis Cluster makes compared to single-node Redis[1][2].

## High-level overview: goals and building blocks
Redis Cluster was designed primarily to:
- Provide **automatic sharding** of data across nodes using a fixed set of hash slots[1].
- Provide **availability** in the presence of a subset of node failures via master–replica pairs and automatic failover[2].
- Maintain simple, low-latency operation with minimal coordination overhead (eventual convergence rather than strong global locking)[1][2].

Core components:
- **16384 hash slots**: logical buckets that partition the key space across masters[1].
- **Cluster bus**: a dedicated TCP-based binary protocol connecting every node to every other node for gossip, PING/PONG, and configuration propagation[1].
- **Node state metadata**: each node stores the cluster configuration it knows (node IDs, slots, flags, replication relationships, last ping/pong times)[1].
- **Master–replica groups**: each master holds a set of hash slots; replicas follow a master and can be promoted on failover[2].

## Key distribution: hash slots and key hashing
Redis maps every key to one of 16384 hash slots using CRC16(key) mod 16384; each slot is owned by exactly one master at a time[4]. When a client issues a command for a key, the client (or a smart client library) computes the slot and sends the command to the responsible master[4][1].

Notes on key tags:
- You can force multiple keys to the same slot by using a substring in braces, e.g., "user:{123}:name"; the CRC is computed on the substring inside braces so related keys can be co-located for multi-key operations[1].

Why 16384 slots?
- A fixed slot count simplifies resharding: slots (not individual keys) are moved between masters during cluster topology changes, reducing coordination complexity[1][5].

## Cluster topology and the cluster bus
Redis Cluster is a full-mesh topology: every node maintains persistent TCP connections to every other node on the "cluster bus" (an extra port, typically client-port + 10000). These connections are long-lived and used for gossip, configuration propagation, and failover messages[1][2].

Gossip and state propagation:
- Nodes gossip cluster state to detect new nodes, propagate node liveness, and synchronize configuration changes[1].
- Each node stores metadata for nodes it knows about: node ID, address, flags (master, replica, failing, etc.), master ID if replica, and last ping/pong timestamps[1].

Implication:
- Full-mesh simplifies availability and reduces coordination latency for relatively small clusters (recommended practical size up to a few hundred nodes), but scales worse than hierarchical designs for very large deployments[1].

## Replication, failover and election protocol
Replication model:
- Each master can have zero or more replicas. Replication is asynchronous: a master acknowledges client writes without waiting for replicas to confirm[2]. This reduces write latency but can cause acknowledged writes to be lost if a master fails before replication completes[2].

Failover overview:
- When a master appears unreachable, replicas and other masters run an election to promote a replica to master automatically[1][2]. Elections are driven by voting from other master nodes and use cluster metadata propagated over the cluster bus[1].

Failure detection and promotion:
- A node is marked as *PFAIL* (possibly failing) locally after missing pings; if enough nodes agree it is unreachable it becomes *FAIL* cluster-wide and its replicas can be promoted[1].
- To avoid split-brain and unsafe promotions, Redis requires a majority of masters to agree and uses additional safety checks (e.g., replica must be up-to-date enough and not flagged with certain problems) before promoting[1][2].

Important trade-off:
- Because replication is asynchronous and master replies to clients immediately, a promoted replica may be missing recent writes — Redis Cluster favors availability and low latency over strict durability or linearizability by default[2].

## Client interaction: redirects and MOVED/ASK
Clients need to locate the master responsible for a key. There are two common approaches:
- Smart clients: cache the cluster slot -> node mapping and send requests directly to the correct node; update mapping on receiving MOVED[1].
- Proxy-based or naive clients: send requests to any node, which will either serve the command or reply with a redirect.

Redirect responses:
- MOVED: permanent redirect when the receiving node knows the correct owner for the slot (client should update its cached mapping and retry at the new node)[1].
- ASK: temporary redirect used during certain resharding operations when a slot is in transition; the client must send an ASKING command before the retried command[1].

Client libraries and tooling commonly implement slot caching and automatic handling of MOVED/ASK to minimize round-trips.

## Rebalancing and resharding
Moving data between masters works at the slot level:
- Administrators reassign hash slots from one master to another (manual or via tools), and the receiving node imports keys for those slots while the source exports them[1].
- During slot migration the cluster can issue ASK redirects for queries targeting slots that are in transition[1].

Because slots are the unit of movement, resharding is relatively efficient compared to moving individual keys and avoids global coordination that would block the cluster[1][5].

## Failure detection and split-brain avoidance
Gossip-based liveness + consensus:
- Nodes gossip about each other's status; local views are combined and propagated so that other nodes can form a consistent picture[1].
- For failover, a majority of masters must vote for promotion to prevent conflicting promotions (split-brain), hence having an odd number of masters or additional replicas is recommended to aid quorum formation[5].

Prominent causes of split-brain:
- Network partitions combined with inadequate voting/quorum configuration can lead both partitions to elect masters independently; Redis Cluster's voting and node state checks aim to minimize this risk but proper deployment topology matters[1][5].

## Performance and consistency trade-offs
Redis Cluster optimizes for low latency and availability:
- Asynchronous replication reduces write latencies but permits potential data loss on master failure unless additional measures (like synchronous replication proxies or application-level durability) are used[2].
- Multi-key operations that span slots are unsupported unless keys are co-located in the same slot; this is a deliberate trade-off to keep routing simple and performant[1].

Scaling:
- Cluster scales horizontally by adding masters and moving slots—clients and cluster metadata observe changes and adapt[4].
- However, the full-mesh bus and coordination design make extremely large numbers of nodes less practical; Redis recommends cluster sizes on the order of hundreds rather than thousands for OSS cluster[1].

## Practical tips for operating Redis Cluster
- Always provision replicas: at least one replica per master to survive single-master failures[2].
- Use odd number of masters or ensure quorum through replicas to prevent tie votes during failover[5].
- Monitor replication lag; asynchronous replication means replicas can lag and may not be eligible for safe promotion[2].
- Expose both client and cluster bus ports in your network and firewall rules; cluster nodes require both ports reachable between each other[1][2].
- Prefer smart/cluster-aware clients to minimize MOVED/ASK latency and retries[1].
- Plan for resharding windows and test slot migrations in staging; use tools that automate safe slot movement[1].

> Note: Redis Enterprise (a separate product) uses a different architecture (proxies and symmetric components) and offers additional features and operational differences from open-source Redis Cluster[3].

## Conclusion
Redis Cluster implements a pragmatic distributed design: fixed 16384 hash slots for predictable sharding, a gossip-based full-mesh cluster bus for state propagation and failover coordination, asynchronous master–replica replication for low latency, and client-side or node-side redirects for efficient routing[1][2]. These choices deliver high performance and availability for many workloads but require awareness of trade-offs (eventual consistency, potential for data loss on failover, and limitations around cross-slot multi-key operations)[1][2][4].

## Resources
- Redis Cluster specification (official documentation): Redis Cluster specification explains slots, cluster bus, gossip, and node metadata in detail[1].
- Scaling with Redis Cluster (official docs): practical guidance on master/replica model, ports, and operational considerations[2].
- Redis Enterprise cluster architecture: differences and enterprise-grade design patterns for Redis in production[3].
- Intro to Redis sharding (blog): practitioner-friendly explanation of CRC16 hashing, slots, and client interactions[4].
- Architecture notes on Redis (article): additional explanation of hash slots and gossiping behavior[5].

(For convenient follow-up reading, consult the official Redis docs and the linked practical guides cited above.)