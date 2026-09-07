---
title: "Building and Evaluating Agents: A Production Engineer's Playbook"
date: "2026-09-07T11:04:12.740"
draft: false
tags: ["agents", "llm", "evaluation", "rag", "mlops", "observability"]
description: "A production engineer's playbook for building and evaluating LLM agents, covering architecture, tool design, eval pipelines, and failure modes that actually ship."
summary: "Most LLM agent demos die in production because teams skip the boring parts: tool contracts, eval harnesses, and observability. This post walks through the architecture, patterns, and evaluation loops that turn a clever prototype into a system you can actually operate."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-07-building-and-evaluating-agents-a-production-engineer.svg"
  alt: "Abstract diagram of an agent loop connecting tools, memory, and evaluators"
  caption: ""
  relative: false
---

> **TL;DR** — A reliable agent is mostly engineering, not prompting: tight tool contracts, deterministic harnesses, structured eval datasets, and observability that treats the LLM like any other distributed dependency. Build the smallest viable loop first, score it offline before you score it online, and never ship without trace-level visibility into every step.

## Why Most Agent Demos Never Reach Production

Every week a new agent demo lands on Hacker News: a CLI that books flights, a chatbot that queries your warehouse, a planner that ships PRs. A few months later, the same team posts a quieter follow-up: "Lessons from running agents in production." The lessons are almost always the same.

The gap between a demo and a production system isn't model quality. It's plumbing. Agents fail in ways that look like intelligence problems but are really contract problems. The model "hallucinates" because the tool schema is ambiguous. The agent "loops forever" because there is no step budget and no termination condition. The "answer is wrong" because the eval harness only measured final output, not the path that produced it.

This post is the playbook I wish I'd had two years ago. It's organized around three questions: what is an agent, really, and what are the patterns that work? How do you evaluate one without fooling yourself? And what does it take to operate one on call?

## What an Agent Actually Is

Strip away the marketing and an agent is three things stitched together:

1. **A reasoning loop** — usually an LLM call that produces structured output: a thought, a tool call, or a final answer.
2. **A tool surface** — typed functions the model can invoke, each with a schema, a timeout, and a side-effect profile.
3. **A state machine** — what gets remembered between turns, what gets forgotten, and what gates "done."

That third piece is the one people under-design. State isn't just chat history. It's the working memory of the task: which files have been read, which API calls succeeded, which assumptions the model has made. Without explicit state, the model improvises, and improvised state is the leading cause of "the agent went off the rails" incidents.

A useful mental model is to treat the agent loop the way you'd treat a database transaction. It has a budget (steps, tokens, wall-clock). It has idempotency requirements. It has rollback semantics. It has a commit point — the final answer — that you want to be reproducible from the same inputs.

### The Loop, Concretely

A minimal but production-shaped loop looks like this:

```python
def run_agent(task: Task, tools: ToolRegistry, policy: Policy) -> Result:
    state = State(task=task)
    for step in range(policy.max_steps):
        action = llm.plan(state)            # returns ToolCall | Answer
        if isinstance(action, Answer):
            return Result(answer=action.text, trace=state.trace)
        result = tools.invoke(action)       # bounded by timeout + retries
        state.record(action, result)
        if policy.should_stop(state):
            return Result(answer=state.best_so_far(), trace=state.trace)
    return Result(answer=state.best_so_far(), trace=state.trace, incomplete=True)
```

Notice what is not in this loop: any cleverness. The interesting decisions — what `best_so_far` means, what `should_stop` checks, how retries interact with idempotency keys — all live outside the model. That separation is what makes the system debuggable.

## Architecture: Patterns That Ship

There are four patterns I've seen survive contact with real users. Each has a sweet spot, and each has a failure mode you should design against upfront.

### Single-Shot Tool Use

The model gets a question, optionally calls one tool, returns an answer. This is not an "agent" in the dramatic sense, but it is the right shape for 60–70% of retrieval-augmented use cases. If your task is "answer this question using this corpus," you don't need planning — you need a good retriever and a tight prompt.

