---
title: "AI Gateways: The Missing Layer Between Your Apps and Every LLM Provider"
date: "2026-09-05T18:52:17.745"
draft: false
tags: ["ai-gateway", "llm", "litellm", "api-management", "production-engineering"]
description: "Why AI gateways are becoming the central control plane for LLM traffic, and how teams use them to cut costs, enforce policy, and ship faster."
summary: "AI gateways sit between applications and foundation model providers, unifying auth, routing, caching, and observability. This post breaks down the patterns, the production wins, and the open source options like LiteLLM and Portkey."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-ai-gateways-the-missing-layer-between-your-apps-and-every-llm-provider.svg"
  alt: "Diagram of an AI gateway routing requests between apps and multiple LLM providers."
  caption: ""
  relative: false
---

> **TL;DR** — An AI gateway is the control plane for LLM traffic: one client, many providers, with routing, caching, rate limits, and observability baked in. Teams adopt them to negotiate price, dodge outages, and centralize policy — the same reasons CDNs and API gateways exist for traditional web traffic.

## Why a New Layer, and Why Now

Two years ago, most teams shipping LLM features wrote their own thin client around one provider, usually OpenAI. That worked fine until it didn't. By mid-2025, a serious production stack had to talk to at least three providers, swap models behind a feature flag, fall back when one vendor degraded, and meter every request for cost attribution. That is no longer "wrap a client" work. That is infrastructure work, and it looks suspiciously like what API gateways did for microservices in the 2010s.

