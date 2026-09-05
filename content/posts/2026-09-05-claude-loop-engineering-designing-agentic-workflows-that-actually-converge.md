---
title: "Claude Loop Engineering: Designing Agentic Workflows That Actually Converge"
date: "2026-09-05T18:28:13.582"
draft: false
tags: ["claude", "agentic-ai", "llm", "prompt-engineering", "workflow-design"]
description: "A field guide to designing reliable Claude agentic loops with guardrails, tool schemas, and stop conditions that ship in production."
summary: "Claude loop engineering is the practice of building bounded, observable, tool-using agentic workflows on top of Anthropic's Claude. This post covers loop anatomy, stop conditions, tool design, and the production patterns that keep agents from drifting, looping forever, or burning budget."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-claude-loop-engineering-designing-agentic-workflows-that-actually-converge.svg"
  alt: "Abstract diagram of an agent loop with tool calls, scratchpad, and termination gates."
  caption: ""
  relative: false
---

> **TL;DR** — Claude loop engineering is the discipline of wrapping Claude in a deterministic outer loop — tool calls, scratchpad memory, validators, and stop conditions — so that an otherwise stochastic model becomes a reliable agent. Production-grade loops converge, are bounded by step and cost budgets, validate every tool result, and expose state for debugging.

## Why "Just Call the API" Isn't Enough

A raw Claude invocation is a function: it takes a prompt and returns text. An agent is something else entirely — a system that can decide what to do next, call tools, observe results, and iterate until a goal is reached. The model is the brain; the loop is the nervous system.

In production, teams quickly discover that prompt-only designs collapse under real workloads. A research agent that can search the web, read PDFs, and write a report needs hundreds of small decisions. A coding agent that edits files and runs tests needs to recover from syntax errors, missing imports, and flaky test suites. Without a thoughtfully engineered outer loop, these systems:

- Loop indefinitely on the same tool call because the model cannot tell progress from repetition.
- Burn thousands of tokens on a single task because every observation is repeated verbatim in the next prompt.
- Crash on malformed tool outputs because no schema validation exists at the boundary.
- Produce answers that look right but quietly violate an invariant the user assumed.

Loop engineering is the answer to all four. It treats the LLM as an untrusted component inside a deterministic harness, and that harness does most of the heavy lifting.

## The Anatomy of a Claude Agent Loop

Every well-built Claude loop has the same five moving parts. Treat this section as the reference diagram you'll mentally return to while reading the rest of the post.

1. **Goal / system prompt.** A static, version-controlled declaration of the agent's role, the tools available, the output schema, and the constraints. This is the contract.
2. **Scratchpad / working memory.** A structured store (usually JSON) of what it has done, what it learned, and what remains. Persisted across steps so the model does not have to re-derive state from conversation history.
3. **Tool registry.** A typed list of callable functions with JSON schemas. Each tool wraps an external system — a database, a search API, a shell command, a vector store.
4. **Driver / executor.** The outer loop itself. It calls Claude, parses the response, dispatches tool calls, validates outputs, updates the scratchpad, and decides whether to continue.
5. **Termination gate.** The condition under which the loop stops. Usually a combination of "model emitted `final_answer`", "max steps reached", and "validator passed".

A minimal Python sketch of this skeleton looks like the following. It is intentionally simplified — real implementations add tracing, retries, and concurrency — but the shape is what matters.

```python
import anthropic
import json
from typing import Callable

client = anthropic.Anthropic()
MAX_STEPS = 25
MAX_COST_USD = 0.50

def run_agent(goal: str, tools: dict[str, Callable], scratchpad: dict) -> dict:
    scratchpad.setdefault("steps", [])
    for step in range(MAX_STEPS):
        prompt = render_prompt(goal, tools, scratchpad)
        message = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            tools=[t.schema for t in tools.values()],
            messages=prompt,
        )
        scratchpad["steps"].append({"role": "assistant", "content": message.content})

        if message.stop_reason == "end_turn":
            return parse_final_answer(scratchpad)

        for block in message.content:
            if block.type == "tool_use":
                result = dispatch(tools, block, scratchpad)
                scratchpad["steps"].append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": block.id, **result}],
                })
    return {"status": "max_steps_exceeded", "scratchpad": scratchpad}
```

Two details are worth lingering on. First, the prompt is **rendered** from state, not concatenated from history — this is how you keep context bounded. Second, `scratchpad["steps"]` is the single source of truth the next turn sees; everything else is derivative.

## Patterns in Production: The Four Loop Shapes

Most production Claude loops collapse into one of four shapes. Choosing early saves a rewrite later.

**1. Single-shot with tools.** The model gets one chance to call tools and produce a final answer. Best for structured extraction, classification with lookup, and SQL generation over a known schema. No iteration, no scratchpad mutation, very cheap.