The failure mode here is the model ignoring retrieved evidence because the prompt allows it. Fix that with explicit grounding instructions and an evaluator that measures whether the answer is supported by retrieved chunks. LangChain's [RAG tutorial](https://python.langchain.com/docs/tutorials/rag/) and the [AWS guidance on RAG evaluation](https://aws.amazon.com/blogs/machine-learning/evaluate-your-rag-application/) both cover this in detail.

### Plan-and-Execute

The model first produces a plan (a list of steps), then executes them. This is what frameworks like [LangGraph](https://langchain-ai.github.io/langgraph/) and [CrewAI](https://docs.crewai.com/) lean on. Plan-and-execute is great when the task is decomposable and the steps are observable, like "research these three competitors and write a comparison."

The trap is treating the plan as truth. Plans from LLMs are hypotheses. They should be inspectable, editable by humans for high-stakes workflows, and re-planned when intermediate results contradict the original assumptions. The most common production bug in this pattern is the agent executing a stale plan after the world changed underneath it.

### ReAct and Tool-Use Loops

ReAct — interleaving reasoning and action — is the pattern most demos are built on. The model thinks, calls a tool, observes the result, thinks again, and so on. This is the right shape for open-ended tasks where the model genuinely needs feedback between steps: debugging, browser use, code execution against a live REPL.

The failure mode is loops. Models get stuck when a tool returns noisy or partially useful results and the prompt doesn't penalize re-trying the same call. Mitigations: a step budget, a "no-progress" detector (did the last N actions change the state?), and explicit guidance to change strategy when results are similar. The original [ReAct paper](https://arxiv.org/abs/2210.03629) is still worth reading for the pattern's intent.

### Human-in-the-Loop and Approval Gates

For any workflow with side effects — sending email, posting to Slack, writing to a database — you want an approval gate before commit, not just before the agent starts. The pattern: the agent proposes, a human (or a deterministic policy) approves, the action executes under an idempotency key so retries are safe.

This is where products like [LangSmith](https://docs.smith.langchain.com/), [Langfuse](https://langfuse.com/), and open-source alternatives earn their keep. They make the proposal-review step a first-class UI rather than a `print()` statement.

## Tool Design: The Part That Determines Everything

If you remember nothing else from this post, remember this: the quality of your agent is bounded by the quality of your tool surface. A model with mediocre reasoning and excellent tools will outperform a brilliant model with sloppy tools every time.

### Contracts Over Conversations

Every tool needs:

- A **typed schema** with required vs. optional fields clearly distinguished.
- A **docstring** that explains not just what the tool does but when to use it, when *not* to use it, and what the common error modes look like.
- **Bounded inputs** — strings with allowed enums, numbers with sensible ranges, IDs that are validated.
- **Bounded outputs** — large results should be summarized or paginated, not returned verbatim. A tool that returns a 50,000-row dataframe will break the model's context window and your latency budget.

A useful trick is to give every tool an example invocation and an example response in its description. Models are remarkably good at pattern-matching from in-tool examples, and bad at inferring from prose alone.

### Idempotency and Side Effects

If a tool can mutate state, it must be idempotent under retry. "Send email" is not idempotent by default — wrap it with a dedupe key derived from the inputs. "Create ticket" should accept a client-provided ID. "Update record" should be a PUT, not a POST.

This isn't agent-specific advice; it's how you build reliable distributed systems. The catch is that agents retry aggressively because they don't know if a failure was transient. Treat the agent like a flaky network client: every call needs a timeout, every retry needs a key.

### Tool Failure as a First-Class Signal

Tools fail. APIs return 500s, rate limits hit, timeouts expire. The agent needs to see the failure and reason about it — but it also needs to know when *not* to keep retrying. A clean pattern is to return structured errors with a `retryable: bool` field and a `suggestion: str` field. The model can then decide whether to retry, switch tools, or escalate.

```json
{
  "ok": false,
  "code": "RATE_LIMITED",
  "retryable": true,
  "suggestion": "Wait 30 seconds and retry, or use the cached results from step 3."
}
```

The `suggestion` field is doing more work than it looks. It converts a generic error into something the model can act on, and it gives you a place to inject guardrails ("do not retry more than twice on this code").

## Evaluation: The Loop That Tells You If Anything Works

You cannot improve what you cannot measure, and you cannot measure an agent with a single number. Agent evaluation is multi-dimensional, and the dimensions interact.

### Offline vs. Online

**Offline evaluation** runs against a fixed dataset with known answers. It's reproducible, cheap, and the only way to compare two versions of an agent without burning user trust. The dataset should be representative of real traffic, not hand-curated toy examples.

**Online evaluation** runs in production against live traffic. It catches things offline evals can't: tool failures, prompt regressions that only show up under load, distribution shift in user inputs. The trade-off is cost and risk — every eval call costs latency and money.

A mature setup runs both. Offline evals gate every release. Online evals run on a sampled fraction of traffic and feed dashboards.

### The Three Layers of Agent Eval

Think of agent evaluation as three concentric rings.

**Ring 1: Component eval.** Does the retriever return relevant documents? Is the tool-selection accuracy above threshold? Does the response parser produce valid JSON 99.9% of the time? These are deterministic and you should automate them heavily. They are the regression tests of an agent system.

**Ring 2: Trajectory eval.** Did the agent take a good path? Even if the final answer is wrong, you can score intermediate steps: did it pick the right tool, did it call the tool with sensible arguments, did it stop when it should have? Tools like [LangSmith](https://docs.smith.langchain.com/) and [Langfuse](https://langfuse.com/) expose traces that make this tractable. There's also a growing ecosystem of LLM-as-judge approaches, though they need their own calibration — see [Anthropic's writeup on Constitutional AI](https://www.anthropic.com/news/claudes-constitution) and [DeepEval](https://docs.confident-ai.com/) for practical patterns.

**Ring 3: Outcome eval.** Did the user get what they wanted? This is the hardest signal to get because it requires either user feedback or a careful proxy. Outcome eval should be small in volume but high in signal: a daily sample, scored either by humans or by a calibrated LLM judge.

### Building an Eval Dataset That Doesn't Lie to You

The single biggest eval mistake is testing on data the model has effectively memorized or seen during training. Two practical fixes:

1. **Hold out a real slice.** Keep 10–20% of production traffic — with PII removed — as a private eval set that never touches training data and never gets shared with model providers.
2. **Synthesize adversarially.** Use an LLM to generate tricky variants of known queries: paraphrases, multi-hop questions, queries that should be refused, queries with conflicting instructions. The [Anthropic Claude docs on prompt engineering](https://docs.anthropic.com/en/docs/build-with-claude/prompt-engineering) and the [OpenAI evals guide](https://github.com/openai/evals) both cover synthesis patterns.

A good eval set also includes **negative examples** — things the agent should refuse, fail gracefully on, or escalate. If your eval only contains questions the agent should answer correctly, you've built a benchmark for the agent you have, not the agent you need.

### LLM-as-Judge, With Caveats

LLM can score other LLMs, and for open-ended quality ("is this response helpful and grounded?") they're often the only scalable option. But they're biased in known ways: they prefer longer answers, they prefer answers that agree with their own priors, and they struggle with factual precision. Calibrate them against human judgments on a small set, measure agreement, and don't trust a judge you haven't validated.

The [Anthropic Claude documentation on evaluation](https://docs.anthropic.com/) and the [Langfuse evaluation docs](https://langfuse.com/docs/evaluation/overview) both describe this calibration loop in detail.

## Observability: Operating an Agent on Call

The day your agent goes live is the day you start learning what it actually does, which is rarely what you designed it to do. Observability is the difference between "the agent is broken" and "the agent called the billing API 47 times in a loop because the schema changed."

### Trace Everything

Every agent run should produce a trace: the input, every LLM call (with prompt, response, latency, token count), every tool invocation (with arguments, result, duration), and the final answer. Store these traces durably. They are your postmortem material, your eval dataset source, and your product analytics goldmine.

OpenTelemetry has become the lingua franca here. [OpenLLMetry](https://github.com/traceloop/openllmetry) and the [OpenInference](https://github.com/Arize-ai/openinference) spec both define semantic conventions for LLM applications, which means your traces can flow into existing observability stacks like [Datadog](https://www.datadoghq.com/), [Honeycomb](https://www.honeycomb.io/), or [Grafana](https://grafana.com/).

### The Metrics That Matter

You can measure hundreds of things. The ones I check first:

- **Step count distribution** — are runs terminating in 1–2 steps, or are some runs going to the step budget?
- **Tool failure rate by tool** — which tools are flaky, and which are silently returning garbage?
- **Cost per task** — tokens in, tokens out, tool costs, judge costs. Track it by task type.
- **Latency p50/p95/p99** — agents are slower than single calls by design; budget for it.
- **Human escalation rate** — if you have an approval gate, what fraction of proposals get rejected or edited?

A spike in any of these is a leading indicator of a regression. A flat trend is a leading indicator of a stable system. Neither happens by accident.

## Patterns in Production: A Reference Architecture

Pulling it all together, a reference architecture for a non-trivial agent looks like this:

```text
                ┌─────────────────────────────────────────────┐
                │                  Gateway                    │
                │  (auth, rate limits, idempotency keys)      │
                └─────────────────────┬───────────────────────┘
                                      │
                ┌─────────────────────▼───────────────────────┐
                │              Orchestrator                    │
                │  (the agent loop, state, step budget)        │
                └──────┬───────────────────────┬──────────────┘
                       │                       │
          ┌────────────▼─────────┐   ┌──────────▼────────────┐
          │       LLM            │   │   Tool Registry       │
          │  (with retries,      │   │  (typed schemas,      │
          │   fallback models)   │   │   timeouts, tracing)  │
          └────────────┬─────────┘   └──────────┬────────────┘
                       │                       │
                ┌──────▼───────────────────────▼──────┐
                │         Observability Sink          │
                │  (traces, metrics, eval results)     │
                └──────┬───────────────────────────────┘
                       │
          ┌────────────▼─────────────┬──────────────────┐
          │     Eval Harness         │   Alerting /     │
          │  (offline + online)      │   Dashboards      │
          └──────────────────────────┴──────────────────┘
```

Every box is a system you'd recognize from any backend architecture. The only novelty is that one of the boxes — the LLM — is non-deterministic and gets treated accordingly: with fallbacks, with caches, with explicit confidence signals, and with eval gates before changes ship.

This is the unsexy truth of agent engineering. You're building a distributed system with a probabilistic core. Everything around the LLM should be deterministic, observable, and boring. That boringness is what lets the LLM be interesting.

## Key Takeaways

- **Agents are state machines, not prompts.** Design the loop, the step budget, and the termination conditions before you tune the prompt.
- **Tools are the product.** Tight schemas, idempotency, structured errors with suggestions, and bounded outputs will do more for reliability than any model upgrade.
- **Evaluate in three rings.** Component, trajectory, and outcome. Each catches a different class of bug, and you need all three.
- **LLM-as-judge is useful but biased.** Calibrate against human labels and measure agreement before you trust it.
- **Trace everything, store traces durably, and watch step counts and tool failure rates.** Those four metrics catch most regressions before users do.
- **Treat the agent like any other distributed system.** Retries with idempotency keys, timeouts, fallbacks, and observability through OpenTelemetry.

## Further Reading

- [LangGraph documentation](https://langchain-ai.github.io/langgraph/) — patterns for stateful, multi-agent workflows.
- [Anthropic's guide to building effective agents](https://www.anthropic.com/engineering/building-effective-agents) — the clearest framing of when agents are and aren't the right tool.
- [OpenAI evals repository](https://github.com/openai/evals) — open-source patterns and datasets for LLM evaluation.
- [Langfuse documentation](https://langfuse.com/docs) — open-source LLM observability and tracing.
- [OpenInference semantic conventions](https://github.com/Arize-ai/openinference) — OpenTelemetry conventions for LLM applications.
- [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — the original paper behind the reasoning-and-action loop pattern.