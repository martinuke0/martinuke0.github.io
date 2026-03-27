---
title: "Cocoon Telegram: A Deep Dive into Building, Managing, and Scaling Telegram Bots with the Cocoon Framework"
date: "2026-03-27T15:25:03.189"
draft: false
tags: ["Telegram", "Bots", "Cocoon", "Automation", "Node.js"]
---

## Introduction

Telegram has evolved from a simple messaging app into a robust platform for bots, channels, and community automation. With more than **700 million active users** and a **Bot API** that supports rich media, payments, and inline queries, developers have a fertile ground for creating interactive experiences. Yet, building a production‑ready bot that can handle thousands of concurrent users, manage state, and stay maintainable is far from trivial.

Enter **Cocoon**, an open‑source framework designed specifically for Telegram bot development. Cocoon abstracts away low‑level API calls, provides a clean middleware pipeline, and offers built‑in tools for scaling, localization, and security. In this article we will explore Cocoon from every angle:

* What Cocoon is and why it exists  
* How its architecture differs from raw Bot API usage  
* Step‑by‑step setup and a full‑featured example bot  
* Advanced capabilities such as payments, inline queries, and multi‑language support  
* Deployment strategies (Docker, serverless, Kubernetes)  
* Real‑world case studies and best practices  

By the end of this guide, you should be able to spin up a production‑grade Telegram bot in under an hour, understand how to extend it safely, and know the operational considerations for running it at scale.

> **Note:** This article assumes familiarity with JavaScript/Node.js, basic concepts of HTTP APIs, and the Telegram Bot API. If you are brand‑new to Telegram bots, consider reviewing the official documentation first.

---

## Table of Contents
*(Optional – omitted because the article is under 10 000 words.)*

---

## 1. What Is Cocoon?

### 1.1 The Problem Cocoon Solves

When you start with the raw Telegram Bot API (via `fetch` or `axios`), you quickly encounter repetitive patterns:

| Pattern | Typical Code | Pain Point |
|---------|--------------|------------|
| Receiving updates | `await fetch('https://api.telegram.org/botTOKEN/getUpdates')` | Manual long‑polling or webhook handling |
| Routing commands | `if (msg.text.startsWith('/start')) …` | Hard‑to‑maintain `if/else` chains |
| State persistence | `fs.writeFileSync(...)` | No built‑in session management |
| Error handling | `try/catch` in each handler | Duplicate boilerplate |
| Scaling | Single process → bottleneck | No clustering or queue integration |

Cocoon tackles these issues by offering:

* **Middleware pipeline** similar to Express.js, enabling composable request processing.  
* **Typed context objects** that carry chat, user, and session data across handlers.  
* **Built‑in session store adapters** (memory, Redis, MongoDB).  
* **Declarative command/scene definitions** that keep routing clear.  
* **Utilities for inline keyboards, payments, and i18n** that follow Telegram’s best practices.

### 1.2 Brief History

Cocoon was released in early 2022 by the open‑source community around the **Telegram Bot SDK for Node.js**. Its name reflects the idea of a protective “cocoon” around the raw API, letting developers focus on business logic rather than plumbing. The project is maintained on GitHub, has over **2 k stars**, and is used by startups, NGOs, and hobbyists worldwide.

---

## 2. Architecture Overview

Understanding Cocoon’s internals helps you make informed design decisions. Below is a high‑level diagram (textual representation) of the request flow:

```
┌─────────────────────┐
│   Telegram Server   │
│ (Webhook / LongPoll)│
└───────▲───────▲──────┘
        │       │
        │       │
   HTTP POST   LongPoll
        │       │
        ▼       ▼
┌─────────────────────┐
│   Cocoon Core       │
│   (Bot instance)    │
│   ┌───────────────┐ │
│   │ Middleware    │ │
│   └─────▲─────▲───┘ │
│         │     │     │
│   ┌─────┴─┐ ┌─┴─────┐│
│   │Router│ │Session││
│   └───────┘ └───────┘│
│         │            │
│   ┌─────▼───────┐    │
│   │ Handlers    │    │
│   └─────────────┘    │
└─────────────────────┘
        │
        ▼
┌─────────────────────┐
│   Telegram API      │
│   (sendMessage, …)  │
└─────────────────────┘
```

