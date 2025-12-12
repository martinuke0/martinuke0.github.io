---
title: "System Design: Building a Detailed, Scalable RSS/Atom Feed (With Resource Links)"
date: "2025-12-12T16:45:21.202"
draft: false
tags: ["system design", "RSS", "Atom", "architecture", "WebSub"]
---

## Introduction

RSS and Atom feeds remain foundational for syndicating content across the web—from news and blogs to podcasts and enterprise integrations. Designing a robust feed system isn’t just about outputting XML; it’s about correctness, scale, freshness, discoverability, compatibility, and reliability.

This article walks through a detailed system design for building and operating RSS/Atom feeds. We’ll cover data modeling, HTTP semantics, caching, pagination and archiving, push (WebSub) vs pull, security, observability, and practical implementation snippets. A comprehensive Resources section at the end provides standards, validators, and production-ready libraries.

> Note: This post uses “feed” broadly to mean RSS 2.0 and/or Atom. Where their semantics differ, we call those out explicitly.

## Table of Contents

- What Feeds Are and Why They Still Matter
- Requirements: Functional and Non-Functional
- Data Model and Semantics
- Protocols, Headers, and Discovery
- Architecture Overview
- Feed Generation Strategies
- Pagination and Archiving
- Scale and Caching
- Push vs Pull with WebSub (PubSubHubbub)
- Multitenancy and Security
- Observability and SLOs
- Testing and Validation
- Implementation Examples
- Common Pitfalls and Best Practices
- Conclusion
- Resources

## What Feeds Are and Why They Still Matter

Feeds provide a standardized, machine-readable stream of content entries. They enable:

- Subscribers (apps, readers, aggregators) to fetch updates reliably
- Platform portability and content federation
- Decoupled integration between producers and consumers
- Podcast delivery (via RSS with enclosures)

Despite social and proprietary APIs, feeds remain a low-friction, open standard that supports automation and longevity.

## Requirements: Functional and Non-Functional

### Functional

- Provide at least one of:
  - RSS 2.0 (with Atom namespace for rel links) and/or
  - Atom (RFC 4287)
- Multiple feed keys:
  - Site-wide, per category/tag/author, per collection (e.g., podcast, newsroom)
- Correct metadata:
  - Stable item GUID/ID, title, link, publication/updated dates, author, categories, enclosures (for media)
- Pagination and archival of older items
- Discovery:
  - rel="self" for feed’s canonical URL
  - rel="alternate" in HTML
  - Optional rel="hub" for WebSub
- File size limits (e.g., target < 1–2 MB for first page)
- Validation against standards

### Non-Functional

- Freshness (update lag under X seconds)
- High cache hit ratio (>95% at CDN)
- Low latency (<200 ms from edge)
- Fault tolerance and graceful degradation
- Backwards-compatible changes only
- Observability (metrics, logs, traces)

## Data Model and Semantics

A minimal normalized model supports both RSS and Atom:

- Feed (key, title, description, link, language, image, updated)
- Entry (id/guid, title, permalink, summary, content, published, updated, categories, author, enclosure URL + type + length)
- Relationships: Feed -> Entries (many), per feed key and time order

### Example: RSS 2.0 with Atom link relations

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>Example News</title>
    <link>https://example.com/</link>
    <description>Latest posts from Example</description>
    <language>en</language>
    <lastBuildDate>Fri, 12 Dec 2025 16:45:00 GMT</lastBuildDate>

    <!-- Canonical feed URL -->
    <atom:link rel="self" type="application/rss+xml"
               href="https://example.com/feed.xml"/>

    <!-- Feed pagination -->
    <atom:link rel="next" type="application/rss+xml"
               href="https://example.com/feed.xml?page=2"/>

    <!-- WebSub hub -->
    <atom:link rel="hub" href="https://hub.example.net/"/>

    <item>
      <title>Launch: New Feature</title>
      <link>https://example.com/posts/new-feature</link>
      <guid isPermaLink="false">post:12345</guid>
      <pubDate>Fri, 12 Dec 2025 16:10:00 GMT</pubDate>
      <category>product</category>
      <description><![CDATA[Short summary…]]></description>
      <enclosure url="https://cdn.example.com/audio/ep1.mp3"
                 type="audio/mpeg" length="34567890"/>
    </item>
  </channel>
