---
title: "Optimizing Web Performance Using Varnish: HTTP Cache Header Strategies"
date: "2026-09-18T11:02:18.236"
draft: false
tags: ["varnish", "http-caching", "web-performance", "reverse-proxy", "cache-headers"]
description: "Master Varnish cache header strategies to dramatically reduce server load and latency. Learn Cache-Control, ETag, Vary, and stale-while-revalidate patterns for high-throughput web applications."
summary: "A deep dive into HTTP cache header strategies for Varnish Cache, covering Cache-Control directives, ETag validation, Vary header handling, and stale-while-revalidate patterns to maximize throughput and minimize latency."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-18-optimizing-web-performance-using-varnish-http-cache-header-strategies.svg"
  alt: "Varnish Cache performance visualization showing request throughput and latency metrics"
  caption: ""
  relative: false
---

> **TL;DR** — Varnish Cache can serve millions of requests per second when configured correctly, but its power is entirely governed by how well you set HTTP cache headers. Understanding `Cache-Control`, `ETag`, `Vary`, and `stale-while-revalidate` transforms Varnish from a simple reverse proxy into a precision caching engine that slashes origin load and cuts latency by orders of magnitude.

## Why Varnish and HTTP Headers Are a Partnership

Varnish Cache sits between your users and your origin servers, intercepting every HTTP request and deciding whether to serve a cached response or forward the request upstream. That decision-making process is driven almost entirely by HTTP cache headers. Get them right, and you achieve sub-millisecond response times at massive scale. Get them wrong, and you either serve stale content or bypass the cache entirely, negating the entire purpose of deploying Varnish.

Unlike application-level caches that require code changes, Varnish operates at the HTTP layer. This means your caching strategy is expressed through standard HTTP headers — the same headers that browsers, CDNs, and intermediate proxies understand. This universality is both Varnish's greatest strength and its most common source of misconfiguration.

Most teams deploy Varnish and see immediate performance gains, then hit a plateau where cache hit ratios stall around 40–60%. The culprit is almost always poorly configured cache headers — either missing `Cache-Control` directives, conflicting `Vary` headers, or `Cache-Control: no-cache` leaking through from upstream responses.

## Understanding Cache-Control Directives in Varnish

The `Cache-Control` header is the single most important header for Varnish operation. It tells Varnish how long to store a response, whether to revalidate before serving, and how to handle different request types.

### Core Directives and Their Varnish Behavior

When Varnish receives a response from the backend, it parses `Cache-Control` directives to determine the Time-To-Live (TTL) and caching behavior. Here are the directives that matter most:

- **`max-age=N`** — Tells Varnish (and browsers) that the response is fresh for N seconds. Varnish will serve this from cache without contacting the origin for the duration.
- **`s-maxage=N`** — Specifically for shared caches like Varnish. This overrides `max-age` for Varnish while leaving the browser's `max-age` intact. This is the most powerful directive for Varnish tuning.
- **`no-cache`** — Forces Varnish to revalidate with the origin before every serve. The response is cached, but never served stale. Useful for frequently updated content where you still want caching infrastructure.
- **`no-store`** — Prohibits caching entirely. Varnish will not store the response. Every request hits the origin.
- **`must-revalidate`** — After TTL expiration, Varnish must validate with the origin before serving stale content. It cannot serve stale responses even under load.
- **`stale-while-revalidate=N`** — Allows Varnish to serve stale content for N seconds while asynchronously revalidating in the background. This is a game-changer for handling origin failures gracefully.

```vcl
vcl 4.1;

sub vcl_backend_response {
    # Apply a generous TTL for static assets
    if (bereq.url ~ "\.(jpg|jpeg|png|gif|ico|css|js)$") {
        set beresp.http.Cache-Control = "public, max-age=31536000, immutable";
        set beresp.ttl = 1y;
    }

    # Use s-maxage to separate Varnish TTL from browser TTL
    if (bereq.url ~ "/api/") {
        set beresp.http.Cache-Control = "public, s-maxage=60, max-age=0";
        set beresp.ttl = 60s;
    }
}
```

### Setting TTLs with VCL vs. Header-Driven TTLs

Varnish gives you two ways to control TTL: through `beresp.ttl` in VCL, or through the `Cache-Control` header. Best practice is to let the backend set the header and let Varnish honor it, but override aggressively in VCL when the backend is unreliable or misconfigured.

```vcl
sub vcl_backend_response {
    # Override misconfigured headers from the backend
    if (beresp.http.Cache-Control ~ "no-cache") {
        set beresp.http.Cache-Control = "public, max-age=300";
        set beresp.ttl = 300s;
    }

    # Cap maximum TTL to prevent serving excessively stale content
    if (beresp.ttl > 1d) {
        set beresp.ttl = 1d;
    }
}
```

## ETag and Conditional Requests

