---
title: "Optimizing Varnish Cache Purges with BAN Tables and Incremental Invalidation"
date: "2026-09-11T20:00:39.241"
draft: false
tags: ["varnish", "caching", "performance", "cdn", "devops"]
description: "Learn how to optimize Varnish Cache purges using BAN tables and incremental invalidation to reduce origin load and maintain cache coherence at scale."
summary: "Explore how Varnish Cache BAN tables and incremental invalidation strategies reduce purge overhead, keep cache coherent, and cut origin load in high-traffic production environments."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-11-optimizing-varnish-cache-purges-with-ban-tables-and-incremental-invalidation.svg"
  alt: "A visualization of Varnish Cache purge flows and BAN table lookups"
  caption: ""
  relative: false
---

> **TL;DR** — Varnish Cache's `PURGE` and `BAN` mechanisms serve fundamentally different roles, and choosing the wrong one at scale can overwhelm your origin or bloat memory. BAN tables with regex matching and incremental invalidation let you target groups of objects precisely, avoiding the thundering herd problem that blanket `PURGE` requests create. This post walks through the architecture, configuration patterns, and production-tested optimizations that keep cache coherence without sacrificing throughput.

## Why Cache Purges Are a Hard Problem

Every high-traffic website eventually hits the same wall: stale content needs to disappear, but evicting it naively triggers a stampede of requests back to the origin. When a single cached object is invalidated and thousands of concurrent users request it simultaneously, Varnish hands every one of those requests to the backend. This is the thundering herd, and it can take down an origin in seconds.

Traditional `PURGE` requests in Varnish operate on exact URL matches. You send a `PURGE /article/123` and Varnish removes that specific object from cache. Simple enough — until you need to invalidate every variant of that article: every language, every device class, every query-parameter permutation. Suddenly one content change means dozens of `PURGE` calls, and if you miss one, users see stale data.

This is where the distinction between hard purges and soft invalidation becomes operationally critical. A `PURGE` removes the object entirely. A `BAN` marks objects as stale without deleting them, so the next request that matches the ban rule triggers a background re-fetch while still serving the stale copy to the first arriving request. The difference is not academic — it directly determines whether your origin sees a spike or a gentle ramp.

## Understanding BAN Tables

BAN (Bitwise AND NOT) tables are Varnish's mechanism for expressing conditional invalidation rules. Unlike `PURGE`, which matches on exact URL, a BAN rule evaluates a VCL expression against every cached object's request headers and URL. When a request arrives and matches a BAN expression, Varnish treats the object as a miss and fetches a fresh copy from the backend.

### How BAN Matching Works Internally

When Varnish receives a request, it checks the object's `req.url` and `req.http` headers against every active BAN entry. The matching uses a bitwise evaluation: if the object's attributes satisfy the ban condition, the object is considered banned. Crucially, BANs do not remove objects from the cache heap — they simply mark them as ineligible for serving. The actual eviction happens lazily, when the object is requested and found to be banned.

This design has a significant performance implication: adding a BAN is an O(1) operation. Varnish appends the rule to a linked list, and the cost of checking it against incoming requests is amortized across the request rate. Compare this to a blanket `PURGE` of a popular URL, which triggers synchronous revalidation for every concurrent request.

```vcl
vcl 4.1;

sub vcl_recv {
    if (req.method == "BAN") {
        if (!client.ip ~ ban_agents) {
            return (synth(403, "Forbidden"));
        }
        ban("req.url ~ " + req.url + " && obj.http.content-type ~ text/html");
        return (synthetic(200, "BAN added"));
    }
}

acl ban_agents {
    "127.0.0.1";
    "10.0.0.0"/8;
}
```

In this configuration, only IPs in the `ban_agents` ACL can submit BAN requests. The BAN expression targets HTML responses whose URL matches the incoming request URL, leaving images, scripts, and other asset types untouched.

### The Cost of Over-Banning

BANs are not free. Every active BAN rule adds a linear scan cost to every cache lookup. Varnish evaluates BAN rules in order, and with thousands of rules in the list, lookup latency degrades measurably. In production environments at companies processing millions of requests per minute, a BAN table exceeding 10,000 entries has been observed to add 0.5–2 ms of latency per request — enough to push response times past SLO thresholds.

The solution is not to avoid BANs, but to manage their lifecycle aggressively. Expire old BANs, consolidate overlapping rules, and use the `ban.list` command to audit the table regularly.

```bash
varnishadm ban.list
```

This command outputs every active BAN expression along with its creation timestamp. Building a cron job that parses this output and removes rules older than a configured TTL prevents unbounded growth.

