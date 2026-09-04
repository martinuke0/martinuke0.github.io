---
title: "Implementing Karpenter's Consolidation Disruption Policies for Spot Instance Workloads"
date: "2026-09-04T02:00:44.255"
draft: false
tags: ["kubernetes", "karpenter", "spot-instances", "cost-optimization", "aws-eks"]
description: "A practical guide to configuring Karpenter consolidation disruption policies for Spot workloads, with patterns for cost savings and stability on EKS."
summary: "How to design consolidation disruption policies in Karpenter that aggressively reclaim underutilized nodes without thrashing your Spot workloads, with real EKS configuration examples."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-implementing-karpenter.svg"
  alt: "Diagram of Karpenter consolidation evaluating nodes for replacement on a Kubernetes cluster."
  caption: ""
  relative: false
---

> **TL;DR** — Consolidation is Karpenter's most powerful disruption policy because it can both *replace* nodes (drift) and *delete* underutilized ones. For Spot workloads, the right pattern is `consolidateAfter` with a price-capacity-optimized instance mix, per-workload `doNotDisrupt` annotations for steady-state batch jobs, and `expireAfter` as a hard backstop. Get the defaults wrong and you get either wasted spend or a self-inflicted pod rebalance every five minutes.

## Why Consolidation Is Different From Drift or Expiration

Karpenter ships four disruption mechanisms, and they solve very different problems:

- **Drift** reacts to AWS-side changes: instance type deprecation, a node getting marked unhealthy, the AMI no longer matching the latest `EC2NodeClass`. This is non-negotiable — you *have* to roll those nodes.
- **Expiration** rotates nodes after a TTL you set (`expireAfter`). It's a blunt instrument, mostly there to keep AMIs, kubelet versions, and instance generations fresh.
- **Deletion** is what you call manually via `kubectl delete node` or by setting a node's `karpenter.sh/do-not-disrupt` annotation and removing it.
- **Consolidation** is the one that actually saves money. It looks at the cluster and asks: *if I removed this node, would the rest of the cluster still fit?* If yes, it deletes the node. It also asks: *if I replaced this node with a different instance type — one that's cheaper or has better Spot capacity — would everything still fit?* If yes, it cordons, drains, and replaces.

The reason consolidation is tricky on Spot is that the second question (replace with a cheaper or better-capacity instance) can produce a constant churn loop if your consolidation policy fires too aggressively. A 10% bin-packing improvement isn't worth a 5-minute pod rebalance.

Karpenter's docs cover the disruption model in detail in [Disruption](https://karpenter.sh/docs/concepts/disruption/), and the consolidation section is worth re-reading every time you tune a fleet.

## The Three Consolidation Knobs

In a `NodePool` (v1) or `EC2NodeClass` setup, you have three consolidation-related fields that matter for Spot:

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-mixed
spec:
  template:
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot"]
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
      nodeClassRef:
        apiVersion: karpenter.k8s.aws/v1beta1
        kind: EC2NodeClass
        name: default
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h
  limits:
    cpu: "200"
    memory: 800Gi
```

The three knobs are:

1. **`consolidationPolicy`** — either `WhenUnderutilized` (only delete truly empty-ish nodes) or `WhenEmptyOrUnderutilized` (also force-replace nodes that *could* be cheaper even if they're not underutilized). The second one is more aggressive and more dangerous for Spot.
2. **`expireAfter`** — the hard TTL. Setting this to something like `720h` (30 days) means even if consolidation never fires, nodes still get recycled monthly.
3. **Per-pod `karpenter.sh/do-not-disrupt: "true"`** — an annotation that opts a workload *out* of disruption entirely. Critical for batch jobs and stateful workloads.

There are also consolidation *budgets* (`schedules`, `duration`, `nodes`) that rate-limit how many nodes can be disrupted in a window. For multi-tenant clusters, these are non-negotiable — without them, a quiet Sunday morning can turn into a 50-node simultaneous drain.

## Pattern: The "Steady-State Spot" Configuration

The configuration I reach for most often on EKS production clusters looks like this:

```yaml
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-batch
spec:
  template:
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
        - key: karpenter.k8s.aws/instance-size
          operator: In
          values: ["large", "xlarge", "2xlarge"]
        - key: topology.kubernetes.io/zone
          operator: In
          values: ["us-east-1a", "us-east-1b", "us-east-1c"]
      nodeClassRef:
        apiVersion: karpenter.k8s.aws/v1beta1
        kind: EC2NodeClass
        name: default
  disruption:
    consolidationPolicy: WhenUnderutilized
    expireAfter: 720h
    budgets:
      - nodes: "10%"
        schedule: "0 9 * * mon-fri"
        duration: 8h
      - nodes: "0"
        schedule: "0 17 * * mon-fri"
        duration: 16h
