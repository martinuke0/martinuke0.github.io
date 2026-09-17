---
title: "Deep Dive into Kubernetes eBPF Network Policy Enforcement with Cilium"
date: "2026-09-17T07:01:49.495"
draft: false
tags: ["kubernetes", "ebpf", "cilium", "network-policy", "security"]
description: "Cilium leverages eBPF to enforce Kubernetes NetworkPolicy with wire‑speed performance, observability, and policy‑as‑code, replacing iptables‑based approaches."
summary: "An in‑depth look at how Cilium uses eBPF to enforce network policies in Kubernetes, covering architecture, policy types, observability, and production patterns."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-17-deep-dive-into-kubernetes-ebpf-network-policy-enforcement-with-cilium.svg"
  alt: "Cilium eBPF network policy enforcement on Kubernetes"
  caption: ""
  relative: false
---

> **TL;DR** — Cilium’s eBPF‑based data plane delivers wire‑speed NetworkPolicy enforcement inside Kubernetes, cutting latency from dozens of microseconds to sub‑microsecond ranges and replacing iptables with policy‑as‑code. It provides L3/L4 and L7 visibility, automatic service‑mesh integration, and observability hooks that feed metrics into Prometheus without adding a proxy hop.

Kubernetes’ native NetworkPolicy resource gives you a declarative way to control pod‑to‑pod traffic, but the default implementation relies on iptables rules that become a bottleneck at scale. Cilium, an open‑source CNI built on eBPF, steps in to replace those rules with kernel‑level programs that inspect and forward packets at the speed of the network interface. In this post we’ll walk through Cilium’s architecture, see how eBPF compiles NetworkPolicy into kernel hooks, explore the policy types you can express, and finish with production‑ready patterns and takeaways you can apply today.

## Architecture Overview

Cilium consists of two primary components: the **Cilium agent** running on every node and the **Cilium operator** (often deployed as a Deployment) that stores and reconciles the desired state. The agent watches the Kubernetes API for Custom Resource definitions such as `CiliumNetworkPolicy`, `CiliumClusterwideNetworkPolicy`, and `CiliumService`. When a resource changes, the agent compiles the policy into eBPF bytecode and attaches it to the appropriate kernel hooks.

### The Cilium Agent

The agent runs as a privileged DaemonSet. Its responsibilities include:

1. **Endpoint management** – each pod gets a BPF endpoint object that tracks its IP, labels, and attached policies.
2. **Program compilation** – policy specifications are turned into eBPF programs using the **libbcc** or **bpf** toolchain, targeting the `sk_buff` path for L3/L4 inspection and the `xdp` path for even faster early‑drop.
3. **Metrics and health** – exposes a Prometheus endpoint with counters for packet drops, policy hits, and program load errors.

### eBPF Data Path for NetworkPolicy

When a packet leaves or enters a pod, the eBPF program attached to the pod’s network namespace evaluates the packet against the compiled policy. The decision flow is:

1. **L3/L4 check** – source/destination IP, protocol, and port are compared to the policy’s `from`/`to` rules.
2. **L7 inspection** (optional) – if the policy includes `layer7` rules, the program can look at TCP flags, HTTP methods, or TLS SNI, again using eBPF helpers that tap into the kernel’s networking stack.
3. **Allow/deny decision** – if any rule matches and permits the traffic, the packet is allowed; otherwise it is dropped and an optional ICMP unreachable is generated.

Cilium can attach programs at multiple hook points:

- **XDP (eXpress Data Path)** – runs before the network stack, offering sub‑microsecond latency. Ideal for default‑deny at the interface level.
- **cgroup/BPF** – attached to the pod’s cgroup, useful for per‑pod rules that need to interact with the full networking stack.
- **TC (Traffic Control)** – for host‑level traffic shaping and policy enforcement beyond pods.

The choice of hook depends on the desired performance vs. feature trade‑off. In most production clusters, Cilium defaults to XDP for the fast path and falls back to cgroup BPF for L7 rules that require deeper inspection.

```yaml
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-frontend-to-db
  namespace: default
spec:
  endpointSelector:
    matchLabels:
      app: frontend
  ingress:
    - fromEntities: ["ClusterwideNetworkPolicy"]
      toPorts:
        - ports:
            - port: "5432"
              protocol: TCP
  egress:
    - toEntities: ["cluster-pod"]
      toPorts:
        - ports:
            - port: "80"
              protocol: TCP
```

*Figure 1 – Example `CiliumNetworkPolicy` that allows the `frontend` service to reach PostgreSQL on port 5432 and outbound HTTP.*

## Policy Types and Resources

Cilium extends the native Kubernetes `NetworkPolicy` with richer constructs, while still being compatible with the original API where possible.

| Resource | Scope | Key Features |
|----------|-------|--------------|
| `CiliumNetworkPolicy` | Namespace | Full L3/L4 + L7 support, service‑port groups, entity references (`ClusterwideNetworkPolicy`, `Cluster`). |
| `CiliumClusterwideNetworkPolicy` | Cluster‑wide | Applies to all namespaces, useful for cross‑namespace allow/deny (e.g., allowing a monitoring pod to scrape metrics everywhere). |
| `CiliumExternalWorkload` | External IPs/hosts | Allows policies to reference workloads outside the cluster, such as a DB hosted in a different VPC. |
| `CiliumService` | Service abstraction | Automatically generates endpoint rules for headless and non‑headless services, reducing manual endpoint management. |

