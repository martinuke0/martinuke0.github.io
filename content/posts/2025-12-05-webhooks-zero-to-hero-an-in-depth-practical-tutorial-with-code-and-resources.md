---
title: "Webhooks Zero to Hero: An In-Depth, Practical Tutorial with Code and Resources"
date: "2025-12-05T01:49:00+02:00"
draft: false
tags: ["Webhooks", "API", "Integration", "Security", "Event-Driven", "Backend"]
---

## Introduction

Webhooks are the backbone of modern, event-driven integrations. Instead of continuously polling an API to ask “has anything changed yet?”, webhooks let services push events to your application as soon as they happen: a payment succeeds, a repository receives a push, a customer updates their profile, or a ticket is assigned.

This in-depth tutorial will take you from zero to hero. You’ll learn:

- What webhooks are and how they compare to polling and WebSockets
- How to build robust webhook receivers in multiple languages
- Signature verification, replay protection, and other security best practices
- Idempotency and reliable processing with retries and dead-letter queues
- How to test locally using tunnels and inspector tools
- How to design and operate your own webhook provider at scale
- Links to the best official docs and tools in the ecosystem

If you’re implementing webhooks for the first time or trying to harden your production setup, this guide will meet you where you are and help you ship with confidence.

---

## Table of Contents

