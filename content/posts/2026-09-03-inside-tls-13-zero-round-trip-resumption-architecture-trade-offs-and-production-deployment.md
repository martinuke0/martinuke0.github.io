---
title: "Inside TLS 1.3 Zero Round-Trip Resumption: Architecture, Trade-Offs, and Production Deployment"
date: "2026-09-03T13:00:38.126"
draft: false
tags: ["TLS 1.3", "0-RTT", "TLS Resumption", "Networking", "Security"]
description: "A production-focused deep dive into TLS 1.3 Zero Round-Trip Resumption (0-RTT): how it works, replay risks, and how to deploy it safely."
summary: "How TLS 1.3 0-RTT cuts handshake latency to a single round trip — and the replay, forward-secrecy, and operational trade-offs you need to understand before turning it on."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-03-inside-tls-13-zero-round-trip-resumption-architecture-trade-offs-and-production-deployment.svg"
  alt: "Network packets traveling along a glowing path representing a TLS 1.3 0-RTT handshake."
  caption: ""
  relative: false
---

> **TL;DR** — TLS 1.3's 0-RTT mode lets a returning client send application payload in its very first flight, cutting handshake latency by roughly one round trip. The cost is real: 0-RTT data is not forward-secret and is replayable, so safe deployment requires strict idempotency, anti-replay defenses at the edge, and careful separation of which routes accept 0-RTT.

If you've ever wondered why your bank's mobile app re-prompts for auth on a flaky LTE connection while a content site just streams immediately on reconnect, the answer often comes down to a single bit in a TLS ClientHello: the `early_data` extension. TLS 1.3's Zero Round-Trip Resumption (commonly called **0-RTT**) is the most consequential performance feature in the protocol, and the most dangerous one if deployed without thinking it through. This post walks through how it actually works, where it lives in the stack, and how production systems — from CDNs to service meshes — gate it to keep latency low without trading away safety.

## Why TLS 1.3 Was Built for 0-RTT

Before TLS 1.3, every session reuse required at least one full round trip — a `ClientHello` carrying the session ticket, then a `ServerHello`, `Finished`, and an application response. On a mobile network where the round-trip time between client and edge might be 80–200 ms, that "free" resumption still cost noticeable latency, especially on the first request of a session resumption.