</rss>
```

> Important: Keep GUID stable for an entry’s lifetime. Changing GUIDs causes duplicate entries in readers.

### Example: Atom

```xml
<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xml:lang="en">
  <title>Example News</title>
  <link rel="alternate" href="https://example.com/"/>
  <link rel="self" type="application/atom+xml" href="https://example.com/atom.xml"/>
  <link rel="next" type="application/atom+xml" href="https://example.com/atom.xml?page=2"/>
  <link rel="hub" href="https://hub.example.net/"/>
  <updated>2025-12-12T16:45:00Z</updated>
  <id>tag:example.com,2025:/feed</id>

  <entry>
    <title>Launch: New Feature</title>
    <link rel="alternate" href="https://example.com/posts/new-feature"/>
    <id>tag:example.com,2025:/posts/new-feature</id>
    <updated>2025-12-12T16:10:00Z</updated>
    <published>2025-12-12T16:10:00Z</published>
    <category term="product"/>
    <summary type="html"><![CDATA[Short summary…]]></summary>
    <content type="html"><![CDATA[Full content…]]></content>
    <author><name>Example Author</name></author>
  </entry>
</feed>
```

## Protocols, Headers, and Discovery

Your feed endpoints should be HTTP/HTTPS with strong cache semantics:

- Content Types:
  - application/rss+xml for RSS
  - application/atom+xml for Atom
- Caching:
  - ETag and Last-Modified
  - Cache-Control: public, max-age=..., stale-while-revalidate=...
  - Conditional GETs (If-None-Match / If-Modified-Since) to save bandwidth
- Compression:
  - gzip/br at the edge

```http
HTTP/1.1 200 OK
Content-Type: application/rss+xml; charset=utf-8
ETag: "feed:home:v5:7b1b7c6"
Last-Modified: Fri, 12 Dec 2025 16:45:00 GMT
Cache-Control: public, max-age=300, stale-while-revalidate=600
Content-Encoding: br
```

### Discovery

- In HTML pages, add:
  ```html
  <link rel="alternate" type="application/rss+xml" title="Example News" href="https://example.com/feed.xml">
  <link rel="alternate" type="application/atom+xml" title="Example News" href="https://example.com/atom.xml">
  ```
- In feeds, include atom:link rel="self" and optionally rel="hub" and rel="next".

> Prefer a canonical feed URL that rarely changes; if it must change, use 301 redirects and preserve GUIDs.

## Architecture Overview

A scalable feed system typically includes:

- Content store: database where posts/media live (e.g., Postgres)
- Event stream: on create/update/publish (e.g., Kafka)
- Feed generator: builds feed snapshots per key
- Snapshot store: object storage (e.g., S3) for XML blobs and archives
- Edge cache/CDN: CloudFront/Fastly/Cloudflare for distribution
- Push notifier: WebSub hub publisher
- Metadata cache: Redis for sorted sets (per-feed entries by publish time)
- Control plane: configuration, feature flags, feed templates
- Observability: logs, metrics, tracing

Data flow:
1) Content write -> event emitted
2) Feed generator updates sorted sets and rebuilds affected feeds
3) Upload new feed snapshot(s) to storage; invalidate CDN or bump ETag
4) Publish to WebSub hub(s); consumers receive updates
5) Observability records freshness, latency, errors

## Feed Generation Strategies

Two common strategies:

- Fan-out on write: Precompute and store feed snapshots whenever new content arrives. Best for high read/low write workloads.
- Fan-out on read: Build feeds on demand when requested. Simple but can be expensive at scale; cache aggressively.

Hybrid approach:
- Precompute hot feeds (e.g., home, popular categories)
- On-demand build for low-traffic feeds with short in-memory caching

### Data structures

- Redis sorted set per feed key:
  - Key: feed:{key}
  - Member: entry_id
  - Score: publish_timestamp
- For pagination, store descending order; keep top N in memory.

### Pseudocode: generator

```python
# Python-like pseudocode
from datetime import datetime
from hashlib import sha256

