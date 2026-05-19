---
title: "Where TCP Transmission Speed Meets the Congestion Window Boundary"
date: "2026-05-19T04:00:06.151"
draft: false
tags: ["TCP","CongestionControl","Networking","Performance","Linux"]
description: "Explore how TCP’s transmission speed interacts with the congestion window, covering slow start, cwnd growth, loss recovery, and tuning for optimal throughput."
summary: "A deep dive into how TCP’s congestion window governs transmission speed, with practical guidance for developers and sysadmins seeking higher network performance."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-19-where-tcp-transmission-speed-meets-the-congestion-window-boundary.svg"
  alt: "Diagram of TCP congestion window and data flow."
  caption: ""
  relative: false
---

> **TL;DR** — TCP’s transmission speed is bounded by the congestion window (cwnd). Understanding how cwnd grows, shrinks, and interacts with RTT, MSS, and loss events lets you tune the stack for higher throughput without risking congestion collapse.

TCP is the workhorse of the Internet, delivering reliable, ordered streams of bytes over an unreliable packet network. Its reliability comes from a set of control mechanisms that adapt the sending rate to the prevailing network conditions. Central among those mechanisms is the **congestion window** (`cwnd`), a software‑only counter that limits the amount of unacknowledged data a sender may have “in flight”. When the sender’s data rate pushes against the cwnd boundary, the network’s capacity, latency, and loss characteristics dictate whether throughput will increase, stay flat, or collapse.

In this article we will:

* Explain the mathematical relationship between `cwnd`, **Maximum Segment Size** (MSS), and **Round‑Trip Time** (RTT).
* Walk through the classic phases of TCP congestion control—slow start, congestion avoidance, fast recovery, and timeout handling.
* Show how loss events reshape the cwnd curve and why the “cwnd boundary” is both a safety valve and a performance limiter.
* Provide concrete, platform‑specific tuning tips for Linux (the most common server OS) and compare two modern congestion‑control algorithms, **CUBIC** and **BBR**.
* Summarize actionable take‑aways for developers, network engineers, and sysadmins who need to squeeze more bandwidth out of existing links.

---

## Understanding the Congestion Window

### The Role of `cwnd` in TCP

`cwnd` is a **byte counter** maintained by the sender. It represents the maximum amount of data that may be transmitted but not yet acknowledged. The effective sending rate (`R`) is therefore bounded by:

```
R ≤ cwnd / RTT
```

where **RTT** is the measured round‑trip time for a given flow. If the sender tries to push more data than `cwnd` allows, the TCP stack will hold the excess in the send buffer until acknowledgments free up space.

Because `cwnd` is expressed in bytes, the **Maximum Segment Size** (`MSS`)—the largest payload a TCP segment can carry without fragmentation—acts as the granularity of cwnd adjustments. In most implementations, `cwnd` is increased or decreased by whole multiples of `MSS`.

### Slow Start and Congestion Avoidance

When a TCP connection is first established, `cwnd` starts at a modest value (often 10 × `MSS` on modern Linux kernels). The **slow‑start** phase then doubles `cwnd` each RTT, following an exponential growth pattern:

```
cwnd = cwnd + MSS   for each ACK received
```

This rapid increase continues until one of two events occurs:

1. **`cwnd` reaches the slow‑start threshold (`ssthresh`)**, at which point the algorithm switches to **congestion avoidance**.
2. **A loss is detected** (duplicate ACKs or timeout), prompting a reduction of `cwnd`.

During congestion avoidance, growth becomes linear:

```
cwnd = cwnd + MSS^2 / cwnd   per RTT   (≈ +1 MSS per RTT)
```

This slower increase avoids overwhelming the network once the sender has probed the available bandwidth.

---

## When Transmission Speed Hits the `cwnd` Boundary

### Calculating the Effective Rate

Assume a connection with:

* `MSS = 1460` bytes (standard Ethernet MTU minus IP/TCP headers)
* Measured `RTT = 40 ms`
* Current `cwnd = 64 KB` (`≈ 44 MSS`)

The theoretical maximum throughput (`T`) is:

```
T = cwnd / RTT
  = 64 KB / 0.04 s
  = 1.6 MB/s ≈ 12.8 Mbit/s
```

If the network path can sustain 15 Mbit/s, the sender will be **cwnd‑limited**: the congestion window prevents it from exploiting the full capacity. Conversely, if the path only supports 8 Mbit/s, the sender will encounter **packet loss** before `cwnd` reaches the limiting value, causing a reduction.

### Impact of RTT and MSS

Two variables strongly influence the cwnd‑derived rate:

| Variable | Effect on Throughput | Typical Tuning |
|----------|----------------------|----------------|
| **RTT**  | Larger RTT → lower `cwnd/RTT` for a given `cwnd`. High‑latency paths need larger `cwnd` to achieve the same throughput. | Increase `cwnd` (or use a congestion algorithm that scales with BDP). |
| **MSS**  | Larger MSS reduces per‑packet overhead, allowing a given `cwnd` to carry more payload. | Enable **TCP segmentation offload (TSO)** and avoid unnecessary MTU reductions. |

The product `cwnd × MSS` essentially defines the **Bandwidth‑Delay Product** (BDP) of the path. Matching `cwnd` to BDP ensures the pipe is full but not over‑filled.

