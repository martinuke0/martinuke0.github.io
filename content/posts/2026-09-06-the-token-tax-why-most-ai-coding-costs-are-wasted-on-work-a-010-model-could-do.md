---
title: "The Token Tax: Why Most AI Coding Costs Are Wasted on Work a $0.10 Model Could Do"
date: "2026-09-06T13:41:36.708"
draft: false
tags: ["ai-agents", "llm", "developer-tools", "cost-optimization", "claude-code"]
description: "Frontier models are overkill for file I/O and boilerplate generation. A practical guide to routing cheap work to cheap models and saving frontier tokens for hard problems."
summary: "Most tokens burned by an AI coding agent are spent on I/O and boilerplate, not reasoning. Here's how to slash your bill by routing grunt work to a cheaper model while keeping your frontier model for the problems that actually need it."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-the-token-tax-why-most-ai-coding-costs-are-wasted-on-work-a-010-model-could-do.svg"
  alt: "Two gears meshing — one large and one small — symbolizing routing work between a heavy frontier model and a lightweight worker model."
  caption: ""
  relative: false
---

> **TL;DR** — The majority of tokens your AI coding agent burns aren't spent reasoning, they're spent reading boilerplate and writing boilerplate. By routing I/O-heavy tasks to a cheap model via a hook-based delegation layer, you can keep the frontier model only for the work that actually requires it. The pattern is simple, the savings are dramatic, and the architecture generalizes far beyond coding assistants.

## Why your Claude Code bill is so high

There's a category mistake happening inside every AI coding agent, and it's costing you money every single day. The mistake is treating "reading a 600-line file to find one method" the same as "designing a distributed lock with idempotency guarantees." Both end up in your token ledger as roughly equivalent expenses, but the actual cognitive work involved is wildly different. One is a grep with extra steps. The other is a system design decision.

A frontier model like Claude Opus 4 or GPT-5 is genuinely extraordinary at the second task. It's catastrophically overqualified for the first. And yet, in a typical session, the ratio is usually inverted: dozens of file reads, dozens of boilerplate writes, and maybe a handful of moments that actually require deep reasoning. You're paying for an F1 engine to drive to the mailbox.

The numbers are getting hard to ignore. Industry surveys suggest that by 2028, AI coding costs for an average developer will exceed the developer's salary itself. Roughly 25% of engineering leaders are already burning between $200 and $500 per developer per month on tokens, with some shops well past $2,000. Those numbers don't include the seat licenses, which are mostly fixed. The variable cost, the part you can actually move, is the token spend — and most of that spend is being wasted on work a much cheaper model would handle identically.

This isn't an anti-AI take. Frontier models earn their keep. The point is that the *allocation* is broken. You wouldn't route every database query through your largest, most expensive analytics warehouse. You wouldn't use an H100 to serve a static HTML file. And you shouldn't be sending a 400-token "summarize this file" prompt to a model that costs $15 per million output tokens when a $0.30 model will return the same answer.

The fix isn't exotic. It's the same principle that gave us CDNs, read replicas, and tiered storage: route by class of work, not by default.

## What "grunt work" actually looks like in a coding session

Before talking solutions, it's worth being specific about what's actually being wasted. When a coding agent like Claude Code works on a real task in a real codebase, the typical token profile looks something like this:

**Reads.** The agent reads the file you mentioned, then reads the three files that import it, then reads the test file for each of those, then reads the test helper, then reads the project config. By the end of one question, ten files have been loaded into context, and only one contained a fact that mattered. This is the single largest source of waste in my own usage — large monolithic files, generated code, vendored dependencies, fixture data. The agent has to *consume* these tokens even when its answer is two sentences.

**Boilerplate generation.** Tests, type stubs, configuration scaffolds, migration files, CRUD endpoints, OpenAPI specs. The shape of the output is almost entirely determined by the shape of neighboring files. There's no creativity required, no architectural judgment. A model that's seen the existing pattern can produce the new file almost deterministically. This is the second largest source of waste.

**Doc and comment updates.** After a meeting, after a rename, after a refactor — "update the docstrings in this module to reflect the new behavior." It's pure transformation work. There's a one-to-one mapping between old text and new text. A cheap model with the diff in front of it can do this perfectly.

**Style enforcement.** "Reformat this file according to our prettier config and fix the lint warnings." Mechanical. Token-heavy on output, but no reasoning required.

**Conversational scaffolding.** Greetings, summaries, "let me think about this for a moment" preambles, markdown fences around code blocks. Some of this is unavoidable, but a lot of it is the model doing what models do by default — being verbose. With the right system prompt, you can suppress almost all of it.

If you sum those categories, you'll find they account for something like 70–85% of the tokens flowing through a typical session. The remaining 15–30% is the actual reasoning, the design decisions, the architectural choices. That's the part that needs the frontier model.

