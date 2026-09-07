---
title: "Agentic AI in 2026: What Stanford's Overview Actually Means for Working Engineers"
date: "2026-09-07T11:03:00.547"
draft: false
tags: ["agentic-ai", "llm", "machine-learning", "software-architecture", "mlops"]
description: "A practical engineering breakdown of agentic AI: how Stanford's framework maps to real systems, where it breaks, and what to build next."
summary: "Stanford's agentic AI overview offers a clean taxonomy, but production engineers need to know how the four-agent model, tool-use loops, and memory architectures translate into deployed systems — and where they fall apart."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-agentic-ai-in-2026-what-stanford.svg"
  alt: "Diagram of an LLM agent loop connecting perception, planning, tool use, and memory"
  caption: ""
  relative: false
---

> **TL;DR** — Stanford's 2025 overview frames agentic AI as four cooperating patterns (reflection, planning, tool use, multi-agent) layered over a perception–planning–action cycle. For working engineers, the value isn't the taxonomy — it's that production-grade agents now look more like distributed systems than chatbots, with hard ceilings around context length, tool reliability, and evaluation.

If you've spent the last two years building anything that calls an LLM, you've noticed the shape of the work has changed. We started with "write a prompt, get a paragraph." We moved to "stuff a PDF into context, ask a question." And now, in 2026, we spend most of our time reasoning about tool schemas, retry policies, vector store latency, and how to stop an agent from deleting the wrong row in Postgres.

That shift is what the Stanford agentic AI overview is really about. The taxonomy it proposes — *what counts as an agent* — matters less than the operational reality it points at: building a useful agent is a distributed systems problem wearing an LLM costume. This post unpacks that reality, section by section, with concrete patterns and production gotchas.

## What "Agentic" Actually Means in 2026

The word *agentic* has been stretched across roughly forty product launches and as many blog headlines. Stanford's overview narrows it to a working definition that engineers can actually build against:

> An **agentic system** is one in which an LLM selects actions, observes results, and iterates — with non-trivial autonomy over the trajectory it takes toward a goal.

Three properties follow from that definition, and they show up in every production agent I've seen:

1. **Goal-directed loop.** The model decides what to do next based on prior steps, not a fixed DAG.
2. **Tool use as a first-class capability.** The model emits structured calls that hit real systems — SQL, HTTP, files, browsers, code interpreters.
3. **Persistent state.** Conversation history, retrieved documents, scratchpads, and tool outputs accumulate across steps.

If your "agent" has none of those three, it's a pipeline with an LLM in the middle. That's fine — many useful systems are exactly that — but it isn't agentic.

### The Perception–Planning–Action Cycle

Every agent framework in production — LangGraph, CrewAI, AutoGen, OpenAI's Assistants runtime, Google's ADK — eventually bottoms out in the same loop:

```text
[Perceive] → [Plan] → [Act] → [Observe] → [Plan] → [Act] → ...
```

Perception is whatever the agent reads: user input, tool outputs, retrieved documents, prior messages. Planning is where most of the "intelligence" lives — the model picks the next action, often with chain-of-thought or a structured plan. Action is a tool call. Observation is the result, fed back into the loop.

What changes between frameworks is who owns each step and where state is stored. LangGraph leans on explicit graphs. CrewAI leans on role-based crews with delegated tasks. The Assistants runtime hides the loop behind a server-side thread. Underneath, all of them are running that same cycle, often dozens of times per user request.

## Stanford's Four Agentic Design Patterns

The overview's most useful contribution is a four-bucket taxonomy of *how* an agent gets smarter than a single forward pass. These aren't mutually exclusive — production agents stack them — but they are distinct design moves with distinct failure modes.

### Pattern 1: Reflection

The model critiques its own output and tries again. This is the cheapest pattern to implement and the one with the most ambiguous evidence. Two flavors show up in the wild:

- **Self-critique in one model.** Generate, then ask the same model "what's wrong with this?" and revise.
- **Critic as a separate model.** A weaker, faster model scores outputs; the main model revises based on scores.

