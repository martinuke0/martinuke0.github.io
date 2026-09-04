---
title: "Architecting gRPC Streaming Services with Envoy as an API Gateway"
date: "2026-09-04T16:00:39.041"
draft: false
tags: ["grpc", "envoy", "api-gateway", "service-mesh", "streaming"]
description: "A production-oriented guide to putting Envoy in front of gRPC unary, server, client, and bidirectional streaming services, with concrete config and pitfalls."
summary: "How to design, configure, and operate Envoy as an API gateway for gRPC streaming services — covering protocol translation, observability, and the failure modes that bite in production."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-architecting-grpc-streaming-services-with-envoy-as-an-api-gateway.svg"
  alt: "Diagram of Envoy routing gRPC unary and streaming calls from clients to backend services"
  caption: ""
  relative: false
---

> **TL;DR** — Envoy is one of the few gateways that natively understands gRPC over HTTP/2, which makes it ideal for fronting streaming services. The hard parts are not routing — they are timeout tuning per stream, framing observability around long-lived RPCs, and choosing the right filter chain (gRPC-JSON transcoder, WASM, ext_authz) for your traffic shape.

## Why Envoy Is a Natural Fit for gRPC Streaming

gRPC is built on HTTP/2, and Envoy is an L7 proxy written in C++ that treats HTTP/2 as a first-class citizen. That alignment sounds trivial, but it is rare: most "API gateways" terminate HTTP/1.1 and bolt gRPC on as an afterthought through a sidecar like [grpc-gateway](https://github.com/grpc-ecosystem/grpc-gateway). Envoy speaks the wire format directly, which means a server-streaming RPC looks like a normal HTTP/2 stream to the data plane — no special "streaming mode," no protocol translation tax.

The practical implications:

- **Single multiplexed connection.** Envoy reuses one HTTP/2 connection per upstream, so 10,000 client streams do not become 10,000 TCP sockets. This is the property that makes streaming at scale tractable.
- **Header-based routing that actually understands gRPC.** The `:path` of a gRPC call is `/<package>.<Service>/<Method>`. Envoy's [gRPC-JSON transcoder](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_json_transcoder_filter) and `google_grpc` service definitions let you route on method without writing custom filters.
- **Built-in support for every streaming shape.** Unary, server-streaming, client-streaming, and bidirectional all flow through the same `envoy.http_connection_manager` filter. You do not need a separate product for bidirectional, which is the mode most gateways quietly refuse to handle.

The catch is that this power is unlocked by configuration, not by a UI. Production teams who succeed with Envoy and gRPC usually invest in a small, opinionated gateway bootstrap — and that is what the rest of this post lays out.

## The Four gRPC Streaming Shapes and How Envoy Sees Them

Before designing the gateway, it helps to be precise about what the data plane actually sees. From Envoy's point of view, every gRPC method is a request stream followed by zero or more response frames, terminated by trailers containing `grpc-status`.

| Streaming mode | Client frames | Server frames | Envoy's view |
|---|---|---|---|
| Unary | 1 | 1 | One request, one response, trailers |
| Server streaming | 1 | N | Open response stream, headers early, data trickle in |
| Client streaming | N | 1 | Open request stream, client pushes, server replies once |
| Bidirectional | N | N | Both directions open until client or server `HalfClose`s |

The HTTP/2 `END_STREAM` flag is what tells Envoy the client is done writing. For server streams, Envoy keeps the upstream connection pinned to a backend pod for the entire lifetime of the stream — which directly influences your load-balancing, health-check, and outlier-detection settings. A naïve `connection_draining` policy that aggressively closes idle upstreams will silently chop long-lived market-data feeds.

If you operate server-streaming RPCs with idle periods longer than your cluster's `connect_timeout`, you'll see "upstream connection failure" errors that look like network bugs but are really your gateway giving up on the backend. The fix is almost always config, not code.

## A Reference Architecture

A gateway you can actually run on-call needs more than routing. Here is the shape I default to for greenfield deployments, expressed in terms a reader can map onto Kubernetes namespaces:

```text
┌─────────────┐      mTLS      ┌────────────────────────────┐      plaintext      ┌──────────────────┐
│  gRPC       │ ─────────────► │ Envoy (DaemonSet + Ingress) │ ─────────────────► │  gRPC backends   │
│  clients    │   HTTP/2       │                            │   HTTP/2 keepalive  │  (StatefulSet    │
│  (mobile,   │                │  • gRPC-JSON transcoder    │                    │   or Deployment) │
│   services) │                │  • ext_authz (OPA)         │                    │                  │
└─────────────┘                │  • local rate limit        │                    └──────────────────┘
                               │  • tap / access logs       │
                               └────────────────────────────┘
                                          │
                                          ▼
                                 ┌──────────────────┐
                                 │  OTel collector  │
                                 │  → Tempo / Jaeger│
                                 └──────────────────┘
```

Two non-obvious choices are worth calling out:

1. **Envoy runs as both a DaemonSet (east-west) and an Ingress (north-south).** Same binary, same config language, different listeners. This is what people mean by "Envoy as the data plane for service mesh lite" — see [the Envoy documentation on deployment topologies](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http).
2. **Authorization is delegated to OPA, not coded into the gateway.** Envoy's [`ext_authz` filter](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter) makes a gRPC callout to an OPA sidecar per request. For streaming RPCs, the callout happens at request open and at trailer close, which is exactly the right semantic — see the [ext_authz gRPC authorization protocol](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/security/ext_authz).

## Patterns in Production

### Pattern 1: Per-Route Transcoding for Mixed Clients

Most teams do not run pure gRPC. Mobile clients want JSON over HTTP/1.1, internal services want gRPC. Running two gateways is wasteful — one Envoy cluster can transcode both ways.

```yaml
# envoy.yaml — abbreviated
static_resources:
  listeners:
    - name: ingress_http
      address:
        socket_address: { address: 0.0.0.0, port_value: 8080 }
      filter_chains:
        - filters:
            - name: envoy.filters.network.http_connection_manager
              typed_config:
                "@type": type.googleapis.com/envoy.extensions.filters.network.http_connection_manager.v3.HttpConnectionManager
                codec_type: AUTO
                stat_prefix: ingress_http
                http2_protocol_options: {}
                route_config:
                  virtual_hosts:
                    - name: json_clients
                      domains: ["*"]
                      routes:
                        - match:
                            prefix: "/v1/"
                          route:
                            cluster: grpc_backend
                            timeout: 0s
                        - match:
                            prefix: "/grpc.health.v1.Health/"
                          route:
                            cluster: grpc_backend
                http_filters:
                  - name: envoy.filters.http.grpc_json_transcoder
                    typed_config:
                      "@type": type.googleapis.com/envoy.extensions.filters.http.grpc_json_v3.GrpcJsonTranscoder
                      proto_descriptor: "/etc/envoy/proto.pb"
                      services: ["orders.v1.OrderService"]
                      print_options:
                        add_whitespace: true
                        always_print_primitive_fields: true
                  - name: envoy.filters.http.router
                    typed_config:
                      "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
```

Three details that bite people:

- `codec_type: AUTO` lets one listener accept both HTTP/1.1 and HTTP/2, so JSON clients and gRPC clients share the same port.
- `timeout: 0s` on the route is deliberate for streaming — default request timeouts will kill server streams.
- The health check route is listed explicitly so probes never traverse the transcoder, which avoids a class of bugs where the transcoder refuses to parse non-gRPC bodies.

For teams using [`grpc-gateway`](https://github.com/grpc-ecosystem/grpc-gateway), the choice is whether to keep that as a separate sidecar or migrate to the transcoder. The transcoder wins on resource usage but loses on flexibility (it cannot do dynamic message reflection). Most production teams run the transcoder for stable public APIs and a small set of gateway sidecars for fast-moving internal ones.

### Pattern 2: Streaming-Aware Timeout and Keepalive Tuning

This is where most outages start. The defaults in Envoy are sane for unary traffic and wrong for streaming.

```yaml
# Upstream cluster for a server-streaming market-data service
clusters:
  - name: market_data_grpc
    type: STRICT_DNS
    connect_timeout: 1s
    lb_policy: ROUND_ROBIN
    http2_protocol_options:
      max_concurrent_streams: 100
      hpack_table_size: 4096
      initial_stream_window_size: 65536  # 64 KiB
      initial_connection_window_size: 1048576  # 1 MiB
    upstream_connection_options:
      tcp_keepalive:
        keepalive_probes: 3
        keepalive_time: 30
        keepalive_interval: 5
    typed_extension_protocol_options:
      envoy.extensions.upstreams.http.v3.HttpProtocolOptions:
        "@type": type.googleapis.com/envoy.extensions.upstreams.http.v3.HttpProtocolOptions
        common_http_protocol_options:
          idle_timeout: 300s           # 5 minutes — longer than any expected stream
        explicit_http_config:
          protocol_options:
            allow_connect: true
        http2_protocol_options:
          keepalive_interval: 30s
          keepalive_timeout: 10s
          max_concurrent_streams: 200
```

Two numbers to internalize:

- **`initial_stream_window_size`** controls how much data the sender can buffer before receiving a `WINDOW_UPDATE`. If your streams carry large proto messages (think order books or video metadata), the default 16 KiB will throttle you. Bumping to 64 KiB is a common first step; some teams go to 1 MiB for telemetry pipelines.
- **`keepalive_interval`** is the heartbeat that detects half-dead connections without sending real traffic. Set this lower than your `idle_timeout` so Envoy tears dead streams before users notice. The gRPC keepalive semantics are documented in the [gRPC keepalive guide](https://grpc.io/docs/guides/keepalive/).

For bidirectional streams (think collaborative editing, chat, or telemetry ingestion), set `idle_timeout: 0s` to disable it entirely — there is no "idle" definition that makes sense when both sides push continuously.

### Pattern 3: Streaming-Aware Observability

The standard Envoy access log format assumes a request has a duration. For a 6-hour server stream, that single timestamp is nearly useless. The solution is to log at both `START` and `END` of the stream using the [`access_log` stream filter](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/access_loggers/stream/v3/stream.proto).

```yaml
access_log:
  - name: envoy.access_loggers.stream
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.access_loggers.stream.v3.StdoutAccessLog
      log_format:
        json_format:
          start_time: "%START_TIME%"
          stream_duration: "%DURATION%"
          grpc_method: "%REQ(:PATH)%"
          grpc_status: "%GRPC_STATUS%"
          upstream_cluster: "%UPSTREAM_CLUSTER%"
          downstream_remote_addr: "%DOWNSTREAM_REMOTE_ADDRESS_WITHOUT_PORT%"
          bytes_received: "%BYTES_RECEIVED%"
          bytes_sent: "%BYTES_SENT%"
```

Pair this with OpenTelemetry tracing where the Envoy trace context spans the full stream lifetime. The trick is to emit the first span at request start, then a `stream.end` event at trailer receipt — your backend tracer joins the two. The [OpenTelemetry gRPC instrumentation spec](https://opentelemetry.io/docs/specs/semconv/rpc/grpc/) defines the canonical attribute names; using them means your streams light up correctly in [Jaeger](https://www.jaegertracing.io/) and [Tempo](https://grafana.com/oss/tempo/) without per-vendor glue.

For dashboards, two metrics matter most: `streams_active` (gauge of currently open RPCs) and `stream_duration` (histogram of end-to-end stream lifetimes). If you operate a market-data or IoT ingestion service, alert on `p99 stream_duration` going up — that is your canary before users notice lag.

### Pattern 4: WASM Filters for Custom Streaming Logic

When you need custom logic on every frame of a stream — schema validation, payload redaction, token bucket per stream — reach for [Envoy's WASM filter SDK](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/advanced/wasm/wasm) before writing native C++ filters.

```rust
// pseudo-code for a WASM filter that rate-limits per stream
fn on_stream_request(&mut self, headers: Headers) -> Action {
    let user = headers.get("x-user-id").unwrap_or_default();
    let bucket = self.buckets.entry(user).or_insert(TokenBucket::new(100, 10.0));
    if !bucket.try_consume(1.0) {
        return Action::Deny;
    }
    Action::Continue
}
```

The same filter is hot-reloadable across the fleet without restarts, which is why teams choose WASM over Lua for production. Lua's `httpCall()` cannot participate in streaming frames the way the WASM ABI can. If you are evaluating languages, the [Proxy-Wasm ABI spec](https://github.com/proxy-wasm/spec) is the source of truth and supports Rust, Go, AssemblyScript, and C++.

The honest trade-off: WASM filters add 50–200 microseconds per call depending on the language. For unary traffic this is invisible. For a high-frequency trading stream doing 50,000 messages per second, it matters. Profile before deploying.

## Common Failure Modes

### "Upstream Reset Before Response Started"

Symptom: clients see `UNAVAILABLE` with `upstream_reset_before_response_started{connection_termination}.` Cause: the cluster's `connect_timeout` is shorter than the time the backend takes to send headers on a cold stream. For services with non-trivial warmup (loading indices, JIT compilation), set `connect_timeout` to 5–10 seconds and use `preconnect` if the upstream supports it.

### "Client Closed Request Mid-Stream"

Symptom: backend logs `RESET_STREAM` errors during traffic spikes. Cause: client-side flow control window is too small, so the client stops reading and TCP back-pressures Envoy. The fix is almost always on the client (`grpc.initial_stream_window_size`), not on Envoy. But Envoy's own `initial_connection_window_size` matters too — a single slow client can starve every other stream on the connection if it is too low.

### "Transcoder 415 on Valid JSON"

Symptom: clients send what looks like correct JSON and Envoy returns `HTTP/1.1 415 Unsupported Media Type`. Cause: the proto descriptor and the deployed service code are out of sync. The transcoder validates the proto against the wire format on every request; if you forgot to regenerate `proto.pb` after a field rename, every request fails. Bake `buf generate` into CI — the [Buf CLI](https://buf.build/docs/cli/) makes this trivial.

### "gRPC Status Code 8 (RESOURCE_EXHAUSTED) Under Load"

Symptom: legitimate traffic is rejected with "too many concurrent streams". Cause: `max_concurrent_streams` on the upstream cluster is hit. The default is 100. For services that fan out (one client request → many backend streams), 100 is not enough. Raise it on both client and server sides, and remember that this is per HTTP/2 connection — with `ROUND_ROBIN` and 50 pods, your effective concurrency is 50 × 100 = 5,000 streams. That is usually fine; it stops being fine when one pod handles the connection for a long-lived stream and the rest stay idle. The fix is `lb_policy: MAGLEV` with `hash_policy` on a stable key.

## Routing and Authorization for Multi-Tenant gRPC

When multiple teams share a gateway, you need to enforce that team A cannot call team B's services. There are three reasonable designs:

1. **Per-service virtual hosts.** Simple but scales poorly — one `virtual_host` per (team, service) pair explodes the route table.
2. **Header-based authorization.** A single route, with [`ext_authz`](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/ext_authz_filter) looking at `x-team-id` and the gRPC method. Cleaner, but the policy lives outside the gateway.
3. **Service-mesh style mTLS.** Each team runs its own Envoy ingress with SPIFFE-issued identities. Strict isolation but operational overhead.

Most teams I have watched converge on option 2 with an OPA sidecar. The policy is one Rego file:

```rego
package envoy.authz

default allow = false

allow {
    input.attributes.request.http.method == "POST"
    team := input.attributes.request.http.headers["x-team-id"]
    method := input.attributes.request.http.path
    data.teams[team].services[_] == method
}
```

The corresponding Envoy config calls OPA per request, and OPA returns allow/deny in roughly 1–3 ms. For streaming RPCs, the callout happens at stream open; subsequent frames are not re-checked unless you also enable [`metadata_context_extensions`](https://www.envoyproxy.io/docs/envoy/latest/api-v3/extensions/filters/http/ext_authz/v3/ext_authz.proto) to re-authorize on metadata events. Most teams do not bother — if a client is trusted to open the stream, re-checking every frame is wasted work.

## Load Balancing Strategies That Actually Matter

Round-robin is the wrong default for streaming. Three strategies that work better:

- **Maglev with consistent hashing on a stable key** (e.g., `x-correlation-id`). Ensures a given stream lands on the same backend pod for its full lifetime, which matters when state is pinned to a connection.
- **Least-busy with active stream count** (the [`cluster_stats` extension](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/upstream/cluster_manager#cluster-stats) is your friend here). Avoids hot-spotting pods that happen to hold long streams.
- **Client-side load balancing via `grpclb` xDS.** Pairs well with Envoy in sidecar mode — the service registry pushes the same set of endpoints to Envoy and to the gRPC client. The [`grpclb` docs](https://github.com/grpc/grpc/blob/master/doc/service-load-balancing.md) explain the protocol.

For server-streaming RPCs with very long durations (minutes to hours), avoid `LEAST_REQUEST` — it reshuffles on every request and will silently migrate a stream mid-flight in some Envoy versions. Sticky hashing is the boring, correct choice.

## Key Takeaways

- Envoy speaks gRPC natively because it is HTTP/2-native — no protocol translation, no sidecar required for the basic case.
- The hard parts of running an Envoy + gRPC gateway are timeout/keepalive tuning, streaming-aware observability, and choosing the right filter chain (transcoder, ext_authz, WASM) for each route.
- Default timeouts and stream windows that work for unary traffic will silently break long-lived server and bidirectional streams. Audit `idle_timeout`, `initial_stream_window_size`, and `max_concurrent_streams` per route.
- Use WASM filters for per-frame custom logic, not Lua — and profile the latency cost before deploying to high-frequency streams.
- For multi-tenant setups, prefer OPA-backed `ext_authz` over per-team virtual hosts; for high-concurrency streaming, prefer Maglev with consistent hashing over round-robin.

## Further Reading

- [Envoy HTTP connection manager configuration reference](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_conn_man/http_conn_man)
- [gRPC keepalive guide and semantics](https://grpc.io/docs/guides/keepalive/)
- [Proxy-Wasm ABI specification](https://github.com/proxy-wasm/spec)
- [OpenTelemetry semantic conventions for gRPC](https://opentelemetry.io/docs/specs/semconv/rpc/grpc/)
- [Envoy gRPC-JSON transcoder filter](https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/grpc_json_transcoder_filter)
- [grpc-gateway: REST → gRPC for legacy clients](https://github.com/grpc-ecosystem/grpc-gateway)