The insight, then, is that you don't need a cheaper frontier model. You need a *different model for a different class of work*. The same principle showed up in databases decades ago: you don't make your OLTP database faster by buying a bigger Oracle license, you move analytical queries to a columnar store. The work is different, so the tool is different.

## The architecture: a delegation layer with hooks

The cleanest implementation of this idea, and the one that scales best in practice, is a delegation layer that sits between the coding agent's tool calls and the actual operations. In Claude Code specifically, the right primitive is the `PreToolUse` hook — a callback that fires before any tool execution and can choose to short-circuit the call.

The pattern looks like this:

1. The agent decides to call a tool (for example, `Read` on a large file).
2. Before the tool actually executes, the hook inspects the call.
3. If the call matches a "delegate this" rule, the hook routes the work to a worker model via an HTTP call, gets the result back, and returns that result to the agent *as if* the agent had done the work itself.
4. The agent never knows the difference, except its context window is full of useful summaries instead of raw file contents.

This is the same architecture that powers request-level caching in web infrastructure. Varnish sits in front of your origin server and serves cached responses for requests that match a known pattern. Your application doesn't know the cache exists, but its database load drops by 80%. Here, the worker model is the cache: it handles the predictable requests, the frontier model only sees the novel ones.

What you delegate to is up to you. A self-hosted smaller model (Qwen-Coder, DeepSeek-Coder, a fine-tuned local model) is one option. A cheap hosted model like Gemini 2.5 Flash or GPT-4o-mini is another. The economics differ — a self-hosted model has fixed cost and unlimited usage, while a hosted model has zero fixed cost but per-token pricing — but the architectural pattern is the same.

For most orgs, hosted wins on day one. The fixed cost of GPU capacity is significant, and unless you're burning tens of millions of tokens a month, the operational overhead isn't worth it. Past a certain scale, hybrid is the right answer: hosted for bursty workloads, self-hosted for the steady baseline. This is the same curve that played out with Elasticsearch and OpenSearch — hosted first, self-hosted as you cross the unit-economics threshold.

## Patterns in production: what to delegate, what to keep

Once you've built the routing layer, the question becomes: what rules should it actually enforce? Here are the patterns that have proven out in real usage.

### File reads above a size threshold

The simplest rule: any `Read` call on a file larger than, say, 400 lines gets routed to the worker model with the original prompt attached. The worker reads the file, returns a structured summary. The agent gets what it actually needed (the answer) without having to load the whole file into context.

Threshold tuning matters. Too low and you'll route trivial reads through a network call. Too high and you'll miss the savings on medium files. A good starting point is to look at your session traces: identify the file reads where the agent only referenced a small portion of what it loaded, and set the threshold just below that. In a typical codebase, 400–800 lines catches the vast majority of waste.

### Test generation from existing patterns

This is the highest-savings single rule you can add. When the agent is asked to write tests for an existing module, the output is almost entirely determined by the existing test files in the same directory. A worker model that ingests the spec and a few reference test files will produce output that's indistinguishable from the frontier model's output — but at roughly 5% of the cost.

The key prompt engineering insight here is to forbid markdown fences in the output. Without that instruction, the worker will wrap its code in ```python``` blocks, which the calling agent then has to parse, strip, and re-format. That parsing isn't free. By returning raw code only, you eliminate a whole category of post-processing tokens.

### Documentation and comment updates

Pure transformation work. A worker model with the diff in front of it can update docstrings, fix outdated comments, and reformat READMEs without ever needing the frontier model's capabilities. This is also the safest category to delegate — documentation errors are non-critical, so even a small accuracy drop is acceptable.

### Stylistic reformatting

"Mechanical refactor to match prettier config." "Convert this file to use the new import style." These are exactly the tasks that give frontier models the most trouble anyway, because they require precise, deterministic output. Worker models with temperature set to 0.1 produce more reliable mechanical output than frontier models at temperature 0.7.

### What to keep on the frontier model

Be conservative about what you delegate. The frontier model should still own:

- **Architectural decisions**: "Should this be a saga or a two-phase commit?" "Where does the cache live?" These genuinely need the best model you have.
- **Novel bug investigation**: Tracking down a bug that hasn't been seen before, especially across multiple systems. Pattern matching from training data is exactly what frontier models excel at.
- **Anything where the cost of being wrong is high**: Production schema migrations, security-sensitive code, anything that touches auth or billing. Don't optimize the cost of code that will cost you ten times more if it breaks.

The general principle: delegate the work where the answer is mostly determined by context already in the codebase. Keep the work where the answer requires synthesis across systems or judgment under ambiguity.

## Cost modeling: what you actually save