* **Webhook/LongPoll Adapter** – Cocoon can receive updates via an HTTPS webhook (recommended for production) or via long‑polling (useful for local development).  
* **Middleware Stack** – Each incoming update passes through a configurable series of middlewares (logging, authentication, i18n, etc.).  
* **Router** – Matches the update’s type (message, callback query, inline query) against registered routes.  
* **Session Store** – Persists per‑user or per‑chat state; can be swapped out with Redis, MongoDB, or a custom store.  
* **Handlers** – Async functions that receive a typed `ctx` (context) object and perform actions (send messages, edit messages, call external APIs).  

Because the pipeline is fully asynchronous and composable, you can inject monitoring (e.g., Sentry), rate limiting, or A/B testing without touching the core business logic.

---

## 3. Getting Started

### 3.1 Prerequisites

| Requirement | Minimum Version |
|-------------|-----------------|
| Node.js | 18.x (LTS) |
| npm or yarn | 8.x |
| Telegram Bot Token | Obtained from **@BotFather** |
| Optional: Redis (for session store) | 6.2+ |

### 3.2 Installing Cocoon

```bash
# Using npm
npm install @cocoon/telegram

# Using yarn
yarn add @cocoon/telegram
```

The package exports a `CocoonBot` class and a set of utilities.

### 3.3 Creating Your First Bot

Create a file named `bot.js`:

```javascript
// bot.js
import { CocoonBot, session, memoryStore, command } from '@cocoon/telegram';
import dotenv from 'dotenv';
dotenv.config();

const bot = new CocoonBot({
  token: process.env.BOT_TOKEN,
  // Choose webhook or longpoll mode
  webhook: {
    url: process.env.WEBHOOK_URL, // e.g., https://mydomain.com/bot/webhook
    port: process.env.PORT || 3000,
  },
});

/**
 * Simple in‑memory session store.
 * For production replace with RedisStore (see later section).
 */
bot.use(session({ store: memoryStore() }));

/**
 * /start command – greets the user and stores a flag in the session.
 */
bot.command('start', async (ctx) => {
  ctx.session.visited = true;
  await ctx.reply('👋 Welcome to the Cocoon demo bot! Type /help to see what I can do.');
});

/**
 * /help command – lists available commands.
 */
bot.command('help', async (ctx) => {
  const helpText = `
📚 *Available commands*:
/start – Begin the conversation
/help – Show this help message
/echo <text> – Echo back the supplied text
`;
  await ctx.reply(helpText, { parse_mode: 'Markdown' });
});

/**
 * /echo command – demonstrates argument parsing.
 */
bot.command('echo', async (ctx, args) => {
  if (!args.length) {
    return ctx.reply('❗️ Please provide text to echo. Usage: /echo <text>');
  }
  await ctx.reply(`🔁 ${args.join(' ')}`);
});

/**
 * Fallback for unknown commands.
 */
bot.on('message', async (ctx) => {
  await ctx.reply('🤔 I did not understand that. Type /help for a list of commands.');
});

/**
 * Start the bot (sets up webhook or longpoll).
 */
bot.start()
  .then(() => console.log('🚀 Cocoon bot is up and running!'))
  .catch(err => console.error('❌ Bot failed to start:', err));
```

#### Running the Bot

```bash
# Create a .env file
echo "BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11" >> .env
echo "WEBHOOK_URL=https://mydomain.com/bot/webhook" >> .env
# For local testing you can comment out the webhook section and use longpoll

node bot.js
```

Visit your bot on Telegram (`t.me/YourBotUsername`) and try `/start`, `/help`, and `/echo hello world`. The bot will respond accordingly, demonstrating Cocoon’s basic routing and session handling.

---

## 4. Core Concepts

### 4.1 Context (`ctx`)

Every handler receives a **context** object that aggregates useful data:

| Property | Description |
|----------|-------------|
| `ctx.update` | Raw Telegram update payload |
| `ctx.message` | Shortcut for `update.message` (if present) |
| `ctx.chat` | Chat object (`id`, `type`, `title`, etc.) |
| `ctx.from` | User object (sender) |
| `ctx.session` | Per‑user/session store (mutable) |
| `ctx.reply(text, options)` | Shortcut for `sendMessage` with chat ID pre‑filled |
| `ctx.api` | Direct access to the low‑level Bot API (`ctx.api.sendMessage(...)`) |

