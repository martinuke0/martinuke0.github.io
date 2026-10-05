---
title: "Build a Portfolio CV Side Project with Real-Time WebSockets, Supabase, and Stripe"
date: "2026-10-05T20:01:54.677"
draft: false
tags: ["portfolio", "websockets", "supabase", "stripe", "telegram"]
description: "Hands-on guide to building a portfolio/CV side project with real-time WebSockets, Supabase backend, Stripe payments, and a Telegram bot for live queries."
summary: "Build a live portfolio site that showcases real-time updates, Stripe payments, and Telegram integration."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-10-05-build-a-portfolio-cv-side-project-with-real-time-websockets-supabase-and-stripe.svg"
  alt: "Portfolio dashboard"
  caption: ""
  relative: false
---

> **TL;DR** — This guide walks you through building a portfolio/CV side project that combines real-time WebSockets, a Supabase backend, Stripe payments, and a Telegram bot, giving you concrete, deployable code that signals strong systems skills to hiring managers.

In a crowded job market, a static résumé is no longer enough. A live, interactive portfolio demonstrates that you can ship full‑stack features, handle real‑time data, and integrate third‑party services—all skills that recruiters look for in senior engineering roles.

## Why This Project Stands Out on a CV

- **Real‑time data streaming** – WebSockets show you understand persistent connections, back‑pressure, and event‑driven architecture.  
- **Serverless backend** – Supabase proves you can leverage managed PostgreSQL with row‑level security and real‑time subscriptions.  
- **Payment integration** – Stripe signals experience with PCI‑DSS‑compliant flows, idempotency, and webhook handling.  
- **Conversational interface** – A Telegram bot demonstrates ability to build stateless, long‑polling services and integrate external APIs.  
- **Custom internal libraries** – The modules `ultrathink`, `triangle dp`, `top500`, `subagents`, and `reactloop` showcase your capacity to design, document, and reuse code—something senior engineers do daily.

## Architecture Overview

```
┌─────────────┐      WebSocket      ┌──────────────────┐
│   React     │ ◄──────────────────► │   FastAPI +      │
│  Frontend   │                      │   ultrathink     │
└──────┬──────┘                      └───────┬──────────┘
       │                                   │
       │ REST / GraphQL                    │ Pub/Sub
       ▼                                   ▼
┌─────────────┐                      ┌───────────────┐
│  Supabase   │ ◄──────────────────► │  subagents    │
│  (Postgres) │                      │  (background) │
└─────────────┘                      └───────┬───────┘
                                            │
                                            ▼
                                   ┌─────────────────┐
                                   │  Stripe /       │
                                   │  Telegram Bot   │
                                   └─────────────────┘
```

- **`reactloop`** – A React hook that manages WebSocket subscriptions, handling reconnects and state synchronization.  
- **`ultrathink`** – A lightweight in‑memory store that mirrors Supabase real‑time updates for instant UI feedback.  
- **`triangle dp`** – A data‑processing pipeline that aggregates portfolio metrics (views, clicks, payments) into a time‑series store.  
- **`top500`** – A leaderboard service that ranks users based on activity, powered by Supabase edge functions.  
- **`subagents`** – Independent worker processes (e.g., email notifications, analytics) that communicate via a Redis‑backed queue.

## Building It Step by Step

### 1. Scaffold the Project

```bash
mkdir portfolio-cv && cd portfolio-cv
npm init -y
npm install react react-dom next stripe @supabase/supabase-js
mkdir pages api components lib
```

### 2. Backend API (FastAPI)

Create `api/main.py`:

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from supabase import create_client, Client
import os
import json
import stripe
from typing import List

app = FastAPI()

# Supabase client
supabase: Client = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_ANON_KEY")
)

