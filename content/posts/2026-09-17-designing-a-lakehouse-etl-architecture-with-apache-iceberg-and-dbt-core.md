---  
title: "Designing a Lakehouse ETL Architecture with Apache Iceberg and dbt Core"  
date: "2026-09-17T12:00:56.605"  
draft: false  
tags: ["data-engineering","lakehouse","apache-iceberg","dbt","etl"]  
description: "A practical guide to building a modern lakehouse ETL pipeline using Apache Iceberg and dbt Core, covering schema evolution, partitioning, and data quality."  
summary: "Learn how to design a scalable lakehouse ETL architecture with Apache Iceberg and orchestrate transformations using dbt Core, ensuring schema evolution and reliable data pipelines."  
showToc: true  
TocOpen: false  
cover:  
  image: "/images/covers/2026-09-17-designing-a-lakehouse-etl-architecture-with-apache-iceberg-and-dbt-core.svg"  
  alt: "Diagram of a lakehouse ETL pipeline with Iceberg storage and dbt transformation layer"  
  caption: ""  
  relative: false  
---  

> **TL;DR** — Apache Iceberg brings table‑like features (schema evolution, time‑travel, hidden partitioning) to object storage, and dbt Core lets you model transformations as SQL. Together they enable a modular, version‑controlled lakehouse ETL that is both scalable and observable.  

A lakehouse merges the best of data warehouses and data lakes: you keep raw files in cheap object storage (S3, GCS, Azure Blob) while gaining schema enforcement, ACID transactions, and query‑engine optimizations. Apache Iceberg is the open‑table format that makes this possible, and dbt Core provides a lightweight, code‑first way to transform data using SQL and Jinja. In this post we’ll walk through a complete ETL architecture that lands raw data into Iceberg tables, then uses dbt to shape, test, and document the analytics layer. We’ll cover Iceberg fundamentals, dbt integration patterns, production‑ready architecture, performance tuning, and practical takeaways you can adopt today.  

## Why a Lakehouse ETL?

Traditional ETL pipelines often rely on a central data warehouse (e.g., Snowflake, Redshift) that ingests data via costly extract‑load steps. When data volumes grow, costs rise sharply and flexibility shrinks. A lakehouse flips the model: raw landing zones stay in object storage, and the “warehouse” is simply a query engine (Trino, Spark, Dremio, etc.) that reads the open table format.  

Key benefits:

- **Cost efficiency** – store raw logs, events, and Parquet files on commodity storage; only pay for compute when you query.  
- **Schema evolution** – add or rename columns without breaking downstream consumers; Iceberg tracks changes automatically.  
- **Time‑travel** – revert to prior states for debugging or compliance.  
- **Vendor neutrality** – the same Iceberg tables can be read by Spark, Flink, Trino, or dbt (via the Iceberg adapter).  

These advantages make the lakehouse an attractive baseline for modern analytics, especially when you want to keep engineering overhead low and leverage existing SQL skills.  

## Apache Iceberg Fundamentals  

### Table properties and schema evolution  

Iceberg tables are defined by a manifest list that points to data files (Parquet, Avro, ORC). Metadata lives in a small set of files (`metadata/manifest-list.json`, `metadata/manifest.json`) stored alongside your data. When you alter a table—add a column, change a type, or drop a column—Iceberg writes a new version of the metadata while keeping old data files readable. Downstream query engines see the updated schema without needing a full rewrite.  

Example: creating an Iceberg table in a Trino session  

```sql
CREATE TABLE iceberg.cust_events
WITH (format = 'parquet')
AS SELECT * FROM raw.cust_events;
```  

After creation, you can add a column:  

```sql
ALTER TABLE iceberg.cust_events ADD COLUMN region STRING;
```  

The change is instantaneous; any query that references `region` will see the new column, while older queries continue to work on the previous schema version.  

### Partitioning and hidden partitioning  

Iceberg supports **hidden partitioning**: the partition columns are stored separately from the data files, and the format decides how to prune partitions based on filter pushdown. You can define partitioning initially and later change the scheme (e.g., from daily to monthly) without rewriting data.  

```sql
CREATE TABLE iceberg.orders
WITH (partitioning = ARRAY['order_date'])
AS SELECT * FROM raw.orders;
```  

