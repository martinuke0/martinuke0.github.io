---
title: "Architecting a Real-Time Video Pipeline with WebRTC and Janus"
date: "2026-09-03T20:00:43.782"
draft: false
tags: ["webrtc", "janus-gateway", "real-time-video", "sfu", "streaming-architecture", "media-servers"]
description: "How to architect a production-grade real-time video pipeline using WebRTC and Janus Gateway, from signaling to SFU scaling and observability."
summary: "A working engineer's guide to building a real-time video pipeline with WebRTC and Meetecho's Janus Gateway, covering signaling, SFU topology, recording, and the failure modes you'll hit in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-architecting-a-real-time-video-pipeline-with-webrtc-and-janus.svg"
  alt: "Diagram of a WebRTC media pipeline with Janus SFU, signaling, TURN, and recording workers."
  caption: ""
  relative: false
---

> **TL;DR** — WebRTC gives you the browser-side plumbing, but production video products live or die on the media server. Janus Gateway is a lightweight, modular C SFU that handles NAT traversal, simulcast, and plugin-based media processing — making it a strong default when you need a self-hostable, open-source alternative to managed services like Agora or LiveKit Cloud.

## Why Janus, and Why Now

If you've ever been asked to add "Zoom-style" video to a product, you've probably had the same conversation twice: once about the WebRTC spec, and once about the thing that actually moves packets between peers. The browser handles the first one for free. The second is where the real architecture starts.

The simplest WebRTC setup is a **mesh**: every peer sends media to every other peer. It works fine for a 4-person standup. It collapses somewhere between 6 and 10 participants, because every additional participant multiplies the upstream bandwidth the browser has to send. A peer in a 10-person mesh isn't sending 10 streams; it's sending 10 copies of its own stream to 9 other peers.

The fix is a **Selective Forwarding Unit (SFU)** — a server that sits in the middle, receives one stream from each peer, and selectively re-emits them. The browser sends once, the SFU fans out. This is what Janus, mediasoup, LiveKit, Jitsi Videobridge, and commercial services like Agora are all, at their core.

Janus sits in an interesting spot. It's a C application, single-binary, with a plugin architecture that's been stable since 2014. It's not the flashiest project, but it has a few properties I keep coming back to:

- **Single static binary.** No runtime, no GC pauses, no JVM warmup. You can ship it in a container that starts in milliseconds.
- **Pluggable transports and media handlers.** SIP, WebSockets, Unix sockets, RabbitMQ. H.264, VP8, VP9, AV1. Recording to MP4 or WebM via a separate plugin process.
- **Battle-tested by Meetecho.** Janus is the media core of meet.jit.si, which routinely handles tens of thousands of concurrent rooms.

If you want a managed SFU, LiveKit Cloud and Daily are excellent. If you need a self-hostable, debuggable, predictable media server that you can read the source of, Janus is still a strong default in 2026.

## The Five Components of a WebRTC Pipeline

Before you write any Janus configuration, you need to understand what you're actually building. A real-time video pipeline has five distinct concerns, and conflating them is the most common architectural mistake I see.

1. **Signaling** — How peers negotiate the SDP offer/answer and exchange ICE candidates. WebRTC explicitly leaves this out of the spec. You bring your own.
2. **NAT traversal** — STUN for discovering your public address, TURN for relaying media when direct UDP is blocked. Roughly 8–15% of real-world sessions end up on TURN depending on your user base.
3. **Media transport** — SRTP over DTLS over ICE. The browser handles this; your server has to terminate it.
4. **Media processing** — Recording, transcoding, simulcast selection, server-side composition, audio mixing.
5. **Observability and control** — Stats, session state, recording lifecycle, room policies, billing hooks.

Janus handles components 3 and 4. You build 1, 2, and 5. If you skip any of them on the assumption "the SFU does it," you'll find out during the first corporate firewall test.

## Architecture: The Topology I'd Default To

For most products, this is the topology I'd start from. I'll annotate each piece with the failure mode it exists to handle.

```
                ┌─────────────────┐
                │  Browser peers  │
                │  (WebRTC)       │
                └────────┬────────┘
                         │  SRTP/UDP (preferred)
                         │  SRTP/TCP/TURN (fallback)
                ┌────────▼────────┐
                │   TURN server   │  coturn, single port range
                │   (relay only)  │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  Edge Janus 1..N │  janus-edge region per PoP
                │  (no plugins    │  terminates DTLS, forwards to core
                │   except video- │
                │   room)         │
                └────────┬────────┘
                         │  (optional) private backbone
                ┌────────▼────────┐
                │  Core Janus     │  holds session state, recording
                │  (recording,    │  talks to control plane
                │   text room,    │
                │   SIP gateway)  │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  Signaling svc  │  your service: auth, room mgmt
                │  (Go/Node/etc)  │  emits janus events upstream
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │  Object store   │  S3/GCS for recordings
                │  + metrics      │  Prometheus + Loki for logs
                └─────────────────┘
```

