---
title: "The Hidden Tax of AI Coding: Why Your Agent Is Burning Money on I/O"
date: "2026-09-08T14:28:19.351"
draft: false
tags: ["AI coding agents", "LLM routing", "token optimization", "Spotify", "Claude Code", "cost engineering"]
description: "Why AI coding agents burn 90% of tokens on I/O instead of reasoning — and the routing strategy that cuts costs without losing quality."
summary: "AI coding agents spend most of their tokens on file reads and boilerplate generation, not actual reasoning. A routing strategy using cheaper models for I/O-heavy work can cut token costs by 90%."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-08-the-hidden-tax-of-ai-coding-why-your-agent-is-burning-money-on-io.svg"
  alt: "A visualization of token costs split between reasoning and I/O in AI coding agents"
  caption: "The hidden split between reasoning tokens and I/O tokens in AI-powered development workflows"
  relative: false
---

> **TL;DR** — AI coding agents spend up to 90% of their tokens on I/O operations — reading files, generating boilerplate, updating docs — not on actual reasoning. By routing that grunt work to cheaper, smaller models and reserving frontier models for complex problems, engineering teams can cut token costs dramatically. The architecture is simpler than you think: two modes, a plugin, and a routing layer.

## The Invisible Cost Sitting Inside Your IDE

Every developer who has used an AI coding assistant in production knows the feeling: you ask a simple question about a function, and the assistant reads fourteen files, generates a test file, updates three documentation pages, and then gives you a one-line answer. The token count is staggering. The reasoning content inside that massive context window? Almost nothing.

This isn't a hypothetical problem. According to industry estimates, by 2028, AI coding costs are expected to exceed the average developer's salary. A quarter of engineering leaders already burn between $200 and $500 per developer per month on tokens alone, with some teams well past $2,000 [1]. The seat license is not what hurts — it is the token consumption at scale.

The uncomfortable truth is that most of what an AI coding agent does is not thinking. It is I/O. Reading five files to answer a question about one method. Generating a test file that follows the exact same pattern as the twenty test files sitting beside it. Updating documentation after a sprint review. Thousands of tokens gone, almost zero reasoning performed.

This is the hidden tax of AI-assisted development. And it is the problem that a team at Spotify set out to solve.

## The Two-Mode Architecture

The core insight behind the approach is deceptively simple: not every task your coding agent performs requires a frontier model. The expensive models — the ones with the largest context windows and deepest reasoning capabilities — are wildly overqualified for the bulk of the work. A Gemini 2.5 Flash or equivalent smaller model handles file reading and boilerplate generation just as well, at a fraction of the cost.

The implementation requires exactly two modes, each defined as a declarative agent that runs on an ephemeral runtime — think AWS Lambda, but purpose-built for agents.

**Mode 1: bulk-reader.** This mode handles the exact scenario that drains tokens fastest: when the agent needs to read multiple large files to answer a single question. The instructions are brutally specific — output structured bullets only, no greetings, no prose, no preambles. Lead every bullet with the exact name, type, or line number. Skip anything the caller did not ask for. The model used is Gemini 2.5 Flash with a temperature of 0.2, configured for deterministic, concise output.

**Mode 2: code-writer.** This mode handles tests, config scaffolding, type stubs, and anything where the output is predictable from existing patterns. The critical instruction here is "output only the code — no explanations, no markdown fences unless asked." Without this constraint, the model wraps everything in markdown fences and explanatory prose that the calling agent then has to parse through, multiplying the token cost unnecessarily.

Both modes share the same underlying model and parameters, but they solve two distinct problems: one for input-heavy tasks, one for output-heavy tasks. Together, they form the backbone of a cost-reduction strategy that does not require a platform team or a new subscription.

## From CLAUDE.md to a Real Plugin

The first version of this routing system was a block of rules embedded in `CLAUDE.md`. It sort of worked. Claude would read the instructions and self-route to the appropriate mode. But it had two fatal flaws. The rules were advisory, not enforced — Claude could ignore them. And every project needed its own copy of the instructions, creating maintenance debt across repositories.

The current implementation replaces this with a Claude Code plugin called **shunt**. Delegation goes through the Portal CLI actions registry, so the plugin works against any Portal instance with the AiKA plugin enabled. This is a meaningful architectural shift: the routing logic is no longer buried in a markdown file that humans might forget to update. It is a first-class component of the development toolchain.

The routing operates on two layers. The first layer uses **hooks** — Claude Code fires hooks before every tool call, and shunt registers two `PreToolUse` hooks. One hook, `check-file-size`, fires on every `Read` call. If the file exceeds a certain threshold, the hook intercepts the call and routes it through the bulk-reader mode instead of letting Claude handle it directly. This is the enforcement mechanism that the `CLAUDE.md` approach lacked.

The second layer is the **actions registry**. When Claude needs to generate code, the plugin intercepts the request and routes it through code-writer. The entire flow is transparent to the developer — the agent thinks it is doing the work itself, but behind the scenes, the heavy lifting is handled by cheaper models optimized for the specific task type.

## Why This Matters Beyond Token Savings

The immediate benefit is financial. But the architectural implications run deeper.

**Latency is a hidden cost.** When a frontier model processes a request to read eight files and summarize them, the response time is significant. A smaller model handling the same task can return results faster, which means faster feedback loops for the developer. In an IDE, latency is not an academic concern — it is the difference between a smooth workflow and one that constantly interrupts your train of thought.

**Model specialization is a real pattern.** The two-mode approach is a microcosm of a broader trend in AI infrastructure: intelligent routing. Just as load balancers distribute traffic across servers with different capabilities, AI routing distributes tasks across models with different strengths. This is not new — content delivery networks have been doing something similar for years. But applying it to the coding agent workflow is a relatively recent innovation.

