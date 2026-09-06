---
title: "Context Graphs for Coding Agents: Why Tool-Call Counts Are the New Token Bill"
date: "2026-09-06T11:09:14.544"
draft: false
tags: ["ai-agents", "llm", "developer-tools", "code-search", "context-engineering"]
description: "Why coding agents burn tokens on retrieval, and how precomputed context graphs can cut tool calls by 46% and tokens by 42% in production benchmarks."
summary: "Coding agents spend most of their budget on file and symbol discovery, not on actual reasoning. Here is how precomputed context graphs change that, and why it matters for every team shipping agentic dev tools."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-06-context-graphs-for-coding-agents-why-tool-call-counts-are-the-new-token-bill.svg"
  alt: "Stylized graph diagram showing code symbols as nodes and dependencies as edges."
  caption: ""
  relative: false
---

> **TL;DR** — Modern coding agents spend the majority of their token budget on retrieval: grepping, listing files, and re-reading modules they've already seen. Precomputed context graphs shift that work out of the agent loop, cutting tool calls by 46%, tokens by 42%, and wall-clock time by 60% in public benchmarks — without hurting, and often improving, correctness.

## The hidden cost inside every agent run

If you have watched a coding agent work — Claude Code, Cursor, Codex, Gemini CLI — you have probably noticed something strange. The model is supposed to be writing code, yet a large fraction of its turns are spent reading the same files twice, listing directories it has already listed, and grepping for symbols it has already resolved. On a recent refactor across a TypeScript service, I watched an agent burn through roughly 60% of its tool-call budget before it wrote a single line of new code.

This is not a model problem. It is a retrieval problem.

LLMs do not have a persistent mental model of your repository. Every turn begins with whatever is in the context window and whatever tools it can call. To answer even a small question like "where is authentication handled?", the agent typically issues a chain like:

1. `ls src/`
2. `grep -r "auth" --include="*.ts"`
3. `read_file src/middleware/auth.ts`
4. `grep "verify" src/middleware/auth.ts`
5. `read_file src/services/users.ts` (because auth.ts imported it)

Each of those calls costs input tokens, output tokens, round-trip latency, and — for paid APIs — real money. Multiply by the thousands of turns a non-trivial PR requires and the retrieval tax becomes the dominant line item on your agent bill.

