---
title: "Inside eBPF and Cilium: How Kernel-Level Filtering Rewrites Container Networking"
date: "2026-09-04T15:00:28.739"
draft: false
tags: ["ebpf", "cilium", "kubernetes", "networking", "linux-kernel", "cloud-native"]
description: "A working engineer's guide to how eBPF and Cilium replace iptables with in-kernel programs for faster, observable container networking."
summary: "How eBPF and Cilium move packet filtering from user-space daemons into the Linux kernel itself — and why that rewrites the rules for Kubernetes networking performance, observability, and security."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-inside-ebpf-and-cilium-how-kernel-level-filtering-rewrites-container-networking.svg"
  alt: "Abstract network mesh with kernel-level filter hooks highlighted."
  caption: ""
  relative: false
---

> **TL;DR** — eBPF lets you run sandboxed programs inside the Linux kernel without patching it, and Cilium uses that to replace iptables with a compiled, in-kernel datapath. The result is lower latency, fewer CPU cycles per packet, richer observability, and a security model that ties policy to identity rather than IP. This post walks through the kernel hooks, the datapath, and the trade-offs that matter when you run it in production.

If you've ever watched a Kubernetes node chug through `iptables -L -t nat` on a cluster with tens of thousands of services, you've already met the problem Cilium was built to solve. The classic kube-proxy model pushes every Service, every Endpoint, and every translation rule into a chain of netfilter tables that the kernel walks linearly on every packet. It works — until it doesn't.

Cilium's bet is simple and a little radical: stop bouncing packets through user space and stop walking gigantic netfilter chains. Do the filtering *inside the kernel*, with a JIT-compiled program attached to the kernel's own socket, XDP, and TC hooks. That's the eBPF promise, and Cilium is now the production-grade proof that it works at scale.

This post walks through what's actually happening under the hood — the kernel machinery, the Cilium datapath, the security model, and the failure modes you'll meet in real clusters.

## A 60-Second Refresher on eBPF