**The pattern connects to observability.** When you route tasks through distinct modes, you gain visibility into which types of tasks consume the most tokens. This data is invaluable for engineering managers trying to understand AI tooling costs. Are developers generating too many tests? Are they reading too many files per query? Without routing and logging, you have no signal. With it, you have a dashboard.

**It also touches on the broader question of AI agent architecture.** The shift from monolithic agents that do everything to composable systems of specialized agents is gaining traction across the industry. OpenAI's recent push toward agent frameworks, Google's Gemini integrations, and the rise of tools like LangGraph all point in the same direction: the future of AI coding is not one giant model doing everything, but a network of specialized models coordinated by a smart router.

## The Engineering Discipline Behind It

What makes this approach particularly compelling is that it does not require new infrastructure. The runtime is ephemeral — AWS Lambda or equivalent. The instructions are declarative — you define what the agent should do, not how it should do it. The routing is handled by a plugin that integrates with existing tooling. This is the kind of engineering that gets overlooked in the hype cycle: simple, declarative, composable solutions that solve real problems without introducing new complexity.

There is a parallel here to how the industry approached microservices a decade ago. The initial instinct was to build massive platforms. The winning approach turned out to be much simpler: define clear boundaries, route requests to the right service, and let each service do one thing well. The AI coding agent routing problem is following the same trajectory.

The temperature settings deserve attention. Both modes use a temperature of 0.2, which is deliberately low. For file reading and code generation, you want deterministic, reproducible output. You do not want the model "being creative" when it is supposed to be matching existing patterns. This is a lesson from production ML systems: the right level of randomness depends entirely on the task. Creative writing demands higher temperature. Boilerplate generation demands lower.

## What Breaks If You Get This Wrong

The risks are real. If the routing logic is too aggressive, you might send a genuinely complex problem to a small model that cannot handle it, producing incorrect code that passes tests but introduces subtle bugs. If the hooks are too permissive, Claude might bypass the routing entirely, defeating the purpose.

The `check-file-size` hook is a good example of a pragmatic boundary. It does not try to decide whether a file is "important" — it just checks the size. Large files get routed to bulk-reader. Small files stay with Claude. This threshold-based approach is simple, predictable, and easy to tune. It avoids the complexity of a classifier that would need training data and ongoing maintenance.

Similarly, the "output only the code" instruction in code-writer is not just a stylistic preference. It is a cost optimization. Every word the model generates costs tokens. Every markdown fence, every explanatory sentence, every "here is the code you asked for" adds to the bill. By constraining the output format at the model level, you eliminate the downstream parsing cost that the calling agent would otherwise incur.

## The Bigger Picture: AI Cost as an Engineering Problem

The conversation around AI coding costs often focuses on model pricing — how much per million tokens, which provider is cheaper, whether open-source models are good enough. But the real engineering problem is not the price per token. It is the number of tokens you are consuming per task.

A developer using an AI coding agent inefficiently might burn 500,000 tokens on a task that could be done with 50,000. The model price per token is the same either way. The difference is entirely in how the agent is architected and routed.

This is why the approach matters. It is not about negotiating better rates with model providers. It is about building systems that use tokens efficiently. It is the same engineering discipline that drove database query optimization, caching strategies, and CDN architectures in previous decades. The tools change. The principles do not.

The teams that treat AI coding costs as an afterthought will find their budgets exploding. The teams that treat it as an engineering problem — with routing, monitoring, and optimization — will be the ones that sustain AI-assisted development at scale.

## Key Takeaways

- **Most AI coding agent tokens are spent on I/O, not reasoning.** Reading files and generating boilerplate dominate the token budget, not the actual problem-solving.
- **Two modes — bulk-reader and code-writer — can handle 90% of the token-heavy work** using smaller, cheaper models without sacrificing quality.
- **Advisory routing (CLAUDE.md) is unreliable.** Enforced routing through hooks and plugins ensures that the cost-saving logic actually runs.
- **Output constraints are cost constraints.** Instructing the model to "output only the code" eliminates unnecessary prose and markdown that inflates token usage.
- **Temperature settings should match the task.** Deterministic output (low temperature) is critical for file reading and code generation where pattern-matching matters more than creativity.
- **AI cost optimization is an engineering problem, not a procurement problem.** The solution lies in architecture and routing, not in negotiating better model pricing.

## Further Reading

- [Anthropic's Claude Code Engineering Post](https://www.anthropic.com/engineering/claude-code) — The original announcement and technical deep-dive on Claude Code's architecture, including how tool use and context management work under the hood.
- [OpenAI on GPT-4o-mini: Advancing Cost-Efficient Intelligence](https://openai.com/index/gpt-4o-mini-advancing-cost-efficient-intelligence/) — OpenAI's analysis of how smaller, specialized models can match frontier model performance on specific tasks at a fraction of the cost.
- [The State of AI in 2024 — Datadog Report](https://www.datadoghq.com/state-of-ai-report/) — Comprehensive data on AI adoption, spending patterns, and the growing cost challenges enterprises face when integrating AI into production workflows.
- [Building Serverless Agents with AWS Lambda](https://aws.amazon.com/blogs/compute/building-serverless-agents-with-aws-lambda/) — AWS's guide to implementing ephemeral agent runtimes on Lambda, which is the architectural pattern underlying the Portal by Spotify approach.
- [Intelligent Routing in AI Systems — Google Cloud Architecture Center](https://cloud.google.com/architecture) — Patterns for implementing model routing and load balancing across multiple LLM endpoints in production systems.

---