def build_feed_xml(entries, feed_meta, fmt="rss"):
    # Use a template/serializer; omitted for brevity
    return render_xml(entries, feed_meta, fmt)

def compute_etag(xml_bytes, version_hint="v1"):
    h = sha256(xml_bytes).hexdigest()[:16]
    return f'"feed:{version_hint}:{h}"'

def generate_snapshot(feed_key, page=1, page_size=50, fmt="rss"):
    entry_ids = redis.zrevrange(f"feed:{feed_key}", (page-1)*page_size, page*page_size - 1)
    entries = db.fetch_entries(entry_ids)  # preserve order by zset score
    feed_meta = db.fetch_feed_meta(feed_key)
    xml = build_feed_xml(entries, feed_meta, fmt)
    etag = compute_etag(xml)
    last_mod = datetime.utcnow()
    path = f"{feed_key}/{fmt}/page/{page}.xml"
    objstore.put(path, xml, content_type=f"application/{fmt}+xml",
                 metadata={"ETag": etag, "Last-Modified": last_mod.isoformat()})
    cdn.purge(f"/{path}")  # or cache-busting via new ETag
    return {"path": path, "etag": etag, "last_modified": last_mod}
```

> Keep feed generation idempotent and deterministic for the same input set.

## Pagination and Archiving

- For Atom, consider RFC 5005: Feed Paging and Archiving. Use rel="next", rel="prev-archive", and archives to allow clients to navigate history.
- For RSS, mimic with next/prev via atom:link relations and stable page URLs (e.g., feed.xml?page=2).
- Page size: 20–100 items; smaller for media-heavy feeds.
- Archive older pages to object storage; avoid regenerating static history.

```xml
<atom:link rel="next" type="application/rss+xml" href="https://example.com/feed.xml?page=2"/>
```

> Ensure item order is stable (typically newest first). Never re-order older items; readers rely on monotonic feeds.

## Scale and Caching

- Edge cache:
  - Cache-Control and ETag for conditional GETs
  - Shielding and origin coalescing to prevent thundering herds
- Snapshot store + CDN:
  - Serve feeds as static objects; rebuild and atomically replace
- TTL strategy:
  - Lower TTL for first page (e.g., 1–5 minutes)
  - Higher TTL for older pages (e.g., hours); they rarely change
- Warm-up:
  - Prefetch after deploy or after rebuild to prime edge caches

### Example: Express.js server headers

```javascript
import express from "express";
import fs from "node:fs/promises";

const app = express();

app.get("/feed.xml", async (req, res) => {
  const obj = await fs.readFile("./snapshots/home/rss/page/1.xml");
  // In production, read metadata from object store
  res.set({
    "Content-Type": "application/rss+xml; charset=utf-8",
    "Cache-Control": "public, max-age=300, stale-while-revalidate=600",
    ETag: '"feed:v5:7b1b7c6"',
    "Last-Modified": new Date().toUTCString(),
  });
  if (req.headers["if-none-match"] === '"feed:v5:7b1b7c6"') {
    return res.status(304).end();
  }
  res.send(obj);
});

app.listen(3000);
```

## Push vs Pull with WebSub (PubSubHubbub)

WebSub allows near-real-time updates:

- Producer includes rel="hub" and rel="self" in the feed
- On updates, producer POSTs to hub with the topic (feed URL)
- Subscribers register with hub for callbacks

### Publish to hub

```bash
curl -X POST https://hub.example.net/ \
  -d "hub.mode=publish" \
  -d "hub.url=https://example.com/feed.xml"
