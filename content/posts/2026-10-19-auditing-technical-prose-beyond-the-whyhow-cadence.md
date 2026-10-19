---
title: "Auditing Technical Prose: Beyond the Why/How Cadence"
date: "2026-10-19T03:01:51.189"
draft: false
tags: ["technical-writing", "systems-design", "engineering-leadership", "documentation", "architecture"]
description: "A technical writer’s guide to auditing and replacing the reflexive Why/How cadence with What/Where/When/Who framing that aligns with production architecture."
summary: "A practical check for technical writers and engineering leads to audit question cadences, shift framing toward architectural context, and improve reader engagement on LinkedIn and beyond."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-19-auditing-technical-prose-beyond-the-whyhow-cadence.svg"
  alt: "Technical writer reviewing documentation structure on a laptop"
  caption: ""
  relative: false
---

> **TL;DR** — We audit our technical writing for the reflexive Why/How cadence, replacing it with What-Where-When-Who framing that aligns with production architecture and reader intent.

Technical documentation often falls into a reflexive pattern: every feature introduction begins with “Why we built this” and every API reference ends with “How to use this.” While those questions feel natural, they can flatten architectural depth and obscure the decision logic that matters to engineers building on top of your systems. In this post, we’ll systematically check for that cadence, explore why it limits reader takeaways, and replace it with a framework rooted in what, where, when, and who — anchored to real production tools like Kafka, Postgres, and Airflow.

## Rethinking Question Cadences in Technical Documentation

The typical technical article or service README slides inevitably default to two interrogative patterns. “Why” frames the narrative around intent, but when overused it becomes a retrospective justification that can feel defensive or vague. “How” frames the mechanics, but when it’s the default, readers skim implementation details without internalizing the constraints, trade-offs, or operational realities that give those mechanics meaning.

This cadence matters because engineer audiences on LinkedIn and technical newsletters scan for signals they can act on. A paragraph that opens with “Why we chose Apache Kafka” often settles into a high-level mission statement: “to enable real-time data pipelines.” That’s useful, but it’s also predictable. The reader expects it, and the paragraph rarely adds a new constraint or failure mode. Similarly, “How to publish messages to Kafka” can devolve into a step-by-step list that, while correct, divorces the steps from the why-not, the when-to-throttle, and the where-the-data-ends-up.

The problem isn’t the words themselves; it’s the cadence. When every section, every tutorial, every changelog entry obeys the same two-openers, the prose becomes a pattern rather than a source of insight. Readers stop asking new questions because the text has already answered the old ones in the same form. Breaking the cadence forces both writer and reader into a different cognitive lane — one that surfaces constraints, data flows, and ownership boundaries that “Why/How” routinely buries.

## A Framework: What-Where-When-Who

Replacing the default with a four-word frame doesn’t mean abandoning intent or mechanics. It means reordering them so that the reader encounters the most operationally relevant information first.

- **What** — the problem domain, the data shape, the invariant being preserved. “What does this component guarantee about message ordering?”
- **Where** — the data path, the dependency graph, the service boundary. “Where does the ordering guarantee break down under partition?”
- **When** — the lifecycle stage, the trigger condition, the latency window. “When does the replica lag exceed the configured threshold?”
- **Who** — the owner, the operator, the stakeholder. “Who is paged when the lag violates SLA?”

Each of these four prompts can be answered with concrete, production-grade detail. “What” pulls in the spec or contract. “Where” references the topology diagram or the topic partition map. “When” ties to the metrics dashboard or the alert rule. “Who” maps to the on-call rotation or the team charter.

I’ve seen teams that shift their README structure from “Why this service exists” + “How to run it” to “What data this service processes” + “Where it sits in the mesh” + “When it scales horizontally” + “Who owns the SLO.” The result is that new engineers spend less time hunting for context and more time evaluating whether the service meets their use case. The framing also makes it easier to audit the documentation itself: if a section can’t be answered in one of these four lenses, it’s likely filler.

## Architecture in Practice: Kafka, Postgres, Airflow

Let’s look at three widely deployed systems and see how the What-Where-When-Who lens reshapes the typical Why/How narrative.

### Kafka: From “How to produce” to “What guarantees, where they break”

A conventional Kafka tutorial might open with “How to produce a message to a topic” and list producer properties: `bootstrap.servers`, `key.serializer`, `acks`. That’s mechanically sound, but it tells the reader nothing about when `acks=all` matters, where the broker’s log directory lives, what the trade-off is between durability and throughput, or who should be paged if the produce latency spikes.

A What-Where-When-Who rewrite might start: “What durability guarantee does `acks=all` provide? It ensures the leader and all in-sync replicas have persisted the record before the producer receives acknowledgment. Where does this guarantee fail? When the ISR shrinks below the configured replication factor, often during broker restarts or network partitions. When should you care? If your SLA requires zero data loss for a given topic, you monitor `produce.request.rate` and `replica.lag.max`. Who owns the decision? The streaming platform team sets the default ISR factor, but application owners choose the topic-level `min.insync.replicas`.”

