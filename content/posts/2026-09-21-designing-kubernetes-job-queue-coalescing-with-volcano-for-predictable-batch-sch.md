---
title: "Designing Kubernetes Job Queue Coalescing with Volcano for Predictable Batch Scheduling"
date: "2026-09-21T15:00:45.846"
draft: false
tags: ["kubernetes", "volcano", "batch-scheduling", "job-coalescing", "resource-management", "distributed-systems"]
description: "Learn how to design Kubernetes job queue coalescing with Volcano to eliminate scheduling fragmentation and achieve predictable batch workloads at scale."
summary: "Explore how Volcano's queue architecture and gang scheduling enable job coalescing strategies that reduce scheduling latency and deliver predictable batch execution in Kubernetes."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-21-designing-kubernetes-job-queue-coalescing-with-volcano-for-predictable-batch-sch.svg"
  alt: "Kubernetes Volcano scheduler dashboard showing coalesced batch job queues"
  caption: ""
  relative: false
---

> **TL;DR** — Kubernetes' default scheduler lacks native support for batch-oriented job coalescing, leading to fragmented resource allocation and unpredictable scheduling latency. Volcano fills this gap with its queue hierarchy, gang scheduling, and customizable scheduling policies. By designing a coalescing layer on top of Volcano's queue API, teams can bundle complementary batch jobs into single scheduling units, dramatically improving cluster utilization and predictability.

## Why Default Kubernetes Scheduling Fails Batch Workloads

The Kubernetes default scheduler is purpose-built for long-running microservices. It optimizes for individual pod placement using bin-packing and spreading heuristics, but it has no concept of a job queue, no gang scheduling semantics, and no mechanism to coordinate the simultaneous placement of pods that belong to the same logical unit of work.

Batch workloads expose these gaps immediately:

- **ML training jobs** require all replicas to start simultaneously. If even one pod cannot be scheduled, the entire job stalls.
- **Data pipeline stages** have strict ordering dependencies. A downstream task cannot begin until upstream tasks complete, and partial scheduling creates wasted intermediate state.
- **Scientific simulations** often demand exclusive access to a fixed set of nodes for the duration of the run, precluding interleaving with other workloads.

The default scheduler handles these scenarios through `PodGroup`, a CRD that signals the scheduler to wait for all pods in a group. But `PodGroup` is a blunt instrument. It does not coalesce jobs across namespaces, does not prioritize within a queue, and offers no policy engine for bundling complementary workloads.

This is where Volcano enters the picture.

## Volcano's Architecture for Batch Scheduling

Volcano is a Kubernetes-native batch scheduling system originally contributed by VMware and now a graduated CNCF project. It introduces several primitives that the default scheduler lacks:

- **Queues**: Logical partitions for workload isolation and priority management.
- **Jobs**: A higher-level abstraction (`Job` CRD) that groups pods and enforces gang scheduling.
- **Scheduling Policies**: Pluggable algorithms (FIFO, DRF, WF1D, etc.) that determine how queues and jobs compete for resources.
- **Actions and Plugins**: A hook-based architecture for customizing scheduling behavior at multiple points in the lifecycle.

The core scheduling flow in Volcano proceeds as follows:

```
Pod submitted → Assigned to Queue → Job created → Gang scheduling trigger → Plugin chain → Binding
```

Each queue can have its own scheduling policy, priority weight, and resource guarantee. This hierarchy — cluster → queue → job → pod — is what makes coalescing possible.

## The Problem of Job Queue Fragmentation

Queue fragmentation occurs when available resources are scattered across nodes in small increments that cannot satisfy any single pending job's resource request. Consider a cluster with 100 nodes, each offering 8 CPUs and 32 GiB of memory. If 50 batch jobs each request 4 CPUs and 16 GiB, the default scheduler might place them such that remaining resources on each node are 4 CPUs and 16 GiB — enough for one more job per node, but not enough for any job requesting 8 CPUs.