```

The shape of the intent: consolidation runs aggressively *during business hours Monday through Friday* (when engineers can respond to weird scheduling artifacts), and is disabled during the overnight weekend window when nobody wants a paging alert. `WhenUnderutilized` is deliberately chosen over `WhenEmptyOrUnderutilized` so we don't churn nodes just because a 2xlarge could fit on a 4xlarge slightly better.

## Pattern: When to Use `WhenEmptyOrUnderutilized`

The `WhenEmptyOrUnderutilized` policy is the right call in one specific situation: when your Spot pricing is volatile enough that instance types *you selected last week* are now 30% more expensive than *instance types you didn't select last week*. If your node is running a `c6i.2xlarge` that costs $0.10/hr on Spot but a `c6a.2xlarge` of the same size is now at $0.06/hr, Karpenter will replace the node — and it will, because that's real money over a month.

The trade-off is that this policy triggers *more often*, and replacement is inherently a disruptive operation. You can't avoid the cordoning and draining. The mitigation is to:

1. **Pick a broad instance set** so the optimizer has somewhere cheaper to go. If your requirements only allow `c6i.*`, the optimizer is locked in.
2. **Use `consolidateAfter`** to delay the action. This is a newer field that says "wait N minutes before consolidating this node" — perfect for absorbing a transient cost spike.

```yaml
disruption:
  consolidationPolicy: WhenEmptyOrUnderutilized
  consolidateAfter: 10m
  expireAfter: 720h
```

`consolidateAfter: 10m` means Karpenter will not consolidate a node that was just created unless it has been at least 10 minutes since launch. This is the single most useful field for Spot because Spot prices fluctuate minute to minute, and you don't want to do a 10-minute consolidation cycle for a price difference that lasts 6 minutes.

The [Karpenter consolidation docs](https://karpenter.sh/docs/concepts/disruption/#consolidation) are explicit about this: consolidation considers both price and bin-packing, and `WhenEmptyOrUnderutilized` is the only mode that triggers on price alone.

## The `doNotDisrupt` Annotation Pattern

Some workloads are simply not safe to interrupt. The canonical example is a Spark driver that holds shuffle state in memory and a 5-minute checkpoint interval. If you disrupt that pod, you lose 5 minutes of work.

The annotation is:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ml-trainer
  annotations:
    karpenter.sh/do-not-disrupt: "true"
spec:
  template:
    metadata:
      labels:
        app: ml-trainer
    spec:
      containers:
        - name: trainer
          resources:
            requests:
              cpu: "4"
              memory: "16Gi"
```

When this annotation is set, Karpenter will skip the node for any disruption reason *except* drift (which can be forced with `karpenter.sh/forced-do-not-disrupt` semantics if needed for emergency AMI patches). For batch jobs with a defined end, this is much cleaner than the older pattern of relying on `PodDisruptionBudgets` plus tight `terminationGracePeriodSeconds`, because PDBuffers are eventually consistent and Karpenter evaluates them in the controller loop.

A common anti-pattern: setting `doNotDisrupt: "true"` on a workload that doesn't actually need it, like a stateless API. This pins the node indefinitely and you lose the cost benefit of consolidation. Audit these annotations regularly with a query like:

```bash
kubectl get deployments -A -o json | \
  jq -r '.items[] | select(.metadata.annotations["karpenter.sh/do-not-disrupt"] == "true") | "\(.metadata.namespace)/\(.metadata.name)"'
```

You'd be surprised how many teams set it during a debugging session in March and never take it off.

## Architecture: How Karpenter Decides What to Consolidate

The decision loop is worth understanding because it informs how you write your requirements. When the consolidation controller wakes up (every few seconds, by default), it:

1. Enumerates all candidate nodes in the NodePool.
2. For each node, runs a simulation: "if I removed this node, would the pods on it fit on the remaining cluster?"
3. If yes, the node is a **deletion candidate**.
4. Separately, for each deletion candidate, it asks: "could this node be replaced with a different instance type that's cheaper *or* has better Spot capacity?"
5. If yes, the node is a **replacement candidate** (deletion + launch).

The simulation is the key. Karpenter uses the actual scheduler, so it respects taints, topology spread, affinity, and resource requests. A node that *looks* underutilized (1 pod, 10% CPU used) is not a deletion candidate if that pod has a `topology.kubernetes.io/zone: us-east-1d` constraint and the only other node in that zone is full.

This is also why **overly broad topology constraints** hurt consolidation. If you say "spread across all 4 zones" but you only have capacity in 3, the fourth zone's nodes become undeletable.