Because `ctx` is a plain JavaScript object, you can augment it with custom properties in middleware (e.g., `ctx.locale`).

### 4.2 Middleware

Middleware functions have the signature `async (ctx, next) => {}`. They must call `await next()` to forward processing. Example: a request logger.

```javascript
bot.use(async (ctx, next) => {
  const start = Date.now();
  console.log(`⏱️ ${ctx.update.update_id} – ${ctx.message?.text || 'non‑text update'}`);
  await next();
  const ms = Date.now() - start;
  console.log(`✅ Handled in ${ms} ms`);
});
```

You can stack as many middlewares as you like—authentication, rate limiting, analytics, etc.

### 4.3 Routing & Commands

Cocoon provides a high‑level **command** helper that parses arguments and normalizes command names.

```javascript
bot.command('weather', async (ctx, args) => {
  const city = args[0] || 'London';
  const forecast = await getWeather(city); // assume external API
  await ctx.reply(`🌤️ Weather in *${city}*: ${forecast}`, { parse_mode: 'Markdown' });
});
```

For more complex flows, Cocoon offers **scenes** (similar to Telegraf’s Stage) that maintain a multi‑step conversation state. Below is a simple registration scene:

```javascript
import { scene, step } from '@cocoon/telegram';

const registerScene = scene('register')
  .step('askName', async (ctx) => {
    await ctx.reply('👤 What is your full name?');
    ctx.session.nextStep = 'askEmail';
  })
  .step('askEmail', async (ctx) => {
    ctx.session.name = ctx.message.text;
    await ctx.reply('📧 Please provide your email address.');
    ctx.session.nextStep = 'complete';
  })
  .step('complete', async (ctx) => {
    ctx.session.email = ctx.message.text;
    await ctx.reply(`✅ Registration complete!\nName: ${ctx.session.name}\nEmail: ${ctx.session.email}`);
    ctx.session.nextStep = null;
  });

bot.use(registerScene.middleware());
bot.command('register', async (ctx) => {
  ctx.session.nextStep = 'askName';
  await ctx.reply('🚀 Starting registration...');
});
```

The scene middleware intercepts messages and forwards them to the appropriate step based on `ctx.session.nextStep`.

### 4.4 Session Stores

Cocoon ships with a **memory store** (good for prototyping) and a **Redis store** for production.

```javascript
import { redisStore } from '@cocoon/telegram';
import Redis from 'ioredis';

const redis = new Redis(process.env.REDIS_URL);
bot.use(session({ store: redisStore(redis) }));
```

The store API implements `get`, `set`, and `delete` for a given key (normally `user:<id>`). You can also write a custom store that persists to PostgreSQL or MongoDB.

---

## 5. Advanced Features

### 5.1 Inline Queries

Inline bots let users type `@yourbot query` in any chat, and the bot returns results without opening a private conversation.

```javascript
bot.inlineQuery(async (ctx) => {
  const query = ctx.inlineQuery.query.trim();
  if (!query) {
    return ctx.answerInlineQuery([]);
  }

  // Simulate a search in a product catalog
  const results = await searchProducts(query); // returns array of objects
  const inlineResults = results.map((p, idx) => ({
    type: 'article',
    id: `${idx}`,
    title: p.title,
    description: p.description,
    input_message_content: {
      message_text: `🛍️ *${p.title}*\n${p.description}\nPrice: $${p.price}`,
      parse_mode: 'Markdown',
    },
    thumb_url: p.thumbnail,
  }));

  await ctx.answerInlineQuery(inlineResults, { cache_time: 60 });
});
```

Key points:

* **`ctx.inlineQuery`** gives you the query text and user info.  
* **`ctx.answerInlineQuery`** must be called within 10 seconds, otherwise Telegram returns a timeout error.  
* Results are limited to **50 items** per request.

### 5.2 Payments

Telegram’s **Payments API** enables in‑app purchases. Cocoon wraps the flow into a simple helper.

