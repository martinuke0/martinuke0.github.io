---
title: "Why Query Planners Fail at Cardinality Estimation"
date: "2026-05-18T15:00:58.446"
draft: false
tags: ["database", "query-planner", "cardinality-estimation", "sql", "performance"]
description: "Explore why modern query planners often misestimate row counts, the statistical pitfalls behind cardinality estimation, and practical ways to improve accuracy."
summary: "A deep dive into the reasons query planners stumble on cardinality estimation, from outdated statistics to optimizer assumptions, and how to mitigate the impact."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-why-query-planners-fail-at-cardinality-estimation.svg"
  alt: "A stylized diagram of a database query plan with mismatched arrows."
  caption: ""
  relative: false
---

> **TL;DR** — Query planners rely on statistical shortcuts that can be stale, ignore column correlation, and oversimplify data distribution. The result is wildly inaccurate cardinality estimates, but disciplined statistics maintenance, extended statistics, and adaptive execution can dramatically reduce the pain.

Database engines spend a surprising amount of time trying to guess *how many* rows a predicate will return. That guess—known as **cardinality estimation**—feeds every downstream decision: join order, index usage, parallelism, and even whether a query should be rewritten at all. When the estimate is off by an order of magnitude, the optimizer can pick a plan that runs minutes instead of seconds, or that exhausts memory and crashes. Understanding *why* planners fail at this step is essential for anyone who writes performance‑critical SQL.

## The Role of Cardinality Estimation in Query Planning

At a high level, a query planner performs three steps:

1. **Generate candidate plans** – permutations of join orders, access paths, and parallel execution strategies.
2. **Estimate cost for each plan** – a function of CPU, I/O, and memory usage.
3. **Choose the cheapest plan** – the one with the lowest estimated cost.

Cost is calculated as:

```
cost = Σ (cpu_cost_per_row * estimated_rows) + Σ (io_cost_per_page * estimated_pages)
```

If the *estimated_rows* component (the cardinality) is wrong, the entire cost model collapses. For example, consider a simple join between `orders` and `customers`:

```sql
EXPLAIN ANALYZE
SELECT *
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE c.country = 'DE' AND o.amount > 1000;
```

If the planner thinks only 10 rows satisfy the filter but the real count is 10 000, it may choose a nested loop join with a hash lookup, which will cause 10 000 random I/O operations instead of a single sequential scan.

## Common Sources of Error

### Out‑of‑date Statistics

Most relational engines collect statistics during a *VACUUM ANALYZE* (PostgreSQL), *UPDATE STATISTICS* (SQL Server), or an automatic background job. These stats capture:

* **Row count** – total rows in a table.
* **Most common values (MCVs)** – a list of the most frequent distinct values.
* **Histograms** – bucketed distributions of numeric columns.

If a table receives a burst of new rows after the last analysis, the stored statistics become stale. The planner still trusts a histogram that says “10 % of rows have `country = 'DE'`” even though a recent data load increased that fraction to 40 %.

*Mitigation*: Schedule frequent auto‑analyze or use incremental statistics where supported (e.g., PostgreSQL 15’s `CREATE STATISTICS`).

### Correlation Blindness

Traditional estimators treat each predicate independently. In the example above, the optimizer multiplies the selectivity of `c.country = 'DE'` by the selectivity of `o.amount > 1000`. If high‑value orders tend to belong to German customers—a correlation the planner cannot see—the product of independent selectivities dramatically underestimates the true row count.

SQL Server’s **extended statistics** and PostgreSQL’s **multivariate statistics** let you capture pairwise correlation:

```sql
-- PostgreSQL example
CREATE STATISTICS cust_country_amount (dependencies)
ON country, amount
FROM customers;
```

### Histogram Granularity

Histograms divide a column’s value range into a fixed number of buckets (e.g., 100 in PostgreSQL). For heavily skewed data, a single bucket may contain millions of rows, while another bucket holds only a handful. When a predicate falls into the “large” bucket, the planner distributes the bucket’s total count evenly across the bucket range, producing a gross over‑ or under‑estimate.

*Illustration*:

| Bucket | Range          | Row Count |
|--------|----------------|-----------|
| 1      | 0‑10           | 5 000     |
| 2      | 11‑20          | 200       |
| 3      | 21‑30          | 50        |
| …      | …              | …         |

A predicate `amount BETWEEN 12 AND 13` lands in bucket 2, but the planner assumes 100 rows (half of 200) even though the true count might be 2.

### Skew and Heavy‑Tail Distributions

When a column follows a Zipfian or Pareto distribution, a tiny set of values dominates the table. Classic uniform‑or‑Gaussian assumptions lead to severe misestimates. For log‑structured storage engines (e.g., Amazon Redshift), tail‑heavy key distributions can cause *partition pruning* to fail entirely.

