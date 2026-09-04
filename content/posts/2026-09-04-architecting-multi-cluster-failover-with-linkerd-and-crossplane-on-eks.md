---
title: "Architecting Multi-Cluster Failover with Linkerd and Crossplane on EKS"
date: "2026-09-04T12:00:37.398"
draft: false
tags: ["linkerd", "crossplane", "eks", "kubernetes", "service-mesh"]
description: "A hands-on architecture for active-passive failover across EKS regions using Linkerd's multi-cluster service mirroring and Crossplane's GitOps control plane."
summary: "How to design an active-passive multi-cluster failover pattern on EKS that combines Linkerd's transparent service mirroring with Crossplane's composable infrastructure claims."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-architecting-multi-cluster-failover-with-linkerd-and-crossplane-on-eks.svg"
  alt: "Multi-cluster failover diagram showing active and standby EKS regions connected through Linkerd gateways and Crossplane compositions."
  caption: ""
  relative: false
---

> **TL;DR** — Linkerd handles the data plane for failover by mirroring services between EKS clusters with built-in load balancing, retries, and mTLS, while Crossplane owns the control plane by treating clusters, databases, and DNS as composable claims. Together they let you express a regional failover policy in YAML and recover in minutes rather than hours.

Most multi-region Kubernetes architectures look great in diagrams and fall apart the moment a region degrades. The two failure modes I see most often are (1) the failover plan lives in someone's head and a runbook nobody has touched in six months, and (2) the mesh configuration drifts between clusters so the "standby" can never actually accept traffic from the "active." Linkerd and Crossplane attack both problems in complementary ways, and on EKS specifically they slot together cleanly because the AWS APIs they need are already well-modeled as Crossplane providers.

This post walks through a production-shaped architecture: an active cluster in `us-east-1`, a passive cluster in `us-west-2`, a Linkerd mesh that mirrors services across the two, and Crossplane compositions that let operators request "a multi-cluster checkout service" without writing Terraform by hand for the third time.

## The Architecture at a Glance

The split-of-concerns is simple and worth stating up front:

- **Linkerd** owns runtime traffic. It terminates mTLS, mirrors service endpoints across clusters via the multi-cluster gateway, retries failed calls, and exposes traffic split primitives for canary or shadow workflows.
- **Crossplane** owns the reconciliation of everything that isn't a request: EKS clusters, RDS instances, Route 53 records, IAM roles, VPC peering, ACM certificates, even the Linkerd control plane installs themselves.

In an active-passive setup, only one cluster serves live traffic at a time. The passive cluster runs the same workloads at a smaller scale (or scaled to zero for cheap stateful services) and is kept warm via Linkerd's service mirror controller. When health checks trip, Route 53 fails over the DNS record to the standby cluster's ingress, and the mesh routes existing connections to the healthy gateway.

```yaml
# Example: a Crossplane Composition for a multi-cluster service claim
apiVersion: apiextensions.crossplane.io/v1
kind: Composition
metadata:
  name: checkout-multiregion
spec:
  compositeTypeRef:
    apiVersion: multicluster.example.com/v1alpha1
    kind: CheckoutService
  resources:
    - name: east-cluster
      base:
        apiVersion: eks.crossplane.io/v1alpha1
        kind: Cluster
        spec:
          region: us-east-1
          nodeGroups: 2
          version: "1.29"
    - name: west-cluster
      base:
        apiVersion: eks.crossplane.io/v1alpha1
        kind: Cluster
        spec:
          region: us-west-2
          nodeGroups: 1
          version: "1.29"
    - name: route53-failover
      base:
        apiVersion: route53.crossplane.io/v1alpha1
        kind: RecordSet
        spec:
          recordType: A
          failoverPolicy: PRIMARY
          healthCheckIdRef: east-health
```

When an operator creates a `CheckoutService` claim, Crossplane reconciles every resource in the composition. The composite resource is the unit of failover, not the individual cluster, which is exactly the abstraction you want when you're paged at 3 a.m.

