---
title: "Building an Agent from Scratch: A Production-Oriented Walkthrough"
date: "2026-09-07T11:06:58.189"
draft: false
tags: ["ai-agents", "llm", "python", "tool-use", "production-architecture"]
description: "Build a real AI agent from scratch: planning loops, tool use, memory, guardrails, and how to ship one that survives production traffic."
summary: "A working engineer's guide to building an LLM agent from zero: the planning loop, tool integration, memory, guardrails, and the production patterns that turn a demo into a service."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-an-agent-from-scratch-a-production-oriented-walkthrough.svg"
  alt: "Diagram of an LLM agent architecture with planning loop, tool calls, and memory layer."
  caption: ""
  relative: false
---

> **TL;DR** — An agent is just an LLM wrapped in a loop that decides what to do, calls tools, observes results, and repeats until done. The hard part isn't the loop — it's the memory model, tool contracts, error handling, and the observability that lets you debug a non-deterministic system in production.

Every team I talk to right now is building some flavor of an "agent." Most of them have the same story arc: a quick prototype that impressed the demo room, followed by six weeks of pain once it met real traffic. The reason isn't that agents are magic. It's that the patterns that make a demo feel alive — clever prompting, a few hand-wired API calls — are almost the opposite of the patterns that make a service survive Monday morning.

This post walks through how to build an agent from scratch with that production lens. We'll start from the minimal loop, then layer on the things you actually need: structured tool contracts, a real memory model, guardrails against runaway costs, and enough observability to debug a system that makes different decisions on every run.

## What an Agent Actually Is

