---
title: "Optimizing ClickHouse MergeTree Compaction: Streaming Ingestion at High Throughput"
date: "2026-11-21T01:01:10.633"
draft: false
tags: ["ClickHouse", "MergeTree", "Performance", "Streaming", "Database"]
description: "Learn how to tune MergeTree compaction for high-throughput streaming ingestion, with practical configuration tips and production architecture patterns."
summary: "Optimizing MergeTree compaction is critical for maintaining query performance under heavy streaming loads. This post covers part merging strategies, background pool tuning, and disk I/O management for production ClickHouse deployments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-11-21-optimizing-clickhouse-mergetree-compaction-streaming-ingestion-at-high-throughpu.svg"
  alt: "ClickHouse MergeTree compaction pipeline visualization"
  caption: ""
  relative: false
---

> **TL;DR** — MergeTree compaction can become a bottleneck under high-throughput streaming ingestion. By tuning the background merge pool, controlling part sizes, and optimizing disk I/O, you can sustain millions of rows per second without query latency degradation. This post walks through the architecture and provides concrete configuration changes for production ClickHouse clusters.

When you're ingesting streaming data into ClickHouse at scale—think Kafka topics with millions of events per second—the MergeTree table engine's compaction mechanism can quickly become the limiting factor. Compaction is essential for query performance: without it, small parts accumulate, queries slow down, and memory pressure increases. But naive compaction can consume I/O bandwidth, starve inserts, and cause latency spikes. In this post, we'll break down how MergeTree compaction works under heavy load, identify the key knobs you can turn, and share patterns from production deployments that sustain high throughput without breaking the bank.

## Understanding MergeTree Compaction

### How Parts Are Created and Merged

Every INSERT in ClickHouse creates a new part. For streaming ingestion, you might be inserting small batches frequently, leading to many small parts. The MergeTree engine periodically merges these parts in the background to reduce their count and improve compression and query efficiency.

The merging process follows a hierarchical strategy: ClickHouse tries to merge parts of similar sizes to avoid the "merge of a large part with many small ones" scenario, which is I/O intensive. The goal is to eventually have one large part per partition.

You can observe the parts and their sizes with a query like:

```sql
SELECT 
    table,
    partition,
    formatReadableSize(sum(bytes_on_disk)) AS size_on_disk,
    count() AS parts,
    min(rows) AS min_rows,
    max(rows) AS max_rows
FROM system.parts
WHERE database = 'default' AND table = 'events'
GROUP BY table, partition
ORDER BY partition;
```

### The Cost of Compaction

Compaction is not free. It reads existing parts, merges them, and writes a new part, all while consuming CPU, memory, and disk I/O. Under high ingestion rates, the background merge pool can compete with inserts for I/O bandwidth, leading to increased insert latency or even temporary stalls.

A common failure mode is "merge storms": when many small parts accumulate faster than they can be merged, the system enters a state where it's constantly merging but never catching up. This results in degraded query performance and elevated resource usage. In one production incident, a cluster ingesting 2 million rows per second saw query latency spike from 200 ms to over 5 seconds because the merge queue had grown to over 10,000 parts per partition.

## Architecture: The Compaction Pipeline

### The Merge Queue

ClickHouse maintains a merge queue for each table. The queue is processed by background workers, whose number is controlled by the `background_pool_size` setting. Each worker picks up a merge task and executes it.

The architecture can be visualized as follows:

```
Inserts → Part Creation → Merge Queue → Background Pool → Merged Parts
```

The merge queue is prioritized based on part size and age. Older, smaller parts are merged first to prevent the accumulation of tiny parts that hurt query performance. The queue is also subject to space constraints: if the total size of parts being merged exceeds `max_bytes_to_merge_at_max_space_in_pool`, new merges are delayed to avoid memory exhaustion.

### Background Workers

The background pool size is a critical setting. If it's too small, merges happen slowly, and parts accumulate. If it's too large, you risk overwhelming the disk I/O subsystem, especially on spinning disks or network-attached storage.

In production, we often set `background_pool_size` to a value that balances merge throughput with insert latency. For example, on a 16-core machine with fast NVMe disks, we might use 8–10 workers. A common starting point is to set it to the number of physical cores minus the number of cores reserved for query processing.

```yaml
<!-- In users.xml or config.xml -->
<clickhouse>
    <background_pool_size>8</background_pool_size>
</clickhouse>
```

### Impact on Query Performance

Unmerged parts slow down queries because ClickHouse has to read from many small files instead of a few large ones. This increases open file descriptors, seeks, and memory overhead for the part index. Queries that scan large ranges can become I/O bound.

Compaction also affects memory usage during merges. Large merges can consume significant memory for sorting and merging, potentially leading to OOM kills if not managed properly. ClickHouse limits the memory used by merges via the `max_bytes_to_merge_at_max_space_in_pool` setting, but you need to size this correctly for your workload.

## Patterns in Production: High-Throughput Ingestion

### Tuning the Background Merge Pool

Beyond `background_pool_size`, you can control merge behavior with the `merge_tree` settings. For high-throughput scenarios, we often increase the `max_bytes_to_merge_at_max_space_in_pool` setting, which limits the total size of parts being merged simultaneously to prevent memory blowups.

