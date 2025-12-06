---
title: "How Batching API Requests Works: Patterns, Protocols, and Practical Implementation"
date: "2025-12-06T17:10:57.04"
draft: false
tags: ["APIs", "Performance", "Backend", "HTTP", "Scalability"]
---

Batching API requests is a proven technique to improve throughput, reduce overhead, and tame the N+1 request problem across web and mobile apps. But batching is more than “combine a few calls into one.” To do it well you need to consider protocol details, error semantics, idempotency, observability, rate limiting, and more.

This article explains how batching works, when to use it, and how to design and implement robust batch endpoints with real code examples.

> TL;DR: Batching reduces per-request overhead by packaging multiple operations into a single request. It’s powerful for chatty networks and high-latency clients (e.g., mobile), but adds complexity around payload limits, error handling, and retries. Implement with clear envelopes, per-operation status, sane limits, idempotency keys, and strong observability.

## Table of contents

- [What is request batching?](#what-is-request-batching)
- [Why batch? Benefits and trade-offs](#why-batch-benefits-and-trade-offs)
- [How batching works at the protocol level](#how-batching-works-at-the-protocol-level)
  - [REST-style JSON envelopes](#rest-style-json-envelopes)
  - [Multipart/mixed batches](#multipartmixed-batches)
  - [JSON-RPC batching](#json-rpc-batching)
  - [GraphQL and gRPC](#graphql-and-grpc)
  - [HTTP/2 and HTTP/3 are not batching](#http2-and-http3-are-not-batching)
- [Designing a batch API](#designing-a-batch-api)
  - [Request and response shape](#request-and-response-shape)
  - [Status codes and partial success](#status-codes-and-partial-success)
  - [Atomicity, ordering, and dependencies](#atomicity-ordering-and-dependencies)
  - [Limits, timeouts, and compression](#limits-timeouts-and-compression)
  - [Security, auth, and validation](#security-auth-and-validation)
- [Client-side batching patterns](#client-side-batching-patterns)
  - [Coalescing windows and flush triggers](#coalescing-windows-and-flush-triggers)
  - [Client batching example (TypeScript)](#client-batching-example-typescript)
- [Server-side implementation patterns](#server-side-implementation-patterns)
  - [Router-style batch executor (Node/Express)](#router-style-batch-executor-nodeexpress)
  - [Write-optimized batching (bulk operations)](#write-optimized-batching-bulk-operations)
- [Error handling, retries, and idempotency](#error-handling-retries-and-idempotency)
- [Performance tips and pitfalls](#performance-tips-and-pitfalls)
- [Rate limiting and observability](#rate-limiting-and-observability)
- [When not to batch](#when-not-to-batch)
- [Conclusion](#conclusion)
- [Resources](#resources)

## What is request batching?

Request batching is the practice of sending multiple API operations in a single network request and receiving a single response that contains the results of all operations. Each operation typically has its own method, path, headers, body, and response status, but the transport overhead (TCP/TLS handshake, headers, request parsing, auth verification, etc.) is paid once per batch rather than once per operation.

Examples:
- A mobile app fetching the profile, settings, and notifications in one call after app launch.
- A frontend collapsing many item detail requests into a single “getMany” call.
- A service collecting multiple writes and committing them as a bulk insert.

## Why batch? Benefits and trade-offs

Benefits:
- Fewer round trips: Cuts latency on high-RTT links (mobile, satellite, cross-region).
- Less overhead: Reduced headers, TLS handshakes, and connection churn.
- Better throughput: Servers can process grouped work more efficiently (bulk DB ops).
- Power-saving: On mobile, fewer radio wakeups can conserve battery.

Trade-offs:
- First-item latency can increase: The earliest operation waits for others to be collected and processed.
- Complexity: Error mapping, retries, idempotency, and limits are trickier.
- Payload size: Larger requests may hit gateway or server limits.
- Caching: Harder for intermediaries to cache composite responses.
- Fairness: Large batches can starve single, latency-sensitive calls if not managed.

> Note: Batching complements, but does not replace, good API design. Sometimes a better resource model (e.g., “/items?ids=…”) removes the need for generic batching.

## How batching works at the protocol level

### REST-style JSON envelopes

A common pattern is a JSON “envelope” where each operation is described by fields like id, method, path, headers, and body. The server returns a list of per-operation results.

Request (JSON):

```json
{
  "operations": [
    {
      "id": "op1",
      "method": "GET",
      "path": "/v1/users/123",
      "headers": { "Accept": "application/json" }
    },
    {
      "id": "op2",
      "method": "POST",
      "path": "/v1/orders",
      "headers": { "Content-Type": "application/json" },
      "body": { "sku": "ABC123", "qty": 1 },
      "idempotencyKey": "order-123-unique-key"
    }
  ],
  "atomic": false,
  "sequential": false
}
```

Response:

```json
{
  "results": [
    {
      "id": "op1",
      "status": 200,
      "headers": { "Content-Type": "application/json" },
      "body": { "id": "123", "name": "Ava" }
    },
    {
      "id": "op2",
      "status": 201,
      "headers": { "Location": "/v1/orders/987" },
      "body": { "id": "987", "state": "created" }
    }
  ],
  "meta": { "durationMs": 28 }
}
```

This style keeps batching transparent: each “virtual” call looks like a normal REST call, just wrapped.

### Multipart/mixed batches

If operations need heterogeneous content types (binary uploads, etc.), multipart/mixed can be used. Each part is a full HTTP-like message.

Example (truncated for brevity):

```http
POST /batch HTTP/1.1
Content-Type: multipart/mixed; boundary=BOUNDARY

--BOUNDARY
Content-Type: application/http; msgtype=request

GET /v1/users/123 HTTP/1.1
Accept: application/json

--BOUNDARY
Content-Type: application/http; msgtype=request

POST /v1/media HTTP/1.1
Content-Type: application/octet-stream

<binary data here>
--BOUNDARY--
```

The response mirrors with application/http parts. This pattern is heavier to implement but flexible.

### JSON-RPC batching

JSON-RPC 2.0 natively supports sending an array of requests:

```json
[
  { "jsonrpc": "2.0", "id": 1, "method": "sum", "params": [1, 2, 3] },
  { "jsonrpc": "2.0", "id": 2, "method": "subtract", "params": { "minuend": 5, "subtrahend": 2 } }
]
```

The server returns an array of responses keyed by id.

### GraphQL and gRPC

- GraphQL: You can often avoid batching by composing one query that fetches everything needed. Some servers also support “persisted queries” and “automatic persisted queries” that reduce overhead. That said, “GraphQL over HTTP” can also support “query batching” (multiple operations per request) depending on your server.
- gRPC: Uses HTTP/2 and supports client-/server-streaming. You can send multiple messages over one stream; that’s not a “batch” in the REST sense, but it amortizes overhead similarly. Some ecosystems build “batch” RPCs with repeated fields for bulk operations.

### HTTP/2 and HTTP/3 are not batching

HTTP/2 multiplexing and HTTP/3 QUIC reduce head-of-line blocking and allow multiple requests in parallel over one connection, but they still incur per-request framing and header processing. Batching can still help by reducing per-request CPU, header bloat, and enabling bulk backends (e.g., one SQL IN query).

## Designing a batch API

### Request and response shape

Key recommendations:
- Include a stable id per operation. This allows result correlation and safe retries.
- Support per-operation headers and bodies.
- Allow hints: atomic (all-or-nothing), sequential (respect order), priority, and timeouts.
- Return per-operation status, headers, and body; include top-level meta.

Example request schema (informal):

```json
{
  "type": "object",
  "properties": {
    "operations": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["id", "method", "path"],
        "properties": {
          "id": { "type": "string" },
          "method": { "type": "string", "enum": ["GET","POST","PUT","PATCH","DELETE"] },
          "path": { "type": "string" },
          "headers": { "type": "object", "additionalProperties": { "type": "string" } },
          "body": {},
          "idempotencyKey": { "type": "string" }
        }
      }
    },
    "atomic": { "type": "boolean", "default": false },
    "sequential": { "type": "boolean", "default": false }
  },
  "required": ["operations"]
}
```

### Status codes and partial success

What should the top-level HTTP status be?

- 200 OK: Batch accepted; per-operation statuses indicate success/failure.
- 207 Multi-Status (RFC 4918): Explicitly signals multiple statuses in the body.
- 400/401/403/413/429/500: Use when the entire batch cannot be processed (validation error, auth failure, payload too large, rate-limited, or server error).

> Tip: Clients should rely on per-operation status for application logic. The top-level status should reflect the fate of the batch envelope itself.

### Atomicity, ordering, and dependencies

- atomic=true: Either all operations succeed, or none are applied. Requires transactional support; otherwise return 501 Not Implemented if unsupported.
- sequential=true: The server executes operations in order. Useful when later operations depend on earlier results.
- Dependencies: You can allow referencing prior results via placeholders (e.g., use `{{results.op1.body.id}}` in a later path). If you support this, validate and sanitize carefully.

### Limits, timeouts, and compression

- Max operations per batch (e.g., 50–100).
- Max body size (e.g., 5–10 MB).
- Max headers per operation (guard against header bloat).
- Server-side coalescing window for internal batching (e.g., up to 5–20 ms) to assemble efficient DB calls.
- Support gzip/br compression for large payloads.
- Timeouts: Provide a clear SLA. Consider returning partial results if not atomic and overall timeout triggers.

### Security, auth, and validation

- AuthN: Inherit the top-level Authorization header; forbid per-operation overrides unless absolutely required.
- AuthZ: Enforce authorization per operation (resource-level checks).
- Validation: Validate the entire envelope and each operation before execution if atomic; or validate per-op in best-effort mode.
- DoS protection: Limit operation counts, reject deeply nested or recursive references, and cap response sizes.
- Auditing: Log each operation with correlation ids.

## Client-side batching patterns

### Coalescing windows and flush triggers

Clients typically buffer operations for a short window (e.g., 5–20 ms) or until a max size is reached, then flush. Triggers:
- Time-based flush (debounce).
- Count-based flush (max N operations).
- Manual flush at lifecycle points (route change, app backgrounding).
- Idle callbacks (`requestIdleCallback`) for non-urgent work.

### Client batching example (TypeScript)

A minimal batcher that groups “virtual” calls and maps results back by id:

```typescript
type Op = {
  id: string;
  method: string;
  path: string;
  headers?: Record<string, string>;
  body?: any;
};

type Result = { id: string; status: number; headers?: Record<string, string>; body?: any };

class BatchClient {
  private queue: { op: Op; resolve: (r: Result) => void; reject: (e: any) => void }[] = [];
  private timer: any = null;

  constructor(
    private baseUrl: string,
    private windowMs = 10,
    private maxOps = 50,
    private fetchImpl: typeof fetch = fetch
  ) {}

  call(op: Omit<Op, "id">): Promise<Result> {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const full: Op = { id, ...op };

    return new Promise<Result>((resolve, reject) => {
      this.queue.push({ op: full, resolve, reject });
      if (this.queue.length >= this.maxOps) {
        this.flush();
      } else if (!this.timer) {
        this.timer = setTimeout(() => this.flush(), this.windowMs);
      }
    });
  }

  private async flush() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    const batch = this.queue.splice(0, this.maxOps);
    if (batch.length === 0) return;

    const body = { operations: batch.map(b => b.op) };

    try {
      const res = await this.fetchImpl(`${this.baseUrl}/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const json = await res.json();
      const byId = new Map<string, Result>(json.results.map((r: Result) => [r.id, r]));
      for (const item of batch) {
        const result = byId.get(item.op.id);
        if (result) {
          item.resolve(result);
        } else {
          item.reject(new Error(`Missing result for ${item.op.id}`));
        }
      }
    } catch (err) {
      for (const item of batch) item.reject(err);
    }
  }
}

// Usage:
const client = new BatchClient("https://api.example.com");
client.call({ method: "GET", path: "/v1/users/123" }).then(console.log);
client.call({ method: "POST", path: "/v1/logs", body: { event: "clicked" } }).then(console.log);
```

## Server-side implementation patterns

### Router-style batch executor (Node/Express)

This example accepts a JSON envelope and dispatches each operation to the internal router. For simplicity we implement handlers inline.

```javascript
// npm i express body-parser
const express = require("express");
const bodyParser = require("body-parser");
const app = express();
app.use(bodyParser.json({ limit: "5mb" }));

// Simple in-memory resources
const users = new Map([["123", { id: "123", name: "Ava" }]]);
const orders = new Map();
let orderSeq = 900;

// Individual handlers (as if they were normal endpoints)
app.get("/v1/users/:id", (req, res) => {
  const u = users.get(req.params.id);
  if (!u) return res.status(404).json({ error: "Not found" });
  res.json(u);
});

app.post("/v1/orders", (req, res) => {
  const id = String(++orderSeq);
  orders.set(id, { id, ...req.body, state: "created" });
  res.status(201).set("Location", `/v1/orders/${id}`).json(orders.get(id));
});

// Batch endpoint
app.post("/batch", async (req, res) => {
  const { operations = [], atomic = false, sequential = false } = req.body || {};
  if (!Array.isArray(operations) || operations.length === 0) {
    return res.status(400).json({ error: "operations required" });
  }
  if (operations.length > 100) {
    return res.status(413).json({ error: "Too many operations" });
  }

  // If atomic, we’ll simulate a transaction by snapshotting state
  const snapshot = atomic ? { orders: new Map(orders) } : null;

  const results = [];
  try {
    if (sequential) {
      for (const op of operations) {
        const r = await executeOp(app, op);
        results.push(r);
        if (atomic && r.status >= 400) throw new Error("Atomic failure");
      }
    } else {
      const r = await Promise.all(operations.map(op => executeOp(app, op)));
      results.push(...r);
      if (atomic && r.some(x => x.status >= 400)) throw new Error("Atomic failure");
    }
  } catch (e) {
    if (atomic && snapshot) {
      // rollback
      orders.clear();
      for (const [k, v] of snapshot.orders.entries()) orders.set(k, v);
    }
    return res.status(207).json({
      results: results.length ? results : operations.map(o => ({ id: o.id, status: 424, body: { error: "Failed due to atomic rollback" } })),
      meta: { atomicRolledBack: true }
    });
  }

  return res.status(207).json({ results, meta: { count: results.length } });
});

// Minimal dispatcher: simulate internal HTTP calls
function executeOp(app, op) {
  return new Promise(resolve => {
    const method = (op.method || "GET").toLowerCase();
    // Create mock req/res
    const req = new express.request.constructor();
    const res = new express.response.constructor();

    req.method = method.toUpperCase();
    req.url = op.path;
    req.headers = op.headers || {};
    req.body = op.body;

    // Intercept response
    let status = 200;
    const headers = {};
    let body;

    res.status = code => { status = code; return res; };
    res.set = (k, v) => { if (typeof k === "string") headers[k] = v; else Object.assign(headers, k); return res; };
    res.json = data => { body = data; finalize(); };
    res.send = data => { body = data; finalize(); };

    function finalize() {
      resolve({ id: op.id, status, headers, body });
    }

    app.handle(req, res);
  });
}

app.listen(3000, () => console.log("Batch API on http://localhost:3000"));
```

Notes:
- This demonstrates per-operation dispatch within one request. In production, you’ll want robust routing, auth checks per op, and proper streaming/limits.
- We return 207 Multi-Status for mixed results.

### Write-optimized batching (bulk operations)

For heavy write paths, bundle multiple creates/updates into one backend call. Example: coalesce writes for 10 ms or until 100 items, then bulk insert. This pattern is common with databases that support bulk operations.

```javascript
// Simple write coalescer for bulk inserts
class BulkInserter {
  constructor({ flushMs = 10, maxItems = 100, insertFn }) {
    this.flushMs = flushMs;
    this.maxItems = maxItems;
    this.insertFn = insertFn;
    this.queue = [];
    this.timer = null;
  }
  add(item) {
    return new Promise((resolve, reject) => {
      this.queue.push({ item, resolve, reject });
      if (this.queue.length >= this.maxItems) return this.flush();
      if (!this.timer) this.timer = setTimeout(() => this.flush(), this.flushMs);
    });
  }
  async flush() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    const batch = this.queue.splice(0, this.maxItems);
    if (!batch.length) return;
    try {
      const items = batch.map(b => b.item);
      const results = await this.insertFn(items); // e.g., INSERT ... VALUES (...), (...), ...
      for (let i = 0; i < batch.length; i++) batch[i].resolve(results[i]);
    } catch (e) {
      for (const b of batch) b.reject(e);
    }
  }
}

// Usage: inside your POST handler
const inserter = new BulkInserter({
  flushMs: 8,
  maxItems: 200,
  insertFn: async (items) => items.map((x, i) => ({ id: Date.now() + i, ...x })) // mock
});

// In Express: app.post("/v1/items", async (req, res) => { const r = await inserter.add(req.body); res.status(201).json(r); });
```

This shifts batching inside the service, even if the public API isn’t explicitly batched.

## Error handling, retries, and idempotency

- Per-operation errors: Include status, error code, and message. Prefer structured errors to free text.
- Top-level vs per-op semantics: A 200/207 can still contain failed operations.
- Retries: Clients may retry the entire batch or individual operations, but beware of duplicates.
- Idempotency: For non-idempotent methods (POST), support idempotency keys per operation so a retry won’t create duplicates.
- Duplicate detection: Store idempotency keys with a short TTL; on duplicate, return the original result.
- Correlation: Include per-operation correlation ids in logs to trace failures.
- Backoff: When receiving 429, observe Retry-After; consider retrying with smaller batches.

Example failed result:

```json
{
  "id": "op7",
  "status": 429,
  "headers": { "Retry-After": "2" },
  "body": { "error": "rate_limited", "message": "Too many requests" }
}
```

## Performance tips and pitfalls

- Tune batch size: Measure p50/p95 latency and server CPU. Diminishing returns often start after 20–50 ops/batch, but it’s workload-dependent.
- Avoid oversized payloads: Large JSON can increase CPU and GC pressure; use compression and reasonable limits.
- Beware HOL inside the batch: One slow operation can delay others. Consider splitting long-running ops into a separate batch or execute in parallel and return partial results (if not atomic).
- Caching: If using generic batch envelopes, CDN caching won’t help. For popular reads, prefer resource-specific “getMany” endpoints (e.g., `/items?ids=...`).
- Network protocol: HTTP/2/3 improve concurrency; batching still reduces header parsing and enables backend coalescing.
- Serialization cost: JSON encoding/decoding for big batches can be expensive. Consider efficient formats (e.g., protobuf) if applicable.

## Rate limiting and observability

- Rate limiting models:
  - Per-batch: Count one batch as one request. Simple, but can be gamed by large batches.
  - Per-operation: Sum operations in the batch. Fairer, but requires batch parsing before enforcement.
  - Hybrid: Charge per batch plus a per-operation cost.
- Metrics:
  - batch.size, batch.bytes, batch.duration_ms
  - op.count, op.status_count{status}
  - op.latency_ms histogram
  - atomic.rollback_count
  - error.rate_limited, error.payload_too_large
- Tracing:
  - One parent span for the batch.
  - Child spans per operation with op.id.
- Logging:
  - Log operation ids and types, not full payloads. Redact PII.

## When not to batch

- Streaming or server-sent events: Use streaming protocols (SSE, WebSocket, gRPC streaming).
- Long-running operations: Prefer asynchronous jobs with callbacks/webhooks or polling.
- Highly cacheable, public GETs: Let CDNs cache individual resources; batching might reduce cache hits.
- Real-time interactivity requiring ultra-low latency per item: Batching’s coalescing delay can hurt.

## Conclusion

Batching API requests is a practical, high-leverage tool to improve efficiency and scalability. Done right, it reduces round trips and CPU overhead, and unlocks bulk backend efficiencies. Done poorly, it introduces opaque errors, retry hazards, and fairness issues.

Design clear envelopes with per-operation ids and statuses, implement sensible limits, support idempotency for safe retries, and invest in observability. Combine batching with sound API design (resource-specific “getMany” endpoints) and modern transports (HTTP/2/3, gRPC) for the best results.

## Resources

- RFC 4918: 207 Multi-Status (WebDAV) — https://www.rfc-editor.org/rfc/rfc4918#section-11.1
- RFC 2046: multipart/mixed — https://www.rfc-editor.org/rfc/rfc2046
- JSON-RPC 2.0 Specification (Batch) — https://www.jsonrpc.org/specification#batch
- GraphQL over HTTP — https://graphql.org/learn/serving-over-http/
- gRPC Concepts (Streaming) — https://grpc.io/docs/what-is-grpc/core-concepts/
- Facebook Graph API Batch Requests — https://developers.facebook.com/docs/graph-api/making-multiple-requests
- Stripe Idempotency Keys — https://stripe.com/docs/idempotency
- Google APIs batch (historical reference) — https://developers.google.com/api-client-library/python/guide/batch (note: some Google REST batch endpoints have been deprecated; check service-specific docs)