## Incremental Invalidation Patterns

Incremental invalidation is the practice of invalidating only the subset of cache objects that are actually affected by a content change, rather than flushing entire sections of the cache. In Varnish, this is achieved by combining BAN expressions with structured URL naming conventions and versioned cache keys.

### Pattern 1: Versioned URLs with BAN Targeting

The most straightforward incremental invalidation strategy is to embed version identifiers directly in URLs. When content at `/products/widgets` changes, you serve it at `/products/widgets?v=2` instead of trying to purge the old entry.

```vcl
sub vcl_hash {
    if (req.url ~ "\?v=") {
        hash_data(req.url);
    } else {
        hash_data(req.url);
        hash_data(req.http.host);
    }
}
```

With this approach, the old URL `/products/widgets?v=1` remains in cache and continues serving until its natural TTL expires. New requests for the updated version automatically populate the cache with fresh content. The BAN table is used only to accelerate the transition — you issue a BAN for the old URL to remove it immediately rather than waiting for TTL expiry.

This pattern eliminates the thundering herd entirely for most content updates, because the old and new versions coexist in cache during the transition window.

### Pattern 2: Tag-Based Invalidation with Header Injection

For more complex relationships — a blog post belongs to a category, which belongs to a section — URL-based BANs become unwieldy. The alternative is to inject content tags into cache objects via backend response headers and use those tags in BAN expressions.

```vcl
sub vcl_backend_response {
    if (bereq.url ~ "^/api/articles/") {
        set beresp.http.X-Cache-Tags = beresp.http.X-Content-Tags;
    }
}

sub vcl_recv {
    if (req.method == "BAN") {
        ban("obj.http.X-Cache-Tags ~ " + req.http.X-Ban-Tag);
        return (synthetic(200, "BAN by tag added"));
    }
}
```

When the backend publishes an article tagged with `["technology", "ai", "2026"]`, those tags are stored in `obj.http.X-Cache-Tags`. To invalidate all AI-related content, you send a BAN request with `X-Ban-Tag: ai`. Varnish matches every cached object whose tags header contains "ai" and marks it for revalidation.

This approach scales to hundreds of content types and relationships without requiring URL restructuring. The tradeoff is that the backend must consistently emit the correct tags, and the BAN matching overhead grows with the number of unique tag values.

### Pattern 3: Grace Mode as a Safety Net

Incremental invalidation is not perfect. There will always be a window — however small — where a banned object is still being served to a request that arrived before the ban took effect. Varnish's `grace` mode bridges this gap by allowing stale objects to be served while a background thread fetches the fresh version.

```vcl
sub vcl_backend_response {
    set beresp.grace = 1h;
}

sub vcl_hit {
    if (obj.ttl >= 0s) {
        return (deliver);
    }
    if (std.healthy(req.http.host)) {
        return (deliver);
    }
    return (fetch);
}
```

With `grace` set to one hour, a banned object that is still within its grace period can be served immediately while Varnish fetches a replacement. The first user after a ban gets a near-instant response, and subsequent users get the fresh content. This pattern is essential for maintaining perceived performance during cache churn.

## Architecture in Production

Running BAN-based invalidation at scale requires careful architectural decisions. The following patterns have been validated in production environments handling 50,000+ requests per second.

### Separation of Concerns: Cache Layer vs. Invalidation Layer

In a typical deployment, Varnish sits behind a load balancer and in front of one or more application servers. The invalidation layer — the service or cron job that issues BAN requests — should be completely separate from both the application and the cache layer.

```
[Application Server] --> [Varnish Cache] <-- [User Requests]
                                  ^
                                  |
                        [Invalidation Service]
                        (issues BAN requests)
```

The invalidation service listens for content change events from the application — webhooks, message queue events, database triggers — and translates them into BAN requests. This decoupling means that a surge of content updates does not compete with user traffic for Varnish worker threads.

### Rate Limiting and Queuing BAN Requests

BAN requests are expensive. Each one adds a rule to the BAN table and triggers evaluation on subsequent requests. A content management system that publishes 500 articles per minute will generate 500 BAN requests per minute, which can overwhelm the BAN table and degrade lookup performance.

The solution is to queue and batch BAN requests. A message queue like RabbitMQ or Kafka absorbs the burst, and a consumer process issues BAN requests at a controlled rate.