- [What Are Webhooks?](#what-are-webhooks)
- [Key Concepts and Terminology](#key-concepts-and-terminology)
- [End-to-End Flow (Mental Model)](#end-to-end-flow-mental-model)
- [Quickstart: Build a Webhook Receiver](#quickstart-build-a-webhook-receiver)
  - [A minimal Node.js/Express receiver](#a-minimal-nodejsexpress-receiver)
  - [Testing with curl](#testing-with-curl)
  - [Expose your local server with a tunnel](#expose-your-local-server-with-a-tunnel)
- [Verify Signatures and Prevent Replays](#verify-signatures-and-prevent-replays)
  - [Generic HMAC verification (Node.js)](#generic-hmac-verification-nodejs)
  - [Provider-specific examples (Stripe, GitHub, Slack, Shopify, Twilio)](#provider-specific-examples-stripe-github-slack-shopify-twilio)
  - [Python and Go verification examples](#python-and-go-verification-examples)
- [Respond Fast, Process Async](#respond-fast-process-async)
  - [Idempotency and deduplication](#idempotency-and-deduplication)
  - [Retries, timeouts, and backoff](#retries-timeouts-and-backoff)
- [Security Hardening](#security-hardening)
- [Designing Your Own Webhook Provider](#designing-your-own-webhook-provider)
  - [Event schema and documentation](#event-schema-and-documentation)
  - [Delivery policy and headers](#delivery-policy-and-headers)
- [Operating at Scale](#operating-at-scale)
- [Language Cookbook: Receivers in Python, Go, Ruby, PHP](#language-cookbook-receivers-in-python-go-ruby-php)
- [Troubleshooting Checklist](#troubleshooting-checklist)
- [Conclusion](#conclusion)
- [Resources](#resources)

---

## What Are Webhooks?

A webhook is an HTTP callback. When an event occurs in a provider system (e.g., “invoice.paid”), the provider sends an HTTP request—usually a POST with JSON—to a URL you own (“your webhook endpoint”). You process the event and respond with a 2xx status to acknowledge receipt.

How webhooks compare to alternatives:

- Polling: Your app asks periodically for changes. Simple but wasteful, can be stale.
- Webhooks: Provider pushes events to your server. Efficient, near real-time.
- WebSockets/Streams: Persistent, bidirectional channel. Great for live data but heavier infra and state considerations.

> Tip: Many platforms combine approaches: accept webhooks for event triggers and provide APIs to fetch full resource details as needed.

---

## Key Concepts and Terminology

- Producer/Provider: The system sending webhooks (e.g., Stripe, GitHub, your SaaS).
- Consumer/Receiver: Your application endpoint handling events.
- Event: The payload describing what happened (type + data + metadata).
- Secret/Signature: The cryptographic token/signature to verify authenticity.
- Idempotency: Ensuring repeated deliveries don’t cause duplicate effects.
- Retry Policy: Provider’s strategy for re-sending failed deliveries.
- Dead-Letter Queue (DLQ): Where persistent failures go for later inspection.

---

## End-to-End Flow (Mental Model)

1. Provider emits event and sends HTTP POST to your endpoint with:
   - Headers (signature, timestamp, attempt count)
   - Body (JSON payload with id, type, data)
2. Your endpoint:
   - Verifies signature and timestamp
   - Checks idempotency (has this event already been processed?)
   - Enqueues work for async processing
   - Returns 2xx quickly
3. Background worker:
   - Processes the job (write to DB, call internal APIs)
   - Handles retries and sends alerts on failures
4. Observability:
   - Logs, metrics, traces show delivery success/failure, latency, and error rates

---

## Quickstart: Build a Webhook Receiver

### A minimal Node.js/Express receiver

Install dependencies:

```bash
npm init -y
npm i express
```

server.js:

```javascript
// server.js
const express = require('express');
const app = express();
const PORT = process.env.PORT || 3000;

// We need the raw body for signature verification; capture it.
app.use(express.json({
  type: '*/*',
  verify: (req, res, buf) => {
    req.rawBody = buf; // Keep raw buffer for HMAC verification
  }
}));

app.post('/webhooks/provider', (req, res) => {
  // In production: verify signature, timestamp, and idempotency (see below)
  const event = req.body;
  console.log('Received event:', event?.id, event?.type);

  // Acknowledge quickly
  res.status(200).send('ok');

  // Process asynchronously (queue/job runner pattern recommended)
  // doWork(event).catch(err => console.error(err));
});

app.get('/', (_, res) => res.send('Webhook receiver running'));
app.listen(PORT, () => console.log(`Listening on http://localhost:${PORT}`));
```

Run it:

```bash
node server.js
```

### Testing with curl

```bash
curl -X POST http://localhost:3000/webhooks/provider \
  -H 'Content-Type: application/json' \
  -d '{"id":"evt_123","type":"invoice.paid","data":{"invoice_id":"inv_789"}}'
```

### Expose your local server with a tunnel

To receive events from external providers during development, expose your local server:

- ngrok: secure tunnels and request inspector
- Cloudflare Tunnel (cloudflared)
- Localtunnel, smee.io

Example (ngrok):

```bash
ngrok http 3000
```

Copy the https URL from ngrok to configure your provider’s webhook endpoint.

> Note: Use a stable subdomain for fewer reconfigurations. ngrok and others offer reserved domains on paid plans.

---

## Verify Signatures and Prevent Replays

Signature verification proves the request really came from the provider and wasn’t tampered with. Replay protection prevents an attacker from re-sending a captured request.

The common pattern:

- Provider sends a timestamp and signature header.
- Compute HMAC over the raw request body (often prefixed with timestamp).
- Compare your computed signature with the header using a timing-safe comparison.
- Ensure the timestamp is fresh (e.g., within 5 minutes).

### Generic HMAC verification (Node.js)

```javascript
// hmac-verify.js
const crypto = require('crypto');

function timingSafeEqual(a, b) {
  const abuf = Buffer.from(a);
  const bbuf = Buffer.from(b);
  if (abuf.length !== bbuf.length) return false;
  return crypto.timingSafeEqual(abuf, bbuf);
}

function verifySignature({ rawBody, secret, signatureHeader, timestampHeader }) {
  const timestamp = timestampHeader; // e.g., '1733423456'
  const payload = `${timestamp}.${rawBody}`;
  const expected = 'sha256=' + crypto.createHmac('sha256', secret).update(payload).digest('hex');
  return timingSafeEqual(expected, signatureHeader);
}

module.exports = { verifySignature };
```

Integrate into Express:

```javascript
const { verifySignature } = require('./hmac-verify');

app.post('/webhooks/provider', (req, res) => {
  const sig = req.get('X-Signature');
  const ts = req.get('X-Timestamp');
  const secret = process.env.WEBHOOK_SECRET;

  // Basic replay window check
  const age = Math.abs(Date.now()/1000 - Number(ts || 0));
  if (!ts || age > 300) return res.status(401).send('stale');

  if (!verifySignature({ rawBody: req.rawBody, secret, signatureHeader: sig, timestampHeader: ts })) {
    return res.status(401).send('invalid signature');
  }

  const event = req.body;
  // ack fast
  res.sendStatus(200);
  // enqueue for processing...
});
```

> Important: Signature verification almost always requires the raw request body buffer. JSON re-serialization can change whitespace/order and break signatures.

### Provider-specific examples (Stripe, GitHub, Slack, Shopify, Twilio)

Each provider documents its own scheme and headers:

- Stripe: Stripe-Signature header; SDK helper recommended.
- GitHub: X-Hub-Signature-256 HMAC SHA-256.
- Slack: X-Slack-Signature with versioned base string and X-Slack-Request-Timestamp.
- Shopify: X-Shopify-Hmac-Sha256 HMAC SHA-256 (base64).
- Twilio: X-Twilio-Signature with URL + params signing.

Stripe (Node.js):

```javascript
const express = require('express');
const stripe = require('stripe')(process.env.STRIPE_SECRET_KEY);
const app = express();

// Keep raw body
app.post('/webhooks/stripe', express.raw({ type: 'application/json' }), (req, res) => {
  const sig = req.headers['stripe-signature'];
  try {
    const event = stripe.webhooks.constructEvent(req.body, sig, process.env.STRIPE_WEBHOOK_SECRET);
    res.sendStatus(200);
    // process event asynchronously...
  } catch (err) {
    console.error('Stripe signature verification failed:', err.message);
    res.sendStatus(400);
  }
});
```

Official docs:
- Stripe: https://stripe.com/docs/webhooks/signatures
- GitHub: https://docs.github.com/webhooks-and-events/webhooks/securing-your-webhooks
- Slack: https://api.slack.com/authentication/verifying-requests-from-slack
- Shopify: https://shopify.dev/docs/apps/build/webhooks/secure
- Twilio: https://www.twilio.com/docs/usage/webhooks/webhooks-security

### Python and Go verification examples

Python (Flask, generic HMAC):

```python
# app.py
import hmac, hashlib, time
from flask import Flask, request, abort

app = Flask(__name__)
WEBHOOK_SECRET = b'supersecret'

def safe_equals(a: bytes, b: bytes) -> bool:
    return hmac.compare_digest(a, b)

@app.route('/webhooks/provider', methods=['POST'])
def webhook():
    raw = request.get_data()
    ts = request.headers.get('X-Timestamp')
    sig = request.headers.get('X-Signature', '')
    if not ts or not sig:
        abort(401)

    # replay check
    if abs(time.time() - int(ts)) > 300:
        abort(401)

    expected = 'sha256=' + hmac.new(WEBHOOK_SECRET, f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
    if not safe_equals(expected.encode(), sig.encode()):
        abort(401)

    # ack
    return ('ok', 200)
```

Go (net/http):

```go
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"fmt"
	"io"
	"log"
	"net/http"
	"strconv"
	"time"
)

var secret = []byte("supersecret")

func verify(ts, sig string, body []byte) bool {
	msg := []byte(ts + "." + string(body))
	mac := hmac.New(sha256.New, secret)
	mac.Write(msg)
	expected := fmt.Sprintf("sha256=%x", mac.Sum(nil))
	return subtle.ConstantTimeCompare([]byte(expected), []byte(sig)) == 1
}

func handler(w http.ResponseWriter, r *http.Request) {
	body, _ := io.ReadAll(r.Body)
	defer r.Body.Close()

	ts := r.Header.Get("X-Timestamp")
	sig := r.Header.Get("X-Signature")

	// replay window
	t, err := strconv.ParseInt(ts, 10, 64)
	if err != nil || time.Since(time.Unix(t, 0)) > 5*time.Minute {
		http.Error(w, "stale", http.StatusUnauthorized)
		return
	}

	if !verify(ts, sig, body) {
		http.Error(w, "invalid signature", http.StatusUnauthorized)
		return
	}

	w.WriteHeader(http.StatusOK)
	w.Write([]byte("ok"))
}

func main() {
	http.HandleFunc("/webhooks/provider", handler)
	log.Println("Listening on :8080")
	http.ListenAndServe(":8080", nil)
}
```

---

## Respond Fast, Process Async

Webhook providers typically expect a quick 2xx response—often within a few seconds. Don’t do heavy work in the HTTP handler. Instead:

1. Verify/acknowledge quickly.
2. Enqueue the event to a background worker.
3. Process in the background with retries.

Node.js with BullMQ (Redis):

```javascript
// queue.js
const { Queue, Worker } = require('bullmq');
const queue = new Queue('webhooks', { connection: { host: 'localhost', port: 6379 } });

async function enqueue(event) {
  await queue.add(event.id || 'event', event, { attempts: 5, backoff: { type: 'exponential', delay: 2000 } });
}

new Worker('webhooks', async job => {
  // process event
  // e.g., write to DB, call internal APIs
}, { connection: { host: 'localhost', port: 6379 } });

module.exports = { enqueue };
```

In your handler:

```javascript
app.post('/webhooks/provider', (req, res) => {
  // ... verify signature
  res.sendStatus(200);
  enqueue(req.body).catch(console.error);
});
```

### Idempotency and deduplication

Because providers deliver at-least-once, duplicates happen. Use a unique event ID to ensure idempotent processing.

SQL with unique constraint:

```sql
CREATE TABLE webhook_events (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  payload JSONB NOT NULL,
  received_at TIMESTAMPTZ DEFAULT now(),
  processed_at TIMESTAMPTZ
);
```

Upsert pattern:

```sql
INSERT INTO webhook_events (id, type, payload)
VALUES ($1, $2, $3)
ON CONFLICT (id) DO NOTHING;
```

Or use Redis SETNX on key event:{id} to short-circuit duplicates.

> Note: If a webhook triggers downstream state (e.g., create an order), ensure the downstream operations are also idempotent (e.g., by referencing the event id or an idempotency key).

### Retries, timeouts, and backoff

- Return 2xx only when you have durably accepted the event (e.g., persisted/enqueued).
- Common provider retry schedule: exponential backoff with jitter (e.g., 1m, 2m, 4m, 10m, 1h).
- Timeouts: Keep handlers lean; providers often enforce 5–30s timeouts.
- Status codes:
  - 2xx: Success; no retry needed
  - 4xx: Client/config error. Some providers stop retrying on certain 4xx (e.g., 410 Gone to unsubscribe)
  - 5xx: Server error; provider will retry

---

## Security Hardening

- Signature verification and replay protection
- Secrets management and rotation
  - Rotate webhook secrets periodically; keep previous secret active during rotation window
- Mutual TLS (mTLS) for high-sensitivity integrations
- IP allowlisting
  - Useful but not sufficient; IPs can change. Always keep signature checks.
- HTTPS only (TLS 1.2+)
- Input validation and size limits
  - Enforce Content-Type, max body size, and timeouts
- Avoid SSRF and amplification
  - If the webhook includes a URL to fetch, validate domain and use allowlists
- PII minimization and encryption at rest
- Observability
  - Correlation IDs, request logging with headers and event ids (redact secrets)
- Replay window
  - Enforce strict timestamp window and nonce/once-only tokens where supported

---

## Designing Your Own Webhook Provider

If you’re building a platform that sends webhooks, design them like a product: predictable, secure, and well-documented.

### Event schema and documentation

- Stable event envelope:
  - id (string, unique)
  - type (string, e.g., order.created)
  - created_at (RFC 3339 timestamp)
  - data (object)
  - version (for schema evolution)
- Consider AsyncAPI or JSON Schema for documentation.

Example JSON schema (fragment):

```json
{
  "$id": "https://api.example.com/schemas/webhook-event.json",
  "type": "object",
  "required": ["id", "type", "created_at", "data", "version"],
  "properties": {
    "id": { "type": "string" },
    "type": { "type": "string" },
    "created_at": { "type": "string", "format": "date-time" },
    "version": { "type": "string" },
    "data": { "type": "object" }
  }
}
```

AsyncAPI snippet:

```yaml
asyncapi: '2.6.0'
info:
  title: Example Webhooks
  version: '1.0.0'
webhooks:
  orderCreated:
    post:
      summary: Order created event
      operationId: orderCreated
      message:
        name: order.created
        payload:
          type: object
          properties:
            id:
              type: string
            type:
              type: string
              enum: [order.created]
            data:
              type: object
              properties:
                order_id:
                  type: string
```

### Delivery policy and headers

- Headers:
  - X-Event-Id
  - X-Event-Type
  - X-Event-Created-At
  - X-Attempt: delivery attempt number
  - X-Timestamp: unix seconds
  - X-Signature: sha256=...
- Signature: HMAC-SHA256 over `${timestamp}.${rawBody}`
- Retries: Exponential backoff with jitter; stop after N attempts; 410 Gone stops immediately
- Rate limiting: Per endpoint or per tenant
- Replay protection: Timestamp + optional nonce
- Test UI/CLI: Let users trigger re-delivery and view event logs
- Large payloads: Consider including a minimal payload plus a signed URL to fetch full data (short-lived token)

> Provide a self-serve “Test send” and a delivery log viewer. This reduces support load and increases developer happiness.

---

## Operating at Scale

- Concurrency control
  - Process events per tenant with partition keys to avoid reordering when order matters
- Ordering
  - Document ordering guarantees (usually none); provide sequence numbers per resource if needed
- Dead-letter queues
  - Route permanently failing deliveries to DLQ (e.g., SQS DLQ, Kafka topic) for analysis
- Metrics
  - Delivery success rate, P99 latency, retry counts, DLQ volume
- Alerting
  - Alert on spikes in 5xx, increased latency, or consecutive failures to a given endpoint
- Backpressure
  - Circuit-breaker on endpoints repeatedly failing to avoid thundering herds
- Multi-region
  - If relevant, sign per region; keep clocks synchronized (NTP) for timestamp windows

---

## Language Cookbook: Receivers in Python, Go, Ruby, PHP

Python (FastAPI):

```python
from fastapi import FastAPI, Request, HTTPException
import hmac, hashlib, time

app = FastAPI()
SECRET = b'supersecret'

@app.post("/webhooks/provider")
async def receive(request: Request):
  raw = await request.body()
  ts = request.headers.get('x-timestamp')
  sig = request.headers.get('x-signature')
  if not ts or not sig:
    raise HTTPException(401, "missing headers")
  if abs(time.time() - int(ts)) > 300:
    raise HTTPException(401, "stale")

  expected = 'sha256=' + hmac.new(SECRET, f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
  if not hmac.compare_digest(expected, sig):
    raise HTTPException(401, "invalid signature")
  return {"ok": True}
```

Go (chi):

```go
r.Post("/webhooks/provider", handler) // same as net/http example above
```

Ruby (Sinatra):

```ruby
require 'sinatra'
require 'openssl'

SECRET = 'supersecret'

post '/webhooks/provider' do
  raw = request.body.read
  ts = request.env['HTTP_X_TIMESTAMP']
  sig = request.env['HTTP_X_SIGNATURE']
  halt 401 unless ts && sig

  expected = 'sha256=' + OpenSSL::HMAC.hexdigest('SHA256', SECRET, "#{ts}.#{raw}")
  halt 401 unless Rack::Utils.secure_compare(expected, sig)
  status 200
  body 'ok'
end
```

PHP (Laravel route + middleware idea):

```php
// routes/api.php
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Route;

Route::post('/webhooks/provider', function (Request $request) {
    // signature verification middleware recommended
    // quick ack
    return response('ok', 200);
});
```

Plain PHP verification:

```php
<?php
$secret = 'supersecret';
$raw = file_get_contents('php://input');
$ts = $_SERVER['HTTP_X_TIMESTAMP'] ?? null;
$sig = $_SERVER['HTTP_X_SIGNATURE'] ?? null;

if (!$ts || !$sig) {
  http_response_code(401); exit('missing headers');
}

$expected = 'sha256=' . hash_hmac('sha256', $ts . '.' . $raw, $secret);
if (!hash_equals($expected, $sig)) {
  http_response_code(401); exit('invalid signature');
}

http_response_code(200);
echo 'ok';
```

---

## Troubleshooting Checklist

- Receiving 4xx from your endpoint:
  - Check Content-Type and body parsing; ensure raw body is available for signature verification
  - Confirm secrets and header names match provider docs
  - Ensure your server responds within provider timeout
- Duplicate events:
  - Implement idempotency with event IDs and unique constraints
- Missing events:
  - Verify tunnel is running and URL is correct
  - Check provider’s delivery logs and whether retries exhausted
- Signature mismatch:
  - Confirm you are using the exact raw body
  - Check timestamp usage and formatting
  - Ensure you’re using the right secret and hashing algorithm
- Large or partial payloads:
  - Inspect provider docs for pagination or follow-up fetch pattern
- Local dev issues:
  - Use ngrok/Cloudflare Tunnel and test with curl first
  - Inspect requests via tooling (ngrok inspector, Hookdeck, webhook.site)

---

## Conclusion

Webhooks unlock real-time, event-driven integrations without the overhead of continuous polling. To make them production-grade:

- Verify signatures and protect against replays
- Respond quickly and process asynchronously
- Design for idempotency and at-least-once delivery
- Implement robust retry policies with backoff and DLQs
- Harden security, monitor delivery health, and document your schema

With the patterns and code in this tutorial—and the resources below—you’re equipped to implement reliable webhooks from scratch and operate them confidently at scale.

---

## Resources

Official provider docs and security guides:
- Stripe Webhooks: https://stripe.com/docs/webhooks
- Stripe Signatures: https://stripe.com/docs/webhooks/signatures
- GitHub Webhooks Security: https://docs.github.com/webhooks-and-events/webhooks/securing-your-webhooks
- Slack Request Verification: https://api.slack.com/authentication/verifying-requests-from-slack
- Shopify Webhooks Security: https://shopify.dev/docs/apps/build/webhooks/secure
- Twilio Webhooks Security: https://www.twilio.com/docs/usage/webhooks/webhooks-security
- PayPal Webhooks: https://developer.paypal.com/docs/api-basics/notifications/webhooks/
- Square Webhooks: https://developer.squareup.com/docs/webhooks/overview

Tools for local development and inspection:
- ngrok: https://ngrok.com/
- Cloudflare Tunnel: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/
- Localtunnel: https://github.com/localtunnel/localtunnel
- webhook.site: https://webhook.site/
- RequestBin (Pipedream): https://pipedream.com/requestbin
- Hookdeck (tunnels, replay, logs): https://hookdeck.com/
- Svix (webhook infrastructure): https://www.svix.com/
- Beeceptor: https://beeceptor.com/
- Smee.io (GitHub-friendly relay): https://smee.io/

Standards and references:
- OWASP Webhooks Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/Webhooks_Security_Cheat_Sheet.html
- AsyncAPI: https://www.asyncapi.com/
- IETF HTTP Message Signatures (draft): https://www.rfc-editor.org/rfc/rfc9421

Framework-specific references:
- Express raw body tips: https://expressjs.com/en/resources/middleware/body-parser.html#bodyparserraw
- Flask: https://flask.palletsprojects.com/
- FastAPI: https://fastapi.tiangolo.com/
- Go net/http: https://pkg.go.dev/net/http
- Ruby Sinatra: https://sinatrarb.com/
- Laravel: https://laravel.com/

Testing and queues:
- Redis: https://redis.io/
- BullMQ: https://docs.bullmq.io/
- Celery: https://docs.celeryq.dev/
- Amazon SQS: https://aws.amazon.com/sqs/
- Google Pub/Sub: https://cloud.google.com/pubsub/docs
- RabbitMQ: https://www.rabbitmq.com/

Cloud deployment patterns:
- AWS API Gateway + Lambda: https://docs.aws.amazon.com/apigateway/latest/developerguide/set-up-lambda-proxy-integrations.html
- Google Cloud Functions/Run: https://cloud.google.com/functions and https://cloud.google.com/run
- Azure Functions: https://learn.microsoft.com/azure/azure-functions/

With these references and the examples above, you can implement, secure, test, and scale webhooks with confidence.