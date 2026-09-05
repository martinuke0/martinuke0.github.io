---
title: "Context Engineering: The Discipline Behind Reliable LLM Applications"
date: "2026-09-05T18:27:25.693"
draft: false
tags: ["context-engineering", "llm", "prompt-design", "rag", "ai-systems"]
description: "Context engineering is the practice of assembling the right information, tools, and instructions before an LLM call. Here's how to do it in production."
summary: "Prompt engineering is shrinking inside the model. Context engineering — choosing what goes into the window — is now the lever for quality, cost, and reliability."
showToc: true
TocOpen: false
cover:
  image: "/images/covers/2026-09-05-context-engineering-the-discipline-behind-reliable-llm-applications.svg"
  alt: "An abstract diagram of tokens flowing into a model window."
  caption: ""
  relative: false
---

> **TL;DR** — Context engineering is the practice of curating exactly what enters an LLM's context window — system prompts, retrieved documents, tool outputs, prior turns — to maximize reliability and minimize cost. It's replacing "prompt engineering" as the real discipline behind production AI systems, and it's where teams should be investing their iteration cycles in 2026.

For a few years, "prompt engineering" was the term. People argued over which magic words unlocked a model's best behavior, traded clever suffixes on Twitter, and shipped thin wrappers around GPT. That era is fading. The frontier models keep getting better at following instructions, so the marginal return on crafting one has shrunk. What has *grown* — and what now determines whether your AI feature actually works — is the quality, structure, and discipline of the **context** you put into the model.

This is what people in the field increasingly call **context engineering**.

## What Is Context Engineering?

Context engineering is the deliberate design of everything that enters an LLM's context window before the model is called: the system prompt, the user message, the retrieved documents, tool outputs, prior conversation turns, structured instructions, and any other supporting material. Its goal is to maximize the probability that the model produces a correct, safe, and useful output — at the lowest possible token cost.

