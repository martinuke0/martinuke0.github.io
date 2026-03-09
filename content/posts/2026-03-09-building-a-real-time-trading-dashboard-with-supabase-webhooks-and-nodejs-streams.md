---
title: "Building a Real-Time Trading Dashboard with Supabase Webhooks and Node.js Streams"
date: "2026-03-09T11:00:46.991"
draft: false
tags: ["Supabase","Webhooks","Node.js","Real-Time","Trading Dashboard"]
---

## Introduction

In the world of algorithmic trading, market data is the lifeblood of every strategy. Traders and developers alike need **instantaneous, reliable, and scalable** pipelines that turn raw exchange events into actionable visualizations. Traditional polling approaches quickly become a bottleneck, especially when dealing with high‑frequency tick data or multi‑asset portfolios.

Enter **Supabase**, the open‑source Firebase alternative that offers a Postgres‑backed backend with built‑in authentication, storage, and—most importantly for this article—**webhooks**. Coupled with **Node.js streams**, you can build a low‑latency, back‑pressure‑aware ingestion layer that pushes updates to a front‑end dashboard in real time.

This guide walks you through the entire process:

1. **Designing a suitable data model** for trades and market quotes.
2. **Configuring Supabase webhooks** to emit events on inserts/updates.
3. **Implementing a Node.js service** that consumes webhook payloads via streams.
4. **Streaming data to a front‑end dashboard** using Server‑Sent Events (SSE) or WebSockets.
5. **Scaling, securing, and deploying** the solution for production use.

By the end, you’ll have a functional, production‑ready real‑time trading dashboard that you can extend to fit any trading strategy.

---

## 1. Understanding Real‑Time Requirements in Trading

Before diving into code, let’s clarify **what “real‑time” means** for a trading dashboard.

| Requirement | Why It Matters |
|-------------|----------------|
| **Low latency (< 200 ms)** | Traders need to see price changes before they act. |
| **High throughput** | A single exchange can generate thousands of ticks per second. |
| **Reliability & consistency** | Missed or duplicated updates can corrupt visualizations and decisions. |
| **Scalability** | As you add more symbols or users, the system must handle the load without degradation. |
| **Security & compliance** | Financial data is sensitive; authentication and audit trails are mandatory. |

Traditional HTTP polling (e.g., every 5 seconds) fails on latency and efficiency. Instead, we’ll **push** updates from the database to the server via **webhooks**, then **stream** them to the client using **Node.js streams**—a native, back‑pressure‑aware abstraction that ensures we never overwhelm the client or the network.

---

## 2. Overview of Supabase Webhooks

Supabase provides **Realtime** (via PostgreSQL logical replication) and **Webhooks** (via the Supabase Functions platform). While Supabase Realtime is great for broadcasting changes directly to the browser, **webhooks give you a programmable hook** where you can:

- Enrich data (e.g., calculate moving averages).
- Perform validation or authentication.
- Fan‑out to multiple downstream services.

A webhook in Supabase is essentially an **HTTP POST** request triggered on a table event (`INSERT`, `UPDATE`, `DELETE`). You configure the target URL, headers, and optionally a secret for HMAC verification.

Key points:

- **Payload**: JSON containing the changed row(s) and metadata.
- **Retry policy**: Supabase retries failed deliveries with exponential back‑off.
- **Signature**: If a secret is set, Supabase sends an `X-Supabase-Signature` header containing an HMAC‑SHA256 hash of the payload.

These features make Supabase webhooks an ideal entry point for a Node.js stream pipeline.

---

## 3. Setting Up Your Supabase Project

### 3.1 Create a New Project

1. Sign in to <https://app.supabase.com>.
2. Click **New Project**, choose a name (e.g., `trading-dashboard`), and select a region.
3. Wait for the Postgres instance to spin up (usually a few minutes).

### 3.2 Enable the `pgcrypto` Extension

We’ll use `pgcrypto` to generate UUIDs for trades.

```sql
create extension if not exists pgcrypto;
```

### 3.3 Install the Supabase CLI (optional but handy)

```bash
npm install -g supabase
supabase login
supabase init
```

The CLI lets you manage migrations, functions, and local emulation.

---

## 4. Designing the Data Model

A robust model is crucial for both performance and clarity. Below is a minimal schema that you can extend.