Now imagine that a new job arrives requesting 8 CPUs and 32 GiB. Despite the cluster having 50% aggregate free resources, no single node can satisfy it. The job sits in a pending state while fragmented free capacity goes unused.

In Volcano, this problem is amplified by queue isolation. Queue A might have 40% of the cluster reserved but only 10% utilized, while Queue B has 20% reserved and 90% utilized. Without coalescing, Queue A's reserved resources sit idle while Queue B's jobs wait.

## Designing Job Queue Coalescing

Job queue coalescing is the practice of combining multiple smaller, complementary jobs into a single scheduling unit so that the scheduler can place them together on a coherent set of nodes. This is distinct from simply increasing resource requests — it is a deliberate architectural pattern for improving scheduling density.

### Coalescing Strategies

There are three primary strategies to consider:

1. **Horizontal Coalescing**: Bundle multiple independent jobs that share resource profiles into a single gang. For example, ten hyperparameter-tuning trials each requesting 2 CPUs can be coalesced into one gang of 20 CPUs total.

2. **Vertical Coalescing**: Combine jobs with different resource profiles (CPU-heavy and memory-heavy) that can be packed onto complementary node pools. A CPU-intensive preprocessing step and a memory-intensive model inference step can share a queue and be scheduled together.

3. **Temporal Coalescing**: Delay the scheduling of a small job until a compatible job arrives, then coalesce them into a single scheduling decision. This requires a custom scheduling plugin or an external coordinator.

### Architecture of a Coalescing Layer

A production-grade coalescing layer sits between the job submission interface and Volcano's queue API. The architecture typically involves:

```
Job Submission API → Coalescing Engine → Volcano Queue → Volcano Scheduler → Nodes
```

The coalescing engine is responsible for:

- **Buffering**: Holding incoming jobs briefly to accumulate compatible tasks.
- **Matching**: Identifying jobs that can share a gang or queue based on resource profiles, node affinity, and priority.
- **Bundling**: Creating a single Volcano `Job` CRD that encompasses multiple logical tasks.
- **Decomposition**: Splitting the bundled job back into individual tasks upon completion for result aggregation.

Here is a simplified Go-based coalescing engine skeleton:

```go
package main

import (
	"context"
	"fmt"
	"sync"
	"time"

	volcanoapi "volcano.sh/apis/pkg/apis/scheduling/v1beta1"
)

type Coalescer struct {
	queue       string
	buffer      map[string][]*volcanoapi.Job
	mu          sync.RWMutex
	flushPeriod time.Duration
}

func NewCoalescer(queue string, flushPeriod time.Duration) *Coalescer {
	return &Coalescer{
		queue:       queue,
		buffer:      make(map[string][]*volcanoapi.Job),
		flushPeriod: flushPeriod,
	}
}

func (c *Coalescer) SubmitJob(ctx context.Context, job *volcanoapi.Job) error {
	c.mu.Lock()
	defer c.mu.Unlock()

	key := c.coalescingKey(job)
	c.buffer[key] = append(c.buffer[key], job)

	if len(c.buffer[key]) >= c.maxBatchSize() {
		return c.flush(ctx, key)
	}

	go c.scheduleFlush(key)
	return nil
}

func (c *Coalescer) coalescingKey(job *volcanoapi.Job) string {
	// Group by node affinity, resource profile, and priority class
	return fmt.Sprintf("%s-%s-%s",
		job.Spec.Policies[0].ResourceName,
		job.Spec.NodeSelector,
		job.Spec.PriorityClassName,
	)
}

func (c *Coalescer) flush(ctx context.Context, key string) error {
	jobs := c.buffer[key]
	delete(c.buffer, key)

	bundled := c.bundleJobs(jobs)
	// Submit bundled job to Volcano queue
	return c.submitToVolcano(ctx, bundled)
}

func (c *Coalescer) bundleJobs(jobs []*volcanoapi.Job) *volcanoapi.Job {
	// Merge pod specs, aggregate resource requests,
	// create a single Volcano Job with multiple task sets
	bundled := &volcanoapi.Job{
		Spec: volcanoapi.JobSpec{
			MinAvailable: jobs[0].Spec.MinAvailable,
			Policies:     jobs[0].Spec.Policies,
		},
	}
	// ... merge logic ...
	return bundled
}
```