### Parameter Sensitivity

Prepared statements and parameterized queries hide literal values from the optimizer. Some engines (PostgreSQL) use generic selectivity defaults (e.g., 0.005 for equality) when the actual value is unknown at plan time. This can be disastrous for high‑selectivity parameters.

## How Optimizers Use Estimates

### Join Order Selection

The optimizer explores a search space of possible join trees. For each candidate, it multiplies the cardinalities of intermediate results to estimate the total number of rows processed. A single bad estimate early in the tree can cascade, inflating the cost of many downstream join orders and causing the optimizer to discard the truly optimal plan.

### Index vs. Sequential Scan Decision

If the estimated number of rows to be fetched is below a threshold (often 5 % of the table), the planner prefers an index scan; otherwise, it chooses a sequential scan. Misestimating a filter that actually returns 30 % of rows as 2 % leads to a costly index lookup for each row.

### Parallelism and Memory Allocation

Parallel workers are allocated based on the estimated size of the data to be processed. Under‑estimation may starve a query of workers, while over‑estimation can spawn unnecessary workers that contend for CPU and memory.

## Mitigation Strategies

### Statistics Maintenance

* **Frequent auto‑analyze** – configure PostgreSQL’s `autovacuum_analyze_scale_factor` and `autovacuum_analyze_threshold` to trigger more often on high‑write tables.
* **Incremental statistics** – PostgreSQL 15+ supports `ALTER TABLE … ALTER COLUMN … SET STATISTICS INCREMENTAL`.
* **Targeted manual ANALYZE** – run `ANALYZE table_name(column_name)` after bulk loads.

### Histograms and Extended Statistics

* **Multi‑column statistics** – capture correlations between columns that are frequently queried together.
* **Higher‑resolution histograms** – increase `default_statistics_target` (PostgreSQL) or `STATISTICS` option (SQL Server) for columns with skewed distributions.
* **Top‑N histograms** – some engines let you store a separate histogram for the most common values, improving selectivity for hot keys.

### Query Hints and Plan Guides

When the optimizer’s estimate is repeatedly wrong, you can override it:

```sql
-- SQL Server example: force a hash join
SELECT /*+ HASH_JOIN(o, c) */ *
FROM orders o
JOIN customers c ON o.customer_id = c.id
WHERE c.country = 'DE' AND o.amount > 1000;
```

*Use sparingly*: hints lock the optimizer into a specific plan, bypassing future improvements.

### Adaptive Query Execution (AQE)

Modern engines (e.g., Apache Spark, PostgreSQL 14+ with `adaptive` planner) can adjust the plan mid‑execution when runtime statistics diverge from estimates. AQE monitors actual row counts after each stage and can:

* Switch from a nested loop to a hash join.
* Re‑partition data to balance worker load.
* Abort a bad plan and fall back to a safer alternative.

### Sample‑Based Estimation

Instead of relying solely on pre‑computed stats, some systems (e.g., Snowflake) sample the data at runtime for predicates that lack accurate statistics. This approach trades a small amount of extra I/O for dramatically better selectivity estimates.

### Application‑Level Techniques

* **Parameter sniffing control** – in SQL Server, use `OPTION (OPTIMIZE FOR UNKNOWN)` to avoid over‑fitting to a particular parameter value.
* **Data model redesign** – denormalize or add covering indexes for columns that are frequently filtered together, reducing the need for the optimizer to estimate complex joins.

## Key Takeaways

- Cardinality estimation is the linchpin of cost‑based optimization; inaccurate estimates cascade into poor join orders, wrong access paths, and suboptimal parallelism.
- The most common error sources are stale statistics, lack of correlation awareness, coarse histograms, and skewed data distributions.
- Regular statistics maintenance, higher‑resolution histograms, and **extended (multivariate) statistics** dramatically improve estimate quality.
- When statistics cannot keep up, consider **adaptive query execution**, **runtime sampling**, or targeted **query hints** as safety nets.
- Monitoring tools (e.g., `EXPLAIN (ANALYZE, BUFFERS)` in PostgreSQL) should be part of a feedback loop to detect recurring misestimates and trigger corrective actions.

## Further Reading

- [PostgreSQL documentation on planner statistics](https://www.postgresql.org/docs/current/planner-stats.html)  
- [SQL Server cardinality estimator overview (Microsoft Docs)](https://learn.microsoft.com/en-us/sql/relational-databases/query-processing/cardinality-estimator?view=sql-server-ver16)  
- [Google research paper “The Case for Adaptive Query Execution”](https://research.google/pubs/pub37624/)  
- [Citus Data blog: “The Truth About PostgreSQL’s Cardinality Estimator”](https://www.citusdata.com/blog/2020/02/05/the-truth-about-postgresqls-cardinality-estimator/)  

---