When you later issue `ALTER TABLE … SET partitioning ARRAY['order_month']`, Iceberg rewrites only the necessary manifest entries, leaving the underlying files untouched.  

### Time‑travel and rollback  

Each commit creates a new snapshot identified by a unique `snapshot-id`. You can query any prior snapshot:  

```sql
SELECT * FROM iceberg.orders FOR SYSTEM_TIME AS OF '2025-07-15';
```  

This is invaluable for auditing, bug fixes, or “what‑if” analysis.  

## dbt Core as the Transformation Layer  

dbt (data build tool) turns SQL files into version‑controlled pipelines. With dbt Core you define models in `.sql` files, write tests, and generate documentation—all within a Git repository. The `dbt‑iceberg` adapter lets dbt read/write Iceberg tables directly, so your transformation SQL runs against the same tables that Spark or Trino see.  

### Model definition and Jinja  

A typical dbt model might look like this:  

```sql
-- models/stg_cust_events.sql
with source as (
    select *
    from {{ source('raw', 'cust_events') }}
),
renamed as (
    select
        event_id,
        user_id,
        event_type,
        cast(event_timestamp as timestamp) as event_ts,
        region
    from source
)
select *
from renamed;
```  

The `{{ source('raw', 'cust_events') }}` macro references the Iceberg table defined in your dbt `profiles.yml` or via the `iceberg` catalog.  

### Tests and data quality  

dbt’s test framework runs assertions after each model execution. Example tests:  

```yaml
# tests/stg_cust_events.yml
- not_null:
    config:
      column: event_id
- unique:
    config:
      column: event_id
- accepted_values:
    config:
      column: event_type
      values: ['click', 'view', 'purchase']
```  

If a test fails, dbt aborts the run and surfaces the issue, enabling CI/CD gates.  

### The `iceberg` adapter  

Install the adapter via pip:  

```bash
pip install dbt-iceberg
```  

Configure your `profiles.yml`:  

```yaml
your_profile:
  target: dev
  outputs:
    dev:
      type: iceberg
      warehouse: s3://my-bucket/iceberg
      s3_endpoint: https://s3.amazonaws.com
      region: us-east-1
      schema: analytics
```  

dbt will create and manage Iceberg tables under the specified warehouse path, handling schema evolution automatically.  

## Architecture Overview  

### End‑to‑end data flow  

1. **Ingestion** – raw logs, event streams, or batch dumps land in a landing‑zone bucket (e.g., `s3://company‑raw/`).  
2. **Iceberg table registration** – a one‑time SQL or dbt command registers the directory as an Iceberg table, specifying initial partitioning and format.  
3. **dbt modeling** – dbt reads the Iceberg table as a source, applies transformations, and writes results back to a separate Iceberg schema (e.g., `analytics`).  
4. **Consumption** – downstream analytics engines (Trino, Superset, Looker) query the `analytics` schema; they benefit from Iceberg’s metadata (partition pruning, statistics).  
5. **Orchestration** – Airflow, Prefect, or Dagster trigger the ingestion step, then invoke `dbt run` as a downstream task. Failures in dbt tests stop the pipeline, preventing bad data from propagating.  

### Orchestration with Airflow  

A minimal DAG might look like:  

```python
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "data-eng",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    "lakehouse_etl",
    start_date=datetime(2025, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    default_args=default_args,
) as dag:

    ingest = BashOperator(
        task_id="ingest_raw",
        bash_command="aws s3 sync s3://company‑raw/ s3://landing‑zone/ --delete",
    )

    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command="dbt run --profiles-dir /dbt/profiles",
    )

    ingest >> dbt_run
```  

The DAG ensures that raw data lands before transformations run, and that a failed dbt run does not silently corrupt downstream dashboards.  

### Patterns in Production  

#### Schema evolution workflow  

When a new column is needed:

1. Add the column to the source Iceberg table (e.g., `ALTER TABLE … ADD COLUMN`).  
2. Update the dbt model to include the new field, possibly with a default or transformation.  
3. Run `dbt debug` and `dbt test` to confirm the schema change propagates without breaking existing models.  

Because Iceberg tracks schema versioning, downstream consumers can continue reading the old version until they opt‑in to the new one.  

#### Incremental builds with dbt  