---

## Loss Events and `cwnd` Reduction

### Fast Retransmit and Fast Recovery

When a sender receives **three duplicate ACKs** (indicating a single packet loss), the classic **fast‑retransmit** algorithm is triggered. The congestion response is:

1. Set `ssthresh = cwnd / 2` (but not below 2 × MSS).
2. Reduce `cwnd = ssthresh + 3 × MSS` (to keep the pipeline moving).
3. Enter **fast recovery**, where each additional duplicate ACK inflates `cwnd` by `MSS`.

This approach tries to recover quickly while still cutting the sending rate to avoid further loss. As described in [RFC 5681](https://datatracker.ietf.org/doc/html/rfc5681), fast recovery is a compromise between aggressive retransmission and conservative back‑off.

### Timeouts and `cwnd` Reset

If a packet is not acknowledged within the **retransmission timeout (RTO)**, TCP assumes a more severe congestion event. The response is harsher:

```
ssthresh = cwnd / 2
cwnd = 1 × MSS   (or the initial cwnd, e.g., 10 × MSS on Linux)
```

The connection re‑enters slow start, probing the network anew. Persistent timeouts can dramatically reduce throughput, especially on high‑latency links where the RTO may be large.

---

## Practical Tuning on Modern OSes

### Linux `sysctl` Knobs

Linux exposes many congestion‑control parameters via `/proc/sys/net/ipv4`. Below is a short **bash** snippet that configures a system for high‑throughput, low‑loss operation using the **CUBIC** algorithm (the default on most kernels):

```bash
# Set the congestion control algorithm
sudo sysctl -w net.ipv4.tcp_congestion_control=cubic

# Increase the default initial cwnd (default is 10 MSS)
sudo sysctl -w net.ipv4.tcp_init_cwnd=20

# Enable TCP Fast Open for reduced handshake latency
sudo sysctl -w net.ipv4.tcp_fastopen=3

# Raise the maximum receive buffer (helps on high‑BDP paths)
sudo sysctl -w net.core.rmem_max=26214400
sudo sysctl -w net.core.rmem_default=26214400

# Turn on TCP segmentation offload (if NIC supports it)
sudo ethtool -K eth0 tso on gso on
```

These settings:

* Double the initial `cwnd`, allowing the sender to ramp up faster on high‑BDP links.
* Expand the socket receive buffer to accommodate large bursts.
* Enable **TCP Fast Open** to reduce the first‑packet latency, which indirectly improves the effective RTT measurement.

### Example: BBR vs. CUBIC

Google’s **BBR** (Bottleneck Bandwidth and RTT) algorithm takes a different approach: instead of reacting to loss, it **periodically measures the bottleneck bandwidth and minimum RTT**, then sets the sending rate accordingly. This can achieve higher throughput on paths where loss is not a reliable congestion signal (e.g., wireless or satellite links).

A quick comparison on a 1 Gbps, 30 ms path with a 10 Mbps cross‑traffic flow:

| Metric            | CUBIC (default) | BBR (kernel ≥ 5.4) |
|-------------------|-----------------|--------------------|
| Average throughput| 8.1 Mbps        | 9.4 Mbps           |
| Packet loss rate | 0.45 %          | 0.12 %             |
| RTT variance      | ↑ 20 ms         | ↔ 30 ms (stable)   |

The numbers are illustrative but align with findings in the original BBR paper (see the **BBR** documentation on the [Google GitHub repository](https://github.com/google/bbr)). Switching to BBR is as simple as:

```bash
sudo sysctl -w net.ipv4.tcp_congestion_control=bbr
```

However, BBR may be less friendly to legacy middleboxes that expect loss‑based signals, so testing in a controlled environment is recommended.

---

## Key Takeaways

- **cwnd limits the sending rate**: `Rate ≤ cwnd / RTT`. Matching `cwnd` to the path’s bandwidth‑delay product (BDP) maximizes utilization.
- **Slow start grows exponentially**, but once `cwnd` reaches `ssthresh`, **congestion avoidance grows linearly** to prevent overshooting the network capacity.
- **Loss triggers cwnd reduction**: three duplicate ACKs halve `cwnd` (fast recovery), while a timeout resets it to the initial value (slow start).
- **RTT and MSS matter**: higher RTT requires larger `cwnd`; larger MSS reduces per‑packet overhead and can improve throughput.
- **Linux tuning can raise the ceiling**: increase `tcp_init_cwnd`, enlarge socket buffers, enable offloads, and choose an appropriate congestion algorithm (CUBIC for general use, BBR for loss‑tolerant environments).
- **Monitoring is essential**: tools like `ss`, `tcptrack`, and `perf` help you see cwnd evolution in real time, allowing you to validate that your tuning decisions are having the intended effect.

---

## Further Reading

- [RFC 5681 – TCP Congestion Control](https://datatracker.ietf.org/doc/html/rfc5681) – The foundational specification for slow start, congestion avoidance, and fast recovery.  
- [Linux TCP sysctl documentation](https://www.kernel.org/doc/Documentation/networking/ip-sysctl.txt) – Complete reference for all tunable kernel parameters.  
- [Google BBR Congestion Control](https://github.com/google/bbr) – Source code, design notes, and performance benchmarks for the BBR algorithm.  