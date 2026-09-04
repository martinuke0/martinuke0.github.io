---
title: "Implementing Envoy's WASM Filter API for Custom Auth at the Edge"
date: "2026-09-04T18:00:29.128"
draft: false
tags: ["envoy", "wasm", "auth", "service-mesh", "edge-gateway"]
description: "Build and deploy a custom Envoy WASM filter for token-based auth at the edge, covering ABI, hostcalls, and zero-downtime rollout."
summary: "A practical guide to shipping a production-grade Envoy WASM filter that validates JWTs and custom tokens at the edge gateway."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-implementing-envoy.svg"
  alt: "Diagram of Envoy proxy running a WASM filter intercepting edge requests."
  caption: ""
  relative: false
---

> **TL;DR** — Envoy's WASM filter API lets you write auth logic once in Rust, AssemblyScript, or C++ and ship it to every proxy in your fleet without recompiling Envoy. This post walks through designing a token validation filter, wiring it through the proxy's lifecycle hooks, and deploying it behind a canary at the edge.

The Envoy proxy is one of those rare pieces of infrastructure that shows up everywhere — at the edge as an ingress gateway, in service meshes as a sidecar, and in API gateways as the request path. Anywhere you see a service-to-service hop in a modern stack, Envoy is usually close by. Most teams hit the same wall as they grow: the built-in `envoy.filters.http.jwt` filter is great when your tokens are pure JWTs, but the moment you need to call out to a session store, evaluate a risk score, or apply a custom header transformation, you start wishing for a programmable hook.