```sql
-- Table to store raw market ticks
create table public.ticks (
  id uuid default gen_random_uuid() primary key,
  symbol text not null,
  price numeric not null,
  volume numeric not null,
  timestamp timestamptz default now()
);

-- Table to store executed trades (could be from your own engine)
create table public.trades (
  id uuid default gen_random_uuid() primary key,
  symbol text not null,
  side text check (side in ('buy', 'sell')) not null,
  quantity numeric not null,
  price numeric not null,
  executed_at timestamptz default now()
);
```

**Indexes** for fast queries:

```sql
create index idx_ticks_symbol_timestamp on public.ticks (symbol, timestamp desc);
create index idx_trades_symbol_executed_at on public.trades (symbol, executed_at desc);
```

**Why separate ticks and trades?**  
Ticks represent market data (price/volume) while trades represent your own execution events. Both streams will feed the dashboard but might require different transformation logic.

---

## 5. Configuring Supabase Webhooks

### 5.1 Create a Webhook for `ticks`

1. In the Supabase dashboard, go to **Database → Replication → Webhooks**.
2. Click **New Webhook**.
3. Set:
   - **Table**: `ticks`
   - **Event**: `INSERT`
   - **URL**: `https://your-node-service.example.com/webhook/ticks`
   - **Secret**: generate a strong random string (e.g., `s3cr3tK3y!`).
4. Save.

Repeat the same for the `trades` table, pointing to `/webhook/trades`.

### 5.2 Verify Signature (HMAC)

Supabase will include an `X-Supabase-Signature` header. In your Node.js service you’ll verify it:

```js
import crypto from 'crypto';

function verifySignature(payload, signature, secret) {
  const hash = crypto
    .createHmac('sha256', secret)
    .update(JSON.stringify(payload))
    .digest('hex');
  return crypto.timingSafeEqual(Buffer.from(hash), Buffer.from(signature));
}
```

---

## 6. Node.js Streams Primer

Node.js streams are **objects that implement a readable, writable, transform, or duplex interface**. They enable:

- **Back‑pressure**: the consumer signals when it can accept more data.
- **Composable pipelines**: you can pipe multiple transforms together.
- **Memory efficiency**: data flows chunk‑by‑chunk instead of loading everything into RAM.

For our use case, we’ll set up a **Writable stream** that receives webhook payloads, transforms them, and pushes them into a **Readable stream** that the SSE/WebSocket server consumes.

### 6.1 Basic Example

```js
import { Writable, Readable } from 'stream';

const tickWriter = new Writable({
  objectMode: true,
  write(chunk, encoding, callback) {
    // Process each tick
    console.log('Received tick:', chunk);
    // Pass to downstream readable
    tickStream.push(chunk);
    callback();
  }
});

const tickStream = new Readable({
  objectMode: true,
  read() {} // No-op; data is pushed manually
});
```

Now `tickStream` can be piped to any consumer that respects back‑pressure.

---

## 7. Building the Node.js Service

We’ll use **Express** for the HTTP webhook endpoint and **EventSource** (SSE) for broadcasting to the front‑end. Feel free to swap WebSockets if you prefer bi‑directional communication.

### 7.1 Project Setup

```bash
mkdir trading-dashboard-backend
cd trading-dashboard-backend
npm init -y
npm install express body-parser cors dotenv node-fetch
npm install --save-dev nodemon
```

Create a `.env` file:

```env
PORT=3000
SUPABASE_WEBHOOK_SECRET=s3cr3tK3y!
```

### 7.2 Server Skeleton (`index.js`)

