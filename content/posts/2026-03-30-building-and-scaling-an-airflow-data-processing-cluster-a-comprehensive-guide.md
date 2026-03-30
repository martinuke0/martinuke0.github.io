---
title: "Building and Scaling an Airflow Data Processing Cluster: A Comprehensive Guide"
date: "2026-03-30T11:22:40.300"
draft: false
tags: ["Apache Airflow","Data Engineering","Cluster Computing","Kubernetes","ETL"]
---

## Introduction

Apache Airflow has become the de‑facto standard for orchestrating complex data pipelines. Its declarative, Python‑based DAG (Directed Acyclic Graph) model makes it easy to express dependencies, schedule jobs, and handle retries. However, as data volumes grow and workloads become more heterogeneous—ranging from Spark jobs and Flink streams to simple Python scripts—running Airflow on a single machine quickly turns into a bottleneck.

Enter the **Airflow data processing cluster**: a collection of machines (or containers) that collectively execute the tasks defined in your DAGs. A well‑designed cluster not only scales horizontally, but also isolates workloads, improves fault tolerance, and integrates tightly with the broader data ecosystem (cloud storage, data warehouses, ML platforms, etc.).

This guide walks you through every step of building, configuring, and operating a production‑grade Airflow cluster. We’ll cover:

1. Core Airflow architecture and the role of executors.
2. Choosing the right executor for a data‑processing workload.
3. Deploying Airflow on Kubernetes (the most flexible option today).
4. Integrating with popular data‑processing engines (Spark, Dask, Flink, Presto).
5. Scaling strategies, monitoring, and security best practices.
6. Real‑world case studies and practical code examples.

Whether you’re a data engineer setting up your first production pipeline or an architect looking to modernize an existing Airflow installation, this article provides the depth and breadth you need to design a resilient, high‑throughput data processing cluster.

---