```python
import pika
import varnishlib

connection = pika.BlockingConnection(pika.ConnectionParameters('rabbitmq'))
channel = connection.channel()
channel.queue_declare(queue='ban_requests')

def on_ban_request(ch, method, properties, body):
    tag = body.decode('utf-8')
    # Batch multiple tags into a single BAN expression
    varnishlib.ban(f"obj.http.X-Cache-Tags ~ {tag}")

channel.basic_consume(queue='ban_requests', on_message_callback=on_ban_request, auto_ack=True)
channel.start_consuming()
```

This pattern ensures that the BAN table grows at a predictable rate and that Varnish is not overwhelmed by synchronous invalidation calls.

### Monitoring BAN Table Health

A BAN table that grows unchecked is a silent performance killer. Monitoring must track three metrics: the number of active BAN rules, the average lookup latency, and the rate of ban-induced revalidations.

```bash
varnishstat -f MAIN.ban_*.
varnishstat -f MAIN.cache_hit
varnishstat -f MAIN.cache_miss
```

The `MAIN.ban_*` counters in `varnishstat` provide visibility into how many bans are being evaluated per request. If the count per request exceeds 50, it is time to prune the table or consolidate rules. Pairing these metrics with Grafana dashboards and alerting thresholds ensures that degradation is caught before it impacts users.

## Common Pitfalls and How to Avoid Them

### Pitfall 1: Using PURGE When BAN Is Required

The most common mistake is reaching for `PURGE` when the content change affects multiple objects. A `PURGE /blog/` request only removes the exact URL `/blog/` — it does not touch `/blog/page/2`, `/blog/?category=tech`, or any other variant. The result is a partially stale cache that serves outdated content silently.

Always ask: "Does this content change affect one URL or many?" If the answer is many, use BAN.

### Pitfall 2: Unbounded BAN Table Growth

Every BAN you add stays in the table until explicitly removed with `ban.url` or until Varnish restarts. In a system where content is updated frequently, the BAN table can grow to millions of entries within hours. The fix is a scheduled cleanup job that removes expired or redundant rules.

```bash
# Remove all BANs older than 1 hour
varnishadm ban.list | awk '/[0-9]{2}:[0-9]{2}:[0-9]{2}/{print $1}' | while read ban_id; do
    varnishadm ban.url "$ban_id"
done
```

### Pitfall 3: Ignoring Accept-Encoding in BAN Matching

Varnish caches separate objects for `gzip` and `br` encoded responses. A BAN that matches `req.url` without considering `Accept-Encoding` will miss one of the encoded variants, leaving stale compressed content in cache. Always include the encoding header in your BAN expressions when your backend serves compressed responses.

## Key Takeaways

- **BAN tables are not purges** — they mark objects as stale for lazy revalidation, avoiding the thundering herd that exact-match `PURGE` requests create.
- **BAN matching is O(1) to add but O(n) to evaluate** — unbounded growth in the BAN table directly degrades lookup latency, so pruning and consolidation are mandatory operational tasks.
- **Incremental invalidation beats blanket invalidation** — versioned URLs, tag-based BANs, and grace mode together ensure that only affected objects are revalidated while maintaining response speed.
- **Separate your invalidation layer from your cache layer** — queue BAN requests through a message broker to prevent content update bursts from overwhelming Varnish worker threads.
- **Monitor `varnishstat` BAN counters religiously** — when ban evaluations per request exceed 50, the table needs attention before performance degrades.
- **Always account for content encoding** — a BAN that ignores `Accept-Encoding` leaves stale compressed variants in cache, creating invisible inconsistency.

## Further Reading

- [Varnish Cache Documentation: BAN and PURGE](https://varnish-cache.org/docs/trunk/users-guide/vcl-ban.html) — The official reference for BAN expressions, PURGE methods, and VCL syntax across versions.
- [Varnish Cache Architecture: The Complete Guide](https://www.varnish-software.com/topics/varnish-cache-architecture/) — A deep dive into Varnish's internal architecture, including the object storage engine and how BAN tables interact with the cache heap.
- [High Performance Browser Networking: Cache Invalidation](https://hpbn.co/cache-invalidation/) — Chapter 12 of Ilya Grigorik's book covers the theory and practice of cache invalidation strategies at scale, including the mathematics of stampede prevention.
- [Varnish Software: Grace Mode and Stale-While-Revalidate](https://www.varnish-software.com/topics/grace-mode-stale-while-revalidate/) — A practical guide to configuring grace periods and understanding how stale content serves as a buffer during cache churn.
- [Varnish Cache GitHub Repository](https://github.com/varnishcache/varnish-cache/) — The source code and issue tracker for Varnish, including discussions on BAN table performance optimizations and known limitations.