The official guidance from [OpenAI's production best practices](https://platform.openai.com/docs/guides/production-best-practices) already nudges teams toward "build a wrapper to track spend, enforce rate limits, and centralize retry logic." Anthropic and Google publish the same advice in slightly different words. Once every vendor tells you to write the same plumbing, the plumbing deserves a name. The name is the AI gateway.

## What an AI Gateway Actually Does

At its core, an AI gateway is a proxy that sits between your application code and the upstream model APIs. It exposes an OpenAI-compatible `/v1/chat/completions` endpoint regardless of which vendor sits behind it. From the application's perspective, nothing changes. Behind the gateway, everything is negotiable.

A serious gateway does roughly this:

- **Protocol translation** — accept OpenAI-format requests and emit Anthropic, Google Vertex, Bedrock, or self-hosted formats underneath.
- **Routing and fallback** — send a request to GPT-5o, and if it 5xxs, fail over to Claude Sonnet within the same latency budget.
- **Caching** — exact-match and semantic caches that collapse duplicate prompts into a single upstream call.
- **Rate limiting and quota** — per-tenant, per-model, per-feature budgets enforced server-side.
- **Authentication** — one set of keys for the gateway, not N sets scattered across repos.
- **Observability** — structured logs of prompt, completion, tokens, latency, cost, and metadata for every call.
- **Policy** — PII redaction, prompt-injection filters, output validation, content moderation.
- **Cost tracking** — attribution by tenant, team, or feature flag, with dollar amounts in real time.

The shape is not new. It is the API gateway pattern, retargeted at the specific failure modes of LLM traffic: long timeouts, token-based pricing, non-deterministic responses, and a vendor landscape that still reshuffles every six months.

## Patterns in Production

Three patterns show up over and over in teams running LLM workloads at scale.

### 1. Multi-Provider with Smart Routing

You send every chat completion to the gateway. The gateway uses a routing rule — by cost, by latency, by capability, by feature flag — to pick the upstream provider. A request from the "draft suggestions" feature might route to a cheap, fast model; the same request from "compliance review" might route to a frontier reasoning model on a different vendor. The application doesn't know, and doesn't care.

This is the pattern Portkey documents in their [production gateway guide](https://portkey.ai/docs), and it is the same pattern Cloudflare's AI Gateway exposes at the edge. The win is that you can A/B test providers without redeploying your app.

### 2. Fallback and Load Shedding

Provider outages are no longer rare events. OpenAI, Anthropic, and Google have all had multi-hour degradations in the past year. An AI gateway turns "our chatbot is down because OpenAI is down" into a degraded-but-running service. Common rules:

- Retry the same provider with exponential backoff up to N attempts.
- On persistent failure, route to a secondary provider with the same system prompt and a translated request body.
- If both fail, return a cached prior response or a graceful "we're temporarily limited" message.

This is the difference between an SLA you can quote and one you can't.

### 3. Semantic Caching for Cost and Latency

Exact-match caching helps when users spam the same prompt. Semantic caching — embedding the prompt and matching against prior embeddings above a similarity threshold — helps when users *almost* repeat the prompt. A request like "summarize this contract" against the same document hashes to one upstream call even if phrased differently. Teams report 20–40% cost reduction on RAG workloads where the corpus is bounded, according to case studies published by [Redis on their semantic cache pattern](https://redis.io/learn/how-to/solve-real-time-problems/ai/semantic-cache).

The catch: cache invalidation is hard, and stale cached answers can be wrong in new and interesting ways. Plan for it.

## LiteLLM: The Open Source Reference Implementation

If you want to see what an AI gateway looks like in code, [LiteLLM](https://github.com/BerriAI/litellm) is the closest thing to a reference implementation. It is a Python proxy that speaks OpenAI's API, supports 100+ providers, and ships with the operational features most teams actually need.

A minimal `config.yaml` looks like this:

```yaml
model_list:
  - model_name: gpt-5o
    litellm_params:
      model: openai/gpt-5o
      api_key: os.environ/OPENAI_API_KEY
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-5
      api_key: os.environ/ANTHROPIC_API_KEY

router_settings:
  routing_strategy: latency-based-routing
  num_retries: 3
  timeout: 30

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

A few things are worth calling out. First, the `model_name` is what your app sees; the upstream `model` is what the provider sees. Second, `routing_strategy` controls whether requests go to the cheapest, fastest, or healthiest provider. Third, the master key is the single credential your application uses; the gateway translates it to provider-specific keys at request time.

You run it with:

```bash
litellm --config config.yaml --port 4000
```

Then point your app at `http://gateway:4000/v1` instead of `api.openai.com`. Done.

## Architecture: Where the Gateway Lives

The gateway is almost always deployed as a stateful service in the same region as your application, fronted by your existing ingress. A common topology:

```
[App] -> [CDN / Load Balancer] -> [AI Gateway] -> [Provider APIs]
                                          |
                                          v
                                   [Postgres / Redis]
                                   (logs, cache, quotas)
```

The data plane concerns — request transformation, retry, streaming — live in the gateway process. The control plane concerns — keys, budgets, routing rules, audit logs — live in the backing database. This split is important because it lets ops teams change routing without redeploying the gateway.

In Kubernetes-native setups, the gateway usually runs as a Deployment with HPA on request volume, with provider credentials mounted as Secrets. Cloudflare's [AI Gateway](https://developers.cloudflare.com/ai-gateway/) and AWS's [Bedrock AgentCore Gateway](https://aws.amazon.com/bedrock/agentcore/) offer managed versions of the same shape, with the data plane at the edge and the control plane in their respective clouds.

## The Hard Parts

AI gateways solve real problems and create new ones. Three things bite teams in production.

**Streaming is awkward.** Chat completions stream via Server-Sent Events, and so do most providers. The gateway has to re-stream while measuring tokens, applying policy, and writing logs — all without adding perceptible latency. Most gateways do this fine, but the streaming path is the first place to look when debugging tail-latency regressions.

**Cost attribution is fragile.** Provider pricing changes. Token counts change. Prompt caching and reasoning tokens can show up on the bill but not in the response body. A serious gateway reconciles the response metadata against the provider's usage endpoint daily, because the in-band numbers lie. Teams that skip this step routinely underestimate spend by 15–25%.

**Caching is a security boundary.** A semantic cache is a database of prior prompts and answers. Treat it like one — encrypt at rest, scope per tenant, and never reuse cached completions across customers. The blast radius of a cache that leaks one tenant's answers into another's UI is large and quiet.

## When You Don't Need One

Counterpoint: not every team needs a gateway. If you ship one feature, talk to one provider, and have under a few thousand requests per day, a thin client is fine. The gateway earns its keep when you hit one of these:

- You use more than one provider, or plan to within six months.
- Cost attribution by team or feature is a real requirement, not a wish.
- You have compliance or PII requirements that need a single chokepoint.
- You're tired of paying the same provider outage tax every quarter.

If none of those apply, save the engineering hours.

## The Vendor Landscape

The space is moving fast. Worth knowing:

- **LiteLLM** — open source, Python, the de facto reference implementation.
- **Portkey** — managed gateway with strong observability and a clean config model.
- **Cloudflare AI Gateway** — edge-deployed, free up to a point, ideal for low-latency global apps.
- **OpenRouter** — consumer-facing router that doubles as a developer gateway.
- **Kong AI Gateway** — the API gateway incumbent, now with LLM plugins.
- **Envoy AI Gateway** — the service mesh crowd's answer; native to the Envoy data plane, CNCF-governed.

The fact that there is a list at all, and that Cloudflare and Kong both shipped one in 2024, tells you the category has arrived. Cloudflare's [announcement post](https://blog.cloudflare.com/announcing-ai-gateway/) and the [Envoy AI Gateway docs](https://gateway.envoyproxy.io/) are both worth reading to see how incumbents are positioning the pattern.

## Key Takeaways

- An AI gateway is a proxy that unifies access to LLM providers, exposing one API and translating to many. It is the API gateway pattern, applied to model traffic.
- The core features are routing, fallback, semantic caching, rate limiting, auth, observability, and policy. Each one pays for itself independently.
- LiteLLM is the most common starting point — open source, OpenAI-compatible, and covers the long tail of providers out of the box.
- Watch out for streaming latency, cost drift between in-band and billed tokens, and treating the cache like a security boundary.
- You probably don't need a gateway at 1,000 requests a day. You definitely need one at 1,000,000.

## Further Reading

- [LiteLLM documentation](https://docs.litellm.ai/docs/)
- [Cloudflare AI Gateway announcement](https://blog.cloudflare.com/announcing-ai-gateway/)
- [Portkey AI Gateway product page](https://portkey.ai/docs)
- [OpenAI production best practices](https://platform.openai.com/docs/guides/production-best-practices)
- [Envoy AI Gateway project docs](https://gateway.envoyproxy.io/)
- [Redis semantic caching for LLMs](https://redis.io/learn/how-to/solve-real-time-problems/ai/semantic-cache)