Strip away the marketing and an agent is a very small idea: a language model running in a loop, deciding each turn whether to answer, call a tool, or stop. The Anthropic [building effective agents](https://www.anthropic.com/engineering/building-effective-agents) guide puts it well — the loop is a controller, not an oracle.

```python
# The entire agent, before we make it useful.
def agent(messages, tools, llm):
    while True:
        decision = llm.decide(messages, tools)
        if decision.stop:
            return decision.answer
        result = tools[decision.tool].run(**decision.args)
        messages.append(result)
```

That's the seed. Everything else in this post is about making that seven-line function safe, observable, and useful enough that someone will pay you to run it.

## The Architecture That Actually Ships

Most production agents I've seen share the same shape, even when the stack differs. Anthropic's [tool use documentation](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview), OpenAI's [function calling guide](https://platform.openai.com/docs/guides/function-calling), and Google's [ADK](https://google.github.io/adk-docs/) all converge on this layering, because it's the smallest structure that lets you reason about failure:

```text
┌─────────────────────────────────────────────┐
│  User Interface (chat, API, scheduled job)  │
└────────────────────┬────────────────────────┘
                     ▼
┌─────────────────────────────────────────────┐
│  Orchestrator (loop, retries, budget cap)   │
└─────┬───────────────────────────┬───────────┘
      ▼                           ▼
┌──────────────┐          ┌──────────────────┐
│  LLM Client  │          │  Tool Registry   │
└──────────────┘          └────────┬─────────┘
                                  ▼
                       ┌──────────────────┐
                       │  Tool Executors  │
                       │  (DB, HTTP, FS)  │
                       └──────────────────┘
```

Two pieces are worth calling out. First, the orchestrator is the only place that owns budget, retries, and termination — never the LLM. Second, the tool registry is a real abstraction, not a bag of functions. Tools have schemas, timeouts, idempotency keys, and cost metadata. The model just sees JSON.

## Step 1: Designing Real Tool Contracts

The single biggest mistake I see is treating tools as Python functions. They're contracts. A tool needs a name, a description, a JSON schema for arguments, a timeout, and a documented failure mode. OpenAI's [function calling docs](https://platform.openai.com/docs/guides/function-calling) and Anthropic's [tool use overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview) both treat them this way for a reason — the schema is what the LLM actually reads.

```python
from pydantic import BaseModel, Field

class SearchKnowledgeBase(BaseModel):
    query: str = Field(description="Natural language search query.")
    top_k: int = Field(default=5, ge=1, le=20)

TOOLS = {
    "search_kb": {
        "schema": SearchKnowledgeBase.model_json_schema(),
        "description": "Search the internal knowledge base. Returns ranked passages.",
        "timeout_s": 4.0,
        "cost_units": 1,
        "side_effect": False,
    },
    "create_ticket": {
        "schema": {...},
        "description": "Open a support ticket in the issue tracker.",
        "timeout_s": 8.0,
        "cost_units": 5,
        "side_effect": True,
        "requires_approval": True,
    },
}
```

The `side_effect` and `requires_approval` flags aren't in any vendor spec — they should be. The model needs to know that some tools change state in a system a human cares about. We'll lean on those flags in the guardrails layer.

### Tool Description Is Prompt Engineering

A tool description is the model's only API doc. Vague descriptions produce vague calls. "Useful for finding things" will get you hallucinated arguments. Compare:

```text
# Bad
description: "Search the knowledge base."

# Better
description: "Semantic search over indexed support docs and runbooks.
              Use for product how-tos, error messages, and policy questions.
              Do NOT use for account-specific data — use lookup_account instead."
```

The second version tells the model when to use the tool *and* when not to. That's half the battle with tool selection. Anthropic's [prompt engineering guide for tool use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use) goes deeper on this — the gist is that every ambiguous boundary between tools is a place the model will guess wrong.

## Step 2: The Loop With a Real Termination Policy

The naive loop terminates when the model says "stop." That works until a model decides to take seventeen steps to answer "what's the weather." You need three termination policies running together:

```python
def run_turn(state, tools, llm, budget):
    response = llm.decide(state.messages, tools.schemas())

    if response.stop:
        return Turn(action="answer", content=response.text)

    if not tools.is_known(response.tool):
        return Turn(action="retry",
                    content=f"Unknown tool {response.tool}. Pick from {list(tools)}.")

    if budget.steps_exhausted():
        return Turn(action="answer",
                    content="I couldn't finish in the allotted steps. Here's what I know so far.")

    if budget.tokens_exhausted():
        return Turn(action="answer",
                    content="I ran out of budget. Escalating to a human.")

    result = tools.execute(response.tool, response.args, timeout=budget.remaining_timeout())
    return Turn(action="observe", tool=response.tool, result=result)
```

Three things to notice. First, unknown tool names are a normal outcome, not an exception — we return a retry message instead of crashing. Second, budget checks happen *before* the tool runs. Third, exhausted budgets don't silently fail; they produce an honest partial answer. This is the difference between a demo and a service.

The [Anthropic prompt library](https://docs.anthropic.com/en/resources/prompt-library/library) has worked examples of this kind of "if you can't finish, say so" instruction — bake it into your system prompt.

## Step 3: Memory That Isn't Just "Append Everything"

Long-context models have made memory look easier than it is. Appending every turn works until the 100th message, when you blow the context window, double your costs, and make the model ignore old instructions because they got pushed out by logs.

A working memory model has three tiers:

```text
┌──────────────────────────────────────────┐
│  Working memory   — full recent turns    │
│  Episodic memory  — summaries of older   │
│                     turns, indexed by    │
│                     topic and time       │
│  Semantic memory  — extracted facts,    │
│                     user prefs, entity   │
│                     graph entries        │
└──────────────────────────────────────────┘
```

For an MVP, working memory plus a simple summary tier is enough. Here's a minimal but real version:

```python
def build_context(history, summary, max_tokens):
    tokens = count_tokens(history)
    if tokens <= max_tokens:
        return summary + history

    keep = history[-6:]                         # last 3 turns
    older = history[:-6]
    new_summary = llm.summarize(summary, older)  # rolling summary
    return new_summary + keep
```

Episodic memory is where most teams over-build. You almost certainly do not need a vector DB on day one — you need a summary of older turns and the ability to grep them. Upgrade to retrieval when you can name a query that summaries genuinely fail. The [LangChain memory module](https://python.langchain.com/docs/concepts/memory/) and [LlamaIndex's memory docs](https://docs.llamaindex.ai/en/stable/module_guides/deploying/agents/memory/) are reasonable references for the patterns, though I wouldn't import either wholesale.

## Step 4: Guardrails — The Part That Pays For Everything

Here's the unsexy truth about agents in production: most outages aren't model failures, they're missing guardrails. A confused model calling a write tool 400 times is a billing event and a compliance report. Treat guardrails as the system, not a wrapper.

The minimum set that has saved me on multiple occasions:

```python
@dataclass
class Budget:
    max_steps: int = 12
    max_tokens: int = 80_000
    max_wallclock_s: float = 60.0
    max_dollars: float = 0.50

    def remaining(self) -> bool: ...

def execute(self, name: str, args: dict, timeout: float):
    tool = self.tools[name]
    if tool["requires_approval"] and not self.human_approved(name, args):
        return {"error": "approval_required", "tool": name}

    with timeout_guard(timeout), cost_counter(tool["cost_units"]):
        return tool["fn"](**args)
```

Three patterns to copy. **Budget objects**, not flags — one struct you check at every transition. **Approval gates** for anything with a side effect, even if your "approval" is a webhook to your own audit service. **Cost counters** that know the relative price of each tool, so a 12-step run that mostly hits cheap tools doesn't get cut off while a 3-step run that hits an expensive one does.

For policy enforcement — PII redaction, jailbreak filtering, schema validation — pair the agent with a small classifier or rule engine. The [Guardrails AI docs](https://www.guardrailsai.com/docs/) and [NeMo Guardrails](https://docs.nvidia.com/nemo/guardrails/latest/index.html) are both worth a look. Use them as libraries, not frameworks; you don't want their loop on top of yours.

### A Note on Non-Determinism

Two runs with the same input will produce different traces. That is by design. Your job is to make the *outputs* reliable, not the path. That means deterministic tool wrappers (no `time.now()` in tool results unless you mock it), seedable randomness where you can, and assertions on output shape rather than exact text.

## Step 5: Observability for Non-Deterministic Systems

You cannot debug an agent from a single log line. You need to see the entire decision tree of every run, replay it, and diff two runs that took different paths to the same answer. Standard APM won't get you there.

What to capture per run:

- Full message history (system, user, assistant, tool results)
- Every tool call with arguments, latency, and result
- Token counts at each step
- Budget state at each transition
- A trace ID that ties everything to your request logs

Langfuse, LangSmith, Helicone, Arize Phoenix — pick one. The [OpenTelemetry GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/) are a good north star even if your vendor doesn't fully implement them. The minimum is that every tool call is a span with attributes, every LLM call is a span with the prompt and completion redacted to taste, and the whole run has one parent span you can search by request ID.

If you only have one weekend, ship **a JSON dump of every run to S3** before you ship a vendor integration. That artifact will save you more production incidents than any dashboard.

## Patterns in Production

A few patterns that show up in every agent I've watched succeed or fail:

### Subagents, Not Mega-Loops

Long-running agents drift. The fix isn't a better prompt — it's decomposition. Anthropic's [multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) writes up their experience: each subagent gets a tight context, a small tool set, and a narrow goal. A coordinator stitches their outputs. This is the same insight microservices taught us a decade ago, applied to prompts.

### Tools With Idempotency Keys

Every write tool takes an `idempotency_key` derived from the agent's run ID and the step number. Your retry logic can now be aggressive without doubling up side effects. Stripe's [idempotency docs](https://docs.stripe.com/api/idempotent_requests) are still the cleanest writeup of the pattern.

### Async by Default

Tool calls dominate wall-clock time. If your orchestrator is synchronous you're paying for nothing. Even if you don't need full asyncio, fire independent tool calls in parallel and wait on them as a group. The [Anthropic parallel tool use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/implement-tool-use) example shows the pattern.

### Evaluation Is Part of the Codebase

You can't ship what you can't measure. The teams I've seen succeed maintain a small eval set — 50 to 200 cases — and run it on every change. The [OpenAI evals guide](https://platform.openai.com/docs/guides/evals) and Anthropic's evaluation cookbook are useful starting points, but the real lesson is discipline: evals die if no one runs them, and a dead eval is worse than no eval because it lies.

## When Not to Build an Agent

An honest post has to say this. Agents are the wrong choice when:

- A two-line classification prompt solves the problem.
- The workflow is fully deterministic and a DAG in Airflow or Prefect would do.
- You can't define what "done" looks like — agents need an objective, even a fuzzy one.

Anthropic's [when to use agents vs workflows](https://www.anthropic.com/engineering/building-effective-agents) post makes the same point: most "agent" use cases are really deterministic workflows with one LLM call per step. If you can write the graph down, write it down and save yourself the variance.

## Key Takeaways

- An agent is a loop plus a tool registry, not a magic box — keep that loop small and inspectable.
- Tools are contracts with schemas, timeouts, cost, and side-effect flags; the model only sees JSON.
- Budgets, approval gates, and idempotency keys are the difference between a demo and a production service.
- Memory needs tiers; appending everything to the context window is a slow-motion outage.
- Observability must capture full traces per run — non-deterministic systems cannot be debugged from single events.
- Decompose into subagents when loops grow long; deterministic workflows when they don't need to be agents at all.

## Further Reading

- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic — Tool Use Overview](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/overview)
- [OpenAI — Function Calling Guide](https://platform.openai.com/docs/guides/function-calling)
- [Google ADK Documentation](https://google.github.io/adk-docs/)
- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/)
- [Stripe — Idempotent Requests](https://docs.stripe.com/api/idempotent_requests)