**2. Plan-and-execute.** The first turn produces a plan (a list of subtasks); subsequent turns execute one subtask at a time. Excellent for long, multi-source research where each subtask can be validated before continuing. This is the shape behind most retrieval-augmented research agents.

**3. ReAct-style reactive loop.** No explicit plan; the model reasons, acts, observes, and reasons again. Powerful for open-ended coding and debugging where the next step genuinely depends on the last result. Vulnerable to drift without strong stop conditions, which is the topic of the next section.

**4. Evaluator–optimizer.** Two roles, one loop. A "worker" produces a candidate; an "evaluator" Claude call scores it against a rubric; if below threshold, the worker retries with feedback. Slower and more expensive, but produces dramatically higher quality on subjective tasks like draft emails or design critiques. The same shape is documented in Anthropic's [building effective agents](https://www.anthropic.com/research/building-effective-agents) write-up.

The right shape is rarely the most general one. A reactive loop on a classification problem is over-engineering; a single-shot on a multi-source research task is a recipe for hallucinated citations.

## Stop Conditions: The Hardest Part

If loop engineering has a single most failure-prone area, it is termination. Three classes of bad termination show up repeatedly in incident reports.

- **Premature stop.** The model emits `final_answer` after two steps because the prompt made the goal sound easy. Output is incomplete.
- **Infinite loop.** The model calls the same search tool, gets similar results, calls it again. Token spend climbs, the user gets nothing.
- **Drift stop.** The model loses the thread, hallucinates a `final_answer` that has nothing to do with the original goal, and exits cleanly.

Defending against all three requires redundant gates.

```text
STOP if any of:
  1. Model emitted final_answer AND validator(answer) == ok
  2. len(steps) >= MAX_STEPS
  3. cumulative_cost_usd >= MAX_COST_USD
  4. scratchpad.last_3_actions_are_identical()   # loop detection
  5. scratchpad.goal_progress_estimate < 0 for K consecutive steps
```

The fourth and fifth conditions are the ones practitioners skip, then regret. Action hashing — a SHA of `(tool_name, sorted(args))` — catches loops that vary their prose but repeat their work. Progress estimation is harder; the cheapest version is to require the model to write a one-line "progress" field on every step and alert when it stops advancing.

For cost, never rely on the model's own accounting. Track prompt and completion tokens at the harness layer and convert to dollars using the [Anthropic pricing](https://docs.anthropic.com/en/docs/about-claude/pricing) page updated at deploy time. A cost budget that the loop itself enforces is the difference between a $3 task and a $300 incident.

## Tool Design: The Contract Layer

Tools are the surface area of your agent. Every tool is a contract between a probabilistic model and a deterministic system, and weak contracts produce weak agents. Three rules cover most of what matters.

**Schemas must be restrictive.** Use `enum` for any field with a closed set of values. Mark required fields explicitly. Use `description` to encode the *intent* of the field, not just its type — Claude reads these and uses them to choose arguments. A schema like `"priority": {"type": "string", "description": "P1 (outage), P2 (degraded), P3 (single user), P4 (cosmetic). Default P3."}` produces dramatically better routing decisions than `"priority": {"type": "string"}`.

**Errors must be structured.** When a tool fails, return a JSON object the model can act on — never a raw stack trace.

```json
{
  "ok": false,
  "error_code": "rate_limited",
  "retry_after_seconds": 12,
  "human_message": "Search backend is throttling. Try a narrower query or wait 12s."
}
```

The `human_message` field is what the model will see and quote back to you in its next reasoning step. Make it useful.

**Tools must be idempotent where possible.** A tool that creates a ticket, sends an email, or charges a card should accept a client-supplied idempotency key. Without this, a retry inside the loop double-fires. Stripe's [idempotency design](https://docs.stripe.com/api/idempotent_requests) is the canonical reference even outside payments.

## Memory: Scratchpad vs. Long-Term Store

A persistent confusion in agent design is where memory lives. The answer is: in two places, with very different rules.

The **scratchpad** is volatile, per-run, and read every step. It holds the goal, the plan, recent observations, and any state the model needs to make the next decision. It should be small — kilobytes, not megabytes. If your scratchpad is growing past a few thousand tokens, your agent is trying to use it as a database.

The **long-term store** is a vector database or key-value store accessed via a tool. The agent does not "remember" it across runs; it *queries* it. This is the right place for user preferences, prior conversation summaries, and institutional knowledge.

A common pattern is to give the agent two memory tools: `memory_search(query)` and `memory_write(key, value)`. The model's job is to decide when to read and when to write. Treat writes as untrusted input — validate, dedupe, and namespace them. Treat reads as the agent's own responsibility; do not silently inject memory into the system prompt, because that hides what the model is actually using.

## Architecture: A Reference Deployment