A new class of tools is attacking this problem head-on by replacing ad-hoc grep with a precomputed, queryable map of the codebase. The most visible open example is [Graft](https://github.com/trailhq/Graft), which frames the work as a "context graph." The framing is useful even if you never install it, because the underlying ideas apply to any team building or buying an agentic dev tool.

## What a context graph actually is

A context graph is a directed graph where:

- **Nodes** represent coarse code units — files, modules, classes, top-level functions, exported symbols. Not lines. Not tokens.
- **Edges** represent typed relationships — imports, calls, inheritance, type references, tests, ownership. Edges have labels, not just presence.
- **Metadata** lives on each node: a summary, an embedding, the last-changed timestamp, the owning team, a path reference.

When the agent asks "what depends on `verifySession`?", it does not grep. It issues one structured query against the graph and gets back a small, ranked set of nodes with their summaries already inlined. The model reasons over summaries; it only opens the underlying source when it actually needs to edit it.

This is the same architectural shift that moved web search from "parse every page on the fly" to "query a precomputed index." Elasticsearch did it for documents. A context graph does it for code.

> The structural argument: retrieval is expensive, repetition is wasteful, and structure is cheaper to store than to rediscover. Graphs are the natural data structure when "what is related to X" is the most common question.

## Patterns in production: the retrieval loop, compressed

Here is what changes in the agent loop when a context graph is in front of the model. Compare the two sequences below for the same task — *"find every place that constructs a `PaymentIntent` so I can add a retry counter."*

### Without a context graph (typical agent behavior)

```text
turn 1  model → list_dir src/
turn 2  model → grep "PaymentIntent" --include="*.ts"
turn 3  model → read_file src/billing/stripe.ts
turn 4  model → grep "new PaymentIntent" src/billing/stripe.ts
turn 5  model → read_file src/webhooks/stripe.ts
turn 6  model → grep "PaymentIntent" src/webhooks/stripe.ts
turn 7  model → read_file src/webhooks/stripe.ts
turn 8  model → grep "PaymentIntent" test/
turn 9  model → list_dir test/billing/
turn 10 model → read_file test/billing/stripe.test.ts
```

Ten tool calls. Five files re-read. Roughly 80k tokens of source code pulled into context, most of it duplicate.

### With a context graph

```text
turn 1  model → graph_query { symbol: "PaymentIntent", kind: "construction" }
turn 2  model → read_file src/billing/stripe.ts   (only the construction site)
turn 3  model → read_file src/webhooks/stripe.ts  (called by construction site)
turn 4  model → graph_query { symbol: "PaymentIntent", kind: "tests" }
turn 5  model → edit src/billing/stripe.ts
```

Five tool calls. Three files read, each once. The graph already knew that `webhooks/stripe.ts` constructs a `PaymentIntent` indirectly through a factory, so it was returned in turn 1 without a grep.

This is exactly the kind of compression that open benchmarks are starting to report. [Graft's published numbers](https://github.com/trailhq/Graft) — 46% tool-call reduction, 42% token savings, 60% wall-clock speedup, with a +12 point bump in correctness on SWE-bench Verified — are not mysterious once you see the loop above. They are the predictable outcome of replacing `grep + read` with `graph_query + read`.

## Why correctness goes up, not down

The instinct is to worry that this kind of optimization trades quality for speed. The benchmarks say the opposite. Two things are going on.

First, **summaries disambiguate**. When the agent gets back a node labeled `stripe.ts — webhook handler, parses Stripe events, constructs PaymentIntent on invoice.finalized`, it can decide whether this is the relevant site in a fraction of the time it would spend reading the file. Summaries also reduce the failure mode where the agent opens a similarly-named file (`stripe-checkout.ts`, `stripe-client.ts`) and reasons about the wrong one.

Second, **edges prevent lost calls**. A grep finds string occurrences. A graph knows about typed call edges, inheritance, and import resolution. If `verifySession` is called through three layers of middleware, the graph returns all three. A grep misses the indirection unless the agent happens to grep for the exact intermediate symbol. On large refactors — rename a function, change a return type — edge-aware retrieval is what keeps the agent from producing incomplete diffs.

The +12 points on [SWE-bench Verified](https://www.swebench.com/) is consistent with this. SWE-bench rewards agents that find every relevant site. Missing one site means a failing test, and that is exactly what edge-aware retrieval reduces.

## How the graph gets built

If you are going to ship something like this, you need to decide what to extract and from what. In practice, a serious implementation has four stages.

### 1. Parse, don't regex

Tree-sitter (or a language-native parser like TypeScript Compiler API, `go/ast`, `rustc --emit=metadata`) gives you a real AST with scope, imports, and symbol resolution. Regex-based extraction works for trivial cases and falls apart on generics, decorators, and re-exports. Any production graph builder should be parser-based per language, with a small number of well-supported languages covering most of the engineering surface. [Tree-sitter's language matrix](https://tree-sitter.github.io/) is a useful starting point.

### 2. Resolve, don't guess

Parsing tells you what is in a file. Resolution tells you what `verifySession` actually refers to when it is called from another module. This step is where you build the typed edges. It is also where monorepos hurt — cross-package references, workspace aliases, path mappings, and build-tool-specific resolution rules all need to be honored. The naive implementation that resolves edges file-by-file will silently miss 20–40% of call edges in a TypeScript monorepo.

### 3. Summarize per node

You need a short description of each node. There are three viable strategies:

- **Heuristic**: first doc comment, first N lines, exported signature. Cheap, deterministic, often good enough.
- **Embedding-based**: embed the source and cluster. Better for search, worse for human reading.
- **LLM-generated**: one short paragraph per node, batched. Most expensive, but produces summaries a model can reason over directly. This is what production systems like Graft appear to do, and it is the difference between a graph and an index.

### 4. Keep it fresh

Graphs rot. A merge to `main` invalidates edges across modules. A reasonable cadence is to rebuild on every PR merge and incrementally update on commit. Teams running this in production typically compute the graph once per mainline commit and reuse it across the dozens of agent runs that PR generates. The build is the expensive part; the queries are cheap.

## Architecture: where the graph sits

There are three reasonable architectures, each with different tradeoffs.

### Local-first, file-backed

The graph lives in the repo as a `.ggraph/` folder, built by a CLI, queried by the agent over MCP. This is what most open tools converge on. Pro: zero infra, works offline, diffs are reviewable in PRs. Con: rebuild cost is paid by the developer, and very large repos strain a laptop.

### Shared, served

A central service builds the graph for every repo and exposes it over HTTP/gRPC. CI pushes commits, agents pull deltas. Pro: consistent across the org, fast queries, can be tuned centrally. Con: you now operate a service, and you have to think about caching, freshness SLAs, and per-team graph partitioning.

### Hybrid

Build locally for dev, serve from a shared cache for CI and review bots. This is the shape production is settling on, because the cost of building is amortized across many consumers (IDE agent, PR reviewer, CI fixers, doc generators) and the freshness story is easier when there is one canonical builder.

The architectural choice is mostly about who pays for compute. A local build that takes 90 seconds on a 1M-line repo is fine for a single developer. It is not fine if 200 developers and 50 CI jobs are running it every hour.

## Tooling integration: MCP is the lingua franca

The practical reason this category of tools is taking off now, not two years ago, is [Model Context Protocol](https://modelcontextprotocol.io/). MCP gives every agent — Claude Code, Cursor, Codex CLI, Gemini CLI, and a growing list of IDE plugins — a uniform way to call external tools. A graph query becomes one MCP tool, declared once, usable everywhere.

```json
{
  "name": "graph_query",
  "description": "Query the repository context graph for symbols, edges, and summaries.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "symbol": { "type": "string" },
      "kind": { "type": "string", "enum": ["definition", "callers", "callees", "tests", "construction", "imports"] },
      "limit": { "type": "number", "default": 10 }
    },
    "required": ["symbol"]
  }
}
```

That single declaration gives every MCP-compatible agent structured, typed access to your codebase. This is a much better integration story than the bespoke per-tool CLI scripts that defined the previous generation of dev tools, and it is why "graph + MCP" has become the de facto pattern.

For deeper integrations — automatic blast-radius review on PRs, suggestions grounded in call edges, refactor planning — the same graph backs a GitHub App that comments on the PR directly. This is the second product surface that context graphs unlock, and arguably the more important one long-term, because most code is reviewed more than it is written.

## What this changes for teams building agents

If you are building an agentic dev tool, the takeaway is uncomfortable: **retrieval is your moat, not your model**. Frontier models are roughly interchangeable on coding tasks at this point, and the public benchmarks are converging. The differentiator is what context the model sees before it writes a line. A tool that gives the model the right 2,000 tokens will outperform a tool that gives it 50,000 tokens of grep results, every time.

Three concrete implications:

1. **Budget retrieval separately.** Track tool-call count, redundant reads, and time-to-first-edit as first-class metrics. If tool-call reduction is not on your dashboard, you are flying blind.
2. **Invest in graph quality before model fine-tuning.** A +12 point correctness bump from better retrieval is almost free. The same bump from fine-tuning is six figures of compute.
3. **Treat the graph as a product.** Summarization quality, edge resolution accuracy, freshness SLAs, and monorepo support are product surfaces, not engineering afterthoughts.

## What this changes for teams using agents

If you are buying an agentic tool rather than building one, the procurement question is no longer "which model" but "which retrieval." Ask vendors:

- Do you precompute a graph, or do you grep at inference time?
- What is your tool-call count per typical task?
- What is your freshness model — per-commit, per-PR, per-day?
- How do you handle monorepos with cross-package type resolution?

These are the questions that predict cost and quality in 2026. The model in the loop matters less than the retrieval in front of it.

> If your agent is reading the same file twice, the model is not the bottleneck — your retrieval layer is.

## Key Takeaways

- Coding agents spend the majority of their tool-call budget on retrieval, not on writing code. This is the dominant cost driver for both latency and tokens.
- A precomputed context graph — typed nodes for code units, typed edges for relationships, summaries on every node — replaces ad-hoc grep with structured queries and cuts the retrieval loop dramatically.
- Public benchmarks show 46% fewer tool calls, 42% fewer tokens, 60% less wall-clock time, and improved correctness when agents are backed by a graph instead of raw filesystem access.
- The architecture that works in production is parser-based extraction, resolved edges, LLM-generated summaries, and per-commit freshness, ideally served over MCP for broad agent compatibility.
- For builders: retrieval quality is now the moat. For buyers: retrieval quality is now the procurement question.

## Further Reading

- [SWE-bench Verified — the canonical coding-agent benchmark](https://www.swebench.com/)
- [Model Context Protocol specification](https://modelcontextprotocol.io/)
- [Tree-sitter — incremental parsing for code understanding](https://tree-sitter.github.io/tree-sitter/)
- [The Pragmatic Engineer — How AI coding agents are actually used in 2026](https://newsletter.pragmaticengineer.com/)
- [LangChain — Context Engineering for Agents](https://blog.langchain.com/context-engineering-for-agents/)