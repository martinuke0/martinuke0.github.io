---
title: "Understanding MDM Raw Read: Concepts, Implementation, and Best Practices"
date: "2026-03-31T16:33:48.203"
draft: false
tags: ["MDM", "Data Integration", "Master Data Management", "ETL", "Data Governance"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is “Raw Read” in MDM?](#what-is-raw-read-in-mdm)  
   2.1 [Raw vs. Processed Views](#raw-vs-processed-views)  
   2.2 [Why Raw Read Matters](#why-raw-read-matters)  
3. [Typical Use‑Cases for Raw Read](#typical-use-cases-for-raw-read)  
   3.1 [Data Migration & Modernization](#data-migration--modernization)  
   3.2 [Audit & Forensic Analysis](#audit--forensic-analysis)  
   3.3 [Machine Learning & Advanced Analytics](#machine-learning--advanced-analytics)  
4. [Technical Foundations](#technical-foundations)  
   4.1 [MDM Architecture Overview](#mdm-architecture-overview)  
   4.2 [Storage Layers: Staging, Hub, and Raw Tables](#storage-layers-staging-hub-and-raw-tables)  
   4.3 [Metadata and Versioning](#metadata-and-versioning)  
5. [Implementing a Raw Read: Step‑by‑Step Guide](#implementing-a-raw-read-step-by-step-guide)  
   5.1 [Identify the Source System(s)](#identify-the-source-systems)  
   5.2 [Configure the Raw Data Model](#configure-the-raw-data-model)  
   5.3 [Extracting Raw Records via API or Direct DB Access](#extracting-raw-records-via-api-or-direct-db-access)  
   5.4 [Sample Code – Java (JDBC) Example](#sample-code---java-jdbc-example)  
   5.5 [Sample Code – Python (REST) Example](#sample-code---python-rest-example)  
   5.6 [Loading Into a Data Lake or Warehouse](#loading-into-a-data-lake-or-warehouse)  
6. [Performance Considerations](#performance-considerations)  
   6.1 [Partitioning & Indexing Strategies](#partitioning--indexing-strategies)  
   6.2 [Incremental vs. Full Raw Reads](#incremental-vs-full-raw-reads)  
   6.3 [Handling Large BLOB/CLOB Columns](#handling-large-blobclob-columns)  
7. [Data Quality and Governance Implications](#data-quality-and-governance-implications)  
   7.1 [Retention Policies](#retention-policies)  
   7.2 [PII Masking & Encryption](#pii-masking--encryption)  
   7.3 [Audit Trails and Compliance](#audit-trails-and-compliance)  
8. [Best Practices Checklist](#best-practices-checklist)  
9. [Common Pitfalls and How to Avoid Them](#common-pitfalls-and-how-to-avoid-them)  
10. [Conclusion](#conclusion)  
11. [Resources](#resources)  

---

## Introduction

Master Data Management (MDM) has become a cornerstone of modern data architectures. Organizations rely on a single, trusted view of core entities—customers, products, suppliers, assets—to drive operational efficiency, analytics, and regulatory compliance. While the “golden record” often steals the spotlight, the **raw data** that flows into an MDM hub holds equal strategic value. 

A **Raw Read** is the act of retrieving that untouched, source‑originated data directly from the MDM repository, bypassing any transformation, enrichment, or survivorship logic that normally produces the golden view. Raw reads empower data engineers, auditors, and data scientists to:

* Re‑create historical states for migration projects.  
* Perform forensic investigations when data anomalies surface.  
* Feed machine‑learning pipelines with the most granular, lineage‑preserved records.

In this article we’ll explore the concept of MDM Raw Read in depth, walk through real‑world scenarios, and provide a practical implementation guide—including code snippets in Java and Python. By the end, you’ll have a clear roadmap for integrating raw reads into your data ecosystem while respecting performance, security, and governance constraints.

---

## What Is “Raw Read” in MDM?

### Raw vs. Processed Views

| Aspect | Processed (Golden) View | Raw View |
|--------|------------------------|----------|
| **Data State** | Consolidated, de‑duplicated, enriched, survivorship applied. | Exact copy of inbound payloads, with source system identifiers. |
| **Schema** | Unified, often abstracted (e.g., Customer entity). | Source‑specific columns, staging fields, change‑type flags. |
| **Purpose** | Operational reporting, downstream applications, UI consumption. | Auditing, re‑processing, data science, migration. |
| **Latency** | Near‑real‑time after business rules execution. | Immediate after source ingestion (often within seconds). |

In many MDM platforms (Informatica MDM, Riversand, Reltio, SAP MDG), the raw layer is persisted in dedicated tables—sometimes called **Staging**, **Raw**, or **Landing** tables. These tables capture every inbound transaction (INSERT, UPDATE, DELETE) along with a **system change number (SCN)**, **timestamp**, and **source system key**.

### Why Raw Read Matters

1. **Regulatory Compliance** – Regulations such as GDPR, CCPA, and Basel III require organizations to retain the original source data for a defined period. A raw read provides the immutable record needed for audits.  
2. **Data Lineage** – Understanding how a golden record was derived from which source feed is essential for impact analysis. Raw reads expose the full lineage chain.  
3. **Re‑processing Flexibility** – When business rules evolve, you may need to re‑run transformations on historic data without re‑extracting from upstream systems. Raw reads allow you to replay the pipeline.  
4. **Advanced Analytics** – Machine‑learning models often benefit from raw attributes (e.g., original address strings, free‑form notes) that are lost during standard cleansing.  

---

## Typical Use‑Cases for Raw Read

### Data Migration & Modernization

Legacy MDM installations may be decommissioned in favor of cloud‑native platforms (e.g., Snowflake, Azure Synapse). A raw read serves as the **single source of truth** for migration, ensuring that no inbound transaction is omitted.

### Audit & Forensic Analysis

When a compliance breach is suspected, auditors need to verify the exact data that entered the MDM hub on a specific date. Raw reads provide an immutable snapshot, enabling root‑cause analysis without relying on potentially altered golden records.

### Machine Learning & Advanced Analytics

Data scientists often experiment with feature engineering on the **original** payloads. For example, sentiment analysis on free‑text comments, or address parsing on raw strings before standardization. Raw reads give them the unfiltered material they need.

---

## Technical Foundations

### MDM Architecture Overview

A typical MDM solution comprises three logical layers:

1. **Source Integration Layer** – Connectors, adapters, and batch jobs that pull data from ERP, CRM, flat files, etc.  
2. **Hub (Core) Layer** – Stores the master entities, survivorship logic, and the golden view.  
3. **Presentation / Consumption Layer** – APIs, UI, and downstream feeds that expose the consolidated data.

The **Raw Layer** sits between the Source Integration Layer and the Hub. It is often implemented as a set of relational tables mirroring the source schema, plus a few system columns (e.g., `RAW_ID`, `SOURCE_SYSTEM`, `CHANGE_TYPE`, `LOAD_DTS`).

### Storage Layers: Staging, Hub, and Raw Tables

```text
[Source System] --> [Staging Tables] --> [Raw Tables] --> [Hub Tables] --> [Golden View]
```

* **Staging** – Temporary area for pre‑validation (e.g., schema checks, duplicate detection).  
* **Raw** – Persistent, immutable storage of every inbound record.  
* **Hub** – Consolidated, de‑duplicated master data.

### Metadata and Versioning

Each raw record typically carries:

* `SYSTEM_CHANGE_NUMBER` – Monotonically increasing identifier.  
* `EFFECTIVE_FROM` / `EFFECTIVE_TO` – Temporal validity windows.  
* `SOURCE_ROW_ID` – Original primary key from the source system.  
* `OPERATION_TYPE` – `I` (Insert), `U` (Update), `D` (Delete).  

These columns enable **point‑in‑time** reconstruction of any entity’s state.

---

## Implementing a Raw Read: Step‑by‑Step Guide

Below is a practical roadmap you can follow regardless of the MDM vendor. Adjust the SQL dialect and API endpoints to match your environment.

### Identify the Source System(s)

1. **Catalog** all inbound feeds (e.g., SAP ERP Customer, Salesforce Account, CSV bulk loads).  
2. Document the **primary key mapping** (e.g., `SAP_CUSTOMER_ID`, `SF_ACCOUNT_ID`).  
3. Determine **frequency** (real‑time, nightly batch).  

### Configure the Raw Data Model

If you are building the raw layer yourself:

```sql
CREATE TABLE mdm_raw_customer (
    raw_id               BIGINT       PRIMARY KEY,
    source_system        VARCHAR(30)  NOT NULL,
    source_row_id        VARCHAR(100) NOT NULL,
    change_type          CHAR(1)      NOT NULL,   -- I/U/D
    load_timestamp       TIMESTAMP    NOT NULL,
    system_change_number BIGINT       NOT NULL,
    payload_json         CLOB         NOT NULL   -- Store the original record as JSON
);
```

*Storing the payload as JSON preserves the exact structure, while additional columns make filtering efficient.*

### Extracting Raw Records via API or Direct DB Access

**Option 1 – Direct Database Query**  
If you have read‑only access to the MDM database, you can query the raw tables directly.

**Option 2 – Vendor‑Provided REST API**  
Many MDM platforms expose a `/raw` endpoint that returns the original payloads. The API usually supports pagination and incremental extraction via `system_change_number`.

### Sample Code – Java (JDBC) Example

```java
import java.sql.*;
import java.time.*;
import java.util.*;

public class MdmRawReadJdbc {
    private static final String URL = "jdbc:postgresql://mdm-host:5432/mdm";
    private static final String USER = "readonly_user";
    private static final String PASS = "securePassword";

    public static void main(String[] args) throws SQLException {
        long startScn = 0L;          // 0 = full load, otherwise incremental
        int batchSize = 5000;

        try (Connection conn = DriverManager.getConnection(URL, USER, PASS)) {
            String sql = "SELECT raw_id, source_system, source_row_id, change_type, " +
                         "load_timestamp, system_change_number, payload_json " +
                         "FROM mdm_raw_customer " +
                         "WHERE system_change_number > ? " +
                         "ORDER BY system_change_number ASC " +
                         "LIMIT ?";

            boolean more = true;
            while (more) {
                try (PreparedStatement ps = conn.prepareStatement(sql)) {
                    ps.setLong(1, startScn);
                    ps.setInt(2, batchSize);
                    try (ResultSet rs = ps.executeQuery()) {
                        int rowCount = 0;
                        while (rs.next()) {
                            long rawId = rs.getLong("raw_id");
                            String sourceSystem = rs.getString("source_system");
                            String sourceRowId = rs.getString("source_row_id");
                            String changeType = rs.getString("change_type");
                            Timestamp ts = rs.getTimestamp("load_timestamp");
                            long scn = rs.getLong("system_change_number");
                            Clob payloadClob = rs.getClob("payload_json");
                            String payload = payloadClob.getSubString(1, (int) payloadClob.length());

                            // Process the raw payload (e.g., write to a data lake)
                            System.out.printf("SCN=%d | %s | %s%n", scn, sourceSystem, changeType);
                            // ... your processing logic here ...

                            startScn = scn; // advance the watermark
                            rowCount++;
                        }
                        more = rowCount == batchSize; // if batch full, assume more rows exist
                    }
                }
            }
        }
    }
}
```

> **Note:** Always use a **read‑only** user and enable row‑level security if your platform supports it.

### Sample Code – Python (REST) Example

```python
import requests
import json
from datetime import datetime

BASE_URL = "https://mdm.example.com/api/v1"
RAW_ENDPOINT = "/raw/customer"
TOKEN = "eyJhbGciOi..."   # OAuth2 bearer token

def get_raw_batch(scn_start: int, page: int = 1, page_size: int = 1000):
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json"
    }
    params = {
        "scn_gt": scn_start,
        "page": page,
        "pageSize": page_size,
        "sort": "system_change_number"
    }
    resp = requests.get(f"{BASE_URL}{RAW_ENDPOINT}", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()

def main():
    scn_watermark = 0
    while True:
        batch = get_raw_batch(scn_watermark)
        records = batch.get("items", [])
        if not records:
            break

        for rec in records:
            scn = rec["system_change_number"]
            payload = rec["payload_json"]
            # Example: write to a local file (or S3, ADLS, etc.)
            filename = f"raw_customer_{scn}.json"
            with open(filename, "w") as f:
                json.dump(payload, f, indent=2)
            scn_watermark = max(scn_watermark, scn)

        if not batch.get("hasMore"):
            break

if __name__ == "__main__":
    main()
```

### Loading Into a Data Lake or Warehouse

After extraction, you typically land the raw JSON payloads into a **data lake** (e.g., Amazon S3, Azure Data Lake Storage) partitioned by `load_date` and `source_system`. From there, tools like **AWS Glue**, **Azure Data Factory**, or **dbt** can transform the raw data into analytical models.

```sql
-- Example: Create an external table in Snowflake over the raw JSON files
CREATE OR REPLACE EXTERNAL TABLE raw_customer_json (
    raw_id               NUMBER,
    source_system        STRING,
    source_row_id        STRING,
    change_type          STRING,
    load_timestamp       TIMESTAMP_TZ,
    system_change_number NUMBER,
    payload              VARIANT
)
WITH LOCATION = @my_stage/raw_customer/
FILE_FORMAT = (TYPE = 'JSON')
PATTERN = '.*\.json';
```

---

## Performance Considerations

### Partitioning & Indexing Strategies

* **Time‑Based Partitioning** – Partition raw tables by `load_timestamp` (e.g., daily). This speeds up point‑in‑time queries and purging.  
* **Composite Index** – `(source_system, source_row_id, system_change_number)` is a common access pattern for incremental reads.  

```sql
CREATE INDEX idx_raw_customer_scndate
ON mdm_raw_customer (system_change_number DESC);
```

### Incremental vs. Full Raw Reads

* **Full Load** – Needed for initial migration; expect high I/O. Use bulk export utilities (e.g., `pg_dump`, `expdp`).  
* **Incremental Load** – Use the `system_change_number` watermark. Schedule every 5‑15 minutes for near‑real‑time pipelines.

### Handling Large BLOB/CLOB Columns

If your raw payload contains large documents (e.g., PDF contracts), store them as **external objects** (S3, Azure Blob) and keep only the reference URL in the raw table. This reduces database size and improves query performance.

---

## Data Quality and Governance Implications

### Retention Policies

Regulations often dictate a **minimum retention period** (e.g., 7 years for financial data). Implement automated purging:

```sql
DELETE FROM mdm_raw_customer
WHERE load_timestamp < CURRENT_DATE - INTERVAL '7' YEAR;
```

Combine with **archival** to a cheaper storage tier before deletion.

### PII Masking & Encryption

If raw payloads contain personally identifiable information (PII), apply:

* **Transparent Data Encryption (TDE)** at rest.  
* **Column‑level masking** for fields like SSN, credit card numbers.  
* **Tokenization** for high‑risk attributes before persisting them.

### Audit Trails and Compliance

Because raw tables are immutable, they serve as the **single source of truth** for audit logs. Ensure that:

* All access is logged (database audit, API gateway logs).  
* Change‑type (`I/U/D`) is captured for each row.  
* A **digital signature** (e.g., SHA‑256 hash) of the payload is stored for non‑repudiation.

---

## Best Practices Checklist

| ✅ | Practice |
|----|----------|
| ✅ | Store raw payloads in an immutable, append‑only table or object store. |
| ✅ | Include a monotonically increasing `system_change_number` for incremental extraction. |
| ✅ | Partition raw tables by load date (daily or hourly) to simplify purging. |
| ✅ | Apply encryption/TDE and field‑level masking for any PII. |
| ✅ | Maintain a separate retention policy distinct from the golden view. |
| ✅ | Use read‑only database users or scoped API tokens for raw reads. |
| ✅ | Document source‑system to raw‑table mapping in a data‑catalog. |
| ✅ | Validate that raw reads reproduce the exact source payload (checksum verification). |
| ✅ | Test incremental pipelines using a “watermark” that survives restarts. |
| ✅ | Include raw data in your data‑lineage metadata (e.g., Apache Atlas, Collibra). |

---

## Common Pitfalls and How to Avoid Them

| Pitfall | Impact | Mitigation |
|---------|--------|------------|
| **Storing raw data in the same tables as the hub** | Accidental overwrites, performance degradation. | Separate schema (`mdm_raw_`) and enforce read‑only permissions on raw tables. |
| **Neglecting to purge old raw data** | Uncontrolled storage growth, cost blow‑out. | Implement automated archival and deletion jobs based on retention policy. |
| **Exposing raw payloads without masking** | GDPR/CCPA violations, data breach risk. | Apply field‑level encryption and tokenization before persisting. |
| **Relying on a single large batch for migration** | Long downtime, high failure probability. | Break migration into incremental windows using `system_change_number`. |
| **Skipping schema evolution handling** | Breaks downstream pipelines when source schema changes. | Store payload as JSON and maintain a version field; use schema‑registry tools (e.g., Confluent Schema Registry). |

---

## Conclusion

Raw reads are the unsung hero of Master Data Management. By preserving every inbound transaction in its original form, they enable compliance, enable data‑lineage visibility, and unlock advanced analytical use‑cases that the polished golden view cannot provide. 

Implementing a robust raw‑read strategy involves:

1. Designing an immutable raw storage layer (tables or object storage).  
2. Capturing essential system metadata (`system_change_number`, timestamps, source keys).  
3. Providing secure, performant extraction mechanisms (SQL, REST, CDC).  
4. Enforcing governance—retention, encryption, audit logging.  

When done correctly, raw reads become a **single source of truth for the truth**—a foundation that supports migration, audit, and innovation without compromising performance or compliance. Adopt the checklist and best‑practice recommendations shared here, and your organization will be well‑positioned to leverage raw data as a strategic asset.

---

## Resources

* [Informatica Master Data Management Documentation – Raw Data Model](https://docs.informatica.com/master-data-management)  
* [Reltan​d MDM Architecture Overview (PDF)](https://www.reltan.com/resources/mdm-architecture-overview.pdf)  
* [Snowflake External Tables Documentation – Working with JSON Files](https://docs.snowflake.com/en/user-guide/external-tables)  
* [AWS Glue – Crawlers and Classifiers for JSON Data](https://aws.amazon.com/glue)  
* [GDPR Article 30 – Records of Processing Activities (Guidance)](https://gdpr.eu/article-30/)  

---