Putting it together, a reference Claude loop in production typically looks like this in terms of moving parts and their boundaries.

- A stateless driver service (Python or TypeScript) that holds the loop and is horizontally scalable.
- A Redis or Postgres-backed scratchpad store so a step can be resumed after a worker crash.
- A tool gateway that wraps every external call with auth, rate limiting, retries, and tracing. Every tool call is a separate microservice in disguise.
- An LLM gateway that handles model routing, prompt templating, and token logging — Anthropic's [Messages API](https://docs.anthropic.com/en/api/messages) reference describes the wire format.
- An evaluation harness that replays production scratchpads through new prompt revisions before rollout.

The driver never talks to Anthropic, the database, or the search backend directly. Every dependency is behind a tool, every tool is behind the gateway, and every gateway emits OpenTelemetry traces. When something goes wrong at 3 a.m., the on-call engineer reads a trace, not a log file.

A useful trace for a multi-step agent looks like this, and is usually emitted as a single OpenTelemetry span per step:

```text
agent.run: task="summarize Q3 incidents"
  ├─ llm.call: model=claude-sonnet-4-5, prompt_tokens=2140, completion_tokens=412
  ├─ tool.dispatch: tool=incident_search, args={since: "2025-07-01", severity: ["P1","P2"]}
  ├─ tool.dispatch: tool=incident_search, args={since: "2025-07-01", severity: ["P1","P2"]}
  ├─ loop_detected: identical_action_streak=2, action_hash=8f3a...
  └─ agent.terminate: reason="loop_detected", steps=2, cost_usd=0.043
```

Notice that the trace makes the failure legible: the model called the same tool twice with identical arguments, the harness detected it, and it terminated cleanly. The user gets a "could not find diverse sources" message instead of a $4 invoice.

## Prompting the Loop, Not Just the Model

A subtle but important shift: when you build a loop, you are no longer prompting a model — you are prompting a *state machine whose next state is partially chosen by the model*. The prompt's job changes.

Concretely, the system prompt should describe:

- The available tools and when to prefer each.
- The structure of the scratchpad and what fields are reserved (the model should not free-form them).
- The exact format of `final_answer`, including any required fields like `confidence` or `sources`.
- The termination contract: that the loop will be killed, not just nudged, if it repeats itself.

A useful pattern is to end the system prompt with a short "rules" section phrased as prohibitions. Phrasing as prohibitions is more reliable than phrasing as encouragements — Claude attends more to "Do not call the same tool with the same arguments twice" than to "Please vary your approach". This is consistent with the broader prompting guidance in Anthropic's [Claude docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview).

## Observability Is the Product

The unglamorous truth is that the difference between a Claude loop that ships and one that gets rolled back is observability. Three signals matter.

- **Step-level traces** with prompt, completion, tool calls, and tool results. Without these, debugging an agent is guesswork.
- **Outcome metrics** — task success rate, human-edit distance, escalation rate — measured against a held-out eval set, not just spot checks.
- **Cost and latency distributions**, p50 and p95, broken down by task type. A regression here is usually the first sign of a prompt change that quietly increased reasoning length.

Langfuse, Helicone, and Arize Phoenix are all reasonable choices for the tracing layer; pick on the basis of your existing stack rather than features. The point is not the tool — it is that you can answer "what did this agent do at step 7 of run 8f3a..." in under a minute.

## Key Takeaways

- **The loop is the product.** A raw Claude call is a function; a Claude loop is a system. Spend your engineering time on the harness, not the prompt.
- **Pick a loop shape early.** Single-shot, plan-and-execute, ReAct, and evaluator–optimizer each fit different problems. Over-generalizing is the most common cause of runaway agents.
- **Termination is multi-signal.** Combine the model's `final_answer` with step limits, cost budgets, action-hash loop detection, and progress estimation. Any one alone will fail.
- **Tools are contracts.** Restrictive schemas, structured errors, and idempotency keys are not optional — they are what makes the model usable.
- **Separate scratchpad from long-term memory.** The first is small, per-run, and read every step. The second is queried via tools and validated at the boundary.
- **Trace everything.** If you cannot answer "what did the agent do at step N" in under a minute, you cannot safely ship the agent.

## Further Reading

- [Building Effective Agents — Anthropic Research](https://www.anthropic.com/research/building-effective-agents)
- [Messages API Reference — Anthropic Docs](https://docs.anthropic.com/en/api/messages)
- [Prompt Engineering Overview — Anthropic Docs](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [Pricing and Token Counting — Anthropic Docs](https://docs.anthropic.com/en/docs/about-claude/pricing)
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
- [LangGraph: Building Agentic Workflows with LangChain](https://langchain-ai.github.io/langgraph/)
- [Idempotent Requests — Stripe API Reference](https://docs.stripe.com/api/idempotent_requests)