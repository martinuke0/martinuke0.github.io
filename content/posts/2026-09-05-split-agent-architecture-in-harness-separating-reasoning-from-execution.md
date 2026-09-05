---
title: "Split Agent Architecture in Harness: Separating Reasoning from Execution"
date: "2026-09-05T18:25:35.688"
draft: false
tags: ["harness", "ai-agents", "software-engineering", "devops", "agent-architecture"]
description: "How Harness's split agent architecture separates the planner from the executor to deliver AI coding agents that are faster, safer, and easier to debug in production."
summary: "Harness separates its AI coding agent into a lightweight planner and a sandboxed executor. Here's why that split matters for latency, security, and observability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-split-agent-architecture-in-harness-separating-reasoning-from-execution.svg"
  alt: "Diagram of a split agent architecture with a planner process and an executor process connected by a control channel."
  caption: ""
  relative: false
---

> **TL;DR** — Harness splits its coding agent into a **planner** that reasons about what to do and an **executor** that actually runs code, edits files, and shells out. The planner stays in your IDE loop with low latency; the executor runs in an ephemeral sandbox with full audit trails. The split is what makes the agent fast enough to feel interactive and safe enough to ship to enterprise teams.

## Why a single-process agent stops working

If you've used an AI coding agent long enough, you've probably hit the same wall I have: the moment the agent needs to do something non-trivial — clone a repo, run tests, mutate a database, hit a real API — the experience falls apart. The model has to either pretend to do it (hallucinated output) or actually do it (and suddenly you're running untrusted code in your laptop's userland).

The naive answer is to give the model a tool-calling loop: let it write code, execute it, read the output, and iterate. This works for demos. It breaks down in production for three reasons:

1. **Latency.** A reasoning turn plus a real execution turn can easily take 20–60 seconds. If that round trip is in the same process as your IDE keystrokes, the UX dies.
2. **Security.** Letting the LLM process directly invoke `subprocess.run` on your dev machine is a recipe for an `rm -rf` incident or a leaked `.env` file. The blast radius is your laptop.
3. **Observability.** When the agent "did something wrong," you have no clean record of what was attempted, what was approved, and what actually ran. Logs are an afterthought.

Harness's answer to all three is architectural: **don't run the brain and the hands in the same process**. Split the agent into two cooperating roles with a narrow contract between them.

## The two roles: planner and executor

A split agent architecture has exactly two components, and the names are boring on purpose.

- The **planner** owns the LLM, the conversation history, the tool schema, and the decision-making. It decides *what* should happen next and produces a structured instruction called a *step*.
- The **executor** owns the filesystem, the shell, the network, and any side effects. It receives a step, runs it, and returns a structured result. It does not contain an LLM and does not decide anything on its own.

The contract between them is a small, typed schema — typically JSON — that describes the action, its arguments, expected outputs, and any safety metadata. This is the only thing that crosses the boundary.

```json
{
  "step_id": "s_8f3a",
  "action": "run_command",
  "args": {
    "cmd": "pytest -q tests/test_user_repo.py",
    "cwd": "/workspace/repo",
    "timeout_s": 120
  },
  "safety": {
    "network": "deny",
    "writes": "workspace_only"
  }
}
```

Because the contract is small and explicit, you can put almost anything between the two roles: an in-process function call, a gRPC channel, a message queue, or even a different machine. That flexibility is the whole point.

## Where the planner runs

The planner lives wherever the user is — in the IDE, in the CLI, in a web chat, in a CI bot. Its job is to keep the user moving. That means it must:

- Stream tokens back to the UI as they arrive, so the user sees the agent "thinking" in real time.
- Stay responsive even when the executor is busy for a minute running a long test suite.
- Never block on side effects directly. If the planner needs a tool result, it dispatches the step and waits asynchronously.

In practice, the planner is a thin event loop wrapped around the model SDK. Something like this:

```python
async def planner_loop(state, executor_client):
    while not state.done:
        # Ask the model what to do next
        decision = await llm.complete(state.messages, tools=TOOL_SCHEMAS)

        if decision.finish_reason == "stop":
            state.done = True
            break

        # Hand the step to the executor and continue reasoning
        for step in decision.tool_calls:
            result = await executor_client.submit(step)
            state.messages.append(tool_result(step, result))
```

Notice what the planner is *not* doing: it's not opening files, not running shell commands, not touching the network. It's only generating structured step requests and waiting for results. That's why it stays fast — its blocking surface is just the LLM API.

## Where the executor runs

The executor lives in a sandbox. For local use, that might be a bubblewrap or Docker container on your laptop. For Harness Cloud, it's a fresh microVM or container per task, torn down when the work is done. The executor is responsible for:

- **Materializing the workspace** — cloning the repo, checking out the right SHA, restoring any cached dependencies.
- **Applying patches** from the planner to the working tree.
- **Running commands** under a policy: timeouts, resource limits, network egress rules, filesystem write scopes.
- **Capturing artifacts** — diffs, logs, test reports, screenshots — and returning them as part of the step result.
- **Producing an audit record** of every action it took, regardless of whether the planner ever sees the result.

A minimal executor looks roughly like this:

```python
def execute_step(step: Step) -> StepResult:
    policy = load_policy(step.safety)
    with sandbox(policy) as sb:
        if step.action == "edit_file":
            sb.write(step.args["path"], step.args["content"])
        elif step.action == "run_command":
            stdout, stderr, rc = sb.run(
                step.args["cmd"],
                cwd=step.args["cwd"],
                timeout=step.args["timeout_s"],
            )
        elif step.action == "read_file":
            content = sb.read(step.args["path"])
        # ... other actions
        return StepResult(
            step_id=step.step_id,
            ok=True,
            artifacts=sb.collect_artifacts(),
            audit=sb.audit_log(),
        )
```

The crucial property: **the executor is dumb on purpose**. It does not interpret natural language. It does not "decide" anything. If a step says `rm -rf /`, the executor checks the policy and either runs it or refuses — but it does not consult the model about whether it should.

## Patterns in Production

### Pattern 1: Synchronous steps for tight feedback loops

For actions that complete in under a second — reading a file, grepping the repo, listing a directory — the planner should call the executor synchronously. The user is waiting for the answer and there's no benefit to asynchrony. This is most of the volume of tool calls in a typical coding session.

### Pattern 2: Fire-and-forget steps for long jobs

For builds, test suites, and deployments, the planner should dispatch the step and continue reasoning about what to do *while* the job runs. The executor returns a `step_id` immediately; the planner polls or subscribes for completion. This is what keeps the UI alive during a 3-minute CI run instead of freezing.

### Pattern 3: The human-in-the-loop checkpoint

The split makes it cheap to insert a human approval step. Because the planner produces a structured step *before* the executor runs it, you can route high-risk actions — `git push`, `kubectl apply`, dropping a database — through an approval queue without changing either side of the architecture. The planner emits the step, the system holds it, a human clicks "approve" in Slack, and only then does the executor run it.

### Pattern 4: Replay and rewind

Because every step and result is a structured record, the entire agent run is replayable. You can re-execute a session with a different model, against a different branch, or with a different policy. This is invaluable for debugging agent behavior and for building evaluation harnesses. You can't replay a monolithic agent's session if the model made a side-effecting tool call at step 7 — the state of the world has moved on.

## What the split actually buys you

Three things that are hard to get any other way:

- **Latency isolation.** The planner's responsiveness is decoupled from the executor's workload. A 90-second test run no longer blocks the user's keystrokes or the next planning turn.
- **Security by construction.** The executor is the only process with real capabilities. The planner has none. You can run the planner on a developer laptop and the executor in a locked-down sandbox and you don't have to trust the model to behave.
- **Observability by default.** Every step is a typed, logged, replayable unit. When something goes wrong, you have the full transcript: the model's reasoning, the exact command it wanted to run, the policy decision, and the actual output.

The split is not free — you pay for serialization, IPC, and the cognitive overhead of thinking in two processes. But in a production agent that real engineers will trust with real repos, those costs are the price of admission.

## Key Takeaways

- A **single-process** agent forces the LLM to share an address space with side effects, which kills latency, security, and observability simultaneously.
- **Splitting** the agent into a reasoning planner and a policy-bound executor makes each side boring and verifiable, which is exactly what you want.
- The planner's contract is **structured steps**, not natural language — this is what enables async execution, replay, and human approval.
- The executor should be **policy-driven and dumb**: it executes typed actions under rules, never consulting the model about whether to run them.
- The architecture unlocks patterns you can't easily build otherwise: **async long jobs, human-in-the-loop checkpoints, full replay**, and clean evaluation harnesses.
- For enterprise adoption, the audit trail and the sandbox boundary are not nice-to-haves — they're the difference between a demo and a tool that survives a security review.

## Further Reading

- [Anthropic's write-up on tool use and computer use agents](https://www.anthropic.com/news/building-effective-agents)
- [OpenAI's function calling and structured outputs documentation](https://platform.openai.com/docs/guides/function-calling)
- [Docker sandboxing primitives for agent executors](https://docs.docker.com/engine/security/)
- [gRPC as a transport for agent control planes](https://grpc.io/docs/what-is-grpc/)
- [The 12-Factor App principles for agent backends](https://12factor.net/)