```js
import express from 'express';
import cors from 'cors';
import bodyParser from 'body-parser';
import { Writable, Readable } from 'stream';
import crypto from 'crypto';
import dotenv from 'dotenv';

dotenv.config();

const app = express();
app.use(cors());
app.use(bodyParser.json({ limit: '1mb' })); // Supabase payloads are small

const PORT = process.env.PORT || 3000;
const WEBHOOK_SECRET = process.env.SUPABASE_WEBHOOK_SECRET;

// ---------- Stream Setup ----------
const tickStream = new Readable({ objectMode: true, read() {} });
const tradeStream = new Readable({ objectMode: true, read() {} });

function createWebhookWriter(targetStream) {
  return new Writable({
    objectMode: true,
    write(payload, _, callback) {
      targetStream.push(payload);
      callback();
    },
  });
}

const tickWriter = createWebhookWriter(tickStream);
const tradeWriter = createWebhookWriter(tradeStream);

// ---------- Signature Verification ----------
function verifySignature(req, secret) {
  const signature = req.headers['x-supabase-signature'];
  if (!signature) return false;
  const payload = JSON.stringify(req.body);
  const hash = crypto.createHmac('sha256', secret).update(payload).digest('hex');
  return crypto.timingSafeEqual(Buffer.from(hash), Buffer.from(signature));
}

// ---------- Webhook Endpoints ----------
app.post('/webhook/ticks', (req, res) => {
  if (!verifySignature(req, WEBHOOK_SECRET)) {
    return res.status(401).send('Invalid signature');
  }
  tickWriter.write(req.body, () => {}); // Push into stream
  res.status(200).send('OK');
});

app.post('/webhook/trades', (req, res) => {
  if (!verifySignature(req, WEBHOOK_SECRET)) {
    return res.status(401).send('Invalid signature');
  }
  tradeWriter.write(req.body, () => {});
  res.status(200).send('OK');
});

// ---------- SSE Endpoint ----------
app.get('/events', (req, res) => {
  // Set SSE headers
  res.set({
    'Cache-Control': 'no-cache',
    'Content-Type': 'text/event-stream',
    Connection: 'keep-alive',
  });
  res.flushHeaders();

  // Helper to send data
  const send = (type, data) => {
    res.write(`event: ${type}\n`);
    res.write(`data: ${JSON.stringify(data)}\n\n`);
  };

  // Pipe tick and trade streams into SSE
  const tickListener = (chunk) => send('tick', chunk);
  const tradeListener = (chunk) => send('trade', chunk);

  tickStream.on('data', tickListener);
  tradeStream.on('data', tradeListener);

  // Clean up on client disconnect
  req.on('close', () => {
    tickStream.off('data', tickListener);
    tradeStream.off('data', tradeListener);
    res.end();
  });
});

app.listen(PORT, () => console.log(`🚀 Server listening on ${PORT}`));
```

**Explanation of key parts:**

- **Writable streams (`tickWriter`, `tradeWriter`)** accept webhook payloads and push them into **Readable streams** (`tickStream`, `tradeStream`).
- **SSE endpoint (`/events`)** listens to both streams and forwards each chunk as an SSE `event`.
- **Signature verification** ensures only Supabase can post data.

### 7.3 Transformations (Optional)

Often you need to compute derived metrics (e.g., moving averages) before broadcasting. Insert a **Transform stream** between writer and readable:

```js
import { Transform } from 'stream';

function movingAverage(windowSize = 10) {
  const prices = [];
  return new Transform({
    objectMode: true,
    transform(chunk, _, cb) {
      const price = Number(chunk.price);
      prices.push(price);
      if (prices.length > windowSize) prices.shift();
      const avg = prices.reduce((a, b) => a + b, 0) / prices.length;
      const enriched = { ...chunk, movingAvg: avg };
      this.push(enriched);
      cb();
    },
  });
}

// Example usage:
const tickTransformer = movingAverage(20);
tickWriter.pipe(tickTransformer).pipe(tickStream);
```

Now every tick sent to the front‑end includes a `movingAvg` field.

---

## 8. Integrating with the Front‑End Dashboard

We’ll build a lightweight React dashboard that consumes the SSE endpoint and visualizes price movements using **Chart.js**.

### 8.1 Front‑End Boilerplate

```bash
npx create-react-app trading-dashboard-frontend
cd trading-dashboard-frontend
npm install chart.js react-chartjs-2
```

### 8.2 `src/App.js`