The phrase has been picking up steam. [Andrej Karpathy popularized it in a June 2025 post](https://x.com/karpathy/status/1937902205765847621), framing it as the next layer above prompt engineering: "the delicate art and science of filling the context window with just the right information for the next step." [Shopify's engineering blog](https://shopify.engineering/context-engineering) and several YC-backed startups now use the term as their primary lens for LLM product work. Even the [LangChain documentation](https://python.langchain.com/docs/concepts/context/) has reorganized itself around context primitives rather than prompts.

Where prompt engineering asks, *"How do I phrase my request?"*, context engineering asks, *"What should the model know, in what order, and in what form, before it answers?"*

## The Anatomy of a Context Window

To engineer context well you have to understand what you're actually feeding the model. Every token in the window competes for attention with every other token. The window is roughly four kinds of content:

1. **System prompt** — the standing instructions. Persona, format, constraints, tool definitions.
2. **Retrieved context** — documents, code, schema definitions, prior messages, anything pulled from outside the immediate user turn.
3. **Tool outputs** — results from function calls, search results, database queries, API replies.
4. **User message** — the actual request, often small relative to the rest.

A naive RAG pipeline looks like `system + retrieved_chunks + user_message`. A well-engineered one looks like `system + structured_grounding + ranked_retrieval + tool_results + compressed_history + user_message + few_shot_examples`. Same model, dramatically different outcome.

[Anthropic's "Effective Context Engineering for AI Agents"](https://www.anthropic.com/news/context-engineering) makes this distinction explicit and warns that stuffing the window is a fast path to degraded behavior — the model loses the thread when too much mid-quality content is present.

## Why Context Engineering Is Now the Bottleneck

Three forces have converged to make context — not prompts — the primary lever for LLM quality.

### 1. Models are better at following instructions

GPT-4 needed coaxing. GPT-4o, Claude 3.5 Sonnet, and the latest Gemini and Llama 4 generations follow well-stated instructions reliably. The gap between a clever prompt and a plain one has narrowed. The gap between relevant context and irrelevant context hasn't.

### 2. Context windows have grown, and that is a trap

200K, 500K, even 1M-token windows feel like an invitation to "just throw everything in." They aren't. [Anthropic's own research](https://www.anthropic.com/news/context-engineering) and the [Chroma team's empirical work](https://research.trychroma.com/context-rot) both show that recall and reasoning quality degrade long before the window fills — a phenomenon sometimes called *context rot*. More tokens means more distractors, more opportunities for the model to latch onto a stale instruction or an outdated tool result.

### 3. Agents have made context a moving target

When an agent loops over tools, every tool call lands in the context. A five-step agent run can leave the model with 50K tokens of accumulated intermediate results — most of which no longer matter by step six. Engineering the *lifecycle* of context across an agentic trajectory is now a first-class problem.

## Core Principles of Context Engineering

A few principles consistently show up across production systems.

### Make every token earn its place

Treat the context window like a precious, paid resource. Token cost is real, latency is real, attention is real. Before adding anything, ask: does this token increase the probability of a correct answer? If not, cut it.

This sounds obvious. In practice, it's where most teams fail. Logs of broken RAG pipelines consistently show that the retrieved chunks include one good document and nine that the model treats as plausible-sounding noise.

### Order matters

Models attend more strongly to information at the **start and end** of the context. Place the most critical instructions and constraints at the boundaries, not buried in the middle. This is one of the few findings robust across [every major context-window study](https://research.trychroma.com/context-rot).

A common pattern: put persona and hard constraints at the top, put the user's question and the most relevant retrieved evidence right before the answer position. Treat the middle as space for supporting detail the model can draw on but doesn't need to focus on.

### Separate instructions from data

System prompts should carry *behavior* ("You are a customer support agent for Acme. Never reveal pricing not in the provided docs."). Retrieved context should carry *facts* ("Pricing tier Pro is $49/month…"). Mixing them — embedding instructions inside retrieved documents — makes both less reliable.

Structured sections with clear delimiters outperform free-form prose. Most teams converge on something like:

```text
<role>
You are a senior code reviewer. Be direct. Cite line numbers.
</role>

<rules>
- Never approve a PR with failing tests.
- Flag any change to /auth without a security review.
</rules>

<context>
{{retrieved_pull_request_diff}}
</context>

<task>
Review the diff above and produce a structured review.
</task>
```

That structure isn't aesthetic. It's a context-engineering decision: it tells the model exactly where each kind of content lives.

### Compress aggressively

The cheapest tokens are the ones you don't send. Techniques that work in production:

- **Summarize prior turns** rather than passing the full transcript. A rolling 200-token summary of the last 10 messages beats the literal last 10 messages almost every time.
- **Strip tool output noise**. If a function returned 4,000 lines of JSON and you only need three fields, project to those fields before putting it in context.
- **Pre-deduplicate retrieved chunks**. Two near-identical paragraphs read as two pieces of evidence and inflate the model's confidence in the wrong one.
- **Use small models as compressors**. A Haiku-class model can usually turn 10K tokens of tool output into 800 tokens of structured findings that the larger model can use directly.

### Use tools to keep context clean

The cleanest way to deal with context bloat in agents is to **never let it into the window in the first place**. Instead of pasting a 200-page document into context and asking the model to summarize it, give the model a `read_page` tool that returns the page it asked for. Instead of dumping a million-row table, expose a `query_db` tool that returns only the rows matching the agent's current need.

This is the "tools as context filters" pattern, and it's the architectural move behind serious agent systems like [Manus](https://manus.im/) and Anthropic's own [computer-use agent](https://www.anthropic.com/news/3-5-sonnet-and-computer-use).

## Patterns in Production

A few concrete patterns show up over and over in well-engineered systems.

### The Two-Pass RAG

The cheap, fast model retrieves and ranks. The expensive, smart model only sees the top-k and writes the answer. This separates *recall* from *reasoning* and keeps the answer-side context tight. It's the default architecture at companies like [Glean](https://www.glean.com/blog/rag-without-llms) and is documented in detail in the [RAG survey from Gao et al.](https://arxiv.org/abs/2312.10997).

### Structured Context with Schemas

Instead of "here is some JSON, do your best," define a schema for retrieved facts and have the retrieval step produce conformant records. The model then parses structure rather than language, which is more reliable and cheaper. Tools like [BAML](https://boundaryml.com/) and [Instructor](https://python.useinstructor.com/) exist almost entirely to make this pattern ergonomic.

### Episodic + Semantic Memory

A common mistake is dumping the entire chat history into the context for every turn. The fix is a memory layer: recent turns are kept verbatim, older turns are summarized, and long-term facts are extracted into a small structured store that is queried by topic. [Mem0](https://mem0.ai/research), [Letta](https://www.letta.com/), and the [LangGraph memory guide](https://langchain-ai.github.io/langgraph/concepts/memory/) all describe variations of this.

### Context Quarantine for Agents

In long agent runs, give each subtask its own "scratchpad" context that is summarized into the parent only when needed. This is the idea behind Anthropic's [per-task message queues](https://www.anthropic.com/news/context-engineering) and OpenAI's [Swarm multi-agent pattern](https://github.com/openai/swarm): agents communicate by passing distilled summaries, not raw transcripts.

### Just-In-Time Retrieval

Don't pre-load documents. Let the agent *ask* for what it needs. This is the pattern that powers systems like [Devin](https://www.cognition.ai/blog/introducing-devin) and most well-built coding agents. The model's own reasoning decides what context to load next, which is closer to how a human engineer works than to how a naive RAG pipeline works.

## A Reference Architecture

Putting it together, a well-engineered LLM application looks like this:

```text
              ┌──────────────────────────────────────┐
              │           Application Layer          │
              └──────────────────┬───────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────┐
│                  Context Assembler                      │
│  ┌────────────┐  ┌────────────┐  ┌───────────────────┐  │
│  │  Memory    │  │  Retrieval │  │  Tool Outputs     │  │
│  │  (rolling  │  │  (re-ranked│  │  (filtered,       │  │
│  │  summary + │  │  top-k,    │  │   projected to    │  │
│  │  structured│  │  deduped)  │  │   needed fields)  │  │
│  │  facts)    │  │            │  │                   │  │
│  └─────┬──────┘  └─────┬──────┘  └─────────┬─────────┘  │
│        └───────────────┼───────────────────┘            │
│                        ▼                                │
│              ┌──────────────────────┐                   │
│              │  Compressor (small   │                   │
│              │  model) — optional   │                   │
│              └──────────┬───────────┘                   │
│                         ▼                               │
│              ┌──────────────────────┐                   │
│              │  Prompt Template      │                   │
│              │  (role → rules →      │                   │
│              │   context → task)     │                   │
│              └──────────┬───────────┘                   │
└─────────────────────────┼───────────────────────────────┘
                          ▼
                   ┌───────────────┐
                   │   Frontier    │
                   │     LLM       │
                   └───────────────┘
```

The assembler is the heart of context engineering. Everything that touches it — memory eviction, retrieval ranking, tool-output filtering, schema enforcement — is part of the discipline.

## Common Mistakes

A short list of failures worth recognizing early:

- **Stuffing the window.** "We have a 200K context window, let's just include the whole codebase." No. The model will lose the thread. Use a tool.
- **Mixing instructions with retrieved content.** The model can't tell which is which.
- **No compression between agent steps.** Trajectory cost balloons, latency creeps, and quality drops as the window fills with stale tool output.
- **Single-pass retrieval with no rerank.** Embedding similarity is a noisy first pass; cross-encoder reranking almost always pays for itself.
- **Ignoring ordering.** Burying the question under 50K tokens of retrieved evidence is a recipe for the model answering a different question than the one asked.
- **Logging the entire context for debugging.** Great for your first three days, ruinous for cost and privacy. Sample, summarize, or hash.

## How to Start Practicing

If you're moving from "we wrote a prompt" to "we engineer context," a practical ramp is:

1. **Instrument the context.** Log the size of each section of every request. You'll be horrified at what you find.
2. **Rank retrieval.** Add a cross-encoder reranker on top of your embeddings. Most teams see a 10–20% quality lift with no model change.
3. **Compress history.** Replace raw chat history with a rolling summary in any conversation past 10 turns.
4. **Filter tool output.** Project function results to the fields the model actually needs before injecting them.
5. **Move from prompts to templates.** Treat context construction as code with tests, not as prose on a Notion page.

## Key Takeaways

- Context engineering is the practice of curating exactly what enters an LLM's window — system prompt, retrieved documents, tool results, memory — to maximize quality at minimal cost.
- Bigger windows are not better. Recall and reasoning degrade long before the window fills; more context means more distractors.
- Order, structure, and separation between instructions and data reliably improve outcomes.
- Compression, summarization, and tool-mediated retrieval are the practical techniques that keep context cheap and focused.
- The frontier of serious agent work is no longer "what should I prompt" but "what should my agent *know* at this moment."

## Further Reading

- [Effective Context Engineering for AI Agents — Anthropic](https://www.anthropic.com/news/context-engineering)
- [The New Skill in AI is Not Prompting, It's Context Engineering — Shopify Engineering](https://shopify.engineering/context-engineering)
- [Context Rot — Chroma Research](https://research.trychroma.com/context-rot)
- [Retrieval-Augmented Generation for Large Language Models — Gao et al., arXiv](https://arxiv.org/abs/2312.10997)
- [LangGraph Memory Concepts — LangChain](https://langchain-ai.github.io/langgraph/concepts/memory/)
- [Andrej Karpathy on Context Engineering (X)](https://x.com/karpathy/status/1937902205765847621)