A production configuration might look like:

```yaml
<clickhouse>
    <merge_tree>
        <max_bytes_to_merge_at_max_space_in_pool>10000000000</max_bytes_to_merge_at_max_space_in_pool> <!-- 10 GB -->
        <max_bytes_to_merge_at_min_space_in_pool>5000000000</max_bytes_to_merge_at_min_space_in_pool> <!-- 5 GB -->
    </merge_tree>
</clickhouse>
```

Another important setting is `number_of_free_threads_to_execute_queries`, but for merges, the relevant thread pool is the background pool. You can also adjust `max_background_merge_pool_size` to limit the number of concurrent merges per table.

### Part Size and Granularity

One of the most effective levers is controlling part size. If you're inserting tiny batches, consider batching inserts client-side to create larger parts. ClickHouse's `min_bytes_to_merge_at_max_space_in_pool` and `max_bytes_to_merge_at_max_space_in_pool` settings influence when merges are scheduled.

You can also use `partition_by` to limit the number of partitions, as merges happen within each partition. Too many partitions can lead to many small parts that never get merged because the merge queue is partitioned.

A practical pattern is to use a time-based partition like `toYYYYMMDD(event_time)` but avoid over-partitioning by not using too granular intervals. For example, partitioning by day instead of hour reduces the number of partitions and keeps merge work manageable.

### Disk I/O and Storage Tiering

High-throughput ingestion generates a lot of I/O. Using fast NVMe SSDs is essential, but you can also employ ClickHouse's storage tiering to move old parts to cheaper, slower storage.

In `config.xml`, you can define disks and volumes:

```xml
<disks>
    <fast_nvme>
        <type>local</type>
        <path>/mnt/fast_nvme/</path>
    </fast_nvme>
    <slow_hdd>
        <type>local</type>
        <path>/mnt/slow_hdd/</path>
    </slow_hdd>
</disks>
<volumes>
    <default>
        <disk>fast_nvme</disk>
    </default>
    <tiered>
        <disk>fast_nvme</disk>
        <disk>slow_hdd</disk>
    </tiered>
</volumes>
```

Then assign the table to the tiered volume:

```sql
CREATE TABLE events
(
    event_time DateTime,
    ...
)
ENGINE = MergeTree()
PARTITION BY toYYYYMMDD(event_time)
ORDER BY (event_time)
SETTINGS index_granularity = 8192,
         storage_policy = 'tiered';
```

This way, recent parts stay on fast storage, and as they age, they migrate to slower storage, freeing up I/O bandwidth for new inserts and merges.

### Real-World Scenario: 2M Rows/Second Ingestion

Consider a ClickHouse cluster ingesting 2 million rows per second from Kafka. The initial setup used default settings and partitioned by hour. Within hours, the cluster had over 50,000 parts per partition, and queries took minutes.

We made the following changes:
- Increased `background_pool_size` from 4 to 12.
- Switched partitioning from `toHour(event_time)` to `toYYYYMMDD(event_time)`.
- Implemented storage tiering with NVMe for the first 7 days and HDD for older data.
- Batched inserts client-side to create parts of at least 1 GB.

After these changes, the merge queue stayed under 100 parts per partition, insert latency remained under 100 ms, and query performance returned to sub-second levels.

### Monitoring and Alerting

You need to monitor the merge queue length and part sizes. The `system.merges` table shows ongoing merges, and `system.parts` shows part counts.

A useful query for merge queue health:

```sql
SELECT 
    database,
    table,
    sum(bytes) AS total_bytes,
    sum(rows) AS total_rows,
    count() AS parts,
    avg(bytes) AS avg_part_size
FROM system.parts
WHERE active = 1
GROUP BY database, table
HAVING parts > 100
ORDER BY parts DESC;
```

Alert if the number of active parts exceeds a threshold, or if the merge queue is growing unboundedly. Also monitor `system.merges` for merge duration and `system.events` for merge-related failures.

## Key Takeaways

- **Control part size**: Batch inserts to avoid creating many tiny parts; use `min_bytes_to_merge_at_max_space_in_pool` to tune merge scheduling.
- **Size the background pool**: Set `background_pool_size` based on your core count and disk I/O capacity; monitor merge queue depth.
- **Leverage storage tiering**: Move old parts to cheaper storage to free up fast I/O for active merges and inserts.
- **Partition wisely**: Avoid over-partitioning; use coarse-grained partitions to keep merge work manageable.
- **Monitor continuously**: Track part counts, merge progress, and I/O wait times to catch merge storms early.

## Further Reading

- [ClickHouse MergeTree Documentation](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree) — the official guide to MergeTree engines and their settings.
- [Background Pool in ClickHouse](https://clickhouse.com/docs/en/operations/server-configuration/settings) — details on background pool configuration and related settings.
- [Storage Policies and Tiering](https://clickhouse.com/docs/en/operations/storage/storage-policies) — how to set up disk tiering for cost-effective storage.
- [Monitoring ClickHouse with Prometheus](https://clickhouse.com/docs/en/operations/metrics) — metrics for merge queue, parts, and I/O.