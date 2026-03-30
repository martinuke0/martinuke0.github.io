---
title: "Mastering Apache Airflow DAGs: From Basics to Production‑Ready Pipelines"
date: "2026-03-30T11:23:18.298"
draft: false
tags: ["apache-airflow","data-engineering","orchestration","python","devops"]
---

## Table of Contents
1. [Introduction](#introduction)  
2. [What Is Apache Airflow?](#what-is-apache-airflow)  
3. [Core Concepts: The Building Blocks of a DAG](#core-concepts-the-building-blocks-of-a-dag)  
4. [Defining a DAG in Python](#defining-a-dag-in-python)  
5. [Operators, Sensors, and Triggers](#operators-sensors-and-triggers)  
6. [Managing Task Dependencies](#managing-task-dependencies)  
7. [Dynamic DAG Generation](#dynamic-dag-generation)  
8. [Templating, Variables, and Connections](#templating-variables-and-connections)  
9. [Error Handling, Retries, and SLAs](#error-handling-retries-and-slas)  
10. [Testing Your DAGs](#testing-your-dags)  
11. [Packaging, CI/CD, and Deployment Strategies](#packaging-cicd-and-deployment-strategies)  
12. [Observability: Monitoring, Logging, and Alerting](#observability-monitoring-logging-and-alerting)  
13. [Scaling Airflow: Executors and Architecture Choices](#scaling-airflow-executors-and-architecture-choices)  
14. [Real‑World Example: End‑to‑End ETL Pipeline](#real-world-example-end-to-end-etl-pipeline)  
15. [Best Practices & Common Pitfalls](#best-practices--common-pitfalls)  
16. [Conclusion](#conclusion)  
17. [Resources](#resources)

---

## Introduction

Apache Airflow has become the de‑facto standard for orchestrating complex data workflows. Its declarative, Python‑based approach lets engineers model pipelines as Directed Acyclic Graphs (DAGs) that are version‑controlled, testable, and reusable. Yet, despite its popularity, many teams still struggle with writing maintainable DAGs, scaling the platform, and integrating Airflow into modern CI/CD pipelines.

This article dives deep into **Airflow DAGs**—the core artifact that defines what, when, and how tasks run. We’ll explore everything from the low‑level API to production‑grade best practices, complete with runnable code snippets and a real‑world end‑to‑end example. By the end, you should be equipped to design, test, and operate robust Airflow pipelines that can survive the rigors of enterprise data engineering.

> **Note:** The examples target Airflow 2.7+, which introduces the `@dag` and `@task` decorators, native task‑flow API, and improved type hints. Adjustments for older 1.x versions are highlighted where relevant.

---

## What Is Apache Airflow?

Apache Airflow is an open‑source workflow management platform originally created at Airbnb in 2014 and later donated to the Apache Software Foundation. At its heart, Airflow does three things:

| Capability | Description | Why It Matters |
|------------|-------------|----------------|
| **Orchestration** | Executes tasks in a specified order based on dependencies. | Guarantees data consistency across stages. |
| **Scheduling** | Triggers DAG runs on a cron‑like schedule or on-demand. | Enables repeatable, time‑driven pipelines. |
| **Observability** | Provides a UI, logs, and metrics for each run. | Simplifies debugging and SLA enforcement. |

Airflow is **language‑agnostic**—the platform itself is written in Python, and tasks can be any executable (Python functions, Bash scripts, Docker containers, Spark jobs, etc.). The **DAG** (Directed Acyclic Graph) is the declarative representation of the workflow, while **Operators** are the concrete actions that run inside tasks.

---

## Core Concepts: The Building Blocks of a DAG

Before writing any code, it’s essential to understand the terminology that Airflow uses.

| Term | Definition | Typical Use |
|------|------------|-------------|
| **DAG** | A collection of tasks with directed edges, guaranteeing no cycles. | Represents a full pipeline (e.g., daily ETL). |
| **Task** | An instance of an Operator (or Sensor) that does work. | “Extract data from S3”, “Run dbt model”. |
| **Operator** | A reusable class that knows how to execute a specific type of work. | `PythonOperator`, `BashOperator`, `KubernetesPodOperator`. |
| **Sensor** | A special Operator that waits for a condition (e.g., file existence). | `S3KeySensor`, `ExternalTaskSensor`. |
| **Executor** | The component that actually runs task instances (local, Celery, Kubernetes, etc.). | Determines scalability and resource isolation. |
| **Scheduler** | Periodically parses DAG files, creates DAG runs, and sends tasks to the executor. | Drives the timing of pipelines. |
| **Trigger** | In Airflow 2+, a lightweight, asynchronous alternative to a Sensor. | Reduces scheduler load for long‑waiting conditions. |
| **XCom** | “Cross‑communication” mechanism for tasks to exchange small data blobs. | Passes file paths or query results between tasks. |
| **TaskGroup** | Logical grouping of tasks for UI clarity and hierarchical dependencies. | Organizes complex DAGs into sub‑sections. |

Understanding these concepts will help you design DAGs that are both **readable** and **scalable**.

---

## Defining a DAG in Python

Airflow DAGs are ordinary Python files placed in the `$AIRFLOW_HOME/dags/` directory (or a directory configured via `dags_folder`). The file is parsed by the scheduler, and any top‑level `DAG` objects become *discoverable* DAGs.

### Minimal DAG Example

```python
# dags/hello_world.py
from datetime import datetime
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    "owner": "data-eng",
    "retries": 1,
    "retry_delay": 300,  # seconds
    "start_date": datetime(2023, 1, 1),
}

with DAG(
    dag_id="hello_world",
    default_args=default_args,
    schedule_interval="@daily",
    catchup=False,
    tags=["example"],
) as dag:
    t1 = BashOperator(
        task_id="print_date",
        bash_command="date"
    )
    t2 = BashOperator(
        task_id="sleep",
        bash_command="sleep 5"
    )
    t1 >> t2  # set dependency
```

**Key sections**:

- **`default_args`** – common arguments applied to every task unless overridden.
- **`schedule_interval`** – cron expression (`@daily`, `0 6 * * *`, `timedelta(hours=1)`, etc.).
- **`catchup=False`** – prevents Airflow from back‑filling runs when you first deploy a DAG.
- **Dependency syntax** – `>>` and `<<` provide a readable way to declare ordering.

### Using the Task‑Flow API (`@dag` and `@task`)

Airflow 2 introduced a more Pythonic way to write DAGs using decorators. This eliminates the need for explicit operator classes for simple Python functions.

```python
# dags/etl_taskflow.py
from datetime import datetime, timedelta
from airflow.decorators import dag, task

default_args = {
    "owner": "data-eng",
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2024, 1, 1),
}

@dag(
    dag_id="taskflow_etl",
    default_args=default_args,
    schedule_interval="0 2 * * *",
    catchup=False,
    tags=["taskflow"],
)
def etl():
    @task
    def extract() -> list:
        # Pretend we read from an API
        return ["row1", "row2", "row3"]

    @task
    def transform(rows: list) -> list:
        return [r.upper() for r in rows]

    @task
    def load(transformed: list):
        # Here you would write to a DB; we just print
        for line in transformed:
            print(line)

    # Declare the data flow
    rows = extract()
    transformed = transform(rows)
    load(transformed)

dag = etl()
```

The **Task‑Flow API** automatically creates `PythonOperator` instances under the hood, handles XCom passing, and makes the DAG code feel like native Python data pipelines.

---

## Operators, Sensors, and Triggers

Operators are the workhorses of Airflow. Below is a quick overview of the most common families and when to use them.

| Operator Family | Example | Typical Use |
|------------------|---------|-------------|
| **BashOperator** | `bash_command="echo Hello"` | Simple shell scripts, legacy scripts |
| **PythonOperator** | `python_callable=my_func` | Running Python code, often via Task‑Flow |
| **DockerOperator** | `image="my-image:latest"` | Containerized jobs without a full K8s cluster |
| **KubernetesPodOperator** | `namespace="airflow"` | Run a pod on a K8s cluster (full isolation) |
| **PostgresOperator** | `sql="SELECT COUNT(*) FROM table"` | Run SQL against a Postgres DB |
| **SnowflakeOperator** | `sql="COPY INTO ..."` | Snowflake data loading |
| **SparkSubmitOperator** | `application="my_spark_job.py"` | Submit Spark jobs to a cluster |
| **HttpSensor** | `endpoint="v1/status"` | Wait for an HTTP endpoint to return 200 |
| **S3KeySensor** | `bucket_key="s3://my-bucket/data_{{ ds }}.csv"` | Wait for a file in S3 |
| **ExternalTaskSensor** | `external_dag_id="parent_dag"` | Synchronize across DAGs |

### Sensors vs. Triggers

Sensors are **blocking** by default—they occupy a worker slot while waiting. In high‑concurrency environments, this can be wasteful. Airflow 2 introduced **deferrable operators** (e.g., `S3KeySensor` with `mode="reschedule"` or the newer `S3KeyTrigger`). These use **Triggers** to pause execution and free up the worker, resuming only when the condition is met.

```python
# Deferrable sensor example
from airflow.providers.amazon.aws.sensors.s3_key import S3KeySensor

wait_for_file = S3KeySensor(
    task_id="wait_for_daily_file",
    bucket_name="my-data-bucket",
    bucket_key="raw/{{ ds }}.csv",
    aws_conn_id="aws_default",
    mode="reschedule",  # <-- frees the worker
    poke_interval=300,
    timeout=60 * 60 * 6,  # 6 hours
)
```

---

## Managing Task Dependencies

Complex pipelines often involve many tasks and sub‑graphs. Airflow provides several mechanisms to make dependency handling clear.

### Classic `set_upstream` / `set_downstream`

```python
t1.set_downstream(t2)   # same as t1 >> t2
t3.set_upstream(t2)     # same as t2 >> t3
```

### Bitshift Operators (`>>`, `<<`)

```python
t1 >> [t2, t3] >> t4
```

### `TaskGroup` for UI Organization

```python
from airflow.utils.task_group import TaskGroup

with TaskGroup("processing", tooltip="Data processing steps") as processing:
    clean = BashOperator(task_id="clean", bash_command="python clean.py")
    enrich = BashOperator(task_id="enrich", bash_command="python enrich.py")
    validate = BashOperator(task_id="validate", bash_command="python validate.py")

# Connect groups to other tasks
extract >> processing >> load
```

### `Chain` Utility

```python
from airflow.models import Chain
Chain([t1, t2, t3, t4])  # equivalent to t1 >> t2 >> t3 >> t4
```

Using these patterns keeps DAG files readable and makes the UI reflect the logical grouping.

---

## Dynamic DAG Generation

Static DAG files are fine for a handful of pipelines, but many organizations need **hundreds** of similar workflows (e.g., per‑customer ETL). Airflow supports dynamic DAG creation by looping over configuration data.

```python
# dags/dynamic_customers.py
import json
from pathlib import Path
from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta

# Load a JSON file that contains a list of customers
CUSTOMERS = json.loads(Path("/opt/airflow/config/customers.json").read_text())

default_args = {
    "owner": "data-eng",
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
    "start_date": datetime(2024, 1, 1),
}

for cust in CUSTOMERS:
    dag_id = f"customer_{cust['id']}_pipeline"

    with DAG(
        dag_id=dag_id,
        schedule_interval=cust["schedule"],
        default_args=default_args,
        catchup=False,
        tags=["customer"],
    ) as dag:
        extract = BashOperator(
            task_id="extract",
            bash_command=f"python extract.py --customer {cust['id']}"
        )
        transform = BashOperator(
            task_id="transform",
            bash_command=f"python transform.py --customer {cust['id']}"
        )
        load = BashOperator(
            task_id="load",
            bash_command=f"python load.py --customer {cust['id']}"
        )
        extract >> transform >> load
```

**Tips for dynamic DAGs**:

1. **Limit the number of DAG objects**: Airflow loads *all* DAGs at scheduler start, so generating thousands of DAGs can increase scheduler memory usage. Consider **sub‑DAGs** or **DAG factories** that generate DAGs on demand using the `DagBag` subclass.
2. **Use a single DAG with parameters**: Instead of many DAGs, you can have one DAG that receives a `customer_id` via `dag_run.conf` and loops internally over a list of customers.
3. **Avoid mutable global state**: Keep configuration loading inside the loop or in a function to prevent cross‑contamination between DAGs.

---

## Templating, Variables, and Connections

Airflow’s **Jinja2 templating engine** allows you to inject runtime values (execution date, DAG run config, XCom results) directly into operator fields.

### Example: BashOperator with templated command

```python
from airflow.operators.bash import BashOperator

run_query = BashOperator(
    task_id="run_query",
    bash_command="""
    psql -d {{ conn.postgres.default.schema }} \
    -c "COPY my_table TO STDOUT WITH CSV HEADER" \
    > /tmp/data_{{ ds }}.csv
    """,
    env={"PGHOST": "{{ conn.postgres.default.host }}"},
)
```

**Key templated variables**:

| Variable | Meaning |
|----------|---------|
| `{{ ds }}` | Execution date in `YYYY-MM-DD` |
| `{{ ds_nodash }}` | Same without dashes |
| `{{ ts }}` | Timestamp with timezone |
| `{{ params.my_param }}` | Custom parameters passed via `dag_run.conf` |
| `{{ var.value.my_variable }}` | Airflow Variable (global key/value store) |
| `{{ conn.my_conn_id.host }}` | Connection details (host, login, password) |

### Airflow Variables

Variables are key/value pairs stored in the metadata DB (or via the UI). They are ideal for values that rarely change (e.g., feature flag, API endpoint). You can also store JSON strings and parse them in the DAG.

```python
from airflow.models import Variable
import json

api_cfg = json.loads(Variable.get("my_api_config", deserialize_json=True))
endpoint = api_cfg["base_url"]
```

### Connections

Connections encapsulate credentials for external systems (databases, cloud services, HTTP APIs). They are defined via the UI, CLI (`airflow connections`), or environment variables (`AIRFLOW_CONN_<CONN_ID>`).

```bash
export AIRFLOW_CONN_SNOWFLAKE="snowflake://user:pwd@account/warehouse/db/schema"
```

In DAGs you reference them by ID, and Airflow automatically injects the credentials.

---

## Error Handling, Retries, and SLAs

A robust pipeline must anticipate failures.

### Retries

All operators inherit `retries`, `retry_delay`, and `retry_exponential_backoff` from `BaseOperator`. Example:

```python
PythonOperator(
    task_id="process",
    python_callable=process,
    retries=3,
    retry_delay=timedelta(minutes=2),
    retry_exponential_backoff=True,
    max_retry_delay=timedelta(minutes=10),
)
```

### Timeout

- **`execution_timeout`**: Maximum runtime for a task; triggers failure if exceeded.
- **`dagrun_timeout`**: Maximum time for the whole DAG run.

```python
from airflow.utils.timeout import timeout

task = BashOperator(
    task_id="long_running",
    bash_command="sleep 600",
    execution_timeout=timedelta(minutes=5),
)
```

### SLA (Service Level Agreement)

Airflow can alert when a task exceeds a *soft* deadline.

```python
default_args = {
    "owner": "data-eng",
    "sla": timedelta(hours=2),  # applies to every task unless overridden
}
```

Tasks can also have individual `sla` values.

### On‑Failure Callbacks

You can attach callbacks to react to failures (e.g., send Slack alerts).

```python
def notify_failure(context):
    from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator
    alert = SlackWebhookOperator(
        task_id="slack_alert",
        http_conn_id="slack_webhook",
        message=f"Task {context['task_instance_key_str']} failed!",
    )
    return alert.execute(context=context)

my_task = PythonOperator(
    task_id="critical_task",
    python_callable=run_critical,
    on_failure_callback=notify_failure,
)
```

---

## Testing Your DAGs

Testing ensures that changes don’t break downstream dependencies.

### Unit Tests with `pytest`

```python
# tests/test_dag_structure.py
import pytest
from airflow.models import DagBag

DAG_FOLDER = "/opt/airflow/dags"

def test_dag_import():
    dag_bag = DagBag(dag_folder=DAG_FOLDER, include_examples=False)
    assert len(dag_bag.import_errors) == 0, "DAG import errors detected"

def test_task_count():
    dag_bag = DagBag(dag_folder=DAG_FOLDER, include_examples=False)
    dag = dag_bag.get_dag("hello_world")
    assert dag is not None, "DAG hello_world not found"
    assert len(dag.tasks) == 2, "Unexpected number of tasks"
```

Run with:

```bash
pytest -q tests/
```

### `airflow tasks test`

Airflow ships a CLI command to execute a single task instance for a given execution date.

```bash
airflow tasks test hello_world print_date 2024-01-01
```

This runs the task in isolation, using the same context that the scheduler would provide.

### Mocking External Services

When a task depends on a database or API, use libraries like `unittest.mock` or `responses` to stub out calls.

```python
from unittest.mock import patch
import requests

@patch("requests.get")
def test_api_call(mock_get):
    mock_get.return_value.json.return_value = {"status": "ok"}
    # call your function that uses requests.get
    result = my_api_function()
    assert result["status"] == "ok"
```

---

## Packaging, CI/CD, and Deployment Strategies

Modern data teams treat DAGs like any other code artifact. Below are proven patterns.

### 1. Dockerize Airflow

Create a minimal Docker image that contains your DAGs, requirements, and a `docker-compose.yml` for local development.

```dockerfile
# Dockerfile
FROM apache/airflow:2.7.0-python3.11

# Install custom dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy DAGs
COPY dags/ /opt/airflow/dags/
COPY plugins/ /opt/airflow/plugins/
```

```yaml
# docker-compose.yml
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_USER: airflow
      POSTGRES_PASSWORD: airflow
      POSTGRES_DB: airflow
  redis:
    image: redis:7
  airflow:
    build: .
    environment:
      AIRFLOW__CORE__EXECUTOR: LocalExecutor
      AIRFLOW__CORE__SQL_ALCHEMY_CONN: postgresql+psycopg2://airflow:airflow@postgres/airflow
      AIRFLOW__CORE__FERNET_KEY: ''
    depends_on:
      - postgres
      - redis
    command: ["airflow", "standalone"]
```

### 2. CI/CD Pipelines

Typical steps in a GitHub Actions workflow:

```yaml
name: Airflow CI

on:
  push:
    branches: [main]

jobs:
  lint-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r dev-requirements.txt
      - name: Lint DAGs
        run: |
          flake8 dags/ plugins/
      - name: Run unit tests
        run: |
          pytest -q tests/
      - name: Verify DAG import
        run: |
          python - <<'PY'
          from airflow.models import DagBag
          dag_bag = DagBag(dag_folder='dags/', include_examples=False)
          assert not dag_bag.import_errors, dag_bag.import_errors
          PY
```

If tests pass, a subsequent job can **publish a Docker image** and trigger a deployment to Kubernetes (e.g., via Helm).

### 3. Deploying to Kubernetes with Helm

Airflow’s official Helm chart (`airflow/airflow`) supports multiple executors (Celery, Kubernetes). Example values:

```yaml
# values.yaml
executor: "KubernetesExecutor"
serviceAccount:
  create: true
  name: "airflow-sa"
dags:
  persistence:
    enabled: true
    existingClaim: "airflow-dags-pvc"
postgresql:
  enabled: true
redis:
  enabled: true
web:
  defaultUser:
    enabled: true
    username: admin
    password: "{{ .Values.web.defaultUser.password | default (randAlphaNum 16) }}"
```

Deploy:

```bash
helm repo add airflow https://airflow.apache.org
helm install my-airflow airflow/airflow -f values.yaml
```

---

## Observability: Monitoring, Logging, and Alerting

A production pipeline needs visibility into each run.

### UI & Logs

- **Web UI**: Shows DAG graph, task status, duration, and logs.
- **Log storage**: By default, logs are stored on the local file system. For scalability, use remote logging (S3, GCS, Elasticsearch) via `airflow.cfg`:

```ini
[logging]
remote_logging = True
remote_log_conn_id = S3_LOGS
remote_base_log_folder = s3://my-airflow-logs/
```

### Metrics

Airflow emits **Prometheus** metrics when enabled:

```ini
[metrics]
statsd_on = True
statsd_host = statsd-exporter
statsd_port = 9125
statsd_prefix = airflow
```

Prometheus can scrape metrics like:

- `airflow_task_successes_total`
- `airflow_task_failures_total`
- `airflow_dag_processing_time_seconds`

Grafana dashboards (e.g., the official Airflow dashboard) visualize these.

### Alerting

- **Email**: Configure SMTP in `airflow.cfg`.
- **Slack**: Use `SlackWebhookOperator` or the built‑in alerting via `on_failure_callback`.
- **PagerDuty**: Use the `PagerDutyOperator` from the `airflow.providers.pagerduty` package.

Example of a global failure alert via a DAG-level callback:

```python
def dag_failure_alert(context):
    from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator
    alert = SlackWebhookOperator(
        task_id="global_failure",
        http_conn_id="slack",
        message=f"DAG {context['dag'].dag_id} failed at {context['execution_date']}",
    )
    alert.execute(context=context)

with DAG(
    dag_id="critical_pipeline",
    default_args=default_args,
    on_failure_callback=dag_failure_alert,
    schedule_interval="@hourly",
) as dag:
    # tasks...
```

---

## Scaling Airflow: Executors and Architecture Choices

Choosing the right executor determines how Airflow scales.

| Executor | Characteristics | When to Use |
|----------|-----------------|------------|
| **SequentialExecutor** | Runs one task at a time, no parallelism. | Development or debugging. |
| **LocalExecutor** | Executes tasks in parallel using local processes. | Small clusters, < 10 concurrent tasks. |
| **CeleryExecutor** | Distributed task queue (RabbitMQ/Redis). | Medium‑scale, need horizontal scaling across workers. |
| **KubernetesExecutor** | Each task runs in its own pod; leverages K8s autoscaling. | Large workloads, heterogeneous resources, need isolation. |
| **DaskExecutor** | Executes tasks on a Dask cluster; good for Python‑heavy workloads. | Data science pipelines with heavy in‑memory processing. |
| **DebugExecutor** | Runs tasks locally for debugging; does not schedule. | Unit testing of task logic. |

### Example: Switching to KubernetesExecutor

```yaml
# values.yaml excerpt
executor: "KubernetesExecutor"
workers:
  replicas: 5
  resources:
    limits:
      cpu: "2"
      memory: "4Gi"
    requests:
      cpu: "1"
      memory: "2Gi"
```

With `KubernetesExecutor`, each task can specify its own pod specs:

```python
from airflow.providers.cncf.kubernetes.operators.kubernetes_pod import KubernetesPodOperator

run_ml_job = KubernetesPodOperator(
    task_id="ml_training",
    name="ml-train",
    namespace="airflow",
    image="my-ml-image:latest",
    cmds=["python", "train.py"],
    resources={
        "limit_cpu": "4",
        "limit_memory": "8Gi",
        "request_cpu": "2",
        "request_memory": "4Gi",
    },
    is_delete_operator_pod=True,
    get_logs=True,
)
```

---

## Real‑World Example: End‑to‑End ETL Pipeline

Let’s walk through a realistic DAG that:

1. **Extracts** daily CSV files from an S3 bucket.
2. **Validates** schema using Great Expectations.
3. **Transforms** data with dbt.
4. **Loads** into Snowflake.
5. **Notifies** stakeholders via Slack.

The pipeline uses a mix of Operators, Sensors, XCom, and the Task‑Flow API.

```python
# dags/etl_daily.py
from datetime import datetime, timedelta
from airflow import DAG
from airflow.decorators import task, dag
from airflow.providers.amazon.aws.sensors.s3_key import S3KeySensor
from airflow.providers.amazon.aws.operators.s3 import S3CopyObjectOperator
from airflow.providers.slack.operators.slack_webhook import SlackWebhookOperator
from airflow.providers.snowflake.operators.snowflake import SnowflakeOperator
from airflow.providers.dbt.cloud.operators.dbt import DbtCloudRunJobOperator
from airflow.utils.trigger_rule import TriggerRule
import json

default_args = {
    "owner": "data-eng",
    "email_on_failure": False,
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2024, 1, 1),
    "catchup": False,
}

@dag(
    dag_id="daily_etl_pipeline",
    schedule_interval="@daily",
    default_args=default_args,
    tags=["etl", "snowflake"],
)
def etl_pipeline():
    # -----------------------------------------------------------------
    # 1️⃣ Wait for the raw file to land in S3
    # -----------------------------------------------------------------
    wait_for_file = S3KeySensor(
        task_id="wait_for_raw_file",
        bucket_name="raw-data-bucket",
        bucket_key="raw/{{ ds }}.csv",
        aws_conn_id="aws_default",
        mode="reschedule",
        poke_interval=300,
        timeout=60 * 60 * 6,  # 6 hrs
    )

    # -----------------------------------------------------------------
    # 2️⃣ Copy raw file to a staging location (optional)
    # -----------------------------------------------------------------
    copy_to_staging = S3CopyObjectOperator(
        task_id="copy_to_staging",
        source_bucket_name="raw-data-bucket",
        source_key="raw/{{ ds }}.csv",
        dest_bucket_name="staging-data-bucket",
        dest_key="staging/{{ ds }}.csv",
        aws_conn_id="aws_default",
    )

    # -----------------------------------------------------------------
    # 3️⃣ Run Great Expectations validation (Python callable)
    # -----------------------------------------------------------------
    @task
    def validate():
        import great_expectations as ge
        from great_expectations.core.batch import BatchRequest

        context = ge.data_context.DataContext()
        batch_request = BatchRequest(
            datasource_name="s3_datasource",
            data_connector_name="default_inferred_data_connector_name",
            data_asset_name="staging/{{ ds }}.csv",
        )
        suite = context.get_expectation_suite("raw_data_suite")
        validator = context.get_validator(batch_request=batch_request, expectation_suite=suite)
        results = validator.validate()
        if not results.success:
            raise ValueError("Data validation failed")
        return {"validation": "passed"}

    validation = validate()

    # -----------------------------------------------------------------
    # 4️⃣ Trigger dbt Cloud job to transform data
    # -----------------------------------------------------------------
    dbt_transform = DbtCloudRunJobOperator(
        task_id="dbt_transform",
        dbt_cloud_conn_id="dbt_cloud",
        job_id=12345,  # dbt Cloud job ID
        trigger_rule=TriggerRule.ALL_SUCCESS,
        # Pass the execution date as a variable for dbt
        variables=json.dumps({"run_date": "{{ ds }}"}),
    )

    # -----------------------------------------------------------------
    # 5️⃣ Load transformed data into Snowflake
    # -----------------------------------------------------------------
    load_to_sf = SnowflakeOperator(
        task_id="load_to_snowflake",
        snowflake_conn_id="snowflake_default",
        sql="""
        COPY INTO analytics.public.fact_sales
        FROM @~/staging/{{ ds }}.parquet
        FILE_FORMAT = (TYPE = PARQUET);
        """,
        autocommit=True,
    )

    # -----------------------------------------------------------------
    # 6️⃣ Notify Slack on success / failure
    # -----------------------------------------------------------------
    success_notify = SlackWebhookOperator(
        task_id="slack_success",
        http_conn_id="slack_webhook",
        message="✅ Daily ETL succeeded for {{ ds }}",
        trigger_rule=TriggerRule.ALL_SUCCESS,
    )

    failure_notify = SlackWebhookOperator(
        task_id="slack_failure",
        http_conn_id="slack_webhook",
        message="❌ Daily ETL FAILED for {{ ds }}. Check Airflow UI.",
        trigger_rule=TriggerRule.ONE_FAILED,
    )

    # -----------------------------------------------------------------
    # Define dependencies
    # -----------------------------------------------------------------
    wait_for_file >> copy_to_staging >> validation >> dbt_transform >> load_to_sf
    load_to_sf >> [success_notify, failure_notify]

dag = etl_pipeline()
```

**Highlights of this DAG**:

- **Deferrable sensor** (`mode="reschedule"`) frees worker slots while waiting for the file.
- **Great Expectations** validation is encapsulated in a `@task` function, making use of XCom to propagate success/failure.
- **dbt Cloud** job runs asynchronously; the operator polls for completion.
- **Trigger rules** ensure that the failure notification fires if any upstream task fails, while the success notification only fires when everything succeeds.
- **Slack alerts** provide immediate visibility to data stakeholders.

---

## Best Practices & Common Pitfalls

### ✅ Best Practices

1. **Version‑control DAGs**: Store them in a Git repository; use PRs for review.
2. **Immutable DAG IDs**: Never rename a DAG; instead, deprecate the old one and create a new DAG.
3. **Parameterize with `dag_run.conf`**: Allows ad‑hoc runs without code changes.
4. **Avoid heavy logic in the DAG file**: Keep only DAG definition; move business logic to reusable Python modules or external services.
5. **Leverage `TaskGroup`** for UI clarity in large DAGs.
6. **Use deferrable sensors** wherever possible to reduce scheduler load.
7. **Set explicit timeouts and retries** to avoid runaway tasks.
8. **Document DAGs**: Include docstrings and comments; the UI shows the docstring as the description.
9. **Use `airflow.utils.dates.days_ago`** for a relative start date during development.
10. **Run linting (`flake8`, `black`) and type checking (`mypy`)** in CI.

### ❌ Common Pitfalls

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| **Mutable global state** | Tasks sharing variables cause race conditions. | Keep state inside XCom or explicit function arguments. |
| **Hard‑coded credentials** | Security breach, failures on other environments. | Use Airflow Connections & Variables, never embed secrets. |
| **Large DAG files** | Scheduler slowness, import errors. | Split into multiple files, use DAG factories. |
| **Blocking sensors** | Exhausted worker slots, scheduler overload. | Switch to deferrable sensors (`mode="reschedule"`). |
| **Cyclic dependencies** | Scheduler throws `AirflowDagCycleException`. | Verify DAG is truly acyclic; use `airflow dags list` to debug. |
| **Missing `catchup=False`** | Unexpected backfills on deployment. | Explicitly set `catchup=False` unless backfill is desired. |
| **Over‑reliance on `airflow.cfg` for env‑specific settings** | Inconsistent configs across dev/prod. | Use environment variables (`AIRFLOW__CORE__...`) or Helm values. |

---

## Conclusion

Apache Airflow’s DAGs are far more than a simple list of tasks—they are a **declarative, version‑controlled blueprint** for data movement, transformation, and orchestration. By mastering the core concepts (operators, sensors, XCom, templating), embracing modern features (Task‑Flow API, deferrable operators, KubernetesExecutor), and integrating robust testing and CI/CD pipelines, you can build pipelines that scale from a single developer’s notebook to enterprise‑wide data platforms.

Remember that the **long‑term health** of an Airflow deployment hinges on good coding hygiene, observability, and clear documentation. Treat DAGs as production code: lint them, test them, review them, and monitor them. With the patterns and examples presented here, you’re well‑equipped to design, implement, and operate Airflow pipelines that are reliable, maintainable, and ready for the data challenges of tomorrow.

---

## Resources

- **Apache Airflow Official Documentation** – Comprehensive reference for all components.  
  [Airflow Docs](https://airflow.apache.org/docs/)

- **Airflow Provider Packages** – Collection of integrations (AWS, Snowflake, dbt, Slack, etc.).  
  [Airflow Providers GitHub](https://github.com/apache/airflow/tree/main/airflow/providers)

- **Great Expectations Documentation** – Data validation framework used in the ETL example.  
  [Great Expectations](https://docs.greatexpectations.io/)

- **dbt Cloud API Guide** – How to trigger dbt runs from Airflow.  
  [dbt Cloud API](https://docs.getdbt.com/docs/dbt-cloud/api)

- **Prometheus Metrics for Airflow** – Official Grafana dashboards and metric list.  
  [Airflow Prometheus Exporter](https://github.com/apache/airflow/tree/main/airflow/providers/prometheus)

- **Astronomer Blog – Scaling Airflow** – Real‑world strategies for large deployments.  
  [Scaling Airflow on Astronomer](https://www.astronomer.io/blog/scaling-apache-airflow)

- **Kubernetes Executor Best Practices** – Helm chart and resource tuning.  
  [Kubernetes Executor Guide](https://airflow.apache.org/docs/apache-airflow/stable/executor/kubernetes.html)

---