Notice how each sentence answers a specific lens, and the reader can skip to the part that matters to their current concern. The “Why” of the design — Kafka’s trade-off between latency and durability — is still present, but it’s embedded in the “When” and “Where” rather than leading as a mission statement.

### Postgres: From “How to query” to “What indexes, where they live”

A typical Postgres guide might begin “How to speed up a slow query with an index.” It then walks through `EXPLAIN ANALYZE`, `CREATE INDEX`, and `VACUUM`. Again, correct, but the reader walks away with a bag of commands rather than a mental model of when the index helps and when it hurts.

A What-Where-When-Who frame: “What column patterns benefit from a B-tree index? Equality filters on low-cardinality columns see diminishing returns, while range queries on high-cardinality columns see immediate benefit. Where does the index live? In the table’s storage segment, with metadata tracked in `pg_index`. When does an index become a liability? When write throughput drops because every INSERT must update the index structure, or when `maintenance_work_mem` is too small to rebuild it efficiently. Who should evaluate this? The database team during quarterly schema reviews, armed with `pg_stat_user_indexes` and `pg_statio_user_tables`.”

The shift from “How” to “What/Where/When/Who” moves the reader from a how-to checklist to a decision framework. They can now assess whether adding an index is a net win for their specific workload, rather than following a generic recipe.

### Airflow: From “How to schedule” to “What DAGs, where they run, when they fail, who owns them”

Airflow DAGs often start with “How to define a DAG” and proceed to `default_args`, `schedule_interval`, and task operators. The pattern repeats across tutorials, and the reader learns the syntax without internalizing the operational implications.

A What-Where-When-Who approach: “What does this DAG produce? A daily sales reconciliation report. Where does it run? On the `airflow-worker` pool, constrained to nodes with access to the `sales-db` endpoint. When does it typically fail? When the upstream `staging` database triggers a lock timeout after the 2 AM batch, or when the DAG run timeout of 4 hours is exceeded. Who is responsible? The data engineering on-call, who monitors `airflow.task_instance_state` and `slack` alerts for `failed` runs.”

Again, the mechanics are there, but they’re nested behind the four lenses. A reader who just needs to know why their DAG hasn’t run can go straight to the “When” and “Who” without wading through the DAG definition syntax.

## Patterns in Production: Question Framing as a Quality Gate

Beyond individual docs, the Why/How cadence can become a systemic issue. Teams that habitually write RFCs, design docs, and post-mortems using the same two prompts tend to produce artifacts that are excellent at describing intent and mechanics, but weak on constraints, ownership, and failure modes. This shows up in post-mortems that spend three paragraphs on “Why the incident happened” and one sentence on “Who paged us at 3 AM.” It shows up in design docs that detail “How the feature will work” without specifying “When the feature is disabled, what state does the user see?”

A practical quality gate is to require every new technical document to pass a four-lens check before merge:

1. **What** — Is the problem or data shape stated without a “Why” preamble?
2. **Where** — Does the doc reference a topology, contract, or dependency that a reader can locate?
3. **When** — Are there latency, timeout, or lifecycle conditions called out?
4. **Who** — Is there an owner, team, or on-call rotation associated with the subject?

If any lens is missing, the doc is sent back for expansion. This gate doesn’t dictate tone or structure; it simply ensures that the Why/How cadence doesn’t crowd out the information engineers actually need to act.

I’ve seen a mid-sized platform team reduce their average post-mortem writing time by 20% after adopting this gate, because the team stopped debating whether a “Why” sentence was sufficiently reflective and instead focused on filling the “When” and “Who” slots that had been historically empty. The quality of the post-mortem improved because the most actionable details were surfaced first, not buried at the end.

## Key Takeaways

- The Why/How cadence in technical writing becomes a reflex that flattens architectural depth and obscures operational realities.
- Shifting to a What-Where-When-Who framework surfaces constraints, data flows, lifecycle conditions, and ownership in a single pass.
- Real-world systems like Kafka, Postgres, and Airflow illustrate how the four lenses produce more actionable, less predictable documentation.
- A four-lens quality gate on new docs ensures that Why/How patterns don’t crowd out the information engineers need to act.
- Engineer audiences scan for signals they can use; framing that respects their time and cognitive load performs better on LinkedIn and technical newsletters.

## Further Reading

- [Celery docs: Best practices for task design](https://docs.celeryq.dev)
- [Kafka documentation: Replication and ISR guides](https://kafka.apache.org/documentation/#replication)
- [Airflow patterns: DAG structure and ownership](https://airflow.apache.org/docs/apache-airflow/stable/best-practices.html)
- [Postgres indexing strategies: When to add, when to remove](https://www.postgresql.org/docs/current/indexes.html)
- [Technical writing handbook: Auditing prose for cadence and clarity](https://techwriter.com/auditing-prose)