```

> Use reputable hubs (self-hosted or services). Include HMAC signatures for subscriber verification if supported.

## Multitenancy and Security

- Private feeds:
  - Signed URLs (e.g., feed.xml?token=... with HMAC and TTL) or HTTP Basic over HTTPS
  - Return 401/403 for invalid/expired tokens
  - Set X-Robots-Tag: noindex
- Input sanitization:
  - Escape XML; sanitize HTML content (allowlists)
  - Enforce UTF-8; avoid malformed entities
- Abuse and rate limits:
  - 429 Too Many Requests with Retry-After
  - IP-based and token-based rate limiting
- Transport:
  - Force HTTPS; enable HSTS
- Size limits:
  - Hard cap feed payload (e.g., 2 MB); trim content or reduce items

## Observability and SLOs

Track:

- Freshness lag: now - latest item published time in feed
- Feed generation latency and error rate
- Cache hit ratio at edge
- Response size distribution and compression ratio
- 304 vs 200 ratio (conditional GET effectiveness)
- WebSub publish success/failure
- Validation failures

SLO examples:
- P99 feed edge latency < 200 ms
- P99 freshness lag < 60 s for home feed
- CDN cache hit ratio > 95%

## Testing and Validation

- Unit tests for serializers (RSS/Atom) with golden files
- Integration tests using a feed parser to assert round-trip
- Schema/validator checks in CI
- Backwards-compat regression tests for GUIDs and link relations

### Example: Python test with feedparser

```python
import feedparser

def test_feed_valid():
    d = feedparser.parse("http://localhost:3000/feed.xml")
    assert d.bozo == 0  # no parse errors
    assert d.feed.title == "Example News"
    assert len(d.entries) <= 50
    assert all(e.id for e in d.entries)
```

## Implementation Examples

### Python: generate RSS with feedgen

```python
# pip install feedgen
from feedgen.feed import FeedGenerator
from datetime import datetime, timezone

fg = FeedGenerator()
fg.title('Example News')
fg.link(href='https://example.com/', rel='alternate')
fg.id('tag:example.com,2025:/feed')
fg.load_extension('atom')
fg.link(href='https://example.com/feed.xml', rel='self', type='application/rss+xml')
fg.link(href='https://hub.example.net/', rel='hub')
fg.language('en')

for item in entries:  # entries from your DB
    fe = fg.add_entry()
    fe.id(item['guid'])
    fe.title(item['title'])
    fe.link(href=item['link'])
    fe.published(item['published'].replace(tzinfo=timezone.utc))
    fe.updated(item['updated'].replace(tzinfo=timezone.utc))
    fe.summary(item['summary'], type='html')
    if item.get('enclosure'):
        fe.enclosure(item['enclosure']['url'],
                     str(item['enclosure']['length']),
                     item['enclosure']['type'])

rss_bytes = fg.rss_str(pretty=True)
with open('feed.xml', 'wb') as f:
    f.write(rss_bytes)
```

### Go: minimal feed with gofeed and custom XML

```go
// go get github.com/gorilla/feeds
package main

import (
  "github.com/gorilla/feeds"
  "net/http"
  "time"
)

func feedHandler(w http.ResponseWriter, r *http.Request) {
  now := time.Now()
  feed := &feeds.Feed{
    Title: "Example News",
    Link:  &feeds.Link{Href: "https://example.com/"},
    Description: "Latest posts",
    Updated: now,
  }
  feed.Items = []*feeds.Item{
    {Title: "Launch", Link: &feeds.Link{Href: "https://example.com/posts/new-feature"},
     Id: "post:12345", Created: now.Add(-time.Hour)},
  }
  rss, _ := feed.ToRss()
  w.Header().Set("Content-Type", "application/rss+xml; charset=utf-8")
  w.Header().Set("Cache-Control", "public, max-age=300, stale-while-revalidate=600")
  w.Write([]byte(rss))
}

