---
title: "Scaling Playwright Sharded Test Runs Across Kubernetes with Allure Reporting"
date: "2026-09-06T16:00:30.978"
draft: false
tags: ["playwright", "kubernetes", "allure", "ci-cd", "testing", "test-infrastructure"]
description: "Practical guide to running Playwright in parallel across Kubernetes shards with aggregated Allure reports for fast, observable end-to-end testing."
summary: "How to shard Playwright test suites across Kubernetes pods, aggregate results into a single Allure report, and keep the loop fast for engineers."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-scaling-playwright-sharded-test-runs-across-kubernetes-with-allure-reporting.svg"
  alt: "Kubernetes pods running Playwright shards feeding results into an Allure report dashboard."
  caption: ""
  relative: false
---

> **TL;DR** — Sharding Playwright across Kubernetes turns a 40-minute serial suite into a 6-minute parallel run, but the hard part is making failures observable. Pair a per-pod blob reporter with a shared object store, then have a final aggregator job render a single Allure report with retries, history, and trends — so engineers see one clean dashboard instead of N pod logs.

## Why Shard Playwright in the First Place

A Playwright suite that fits comfortably on a developer's laptop becomes painful the moment it lands in CI. Once you cross a few hundred tests, headless Chromium, Firefox, and WebKit all firing in sequence against a real browser engine, you'll see wall-clock times balloon from "a coffee break" to "an entire afternoon." Two paths exist: buy a bigger box, or run more boxes.