```jsx
import React, { useEffect, useState, useRef } from 'react';
import { Line } from 'react-chartjs-2';
import 'chartjs-adapter-date-fns';

function App() {
  const [ticks, setTicks] = useState([]);
  const [trades, setTrades] = useState([]);
  const eventSourceRef = useRef(null);

  useEffect(() => {
    // Connect to SSE endpoint
    const es = new EventSource('http://localhost:3000/events');
    eventSourceRef.current = es;

    es.addEventListener('tick', (e) => {
      const data = JSON.parse(e.data);
      setTicks((prev) => [...prev, data].slice(-200)); // Keep last 200 points
    });

    es.addEventListener('trade', (e) => {
      const data = JSON.parse(e.data);
      setTrades((prev) => [...prev, data].slice(-50));
    });

    es.onerror = (err) => {
      console.error('SSE error', err);
      es.close();
    };

    return () => {
      es.close();
    };
  }, []);

  const chartData = {
    labels: ticks.map((t) => new Date(t.timestamp)),
    datasets: [
      {
        label: 'Price',
        data: ticks.map((t) => t.price),
        borderColor: 'rgba(75,192,192,1)',
        fill: false,
      },
      {
        label: 'Moving Avg (20)',
        data: ticks.map((t) => t.movingAvg),
        borderColor: 'rgba(255,99,132,1)',
        fill: false,
        borderDash: [5, 5],
      },
    ],
  };

  const chartOptions = {
    scales: {
      x: {
        type: 'time',
        time: {
          unit: 'second',
        },
      },
    },
  };

  return (
    <div style={{ padding: '2rem' }}>
      <h1>Real‑Time Trading Dashboard</h1>
      <Line data={chartData} options={chartOptions} />
      <h2>Recent Trades</h2>
      <table>
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Price</th>
          </tr>
        </thead>
        <tbody>
          {trades
            .slice()
            .reverse()
            .map((t) => (
              <tr key={t.id}>
                <td>{new Date(t.executed_at).toLocaleTimeString()}</td>
                <td>{t.symbol}</td>
                <td>{t.side}</td>
                <td>{t.quantity}</td>
                <td>{t.price}</td>
              </tr>
            ))}
        </tbody>
      </table>
    </div>
  );
}

export default App;
```

**Key points:**

- **EventSource** automatically reconnects on network hiccups.
- **State slices** keep UI memory usage bounded.
- **Chart.js** renders a live line chart with both raw price and moving average.

### 8.3 Running the Stack

1. **Start backend**:

```bash
npm run dev   # with nodemon watching index.js
```

2. **Start front‑end**:

```bash
npm start
```

Open `http://localhost:3000` (backend) and `http://localhost:3001` (React app). When you insert rows into `ticks` or `trades` via Supabase dashboard or API, the chart updates instantly.

---

## 9. Handling Scaling and Reliability

A production deployment will face higher traffic, network partitions, and the need for fault tolerance.

### 9.1 Horizontal Scaling

- **Stateless webhook handlers**: The Express server is stateless; you can run multiple instances behind a load balancer (e.g., Nginx, Cloudflare Load Balancing).
- **Shared stream**: Use a **Redis Stream** or **Kafka** as a central message bus instead of in‑process streams. Replace `Readable`/`Writable` with a Redis client that **XADD** and **XREAD**.

```js
import { createClient } from 'redis';
const redis = createClient();
await redis.connect();

app.post('/webhook/ticks', async (req, res) => {
  // ... verify signature
  await redis.xAdd('ticks', '*', req.body);
  res.send('OK');
});
```

Front‑end SSE servers then **XREAD** from Redis, ensuring all instances see the same events.

### 9.2 Back‑Pressure & Rate Limiting

If the front‑end can’t keep up, the SSE connection will buffer. To avoid OOM:

- Set **`highWaterMark`** on streams.
- Use **`pause()`/`resume()`** based on client ACKs (more advanced, usually needed with WebSockets).

### 9.3 Retry Logic & Idempotency

Supabase already retries with exponential back‑off, but **duplicate webhook deliveries** can still happen. Ensure your processing is **idempotent**:

- Insert rows using **`ON CONFLICT DO NOTHING`** based on the primary key (`id`).
- Store a **`processed_at`** timestamp; ignore if already set.

### 9.4 Monitoring & Alerting

- **Prometheus** + **Grafana**: Export metrics (`process_ticks_total`, `webhook_errors_total`).
- **Health checks**: `/healthz` endpoint returning `200 OK` if DB connection alive.
- **Log aggregation**: Use **Winston** or **Pino** with a central log sink (e.g., Logflare, Datadog).

---

## 10. Security Considerations

| Threat | Mitigation |
|--------|------------|
| **Unauthorized webhook calls** | Verify HMAC signature; reject mismatches. |
| **SQL injection** | Use parameterized queries; Supabase client (`supabase-js`) handles this. |
| **Data leakage** | Enforce Row‑Level Security (RLS) in Supabase; only expose necessary columns. |
| **Denial‑of‑Service (DoS)** | Rate‑limit incoming webhook IPs; enable Cloudflare WAF. |
| **Cross‑Site Scripting (XSS)** | Escape all data rendered on the front‑end; use React’s default escaping. |
| **Man‑in‑the‑middle** | Serve backend over HTTPS (let’s encrypt or managed TLS). |

---

## 11. Testing and Debugging