Three things worth calling out:

- **TURN is a separate service.** Don't run coturn on the same box as Janus. It has different scaling characteristics (bandwidth-bound, not state-bound) and you'll want to scale them independently. The [coturn project](https://github.com/coturn/coturn) is the de facto choice.
- **Edge vs. core is optional but pays off.** If your users are global, putting a stateless Janus edge close to them and a stateful core in a single region dramatically reduces time-to-first-frame. The cost is operational complexity, so don't do it on day one.
- **The signaling service is yours.** This is where your product lives. Authentication, room policies, billing events, chat history, presence — all of it goes here. Janus exposes a [JSON-over-WebSocket API](https://janus.conf.meetecho.com/docs/rest.html) and a [plain HTTP API](https://janus.conf.meetecho.com/docs/http.html); your service sits in front of it.

## Signaling: The Part You Have to Write

WebRTC's biggest design choice was punting on signaling. It's liberating and infuriating in equal measure. The good news is that the shape of a signaling service is well understood: you need an authentication step, a way for peers in the same room to discover each other, and a way to relay SDP and ICE candidates.

A common pattern is to have the browser open two long-lived connections to your signaling service:

1. A **WebSocket** for control messages (join, leave, mute, chat).
2. The **WebRTC PeerConnection** itself, which exchanges SDP and ICE via the WebSocket.

Here's a minimal example of what a peer sends when joining a room. This is the contract your signaling service has to honor:

```js
// Browser side, after opening a signaling WebSocket
const ws = new WebSocket("wss://signaling.example.com/room/42");
ws.onopen = () => {
  ws.send(JSON.stringify({
    type: "join",
    room: "42",
    token: jwtFromYourAuthService,
    displayName: "alice"
  }));
};
```

On the server side, you don't actually proxy WebRTC media through your signaling service — Janus handles that. You only relay control messages. A Go-based signaling service can comfortably handle tens of thousands of concurrent WebSocket connections on a single box if you're not doing heavy per-message work.

The [Janus documentation on the video room plugin](https://janus.conf.meetecho.com/docs/videoroom.html) is the canonical reference for what events the SFU will expect from your signaling layer. At minimum, you need to implement `join`, `configure`, `publish`, and `subscribe`.

## NAT Traversal: STUN, TURN, and the Corporate Firewall

The dirty secret of WebRTC is that 100% P2P is a lie for a meaningful fraction of users. Symmetric NATs, corporate firewalls, and mobile carrier networks regularly block inbound UDP. When ICE fails to find a direct path, you fall back to TURN, which means the media flows through your relay server.

Practical numbers from public measurements by [bloggeek.me](https://bloggeek.me/webrtc-issues/) and various SFU vendors suggest:

- 80–90% of sessions establish direct peer-to-SFU connectivity.
- 10–20% require TURN relay.
- 1–3% fail entirely, usually due to misconfigured firewalls blocking all UDP and TCP/443 simultaneously.

The implication: **your TURN capacity has to be sized for your worst-case distribution, not your median.** If 15% of your traffic needs TURN and you size TURN for 5%, you'll be explaining an outage to your CEO on a Friday night.

coturn configuration essentials:

```bash
# /etc/turnserver.conf
listening-port=3478
tls-listening-port=5349
realm=turn.example.com
use-auth-secret
static-auth-secret=YOUR_LONG_RANDOM_SECRET
total-quota=100
bps-capacity=0
stale-nonce=600
```

The `use-auth-secret` + `static-auth-secret` pattern uses [REST API for Access-Tokens (RFC 7635)](https://datatracker.ietf.org/doc/html/rfc7635), which lets your signaling service mint short-lived TURN credentials at session start instead of hardcoding long-lived passwords. This is the right way to do it in 2026.

## Patterns in Production: Recording, Simulcast, and the Recording Plugin

The thing that turns a demo into a product is recording. Janus ships a [`janus-recording`](https://github.com/meetecho/janus-gateway/wiki/Recording-Plugin) plugin that writes per-stream `.mjr` files, and a separate [`postprocessing`](https://github.com/meetecho/janus-gateway/tree/master/postprocessing) utility that can mux them into MP4 or WebM. The default workflow is:

1. Recording is enabled per-publisher via a config flag on the room.
2. Janus writes a separate file per stream to local disk.
3. A sidecar process (or a cron-triggered container) picks up finished files, muxes them, and uploads to S3.

One subtle but important detail: **the recording plugin runs in the same process as Janus by default**. If you're doing heavy recording, fork it into a separate process or you'll compete with live forwarding for CPU. The [Janus deployment guide](https://janus.conf.meetecho.com/docs/deploy.html) covers this.

Simulcast is the other production pattern worth understanding. A modern browser will publish the same video at three resolutions (typically 180p, 360p, 720p) as three separate RTP streams. The SFU decides which to forward to each subscriber based on their available bandwidth. Janus supports this in the `videoroom` plugin via the `simulcast` option on the publisher, and it dramatically improves perceived quality on mobile networks.

## Scaling Janus: The Honest Version

The [Janus project docs](https://janus.conf.meetecho.com/docs/deploy.html) are pretty upfront: Janus is **not horizontally scalable out of the box**. A single Janus instance can handle roughly 500–1000 concurrent publishers depending on hardware, codec, and plugin load. Beyond that, you need to think about the problem differently.

The pattern that actually works in production:

- **Scale up before scaling out.** A single Janus on a 16-core, 32GB box with kernel-bypass networking (DPDK isn't necessary; just make sure you're not in a VM with a software-emulated NIC) can push surprisingly far.
- **Sharding by room, not by connection.** Run multiple Janus instances, each owning a subset of rooms. Your signaling service is the router. Don't try to share state between instances — it's not worth the complexity for most products.
- **For very large rooms (1000+ subscribers), use the `multistream` plugin.** It's a different protocol that trades per-subscriber state for broadcast efficiency, and is how meet.jit.si handles large audiences.

If you genuinely need a horizontally scalable SFU with native multi-region, [LiveKit](https://livekit.io/) is a more modern choice that takes a different architectural stance. But the operational cost of running it is higher, and you give up the "single binary, no runtime" property that makes Janus so easy to reason about.

## Observability: The Thing You'll Wish You Had First

You cannot debug a real-time video pipeline without three things: per-session stats, ICE candidate visibility, and media quality metrics.

Janus exposes a [Admin API](https://janus.conf.meetecho.com/docs/admin.html) that gives you per-session state, bitrate, packet loss, and round-trip time. The trick is exposing this somewhere queryable. The pattern I recommend:

1. Run a Prometheus exporter that polls the Admin API every 10–15 seconds.
2. Ship Janus's stdout to Loki or your log aggregator of choice — the verbose log is noisy but invaluable when a specific session misbehaves.
3. Capture client-side stats in the browser (`RTCPeerConnection.getStats()`) and ship them to your backend for aggregation.

The [WebRTC samples stats](https://webrtc.github.io/samples/src/content/peerconnection/periodic-stats/) page is a good reference for what stats the browser exposes. The most useful ones in production are `bytesSent`, `packetsLost`, `framesPerSecond`, `jitter`, and `roundTripTime`.

## Key Takeaways

- **WebRTC is half a spec.** The browser gives you media, but the SFU, signaling, NAT traversal, and observability are all your problem.
- **Janus is a strong default for self-hosted SFU** when you want a single binary, low operational overhead, and a plugin architecture for recording, SIP, and text data.
- **Topology matters more than throughput.** Edge Janus for global latency, TURN as a separate service sized for worst case, and a signaling layer you own.
- **Recording and simulcast are the two patterns that turn a demo into a product.** Both are first-class in Janus's `videoroom` plugin but require operational care to run well.
- **Plan for sharding by room, not by connection.** Janus scales up nicely; horizontal scaling is a different problem you may not need to solve on day one.
- **Observability is not optional.** If you can't answer "what is the packet loss for session X right now," you cannot run this in production.

## Further Reading

- [Janus Gateway Official Documentation](https://janus.conf.meetecho.com/docs/index.html) — the canonical reference for every plugin and transport.
- [WebRTC for the Curious (webrtcforthecurious.com)](https://webrtcforthecurious.com/) — the best end-to-end explanation of the WebRTC stack I've read.
- [coturn project on GitHub](https://github.com/coturn/coturn) — the de facto TURN/STUN server.
- [RFC 7635 — REST API for Access-Tokens (TURN short-lived credentials)](https://datatracker.ietf.org/doc/html/rfc7635) — the right way to authenticate TURN.
- [WebRTC samples — periodic PeerConnection stats](https://webrtc.github.io/samples/src/content/peerconnection/periodic-stats/) — browser-side observability reference.
- [bloggeek.me — WebRTC Issues](https://bloggeek.me/webrtc-issues/) — Tsahi Levent-Levi's ongoing series on production WebRTC problems.