Let's put real numbers on this. Assume a team of 50 engineers, each averaging 2 hours per day of agent-assisted coding, with an average of 80,000 tokens (input + output combined) consumed per engineer per session, weighted by task. At Claude Opus 4 pricing of roughly $15 per million input tokens and $75 per million output tokens, and assuming an 80/20 input/output split, that's about $7.20 per engineer per session on the frontier model alone. Across the team, that's around $18,000 per month in token spend.

Now route the four categories above — bulk reads, test generation, doc updates, and style reformatting — through Gemini 2.5 Flash at roughly $0.30 per million input and $1.20 per million output. If those categories are 75% of total token volume (a conservative estimate), then:

- Frontier model volume drops by 75%: new spend is $4,500 per month
- Worker model volume is 75% of original at ~6% of the per-token cost: new spend is around $810 per month
- Total: roughly $5,300 per month, versus $18,000 before — a ~70% reduction

If your actual mix skews more heavily toward I/O (which is common — most sessions are dominated by reads), the savings climb past 80%. Some teams report numbers in the 85–95% range, especially in codebases with lots of large generated files or vendored dependencies.

These numbers also don't capture the secondary benefit: faster sessions. Frontier model latency is dominated by output generation, and routing high-volume-but-low-value output to a faster model cuts total session wall-clock time meaningfully. Engineers report 20–40% faster iteration loops, which compounds the savings.

## Generalizing the architecture: this isn't just about coding

The most interesting thing about this pattern is how general it is. Anywhere you have an expensive system that handles mixed workloads, you can almost always find a tiered architecture that does better.

**Search infrastructure.** Google doesn't send every query to its full ranking stack. Common queries are served from a precomputed cache. Long-tail queries get the heavy pipeline. The architecture is the same: cheap tier for known patterns, expensive tier for novel input.

**Database systems.** HTAP architectures route analytical queries to columnar stores while OLTP traffic stays on row-based engines. The classification is similar: predictable, repeatable queries on one side; exploratory, ad-hoc queries on the other.

**CDNs.** Static content served from edge caches close to the user, dynamic content served from origin. The savings come from exactly the same insight: not every request needs the full power of your best infrastructure.

**Compilers.** LLVM's optimization pipeline is famously tiered: cheap passes first, expensive ones only when cheaper passes leave measurable gains. No serious compiler runs the full -O3 pipeline on every basic block.

What all of these have in common is a classification step at the boundary. Some classifier — by file size, by query type, by cache key, by optimization opportunity — decides which tier handles the request. The classifier doesn't need to be perfect. It just needs to be right often enough that the expensive tier sees a manageable workload.

Your delegation layer is exactly that classifier. It doesn't need to understand whether the agent's question is "easy" or "hard" in any deep sense. It just needs to recognize the patterns that are known to be high-volume and low-value: big reads, boilerplate writes, mechanical transforms. Everything else falls through to the frontier model, which is exactly where it should be.

This is also why the routing layer shouldn't be too clever. A rules-based system beats a learned router for this use case, because the rules are inspectable, debuggable, and easy to evolve as you watch traffic. A learned router adds opacity without meaningfully improving accuracy. The cost of misclassification is low — the frontier model can still handle delegated work if it has to — so the marginal value of a perfect classifier is small.

## Key Takeaways

- **Token spend in AI coding is dominated by I/O, not reasoning.** Roughly 70–85% of tokens in a typical session are spent on file reads, boilerplate writes, and mechanical transforms that don't require a frontier model.
- **A delegation layer with hooks can route that work to a cheap model** while keeping the frontier model for the design decisions and novel investigations that actually need it.
- **The architecture mirrors well-established patterns** from CDNs, tiered databases, search infrastructure, and compiler pipelines — cheap tier for predictable work, expensive tier for novel work.
- **Real savings land in the 70–90% range**, with secondary benefits in session latency and engineer iteration speed.
- **Conservative delegation is the right starting posture.** Delegate high-volume, low-judgment work; keep architectural decisions, novel bugs, and security-sensitive code on the frontier model until you've validated your routing layer.
- **The pattern generalizes** beyond coding assistants. Anywhere expensive infrastructure handles mixed workloads, a tiered router will almost always beat a single-tier system.

## Further Reading

- [The Pragmatic Engineer — How engineering teams are using AI coding agents in production](https://newsletter.pragmaticengineer.com/p/ai-coding-agents-in-production)
- [Anthropic — Claude Code hooks documentation](https://docs.anthropic.com/en/docs/claude-code/hooks)
- [Google Cloud — Gemini 2.5 Flash model card and pricing](https://cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash)
- [AWS Architecture Blog — The patterns of tiered storage and why it always wins](https://aws.amazon.com/blogs/architecture/)
- [LangChain — Building production agent systems with tool routing](https://blog.langchain.com/building-production-agent-systems/)
- [Varnish Cache documentation — request routing and classification](https://varnish-cache.org/docs/)