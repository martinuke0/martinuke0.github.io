---
title: "Database Indexes Internally: A Deep Dive into Data Structures and Operations"
date: "2025-12-13T21:53:55.951"
draft: false
tags: ["database", "indexing", "b-tree", "performance", "sql", "data-structures"]
---

## Introduction

Database indexes are essential for optimizing query performance in relational databases, acting as lookup tables that dramatically reduce data retrieval times from full table scans to targeted searches.[1][2] Internally, they rely on sophisticated data structures like **B-trees** and **B+ trees** to organize keys and pointers efficiently, minimizing disk I/O operations which are often the primary bottleneck in database systems.[3][5] This article explores how indexes work under the hood, from creation and structure to query execution, maintenance, and trade-offs, providing developers and DBAs with the depth needed to design effective indexing strategies.

## What is a Database Index?

At its core, a database index is a separate data structure that stores **sorted key values** from one or more columns alongside **pointers** to the actual data rows in the table.[1][2][6] Instead of scanning every row during a query (O(n) time complexity), the database engine uses the index for fast lookups, often achieving O(log n) efficiency.[6]

When you create an index—e.g., `CREATE INDEX idx_user_id ON users(id)`—the DBMS scans the table, extracts the indexed column values, sorts them, and builds the structure with pointers to the corresponding rows.[1] This "pseudo-table" remains sorted, enabling binary search-like operations.[6]

> **Key Insight**: Indexes trade storage space and write overhead for read speed, making them ideal for read-heavy workloads but costly for high-update tables.[7]

## Types of Database Indexes

Databases support various index types, each suited to specific access patterns. Here's a breakdown:

- **Primary Index**: Automatically created on the primary key, ensuring uniqueness and ordering the table physically (in clustered setups).[1]
- **Clustered Index**: Dictates the **physical order** of data rows on disk; only one per table, excelling in range queries (e.g., `WHERE date BETWEEN '2025-01-01' AND '2025-12-31'`).[1][5]
- **Non-Clustered (Secondary) Index**: Stores keys and pointers separately from data; multiple allowed per table, using virtual references to rows.[1]

Other variants include hash indexes for equality lookups and full-text indexes for search, but **B-tree based indexes** dominate due to their versatility.[2][6]

## Core Data Structures: B-Trees and B+ Trees

Most relational databases (MySQL, PostgreSQL, SQL Server) use **B+ trees** for indexes because they optimize for disk-based storage and range scans.[3][4][5]

### B-Tree Basics

A **B-tree** is a self-balancing tree where:
- Each node holds multiple keys and child pointers (order defined by fanout, typically 100-200 for disk pages).[4]
- Nodes are stored in fixed-size **pages** (e.g., 4KB-16KB), minimizing I/O by loading entire pages at once.[3]
- Search traverses from root to leaf in O(log n) steps, where n is the number of keys.[6]

**Insertion**:
1. Traverse to the leaf where the key belongs.
2. Insert and split if the node exceeds max keys (promoting middle key upward).
3. Rebalance if needed to maintain height balance.[4]

**Deletion** mirrors this, merging underfull nodes.

### B+ Tree Enhancements

**B+ trees** improve on B-trees for databases:
- **Internal (routing) nodes** only store keys for navigation; no data pointers.[3]
- **Leaf nodes** form a **linked list** for efficient range scans (forward/backward traversal).[4]
- Only ~1% of pages (routing nodes) stay in memory; leaves load on-demand.[3]

```sql
-- Example: MySQL B+ tree index on users(id, name)
CREATE INDEX idx_users_id_name ON users(id, name) USING BTREE;
```

In a `SELECT * FROM users WHERE id = 50`:
1. Load root/internal pages (cached in memory).
2. Reach leaf with key 50 and pointer.
3. Fetch row via pointer (1 extra I/O).[3][6]

For covering indexes (query columns all in index): Serve directly from leaves, skipping table I/O.[3]

| Feature | B-Tree | B+ Tree |
|---------|--------|---------|
| **Leaf Nodes** | Contain data pointers | Linked list + data pointers |
| **Range Scans** | Inefficient (no sibling links) | Efficient (sequential access) |
| **Memory Usage** | Higher (all nodes point to data) | Lower (routing nodes only ~1%)[3] |
| **DB Usage** | Rare | MySQL/PostgreSQL default[4][5] |

