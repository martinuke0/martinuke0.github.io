---
title: "Implementing Schema Evolution in Apache Iceberg ETL with Avro Compatibility"
date: "2026-09-17T21:01:21.446"
draft: false
tags: ["apache-iceberg", "avro", "etl", "schema-evolution", "data-lakehouse", "data-engineering"]
description: "Learn how to implement robust schema evolution in Apache Iceberg ETL pipelines while maintaining backward and forward compatibility with Avro records."
summary: "A practical guide to implementing schema evolution in Apache Iceberg ETL pipelines using Avro compatibility guarantees, covering the mechanics, architecture patterns, and production pitfalls."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-17-implementing-schema-evolution-in-apache-iceberg-etl-with-avro-compatibility.svg"
  alt: "Apache Iceberg and Avro schema evolution diagram showing data lakehouse architecture"
  caption: ""
  relative: false
---

> **TL;DR** — Apache Iceberg provides first-class schema evolution support that aligns naturally with Avro's compatibility model, but the interaction between the two introduces subtle gotchas around column mapping, partition evolution, and snapshot isolation. This post walks through the mechanics, a production-grade architecture pattern, and the pitfalls that will burn you at scale.

## Why Schema Evolution Is a First-Class Problem in Data Lakes

In traditional relational databases, ALTER TABLE is a solved problem. In data lakehouses, schema changes propagate through files that were written months ago, and every reader—whether a Spark job, a Flink pipeline, or a Presto query—must interpret those files correctly. A single malformed schema transition can silently corrupt downstream analytics or outright fail a production ETL job.

The stakes are concrete. Consider a retail data platform where a `customer_events` table accumulates billions of records across hundreds of partitions. When the product team adds a `loyalty_tier` column to the event payload, the ETL pipeline that ingests events from Kafka must:

1. Write new files with the expanded schema.
2. Make those files readable by existing queries that don't reference `loyalty_tier`.
3. Ensure that backfills and historical re-processing don't break on the new column.
4. Maintain exactly-once semantics across the transition.

Apache Iceberg was built to solve precisely this class of problems. Its table format tracks schema versions as part of the table metadata, and every snapshot records which schema was used to write it. Avro, meanwhile, provides the schema resolution rules that define how a reader schema reconciles with a writer schema. Together, they form a powerful compatibility framework—but only if you understand how they interact.

## How Iceberg Manages Schema Versions

Every Iceberg table maintains an ordered list of schemas, each identified by a unique integer ID. When you add a column, Iceberg appends a new schema to this list and records a mapping from the new schema to the previous one. This mapping is what allows readers using an older schema to correctly interpret data written with a newer schema.

```
Schema ID 1: {id: string, name: string, amount: double}
Schema ID 2: {id: string, name: string, amount: double, loyalty_tier: string}
```

When a query specifies a read schema of ID 1, Iceberg uses the stored column ID mapping to project the `loyalty_tier` field out of the read plan. The underlying Parquet or ORC files contain the data, but Iceberg's manifest entries know which schema was used to write each file and how to resolve it to the query schema.

This is fundamentally different from Hive's schema-on-read approach, where the metastore schema is the single source of truth and files are expected to conform to it. Iceberg's decoupling of write schema from read schema is what makes zero-copy schema evolution possible.

### The Role of Column IDs

One detail that catches teams off guard: Iceberg uses **column IDs**, not names, for schema resolution. When you add a column, Iceberg assigns it a new ID. If you later rename the column, the ID stays the same, and the data remains accessible. But if you delete and re-add a column with the same name, it gets a different ID, and the data becomes orphaned.

```python
# Adding a column via PyIceberg
from pyiceberg.catalog import load_catalog

catalog = load_catalog("default")
table = catalog.load_table("prod.customer_events")

# This generates a new schema with a new column ID for loyalty_tier
new_schema = table.update_schema()
new_schema = new_schema.add_column("loyalty_tier", "string", required=False)
new_schema.commit()
```

This is why treating Iceberg columns like relational columns—where name is the primary identifier—is a common source of bugs in production.

## Avro Compatibility Rules and Iceberg's Assumptions

Avro defines four compatibility directions:

- **Backward**: new readers can read old data (writers are old, readers are new).
- **Forward**: old readers can read new data (writers are new, readers are old).
- **Full**: both backward and forward.
- **None**: no guarantees.

Iceberg's schema evolution is designed around Avro's compatibility model, but with an important caveat: Iceberg assumes **column ID stability**, which maps to Avro's field index matching rather than name matching. When Iceberg resolves a writer schema to a reader schema, it matches fields by their ID, not their name. This means:

- Adding a field at the end of a struct is always compatible (forward-compatible for old readers).
- Removing a field is backward-compatible for old readers if the field ID is preserved but marked as unused.
- Renaming a field is safe because Iceberg uses IDs internally.
- Reordering fields is safe for the same reason.

However, type promotion follows Avro's rules: `int` can be promoted to `long`, `long` to `float`, `float` to `double`, and `string` to `Char` or `Varchar`. Widening types is safe; narrowing is not.

```json
// Writer schema (Avro)
{
  "type": "record",
  "name": "CustomerEvent",
  "fields": [
    {"name": "id", "type": "string"},
    {"name": "amount", "type": "double"},
    {"name": "loyalty_tier", "type": ["null", "string"], "default": null}
  ]
}

// Reader schema (Avro) - older version without loyalty_tier
{
  "type": "record",
  "name": "CustomerEvent",
  "fields": [
    {"name": "id", "type": "string"},
    {"name": "amount", "type": "double"}
  ]
}
```

In this scenario, the Avro resolver will silently drop `loyalty_tier` when reading, and Iceberg's column ID mapping ensures the physical projection is correct. The reader never sees the field, and no error is thrown.

## Architecture Pattern: Schema Evolution in a Production Iceberg ETL Pipeline

Here's the architecture I've used in production environments handling multi-terabyte Iceberg tables with frequent schema changes. The key insight is to decouple schema governance from the ETL execution layer.

### Components

1. **Schema Registry Service**: A lightweight service (often backed by a GitOps repository) that stores canonical Avro schemas with version numbers and compatibility policies. Every schema change goes through a pull request that runs automated compatibility checks against the previous version using a library like `avro-compatibility`.

2. **Iceberg Table Operator**: A controller (or scheduled job) that translates approved schema changes into Iceberg schema updates. This operator uses the column ID mapping to ensure that the Iceberg schema version graph remains consistent with the Avro schema registry.

3. **ETL Runner**: The Spark or Flink job that reads from source topics, applies transformations, and writes to Iceberg. The runner loads the Avro schema from the registry, validates incoming records against it, and uses Iceberg's `UpdateSchema` API to apply changes.

4. **Read Model Validator**: A pre-query hook that checks whether the requested read schema is compatible with the latest write schema. This catches incompatibilities before they hit the query engine.

### The Write Path

```python
from pyiceberg.catalog import load_catalog
from pyiceberg.schema import Schema
from pyiceberg.types import NestedField, StringType, DoubleType, OptionalType
from avro import schema as avro_schema
from avro.datafile import DataFileReader, DataFileWriter
from avro.io import DatumWriter

# Load the current Avro schema from the registry
current_avro = avro_schema.Parse(open("schemas/customer_event_v2.avsc").read())

# Load the Iceberg table
catalog = load_catalog("prod")
table = catalog.load_table("customer_events")

# Check if schema needs updating
iceberg_schema = table.schema()
if not schemas_are_compatible(current_avro, iceberg_schema):
    # Apply Iceberg schema evolution
    update = table.update_schema()
    for field in extract_new_fields(current_avro, iceberg_schema):
        update = update.add_column(field.name, field.type, field.required)
    update.commit()

# Write new data using the evolved schema
with table.new_write() as write:
    for record in kafka_consumer:
        # Validate against Avro schema before writing
        validate_avro(record, current_avro)
        write.write(record)
```

### The Read Path

On the read side, the pattern is simpler but equally important. Iceberg handles the projection automatically, but you should still enforce compatibility at the query layer:

```python
# Spark read with schema enforcement
df = spark.read.format("iceberg") \
    .option("schema-evolution-mode", "resolve-to-latest") \
    .table("prod.customer_events") \
    .select("id", "amount", "event_timestamp")

# The query uses an older schema subset
# Iceberg projects only the requested columns
# Fields added after the query's schema version are silently ignored
```

The `schema-evolution-mode` option is critical here. Setting it to `resolve-to-latest` tells Spark to use the latest schema for reading, which is safe for forward compatibility but can surface new columns unexpectedly. For strict backward compatibility, use `resolve-to-oldest` or explicitly specify the read schema.

## Common Pitfalls in Production

### Pitfall 1: Partition Evolution Breaks Snapshot Isolation

Iceberg supports partition evolution—changing how data is partitioned without rewriting existing files. However, this interacts poorly with schema evolution if you're also changing partition columns. When you add a new partition field, Iceberg creates a new partition spec, and files written under the old spec are associated with the old spec ID. If your ETL job assumes a single partition spec, you'll get silent data loss or duplicate writes.

```python
# Dangerous: changing partition spec during schema evolution
table.update_spec()
    .add_field("loyalty_tier")  # New partition field
    .commit()

# Now files written before this commit use spec ID 0
# Files written after use spec ID 1
# Queries must handle both specs, or data becomes invisible
```