## Why Active-Passive (and Not Active-Active)

Active-active across regions is seductive. It also doubles your bill, complicates write paths for stateful workloads, and turns every conflict resolution into a custom problem. For most product teams — payments, internal APIs, batch jobs — active-passive is the right starting point. You get nearly all of the availability benefit without paying for two of every database.

The catch is that passive clusters rot. Workloads deployed to active stop being deployed to passive. Schema migrations don't always run in both places. By the time you actually need the passive cluster, it has diverged enough that the failover is slower and uglier than it should have been. The Linkerd + Crossplane combo addresses this by making the passive cluster a managed artifact of the same composite resource that owns the active one.

## Patterns in Production: The Three Layers

A working multi-cluster failover setup has three layers that all need to agree. Skip any one of them and the failover will be lossy, slow, or both.

### Layer 1 — Infrastructure (Crossplane)

Crossplane providers for AWS ([`provider-aws`](https://github.com/crossplane-contrib/provider-aws)) give you managed resources for nearly every primitive you'll touch: `Cluster`, `NodeGroup`, `VPC`, `Subnet`, `RouteTable`, `InternetGateway`, `SecurityGroup`, `RDSInstance`, `Route53RecordSet`, `HealthCheck`. You wrap groups of these into a `Composition`, expose a small `CompositeResourceClaim` schema to your application teams, and the rest is GitOps.

Two non-obvious wins for failover:

1. **Drift detection is free.** Crossplane periodically re-reads the AWS API and reconciles if reality diverges from the spec. Manual console edits on a Friday get reverted on Saturday.
2. **The composite resource is the blast radius.** If you need to tear down the passive cluster to save cost during a quiet period, you delete one `Claim` and Crossplane cleans up everything that was created on its behalf, including IAM roles and Route 53 records.

### Layer 2 — Service Mesh (Linkerd Multi-Cluster)

Linkerd's [multi-cluster installation](https://linkerd.io/2.14/features/multicluster/) introduces three things you need to understand:

- **The gateway** — a proxy that exposes the mesh's control plane on a public (or VPC-peered) address. Each cluster runs one.
- **ServiceMirror** — a controller in the passive cluster that watches `Service` and `EndpointSlice` objects in the active cluster and creates local mirror services pointing at the gateway.
- **Mirror services** — these are normal Kubernetes `Service` objects with a special `mirror.linkerd.io/multicluster-gateway` annotation. Traffic sent to a mirror service in cluster B is load-balanced by Linkerd to live pods in cluster A, with mTLS end-to-end and automatic retries.

When you install the Linkerd Helm chart with the `multicluster` values, you get a `linkerd-multicluster` namespace containing the gateway deployment and the controllers. Linking two clusters is one `linkerd multicluster link` command per direction, and the result is a `ServiceProfile` and mirror `Service` per workload.

```bash
# Link cluster A (us-east-1) to cluster B (us-west-2)
linkerd multicluster link --kubeconfig=kubeconfig-east \
  --cluster-name=us-east-1 --api-server-address=api-east.example.com \
  --gateway-address=linkerd-gateway.east.example.com:4143 \
  | kubectl apply -f - --kubeconfig=kubeconfig-west
```

The mirror services are how your applications stay cluster-agnostic. A pod in cluster B calling `checkout.default.svc.cluster.local` doesn't know or care whether the destination is local or mirrored — Linkerd picks the right gateway and handles authentication.

### Layer 3 — Traffic Steering (Route 53 + Failover Policy)

For an active-passive setup, AWS Route 53's failover routing policy is the right primitive. You create two records with the same name, mark one `PRIMARY` and one `SECONDARY`, attach a health check to the primary, and Route 53 does the rest. DNS TTL becomes your recovery latency, so keep it short (30–60 seconds for failover use cases).

The health check should probe an application endpoint, not just a TCP port. A `/healthz` that returns 200 only when the database is reachable and the cache is warm is worth the extra five lines of code. Route 53's failover is well-documented in the [AWS Route 53 Developer Guide](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover.html), and the Crossplane provider models the resource cleanly.

## Failure Modes and How This Design Handles Them

Real-world failover gets weird because the failure isn't usually "the cluster is down." It's one of:

### Partial Degradation

A node group loses capacity, AZs become imbalanced, or a managed service throttles. Linkerd's load balancing metrics surface the problem before users do, and mirror services route around hot pods automatically. Crossplane's reconciliation will (politely) scale up the affected `NodeGroup` if you've set the field as observable.

### Control Plane Outage in One Region

If the Linkerd control plane in the active region is unreachable from workloads, mesh identity stops working but proxy data planes keep existing connections open for a while. This is where you'd trigger manual failover via Route 53 — a short DNS TTL means clients reconnect into the passive cluster, which has its own healthy control plane.

### Failed Deployment

A bad release breaks the checkout service in the active region. With Linkerd traffic split, you can route 100% of traffic back to the last-known-good revision without touching DNS or the mesh. Crossplane rolls forward by reconciling to the desired Helm release, which is exactly what you'd want anyway.

### Split Brain

Two clusters both believe they're primary. DNS TTL and Route 53 failover make this unlikely if you've actually attached health checks, but defense in depth is cheap: write paths to RDS should reject writes when the cluster isn't authoritative. A common pattern is an `STS assume role` that only the primary cluster can obtain, gated by the Route 53 health check.

## Operational Reality: What This Looks Like Day-to-Day

A team running this pattern day-to-day has three jobs:

1. **Update the composite resource definition** when a new component is added to the service (a new database, a new region, a new dependency). Crossplane's schema validation catches most mistakes at PR time.
2. **Run chaos drills.** Failover you haven't rehearsed isn't failover; it's a hypothesis. Tools like [`linkerd-await`](https://linkerd.io/2.14/reference/cli/inject/) and AWS Fault Injection Simulator let you validate the path end-to-end. A quarterly game day where you fail the primary region and measure recovery time is worth more than any architecture diagram.
3. **Watch the right metrics.** Focus on the Linkerd control plane dashboards (request rate, success rate, latency p99), Crossplane's reconciliation health, and Route 53 health check status. Everything else is secondary.

One thing that surprises people: the passive cluster can be much smaller than the active one. You don't need full capacity sitting idle for the rare bad day. If your failover RTO is "30 minutes," you can let the passive cluster scale up from zero and recover within budget — Linkerd will pick up mirror traffic as pods become ready.

## Key Takeaways

- **Linkerd handles the data plane, Crossplane handles the control plane.** Trying to do both with one tool usually means doing neither well.
- **Active-passive is the right default** for most workloads. Active-active is a specific cost-and-complexity decision, not a free upgrade.
- **The composite resource is the unit of failover.** Modeling the entire multi-region service as one Crossplane claim means a single delete cleans everything up, and a single edit propagates to both clusters.
- **DNS TTL is your recovery latency budget.** Keep it short, attach a real health check, and don't rely on the TCP-only default.
- **Test it.** A failover plan that hasn't been executed in production is at best a guess. Schedule chaos drills and track actual RTO against the target.
- **Mirror services keep applications cluster-agnostic.** Workloads call `service.namespace.svc.cluster.local` and Linkerd figures out whether the destination is local or in another cluster.

## Further Reading

- [Linkerd Multi-Cluster Installation Guide](https://linkerd.io/2.14/features/multicluster/)
- [Crossplane Compositions Documentation](https://docs.crossplane.io/latest/concepts/compositions/)
- [provider-aws on GitHub](https://github.com/crossplane-contrib/provider-aws)
- [AWS Route 53 Failover Routing](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/dns-failover.html)
- [EKS Best Practices Guide on Reliability](https://aws.github.io/aws-eks-best-practices/karpenter/)
- [Linkerd Service Profiles and Traffic Split](https://linkerd.io/2.14/features/traffic-split/)