Sharding is the second path. Playwright ships with first-class support for it — the [`--shard`](https://playwright.dev/docs/test-parallel#shard-tests-between-multiple-machines) flag splits the test file list by index and total, so you can run the same suite on N machines and each one executes a deterministic slice. When every shard finishes, you merge the JSON blob reports, render them, and ship the result to whoever's waiting on the merge queue.

Kubernetes is the natural execution surface: it gives you a node pool, ephemeral pods, clean teardown, and a control plane that already integrates with every CI system you're likely using. The catch is that a naïve kubectl-based fan-out leaves you with N HTML reports and an engineer spelunking through pod logs. The fix is to add one piece of durable infrastructure — an object store bucket — and one final aggregator job. With those, you get a single, navigable Allure report for the entire run, every time.

## The Architecture at a Glance

Before diving into the YAML, it helps to see the moving parts. Each run has four distinct actors:

1. **CI orchestrator** — GitHub Actions, GitLab CI, Buildkite, or Jenkins triggers a job and waits for a URL. It knows nothing about Kubernetes internals.
2. **Kubernetes Job** — A `Job` resource with `parallelism: N` spawns N pods. Each pod runs the Playwright shard, writes JSON/asset blobs to a shared bucket, and exits.
3. **Object store** — S3, GCS, MinIO, or an in-cluster PVC. Holds the per-pod reports plus a running `history/` directory used by Allure for trend charts.
4. **Aggregator Job** — A second Kubernetes `Job` runs after the test pods complete, downloads all per-shard artifacts, runs `allure generate`, optionally `allure report --serve` or uploads the static site to S3/Allure Server, and exits 0.

```
        ┌──────────────┐
        │ CI Trigger   │
        └──────┬───────┘
               │ creates
               ▼
       ┌─────────────────┐
       │ K8s Job         │  parallelism: N
       │  ┌────┐ ┌────┐  │
       │  │Pod1│ │Pod2│  │  ... PodN
       │  └─┬──┘ └─┬──┘  │
       └────│──────│─────┘
            │      │
            ▼      ▼
       ┌─────────────────┐
       │  Object Store   │  s3://bucket/<run-id>/shard-*/
       └────────┬────────┘
                │
                ▼
       ┌─────────────────┐
       │ Aggregator Job  │  allure generate + publish
       └─────────────────┘
```

This pattern is essentially [the dynamic job pattern](https://kubernetes.io/docs/concepts/workloads/controllers/job/#parallel-jobs) that Kubernetes ships for exactly this kind of fan-out/fan-in workload.

## Writing the Test Image

The pod needs a deterministic image: a fixed Node version, Playwright's browser binaries, the Allure CLI, and the test repo. The official [`mcr.microsoft.com/playwright`](https://playwright.dev/docs/docker) image covers the first three, so a thin Dockerfile is enough:

```dockerfile
FROM mcr.microsoft.com/playwright:v1.49.1-jammy

RUN npm install -g allure-commandline@2.30.0 \
 && mkdir -p /app
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
```

Two environment variables drive the sharding math:

- `SHARD_INDEX` — which slice am I (0-based).
- `SHARD_TOTAL` — how many slices total.

Kubernetes injects these via the [`JobIndexRange` and `Completions` pattern](https://kubernetes.io/docs/tasks/job/indexed-parallel-processing-static-assignment/), or you can synthesize them with a small `env` block. Either way, the Playwright invocation is identical for every pod:

```bash
npx playwright test \
  --reporter=list,json,allure-playwright \
  --shard=$SHARD_INDEX/$SHARD_TOTAL
```

The triple reporter is the trick that makes aggregation painless. `list` gives you live pod logs. `json` produces one machine-readable blob per shard. `allure-playwright` produces the per-shard result directory that the aggregator later concatenates.

## The Kubernetes Job Manifest

A single manifest defines the whole run. The interesting bits are the parallelism, the per-pod env, and the bucket upload sidecar step.

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: playwright-e2e
  labels:
    test-run-id: "ci-2026-09-06-1600"
spec:
  parallelism: 8
  completions: 8
  completionMode: Indexed
  backoffLimit: 1
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      serviceAccountName: playwright-runner
      containers:
        - name: shard
          image: ghcr.io/acme/playwright-runner:1.49.1
          env:
            - name: SHARD_INDEX
              valueFrom:
                fieldRef:
                  fieldPath: metadata.labels['batch.kubernetes.io/job-completion-index']
            - name: SHARD_TOTAL
              value: "8"
            - name: RUN_ID
              value: "ci-2026-09-06-1600"
            - name: AWS_REGION
              value: us-east-1
            - name: BUCKET
              value: acme-test-artifacts
          command: ["bash", "-lc"]
          args:
            - |
              set -euo pipefail
              echo "Running shard ${SHARD_INDEX} of ${SHARD_TOTAL}"
              npx playwright test \
                --reporter=list,json,allure-playwright \
                --shard=${SHARD_INDEX}/${SHARD_TOTAL}
              aws s3 sync test-results/allure-results \
                s3://${BUCKET}/${RUN_ID}/shard-${SHARD_INDEX}/allure-results
              aws s3 cp test-results.json \
                s3://${BUCKET}/${RUN_ID}/shard-${SHARD_INDEX}/results.json
```

The `Indexed` completion mode is the cleanest way to get `0..N-1` into a pod without writing a controller. Each pod sees its own index in `batch.kubernetes.io/job-completion-index`, which is mapped straight into `SHARD_INDEX`. If you prefer the simpler "all pods get the same env" model, replace the `fieldRef` block with a hardcoded loop driven by `value: "0"` through `value: "7"` in eight separate manifests — uglier, but it works on older clusters.

### Service Account and IRSA

The pod needs credentials to write to the bucket. On EKS, the modern answer is [IAM Roles for Service Accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-account.html). Annotate the service account with the role ARN, and the AWS SDK inside the pod picks it up automatically — no static keys.

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: playwright-runner
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::123456789012:role/PlaywrightRunnerRole
```

On GKE, swap that for [Workload Identity](https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity). On a self-hosted cluster, a Velero-style [kube2iam](https://github.com/jtblin/kube2iam) deployment does the same thing with IAM roles. Whatever your platform, the rule is the same: no long-lived secrets in pod spec.

## The Aggregator Job

The aggregator waits for all eight shards to finish, pulls their artifacts, downloads the Allure history from the bucket, generates the report, and publishes the static site. A second `Job` resource expresses this:

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: playwright-aggregate
spec:
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: aggregate
          image: ghcr.io/acme/playwright-runner:1.49.1
          env:
            - { name: RUN_ID, value: "ci-2026-09-06-1600" }
            - { name: BUCKET, value: "acme-test-artifacts" }
            - { name: SHARD_TOTAL, value: "8" }
          command: ["bash", "-lc"]
          args:
            - |
              set -euo pipefail
              mkdir -p allure-merged allure-history
              for i in $(seq 0 $((SHARD_TOTAL-1))); do
                aws s3 sync --only-show-errors \
                  s3://${BUCKET}/${RUN_ID}/shard-${i}/allure-results \
                  allure-merged/
              done
              # Pull history so trend charts work
              aws s3 sync --only-show-errors \
                s3://${BUCKET}/history/ allure-history/ || true
              cp -r allure-history/* allure-merged/ || true

              allure generate allure-merged \
                --clean -o allure-report

              aws s3 sync allure-report \
                s3://${BUCKET}/${RUN_ID}/report/

              echo "Report ready at https://reports.acme.internal/${RUN_ID}/index.html"
```

Two details matter here:

- **History merging.** Allure's trend, retries, and duration charts only look meaningful if the new run sees the previous runs' data. Pulling `s3://bucket/history/` and dropping it into the merged results directory before `allure generate` is what turns a single-run snapshot into a useful trend line. After generation, copy the *new* history back so the next run inherits it.
- **Failure handling.** `aws s3 sync` returns 0 even when a shard has zero artifacts, but `set -euo pipefail` will still abort the script if `allure generate` finds no results. A common pattern is to seed an empty `allure-merged/` directory with a placeholder result if all shards failed, so CI gets a green aggregator and a clearly red test report.

### Orchestrating the Two Jobs

CI shouldn't be in the business of polling kubectl. A thin orchestrator script — or, increasingly, a Tekton or Argo Workflows pipeline — owns the sequence:

```bash
kubectl apply -f playwright-job.yaml
kubectl wait --for=condition=complete --timeout=30m job/playwright-e2e
kubectl apply -f playwright-aggregate-job.yaml
kubectl wait --for=condition=complete --timeout=10m job/playwright-aggregate
URL="https://reports.acme.internal/${RUN_ID}/index.html"
echo "::notice title=Report ready::$URL"
```

On Argo, the same logic is a [DAG of two `Resource` templates](https://argo-workflows.github.io/argo-workflows/workflow-templates/) with a `dependencies: [TestRun]` clause on the aggregator. On GitHub Actions, the [`cloud-platform-deploy/k8s-deploy`](https://github.com/marketplace/actions/k8s-deploy) action pairs nicely with a wait step that watches the Job's `status.conditions`.

## Patterns in Production

After running this shape across a couple of dozen services, a few patterns reliably separate the "works on my laptop" version from the one engineers actually trust.

### Right-Sizing Parallelism

Eight shards is not a magic number. The honest answer is "as many shards as your slowest test file, divided by your average per-file runtime." A common mistake is to over-shard a fast suite — if your entire suite is 90 seconds, splitting it across 16 pods mostly pays for image pull and cluster cold-start latency. A simple heuristic: aim for 4–8 minutes of wall-clock per shard. Anything shorter, and you should reduce `parallelism` or run more tests per shard.

### Pinning Browser Versions

Browser engines drift. A green run on Chromium 132 and a red run on Chromium 133 is a real failure mode, not a flake. Pin the Playwright Docker image tag and treat every bump as a deliberate change. The Playwright team's own [release notes](https://github.com/microsoft/playwright/releases) make this easy — a one-line PR bumps the image and CI tells you the truth.

### Handling Flakes with Retries

Allure's [retry semantics](https://allure-framework.github.io/allure-docs/) light up only when each shard emits its *own* retry history. Configure Playwright to retry at the suite level:

```ts
// playwright.config.ts
export default defineConfig({
  retries: process.env.CI ? 2 : 0,
  reporter: [
    ['list'],
    ['json', { outputFile: 'test-results/results.json' }],
    ['allure-playwright', { outputFolder: 'test-results/allure-results' }],
  ],
});
```

The `allure-playwright` reporter records every attempt as a separate step, so a test that passes on retry shows up as flaky in the trend chart — not as a pass. That single bit of metadata is the difference between "the dashboard lies" and "the dashboard is the source of truth."

### Ephemeral Test Targets

Pods can't reliably talk to `localhost` services. If your tests hit a staging URL, use a real DNS name that resolves to a stable environment. If they need to drive the service under test, deploy it as a sibling resource in the same namespace and wait for its readiness probe — patterns familiar from [`kind` for local CI](https://kind.sigs.k8s.io/) and [Tilt](https://tilt.dev/) for development loops.

### Cluster Sizing and Bin-Packing

Browsers are memory pigs. A Chromium process with three pages open easily takes 1.5 GB of RSS. On a `m6i.large`-class node (2 vCPU, 8 GB), you can comfortably run two Playwright pods. Anything denser and you'll see OOM kills that masquerade as test failures. If you're on a managed cluster, request a node pool dedicated to tests with a [taint](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/) so unrelated workloads don't evict your pods mid-test.

```yaml
spec:
  containers:
    - name: shard
      resources:
        requests: { cpu: "1", memory: "2Gi" }
        limits:   { cpu: "2", memory: "4Gi" }
  tolerations:
    - key: dedicated
      operator: Equal
      value: test-runners
      effect: NoSchedule
  nodeSelector:
    workload: test-runners
```

## Key Takeaways

- **Shard on the cluster, not on the CI runner.** Kubernetes `Job` parallelism gives you clean per-shard identity, native retries, and free garbage collection on teardown.
- **Per-pod blob reporters + one aggregator job is the simplest pattern that produces one Allure report.** Anything fancier (live merging, streaming dashboards) is incremental value, not a prerequisite.
- **A shared bucket is non-negotiable.** It's how history survives across runs, how artifacts survive across shards, and how the trend chart stays meaningful.
- **Pin everything.** Image tag, Playwright version, Node version, Allure CLI version. Browser engines silently regressing is one of the most expensive classes of flake.
- **Treat retries as first-class signal.** A flaky test that passes on retry should appear flaky in the report, not green — that distinction is what makes the dashboard trustworthy.

## Further Reading

- [Playwright Sharding Documentation](https://playwright.dev/docs/test-parallel#shard-tests-between-multiple-machines)
- [Kubernetes Indexed Jobs for Parallel Processing](https://kubernetes.io/docs/tasks/job/indexed-parallel-processing-static-assignment/)
- [Allure Framework Reference](https://allure-framework.github.io/allure-docs/)
- [AWS IAM Roles for Service Accounts](https://docs.aws.amazon.com/eks/latest/userguide/iam-roles-for-service-account.html)
- [Argo Workflows Resource Templates](https://argo-workflows.github.io/argo-workflows/workflow-templates/)