ETags (Entity Tags) enable conditional requests that save bandwidth and keep cached content fresh without full retransfers. When Varnish has a cached response with an ETag and the origin responds with `Cache-Control` requiring revalidation, Varnish sends an `If-None-Match` request. If the ETag matches, the origin returns `304 Not Modified`, and Varnish serves the cached body.

### How ETags Work in a Varnish Pipeline

1. Origin returns `ETag: "abc123"` with the response.
2. Varnish stores the response body and the ETag header.
3. On revalidation, Varnish sends `If-None-Match: "abc123"`.
4. Origin compares the ETag and returns `304 Not Modified` if unchanged.
5. Varnish extends the TTL and serves the cached body.

The critical detail is that Varnish must be configured to pass conditional headers through. By default, Varnish strips `If-None-Match` from client requests but forwards them to the backend during revalidation. This happens automatically in `vcl_recv` and `vcl_backend_request`.

```vcl
sub vcl_backend_request {
    # Ensure conditional request headers reach the origin
    if (bereq.http.If-None-Match) {
        set bereq.http.If-None-Match = bereq.http.If-None-Match;
    }
}
```

### Weak vs. Strong ETags

HTTP distinguishes between weak ETags (prefixed with `W/`) and strong ETags. Weak ETags indicate semantic equivalence — the content may differ at the byte level but is functionally the same. Strong ETags require byte-for-byte identity. Varnish treats both correctly, but you should be aware that weak ETags can cause unexpected cache hits if your origin generates them inconsistently.

```text
ETag: "abc123"          — Strong ETag (byte-for-byte match required)
ETag: W/"abc123"        — Weak ETag (semantic equivalence sufficient)
```

## The Vary Header: Precision Caching for Dynamic Content

The `Vary` header is the most commonly misconfigured header in production Varnish setups. It tells Varnish to create separate cache entries based on the value of specified request headers. Without it, Varnish serves the same cached response to every client, regardless of differences that matter.

### Common Vary Scenarios

- **`Vary: Accept-Encoding`** — Varnish stores separate cached versions for gzip, brotli, and uncompressed responses. This is essential for any site using compression.
- **`Vary: User-Agent`** — Serves different cached responses for mobile and desktop clients. Use sparingly — this fragments the cache aggressively.
- **`Vary: Accept-Language`** — Stores locale-specific versions. Critical for internationalized sites.
- **`Vary: Cookie`** — Creates per-user cache entries. This effectively disables caching for those responses, so use it only when absolutely necessary.

```vcl
sub vcl_backend_response {
    # Vary on Accept-Encoding for compressed responses
    if (bereq.http.Accept-Encoding) {
        set beresp.http.Vary = "Accept-Encoding";
    }

    # Vary on Accept-Language for internationalized content
    if (bereq.http.Accept-Language) {
        set beresp.http.Vary = "Accept-Language";
    }
}
```

### The Vary Fragmentation Problem

Every additional `Vary` header dimension multiplies the number of cache entries. If you `Vary` on `Accept-Encoding` (3 values), `Accept-Language` (50 values), and `User-Agent` (100 values), you potentially create 15,000 cache entries for a single URL. This fragments your cache and destroys hit ratios.

In production, I've seen teams lose 70% of their cache hit ratio simply by adding `Vary: User-Agent` without realizing the combinatorial explosion. The fix is to normalize User-Agent at the Varnish level — classify devices into broad categories and use a single header value instead.

```vcl
sub vcl_recv {
    # Normalize User-Agent to prevent cache fragmentation
    if (req.http.User-Agent ~ "(Mobile|Android|iPhone)") {
        set req.http.X-Device-Class = "mobile";
    } else {
        set req.http.X-Device-Class = "desktop";
    }
}
```

## Stale-While-Revalidate: Grace Under Pressure

`stale-while-revalidate` (SWR) is arguably the most impactful cache header for production resilience. It allows Varnish to serve stale content while simultaneously revalidating in the background. This means users never experience cache misses during origin failures or slow responses.

### Architecture Pattern: SWR in Production

Consider a high-traffic e-commerce product page with a 5-minute TTL. At minute 5:01, the cache expires. Without SWR, the next user request hits the origin, which takes 800ms to respond. The user waits. With SWR set to `stale-while-revalidate=60`, Varnish serves the stale content instantly (sub-millisecond) while spawning a background request to the origin. The next user after that gets fresh content.

```vcl
sub vcl_backend_response {
    # Enable stale-while-revalidate for all API responses
    set beresp.http.Cache-Control = beresp.http.Cache-Control + ", stale-while-revalidate=60";

    # For homepage and critical pages, extend SWR window
    if (bereq.url == "/") {
        set beresp.http.Cache-Control = beresp.http.Cache-Control + ", stale-while-revalidate=120";
    }
}
```

### Combining SWR with Grace Mode