## Table of Contents
* [1. Airflow Architecture Refresher](#1-airflow-architecture-refresher)  
  * 1.1 Scheduler, Webserver, Workers, and Metadata DB  
  * 1.2 Executors: The Bridge Between Scheduler and Workers  
* [2. Selecting an Executor for Data‑Intensive Workloads](#2-selecting-an-executor-for-data‑intensive-workloads)  
  * 2.1 SequentialExecutor (Why It’s Not for Production)  
  * 2.2 LocalExecutor (Good for Small Teams)  
  * 2.3 CeleryExecutor (Classic Distributed Model)  
  * 2.4 KubernetesExecutor (Container‑Native Scaling)  
  * 2.5 Comparison Table  
* [3. Deploying Airflow on Kubernetes](#3-deploying-airflow-on-kubernetes)  
  * 3.1 Prerequisites (K8s Cluster, Helm, Docker Registry)  
  * 3.2 Helm Chart Configuration (Values.yaml)  
  * 3.3 Setting Up the Metadata Database (PostgreSQL)  
  * 3.4 Configuring the Scheduler, Webserver, and Workers  
  * 3.5 Secrets Management (Kubernetes Secrets & Vault)  
* [4. Integrating Data‑Processing Engines](#4-integrating-data‑processing-engines)  
  * 4.1 Spark on Kubernetes via `SparkSubmitOperator`  
  * 4.2 Dask Cluster with `DaskKubernetesOperator`  
  * 4.3 Flink Jobs through `FlinkKubernetesOperator`  
  * 4.4 Presto/Trino Queries with `PrestoOperator`  
  * 4.5 Example DAG: End‑to‑End ETL with Spark → S3 → Redshift  
* [5. Scaling Strategies and Performance Tuning](#5-scaling-strategies-and-performance-tuning)  
  * 5.1 Horizontal Pod Autoscaling (HPA) for Workers  
  * 5.2 Resource Requests & Limits (CPU, Memory)  
  * 5.3 Queue Management and Prioritization  
  * 5.4 Task Concurrency vs. DAG Concurrency  
  * 5.5 Monitoring with Prometheus & Grafana  
* [6. High Availability & Disaster Recovery](#6-high-availability--disaster-recovery)  
  * 6.1 Multi‑Master Scheduler Setup  
  * 6.2 Database Replication and Backups  
  * 6.3 StatefulSet vs. Deployment for Scheduler/Webserver  
* [7. Security Best Practices](#7-security-best-practices)  
  * 7.1 RBAC in Airflow and Kubernetes  
  * 7.2 Network Policies & Service Meshes  
  * 7.3 Credential Rotation and Secret Backend Choices  
* [8. Real‑World Case Studies](#8-real‑world-case-studies)  
  * 8.1 E‑Commerce Clickstream Processing (Spark + S3)  
  * 8.2 Financial Time‑Series Aggregation (Flink + Kafka)  
  * 8.3 Machine‑Learning Feature Store Refresh (Dask + Snowflake)  
* [9. Conclusion](#9-conclusion)  
* [10. Resources](#10-resources)  

---

## 1. Airflow Architecture Refresher

Before diving into clusters, let’s quickly recap Airflow’s core components and how they interact.

### 1.1 Scheduler, Webserver, Workers, and Metadata DB

| Component | Responsibility | Typical Deployment |
|-----------|----------------|--------------------|
| **Scheduler** | Parses DAG files, determines runnable tasks, enqueues them in the executor’s queue. | One or more pods (high‑availability) |
| **Webserver** | UI for DAG visualization, task logs, admin actions. | Stateless Deployment, can be scaled horizontally |
| **Workers** | Execute the actual tasks (Python callables, Bash scripts, Spark jobs, etc.). | Managed by the executor (Celery workers, K8s pods, etc.) |
| **Metadata DB** | Stores DAG definitions, task instances, XComs, and configuration. | PostgreSQL or MySQL; must be HA for production |

All state transitions (e.g., `queued → running → success/failed`) are persisted in the metadata DB, making the system resilient to individual pod failures.

### 1.2 Executors: The Bridge Between Scheduler and Workers

An **executor** abstracts how tasks are handed off from the scheduler to workers. The executor determines:

* How many tasks can run concurrently.
* Where tasks run (local process, remote Celery worker, Kubernetes pod, etc.).
* How task results and logs are collected.

Choosing the right executor is the single most important decision when building a data‑processing cluster.

---

## 2. Selecting an Executor for Data‑Intensive Workloads

| Executor | Execution Model | Pros | Cons | Typical Use‑Case |
|----------|------------------|------|------|-----------------|
| **SequentialExecutor** | Scheduler runs tasks in the same process. | Simple, zero external deps. | No parallelism; not HA. | Development, testing only. |
| **LocalExecutor** | Scheduler spawns subprocesses on the same machine. | Parallelism on a single node; easy setup. | Limited by one machine’s resources; no true distribution. | Small teams or proof‑of‑concept. |
| **CeleryExecutor** | Distributed task queue (RabbitMQ/Redis + Celery workers). | Mature, supports many workers across VMs. | Requires separate message broker; scaling can be complex; workers share the same OS environment. | Traditional VM‑based clusters. |
| **KubernetesExecutor** | Scheduler creates a pod per task on a K8s cluster. | Native container isolation, dynamic scaling, per‑task resources. | Requires a healthy K8s cluster; initial learning curve. | Modern cloud‑native data pipelines. |

### 2.1 SequentialExecutor (Why It’s Not for Production)

The `SequentialExecutor` is essentially a single‑threaded runner. It is useful only for debugging DAG parsing errors because it guarantees deterministic ordering. For any data‑processing workload that involves Spark jobs or heavy I/O, it will choke.

### 2.2 LocalExecutor (Good for Small Teams)

`LocalExecutor` allows parallel execution on a single node, configurable via `parallelism`. It’s a sweet spot for teams that:

* Have modest data volumes (< 10 TB/day).
* Run on a powerful VM (e.g., 32 vCPU, 128 GB RAM).
* Want to avoid the operational overhead of a message broker.

**Limitation:** If a task crashes the worker process, the entire scheduler pod may be affected. Also, you cannot leverage container‑level isolation for different runtime dependencies.

### 2.3 CeleryExecutor (Classic Distributed Model)

Celery uses a message broker (RabbitMQ or Redis) to dispatch tasks to worker processes that can run on any host reachable by the broker. The typical deployment looks like:

```
[Scheduler] → RabbitMQ (queue) → [Celery Worker 1]
                                      → [Celery Worker 2]
                                      → …
```

**Pros:**

* Mature, battle‑tested.
* Workers can be on VMs with different OS images.
* Fine‑grained control over concurrency per worker.

**Cons:**

* Broker becomes a single point of failure unless you set up HA.
* Scaling requires provisioning new VMs and configuring them to join the Celery pool.
* Managing Python dependencies across heterogeneous workers can be error‑prone.

### 2.4 KubernetesExecutor (Container‑Native Scaling)

The `KubernetesExecutor` creates **one pod per task**, inheriting the Airflow scheduler’s environment variables and any custom `pod_template.yaml`. Example flow:

```
[Scheduler] → API call → Kubernetes API → Pod (Task A)
                                            └─> Pod (Task B) …
```

**Advantages for data processing:**

* **Per‑task resource guarantees:** Assign CPU, memory, GPU, and even node selectors.
* **Isolation:** Each task runs in its own container image, avoiding dependency clashes.
* **Autoscaling:** Combine with Horizontal Pod Autoscaler (HPA) or custom metrics to spin up workers only when the queue backs up.

**Considerations:**

* Requires a robust K8s cluster (managed services like GKE, EKS, AKS, or on‑prem K8s).
* Pods start with a short latency (typically 5–30 seconds); for very short tasks, this overhead can dominate.

### 2.5 Comparison Table

| Feature | Sequential | Local | Celery | Kubernetes |
|---------|------------|-------|--------|------------|
| Parallelism | 1 | Up to `parallelism` on one node | Unlimited across nodes | Unlimited across nodes |
| Isolation | None | Process‑level | Worker‑level (shared OS) | Container‑level |
| Autoscaling | No | Manual VM scaling | Manual worker addition | Native HPA & Cluster Autoscaler |
| Dependency Management | Same env | Same env | Same env per worker | Image‑per‑task |
| Complexity | Minimal | Low | Medium (broker) | Medium‑High (K8s) |
| Best for Data‑Processing | ❌ | ✅ (small) | ✅ (mid‑size) | ✅ (large, cloud‑native) |

**Recommendation:** For any modern data‑processing platform aiming for elasticity, the **KubernetesExecutor** is the most future‑proof choice. The following sections dive deep into its deployment.

---

## 3. Deploying Airflow on Kubernetes

### 3.1 Prerequisites

| Item | Why It’s Needed |
|------|-----------------|
| **Kubernetes cluster** (≥ 1.22) | Provides the API for pod creation, networking, and storage. |
| **Helm 3** | Simplifies Airflow chart installation and upgrades. |
| **Docker registry** (Docker Hub, ECR, GCR, or private) | Stores custom task images. |
| **PostgreSQL** (or CloudSQL, RDS) | Persistent metadata DB. |
| **Secrets backend** (Kubernetes Secrets, HashiCorp Vault, AWS Secrets Manager) | Secure credential storage. |

> **Tip:** If you’re on a major cloud provider, consider using their **managed Airflow service** (MWAA, Composer, Azure Data Factory) for a quick start, but keep in mind you’ll have less control over executor choice and custom images.

### 3.2 Helm Chart Configuration

The official Apache Airflow Helm chart (`apache-airflow/airflow`) is battle‑tested. Below is a trimmed `values.yaml` focusing on the KubernetesExecutor.

```yaml
# values.yaml
executor: "KubernetesExecutor"

# Airflow configuration
config:
  core:
    load_examples: "False"
    sql_alchemy_conn: "postgresql+psycopg2://airflow:{{ .Values.postgresql.password }}@airflow-postgresql/airflow"
    executor: "KubernetesExecutor"
    # Enable XCom backend for large data
    xcom_backend: "airflow.providers.amazon.aws.xcom_aws.AwsXComBackend"

# PostgreSQL sub‑chart (or external)
postgresql:
  enabled: true
  postgresqlDatabase: airflow
  postgresqlUsername: airflow
  postgresqlPassword: "YOUR_SECURE_PASSWORD"

# Scheduler settings
scheduler:
  replicas: 2               # HA scheduler
  podAnnotations:
    prometheus.io/scrape: "true"
  resources:
    requests:
      cpu: "500m"
      memory: "1Gi"
    limits:
      cpu: "2"
      memory: "4Gi"

# Webserver
web:
  replicas: 2
  resources:
    requests:
      cpu: "250m"
      memory: "512Mi"
    limits:
      cpu: "1"
      memory: "2Gi"

# Workers (KubernetesExecutor creates pods dynamically, but we can set a default pod template)
workers:
  pod_template_file: "/opt/airflow/pod_template.yaml"

# Secrets
env:
  - name: AIRFLOW__SECRETS__BACKEND
    value: "airflow.providers.hashicorp.secrets.vault.VaultBackend"
  - name: AIRFLOW__SECRETS__VAULT__URL
    value: "https://vault.mycompany.com"
  - name: AIRFLOW__SECRETS__VAULT__TOKEN
    valueFrom:
      secretKeyRef:
        name: vault-token
        key: token
```

**Key points:**

* **`executor: "KubernetesExecutor"`** tells Airflow to spin up pods per task.
* **`pod_template_file`** defines a base pod spec that every task inherits (e.g., default service account, image pull secrets, volume mounts).
* **HA Scheduler** (2 replicas) ensures that if one scheduler pod crashes, the other continues to schedule tasks.
* **Resource limits** prevent a single scheduler from starving the cluster.

#### Sample `pod_template.yaml`

```yaml
apiVersion: v1
kind: Pod
metadata:
  labels:
    app: airflow
spec:
  serviceAccountName: airflow-worker
  imagePullSecrets:
    - name: regcred
  containers:
    - name: base
      image: apache/airflow:2.7.0-python3.10
      command: ["bash", "-c"]
      args: ["{{ task.command }}"]
      envFrom:
        - secretRef:
            name: airflow-secrets
  # Optional: mount a persistent volume for large logs
  volumes:
    - name: airflow-logs
      persistentVolumeClaim:
        claimName: airflow-logs-pvc
  volumeMounts:
    - name: airflow-logs
      mountPath: /opt/airflow/logs
```

### 3.3 Setting Up the Metadata Database

You can use the bundled PostgreSQL sub‑chart or point to an external managed DB. For production, **enable WAL archiving** and **daily backups**:

```yaml
postgresql:
  primary:
    persistence:
      size: 20Gi
    extraEnv:
      - name: POSTGRESQL_POSTGRES_PASSWORD
        valueFrom:
          secretKeyRef:
            name: pg-secret
            key: postgres-password
  backup:
    enabled: true
    schedule: "0 2 * * *"   # daily at 2 AM UTC
    retention: 30           # keep 30 days of backups
```

### 3.4 Configuring Scheduler, Webserver, and Workers

* **Scheduler:** Set `max_active_runs_per_dag` and `max_active_tasks_per_dag` based on expected concurrency. Example:

```yaml
config:
  core:
    max_active_runs_per_dag: "10"
    max_active_tasks_per_dag: "30"
```

* **Webserver:** Expose via an Ingress with TLS termination. Add basic auth or SSO (e.g., OIDC) using the `auth_backend` config.

* **Workers (K8s Pods):** The `KubernetesExecutor` automatically creates pods. However, you can define **task‑specific pod overrides** in the DAG using `KubernetesPodOperator` or by specifying `executor_config`:

```python
task = BashOperator(
    task_id='heavy_transform',
    bash_command='python transform.py',
    executor_config={
        "KubernetesExecutor": {
            "request_memory": "8Gi",
            "request_cpu": "4",
            "node_selector": {"cloud.google.com/gke-nodepool": "highmem"},
            "affinity": {
                "nodeAffinity": {
                    "requiredDuringSchedulingIgnoredDuringExecution": {
                        "nodeSelectorTerms": [
                            {
                                "matchExpressions": [
                                    {
                                        "key": "gpu",
                                        "operator": "Exists"
                                    }
                                ]
                            }
                        ]
                    }
                }
            },
        }
    },
)
```

### 3.5 Secrets Management

Never hard‑code credentials. Airflow supports several backends; a common pattern:

* **Kubernetes Secrets** for non‑critical values (e.g., Slack webhook URL).
* **HashiCorp Vault** for database passwords, API keys, and RSA keys.
* **AWS Secrets Manager** when you’re on AWS.

Configure the backend in `airflow.cfg` (or via environment variables) as shown in the `values.yaml` snippet above.

---

## 4. Integrating Data‑Processing Engines

Airflow’s strength lies in its **operator ecosystem**. Below we walk through the most common data‑processing engines and provide concrete DAG snippets.

### 4.1 Spark on Kubernetes via `SparkSubmitOperator`

Airflow ships with a `SparkSubmitOperator` that can target a Spark cluster running on Kubernetes (the **Spark-on-K8s** mode). The operator essentially runs `spark-submit` inside a pod.

**Prerequisites:**

* Spark 3.2+ compiled with `kubernetes` support.
* A dedicated namespace (e.g., `spark-jobs`) where Spark driver pods are launched.
* Service account with `pods/create` permissions.

**Sample DAG:**

```python
from airflow import DAG
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "data-eng",
    "depends_on_past": False,
    "email_on_failure": True,
    "email": ["alerts@mycompany.com"],
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="spark_etl_pipeline",
    default_args=default_args,
    schedule_interval="@daily",
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:

    spark_job = SparkSubmitOperator(
        task_id="run_spark_transform",
        application="/opt/airflow/dags/jobs/transform.py",
        name="daily_transform",
        conn_id="spark_k8s",               # Airflow connection pointing to k8s master
        conf={
            "spark.kubernetes.namespace": "spark-jobs",
            "spark.kubernetes.container.image": "myrepo/spark-job:latest",
            "spark.executor.instances": "4",
            "spark.executor.memory": "8g",
            "spark.driver.memory": "4g",
        },
        packages="org.apache.hadoop:hadoop-aws:3.3.2",
        jars="/opt/airflow/jars/aws-java-sdk-bundle.jar",
        verbose=True,
    )
```

**Explanation:**

* `conn_id="spark_k8s"` references a **Spark connection** in Airflow that points to the Kubernetes master API (or uses the local `kubectl` config).
* The `conf` dictionary is passed directly to `spark-submit` as `--conf`.
* By using `SparkSubmitOperator`, Airflow monitors the driver pod’s logs and marks the task as `success` only when the Spark job completes.

### 4.2 Dask Cluster with `DaskKubernetesOperator`

Dask is ideal for Python‑centric analytics (Pandas, NumPy, XGBoost). Airflow’s `DaskKubernetesOperator` creates a Dask scheduler and a set of workers on the fly.

**DAG Example:**

```python
from airflow import DAG
from airflow.providers.dask.operators.dask import DaskKubernetesOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "ml-team",
    "email_on_failure": True,
    "email": ["ml-ops@mycompany.com"],
    "retries": 1,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="dask_feature_engineering",
    default_args=default_args,
    schedule_interval="0 3 * * *",
    start_date=datetime(2024, 6, 1),
    catchup=False,
) as dag:

    dask_job = DaskKubernetesOperator(
        task_id="run_feature_job",
        namespace="dask",
        image="myrepo/dask-feature:2024-06",
        env_vars={"AWS_DEFAULT_REGION": "us-east-1"},
        worker_memory="8Gi",
        worker_cpu="4",
        n_workers=6,
        # The Python callable is packaged inside the Docker image.
        python_callable="my_package.jobs.feature_engineering.run",
        # Optional: pass parameters via kwargs
        op_kwargs={"date": "{{ ds }}"},
    )
```

**What happens under the hood:**

1. Airflow creates a **Dask Scheduler** pod.
2. It then spins up the requested number of **Worker** pods.
3. The `python_callable` is executed on the Dask cluster.
4. Upon completion, the scheduler and workers are terminated automatically.

### 4.3 Flink Jobs through `FlinkKubernetesOperator`

For streaming pipelines, Apache Flink shines. The `FlinkKubernetesOperator` abstracts the deployment of a Flink job on a K8s cluster.

```python
from airflow import DAG
from airflow.providers.apache.flink.operators.flink import FlinkKubernetesOperator
from datetime import datetime

default_args = {
    "owner": "streaming-team",
    "email_on_failure": True,
    "email": ["streaming@mycompany.com"],
}

with DAG(
    dag_id="flink_clickstream_ingest",
    default_args=default_args,
    schedule_interval=None,   # Triggered by external event or sensor
    start_date=datetime(2024, 5, 1),
    catchup=False,
) as dag:

    flink_job = FlinkKubernetesOperator(
        task_id="run_flink_job",
        job_name="clickstream-processor",
        job_file="/opt/airflow/dags/flink/jobs/clickstream.jar",
        parallelism=8,
        flink_version="1.15",
        namespace="flink",
        kubernetes_context="gke_myproject_us-east1-b_mycluster",
        # Optional: pass arguments to the main class
        program_args="--input-topic click_events --output-table daily_summary",
    )
```

The operator monitors the Flink job’s lifecycle through the Flink REST API and only marks the task as successful when the job reaches a **FINISHED** or **CANCELED** state (depending on your configuration).

### 4.4 Presto/Trino Queries with `PrestoOperator`

If you need to run ad‑hoc SQL against a data lake, the `PrestoOperator` (or `TrinoOperator` for Trino) is perfect.

```python
from airflow import DAG
from airflow.providers.presto.operators.presto import PrestoOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "analytics",
    "retries": 2,
    "retry_delay": timedelta(minutes=5),
}

with DAG(
    dag_id="presto_daily_aggregation",
    default_args=default_args,
    schedule_interval="@hourly",
    start_date=datetime(2024, 7, 1),
    catchup=False,
) as dag:

    aggregate = PrestoOperator(
        task_id="run_daily_agg",
        presto_conn_id="presto_aws",
        sql="""
        INSERT INTO analytics.daily_sales
        SELECT
            date_trunc('day', order_ts) AS day,
            SUM(amount) AS total_sales,
            COUNT(*) AS order_cnt
        FROM raw.orders
        WHERE order_ts >= DATE_ADD('day', -1, CURRENT_DATE)
        GROUP BY 1
        """,
        dag=dag,
    )
```

### 4.5 Example End‑to‑End ETL DAG (Spark → S3 → Redshift)

Below is a **complete** DAG that demonstrates a typical data‑engineering flow:

```python
from airflow import DAG
from airflow.providers.amazon.aws.operators.s3_copy_object import S3CopyObjectOperator
from airflow.providers.amazon.aws.transfers.s3_to_redshift import S3ToRedshiftOperator
from airflow.providers.apache.spark.operators.spark_submit import SparkSubmitOperator
from datetime import datetime, timedelta

default_args = {
    "owner": "etl",
    "email_on_failure": True,
    "email": ["etl-alerts@mycompany.com"],
    "retries": 3,
    "retry_delay": timedelta(minutes=10),
}

with DAG(
    dag_id="spark_s3_redshift_etl",
    default_args=default_args,
    schedule_interval="0 4 * * *",  # Run daily at 04:00 UTC
    start_date=datetime(2024, 1, 1),
    catchup=False,
) as dag:

    # 1️⃣ Run Spark job that reads from raw Kafka topic, transforms, writes Parquet to S3
    spark_transform = SparkSubmitOperator(
        task_id="spark_transform",
        application="/opt/airflow/dags/jobs/transform_parquet.py",
        conn_id="spark_k8s",
        conf={
            "spark.kubernetes.namespace": "spark-etl",
            "spark.kubernetes.container.image": "myrepo/spark-transform:2024-01",
            "spark.driver.memory": "4g",
            "spark.executor.instances": "6",
            "spark.executor.memory": "8g",
        },
        packages="org.apache.spark:spark-sql-kafka-0-10_2.12:3.3.1",
        verbose=True,
    )

    # 2️⃣ Copy the resulting files to a versioned S3 prefix (optional step)
    copy_to_versioned = S3CopyObjectOperator(
        task_id="copy_to_versioned",
        source_bucket_name="raw-data-bucket",
        source_bucket_key="spark-output/{{ ds }}/",
        dest_bucket_name="processed-data-bucket",
        dest_bucket_key="sales/parquet/{{ ds }}/",
        aws_conn_id="aws_default",
    )

    # 3️⃣ Load the Parquet files into Redshift using the COPY command
    load_to_redshift = S3ToRedshiftOperator(
        task_id="load_to_redshift",
        schema="analytics",
        table="daily_sales",
        s3_bucket="processed-data-bucket",
        s3_key="sales/parquet/{{ ds }}/",
        copy_options=["FORMAT AS PARQUET"],
        redshift_conn_id="redshift_default",
        aws_conn_id="aws_default",
    )

    spark_transform >> copy_to_versioned >> load_to_redshift
```

**Why this DAG works well on a K8s cluster:**

* **Spark job** runs in its own isolated pod with required libraries.
* **S3CopyObjectOperator** and **S3ToRedshiftOperator** are lightweight Python tasks that share the same Airflow worker pod resources.
* **Task dependencies** (`>>`) guarantee that the Redshift load only starts after the Parquet files are safely copied.

---

## 5. Scaling Strategies and Performance Tuning

A data‑processing cluster must handle **burst loads** (e.g., end‑of‑day batch windows) while staying cost‑efficient during idle periods. Below are proven tactics.

### 5.1 Horizontal Pod Autoscaling (HPA) for Workers

Airflow’s `KubernetesExecutor` already creates a pod per task, but you can also **autoscale the scheduler** and **webserver** to keep up with DAG parsing overhead.

```yaml
apiVersion: autoscaling/v2beta2
kind: HorizontalPodAutoscaler
metadata:
  name: airflow-scheduler-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: airflow-scheduler
  minReplicas: 2
  maxReplicas: 6
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

**Note:** For the **task pods** themselves, you can configure **`max_active_runs_per_dag`** and **`max_active_tasks`** to avoid overwhelming the cluster. The scheduler will automatically queue tasks when the cluster reaches its capacity.

### 5.2 Resource Requests & Limits

Define **CPU and memory** for each task explicitly. This prevents “noisy neighbor” issues where a Spark driver pod consumes all node resources, starving other tasks.

```python
task = BashOperator(
    task_id="large_sql",
    bash_command="psql -f query.sql",
    executor_config={
        "KubernetesExecutor": {
            "request_memory": "4Gi",
            "request_cpu": "2",
            "limit_memory": "6Gi",
            "limit_cpu": "3",
        }
    },
)
```

**Best practice:** Keep **requests ≤ limits** and aim for a **2:1 ratio** (request is half of limit) to give the scheduler room for burst spikes.

### 5.3 Queue Management and Prioritization

Airflow supports **multiple queues**. Assign high‑priority jobs (e.g., SLA‑critical pipelines) to a dedicated queue with a larger pool of worker pods.

```yaml
# values.yaml snippet
queues:
  high_priority:
    resources:
      requests:
        cpu: "2"
        memory: "4Gi"
  default:
    resources:
      requests:
        cpu: "500m"
        memory: "1Gi"
```

In the DAG:

```python
high_task = PythonOperator(
    task_id="critical_report",
    python_callable=generate_report,
    queue="high_priority",
)
```

### 5.4 Task Concurrency vs. DAG Concurrency

* **`max_active_tasks_per_dag`** – caps tasks for a single DAG.
* **`max_active_runs_per_dag`** – caps concurrent runs of the same DAG (useful for back‑fills).
* **`dag_concurrency`** (global) – caps total running tasks across all DAGs.

Fine‑tune these values based on your cluster’s capacity and the criticality of each pipeline.

### 5.5 Monitoring with Prometheus & Grafana

Airflow ships a **Prometheus exporter**. Enable it in `values.yaml`:

```yaml
metrics:
  enabled: true
  service:
    annotations:
      prometheus.io/scrape: "true"
      prometheus.io/port: "8080"
```

Create Grafana dashboards to visualize:

* **Task duration** (average, p95, p99).
* **Scheduler queue length**.
* **Worker pod restarts** (indicates instability).
* **Database connection pool usage**.

**Alerting**: Set up alerts for queue length > 200, task failure rate > 5 %, or scheduler CPU > 80 % for > 5 minutes.

---

## 6. High Availability & Disaster Recovery

A production data‑processing cluster must survive node failures, network partitions, and data loss.

### 6.1 Multi‑Master Scheduler Setup

Deploy **two scheduler replicas** behind a **leader election lock** (Airflow uses a database row to elect the leader). With `scheduler.replicas: 2` in Helm, both instances will compete; only one becomes active, the other stays idle ready to take over.

### 6.2 Database Replication and Backups

* **Primary‑Replica**: Use PostgreSQL streaming replication (e.g., CloudSQL read replica). Airflow reads from the primary; the replica can serve read‑only queries for reporting tools.
* **Point‑In‑Time Recovery (PITR)**: Enable WAL archiving to a bucket (GCS, S3) for recovery to any point within the retention window.
* **Backup Schedule**: Daily logical dumps (`pg_dump`) stored in a separate bucket, rotated weekly.

### 6.3 StatefulSet vs. Deployment for Scheduler/Webserver

Although the scheduler can be a **Deployment**, many teams prefer a **StatefulSet** to guarantee stable network identities for metrics scraping and for easier debugging. The webserver is typically a **Deployment** because it’s stateless.

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: airflow-scheduler
spec:
  serviceName: "airflow-scheduler"
  replicas: 2
  selector:
    matchLabels:
      component: scheduler
  template:
    metadata:
      labels:
        component: scheduler
    spec:
      containers:
        - name: scheduler
          image: apache/airflow:2.7.0
          command: ["airflow", "scheduler"]
```

---

## 7. Security Best Practices

### 7.1 RBAC in Airflow and Kubernetes

* **Airflow UI** – Enable **role‑based access control** (`rbac = True` in `airflow.cfg`). Define roles: `Viewer`, `Operator`, `Admin`.
* **Kubernetes** – Use **ServiceAccounts** per DAG or per task group. Grant the minimal set of permissions (e.g., only `pods/create` in the `airflow-tasks` namespace).

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  namespace: airflow-tasks
  name: task-runner
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["create", "delete", "get", "list", "watch"]
```

### 7.2 Network Policies & Service Meshes

Limit traffic between Airflow components and external services.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: airflow-egress
  namespace: airflow
spec:
  podSelector:
    matchLabels:
      component: scheduler
  policyTypes:
    - Egress
  egress:
    - to:
        - ipBlock:
            cidr: 10.0.0.0/8   # internal services
      ports:
        - protocol: TCP
          port: 5432           # PostgreSQL
        - protocol: TCP
          port: 8080           # Prometheus
```

If you use a **service mesh** (Istio, Linkerd), enable **mutual TLS** for inter‑pod communication and leverage mesh observability.

### 7.3 Credential Rotation and Secret Backend Choices

* **AWS IAM Roles for Service Accounts (IRSA)** – Use IAM roles attached to the K8s service account instead of static AWS keys.
* **Vault Dynamic Secrets** – Airflow’s Vault backend can generate temporary database credentials per task.
* **Rotation Schedule** – Rotate secrets every 30 days; integrate with CI/CD pipelines to rebuild Docker images if necessary.

---

## 8. Real‑World Case Studies

### 8.1 E‑Commerce Clickstream Processing (Spark → S3)

**Problem:** Process 500 GB of raw clickstream logs every hour, enrich them with product catalog data, and store results as partitioned Parquet in S3 for downstream analytics.

**Solution Architecture:**

1. **Ingestion:** Kafka topic `clicks_raw` → Spark Structured Streaming on K8s.
2. **Enrichment:** Broadcast join with product catalog (loaded from DynamoDB).
3. **Sink:** Write to S3 partitioned by `event_date` and `country`.
4. **Orchestration:** Airflow DAG triggers a **SparkSubmitOperator** every hour, monitors job status, and sends Slack alerts on failure.

**Key Metrics:**

| Metric | Before Airflow (manual cron) | After Airflow Cluster |
|--------|-----------------------------|-----------------------|
| Avg. processing time | 45 min | 28 min |
| Failure rate | 12 % (human error) | 2 % (automated retries) |
| Ops overhead | 6 h/week (manual) | < 1 h/week (monitoring) |

### 8.2 Financial Time‑Series Aggregation (Flink → Kafka → Snowflake)

**Problem:** Real‑time aggregation of market tick data, with sub‑second latency requirements for risk calculations.

**Solution:**

* Deploy **Flink on Kubernetes** via `FlinkKubernetesOperator`.
* Flink job consumes from `ticks` Kafka topic, computes minute‑level OHLCV bars, writes to Snowflake using the Snowflake JDBC sink.
* Airflow DAG manages **job lifecycle**: start job at market open, checkpoint every hour, stop at market close.

**Outcome:**

* Latency dropped from 2 seconds (legacy Spark) to **300 ms**.
* SLA compliance improved to **99.9 %**.
* Cost reduction of **30 %** by scaling down Flink task managers overnight.

### 8.3 Machine‑Learning Feature Store Refresh (Dask → Snowflake)

**Problem:** Nightly recompute feature vectors for millions of users, requiring heavy Python data‑science libraries (NumPy, Pandas, Scikit‑Learn).

**Solution:**

* Use **DaskKubernetesOperator** to spin up a Dask cluster with 10 workers (each 8 CPU, 32 GB RAM).
* Run a Python script that reads raw events from Snowflake, performs feature engineering, and writes back to a `feature_store` table.
* Airflow monitors the Dask job, retries on worker failures, and triggers downstream model training DAGs.

**Results:**

* Feature generation time reduced from 5 hours to **1.2 hours**.
* Resource utilization improved via auto‑scaled Dask workers.
* Pipeline reliability increased, with **zero data loss** across nightly runs.

---

## 9. Conclusion

Building a robust **Airflow data processing cluster** is no longer a niche engineering effort—it’s a foundational capability for modern data‑centric organizations. By leveraging the **KubernetesExecutor**, you gain:

* **Container‑level isolation** for heterogeneous workloads (Spark, Dask, Flink, Presto).
* **Dynamic scaling** that matches the bursty nature of batch windows and streaming jobs.
* **Fine‑grained security** through Kubernetes RBAC, network policies, and secret backends.

Key takeaways for a production‑ready deployment:

1. **Start with a solid Helm‑based installation** and a dedicated PostgreSQL instance.
2. **Configure a pod template** that includes necessary IAM roles, volume mounts, and resource defaults.
3. **Choose the right executor** (KubernetesExecutor for most cloud‑native workloads; CeleryExecutor if you must stay on VMs).
4. **Integrate data‑processing engines** via native Airflow operators and keep Docker images versioned.
5. **Implement autoscaling, monitoring, and alerting** to keep the cluster healthy and cost‑effective.
6. **Plan for HA and disaster recovery**—multiple schedulers, DB replication, and regular backups.
7. **Secure everything** from UI access to pod creation permissions.

When these pieces come together, you’ll have a **scalable, observable, and secure platform** that can run anything from a simple daily CSV load to a multi‑stage streaming analytics pipeline—all orchestrated through clean, Pythonic DAGs. The examples and best practices presented here should give you a concrete roadmap to design, deploy, and operate such a cluster in your organization.

Happy orchestrating!

---

## 10. Resources

* **Apache Airflow Documentation** – Comprehensive guide to installation, executors, and operators.  
  [Apache Airflow Docs](https://airflow.apache.org/docs/)

* **Airflow Helm Chart Repository** – Official Helm chart with configurable values for Kubernetes deployments.  
  [Airflow Helm Chart](https://github.com/apache/airflow/tree/main/chart)

* **Kubernetes Executor Deep Dive** – Blog post by Astronomer explaining the internals of the K8s executor and best‑practice patterns.  
  [Astronomer – KubernetesExecutor Overview](https://www.astronomer.io/guides/kubernetes-executor/)

* **Spark on Kubernetes Documentation** – Official Spark guide for running Spark jobs on K8s clusters.  
  [Spark on Kubernetes](https://spark.apache.org/docs/latest/running-on-kubernetes.html)

* **Prometheus & Grafana Integration for Airflow** – Tutorial on exposing Airflow metrics and building dashboards.  
  [Monitoring Airflow with Prometheus](https://medium.com/apache-airflow/monitoring-apache-airflow-with-prometheus-and-grafana-5e6b3c5a2f1b)

* **HashiCorp Vault Airflow Backend** – How to configure Airflow to retrieve secrets from Vault.  
  [Vault Backend for Airflow](https://developer.hashicorp.com/vault/docs/integrations/airflow)

---