In production, self-critique is mostly useful for narrow tasks where you can constrain the rubric — code style, JSON validity, tone. The [Anthropic guide to building effective agents](https://www.anthropic.com/news/building-effective-agents) explicitly recommends *against* reflection loops for tasks where the model already gets it right, because the revision step can introduce regressions. As the Anthropic team puts it: "Don't build an agent when a loop will do."

### Pattern 2: Planning

Planning means the agent produces (and updates) an explicit trajectory before acting. The classic move is to ask the model to emit a step-by-step plan, then execute it, optionally replanning after each step.

This is where the LangChain/LangGraph ecosystem has bet heavily — and where most production failures originate. A planner that's allowed to invent tools that don't exist will produce gorgeous-looking traces and useless outputs. The fix isn't fancier prompting; it's tool catalogs with strict schemas and a runtime that rejects unknown tool calls before they hit a real API.

```python
from typing import Literal
from pydantic import BaseModel

class PlanStep(BaseModel):
    step_id: int
    action: Literal["search_docs", "query_db", "send_email", "ask_user"]
    args: dict
    rationale: str
```

Constraining the action space to a literal enum is the single highest-leverage move you can make in an agent. It's also why typed tool definitions have quietly become the standard in frameworks like [Pydantic AI](https://ai.pydantic.dev/) and [MCP servers](https://modelcontextprotocol.io/).

### Pattern 3: Tool Use (and the Reliability Problem)

Tool use is where agents earn their keep — and where they break. Stanford's framing emphasizes that tool use isn't just "call an API." It's a contract between a stochastic system (the model) and a deterministic one (your service), and contracts need enforcement.

Concrete patterns that work:

- **Strict JSON schemas on every tool**, validated server-side. Pydantic, Zod, or your language equivalent.
- **Idempotency keys** on every mutating call. Agents retry. If your `delete_user` isn't idempotent, your agent will eventually delete the same user twice.
- **Sandboxing.** If a tool can run code, run it in [Firecracker](https://github.com/firecracker-microvm/firecracker) or [gVisor](https://gvisor.dev/), not on your agent's host.
- **Result truncation.** Tool outputs regularly exceed context windows. A search result that returns 200KB of HTML will break the next plan step. Truncate, summarize, or paginate before the model ever sees it.

The reliability problem isn't theoretical. Anthropic's own [evaluations of computer-use agents](https://www.anthropic.com/news/developing-computer-use) report success rates that look impressive in demos and disappointing in benchmarks. If you're betting production SLAs on an agent's tool calls, you need observability — every call logged with its arguments, return value, latency, and retry count — exactly like you'd instrument any other distributed service.

### Pattern 4: Multi-Agent Collaboration

Multiple agents, each with a role, hand off work to each other. CrewAI, AutoGen, and ChatDev popularized this pattern; LangGraph now supports it as a graph topology.

The honest version: most multi-agent systems shipped to date don't outperform a well-instructed single agent with tools. They cost more (more tokens, more latency), are harder to debug (whose context broke the conversation?), and often degrade into one agent doing all the work while the others echo.

The exception is when agents have genuinely different capabilities or contexts. A research agent with web search, a writer agent with a style guide, and an editor agent with a rubric is a reasonable decomposition. Three "general-purpose" agents talking in a loop is usually a waste of money. As one AutoGen maintainer [noted in a 2025 retrospective](https://microsoft.github.io/autogen/), the framework's own examples moved toward clearer role separation as the year progressed.

## Patterns in Production: What a Real Agent Stack Looks Like

Enough taxonomy. Here's the shape of an agent system that actually ships in 2026, with the moving parts named.

```text
                ┌──────────────┐
   user ───────▶│  API Gateway │
                └──────┬───────┘
                       │
                ┌──────▼───────┐    ┌─────────────┐
                │ Orchestrator │───▶│  LLM (plan)  │
                │  (LangGraph  │    └──────┬──────┘
                │   or custom) │           │
                └──────┬───────┘    ┌──────▼──────┐
                       │            │ Tool Router │
                       │            └──────┬──────┘
        ┌──────────────┼─────────────┐    │
        │              │             │    │
   ┌────▼────┐   ┌─────▼─────┐  ┌────▼───┐ ▼
   │ Postgres│   │  Vector   │  │  HTTP  │  ⇄ External APIs
   │ (state) │   │  Store    │  │ tools  │   (Stripe, GitHub, ...)
   └─────────┘   └───────────┘  └────────┘
```

A few things to notice, all of which the Stanford overview implies but doesn't draw.

### Memory Is a Database Problem

"Memory" in agent systems means three things, and they have different storage requirements:

- **Short-term / working memory** is the conversation thread. It's already handled by your framework (OpenAI's thread, LangGraph's checkpointer). Store it in Postgres or Redis with a TTL.
- **Long-term / semantic memory** is facts about the user or domain that should survive across sessions. This is a vector store problem: chunk, embed, retrieve on each turn. [pgvector](https://github.com/pgvector/pgvector) on Postgres is now the boring default for small-to-medium workloads; [Qdrant](https://qdrant.tech/) or [Weaviate](https://weaviate.io/) for larger ones.
- **Episodic / procedural memory** is "what worked last time." This is the experimental frontier — systems like [MemGPT](https://research.memgpt.ai/) push agents to manage their own memory hierarchies, but in production it's still hand-rolled.

The cardinal sin is treating all three as "just stuff the LLM remembers." None of them are.

### Tools Are Microservices

Every tool your agent can invoke should be:

1. **Versioned.** A schema change should not silently break agents in production.
2. **Authenticated.** Per-agent credentials with scoped permissions, not a shared service account.
3. **Observable.** Logs and traces per call. OpenTelemetry exporters into your existing tracing stack (Jaeger, Honeycomb, Tempo).
4. **Rate-limited.** Agents will hammer tools. If you don't rate-limit, the agent will DoS your downstream.

The Model Context Protocol (MCP) has emerged as the de facto standard for tool definition and discovery — Anthropic published it, and [OpenAI officially adopted it in 2025](https://modelcontextprotocol.io/). If you're starting a new agent project in 2026, build MCP servers for your internal tools. You'll thank yourself the first time you switch model providers.

### Evaluation Is the Hard Part

Stanford's overview doesn't dwell on evaluation, but for working engineers it's the whole game. A demo agent and a production agent are separated by evaluation infrastructure.

What you need, at minimum:

- **Golden sets** of (input, expected trajectory, expected outcome) tuples. ~50–500 of them, version-controlled.
- **LLM-as-judge** for subjective quality, with a separate held-out set of human-rated examples to calibrate the judge. Don't trust the judge until you've checked.
- **Tool-call accuracy** — did the agent call the right tool with the right args? Often easier to grade than end-to-end outcome.
- **Cost and latency budgets** — track tokens-per-task and seconds-per-task as first-class metrics.

The [LangSmith evaluation docs](https://docs.smith.langchain.com/) and [Braintrust's eval guide](https://www.braintrust.dev/docs) are the two most practically useful starting points I've seen. Both treat evals as CI gates, which is the only thing that prevents regressions when you swap models every six weeks.

## Where the Stanford Framing Breaks Down

It's worth being honest about where the overview's taxonomy falls over.

**The four-pattern model implies clean separation.** In practice, planning and reflection blend into the same forward pass; a model that "plans" with chain-of-thought is also implicitly reflecting on its own reasoning. The buckets are useful for teaching, less useful for architecture diagrams.

**It underplays the role of context engineering.** The biggest lever in modern agents isn't the prompt or the plan — it's what you put in the context window. Anthropic's own engineering blog has argued, persuasively, that [context engineering is the core skill](https://www.anthropic.com/engineering/building-effective-agents-with-claude) of agent design. The Stanford overview touches on retrieval but doesn't give it the weight it deserves.

**It doesn't engage with the safety story.** Agents that can take real actions need the same threat modeling as any privileged service: prompt injection via tool outputs, exfiltration via tool calls, runaway loops. The [OWASP top 10 for LLM applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/) is a better starting point than most academic surveys, and the overview doesn't link to it.

**It treats "agentic" as a binary.** It's a spectrum. A single LLM call with retrieval is at one end; a fully autonomous multi-agent system acting on production infrastructure is at the other. Most useful production systems sit somewhere in the middle, and labeling everything in that range as "agentic" obscures more than it reveals.

## Architecture Decisions That Actually Matter

If you're building an agent in 2026, five decisions will dominate your roadmap. They map loosely to the Stanford taxonomy but live in the implementation layer.

**1. Single agent vs. multi-agent.** Default to single. Multi-agent is justified only by a clear capability gap — different models, different contexts, different toolsets — that you can't bridge with a single well-instructed agent.

**2. Synchronous vs. streaming tool execution.** Streaming (the agent emits tokens while tools run) feels nice but complicates retry, cancellation, and observability. Start synchronous; add streaming only where user experience demands it.

**3. Where state lives.** Server-side threads (OpenAI Assistants, Anthropic's experimental memory API) are easy and opaque. Client-side state (you manage the messages array) is more work but gives you full control. Most serious systems end up hybrid: server-side for short-term, client-owned long-term memory.

**4. How you handle tool failure.** Plan for tools to fail. Decide upfront whether the agent retries, asks the user, or escalates to a human. Hard-code this in your orchestrator — letting the LLM decide leads to infinite retry loops.

**5. How you evaluate before deploy.** If you can't point to a numeric score on a held-out test set, you don't know whether your last change helped or hurt. Build the eval harness before you build the agent.

## Key Takeaways

- **Agentic AI is a distributed systems problem, not a prompting problem.** Memory, tool reliability, observability, and idempotency dominate the engineering work.
- **Stanford's four-pattern taxonomy (reflection, planning, tool use, multi-agent) is a teaching tool, not an architecture.** Production agents stack patterns; they don't pick one.
- **Tool contracts are the highest-leverage surface.** Strict schemas, versioned APIs, idempotency keys, and sandboxed execution are non-negotiable.
- **Memory is three different problems.** Short-term (thread), long-term (vector store), and episodic (still hand-rolled) — and they need different storage.
- **Evaluation is the moat.** A golden set, an LLM judge calibrated against human ratings, and CI-gated evals are the only way to ship agents that don't regress.
- **The biggest unstated lever is context engineering.** What you put in the window matters more than which pattern you pick.

## Further Reading

- [Reflections on Building Agentic Systems — Andrew Ng, DeepLearning.AI](https://www.deeplearning.ai/the-batch/agentic-ai/)
- [Building Effective Agents — Anthropic](https://www.anthropic.com/news/building-effective-agents)
- [Model Context Protocol Specification](https://modelcontextprotocol.io/)
- [LangGraph Documentation: Building Stateful Agents](https://langchain-ai.github.io/langgraph/)
- [OWASP Top 10 for LLM Applications](https://owasp.org/www-project-top-10-for-large-language-model-applications/)
- [pgvector: Vector Similarity Search in Postgres](https://github.com/pgvector/pgvector)