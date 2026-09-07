---
title: "Inside QUIC's Loss Recovery and Congestion Control Machinery in Production Deployures"
date: "2026-09-07T07:00:29.505"
draft: false
tags: ["quic", "networking", "congestion-control", "http3", "performance"]
description: "How QUIC's loss recovery and congestion control actually work in production, from ACK frames and PTO to BBRv3 and tail latency wins."
summary: "A deep dive into the loss detection, ACK handling, and congestion control loops inside QUIC, with a focus on how they behave under real production traffic on HTTP/3 and gRPC."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-inside-quic.svg"
  alt: "Diagram showing QUIC packet flow with ACK frames and congestion window feedback loop."
  caption: ""
  relative: false
---

> **TL;DR** — QUIC folds loss recovery and congestion control into the transport itself, replacing TCP's three-way handshake + SACK + NewReno dance with a frame-driven, RTT-aware loop. In production, this collapses tail latency, enables zero-RTT resumption to behave predictably, and lets operators deploy BBRv3 or a custom CUBIC alongside HTTP/3 with far more visibility than kernel TCP ever offered.

## Why QUIC's Loss Recovery Looks Nothing Like TCP's

TCP's loss recovery grew in layers: Reno's fast retransmit, SACK for partial acknowledgment, NewReno's partial ACK handling, then later Linux got DCTCP, BBR, and TLP/PRR stitched on top. Each layer had to coexist with the others, and every retransmission was a packet that the kernel might decide to drop silently under memory pressure.