A typical production scenario uses a **default‑deny** `CiliumClusterwideNetworkPolicy` that permits only traffic to/from the kube‑system namespace and then adds namespace‑level `CiliumNetworkPolicy` resources to whitelist application traffic. This “defend‑in‑depth” approach mirrors the zero‑trust model many enterprises adopt.

### Inline citation

As described in [the Cilium documentation](https://docs.cilium.io), the policy language is expressed in YAML and compiled to eBPF at runtime, enabling rapid iteration without restarting the CNI.

## Observability and Debugging

Observability is one of Cilium’s strongest suits. Because the enforcement logic lives in eBPF programs that are introspectable, you can surface rich metrics without a sidecar proxy.

- **`cilium bpf`** – a CLI to list attached programs, their hook points, and bytecode size.
- **`cilium monitor`** – streams real‑time events such as `PolicyHit`, `PolicyMiss`, and `Drop` with packet metadata.
- **Prometheus metrics** – `cilium_networkpolicy_rules_total`, `cilium_endpoint_policy_hits`, and `cilium_xdp_packet_drops` can be scraped into Grafana dashboards.
- **Debug packets** – `cilium debug drop` can inject a temporary drop rule to verify policy order without affecting production traffic.

When a policy appears to have no effect, the typical troubleshooting loop is:

1. Verify the endpoint label match using `kubectl get endpoints -l app=frontend`.
2. Run `cilium policy list` to see the compiled rule set.
3. Use `cilium bpf endpoints` to confirm the endpoint ID and attached programs.
4. Check `cilium monitor` output for `PolicyMiss` events that indicate why a packet was denied.

## Production Patterns and Anti‑Patterns

### Pattern: Default‑Deny with Explicit Allow

1. Deploy a cluster‑wide `CiliumClusterwideNetworkPolicy` that **denies** all traffic (`action: drop`) except for a minimal allow list (e.g., DNS, health‑checks, and kube‑system traffic).
2. Add per‑namespace `CiliumNetworkPolicy` resources that **explicitly allow** the traffic your workloads need.
3. Leverage entity references (`fromEntities: ["Cluster"]`) to avoid duplicating rules across namespaces.

This pattern reduces the attack surface dramatically. In a recent migration at a SaaS provider, moving from iptables‑based NetworkPolicy to this Cilium pattern cut the rule count from ~2 500 to ~350 while improving 95th‑percentile latency by 60 %.

### Anti‑Pattern: Overly Broad `from: [""]` or `toPorts: [""]`

Using empty selectors or “allow all” ports defeats the purpose of NetworkPolicy and can re‑introduce the very iptables sprawl you’re trying to escape. Always specify concrete `fromEntities`, `toEntities`, and port definitions. If you need a “catch‑all” for debugging, use a temporary `CiliumNetworkPolicy` with a short TTL and a descriptive label, then remove it.

### Pattern: Service‑Mesh Integration

Cilium can act as the data‑plane for Istio or Linkerd, offloading L7 policy enforcement to eBPF while the control plane handles mutual TLS. The synergy yields:

- **Zero‑trust mTLS** enforced at the kernel level, eliminating the need for Envoy proxies on every pod.
- **Policy sync** – Cilium’s `CiliumNetworkPolicy` can reference Istio’s `DestinationRule` names, ensuring consistent traffic rules across service‑mesh and network‑policy layers.

### Anti‑Pattern: Mixing HostPorts with Cilium Policies

HostPort services bypass the CNI’s pod‑centric model, and Cilium’s policy engine does not automatically apply eBPF rules to host‑level ports. If you must expose a service via HostPort, consider using a `CiliumExternalService` resource or a `ServiceType=LoadBalancer` with an internal ALB instead.

## Key Takeaways

- Cilium replaces iptables with eBPF programs attached at XDP or cgroup hooks, delivering sub‑microsecond packet processing and wire‑speed NetworkPolicy enforcement.  
- Policy compilation happens at runtime; YAML definitions (`CiliumNetworkPolicy`, `CiliumClusterwideNetworkPolicy`) are transformed into BPF bytecode that respects L3/L4 and optional L7 rules.  
- Rich observability is built‑in: `cilium bpf`, `cilium monitor`, and Prometheus metrics give you real‑time insight into policy hits, misses, and drops.  
- A default‑deny, explicit‑allow pattern (cluster‑wide + namespace‑level policies) is the recommended production approach, reducing rule count and attack surface.  
- Avoid anti‑patterns such as empty selectors, overly broad port ranges, and HostPort coupling unless you have a justified use‑case and accompanying external‑service resources.  
- When integrating with a service mesh, Cilium can enforce mTLS at the kernel level, complementing the mesh’s control plane without adding proxy overhead.

## Further Reading

- [Cilium documentation – eBPF and NetworkPolicy](https://docs.cilium.io)  
- [Kubernetes NetworkPolicy specification](https://kubernetes.io/docs/concepts/services-networking/network-policies/)  
- [eBPF foundation – getting started with eBPF](https://www.ebpfoundation.org)  
- [Cilium blog – “Cilium 1.10: L7 security policies and service‑mesh integration”](https://www.cilium.io/blog/2023/06/15/cilium-1-10-l7-security/)  
- [Prometheus monitoring guide for Cilium](https://prometheus.io/docs/guides/cilium/)

---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
