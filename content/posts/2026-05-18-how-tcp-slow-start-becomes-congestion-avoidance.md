---
title: "How TCP Slow Start Becomes Congestion Avoidance"
date: "2026-05-18T03:01:00.219"
draft: false
tags: ["TCP","CongestionControl","Networking","ComputerScience","Internet"]
description: "Explore how TCP's Slow Start algorithm transitions into Congestion Avoidance, detailing the mechanisms, thresholds, and implications for network performance."
summary: "A deep dive into TCP's Slow Start and how it evolves into Congestion Avoidance, explaining the algorithms, thresholds, and real‑world impact."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-05-18-how-tcp-slow-start-becomes-congestion-avoidance.png"
  alt: "Illustration of TCP congestion window growth phases."
  caption: ""
  relative: false
---

> **TL;DR** — TCP begins a new connection in Slow Start, rapidly expanding its congestion window (cwnd) until loss is detected or a pre‑set threshold (ssthresh) is reached. At that point the algorithm switches to Congestion Avoidance, increasing cwnd more conservatively to probe available bandwidth while keeping the network stable.

TCP is the workhorse of the modern Internet, moving everything from email to video streams. Its reliability hinges on sophisticated congestion control mechanisms that balance throughput against network stability. Two of the most recognizable phases are **Slow Start** and **Congestion Avoidance**. Though they sound like separate algorithms, they are tightly coupled steps of a single state machine that adapts to changing network conditions. This article unpacks how Slow Start grows the congestion window, why it must give way to Congestion Avoidance, and what the transition tells us about the health of the path.

## The Congestion Window (cwnd) and Its Significance

The **congestion window** (`cwnd`) is a sender‑side variable that limits the amount of unacknowledged data a TCP endpoint may have in flight. It is expressed in **segments** (usually 1460‑byte packets) rather than bytes, allowing the algorithm to react to packet loss at the granularity of whole packets.

```text
cwnd (segments)   <-- controls -->   outstanding, unacknowledged data
```

When `cwnd` is small, the sender transmits only a few packets before waiting for acknowledgments (ACKs). As `cwnd` grows, the sender can inject more packets into the network, raising throughput—*provided the network can accommodate the extra load*.

Two other variables interact with `cwnd`:

* **ssthresh** (slow‑start threshold) – the point at which the algorithm switches from exponential to linear growth.
* **rwnd** (receiver window) – advertised by the receiver to prevent overwhelming its buffers.

The sender’s effective sending limit is the minimum of these three values:

```python
send_limit = min(cwnd, ssthresh, rwnd)
```

Understanding how `cwnd` evolves is the key to grasping the Slow Start → Congestion Avoidance transition.

## Slow Start: Exponential Growth for Quick Bandwidth Discovery

When a TCP connection is established, the sender initializes `cwnd` to a small value, historically one Maximum Segment Size (MSS). Modern implementations often start with 10 MSS to reduce latency on high‑speed links, but the principle remains the same: **probe the network aggressively**.

### The Mechanics

* **ACK‑driven increase** – For each ACK received, `cwnd` is increased by one MSS.
* **Resulting exponential growth** – Because each ACK acknowledges a packet that was sent because of a previous ACK, the number of packets doubles each round‑trip time (RTT).

A simple representation:

```python
# Pseudocode for Slow Start
cwnd = 1 * MSS                # Initial window
while cwnd < ssthresh:
    send(cwnd)                # Transmit cwnd segments
    wait_for_acks()           # One RTT
    cwnd += cwnd              # Double cwnd (exponential)
```

If the network can sustain the growth, throughput quickly ramps up, reaching the path’s capacity in just a few RTTs.

### Why Slow Start Is Not Forever

Exponential growth is unsustainable on a congested path. If the sender continues to double `cwnd` without restraint, it will soon inject more packets than the network can handle, leading to **queue overflow** and **packet loss**. TCP treats loss as a signal that the network is congested, prompting a reduction in `cwnd` and a shift to a more measured growth strategy.

## Detecting the Need to Transition

Two primary events trigger the exit from Slow Start:

1. **Packet loss detection** – Typically via three duplicate ACKs (fast retransmit) or a timeout.
2. **cwnd reaching ssthresh** – A pre‑configured threshold that marks the boundary between the two phases.

When loss occurs, TCP sets `ssthresh` to roughly half the current `cwnd` (often `cwnd/2`) and reduces `cwnd` to 1 MSS (or a small value). This reset is known as **multiplicative decrease**. The connection then re‑enters Slow Start, but with a lower `ssthresh`, ensuring the next growth phase will be shorter.

```bash
# Example: Loss event handling (RFC 5681)
if loss_detected:
    ssthresh = max(cwnd / 2, 2 * MSS)
    cwnd = 1 * MSS               # Restart Slow Start
```

If `cwnd` simply grows until it *equals* `ssthresh` without encountering loss, the algorithm transitions **smoothly** to Congestion Avoidance. This is the “happy‑path” scenario where the network’s capacity matches the sender’s expectations.

## Congestion Avoidance: Linear Growth for Stability

Once `cwnd` ≥ `ssthresh`, TCP adopts a **linear increase** strategy, sometimes called **Additive Increase**. The goal is to probe for extra bandwidth in a controlled manner, adding only a fraction of an MSS per RTT.

### The Classic Additive Increase

* **Increase by MSS² / cwnd per ACK** – This yields roughly one MSS per RTT, regardless of the current window size.
* **Mathematically**: `cwnd = cwnd + (MSS * MSS) / cwnd` per ACK.

A concise pseudocode:

```python
# Pseudocode for Congestion Avoidance
while True:
    send(cwnd)                  # Transmit cwnd segments
    wait_for_acks()             # One RTT
    cwnd += MSS * MSS / cwnd    # Approx. +1 MSS per RTT
```

Because the increment shrinks as `cwnd` grows, the algorithm behaves like a **gentle slope**, allowing the sender to “feel” the network’s limits without causing sudden bursts that could trigger loss.

### Fast Retransmit / Fast Recovery Interaction

If loss occurs during Congestion Avoidance, TCP typically enters **Fast Retransmit** after three duplicate ACKs, followed by **Fast Recovery**. In this path, `cwnd` is halved but not reset to 1 MSS; instead, it is set to `ssthresh` (the reduced value) and then linearly increased again. This preserves the additive increase behavior while reacting quickly to loss.

```python
# Fast Recovery (simplified)
if three_dup_acks:
    ssthresh = max(cwnd / 2, 2 * MSS)
    cwnd = ssthresh + 3 * MSS   # Inflate for each duplicate ACK
    # Retransmit missing segment
    # Continue sending new data as allowed by cwnd
```

The combination of **Multiplicative Decrease** (cut cwnd) and **Additive Increase** (grow cwnd) is the celebrated **AIMD** principle that underpins TCP’s stability.

## The Role of ssthresh: A Dynamic Boundary

`ssthresh` is not a static constant; it evolves with each loss event. Its primary purpose is to remember the last “safe” window size before congestion was observed. Over time, as the network’s capacity changes (e.g., due to routing adjustments or cross‑traffic fluctuations), `ssthresh` adapts, allowing the sender to oscillate around the optimal operating point.

### Example Timeline

| Event                     | cwnd (MSS) | ssthresh (MSS) | Phase            |
|---------------------------|------------|----------------|------------------|
| Connection start          | 1          | 64 (default)   | Slow Start       |
| After 3 RTTs (exponential) | 8          | 64             | Slow Start       |
| Loss detected (fast retransmit) | 8 → 4 (ssthresh) | 4 | Congestion Avoidance |
| Linear growth for 5 RTTs | 5 → 10     | 4              | Congestion Avoidance |
| cwnd reaches ssthresh (4) | 4          | 4              | Transition to Congestion Avoidance (if not already) |

The table illustrates how the same `ssthresh` value can serve both as a **stop‑line** for Slow Start and as a **baseline** for the additive increase in Congestion Avoidance.

## Variants and Extensions: Beyond Classic TCP

The classic Slow Start → Congestion Avoidance model described in RFC 5681 has spawned many refinements:

* **TCP Reno** – Introduced Fast Recovery, the classic AIMD behavior.
* **TCP NewReno** – Improves loss recovery when multiple packets are lost within a single window.
* **TCP CUBIC** – Uses a cubic function for cwnd growth, allowing more aggressive probing in high‑bandwidth, high‑latency (so‑called “long fat networks”) while still backing off on loss.
* **TCP BBR** – Bypasses loss‑based signals and instead estimates bottleneck bandwidth and RTT, fundamentally changing the notion of “slow start”.

Even with these innovations, the **conceptual boundary** between rapid probing (slow start) and cautious probing (congestion avoidance) remains a cornerstone of congestion control design.

## Real‑World Observations: When Slow Start Becomes a Bottleneck

In modern data centers, **bufferbloat**—excessively large buffers—can mask loss, causing Slow Start to overshoot the true capacity. This leads to prolonged latency spikes. Operators mitigate the issue by:

* **Tuning `initcwnd`** – Starting with a larger `cwnd` reduces the number of RTTs needed to reach optimal throughput, but risks overshooting on lossy links.
* **Enabling ECN (Explicit Congestion Notification)** – Allows routers to signal congestion before packet loss occurs, prompting earlier transition to Congestion Avoidance.
* **Deploying pacing** – Sends packets at a controlled rate rather than in bursts, smoothing out the exponential growth of Slow Start.

These practices illustrate that while the algorithmic transition is mathematically defined, network engineers often fine‑tune parameters to match the realities of their infrastructure.

## Key Takeaways

- **Slow Start** grows `cwnd` exponentially, quickly discovering available bandwidth but risking loss if the network cannot keep up.
- **`ssthresh`** marks the boundary; when `cwnd` reaches it—or when loss occurs—TCP switches to **Congestion Avoidance**.
- **Congestion Avoidance** uses additive increase (≈ 1 MSS per RTT) to probe bandwidth conservatively, embodying the AIMD principle.
- Loss events trigger **multiplicative decrease**, resetting `ssthresh` to roughly half of the current `cwnd` and forcing a return to Slow Start if needed.
- Modern TCP variants (Reno, NewReno, CUBIC, BBR) retain the core idea of a rapid‑probe phase followed by a measured‑probe phase, even if the exact growth functions differ.
- Practical network tuning (initial cwnd, ECN, pacing) can mitigate the drawbacks of aggressive Slow Start, especially in environments with large buffers or variable cross‑traffic.

## Further Reading

- [RFC 5681 – TCP Congestion Control](https://datatracker.ietf.org/doc/html/rfc5681) – The foundational specification describing Slow Start and Congestion Avoidance.
- [Wikipedia – Transmission Control Protocol](https://en.wikipedia.org/wiki/Transmission_Control_Protocol) – A comprehensive overview of TCP, including its congestion control algorithms.
- [TCP Congestion Control Primer – Cloudflare Learning](https://www.cloudflare.com/learning/network-layer/transport-layer/tcp-congestion-control/) – An accessible tutorial that explains the phases and modern extensions.