QUIC started over. Loss recovery is specified directly inside the transport ([RFC 9002](https://www.rfc-editor.org/rfc/rfc9002.html)), and the data plane is packet-based while the control plane is frame-based. That split is what lets QUIC do things TCP can't:

- ACK frames report acknowledged packet numbers with explicit ranges and ack-eliciting flags.
- Lost packets are detected by comparing the largest acked packet to a set of "send thresholds," not by counting duplicate ACKs.
- The congestion controller is a modular interface (`OnAck`, `OnCongestionEvent`, `OnPacketSent`), not a kernel state machine.

In practice at Cloudflare, Google's frontend, and Meta's edge, this means QUIC servers can ship telemetry per packet number, per ACK frame, and per congestion event — something kernel TCP only offers through `tcp_probe` and a prayer.

## Anatomy of a QUIC ACK Frame

The ACK frame is the heart of QUIC's recovery. A minimal example:

```text
ACK Frame
├── ACK Delay (variable-length integer, in microseconds)
├── ACK Range Count
├── First ACK Range (smallest packet number acked)
└── ACK Ranges
    ├── Gap (variable-length integer)
    └── ACK Range Length
```

The wire format matters because:

1. **Range reporting is explicit.** SACK in TCP is implicit (the receiver reconstructs blocks from `SACK` option bytes); QUIC ships a normalized list of (gap, length) pairs.
2. **`ACK Delay` is the receiver's local estimate of time spent between receiving the packet and sending the ACK**, in microseconds. The sender subtracts this from `now - sent_time` to get a clean RTT sample. This is why QUIC's RTT estimates don't suffer from the systematic bias that plagued early TCP stacks — see the explanation in [RFC 9000 §A.6](https://www.rfc-editor.org/rfc/rfc9000.html#appendix-A.6).
3. **The ECN counter is in the same frame.** The `ECT(0)`, `ECT(1)`, and `CE` counts ride alongside the ACK so the sender can wire L4S-style explicit congestion notification without a side channel.

In production, the largest ACK frame you'll see is bounded by `MAX_ACK_RANGES` (default 32), which caps parsing cost on the server side. This was a deliberate choice; QUIC's authors worried about ACK-frame-amplification attacks and CPU-burning parsers, as discussed in the [QUIC working group's security analysis](https://www.ietf.org/archive/id/draft-ietf-quic-protocol-39.html).

## Packet Number Spaces: Why QUIC Has Three

QUIC keeps three independent packet number spaces: Initial, Handshake, and 0-RTT/1-RTT (App data). Each space has its own loss recovery, its own ACK stream, and its own keying. The reasons are not theoretical:

- **Initial space loss recovery is short-lived.** It must complete within a few RTTs, otherwise handshake keys can be discarded before the client confirms them. This is why Initial packets are aggressively retransmitted — see the PTO math below.
- **Handshake space loss recovery is gated by TLS.** A lost Handshake CRYPTO frame blocks key derivation, so the PTO timer has to be tight (as low as 10 ms) until the first Handshake ACK arrives.
- **App data space is where congestion control lives.** Only packet numbers in this space count toward the congestion window, bytes in flight, and BBR's bandwidth model. This isolation means a lossy Initial exchange doesn't artificially inflate cwnd after handshake completion.

A real consequence: a client reconnecting to a CDN sees Initial-space packet loss without that loss affecting the App data cwnd. With TCP+TLS 1.2 over the same network, a lost SYN-ACK or a retransmitted ServerHello would have eaten into the data path's behavior.

## Loss Detection: The Three Timers

QUIC's loss detection has exactly three timers per packet number space ([RFC 9002 §5](https://www.rfc-editor.org/rfc/rfc9002.html#section-5)):

1. **Packet Threshold.** If `kPacketThreshold` (default 3) packets are sent after a given packet and none of them are acknowledged, that packet is declared lost. This is QUIC's equivalent of fast retransmit.
2. **Time Threshold.** If `smoothed_rtt + 4 * rttvar` has passed since a packet was sent without acknowledgment, it's lost. This is QUIC's equivalent of RTO.
3. **PTO (Probe Timeout).** A separate timer that fires when the sender believes the peer has gone silent. This is QUIC's response to TCP's "tail-loss probe" and "RTO" problem.

The crucial bit: when a packet is declared lost, the frames inside it are *reframed* into a new packet and re-sent. Crucially, the original packet number is *not* reused. This avoids the TCP "retransmission ambiguity" problem where a sender can't tell whether an ACK refers to the original or the retransmission.

```python
# Simplified pseudo-code from a production-style QUIC sender
def on_ack_received(ack_frame, space):
    largest_acked = ack_frame.largest_acked
    rtt_sample = now() - sent_times[largest_acked] - ack_frame.ack_delay
    rtt_estimator.update(rtt_sample)

    # Detect losses via packet threshold
    for pn in sent_packets[space]:
        if pn > largest_acked - K_PACKET_THRESHOLD:
            continue  # Too recent, skip
        if pn not in acked[space]:
            mark_lost(pn)

    # Detect losses via time threshold
    for pn in sent_packets[space]:
        if pn not in acked[space]:
            if now() - sent_times[pn] > rtt_estimator.smoothed + 4 * rtt_estimator.rttvar:
                mark_lost(pn)

    congestion.on_ack(ack_frame)
```

## PTO: The Lifeline That TCP Never Had

The PTO timer exists because QUIC supports ack-eliciting frames that the receiver must ACK, and the receiver must keep sending something even if it has no data to send. If the sender's data all goes silent and so do ACKs, both sides need a way to detect "we've heard nothing, let's send a probe."

The PTO calculation, simplified from [RFC 9002 §5.4](https://www.rfc-editor.org/rfc/rfc9002.html#section-5.4):

```text
PTO = smoothed_rtt + max(4 * rttvar, granularity) + max_ack_delay
```

Where `granularity` is the timer wheel resolution (often 1 ms in userspace stacks) and `max_ack_delay` is the receiver's declared upper bound on ACK delay (sent in the `max_ack_delay` transport parameter, default 25 ms).

When PTO fires:

1. Send a PING frame (ack-eliciting, no payload) in the App data space.
2. If a second PTO fires, send PING in the Handshake space.
3. If a third fires, send PING in the Initial space.
4. After enough PTOs without recovery, declare a connection error.

In production, you'll see PINGs during mobile handoffs (LTE → WiFi) and during serverless cold starts when the upstream is momentarily silent. PINGs are also how QUIC keeps middleboxes from idling out the connection — NATs and load balancers age out flows, but PINGs keep them warm. Cloudflare has documented this use case in their [HTTP/3 deployment notes](https://blog.cloudflare.com/the-road-to-quic/).

## Congestion Control: CUBIC Comes for Free

QUIC doesn't mandate a congestion controller. RFC 9002 specifies CUBIC ([RFC 8312](https://www.rfc-editor.org/rfc/rfc8312.html)) as the default, but the controller is a pluggable interface.

The interface, from [RFC 9002 §7](https://www.rfc-editor.org/rfc/rfc9002.html#section-7), has four hooks:

```c
void OnCongestionEvent(uint64_t acked_bytes, uint64_t prior_in_flight);
void OnPacketSent(uint64_t sent_bytes);
void OnPacketAcked(uint64_t acked_bytes);
void OnPacketLost(uint64_t lost_bytes);
```

CUBIC inside QUIC behaves like CUBIC inside Linux TCP — the `W_cubic` and `K_cubic` constants are unchanged — but the variables (`ssthresh`, `cwnd`, `t_epoch`) live in userspace. That means:

- **Restartable.** A connection can migrate to a new path (4G → WiFi) and the cwnd can be reset without kernel state surviving across the migration.
- **Observable.** Every `OnCongestionEvent` can be logged to a histogram and shipped to a telemetry backend.
- **Swappable.** You can ship a custom controller per endpoint without forking the kernel.

## BBRv3: Where QUIC Really Shines

Bottleneck Bandwidth and Round-trip propagation time (BBR) v3, described in [the BBR v3 draft](https://datatracker.ietf.org/doc/draft-cardwell-iccrg-bbr-congestion-control/) and shipped by Google since Chrome 124 and QUIC.he servers since 2023, is the controller of choice for most production HTTP/3 traffic. BBR models the path as `(BtlBw, RTprop)` and probes for both, aiming to operate near the bandwidth-delay product rather than the loss-based cwnd.

Why QUIC matters here: BBR needs accurate RTT samples, and QUIC's `ACK Delay` field gives them without the receiver-side heuristic shenanigans that kernel TCP requires. The result, as Google's measurements have shown, is tail-latency improvements of 10–25% on lossy networks ([Google's QUIC paper](https://dl.acm.org/doi/10.1145/3098822.3098842) and follow-up field reports).

```text
BBR State Machine (simplified)
├── Startup      → ramp up cwnd exponentially until BtlBw plateaus
├── Drain        → shed the excess queue Startup created
├── ProbeBW      → cycle through 8 phases, one cycle = 8 RTTs,
│                   each phase paces at a multiple of BtlBw
└── ProbeRTT     → hold cwnd to 4 * MTU for ~200 ms to refresh RTprop
```

The four ProbeRTT phases per cycle (one cycle = roughly 10 seconds on a clean link) are what let BBR coexist with CUBIC flows — a BBR flow periodically empties its bottleneck queue so the loss-based CUBIC flows stop seeing loss. This is one of the most useful properties of BBRv3 in mixed deployments.

## Patterns in Production

Here are three patterns that show up consistently in QUIC's loss recovery machinery when it ships to millions of connections.

### 1. ACK-Gap Compression Under Loss Bursts

When a QUIC connection sees a burst of packet loss (e.g., a WiFi association failure mid-download), the receiver coalesces its ACK ranges. Instead of sending one ACK per packet, it sends one ACK covering everything acknowledged so far, with the gap/length pairs compressing the report. This caps the ACK-frame bandwidth cost during loss bursts, which keeps the recovery loop from being self-defeating.

In Chrome's telemetry, this is visible as a spike in `ack_frame_bytes / data_bytes` ratios during the first 100 ms after a network change.

### 2. The 1-RTT Cwnd Reset on Path Validation

When a client migrates (e.g., switches from cellular to WiFi mid-stream), QUIC validates the new path by sending a PATH_CHALLENGE frame. Until the peer replies with PATH_RESPONSE, the App data cwnd is *not* reset — but bytes in flight on the old path *are* marked lost if they aren't acknowledged within a few RTTs. The net effect is that the new path starts with a sensible cwnd but isn't artificially penalized by the old path's accumulated state.

Cloudflare's edge logs ([publicly visible](https://blog.cloudflare.com/http-3-the-past-present-and-future/)) show that this is responsible for a measurable improvement in mobile hand-off latency for QUIC connections.

### 3. Datacenter QUIC: When the Bottleneck Is the NIC

Inside a single datacenter, QUIC usually runs on hosts that already have kernel-bypass networking (DPDK, Solarflare ef_vi, AWS DPDK-AMZN). On these paths, the bottleneck isn't bandwidth — it's packets-per-second. QUIC's per-packet encryption cost is the limiting factor, and the loss recovery machinery has to be tuned so it doesn't waste CPU on retransmits that the kernel would have absorbed transparently.

Meta's `mvfst` QUIC library (open-sourced at [facebookincubator/mvfst](https://github.com/facebookincubator/mvfst)) ships a "low-latency" mode that disables certain speculative retransmits and reduces PTO aggressiveness when the path is known to be a datacenter. This is not something TCP can offer without a kernel patch.

## Operational Pitfalls

Loss recovery is where production engineers find the sharp edges. A few I've seen firsthand:

- **Aggressive PTO underestimating `max_ack_delay`.** The receiver declares 25 ms `max_ack_delay`, but the receiver's app delays ACKs by 200 ms because of a slow serializer. The sender's PTO fires too early, PINGs flood the network, and the connection burns CPU. Fix: clamp `max_ack_delay` at the server boundary, or expose it as a config knob.
- **ACK-frame loss in the Handshake space.** A lost Handshake ACK delays the App data cwnd from opening up. The connection spends its first second on App data with cwnd = `min(4 * MTU, 10 * initial_cwnd)` instead of the full initial window. Trace it with `OnAck(space=Handshake)` event logs.
- **BBR over-pacing on satellite links.** BBRv3's ProbeBW phase 6/7 paces at 1.25× BtlBw, which on a 600 ms RTT satellite link causes an unnecessary queue. Consider running CUBIC on known-satellite paths.
- **Loss recovery running during migration.** A client that flips between SSIDs mid-stream triggers both PATH_CHALLENGE and packet loss detection at the same time. The congestion controller can oscillate. The fix is to suppress `OnCongestionEvent` until PATH_RESPONSE arrives, which is what most production stacks now do.

## Key Takeaways

- QUIC's loss recovery is built around three timers (packet threshold, time threshold, PTO) operating independently per packet number space, which is why it's both more predictable and more observable than kernel TCP.
- ACK frames carry explicit ranges, microsecond-granularity ACK delay, and ECN counts in one structure — this is the lever that makes BBR accurate and congestion control fair.
- The PTO timer is QUIC's answer to TCP's tail-loss probe problem; in production it's what keeps connections alive during middlebox idling and mobile handoffs.
- CUBIC is the default, but the pluggable congestion controller interface is what lets operators deploy BBRv3 or a custom controller per endpoint without forking the kernel.
- Loss recovery interacts with path migration in ways that production stacks now have explicit suppressors for; without them, cwnd oscillation during handoffs is a measurable source of tail latency.

## Further Reading

- [RFC 9002 — QUIC Loss Detection and Congestion Control](https://www.rfc-editor.org/rfc/rfc9002.html)
- [RFC 9000 — QUIC: A UDP-Based Multiplexed and Secure Transport](https://www.rfc-editor.org/rfc/rfc9000.html)
- [RFC 8312 — CUBIC for Fast Long-Distance Networks](https://www.rfc-editor.org/rfc/rfc8312.html)
- [The Road to QUIC — Cloudflare](https://blog.cloudflare.com/the-road-to-quic/)
- [HTTP/3: The Past, Present, and Future — Cloudflare](https://blog.cloudflare.com/http-3-the-past-present-and-future/)
- [facebookincubator/mvfst — Meta's QUIC implementation](https://github.com/facebookincubator/mvfst)
- [BBR v3 draft — IETF](https://datatracker.ietf.org/doc/draft-cardwell-iccrg-bbr-congestion-control/)
- [Measuring QUIC's Performance — Google Research](https://research.google/pubs/the-quic-transport-protocol-overview-and-current-implementation-status/)