eBPF (extended Berkeley Packet Filter) is a way to run sandboxed bytecode inside the Linux kernel without writing a kernel module. You write C (or Rust, via [libbpf](https://github.com/libbpf/libbpf)), compile it with clang, and the verifier in the kernel proves the program is safe to run — bounded loops, no uninitialized memory reads, no out-of-bounds access — before any packet ever hits it.

Once loaded, the program is attached to a *hook point*: a network event, a syscall entry, a kprobe, a tracepoint, a socket operation, or a userspace function via uprobe. When the hook fires, the kernel JITs the bytecode to native instructions and runs it in kernel context.

A few properties matter most for networking:

- **No context switch.** Packets never leave the kernel. Compared to a user-space proxy that does `recvmsg` → parse → `sendmsg`, that's often a 10x latency improvement on the same hardware, as routinely measured by the [Cilium community benchmarks](https://docs.cilium.io/en/latest/overview/performance/).
- **The verifier is the real feature.** It's not a sandbox in the browser sense; it's a formal proof that the program terminates and cannot read memory it shouldn't. That makes eBPF practical to load on production hosts.
- **Maps are the data plane.** eBPF programs don't keep state in process memory; they read and write kernel-resident maps (hash tables, arrays, LRU caches, ring buffers) that other eBPF programs or user space can also touch. This is how endpoints, identities, and policy get shared at kernel speed.

A good mental model: eBPF is to the kernel what JavaScript event handlers are to a browser — small programs attached to well-defined points, with shared data structures, executed by the host itself.

## Why iptables Became a Problem

To understand why Cilium exists, you have to understand what it replaces.

In a default Kubernetes cluster, `kube-proxy` watches the API server and translates Service/Endpoint objects into iptables rules in the `nat` and `filter` tables. Every connection to a ClusterIP traverses the `PREROUTING` and `OUTPUT` chains; the kernel walks them top-to-bottom until it finds a matching rule, then performs DNAT to the chosen backend pod IP.

This scales poorly in three ways:

1. **Rule count.** A 10,000-Service cluster can produce hundreds of thousands of iptables rules. Each rule is a comparison and a jump.
2. **Linear scan.** Netfilter evaluates rules sequentially. Per-packet, per-rule overhead is small, but at 10 Gbps with 64-byte packets, "small" multiplies.
3. **Update churn.** Every Endpoint change — pod rescheduled, HPA scales, node drain — rewrites a long prefix of the chain. Updates take seconds; during them, rule misses or duplication are real.

ipvs mode helps with lookup (it uses a hash table) but it still runs in user space and still has to push state into the kernel via `netlink` for connection tracking. The fundamental cost — leaving the kernel for control-plane decisions — remains.

Cilium's premise is that if the *data plane* could live in the kernel itself, with policy and identity compiled into maps that eBPF programs read on the fast path, you could cut the overhead dramatically.

## The Cilium Datapath, End to End

When you install Cilium via Helm and replace kube-proxy, here's what actually happens on a node.

### Identity, Not IP

The first thing to internalize is that Cilium does not use pod CIDRs as the basis for policy. Each pod gets a **security identity** — a 32-bit label-derived identifier — assigned at admission time and stored in an eBPF map keyed by pod IP. Two pods with identical labels share an identity, so policy is expressed as "allow identity 42 to talk to identity 87 on port 8080."

Identity assignment is centralized in a small set of control-plane components (the Cilium operator and the identity garbage collector), but identity *enforcement* is entirely local to the node running the eBPF datapath. There's no central policy daemon in the packet path.

### Hooks, Top to Bottom on the Packet Path

For an incoming pod-to-pod TCP connection, the packet passes through several eBPF programs:

1. **TC ingress on the host veth.** The packet enters the kernel from the network device attached to the pod's veth pair. A TC classifier (an eBPF program attached via `tc filter`) sees it first.
2. **Endpoint lookup.** The program looks up the destination IP in the `cilium_ipcache` map to find the destination identity and the destination endpoint's metadata.
3. **Policy verdict.** It then checks `cilium_policy` (and the reverse-direction map for replies). Verdict is either allow, deny, or redirect-to-proxy.
4. **Conntrack.** If the flow is new, an entry is created in the conntrack map with source and destination identities. Replies later match the existing entry in O(1), which is the key reason eBPF datapath can actually keep up.
5. **Encapsulation (if needed).** For multi-node clusters, the program may encapsulate the packet in VXLAN or Geneve, then send it out the host interface. With [Cilium's native routing mode](https://docs.cilium.io/en/latest/network/concepts/routing/), no encapsulation is needed and the packet is forwarded via the kernel's normal routing table.
6. **XDP on the physical NIC.** For certain operations — node-level DDoS mitigation, load balancing to a local backend — Cilium can attach an XDP program that runs *before* the kernel allocates an `sk_buff`, which is roughly an order of magnitude cheaper than TC. This is the [kube-proxy replacement mode](https://docs.cilium.io/en/latest/gettingstarted/kube-proxy-replacement/) that handles NodePort and LoadBalancer traffic at line rate.

All of this happens before the packet reaches iptables at all. In a default install with kube-proxy removed, the `iptables-save` output is essentially empty for Service-related rules.

### Connection Tracking, But Local

eBPF connection tracking (`bpf_ct`) is not the same as `nf_conntrack`. It lives in BPF maps (`cilium_ct4_global`, `cilium_ct6_global`), it doesn't share state with the netfilter subsystem, and its GC is custom — tuned by Cilium's agent. The benefit is that CT lookups happen with a single hash map probe, the cost is that you can no longer use `conntrack-tools` to inspect flow state. Many operators expose visibility through `cilium monitor` and Hubble instead.

### L7 Without a Sidecar

For HTTP, gRPC, and Kafka, Cilium can intercept requests at L7 using a per-node Envoy proxy. But — and this is the clever bit — the redirect from the eBPF datapath to Envoy happens by **rewriting the destination to a local socket**, then back into the datapath on the way out. There's no iptables REDIRECT chain, no NAT gymnastics. This is what enables Cilium's L7 policy without a sidecar in every pod, as [the Cilium architecture docs](https://docs.cilium.io/en/latest/overview/architecture/) describe.

## Patterns in Production

The architecture is interesting; the way it survives a 5,000-node cluster with constant churn is more interesting. A few patterns worth knowing.

### Identity Stability Across Node Drains

When a pod is rescheduled, it gets the same labels — so it gets the same identity — as long as the namespace and labels don't change. That means policy decisions don't have to be republished through a global control plane; the new pod simply inherits an identity that's already in every node's `cilium_ipcache`. This is a quiet but significant operational win: node drains don't require a global policy recompute.

### Selective Encapsulation

You can run with VXLAN everywhere, with native routing where the underlying network supports it, or with a hybrid. With AWS ENCNI + Cilium, for instance, you can run native routing on the cloud backbone and VXLAN only between overlapping CIDRs. The encapsulation decision lives in the BPF program and is per-cluster, not per-pod.

### Hubble for Observability

Cilium ships [Hubble](https://github.com/cilium/hubble), which taps into the same eBPF programs via a ring buffer map (`cilium_events`) and produces a structured flow log: source identity, destination identity, verdict, latency, HTTP status, DNS name. Because the data comes from the same program that enforces policy, the verdict you see in Hubble is the verdict the kernel actually applied — no separate audit pipeline that can drift from reality. In incident response, this is a quietly huge improvement over `tcpdump` archaeology.

### Service Mesh Without Sidecars

For many teams, the most consequential consequence of moving to Cilium is that the eBPF datapath replaces the data plane of a service mesh. Mutating TLS, retries, telemetry, and policy can all live at the kernel boundary rather than in a per-pod Envoy. Istio's [ambient mesh](https://istio.io/latest/docs/overview/ambient/) design is built around exactly this idea, and Cilium's implementation is the reference.

## The Trade-offs You Actually Hit

eBPF in production is genuinely better than iptables for almost every workload — but not free, and not magic.

**Kernel version coupling.** Cilium requires a modern kernel (typically 5.10+ for full feature support). Older LTS distros may force you onto older features or fail to load programs at all. The verifier is conservative; code that runs fine on 5.15 may be rejected on 5.4. Plan kernel upgrades deliberately.

**Debugging is different.** You can't `strace` a BPF program. When something is wrong, you reach for `bpftool prog show`, `bpftool map dump`, `cilium monitor`, and Hubble. Build the muscle before the incident. The [bpftool reference](https://github.com/libbpf/libbpf/blob/master/src/bpftool/Documentation/bpftool.rst) is your friend.

**CT map sizing.** Connection tracking is in-memory per node. Under sustained connection storms (load tests, aggressive scanners), the map can fill, and Cilium will start dropping or NAT-failing new connections. Set `bpf-ct-global-tcp-max` and friends with intent, not defaults.

**One datapath per node.** Because the eBPF datapath is per-node and shared across all pods on that node, a kernel crash (or a verifier bug, historically rare) takes out all local pods at once. This is structurally different from a sidecar that fails one pod at a time.

**Cilium operator is still needed.** The eBPF datapath is fast, but identity allocation, IPAM, clustermesh, and policy distribution still need a control plane. You haven't eliminated the agent — you've moved it out of the hot path.

## Key Takeaways

- eBPF is the mechanism: sandboxed, JIT-compiled programs attached to kernel hooks, with shared maps for state. The kernel verifier is what makes it safe to load on production hosts.
- Cilium is the application: it uses eBPF to replace kube-proxy's iptables model with an in-kernel datapath that decides on identity, not IP.
- Performance gains come from skipping both the netfilter walk and the user-space bounce. Hubble-style observability comes from tapping the same program that enforces policy.
- The security model is identity-based and locally enforceable, which is why cluster-wide policy can update without a per-packet control-plane round-trip.
- Operational gotchas — kernel version, CT map sizing, debugging tools — are real but manageable. Cilium has been production-hardened long enough that the answers are out there.

## Further Reading

- [Cilium Architecture Overview (official docs)](https://docs.cilium.io/en/latest/overview/architecture/)
- [eBPF — What is eBPF? (official project site)](https://ebpf.io/what-is-ebpf/)
- [BPF and XDP Reference Guide — Cilium edition](https://docs.cilium.io/en/latest/bpf/)
- [Cilium kube-proxy replacement guide](https://docs.cilium.io/en/latest/gettingstarted/kube-proxy-replacement/)
- [Linux Foundation — eBPF and the future of the kernel datapath](https://www.linuxfoundation.org/resources/publications/ebpf-and-the-future-of-the-datapath)
- [libbpf and bpftool on GitHub](https://github.com/libbpf/libbpf)