### 11.1 Unit Tests

Use **Jest** to test the signature verification:

```js
import { verifySignature } from '../src/verify';

test('valid signature passes', () => {
  const payload = { foo: 'bar' };
  const secret = 'test-secret';
  const signature = crypto.createHmac('sha256', secret).update(JSON.stringify(payload)).digest('hex');
  const req = { body: payload, headers: { 'x-supabase-signature': signature } };
  expect(verifySignature(req, secret)).toBe(true);
});
```

### 11.2 End‑to‑End with Supabase CLI

Supabase CLI can emulate webhook calls locally:

```bash
supabase functions invoke webhook/ticks --payload '{"symbol":"AAPL","price":150.23,"volume":100}'
```

Observe the SSE output in the browser console.

### 11.3 Debugging Tips

- **Log raw webhook payloads** (sanitize before production).
- Use **`curl -v`** to manually POST to `/webhook/ticks`.
- Inspect **Redis stream entries** (`XREAD`/`XRANGE`) if using a message broker.
- Browser DevTools → **Network → EventSource** shows the raw SSE frames.

---

## 12. Deployment Strategies

### 12.1 Dockerizing the Backend

`Dockerfile`:

```Dockerfile
FROM node:20-alpine

WORKDIR /app
COPY package*.json ./
RUN npm ci --only=production
COPY . .

ENV PORT=3000
EXPOSE 3000

CMD ["node", "index.js"]
```

Build and run:

```bash
docker build -t trading-dashboard-backend .
docker run -d -p 3000:3000 --restart unless-stopped trading-dashboard-backend
```

### 12.2 Hosting Options

| Platform | Pros | Cons |
|----------|------|------|
| **Render** | Free tier, auto‑deploy from Git, built‑in TLS | Limited concurrent connections on free tier |
| **Fly.io** | Global edge, supports WebSockets/SSE out‑of‑the‑box | Slightly higher learning curve |
| **Railway** | Simple UI, PostgreSQL add‑on (useful for Supabase dev) | Billing can be unpredictable for high traffic |
| **Kubernetes (GKE/EKS)** | Full control, auto‑scaling | Overkill for small projects |

For the front‑end, static hosting on **Vercel**, **Netlify**, or **Cloudflare Pages** works perfectly.

### 12.3 Environment Variables

- `SUPABASE_WEBHOOK_SECRET` – keep in secret manager (e.g., Vercel Secrets).
- `DATABASE_URL` – not needed for webhook-only service, but you may store data for audit.

### 12.4 CI/CD

- **GitHub Actions**: Build Docker image, push to Docker Hub, trigger deployment via webhook.
- **Supabase Functions**: Consider moving the webhook processing into Supabase Edge Functions for tighter integration (still utilizes streams via Edge‑runtime).

---

## 13. Conclusion

Building a real‑time trading dashboard doesn’t have to involve a labyrinth of custom protocols and heavyweight message brokers. By leveraging **Supabase webhooks** for event emission and **Node.js streams** for back‑pressure‑aware processing, you can create a **scalable**, **secure**, and **maintainable** pipeline that pushes market data directly to a responsive front‑end.

Key takeaways:

1. **Supabase webhooks** provide a simple, authenticated push mechanism from PostgreSQL.
2. **Node.js streams** let you transform and forward data efficiently while respecting consumer capacity.
3. **Server‑Sent Events** (or WebSockets) give browsers a low‑latency, persistent channel without the overhead of polling.
4. **Scaling** can be achieved by replacing in‑process streams with a distributed message bus (Redis, Kafka) and running stateless webhook workers behind a load balancer.
5. **Security**—signature verification, TLS, RLS—must be baked in from day one.

With the code snippets, architecture diagrams, and deployment guidance provided, you’re ready to spin up a production‑grade real‑time trading dashboard that can evolve alongside your trading strategies.

Happy coding, and may your latency be low and your profits high!

## Resources

- [Supabase Documentation – Webhooks](https://supabase.com/docs/guides/database/webhooks)
- [Node.js Streams API](https://nodejs.org/api/stream.html)
- [Server‑Sent Events (MDN)](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events)
- [Chart.js – React Wrapper](https://react-chartjs-2.dev/)
- [Redis Streams – Official Docs](https://redis.io/docs/data-types/streams/)
- [Secure HMAC Verification in Node.js](https://nodejs.org/api/crypto.html#crypto_crypto_createhmac_algorithm_key_options)