```javascript
import { LabeledPrice } from '@cocoon/telegram';

bot.command('buy', async (ctx) => {
  const prices = [new LabeledPrice('Premium Subscription', 9900)]; // price in cents
  await ctx.sendInvoice({
    title: 'Premium Subscription',
    description: 'Access to exclusive content for 30 days.',
    payload: 'premium_30d',
    provider_token: process.env.PAYMENTS_PROVIDER_TOKEN,
    currency: 'USD',
    prices,
    start_parameter: 'premium_30d',
  });
});

bot.preCheckoutQuery(async (ctx) => {
  // Optionally validate the payload, amount, etc.
  await ctx.answerPreCheckoutQuery(true);
});

bot.successfulPayment(async (ctx) => {
  // Grant the user premium access
  ctx.session.isPremium = true;
  await ctx.reply('🎉 Payment successful! You now have premium access.');
});
```

**Important:** Payments require a **provider token** from a supported payment provider (e.g., Stripe, Razorpay). The flow must be hosted on a **TLS‑enabled** domain.

### 5.3 Localization (i18n)

Cocoon’s `i18n` middleware loads translation files and attaches a `t` function to the context.

```javascript
import { i18n } from '@cocoon/telegram';
import path from 'path';

bot.use(i18n({
  defaultLocale: 'en',
  localesPath: path.resolve('locales'), // folder with JSON files per locale
}));

// locales/en.json
{
  "welcome": "👋 Welcome, {{name}}!",
  "help": "Here are the commands you can use..."
}

// locales/es.json
{
  "welcome": "👋 ¡Bienvenido, {{name}}!",
  "help": "Estos son los comandos que puedes usar..."
}
```

Usage in a handler:

```javascript
bot.command('start', async (ctx) => {
  const name = ctx.from.first_name;
  await ctx.reply(ctx.t('welcome', { name }));
});
```

Cocoon automatically detects the user’s language (`ctx.from.language_code`) and falls back to `defaultLocale` if a translation is missing.

### 5.4 Rate Limiting

To protect against spam, you can add a simple Redis‑backed rate limiter:

```javascript
import { rateLimiter } from '@cocoon/telegram';
import Redis from 'ioredis';

const redis = new Redis(process.env.REDIS_URL);
bot.use(rateLimiter({
  store: redis,
  windowMs: 60_000,   // 1 minute
  max: 20,            // allow 20 messages per minute per user
  keyGenerator: (ctx) => `rl:${ctx.from.id}`,
  onLimitExceeded: async (ctx) => {
    await ctx.reply('⚠️ You are sending messages too fast. Please wait a moment.');
  },
}));
```

If the limit is exceeded, the `onLimitExceeded` callback runs and the request chain stops.

---

## 6. Deployment Strategies

### 6.1 Docker

A Dockerfile isolates dependencies and makes scaling trivial.

```dockerfile
# Dockerfile
FROM node:18-alpine

# Create app directory
WORKDIR /usr/src/app

# Install app dependencies
COPY package*.json ./
RUN npm ci --only=production

# Bundle app source
COPY . .

# Environment variables
ENV NODE_ENV=production
ENV PORT=3000

EXPOSE 3000

CMD ["node", "bot.js"]
```

Build and run:

```bash
docker build -t cocoon-telegram-bot .
docker run -d -p 3000:3000 \
  -e BOT_TOKEN=$BOT_TOKEN \
  -e WEBHOOK_URL=$WEBHOOK_URL \
  -e REDIS_URL=$REDIS_URL \
  cocoon-telegram-bot
```

### 6.2 Serverless (AWS Lambda)

Cocoon can be used with **Serverless Framework** or **AWS SAM** by exposing a Lambda handler.

```javascript
// lambda.js
import { createLambdaHandler } from '@cocoon/telegram';
import bot from './bot-instance'; // export the configured CocoonBot instance

export const handler = createLambdaHandler(bot);
```

Add to `serverless.yml`:

```yaml
functions:
  telegramWebhook:
    handler: lambda.handler
    events:
      - http:
          path: bot/webhook
          method: post
          payload: '2.0'
```

Serverless eliminates the need for a dedicated server; each update triggers a new Lambda invocation. Remember to keep the **session store** external (Redis or DynamoDB) because Lambda containers are stateless.

### 6.3 Kubernetes with Horizontal Pod Autoscaling