The [AWS Karpenter GitHub](https://github.com/aws/karpenter-provider-aws) repository has the consolidation logic in `pkg/controllers/disruption/`. If you're going to run Karpenter in production, it's worth reading the [`simulator`](https://github.com/aws/karpenter-provider-aws/tree/main/pkg/scheduling) package — it tells you exactly what Karpenter is and isn't willing to do.

## Patterns in Production: Three Real Configurations

### 1. The ML Training Cluster

A cluster running SageMaker-style training jobs. Workloads are long (4–12 hours), interruption-tolerant at the *job* level (the training script saves checkpoints), but disruptive to interrupt *within* a checkpoint interval.

```yaml
disruption:
  consolidationPolicy: WhenUnderutilized
  expireAfter: 168h  # 7 days
  budgets:
    - nodes: "5"
      schedule: "@every 6h"
```

Why: `WhenUnderutilized` only deletes empty nodes, so running training jobs are never replaced. The 7-day expiration catches nodes that are pinned by an over-zealous `doNotDisrupt`. The budget limits Karpenter to 5 disruptions per 6 hours, which is enough to clean up post-job but not enough to cause a thundering herd.

### 2. The Stateless Web Tier

A typical 3-tier web app, hundreds of replicas, behind a load balancer. Pure horizontal scale, stateless, fully interruption-tolerant.

```yaml
disruption:
  consolidationPolicy: WhenEmptyOrUnderutilized
  consolidateAfter: 15m
  expireAfter: 720h
```

Why: aggressive replacement is safe because pods restart in 5 seconds and the HPA absorbs the blip. `consolidateAfter: 15m` absorbs transient Spot price spikes. 30-day expiration handles AMI rotation.

### 3. The Cost-Optimized Batch Cluster

A cluster that runs nightly ETL. Pods are short-lived (minutes), everything is replaceable, the only concern is total cost.

```yaml
disruption:
  consolidationPolicy: WhenEmptyOrUnderutilized
  expireAfter: 24h
  budgets:
    - nodes: "100%"
```

Why: nightly ETL means nodes get created around midnight and torn down around 4am. 24-hour expiration is a backstop, but consolidation will do most of the work. The `100%` budget means "disrupt as many as you want" — there's no human pager concern at 3am, and the ETL is idempotent.

## Spot-Specific Gotchas

A few failure modes that only show up with Spot:

- **Capacity blocks drain too aggressively.** If you're using [EC2 Capacity Blocks for ML](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-capacity-blocks.html), you want to be careful with consolidation. A capacity block reservation is a 1-14 day scheduled reservation; consolidation doesn't understand this and may try to replace nodes in a capacity reservation thinking they're interchangeable with on-demand.

- **Capacity-optimized allocation strategy.** Set `allocationStrategy: capacity-optimized` on the `EC2NodeClass` if you want Karpenter to ask AWS for the cheapest Spot pool that *also* has the best chance of having capacity. This dramatically reduces the frequency of Spot interruptions and is the recommended default in the [AWS Karpenter best practices guide](https://aws.github.io/aws-eks-best-practices/karpenter/).

- **Interruption handling.** Karpenter has a [Spot interruption handler](https://github.com/aws/karpenter-provider-aws/blob/main/docs/interruption.md) that polls the EC2 metadata for the 2-minute interruption notice and proactively drains the node. This works *alongside* consolidation, not against it — when an interruption notice fires, Karpenter treats it as drift and replaces the node immediately.

## Key Takeaways

- **Start with `WhenUnderutilized`** and only move to `WhenEmptyOrUnderutilized` once you understand the cost trade-offs. The second policy will save you more money but is much more disruptive.
- **Use `consolidateAfter`** (10–15 minutes) to absorb transient Spot price spikes. This is the single highest-leverage field for Spot workloads.
- **Audit `doNotDisrupt` annotations quarterly** — they accumulate, and every one is a node that consolidation cannot touch.
- **Use disruption budgets** for any cluster that other humans depend on. Without them, a quiet cluster on a Sunday morning will turn into a 30-node simultaneous drain.
- **Pair consolidation with a Spot interruption handler** and a 30-day `expireAfter` so you're protected from price volatility, capacity loss, and AMI drift all at once.
- **Broaden your instance requirements** if you want aggressive replacement to actually be cheaper. A 3-instance-type constraint gives the optimizer no room to maneuver.

## Further Reading

- [Karpenter Disruption Concepts](https://karpenter.sh/docs/concepts/disruption/)
- [Karpenter AWS Provider Best Practices](https://aws.github.io/aws-eks-best-practices/karpenter/)
- [AWS Spot Instance Interruption Notices](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-instance-termination-notices.html)
- [Karpenter Spot Interruption Handling](https://github.com/aws/karpenter-provider-aws/blob/main/docs/interruption.md)
- [EC2 Spot Capacity-Optimized Allocation Strategy](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-best-practices.html)
- [Karpenter GitHub Repository](https://github.com/aws/karpenter-provider-aws)