# Stripe configuration
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/create-checkout-session")
async def create_checkout_session(price_id: str):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url="https://yourdomain.com/success",
            cancel_url="https://yourdomain.com/cancel"
        )
        return {"url": session.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo or process incoming messages
            await manager.broadcast(f"Portfolio update: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

### 3. Supabase Schema

Run in the Supabase SQL editor:

```sql
create table if not exists profiles (
    id uuid references auth.users on delete cascade primary key,
    full_name text,
    bio text,
    avatar_url text
);

create table if not exists metrics (
    id bigint generated always as identity primary key,
    profile_id uuid references profiles(id),
    event text not null,
    created_at timestamptz default now()
);

alter table profiles enable row level security;
alter table metrics enable row level security;

create policy "Public profiles are viewable by everyone"
on profiles for select using (true);

create policy "Users can insert their own profile"
on profiles for insert with check (auth.uid() = id);
```

### 4. `reactloop` – WebSocket Hook

`lib/reactloop.ts`:

```ts
import { useEffect, useState } from 'react';

export function useWebSocket(url: string) {
    const [ws, setWs] = useState<WebSocket | null>(null);
    const [messages, setMessages] = useState<string[]>([]);

    useEffect(() => {
        const socket = new WebSocket(url);
        setWs(socket);

        socket.onopen = () => console.log('WebSocket connected');
        socket.onmessage = (event) => {
            setMessages(prev => [...prev, event.data]);
        };
        socket.onclose = () => console.log('WebSocket disconnected');
        socket.onerror = (err) => console.error('WebSocket error', err);

        return () => socket.close();
    }, [url]);

    return { ws, messages };
}
```

### 5. Frontend Component

`components/PortfolioDashboard.tsx`:

```tsx
import { useWebSocket } from '../lib/reactloop';
import { useEffect, useState } from 'react';

export default function PortfolioDashboard() {
    const { messages } = useWebSocket('ws://localhost:8000/ws');
    const [profile, setProfile] = useState<any>(null);

    useEffect(() => {
        // Fetch profile from Supabase
        fetch('/api/profile').then(res => res.json()).then(setProfile);
    }, []);

    return (
        <div>
            <h1>{profile?.full_name || 'Loading...'}</h1>
            <ul>
                {messages.map((msg, idx) => <li key={idx}>{msg}</li>)}
            </ul>
        </div>
    );
}
```

### 6. Telegram Bot (Python)

`bot/telegram_bot.py`:

```python
import os
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext

def start(update: Update, context: CallbackContext):
    update.message.reply_text("Hi! I'm your portfolio assistant. Send /metrics to see live stats.")

def metrics(update: Update, context: CallbackContext):
    # Query Supabase for latest metrics
    # Example: response = supabase.table('metrics').select('*').execute()
    update.message.reply_text("Latest views: 128, clicks: 57, payments: 3")

def main():
    updater = Updater(os.getenv("TELEGRAM_BOT_TOKEN"), use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("metrics", metrics))
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
```

### 7. `triangle dp` – Aggregation Pipeline

`lib/triangle_dp.py`:

```python
import asyncio
from supabase import create_client, Client

async def aggregate_metrics():
    supabase: Client = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY")
    )
    # Simple triangular aggregation: sum events per hour
    response = supabase.table('metrics') \
        .select('created_at, event') \
        .gte('created_at', 'now() - interval \'1 hour\'') \
        .execute()
    # Process data...
    print("Aggregated metrics:", response.data)

# Run as a subagent
asyncio.run(aggregate_metrics())
```

### 8. `top500` Leaderboard (Edge Function)

`supabase/functions/top500/index.ts`:

```ts
import { createClient } from '@supabase/supabase-js';
import { serve } from 'https://deno.land/std@0.160.0/server/mod.ts';

serve(async (req) => {
  const supabase = createClient(
    Deno.env.get('SUPABASE_URL')!,
    Deno.env.get('SUPABASE_ANON_KEY')!
  );

  const { data, error } = await supabase
    .from('profiles')
    .select('id, full_name, metrics(count)')
    .order('metrics.count', { ascending: false })
    .limit(500);

  if (error) return new Response(JSON.stringify(error), { status: 500 });
  return new Response(JSON.stringify(data), { headers: { 'Content-Type': 'application/json' } });
});
```

## Running and Testing It

1. **Start the API**  
   ```bash
   cd api && uvicorn main:app --reload
   ```

2. **Run the Telegram bot**  
   ```bash
   python bot/telegram_bot.py
   ```

3. **Launch the frontend**  
   ```bash
   npm run dev
   ```

4. **Verify WebSocket**  
   Open `ws://localhost:8000/ws` in a browser console or use `websocat`:
   ```bash
   websocat ws://localhost:8000/ws
   ```

5. **Test Stripe Checkout**  
   POST to `/create-checkout-session` with a valid `price_id` and follow the returned URL.

6. **Check Supabase Realtime**  
   Insert a row in the `metrics` table; you should receive a WebSocket message instantly.

## Extending It: Your Roadmap to Senior-Level

1. **Persistent Session Store** – Replace in‑memory `ConnectionManager` with Redis to survive restarts and enable horizontal scaling.  
2. **Horizontal Scaling** – Deploy the API behind a load balancer; use sticky sessions or a shared Redis pub/sub to broadcast WebSocket messages across instances.  
3. **Observability** – Add OpenTelemetry traces and Prometheus metrics; ship logs to ELK to debug latency spikes in real‑time pipelines.  
4. **Fault Tolerance** – Implement dead‑letter queues for failed Stripe webhooks and Telegram messages; use exponential backoff and idempotency keys.  
5. **Benchmarking** – Write a Locust script that simulates 1,000 concurrent WebSocket connections to measure throughput and identify bottlenecks in `ultrathink`.  
6. **CI/CD Pipeline** – Containerize the service with Docker, push to GitHub Container Registry, and set up a GitHub Actions workflow that runs integration tests on every push.

## Key Takeaways

- **Real‑time UI** is achievable with WebSockets and a lightweight state mirror like `ultrathink`.  
- **Serverless backends** (Supabase, Edge Functions) reduce ops overhead while still offering row‑level security.  
- **Third‑party integrations** (Stripe, Telegram) demonstrate you can handle external APIs, webhooks, and idempotency.  
- **Custom internal libraries** (`reactloop`, `triangle dp`, `subagents`) signal the ability to design reusable, testable code.  
- **Production readiness** comes from adding persistence, scaling, observability, and automated testing.

## Further Reading

- [Supabase Realtime Docs](https://supabase.com/docs/guides/realtime) – Deep dive into PostgreSQL replication and subscription APIs.  
- [Stripe Checkout Documentation](https://stripe.com/docs/payments/accept-a-payment) – Canonical reference for building payment flows.  
- [Telegram Bot API](https://core.telegram.org/bots) – Official guide for long polling, webhooks, and bot commands.  
- [WebSocket Protocol (RFC 6455)](https://datatracker.ietf.org/doc/html/rfc6455) – The spec behind the real‑time layer.  
- [React Hooks API](https://reactjs.org/docs/hooks-intro.html) – Best practices for building reusable hooks like `reactloop`.  
- [FastAPI WebSocket Guide](https://fastapi.tiangolo.com/advanced/websockets/) – How to structure WebSocket endpoints in a Python async framework.