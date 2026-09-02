---
title: "Mastering the USE Method: A Comprehensive Guide to Utilization, Saturation, and Error Analysis"
date: "2026-09-02T18:00:48.655"
draft: false
tags: ["performance", "observability", "sre", "linux", "monitoring"]
description: "A practical, in-depth guide to Brendan Gregg's USE method for measuring utilization, saturation, and errors across CPU, memory, disk, and network."
summary: "Learn how to apply the USE method to systematically diagnose performance bottlenecks in production systems by checking utilization, saturation, and errors for every resource."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-02-mastering-the-use-method-a-comprehensive-guide-to-utilization-saturation-and-error-analysis.svg"
  alt: "Dashboard panels showing CPU utilization, memory saturation queues, and network error counters."
  caption: ""
  relative: false
---

> **TL;DR** — The USE method (Utilization, Saturation, Errors), coined by Brendan Gregg, is a checklist-first approach to performance work: for every resource, check how busy it is, how much work is queued, and how many errors it produced. It complements the RED method and is most powerful when you treat it as a triage loop, not a one-shot investigation.

When a service starts misbehaving in production, the instinct is to open a flame graph, run `top`, or grep logs. Those are reasonable moves, but they suffer from a hidden bias: you investigate what you suspect is broken, not what is actually broken. The USE method inverts that loop. You commit, up front, to checking every resource in the system, asking three identical questions for each one. The structure of the method is the value — it prevents blind spots, shortens the time to a smoking gun, and makes your postmortems reproducible.

This guide walks through the method end to end: the underlying mental model, a concrete checklist for the four classic resources, the tooling you actually need on Linux, and the patterns that show up in real incident triage.

## Origins and the Mental Model