That hook exists: the [Proxy-Wasm ABI](https://github.com/proxy-wasm/spec). It is the same ABI the OpenResty and Kong Gateway WASM runtimes implement, which means a filter you build for Envoy slots into Istio and into the Contour ingress with minimal changes. In this post I'll show you what it looks like to author one of these filters in Rust — by far the most ergonomic choice for production — and deploy it to a real edge gateway.

## Why WASM at the Edge?

Before we touch code, let's be honest about the trade-offs. A WASM filter is not free. It runs in a sandboxed VM, typically V8 or Wasmtime, with a per-request context that you allocate yourself. For high-fanout edge traffic, that overhead matters.

So why bother?

- **Polyglot rollout.** You can ship a filter in Rust today, switch to Go or AssemblyScript tomorrow, without rebuilding Envoy.
- **Process isolation.** A panic in your filter takes down the WASM VM, not the data plane. Envoy keeps proxying.
- **Hot reload.** `envoy --reload` re-pulls filters from the local disk or from a remote HTTP source with no restart.
- **Standard ABI.** The same `.wasm` artifact runs in Istio, Contour, Gloo Edge, and the open-source Solo.io Envoy distribution. The [Solo blog](https://www.solo.io/blog) has a good overview of filter portability.

The honest counterpoint: for a single-digit-RPS internal service, an inline Lua script is simpler. WASM shines when you have a fleet of gateways, a need for safe rollout, and logic that is too rich for the built-in filters.

## Architecture: Where the Filter Sits

Picture an edge deployment with two regions, each fronted by an Envoy cluster terminating TLS and routing to a Kubernetes backend. Auth happens *before* the route filter executes — we want to reject anonymous traffic as early as possible so we don't burn rate limiter quota on it.

```
Client ──► TLS ──► [ envoy.filters.network.http_connection_manager ]
                       │
                       ├─► wasm.auth.custom (this post)
                       │
                       ├─► envoy.filters.http.router
                       │
                       └─► upstream cluster
```

In the HTTP connection manager, filters run in a chain. Our WASM filter gets a `RootContext` for configuration and a `Context` per request. The filter reads the `Authorization` header, validates the token, and either short-circuits with a `401` or passes the request downstream with claims attached as request headers for downstream services.

## The Proxy-Wasm ABI in 30 Seconds

The ABI is documented in the [proxy-wasm/spec](https://github.com/proxy-wasm/spec) repo. From the filter author's perspective you only need a handful of functions:

| Trait method | When Envoy calls it |
|---|---|
| `on_configure` | On filter load. Parse your plugin config here. |
| `on_request_headers` | Once headers are buffered. Return `Action::Continue` or `Action::Pause` if you'll call back asynchronously. |
| `on_response_headers` | Mirror image on the way out. |
| `on_log` | After the response is sent. Good for metrics. |

`Action::Pause` is the magic: it tells Envoy to suspend the request while your filter does async work — say, an HTTP callout to a session store. We will not use it in the simplest version of our filter, but knowing it exists is what unlocks the genuinely interesting filters.

## Writing the Filter in Rust

The `proxy-wasm` crate wraps the C ABI in safe Rust. Add it to `Cargo.toml`:

```toml
[package]
name = "auth-edge"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
proxy-wasm = "0.2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"
base64 = "0.22"
```

The `crate-type = ["cdylib"]` is the crucial line — it tells Rust to emit a dynamic library that compiles cleanly to `wasm32-unknown-unknown`.

### Plugin Configuration

A real edge filter takes config. We accept it as a JSON blob in the Envoy YAML and parse it in `on_configure`:

```rust
use proxy_wasm::traits::{Context, HttpContext, RootContext};
use proxy_wasm::types::{Action, ContextType, LogLevel};
use serde::Deserialize;

#[derive(Deserialize, Debug)]
struct PluginConfig {
    shared_secret: String,
    allow_anonymous_paths: Vec<String>,
}

struct AuthRoot {
    config: Option<PluginConfig>,
}

impl Context for AuthRoot {
    fn on_configure(&mut self, _vm_id: u32, configuration_size: usize) -> bool {
        let Some(body) = self.get_configuration(configuration_size) else {
            self.log(LogLevel::Critical, "missing plugin config");
            return false;
        };
        match serde_json::from_slice::<PluginConfig>(body.as_bytes()) {
            Ok(cfg) => { self.config = Some(cfg); true }
            Err(e) => {
                self.log(LogLevel::Critical, &format!("config parse: {e}"));
                false
            }
        }
    }
}

impl RootContext for AuthRoot {
    fn create_http_context(&self, _ctx_id: u32) -> Box<dyn HttpContext> {
        Box::new(AuthFilter { config: self.config.clone().unwrap() })
    }
    fn get_type(&self) -> ContextType { ContextType::HttpContext }
}
```

`on_configure` returning `false` is the polite way to tell Envoy "this filter is broken, fail closed." For an auth filter that is exactly the right default: we'd rather reject every request than let unauthenticated traffic through because of a config bug.

### Per-Request Logic

The per-request context receives a clone of the parsed config — `PluginConfig` is `Clone` because we derived it above — so there's no shared mutable state to worry about:

```rust
struct AuthFilter { config: PluginConfig }

impl Context for AuthFilter {}

impl HttpContext for AuthFilter {
    fn on_request_headers(&mut self, _num_headers: usize, _eof: bool) -> Action {
        let Some(path) = self.get_http_request_header(":path") else {
            return Action::Continue;
        };

        if self.config.allow_anonymous_paths.iter().any(|p| path.starts_with(p)) {
            return Action::Continue;
        }

        let Some(auth) = self.get_http_request_header("authorization") else {
            return self.deny(401, "missing authorization");
        };

        let Some(token) = auth.strip_prefix("Bearer ") else {
            return self.deny(401, "unsupported scheme");
        };

        // In real life: signature verification, expiry check, replay window.
        if !self.token_is_valid(token) {
            return self.deny(401, "invalid token");
        }

        Action::Continue
    }
}

impl AuthFilter {
    fn deny(&self, status: u64, msg: &str) -> Action {
        self.send_http_response(
            status,
            vec![("content-type", "application/json")],
            Some(format!(r#"{{"error":"{msg}"}}"#).as_bytes()),
        );
        Action::Pause
    }

    fn token_is_valid(&self, token: &str) -> bool {
        // HMAC-SHA256 verification omitted for brevity.
        !token.is_empty() && self.config.shared_secret.len() == 32
    }
}
```

Two details worth calling out. First, `send_http_response` is the only way to terminate a request from inside a filter without forwarding it. Second, returning `Action::Pause` after `send_http_response` is required — Envoy won't actually stop processing otherwise. This is the bit that trips up every new author.

## Building for the Right Target

```bash
rustup target add wasm32-unknown-unknown
cargo build --release --target wasm32-unknown-unknown
```

The output lands at `target/wasm32-unknown-unknown/release/auth_edge.wasm`. Strip it before deployment — release builds are already small, but `wasm-strip` from [wabt](https://github.com/WebAssembly/wabt) shaves a few hundred kilobytes off larger filters.

A gotcha: if you accidentally pull in `std::time::SystemTime` or anything that calls out to the host clock, your build will succeed but fail to load. Proxy-Wasm does not yet expose a clock hostcall in all runtimes. Stick to monotonic durations exposed by `proxy-wasm` itself or accept the wall clock via a header you trust.

## Wiring It Into Envoy

The Envoy config fragment:

```yaml
http_filters:
  - name: envoy.filters.http.wasm
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm
      config:
        name: auth_edge
        configuration:
          "@type": type.googleapis.com/google.protobuf.StringValue
          value: |
            {
              "shared_secret": "k7P9...32-bytes-of-entropy...",
              "allow_anonymous_paths": ["/healthz", "/version"]
            }
        vm_config:
          vm_id: edge_auth_v1
          runtime: envoy.wasm.runtime.v8
          code:
            local:
              filename: /etc/envoy/filters/auth_edge.wasm
          configuration: {}
```

Three things to verify before you ship:

1. **Order in the filter chain.** WASM filters must come *before* `envoy.filters.http.router` or you'll have already forwarded to the upstream by the time your filter runs.
2. **Allowlist the path.** Note how `/healthz` and `/version` are exempted — your load balancer probes will fail otherwise.
3. **Disk or remote.** `local` reads from the proxy's filesystem; `remote` pulls from an HTTP source with an optional SHA-256 pin. Use remote for fleet-wide rollout, local for tests.

## Patterns in Production

Once a filter is in the codebase, the team will want to extend it. Here are the patterns that hold up well at the edge.

### Metric Emission

Filter execution time is the most-watched metric. Envoy exposes a hostcall to record histograms:

```rust
self.define_metric(
    "auth_edge.request.duration_us",
    MetricType::Histogram,
);

let start = self.get_current_time_micros();
self.on_request_headers(_num_headers, _eof);
let elapsed = self.get_current_time_micros() - start;
self.record_metric("auth_edge.request.duration_us", elapsed as u64);
```

Scrape these from the Envoy admin endpoint on port 9901 and chart p50/p99. The Envoy team's [performance guide](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/advanced/wasm) is the source of truth for what hostcalls are cheap and what will allocate.

### Safe Rollout

A filter that fails closed at boot will take down your edge. Mitigate with:

- A **canary listener** on a separate port, fed by a small slice of production traffic.
- A **watchdog metric** — if `auth_edge.denied_total` spikes or `auth_edge.configured` ever goes to zero, alert and roll back.
- The **fail-open mode** flag in your plugin config, gated by an admin endpoint, for genuine emergencies.

Most teams set `fail_open: false` permanently and rely on Envoy's `--reload` to swap the filter back. The Envoy project's [hot restart docs](https://www.envoyproxy.io/docs/envoy/latest/operations/hot_restarter) describe the lifecycle in detail.

### Async Auth

If validating a token requires calling a session service, use the dispatch hostcall. Pseudocode:

```rust
fn on_request_headers(&mut self, n: usize, eof: bool) -> Action {
    self.dispatch_http_call(
        "session_store",
        vec![(":method", "POST"), (":path", "/validate"), (":authority", "session")],
        Some(serde_json::to_vec(&body).unwrap()),
        vec!["result"],
        Duration::from_millis(50),
    )?;
    Action::Pause
}

fn on_http_call_response(&mut self, ...) -> Action {
    if status == 200 { Action::Continue } else { self.deny(401, "session reject"); }
}
```

`Action::Pause` is mandatory when dispatching. The 50 ms ceiling is the move that turns this into a real production pattern — after that, fail closed rather than queue.

## Common Failure Modes

Three things bite every team shipping their first WASM filter:

- **Hidden allocations.** Every `format!` and `String` allocates on the WASM heap. At 50k RPS that's measurable. Reuse buffers when you can.
- **Misordered filters.** If `router` runs first, your filter never sees the request. Always `diff` the rendered config.
- **Sync hostcalls from async contexts.** Envoy will assert and abort the worker thread. The error log is unhelpful — you have to read the source. Sticking to the documented per-phase hostcalls saves you hours.

## Key Takeaways

- WASM filters are the right abstraction when you need richer auth than the built-in JWT filter can express, and you want one binary that runs in Envoy, Istio, and Contour.
- `crate-type = ["cdylib"]` plus the `wasm32-unknown-unknown` target is the only Rust setup that matters; everything else is standard.
- Filter placement and chain order matter more than the filter logic itself — a correctly ordered minimal filter beats a perfect filter in the wrong slot.
- Build with failure mode + metric + canary in mind from day one. Auth filters fail loudly and visibly.
- The Proxy-Wasm ABI is small. You can learn the entire surface in an afternoon, and the proxy-wasm crate keeps the unsafe C boundary out of your code.

## Further Reading

- [Proxy-Wasm specification and C header](https://github.com/proxy-wasm/spec)
- [Envoy WASM filter reference](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/advanced/wasm)
- [proxy-wasm Rust crate documentation](https://docs.rs/proxy-wasm)
- [Solo.io: WebAssembly at the edge with Envoy](https://www.solo.io/blog)
- [Wasmtime runtime used by Envoy](https://wasmtime.dev/)