## How Queries Use Indexes: Step-by-Step

1. **Query Optimizer** checks for usable indexes on `WHERE`, `JOIN`, `ORDER BY` clauses.[1]
2. **Index Scan**: Traverse B+ tree to find matching keys (point or range).[2]
3. **Bookmark Lookup**: Use pointers to fetch full rows from table (non-covering).[3]
4. **Return Results**: Merge/sort as needed.

**Example I/O Breakdown** (100-row table, 4-row pages):[3]
- No index: Full scan = 25 I/O.
- Index: Tree traversal (4 I/O) + 1 lookup = 5 I/O.

Multilevel indexing handles large indexes by nesting trees, keeping roots in memory.[2]

## Index Creation and Building Process

```sql
-- Building scans table once, sorts keys, constructs tree
CREATE INDEX idx_location_time ON Location(log_time);
```
- **Scan Phase**: Read table sequentially.[1]
- **Sort Phase**: Heap-sort keys in memory/disk.
- **Tree Construction**: Bottom-up insertion or bulk-load for efficiency.[7]
- **Cost**: O(n log n) time, doubles storage for indexed columns.[7]

## Maintenance: Inserts, Updates, Deletes

Every DML operation updates indexes:
- **INSERT**: Add to leaf, split/rebalance (O(log n)).[4]
- **UPDATE**: Delete old key, insert new (2x log n if key changes).[7]
- **DELETE**: Mark/remove leaf entry, merge if underfull.[4]

High churn? Indexes fragment, requiring `ANALYZE` or `REBUILD`.[2]

**Fragmentation Example**:
```
Before frequent inserts: Tight B+ tree pages.
After: Page splits → 50% empty space → More I/O.
```

## Trade-Offs and Best Practices

**Pros**:
- Speed up SELECTs by 100-1000x.[6]
- Enable efficient JOINs/sorts.

**Cons**:
- **Storage Overhead**: 10-50% of table size.[7]
- **Write Penalty**: 2-10x slower INSERT/UPDATE.[7]
- **Cache Pollution**: Too many indexes evict hot data.

**Tips**:
- Index selective columns (>5% unique).[6]
- Composite indexes: Leading columns first (`(user_id, date)`).[6]
- Avoid on low-cardinality (e.g., gender).[1]
- Monitor with `EXPLAIN` plans.

## Advanced Topics: Hash Indexes and Beyond

- **Hash Indexes**: O(1) equality lookups (MySQL MEMORY engine); no ranges.[6]
- **Multilevel/Block Indexes**: For massive datasets, sparse outer indexes point to inner B-trees.[2]
- **Covering Indexes**: Include queried columns in index to avoid table lookups.[3]

## Conclusion

Understanding database indexes internally reveals them as masterful data structures—primarily **B+ trees**—that balance read efficiency with manageable write costs through sorted keys, pointers, and hierarchical paging.[1][3][4] By minimizing disk I/O via logarithmic searches and range-linked leaves, they transform brute-force scans into precise operations. However, thoughtful design is key: over-indexing bloats storage and slows writes, while under-indexing hampers reads. Experiment with `EXPLAIN`, monitor fragmentation, and align indexes with query patterns for optimal performance. Mastering these internals empowers you to build scalable, responsive database systems.

## Resources

- [A Detailed Guide on Database Indexes](https://blog.algomaster.io/p/a-detailed-guide-on-database-indexes)[1]
- [Indexing in Databases (GeeksforGeeks)](https://www.geeksforgeeks.org/dbms/indexing-in-databases-set-1/)[2]
- [Database Indexing Explained (Substack)](https://computersciencesimplified.substack.com/p/database-indexing-explained)[3]
- [Database Index Internals (ByteByteGo)](https://blog.bytebytego.com/p/database-index-internals-understanding)[4]
- [How Does Indexing Work (Atlassian)](https://www.atlassian.com/data/databases/how-does-indexing-work)[5]
- [How Do Database Indexes Work (PlanetScale)](https://planetscale.com/blog/how-do-database-indexes-work)[6]
- [Database Indexing and Partitioning (Macrometa)](https://www.macrometa.com/distributed-data/database-indexing-and-partitioning)[7]

*PostgreSQL/MySQL docs on B-tree indexes recommended for engine-specific details.*