dbt’s `incremental` models let you process only new or changed records. Combined with Iceberg’s hidden partitioning, you can define an `on` clause that uses a timestamp column:  

```sql
{{ config(materialized='incremental', unique_key='event_id') }}

with stg as (
    select *
    from {{ source('raw', 'cust_events') }}
),
filtered as (
    select *
    from stg
    {% if is_incremental() %}
    where event_ts > (select max(event_ts) from {{ this }})
    {% endif %}
)
select *
from filtered;
```  

Each run processes only records newer than the last max timestamp, reducing compute cost while Iceberg maintains the full history via time‑travel.  

#### Data‑quality gate with dbt tests  

Define tests that check for nulls, uniqueness, and domain constraints. Integrate these tests into your CI pipeline (GitHub Actions, GitLab CI) so that every PR is validated against the Iceberg table before merging.  

#### Optimizing file size and compaction  

Iceberg provides an `optimize` operation that rewrites small files into larger, more query‑friendly Parquet files. You can schedule this as a nightly job:  

```sql
CALL system.iceberg.optimize('iceberg.orders', max_file_size='128MB');
```  

dbt can trigger this after a successful run via a post‑hook SQL command, ensuring that the table stays performant as data volume grows.  

## Performance Tuning  

### Partitioning strategy  

Choose partitioning keys that align with common query filters. For event‑driven data, partitioning by `event_date` (daily) often yields good pruning. For transactional data, consider monthly or quarterly partitions if the query pattern aggregates over longer windows.  

### Bucketing and clustering  

Iceberg supports **bucketing** (hash‑based distribution) combined with **clustering** (statistics‑driven). Example:  

```sql
CREATE TABLE iceberg.orders
WITH (bucketing = ARRAY['order_id'], clustering = ARRAY['order_date'])
AS SELECT * FROM raw.orders;
```  

Bucketing reduces the amount of data scanned for equi‑joins, while clustering leverages min/max statistics to skip irrelevant files.  

### File size targets  

Aim for Parquet files in the 128 MB–1 GB range. Iceberg’s `optimize` command can auto‑target this range. Too many small files increase metadata overhead; too large files hinder parallelism.  

## Monitoring and Observability  

- **Iceberg metrics** – many query engines expose Iceberg metrics (file counts, snapshot age). Export them to Prometheus and alert on unusually old snapshots or sudden spikes in file count.  
- **dbt run logs** – dbt emits concise JSON logs that include model execution time, test results, and any errors. Integrate these with your log aggregation system (ELK, Loki).  
- **Data‑lineage** – dbt generates a DAG of model dependencies; visualizing this alongside Iceberg table versions gives end‑to‑end traceability from raw source to analytics view.  

## Key Takeaways  

- Apache Iceberg adds table‑like features (schema evolution, time‑travel, hidden partitioning) to object storage, making it a perfect foundation for a lakehouse.  
- dbt Core provides a Git‑friendly, test‑driven way to transform data using SQL; the `dbt‑iceberg` adapter bridges dbt and Iceberg tables seamlessly.  
- An end‑to‑end architecture lands raw data into Iceberg tables, then uses dbt models to produce curated analytics schemas, all orchestrated by Airflow, Prefect, or similar tools.  
- Production patterns such as incremental builds, schema‑evolution workflows, and automated compaction keep pipelines efficient and resilient.  
- Performance hinges on thoughtful partitioning, bucketing, and regular file‑size optimization; monitoring Iceberg metrics and dbt test results ensures early detection of issues.  
- Combining Iceberg’s metadata‑driven query pruning with dbt’s test suite yields a trustworthy, observable data platform that scales without costly warehouse licensing.  

## Further Reading  

- [Apache Iceberg documentation](https://iceberg.apache.org/docs/) – official guides on table creation, schema evolution, and optimization.  
- [dbt Core docs](https://docs.getdbt.com/docs/) – model configuration, testing, and adapter reference.  
- [dbt‑iceberg adapter repository](https://github.com/dbt-labs/dbt-iceberg) – installation, profiling, and troubleshooting tips.  
- [Trino Iceberg connector overview](https://trino.io/docs/current/connector/iceberg.html) – query engine integration details.  
- [Lakehouse architecture best practices](https://databricks.com/blog/2023/01/31/lakehouse-architecture-best-practices.html) – high‑level patterns from the Databricks team.  

---