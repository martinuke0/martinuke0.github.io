---
title: "LLM-to-LLM Communication: Why Hero-to-Hero Beats Hero-to-API"
date: "2026-09-04T12:46:36.437"
draft: false
tags: ["llm", "agentic-ai", "mcp", "multi-agent-systems", "architecture"]
description: "Why direct LLM-to-LLM communication beats brittle JSON tool calls, and how MCP, A2A, and Anthropic's recent work reshape agent design."
summary: "The next leap in agentic AI isn't a bigger model — it's how models talk to each other. Here's why LLM-to-LLM protocols like MCP and Google's A2A are replacing the brittle hero-to-API pattern."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-04-llm-to-llm-communication-why-hero-to-hero-beats-hero-to-api.svg"
  alt: "Two stylized neural networks exchanging structured messages instead of a single agent calling many tool APIs."
  caption: ""
  relative: false
---

> **TL;DR** — The classic agent loop ("hero LLM + N tool APIs") is hitting a wall at scale: tool sprawl, fragile JSON schemas, and context-window bloat. The emerging alternative is **hero-to-hero**: agents that negotiate, delegate, and verify work through structured inter-agent protocols like Anthropic's [Model Context Protocol](https://modelcontextprotocol.io) and Google's [Agent2Agent](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/). When two models can speak a native protocol instead of pretending to be REST clients, everything from auth to long-horizon planning gets cheaper and more reliable.

## The Hero-and-Tools Pattern Is Showing Its Cracks

For the last two years, the default mental model for an "AI agent" has been a single frontier model wrapped around a fat bundle of tool definitions. You take GPT-4o, Claude, or Gemini, paste in 40 function-calling schemas, and let the model decide which endpoint to hit. It works — until it doesn't.

Three failure modes keep showing up in production:

1. **Schema drift.** A vendor renames a field from `max_tokens` to `maxOutputTokens` and your carefully once-tuned agent now hallucinates parameter names.
2. **Context bloat.** Every tool description eats tokens. Once you cross ~60 tools, the model starts [primacy/recency-biasing](https://arxiv.org/abs/2307.03172) the tool list and ignoring the middle.
3. **No negotiation.** The hero LLM cannot say "I don't know what `customer_id` you mean, please clarify." It hallucinates or fails silently. There is no protocol for *asking*.

You can see this clearly in the way the big agent frameworks have evolved. [LangChain](https://www.langchain.com), [CrewAI](https://www.crewai.com), and [AutoGen](https://github.com/microsoft/autogen) all started with "LLM + lots of tools," and all of them have spent the last 12 months quietly shipping **multi-agent** primitives — supervisor loops, router agents, agent-as-tool wrappers. The industry is converging on the same conclusion: one hero isn't enough.

## What "Hero-to-Hero" Actually Means

Hero-to-hero is the idea that **the primary unit of work is an agent, not an API call.** Each hero is itself an LLM (often a smaller, cheaper, specialized one) plus a small, focused set of capabilities. Heroes communicate by exchanging structured messages in a protocol they both understand — not by stuffing each other's tool schemas into context.

Think of the difference this way:

- **Hero-to-API** is like a tourist in a foreign country pointing at pictures in a phrasebook. Every interaction is a translation.
- **Hero-to-hero** is like two diplomats who share a language. They can negotiate, hedge, escalate, and verify.

The shift is small in code but enormous in capability. A hero-to-hero agent can say:

- "I need a structured `customer_id` in UUID form. What namespace?"
- "I'm 80% confident in this answer; please verify against the source before acting."
- "I'm going to delegate subtask X to you; here is the relevant slice of context."

None of those are expressible in today's `function_calling` JSON.

## Three Protocols Actually Doing This in 2026

The space has moved from blog posts to shipped specs in the last nine months. Three matter right now.

### 1. Model Context Protocol (MCP) — Anthropic

[MCP](https://modelcontextprotocol.io) is the closest thing we have to a standard. It's a JSON-RPC-based protocol where a host application (Claude Desktop, Cursor, an IDE plugin) connects to **MCP servers** that expose tools, resources, and prompts over stdio or HTTP+SSE.

The key insight: tools are no longer "stuff the model sees in its prompt." They are *remote capabilities* that the model queries for on demand. The server returns a structured schema the model then interprets. As Anthropic's [MCP launch post](https://www.anthropic.com/news/model-context-protocol) puts it, MCP is "USB-C for AI applications" — a single connector shape that replaces dozens of bespoke integrations.

```python
# A minimal MCP server exposing one tool
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("weather-server")

@server.list_tools()
async def list_tools():
    return [Tool(
        name="get_forecast",
        description="Get the weather forecast for a latitude/longitude.",
        input_schema={
            "type": "object",
            "properties": {
                "lat": {"type": "number"},
                "lon": {"type": "number"},
            },
            "required": ["lat", "lon"],
        },
    )]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_forecast":
        forecast = await fetch_open_meteo(arguments["lat"], arguments["lon"])
        return [TextContent(type="text", text=str(forecast))]
```

But here's the underrated part: **MCP isn't just hero-to-tool, it's hero-to-hero in disguise.** An MCP server can itself be an LLM. You can wrap a specialist model (say, a fine-tuned SQL agent) in an MCP server and another hero LLM can call it the same way it calls a calculator. The protocol doesn't care what's on the other end. This is why [OpenAI](https://openai.com/index/mcp-support/), [Replit](https://docs.replit.com), [Sourcegraph](https://sourcegraph.com), and [Block](https://block.xyz) all adopted MCP within months — it's the substrate for both patterns.

### 2. Agent2Agent (A2A) — Google

In April 2025 Google published [A2A](https://github.com/google/A2A), specifically targeted at multi-agent workflows. A2A defines **Agent Cards** (think: structured capability manifests), **tasks** (stateful, long-running units of work), and **artifacts** (the typed outputs of those tasks). Communication happens over JSON-RPC 2.0 over HTTPS, with optional SSE streaming for partial results.

The crucial A2A pattern is **streaming partial answers**. A research agent can push incremental findings back to the orchestrator instead of blocking until completion. This composes naturally with hero-to-hero: the orchestrator can cancel, redirect, or escalate mid-flight.

```json
// An A2A Agent Card (truncated)
{
  "name": "financial-research-agent",
  "version": "1.2.0",
  "skills": [
    {
      "id": "earnings-summary",
      "description": "Summarize the most recent earnings call for a US ticker.",
      "inputModes": ["text"],
      "outputModes": ["text", "application/json"]
    }
  ],
  "authentication": { "schemes": ["bearer"] }
}
```

A2A was co-designed with 50+ partners including Atlassian, MongoDB, Salesforce, and ServiceNow. That consortium signal matters: it means real enterprise systems are getting first-class agent endpoints in 2026, not afterthought webhooks.

### 3. ANP / Agent Network Protocol — open-source community

Less mature but worth watching: [ANP](https://github.com/agent-network-protocol/AgentNetworkProtocol), an effort to give agents **DNS-style discovery** on the open web. Each agent publishes a manifest at a well-known URL; other agents find it, verify it cryptographically (W3C Verifiable Credentials), and negotiate a session. It's hero-to-hero with **no central registry**, which is the property most enterprise architects actually want.

## Architecture: A Hero-to-Hero Stack in Production

Here's a pattern that is shipping in real products as of this quarter — three heroes, one orchestrator, zero tool-spaghetti.

```text
┌──────────────────────────────────────────────────────────┐
│                 Orchestrator (Claude Sonnet)            │
│  - holds the user goal                                   │
│  - picks which specialist to invoke                      │
│  - owns the long-horizon plan                             │
└──────────────┬─────────────────────────┬────────────────┘
               │ A2A task                │ A2A task
               ▼                         ▼
┌──────────────────────┐    ┌────────────────────────────┐
│ Research Hero        │    │ Coding Hero                │
│ (small open model +  │    │ (Claude + MCP tools:       │
│  web search MCP)     │    │  shell, file edit, git)    │
│                      │    │                            │
│ streams partial      │    │ returns diff + tests       │
│ findings via SSE     │    │                            │
└──────────────────────┘    └────────────────────────────┘
               │                         │
               ▼                         ▼
        MCP (HTTP+SSE)             MCP (stdio)
   ┌────────────────────┐    ┌─────────────────────┐
   │ Web-search server  │    │ Sandbox filesystem  │
   └────────────────────┘    └─────────────────────┘
```

Why this beats the monolith:

- **Context stays small.** The orchestrator never sees raw search results; it gets a 200-token digest. The coding hero never sees the user's full chat history; it gets a self-contained ticket. Each model's context window is used for what it's *for*.
- **Failure is contained.** If the research hero hallucinates a URL, only its digest is wrong. The orchestrator can ask for a re-query with a tighter constraint. In a hero+tools monolith, one bad tool call corrupts the whole plan.
- **Models are swappable.** The research hero could be a 7B local model today and a frontier model tomorrow. Because the protocol is stable, no one else's code changes.

This is exactly the pattern OpenAI's [Agents SDK](https://openai.com/index/new-llm-agent-tools-and-evaluations-in-2026/) and Anthropic's [claude-agent-sdk](https://github.com/anthropics/claude-agent-sdk-python) are converging on: handoffs, sub-agents, and protocol-level isolation.

## Patterns in Production

### Pattern 1: Verifier-as-Peer

In a hero+tools setup, verification is bolted on — a regex, a unit test, maybe a second LLM call at the end. In hero-to-hero, **verification is a peer**. The orchestrator hands the coder hero a task; a *verifier* hero (often a different model family entirely — Claude verifying GPT-4o, or vice versa) reads the diff and pings back issues. The coder hero iterates. This is the pattern behind [Anthropic's agentic eval suite](https://www.anthropic.com/research/building-effective-agents) and is structurally what [SWE-bench Verified](https://www.swebench.com) measures.

The trick: because the verifier is a peer agent with its own context, it can **disagree usefully** — it can point at a specific line and say "this branch is unreachable" in language the coder understands.

### Pattern 2: Streaming Skills with Skill Discovery

Both MCP and A2A support late-binding: the orchestrator doesn't need to know the full tool list upfront. It can ask an agent card for its skills, pick one, and call it. This is huge for **skills marketplaces** — Block's [Goose](https://github.com/block/goose), for instance, ships with an MCP "skill library" you can browse at runtime.

```js
// Orchestrator discovering what a peer can do, lazily
const card = await fetch("https://agent.example.com/.well-known/agent-card.json");
const skills = card.skills.filter(s => s.id.startsWith("summarize-"));
```

### Pattern 3: Negotiated Context Instead of Dumped Context

The single biggest token saving in hero-to-hero comes from **negotiated payloads**. Instead of the orchestrator copying its full chat history to a sub-agent, it sends a *contract*: "here is the goal, here are the constraints, here is the format I expect back." The sub-agent's response is constrained by the contract. As [Anthropic's prompt caching work](https://www.anthropic.com/news/prompt-caching) and OpenAI's structured outputs both show, this kind of contract negotiation is where context-engineering actually lives.

## Why the Industry Is Moving This Way

The economic argument is sharper than the technical one. A hero LLM with 60 tool schemas costs roughly **3-5x more per request** than the same LLM with 6 tool schemas, because of input tokens alone — and that's before the latency hit from long contexts. With hero-to-hero, each model's context is small and fit-for-purpose, so you can:

- Run the orchestrator on a strong model (Sonnet, GPT-4o) and specialists on cheap models (Haiku, 4o-mini, local Llama). The math works out to roughly **60-80% cost reduction** on multi-step workflows, per Anthropic's [cost engineering case studies](https://www.anthropic.com/engineering/claude-code-best-practices).
- Cache skill descriptors and agent contracts independently, which composes with [prompt caching](https://platform.openai.com/docs/guides/prompt-caching).
- Localize PII — a privacy-sensitive hero never receives the full conversation, only the slice it needs. This is a compliance story as much as an architecture one.

## What This Means for the Next 12 Months

Three predictions I'd bet on:

- **MCP becomes table stakes.** By end of 2026, any agent framework that *doesn't* speak MCP will be the equivalent of a database that doesn't speak SQL. Anthropic's [public roadmap](https://modelcontextprotocol.io/development/roadmap) already shows registry, auth, and streaming extensions coming.
- **A2A wins the long-horizon orchestration layer.** MCP is great for tool access; A2A's task/artifact model fits long-running, multi-day workflows better. Expect the two to compose: MCP for capabilities, A2A for coordination.
- **"Agent" stops meaning "LLM with tools."** The term will start meaning **a speaking peer in a protocol**, the same way "service" stopped meaning "PHP script" and started meaning "anything with an HTTP endpoint."

## Key Takeaways

- Hero+tools works for ≤20 tools and short workflows. It breaks down via schema drift, context bloat, and inability to negotiate.
- Hero-to-hero puts agents at the protocol layer; tools become remote capabilities reachable on demand.
- MCP, A2A, and ANP are the three protocols worth tracking. MCP is winning the tool/server interface; A2A is winning the orchestrator/sub-agent interface.
- Real production wins in 2026 come from smaller contexts per agent, verifier-as-peer, and contract-based payloads — not from larger base models.
- If you're building an agent product today, design for hero-to-hero even if you ship hero+tools tomorrow. The protocol boundary is what gives you optionality.

## Further Reading

- [Anthropic — Model Context Protocol specification and launch announcement](https://modelcontextprotocol.io)
- [Google Developers Blog — A2A: A new era of agent interoperability](https://developers.googleblog.com/en/a2a-a-new-era-of-agent-interoperability/)
- [GitHub — google/A2A reference implementation and spec](https://github.com/google/A2A)
- [Anthropic — Building effective agents (architecture patterns)](https://www.anthropic.com/research/building-effective-agents)
- [OpenAI — MCP support and the Agents SDK](https://openai.com/index/mcp-support/)
- [GitHub — agent-network-protocol/AgentNetworkProtocol (ANP)](https://github.com/agent-network-protocol/AgentNetworkProtocol)