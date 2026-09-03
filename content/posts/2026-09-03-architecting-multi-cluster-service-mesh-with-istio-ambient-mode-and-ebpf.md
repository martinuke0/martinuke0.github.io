---
title: "Architecting Multi-Cluster Service Mesh with Istio Ambient Mode and eBPF"
date: "2026-09-03T15:00:48.796"
draft: false
tags: ["istio", "service-mesh", "ebpf", "multi-cluster", "kubernetes", "cilium"]
description: "How to design a multi-cluster service mesh using Istio Ambient Mode and eBPF, covering ztunnel, waypoint proxies, and zero-trust networking."
summary: "A practical architecture guide to running Istio Ambient Mode across multiple Kubernetes clusters, with eBPF-powered data planes handling L4 and waypoint proxies owning L7."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-architecting-multi-cluster-service-mesh-with-istio-ambient-mode-and-ebpf.svg"
  alt: "Network diagram showing multiple Kubernetes clusters connected through an Istio ambient mesh with ztunnel and waypoint components."
  caption: ""
  relative: false
---

> **TL;DR** — Istio Ambient Mode splits the sidecar into two layers: an eBPF-accelerated `ztunnel` (L4) and an optional waypoint proxy (L7). Across multiple clusters, this gives you a lighter, more uniform data plane that scales better than sidecars, while still letting you pin L7 policy to namespaces or services. The trade-off is operational complexity in identity, certificate, and control-plane federation.

## Why Ambient Mode Changes the Mesh Conversation

The classic Istio story — one Envoy sidecar per pod — is a love letter to consistency and a tax on infrastructure. Every pod pays for an extra container, an extra init, and an extra iptables redirection chain, even when the workload is a tiny gRPC service that only needs mTLS. At a few hundred pods, that tax is fine. At 10,000, it shows up in your node budgets and your cold-start latency.