The fix is to stage partition changes separately from schema changes. Run a full table rewrite with the new partition spec before deploying any ETL jobs that use it.

### Pitfall 2: Avro Default Values and Iceberg Nullability Mismatches

Avro uses default values to handle missing fields during schema resolution. Iceberg uses nullability. If you add a field with an Avro default of `"standard"` but declare it as required in Iceberg, the compatibility check passes at the Avro level but Iceberg will reject null values on write. Conversely, if you declare it as optional in Iceberg but don't provide an Avro default, old readers will get null instead of the default value.

Always align the Avro default with the Iceberg nullability declaration:

| Avro Default | Iceberg Required | Compatible? |
|---|---|---|
| `"standard"` | `false` (optional) | ✅ Yes |
| `"standard"` | `true` (required) | ❌ No—old readers get default, new readers expect non-null |
| `null` | `false` (optional) | ✅ Yes |
| No default | `true` (required) | ❌ No—old readers can't supply a value |

### Pitfall 3: Nested Field Evolution and Column ID Mapping

Iceberg's column ID assignment is depth-first, left-to-right. When you add a nested field inside a struct, the ID assignment depends on the current schema structure. If two teams independently add nested fields to the same struct in different branches, the ID assignments can diverge, and the merge will produce conflicting mappings.

```python
# Team A adds nested_field_a inside address
table.update_schema()
    .add_column("address.nested_field_a", "string")
    .commit()

# Team B adds nested_field_b inside address (merged later)
table.update_schema()
    .add_column("address.nested_field_b", "string")
    .commit()

# The resulting schema has IDs assigned in merge order
# If the merge order differs, the ID mapping changes
# This breaks Avro compatibility because Avro uses field indices
```

The mitigation is to use a centralized schema registry that serializes all schema changes and assigns IDs deterministically.

### Pitfall 4: Snapshot Commits and Concurrent Schema Changes

Iceberg's snapshot isolation means that schema changes are atomic at the commit level. But if two ETL jobs try to evolve the schema concurrently, one commit will succeed and the other will fail with a `CommitStateUnknownException`. In practice, this manifests as a job failure that requires manual intervention to retry the schema update.

Use a distributed lock (Redis, ZooKeeper, or a database row-level lock) around schema evolution operations in your ETL pipeline. The lock should cover both the schema check and the commit, not just the commit itself.

## Monitoring and Observability

Schema evolution is invisible by design, which makes it hard to monitor. You need explicit observability:

- **Schema version tracking**: Log the Iceberg schema ID used by every write operation. This lets you reconstruct the schema history for any table.
- **Compatibility check results**: Store the output of every Avro compatibility check in your schema registry. When a query fails, you can quickly determine whether it's a schema issue.
- **Column access patterns**: Track which columns are actually queried. Columns that are added but never accessed may indicate unnecessary schema bloat or a deprecated field that should be removed.

```sql
-- Query to see schema history for a table
SELECT schema_id, schema_text, added_timestamp
FROM iceberg_table_schemas
WHERE table_name = 'customer_events'
ORDER BY added_timestamp DESC;
```

## Key Takeaways

- Iceberg's column ID-based schema resolution is more robust than name-based matching, but it requires disciplined ID management and a centralized schema registry to avoid conflicts.
- Avro compatibility rules map cleanly to Iceberg's evolution model for flat schemas, but nested structures and partition evolution introduce edge cases that need explicit handling.
- Always stage partition spec changes separately from column schema changes to avoid snapshot isolation issues and invisible data.
- Align Avro default values with Iceberg nullability declarations—mismatches here are the most common source of silent data corruption.
- Use distributed locking around schema evolution commits in concurrent ETL environments to prevent `CommitStateUnknownException` failures.
- Instrument schema version tracking and compatibility check results as first-class observability signals, not afterthoughts.

## Further Reading

- [Apache Iceberg Specification — Schema Evolution](https://iceberg.apache.org/docs/latest/)
- [Avro Schema Resolution Documentation](https://avro.apache.org/docs/current/spec.html#schema_resolution)
- [Netflix's Guide to Apache Iceberg at Scale](https://netflixtechblog.com/open-sourcing-apache-iceberg-part-1-7c8e81d4fa5c)
- [Tabular: Iceberg Table Format Deep Dive](https://tabular.io/blog/iceberg-table-format-deep-dive)
- [PyIceberg Documentation — Schema Management](https://py.iceberg.apache.org/)
- [Confluent Schema Registry Compatibility Rules](https://docs.confluent.io/platform/current/schema-registry/avrocompatible.html)
- [Apache Iceberg Partition Evolution](https://iceberg.apache.org/docs/latest/spec/#partition-evolution)

---