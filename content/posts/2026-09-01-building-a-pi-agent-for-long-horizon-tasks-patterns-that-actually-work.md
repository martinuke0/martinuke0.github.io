---
title: "Building a pi-agent for Long-Horizon Tasks: Patterns That Actually Work"
date: "2026-09-01T19:47:09.422"
draft: false
tags: ["ai-agents", "long-horizon", "llm", "tool-use", "agent-architecture"]
description: "A working engineer's guide to designing pi-agents that survive multi-hour, multi-tool tasks without drifting, looping, or losing state."
summary: "Pi-agents for long-horizon tasks need more than a clever prompt. This post covers the architecture, memory patterns, and failure modes that decide whether the agent finishes the job or burns budget on a loop."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-01-building-a-pi-agent-for-long-horizon-tasks-patterns-that-actually-work.svg"
  alt: "Diagram of a pi-agent control loop with memory, tools, and a verifier."
  caption: ""
  relative: false
---

> **TL;DR** — A pi-agent only earns the "long-horizon" label when it can run for hours across hundreds of tool calls without drifting, looping, or forgetting why it started. The winning pattern in production is a tight inner loop (think, act, verify) wrapped by persistent memory, an explicit plan, and a cheap verifier that catches garbage before it compounds.

## Why Long-Horizon Is a Different Problem

Short demos make agentic AI look easy. Give a model a browser, a shell, and a goal, and within twenty tool calls it has usually booked the flight, refactored the file, or pulled the report. The illusion breaks the moment the task stretches past an hour. Tool counts climb into the hundreds. Context windows fill with half-finished subtasks. The model's "objective" silently drifts toward whatever it was doing five minutes ago rather than the goal you set at the start.

This is the long-horizon problem, and it is the reason your clever weekend prototype quietly dies the first time you ask it to migrate a 40-service monorepo. The challenge is not smarter reasoning. It is **state management under unbounded execution**: how does an agent remember what it is doing, prove it is making progress, and refuse to keep grinding when it has lost the plot?