[Ambient Mode](https://istio.io/latest/docs/ambient/overview/) is Istio's answer: split the sidecar into two roles. The **ztunnel** is a per-node, Rust-based L4 proxy that handles mTLS, L4 authorization, and telemetry. The **waypoint** is an optional, deployment-scoped Envoy that handles L7 policy — retries, header routing, ext-auth. Workloads join the mesh by selecting a namespace or a `Service` label; they don't need an injection webhook at all.

Pair that with **eBPF** in the kernel — programs attached to hooks like `cgroup/sock_ops`, `tc`, and `connect()` — and you get a data plane that does the L4 part almost entirely in kernel space, with a thin userland component to own identity and certificates. That's the architectural promise. The hard part is making it work across clusters.

## The Multi-Cluster Problem, Restated

If you have only one cluster, ambient mode is comparatively easy: install `istiod`, install `ztunnel` as a DaemonSet, optionally deploy a waypoint per namespace, done. The moment you have more than one cluster, you inherit three problems:

1. **Identity federation.** Workloads in cluster A and cluster B need to trust each other's SPIFFE identities. That means either a shared root CA or cross-signed intermediates, plus trust bundles pushed to every `ztunnel`.
2. **Service discovery across boundaries.** A pod in cluster-east asking for `payments.checkout` needs a way to resolve that name to a workload in cluster-west, with the right identity attached.
3. **Network reachability.** Pod CIDRs don't route between clusters by default. You need a flat overlay (Cilium ClusterMesh, Submariner, KubeFed-style networking) or a gateway model where each cluster exposes a VIP.

You can solve each independently, but the mesh only feels coherent when all three are solved with the same set of assumptions.

## The Reference Architecture

The architecture I want to walk through is three Kubernetes clusters (`east`, `west`, `central`) running on different cloud regions, each running Istio in ambient mode, federated through a shared control plane and a Cilium ClusterMesh overlay. The piece that ties it together is the **shared root CA**, which is the single most important decision in this design.

```
┌────────────────────────┐   ┌────────────────────────┐
│ Cluster: east          │   │ Cluster: west          │
│  ┌──────────────────┐  │   │  ┌──────────────────┐  │
│  │  istiod (replica)│  │   │  │  istiod (replica)│  │
│  └──────────────────┘  │   │  └──────────────────┘  │
│  ┌──────────────────┐  │   │  ┌──────────────────┐  │
│  │  ztunnel (DS)    │◄─┼───┼─►│  ztunnel (DS)    │  │
│  │  + eBPF (Cilium) │  │   │  │  + eBPF (Cilium) │  │
│  └──────────────────┘  │   │  └──────────────────┘  │
│  ┌──────────────────┐  │   │  ┌──────────────────┐  │
│  │  waypoint (opt)  │  │   │  │  waypoint (opt)  │  │
│  └──────────────────┘  │   │  └──────────────────┘  │
│  Spire/External CA ◄──┼───┼──► Spire/External CA    │
└─────────┬──────────────┘   └──────────┬─────────────┘
          │                             │
          └────────────┬────────────────┘
                       ▼
              ┌──────────────────┐
              │  Cluster: central│
              │  istiod (primary)│
              │  cert authority  │
              └──────────────────┘
```

Two non-obvious decisions are already baked into this picture. First, `istiod` runs as a **primary in `central`** with **read-only replicas in `east` and `west`** — this is the pattern documented in the [Istio multi-primary docs](https://istio.io/latest/docs/setup/install/multicluster/multi-primary/). Second, **Cilium is the CNI in every cluster** because its eBPF datapath and `ztunnel` cooperate well — `ztunnel` is built to delegate L4 to the kernel where it can, and Cilium's socket-level hooks are exactly the integration point it expects. You can run ambient with other CNIs, but you'll be giving up the eBPF shortcut.

### Layer 1: Identity Federation

The shared root CA is the load-bearing decision. There are two viable patterns:

- **Self-signed intermediate per cluster, signed by an external root.** This is what most production setups look like. You run a Vault or SPIRE server out-of-cluster, generate a root, and have each cluster's `istiod` mint a signing intermediate against that root. The trust bundle (the root cert) is pushed to every `ztunnel` so that any workload can verify any other workload's leaf cert.
- **SPIRE federation.** Each cluster runs SPIRE and exchanges trust bundles. Heavier to operate, but gives you workload attestation that goes beyond Kubernetes ServiceAccounts (e.g., AWS instance identity, GCP service account tokens).

For most teams, option one is the right starting point. The configuration is straightforward: point `istiod` at the same root via `--ca-cert`, and `ztunnel` picks up the trust bundle from the `istio` ConfigMap. The cert chain looks like:

```
Root CA (off-cluster, long-lived)
 └── Intermediate CA per cluster (rotated yearly)
      ├── Workload identity certs (rotated every 24h by istiod)
```

What you must not do is let each cluster run its own self-signed root. Once that happens, cross-cluster mTLS fails with a `x509: certificate signed by unknown authority` error that looks like a network problem and burns half a day of debugging.

### Layer 2: eBPF in the Data Plane

`ztunnel` is the userland piece, but the interesting work happens in the kernel. Three eBPF program types do most of the heavy lifting, and each solves a different problem:

- **Cgroup / sock_ops hooks** let the kernel observe socket operations — `connect()`, `accept()`, `sendmsg()`. When a workload in pod A connects to pod B, the eBPF program can intercept the connection, look up the destination identity, and choose whether to redirect through `ztunnel` for mTLS or pass it through if the destination is on a mesh-exclusion list. This is where the L4 acceleration lives.
- **TC (traffic control) ingress/egress** programs attach to the network interface and can rewrite or redirect packets before they hit the regular TCP stack. `ztunnel` uses these for outbound traffic that didn't go through a socket hook — for example, UDP, ICMP, or connections initiated before the workload's identity was available.
- **Tracepoint programs** on `net/sock_stat` and friends provide per-flow metrics that flow into `ztunnel`'s telemetry and from there into Prometheus. This is why ambient mode can give you per-workflow metrics without sidecars.

The net effect is that for two workloads inside the same cluster, the steady-state path is **kernel → kernel**, with `ztunnel` only consulted for policy decisions at connect time. For a sidecar mesh, by contrast, every byte of every request traverses a userspace proxy.

### Layer 3: Waypoint Proxies for L7

L7 is where ambient mode makes you make decisions. A waypoint proxy is a regular Envoy deployment that owns L7 policy for a scope — usually a namespace or a service. Workloads discover the waypoint through DNS (a synthetic `*.waypoint.mesh.internal` entry) and route L7 traffic through it; L4 traffic bypasses the waypoint entirely.

The pattern that works in practice:

- **Default namespace: L4 only.** Most namespaces don't need retries, header-based routing, or ext-auth. They get mTLS, L4 authorization, and rich telemetry, and they don't pay for an Envoy.
- **Specific namespace: L7.** Namespaces that need an `AuthorizationPolicy` with `when:` clauses on headers, or that need gRPC retries with custom backoff, get a waypoint. You label the namespace: `istio.io/for-service-mesh: "true"` and `istio.io/for-service: "checkout"`, and `istiod` materializes the waypoint.
- **Per-service opt-in for hot paths.** For a service that sees 50k RPS and needs header-based canary routing, you can pin a waypoint to that single `Service`. The rest of the namespace stays L4.

This is the architectural lever: L7 is opt-in and scoped, not universal. That alone reclaims a meaningful fraction of your sidecar bill.

## Patterns in Production

Three patterns show up in nearly every multi-cluster ambient deployment that survives its first quarter.

### Pattern 1: Split-Horizon Service Discovery

`east` and `west` are in different regions. The `payments` service runs in `east` because that's where the database is. A request from `west` should land in `east` without the application knowing anything about clusters.

You achieve this with a **multi-network service entry**: an `Istio` resource in each cluster that mirrors the remote service's endpoints. When a workload in `west` asks for `payments.checkout.svc.cluster.local`, the local DNS returns the local Service IP (which is a virtual IP in the mesh) and the local `ztunnel` redirects based on the destination's identity. Because both clusters share a trust bundle and the same root CA, the cert handshake succeeds, and the connection lands in `east` over the Cilium ClusterMesh tunnel.

```yaml
apiVersion: networking.istio.io/v1
kind: ServiceEntry
metadata:
  name: payments-east
  namespace: checkout
spec:
  hosts:
  - payments.checkout.svc.cluster.local
  location: MESH_INTERNAL
  ports:
  - number: 8080
    name: http
    protocol: HTTP
  resolution: STATIC
  endpoints:
  - address: 10.200.4.17  # Cilium ClusterMesh-routable IP in east
    labels:
      cluster: east
    network: east
```

The `network` label is what tells `istiod` to treat this endpoint as remote and to skip local load balancing. The `ztunnel` in `west` is the one that opens the mTLS tunnel to `east`'s `ztunnel`; the workload has no idea any of this is happening.

### Pattern 2: Namespace-Scoped Waypoints with Cluster Affinity

Waypoint proxies are stateless and can run in any cluster, but they should run in the cluster where the service lives, not in a remote one. The reason is the same as why you don't put a database in a different region from your application: latency, bandwidth cost, and the failure modes that follow from both.

So the pattern is: a waypoint lives next to its workload. Cross-cluster traffic still flows over the mesh, but it terminates at the L4 boundary in the remote cluster's `ztunnel`, then a short hop to the local waypoint, then to the workload.

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: checkout-waypoint
  namespace: checkout
  labels:
    istio.io/for-service-mesh: "true"
spec:
  gatewayClassName: istio-waypoint
  listeners:
  - name: mesh
    port: 15008
    protocol: HBONE
```

This is a [Kubernetes Gateway API](https://gateway-api.sigs.k8s.io/) resource — `istiod` watches these and materializes the waypoint deployment. The `HBONE` protocol is the HTTP-based tunneling that ambient mode uses between `ztunnel` and waypoint.

### Pattern 3: Failure Domains via Control-Plane Geography

When the central cluster's `istiod` goes down, you want clusters to keep serving traffic to workloads they already know about. The mechanism is the read-only `istiod` replica in each cluster, which keeps a recent copy of the config and the trust bundle. It can serve push-based config to `ztunnel` and answer the occasional `DiscoveryRequest`, but it can't mint new workload certificates.

The way you size this is: each cluster's `istiod` replica needs to be able to survive a 30-minute outage of the central primary. In practice that means running it as a 2-replica deployment with a local SQLite or PostgreSQL backend, and a pre-warmed trust bundle. When the central primary comes back, cert minting resumes and any workloads that need rotation get fresh certs.

## Failure Modes You Will Hit

A few real failure modes are worth naming because they will appear in your first month of operation.

**Clock skew breaks mTLS.** Workload certs are short-lived (24 hours by default) and have a `NotBefore` / `NotAfter` window. If a node's clock drifts by more than a few minutes, `ztunnel` will reject a cert it just minted. The fix is `chrony` or `ntpd` with a sane configuration, and a Prometheus alert on clock drift per node. Don't let the mesh be the only thing telling you your clocks are wrong.

**Trust bundle propagation lag.** When you rotate the root CA, every `ztunnel` needs the new bundle before any workload presents a cert signed by it. If you push the bundle to `east` and `west` at the same time but the central primary has already started minting under the new root, there's a window where some clusters can't verify. The fix is to push the new root, wait for a `ztunnel`-wide rollout, and *then* start minting against it. The Istio docs on [CA rotation](https://istio.io/latest/docs/ops/common-problems/CA/) walk through this; the trap is that the procedure looks like a config push but is actually a coordinated sequence.

**eBPF program limit on old kernels.** If you're stuck on a 4.19 kernel, you'll hit the older, smaller eBPF program size limits and `ztunnel` will fall back to a slower path. Cilium's [kernel requirements](https://docs.cilium.io/en/latest/operations/system_requirements/) page is the right reference — anything older than 5.4 is asking for trouble.

**Waypoint scaling on cold namespaces.** A waypoint that just got deployed is cold. Its first request takes the regular Envoy warm-up time. If your traffic is bursty and you have many namespaces with waypoints, you'll see occasional 200–400ms tails. The fix is a small readiness probe that warms the listener, or a horizontal autoscale with a min replica count of 1 per cluster.

**Cross-cluster DNS in the presence of ClusterMesh.** Cilium's ClusterMesh provides L3 connectivity, not DNS. You still need a way to resolve `payments.checkout.svc.cluster.local` from a workload in a different cluster. The standard answer is a [multi-cluster DNS solution](https://docs.cilium.io/en/latest/network/clustermesh/clustermesh/#global-namespaces) — either a global namespace that the Cilium operator mirrors, or a `NodeLocal` DNSCache with a forwarding path to a central CoreDNS.

## The Cost Story

A sidecar mesh on a 4-vCPU pod adds roughly 100–200ms of p99 latency and 30–50MB of resident memory per pod. For 2,000 pods, that's a meaningful bill. Ambient mode with Cilium CNI gets you the same mTLS and L4 telemetry for a flat overhead that scales with node count, not pod count — typically one `ztunnel` per node (~80MB) plus a few eBPF programs in the kernel. The waypoint layer is opt-in, so you only pay for Envoy where you've actually chosen L7.

If you want concrete numbers: in a 2,000-pod benchmark, ambient mode typically reports a 60–80% reduction in mesh-related CPU and memory versus sidecar mode, with p99 latency within 1–2% of an unmasked baseline. The waypoint layer, when activated, adds back about half of what the sidecar would have cost — but only for the namespaces that need it.

## Key Takeaways

- **Ambient mode is a separation of concerns.** `ztunnel` does L4 (and is eBPF-accelerated), the waypoint does L7. Most namespaces never need a waypoint, and that's the whole point.
- **The shared root CA is the most important decision.** Once you federate identity, the rest of the multi-cluster story becomes tractable. Use a single root with per-cluster intermediates and propagate the trust bundle aggressively.
- **eBPF is the latency and CPU win.** Kernel-space packet handling means the steady-state path between two meshed pods avoids userland proxies entirely. The integration with Cilium is the most mature.
- **Waypoints are scoped, not global.** A namespace-scoped or service-scoped waypoint gives you L7 only where you need it. Don't deploy waypoints cluster-wide.
- **Multi-cluster ambient works, but expects you to solve three problems together:** identity, discovery, and reachability. Solve identity first; the other two are easier once workloads can authenticate each other.

## Further Reading

- [Istio Ambient Mode Architecture Overview](https://istio.io/latest/docs/ambient/overview/)
- [Cilium ClusterMesh Documentation](https://docs.cilium.io/en/latest/network/clustermesh/clustermesh/)
- [Kubernetes Gateway API Specification](https://gateway-api.sigs.k8s.io/)
- [eBPF.io — Introduction and Program Types](https://ebpf.io/what-is-ebpf/)
- [Istio Multi-Primary on Multiple Clusters](https://istio.io/latest/docs/setup/install/multicluster/multi-primary/)