For high‑traffic bots, deploy a **Deployment** with **HPA** based on CPU or custom metrics (e.g., queue length).

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cocoon-bot
spec:
  replicas: 2
  selector:
    matchLabels:
      app: cocoon-bot
  template:
    metadata:
      labels:
        app: cocoon-bot
    spec:
      containers:
        - name: bot
          image: yourrepo/cocoon-telegram-bot:latest
          env:
            - name: BOT_TOKEN
              valueFrom:
                secretKeyRef:
                  name: telegram-secrets
                  key: token
            - name: REDIS_URL
              value: redis://redis:6379
          ports:
            - containerPort: 3000
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: cocoon-bot-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: cocoon-bot
  minReplicas: 2
  maxReplicas: 10
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
```

With this setup, Kubernetes automatically adds pods when CPU usage rises, ensuring the bot can handle spikes without downtime.

---

## 7. Security and Compliance

### 7.1 Token Protection

Never hard‑code the bot token. Use environment variables or secret management services (AWS Secrets Manager, HashiCorp Vault). In CI/CD pipelines, mask the token in logs.

### 7.2 Input Validation

Telegram users can send arbitrary text, including markdown that could break your messages. Always **escape** user‑provided data when using `parse_mode: 'MarkdownV2'`.

```javascript
import { escapeMarkdown } from '@cocoon/telegram';

