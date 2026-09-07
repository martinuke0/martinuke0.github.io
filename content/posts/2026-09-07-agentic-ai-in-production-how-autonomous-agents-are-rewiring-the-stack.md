---
title: "Agentic AI in Production: How Autonomous Agents Are Rewiring the Stack"
date: "2026-09-07T11:03:38.824"
draft: false
tags: ["agentic-ai", "llm", "orchestration", "rag", "tooling", "mcp"]
description: "Agentic AI moves beyond single prompts into autonomous loops that plan, call tools, and recover from failure. Here is how the stack actually works."
summary: "Agentic AI is the shift from one-shot prompting to autonomous loops that plan, call tools, observe results, and recover from failure. This guide walks through the core loop, the production patterns, and the infrastructure that makes agents viable at scale."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-agentic-ai-in-production-how-autonomous-agents-are-rewiring-the-stack.svg"
  alt: "Diagram of an agent loop with planning, tool use, and reflection stages."
  caption: ""
  relative: false
---

> **TL;DR** — Agentic AI replaces single-prompt LLM calls with autonomous loops that plan, call external tools, observe results, and recover from failure. In production, the model is only one piece of the system — orchestration, tool contracts, memory, and evaluation pipelines decide whether an agent is shippable or a demo.

## Why "Agentic" Is More Than a Marketing Label

Two years ago, most LLM applications were a single prompt in and a string of text out. The model was the application. If the prompt was good and the model was strong, the output was usable. If either was off, the user got a hallucination, a refusal, or a paraphrase of their own question.

Agentic AI inverts that picture. The model becomes one component inside a control loop that owns planning, action, and recovery. Instead of asking the model to produce a final answer, you ask it to produce the *next step*, observe the result of that step, and decide what to do next. The agent runs until it hits a termination condition — task done, budget exhausted, or stuck.

Three things make this shift stick in 2026:

1. **Reasoning models** (o1-style, Claude extended thinking, DeepSeek-R1) spend inference-time compute on planning and self-critique. That makes the inner loop dramatically more reliable than the "stochastic parrot" era.
2. **Standardized tool protocols** — most importantly the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) — give agents a typed, composable way to talk to databases, browsers, internal APIs, and IDEs.
3. **Production infrastructure has caught up.** Durable execution engines (Temporal, Inngest, Restate), vector stores that handle billions of embeddings, and policy layers for tool authorization are all shipping in real systems, not just research prototypes.

The result is that teams are now shipping agents that genuinely do work, not just talk about doing work.

## The Anatomy of an Agent Loop