The name "pi-agent" comes from the original [π paper](https://arxiv.org/abs/2412.06707) by AI2 — though the concept generalizes beyond any single framework. A pi-agent treats execution as a program: an outer loop maintains persistent memory and a plan, while an inner loop executes individual steps with a tight think-act-verify cycle. That separation is the entire trick.

## The Two-Loop Architecture

The most reliable long-horizon agents I've shipped or reviewed share a common shape. There is an **outer loop** that owns the plan, the persistent state, and the high-level "should I keep going?" decision. There is an **inner loop** that handles a single concrete step: think briefly, call one tool, observe the result, verify the result is sane, then return control.

```text
┌─────────────────────────────────────────────────────────┐
│                    OUTER LOOP                           │
│  - Persistent plan (written to disk)                    │
│  - Memory: scratchpad + episodic log + facts DB         │
│  - Stop conditions: budget, wall-clock, goal-check     │
│  - Step allocator: pick next sub-task from plan         │
└──────────────────────┬──────────────────────────────────┘
                       │ "Do step N, return verified result"
                       ▼
┌─────────────────────────────────────────────────────────┐
│                    INNER LOOP                           │
│  1. Read sub-task + minimal context                     │
│  2. Reason briefly (a few hundred tokens)               │
│  3. Call one tool                                      │
│  4. Verify result (assertion or schema check)           │
│  5. Write a one-paragraph outcome note                  │
│  6. Return: { status, evidence, next_hint }             │
└─────────────────────────────────────────────────────────┘
```

Why two loops? Because the failure modes are different. The inner loop fails in **narrow, fast ways** — a bad tool call, a malformed argument, a hallucinated file path. The outer loop fails in **slow, structural ways** — the plan no longer matches reality, the agent is on step 47 of a 12-step plan, or two parallel branches contradict each other. Mixing them in one prompt is what causes the agent to suddenly "decide" the task is done at step 11 or to spend 90% of its tokens rereading its own history.

A useful mental model: the inner loop is a function call. It takes a sub-task and returns a verified result. The outer loop is a scheduler. It decides which function to call next and what to do with the result. Treat them as separate processes with a clean contract.

## Persistent Memory: What Actually Belongs There

Most agent frameworks ship with a "memory" abstraction that turns out to be a vector store and a hope. That is not enough for long-horizon work. You need at least three distinct stores, each answering a different question.

**The scratchpad** is the agent's working memory. It is a short, structured document — usually markdown — that the agent updates after every meaningful event. It holds the current plan, the last verified state of the world, and a list of open questions. The scratchpad is read in full at the start of every outer-loop iteration and is bounded to a few thousand tokens.

**The episodic log** is an append-only journal of what actually happened. Every inner-loop completion writes one paragraph: "Step 17: ran `pytest tests/test_migrations.py`, 142 passed, 2 failed in test_user_flow. Updated scratchpad: blockers now include test_user_flow." This log is never summarized automatically. Summarization is exactly how agents lose the evidence they need to debug themselves.

**The facts store** is a small structured database (often a JSON file or a single SQLite table) for things that must survive across restarts: API endpoints discovered, credentials, environment quirks, file hashes, contract versions. The agent reads from it by key and writes to it through a dedicated tool. Without this, a restarted agent will rediscover the same wrong port five times in a row.

A common production pattern is to store the scratchpad and episodic log on local disk under a per-run directory, and to checkpoint the facts store after every successful inner loop. The [LangGraph persistence docs](https://langchain-ai.github.io/langgraph/concepts/persistence/) describe a similar idea with their checkpoint abstraction, where each super-step can be replayed after a crash.

## The Plan Is an Artifact, Not a Thought

One of the highest-leverage changes you can make to a long-horizon agent is to force it to write the plan down — to a file, with a schema, before it does anything. The plan should be explicit about ordering, dependencies, and acceptance criteria for each step.

```yaml
# plan.yaml — checked into the run directory
goal: "Migrate billing service from Stripe API v1 to v2"
steps:
  - id: 1
    description: "Inventory all Stripe API calls in the codebase"
    acceptance: "grep output saved to inventory.txt, no calls missed"
    depends_on: []
    status: pending
  - id: 2
    description: "Map each v1 call to its v2 equivalent"
    acceptance: "mapping.md reviewed and signed off"
    depends_on: [1]
    status: pending
  - id: 3
    description: "Apply changes behind a feature flag"
    acceptance: "PR opened, CI green, flag default off"
    depends_on: [2]
    status: pending
  - id: 4
    description: "Run shadow traffic for 24h"
    acceptance: "shadow_report.json shows <0.1% divergence"
    depends_on: [3]
    status: pending
```

Two things change once the plan is an artifact. First, the agent can be interrupted and resumed without losing its place — a human can read `plan.yaml` and see exactly where things stand. Second, the outer loop gets a cheap progress signal: count of `status: completed` versus `status: pending`. When the count stops moving for N iterations, the agent is almost certainly stuck.

The Anthropic engineering writeup on [building effective agents](https://www.anthropic.com/engineering/building-effective-agents) makes a related point: agents work best when the workflow is explicit and composable, not when everything is implicit in a single prompt.

## Verification: The Part Everyone Skips

If you take only one pattern from this post, take this: every inner loop must end with a verifier. Not a "looks good to me" self-check, but a concrete assertion against an objective signal. Three classes of verifier cover most production cases.

**Schema verifiers** check that the tool returned the shape you asked for. A JSON schema, a regex, a required-key check. Cheap, fast, catches the bulk of "the model called the wrong tool with the right intent" failures.

**Behavioral verifiers** check that the world actually changed the way you expected. You ran a migration — did the row count go up? You wrote a file — does `wc -l` match what you wrote? You deployed — does `curl /healthz` return 200? These are the verifiers that catch silent corruption. If you don't have them, the agent will happily report success on a step that did nothing.

**Goal verifiers** are rare and expensive, and you only run them when the plan says you're done. They check the original user goal against the current state. A migration goal is verified by running the full test suite in staging, not by checking that step 4 of 4 is marked complete.

A practical heuristic from the [OpenAI function calling guide](https://platform.openai.com/docs/guides/function-calling) and similar docs: any tool call whose result you cannot verify in under one second is a tool you should wrap in a slower, audited loop. The agent should not be allowed to mark a step complete on faith.

## Tool Surface: Less Is More

Long-horizon agents get worse as their tool count grows. With 50 tools, the model spends a meaningful fraction of its reasoning budget choosing between them, and the chance of selecting a near-correct but wrong tool rises sharply. The teams running the longest-lived agents in production aggressively curate their tool surface.

Two rules that hold up well. First, **prefer coarse-grained tools over fine-grained ones**. Instead of `read_file`, `read_file_range`, `grep`, `grep_recursive`, ship `search_code` and `read_file` and let the agent compose them. Second, **wrap destructive operations**. There should never be a raw `rm -rf` or `DROP TABLE` tool. Wrap them as `archive_and_delete` or `soft_delete` that records an undo path before acting. The cost of a wrapper is one extra function definition; the cost of skipping it is a corrupted production database.

If you are using a framework like [LangChain](https://python.langchain.com/docs/introduction/) or [CrewAI](https://docs.crewai.com/), pay attention to how they let you scope tools per-agent. The right pattern is usually a small core set of safe tools available everywhere, plus a domain-specific set mounted only when the outer loop has decided the agent is in that phase of the plan.

## Failure Modes You Will Hit

A non-exhaustive list, ranked by how often they show up in real long-horizon runs.

**Loop traps.** The agent calls the same tool with the same arguments, gets the same error, and retries. The fix is a per-tool-call signature in the episodic log and a hard rule in the outer loop: if the last three tool calls have the same signature and same error, stop and ask for human input.

**Goal drift.** By step 60, the agent is doing something adjacent to the original goal but not the goal itself. The fix is to re-read the original goal and the current plan into the prompt every N outer-loop iterations, and to require an explicit "still aligned" statement before continuing.

**Context collapse.** The model gets confused because the inner loop stuffed too much raw output into the next call. The fix is to enforce a per-step output budget — the inner loop is only allowed to return a short summary plus pointers into the episodic log.

**Phantom progress.** The agent marks a step complete because the verifier passed a trivial check, but the real work wasn't done. The fix is to make verifiers as specific as possible. "Tests pass" is a fine verifier; "the 17 specific tests listed in step 2's acceptance criteria all pass" is much better.

**Cost blowup.** A loop trap you didn't catch runs for an hour and burns through your weekly budget. The fix is hard outer limits — both a per-step token cap and a per-run dollar cap — with a graceful stop-and-handoff behavior rather than an abrupt kill.

The [Anthropic prompt engineering guide](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview) and the [OpenAI best practices for agentic workflows](https://help.openai.com/en/articles/11885375-best-practices-for-using-the-openai-api-for-complex-ai-tasks) both cover related ground and are worth bookmarking.

## Patterns in Production

Three concrete patterns show up again and again in the agents that actually finish long jobs.

**Checkpointed resume.** Every outer-loop iteration writes a checkpoint. The agent process can crash, the box can reboot, and the next invocation picks up exactly where the last one stopped. LangGraph's checkpointer, the [Inngest](https://www.inngest.com/docs) durable execution model, and simple filesystem checkpoints all implement variations of this. The agent should not be a single long-lived process; it should be a sequence of short invocations chained by durable state.

**Human-in-the-loop at plan boundaries, not in the loop.** Don't ask a human to approve every tool call — you'll get no signal because humans can't review at that cadence. Do ask a human to approve the plan before execution starts and to review checkpoints at every major boundary. This is the same pattern argued for in the [LangChain human-in-the-loop docs](https://langchain-ai.github.io/langgraph/concepts/human_in_the_loop/).

**Verifier-driven loops for self-correction.** Instead of asking the model to "try again" on a failed step, feed the verifier's output back into the inner loop with explicit instructions to address the failure. This sounds obvious, but many agents still rely on the model to notice its own mistakes, which it won't, especially deep into a long run.

## Architecture for a Pluggable Pi-Agent

A clean way to think about this is in three layers, each replaceable.

```python
class OuterLoop:
    def __init__(self, plan, memory, verifier_registry):
        self.plan = plan
        self.memory = memory
        self.verifiers = verifier_registry

    def step(self) -> bool:
        sub = self.plan.next_pending()
        if sub is None:
            return self.check_goal()
        result = InnerLoop(sub, self.memory).run()
        sub.mark(result.status, result.evidence)
        self.plan.save()
        return True

class InnerLoop:
    def __init__(self, sub_task, memory):
        self.task = sub_task
        self.memory = memory
        self.budget = TokenBudget(max_in=4000, max_out=1000)

    def run(self) -> StepResult:
        context = self.memory.scratchpad() + self.task.spec
        action = llm(context, tools=self.task.allowed_tools)
        observation = action.execute()
        ok, evidence = self.task.verifier(observation)
        if not ok:
            return self.retry_with_feedback(action, evidence)
        self.memory.append_episode(self.task.id, evidence)
        return StepResult(status="ok", evidence=evidence)
```

The interesting bit is that `OuterLoop` knows nothing about specific tools, and `InnerLoop` knows nothing about the overall plan. You can swap the model, swap the verifier library, or even swap the inner loop for a human operator, and the outer loop keeps working.

## What to Measure

If you can't measure it, you can't tune it. For long-horizon agents the metrics that actually matter are:

- **Step success rate** — what fraction of inner-loop runs pass their verifier on the first try.
- **Plan completion rate** — what fraction of runs finish with the goal verifier passing.
- **Cost per completed goal** — total spend divided by successful runs, not by total runs.
- **Wall-clock to completion** — measured end-to-end, including retries and human wait time.
- **Human interventions per run** — how often you had to step in. The goal is to drive this toward zero without losing safety.

Track these per task type. The numbers will vary wildly between "migrate a billing service" and "summarize this week's customer feedback," and that's fine — the point is to know which task types your agent is actually good at, and to route accordingly.

## Key Takeaways

- Long-horizon work is a state-management problem first and a reasoning problem second. Design your architecture around persistent memory, durable checkpoints, and resumable execution.
- Separate the outer loop (plan, memory, stop conditions) from the inner loop (think, act, verify). The two fail in different ways and need different mitigations.
- Make the plan a real artifact — a file with a schema — not a thought in the prompt. It is the single best debug surface you have.
- Every inner loop needs a verifier that returns a boolean plus evidence. "Looks fine" is not verification.
- Curate the tool surface aggressively. Coarse-grained, wrapped, domain-scoped tools beat a sprawling toolbox every time.
- Track step success rate, plan completion rate, and cost per completed goal. Without these you are flying blind.

## Further Reading

- [AI2's π paper — the original pi-agent architecture](https://arxiv.org/abs/2412.06707)
- [Anthropic — Building Effective Agents](https://www.anthropic.com/engineering/building-effective-agents)
- [LangGraph — Persistence and checkpointing concepts](https://langchain-ai.github.io/langgraph/concepts/persistence/)
- [Anthropic — Prompt engineering overview for agents](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering/overview)
- [OpenAI — Function calling guide](https://platform.openai.com/docs/guides/function-calling)
- [Inngest — Durable execution for long-running workflows](https://www.inngest.com/docs)