Brendan Gregg formalized the USE method in his book *Systems Performance* and on [his performance methodology page](https://www.brendangregg.com/methodology.html). The premise is brutally simple. Performance problems eventually manifest as some resource being exhausted, contended, or faulty. If you check every resource and none is misbehaving, the problem is somewhere else (usually application code, a configuration, or an external dependency).

For each resource, you answer three questions:

- **Utilization**: How busy is the resource, over a time interval? Expressed as a percentage of time the resource was busy servicing work.
- **Saturation**: How much work is queued or waiting? A resource at 100% utilization is fully busy; saturation measures the degree to which it is *over* subscribed.
- **Errors**: How many error events occurred? This includes both observable failures and the silent ones (dropped packets, corrected ECC, retries).

Saturation is the trickiest of the three to measure and the one engineers most often skip. A CPU at 100% utilization is fine if there is no queue; a CPU at 50% utilization with a long run queue is in trouble. The same applies to disks (queue depth, await), networks (socket buffer drops, qdisc backlog), and memory (page scans, swap-in rate).

> Gregg's point: utilization and saturation are not redundant. Utilization tells you *how much* of a resource is being used; saturation tells you *how much more work is waiting*. Treat them as orthogonal dimensions, not synonyms.

## When to Reach for USE

USE shines during **first-pass triage** of an unknown problem. You have a symptom — high latency, dropped requests, slow deploys — and no obvious cause. Working through the checklist gives you either a culprit or confidence to look elsewhere. It is less useful once you already know which subsystem is broken; at that point, the RED method (Rate, Errors, Duration) on the service is usually faster.

A reasonable workflow:

1. Define the resource list for the system under test: CPUs, memory, disks, network interfaces, controllers, interconnects, software-defined limits (file descriptors, thread pools, connection pools).
2. For each, capture utilization, saturation, and error metrics over a representative window.
3. Cross-reference the symptom timeline with any resource that crossed a threshold.
4. Drill into the offender using deeper tooling (flame graphs, tracing, bpf tools).

The time investment is real. The payoff is that you stop guessing.

## The Resource Checklist

The canonical list, adapted from Gregg's writings, covers four physical resources plus a handful of software ones. I'll go through each with the specific signals worth measuring and the tools that surface them on Linux.

### CPU

**Utilization** is the time the CPU was not idle. The classic `top` and `mpstat -P ALL 1` columns work, but for production triage prefer per-CPU breakdown — a single hot core looks identical to a cool system at 60% in aggregate.

```text
$ mpstat -P ALL 1
Linux 6.5.0 (host-1)   09/02/2026   _x86_64_   (8 CPU)

10:00:00  CPU  %usr  %nice  %sys  %iowait  %irq  %soft  %steal  %guest  %idle
10:00:01  all  62.5   0.0   8.2     3.1    0.0   1.2     0.0     0.0    25.0
10:00:01    0  98.0   0.0   1.5     0.5    0.0   0.0     0.0     0.0     2.0
10:00:01    1  12.0   0.0  10.0    15.0    0.0   3.0     0.0     0.0    60.0
```

**Saturation** shows up as the run-queue length and load average. `vmstat 1` prints `r`, the number of runnable threads waiting for CPU. Load average above the core count is a classic signal. Modern kernels also expose pressure stall information (PSI), which is the most actionable saturation signal Linux offers:

```bash
cat /proc/pressure/cpu
some avg10=0.00 avg60=0.00 avg300=0.00 total=...
full avg10=12.34 avg60=8.91 avg300=5.10 total=...
```

`full` line pressure is the percentage of time at least one task was stalled waiting for CPU. Anything above a few percent sustained means you are CPU-bound *right now*, not on average. As Facebook's engineering team has written, PSI is closer to the user-visible truth than utilization alone.

**Errors** are unusual on a CPU but show up as machine check exceptions (`mcelog`), or corrected errors on hardware with RAS support. In containers, "CPU errors" usually mean throttling — check `cpu.cfs_quota_us` violations and `nr_throttled` in cgroup stats.

### Memory

**Utilization** is straightforward: `free -m` and `vmstat 1` show used and available memory. Track `available`, not `free` — the kernel reserves pages for caches that are reclaimable under pressure.

**Saturation** is the part most teams misread. The proxies to watch are:

- `pgscan` and `pgsteal` from `vmstat`: page scans per second. Anything sustained above zero means the kernel is working to reclaim memory.
- Swap-in (`si`) and swap-out (`so`) columns: non-zero values on a host with swap configured mean real pressure.
- PSI memory pressure at `/proc/pressure/memory`: the `full` line tells you how often *all* tasks are stalled waiting for memory simultaneously, which is a strong signal of perceptible user-facing latency.

**Errors** include OOM kills (`dmesg | grep -i oom`, also exposed via `memory.events` in cgroup v2) and allocation failures. A subtle one: page allocation failures under `vmstat` and from the kernel's `extfrag` counters.

A common pitfall is conflating high cache utilization with memory pressure. Caches grow to use spare memory and shrink automatically; they are not saturation. What indicates saturation is *the system reclaiming* that cache under load.

### Disks and Storage

**Utilization** of a block device is the percentage of time it had at least one request in flight. This is the most-misleading metric in the USE list: a 100% busy SSD can be healthy if requests are shallow and latency is fine, while a 10% busy SATA disk under heavy random IO can be a disaster. Always read utilization alongside the queue and the latency.

```bash
iostat -xz 1
```

**Saturation** for disks lives in the `aqu-sz` (average queue size) and `rareq-sz`/`wareq-sz` columns. A queue depth persistently above 1 on a single device means the device is the bottleneck. For NVMe, also check `nvme` smart logs and the `inflight` counter. For network-attached or distributed storage, saturation often hides behind a transport-level timeout you cannot see from the host side.

**Errors** are pulled from `/sys/block/<dev>/stat` fields like `io_errs`, or from the device's own SMART counters. Software errors show up in `dmesg` (SCSI errors, I/O errors) and in the `errors` mount option counters in `/proc/self/mountinfo`. In cloud environments, this is the place where vendor metrics (EBS `VolumeQueueLength`, disk `Errors` on Azure) become the authoritative source.

### Network

**Utilization** is the most forgiving of the three: a 1 Gbps link at 90% utilization is a saturated link, while a 100 Gbps link at 5% may already be queueing for some flows. Always express utilization as a fraction of the link capacity, not as an absolute number. `sar -n DEV 1` gives per-interface throughput.

**Saturation** is the most often missed. On Linux, the most useful signals are:

- `sar -n TCP,ETCP 1` for retransmits and active connections.
- `ss -s` for socket counts and the inuse/ orphan breakdown.
- `nstat -az` for the full set of TCP and IP counters, including `TcpExtPruneCalled`, `TcpRetransFail`, and `IPExtInBcastOctets`.
- `tc -s qdisc` to see drops at the qdisc layer.
- For the modern data path, eXpress Data Path (XDP) and the kernel's network stack expose queue lengths via `ethtool -S` per-queue counters.

**Errors** are split across many places: `ifconfig`/`ip -s link` for interface errors, NIC-level errors via `ethtool -S <iface>`, TCP retransmits and resets, and the firewall's dropped packets (`iptables -L -v` or `nft list ruleset` counters). When chasing "the network is slow," a quick loop is to sum errors at every layer — L1 (symbol errors), L2 (CRC), L3 (checksum offload mismatches), L4 (resets, timeouts).

## Architecture: USE in a Production Observability Stack

USE in its pure form is a checklist you run on a host. In a modern stack you want the same questions answered continuously, aggregated, and alertable. The standard approach is to map every USE signal to a metric in your monitoring system with a fixed naming convention, then build a single USE dashboard per host or per service.

A common structure in Prometheus:

```yaml
# USE convention: use_<resource>_<signal>
- record: use:cpu:utilization
  expr: 1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

- record: use:cpu:saturation_psi
  expr: avg by (instance) (node_pressure_cpu_waiting_seconds_total[5m]) / 5

- record: use:mem:saturation_pgscan
  expr: rate(node_vmstat_pgscan[5m])

- record: use:net:errors
  expr: rate(node_network_receive_errs_total[5m]) + rate(node_network_transmit_errs_total[5m])
```

Once every resource and signal has a metric, the USE checklist becomes a Grafana panel matrix: rows are resources, columns are U/S/E, every cell a timeseries. The discipline is what matters: every row gets a panel, every panel gets a color, and an on-call engineer can scan the whole system in 30 seconds.

For Kubernetes, the node-exporter + cAdvisor combination gives you the host-level signals. The `kube-state-metrics` exporter gives the saturation of the orchestrator: pod scheduling queue depth, PVC binding latency, and image pull errors. Treating the Kubernetes control plane as just another resource and running USE on it is one of the highest-leverage habits a platform team can build.

## Patterns in Production

A few patterns show up often enough to be worth naming explicitly.

**The inverted profile.** A host looks healthy in aggregate — 40% CPU, 60% memory used, low disk utilization — but has high PSI on CPU or memory. This is the canonical case where utilization alone lies. PSI was added to Linux precisely to surface this. The [kernel documentation on PSI](https://docs.kernel.org/accounting/psi.html) is short and worth reading.

**The single hot device.** A database with 16 disks behind a RAID controller, one of which is failing, shows up as a latency spike on every disk because the controller is retrying. From the OS you see normal utilization on all devices; saturation on the controller (`/sys/block/<md>/stat` or hardware vendor metrics) is the only clue. USE forces you to include the controller on the resource list, which is where most first-pass checklists fail.

**The hidden software resource.** Connection pools, thread pools, and file descriptors are resources with utilization and saturation that the OS does not see. A common incident shape: a service with 50% CPU and ample memory that gets slow, because its HTTP client is throttled to 10 connections per upstream and 200 of them are queued. The fix is to add a USE pass over every software-defined limit. Most APM systems expose pool saturation directly — for example, HikariCP's `hikaricp_pending_connections` in Micrometer.

**The noisy-neighbor container.** In a shared cluster, utilization metrics from the host hide per-container saturation. Always run USE at the cgroup/v2 level, not just at the host, in containerized environments. `container_cpu_pressure_total` from cAdvisor is the saturation signal you want.

**Errors that aren't really errors.** Network interface errors include "out-of-buffer" events on some NICs, which are routine and not failure. TCP retransmits include the fast-retransmit path, which is normal. Distinguishing failure from normal-recovery requires reading the source of the counter, not just the name. The `nstat` man page and the [kernel's networking documentation](https://www.kernel.org/doc/Documentation/networking/) are the canonical references.

## Common Mistakes

Treating USE as a one-time audit. The method is most useful as a recurring process, embedded in your on-call runbook. A quarterly USE review of every tier of your stack catches capacity issues, firmware regressions, and config drift long before they become incidents.

Stopping at utilization. The temptation is to declare "CPU is 70%, so we're fine" and move on. Always answer the saturation and errors questions too, even if the numbers look small. Saturation is the leading indicator; errors are the trailing one.

Ignoring the resource list itself. The first five minutes should be spent writing down the resource list for the system. If you skip that, you will check CPU, memory, disk, and network and miss the storage controller, the kernel's TCP send buffer, the cgroup memory high watermark, or the DNS resolver.

Confusing USE with the only method you need. USE is one of three commonly paired methodologies in Gregg's toolkit. The other two are RED (Rate, Errors, Duration for services) and the Four Golden Signals (latency, traffic, errors, saturation from the SRE book). USE is resource-focused; RED is service-focused; they answer different questions. A complete triage uses both.

## USE vs RED vs Golden Signals

A useful way to keep these straight:

- **USE** asks: is the machine okay? Resource view, host-level, ideal for infrastructure and platform teams.
- **RED** asks: is the service okay? Request view, ideal for service owners and SREs looking at a specific API.
- **Golden Signals** is RED plus traffic, written for the [Google SRE book](https://sre.google/sre-book/monitoring-distributed-systems/) and broadly equivalent for triage purposes.

A complete on-call runbook for a service typically starts with RED on the service, then drops down to USE on the host when RED shows a problem that is not externally explainable. Together they form a funnel from "user pain" to "machine cause."

## Key Takeaways

- The USE method's value is its completeness. The discipline of asking the same three questions for every resource catches problems you would otherwise miss.
- Utilization and saturation are orthogonal. A resource can be heavily utilized with no queue, or lightly utilized with a long queue. Measure both.
- On Linux, PSI is the most actionable signal for CPU and memory saturation; `iostat`, `nstat`, and `ethtool` cover the rest.
- Software-defined resources — pools, queues, file descriptors, cgroup limits — are part of the resource list. Omitting them is the most common reason USE fails in practice.
- USE pairs with RED: USE for the host, RED for the service. Together they form a complete triage loop from user-visible symptoms down to machine cause.
- Embed the method in your runbooks and dashboards. A static list is less useful than a panel matrix you actually look at during incidents.

## Further Reading

- [Brendan Gregg — The USE Method](https://www.brendangregg.com/usemethod.html)
- [Brendan Gregg — Performance Methodology](https://www.brendangregg.com/methodology.html)
- [Linux kernel documentation — Pressure Stall Information (PSI)](https://docs.kernel.org/accounting/psi.html)
- [Google SRE Book — Monitoring Distributed Systems (Golden Signals)](https://sre.google/sre-book/monitoring-distributed-systems/)
- [Prometheus node_exporter — metrics reference](https://github.com/prometheus/node_exporter#enabled-by-default)
- [bcc tools — Brendan Gregg's performance tooling collection](https://github.com/iovisor/bcc)