Strip away the marketing and every agent in production looks like a variant of the same control loop. The [Anthropic guide to building effective agents](https://www.anthropic.com/news/building-effective-agents) and the [AWS prescriptive guidance on agents](https://aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/introduction.html) both describe this same structure, sometimes under different names.

The canonical loop has five stages:

1. **Perceive** — read the user request, retrieve relevant memory, gather available tool definitions.
2. **Plan** — decide what to do next, usually expressed as a structured action (a tool call, a sub-task, or a final answer).
3. **Act** — execute the chosen action against an external system: a SQL database, a browser, a vector store, a code interpreter, a third-party API.
4. **Observe** — capture the result, normalize errors, and update internal state.
5. **Reflect** — judge whether the result advances the goal. If yes, continue or finish. If no, replan or escalate.

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass
class AgentState:
    goal: str
    history: list[dict] = field(default_factory=list)
    budget: int = 12  # max loop iterations

    def record(self, step: dict) -> None:
        self.history.append(step)

    def exhausted(self) -> bool:
        return len(self.history) >= self.budget

def run_loop(state: AgentState, model, tools) -> dict:
    while not state.exhausted():
        decision = model.decide(state.goal, state.history, tools.schemas())
        if decision.kind == "final":
            return decision.answer
        result = tools.invoke(decision.tool, decision.args)
        state.record({"decision": decision, "result": result})
    return {"status": "incomplete", "history": state.history}
```

The `budget` field matters more than people realize. Without an explicit cap on loop iterations, an agent with a flaky tool will burn tokens forever. Production agents almost always enforce a hard ceiling, then degrade gracefully to a partial answer or a human handoff.

## Patterns in Production

The term "agent" hides at least five distinct architectures. Picking the wrong one is the most common reason agent projects fail.

### 1. Single-Agent with Tools

One model, one loop, a handful of carefully scoped tools. This is the right starting point for almost everything. Stripe's documentation assistant and Notion's Q&A both started here.

**When to use:** Tasks with a small, well-defined surface area — answering questions from a knowledge base, querying a database, generating code from a repo, summarizing a webpage.

**When to avoid:** Anything that requires parallel research, long-horizon planning, or domain expertise that one prompt cannot hold.

### 2. Multi-Agent Orchestration

A planner agent delegates to specialist sub-agents. Each sub-agent has its own prompt, its own tools, and usually its own context window. Anthropic's [multi-agent research system](https://www.anthropic.com/research/building-effective-agents) and Microsoft's [AutoGen](https://github.com/microsoft/autogen) both implement variations of this.

The benefit is modularity — you can swap a "researcher" agent without rewriting the planner — and parallelism, because sub-agents can work on independent subtasks concurrently. The cost is coordination overhead and the failure modes that come with it: one sub-agent can hand the planner a confidently wrong summary, and the planner has no way to detect that without its own verification pass.

### 3. Orchestrator-Worker

A central orchestrator holds the canonical state and dispatches workers. This is the pattern behind most "agentic workflow" products from [LangGraph](https://langchain-ai.github.io/langgraph/), [CrewAI](https://github.com/crewAIInc/crewAI), and [Inngest](https://www.inngest.com/docs/agents). Workers do not talk to each other directly; they only talk to the orchestrator.

This pattern is popular because it maps cleanly onto durable execution. Every worker step is a checkpoint, so if the agent crashes mid-loop, you resume from the last successful step rather than restarting.

### 4. Plan-and-Execute

The agent first generates an explicit, numbered plan, then executes it step by step, re-reading the plan at each iteration. This is the [LangChain Plan-and-Execute](https://python.langchain.com/docs/modules/agents/agent_types/plan_and_execute) pattern and the [ReAct](https://arxiv.org/abs/2210.03629) paper in different clothes.

Plan-and-execute gives you a traceable artifact — you can show them the plan, and they can correct it before any tool fires. That makes it the safest pattern for high-stakes workflows where humans need to inspect what the agent is about to do.

### 5. Computer-Use Agents

The newest category: agents that drive a browser or a desktop like a human would. [Anthropic's computer use](https://docs.anthropic.com/en/docs/build-with-claude/computer-use) and [OpenAI's Operator](https://operator.chatgpt.com/) are the most visible examples.

These are the most fragile and the most expensive. They are also the most general — they can reach any software a human can reach, without an integration project. Treat them as a fallback for long-tail tasks that no team will ever build a tool for.

## The Tool Layer: MCP and Why It Matters

The unglamorous reason most agent projects die is that tool integration does not scale. Each tool needs a JSON schema, an authentication story, an error contract, and a way to handle retries. Doing that for ten tools by hand is fine. Doing it for a hundred is not.

The [Model Context Protocol](https://modelcontextprotocol.io/) is emerging as the default. MCP is a JSON-RPC based protocol where a host application (your agent runtime) connects to one or more *servers* that expose a set of tools with typed inputs and outputs. The server side handles auth, rate limiting, and resource access. The client side just calls `tools/call` with a name and arguments.

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "tools/call",
  "params": {
    "name": "postgres_query",
    "arguments": {
      "sql": "SELECT count(*) FROM orders WHERE created_at > now() - interval '7 days'"
    }
  }
}
```

The practical consequence is that an agent runtime (Claude Desktop, Cursor, a custom Python service) can talk to a Postgres MCP server, a GitHub MCP server, a Sentry MCP server, and a Notion MCP server using the exact same protocol. You build the integration once on the server side, and every compatible client gets it for free.

This is the same shape as LSP (Language Server Protocol) had for editors — a thin, well-designed protocol that turns N×M integration pain into N+M. The registry at [modelcontextprotocol/servers](https://github.com/modelcontextprotocol/servers) already lists hundreds of community-maintained servers.

## Memory: The Part Most Demos Skip

Stateless agents are toys. Useful agents remember. Memory usually splits into three tiers:

- **Working memory** — the contents of the current loop: the goal, recent tool calls, recent observations. Almost always just a list of messages.
- **Episodic memory** — past interactions, indexed by similarity, retrieved at the start of new sessions. Stored in a vector database like [pgvector](https://github.com/pgvector/pgvector), [Weaviate](https://weaviate.io/), or [Qdrant](https://qdrant.tech/).
- **Procedural / semantic memory** — long-lived facts about the user, the project, or the company. Often stored as a structured profile plus a vector index, and updated when an explicit extraction step runs.

The hard problem is not storing memory. It is deciding what to forget. A memory store that grows unbounded will eventually include contradictory, stale, or low-signal entries that the agent retrieves confidently and acts on incorrectly. Production systems run an explicit consolidation step — usually a smaller model — that summarizes, deduplicates, and prunes the memory store on a schedule.

## Evaluation: The Difference Between Demos and Production

You cannot ship an agent without evaluating it. But unlike a classifier, an agent's output is a trace, not a label. You have to grade the whole trajectory.

Three layers of evaluation matter:

1. **Outcome evaluation** — did the agent accomplish the task? For a SQL agent, did it return the right rows? For a coding agent, did the tests pass? This is the most important signal and the hardest to automate, because "right" often requires a domain expert.
2. **Trajectory evaluation** — did the agent take a reasonable path? Even when the final answer is correct, you want to catch agents that took ten steps when three would have done, or hallucinated a tool that doesn't exist. Tools like [LangSmith](https://docs.smith.langchain.com/), [Arize Phoenix](https://phoenix.arize.com/), and [Braintrust](https://www.braintrust.dev/) are built for this.
3. **Safety evaluation** — did the agent stay inside its guardrails? Did it call only the tools it was authorized to call? Did it leak PII? Did it fall for a prompt injection hidden in a fetched webpage?

A useful pattern is to run an "LLM-as-judge" evaluator on every production trace and store the result alongside it. Even imperfect judges catch regressions in aggregate. The [Anthropic guide to agent evaluation](https://docs.anthropic.com/en/docs/build-with-claude/test-and-evaluate/strengthen-guardrails/eval-driven-development) and the [DeepEval framework](https://github.com/confident-ai/deepeval) are good starting points.

## Failure Modes That Bite

Every production agent system I have seen shipped has been bitten by at least three of these. Listing them explicitly saves a quarter of debugging.

- **Tool hallucination.** The agent invents a tool that does not exist, or calls an existing tool with the wrong argument shape. Fix: strict schema validation at the tool boundary, plus reflection prompts that ask the model to verify tool names before invocation.
- **Context rot.** As the context window fills, the model starts ignoring earlier instructions. Fix: aggressive summarization, explicit "current task" reminders, and structured state outside the context window.
- **Prompt injection.** A tool fetches a webpage or a document that contains adversarial instructions telling the agent to exfiltrate data. Fix: treat all tool outputs as untrusted, never echo them directly into privileged tool calls, and run a separate classifier over tool outputs.
- **Loop thrash.** The agent gets stuck repeating the same failed step because its reflection step is weak. Fix: hard iteration budget, deduplication of recent actions, and an explicit "give up and ask the user" path.
- **Cost blowup.** A reasoning model plus a long tool loop plus a verifier model adds up fast. A single misconfigured agent can burn thousands of dollars per run. Fix: per-request cost caps, cheaper models for sub-tasks, and observability that surfaces cost per trajectory.
- **Silent partial success.** The agent returns a plausible-looking answer but one step silently failed and was ignored. Fix: every tool call must return a typed result that the agent is forced to read and acknowledge.

## A Reference Stack

If you were building a serious agent system today, this is roughly the stack you would converge on:

| Concern | Production pick |
| --- | --- |
| Reasoning model | Claude, GPT, Gemini, or open weights like DeepSeek-R1 |
| Cheap model for sub-tasks | GPT-4o-mini, Claude Haiku, Llama 3.x small |
| Orchestration | LangGraph, Temporal, Inngest |
| Tool protocol | MCP servers, one per integration |
| Vector store | pgvector, Weaviate, or Qdrant |
| Memory | Working = messages, episodic = vector store, semantic = structured profile |
| Evaluation | LangSmith or Braintrust with an LLM-as-judge |
| Observability | OpenTelemetry traces + a tool-call log |
| Guardrails | Output classifier + tool authorization policy |
| Hosting | Containers on Cloud Run, Fly, ECS, or Modal |

The point is not that this stack is the only one. The point is that "an LLM plus a prompt" is not on the list, and that is exactly the shift agentic AI represents. The model is the brain, but the body, the hands, and the guardrails are the rest of the system.

## Key Takeaways

- **An agent is a control loop, not a prompt.** Plan → act → observe → reflect, with a hard iteration budget.
- **Tool contracts are the real interface.** MCP is becoming the default protocol for exposing typed tools to any compliant agent.
- **Memory is tiered.** Working memory lives in the loop, episodic memory in a vector store, semantic memory in a structured profile, and all of it needs a consolidation step.
- **Evaluation is trajectory-shaped.** You have to grade the path the agent took, not just the final answer, and you have to do it on every production trace.
- **Failure modes are predictable.** Tool hallucination, context rot, prompt injection, loop thrash, cost blowup, and silent partial success — plan for all six from day one.
- **Start with a single agent and a handful of tools.** Promote to multi-agent orchestration only when the single-agent design hits a wall you can name.

## Further Reading

- [Anthropic: Building Effective Agents](https://www.anthropic.com/news/building-effective-agents)
- [Model Context Protocol specification](https://modelcontextprotocol.io/)
- [AWS Prescriptive Guidance: Agentic AI Patterns](https://aws.amazon.com/prescriptive-guidance/latest/agentic-ai-patterns/introduction.html)
- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
- [Braintrust: What we learned building evals for agents](https://www.braintrust.dev/blog)
- [OpenAI: A Practical Guide to Building Agents](https://platform.openai.com/docs/guides/agents)