Varnish's `grace` period complements SWR. While SWR controls the `Cache-Control` header behavior, grace allows Varnish to serve expired content even when the backend is completely unreachable. Together, they create a robust caching layer that degrades gracefully rather than failing catastrophically.

```vcl
sub vcl_recv {
    # Enable grace mode for all requests
    set req.grace = 30s;
}

sub vcl_backend_response {
    # Set grace period per response
    set beresp.grace = 30s;
}
```

When the origin is down, Varnish serves content that is up to 30 seconds past its TTL. Combined with `stale-while-revalidate=60`, your users experience zero downtime even during full origin outages.

## The Vary Header: Precision Caching for Dynamic Content

### Handling Authorization and Private Content

Responses with `Cache-Control: private` or `Authorization` headers require special handling. Varnish treats `Authorization` as a signal to bypass the cache by default, which is correct for user-specific content. However, you can override this behavior for public APIs that use authorization tokens for rate limiting rather than content personalization.

```vcl
sub vcl_recv {
    # Allow caching of responses with Authorization header
    if (req.http.Authorization) {
        unset req.http.Authorization;
    }
}

sub vcl_backend_response {
    # Override private cache control for public API endpoints
    if (bereq.url ~ "/api/public/") {
        set beresp.http.Cache-Control = "public, max-age=300";
        set beresp.uncacheable = false;
    }
}
```

## Monitoring and Tuning Cache Hit Ratios

No caching strategy is complete without measurement. Varnish exposes detailed statistics through `varnishstat` and the Management Interface. The key metrics to watch are:

- **`cache_hit`** — Number of requests served from cache.
- **`cache_miss`** — Number of requests that required origin fetch.
- **`cache_hitrate`** — The ratio of hits to total requests. A healthy production Varnish instance should maintain above 85–95% hit rate for most workloads.
- **`n_lru_nuked`** — Number of objects evicted from cache due to memory pressure. High numbers indicate your cache size is too small for your working set.

```bash
# Check cache hit ratio
varnishstat -f cache_hit -f cache_miss

# Monitor evictions
varnishstat -f n_lru_nuked

# View real-time traffic
varnishlog -g request -q "ReqURL ~ '/api/'"
```

When your hit ratio drops, the first thing to check is whether `Vary` headers have expanded the cache working set beyond available memory. The second is whether backend responses have started returning `Cache-Control: no-store` or `no-cache` unexpectedly. A simple `varnishlog` grep for `Cache-Control` in backend responses will reveal the problem quickly.

```bash
# Debug cache-control headers from backend
varnishlog -g request -q "BerespHeader Cache-Control"
```

## Key Takeaways

- **`s-maxage` is your best friend** — It decouples Varnish's TTL from the browser's TTL, giving you independent control over edge and client caching behavior.
- **`Vary` headers fragment your cache** — Every dimension multiplies cache entries. Normalize request headers at the VCL level rather than relying on `Vary` for every difference.
- **`stale-while-revalidate` provides resilience** — It eliminates cache-miss latency spikes and keeps your site responsive during origin failures.
- **ETags enable efficient revalidation** — They save bandwidth by allowing `304 Not Modified` responses instead of full body transfers.
- **Monitor hit ratios continuously** — A dropping hit ratio is an early warning signal for misconfigured headers or cache fragmentation.
- **Override backend headers in VCL** — Never trust upstream `Cache-Control` settings blindly. Use VCL to enforce your caching policy.

## Further Reading

- [Varnish Cache Documentation — VCL Reference](https://varnish-cache.org/docs/trunk/users-guide/vcl.html) — The official VCL reference covering every subroutine, variable, and built-in function available in Varnish configuration.
- [HTTP Caching — MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/HTTP/Caching) — Comprehensive guide to HTTP cache headers, validation, and browser caching behavior from Mozilla's developer network.
- [Varnish Cache: Principles, Configuration and Usage](https://www.nginx.com/blog/varnish-cache-principles-configuration-and-usage/) — A detailed exploration of Varnish architecture, configuration patterns, and production deployment strategies from NGINX.
- [RFC 7234 — HTTP/1.1 Caching](https://tools.ietf.org/html/rfc7234) — The official IETF specification defining HTTP caching semantics, including `Cache-Control`, `ETag`, `Vary`, and conditional request behavior.
- [Varnish Cache GitHub Repository](https://github.com/varnishcache/varnish-cache) — Source code, issue tracker, and community discussions for the Varnish Cache project.
- [Varnish Plus Documentation — Stale While Revalidate](https://docs.varnish-software.com/varnish-cache-plus/stale-while-revalidate/) — Official documentation for Varnish Plus features including advanced stale content handling and real-time configuration.


---

*Building something like this? I'm an AI/systems contractor open to new projects. [Book a 30-min call](https://calendly.com/alexandrumartiniuc-dev/30min).*