TLS 1.3 was designed from the ground up with two related optimizations: **1-RTT handshakes** (a full handshake now completes in one round trip instead of two) and **0-RTT handshakes** (a resumed handshake can complete in *zero* additional round trips, by allowing the client to send application data alongside its very first flight). The trade-off is described directly in [RFC 8446 §8](https://www.rfc-editor.org/rfc/rfc8446#section-8), which notes that 0-RTT data is fundamentally weaker than 1-RTT data because it lacks forward secrecy and can be replayed.

The result is a protocol that, on a warm connection to a nearby edge, can serve the first byte of application data in a single network round trip. That's why it powers the speed behind HTTPS connections at hyperscale CDNs and is increasingly common at the service-to-service mesh tier.

## How a TLS 1.3 Handshake Works Without 0-RTT

To understand 0-RTT, you have to know what it skips. A fresh TLS 1.3 handshake looks like this in one round trip:

1. **Client → Server**: `ClientHello` plus key share (`ClientKeyShare`), plus extensions like `supported_versions`, `signature_algorithms`, and (for resumption) `psk_key_exchange_modes` and `pre_shared_key`.
2. **Server → Client**: `ServerHello`, server key share, certificate, `CertificateVerify`, `Finished`. The server's `Finished` is already encrypted under handshake keys.
3. **Client → Server**: `Finished` plus the first application request.

That's three flights total, but only one round trip of latency matters for the application's first byte. On a 50 ms RTT link, that's ~50 ms before the first application byte can fly.

When the server hands the client a **NewSessionTicket** at the end of that handshake, the client stores it. On the next connection, the client can reuse that ticket — that's where 0-RTT enters.

## Inside 0-RTT: The Pre-Shared Key Exchange Mode

The mechanism that makes 0-RTT possible is the **pre-shared key (PSK)** exchange mode, specifically the `psk_ke` mode defined in [RFC 8446 §4.2.9](https://www.rfc-editor.org/rfc/rfc8446#section-4.2.9). There are two PSK modes in TLS 1.3:

- **`psk_dhe_ke`** — a PSK is used for authentication, but the actual key derivation mixes in a fresh (EC)DHE exchange. This gives forward secrecy and is the *safe* mode used for normal session resumption.
- **`psk_ke`** — the PSK alone is used to derive the early traffic secret. No fresh key share is exchanged for the 0-RTT data path. This is the 0-RTT mode, and it's the one with the trade-offs.

When a client wants 0-RTT, it sends the `early_data` extension alongside the `pre_shared_key` extension in its `ClientHello`, along with the application data it wants to send — all in flight one. The server, if it accepts the ticket and chooses to accept early data, processes that data immediately using keys derived from the PSK alone.

The cryptographic binding is clever but conservative: the client's `ClientHello` is committed to the PSK via a `binder` value inside `pre_shared_key`, which is essentially an HMAC over the `ClientHello` so far using a key derived from the PSK. If the binder doesn't validate, the server rejects the 0-RTT and falls back to a normal 1-RTT handshake. That design is described in detail in [Cloudflare's primer on TLS 1.3 0-RTT](https://blog.cloudflare.com/tls-1-3-0-rtt-and-optimizations/).

## What the Resumption Ticket Actually Contains

A `NewSessionTicket` is opaque to the client — it looks like a blob — but on the server side it typically carries:

- A **ticket lifetime**, capped at 7 days by the spec but often much shorter in practice (hours, or even minutes, for high-security sites).
- A **PSK identity** (the ticket value) and a **PSK** itself (sometimes derived, sometimes stored).
- A **ticket nonce** and an **obfuscated ticket age** addendum the client sends back so the server can reconstruct context.

Servers have two deployment models for tickets, each with very different 0-RTT behavior:

1. **Server-side state** (the model from TLS 1.2) — the server stores the master secret in a session cache and the ticket is just an opaque lookup key. The server can reject any ticket it wants, including for replay.
2. **Stateless / encrypted tickets** — the ticket is an encrypted blob the server can decrypt on the fly using a key only it knows. This is what most modern servers (Nginx, Envoy, BoringSSL-based stacks) deploy because it scales horizontally. The downside: the server can't easily remember "this exact ticket was already used" unless it adds a replay cache.

That distinction matters because 0-RTT replay defense is largely a problem of *server-side state*.

## The Two Fundamental Risks of 0-RTT

Every serious deployment guide for 0-RTT calls out the same two risks. The [IETF TLS Working Group's guidance on 0-RTT](https://datatracker.ietf.org/doc/html/rfc8446#appendix-E.5) is unambiguous about both.

### 1. Replay

Because the client's first flight is encrypted with a key derived only from the PSK, an attacker who captures that flight can simply replay it to the server. If the server processes the replayed request as if it were new — say, by charging a credit card or incrementing a counter — the system has a problem. The TLS layer itself doesn't know the difference between a fresh request and a replayed one. Application-layer idempotency is the only reliable defense.

A useful mental model: treat the entire 0-RTT request as if it might arrive twice. If your endpoint can safely receive the same request twice and produce the same outcome, 0-RTT is generally safe. If it can't — typical examples include POSTing to a payments endpoint, sending an email, or pushing a Kafka message with a non-idempotent producer — 0-RTT should not be used for that endpoint.

### 2. Lack of Forward Secrecy

A normal TLS 1.3 1-RTT handshake uses a fresh (EC)DHE key exchange on every connection, even when a PSK is used (in `psk_dhe_ke` mode). The session keys depend on both the PSK and a new ephemeral key pair. If an attacker later compromises the PSK, they cannot decrypt past sessions.

With 0-RTT in `psk_ke` mode, the early traffic keys are derived from the PSK alone. If an attacker records 0-RTT traffic and later exfiltrates the PSK (from server memory, a ticket database, a backup, or a memory dump), they can decrypt that traffic. This is the same risk as static RSA key exchange in TLS 1.2 — it was deprecated for exactly this reason, but 0-RTT accepts the same trade-off *only for the early data*.

The way production stacks handle this: 0-RTT is used only for short-lived data (often just GETs, or the first request in a connection), and the bulk of the session traffic still happens over `psk_dhe_ke` once the server's `Finished` arrives. So forward secrecy is preserved for everything except the 0-RTT slice — but that slice is precisely the part an attacker would most want to capture.

## Patterns in Production: Where 0-RTT Actually Helps

In real deployments, 0-RTT is gated ruthlessly. Three patterns show up repeatedly:

### Pattern 1 — Only 0-RTT the Idempotent GETs

Large CDNs and edge platforms allow 0-RTT only for `GET` and `HEAD` methods, and only on routes that don't change state. Cloudflare, Fastly, AWS CloudFront, and Akamai all publish policies along these lines. The reasoning is exactly the idempotency argument above — GETting `/api/v1/articles/12345` twice yields the same response and same side effects (cache fills, telemetry, that's it).

Cloudflare's documentation explicitly [lists which request types it forwards in 0-RTT](https://developers.cloudflare.com/fundamentals/reference/connection-encryption/#0-rtt), and it's a much narrower set than naive users expect.

### Pattern 2 — Server-Side Replay Cache for Stateless Tickets

When a server uses stateless encrypted tickets, the canonical way to defend against replay is a **client hello replay cache**: a fast key-value store (Redis, Memcached, or an in-memory LRU keyed by ticket) that records every 0-RTT `ClientHello` it has seen recently and rejects duplicates within the ticket's lifetime. AWS's [`s2n` library](https://github.com/aws/s2n-tls) shipped this as a default behavior.

The trade-off is operational: you need a cache that survives across all edge POPs that might receive a replay, otherwise an attacker who replays a request to a different region gets through. Production rollouts typically scope the cache to a region and accept a small cross-region replay window.

### Pattern 3 — Strict Transport-Level Time Bounds

The cheapest defense: keep ticket lifetimes short. If a ticket expires in 60 seconds, the replay window is 60 seconds. Many production systems cap ticket lifetime at tens of minutes specifically because every minute of lifetime is also a minute of replay window. Browsers like Chrome and Firefox have also tightened the client side, by [persisting 0-RTT tickets only briefly and refusing to use them after certain clock skew conditions](https://blog.mozilla.org/security/2018/08/13/tls-1-3-published/).

## Architecture: Where 0-RTT Lives in a Modern Stack

A typical production topology for 0-RTT looks like this:

```
[Client App / Browser]
        |   0-RTT ClientHello + early_data
        v
[Edge LB / CDN POP]  --  Decides: accept early_data or not
        |             --  If accepted: forward to origin (or serve cached response)
        v
[Origin / Service Mesh]
        |
        v
[Replay Cache]  <--- (optional) keyed by ticket or binder hash
```

The interesting policy decisions live at the edge LB. Modern ingress controllers expose a knob for this. In **Envoy**, it's [`initial_fetch_timeout`](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_proxy#0-rtt) at the listener level and `allow_extended_cache` related options at the cluster level. In **Nginx**, the relevant directives are inside the `ssl_early_data` block. In **HAProxy**, it's the [`ssl-max-early-data`](https://docs.haproxy.org/) directive.

A reasonable production policy:

| Endpoint / Method | Accept 0-RTT? | Reason |
|---|---|---|
| `GET /static/*` | Yes | Idempotent, cacheable, low value |
| `GET /api/v1/feed` | Yes | Idempotent, high-frequency |
| `POST /api/v1/login` | **No** | State-changing |
| `POST /api/v1/charge` | **No** | State-changing, financial |
| `GET /api/v1/user/balance` | Sometimes | Read-only but sensitive — accept only with replay cache |
| Any request with `Cookie: session=...` carrying auth | **No** | Replay would replay the auth |

The cookie point is subtle but important. If your 0-RTT request carries a session cookie, an attacker who replays it impersonates the user. Most guides go further than the spec and say: never accept 0-RTT for any request that includes authentication material, regardless of method. That matches what the [OWASP TLS Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.html) effectively recommends.

## A Concrete Trace: 0-RTT on a Service Mesh

Consider an internal microservice mesh where Service A talks to Service B over mTLS, and they have already completed a handshake recently. With 0-RTT enabled at the sidecar proxy (Envoy, Linkerd, or istio with Envoy underneath), the next request might look like:

```
T+0 ms     Sidecar A → Sidecar B: ClientHello + early_data + HTTP/2 HEADERS + DATA frame
T+R ms     Sidecar B → Sidecar A: ServerHello + EncryptedExtensions + Finished
T+~R ms    Sidecar A → Sidecar B: (rest of handshake) + full HTTP/2 stream
```

For a 5 ms in-cluster RTT, that's the difference between ~10 ms and ~5 ms for the first byte of the application request to arrive — meaningful in tail-latency-sensitive systems.

The mesh tier has one specific advantage here: requests are usually small, authenticated via mTLS at the workload layer (not just TLS), and idempotent by mesh convention. That makes it one of the safer places to enable 0-RTT broadly. Most service meshes enable it by default for outbound connections and rely on application-level routing rules to demote non-idempotent paths.

## Trade-Offs You Should Price In

If you're deciding whether to enable 0-RTT for your service, here are the trade-offs to make explicit. They aren't hidden, but they're easy to forget when you're chasing p99 latency.

- **Latency win**: roughly one RTT on the first request of a resumed session. In a mobile-heavy product, that's the difference between a 100 ms and a 200 ms Time to First Byte for the initial page.
- **Replay exposure window**: equal to your ticket lifetime. If you set lifetime to 10 minutes, you accept up to 10 minutes of replay risk for any non-strictly-idempotent request you let through.
- **Forward secrecy**: lost for 0-RTT data only, retained for the rest of the session. Most "sensitive" data is exchanged after the 1-RTT handshake completes, so this is usually acceptable — but it should be a conscious choice.
- **Operational complexity**: a replay cache, if you go that route, is another distributed system to operate. For stateless tickets without a cache, you give up that defense and rely purely on application idempotency.
- **Client-side compatibility**: not every TLS 1.3 client speaks 0-RTT well. Older `openssl` versions, some embedded stacks, and certain proxies can mishandle `early_data`. Worth a graceful fallback path and a metric on the rejection rate.

## Key Takeaways

- 0-RTT works by letting the client send application data inside its very first TLS flight, using a key derived solely from a previously-issued session ticket (the `psk_ke` mode).
- It is fundamentally replayable and not forward-secret — these aren't bugs, they're the explicit trade-off RFC 8446 acknowledges.
- The safe deployment pattern is to gate 0-RTT to strictly idempotent requests (typically `GET`/`HEAD`, no auth cookies) and to enforce short ticket lifetimes.
- Production stacks that use stateless encrypted tickets should add a replay cache unless they can guarantee application-level idempotency for every endpoint that accepts 0-RTT.
- Service meshes and CDNs are the most common places you'll see 0-RTT in production; the wire-level configuration lives in Envoy, Nginx, HAProxy, and BoringSSL-derived servers.
- The biggest mistake teams make is enabling 0-RTT globally without classifying their endpoints first. The biggest wasted opportunity is leaving it off globally when most of your traffic is idempotent GETs.

## Further Reading

- [RFC 8446 — The Transport Layer Security (TLS) Protocol Version 1.3](https://www.rfc-editor.org/rfc/rfc8446)
- [RFC 8446 §8 — 0-RTT data and the replay/forward-secrecy trade-offs](https://www.rfc-editor.org/rfc/rfc8446#section-8)
- [Cloudflare — TLS 1.3 0-RTT and Optimizations](https://blog.cloudflare.com/tls-1-3-0-rtt-and-optimizations/)
- [Mozilla Security Blog — TLS 1.3 Published, 0-RTT client-side considerations](https://blog.mozilla.org/security/2018/08/13/tls-1-3-published/)
- [Envoy Proxy — HTTP connection manager, 0-RTT handling](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_proxy)
- [OWASP — Transport Layer Protection Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.html)
- [aws/s2n-tls — Stateless ticket implementation with replay defense](https://github.com/aws/s2n-tls)