const safeText = escapeMarkdown(userInput);
await ctx.reply(`You said: ${safeText}`, { parse_mode: 'MarkdownV2' });
```

### 7.3 Rate Limiting & Abuse Prevention

Combine per‑user rate limiting (as shown in Section 5.4) with **IP‑based** limits on your webhook endpoint (e.g., using Nginx `limit_req_zone`). This protects against DDoS attacks on the webhook URL.

### 7.4 GDPR & Data Retention

If you store personal data (name, email, location), you must:

1. **Obtain explicit consent** – ask users before storing data.  
2. **Provide a deletion command** – e.g., `/delete_my_data`.  
3. **Set retention policies** – automatically purge data after a defined period (e.g., 90 days).  

Cocoon’s session store can be configured with TTL:

```javascript
bot.use(session({
  store: redisStore(redis, { ttl: 60 * 60 * 24 * 30 }) // 30 days
}));
```

### 7.5 Webhook TLS

Telegram only accepts HTTPS webhooks with a **valid certificate** from a trusted CA. Self‑signed certificates are allowed only if you upload the public key to Telegram via `setWebhook`. For production, use **Let’s Encrypt** certificates and automate renewal.

---

## 8. Real‑World Use Cases

### 8.1 Customer Support Chatbot

A SaaS company deployed a Cocoon bot to field first‑level support tickets:

* **Features:** ticket creation, status lookup, FAQ search via inline queries.  
* **Architecture:** Webhook → Cocoon → PostgreSQL (tickets) + Redis (sessions).  
* **Outcome:** 40 % of support tickets were resolved without human intervention, reducing cost by **$12k/month**.

### 8.2 Community Management for a Large Telegram Channel

An online community with **150 k members** used Cocoon to:

* Automate onboarding (`/rules`, `/verify`).  
* Run polls and quizzes with inline keyboards.  
* Enforce anti‑spam policies via middleware that checks message frequency and blacklists.  

The bot’s **scene** system guided new members through a three‑step verification (captcha → email link → role assignment). The community reported a **30 % drop** in spam incidents.

### 8.3 E‑Commerce Order Tracking

An e‑commerce retailer integrated Cocoon to let customers:

* Query order status via `/track <order_id>`.  
* Receive real‑time shipping updates through push notifications.  
* Pay for additional services (gift wrap) using the Payments API.  

By connecting Cocoon to the retailer’s ERP via a REST API, the bot delivered **instant** order info, improving NPS by **+8 points**.

---

## 9. Best Practices

| Area | Recommendation |
|------|----------------|
| **Project Structure** | Keep bot logic in `src/handlers/`, middlewares in `src/middleware/`, and configuration in `src/config/`. |
| **Error Handling** | Use a global error‑handling middleware that logs to a monitoring service (Sentry, LogRocket). |
| **Testing** | Write unit tests for handlers with `node-mocks-http` and integration tests using Telegram’s **test bot** (`@BotFather` can create a sandbox). |
| **Logging** | Include `update_id`, `chat_id`, and `user_id` in each log line. Use a structured logger (pino, winston). |
| **Version Control** | Pin the Cocoon version in `package.json` (e.g., `"@cocoon/telegram": "^1.4.0"`). |
| **CI/CD** | Automate Docker image builds on merge, run linting (`eslint`), and run tests before deployment. |
| **Scalability** | Store sessions in Redis, not in memory. Use a stateless design so you can add replicas behind a load balancer. |
| **Security** | Validate all external API responses, escape user input, and rotate the bot token if you suspect a leak. |
| **Documentation** | Keep a `README.md` with setup steps, environment variables, and a quick command cheat‑sheet. |

---

## 10. Common Pitfalls & How to Avoid Them

1. **Using Long‑Polling in Production** – While convenient for local dev, long‑polling can cause missed updates under high load. Switch to webhooks and configure a reliable HTTPS endpoint.  
2. **Storing Sessions in Memory** – Works for a single‑instance bot but fails when you scale horizontally. Always configure a shared store (Redis) before adding more instances.  
3. **Ignoring Telegram Rate Limits** – Telegram caps `sendMessage` at **30 messages per second per bot**. If you exceed this, you’ll receive `429 Too Many Requests`. Use a queuing system (BullMQ) or built‑in rate limiter.  
4. **Hard‑Coded URLs in Inline Results** – Telegram caches inline query results for up to **24 hours**. If you change the underlying data, you must include a `cache_time` of `0` or a new `id` for each result.  
5. **Not Handling `pre_checkout_query`** – Failing to answer this query leads to a “Payment failed” message for the user. Always respond with `answerPreCheckoutQuery(true)` (or `false` with an error string).  

---

## 11. Future Roadmap for Cocoon

The Cocoon maintainers have outlined several upcoming features (as of early 2026):

| Feature | Expected Release | Description |
|---------|------------------|-------------|
| **Typed Context for TypeScript** | v2.0 (Q3 2026) | Full TypeScript definitions for `ctx`, middleware, and stores. |
| **Built‑in Bot Analytics Dashboard** | v2.1 (Q4 2026) | Real‑time metrics (active users, command usage, error rates) with Grafana integration. |
| **AI‑Powered Intent Classification Middleware** | v2.2 (Q1 2027) | Plug‑and‑play NLU that maps free‑text messages to intents without manual regexes. |
| **Zero‑Downtime Deployment Mode** | v2.3 (Q2 2027) | Graceful migration of webhook URLs using a rolling update pattern. |

Community contributions are encouraged, and the project’s GitHub issues page is active with feature requests and bug reports.

---

## Conclusion

Cocoon provides a **clean, extensible, and production‑ready** foundation for Telegram bot development. By abstracting away repetitive plumbing—routing, session handling, middleware composition, and error management—it lets developers focus on delivering value to users. Whether you are building a simple FAQ bot or a full‑fledged e‑commerce assistant, Cocoon’s modular architecture scales from a single Docker container to a Kubernetes‑managed fleet behind a load balancer.

Key takeaways:

* **Start small** with the built‑in memory store, then migrate to Redis for scalability.  
* Leverage **middleware** for logging, security, and rate limiting—this keeps your handlers pure.  
* Use **scenes** for multi‑step conversations and **i18n** for global audiences.  
* Deploy via **webhooks** on HTTPS, preferably behind Docker or serverless platforms, and monitor health with structured logs.  
* Follow the best‑practice checklist to stay compliant with GDPR, avoid token leaks, and respect Telegram’s rate limits.

With the knowledge and code snippets presented here, you should feel confident to prototype, ship, and iterate on Telegram bots that delight users and stand up to real‑world traffic. Happy coding, and may your bots always stay within the cocoon of reliability!

---

## Resources

1. **Telegram Bot API Documentation** – Official reference for all Bot API methods and webhook setup.  
   [Telegram Bot API Docs](https://core.telegram.org/bots/api)

2. **Cocoon GitHub Repository** – Source code, issue tracker, and contribution guidelines.  
   [Cocoon on GitHub](https://github.com/cocoon-telegram/cocoon)

3. **Node‑Telegram‑Bot‑API** – An alternative Node.js library; useful for comparing design patterns.  
   [node-telegram-bot-api](https://github.com/yagop/node-telegram-bot-api)

4. **Redis Official Documentation** – Guides for setting up Redis as a session store.  
   [Redis.io Documentation](https://redis.io/documentation)

5. **Telegram Payments Guide** – Detailed steps for configuring payment providers and handling callbacks.  
   [Payments Guide](https://core.telegram.org/bots/payments)

---