func main() {
  http.HandleFunc("/feed.xml", feedHandler)
  http.ListenAndServe(":8080", nil)
}
```

### Node: publish to WebSub hub on update

```javascript
import fetch from "node-fetch";

async function publishToHub(feedUrl, hubUrl) {
  const params = new URLSearchParams();
  params.set("hub.mode", "publish");
  params.set("hub.url", feedUrl);

  const res = await fetch(hubUrl, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: params.toString()
  });
  if (!res.ok) {
    throw new Error(`Hub publish failed: ${res.status}`);
  }
}
```

## Common Pitfalls and Best Practices

- Do not change GUID/ID for existing entries
- Always include rel="self"; consumers use it for caching and identity
- Use UTC for dates; RSS requires RFC 822 date format
- Keep feeds small; include summaries, not full HTML, unless necessary
- Escape XML and sanitize HTML; wrap HTML in CDATA when appropriate
- Provide both RSS and Atom if your audience is broad; otherwise pick one and implement it well
- Add atom:link rel="next" for pagination; archive static pages
- Validate feeds regularly and in CI
- Serve over HTTPS; add HSTS; set correct content type
- Handle conditional requests to reduce bandwidth (304 Not Modified)
- For podcasts, include proper enclosure metadata and consider iTunes-specific namespaces

## Conclusion

Designing a feed system is as much about operational rigor as it is about XML. By modeling entries cleanly, adhering to standards (RSS/Atom), using correct HTTP semantics, and layering caching and push notifications, you can deliver fast, reliable syndication at scale. Add robust observability and validation to keep quality high, and avoid breaking changes that would disrupt subscribers. With the patterns and examples above, you can confidently build and evolve a production-grade feed pipeline.

## Resources

Standards and specifications:
- RSS 2.0 Specification: https://www.rssboard.org/rss-specification
- Atom Syndication Format (RFC 4287): https://www.rfc-editor.org/rfc/rfc4287
- WebSub (W3C Recommendation): https://www.w3.org/TR/websub/
- Feed Paging and Archiving (RFC 5005): https://www.rfc-editor.org/rfc/rfc5005
- HTTP Caching (RFC 9111): https://www.rfc-editor.org/rfc/rfc9111
- Conditional Requests (RFC 9110, Sections 13–15): https://www.rfc-editor.org/rfc/rfc9110

Validation and tools:
- W3C Feed Validation Service: https://validator.w3.org/feed/
- Feed Validator (alternate): https://www.feedvalidator.org/
- feedparser (Python): https://github.com/kurtmckee/feedparser

Libraries:
- Python feedgen: https://github.com/lkiesow/python-feedgen
- Node rss: https://github.com/dylang/node-rss
- Go gorilla/feeds: https://github.com/gorilla/feeds
- Go gofeed (parser): https://github.com/mmcdole/gofeed

Guides and references:
- RSS Advisory Board: https://www.rssboard.org/
- Google’s WebSub docs (legacy PubSubHubbub): https://pubsubhubbub.appspot.com/
- Cloudflare Caching Basics: https://developers.cloudflare.com/cache/about/
- Fastly Caching: https://docs.fastly.com/en/guides/cache-control-tutorial

Security and HTML sanitization:
- OWASP XSS Prevention Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Cross_Site_Scripting_Prevention_Cheat_Sheet.html
- OWASP HTML Sanitization: https://owasp.org/www-community/attacks/HTML5_Security_Cheat_Sheet

Operational tips:
- AWS S3 + CloudFront best practices: https://docs.aws.amazon.com/AmazonCloudFront/latest/DeveloperGuide/Introduction.html
- Retry-After header semantics: https://www.rfc-editor.org/rfc/rfc9110#name-retry-after

> Bookmark this page for quick access to specs, validators, and libraries while you implement or audit your feed system.