### Configuring Volcano Queues for Coalescing

Volcano queues are defined via the `Queue` CRD. A coalescing-optimized setup uses a hierarchical queue structure:

```yaml
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: batch-coalesced
spec:
  weight: 100
  schedulingPolicy:
    policy: DRF
  gangs:
    minMember: 1
  reclaimable: true
  namespace:
    namespaces:
      - batch-jobs
```

Key configuration points:

- **`schedulingPolicy: DRF`** (Dominant Resource Fairness) ensures that queues with different resource profiles compete fairly rather than starving one another.
- **`gangs.minMember`** set to `1` allows single-pod gangs, which is necessary when the coalescing engine handles bundling externally.
- **`reclaimable: true`** allows the scheduler to reclaim resources from lower-priority jobs when higher-priority coalesced batches arrive.

For a multi-tier setup:

```yaml
# Parent queue
apiVersion: scheduling.volcano.sh/v1beta1
kind: Queue
metadata:
  name: batch-parent
spec:
  weight: 100
  queues:
    - name: high-priority-coalesced
      weight: 70
      schedulingPolicy:
        policy: DRF
    - name: low-priority-coalesced
      weight: 30
      schedulingPolicy:
        policy: FIFO
```

## Patterns in Production

### Pattern 1: Slot-Based Coalescing

In production ML platforms, teams often reserve fixed "slots" on nodes for batch workloads. A slot represents a guaranteed fraction of node resources. The coalescing engine fills slots by bundling small jobs until the slot is full, then submits the bundle as a single Volcano job.

This pattern reduces scheduling overhead from O(n) individual bindings to O(n/slot-size) batched bindings. At scale, this can reduce average scheduling latency from minutes to seconds.

### Pattern 2: Priority-Aware Preemption Coalescing

When a high-priority job arrives and cannot be immediately satisfied, the coalescing engine can preempt lower-priority jobs, coalesce the reclaimed resources with the new job's requirements, and submit a single bundled job. This requires Volcano's preemption plugin and careful configuration of `preemptible` flags on lower-priority queues.

### Pattern 3: Time-Window Coalescing for CI/CD Pipelines

CI/CD batch jobs often arrive in bursts (e.g., nightly builds). A time-window coalescer buffers jobs for a fixed interval (e.g., 60 seconds), then bundles all compatible jobs into a single Volcano gang. This maximizes node packing density and ensures that the entire pipeline stage completes in a single scheduling pass.

### Pattern 4: Hybrid Coalescing with Kueue

Kueue is a Kubernetes job queueing and admission controller that complements Volcano. In a hybrid architecture, Kueue handles admission and prioritization while Volcano handles gang scheduling and node placement. The coalescing engine sits between them, transforming Kueue `Workload` objects into Volcano `Job` objects with bundled task specifications.

```yaml
# Kueue Workload with coalescing hint
apiVersion: kueue.x-k8s.io/v1beta1
kind: Workload
metadata:
  name: ml-training-coalesced
spec:
  podSetSpecs:
    - template:
        spec:
          containers:
            - name: trainer
              resources:
                requests:
                  cpu: "2"
                  memory: 8Gi
  queueName: batch-coalesced
  # Coalescing annotation tells the engine to bundle
  annotations:
    kueue.x-k8s.io/coalesce-family: "ml-training-gpu"
```

## Monitoring and Tuning Coalesced Schedules

Coalescing introduces new observability requirements. You must track:

- **Coalescing latency**: Time spent in the buffer before flushing. This is a tradeoff — longer buffers yield better packing but increase job start time.
- **Bundling efficiency**: Ratio of requested resources to actually allocated resources. Low efficiency means the coalescing key is too broad and incompatible jobs are being bundled.
- **Queue depth**: Number of jobs waiting in Volcano queues. A growing depth signals that coalescing is not keeping pace with submission rate.
- **Preemption rate**: High preemption rates indicate that the queue weights or priority classes need adjustment.

Volcano exposes Prometheus metrics out of the box. Key metrics to monitor:

```promql
# Jobs pending in queue longer than 5 minutes
volcano_queue_job_count{queue_name="batch-coalesced", state="pending"} > 0
and
time() - volcano_queue_job_timestamp{queue_name="batch-coalesced"} > 300

# Gang scheduling success rate
rate(volcano_gang_scheduling_total{status="success"}[5m])
  /
rate(volcano_gang_scheduling_total[5m])
```

## Common Pitfalls and How to Avoid Them

1. **Over-coalescing**: Bundling too many jobs into a single gang increases the probability that scheduling fails entirely (all-or-nothing). Keep gang sizes manageable — typically under 50 pods per gang.

2. **Ignoring node topology**: Coalescing without considering node topology (zones, racks, GPU models) can result in bundles that are technically schedulable but performantly suboptimal. Always include topology constraints in your coalescing key.

3. **Queue starvation**: Aggressive coalescing in high-priority queues can starve lower-priority queues. Use Volcano's `fair-sharing` or `DRF` policies and set appropriate queue weights.

4. **Stateful coalescing**: Jobs with persistent volumes or stateful sets require careful handling. Coalescing must preserve volume claims and anti-affinity rules. Volcano supports this through its `podGroup` binding, but the coalescing engine must be aware of these constraints.

## Key Takeaways

- Volcano's queue hierarchy and gang scheduling provide the primitives necessary for job coalescing, but the coalescing logic itself typically requires a dedicated engine or controller.
- Horizontal, vertical, and temporal coalescing address different fragmentation patterns — choose the strategy that matches your workload characteristics.
- A well-tuned coalescing layer can reduce scheduling latency by an order of magnitude and improve cluster utilization by 30-50% for batch-heavy workloads.
- Monitor coalescing latency, bundling efficiency, and queue depth as first-class metrics; they reveal whether your coalescing strategy is helping or hurting.
- Combining Kueue for admission with Volcano for scheduling creates a powerful hybrid architecture that separates concerns and enables more sophisticated coalescing policies.
- Avoid over-coalescing: smaller, more frequent bundles with high compatibility scores outperform large, heterogeneous gangs that fail to schedule and waste resources.

## Further Reading

- [Volcano Official Documentation — Scheduling Policies](https://volcano.sh/docs/concepts/scheduling/policy/) — Comprehensive guide to Volcano's pluggable scheduling policies including DRf, WF1D, and FIFO.
- [Volcano Official Documentation — Queue Architecture](https://volcano.sh/docs/concepts/scheduling/queue/) — Detailed reference on queue configuration, hierarchy, and resource allocation.
- [Kueue: Job Queueing and Admission for Kubernetes](https://kueue.sigs.k8s.io/) — The Kubernetes-native job queueing system that complements Volcano for advanced batch workload management.
- [Volcano GitHub Repository — Gang Scheduling](https://github.com/volcano-sh/volcano/blob/main/docs/design/gang-scheduling.md) — Design document covering gang scheduling semantics and implementation details.
- [SIG Batch — Kubernetes Batch Workloads](https://github.com/kubernetes/sig-node/tree/main/proposals) — Community proposals and design documents related to batch scheduling in Kubernetes.
- [Dominant Resource Fairness: Fair Allocation in the Presence of Multiple Resource Dimensions](https://proceedings.mlr.press/v28/josefiroz13.html) — The foundational paper on DRF, the scheduling policy that underpins fair queue competition in Volcano.
